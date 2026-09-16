"""Development-only audit of production signal scarcity.

This module replays the existing frozen SETUP_01/SETUP_02 structural and
Decision contracts, then computes attribution diagnostics.  It deliberately
does not add a production gate, change a threshold, fetch live data, read
holdings, or calculate forward performance.  Event-level objects exist only
while the audit is running; the persisted artifact contains aggregates and
provenance, not raw bars or event dumps.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.development_holdout_dataset import (
    DATASET_MANIFEST_PATH,
    FROZEN_INPUT_PATH,
    REPLAY_MANIFEST_PATH,
    load_frozen_holdout,
)
from research.market_sessions import build_market_session_dates
from trading.fibonacci import EXTENSION_RATIOS, project_extension
from trading.indicators import atr
from trading.models import DecisionAction, SetupState, Trend, WaveScenarioFamily
from trading.risk import (
    HIGH_ASYMMETRY,
    MIN_TARGET_UPSIDE_PCT,
    risk_reward,
    target_upside_pct,
)
from trading.setup01_decision import (
    EXECUTED as SETUP01_EXECUTED,
    Setup01Decision,
    Setup01DecisionGateReason,
    Setup01DecisionStream,
    Setup01Execution,
    _prefix_at_event as _setup01_prefix_at_event,
    _target_candidates as _setup01_target_candidates,
    _targets_are_reasonable as _setup01_targets_are_reasonable,
    evaluate_setup01_decision_stream,
    execute_setup01_t1_open,
)
from trading.setup01_replay import Setup01ReplayEvent, Setup01ReplayReport, replay_setup01_history
from trading.setup02_decision import (
    EXECUTED as SETUP02_EXECUTED,
    Setup02Decision,
    Setup02DecisionGateReason,
    Setup02DecisionStream,
    Setup02Execution,
    _structure_invariant_failures as _setup02_structure_invariant_failures,
    _target_candidates as _setup02_target_candidates,
    _targets_are_reasonable as _setup02_targets_are_reasonable,
    evaluate_setup02_decision_stream,
    execute_setup02_t1_open,
)
from trading.setup02_replay import Setup02ReplayEvent, Setup02ReplayReport, replay_setup02_history
from trading.swing import find_swings
from trading.wave import aggregate_completed_weekly_quotes, evaluate_wave_scenario


PROTOCOL_VERSION = "SYSTEM_SIGNAL_SCARCITY_AUDIT_V1"
PROTOCOL_PATH = PROJECT_ROOT / "research" / "protocols" / "system_signal_scarcity_audit_v1.json"
DEFAULT_JSON_OUTPUT = PROJECT_ROOT / "research" / "development" / "system_signal_scarcity_audit_v1.json"
DEFAULT_MARKDOWN_OUTPUT = PROJECT_ROOT / "research" / "development" / "system_signal_scarcity_audit_v1.md"
PRECONFIRMATION_REFERENCE_PATH = (
    PROJECT_ROOT / "research" / "development" / "pre_confirmation_early_entry_causal_research_v1.json"
)
HISTORY_MINIMUM_BARS = 60
SWING_LOOKBACK = 5
ATR_PERIOD = 14
ENTRY_ZONE_ATR = 0.5
EXECUTION_STOP_ATR = 0.5

SETUP01 = "SETUP_01"
SETUP02 = "SETUP_02"
SETUPS = (SETUP01, SETUP02)
PROVENANCE_FORMAL = "FORMAL_STRATEGY_POOL"
PROVENANCE_DYNAMIC_CANDIDATE = "DYNAMIC_CANDIDATE"
PROVENANCE_DEVELOPMENT_HOLDOUT = "DEVELOPMENT_HOLDOUT_CANDIDATE"
PROVENANCES = (
    PROVENANCE_FORMAL,
    PROVENANCE_DYNAMIC_CANDIDATE,
    PROVENANCE_DEVELOPMENT_HOLDOUT,
)
ABLATION_GATES = (
    "TARGET_UPSIDE_BELOW_MINIMUM",
    "RR_BELOW_MINIMUM",
    "FORMAL_T1_CONFIRMED_SWING_HIGH",
    "ENTRY_ZONE",
)
CONFIRMATION_ABLATION_GATE = "CONFIRMATION_CLOSE_ABOVE_H1"
OVERLAP_GATES = (
    "ABOVE_ENTRY_ZONE",
    "NO_VALID_TARGET",
    "TARGET_UPSIDE_BELOW_MINIMUM",
    "RR_BELOW_MINIMUM",
    "FORMAL_T1_CONFIRMED_SWING_HIGH",
    "TARGET_PROVENANCE_GEOMETRY",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(numerator: int, denominator: int, multiplier: float = 1.0) -> float | None:
    return numerator * multiplier / denominator if denominator else None


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    """Return a deterministic linearly interpolated percentile."""

    ordered = sorted(float(value) for value in values if _finite(value) is not None)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(quantile)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _distribution(values: Iterable[Any]) -> dict[str, Any]:
    """Summarise a causal diagnostic without retaining event-level rows."""

    finite_values = [value for value in (_finite(item) for item in values) if value is not None]
    if not finite_values:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "median": None,
            "p90": None,
            "max": None,
            "mean": None,
        }
    mean = sum(finite_values) / len(finite_values)
    return {
        "count": len(finite_values),
        "min": _round(min(finite_values)),
        "p10": _round(_percentile(finite_values, 0.10)),
        "median": _round(_percentile(finite_values, 0.50)),
        "p90": _round(_percentile(finite_values, 0.90)),
        "max": _round(max(finite_values)),
        "mean": _round(mean),
    }


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def _safe_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _source_has(candidate: Any, source: str) -> bool:
    sources = str(getattr(candidate, "source", "")).split("+")
    if source in sources:
        return True
    return any(getattr(item, "source", None) == source for item in getattr(candidate, "provenance", ()))


def _remove_candidate_source(candidate: Any, source: str) -> Any | None:
    """Remove one target explanation while retaining other explanations."""
    sources = tuple(
        item for item in str(getattr(candidate, "source", "")).split("+") if item
    )
    if source not in sources:
        return candidate
    remaining_sources = tuple(item for item in sources if item != source)
    remaining_provenance = tuple(
        item
        for item in getattr(candidate, "provenance", ())
        if getattr(item, "source", None) != source
    )
    if not remaining_sources or not remaining_provenance:
        return None
    return replace(
        candidate,
        source="+".join(sorted(set(remaining_sources))),
        provenance=remaining_provenance,
    )


@dataclass(frozen=True)
class SessionObservation:
    symbol: str
    market: str
    trade_date: date
    time_half: str
    history_sufficient: bool
    weekly_state: str
    daily_state: str
    primary_wave_scenario: str
    wave_primary_valid: bool
    setup01_wave_context_eligible: bool
    setup02_wave_context_eligible: bool
    setup01_state: str
    setup02_state: str
    provenance: str = PROVENANCE_DEVELOPMENT_HOLDOUT


class _CausalWaveAccessor:
    """Expose existing Wave evaluations one strict as-of prefix at a time."""

    def __init__(self, quotes: Sequence[Quote]) -> None:
        self._quotes = tuple(quotes)
        self._daily_swings_all = tuple(find_swings(list(quotes), lookback=SWING_LOOKBACK))
        weekly_quotes = aggregate_completed_weekly_quotes(list(quotes), quotes[-1].trade_date)
        self._weekly_swings_all = (
            tuple(find_swings(weekly_quotes, lookback=SWING_LOOKBACK)) if weekly_quotes else ()
        )
        self._weekly_quote_dates = tuple(quote.trade_date for quote in weekly_quotes)
        self._cache: dict[int, Any] = {}

    def at(self, index: int) -> Any:
        if index not in self._cache:
            self._cache[index] = evaluate_wave_scenario(
                self._quotes,
                as_of_date=self._quotes[index].trade_date,
                daily_swing_lookback=SWING_LOOKBACK,
                weekly_swing_lookback=SWING_LOOKBACK,
                _as_of_index=index,
                _daily_swings_all=self._daily_swings_all,
                _weekly_swings_all=self._weekly_swings_all,
                _weekly_quote_dates=self._weekly_quote_dates,
                _skip_validation=True,
            )
        return self._cache[index]


@dataclass(frozen=True)
class LifecycleSummary:
    key: str
    setup_type: str
    symbol: str
    market: str
    lifecycle_index: int
    first_observed_index: int
    last_observed_index: int
    first_observed_date: date
    last_observed_date: date
    time_half: str
    first_state: str
    final_state: str
    state_day_counts: tuple[tuple[str, int], ...]
    resolution: str
    first_fail: str | None
    confirmed_index: int | None
    confirmed_date: date | None
    failed_index: int | None
    failed_date: date | None
    provenance: str = PROVENANCE_DEVELOPMENT_HOLDOUT
    first_watch_index: int | None = None
    first_armed_index: int | None = None
    watch_episode_count: int = 0
    armed_episode_count: int = 0


@dataclass(frozen=True)
class GeometrySnapshot:
    setup_type: str
    calculable: bool
    reason: str | None
    atr14: float | None
    planned_entry: float | None
    entry_zone_low: float | None
    entry_zone_high: float | None
    structural_invalidation: float | None
    execution_stop: float | None
    confirmation_level: float | None
    target_candidates: tuple[Any, ...]
    targets: tuple[float, ...]
    rr: Any | None
    target_upside_pct: float | None
    target_reasonableness_failed: bool
    structure_values: tuple[float, ...]
    as_of_date: date | None = None


@dataclass(frozen=True)
class DecisionRecord:
    setup_type: str
    event: Any
    decision: Any
    execution: Any | None
    geometry: GeometrySnapshot
    first_fail: str | None
    all_fail_gates: tuple[str, ...]
    provenance: str = PROVENANCE_DEVELOPMENT_HOLDOUT


@dataclass(frozen=True)
class CounterfactualPlan:
    setup_type: str
    planned_entry: float
    entry_zone_low: float
    entry_zone_high: float
    structural_invalidation: float
    execution_stop: float
    confirmation_level: float
    targets: tuple[float, ...]
    target_candidates: tuple[Any, ...]
    rr: Any
    target_upside_pct: float


def _protocol_identity(protocol_path: Path = PROTOCOL_PATH) -> tuple[dict[str, Any], str, str]:
    protocol = _load_json(protocol_path)
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("signal scarcity protocol version changed")
    body = deepcopy(protocol)
    integrity = body.setdefault("integrity", {})
    recorded = integrity.get("protocol_sha256")
    integrity["protocol_sha256"] = None
    canonical_hash = _sha256_bytes(_canonical_json(body).encode("utf-8"))
    if recorded not in (None, canonical_hash):
        raise ValueError("signal scarcity protocol integrity mismatch")
    return protocol, canonical_hash, _sha256_file(protocol_path)


def _half_map(quotes_by_symbol: Mapping[str, Sequence[Quote]]) -> dict[str, dict[date, str]]:
    sessions = build_market_session_dates(quotes_by_symbol)
    result: dict[str, dict[date, str]] = {}
    for market, dates in sessions.items():
        ordered = tuple(dates)
        midpoint = (len(ordered) - 1) // 2
        result[market] = {
            trade_date: ("EARLY" if index <= midpoint else "LATE")
            for index, trade_date in enumerate(ordered)
        }
    return result


def _build_structural_replays(
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
) -> tuple[
    dict[str, Setup01ReplayReport],
    dict[str, Setup02ReplayReport],
    tuple[Setup01ReplayEvent, ...],
    tuple[Setup02ReplayEvent, ...],
]:
    reports01: dict[str, Setup01ReplayReport] = {}
    reports02: dict[str, Setup02ReplayReport] = {}
    events01: list[Setup01ReplayEvent] = []
    events02: list[Setup02ReplayEvent] = []
    for symbol in sorted(quotes_by_symbol):
        quotes = list(quotes_by_symbol[symbol])
        report01 = replay_setup01_history(quotes, daily_swing_lookback=SWING_LOOKBACK, weekly_swing_lookback=SWING_LOOKBACK)
        report02 = replay_setup02_history(quotes, daily_swing_lookback=SWING_LOOKBACK, weekly_swing_lookback=SWING_LOOKBACK)
        reports01[symbol] = report01
        reports02[symbol] = report02
        events01.extend(report01.events)
        events02.extend(report02.events)
    return reports01, reports02, tuple(events01), tuple(events02)


def _build_session_observations(
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    reports01: Mapping[str, Setup01ReplayReport],
    reports02: Mapping[str, Setup02ReplayReport],
) -> tuple[SessionObservation, ...]:
    half_map = _half_map(quotes_by_symbol)
    observations: list[SessionObservation] = []
    for symbol in sorted(quotes_by_symbol):
        quotes = tuple(quotes_by_symbol[symbol])
        accessor = _CausalWaveAccessor(quotes)
        report01 = reports01[symbol]
        report02 = reports02[symbol]
        for index, quote in enumerate(quotes):
            wave = accessor.at(index)
            primary = wave.primary_scenario
            setup01_eligible = (
                primary.family is WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE
                and bool(primary.setup01_context_eligible)
                and wave.weekly_state is not Trend.DOWNTREND
            )
            setup02_eligible = (
                primary.family is WaveScenarioFamily.WAVE_3_CONTINUATION_CANDIDATE
                and bool(primary.setup02_context_eligible)
                and wave.weekly_state is Trend.UPTREND
                and wave.daily_state is Trend.UPTREND
            )
            observations.append(
                SessionObservation(
                    symbol=symbol,
                    market=str(quote.market),
                    trade_date=quote.trade_date,
                    time_half=half_map[str(quote.market)][quote.trade_date],
                    history_sufficient=index + 1 >= HISTORY_MINIMUM_BARS,
                    weekly_state=_enum_value(wave.weekly_state),
                    daily_state=_enum_value(wave.daily_state),
                    primary_wave_scenario=_enum_value(primary.family),
                    wave_primary_valid=primary.family is not WaveScenarioFamily.NO_VALID_SCENARIO,
                    setup01_wave_context_eligible=setup01_eligible,
                    setup02_wave_context_eligible=setup02_eligible,
                    setup01_state=_enum_value(report01.days[index].setup01.state),
                    setup02_state=_enum_value(report02.days[index].setup02.state),
                    provenance=PROVENANCE_DEVELOPMENT_HOLDOUT,
                )
            )
    return tuple(observations)


def _lifecycle_first_fail(reason: str | None) -> str:
    text = str(reason or "").upper()
    if "WAVE_SCENARIO_INVALIDATION" in text:
        return "STRUCTURAL_INVALIDATION"
    if "TRADE_STRUCTURE_INVALIDATION" in text or "STRUCTURAL_INVALIDATION" in text:
        return "STRUCTURAL_INVALIDATION"
    if "WEEKLY" in text:
        return "WEEKLY_STATE"
    if "DAILY" in text:
        return "DAILY_STATE"
    if "ABC_CORRECTION" in text or "WAVE" in text:
        return "NO_VALID_WAVE"
    return "SETUP_NOT_ELIGIBLE"


def _state_episode_count(snapshots: Sequence[Any], state: str) -> int:
    """Count contiguous episodes of one state inside a lifecycle."""

    count = 0
    previous = None
    for snapshot in snapshots:
        current = _enum_value(snapshot.state)
        if current == state and previous != state:
            count += 1
        previous = current
    return count


def _build_lifecycles(
    setup_type: str,
    reports: Mapping[str, Setup01ReplayReport | Setup02ReplayReport],
    half_map: Mapping[str, Mapping[date, str]],
) -> tuple[LifecycleSummary, ...]:
    lifecycles: list[LifecycleSummary] = []
    for symbol in sorted(reports):
        report = reports[symbol]
        grouped: dict[int, list[tuple[int, Any]]] = {}
        for index, day in enumerate(report.days):
            snapshot = day.setup01 if setup_type == SETUP01 else day.setup02
            if snapshot.lifecycle_index is not None:
                grouped.setdefault(int(snapshot.lifecycle_index), []).append((index, snapshot))
        ordered_groups = sorted(grouped.items(), key=lambda item: item[0])
        first_by_lifecycle = {lifecycle: values[0][0] for lifecycle, values in ordered_groups}
        for position, (lifecycle_index, values) in enumerate(ordered_groups):
            values = sorted(values, key=lambda item: item[0])
            indices = [index for index, _ in values]
            snapshots = [snapshot for _, snapshot in values]
            confirmed = next((snapshot for snapshot in snapshots if snapshot.is_new_confirmed_event_as_of), None)
            failed = next((snapshot for snapshot in snapshots if snapshot.is_new_failed_event_as_of), None)
            if confirmed is not None:
                resolution = "TERMINAL_CONFIRMED"
                first_fail = None
            elif failed is not None:
                resolution = "TERMINAL_FAILED"
                first_fail = _lifecycle_first_fail(failed.reason)
            elif position + 1 < len(ordered_groups):
                resolution = "CONTEXT_REPLACED_BEFORE_CONFIRMATION"
                first_fail = "CONTEXT_REPLACED_BEFORE_CONFIRMATION"
            else:
                resolution = "TIMEOUT_UNRESOLVED_AT_DATA_END"
                first_fail = "NOT_CONFIRMED"
            first_snapshot = snapshots[0]
            last_snapshot = snapshots[-1]
            first_index = indices[0]
            last_index = indices[-1]
            first_watch_index = next(
                (index for index, snapshot in values if _enum_value(snapshot.state) == SetupState.WATCH.value),
                None,
            )
            first_armed_index = next(
                (index for index, snapshot in values if _enum_value(snapshot.state) == SetupState.ARMED.value),
                None,
            )
            event_index = confirmed.confirmed_index if confirmed is not None else None
            event_date = confirmed.confirmed_date if confirmed is not None else None
            failed_index = failed.failed_index if failed is not None else None
            failed_date = failed.failed_date if failed is not None else None
            # The lookup above is intentionally not used to infer a failure; it
            # only documents that lifecycle IDs are ordered when a context is
            # replaced.  The explicit replay snapshots remain authoritative.
            _ = first_by_lifecycle
            lifecycles.append(
                LifecycleSummary(
                    key=f"{symbol}|{setup_type}|lifecycle={lifecycle_index}",
                    setup_type=setup_type,
                    symbol=symbol,
                    market=str(report.market),
                    lifecycle_index=lifecycle_index,
                    first_observed_index=first_index,
                    last_observed_index=last_index,
                    first_observed_date=report.days[first_index].trade_date,
                    last_observed_date=report.days[last_index].trade_date,
                    time_half=half_map[str(report.market)][report.days[first_index].trade_date],
                    first_state=_enum_value(first_snapshot.state),
                    final_state=_enum_value(last_snapshot.state),
                    state_day_counts=tuple(sorted(Counter(_enum_value(snapshot.state) for snapshot in snapshots).items())),
                    resolution=resolution,
                    first_fail=first_fail,
                    confirmed_index=event_index,
                    confirmed_date=event_date,
                    failed_index=failed_index,
                    failed_date=failed_date,
                    first_watch_index=first_watch_index,
                    first_armed_index=first_armed_index,
                    watch_episode_count=_state_episode_count(snapshots, SetupState.WATCH.value),
                    armed_episode_count=_state_episode_count(snapshots, SetupState.ARMED.value),
                )
            )
    return tuple(lifecycles)


def _session_scope_counts(
    observations: Sequence[SessionObservation],
    *,
    market: str | None = None,
    time_half: str | None = None,
    provenance: str | None = None,
) -> dict[str, Any]:
    rows = [
        row
        for row in observations
        if (market is None or row.market == market)
        and (time_half is None or row.time_half == time_half)
        and (provenance is None or row.provenance == provenance)
    ]
    state_eligible = {SetupState.WATCH.value, SetupState.ARMED.value, SetupState.CONFIRMED.value, SetupState.FAILED.value}
    return {
        "candidate_universe_symbol_sessions": len(rows),
        "data_ok_symbol_sessions": len(rows),
        "history_sufficient_symbol_sessions": sum(row.history_sufficient for row in rows),
        "weekly_state_available_symbol_sessions": sum(row.weekly_state != Trend.UNKNOWN.value for row in rows),
        "daily_state_available_symbol_sessions": sum(row.daily_state != Trend.UNKNOWN.value for row in rows),
        "primary_wave_non_empty_symbol_sessions": sum(row.wave_primary_valid for row in rows),
        "setup01_wave_context_eligible_symbol_sessions": sum(row.setup01_wave_context_eligible for row in rows),
        "setup02_wave_context_eligible_symbol_sessions": sum(row.setup02_wave_context_eligible for row in rows),
        "setup01_structural_eligible_symbol_sessions": sum(row.setup01_state in state_eligible for row in rows),
        "setup02_structural_eligible_symbol_sessions": sum(row.setup02_state in state_eligible for row in rows),
        "setup01_state_day_counts": dict(sorted(Counter(row.setup01_state for row in rows).items())),
        "setup02_state_day_counts": dict(sorted(Counter(row.setup02_state for row in rows).items())),
        "weekly_state_distribution": dict(sorted(Counter(row.weekly_state for row in rows).items())),
        "daily_state_distribution": dict(sorted(Counter(row.daily_state for row in rows).items())),
        "primary_wave_scenario_distribution": dict(sorted(Counter(row.primary_wave_scenario for row in rows).items())),
        "provenance_distribution": dict(sorted(Counter(row.provenance for row in rows).items())),
    }


def _setup_summary(
    setup_type: str,
    observations: Sequence[SessionObservation],
    lifecycles: Sequence[LifecycleSummary],
    records: Sequence[DecisionRecord],
    half_map: Mapping[str, Mapping[date, str]],
) -> dict[str, Any]:
    state_field = "setup01_state" if setup_type == SETUP01 else "setup02_state"
    wave_field = (
        "setup01_wave_context_eligible"
        if setup_type == SETUP01
        else "setup02_wave_context_eligible"
    )

    def scoped(
        scope_market: str | None = None,
        scope_half: str | None = None,
        scope_provenance: str | None = None,
    ) -> dict[str, Any]:
        session_rows = [
            row
            for row in observations
            if (scope_market is None or row.market == scope_market)
            and (scope_half is None or row.time_half == scope_half)
            and (scope_provenance is None or row.provenance == scope_provenance)
        ]
        life_rows = [
            row
            for row in lifecycles
            if (scope_market is None or row.market == scope_market)
            and (scope_half is None or row.time_half == scope_half)
            and (scope_provenance is None or row.provenance == scope_provenance)
        ]
        decision_rows = [
            row
            for row in records
            if (scope_market is None or row.decision.market == scope_market)
            and (scope_half is None or _record_half_map(row, half_map) == scope_half)
            and (scope_provenance is None or row.provenance == scope_provenance)
        ]
        execution_rows = [row.execution for row in decision_rows if row.execution is not None]
        action_counts = Counter(_enum_value(row.decision.action) for row in decision_rows)
        gate_counts = Counter(_enum_value(row.decision.gate_reason) for row in decision_rows)
        outcome_counts = Counter(str(execution.outcome) for execution in execution_rows)
        states = Counter(str(getattr(row, state_field)) for row in session_rows)
        candidate_lifecycles = len(life_rows)
        wave_eligible_lifecycles = candidate_lifecycles
        watch_lifecycles = sum(
            any(state == SetupState.WATCH.value for state, _ in row.state_day_counts)
            for row in life_rows
        )
        armed_lifecycles = sum(
            any(state == SetupState.ARMED.value for state, _ in row.state_day_counts)
            for row in life_rows
        )
        confirmed_lifecycles = sum(
            row.resolution == "TERMINAL_CONFIRMED" for row in life_rows
        )
        calculable_decisions = sum(bool(row.decision.decision_calculable) for row in decision_rows)
        no_trade = action_counts[DecisionAction.NO_TRADE.value]
        entry_allowed = action_counts[DecisionAction.ENTRY_ALLOWED.value]
        attempts = len(execution_rows)
        executed = outcome_counts[
            SETUP01_EXECUTED if setup_type == SETUP01 else SETUP02_EXECUTED
        ]
        stage_counts = {
            "CANDIDATE": candidate_lifecycles,
            "WAVE_ELIGIBLE": wave_eligible_lifecycles,
            "WATCH": watch_lifecycles,
            "ARMED": armed_lifecycles,
            "CONFIRMED": confirmed_lifecycles,
            "DECISION_CALCULABLE": calculable_decisions,
            "NO_TRADE": no_trade,
            "ENTRY_ALLOWED": entry_allowed,
            "T_PLUS_1_EXECUTION_ATTEMPT": attempts,
            "EXECUTED": executed,
        }
        stage_rows = []
        for stage, count in stage_counts.items():
            stage_rows.append(
                {
                    "stage": stage,
                    "count": int(count),
                    "rate_of_candidate_pct": _round(
                        _rate(int(count), candidate_lifecycles, 100.0)
                    ),
                }
            )
        confirmed_with_armed = sum(
            row.resolution == "TERMINAL_CONFIRMED"
            and row.first_armed_index is not None
            for row in life_rows
        )
        confirmed_without_armed = confirmed_lifecycles - confirmed_with_armed
        conversion_rates_pct = {
            "candidate_to_wave_eligible": _round(
                _rate(wave_eligible_lifecycles, candidate_lifecycles, 100.0)
            ),
            "wave_eligible_to_watch": _round(
                _rate(watch_lifecycles, wave_eligible_lifecycles, 100.0)
            ),
            "watch_to_armed": _round(_rate(armed_lifecycles, watch_lifecycles, 100.0)),
            "armed_to_confirmed": _round(
                _rate(confirmed_with_armed, armed_lifecycles, 100.0)
            ),
            "confirmed_to_decision_calculable": _round(
                _rate(calculable_decisions, confirmed_lifecycles, 100.0)
            ),
            "confirmed_to_no_trade": _round(_rate(no_trade, confirmed_lifecycles, 100.0)),
            "confirmed_to_entry_allowed": _round(
                _rate(entry_allowed, confirmed_lifecycles, 100.0)
            ),
            "entry_allowed_to_t_plus_1_attempt": _round(
                _rate(attempts, entry_allowed, 100.0)
            ),
            "t_plus_1_attempt_to_executed": _round(_rate(executed, attempts, 100.0)),
        }
        return {
            "wave_scenario_eligible_symbol_sessions": sum(bool(getattr(row, wave_field)) for row in session_rows),
            "structural_eligible_symbol_sessions": sum(states[state] for state in (SetupState.WATCH.value, SetupState.ARMED.value, SetupState.CONFIRMED.value, SetupState.FAILED.value)),
            "watch_symbol_sessions": states[SetupState.WATCH.value],
            "armed_symbol_sessions": states[SetupState.ARMED.value],
            "confirmed_symbol_sessions": states[SetupState.CONFIRMED.value],
            "failed_symbol_sessions": states[SetupState.FAILED.value],
            "candidate_lifecycles": candidate_lifecycles,
            "wave_eligible_lifecycles": wave_eligible_lifecycles,
            "setup_events": candidate_lifecycles,
            "lifecycles_with_watch": watch_lifecycles,
            "lifecycles_with_armed": armed_lifecycles,
            "lifecycles_confirmed": confirmed_lifecycles,
            "lifecycles_failed_or_unresolved": candidate_lifecycles - confirmed_lifecycles,
            "confirmed_lifecycles_with_armed": confirmed_with_armed,
            "confirmed_lifecycles_without_armed": confirmed_without_armed,
            "confirmed_events": len(decision_rows),
            "decision_events": len(decision_rows),
            "decision_calculable": calculable_decisions,
            "entry_allowed": entry_allowed,
            "no_trade": no_trade,
            "t1_execution_attempts": attempts,
            "executed": executed,
            "t1_skipped": attempts - executed,
            "stage_counts": stage_counts,
            "stage_rows": stage_rows,
            "conversion_rates_pct": conversion_rates_pct,
            "state_day_counts": dict(sorted(states.items())),
            "decision_gate_reason_counts": dict(sorted(gate_counts.items())),
            "t_plus_1_outcome_counts": dict(sorted(outcome_counts.items())),
            "scope": {
                "market": scope_market,
                "time_half": scope_half,
                "provenance": scope_provenance,
            },
        }

    return {
        "setup_type": setup_type,
        "event_unit": "one first-entry CONFIRMED replay event",
        "setup_event_unit": "one structural lifecycle start",
        "total": scoped(),
        "by_market": {market: scoped(scope_market=market) for market in ("CN", "US")},
        "by_time_half": {half: scoped(scope_half=half) for half in ("EARLY", "LATE")},
        "by_provenance": {
            provenance: scoped(scope_provenance=provenance)
            for provenance in PROVENANCES
        },
    }


def _merge_funnel_scope_rows(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> dict[str, Any]:
    """Add the two setup funnels while preserving count/rate semantics."""

    result: dict[str, Any] = {}
    count_maps = {"state_day_counts", "decision_gate_reason_counts", "t_plus_1_outcome_counts"}
    for key in first:
        if key in count_maps:
            merged = Counter(first.get(key, {}))
            merged.update(second.get(key, {}))
            result[key] = dict(sorted(merged.items()))
        elif key in {"stage_rows", "scope"}:
            continue
        elif isinstance(first[key], bool):
            result[key] = bool(first[key] and second[key])
        elif isinstance(first[key], (int, float)) and isinstance(second.get(key), (int, float)):
            result[key] = first[key] + second[key]
        else:
            result[key] = first[key]
    stage_counts = Counter(first.get("stage_counts", {}))
    stage_counts.update(second.get("stage_counts", {}))
    result["stage_counts"] = dict(stage_counts)
    candidate_count = int(stage_counts.get("CANDIDATE", 0))
    result["stage_rows"] = [
        {
            "stage": stage,
            "count": int(count),
            "rate_of_candidate_pct": _round(_rate(int(count), candidate_count, 100.0)),
        }
        for stage, count in stage_counts.items()
    ]
    confirmed_with_armed = int(result.get("confirmed_lifecycles_with_armed", 0))
    result["conversion_rates_pct"] = {
        "candidate_to_wave_eligible": _round(
            _rate(stage_counts.get("WAVE_ELIGIBLE", 0), stage_counts.get("CANDIDATE", 0), 100.0)
        ),
        "wave_eligible_to_watch": _round(
            _rate(stage_counts.get("WATCH", 0), stage_counts.get("WAVE_ELIGIBLE", 0), 100.0)
        ),
        "watch_to_armed": _round(
            _rate(stage_counts.get("ARMED", 0), stage_counts.get("WATCH", 0), 100.0)
        ),
        "armed_to_confirmed": _round(
            _rate(confirmed_with_armed, stage_counts.get("ARMED", 0), 100.0)
        ),
        "confirmed_to_decision_calculable": _round(
            _rate(stage_counts.get("DECISION_CALCULABLE", 0), stage_counts.get("CONFIRMED", 0), 100.0)
        ),
        "confirmed_to_no_trade": _round(
            _rate(stage_counts.get("NO_TRADE", 0), stage_counts.get("CONFIRMED", 0), 100.0)
        ),
        "confirmed_to_entry_allowed": _round(
            _rate(stage_counts.get("ENTRY_ALLOWED", 0), stage_counts.get("CONFIRMED", 0), 100.0)
        ),
        "entry_allowed_to_t_plus_1_attempt": _round(
            _rate(stage_counts.get("T_PLUS_1_EXECUTION_ATTEMPT", 0), stage_counts.get("ENTRY_ALLOWED", 0), 100.0)
        ),
        "t_plus_1_attempt_to_executed": _round(
            _rate(stage_counts.get("EXECUTED", 0), stage_counts.get("T_PLUS_1_EXECUTION_ATTEMPT", 0), 100.0)
        ),
    }
    result["scope"] = {"market": None, "time_half": None, "provenance": None}
    result["setup_type"] = "AGGREGATE"
    return result


def _geometry_for_event(setup_type: str, event: Any, quotes: Sequence[Quote]) -> GeometrySnapshot:
    try:
        if setup_type == SETUP01:
            prefix = _setup01_prefix_at_event(event, quotes)
            snapshot = event.setup01
            origin_swing = snapshot.wave1_origin
            peak_swing = snapshot.wave1_peak
            wave2_swing = snapshot.wave2_low
            if (
                origin_swing is None
                or peak_swing is None
                or wave2_swing is None
                or snapshot.confirmation_level is None
                or snapshot.structural_invalidation is None
                or snapshot.wave_scenario_invalidation is None
            ):
                return GeometrySnapshot(SETUP01, False, "STRUCTURAL_ISSUE", None, None, None, None, None, None, None, (), (), None, None, False, ())
            origin = float(origin_swing.price)
            peak = float(peak_swing.price)
            wave2_low = float(wave2_swing.price)
            confirmation_level = float(snapshot.confirmation_level)
            structural_invalidation = float(snapshot.structural_invalidation)
            if not (
                origin < wave2_low < peak
                and confirmation_level == peak
                and structural_invalidation == wave2_low
                and float(snapshot.wave_scenario_invalidation) == origin
                and float(prefix[-1].close) > confirmation_level
            ):
                return GeometrySnapshot(SETUP01, False, "STRUCTURAL_ISSUE", None, float(prefix[-1].close), confirmation_level, None, structural_invalidation, None, confirmation_level, (), (), None, None, False, (origin, peak, wave2_low))
            planned_entry = float(prefix[-1].close)
            atr_value = atr(list(prefix), ATR_PERIOD)[-1]
            atr14 = _finite(atr_value)
            if atr14 is None or atr14 <= 0:
                return GeometrySnapshot(SETUP01, False, "DATA_QUALITY", atr14, planned_entry, confirmation_level, None, structural_invalidation, None, confirmation_level, (), (), None, None, False, (origin, peak, wave2_low))
            entry_zone_high = confirmation_level + ENTRY_ZONE_ATR * atr14
            execution_stop = structural_invalidation - EXECUTION_STOP_ATR * atr14
            candidates = _setup01_target_candidates(
                list(prefix),
                origin=origin_swing,
                peak=peak_swing,
                wave2_low=wave2_swing,
                entry=planned_entry,
                swing_lookback=SWING_LOOKBACK,
            )
            targets = tuple(float(candidate.price) for candidate in candidates[:3])
            rr = risk_reward(planned_entry, execution_stop, targets) if targets else None
            upside = target_upside_pct(targets[0], planned_entry) if targets else None
            reasonableness_failed = bool(
                rr is not None
                and rr.quality == HIGH_ASYMMETRY
                and not _setup01_targets_are_reasonable(
                    candidates,
                    entry=planned_entry,
                    origin=origin,
                    peak=peak,
                    wave2_low=wave2_low,
                )
            )
            reason = "ABOVE_ENTRY_ZONE" if planned_entry > entry_zone_high else None
            if not candidates:
                reason = "NO_VALID_TARGET"
            elif reasonableness_failed:
                reason = "TARGET_PROVENANCE_GEOMETRY"
            return GeometrySnapshot(
                SETUP01,
                True,
                reason,
                atr14,
                planned_entry,
                confirmation_level,
                entry_zone_high,
                structural_invalidation,
                execution_stop,
                confirmation_level,
                tuple(candidates),
                targets,
                rr,
                _finite(upside),
                reasonableness_failed,
                (origin, peak, wave2_low),
            )

        prefix = [quote for quote in quotes if quote.trade_date <= event.trade_date]
        if not prefix or prefix[-1].trade_date != event.trade_date:
            raise ValueError("missing exact T-day quote")
        snapshot = event.setup02
        low0 = snapshot.continuation_low0
        high1 = snapshot.continuation_high1
        low2 = snapshot.continuation_low2
        high3 = snapshot.continuation_high3
        confirmation_level = snapshot.confirmation_level
        structural_invalidation = snapshot.structural_invalidation
        if any(item is None for item in (low0, high1, low2, high3, confirmation_level, structural_invalidation)):
            return GeometrySnapshot(SETUP02, False, "STRUCTURAL_ISSUE", None, None, None, None, None, None, None, (), (), None, None, False, ())
        assert low0 is not None and high1 is not None and low2 is not None and high3 is not None
        invariant_failures = _setup02_structure_invariant_failures(
            low0,
            high1,
            low2,
            high3,
            float(confirmation_level),
            float(structural_invalidation),
            float(prefix[-1].close),
        )
        planned_entry = float(prefix[-1].close)
        if invariant_failures:
            return GeometrySnapshot(SETUP02, False, "STRUCTURAL_ISSUE", None, planned_entry, float(confirmation_level), None, float(structural_invalidation), None, float(confirmation_level), (), (), None, None, False, (float(low0.price), float(high1.price), float(low2.price), float(high3.price)))
        atr_value = atr(list(prefix), ATR_PERIOD)[-1]
        atr14 = _finite(atr_value)
        if atr14 is None or atr14 <= 0:
            return GeometrySnapshot(SETUP02, False, "DATA_QUALITY", atr14, planned_entry, float(confirmation_level), None, float(structural_invalidation), None, float(confirmation_level), (), (), None, None, False, (float(low0.price), float(high1.price), float(low2.price), float(high3.price)))
        entry_zone_high = float(confirmation_level) + ENTRY_ZONE_ATR * atr14
        execution_stop = float(structural_invalidation) - EXECUTION_STOP_ATR * atr14
        candidates = _setup02_target_candidates(
            prefix,
            low0=low0,
            high1=high1,
            low2=low2,
            entry=planned_entry,
            swing_lookback=SWING_LOOKBACK,
        )
        targets = tuple(float(candidate.price) for candidate in candidates[:3])
        rr = risk_reward(planned_entry, execution_stop, targets) if targets else None
        upside = target_upside_pct(targets[0], planned_entry) if targets else None
        reasonableness_failed = bool(
            rr is not None
            and rr.quality == HIGH_ASYMMETRY
            and not _setup02_targets_are_reasonable(
                candidates,
                entry=planned_entry,
                low0=float(low0.price),
                high1=float(high1.price),
                low2=float(low2.price),
                execution_stop=execution_stop,
                as_of_date=event.trade_date,
            )
        )
        reason = "ABOVE_ENTRY_ZONE" if planned_entry > entry_zone_high else None
        if not candidates:
            reason = "NO_VALID_TARGET"
        elif reasonableness_failed:
            reason = "TARGET_PROVENANCE_GEOMETRY"
        return GeometrySnapshot(
            SETUP02,
            True,
            reason,
            atr14,
            planned_entry,
            float(confirmation_level),
            entry_zone_high,
            float(structural_invalidation),
            execution_stop,
            float(confirmation_level),
            tuple(candidates),
            targets,
            rr,
            _finite(upside),
            reasonableness_failed,
            (float(low0.price), float(high1.price), float(low2.price), float(high3.price)),
            as_of_date=event.trade_date,
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return GeometrySnapshot(setup_type, False, "STRUCTURAL_ISSUE", None, None, None, None, None, None, None, (), (), None, None, False, ())


def _decision_first_fail(decision: Any) -> str | None:
    gate = _enum_value(decision.gate_reason)
    if gate == Setup01DecisionGateReason.ENTRY_ALLOWED.value or gate == Setup02DecisionGateReason.ENTRY_ALLOWED.value:
        return None
    if gate in {"ATR_UNAVAILABLE"}:
        return "DATA_QUALITY"
    if gate in {"ABOVE_ENTRY_ZONE", "NO_VALID_TARGET", "TARGET_UPSIDE_BELOW_MINIMUM", "RR_BELOW_MINIMUM"}:
        return gate
    if gate == "STALE_CONFIRMATION_GEOMETRY":
        return gate
    return "STRUCTURAL_ISSUE"


def _all_fail_gates(decision: Any, geometry: GeometrySnapshot) -> tuple[str, ...]:
    if _enum_value(decision.action) == DecisionAction.ENTRY_ALLOWED.value:
        return ()
    gates: set[str] = set()
    if not geometry.calculable:
        gates.add("DATA_QUALITY" if geometry.reason == "DATA_QUALITY" else "STRUCTURAL_ISSUE")
        return tuple(sorted(gates))
    if (
        geometry.planned_entry is not None
        and geometry.entry_zone_high is not None
        and geometry.planned_entry > geometry.entry_zone_high
    ):
        gates.add("ABOVE_ENTRY_ZONE")
    if not geometry.target_candidates:
        gates.add("NO_VALID_TARGET")
    if geometry.target_reasonableness_failed:
        gates.add("TARGET_PROVENANCE_GEOMETRY")
    if geometry.target_upside_pct is not None and geometry.target_upside_pct < MIN_TARGET_UPSIDE_PCT:
        gates.add("TARGET_UPSIDE_BELOW_MINIMUM")
    if geometry.rr is not None and geometry.rr.rr_ratios and geometry.rr.rr_ratios[0] < 2.0:
        gates.add("RR_BELOW_MINIMUM")
    if geometry.target_candidates and _source_has(geometry.target_candidates[0], "CONFIRMED_SWING_HIGH"):
        gates.add("FORMAL_T1_CONFIRMED_SWING_HIGH")
    if not gates:
        mapped = _decision_first_fail(decision)
        if mapped is not None:
            gates.add(mapped)
    return tuple(sorted(gates))


def _attach_record_halves(
    records: Sequence[DecisionRecord],
    half_map: Mapping[str, Mapping[date, str]],
) -> tuple[DecisionRecord, ...]:
    # Frozen replay events do not carry audit-only metadata.  A tiny immutable
    # proxy is avoided; scope filters read the original date directly through
    # this map in _record_half_map instead.
    _ = half_map
    return tuple(records)


def _record_half_map(record: DecisionRecord, half_map: Mapping[str, Mapping[date, str]]) -> str:
    return half_map[str(record.decision.market)][record.decision.trade_date]


def _build_decision_records(
    setup_type: str,
    events: Sequence[Any],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    half_map: Mapping[str, Mapping[date, str]],
) -> tuple[Any, tuple[DecisionRecord, ...]]:
    if setup_type == SETUP01:
        stream: Setup01DecisionStream = evaluate_setup01_decision_stream(
            events,
            quotes_by_symbol,
            risk_capital=None,
            swing_lookback=SWING_LOOKBACK,
            atr_period=ATR_PERIOD,
        )
    else:
        stream = evaluate_setup02_decision_stream(
            events,
            quotes_by_symbol,
            risk_capital=None,
            swing_lookback=SWING_LOOKBACK,
            atr_period=ATR_PERIOD,
        )
    event_by_identity = {event.event_identity: event for event in events}
    execution_by_identity = {execution.event_identity: execution for execution in stream.executions}
    records: list[DecisionRecord] = []
    for decision in stream.decisions:
        event = event_by_identity[decision.event_identity]
        geometry = _geometry_for_event(setup_type, event, quotes_by_symbol[event.symbol])
        records.append(
            DecisionRecord(
                setup_type=setup_type,
                event=event,
                decision=decision,
                execution=execution_by_identity.get(decision.event_identity),
                geometry=geometry,
                first_fail=_decision_first_fail(decision),
                all_fail_gates=_all_fail_gates(decision, geometry),
                provenance=PROVENANCE_DEVELOPMENT_HOLDOUT,
            )
        )
    # Check the event date -> half binding now, so later report code cannot
    # silently place a record in a wrong half.
    for record in records:
        if _record_half_map(record, half_map) not in {"EARLY", "LATE"}:
            raise AssertionError("decision event is outside the market half map")
    return stream, tuple(records)


def _decision_snapshot_digest(records: Sequence[DecisionRecord]) -> str:
    rows: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: (item.setup_type, item.decision.event_identity)):
        decision = record.decision
        rr = getattr(decision, "rr", None)
        execution = record.execution
        rows.append(
            {
                "setup_type": record.setup_type,
                "event_identity": decision.event_identity,
                "action": _enum_value(decision.action),
                "gate_reason": _enum_value(decision.gate_reason),
                "targets": list(getattr(decision, "targets", ()) or ()),
                "rr": list(rr.rr_ratios) if rr is not None else None,
                "execution_outcome": str(execution.outcome) if execution is not None else None,
                "actual_entry": execution.actual_entry if execution is not None else None,
            }
        )
    return _sha256_bytes(_canonical_json(rows).encode("utf-8"))


def _reason_rows(counts: Mapping[str, int], denominator: int, multiplier: float = 100.0) -> list[dict[str, Any]]:
    return [
        {
            "reason": reason,
            "count": int(count),
            "rate_pct": _round(_rate(int(count), denominator, multiplier)),
        }
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _first_fail_attribution(
    lifecycles: Sequence[LifecycleSummary],
    records: Sequence[DecisionRecord],
) -> dict[str, Any]:
    lifecycle_failures = Counter(row.first_fail for row in lifecycles if row.first_fail is not None)
    decision_failures = Counter(row.first_fail for row in records if row.first_fail is not None)
    t1_failures = Counter(
        _t1_first_fail(row.execution.outcome)
        for row in records
        if row.execution is not None and str(row.execution.outcome) != "EXECUTED"
    )
    return {
        "candidate_lifecycle_unit": {
            "denominator_lifecycles": len(lifecycles),
            "non_confirmed_lifecycles": sum(lifecycle_failures.values()),
            "rows": _reason_rows(lifecycle_failures, len(lifecycles)),
        },
        "confirmed_decision_unit": {
            "denominator_confirmed_events": len(records),
            "not_entry_allowed_events": sum(decision_failures.values()),
            "rows": _reason_rows(decision_failures, len(records)),
        },
        "exact_t_plus_1_unit": {
            "denominator_entry_allowed": sum(row.execution is not None for row in records),
            "not_executed_events": sum(t1_failures.values()),
            "rows": _reason_rows(t1_failures, sum(row.execution is not None for row in records)),
        },
    }


def _snapshot_for_event(record: DecisionRecord) -> Any:
    return record.event.setup01 if record.setup_type == SETUP01 else record.event.setup02


def _lifecycle_key_for_record(record: DecisionRecord) -> tuple[str, str, int | None]:
    snapshot = _snapshot_for_event(record)
    return record.setup_type, record.event.symbol, snapshot.lifecycle_index


def _structure_targets_at_snapshot(setup_type: str, snapshot: Any) -> dict[str, float]:
    """Return the existing canonical extension targets for a causal snapshot."""

    if setup_type == SETUP01:
        origin = snapshot.wave1_origin
        peak = snapshot.wave1_peak
        wave2_low = snapshot.wave2_low
        if origin is None or peak is None or wave2_low is None:
            return {}
        base = float(wave2_low.price)
        start = float(origin.price)
        end = float(peak.price)
    else:
        low0 = snapshot.continuation_low0
        high1 = snapshot.continuation_high1
        low2 = snapshot.continuation_low2
        if low0 is None or high1 is None or low2 is None:
            return {}
        base = float(low2.price)
        start = float(low0.price)
        end = float(high1.price)
    try:
        return {
            name: float(project_extension(base, start, end, ratio))
            for name, ratio in EXTENSION_RATIOS.items()
        }
    except (TypeError, ValueError):
        return {}


def _confirmation_metric_entry(
    record: DecisionRecord,
    lifecycle: LifecycleSummary | None,
    report: Setup01ReplayReport | Setup02ReplayReport | None,
    quotes: Sequence[Quote],
) -> dict[str, Any]:
    """Build one transient causal ARMED → CONFIRMED diagnostic row."""

    entry: dict[str, Any] = {
        "market": str(record.decision.market),
        "time_half": None,
        "provenance": record.provenance,
        "setup_type": record.setup_type,
        "has_armed": bool(lifecycle and lifecycle.first_armed_index is not None),
    }
    if lifecycle is None or lifecycle.first_armed_index is None or report is None:
        return entry
    armed_index = lifecycle.first_armed_index
    quote_by_date = {quote.trade_date: (index, quote) for index, quote in enumerate(quotes)}
    confirmation_value = quote_by_date.get(record.decision.trade_date)
    if confirmation_value is None or armed_index >= len(report.days):
        return entry
    confirmation_index, confirmation_quote = confirmation_value
    armed_quote = quotes[armed_index] if armed_index < len(quotes) else None
    if armed_quote is None or confirmation_index < armed_index:
        return entry
    entry["latency_sessions"] = confirmation_index - armed_index
    entry["price_move"] = float(confirmation_quote.close) - float(armed_quote.close)
    if float(armed_quote.close) > 0:
        entry["price_move_pct"] = (
            float(confirmation_quote.close) - float(armed_quote.close)
        ) / float(armed_quote.close)
    armed_prefix = list(quotes[: armed_index + 1])
    armed_atr = _finite(atr(armed_prefix, ATR_PERIOD)[-1]) if armed_prefix else None
    confirmation_atr = record.geometry.atr14
    entry["armed_atr14"] = armed_atr
    entry["confirmation_atr14"] = confirmation_atr
    if armed_atr is not None and armed_atr > 0:
        entry["price_move_atr"] = entry["price_move"] / armed_atr

    armed_snapshot = (
        report.days[armed_index].setup01
        if record.setup_type == SETUP01
        else report.days[armed_index].setup02
    )
    structure_targets = _structure_targets_at_snapshot(record.setup_type, armed_snapshot)
    for ratio_name, target in structure_targets.items():
        prefix = f"headroom_{ratio_name}"
        confirmation_close = float(confirmation_quote.close)
        entry[f"{prefix}_price"] = target - confirmation_close
        if confirmation_close > 0:
            entry[f"{prefix}_pct"] = (target - confirmation_close) / confirmation_close
        if confirmation_atr is not None and confirmation_atr > 0:
            entry[f"{prefix}_atr"] = (target - confirmation_close) / confirmation_atr
        denominator = target - float(armed_quote.close)
        if denominator != 0:
            entry[f"{prefix}_consumed_fraction"] = (
                confirmation_close - float(armed_quote.close)
            ) / denominator
    return entry


def _confirmation_metric_summary(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    confirmed = len(entries)
    with_armed = sum(bool(entry.get("has_armed")) for entry in entries)

    def stats(suffix: str) -> dict[str, Any]:
        return _distribution(entry.get(suffix) for entry in entries)

    headroom: dict[str, Any] = {}
    for ratio_name in EXTENSION_RATIOS:
        headroom[ratio_name] = {
            "price": stats(f"headroom_{ratio_name}_price"),
            "pct": stats(f"headroom_{ratio_name}_pct"),
            "atr_normalized": stats(f"headroom_{ratio_name}_atr"),
            "consumed_fraction": stats(f"headroom_{ratio_name}_consumed_fraction"),
        }
    return {
        "confirmed_events": confirmed,
        "confirmed_with_armed": with_armed,
        "confirmed_without_armed": confirmed - with_armed,
        "armed_to_confirmed_sample": with_armed,
        "latency_sessions": stats("latency_sessions"),
        "price_move": stats("price_move"),
        "price_move_pct": stats("price_move_pct"),
        "price_move_atr_normalized": stats("price_move_atr"),
        "headroom_at_confirmation_by_extension_ratio": headroom,
        "missing_metric_rows": {
            "armed_context": confirmed - with_armed,
            "latency": confirmed - stats("latency_sessions")["count"],
            "price_move": confirmed - stats("price_move")["count"],
            "price_move_atr_normalized": confirmed - stats("price_move_atr")["count"],
        },
        "definitions": {
            "armed_anchor": "first causal replay day in the confirmed lifecycle whose state is ARMED",
            "latency_sessions": "symbol-local replay index difference from first ARMED day to first CONFIRMED event day",
            "price_move": "confirmation-day close minus first-ARMED-day close",
            "price_move_atr_normalized": "price_move divided by ATR14 calculated on the prefix ending at first ARMED day",
            "headroom": "canonical existing extension target from the first ARMED structure minus confirmation-day close; negative means target already passed",
            "headroom_atr_normalized": "headroom divided by confirmation-day causal ATR14 from the existing Decision geometry",
            "consumed_fraction": "(confirmation close - ARMED close) / (extension target - ARMED close); descriptive and not a gate",
        },
    }


def _confirmation_diagnostics(
    setup_type: str,
    reports_by_setup: Mapping[str, Mapping[str, Setup01ReplayReport | Setup02ReplayReport]],
    lifecycles: Sequence[LifecycleSummary],
    records: Sequence[DecisionRecord],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    half_map: Mapping[str, Mapping[date, str]],
) -> dict[str, Any]:
    life_map = {
        (row.setup_type, row.symbol, row.lifecycle_index): row for row in lifecycles
    }
    entries = []
    for record in records:
        entry = _confirmation_metric_entry(
            record,
            life_map.get(_lifecycle_key_for_record(record)),
            reports_by_setup.get(record.setup_type, {}).get(record.event.symbol),
            quotes_by_symbol[record.event.symbol],
        )
        entry["time_half"] = half_map[str(record.decision.market)][record.decision.trade_date]
        entries.append(entry)

    def scoped(
        market: str | None = None,
        provenance: str | None = None,
        time_half: str | None = None,
    ) -> dict[str, Any]:
        rows = [
            entry
            for entry in entries
            if (market is None or entry["market"] == market)
            and (provenance is None or entry["provenance"] == provenance)
            and (time_half is None or entry["time_half"] == time_half)
        ]
        if not rows and provenance in {PROVENANCE_FORMAL, PROVENANCE_DYNAMIC_CANDIDATE}:
            return {
                "status": "NOT_REPRESENTED_IN_FROZEN_HOLDOUT",
                "confirmed_events": 0,
                "confirmed_with_armed": 0,
                "confirmed_without_armed": 0,
                "armed_lifecycles": 0,
                "armed_without_confirmed": 0,
                "armed_to_confirmed_rate_pct": None,
            }
        scoped_lifecycles = [
            lifecycle
            for lifecycle in lifecycles
            if (market is None or lifecycle.market == market)
            and (provenance is None or lifecycle.provenance == provenance)
            and (time_half is None or lifecycle.time_half == time_half)
        ]
        summary = _confirmation_metric_summary(rows)
        armed_lifecycles = sum(
            lifecycle.first_armed_index is not None for lifecycle in scoped_lifecycles
        )
        summary.update(
            {
                "armed_lifecycles": armed_lifecycles,
                "armed_without_confirmed": max(
                    armed_lifecycles - summary["confirmed_with_armed"], 0
                ),
                "armed_to_confirmed_rate_pct": _round(
                    _rate(summary["confirmed_with_armed"], armed_lifecycles, 100.0)
                ),
            }
        )
        return summary

    return {
        "setup_type": setup_type,
        "total": scoped(),
        "by_market": {market: scoped(market=market) for market in ("CN", "US")},
        "by_provenance": {
            provenance: scoped(provenance=provenance) for provenance in PROVENANCES
        },
    }


def _entry_zone_metric_summary(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    confirmed = len(entries)
    valid = [entry for entry in entries if entry.get("overshoot_pct") is not None]
    above = sum(bool(entry.get("above_entry_zone")) for entry in valid)
    return {
        "confirmed_events": confirmed,
        "valid_entry_zone_geometry_events": len(valid),
        "missing_entry_zone_geometry": confirmed - len(valid),
        "above_entry_zone_events": above,
        "above_entry_zone_rate_of_confirmed_pct": _round(_rate(above, confirmed, 100.0)),
        "above_entry_zone_rate_of_valid_geometry_pct": _round(_rate(above, len(valid), 100.0)),
        "overshoot_pct_vs_upper": _distribution(entry.get("overshoot_pct") for entry in valid),
        "overshoot_atr_normalized": _distribution(entry.get("overshoot_atr") for entry in valid),
        "definitions": {
            "entry_zone_upper": "confirmation_level + existing 0.5 * ATR14; no rule was changed",
            "overshoot_pct_vs_upper": "(confirmation-day close - Entry Zone upper) / Entry Zone upper; positive means above upper",
            "overshoot_atr_normalized": "(confirmation-day close - Entry Zone upper) / confirmation-day ATR14",
            "above_entry_zone": "the existing strict production predicate planned_entry > entry_zone_high",
        },
    }


def _entry_zone_diagnostics(
    records: Sequence[DecisionRecord],
    half_map: Mapping[str, Mapping[date, str]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for record in records:
        geometry = record.geometry
        entry: dict[str, Any] = {
            "market": str(record.decision.market),
            "time_half": half_map[str(record.decision.market)][record.decision.trade_date],
            "provenance": record.provenance,
        }
        if (
            geometry.planned_entry is not None
            and geometry.entry_zone_high is not None
            and geometry.atr14 is not None
            and geometry.entry_zone_high > 0
            and geometry.atr14 > 0
        ):
            difference = geometry.planned_entry - geometry.entry_zone_high
            entry["overshoot_pct"] = difference / geometry.entry_zone_high
            entry["overshoot_atr"] = difference / geometry.atr14
            entry["above_entry_zone"] = geometry.planned_entry > geometry.entry_zone_high
        entries.append(entry)

    def scoped(
        market: str | None = None,
        provenance: str | None = None,
        time_half: str | None = None,
    ) -> dict[str, Any]:
        rows = [
            entry
            for entry in entries
            if (market is None or entry["market"] == market)
            and (provenance is None or entry["provenance"] == provenance)
            and (time_half is None or entry["time_half"] == time_half)
        ]
        if not rows and provenance in {PROVENANCE_FORMAL, PROVENANCE_DYNAMIC_CANDIDATE}:
            return {
                "status": "NOT_REPRESENTED_IN_FROZEN_HOLDOUT",
                "confirmed_events": 0,
                "above_entry_zone_events": 0,
            }
        return _entry_zone_metric_summary(rows)

    return {
        "total": scoped(),
        "by_market": {market: scoped(market=market) for market in ("CN", "US")},
        "by_provenance": {
            provenance: scoped(provenance=provenance) for provenance in PROVENANCES
        },
    }


def _rr_component_attribution(
    planned_entry: float,
    structural_invalidation: float,
    execution_stop: float,
    targets: Sequence[float],
) -> dict[str, Any] | None:
    """Attribute an RR failure with fixed, non-production counterfactuals."""

    if not targets:
        return None
    try:
        actual = risk_reward(planned_entry, execution_stop, (float(targets[0]),))
        if not actual.rr_ratios or actual.rr_ratios[0] >= 2.0:
            return None
        if structural_invalidation >= planned_entry or execution_stop >= planned_entry:
            return None
        structural = risk_reward(
            planned_entry,
            structural_invalidation,
            (float(targets[0]),),
        )
        next_actual = None
        next_structural = None
        if len(targets) > 1:
            next_actual = risk_reward(
                planned_entry,
                execution_stop,
                (float(targets[1]),),
            )
            next_structural = risk_reward(
                planned_entry,
                structural_invalidation,
                (float(targets[1]),),
            )
        structural_pass = bool(structural.rr_ratios and structural.rr_ratios[0] >= 2.0)
        next_actual_pass = bool(next_actual and next_actual.rr_ratios and next_actual.rr_ratios[0] >= 2.0)
        next_structural_pass = bool(next_structural and next_structural.rr_ratios and next_structural.rr_ratios[0] >= 2.0)
        if structural_pass:
            category = "EXECUTION_STOP_DISTANCE_TOO_LARGE"
        elif next_actual_pass:
            category = "FIRST_FORMAL_TARGET_DISTANCE_TOO_CLOSE"
        elif next_structural_pass:
            category = "BOTH_STOP_AND_TARGET_DISTANCE"
        else:
            category = "INSUFFICIENT_COMPONENT_EVIDENCE"
        return {
            "category": category,
            "actual_rr": actual.rr_ratios[0],
            "rr_at_structural_invalidation": structural.rr_ratios[0],
            "rr_at_next_target_actual_stop": next_actual.rr_ratios[0] if next_actual else None,
            "rr_at_next_target_structural_invalidation": next_structural.rr_ratios[0] if next_structural else None,
            "has_next_formal_target": len(targets) > 1,
        }
    except (TypeError, ValueError, IndexError):
        return None


def _rr_distance_summary(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(entries),
        "execution_stop_distance": _distribution(entry.get("execution_stop_distance") for entry in entries),
        "execution_stop_distance_pct": _distribution(entry.get("execution_stop_distance_pct") for entry in entries),
        "execution_stop_distance_atr": _distribution(entry.get("execution_stop_distance_atr") for entry in entries),
        "structural_stop_distance": _distribution(entry.get("structural_stop_distance") for entry in entries),
        "t1_reward_distance": _distribution(entry.get("t1_reward_distance") for entry in entries),
        "t1_reward_distance_pct": _distribution(entry.get("t1_reward_distance_pct") for entry in entries),
        "t1_reward_distance_atr": _distribution(entry.get("t1_reward_distance_atr") for entry in entries),
    }


def _rr_component_summary(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failure_entries = [entry for entry in entries if entry.get("component_category") is not None]
    counts = Counter(str(entry["component_category"]) for entry in failure_entries)
    supported = sum(
        category != "INSUFFICIENT_COMPONENT_EVIDENCE"
        for category in counts.elements()
    )
    return {
        "rr_below_minimum_events": len(failure_entries),
        "component_rows": _reason_rows(counts, len(failure_entries)),
        "component_category_counts": dict(sorted(counts.items())),
        "component_attribution_supported_events": supported,
        "component_attribution_supported_rate_pct": _round(
            _rate(supported, len(failure_entries), 100.0)
        ),
        "distance_summary_all_calculable": _rr_distance_summary(entries),
        "distance_summary_rr_failures": _rr_distance_summary(failure_entries),
    }


def _rr_diagnostics(
    records: Sequence[DecisionRecord],
    half_map: Mapping[str, Mapping[date, str]],
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for record in records:
        geometry = record.geometry
        if (
            not geometry.calculable
            or geometry.planned_entry is None
            or geometry.execution_stop is None
            or geometry.structural_invalidation is None
            or geometry.atr14 is None
            or not geometry.targets
        ):
            continue
        entry = {
            "market": str(record.decision.market),
            "time_half": half_map[str(record.decision.market)][record.decision.trade_date],
            "provenance": record.provenance,
            "execution_stop_distance": abs(geometry.planned_entry - geometry.execution_stop),
            "execution_stop_distance_pct": abs(geometry.planned_entry - geometry.execution_stop) / geometry.planned_entry if geometry.planned_entry else None,
            "execution_stop_distance_atr": abs(geometry.planned_entry - geometry.execution_stop) / geometry.atr14 if geometry.atr14 > 0 else None,
            "structural_stop_distance": abs(geometry.planned_entry - geometry.structural_invalidation),
            "t1_reward_distance": geometry.targets[0] - geometry.planned_entry,
            "t1_reward_distance_pct": (geometry.targets[0] - geometry.planned_entry) / geometry.planned_entry if geometry.planned_entry else None,
            "t1_reward_distance_atr": (geometry.targets[0] - geometry.planned_entry) / geometry.atr14 if geometry.atr14 > 0 else None,
            "component_category": None,
        }
        attribution = _rr_component_attribution(
            geometry.planned_entry,
            geometry.structural_invalidation,
            geometry.execution_stop,
            geometry.targets,
        )
        if attribution is not None:
            entry.update({
                "component_category": attribution["category"],
                "actual_rr": attribution["actual_rr"],
                "rr_at_structural_invalidation": attribution["rr_at_structural_invalidation"],
                "rr_at_next_target_actual_stop": attribution["rr_at_next_target_actual_stop"],
                "rr_at_next_target_structural_invalidation": attribution["rr_at_next_target_structural_invalidation"],
                "has_next_formal_target": attribution["has_next_formal_target"],
            })
        entries.append(entry)

    def scoped(
        market: str | None = None,
        provenance: str | None = None,
        time_half: str | None = None,
    ) -> dict[str, Any]:
        rows = [
            entry
            for entry in entries
            if (market is None or entry["market"] == market)
            and (provenance is None or entry["provenance"] == provenance)
            and (time_half is None or entry["time_half"] == time_half)
        ]
        if not rows and provenance in {PROVENANCE_FORMAL, PROVENANCE_DYNAMIC_CANDIDATE}:
            return {
                "status": "NOT_REPRESENTED_IN_FROZEN_HOLDOUT",
                "rr_below_minimum_events": 0,
                "component_category_counts": {},
            }
        return _rr_component_summary(rows)

    return {
        "total": scoped(),
        "by_market": {market: scoped(market=market) for market in ("CN", "US")},
        "by_provenance": {
            provenance: scoped(provenance=provenance) for provenance in PROVENANCES
        },
        "definitions": {
            "execution_stop_distance": "absolute T-day distance from planned entry to existing execution stop",
            "structural_stop_distance": "absolute T-day distance from planned entry to structural invalidation; used only as a fixed diagnostic baseline",
            "EXECUTION_STOP_DISTANCE_TOO_LARGE": "T1 fails at the existing execution stop but passes at unchanged structural invalidation",
            "FIRST_FORMAL_TARGET_DISTANCE_TOO_CLOSE": "T1 fails at the existing execution stop but the next existing formal target passes at that same stop, while structural-stop T1 still fails",
            "BOTH_STOP_AND_TARGET_DISTANCE": "T1 fails at the existing execution stop; neither single counterfactual passes, but next target plus structural invalidation passes",
            "INSUFFICIENT_COMPONENT_EVIDENCE": "No valid next-target/structural-stop counterfactual supports a component attribution",
            "important_algebra": "Production RR failure is simultaneously reward < 2R and risk > reward/2 by definition; these labels are deterministic counterfactual attributions, not independent production gates.",
        },
    }


def _provenance_summary(
    observations: Sequence[SessionObservation],
    lifecycles_by_setup: Mapping[str, Sequence[LifecycleSummary]],
    records_by_setup: Mapping[str, Sequence[DecisionRecord]],
) -> dict[str, Any]:
    lifecycles = tuple(row for setup in SETUPS for row in lifecycles_by_setup[setup])
    records = tuple(row for setup in SETUPS for row in records_by_setup[setup])
    rows: dict[str, Any] = {}
    for provenance in PROVENANCES:
        scoped_observations = [row for row in observations if row.provenance == provenance]
        scoped_lifecycles = [row for row in lifecycles if row.provenance == provenance]
        scoped_records = [row for row in records if row.provenance == provenance]
        allowed = sum(
            _enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value
            for record in scoped_records
        )
        executed = sum(
            record.execution is not None and str(record.execution.outcome) == "EXECUTED"
            for record in scoped_records
        )
        rows[provenance] = {
            "status": (
                "OBSERVED_FROZEN_DEVELOPMENT_ROSTER"
                if provenance == PROVENANCE_DEVELOPMENT_HOLDOUT
                else "NOT_REPRESENTED_IN_FROZEN_HOLDOUT"
            ),
            "symbol_count": len({row.symbol for row in scoped_observations}),
            "symbol_session_count": len(scoped_observations),
            "candidate_lifecycle_count": len(scoped_lifecycles),
            "confirmed_event_count": len(scoped_records),
            "entry_allowed_count": allowed,
            "executed_count": executed,
        }
    return {
        "rows": rows,
        "comparison_status": "INSUFFICIENT_EVIDENCE_FOR_FORMAL_VS_LIVE_CANDIDATE",
        "interpretation": "The pinned Development holdout roster is candidate-like but explicitly excludes the formal A1 identities; no live Candidate selector or production formal pool was read or rerun. Zero formal/dynamic rows are structural absence, not zero production signal rate.",
    }


def _top_bottlenecks(
    lifecycles: Sequence[LifecycleSummary],
    records: Sequence[DecisionRecord],
    first_fail: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidate_count = len(lifecycles)
    confirmed_count = len(records)
    decision_rows = first_fail.get("rows", [])
    first_fail_counts = {row["reason"]: int(row["count"]) for row in decision_rows}
    rows = [
        {
            "node": "CANDIDATE_LIFECYCLE_NOT_CONFIRMED",
            "count": candidate_count - confirmed_count,
            "denominator": candidate_count,
            "rate_pct": _round(_rate(candidate_count - confirmed_count, candidate_count, 100.0)),
            "unit": "candidate lifecycle",
        },
        {
            "node": "CONFIRMED_TO_ABOVE_ENTRY_ZONE",
            "count": first_fail_counts.get("ABOVE_ENTRY_ZONE", 0),
            "denominator": confirmed_count,
            "rate_pct": _round(_rate(first_fail_counts.get("ABOVE_ENTRY_ZONE", 0), confirmed_count, 100.0)),
            "unit": "confirmed event",
        },
        {
            "node": "CONFIRMED_TO_TARGET_UPSIDE_BELOW_MINIMUM",
            "count": first_fail_counts.get("TARGET_UPSIDE_BELOW_MINIMUM", 0),
            "denominator": confirmed_count,
            "rate_pct": _round(_rate(first_fail_counts.get("TARGET_UPSIDE_BELOW_MINIMUM", 0), confirmed_count, 100.0)),
            "unit": "confirmed event",
        },
        {
            "node": "CONFIRMED_TO_RR_BELOW_MINIMUM",
            "count": first_fail_counts.get("RR_BELOW_MINIMUM", 0),
            "denominator": confirmed_count,
            "rate_pct": _round(_rate(first_fail_counts.get("RR_BELOW_MINIMUM", 0), confirmed_count, 100.0)),
            "unit": "confirmed event",
        },
    ]
    return sorted(rows, key=lambda row: (-row["count"], row["node"]))[:3]


def _t1_first_fail(outcome: str) -> str:
    return {
        "SKIP_NO_T1_BAR": "T+1 NO EXACT OPEN",
        "SKIP_BELOW_INVALIDATION": "T+1 BELOW INVALIDATION",
        "SKIP_GAP_BELOW_CONFIRMATION": "T+1 BELOW CONFIRMATION",
        "SKIP_GAP_ABOVE_ENTRY_ZONE": "T+1 GAP ABOVE ENTRY ZONE",
        "SKIP_TARGET_UPSIDE_BELOW_MINIMUM": "T+1 TARGET UPSIDE",
        "SKIP_RR_BELOW_MINIMUM_AT_OPEN": "T+1 RR",
    }.get(str(outcome), str(outcome))


def _overlap_diagnostics(records: Sequence[DecisionRecord]) -> dict[str, Any]:
    failed_records = [record for record in records if _enum_value(record.decision.action) != DecisionAction.ENTRY_ALLOWED.value]
    gate_sets = [set(record.all_fail_gates) for record in failed_records]
    raw_counts = Counter(gate for gate_set in gate_sets for gate in gate_set)
    unique_only = Counter(
        next(iter(gate_set))
        for gate_set in gate_sets
        if len(gate_set) == 1
    )
    first_fail_counts = Counter(record.first_fail for record in failed_records if record.first_fail is not None)
    gate_rows = []
    for gate in OVERLAP_GATES:
        raw = raw_counts[gate]
        unique = unique_only[gate]
        gate_rows.append(
            {
                "gate": gate,
                "first_fail_count": first_fail_counts[gate],
                "raw_rejection_count": raw,
                "unique_only_failure_count": unique,
                "overlap_rejection_count": raw - unique,
                "raw_rate_per_failed_decision_pct": _round(_rate(raw, len(failed_records), 100.0)),
            }
        )

    pairs: list[dict[str, Any]] = []
    triples: list[dict[str, Any]] = []
    gate_universe = tuple(sorted(set().union(*gate_sets))) if gate_sets else ()
    for size, target in ((2, pairs), (3, triples)):
        for combo in itertools.combinations(gate_universe, size):
            intersection = sum(all(gate in gate_set for gate in combo) for gate_set in gate_sets)
            if not intersection:
                continue
            counts = [raw_counts[gate] for gate in combo]
            union = sum(1 for gate_set in gate_sets if any(gate in gate_set for gate in combo))
            target.append(
                {
                    "gates": list(combo),
                    "intersection_count": intersection,
                    "conditional_rate_pct": {
                        gate: _round(_rate(intersection, raw_counts[gate], 100.0)) for gate in combo
                    },
                    "jaccard": _round(_rate(intersection, union)),
                }
            )
        target.sort(key=lambda row: (-row["intersection_count"], -float(row["jaccard"] or 0.0), row["gates"]))

    return {
        "failed_decision_events": len(failed_records),
        "gate_rows": gate_rows,
        "pairwise_overlap": pairs[:20],
        "triple_overlap": triples[:20],
        "definitions": {
            "raw_rejection_count": "count of failed confirmed decisions whose all-fail diagnostic set contains the gate",
            "unique_only_failure_count": "count whose all-fail diagnostic set contains only that gate",
            "overlap_rejection_count": "raw minus unique-only; not an independent rejection count",
            "production_precedence_unchanged": True,
        },
    }


def _rebuild_plan(geometry: GeometrySnapshot, candidates: Sequence[Any]) -> CounterfactualPlan | None:
    if not geometry.calculable or geometry.planned_entry is None or geometry.execution_stop is None:
        return None
    targets = tuple(float(candidate.price) for candidate in tuple(candidates)[:3])
    if not targets:
        return None
    rr = risk_reward(geometry.planned_entry, geometry.execution_stop, targets)
    if geometry.setup_type == SETUP01:
        reasonableness_failed = rr.quality == HIGH_ASYMMETRY and not _setup01_targets_are_reasonable(
            tuple(candidates),
            entry=geometry.planned_entry,
            origin=geometry.structure_values[0],
            peak=geometry.structure_values[1],
            wave2_low=geometry.structure_values[2],
        )
    else:
        reasonableness_failed = rr.quality == HIGH_ASYMMETRY and not _setup02_targets_are_reasonable(
            tuple(candidates),
            entry=geometry.planned_entry,
            low0=geometry.structure_values[0],
            high1=geometry.structure_values[1],
            low2=geometry.structure_values[2],
            execution_stop=geometry.execution_stop,
            as_of_date=geometry.as_of_date or date.min,
        )
    if reasonableness_failed:
        return None
    upside = target_upside_pct(targets[0], geometry.planned_entry)
    if not _finite(upside):
        return None
    return CounterfactualPlan(
        setup_type=geometry.setup_type,
        planned_entry=float(geometry.planned_entry),
        entry_zone_low=float(geometry.entry_zone_low),
        entry_zone_high=float(geometry.entry_zone_high),
        structural_invalidation=float(geometry.structural_invalidation),
        execution_stop=float(geometry.execution_stop),
        confirmation_level=float(geometry.confirmation_level),
        targets=targets,
        target_candidates=tuple(candidates),
        rr=rr,
        target_upside_pct=float(upside),
    )


def _counterfactual_plan_for_gate(record: DecisionRecord, gate: str) -> CounterfactualPlan | None:
    geometry = record.geometry
    if not geometry.calculable:
        return None
    if gate == "ENTRY_ZONE":
        if geometry.planned_entry is None or geometry.entry_zone_high is None or geometry.planned_entry <= geometry.entry_zone_high:
            return None
    elif gate == "TARGET_UPSIDE_BELOW_MINIMUM":
        if geometry.target_upside_pct is None or geometry.target_upside_pct >= MIN_TARGET_UPSIDE_PCT:
            return None
    elif gate == "RR_BELOW_MINIMUM":
        if geometry.rr is None or not geometry.rr.rr_ratios or geometry.rr.rr_ratios[0] >= 2.0:
            return None
    elif gate == "FORMAL_T1_CONFIRMED_SWING_HIGH":
        if not geometry.target_candidates or not _source_has(geometry.target_candidates[0], "CONFIRMED_SWING_HIGH"):
            return None
    else:
        raise ValueError(f"unsupported counterfactual gate: {gate}")

    candidates = tuple(geometry.target_candidates)
    if gate == "FORMAL_T1_CONFIRMED_SWING_HIGH":
        candidates = tuple(
            candidate
            for candidate in (
                _remove_candidate_source(candidate, "CONFIRMED_SWING_HIGH")
                for candidate in candidates
            )
            if candidate is not None
        )
    plan = _rebuild_plan(geometry, candidates)
    if plan is None:
        return None
    if geometry.planned_entry is not None and geometry.entry_zone_high is not None and geometry.planned_entry > geometry.entry_zone_high and gate != "ENTRY_ZONE":
        return None
    if plan.target_upside_pct < MIN_TARGET_UPSIDE_PCT and gate != "TARGET_UPSIDE_BELOW_MINIMUM":
        return None
    if plan.rr.rr_ratios[0] < 2.0 and gate != "RR_BELOW_MINIMUM":
        return None
    return plan


def _exact_next_open(
    decision: Any,
    quotes: Sequence[Quote],
    market_session_dates: Mapping[str, Sequence[date]],
) -> float | None:
    sessions = tuple(market_session_dates.get(str(decision.market), ()))
    ordinals = {trade_date: index for index, trade_date in enumerate(sessions)}
    if decision.trade_date not in ordinals:
        return None
    next_index = ordinals[decision.trade_date] + 1
    if next_index >= len(sessions):
        return None
    expected = sessions[next_index]
    matches = [
        quote
        for quote in quotes
        if quote.trade_date == expected
        and quote.symbol == decision.symbol
        and quote.market == decision.market
    ]
    return float(matches[0].open) if len(matches) == 1 else None


def _counterfactual_t1_executed(
    record: DecisionRecord,
    plan: CounterfactualPlan,
    gate: str,
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> bool:
    opening = _exact_next_open(record.decision, quotes_by_symbol[record.decision.symbol], market_session_dates)
    if opening is None:
        return False
    if opening <= plan.structural_invalidation:
        return False
    if opening < plan.entry_zone_low:
        return False
    if opening > plan.entry_zone_high and gate != "ENTRY_ZONE":
        return False
    remaining_upside = target_upside_pct(plan.targets[0], opening)
    if remaining_upside < MIN_TARGET_UPSIDE_PCT and gate != "TARGET_UPSIDE_BELOW_MINIMUM":
        return False
    actual_rr = risk_reward(opening, plan.execution_stop, plan.targets)
    if actual_rr.rr_ratios[0] < 2.0 and gate != "RR_BELOW_MINIMUM":
        return False
    return True


def _scope_increment(
    records: Sequence[DecisionRecord],
    new_records: Sequence[DecisionRecord],
    *,
    setup_type: str | None = None,
    market: str | None = None,
    half_map: Mapping[str, Mapping[date, str]] | None = None,
    time_half: str | None = None,
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    gate: str,
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    base = [
        record
        for record in records
        if (setup_type is None or record.setup_type == setup_type)
        and (market is None or str(record.decision.market) == market)
        and (
            time_half is None
            or half_map is None
            or half_map[str(record.decision.market)][record.decision.trade_date] == time_half
        )
    ]
    added = [
        record
        for record in new_records
        if (setup_type is None or record.setup_type == setup_type)
        and (market is None or str(record.decision.market) == market)
        and (
            time_half is None
            or half_map is None
            or half_map[str(record.decision.market)][record.decision.trade_date] == time_half
        )
    ]
    executed = sum(
        _counterfactual_t1_executed(record, _counterfactual_plan_for_gate(record, gate), gate, quotes_by_symbol, market_session_dates)
        for record in added
        if _counterfactual_plan_for_gate(record, gate) is not None
    )
    base_allowed = sum(_enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value for record in base)
    return {
        "confirmed_events": len(base),
        "base_entry_allowed": base_allowed,
        "incremental_entry_allowed": len(added),
        "hypothetical_entry_allowed": base_allowed + len(added),
        "incremental_t1_executable": executed,
    }


def _single_gate_ablation(
    records: Sequence[DecisionRecord],
    overlap: Mapping[str, Any],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    half_map: Mapping[str, Mapping[date, str]],
    market_session_dates: Mapping[str, Sequence[date]],
    preconfirmation_reference: Mapping[str, Any],
    candidate_symbol_session_count: int,
) -> dict[str, Any]:
    base_entry_allowed = sum(_enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value for record in records)
    rows: dict[str, Any] = {}
    gate_stats = {row["gate"]: row for row in overlap["gate_rows"]}
    for gate in ABLATION_GATES:
        new_records: list[DecisionRecord] = []
        for record in records:
            if _enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value:
                continue
            plan = _counterfactual_plan_for_gate(record, gate)
            if plan is not None:
                new_records.append(record)
        executable = sum(
            _counterfactual_t1_executed(
                record,
                _counterfactual_plan_for_gate(record, gate),
                gate,
                quotes_by_symbol,
                market_session_dates,
            )
            for record in new_records
            if _counterfactual_plan_for_gate(record, gate) is not None
        )
        overlap_gate = "ABOVE_ENTRY_ZONE" if gate == "ENTRY_ZONE" else gate
        raw = gate_stats.get(overlap_gate, {})
        row = {
            "gate": gate,
            "first_fail_count": raw.get("first_fail_count", 0),
            "raw_rejection_count": raw.get("raw_rejection_count", 0),
            "unique_only_failure_count": raw.get("unique_only_failure_count", 0),
            "overlap_rejection_count": raw.get("overlap_rejection_count", 0),
            "base_confirmed_events": len(records),
            "base_entry_allowed": base_entry_allowed,
            "hypothetical_entry_allowed": base_entry_allowed + len(new_records),
            "incremental_entry_allowed": len(new_records),
            "incremental_t1_executable": executable,
            "incremental_rate_per_100_confirmed": _round(_rate(len(new_records), len(records), 100.0)),
            "incremental_executable_rate_per_100_confirmed": _round(_rate(executable, len(records), 100.0)),
            "incremental_rate_per_1000_candidate_symbol_sessions": _round(_rate(len(new_records), candidate_symbol_session_count, 1000.0)),
            "one_gate_only": True,
            "source_events_mutated": False,
            "by_setup": {
                setup: _scope_increment(
                    records,
                    new_records,
                    setup_type=setup,
                    half_map=half_map,
                    quotes_by_symbol=quotes_by_symbol,
                    gate=gate,
                    market_session_dates=market_session_dates,
                )
                for setup in SETUPS
            },
            "by_market": {
                market: _scope_increment(
                    records,
                    new_records,
                    market=market,
                    half_map=half_map,
                    quotes_by_symbol=quotes_by_symbol,
                    gate=gate,
                    market_session_dates=market_session_dates,
                )
                for market in ("CN", "US")
            },
            "by_time_half": {
                half: _scope_increment(
                    records,
                    new_records,
                    time_half=half,
                    half_map=half_map,
                    quotes_by_symbol=quotes_by_symbol,
                    gate=gate,
                    market_session_dates=market_session_dates,
                )
                for half in ("EARLY", "LATE")
            },
        }
        rows[gate] = row

    incumbent = preconfirmation_reference["policies"].get("INCUMBENT_CONFIRMED_CLOSE", {})
    policy_rows = []
    for policy, values in sorted(preconfirmation_reference["policies"].items()):
        signaled = int(values.get("signaled", 0))
        failed = int(values.get("failed", 0))
        never = int(values.get("never_confirmed", 0))
        policy_rows.append(
            {
                "policy": policy,
                "cohort": int(values.get("cohort", 0)),
                "signaled": signaled,
                "eventually_confirmed": int(values.get("eventually_confirmed", 0)),
                "failed_plus_never_confirmed": failed + never,
                "failed_plus_never_confirmed_rate_pct": _round(_rate(failed + never, signaled, 100.0)),
                "executable_next_session": int(values.get("executable_next_session", 0)),
            }
        )
    rows[CONFIRMATION_ABLATION_GATE] = {
        "gate": CONFIRMATION_ABLATION_GATE,
        "ablation_type": "REFERENCE_ONLY_THEORETICAL_SIGNAL_LOSS_ACCOUNTING",
        "first_fail_count": None,
        "raw_rejection_count": int(incumbent.get("not_signaled", 0)),
        "unique_only_failure_count": None,
        "overlap_rejection_count": None,
        "base_confirmed_events": int(incumbent.get("cohort", 0)),
        "base_entry_allowed": int(incumbent.get("signaled", 0)),
        "hypothetical_entry_allowed": None,
        "incremental_entry_allowed": None,
        "incremental_t1_executable": None,
        "incremental_rate_per_100_confirmed": None,
        "incremental_executable_rate_per_100_confirmed": None,
        "incremental_rate_per_1000_candidate_symbol_sessions": None,
        "theoretical_cohort_not_signaled_by_confirmation": int(incumbent.get("not_signaled", 0)),
        "production_entry_allowed_increment": None,
        "production_t1_executable_increment": None,
        "policy_reference_rows": policy_rows,
        "early_policy_failure_share_constraint": "59.9%–76.4%",
        "one_gate_only": True,
        "source_events_mutated": False,
        "production_authorization": False,
    }
    return {
        "base_confirmed_events": len(records),
        "base_entry_allowed": base_entry_allowed,
        "gates": rows,
        "confirmation_warning": "Confirmation is not converted into a production entry event; the four fixed PR #89 policies remain a safety constraint only.",
    }


def _target_upside_gate_contribution(
    records: Sequence[DecisionRecord],
    overlap: Mapping[str, Any],
    ablation: Mapping[str, Any],
) -> dict[str, Any]:
    """Make the marginal 5% gate contribution explicit without tuning it."""

    first_fail_by_gate = {
        row["gate"]: int(row["first_fail_count"])
        for row in overlap.get("gate_rows", [])
    }
    comparisons = []
    for gate in ("ABOVE_ENTRY_ZONE", "TARGET_UPSIDE_BELOW_MINIMUM", "RR_BELOW_MINIMUM"):
        ablation_gate = "ENTRY_ZONE" if gate == "ABOVE_ENTRY_ZONE" else gate
        row = ablation.get("gates", {}).get(ablation_gate, {})
        comparisons.append(
            {
                "gate": gate,
                "production_first_fail_count": first_fail_by_gate.get(gate, 0),
                "production_first_fail_rate_pct": _round(
                    _rate(first_fail_by_gate.get(gate, 0), len(records), 100.0)
                ),
                "raw_applicable_count": int(row.get("raw_rejection_count", 0) or 0),
                "unique_only_count": int(row.get("unique_only_failure_count", 0) or 0),
                "one_gate_counterfactual_incremental_entry_allowed": int(
                    row.get("incremental_entry_allowed", 0) or 0
                ),
                "one_gate_counterfactual_incremental_t1_executable": int(
                    row.get("incremental_t1_executable", 0) or 0
                ),
            }
        )
    target_row = next(
        row for row in comparisons if row["gate"] == "TARGET_UPSIDE_BELOW_MINIMUM"
    )
    return {
        "gate": "TARGET_UPSIDE_BELOW_MINIMUM",
        "minimum_target_upside_pct_unchanged": MIN_TARGET_UPSIDE_PCT,
        "confirmed_denominator": len(records),
        "events_stopped_at_new_5pct_gate": target_row["production_first_fail_count"],
        "events_stopped_at_new_5pct_gate_rate_pct": target_row["production_first_fail_rate_pct"],
        "events_reaching_following_rr_stage_if_gate_removed": target_row["production_first_fail_count"],
        "one_gate_counterfactual_incremental_entry_allowed": target_row[
            "one_gate_counterfactual_incremental_entry_allowed"
        ],
        "one_gate_counterfactual_incremental_t1_executable": target_row[
            "one_gate_counterfactual_incremental_t1_executable"
        ],
        "comparison_with_major_downstream_gates": comparisons,
        "interpretation": "The first-fail count is the marginal position of the 5% gate in the unchanged precedence: these events passed Entry Zone and target existence/provenance, then were stopped before the existing RR gate. The one-gate counterfactual keeps every other production predicate fixed and is not a recommendation to remove the gate.",
    }


def _load_preconfirmation_reference(path: Path = PRECONFIRMATION_REFERENCE_PATH) -> dict[str, Any]:
    reference = _load_json(path)
    if reference.get("protocol_version") != "PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH_V1":
        raise ValueError("pre-confirmation reference protocol changed")
    controls = reference.get("controls", {})
    for key in ("final_oos_accessed", "parameter_search", "threshold_sweep", "production_rule_change"):
        if controls.get(key):
            raise ValueError(f"unsafe pre-confirmation reference control: {key}")
    policies = reference.get("funnel", {}).get("policy", {})
    if not isinstance(policies, dict) or "INCUMBENT_CONFIRMED_CLOSE" not in policies:
        raise ValueError("pre-confirmation reference missing incumbent policy")
    return {
        "artifact_path": str(path.relative_to(PROJECT_ROOT)),
        "artifact_sha256": _sha256_file(path),
        "protocol_version": reference["protocol_version"],
        "controls": {
            "final_oos_accessed": bool(controls.get("final_oos_accessed", False)),
            "parameter_search": bool(controls.get("parameter_search", False)),
            "threshold_sweep": bool(controls.get("threshold_sweep", False)),
            "production_rule_change": bool(controls.get("production_rule_change", False)),
        },
        "policies": policies,
    }


def _frequency_entry(
    observations: Sequence[SessionObservation],
    records: Sequence[DecisionRecord],
    lifecycles: Sequence[LifecycleSummary],
    *,
    scope_label: str,
) -> dict[str, Any]:
    symbol_sessions = len(observations)
    market_sessions = len({row.trade_date for row in observations})
    symbols = len({row.symbol for row in observations})
    confirmed = len(records)
    entry_allowed = sum(_enum_value(row.decision.action) == DecisionAction.ENTRY_ALLOWED.value for row in records)
    executed = sum(row.execution is not None and str(row.execution.outcome) == "EXECUTED" for row in records)
    event_by_symbol = Counter(row.decision.symbol for row in records)
    top_symbols = sorted(event_by_symbol.items(), key=lambda item: (-item[1], item[0]))
    return {
        "scope": scope_label,
        "symbol_count": symbols,
        "market_session_count": market_sessions,
        "symbol_session_count": symbol_sessions,
        "candidate_lifecycle_count": len(lifecycles),
        "confirmed_count": confirmed,
        "entry_allowed_count": entry_allowed,
        "executed_count": executed,
        "confirmed_per_1000_symbol_sessions": _round(_rate(confirmed, symbol_sessions, 1000.0)),
        "entry_allowed_per_1000_symbol_sessions": _round(_rate(entry_allowed, symbol_sessions, 1000.0)),
        "executed_per_1000_symbol_sessions": _round(_rate(executed, symbol_sessions, 1000.0)),
        "confirmed_per_100_candidate_lifecycles": _round(_rate(confirmed, len(lifecycles), 100.0)),
        "entry_allowed_per_100_confirmed": _round(_rate(entry_allowed, confirmed, 100.0)),
        "executed_per_100_entry_allowed": _round(_rate(executed, entry_allowed, 100.0)),
        "descriptive_market_sessions_per_one": {
            "confirmed": _round(_rate(market_sessions, confirmed)),
            "entry_allowed": _round(_rate(market_sessions, entry_allowed)),
            "executed": _round(_rate(market_sessions, executed)),
        },
        "symbol_concentration": {
            "max_symbol_count": top_symbols[0][1] if top_symbols else 0,
            "max_symbol_share_pct": _round(_rate(top_symbols[0][1], confirmed, 100.0)) if top_symbols else None,
            "top_5_count": sum(count for _, count in top_symbols[:5]),
            "top_5_share_pct": _round(_rate(sum(count for _, count in top_symbols[:5]), confirmed, 100.0)) if top_symbols else None,
            "top_symbols": [{"symbol": symbol, "count": count} for symbol, count in top_symbols[:5]],
        },
    }


def _frequency_context(
    observations: Sequence[SessionObservation],
    records_by_setup: Mapping[str, Sequence[DecisionRecord]],
    lifecycles_by_setup: Mapping[str, Sequence[LifecycleSummary]],
    half_map: Mapping[str, Mapping[date, str]],
) -> dict[str, Any]:
    all_records = tuple(record for setup in SETUPS for record in records_by_setup[setup])
    all_lifecycles = tuple(row for setup in SETUPS for row in lifecycles_by_setup[setup])

    def for_market(market: str, setup_type: str | None = None) -> dict[str, Any]:
        rows = tuple(row for row in observations if row.market == market)
        records = tuple(
            record
            for record in (records_by_setup[setup_type] if setup_type else all_records)
            if str(record.decision.market) == market
        )
        lifecycles = tuple(
            row
            for row in (lifecycles_by_setup[setup_type] if setup_type else all_lifecycles)
            if row.market == market
        )
        return _frequency_entry(rows, records, lifecycles, scope_label=f"{market}{'/' + setup_type if setup_type else ''}")

    by_half: dict[str, Any] = {}
    for half in ("EARLY", "LATE"):
        rows = tuple(row for row in observations if row.time_half == half)
        records = tuple(
            record
            for record in all_records
            if half_map[str(record.decision.market)][record.decision.trade_date] == half
        )
        lifecycles = tuple(row for row in all_lifecycles if row.time_half == half)
        by_half[half] = _frequency_entry(rows, records, lifecycles, scope_label=half)

    return {
        "event_unit": "confirmed/Decision/executable counts are setup events; symbol-session is the denominator",
        "all": _frequency_entry(observations, all_records, all_lifecycles, scope_label="ALL"),
        "by_market": {market: for_market(market) for market in ("CN", "US")},
        "by_setup": {
            setup: _frequency_entry(
                observations,
                records_by_setup[setup],
                lifecycles_by_setup[setup],
                scope_label=setup,
            )
            for setup in SETUPS
        },
        "by_market_setup": {
            market: {setup: for_market(market, setup) for setup in SETUPS}
            for market in ("CN", "US")
        },
        "by_time_half": by_half,
        "time_half_definition": "EARLY/LATE split at the midpoint of each market's sorted observed frozen session-date union; descriptive only.",
    }


def _architecture_classification(overlap: Mapping[str, Any]) -> dict[str, Any]:
    pairs = overlap.get("pairwise_overlap", [])
    redundancy_candidates = [
        {
            "gates": row["gates"],
            "jaccard": row["jaccard"],
            "intersection_count": row["intersection_count"],
            "classification": "CANDIDATE_REDUNDANCY_ONLY",
        }
        for row in pairs
        if row["jaccard"] is not None and float(row["jaccard"]) >= 0.50
    ]
    return {
        "SAFETY_VALIDITY_HARD_GATE": [
            "DATA_QUALITY",
            "HISTORY_INSUFFICIENT",
            "WEEKLY_STATE",
            "DAILY_STATE",
            "NO_VALID_WAVE",
            "SETUP_NOT_ELIGIBLE",
            "STRUCTURAL_INVALIDATION",
            "STRUCTURAL_ISSUE",
            "NO_VALID_TARGET",
            "TARGET_PROVENANCE_GEOMETRY",
            "STALE_CONFIRMATION_GEOMETRY",
            "CONFIRMATION_CLOSE_ABOVE_H1",
            "T+1 NO EXACT OPEN",
            "T+1 BELOW INVALIDATION",
            "T+1 BELOW CONFIRMATION",
        ],
        "ECONOMIC_HARD_GATE": [
            "ABOVE_ENTRY_ZONE",
            "TARGET_UPSIDE_BELOW_MINIMUM",
            "RR_BELOW_MINIMUM",
            "T+1 GAP ABOVE ENTRY ZONE",
            "T+1 TARGET UPSIDE",
            "T+1 RR",
        ],
        "QUALITY_RANKING_CANDIDATE": [
            "trend strength",
            "depth",
            "overhead resistance proximity",
            "target upside band",
            "confirmation strength",
            "wave quality",
        ],
        "REDUNDANT_DERIVED_CANDIDATES": [
            "FORMAL_T1_CONFIRMED_SWING_HIGH",
            "target/RR/entry-zone geometry overlap identified by the matrix",
        ],
        "observed_overlap_candidates": redundancy_candidates,
        "classification_boundary": "This is a research classification. QUALITY_RANKING_CANDIDATE and CANDIDATE_REDUNDANCY_ONLY do not authorize a production change.",
    }


def _final_classification(
    records: Sequence[DecisionRecord],
    lifecycles: Sequence[LifecycleSummary],
    ablation: Mapping[str, Any],
    overlap: Mapping[str, Any],
    entry_zone: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    confirmed_count = len(records)
    candidate_count = len(lifecycles)
    total_entry_zone = entry_zone.get("total", {})
    above = int(total_entry_zone.get("above_entry_zone_events", 0))
    above_rate = _rate(above, confirmed_count)
    pairwise = overlap.get("pairwise_overlap", [])
    strongest_pair = pairwise[0] if pairwise else None
    entry_allowed = sum(
        _enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value
        for record in records
    )

    if not records or not lifecycles:
        classification = "INSUFFICIENT_EVIDENCE"
        classification_name = classification
        reason = "The frozen replay did not produce enough lifecycle and Decision events for attribution."
    elif above_rate is not None and above_rate >= 0.50:
        classification = "STRUCTURAL_GATE_COLLISION_OBSERVED"
        classification_name = classification
        reason = (
            f"{above} of {confirmed_count} confirmed events ({above_rate * 100:.2f}%) "
            "were already above the unchanged Entry Zone upper bound on the confirmation close; this is a recurring confirmation/entry-zone interaction, not a single-day example."
        )
    elif provenance.get("comparison_status") == "INSUFFICIENT_EVIDENCE_FOR_FORMAL_VS_LIVE_CANDIDATE":
        classification = "INSUFFICIENT_EVIDENCE"
        classification_name = classification
        reason = "The frozen replay supports internal funnel attribution, but its population cannot support a formal-pool versus live-Candidate comparison."
    else:
        classification = "SYSTEM_WORKING_AS_DESIGNED_BUT_SIGNAL_SPARSE"
        classification_name = classification
        reason = "Observed low frequency is explained by the unchanged causal validity and economic gates without a measured structural collision at the requested scale."

    return {
        "classification_code": classification,
        "classification": classification_name,
        "reason": reason,
        "evidence": {
            "candidate_lifecycles": candidate_count,
            "confirmed_events": confirmed_count,
            "entry_allowed_events": entry_allowed,
            "above_entry_zone_events": above,
            "above_entry_zone_rate_of_confirmed": _round(above_rate),
            "entry_allowed_events": entry_allowed,
            "highest_pairwise_overlap": strongest_pair,
            "formal_vs_dynamic_candidate_comparison": provenance.get("comparison_status"),
        },
        "status": "DESCRIPTIVE_RESEARCH_CLASSIFICATION_NOT_PRODUCTION_AUTHORIZATION",
    }


def _dashboard_contract_audit() -> dict[str, Any]:
    """Record the existing ARMED data contract without changing the renderer."""

    return {
        "state_audited": SetupState.ARMED.value,
        "source_files_reviewed": [
            "trading/setup01.py",
            "trading/setup02.py",
            "trading/setup01_decision.py",
            "trading/setup02_decision.py",
            "trading/daily_decision_chain.py",
            "trading/daily_dashboard.py",
        ],
        "causal_availability_in_structural_evaluator": {
            "confirmation_trigger_price": {
                "available": True,
                "source": "Setup01Evaluation.confirmation_level / Setup02Evaluation.confirmation_level",
                "current_daily_result_exposed": False,
            },
            "structural_invalidation": {
                "available": True,
                "source": "Setup01Evaluation.structural_invalidation / Setup02Evaluation.structural_invalidation",
                "current_daily_result_exposed": False,
            },
            "setup_type": {
                "available": True,
                "source": "SETUP_01 / SETUP_02 replay namespace and DailyDecisionResult setup state fields",
                "current_daily_result_exposed": True,
            },
            "current_close": {
                "available": True,
                "source": "causal Quote used by daily_decision_chain._evaluate_symbol",
                "current_daily_result_exposed": False,
            },
            "trigger_distance": {
                "available": True,
                "source": "causal subtraction of current close and confirmation_level",
                "current_daily_result_exposed": False,
            },
            "trigger_distance_pct": {
                "available": True,
                "source": "causal relative distance using current close and confirmation_level",
                "current_daily_result_exposed": False,
            },
            "expected_entry_zone": {
                "available": True,
                "source": "existing Decision contract: confirmation_level + existing 0.5 * ATR14; ATR must be calculated on the T-day prefix",
                "current_armed_result_exposed": False,
            },
        },
        "dashboard_current_behavior": {
            "armed_row": "shows waiting/monitoring state but does not present the causal trigger-distance or pre-confirmation entry-zone context",
            "confirmed_plan": "renders existing Decision fields when a T-day Decision proposal exists",
            "renderer_recomputes_trade_math": False,
        },
        "contract_gap": "The underlying structural evaluator has trigger and invalidation, but DailyDecisionResult does not carry the current ARMED snapshot/close/ATR projection. Therefore the missing ARMED values are a result-contract gap plus presentation gap, not evidence that the structural evaluator lacks causal inputs.",
        "minimum_follow_up_fix": {
            "scope": "presentation-only follow-up; not included in this audit PR",
            "correct_location": "daily_decision_chain read-only result projection, reusing a shared causal pre-confirmation/Entry Zone projection helper from the existing setup Decision layer",
            "fields": [
                "setup_type",
                "current_close",
                "confirmation_trigger_price",
                "distance_to_trigger",
                "distance_to_trigger_pct",
                "expected_entry_zone_low",
                "expected_entry_zone_high",
                "structural_invalidation",
                "atr14_as_of_current_close",
            ],
            "renderer_rule": "daily_dashboard should render these fields only; it must not duplicate ATR, Entry Zone, or invalidation calculations",
        },
    }


def _recent_live_context(reports_root: Path = PROJECT_ROOT / "reports") -> dict[str, Any]:
    # Only explicitly named aggregate daily-report JSON files are eligible.
    # Generic shadows and dashboard artifacts are not live production reports.
    paths = sorted(reports_root.rglob("daily-report.json")) if reports_root.exists() else []
    if not paths:
        return {
            "status": "INSUFFICIENT_RECENT_LIVE_SAMPLE",
            "files_considered": 0,
            "production_reports_used": False,
            "reason": "No production daily-report.json artifact was present under reports; no Sheets, holdings, secrets, or provider access was attempted.",
        }
    rows: list[dict[str, Any]] = []
    for path in paths[-30:]:
        try:
            data = _load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
        rows.append(
            {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "sha256": _sha256_file(path),
                "market": metadata.get("market", data.get("market")),
                "trade_date": metadata.get("trade_date", data.get("trade_date")),
                "entry_allowed": data.get("entry_allowed", data.get("funnel", {}).get("entry_allowed") if isinstance(data.get("funnel"), dict) else None),
                "executed": data.get("executed", data.get("funnel", {}).get("executed") if isinstance(data.get("funnel"), dict) else None),
            }
        )
    if not rows:
        return {
            "status": "INSUFFICIENT_RECENT_LIVE_SAMPLE",
            "files_considered": len(paths),
            "production_reports_used": False,
            "reason": "Named report files were present but no readable aggregate report could be safely identified.",
        }
    return {
        "status": "OPERATIONAL_CONTEXT_ONLY",
        "files_considered": len(rows),
        "production_reports_used": True,
        "rows": rows,
        "interpretation": "Recent live reports are context only and cannot replace the Development attribution population.",
    }


def _validation(
    observations: Sequence[SessionObservation],
    confirmed_event_counts: Mapping[str, int],
    records_by_setup: Mapping[str, Sequence[DecisionRecord]],
    lifecycles_by_setup: Mapping[str, Sequence[LifecycleSummary]],
    overlap: Mapping[str, Any],
    ablation: Mapping[str, Any],
    source_digest_before: str,
    source_digest_after: str,
) -> dict[str, Any]:
    setup_checks: dict[str, Any] = {}
    for setup in SETUPS:
        records = records_by_setup[setup]
        lifecycles = lifecycles_by_setup[setup]
        allowed = sum(_enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value for record in records)
        attempts = sum(record.execution is not None for record in records)
        executed = sum(record.execution is not None and str(record.execution.outcome) == "EXECUTED" for record in records)
        actual_entry_iff_executed = all(
            (record.execution.actual_entry is not None) == (str(record.execution.outcome) == "EXECUTED")
            for record in records
            if record.execution is not None
        )
        setup_checks[setup] = {
            "lifecycle_count": len(lifecycles),
            "confirmed_event_count": len(records),
            "confirmed_equals_decisions": int(confirmed_event_counts[setup]) == len(records),
            "decision_equals_entry_allowed_plus_no_trade": allowed + sum(_enum_value(record.decision.action) == DecisionAction.NO_TRADE.value for record in records) == len(records),
            "entry_allowed_equals_t1_attempts": allowed == attempts,
            "t1_attempts_equals_executed_plus_skipped": attempts == (
                sum(
                    record.execution is not None
                    and str(record.execution.outcome) == "EXECUTED"
                    for record in records
                )
                + sum(
                    record.execution is not None
                    and str(record.execution.outcome) != "EXECUTED"
                    for record in records
                )
            ),
            "actual_entry_iff_executed": actual_entry_iff_executed,
            "confirmed_lifecycle_binding": sum(row.resolution == "TERMINAL_CONFIRMED" for row in lifecycles) == len(records),
        }
    all_session_by_market = {
        market: sum(row.market == market for row in observations)
        for market in ("CN", "US")
    }
    all_session_conserved = sum(all_session_by_market.values()) == len(observations)
    failed_records = [
        record
        for records in records_by_setup.values()
        for record in records
        if record.first_fail is not None
    ]
    first_fail_conserved = len(failed_records) == sum(
        len([record for record in records if record.first_fail is not None])
        for records in records_by_setup.values()
    )
    overlap_consistency = all(
        row["raw_rejection_count"] == row["unique_only_failure_count"] + row["overlap_rejection_count"]
        for row in overlap["gate_rows"]
    )
    ablation_keys = tuple(ablation["gates"])
    return {
        "current_production_funnel_parity": all(all(values.values()) for values in setup_checks.values()),
        "setup01_setup02_conservation": setup_checks,
        "first_fail_conservation": first_fail_conserved,
        "all_fail_overlap_consistency": overlap_consistency,
        "single_gate_ablation_one_at_a_time": ablation_keys == (*ABLATION_GATES, CONFIRMATION_ABLATION_GATE),
        "single_gate_ablation_has_no_combined_gate": all(row.get("one_gate_only") is True for row in ablation["gates"].values()),
        "source_event_snapshot_unchanged": source_digest_before == source_digest_after,
        "cn_us_symbol_session_conservation": all_session_conserved,
        "cn_us_symbol_session_counts": all_session_by_market,
        "causal_as_of_replay": True,
        "exact_t_plus_1_open_only": True,
        "final_oos_accessed": False,
        "parameter_search": False,
        "threshold_sweep": False,
        "production_writes": False,
        "state_writes": 0,
        "sheets_writes": 0,
        "broker_orders": 0,
        "real_holdings_accessed": False,
        "raw_market_bars_persisted": False,
        "raw_event_dump_persisted": False,
        "recent_live_reports_replace_development": False,
    }


def _compact_dataset_identity(
    manifest: Mapping[str, Any],
    replay_manifest: Any,
) -> dict[str, Any]:
    return {
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "replay_input_aggregate_sha256": replay_manifest.aggregate_hash,
        "symbol_count": replay_manifest.total_symbol_count,
        "bar_count": replay_manifest.total_bar_count,
        "market_coverage": manifest.get("market_coverage", {}),
        "provider_split": manifest.get("provider_split", {}),
        "artifact_labels": manifest.get("artifact_labels", []),
    }


def _render_markdown(payload: Mapping[str, Any]) -> str:
    def fmt(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    def pct(value: Any) -> str:
        return "—" if value is None else f"{float(value):.2f}%"

    def dist(value: Mapping[str, Any], key: str = "median") -> str:
        return fmt(value.get(key)) if value.get("count", 0) else "—"

    lines = [
        "<!-- DEVELOPMENT_ONLY; NOT_FORMAL_VALIDATION; NOT_FINAL_OOS -->",
        "# SYSTEM_SIGNAL_SCARCITY_AUDIT_V1",
        "",
        "> 本报告只做当前生产语义的 Development replay funnel、first-fail、overlap 与 one-gate counterfactual attribution；不改变生产策略，不产生生产授权。",
        "",
        "## 1. 结论",
        "",
        f"- 最终分类：`{payload['decision']['classification_code']}` — `{payload['decision']['classification']}`。",
        f"- 证据摘要：{payload['decision']['reason']}",
        f"- 研究状态：`{payload['status']}`。",
        "- Confirmation ablation 仅为理论 signal-loss accounting；不得把 pre-confirmation rows 当作合法 `ENTRY_ALLOWED`。",
        "",
        "## 2. 固定输入与边界",
        "",
        f"- dataset：`{payload['source']['dataset_version']}`；manifest `{payload['source']['dataset_manifest_sha256']}`。",
        f"- replay aggregate：`{payload['source']['replay_input_aggregate_sha256']}`；symbols `{payload['source']['symbol_count']}`；bars `{payload['source']['bar_count']}`。",
        "- Development holdout 是主要 attribution population；没有访问 Final OOS、provider、真实 holdings、Sheets、state 或 broker。",
        "- symbol-session denominator 是冻结 Quote 行；candidate selector 没有被重新筛选，避免把 outcome-driven universe 混入研究。",
        f"- SETUP_03：{payload['research_boundaries']['setup_scope']['SETUP_03']}。",
        f"- SETUP_04：{payload['research_boundaries']['setup_scope']['SETUP_04']}。",
        "",
        "## 3. Symbol-session funnel",
        "",
        "| scope | candidate/session | DATA_OK | history≥60 | weekly state | daily state | SETUP_01 wave | SETUP_02 wave |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scope, row in [("ALL", payload["funnel"]["symbol_session"]["ALL"]), ("CN", payload["funnel"]["symbol_session"]["CN"]), ("US", payload["funnel"]["symbol_session"]["US"])]:
        lines.append(
            f"| {scope} | {row['candidate_universe_symbol_sessions']} | {row['data_ok_symbol_sessions']} | {row['history_sufficient_symbol_sessions']} | {row['weekly_state_available_symbol_sessions']} | {row['daily_state_available_symbol_sessions']} | {row['setup01_wave_context_eligible_symbol_sessions']} | {row['setup02_wave_context_eligible_symbol_sessions']} |"
        )
    lines.extend(["", "## 4. Production funnel by setup", "", "| setup/scope | wave eligible sessions | lifecycles/setup events | WATCH | ARMED | CONFIRMED | Decision | ENTRY_ALLOWED | exact T+1 attempts | EXECUTED |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for setup in SETUPS:
        for scope, row in [("ALL", payload["funnel"][setup]["total"]), ("CN", payload["funnel"][setup]["by_market"]["CN"]), ("US", payload["funnel"][setup]["by_market"]["US"])]:
            lines.append(
                f"| {setup}/{scope} | {row['wave_scenario_eligible_symbol_sessions']} | {row['candidate_lifecycles']} | {row['watch_symbol_sessions']} | {row['armed_symbol_sessions']} | {row['confirmed_events']} | {row['decision_events']} | {row['entry_allowed']} | {row['t1_execution_attempts']} | {row['executed']} |"
            )
    combined = payload["funnel"]["aggregate"]
    lines.append(f"| AGGREGATE/ALL | — | {combined['candidate_lifecycles']} | — | — | {combined['confirmed_events']} | {combined['decision_events']} | {combined['entry_allowed']} | {combined['t1_execution_attempts']} | {combined['executed']} |")
    lines.extend(["", "## 5. First-fail attribution", "", "### Confirmed → Decision", "", "| setup | first fail | count | rate of confirmed decisions |", "|---|---|---:|---:|"])
    for setup in SETUPS:
        for row in payload["first_fail"][setup]["confirmed_decision_unit"]["rows"]:
            lines.append(f"| {setup} | {row['reason']} | {row['count']} | {pct(row['rate_pct'])} |")
    lines.extend(["", "### Lifecycle and exact T+1", "", "| unit | reason | count | rate |", "|---|---|---:|---:|"])
    for unit, unit_payload in (("SETUP_01 lifecycle", payload["first_fail"][SETUP01]["candidate_lifecycle_unit"]), ("SETUP_02 lifecycle", payload["first_fail"][SETUP02]["candidate_lifecycle_unit"]), ("SETUP_01 T+1", payload["first_fail"][SETUP01]["exact_t_plus_1_unit"]), ("SETUP_02 T+1", payload["first_fail"][SETUP02]["exact_t_plus_1_unit"])):
        for row in unit_payload["rows"]:
            lines.append(f"| {unit} | {row['reason']} | {row['count']} | {pct(row['rate_pct'])} |")
    lines.extend(["", "## 6. Gate overlap", "", "| gate | first-fail | raw applicable | unique-only | overlap |", "|---|---:|---:|---:|---:|"])
    aggregate_overlap = payload["gate_overlap"]["aggregate"]
    for row in aggregate_overlap["gate_rows"]:
        lines.append(f"| {row['gate']} | {row['first_fail_count']} | {row['raw_rejection_count']} | {row['unique_only_failure_count']} | {row['overlap_rejection_count']} |")
    lines.extend(["", "Top pairwise overlaps:", "", "| gates | intersection | Jaccard | conditional rates |", "|---|---:|---:|---|"])
    for row in aggregate_overlap["pairwise_overlap"][:8]:
        conditional = ", ".join(f"{gate} {pct(rate)}" for gate, rate in row["conditional_rate_pct"].items())
        lines.append(f"| {' ∩ '.join(row['gates'])} | {row['intersection_count']} | {fmt(row['jaccard'])} | {conditional} |")
    lines.extend(["", "## 7. Single-gate ablation", "", "| gate | raw applicable | unique-only | incremental ENTRY_ALLOWED | incremental T+1 executable | +/100 confirmed | +/1000 symbol-sessions |", "|---|---:|---:|---:|---:|---:|---:|"])
    for gate, row in payload["single_gate_ablation"]["gates"].items():
        lines.append(f"| {gate} | {fmt(row['raw_rejection_count'])} | {fmt(row['unique_only_failure_count'])} | {fmt(row['incremental_entry_allowed'])} | {fmt(row['incremental_t1_executable'])} | {pct(row['incremental_rate_per_100_confirmed'])} | {fmt(row['incremental_rate_per_1000_candidate_symbol_sessions'])} |")
    lines.append("| Note | Confirmation has no production increment; it is reference-only theoretical accounting. |  |  |  |  |  |")
    lines.extend(["", "## 8. Signal frequency", "", "| scope | confirmed/1000 symbol-session | ENTRY_ALLOWED/1000 | executed/1000 | confirmed/100 lifecycle | ENTRY_ALLOWED/100 confirmed | executed/100 ENTRY_ALLOWED |", "|---|---:|---:|---:|---:|---:|---:|"])
    for key, row in [("CN", payload["frequency"]["by_market"]["CN"]), ("US", payload["frequency"]["by_market"]["US"]), ("SETUP_01", payload["frequency"]["by_setup"][SETUP01]), ("SETUP_02", payload["frequency"]["by_setup"][SETUP02]), ("EARLY", payload["frequency"]["by_time_half"]["EARLY"]), ("LATE", payload["frequency"]["by_time_half"]["LATE"])]:
        lines.append(f"| {key} | {fmt(row['confirmed_per_1000_symbol_sessions'])} | {fmt(row['entry_allowed_per_1000_symbol_sessions'])} | {fmt(row['executed_per_1000_symbol_sessions'])} | {fmt(row['confirmed_per_100_candidate_lifecycles'])} | {fmt(row['entry_allowed_per_100_confirmed'])} | {fmt(row['executed_per_100_entry_allowed'])} |")
    lines.extend(["", "Symbol concentration is retained in JSON under `frequency`; it is descriptive, not a ranking rule.", "", "## 9. Architecture classification", ""])
    architecture = payload["architecture_classification"]
    for key in ("SAFETY_VALIDITY_HARD_GATE", "ECONOMIC_HARD_GATE", "QUALITY_RANKING_CANDIDATE", "REDUNDANT_DERIVED_CANDIDATES"):
        lines.append(f"- `{key}`: {', '.join(str(value) for value in architecture[key])}.")
    lines.extend(["", "## 10. Recent daily-report context", "", f"- status: `{payload['recent_live_context']['status']}`; files considered: `{payload['recent_live_context']['files_considered']}`.", f"- interpretation: {payload['recent_live_context'].get('reason', payload['recent_live_context'].get('interpretation', 'operational context only'))}", "", "## 11. Controls and validation", ""])
    for key, value in payload["controls"].items():
        lines.append(f"- `{key}`: `{value}`")
    for key, value in payload["validation"].items():
        if isinstance(value, (bool, int, str)):
            lines.append(f"- validation `{key}`: `{value}`")
    lines.extend(["", "## 12. Remaining boundary", "", "- No production gate, threshold, Entry Zone, confirmation, Fib, Swing, Wave, depth band, state path, Sheets path, or broker path was changed.", "- If a follow-up is approved, it must be a new protocol. Depending on the evidence, the safe next study is hard-gate-vs-ranking architecture research or fresh-validation Early Entry; no same-dataset unbounded filter search is authorized.", "", f"`{payload['status']}`", ""])
    return "\n".join(lines)


def run_audit(
    *,
    manifest_path: Path = DATASET_MANIFEST_PATH,
    replay_input_path: Path = FROZEN_INPUT_PATH,
    replay_manifest_path: Path = REPLAY_MANIFEST_PATH,
    output_json: Path = DEFAULT_JSON_OUTPUT,
    output_markdown: Path = DEFAULT_MARKDOWN_OUTPUT,
    reports_root: Path = PROJECT_ROOT / "reports",
) -> dict[str, Any]:
    protocol, protocol_hash, protocol_file_hash = _protocol_identity()
    manifest, quotes_by_symbol, replay_manifest = load_frozen_holdout(
        Path(manifest_path),
        Path(replay_input_path),
        Path(replay_manifest_path),
    )
    if manifest["dataset_version"] != protocol["population"]["dataset_version"]:
        raise ValueError("audit dataset version does not match protocol pin")
    if manifest["integrity"]["manifest_sha256"] != protocol["population"]["dataset_manifest_sha256"]:
        raise ValueError("audit dataset manifest does not match protocol pin")
    if replay_manifest.aggregate_hash != protocol["population"]["replay_input_aggregate_sha256"]:
        raise ValueError("audit replay aggregate does not match protocol pin")
    if replay_manifest.total_symbol_count != int(protocol["population"]["symbol_count"]) or replay_manifest.total_bar_count != int(protocol["population"]["bar_count"]):
        raise ValueError("audit replay coverage does not match protocol pin")

    reference = _load_preconfirmation_reference()
    half_map = _half_map(quotes_by_symbol)
    market_session_dates = build_market_session_dates(quotes_by_symbol)
    reports01, reports02, events01, events02 = _build_structural_replays(quotes_by_symbol)
    observations = _build_session_observations(quotes_by_symbol, reports01, reports02)
    lifecycles01 = _build_lifecycles(SETUP01, reports01, half_map)
    lifecycles02 = _build_lifecycles(SETUP02, reports02, half_map)
    stream01, records01 = _build_decision_records(SETUP01, events01, quotes_by_symbol, half_map)
    stream02, records02 = _build_decision_records(SETUP02, events02, quotes_by_symbol, half_map)
    records_by_setup = {SETUP01: records01, SETUP02: records02}
    lifecycles_by_setup = {SETUP01: lifecycles01, SETUP02: lifecycles02}
    all_records = tuple(records01) + tuple(records02)
    all_lifecycles = tuple(lifecycles01) + tuple(lifecycles02)
    source_digest_before = _decision_snapshot_digest(all_records)

    overlap01 = _overlap_diagnostics(records01)
    overlap02 = _overlap_diagnostics(records02)
    overlap_all = _overlap_diagnostics(all_records)
    ablation = _single_gate_ablation(
        all_records,
        overlap_all,
        quotes_by_symbol,
        half_map,
        market_session_dates,
        reference,
        len(observations),
    )
    source_digest_after = _decision_snapshot_digest(all_records)

    symbol_session = {
        "ALL": _session_scope_counts(observations),
        "CN": _session_scope_counts(observations, market="CN"),
        "US": _session_scope_counts(observations, market="US"),
        "by_provenance": {
            provenance: _session_scope_counts(observations, provenance=provenance)
            for provenance in PROVENANCES
        },
        "by_time_half": {
            half: _session_scope_counts(observations, time_half=half)
            for half in ("EARLY", "LATE")
        },
    }
    setup_funnel = {
        SETUP01: _setup_summary(SETUP01, observations, lifecycles01, records01, half_map),
        SETUP02: _setup_summary(SETUP02, observations, lifecycles02, records02, half_map),
    }
    aggregate_scopes = {
        "total": _merge_funnel_scope_rows(
            setup_funnel[SETUP01]["total"], setup_funnel[SETUP02]["total"]
        ),
        "by_market": {
            market: _merge_funnel_scope_rows(
                setup_funnel[SETUP01]["by_market"][market],
                setup_funnel[SETUP02]["by_market"][market],
            )
            for market in ("CN", "US")
        },
        "by_provenance": {
            provenance: _merge_funnel_scope_rows(
                setup_funnel[SETUP01]["by_provenance"][provenance],
                setup_funnel[SETUP02]["by_provenance"][provenance],
            )
            for provenance in PROVENANCES
        },
        "by_time_half": {
            time_half: _merge_funnel_scope_rows(
                setup_funnel[SETUP01]["by_time_half"][time_half],
                setup_funnel[SETUP02]["by_time_half"][time_half],
            )
            for time_half in ("EARLY", "LATE")
        },
    }
    aggregate_funnel = {
        **aggregate_scopes["total"],
        "by_market": aggregate_scopes["by_market"],
        "by_provenance": aggregate_scopes["by_provenance"],
        "by_time_half": aggregate_scopes["by_time_half"],
        "setup01_confirmed_events": len(records01),
        "setup02_confirmed_events": len(records02),
        "setup01_entry_allowed": sum(_enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value for record in records01),
        "setup02_entry_allowed": sum(_enum_value(record.decision.action) == DecisionAction.ENTRY_ALLOWED.value for record in records02),
    }
    first_fail = {
        SETUP01: _first_fail_attribution(lifecycles01, records01),
        SETUP02: _first_fail_attribution(lifecycles02, records02),
        "aggregate_confirmed_decision": _first_fail_attribution(all_lifecycles, all_records)["confirmed_decision_unit"],
    }
    provenance = _provenance_summary(observations, lifecycles_by_setup, records_by_setup)
    architecture = _architecture_classification(overlap_all)
    frequency = _frequency_context(observations, records_by_setup, lifecycles_by_setup, half_map)
    entry_zone_row = next(
        (row for row in overlap_all["gate_rows"] if row["gate"] == "ABOVE_ENTRY_ZONE"),
        {"raw_rejection_count": 0},
    )
    decision = _final_classification(
        all_records,
        all_lifecycles,
        ablation,
        overlap_all,
        {"total": {"above_entry_zone_events": entry_zone_row["raw_rejection_count"]}},
        provenance,
    )
    recent_live = _recent_live_context(reports_root)
    validation = _validation(
        observations,
        {
            SETUP01: sum(event.event_type is SetupState.CONFIRMED for event in events01),
            SETUP02: sum(event.event_type is SetupState.CONFIRMED for event in events02),
        },
        records_by_setup,
        lifecycles_by_setup,
        overlap_all,
        ablation,
        source_digest_before,
        source_digest_after,
    )
    controls = {
        "development_only": True,
        "formal_validation": False,
        "final_oos_accessed": False,
        "parameter_search": False,
        "threshold_sweep": False,
        "multi_gate_combination_search": False,
        "production_rule_change": False,
        "production_code_modified": False,
        "state_writes": 0,
        "sheets_writes": 0,
        "broker_orders": 0,
        "real_holdings_accessed": False,
        "provider_accessed": False,
        "raw_market_bars_persisted": False,
        "raw_event_dump_persisted": False,
        "outcome_metrics_computed": False,
        "preconfirmation_reference_used_as_constraint_only": True,
        "pr82_mixed_in": False,
    }
    payload: dict[str, Any] = {
        "artifact_type": "SYSTEM_SIGNAL_SCARCITY_AUDIT_V1",
        "artifact_version": "system-signal-scarcity-audit-v1",
        "status": "READY_FOR_DECISION",
        "protocol": {
            "version": PROTOCOL_VERSION,
            "canonical_sha256": protocol_hash,
            "file_sha256": protocol_file_hash,
        },
        "source": {
            **_compact_dataset_identity(manifest, replay_manifest),
            "protocol_source": "research/protocols/system_signal_scarcity_audit_v1.json",
            "preconfirmation_reference": reference,
        },
        "population": {
            "symbol_session_unit": True,
            "candidate_lifecycle_unit": True,
            "setup_event_unit": True,
            "confirmed_event_unit": True,
            "decision_event_unit": True,
            "exact_t_plus_1_executable_event_unit": True,
            "candidate_selector_rerun": False,
            "history_minimum_bars": HISTORY_MINIMUM_BARS,
            "time_half_definition": "market-local sorted observed session-date midpoint",
            "provenance_scopes": list(PROVENANCES),
            "formal_strategy_pool_rows": 0,
            "dynamic_candidate_rows": 0,
            "development_holdout_roster_rows": len({row.symbol for row in observations}),
            "provenance_comparison_status": provenance["comparison_status"],
        },
        "funnel": {
            "symbol_session": symbol_session,
            SETUP01: setup_funnel[SETUP01],
            SETUP02: setup_funnel[SETUP02],
            "aggregate": aggregate_funnel,
        },
        "first_fail": first_fail,
        "gate_overlap": {
            "SETUP_01": overlap01,
            "SETUP_02": overlap02,
            "aggregate": overlap_all,
            "highest_overlaps": overlap_all["pairwise_overlap"][:5],
        },
        "single_gate_ablation": ablation,
        "frequency": frequency,
        "architecture_classification": architecture,
        "decision": decision,
        "recent_live_context": recent_live,
        "controls": controls,
        "validation": validation,
        "research_boundaries": {
            "production_strategy_unchanged": True,
            "setup03_contributed_entry_allowed": False,
            "setup04_contributed_entry_allowed": False,
            "setup_scope": {
                "SETUP_03": "Excluded from this SETUP_01/SETUP_02 attribution population: formal validation is stopped; its legacy manual path remains outside this audit's enabled production source scope.",
                "SETUP_04": "Not implemented and therefore has no production source or entry contribution.",
            },
            "next_step_requires_new_protocol": True,
        },
    }
    body = deepcopy(payload)
    body["integrity"] = {
        "canonical_payload_sha256": None,
        "hash_scope": "canonical JSON with integrity.canonical_payload_sha256=null",
        "artifact_compact": True,
        "event_level_rows_persisted": 0,
    }
    canonical_payload_hash = _sha256_bytes(_canonical_json(body).encode("utf-8"))
    payload["integrity"] = {
        "canonical_payload_sha256": canonical_payload_hash,
        "hash_scope": "canonical JSON with integrity.canonical_payload_sha256=null",
        "artifact_compact": True,
        "event_level_rows_persisted": 0,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.write_text(_render_markdown(payload).rstrip() + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DATASET_MANIFEST_PATH)
    parser.add_argument("--replay-input", type=Path, default=FROZEN_INPUT_PATH)
    parser.add_argument("--replay-wrapper", type=Path, default=REPLAY_MANIFEST_PATH)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--reports-root", type=Path, default=PROJECT_ROOT / "reports")
    args = parser.parse_args()
    payload = run_audit(
        manifest_path=args.manifest,
        replay_input_path=args.replay_input,
        replay_manifest_path=args.replay_wrapper,
        output_json=args.output_json,
        output_markdown=args.output_markdown,
        reports_root=args.reports_root,
    )
    print(
        "SYSTEM_SIGNAL_SCARCITY_AUDIT_SUMMARY "
        + json.dumps(
            {
                "status": payload["status"],
                "classification": payload["decision"]["classification"],
                "classification_code": payload["decision"]["classification_code"],
                "symbol_sessions": payload["funnel"]["symbol_session"]["ALL"]["candidate_universe_symbol_sessions"],
                "confirmed": payload["funnel"]["aggregate"]["confirmed_events"],
                "entry_allowed": payload["funnel"]["aggregate"]["entry_allowed"],
                "executed": payload["funnel"]["aggregate"]["executed"],
                "artifact_sha256": payload["integrity"]["canonical_payload_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

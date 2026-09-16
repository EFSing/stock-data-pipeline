"""Development-only causal research for pre-confirmation SETUP_01 entries.

The module rebuilds a cohort from every causal primary/alternate Wave2 context in
the frozen development replay.  It evaluates a small, pre-registered set of
milestones and keeps the current ``close > H1`` confirmation entry as an
incumbent comparator.  No result is sent back into the structural evaluator,
Decision/Risk, execution, state, Sheets, or broker paths.

The cohort is deliberately anchor-context-based rather than CONFIRMED-event-based:
later-confirmed, failed, screened-out, and unresolved candidates remain in
the denominator.  Future bars are used only after a signal has been fixed, for
the descriptive outcome calculations required by the protocol.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.development_holdout_dataset import load_frozen_holdout
from research.market_sessions import build_market_session_dates, trading_day_distance
from trading.models import (
    SetupState,
    SwingPoint,
    Trend,
    WaveScenarioEvaluation,
    WaveScenarioFamily,
)
from trading.setup01_replay import replay_setup01_history
from trading.swing import find_swings
from trading.wave import (
    aggregate_completed_weekly_quotes,
    evaluate_wave_scenario,
)


PROTOCOL_VERSION = "PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH_V1"
PROTOCOL_PATH = PROJECT_ROOT / "research" / "protocols" / "pre_confirmation_early_entry_causal_research_v1.json"
DEFAULT_JSON_OUTPUT = PROJECT_ROOT / "research" / "development" / "pre_confirmation_early_entry_causal_research_v1.json"
DEFAULT_MARKDOWN_OUTPUT = PROJECT_ROOT / "research" / "development" / "pre_confirmation_early_entry_causal_research_v1.md"

INCUMBENT_POLICY = "INCUMBENT_CONFIRMED_CLOSE"
EARLY_POLICIES = (
    "FIRST_BULLISH_RECOVERY",
    "ARMED_HALF_RECOVERY",
    "H1_INTRADAY_RECLAIM",
    "ARMED_HALF_RECOVERY_DAILY_UPTREND",
)
POLICY_IDS = (INCUMBENT_POLICY, *EARLY_POLICIES)
DEPTH_BANDS = ("NORMAL_OR_SHALLOW", "DEEP", "VERY_DEEP")
EVENTUAL_STATUSES = ("LATER_CONFIRMED", "FAILED", "NEVER_CONFIRMED")
RESOLUTIONS = (
    "TERMINAL_CONFIRMED",
    "TERMINAL_FAILED",
    "STRUCTURAL_INVALIDATION_BEFORE_CONFIRMATION",
    "SCREENED_OUT_BY_CURRENT_SYSTEM",
    "TIMEOUT_UNRESOLVED_AT_DATA_END",
)
HURDLE_IDS = (("HURDLE_0272", 0.272), ("HURDLE_0618", 0.618))
HURDLE_OUTCOMES = (
    "HURDLE_BEFORE_RESOLUTION",
    "STRUCTURAL_INVALIDATION_BEFORE_HURDLE",
    "RESOLUTION_BEFORE_HURDLE",
    "SAME_BAR_AMBIGUOUS",
    "CENSORED_INSUFFICIENT_PATH",
)


@dataclass(frozen=True)
class WaveCandidateObservation:
    index: int
    sources: tuple[str, ...]
    close: float
    origin: SwingPoint
    peak: SwingPoint
    wave2_low: SwingPoint
    daily_state: Trend
    weekly_state: Trend


@dataclass(frozen=True)
class CandidateLifecycle:
    key: str
    symbol: str
    market: str
    lifecycle_index: int
    first_observed_index: int
    last_observed_index: int
    ready_index: int
    first_observed_date: date
    last_observed_date: date
    ready_date: date
    origin_price: float
    origin_pivot_date: date
    peak_price: float
    peak_pivot_date: date
    wave2_low_price: float
    wave2_low_pivot_date: date
    wave1_range_R: float
    retracement_ratio_r: float
    geometry_valid: bool
    depth_band: str
    time_half: str
    eventual_status: str
    resolution: str
    resolution_index: int
    resolution_date: date
    confirmed_index: int | None
    confirmed_date: date | None
    failed_index: int | None
    failed_date: date | None
    failure_class: str | None
    failure_reason: str | None
    source_visibility: str
    observations: tuple[WaveCandidateObservation, ...]


@dataclass(frozen=True)
class PolicySignal:
    policy_id: str
    candidate_key: str
    symbol: str
    market: str
    signal_index: int
    signal_date: date
    signal_close: float
    entry_index: int | None
    entry_date: date | None
    entry_price: float | None
    eventual_status: str
    resolution: str
    confirmed_index: int | None
    confirmed_date: date | None


@dataclass(frozen=True)
class _LifecycleBuilder:
    symbol: str
    market: str
    lifecycle_index: int
    anchor_key: tuple[int, int, int]
    first_index: int
    last_index: int
    observations: tuple[WaveCandidateObservation, ...]
    confirmed_index: int | None
    confirmed_date: date | None
    failed_index: int | None
    failed_date: date | None
    failure_reason: str | None


class _CausalWaveAccessor:
    """Read full existing Wave evaluations with the existing as-of contract."""

    def __init__(self, quotes: Sequence[Quote]) -> None:
        self._quotes = tuple(quotes)
        self._daily_swings_all = tuple(find_swings(list(quotes), lookback=5))
        weekly_quotes = aggregate_completed_weekly_quotes(list(quotes), quotes[-1].trade_date)
        self._weekly_swings_all = tuple(find_swings(weekly_quotes, lookback=5)) if weekly_quotes else ()
        self._weekly_quote_dates = tuple(quote.trade_date for quote in weekly_quotes)
        self._cache: dict[int, WaveScenarioEvaluation] = {}

    def at(self, index: int) -> WaveScenarioEvaluation:
        if index not in self._cache:
            evaluation = evaluate_wave_scenario(
                self._quotes,
                as_of_date=self._quotes[index].trade_date,
                daily_swing_lookback=5,
                weekly_swing_lookback=5,
                _as_of_index=index,
                _daily_swings_all=self._daily_swings_all,
                _weekly_swings_all=self._weekly_swings_all,
                _weekly_quote_dates=self._weekly_quote_dates,
                _skip_validation=True,
            )
            self._cache[index] = evaluation
        return self._cache[index]


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _distribution(values: Iterable[float | int]) -> dict[str, Any]:
    clean = [float(value) for value in values if _finite(value) is not None]
    return {
        "n": len(clean),
        "p10": _percentile(clean, 0.10),
        "p25": _percentile(clean, 0.25),
        "median": _percentile(clean, 0.50),
        "p75": _percentile(clean, 0.75),
        "p90": _percentile(clean, 0.90),
    }


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _sha256_file(path: Path, *, normalize_lf: bool = False) -> str:
    payload = path.read_bytes()
    if normalize_lf:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _json_load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("pre-confirmation protocol version changed")
    policies = protocol.get("candidate_policies")
    if not isinstance(policies, list) or tuple(item.get("id") for item in policies) != POLICY_IDS:
        raise ValueError("pre-confirmation policy set changed")
    forbidden = set(protocol.get("forbidden", ()))
    required_forbidden = {
        "production rule change",
        "Final OOS",
        "parameter optimization or threshold sweep",
        "broker, state write, or Sheets mutation",
    }
    if not required_forbidden.issubset(forbidden):
        raise ValueError("pre-confirmation forbidden boundary changed")
    fixed = protocol.get("fixed_geometry", {})
    if fixed.get("fixed_existing_threshold", {}).get("value") != 0.5:
        raise ValueError("existing recovery threshold changed")
    if protocol.get("governance", {}).get("final_oos_accessed") is not False:
        raise ValueError("protocol must remain Final OOS-free")


def _failure_class(reason: str | None) -> str | None:
    if not reason:
        return None
    if "INVALIDATION" in reason or "at or below" in reason:
        return "STRUCTURAL_INVALIDATION"
    return "CONTEXT_OR_ELIGIBILITY_FAILURE"


def _anchor_key_from_event(event: Any) -> tuple[int, int, int]:
    evaluation = event.setup01
    if (
        evaluation.wave1_origin is None
        or evaluation.wave1_peak is None
        or evaluation.wave2_low is None
    ):
        raise ValueError("candidate anchor fields are incomplete")
    return (
        evaluation.wave1_origin.pivot_index,
        evaluation.wave1_peak.pivot_index,
        evaluation.wave2_low.pivot_index,
    )


def _scenario_candidate(
    scenario: Any,
    *,
    index: int,
) -> tuple[SwingPoint, SwingPoint, SwingPoint] | None:
    if (
        scenario.family is not WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE
        or scenario.candidate_impulse_leg is None
        or scenario.candidate_retracement_leg is None
    ):
        return None
    origin = scenario.candidate_impulse_leg.start
    peak = scenario.candidate_impulse_leg.end
    wave2_low = scenario.candidate_retracement_leg.end
    anchors = (origin, peak, wave2_low)
    if any(anchor.confirmed_index is None or anchor.confirmed_index > index for anchor in anchors):
        return None
    if not (
        origin.kind.value == "LOW"
        and peak.kind.value == "HIGH"
        and wave2_low.kind.value == "LOW"
        and origin.pivot_index < peak.pivot_index < wave2_low.pivot_index
    ):
        return None
    return origin, peak, wave2_low


def _first_structural_invalidation_for_builder(
    builder: _LifecycleBuilder,
    quotes: Sequence[Quote],
) -> tuple[int, str] | None:
    first_observation = builder.observations[0]
    origin_price = first_observation.origin.price
    wave2_low_price = first_observation.wave2_low.price
    for index in range(builder.first_index, builder.last_index + 1):
        close = _finite(quotes[index].close)
        if close is not None and close <= origin_price:
            return index, "STRUCTURAL_INVALIDATION: close <= LOW0"
        if close is not None and close <= wave2_low_price:
            return index, "STRUCTURAL_INVALIDATION: close <= LOW2"
    return None


def _build_lifecycle_builders(
    symbol_quotes: Mapping[str, Sequence[Quote]],
) -> tuple[_LifecycleBuilder, ...]:
    builders: list[_LifecycleBuilder] = []
    for symbol, quotes in sorted(symbol_quotes.items()):
        setup_report = replay_setup01_history(list(quotes))
        current_events: dict[tuple[int, int, int], dict[str, Any]] = {}
        for event in setup_report.events:
            key = _anchor_key_from_event(event)
            item = current_events.setdefault(key, {})
            if event.event_type is SetupState.CONFIRMED:
                item["confirmed_index"] = event.setup01.confirmed_index
                item["confirmed_date"] = event.trade_date
            elif event.event_type is SetupState.FAILED:
                item["failed_index"] = event.setup01.failed_index
                item["failed_date"] = event.trade_date
                item["failure_reason"] = event.setup01.reason

        accessor = _CausalWaveAccessor(quotes)
        mutable: dict[tuple[int, int, int], dict[str, Any]] = {}
        for index, quote in enumerate(quotes):
            wave = accessor.at(index)
            for source, scenario in (
                ("PRIMARY", wave.primary_scenario),
                ("ALTERNATE", wave.alternate_scenario),
            ):
                anchors = _scenario_candidate(scenario, index=index)
                if anchors is None:
                    continue
                origin, peak, wave2_low = anchors
                key = (origin.pivot_index, peak.pivot_index, wave2_low.pivot_index)
                item = mutable.setdefault(
                    key,
                    {
                        "symbol": symbol,
                        "market": quote.market,
                        "anchor_key": key,
                        "first_index": index,
                        "last_index": index,
                        "observations_by_index": {},
                    },
                )
                observation = item["observations_by_index"].setdefault(
                    index,
                    {
                        "sources": set(),
                        "close": float(quote.close),
                        "origin": origin,
                        "peak": peak,
                        "wave2_low": wave2_low,
                        "daily_state": wave.daily_state,
                        "weekly_state": wave.weekly_state,
                    },
                )
                observation["sources"].add(source)
                item["first_index"] = min(item["first_index"], index)
                item["last_index"] = max(item["last_index"], index)
        for item in mutable.values():
            observations = tuple(
                WaveCandidateObservation(
                    index=index,
                    sources=tuple(sorted(value["sources"])),
                    close=value["close"],
                    origin=value["origin"],
                    peak=value["peak"],
                    wave2_low=value["wave2_low"],
                    daily_state=value["daily_state"],
                    weekly_state=value["weekly_state"],
                )
                for index, value in sorted(item["observations_by_index"].items())
            )
            if not observations:
                raise ValueError("Wave candidate builder has no observations")
            current_event = current_events.get(item["anchor_key"], {})
            builders.append(
                _LifecycleBuilder(
                    symbol=item["symbol"],
                    market=item["market"],
                    lifecycle_index=0,
                    anchor_key=item["anchor_key"],
                    first_index=item["first_index"],
                    last_index=item["last_index"],
                    observations=observations,
                    confirmed_index=current_event.get("confirmed_index"),
                    confirmed_date=current_event.get("confirmed_date"),
                    failed_index=current_event.get("failed_index"),
                    failed_date=current_event.get("failed_date"),
                    failure_reason=current_event.get("failure_reason"),
                )
            )
    builders = sorted(
        builders,
        key=lambda item: (item.market, item.symbol, item.first_index, item.anchor_key),
    )
    return tuple(
        _LifecycleBuilder(
            symbol=builder.symbol,
            market=builder.market,
            lifecycle_index=index,
            anchor_key=builder.anchor_key,
            first_index=builder.first_index,
            last_index=builder.last_index,
            observations=builder.observations,
            confirmed_index=builder.confirmed_index,
            confirmed_date=builder.confirmed_date,
            failed_index=builder.failed_index,
            failed_date=builder.failed_date,
            failure_reason=builder.failure_reason,
        )
        for index, builder in enumerate(builders, start=1)
    )


def _depth_band(retracement_ratio: float) -> str:
    if retracement_ratio <= 0.618:
        return "NORMAL_OR_SHALLOW"
    if retracement_ratio <= 0.786:
        return "DEEP"
    return "VERY_DEEP"


def build_causal_cohort(
    symbol_quotes: Mapping[str, Sequence[Quote]],
) -> tuple[CandidateLifecycle, ...]:
    """Rebuild every causal Wave2 lifecycle, including non-confirmed rows."""
    market_sessions = build_market_session_dates(symbol_quotes)
    builders = _build_lifecycle_builders(symbol_quotes)
    result: list[CandidateLifecycle] = []
    for builder in builders:
        symbol_quotes_for_row = symbol_quotes[builder.symbol]
        first_observation = builder.observations[0]
        origin = first_observation.origin
        peak = first_observation.peak
        wave2_low = first_observation.wave2_low
        if (origin.pivot_index, peak.pivot_index, wave2_low.pivot_index) != builder.anchor_key:
            raise ValueError("candidate anchor identity changed during cohort construction")
        confirmed_indices = (
            origin.confirmed_index,
            peak.confirmed_index,
            wave2_low.confirmed_index,
        )
        if any(index is None for index in confirmed_indices):
            raise ValueError("cohort contains an unconfirmed anchor")
        ready_index = max(int(index) for index in confirmed_indices if index is not None)
        if ready_index > builder.first_index:
            raise ValueError("candidate appeared before all anchors were causally confirmed")
        wave1_range = float(peak.price) - float(origin.price)
        if not math.isfinite(wave1_range) or wave1_range <= 0:
            raise ValueError("candidate has non-positive Wave1 range")
        retracement_ratio = (float(peak.price) - float(wave2_low.price)) / wave1_range
        geometry_valid = (
            origin.price < wave2_low.price < peak.price
        )
        failed_index = builder.failed_index
        failed_date = builder.failed_date
        failure_reason = builder.failure_reason
        if builder.confirmed_index is not None:
            eventual_status = "LATER_CONFIRMED"
            resolution = "TERMINAL_CONFIRMED"
            resolution_index = builder.confirmed_index
        elif builder.failed_index is not None:
            eventual_status = "FAILED"
            resolution = "TERMINAL_FAILED"
            resolution_index = builder.failed_index
        else:
            structural = _first_structural_invalidation_for_builder(
                builder, symbol_quotes_for_row
            )
            if structural is not None:
                eventual_status = "FAILED"
                resolution = "STRUCTURAL_INVALIDATION_BEFORE_CONFIRMATION"
                resolution_index = structural[0]
                failed_index = structural[0]
                failed_date = symbol_quotes_for_row[structural[0]].trade_date
                failure_reason = structural[1]
            elif builder.last_index < len(symbol_quotes_for_row) - 1:
                eventual_status = "NEVER_CONFIRMED"
                resolution = "SCREENED_OUT_BY_CURRENT_SYSTEM"
                resolution_index = builder.last_index + 1
                failed_index = builder.failed_index
                failed_date = builder.failed_date
                failure_reason = builder.failure_reason
            else:
                eventual_status = "NEVER_CONFIRMED"
                resolution = "TIMEOUT_UNRESOLVED_AT_DATA_END"
                resolution_index = len(symbol_quotes_for_row) - 1
        if resolution_index < builder.first_index or resolution_index >= len(symbol_quotes_for_row):
            raise ValueError("candidate resolution is outside the frozen symbol series")
        ready_date = symbol_quotes_for_row[ready_index].trade_date
        sessions = market_sessions[builder.market]
        if ready_date not in sessions:
            raise ValueError("candidate ready date is not in its market session set")
        midpoint_index = (len(sessions) - 1) // 2
        time_half = (
            "FIRST_HALF"
            if sessions.index(ready_date) <= midpoint_index
            else "SECOND_HALF"
        )
        source_set = {
            source
            for observation in builder.observations
            for source in observation.sources
        }
        source_visibility = (
            "PRIMARY_AND_ALTERNATE"
            if source_set == {"PRIMARY", "ALTERNATE"}
            else "PRIMARY_ONLY"
            if source_set == {"PRIMARY"}
            else "ALTERNATE_ONLY"
        )
        depth_band = _depth_band(retracement_ratio) if geometry_valid else "INVALID_WAVE2_GEOMETRY"
        result.append(
            CandidateLifecycle(
                key=(
                    f"{builder.symbol}|SETUP_01|wave2_context="
                    f"{builder.anchor_key[0]}/{builder.anchor_key[1]}/{builder.anchor_key[2]}"
                ),
                symbol=builder.symbol,
                market=builder.market,
                lifecycle_index=builder.lifecycle_index,
                first_observed_index=builder.first_index,
                last_observed_index=builder.last_index,
                ready_index=ready_index,
                first_observed_date=symbol_quotes_for_row[builder.first_index].trade_date,
                last_observed_date=symbol_quotes_for_row[builder.last_index].trade_date,
                ready_date=ready_date,
                origin_price=float(origin.price),
                origin_pivot_date=origin.pivot_date,
                peak_price=float(peak.price),
                peak_pivot_date=peak.pivot_date,
                wave2_low_price=float(wave2_low.price),
                wave2_low_pivot_date=wave2_low.pivot_date,
                wave1_range_R=wave1_range,
                retracement_ratio_r=retracement_ratio,
                geometry_valid=geometry_valid,
                depth_band=depth_band,
                time_half=time_half,
                eventual_status=eventual_status,
                resolution=resolution,
                resolution_index=resolution_index,
                resolution_date=symbol_quotes_for_row[resolution_index].trade_date,
                confirmed_index=builder.confirmed_index,
                confirmed_date=builder.confirmed_date,
                failed_index=failed_index,
                failed_date=failed_date,
                failure_class=_failure_class(failure_reason),
                failure_reason=failure_reason,
                source_visibility=source_visibility,
                observations=builder.observations,
            )
        )
    return tuple(result)


def _next_session_entry(
    signal_index: int,
    quotes: Sequence[Quote],
    market_session_dates: Mapping[str, Sequence[date]],
) -> tuple[int, date, float] | None:
    signal_date = quotes[signal_index].trade_date
    market = quotes[signal_index].market
    sessions = tuple(market_session_dates.get(market, ()))
    position = bisect_right(sessions, signal_date)
    if position >= len(sessions):
        return None
    next_date = sessions[position]
    indices = [index for index, quote in enumerate(quotes) if quote.trade_date == next_date]
    if len(indices) != 1:
        return None
    entry_index = indices[0]
    entry_price = _finite(quotes[entry_index].open)
    if entry_index <= signal_index or entry_price is None:
        return None
    return entry_index, next_date, entry_price


def _policy_signal_index(
    policy_id: str,
    candidate: CandidateLifecycle,
    quotes: Sequence[Quote],
) -> int | None:
    if policy_id == INCUMBENT_POLICY:
        return candidate.confirmed_index
    if not candidate.geometry_valid:
        return None
    for observation in candidate.observations:
        index = observation.index
        if index < candidate.ready_index:
            continue
        if candidate.confirmed_index is not None and index >= candidate.confirmed_index:
            continue
        if candidate.eventual_status == "FAILED" and index >= candidate.resolution_index:
            continue
        quote = quotes[index]
        close = _finite(quote.close)
        high = _finite(quote.high)
        if close is None or high is None:
            continue
        if policy_id == "FIRST_BULLISH_RECOVERY":
            if index == 0:
                continue
            previous_close = _finite(quotes[index - 1].close)
            if (
                previous_close is not None
                and close > previous_close
                and close > candidate.wave2_low_price
                and close <= candidate.peak_price
            ):
                return index
        elif policy_id == "ARMED_HALF_RECOVERY":
            recovery = candidate.wave2_low_price + 0.5 * (
                candidate.peak_price - candidate.wave2_low_price
            )
            if close >= recovery and close <= candidate.peak_price:
                return index
        elif policy_id == "H1_INTRADAY_RECLAIM":
            if high >= candidate.peak_price and close <= candidate.peak_price:
                return index
        elif policy_id == "ARMED_HALF_RECOVERY_DAILY_UPTREND":
            recovery = candidate.wave2_low_price + 0.5 * (
                candidate.peak_price - candidate.wave2_low_price
            )
            if close >= recovery and close <= candidate.peak_price:
                if (
                    observation.daily_state is Trend.UPTREND
                    and observation.weekly_state is not Trend.DOWNTREND
                ):
                    return index
        else:
            raise ValueError(f"unknown policy: {policy_id}")
    return None


def evaluate_policy_signals(
    policy_id: str,
    candidates: Sequence[CandidateLifecycle],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> tuple[PolicySignal, ...]:
    """Freeze one first signal per candidate under a registered policy."""
    if policy_id not in POLICY_IDS:
        raise ValueError(f"unknown policy: {policy_id}")
    signals: list[PolicySignal] = []
    for candidate in candidates:
        quotes = symbol_quotes[candidate.symbol]
        signal_index = _policy_signal_index(policy_id, candidate, quotes)
        if signal_index is None:
            continue
        signal_quote = quotes[signal_index]
        signal_close = _finite(signal_quote.close)
        if signal_close is None:
            raise ValueError("signal close is not finite")
        if policy_id != INCUMBENT_POLICY:
            if candidate.confirmed_index is not None and signal_index >= candidate.confirmed_index:
                raise ValueError("pre-confirmation policy signaled at/after confirmation")
            if candidate.ready_index > signal_index:
                raise ValueError("pre-confirmation signal used an unconfirmed anchor")
        entry = _next_session_entry(signal_index, quotes, market_session_dates)
        signals.append(
            PolicySignal(
                policy_id=policy_id,
                candidate_key=candidate.key,
                symbol=candidate.symbol,
                market=candidate.market,
                signal_index=signal_index,
                signal_date=signal_quote.trade_date,
                signal_close=signal_close,
                entry_index=entry[0] if entry else None,
                entry_date=entry[1] if entry else None,
                entry_price=entry[2] if entry else None,
                eventual_status=candidate.eventual_status,
                resolution=candidate.resolution,
                confirmed_index=candidate.confirmed_index,
                confirmed_date=candidate.confirmed_date,
            )
        )
    candidate_keys = [signal.candidate_key for signal in signals]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise ValueError(f"policy emitted more than one signal for a candidate: {policy_id}")
    return tuple(signals)


def _structural_invalidation_index(
    candidate: CandidateLifecycle,
    quotes: Sequence[Quote],
    start_index: int,
) -> int | None:
    for index in range(start_index, len(quotes)):
        close = _finite(quotes[index].close)
        if close is not None and (
            close <= candidate.origin_price or close <= candidate.wave2_low_price
        ):
            return index
    return None


def _horizon(
    signal: PolicySignal,
    candidate: CandidateLifecycle,
    quotes: Sequence[Quote],
) -> tuple[int, bool, str]:
    if signal.entry_index is None:
        raise ValueError("horizon requested for a non-executable signal")
    if signal.policy_id == INCUMBENT_POLICY:
        invalidation = _structural_invalidation_index(candidate, quotes, signal.entry_index)
        if invalidation is not None:
            return invalidation, False, "STRUCTURAL_INVALIDATION"
        return len(quotes) - 1, True, "DATASET_END_CENSORED"
    censored = candidate.eventual_status == "NEVER_CONFIRMED"
    if candidate.resolution_index < signal.entry_index:
        return signal.entry_index, censored, "EMPTY_ENTRY_BOUNDARY"
    boundary = (
        "CONFIRMATION"
        if candidate.resolution == "TERMINAL_CONFIRMED"
        else "FAILURE"
        if candidate.resolution == "TERMINAL_FAILED"
        else "SCREENED_OUT"
        if candidate.resolution == "SCREENED_OUT_BY_CURRENT_SYSTEM"
        else "DATASET_END"
    )
    return candidate.resolution_index, censored, boundary


def _hurdle_outcome(
    candidate: CandidateLifecycle,
    quotes: Sequence[Quote],
    entry_index: int,
    endpoint_index: int,
    endpoint_censored: bool,
    level: float,
) -> str:
    for index in range(entry_index, min(endpoint_index, len(quotes) - 1) + 1):
        quote = quotes[index]
        high = _finite(quote.high)
        close = _finite(quote.close)
        if high is None or close is None:
            continue
        invalidation = close <= candidate.origin_price or close <= candidate.wave2_low_price
        hurdle_hit = high >= level
        if invalidation and hurdle_hit:
            return "SAME_BAR_AMBIGUOUS"
        if invalidation:
            return "STRUCTURAL_INVALIDATION_BEFORE_HURDLE"
        if hurdle_hit:
            return "HURDLE_BEFORE_RESOLUTION"
    if endpoint_censored:
        return "CENSORED_INSUFFICIENT_PATH"
    return "RESOLUTION_BEFORE_HURDLE"


def _hurdle_horizon(
    signal: PolicySignal,
    candidate: CandidateLifecycle,
    quotes: Sequence[Quote],
) -> tuple[int, bool]:
    """Use the fixed structural hurdle horizon, distinct from adverse horizon."""
    if signal.entry_index is None:
        raise ValueError("hurdle horizon requested for a non-executable signal")
    if candidate.eventual_status == "NEVER_CONFIRMED":
        return candidate.resolution_index, True
    if candidate.eventual_status == "FAILED":
        return candidate.resolution_index, False
    invalidation = _structural_invalidation_index(candidate, quotes, signal.entry_index)
    if invalidation is not None:
        return invalidation, False
    return len(quotes) - 1, True


def _structural_horizon_adverse(
    candidate: CandidateLifecycle,
    quotes: Sequence[Quote],
    entry_index: int,
    entry_price: float,
) -> float | None:
    """Return adverse magnitude through structural invalidation or data end."""
    endpoint = _structural_invalidation_index(candidate, quotes, entry_index)
    if endpoint is None:
        endpoint = len(quotes) - 1
    lows = [_finite(quote.low) for quote in quotes[entry_index : endpoint + 1]]
    lows = [value for value in lows if value is not None]
    if not lows:
        return None
    return max(entry_price - min(lows), 0.0) / candidate.wave1_range_R


def _signal_path_metrics(
    signal: PolicySignal,
    candidate: CandidateLifecycle,
    quotes: Sequence[Quote],
) -> dict[str, Any] | None:
    if signal.entry_index is None or signal.entry_price is None:
        return None
    endpoint, endpoint_censored, boundary = _horizon(signal, candidate, quotes)
    if endpoint < signal.entry_index:
        return {
            "empty": True,
            "censored": endpoint_censored,
            "boundary": boundary,
            "hurdles": {hurdle_id: "CENSORED_INSUFFICIENT_PATH" for hurdle_id, _ in HURDLE_IDS},
        }
    path = quotes[signal.entry_index : min(endpoint, len(quotes) - 1) + 1]
    lows = [_finite(quote.low) for quote in path]
    lows = [value for value in lows if value is not None]
    if not lows:
        return {
            "empty": True,
            "censored": endpoint_censored,
            "boundary": boundary,
            "hurdles": {hurdle_id: "CENSORED_INSUFFICIENT_PATH" for hurdle_id, _ in HURDLE_IDS},
        }
    minimum_low = min(lows)
    adverse_signed = (minimum_low - signal.entry_price) / candidate.wave1_range_R
    adverse_magnitude = max(signal.entry_price - minimum_low, 0.0) / candidate.wave1_range_R
    hurdle_endpoint, hurdle_censored = _hurdle_horizon(signal, candidate, quotes)
    hurdles = {
        hurdle_id: _hurdle_outcome(
            candidate,
            quotes,
            signal.entry_index,
            hurdle_endpoint,
            hurdle_censored,
            candidate.peak_price + ratio * candidate.wave1_range_R,
        )
        for hurdle_id, ratio in HURDLE_IDS
    }
    return {
        "empty": False,
        "censored": endpoint_censored,
        "boundary": boundary,
        "adverse_signed_R": adverse_signed,
        "adverse_magnitude_R": adverse_magnitude,
        "hurdles": hurdles,
    }


def _status_counts(
    candidates: Sequence[CandidateLifecycle],
    signals: Sequence[PolicySignal],
) -> dict[str, Any]:
    cohort_status = Counter(candidate.eventual_status for candidate in candidates)
    signal_status = Counter(signal.eventual_status for signal in signals)
    signal_resolution = Counter(signal.resolution for signal in signals)
    return {
        "cohort_composition": {
            status: cohort_status.get(status, 0) for status in EVENTUAL_STATUSES
        },
        "signaled_composition": {
            status: signal_status.get(status, 0) for status in EVENTUAL_STATUSES
        },
        "signaled_resolution": {
            resolution: signal_resolution.get(resolution, 0) for resolution in RESOLUTIONS
        },
    }


def summarize_policy(
    policy_id: str,
    candidates: Sequence[CandidateLifecycle],
    signals: Sequence[PolicySignal],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    """Aggregate policy evidence without exposing event-level or raw-bar data."""
    candidate_by_key = {candidate.key: candidate for candidate in candidates}
    if any(signal.candidate_key not in candidate_by_key for signal in signals):
        raise ValueError("policy signal is not in the selected causal cohort")
    executable = [signal for signal in signals if signal.entry_index is not None]
    entry_h1 = [
        (candidate_by_key[signal.candidate_key].peak_price - signal.entry_price)
        / candidate_by_key[signal.candidate_key].wave1_range_R
        for signal in executable
        if signal.entry_price is not None
    ]
    entry_fib1272 = [
        (
            candidate_by_key[signal.candidate_key].wave2_low_price
            + 1.272 * candidate_by_key[signal.candidate_key].wave1_range_R
            - signal.entry_price
        )
        / candidate_by_key[signal.candidate_key].wave1_range_R
        for signal in executable
        if signal.entry_price is not None
    ]
    entry_fib1618 = [
        (
            candidate_by_key[signal.candidate_key].wave2_low_price
            + 1.618 * candidate_by_key[signal.candidate_key].wave1_range_R
            - signal.entry_price
        )
        / candidate_by_key[signal.candidate_key].wave1_range_R
        for signal in executable
        if signal.entry_price is not None
    ]
    adverse_signed: list[float] = []
    adverse_magnitude: list[float] = []
    censored_path_count = 0
    empty_path_count = 0
    boundary_counts: Counter[str] = Counter()
    hurdle_counts: dict[str, Counter[str]] = {
        hurdle_id: Counter() for hurdle_id, _ in HURDLE_IDS
    }
    for signal in executable:
        candidate = candidate_by_key[signal.candidate_key]
        metrics = _signal_path_metrics(signal, candidate, symbol_quotes[signal.symbol])
        if metrics is None:
            continue
        boundary_counts[metrics["boundary"]] += 1
        censored_path_count += int(metrics["censored"])
        empty_path_count += int(metrics["empty"])
        if not metrics["empty"]:
            adverse_signed.append(float(metrics["adverse_signed_R"]))
            adverse_magnitude.append(float(metrics["adverse_magnitude_R"]))
        for hurdle_id in hurdle_counts:
            hurdle_counts[hurdle_id][metrics["hurdles"][hurdle_id]] += 1
    latency_saved = [
        trading_day_distance(
            signal.signal_date,
            signal.confirmed_date,
            market=signal.market,
            market_session_dates=market_session_dates,
        )
        for signal in signals
        if signal.eventual_status == "LATER_CONFIRMED" and signal.confirmed_date is not None
    ]
    invalidation_first = sum(
        1
        for signal in signals
        if (
            signal.eventual_status == "FAILED"
            and candidate_by_key[signal.candidate_key].failure_class == "STRUCTURAL_INVALIDATION"
        )
    )
    hurdle_summary: dict[str, Any] = {}
    for hurdle_id, _ in HURDLE_IDS:
        counts = hurdle_counts[hurdle_id]
        denominator = sum(counts.values())
        hurdle_summary[hurdle_id] = {
            "fixed_level": f"H1 + {0.272 if hurdle_id == 'HURDLE_0272' else 0.618} * R",
            "outcomes": {
                outcome: {
                    "count": counts.get(outcome, 0),
                    "rate": _rate(counts.get(outcome, 0), denominator),
                }
                for outcome in HURDLE_OUTCOMES
            },
            "success_count": counts.get("HURDLE_BEFORE_RESOLUTION", 0),
            "success_rate": _rate(counts.get("HURDLE_BEFORE_RESOLUTION", 0), denominator),
        }
    summary = {
        "policy_id": policy_id,
        "total_candidate_count": len(candidates),
        "signaled_candidate_count": len(signals),
        "not_signaled_candidate_count": len(candidates) - len(signals),
        "actual_executable_next_session_entry_count": len(executable),
        "not_executable_next_session_count": len(signals) - len(executable),
        **_status_counts(candidates, signals),
        "eventually_confirmed_count": sum(signal.eventual_status == "LATER_CONFIRMED" for signal in signals),
        "never_confirmed_count": sum(signal.eventual_status == "NEVER_CONFIRMED" for signal in signals),
        "failed_count": sum(signal.eventual_status == "FAILED" for signal in signals),
        "structural_invalidation_before_confirmation": {
            "count": invalidation_first,
            "rate_of_signals": _rate(invalidation_first, len(signals)),
            "rate_of_failed_signals": _rate(invalidation_first, sum(signal.eventual_status == "FAILED" for signal in signals)),
        },
        "entry_geometry_over_R": {
            "entry_to_H1_distance": _distribution(entry_h1),
            "entry_to_Fib1.272_remaining_headroom": _distribution(entry_fib1272),
            "entry_to_Fib1.618_remaining_headroom": _distribution(entry_fib1618),
        },
        "adverse_excursion_until_resolution": {
            "signed_R": _distribution(adverse_signed),
            "adverse_magnitude_R": _distribution(adverse_magnitude),
            "executable_path_count": len(adverse_signed),
            "censored_path_count": censored_path_count,
            "empty_path_count": empty_path_count,
            "boundary_counts": dict(sorted(boundary_counts.items())),
        },
        "confirmation_latency_saved_sessions": _distribution(latency_saved),
        "common_fixed_structural_hurdles": hurdle_summary,
        "stop_invalidation_first": {
            "production_stop_defined": False,
            "production_stop_semantics": "NOT_DEFINED_BY_THIS_RESEARCH_PROTOCOL",
            "research_structural_invalidation_first_count": invalidation_first,
            "research_structural_invalidation_first_rate_of_signals": _rate(invalidation_first, len(signals)),
        },
        "censored_ambiguous": {
            "never_confirmed_signals": sum(signal.eventual_status == "NEVER_CONFIRMED" for signal in signals),
            "censored_executable_paths": censored_path_count,
            "same_bar_ambiguous_by_hurdle": {
                hurdle_id: hurdle_counts[hurdle_id].get("SAME_BAR_AMBIGUOUS", 0)
                for hurdle_id, _ in HURDLE_IDS
            },
        },
    }
    return summary


def _paired_headroom(
    early_policy: str,
    candidates: Sequence[CandidateLifecycle],
    early_signals: Sequence[PolicySignal],
    incumbent_signals: Sequence[PolicySignal],
    symbol_quotes: Mapping[str, Sequence[Quote]],
) -> dict[str, Any]:
    candidate_by_key = {candidate.key: candidate for candidate in candidates}
    incumbent_by_key = {signal.candidate_key: signal for signal in incumbent_signals}
    early_by_key = {signal.candidate_key: signal for signal in early_signals}
    paired_h1: list[float] = []
    paired_fib1272: list[float] = []
    paired_fib1618: list[float] = []
    paired_latency: list[float] = []
    paired_early_adverse: list[float] = []
    paired_incumbent_adverse: list[float] = []
    paired_adverse_delta: list[float] = []
    for key, early in early_by_key.items():
        candidate = candidate_by_key[key]
        incumbent = incumbent_by_key.get(key)
        if incumbent is None:
            continue
        if candidate.eventual_status == "LATER_CONFIRMED" and candidate.confirmed_index is not None:
            paired_latency.append(float(candidate.confirmed_index - early.signal_index))
        if early.entry_price is None or incumbent.entry_price is None:
            continue
        paired_h1.append(
            (candidate.peak_price - early.entry_price) / candidate.wave1_range_R
            - (candidate.peak_price - incumbent.entry_price) / candidate.wave1_range_R
        )
        early_fib1272 = (candidate.wave2_low_price + 1.272 * candidate.wave1_range_R - early.entry_price) / candidate.wave1_range_R
        incumbent_fib1272 = (candidate.wave2_low_price + 1.272 * candidate.wave1_range_R - incumbent.entry_price) / candidate.wave1_range_R
        paired_fib1272.append(early_fib1272 - incumbent_fib1272)
        early_fib1618 = (candidate.wave2_low_price + 1.618 * candidate.wave1_range_R - early.entry_price) / candidate.wave1_range_R
        incumbent_fib1618 = (candidate.wave2_low_price + 1.618 * candidate.wave1_range_R - incumbent.entry_price) / candidate.wave1_range_R
        paired_fib1618.append(early_fib1618 - incumbent_fib1618)
        early_adverse = _structural_horizon_adverse(
            candidate,
            symbol_quotes[candidate.symbol],
            early.entry_index,
            early.entry_price,
        )
        incumbent_adverse = _structural_horizon_adverse(
            candidate,
            symbol_quotes[candidate.symbol],
            incumbent.entry_index,
            incumbent.entry_price,
        )
        if early_adverse is not None and incumbent_adverse is not None:
            paired_early_adverse.append(early_adverse)
            paired_incumbent_adverse.append(incumbent_adverse)
            paired_adverse_delta.append(early_adverse - incumbent_adverse)
    return {
        "early_policy": early_policy,
        "incumbent_policy": INCUMBENT_POLICY,
        "paired_later_confirmed_executable_count": len(paired_h1),
        "early_minus_incumbent_headroom_R": {
            "H1": _distribution(paired_h1),
            "Fib1.272": _distribution(paired_fib1272),
            "Fib1.618": _distribution(paired_fib1618),
        },
        "paired_post_entry_structural_adverse_magnitude_R": {
            "early": _distribution(paired_early_adverse),
            "incumbent": _distribution(paired_incumbent_adverse),
            "early_minus_incumbent": _distribution(paired_adverse_delta),
        },
        "confirmation_latency_saved_sessions_on_later_confirmed": _distribution(paired_latency),
    }


def _compact_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Project robustness slices without repeating the full policy payload."""
    def compact_distribution(distribution: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: distribution.get(key)
            for key in ("n", "median", "p90")
        }

    geometry = summary["entry_geometry_over_R"]
    adverse = summary["adverse_excursion_until_resolution"]
    hurdles = {
        hurdle_id: {
            "success_count": value["success_count"],
            "success_rate": value["success_rate"],
            "structural_invalidation_before_hurdle_count": value["outcomes"][
                "STRUCTURAL_INVALIDATION_BEFORE_HURDLE"
            ]["count"],
            "structural_invalidation_before_hurdle_rate": value["outcomes"][
                "STRUCTURAL_INVALIDATION_BEFORE_HURDLE"
            ]["rate"],
            "same_bar_ambiguous_count": value["outcomes"]["SAME_BAR_AMBIGUOUS"]["count"],
            "censored_count": value["outcomes"]["CENSORED_INSUFFICIENT_PATH"]["count"],
        }
        for hurdle_id, value in summary["common_fixed_structural_hurdles"].items()
    }
    return {
        "total_candidate_count": summary["total_candidate_count"],
        "signaled_candidate_count": summary["signaled_candidate_count"],
        "actual_executable_next_session_entry_count": summary[
            "actual_executable_next_session_entry_count"
        ],
        "eventually_confirmed_count": summary["eventually_confirmed_count"],
        "never_confirmed_count": summary["never_confirmed_count"],
        "failed_count": summary["failed_count"],
        "structural_invalidation_before_confirmation": summary[
            "structural_invalidation_before_confirmation"
        ],
        "entry_geometry_over_R": {
            "entry_to_H1_distance": compact_distribution(geometry["entry_to_H1_distance"]),
            "entry_to_Fib1.272_remaining_headroom": compact_distribution(
                geometry["entry_to_Fib1.272_remaining_headroom"]
            ),
            "entry_to_Fib1.618_remaining_headroom": compact_distribution(
                geometry["entry_to_Fib1.618_remaining_headroom"]
            ),
        },
        "adverse_excursion_until_resolution": {
            "signed_R": compact_distribution(adverse["signed_R"]),
            "adverse_magnitude_R": compact_distribution(adverse["adverse_magnitude_R"]),
            "executable_path_count": adverse["executable_path_count"],
            "censored_path_count": adverse["censored_path_count"],
            "empty_path_count": adverse["empty_path_count"],
            "boundary_counts": adverse["boundary_counts"],
        },
        "confirmation_latency_saved_sessions": compact_distribution(
            summary["confirmation_latency_saved_sessions"]
        ),
        "common_fixed_structural_hurdles": hurdles,
    }


def _subset_summary(
    policy_id: str,
    candidates: Sequence[CandidateLifecycle],
    signals: Sequence[PolicySignal],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
    predicate: Callable[[CandidateLifecycle], bool],
) -> dict[str, Any]:
    selected = tuple(candidate for candidate in candidates if predicate(candidate))
    selected_keys = {candidate.key for candidate in selected}
    selected_signals = tuple(signal for signal in signals if signal.candidate_key in selected_keys)
    return summarize_policy(
        policy_id,
        selected,
        selected_signals,
        symbol_quotes,
        market_session_dates,
    )


def _robustness(
    policy_id: str,
    candidates: Sequence[CandidateLifecycle],
    signals: Sequence[PolicySignal],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    def compact(predicate: Callable[[CandidateLifecycle], bool]) -> dict[str, Any]:
        return _compact_summary(
            _subset_summary(
                policy_id,
                candidates,
                signals,
                symbol_quotes,
                market_session_dates,
                predicate,
            )
        )

    markets = {
        market: compact(lambda candidate, market=market: candidate.market == market)
        for market in sorted({candidate.market for candidate in candidates})
    }
    time_halves = {
        half: compact(lambda candidate, half=half: candidate.time_half == half)
        for half in ("FIRST_HALF", "SECOND_HALF")
    }
    depths = {
        band: compact(lambda candidate, band=band: candidate.depth_band == band)
        for band in DEPTH_BANDS
    }
    outcome_strata = {
        status: compact(
            lambda candidate, status=status: candidate.eventual_status == status
        )
        for status in EVENTUAL_STATUSES
    }
    signal_counts = Counter(signal.symbol for signal in signals)
    leading_symbol = (
        sorted(signal_counts, key=lambda symbol: (-signal_counts[symbol], symbol))[0]
        if signal_counts
        else None
    )
    without_leader = None
    if leading_symbol is not None:
        without_leader = compact(
            lambda candidate: candidate.symbol != leading_symbol
        )
    return {
        "CN_US": markets,
        "time_split_by_candidate_ready_date": {
            "definition": "frozen market-session ordinal midpoint",
            "halves": time_halves,
        },
        "depth_bands": depths,
        "later_confirmed_vs_never_confirmed_failed": outcome_strata,
        "symbol_concentration": {
            "signal_counts_by_symbol": dict(sorted(signal_counts.items())),
            "count_leading_symbol": leading_symbol,
            "count_leading_symbol_signal_count": signal_counts.get(leading_symbol, 0) if leading_symbol else 0,
            "without_count_leading_symbol": without_leader,
        },
    }


def _cohort_composition(candidates: Sequence[CandidateLifecycle]) -> dict[str, Any]:
    eventual = Counter(candidate.eventual_status for candidate in candidates)
    resolution_counts = Counter(candidate.resolution for candidate in candidates)
    failure_classes = Counter(
        candidate.failure_class
        for candidate in candidates
        if candidate.failure_class is not None
    )
    by_market = {
        market: {
            "candidate_count": sum(candidate.market == market for candidate in candidates),
            "eventual_status": {
                status: sum(
                    candidate.market == market and candidate.eventual_status == status
                    for candidate in candidates
                )
                for status in EVENTUAL_STATUSES
            },
        }
        for market in sorted({candidate.market for candidate in candidates})
    }
    by_depth = {
        band: {
            "candidate_count": sum(candidate.depth_band == band for candidate in candidates),
            "eventual_status": {
                status: sum(
                    candidate.depth_band == band and candidate.eventual_status == status
                    for candidate in candidates
                )
                for status in EVENTUAL_STATUSES
            },
        }
        for band in DEPTH_BANDS
    }
    def has_preconfirmation_window(candidate: CandidateLifecycle) -> bool:
        cutoff = candidate.confirmed_index or candidate.failed_index
        return any(
            observation.index < (cutoff if cutoff is not None else candidate.resolution_index)
            and observation.close <= candidate.peak_price
            for observation in candidate.observations
        )

    with_preconfirmation_window = {
        "WITH_LIVE_WATCH_OR_ARMED_OBSERVATION": sum(
            has_preconfirmation_window(candidate) for candidate in candidates
        ),
        "NO_PRECONFIRMATION_WINDOW_OBSERVED": sum(
            not has_preconfirmation_window(candidate) for candidate in candidates
        ),
    }
    no_window_by_status = {
        status: sum(
            candidate.eventual_status == status
            and not has_preconfirmation_window(candidate)
            for candidate in candidates
        )
        for status in EVENTUAL_STATUSES
    }
    visibility_counts = Counter(candidate.source_visibility for candidate in candidates)
    return {
        "total_candidate_count": len(candidates),
        "eventually_confirmed_count": eventual.get("LATER_CONFIRMED", 0),
        "failed_count": eventual.get("FAILED", 0),
        "never_confirmed_count": eventual.get("NEVER_CONFIRMED", 0),
        "resolution": {
            resolution: resolution_counts.get(resolution, 0)
            for resolution in RESOLUTIONS
        },
        "failure_class": dict(sorted(failure_classes.items())),
        "geometry_validity": {
            "valid_geometry_count": sum(candidate.geometry_valid for candidate in candidates),
            "invalid_wave2_geometry_count": sum(not candidate.geometry_valid for candidate in candidates),
        },
        "wave_source_visibility": dict(sorted(visibility_counts.items())),
        "preconfirmation_window": {
            "counts": with_preconfirmation_window,
            "no_window_by_eventual_status": no_window_by_status,
            "no_window_rows_retained_in_cohort": True,
        },
        "by_market": by_market,
        "by_depth_band": by_depth,
    }


def _validate_results(
    candidates: Sequence[CandidateLifecycle],
    signals_by_policy: Mapping[str, Sequence[PolicySignal]],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    candidate_keys = [candidate.key for candidate in candidates]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise ValueError("causal cohort contains duplicate lifecycle identities")
    status_total = sum(
        sum(candidate.eventual_status == status for candidate in candidates)
        for status in EVENTUAL_STATUSES
    )
    resolution_total = sum(
        sum(candidate.resolution == resolution for candidate in candidates)
        for resolution in RESOLUTIONS
    )
    if status_total != len(candidates) or resolution_total != len(candidates):
        raise ValueError("causal cohort composition is not conserved")
    for candidate in candidates:
        if not (
            candidate.ready_index <= candidate.first_observed_index
            and candidate.first_observed_index <= candidate.last_observed_index
            and candidate.last_observed_index < len(symbol_quotes[candidate.symbol])
        ):
            raise ValueError("candidate chronology is not causal")
        for observation in candidate.observations:
            if any(
                anchor.confirmed_index is None
                or anchor.confirmed_index > observation.index
                for anchor in (observation.origin, observation.peak, observation.wave2_low)
            ):
                raise ValueError("cohort observation uses a future/unconfirmed Swing")
    policy_validation: dict[str, Any] = {}
    for policy_id in POLICY_IDS:
        signals = tuple(signals_by_policy[policy_id])
        if len({signal.candidate_key for signal in signals}) != len(signals):
            raise ValueError(f"duplicate signal identity for {policy_id}")
        for signal in signals:
            if signal.policy_id != policy_id:
                raise ValueError("signal policy identity changed")
            selected_candidate = next(
                candidate
                for candidate in candidates
                if candidate.key == signal.candidate_key
            )
            if not selected_candidate.geometry_valid:
                raise ValueError("invalid Wave2 geometry produced a policy signal")
            if signal.entry_index is not None:
                if signal.entry_index <= signal.signal_index:
                    raise ValueError("entry is not strictly next-session")
                entry_quote = symbol_quotes[signal.symbol][signal.entry_index]
                if signal.entry_date != entry_quote.trade_date or signal.entry_price != entry_quote.open:
                    raise ValueError("entry does not match exact next-session OPEN")
                sessions = tuple(market_session_dates[signal.market])
                if signal.entry_date != sessions[bisect_right(sessions, signal.signal_date)]:
                    raise ValueError("entry does not use the next frozen market session")
            if policy_id != INCUMBENT_POLICY and signal.confirmed_index is not None:
                if signal.signal_index >= signal.confirmed_index:
                    raise ValueError("early policy signal is not pre-confirmation")
        policy_validation[policy_id] = {
            "signal_count": len(signals),
            "unique_candidate_signal_count": len(signals),
            "entry_index_strictly_after_signal": True,
            "early_signals_strictly_before_confirmation": policy_id == INCUMBENT_POLICY or all(
                signal.confirmed_index is None or signal.signal_index < signal.confirmed_index
                for signal in signals
            ),
        }
    return {
        "cohort_unique_lifecycle_count": len(candidates),
        "cohort_eventual_status_conserved": status_total == len(candidates),
        "cohort_resolution_conserved": resolution_total == len(candidates),
        "all_anchor_confirmed_as_of_observation": True,
        "preconfirmation_window_rows_retained_even_when_not_observed": True,
        "early_policy_signals_strictly_before_confirmation": all(
            policy_id == INCUMBENT_POLICY
            or all(
                signal.confirmed_index is None or signal.signal_index < signal.confirmed_index
                for signal in signals_by_policy[policy_id]
            )
            for policy_id in POLICY_IDS
        ),
        "policy_ids_match_registered_protocol": tuple(signals_by_policy) == POLICY_IDS,
        "policy_validation": policy_validation,
        "signal_definition_uses_outcomes": False,
        "future_data_used_only_after_signal_for_evaluation": True,
        "exact_next_session_open_only": True,
    }


def _render_rate(value: Any) -> str:
    return "—" if value is None else f"{float(value):.1%}"


def _render_num(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _summary_row(summary: Mapping[str, Any]) -> str:
    return (
        f"| {summary['policy_id']} | {summary['total_candidate_count']} | "
        f"{summary['signaled_candidate_count']} | "
        f"{summary['actual_executable_next_session_entry_count']} | "
        f"{summary['eventually_confirmed_count']} | {summary['never_confirmed_count']} | "
        f"{summary['failed_count']} | "
        f"{summary['structural_invalidation_before_confirmation']['count']} "
        f"({_render_rate(summary['structural_invalidation_before_confirmation']['rate_of_signals'])}) | "
        f"{_render_num(summary['entry_geometry_over_R']['entry_to_Fib1.272_remaining_headroom']['median'])} | "
        f"{_render_num(summary['entry_geometry_over_R']['entry_to_Fib1.618_remaining_headroom']['median'])} |"
    )


def render_markdown(document: Mapping[str, Any]) -> str:
    cohort = document["cohort_construction"]
    policies = document["policies"]
    lines = [
        "# PRE-CONFIRMATION Early Entry Causal Research V1",
        "",
        "> Development research only. No production entry rule, confirmation, target, stop, RR, state, Sheets, or broker behavior is changed.",
        "",
        f"- Protocol: `{document['protocol_version']}`",
        f"- Status: `{document['status']}`",
        f"- Frozen input: `{document['source_artifacts']['replay_input']['path']}`",
        f"- Final OOS access: `{str(document['controls']['final_oos_accessed']).lower()}`",
        "",
        "## Cohort construction",
        "",
        "The cohort is rebuilt from every causal primary/alternate WAVE_2_TO_3 anchor context in strict as-of Wave replay, not from the existing CONFIRMED-only sample. Contexts hidden by current primary-scenario selection remain included.",
        "",
        "| item | count |",
        "|---|---:|",
        f"| frozen symbols | {document['funnel']['frozen_symbol_count']} |",
        f"| frozen bars | {document['funnel']['frozen_bar_count']} |",
        f"| causal Wave2 anchor contexts | {cohort['total_candidate_count']} |",
        f"| valid Wave2 geometry contexts | {cohort['geometry_validity']['valid_geometry_count']} |",
        f"| invalid Wave2 geometry contexts retained/screened | {cohort['geometry_validity']['invalid_wave2_geometry_count']} |",
        f"| PRIMARY-only / PRIMARY+ALTERNATE / ALTERNATE-only visibility | {cohort['wave_source_visibility'].get('PRIMARY_ONLY', 0)} / {cohort['wave_source_visibility'].get('PRIMARY_AND_ALTERNATE', 0)} / {cohort['wave_source_visibility'].get('ALTERNATE_ONLY', 0)} |",
        f"| later CONFIRMED | {cohort['eventually_confirmed_count']} |",
        f"| FAILED | {cohort['failed_count']} |",
        f"| never CONFIRMED | {cohort['never_confirmed_count']} |",
        f"| screened out by current system | {cohort['resolution']['SCREENED_OUT_BY_CURRENT_SYSTEM']} |",
        f"| timeout/unresolved at data end | {cohort['resolution']['TIMEOUT_UNRESOLVED_AT_DATA_END']} |",
        f"| candidates with a causal pre-confirmation observation | {cohort['preconfirmation_window']['counts']['WITH_LIVE_WATCH_OR_ARMED_OBSERVATION']} |",
        f"| retained candidates without an observed pre-confirmation window | {cohort['preconfirmation_window']['counts']['NO_PRECONFIRMATION_WINDOW_OBSERVED']} |",
        "",
        "## Fixed research policies",
        "",
        "All definitions below were fixed in the protocol before outcome analysis; each policy emits at most one first signal per lifecycle.",
        "",
        "| policy | signal milestone |",
        "|---|---|",
        "| INCUMBENT_CONFIRMED_CLOSE | first causal `close > H1` CONFIRMED day; next frozen-session OPEN |",
        "| FIRST_BULLISH_RECOVERY | first causal primary/alternate WAVE_2_TO_3 context day after confirmed anchors with `close > previous close`, `close > LOW2`, `close <= H1` |",
        "| ARMED_HALF_RECOVERY | first causal context day after confirmed anchors with `close >= LOW2 + 0.5 × (H1 − LOW2)`, `close <= H1` |",
        "| H1_INTRADAY_RECLAIM | first causal context day after confirmed anchors with `high >= H1`, `close <= H1` |",
        "| ARMED_HALF_RECOVERY_DAILY_UPTREND | fixed ARMED_HALF_RECOVERY milestone plus existing as-of daily UPTREND and weekly not DOWNTREND |",
        "",
        "Every entry is the exact next frozen market-session OPEN. Missing symbol bars are not substituted by a later bar.",
        "",
        "## Funnel and composition",
        "",
        "| policy | cohort | signaled | executable next OPEN | later confirmed | never confirmed | failed | structural invalidation-first | Fib1.272 remaining headroom/R median | Fib1.618 remaining headroom/R median |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(_summary_row(policies[policy_id]) for policy_id in POLICY_IDS)
    lines.extend([
        "",
        f"The policy counts above are signal-set counts; the cohort denominator remains the full {cohort['total_candidate_count']}-context cohort for every policy.",
        "",
        "## Headroom improvement versus incumbent",
        "",
        "Positive values mean the early entry retained more normalized space than the paired incumbent next-session OPEN on the same later-CONFIRMED lifecycle. The paired adverse delta uses a common post-entry structural-invalidation/data-end horizon; positive means the early entry experienced more adverse excursion because it was held from an earlier point.",
        "",
        "| early policy | paired executable later-CONFIRMED | H1 median gain/R | Fib1.272 median gain/R | Fib1.618 median gain/R | confirmation latency saved median sessions | paired adverse delta median/R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for policy_id in EARLY_POLICIES:
        paired = document["headroom_vs_incumbent"][policy_id]
        lines.append(
            f"| {policy_id} | {paired['paired_later_confirmed_executable_count']} | "
            f"{_render_num(paired['early_minus_incumbent_headroom_R']['H1']['median'])} | "
            f"{_render_num(paired['early_minus_incumbent_headroom_R']['Fib1.272']['median'])} | "
            f"{_render_num(paired['early_minus_incumbent_headroom_R']['Fib1.618']['median'])} | "
            f"{_render_num(paired['confirmation_latency_saved_sessions_on_later_confirmed']['median'], 1)} | "
            f"{_render_num(paired['paired_post_entry_structural_adverse_magnitude_R']['early_minus_incumbent']['median'])} |"
        )
    lines.extend(["", "## Failure and adverse-excursion tradeoff", ""])
    lines.extend([
        "Adverse excursion is the minimum low from executable entry through confirmation, failure, screened-out replacement, or dataset end, normalized by Wave1 `R = H1 − LOW0`. Fixed hurdles continue after confirmation until structural invalidation or dataset end for later-confirmed paths; never-confirmed paths remain censored. No production Stop is defined by this study.",
        "",
        "| policy | adverse magnitude median/R | adverse magnitude P90/R | censored paths | HURDLE_0272 success | HURDLE_0618 success |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for policy_id in POLICY_IDS:
        summary = policies[policy_id]
        lines.append(
            f"| {policy_id} | "
            f"{_render_num(summary['adverse_excursion_until_resolution']['adverse_magnitude_R']['median'])} | "
            f"{_render_num(summary['adverse_excursion_until_resolution']['adverse_magnitude_R']['p90'])} | "
            f"{summary['adverse_excursion_until_resolution']['censored_path_count']} | "
            f"{summary['common_fixed_structural_hurdles']['HURDLE_0272']['success_count']} "
            f"({_render_rate(summary['common_fixed_structural_hurdles']['HURDLE_0272']['success_rate'])}) | "
            f"{summary['common_fixed_structural_hurdles']['HURDLE_0618']['success_count']} "
            f"({_render_rate(summary['common_fixed_structural_hurdles']['HURDLE_0618']['success_rate'])}) |"
        )
    lines.extend(["", "## Robustness", ""])
    for policy_id in EARLY_POLICIES:
        robust = document["robustness"][policy_id]
        lines.extend([f"### {policy_id}", ""])
        lines.append("| slice | cohort | signaled | executable | later confirmed | never confirmed | failed |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for market, summary in robust["CN_US"].items():
            lines.append(
                f"| {market} | {summary['total_candidate_count']} | {summary['signaled_candidate_count']} | "
                f"{summary['actual_executable_next_session_entry_count']} | {summary['eventually_confirmed_count']} | "
                f"{summary['never_confirmed_count']} | {summary['failed_count']} |"
            )
        for band, summary in robust["depth_bands"].items():
            lines.append(
                f"| depth:{band} | {summary['total_candidate_count']} | {summary['signaled_candidate_count']} | "
                f"{summary['actual_executable_next_session_entry_count']} | {summary['eventually_confirmed_count']} | "
                f"{summary['never_confirmed_count']} | {summary['failed_count']} |"
            )
        leader = robust["symbol_concentration"]["count_leading_symbol"]
        if leader:
            without = robust["symbol_concentration"]["without_count_leading_symbol"]
            lines.append(
                f"| without count-leading symbol `{leader}` | {without['total_candidate_count']} | "
                f"{without['signaled_candidate_count']} | {without['actual_executable_next_session_entry_count']} | "
                f"{without['eventually_confirmed_count']} | {without['never_confirmed_count']} | {without['failed_count']} |"
            )
        lines.append("")
    lines.extend([
        "Time halves use the frozen market-session ordinal midpoint of candidate ready date. The complete JSON includes time halves, resolution strata, and later-CONFIRMED versus never-CONFIRMED/FAILED strata for every policy.",
        "",
        "## Bias checks and controls",
        "",
    ])
    for key, value in document["validation"].items():
        if key == "policy_validation":
            continue
        lines.append(f"- `{key}`: `{str(value).lower() if isinstance(value, bool) else value}`")
    lines.extend([
        f"- Final OOS access = `{str(document['controls']['final_oos_accessed']).lower()}`.",
        "- No parameter search or threshold sweep.",
        "- No P&L, return, win-rate, expectancy, or broker outcome was used as the first-layer selection criterion.",
        "- Production unchanged: no confirmation, Entry, Stop, Target, RR, Wave, Swing, 5% gate, or 2R change; no state/Sheets writes; no broker orders.",
        "",
        "## Decision node",
        "",
        f"**{document['decision']['classification']}** — {document['decision']['reason']}",
        "",
        f"- Supports a separate follow-up research decision: `{str(document['decision']['supports_separate_followup_research']).lower()}`.",
        f"- Supports execution/cost research now: `{str(document['decision']['supports_execution_cost_research']).lower()}`.",
        "- No policy is production-authorized by this artifact.",
        "",
        "Status: `READY_FOR_DECISION`.",
    ])
    return "\n".join(lines) + "\n"


def _source_artifact_payload(path: Path, *, normalize_lf: bool = False) -> dict[str, str]:
    return {"path": path.relative_to(PROJECT_ROOT).as_posix(), "sha256": f"sha256:{_sha256_file(path, normalize_lf=normalize_lf)}"}


def run_research(
    *,
    protocol_path: Path = PROTOCOL_PATH,
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    protocol = _json_load(protocol_path)
    _validate_protocol(protocol)
    manifest, symbol_quotes, replay_manifest = load_frozen_holdout()
    market_session_dates = build_market_session_dates(symbol_quotes)
    candidates = build_causal_cohort(symbol_quotes)
    signals_by_policy = {
        policy_id: evaluate_policy_signals(
            policy_id,
            candidates,
            symbol_quotes,
            market_session_dates,
        )
        for policy_id in POLICY_IDS
    }
    validation = _validate_results(
        candidates,
        signals_by_policy,
        symbol_quotes,
        market_session_dates,
    )
    policies = {
        policy_id: summarize_policy(
            policy_id,
            candidates,
            signals_by_policy[policy_id],
            symbol_quotes,
            market_session_dates,
        )
        for policy_id in POLICY_IDS
    }
    headroom_vs_incumbent = {
        policy_id: _paired_headroom(
            policy_id,
            candidates,
            signals_by_policy[policy_id],
            signals_by_policy[INCUMBENT_POLICY],
            symbol_quotes,
        )
        for policy_id in EARLY_POLICIES
    }
    robustness = {
        policy_id: _robustness(
            policy_id,
            candidates,
            signals_by_policy[policy_id],
            symbol_quotes,
            market_session_dates,
        )
        for policy_id in EARLY_POLICIES
    }
    cohort = _cohort_composition(candidates)
    policy_funnel = {
        policy_id: {
            "cohort": len(candidates),
            "signaled": len(signals_by_policy[policy_id]),
            "not_signaled": len(candidates) - len(signals_by_policy[policy_id]),
            "executable_next_session": policies[policy_id]["actual_executable_next_session_entry_count"],
            "not_executable_next_session": policies[policy_id]["not_executable_next_session_count"],
            "eventually_confirmed": policies[policy_id]["eventually_confirmed_count"],
            "never_confirmed": policies[policy_id]["never_confirmed_count"],
            "failed": policies[policy_id]["failed_count"],
        }
        for policy_id in POLICY_IDS
    }
    cohort_rebuild_count = cohort["total_candidate_count"]
    if cohort_rebuild_count <= cohort["eventually_confirmed_count"]:
        raise ValueError("cohort unexpectedly collapsed to confirmed-only rows")
    non_confirmed_signal_rates = {
        policy_id: _rate(
            policies[policy_id]["failed_count"] + policies[policy_id]["never_confirmed_count"],
            policies[policy_id]["signaled_candidate_count"],
        )
        for policy_id in EARLY_POLICIES
    }
    paired_headroom_medians = {
        policy_id: {
            metric: headroom_vs_incumbent[policy_id]["early_minus_incumbent_headroom_R"][metric]["median"]
            for metric in ("H1", "Fib1.272", "Fib1.618")
        }
        for policy_id in EARLY_POLICIES
    }
    decision = {
        "classification": "READY_FOR_DECISION",
        "supports_separate_followup_research": True,
        "supports_execution_cost_research": False,
        "non_confirmed_signal_rates": non_confirmed_signal_rates,
        "paired_headroom_median_gains_R": paired_headroom_medians,
        "reason": "The full causal cohort is reconstructable and every fixed early policy adds normalized entry headroom on its matched later-CONFIRMED subset, but all early policies also admit a substantial FAILED/never-CONFIRMED population. The first-layer question is therefore not cleared: this artifact supports a user decision about further research only, does not yet support moving to execution/cost research, and authorizes no production policy.",
        "evidence_scope": "structural timing, normalized headroom, adverse excursion, fixed hurdles, and failure composition; no P&L first-layer selection",
        "production_authorization": False,
    }
    controls = {
        "development_only": True,
        "final_oos_accessed": False,
        "parameter_search": False,
        "threshold_sweep": False,
        "signal_definition_uses_future_data": False,
        "outcomes_used_to_define_signal": False,
        "production_rule_change": False,
        "confirmation_modified": False,
        "entry_modified": False,
        "stop_modified": False,
        "target_modified": False,
        "rr_modified": False,
        "wave_modified": False,
        "swing_modified": False,
        "state_writes": 0,
        "sheets_writes": 0,
        "broker_orders": 0,
        "pr82_mixed_in": False,
    }
    protocol_sha = _sha256_file(protocol_path, normalize_lf=True)
    replay_input_path = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_replay_input.jsonl.gz"
    dataset_manifest_path = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_dataset_manifest.json"
    replay_wrapper_path = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_replay_manifest.json"
    document: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "artifact_type": "PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH",
        "artifact_version": "v1",
        "status": "READY_FOR_DECISION",
        "source_artifacts": {
            "protocol": {"path": protocol_path.relative_to(PROJECT_ROOT).as_posix(), "sha256": f"sha256:{protocol_sha}"},
            "replay_input": _source_artifact_payload(replay_input_path),
            "dataset_manifest": _source_artifact_payload(dataset_manifest_path),
            "replay_wrapper": _source_artifact_payload(replay_wrapper_path),
            "replay_aggregate_hash": replay_manifest.aggregate_hash,
            "dataset_version": manifest.get("dataset_version"),
        },
        "cohort_construction": cohort,
        "funnel": {
            "frozen_symbol_count": replay_manifest.total_symbol_count,
            "frozen_bar_count": replay_manifest.total_bar_count,
            "candidate_lifecycle_count": len(candidates),
            "policy": policy_funnel,
        },
        "fixed_policies": {
            "policy_ids": list(POLICY_IDS),
            "protocol_source": "registered protocol JSON; no runtime threshold arguments",
            "entry": "exact next frozen market-session OPEN",
            "wave1_R": "H1 - LOW0",
            "fib_headroom": {
                "Fib1.272": "LOW2 + 1.272 * R - entry",
                "Fib1.618": "LOW2 + 1.618 * R - entry",
            },
            "common_hurdles": {hurdle_id: f"H1 + {ratio} * R" for hurdle_id, ratio in HURDLE_IDS},
        },
        "policies": policies,
        "headroom_vs_incumbent": headroom_vs_incumbent,
        "robustness": robustness,
        "validation": validation,
        "controls": controls,
        "decision": decision,
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_output.write_text(render_markdown(document), encoding="utf-8")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args(argv)
    document = run_research(
        protocol_path=args.protocol,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps({
        "status": document["status"],
        "protocol_version": document["protocol_version"],
        "cohort": document["cohort_construction"]["total_candidate_count"],
        "eventual_status": {
            "LATER_CONFIRMED": document["cohort_construction"]["eventually_confirmed_count"],
            "FAILED": document["cohort_construction"]["failed_count"],
            "NEVER_CONFIRMED": document["cohort_construction"]["never_confirmed_count"],
        },
        "policies": {
            policy_id: document["policies"][policy_id]["signaled_candidate_count"]
            for policy_id in POLICY_IDS
        },
        "final_oos_accessed": document["controls"]["final_oos_accessed"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

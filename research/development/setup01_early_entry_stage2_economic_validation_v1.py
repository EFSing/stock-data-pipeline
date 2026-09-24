"""Stage-2 read-only economic validation of the constrained SETUP_01 earlier entry.

Implements ``SETUP01_EARLY_ENTRY_STAGE2_ECONOMIC_VALIDATION_V1`` exactly as registered
before any economic result was computed.  It rebuilds the unchanged first-stage cohort on
the frozen independent sample, forms the three registered identities (full incumbent,
first-CONFIRMED structural comparator, constrained PKG_B experimental group), replays the
pre-registered management policy, applies the registered CN/US cost scenarios, and reports
event-level economics with symbol-clustered uncertainty.

No production rule, state, Sheet or broker path is touched; no Final OOS, real holdings or
account NAV is read; portfolio drawdown is not estimable and is never fabricated.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.development.pre_confirmation_early_entry_causal_research_v1 import (
    INCUMBENT_POLICY,
    _next_session_entry,
    _percentile,
    _rate,
    build_causal_cohort,
    evaluate_policy_signals,
)
from research.development.setup01_early_entry_independent_validation_dataset import (
    ARTIFACT_DIR,
    DATASET_MANIFEST_PATH,
    DATASET_VERSION,
    FROZEN_INPUT_PATH,
    load_validation_sample,
)
from research.development.setup01_early_entry_stage2_engine import (
    CENSORED_AT_DATA_END,
    EXIT_GAP_BELOW_STOP,
    EXIT_LIFECYCLE_TERMINATED,
    EXIT_PRE_CONFIRMATION_TIMEOUT,
    EXIT_STOP_TRIGGERED,
    EXIT_STRUCTURAL_INVALIDATION,
    EXIT_TARGET_T1_REACHED,
    FLAG_CONFIRMATION_DECISION_UNAVAILABLE,
    FLAG_NO_VALID_TARGET_AT_CONFIRMATION,
    IDENTITY_A,
    IDENTITY_B,
    IDENTITY_C,
    IDENTITY_IDS,
    NOT_EVALUABLE_NO_ATR,
    NOT_EXECUTABLE_AT_RESEARCH_BUDGET,
    SCENARIO_BASELINE,
    SCENARIO_IDS,
    SCENARIO_STRESS,
    SKIP_INVALID_OPEN,
    SKIP_LIFECYCLE_TERMINATED_BEFORE_ENTRY,
    SKIP_NO_NEXT_SESSION_BAR,
    SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP,
    SKIP_OPEN_AT_OR_BELOW_WAVE2_LOW,
    SKIP_ZERO_VOLUME_AT_ENTRY,
    TIMEOUT_SESSIONS,
    TradeGeometry,
    limit_flags,
    load_cn_preclose_index,
    preclose_for_date,
    simulate_trade,
    size_position,
    trade_economics,
)
from research.market_sessions import build_market_session_dates
from trading.indicators import atr
from trading.models import DecisionAction
from trading.setup01 import SETUP01_RECOVERY_RATIO
from trading.setup01_decision import (
    EXECUTED,
    evaluate_setup01_decision_stream,
)
from trading.setup01_replay import replay_setup01_history


PROTOCOL_VERSION = "SETUP01_EARLY_ENTRY_STAGE2_ECONOMIC_VALIDATION_V1"
PROTOCOL_PATH = (
    PROJECT_ROOT
    / "research"
    / "protocols"
    / "setup01_early_entry_stage2_economic_validation_v1.json"
)
PINNED_PROTOCOL_SHA256 = (
    "sha256:19a5fe3fc45c61a075ad0f439d573cf7cce8bf9d2ea65f1293be79e9c3c7be91"
)
STAGE1_PROTOCOL_PATH = (
    PROJECT_ROOT
    / "research"
    / "protocols"
    / "setup01_early_entry_independent_validation_v1.json"
)
STAGE1_JSON_PATH = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_independent_validation_v1.json"
)
DECISION_RECORD_PATH = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_second_stage_decision_v1.json"
)
DEFAULT_JSON_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_stage2_economic_validation_v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_stage2_economic_validation_v1.md"
)
EXPERIMENTAL_POLICY = "ARMED_HALF_RECOVERY"
MARKETS = ("CN", "US")
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260924
PRIMARY_POLICY = "PRIMARY_TARGET_EXIT"
SECONDARY_POLICY = "NO_TARGET_EXIT_VARIANT"

OUTCOME_SUPPORTED = "SUPPORTED_FOR_INDEPENDENT_EXECUTION_VALIDATION"
OUTCOME_NOT_SUPPORTED = "NOT_SUPPORTED"
OUTCOME_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def _sha256_file(path: Path, *, normalize_lf: bool = False) -> str:
    payload = path.read_bytes()
    if normalize_lf:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _source_artifact(path: Path) -> dict[str, str]:
    normalize_lf = path.suffix != ".gz"
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": f"sha256:{_sha256_file(path, normalize_lf=normalize_lf)}",
    }


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _distribution(values: Sequence[float | None]) -> dict[str, Any]:
    clean = [float(value) for value in values if _finite(value) is not None]
    if not clean:
        return {
            "n": 0,
            "mean": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "worst": None,
        }
    return {
        "n": len(clean),
        "mean": sum(clean) / len(clean),
        "p10": _percentile(clean, 0.10),
        "p25": _percentile(clean, 0.25),
        "median": _percentile(clean, 0.50),
        "p75": _percentile(clean, 0.75),
        "p90": _percentile(clean, 0.90),
        "worst": min(clean),
    }


def _counts(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _index_of_date(quotes: Sequence[Quote], trade_date: date) -> int | None:
    for index, quote in enumerate(quotes):
        if quote.trade_date == trade_date:
            return index
    return None


def _lifecycle_termination_index(candidate: Any) -> int | None:
    if candidate.eventual_status == "LATER_CONFIRMED":
        return None
    if candidate.resolution == "TIMEOUT_UNRESOLVED_AT_DATA_END":
        return None
    return int(candidate.resolution_index)


def _identity_c_geometry(
    *,
    candidate: Any,
    signal: Any,
    quotes: Sequence[Quote],
    decision_by_confirmation: Mapping[tuple[str, str], Any],
) -> tuple[TradeGeometry | None, str]:
    """Apply the registered experimental admission rules to one ARMED signal."""
    if signal.entry_index is None:
        return None, SKIP_NO_NEXT_SESSION_BAR
    entry_quote = quotes[signal.entry_index]
    opening = _finite(entry_quote.open)
    if opening is None or opening <= 0:
        return None, SKIP_INVALID_OPEN
    termination = _lifecycle_termination_index(candidate)
    if termination is not None and termination < signal.entry_index:
        return None, SKIP_LIFECYCLE_TERMINATED_BEFORE_ENTRY
    volume = _finite(entry_quote.volume)
    if volume is None or volume <= 0:
        return None, SKIP_ZERO_VOLUME_AT_ENTRY
    prefix = list(quotes[: signal.signal_index + 1])
    atr14 = _finite(atr(prefix, 14)[-1])
    if atr14 is None:
        return None, NOT_EVALUABLE_NO_ATR
    stop = float(candidate.wave2_low_price) - 0.5 * atr14
    if opening <= candidate.wave2_low_price:
        return None, SKIP_OPEN_AT_OR_BELOW_WAVE2_LOW
    if opening <= stop:
        return None, SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP
    confirmation_index = candidate.confirmed_index
    confirmation_targets: tuple[float, ...] = ()
    if confirmation_index is not None:
        decision = decision_by_confirmation.get(
            (candidate.symbol, candidate.confirmed_date.isoformat())
        )
        if decision is not None:
            confirmation_targets = tuple(float(price) for price in decision.targets)
    geometry = TradeGeometry(
        identity=IDENTITY_C,
        symbol=candidate.symbol,
        market=candidate.market,
        candidate_key=candidate.key,
        signal_date=signal.signal_date.isoformat(),
        entry_index=int(signal.entry_index),
        entry_date=signal.entry_date.isoformat(),
        entry_price=float(opening),
        execution_stop=stop,
        one_r=float(opening) - stop,
        structural_low=float(candidate.wave2_low_price),
        initial_targets=(),
        confirmation_index=(
            int(confirmation_index) if confirmation_index is not None else None
        ),
        confirmation_targets=confirmation_targets,
        lifecycle_termination_index=termination,
        manage_pre_confirmation=True,
    )
    return geometry, "ADMITTED"


def _identity_b_geometry(
    *,
    decision: Any,
    quotes: Sequence[Quote],
    market_session_dates: Mapping[str, Sequence[date]],
    candidate_by_key: Mapping[str, Any],
) -> tuple[TradeGeometry | None, str]:
    """Structural timing comparator: same plan geometry, no admission gates."""
    stop = _finite(decision.execution_stop)
    structural_low = _finite(decision.structural_invalidation)
    if stop is None or structural_low is None or not decision.decision_calculable:
        return None, NOT_EVALUABLE_NO_ATR
    event_index = _index_of_date(quotes, decision.trade_date)
    if event_index is None:
        return None, NOT_EVALUABLE_NO_ATR
    entry = _next_session_entry(event_index, quotes, market_session_dates)
    if entry is None:
        return None, SKIP_NO_NEXT_SESSION_BAR
    entry_index, entry_date, entry_price = entry
    if entry_price is None or entry_price <= 0:
        return None, SKIP_INVALID_OPEN
    if entry_price <= stop:
        return None, SKIP_INVALID_OPEN
    geometry = TradeGeometry(
        identity=IDENTITY_B,
        symbol=decision.symbol,
        market=decision.market,
        candidate_key=f"{decision.symbol}|CONFIRMED|{decision.trade_date.isoformat()}",
        signal_date=decision.trade_date.isoformat(),
        entry_index=entry_index,
        entry_date=entry_date.isoformat(),
        entry_price=float(entry_price),
        execution_stop=float(stop),
        one_r=float(entry_price) - float(stop),
        structural_low=float(structural_low),
        initial_targets=tuple(float(price) for price in decision.targets),
        confirmation_index=None,
        confirmation_targets=(),
        lifecycle_termination_index=None,
        manage_pre_confirmation=False,
    )
    return geometry, "ADMITTED"


def _identity_a_geometry(
    *,
    decision: Any,
    execution: Any,
    quotes: Sequence[Quote],
) -> tuple[TradeGeometry | None, str]:
    if execution is None or execution.outcome != EXECUTED:
        return None, "NOT_EXECUTED_BY_INCUMBENT"
    entry = _finite(execution.actual_entry)
    stop = _finite(decision.execution_stop)
    structural_low = _finite(decision.structural_invalidation)
    if entry is None or stop is None or structural_low is None:
        return None, NOT_EVALUABLE_NO_ATR
    entry_index = _index_of_date(quotes, execution.execution_date)
    if entry_index is None:
        return None, SKIP_NO_NEXT_SESSION_BAR
    geometry = TradeGeometry(
        identity=IDENTITY_A,
        symbol=decision.symbol,
        market=decision.market,
        candidate_key=f"{decision.symbol}|CONFIRMED|{decision.trade_date.isoformat()}",
        signal_date=decision.trade_date.isoformat(),
        entry_index=entry_index,
        entry_date=execution.execution_date.isoformat(),
        entry_price=float(entry),
        execution_stop=float(stop),
        one_r=float(entry) - float(stop),
        structural_low=float(structural_low),
        initial_targets=tuple(float(price) for price in decision.targets),
        confirmation_index=None,
        confirmation_targets=(),
        lifecycle_termination_index=None,
        manage_pre_confirmation=False,
    )
    return geometry, "ADMITTED"


@dataclass(frozen=True)
class TradeEntry:
    geometry: TradeGeometry | None
    admission: str
    eventual_status: str | None = None
    resolution: str | None = None
    depth_band: str | None = None
    time_half: str | None = None
    confirmation_flag: str | None = None
    pair_key: str | None = None


def _replay_identity(
    entries: Sequence[TradeEntry],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    preclose_by_symbol: Mapping[str, Mapping[str, float]],
    *,
    target_exit_enabled: bool,
) -> dict[str, Any]:
    """Replay every admitted geometry of one identity under one exit policy."""
    skip_counts: dict[str, int] = {}
    outcomes: list[dict[str, Any]] = []
    not_executable_at_budget = 0
    for entry in entries:
        if entry.geometry is None:
            skip_counts[entry.admission] = skip_counts.get(entry.admission, 0) + 1
            continue
        geometry = entry.geometry
        quotes = symbol_quotes[geometry.symbol]
        sized = size_position(geometry.market, geometry.entry_price, geometry.execution_stop)
        if sized is None:
            not_executable_at_budget += 1
            continue
        outcome = simulate_trade(
            geometry, quotes, target_exit_enabled=target_exit_enabled
        )
        flags = list(outcome.flags)
        if entry.confirmation_flag is not None:
            flags.append(entry.confirmation_flag)
        preclose_index = preclose_by_symbol.get(geometry.symbol, {})
        flags.extend(
            limit_flags(
                market=geometry.market,
                symbol=geometry.symbol,
                entry_open=geometry.entry_price,
                entry_preclose=preclose_for_date(preclose_index, geometry.entry_date),
                exit_price=outcome.exit_price,
                exit_preclose=preclose_for_date(preclose_index, outcome.exit_date),
                limit_data_available=bool(preclose_index) or geometry.market != "CN",
            )
        )
        economics = {
            scenario: trade_economics(
                outcome,
                market=geometry.market,
                scenario=scenario,
                exit_date=outcome.exit_date,
                sized=sized,
            )
            for scenario in SCENARIO_IDS
        }
        outcomes.append(
            {
                "identity": geometry.identity,
                "market": geometry.market,
                "symbol": geometry.symbol,
                "candidate_key": geometry.candidate_key,
                "signal_date": geometry.signal_date,
                "entry_date": geometry.entry_date,
                "entry_price": geometry.entry_price,
                "execution_stop": geometry.execution_stop,
                "one_r": geometry.one_r,
                "structural_low": geometry.structural_low,
                "confirmation_index": geometry.confirmation_index,
                "entry_index": geometry.entry_index,
                "exit_index": outcome.exit_index,
                "exit_date": outcome.exit_date,
                "exit_price": outcome.exit_price,
                "exit_reason": outcome.exit_reason,
                "sessions_held": outcome.sessions_held,
                "censored": outcome.censored,
                "flags": tuple(sorted(set(flags))),
                "target_exit_used": outcome.target_exit_used,
                "economics": economics,
                "eventual_status": entry.eventual_status,
                "resolution": entry.resolution,
                "depth_band": entry.depth_band,
                "time_half": entry.time_half,
                "pair_key": entry.pair_key,
            }
        )
    return {
        "admitted": sum(1 for entry in entries if entry.geometry is not None),
        "eligible": len(entries),
        "skip_counts": dict(sorted(skip_counts.items())),
        "not_executable_at_research_budget": not_executable_at_budget,
        "outcomes": outcomes,
    }


def _bootstrap(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    statistic_identities: Sequence[str],
    scenario: str,
    symbols: Sequence[str],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Symbol-clustered bootstrap of mean net R per realized trade."""
    by_symbol: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in symbols}
    for row in outcomes:
        if row["censored"]:
            continue
        by_symbol.setdefault(row["symbol"], []).append(row)

    def mean_net_r(rows: Sequence[Mapping[str, Any]]) -> float | None:
        values = [row["economics"][scenario]["net_r"] for row in rows]
        clean = [value for value in values if value is not None]
        return sum(clean) / len(clean) if clean else None

    point = {
        identity: mean_net_r([row for row in outcomes if row["identity"] == identity and not row["censored"]])
        for identity in statistic_identities
    }
    rng = random.Random(seed)
    draws: dict[str, list[float]] = {key: [] for key in _bootstrap_keys(statistic_identities)}
    skipped: dict[str, int] = {key: 0 for key in draws}
    for _ in range(resamples):
        sampled = [symbols[rng.randrange(len(symbols))] for _ in range(len(symbols))]
        pooled: dict[str, list[Mapping[str, Any]]] = {identity: [] for identity in statistic_identities}
        for symbol in sampled:
            for row in by_symbol.get(symbol, ()):
                pooled[row["identity"]].append(row)
        means = {
            identity: mean_net_r(pooled[identity]) for identity in statistic_identities
        }
        for key, (left, right) in _bootstrap_keys(statistic_identities).items():
            if means[left] is None or means[right] is None:
                skipped[key] += 1
                continue
            draws[key].append(means[left] - means[right])
    return {
        "scenario": scenario,
        "resamples": resamples,
        "resamples_skipped": skipped,
        "seed": seed,
        "point": point,
        "interval": {
            key: {
                "lower": _percentile(values, 0.025) if values else None,
                "upper": _percentile(values, 0.975) if values else None,
                "median": _percentile(values, 0.50) if values else None,
                "n": len(values),
            }
            for key, values in draws.items()
        },
    }


def _bootstrap_keys(identities: Sequence[str]) -> dict[str, tuple[str, str]]:
    keys: dict[str, tuple[str, str]] = {}
    if IDENTITY_C in identities and IDENTITY_B in identities:
        keys[f"{IDENTITY_C}_minus_{IDENTITY_B}"] = (IDENTITY_C, IDENTITY_B)
    if IDENTITY_C in identities and IDENTITY_A in identities:
        keys[f"{IDENTITY_C}_minus_{IDENTITY_A}"] = (IDENTITY_C, IDENTITY_A)
    if IDENTITY_B in identities and IDENTITY_A in identities:
        keys[f"{IDENTITY_B}_minus_{IDENTITY_A}"] = (IDENTITY_B, IDENTITY_A)
    return keys


def _identity_report(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    scenario: str,
) -> dict[str, Any]:
    realized = [row for row in outcomes if not row["censored"]]
    censored = [row for row in outcomes if row["censored"]]
    net_r = [row["economics"][scenario]["net_r"] for row in realized]
    gross_r = [row["economics"][scenario]["gross_r"] for row in realized]
    net_return = [row["economics"][scenario]["net_return"] for row in realized]
    gross_return = [row["economics"][scenario]["gross_return"] for row in realized]
    losing = sum(1 for value in net_r if value is not None and value < 0)
    at_or_below_minus_one_r = sum(
        1 for value in net_r if value is not None and value <= -1.0
    )
    total_cost_r = [
        row["economics"][scenario]["total_cost_per_share"] / row["one_r"]
        for row in realized
    ]
    return {
        "scenario": scenario,
        "realized_trades": len(realized),
        "censored_trades": len(censored),
        "gross_r": _distribution(gross_r),
        "net_r": _distribution(net_r),
        "gross_return": _distribution(gross_return),
        "net_return": _distribution(net_return),
        "cost_r": _distribution(total_cost_r),
        "losing_share": _rate(losing, len(realized)),
        "share_at_or_below_minus_one_r": _rate(at_or_below_minus_one_r, len(realized)),
        "net_r_sum": sum(value for value in net_r if value is not None),
        "net_pnl_total_sum": sum(
            row["economics"][scenario]["net_pnl_total"] for row in realized
        ),
        "notional": _distribution(
            [row["economics"][scenario]["notional"] for row in realized]
        ),
        "position_days": _distribution([row["sessions_held"] for row in realized]),
        "capital_time": _distribution(
            [row["economics"][scenario]["capital_time"] for row in realized]
        ),
        "exit_reason_counts": _counts([row["exit_reason"] for row in realized]),
        "flag_counts": _counts(
            [flag for row in outcomes for flag in row["flags"]]
        ),
        "eventual_status_composition": _counts(
            [str(row["eventual_status"]) for row in outcomes]
        ),
        "resolution_composition": _counts([str(row["resolution"]) for row in outcomes]),
        "symbol_count": len({row["symbol"] for row in realized}),
        "count_leading_symbol": _count_leading_symbol(realized),
        "including_censored_at_final_close": {
            "n": len(outcomes),
            "net_r": _distribution(
                [row["economics"][scenario]["net_r"] for row in outcomes]
            ),
            "note": (
                "sensitivity only: right-censored rows are valued at the final frozen close "
                "and are never mixed into realized trade results"
            ),
        },
    }


def _paired_subset(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    scenario: str,
) -> dict[str, Any]:
    """Descriptive paired comparison on shared confirmed lifecycles."""
    by_identity: dict[str, dict[str, float]] = {identity: {} for identity in IDENTITY_IDS}
    for row in outcomes:
        if row["censored"] or row["pair_key"] is None:
            continue
        value = row["economics"][scenario]["net_r"]
        if value is None:
            continue
        by_identity[row["identity"]][row["pair_key"]] = value
    result: dict[str, Any] = {}
    for left, right in ((IDENTITY_C, IDENTITY_B), (IDENTITY_C, IDENTITY_A)):
        shared = sorted(set(by_identity[left]) & set(by_identity[right]))
        differences = [by_identity[left][key] - by_identity[right][key] for key in shared]
        result[f"{left}_minus_{right}"] = {
            "paired_lifecycles": len(shared),
            "net_r_difference": _distribution(differences),
            "left_net_r": _distribution([by_identity[left][key] for key in shared]),
            "right_net_r": _distribution([by_identity[right][key] for key in shared]),
            "note": "descriptive only; pairing is on the shared confirmed lifecycle",
        }
    return result


def _count_leading_symbol(realized: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = _counts([row["symbol"] for row in realized])
    if not counts:
        return {"symbol": None, "trades": 0}
    symbol = max(counts.items(), key=lambda item: (item[1], item[0]))[0]
    return {"symbol": symbol, "trades": counts[symbol]}


def _strata_report(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    scenario: str,
) -> dict[str, Any]:
    def slice_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        realized = [row for row in rows if not row["censored"]]
        return {
            "realized_trades": len(realized),
            "censored_trades": len(rows) - len(realized),
            "net_r": _distribution(
                [row["economics"][scenario]["net_r"] for row in realized]
            ),
        }

    strata: dict[str, Any] = {"time_half": {}, "depth_band": {}, "market": {}}
    for key, target in (("time_half", "time_half"), ("depth_band", "depth_band"), ("market", "market")):
        values = sorted({str(row[target]) for row in outcomes if row[target] is not None})
        for value in values:
            strata[key][value] = slice_rows([row for row in outcomes if str(row[target]) == value])
    return strata


def _identities_report(
    replay: Mapping[str, Any],
    *,
    scenario: str,
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for identity in IDENTITY_IDS:
        rows = [row for row in replay["outcomes"] if row["identity"] == identity]
        report[identity] = _identity_report(rows, scenario=scenario)
        report[identity]["strata"] = _strata_report(rows, scenario=scenario)
    return report


def _funnel_report(replay: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "eligible": replay["eligible"],
        "admitted": replay["admitted"],
        "skip_counts": replay["skip_counts"],
        "not_executable_at_research_budget": replay["not_executable_at_research_budget"],
    }


def _mean_net_r(rows: Sequence[Mapping[str, Any]], scenario: str) -> float | None:
    values = [
        row["economics"][scenario]["net_r"]
        for row in rows
        if not row["censored"] and row["economics"][scenario]["net_r"] is not None
    ]
    return sum(values) / len(values) if values else None


def _differences(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    scenario: str,
) -> dict[str, float | None]:
    by_identity: dict[str, list[Mapping[str, Any]]] = {identity: [] for identity in IDENTITY_IDS}
    for row in outcomes:
        by_identity[row["identity"]].append(row)
    means = {
        identity: _mean_net_r(rows, scenario) for identity, rows in by_identity.items()
    }
    result: dict[str, float | None] = {}
    for key, (left, right) in _bootstrap_keys(IDENTITY_IDS).items():
        if means[left] is None or means[right] is None:
            result[key] = None
        else:
            result[key] = means[left] - means[right]
    return result


def _classify(
    *,
    protocol: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
    bootstrap: Mapping[str, Any],
    roster_symbols: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    floors = protocol["decision_rules"]["floors"]
    baseline = SCENARIO_BASELINE
    stress = SCENARIO_STRESS
    per_market: dict[str, Any] = {}
    floor_failures: dict[str, list[str]] = {}
    for market in MARKETS:
        rows = [row for row in outcomes if row["market"] == market]
        realized = {
            identity: [
                row
                for row in rows
                if row["identity"] == identity and not row["censored"]
            ]
            for identity in IDENTITY_IDS
        }
        c_rows = [row for row in rows if row["identity"] == IDENTITY_C]
        censored_c = sum(1 for row in c_rows if row["censored"])
        failures: list[str] = []
        if len(realized[IDENTITY_C]) < floors["min_realized_trades_C_per_market"]:
            failures.append("MIN_REALIZED_TRADES_C")
        if len(realized[IDENTITY_B]) < floors["min_realized_trades_B_per_market"]:
            failures.append("MIN_REALIZED_TRADES_B")
        if len(realized[IDENTITY_A]) < floors["min_realized_trades_A_per_market"]:
            failures.append("MIN_REALIZED_TRADES_A")
        if len({row["symbol"] for row in realized[IDENTITY_C]}) < floors[
            "min_symbols_with_realized_C_per_market"
        ]:
            failures.append("MIN_SYMBOLS_WITH_REALIZED_C")
        censored_share = _rate(censored_c, len(c_rows))
        if censored_share is not None and censored_share > floors[
            "censored_share_of_C_entries_max"
        ]:
            failures.append("CENSORED_SHARE_OF_C_ENTRIES")
        means = {
            identity: _mean_net_r(realized[identity], baseline)
            for identity in IDENTITY_IDS
        }
        differences = _differences(rows, scenario=baseline)
        per_market[market] = {
            "realized_counts": {
                identity: len(realized[identity]) for identity in IDENTITY_IDS
            },
            "symbols_with_realized_C": len(
                {row["symbol"] for row in realized[IDENTITY_C]}
            ),
            "censored_share_of_C_entries": censored_share,
            "mean_net_r_baseline": means,
            "differences_baseline": differences,
            "floors_failed": failures,
        }
        floor_failures[market] = failures

    pooled_baseline = _differences(outcomes, scenario=baseline)
    pooled_stress = _differences(outcomes, scenario=stress)
    leading = {
        market: _count_leading_symbol(
            [
                row
                for row in outcomes
                if row["market"] == market
                and row["identity"] == IDENTITY_C
                and not row["censored"]
            ]
        )["symbol"]
        for market in MARKETS
    }
    dropped = [
        row for row in outcomes if leading.get(row["market"]) not in (None, row["symbol"])
    ]
    pooled_dropped = _differences(dropped, scenario=baseline)
    intervals = bootstrap[baseline]["combined"]["interval"]

    positive_vs_b = pooled_baseline.get(f"{IDENTITY_C}_minus_{IDENTITY_B}")
    positive_vs_a = pooled_baseline.get(f"{IDENTITY_C}_minus_{IDENTITY_A}")
    stress_vs_b = pooled_stress.get(f"{IDENTITY_C}_minus_{IDENTITY_B}")
    stress_vs_a = pooled_stress.get(f"{IDENTITY_C}_minus_{IDENTITY_A}")
    dropped_vs_b = pooled_dropped.get(f"{IDENTITY_C}_minus_{IDENTITY_B}")
    dropped_vs_a = pooled_dropped.get(f"{IDENTITY_C}_minus_{IDENTITY_A}")
    ci_b = intervals.get(f"{IDENTITY_C}_minus_{IDENTITY_B}", {})
    ci_a = intervals.get(f"{IDENTITY_C}_minus_{IDENTITY_A}", {})
    ci_lower_b = ci_b.get("lower")
    ci_lower_a = ci_a.get("lower")
    floors_ok = all(not value for value in floor_failures.values())
    market_point_rule = all(
        (per_market[market]["mean_net_r_baseline"][IDENTITY_C] is not None)
        and (per_market[market]["mean_net_r_baseline"][IDENTITY_B] is not None)
        and (per_market[market]["mean_net_r_baseline"][IDENTITY_A] is not None)
        and per_market[market]["mean_net_r_baseline"][IDENTITY_C]
        > per_market[market]["mean_net_r_baseline"][IDENTITY_B]
        and per_market[market]["mean_net_r_baseline"][IDENTITY_C]
        > per_market[market]["mean_net_r_baseline"][IDENTITY_A]
        for market in MARKETS
    )

    if positive_vs_b is None or positive_vs_a is None:
        overall = OUTCOME_INSUFFICIENT
        reason = "an identity has no realized trade, so no pooled comparison exists"
    elif not floors_ok:
        overall = OUTCOME_INSUFFICIENT
        reason = (
            "a registered floor failed, so the comparison against the full incumbent is not "
            "evaluable at the registered standard; the protocol states that a failed floor "
            "yields INSUFFICIENT_EVIDENCE and never NOT_SUPPORTED. Raw pooled point estimates "
            f"are kept as reported: C-B {positive_vs_b:.4f} and C-A {positive_vs_a:.4f}"
        )
    elif positive_vs_b <= 0 or positive_vs_a <= 0:
        overall = OUTCOME_NOT_SUPPORTED
        reason = "the pooled mean net R advantage over the structural comparator or the incumbent is not positive"
    elif (
        floors_ok
        and market_point_rule
        and ci_lower_b is not None
        and ci_lower_a is not None
        and ci_lower_b > 0
        and ci_lower_a > 0
        and stress_vs_b is not None
        and stress_vs_a is not None
        and stress_vs_b > 0
        and stress_vs_a > 0
        and dropped_vs_b is not None
        and dropped_vs_a is not None
        and dropped_vs_b > 0
        and dropped_vs_a > 0
    ):
        overall = OUTCOME_SUPPORTED
        reason = (
            "every floor, per-market point estimate, clustered interval and cost/concentration "
            "robustness condition registered for support is satisfied"
        )
    else:
        overall = OUTCOME_INSUFFICIENT
        reason = (
            "point estimates are positive but at least one registered floor, clustered interval "
            "or cost/concentration robustness condition is not satisfied"
        )
    return {
        "overall_classification": overall,
        "reason": reason,
        "rule_precedence_applied": (
            "floors are evaluated before the point-estimate rule because the registered floor "
            "derivation states that a failed floor can never produce NOT_SUPPORTED; both the "
            "floor state and the raw pooled point estimates are reported"
        ),
        "per_market": per_market,
        "floors_failed": floor_failures,
        "pooled_baseline_differences": pooled_baseline,
        "pooled_stress_differences": pooled_stress,
        "pooled_drop_count_leading_symbol_differences": pooled_dropped,
        "pooled_bootstrap_intervals_baseline": intervals,
        "count_leading_symbol_dropped": leading,
        "absolute_net_r_negative_markets": [
            market
            for market in MARKETS
            if per_market[market]["mean_net_r_baseline"][IDENTITY_C] is not None
            and per_market[market]["mean_net_r_baseline"][IDENTITY_C] < 0
        ],
        "censoring_caveat": (
            "the registered primary statistic excludes right-censored rows, and censoring is "
            "asymmetric: C resolves almost every entry through its 20-session pre-confirmation "
            "waiting bound while A and B have no such bound. The final-close valuation "
            "sensitivity is therefore reported for all identities; where it reorders the "
            "comparison the economic conclusion is treated as not robust to censoring. It never "
            "replaces the realized statistic and is never mixed into it"
        ),
        "production_authorization": False,
        "supports_next_independent_execution_validation": overall == OUTCOME_SUPPORTED,
    }


def run_validation(
    *,
    protocol_path: Path = PROTOCOL_PATH,
    dataset_manifest_path: Path = DATASET_MANIFEST_PATH,
    frozen_input_path: Path = FROZEN_INPUT_PATH,
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    protocol_digest = f"sha256:{_sha256_file(protocol_path, normalize_lf=True)}"
    if protocol_digest != PINNED_PROTOCOL_SHA256:
        raise ValueError("the registered stage-2 protocol changed after registration")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("stage-2 protocol identity changed")
    if float(SETUP01_RECOVERY_RATIO) != 0.5:
        raise ValueError("the pre-defined SETUP_01 recovery milestone changed")

    manifest, symbol_quotes, replay_manifest = load_validation_sample(
        dataset_manifest_path=dataset_manifest_path,
        frozen_input_path=frozen_input_path,
    )
    quotes_by_symbol = {symbol: list(values) for symbol, values in symbol_quotes.items()}
    market_session_dates = build_market_session_dates(quotes_by_symbol)
    candidates = build_causal_cohort(quotes_by_symbol)
    candidate_by_key = {candidate.key: candidate for candidate in candidates}
    candidate_by_confirmation = {
        (candidate.symbol, candidate.confirmed_date.isoformat()): candidate
        for candidate in candidates
        if candidate.confirmed_date is not None
    }
    signals = {
        policy_id: evaluate_policy_signals(
            policy_id, candidates, quotes_by_symbol, market_session_dates
        )
        for policy_id in (EXPERIMENTAL_POLICY, INCUMBENT_POLICY)
    }

    stage1 = json.loads(STAGE1_JSON_PATH.read_text(encoding="utf-8"))
    denominator_check = {
        "cohort_matches_stage1": len(candidates)
        == stage1["cohort_construction"]["total_candidate_count"],
        "armed_signals_matches_stage1": len(signals[EXPERIMENTAL_POLICY])
        == stage1["policies"][EXPERIMENTAL_POLICY]["signaled_candidate_count"],
    }
    for market in MARKETS:
        executable = sum(
            1
            for signal in signals[EXPERIMENTAL_POLICY]
            if signal.market == market and signal.entry_index is not None
        )
        denominator_check[f"executable_{market}_matches_stage1"] = (
            executable
            == stage1["market_metrics"][market]["executable_early_signals"]
        )
    if not all(denominator_check.values()):
        raise ValueError("the rebuilt cohort does not reproduce the first stage")

    reports = [
        replay_setup01_history(quotes_by_symbol[symbol])
        for symbol in sorted(quotes_by_symbol)
    ]
    confirmed_events = [
        event
        for report in reports
        for event in report.events
        if event.event_type.value == "CONFIRMED"
        and event.setup01.is_new_confirmed_event_as_of
        and event.setup01.confirmed_date == event.trade_date
        and event.setup01.as_of_date == event.trade_date
    ]
    stream = evaluate_setup01_decision_stream(
        confirmed_events, quotes_by_symbol, risk_capital=None
    )
    execution_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    decision_by_confirmation = {
        (decision.symbol, decision.trade_date.isoformat()): decision
        for decision in stream.decisions
    }
    production_funnel = {
        "confirmed_events": len(confirmed_events),
        "decisions": len(stream.decisions),
        "gate_reason_counts": _counts(
            [str(decision.gate_reason) for decision in stream.decisions]
        ),
        "execution_outcome_counts": _counts(
            [str(execution.outcome) for execution in stream.executions]
        ),
    }

    preclose_by_symbol: dict[str, Mapping[str, float]] = {}
    for symbol in quotes_by_symbol:
        if not symbol.endswith((".SH", ".SZ")):
            continue
        preclose_by_symbol[symbol] = load_cn_preclose_index(
            ARTIFACT_DIR / "raw_baostock" / "CN" / f"{symbol}.csv"
        )

    a_entries: list[TradeEntry] = []
    b_entries: list[TradeEntry] = []
    for decision in stream.decisions:
        quotes = quotes_by_symbol[decision.symbol]
        execution = execution_by_identity.get(decision.event_identity)
        geometry_a, admission_a = _identity_a_geometry(
            decision=decision, execution=execution, quotes=quotes
        )
        pair_key = f"{decision.symbol}|CONFIRMED|{decision.trade_date.isoformat()}"
        confirmed_candidate = candidate_by_confirmation.get(
            (decision.symbol, decision.trade_date.isoformat())
        )
        a_entries.append(
            TradeEntry(
                geometry=geometry_a,
                admission=admission_a,
                pair_key=pair_key,
                eventual_status=getattr(confirmed_candidate, "eventual_status", None),
                resolution=getattr(confirmed_candidate, "resolution", None),
                depth_band=getattr(confirmed_candidate, "depth_band", None),
                time_half=getattr(confirmed_candidate, "time_half", None),
            )
        )
        geometry_b, admission_b = _identity_b_geometry(
            decision=decision,
            quotes=quotes,
            market_session_dates=market_session_dates,
            candidate_by_key=candidate_by_key,
        )
        b_entries.append(
            TradeEntry(
                geometry=geometry_b,
                admission=admission_b,
                pair_key=pair_key,
                eventual_status=getattr(confirmed_candidate, "eventual_status", None),
                resolution=getattr(confirmed_candidate, "resolution", None),
                depth_band=getattr(confirmed_candidate, "depth_band", None),
                time_half=getattr(confirmed_candidate, "time_half", None),
            )
        )

    c_entries: list[TradeEntry] = []
    confirmation_flags: dict[str, str] = {}
    for signal in signals[EXPERIMENTAL_POLICY]:
        candidate = candidate_by_key[signal.candidate_key]
        geometry, admission = _identity_c_geometry(
            candidate=candidate,
            signal=signal,
            quotes=quotes_by_symbol[candidate.symbol],
            decision_by_confirmation=decision_by_confirmation,
        )
        confirmation_flag = None
        if candidate.confirmed_index is not None:
            decision = decision_by_confirmation.get(
                (candidate.symbol, candidate.confirmed_date.isoformat())
            )
            if decision is None:
                confirmation_flag = FLAG_CONFIRMATION_DECISION_UNAVAILABLE
            elif not decision.targets:
                confirmation_flag = FLAG_NO_VALID_TARGET_AT_CONFIRMATION
        confirmation_flags[candidate.key] = confirmation_flag or ""
        c_entries.append(
            TradeEntry(
                geometry=geometry,
                admission=admission,
                eventual_status=candidate.eventual_status,
                resolution=candidate.resolution,
                depth_band=candidate.depth_band,
                time_half=candidate.time_half,
                confirmation_flag=confirmation_flag,
                pair_key=(
                    f"{candidate.symbol}|CONFIRMED|{candidate.confirmed_date.isoformat()}"
                    if candidate.confirmed_date is not None
                    else None
                ),
            )
        )

    replay_primary = {
        IDENTITY_A: _replay_identity(
            a_entries, quotes_by_symbol, preclose_by_symbol, target_exit_enabled=True
        ),
        IDENTITY_B: _replay_identity(
            b_entries, quotes_by_symbol, preclose_by_symbol, target_exit_enabled=True
        ),
        IDENTITY_C: _replay_identity(
            c_entries, quotes_by_symbol, preclose_by_symbol, target_exit_enabled=True
        ),
    }
    replay_secondary = {
        IDENTITY_A: _replay_identity(
            a_entries, quotes_by_symbol, preclose_by_symbol, target_exit_enabled=False
        ),
        IDENTITY_B: _replay_identity(
            b_entries, quotes_by_symbol, preclose_by_symbol, target_exit_enabled=False
        ),
        IDENTITY_C: _replay_identity(
            c_entries, quotes_by_symbol, preclose_by_symbol, target_exit_enabled=False
        ),
    }

    def outcomes_of(replay: Mapping[str, Any]) -> list[dict[str, Any]]:
        return list(replay[IDENTITY_A]["outcomes"]) + list(
            replay[IDENTITY_B]["outcomes"]
        ) + list(replay[IDENTITY_C]["outcomes"])

    primary_outcomes = outcomes_of(replay_primary)
    secondary_outcomes = outcomes_of(replay_secondary)
    roster_symbols = {
        market: sorted(
            item["canonical_symbol"] for item in manifest["symbols"] if item["market"] == market
        )
        for market in MARKETS
    }
    bootstrap: dict[str, Any] = {}
    for scenario in SCENARIO_IDS:
        bootstrap[scenario] = {
            "combined": _bootstrap(
                primary_outcomes,
                statistic_identities=IDENTITY_IDS,
                scenario=scenario,
                symbols=roster_symbols["CN"] + roster_symbols["US"],
            ),
            "per_market": {
                market: _bootstrap(
                    [row for row in primary_outcomes if row["market"] == market],
                    statistic_identities=IDENTITY_IDS,
                    scenario=scenario,
                    symbols=roster_symbols[market],
                )
                for market in MARKETS
            },
        }

    classification = _classify(
        protocol=protocol,
        outcomes=primary_outcomes,
        bootstrap=bootstrap,
        roster_symbols=roster_symbols,
    )
    document: dict[str, Any] = {
        "artifact_type": "setup01-early-entry-stage2-economic-validation",
        "artifact_version": PROTOCOL_VERSION,
        "status": classification["overall_classification"],
        "protocol": {
            "path": protocol_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": protocol_digest,
            "pinned_sha256": PINNED_PROTOCOL_SHA256,
            "registered_before_outcome_access": True,
            "selected_package": protocol["authorization"]["selected_package"],
        },
        "source_artifacts": {
            "stage1_protocol": _source_artifact(STAGE1_PROTOCOL_PATH),
            "stage1_result": _source_artifact(STAGE1_JSON_PATH),
            "decision_record": _source_artifact(DECISION_RECORD_PATH),
            "dataset_manifest": _source_artifact(dataset_manifest_path),
            "frozen_replay_input": _source_artifact(frozen_input_path),
            "dataset_version": DATASET_VERSION,
            "replay_aggregate_hash": replay_manifest.aggregate_hash,
            "universe_manifest_sha256": manifest["universe"]["manifest_sha256"],
            "universe_symbol_list_sha256": manifest["universe"]["symbol_list_sha256"],
        },
        "denominator": {
            "anchor_contexts": len(candidates),
            "armed_signals": len(signals[EXPERIMENTAL_POLICY]),
            "confirmed_events": len(confirmed_events),
            "checks": denominator_check,
            "cohort_matches_first_stage": True,
        },
        "production_funnel": production_funnel,
        "funnels": {
            "primary_policy": {
                identity: _funnel_report(replay_primary[identity])
                for identity in IDENTITY_IDS
            }
        },
        "results": {
            "primary_policy": {
                "combined": _identities_report(
                    {"outcomes": primary_outcomes}, scenario=SCENARIO_BASELINE
                ),
                "per_market": {
                    market: _identities_report(
                        {
                            "outcomes": [
                                row for row in primary_outcomes if row["market"] == market
                            ]
                        },
                        scenario=SCENARIO_BASELINE,
                    )
                    for market in MARKETS
                },
                "stress_costs": {
                    "combined": _identities_report(
                        {"outcomes": primary_outcomes}, scenario=SCENARIO_STRESS
                    ),
                    "per_market": {
                        market: _identities_report(
                            {
                                "outcomes": [
                                    row
                                    for row in primary_outcomes
                                    if row["market"] == market
                                ]
                            },
                            scenario=SCENARIO_STRESS,
                        )
                        for market in MARKETS
                    },
                },
            },
            "secondary_policy_no_target_exit": {
                "combined": _identities_report(
                    {"outcomes": secondary_outcomes}, scenario=SCENARIO_BASELINE
                ),
                "per_market": {
                    market: _identities_report(
                        {
                            "outcomes": [
                                row
                                for row in secondary_outcomes
                                if row["market"] == market
                            ]
                        },
                        scenario=SCENARIO_BASELINE,
                    )
                    for market in MARKETS
                },
            },
        },
        "uncertainty": bootstrap,
        "decision": classification,
        "paired_subset": _paired_subset(primary_outcomes, scenario=SCENARIO_BASELINE),
        "cost_model": {
            "scenarios": protocol["cost_model"]["scenarios"],
            "CN": protocol["cost_model"]["CN"],
            "US": protocol["cost_model"]["US"],
            "status": "REGISTERED_RESEARCH_ASSUMPTIONS_NOT_BROKER_FILLS",
        },
        "sizing": {
            "risk_fraction": protocol["position_sizing"]["risk_budget_per_trade"],
            "standardised_research_budget": protocol["position_sizing"][
                "standardised_research_budget"
            ],
            "status": protocol["position_sizing"]["budget_status"],
        },
        "limitations": [
            "event-level results are not a portfolio: no concurrency, budget path or holdings state is modelled",
            "portfolio drawdown is NOT_ESTIMABLE",
            "CN limit, suspension and lot checks are model-level checks without order-book, queue or real volume evidence",
            "US spread and slippage are scenario assumptions because the frozen payload carries no quotes",
            "the sample window overlaps Development and this sample was already used for the first-stage decision, so it is not a fresh untouched out-of-sample set",
        ],
        "controls": {
            "research_only": True,
            "production_strategy_unchanged": True,
            "portfolio_drawdown_estimated": False,
            "broker_fills_claimed": False,
            "final_oos_accessed": False,
            "real_holdings_accessed": False,
            "state_writes": 0,
            "sheets_writes": 0,
            "broker_orders": 0,
            "parameter_search_or_threshold_sweep": False,
            "sample_replaced_or_extended": False,
            "production_authorization": False,
        },
    }
    document["validation"] = _validate_document(document)
    json_output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown_output.write_text(render_markdown(document), encoding="utf-8", newline="\n")
    return document


def _validate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    controls = document["controls"]
    if controls["portfolio_drawdown_estimated"] or controls["broker_fills_claimed"]:
        raise ValueError("stage-2 artifact must not claim portfolio or broker results")
    if document["protocol"]["sha256"] != document["protocol"]["pinned_sha256"]:
        raise ValueError("stage-2 protocol hash is not the registered one")
    if not document["denominator"]["cohort_matches_first_stage"]:
        raise ValueError("stage-2 cohort does not match the first stage")
    for identity in IDENTITY_IDS:
        funnel = document["funnels"]["primary_policy"][identity]
        if funnel["admitted"] + sum(funnel["skip_counts"].values()) != funnel["eligible"]:
            raise ValueError(f"{identity} funnel is not conserved")
    return {
        "protocol_hash_matches_registration": True,
        "cohort_matches_first_stage": True,
        "funnels_conserved": True,
        "drawdown_estimated": False,
        "broker_fills_claimed": False,
    }


def _num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _dist(value: Mapping[str, Any]) -> str:
    if not value or not value.get("n"):
        return "-"
    return (
        f"mean {_num(value['mean'])} / median {_num(value['median'])} "
        f"[{_num(value['p10'])}..{_num(value['p90'])}] n={value['n']}"
    )


IDENTITY_LABELS = {
    IDENTITY_A: "A full incumbent Decision",
    IDENTITY_B: "B first-CONFIRMED structural comparator (not a strategy)",
    IDENTITY_C: "C ARMED + constrained PKG_B (research group)",
}


def render_markdown(document: Mapping[str, Any]) -> str:
    lines: list[str] = [
        "# SETUP_01 earlier entry - stage 2 economic validation V1",
        "",
        "> Research only. No production rule, state, Sheet or broker path is touched, no "
        "Final OOS or real holdings are read, and portfolio drawdown is not estimable.",
        "",
        f"- Protocol: `{document['artifact_version']}` (`{document['protocol']['sha256']}`)",
        f"- Status: **{document['status']}**",
        f"- Selected package: `{document['protocol']['selected_package']}`",
        f"- Denominator: {document['denominator']['anchor_contexts']} anchor contexts, "
        f"{document['denominator']['armed_signals']} ARMED signals, "
        f"{document['denominator']['confirmed_events']} first-CONFIRMED events",
        "",
        "## Decision",
        "",
        document["decision"]["reason"],
        "",
        "| market | realized A / B / C | mean net R C-A | mean net R C-B | floors failed |",
        "|---|---:|---:|---:|---|",
    ]
    for market in MARKETS:
        result = document["decision"]["per_market"][market]
        counts = result["realized_counts"]
        differences = result["differences_baseline"]
        lines.append(
            f"| {market} | {counts[IDENTITY_A]} / {counts[IDENTITY_B]} / "
            f"{counts[IDENTITY_C]} | "
            f"{_num(differences.get(f'{IDENTITY_C}_minus_{IDENTITY_A}'))} | "
            f"{_num(differences.get(f'{IDENTITY_C}_minus_{IDENTITY_B}'))} | "
            f"{', '.join(result['floors_failed']) or '-'} |"
        )

    pooled = document["decision"]["pooled_baseline_differences"]
    pooled_stress = document["decision"]["pooled_stress_differences"]
    pooled_dropped = document["decision"]["pooled_drop_count_leading_symbol_differences"]
    intervals = document["decision"]["pooled_bootstrap_intervals_baseline"]
    lines.extend(
        [
            "",
            "| pooled statistic (CN+US) | baseline | stress 25bp | drop leading symbol | bootstrap 95% baseline |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for key in sorted(pooled):
        interval = intervals.get(key, {})
        lines.append(
            f"| {key} | {_num(pooled.get(key))} | {_num(pooled_stress.get(key))} | "
            f"{_num(pooled_dropped.get(key))} | "
            f"[{_num(interval.get('lower'))}, {_num(interval.get('upper'))}] |"
        )

    lines.extend(
        [
            "",
            "## Funnels (conserved; all statuses retained)",
            "",
            "| identity | eligible | admitted | not executable at research budget | skip reasons |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for identity in IDENTITY_IDS:
        funnel = document["funnels"]["primary_policy"][identity]
        skips = ", ".join(f"{key}={value}" for key, value in funnel["skip_counts"].items())
        lines.append(
            f"| {IDENTITY_LABELS[identity]} | {funnel['eligible']} | {funnel['admitted']} | "
            f"{funnel['not_executable_at_research_budget']} | {skips or '-'} |"
        )

    production = document["production_funnel"]
    lines.extend(
        [
            "",
            f"Production first-CONFIRMED funnel: {production['confirmed_events']} events, "
            f"gate reasons {production['gate_reason_counts']}, execution outcomes "
            f"{production['execution_outcome_counts']}.",
        ]
    )

    for policy_key, title in (
        ("primary_policy", "Primary policy (T1 exit enabled)"),
        ("secondary_policy_no_target_exit", "Secondary policy (no target exit)"),
    ):
        lines.extend(["", f"## {title}", ""])
        for market in ("combined", *MARKETS):
            block = (
                document["results"][policy_key]["combined"]
                if market == "combined"
                else document["results"][policy_key]["per_market"][market]
            )
            lines.extend([f"### {market}", ""])
            lines.extend(
                [
                    "| identity | realized | censored | mean net R | median net R | mean net return | median net return | cost /R | losing share | <= -1R share | median days |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for identity in IDENTITY_IDS:
                report = block[identity]
                lines.append(
                    f"| {identity} | {report['realized_trades']} | {report['censored_trades']} | "
                    f"{_num(report['net_r']['mean'])} | {_num(report['net_r']['median'])} | "
                    f"{_num(report['net_return']['mean'], 4)} | "
                    f"{_num(report['net_return']['median'], 4)} | "
                    f"{_num(report['cost_r']['median'])} | "
                    f"{_num(report['losing_share'])} | "
                    f"{_num(report['share_at_or_below_minus_one_r'])} | "
                    f"{_num(report['position_days']['median'], 1)} |"
                )
            lines.extend(["", "Exit reasons and status composition", ""])
            for identity in IDENTITY_IDS:
                report = block[identity]
                lines.append(
                    f"- `{identity}`: exits {report['exit_reason_counts']}; status "
                    f"{report['eventual_status_composition']}; censored {report['censored_trades']}."
                )
            lines.append("")

    stress = document["results"]["primary_policy"]["stress_costs"]["combined"]
    lines.extend(["", "## Cost scenario sensitivity (pooled)", ""])
    lines.extend(
        [
            "| identity | mean net R baseline | mean net R stress | cost /R median baseline | cost /R median stress |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    baseline_combined = document["results"]["primary_policy"]["combined"]
    for identity in IDENTITY_IDS:
        lines.append(
            f"| {identity} | {_num(baseline_combined[identity]['net_r']['mean'])} | "
            f"{_num(stress[identity]['net_r']['mean'])} | "
            f"{_num(baseline_combined[identity]['cost_r']['median'])} | "
            f"{_num(stress[identity]['cost_r']['median'])} |"
        )

    lines.extend(
        [
            "",
            "## Paired subset on shared confirmed lifecycles (descriptive)",
            "",
            "| pair | paired lifecycles | mean net R difference | left mean net R | right mean net R |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for key, value in document["paired_subset"].items():
        lines.append(
            f"| {key} | {value['paired_lifecycles']} | "
            f"{_num(value['net_r_difference']['mean'])} | "
            f"{_num(value['left_net_r']['mean'])} | "
            f"{_num(value['right_net_r']['mean'])} |"
        )

    lines.extend(
        [
            "",
            "## Censored-inclusive sensitivity (final-close valuation, not realized)",
            "",
            "| identity | realized mean net R | censored-inclusive mean net R | n |",
            "|---|---:|---:|---:|",
        ]
    )
    for identity in IDENTITY_IDS:
        report = baseline_combined[identity]
        lines.append(
            f"| {identity} | {_num(report['net_r']['mean'])} | "
            f"{_num(report['including_censored_at_final_close']['net_r']['mean'])} | "
            f"{report['including_censored_at_final_close']['n']} |"
        )

    lines.extend(["", "## Registered assumptions and boundaries", ""])
    lines.append(f"- {document['decision']['censoring_caveat']}")
    for item in document["limitations"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "- CN commission (2.5bp per side, minimum 5 CNY) and the US commission of 0 are "
            "research assumptions, not verified account rates; the CN sell stamp duty is applied "
            "as 10bp before 2023-08-28 and 5bp from 2023-08-28; the CN transfer fee is left "
            "UNKNOWN_NOT_MODELED.",
            "- Fill model: an exit is executed at the next valid session OPEN when it is "
            "scheduled by the exit policy, at the stop price when the stop is touched "
            "intraday, and at T1 when the target is reached; the execution stop always takes "
            "precedence over a target touch on the same bar.",
            "- The T1 exit is a research-only assumption; frozen Position Management treats "
            "targets as diagnostic and never auto-sells. The secondary policy removes it.",
            "",
            "Status: `" + str(document["status"]) + "`",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--dataset-manifest", type=Path, default=DATASET_MANIFEST_PATH)
    parser.add_argument("--frozen-input", type=Path, default=FROZEN_INPUT_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args(argv)
    document = run_validation(
        protocol_path=args.protocol,
        dataset_manifest_path=args.dataset_manifest,
        frozen_input_path=args.frozen_input,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "denominator": document["denominator"]["anchor_contexts"],
                "pooled_differences": document["decision"][
                    "pooled_baseline_differences"
                ],
                "final_oos_accessed": document["controls"]["final_oos_accessed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

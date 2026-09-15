"""Research-only SETUP_01 first-reward boundary counterfactual.

This module answers whether the nearest T-known ``CONFIRMED_SWING_HIGH``
should remain in the formal first target.  It is deliberately a small
research adapter around the existing causal replay, Decision evaluator,
exact T+1 executor, and Position Management replay.  It does not alter any
production module or Decision semantics.

P0 is the current formal policy.  P1 selects the nearest existing
``WAVE3_FIB_EXTENSION`` candidate as a research-only T1 for the fixed
``NEAR_SWING_ONLY`` sample from the preceding geometry artifact.  P1 never
creates a target, uses a future signal, or falls back to T2/T3.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, timedelta
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.development_holdout_dataset import load_frozen_holdout
from research.development_holdout_universe import load_holdout_universe_manifest
from research.market_sessions import (
    DEVELOPMENT_SESSION_IDENTITY,
    build_market_session_dates,
)
from trading.models import DecisionAction
from trading.paper_lifecycle import calculate_performance
from trading.position_management import (
    PositionExitReason,
    PositionReplay,
    position_origin_from_execution,
    replay_position,
)
from trading.risk import (
    HIGH_ASYMMETRY,
    MIN_TARGET_UPSIDE_PCT,
    relative_distance_pct,
    risk_reward,
    target_upside_band,
    target_upside_pct,
)
from trading.setup01_decision import (
    EXECUTED,
    SETUP01_DECISION_PROTOCOL_VERSION,
    Setup01Decision,
    Setup01DecisionGateReason,
    Setup01Execution,
    Setup01TargetCandidate,
    _candidate_extension_ratio,
    _candidate_has_source,
    _targets_are_reasonable,
    evaluate_setup01_decision_stream,
    execute_setup01_t1_open,
    setup01_target_projection,
)
from trading.setup01_replay import Setup01ReplayEvent, replay_setup01_history


PROTOCOL_VERSION = (
    "SETUP-01-CONFIRMED-SWING-HIGH-FIRST-REWARD-BOUNDARY-COUNTERFACTUAL-"
    "2026-09-15-v1"
)
P0_POLICY = "P0_CURRENT"
P1_POLICY = "P1_FIB_FORMAL_T1_RESEARCH_ONLY"
DECISION_CLASSIFICATION = "INSUFFICIENT_EVIDENCE"
NEAR_SWING_ONLY = "NEAR_SWING_ONLY"
EXPECTED_CONFIRMED = 745
EXPECTED_NEAR_SWING_ONLY = 117
EXPECTED_BOTH_NEAR = 63
EXPECTED_SMALL_WAVE_FIB = 18

DEFAULT_DATASET_MANIFEST = (
    PROJECT_ROOT / "research" / "development_holdout" / "dataset_manifest.json"
)
DEFAULT_REPLAY_INPUT = (
    PROJECT_ROOT
    / "artifacts"
    / "phase5j_v3_development_holdout"
    / "development_holdout_replay_input.jsonl.gz"
)
DEFAULT_REPLAY_WRAPPER = (
    PROJECT_ROOT / "research" / "development_holdout" / "replay_manifest.json"
)
DEFAULT_UNIVERSE_MANIFEST = (
    PROJECT_ROOT / "research" / "development_holdout" / "universe_manifest.json"
)
DEFAULT_PRIOR_GEOMETRY = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_wave2_to_wave3_structure_scale_diagnostic_v1.json"
)
DEFAULT_JSON_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_confirmed_swing_high_first_reward_boundary_counterfactual_v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_confirmed_swing_high_first_reward_boundary_counterfactual_v1.md"
)

STOP_EXIT_REASONS = frozenset(
    {
        PositionExitReason.EXIT_GAP_BELOW_STOP,
        PositionExitReason.EXIT_STOP_TRIGGERED,
    }
)


def _value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date,)):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
            allow_nan=False,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _sha256_json(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _candidate_dict(candidate: Setup01TargetCandidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "price": float(candidate.price),
        "source": candidate.source,
        "reason": candidate.reason,
        "provenance": [
            {
                "source": item.source,
                "pivot_date": _date_text(item.pivot_date),
                "confirmed_date": _date_text(item.confirmed_date),
                "extension_ratio": item.extension_ratio,
            }
            for item in candidate.provenance
        ],
    }


def _fib_candidates(decision: Setup01Decision) -> tuple[Setup01TargetCandidate, ...]:
    return tuple(
        candidate
        for candidate in decision.target_candidates
        if _candidate_has_source(candidate, "WAVE3_FIB_EXTENSION")
        and _candidate_extension_ratio(candidate) is not None
        and decision.planned_entry is not None
        and candidate.price > decision.planned_entry
    )


def _nearest_fib_candidate(
    decision: Setup01Decision,
) -> Setup01TargetCandidate | None:
    candidates = _fib_candidates(decision)
    return min(
        candidates,
        key=lambda item: (
            float(item.price),
            _candidate_extension_ratio(item) or math.inf,
            item.source,
        ),
        default=None,
    )


def _replay_events(
    symbol_quotes: Mapping[str, Sequence[Quote]],
) -> tuple[Setup01ReplayEvent, ...]:
    events: list[Setup01ReplayEvent] = []
    for symbol in sorted(symbol_quotes):
        report = replay_setup01_history(list(symbol_quotes[symbol]))
        events.extend(report.events)
    return tuple(
        sorted(events, key=lambda item: (item.trade_date, item.market, item.symbol, item.event_identity))
    )


def _load_prior_geometry(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("artifact_type") != "SETUP_01_WAVE2_WAVE3_STRUCTURE_SCALE_DIAGNOSTIC":
        raise ValueError("prior geometry artifact type changed")
    controls = document.get("controls", {})
    forbidden_controls = (
        "final_oos_accessed",
        "outcome_accessed",
        "t_plus_1_executor_called",
        "production_parameters_modified",
        "production_semantics_modified",
        "new_production_gate_added",
        "new_threshold_selected",
        "target_redefined",
        "t2_or_t3_substituted",
    )
    if any(controls.get(name) for name in forbidden_controls):
        raise ValueError("prior geometry artifact contains a prohibited control")
    events = document.get("events")
    if not isinstance(events, list) or len(events) != EXPECTED_CONFIRMED:
        raise ValueError("prior geometry event count changed")
    by_identity: dict[str, dict[str, Any]] = {}
    for row in events:
        identity = str(row.get("event_identity", ""))
        if not identity or identity in by_identity:
            raise ValueError("prior geometry event identities are not unique")
        by_identity[identity] = row
    summary = document.get("summary", {})
    category_results = summary.get("category_results", {})
    observed = {
        name: int(category_results.get(name, {}).get("count", -1))
        for name in (NEAR_SWING_ONLY, "BOTH_NEAR", "SMALL_WAVE_FIB")
    }
    expected = {
        NEAR_SWING_ONLY: EXPECTED_NEAR_SWING_ONLY,
        "BOTH_NEAR": EXPECTED_BOTH_NEAR,
        "SMALL_WAVE_FIB": EXPECTED_SMALL_WAVE_FIB,
    }
    if observed != expected:
        raise ValueError(f"prior geometry category conservation changed: {observed}")
    if sum(observed.values()) != int(summary.get("formal_t1_lt_5_count", -1)):
        raise ValueError("prior geometry low-T1 category conservation changed")
    return document, by_identity


def _p0_signature(decision: Setup01Decision) -> tuple[Any, ...]:
    """Return the immutable P0 fields used for the no-mutation assertion."""

    candidates = tuple(
        (
            float(candidate.price),
            candidate.source,
            tuple(
                (
                    item.source,
                    _date_text(item.pivot_date),
                    _date_text(item.confirmed_date),
                    item.extension_ratio,
                )
                for item in candidate.provenance
            ),
        )
        for candidate in decision.target_candidates
    )
    return (
        decision.event_identity,
        decision.symbol,
        decision.market,
        decision.trade_date,
        _value(decision.event_type),
        decision.decision_calculable,
        _value(decision.action),
        str(_value(decision.gate_reason)),
        decision.gate_detail,
        decision.atr14,
        decision.wave1_origin,
        decision.confirmation_level,
        decision.planned_entry,
        decision.entry_zone_low,
        decision.entry_zone_high,
        decision.structural_invalidation,
        decision.wave_scenario_invalidation,
        decision.execution_stop,
        candidates,
        tuple(decision.targets),
        decision.target_reasonableness_checked,
        decision.target_reasonableness_passed,
        decision.rr,
        decision.target_upside_pct,
        decision.target_upside_band,
        decision.minimum_target_upside_pct,
    )


def _p0_prior_parity(
    decisions: Sequence[Setup01Decision],
    prior_by_identity: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Cross-bind P0 gate/action identities to the prior outcome-free artifact."""

    if len(decisions) != len(prior_by_identity):
        raise ValueError("P0 decision count does not match prior geometry artifact")
    mismatches: list[dict[str, Any]] = []
    for decision in decisions:
        prior = prior_by_identity.get(decision.event_identity)
        if prior is None:
            mismatches.append({"event_identity": decision.event_identity, "field": "missing_prior_row"})
            continue
        current_reason = str(_value(decision.gate_reason))
        current_action = str(_value(decision.action))
        if current_reason != str(prior.get("formal_decision_gate_reason")):
            mismatches.append(
                {
                    "event_identity": decision.event_identity,
                    "field": "formal_decision_gate_reason",
                    "current": current_reason,
                    "prior": prior.get("formal_decision_gate_reason"),
                }
            )
        if current_action != str(prior.get("formal_decision_action")):
            mismatches.append(
                {
                    "event_identity": decision.event_identity,
                    "field": "formal_decision_action",
                    "current": current_action,
                    "prior": prior.get("formal_decision_action"),
                }
            )
        prior_t1 = _number(prior.get("formal_t1_price"))
        current_t1 = float(decision.targets[0]) if decision.targets else None
        if (prior_t1 is None) != (current_t1 is None) or (
            prior_t1 is not None
            and current_t1 is not None
            and not math.isclose(prior_t1, current_t1, rel_tol=0.0, abs_tol=1e-9)
        ):
            mismatches.append(
                {
                    "event_identity": decision.event_identity,
                    "field": "formal_t1_price",
                    "current": current_t1,
                    "prior": prior_t1,
                }
            )
        prior_source = str(prior.get("formal_t1_source") or "")
        current_source = (
            decision.target_candidates[0].source
            if decision.target_candidates and current_t1 is not None
            else ""
        )
        if prior_source and prior_source not in current_source.split("+"):
            mismatches.append(
                {
                    "event_identity": decision.event_identity,
                    "field": "formal_t1_source",
                    "current": current_source,
                    "prior": prior_source,
                }
            )
    return {
        "event_count": len(decisions),
        "gate_action_target_parity": not mismatches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def _p0_funnel(
    decisions: Sequence[Setup01Decision],
    executions: Sequence[Setup01Execution],
) -> dict[str, Any]:
    execution_counts = Counter(str(_value(item.outcome)) for item in executions)
    gate_counts = Counter(str(_value(item.gate_reason)) for item in decisions)
    return {
        "confirmed_events": len(decisions),
        "decision_rows": len(decisions),
        "decision_calculable": sum(item.decision_calculable for item in decisions),
        "entry_allowed": sum(item.action is DecisionAction.ENTRY_ALLOWED for item in decisions),
        "no_trade": sum(item.action is DecisionAction.NO_TRADE for item in decisions),
        "t1_execution_attempts": len(executions),
        "executed": execution_counts.get(EXECUTED, 0),
        "decision_gate_reason_counts": dict(sorted(gate_counts.items())),
        "execution_outcome_counts": dict(sorted(execution_counts.items())),
    }


def _p1_no_trade(
    decision: Setup01Decision,
    *,
    reason: Setup01DecisionGateReason,
    detail: str,
    target_candidates: tuple[Setup01TargetCandidate, ...] = (),
    targets: tuple[float, ...] = (),
    rr: Any = None,
    target_upside: float | None = None,
    reasonableness_checked: bool = False,
    reasonableness_passed: bool | None = None,
) -> Setup01Decision:
    return replace(
        decision,
        action=DecisionAction.NO_TRADE,
        gate_reason=reason,
        gate_detail=detail,
        target_candidates=target_candidates,
        targets=targets,
        target_reasonableness_checked=reasonableness_checked,
        target_reasonableness_passed=reasonableness_passed,
        rr=rr,
        target_upside_pct=target_upside,
        target_upside_band=(target_upside_band(target_upside) if target_upside is not None else None),
        position_size=None,
    )


def _build_p1_decision(
    p0: Setup01Decision,
    event: Setup01ReplayEvent,
) -> Setup01Decision:
    """Derive P1 only from P0's T-known candidate provenance and geometry."""

    fib = _nearest_fib_candidate(p0)
    if fib is None:
        return _p1_no_trade(
            p0,
            reason=Setup01DecisionGateReason.NO_VALID_TARGET,
            detail="P1 没有既有、T 日已知且高于 planned_entry 的 Wave3 Fib extension",
        )
    if p0.planned_entry is None or p0.execution_stop is None:
        return _p1_no_trade(
            p0,
            reason=Setup01DecisionGateReason.INVALID_STRUCTURE,
            detail="P1 无法复用 P0 的 planned_entry / execution_stop",
        )

    p1_target = float(fib.price)
    upside = target_upside_pct(p1_target, float(p0.planned_entry))
    p1_rr = risk_reward(float(p0.planned_entry), float(p0.execution_stop), (p1_target,))
    checked = p1_rr.quality == HIGH_ASYMMETRY
    passed: bool | None = None
    snapshot = event.setup01
    if checked:
        passed = _targets_are_reasonable(
            (fib,),
            entry=float(p0.planned_entry),
            origin=float(p0.wave1_origin) if p0.wave1_origin is not None else math.nan,
            peak=float(snapshot.wave1_peak.price) if snapshot.wave1_peak is not None else math.nan,
            wave2_low=float(snapshot.wave2_low.price) if snapshot.wave2_low is not None else math.nan,
        )
        if not passed:
            return _p1_no_trade(
                p0,
                reason=Setup01DecisionGateReason.NO_VALID_TARGET,
                detail="P1 >5R Fib target 未通过既有 provenance/geometry sanity check",
                target_candidates=(fib,),
                targets=(p1_target,),
                rr=p1_rr,
                target_upside=upside,
                reasonableness_checked=True,
                reasonableness_passed=False,
            )
    if upside < MIN_TARGET_UPSIDE_PCT:
        return _p1_no_trade(
            p0,
            reason=Setup01DecisionGateReason.TARGET_UPSIDE_BELOW_MINIMUM,
            detail="P1 Fib T1 gross upside < existing 5% minimum",
            target_candidates=(fib,),
            targets=(p1_target,),
            rr=p1_rr,
            target_upside=upside,
            reasonableness_checked=checked,
            reasonableness_passed=passed,
        )
    if p1_rr.rr_ratios[0] < 2.0:
        return _p1_no_trade(
            p0,
            reason=Setup01DecisionGateReason.RR_BELOW_MINIMUM,
            detail="P1 Fib T1 first-target gross R/R < existing 2R minimum",
            target_candidates=(fib,),
            targets=(p1_target,),
            rr=p1_rr,
            target_upside=upside,
            reasonableness_checked=checked,
            reasonableness_passed=passed,
        )
    return replace(
        p0,
        action=DecisionAction.ENTRY_ALLOWED,
        gate_reason=Setup01DecisionGateReason.ENTRY_ALLOWED,
        gate_detail="P1 research-only Fib T1 passes existing 5% and 2R gates",
        target_candidates=(fib,),
        targets=(p1_target,),
        target_reasonableness_checked=checked,
        target_reasonableness_passed=passed,
        rr=p1_rr,
        target_upside_pct=upside,
        target_upside_band=target_upside_band(upside),
        position_size=None,
    )


def _stage_reason(counter: dict[str, Counter[str]], stage: str, reason: str) -> None:
    counter.setdefault(stage, Counter())[reason] += 1


def _build_p1_funnel(
    sample_events: Sequence[Setup01ReplayEvent],
    p0_by_identity: Mapping[str, Setup01Decision],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    exclusions: dict[str, Counter[str]] = {}
    counts = Counter()
    for event in sample_events:
        p0 = p0_by_identity[event.event_identity]
        p1 = _build_p1_decision(p0, event)
        counts["fixed_sample"] += 1
        has_fib = bool(p1.targets) and _nearest_fib_candidate(p0) is not None
        if has_fib:
            counts["fib_t1_available"] += 1
        else:
            _stage_reason(exclusions, "fib_t1_available", str(_value(p1.gate_reason)))
        upside_pass = has_fib and p1.target_upside_pct is not None and p1.target_upside_pct >= MIN_TARGET_UPSIDE_PCT
        if upside_pass:
            counts["fib_t1_upside_ge_5"] += 1
        elif has_fib:
            _stage_reason(exclusions, "fib_t1_upside_ge_5", str(_value(p1.gate_reason)))
        rr_pass = upside_pass and p1.rr is not None and p1.rr.rr_ratios[0] >= 2.0
        if rr_pass:
            counts["rr_ge_2"] += 1
        elif upside_pass:
            _stage_reason(exclusions, "rr_ge_2", str(_value(p1.gate_reason)))
        entry_allowed = p1.action is DecisionAction.ENTRY_ALLOWED and rr_pass
        if entry_allowed:
            counts["entry_allowed_research"] += 1
        elif rr_pass:
            _stage_reason(exclusions, "entry_allowed_research", str(_value(p1.gate_reason)))
        execution: Setup01Execution | None = None
        replay: PositionReplay | None = None
        if entry_allowed:
            execution = execute_setup01_t1_open(
                p1,
                quotes_by_symbol[event.symbol],
                market_session_dates=market_session_dates,
            )
        exact_open = execution is not None and execution.execution_date is not None and execution.t1_open is not None
        if exact_open:
            counts["exact_t_plus_1_open_eligible"] += 1
        elif entry_allowed:
            _stage_reason(
                exclusions,
                "exact_t_plus_1_open_eligible",
                str(_value(execution.outcome)) if execution is not None else "NOT_ENTRY_ALLOWED",
            )
        executed = execution is not None and execution.outcome == EXECUTED and execution.actual_entry is not None
        if executed:
            counts["executed_research"] += 1
            origin = position_origin_from_execution("SETUP_01", event, p1, execution)
            if origin is None:
                raise ValueError("P1 EXECUTED row did not produce a PositionOrigin")
            replay = replay_position(origin, quotes_by_symbol[event.symbol])
        elif exact_open:
            _stage_reason(
                exclusions,
                "executed_research",
                str(_value(execution.outcome)) if execution is not None else "NOT_ENTRY_ALLOWED",
            )
        rows.append(
            {
                "event": event,
                "p0": p0,
                "p1": p1,
                "execution": execution,
                "replay": replay,
                "fib_t1_available": has_fib,
                "fib_t1_upside_ge_5": upside_pass,
                "rr_ge_2": rr_pass,
                "entry_allowed_research": entry_allowed,
                "exact_t_plus_1_open_eligible": exact_open,
                "executed_research": executed,
            }
        )
    funnel = {
        "stages": {key: counts[key] for key in (
            "fixed_sample",
            "fib_t1_available",
            "fib_t1_upside_ge_5",
            "rr_ge_2",
            "entry_allowed_research",
            "exact_t_plus_1_open_eligible",
            "executed_research",
        )},
        "stage_exclusion_reasons": {
            stage: dict(sorted(counter.items()))
            for stage, counter in sorted(exclusions.items())
        },
        "research_entry_execution_outcome_counts": dict(
            sorted(
                Counter(
                    str(_value(row["execution"].outcome))
                    for row in rows
                    if row["entry_allowed_research"] and row["execution"] is not None
                ).items()
            )
        ),
        "terminal_outcome_distribution": dict(
            sorted(
                Counter(
                    _terminal_outcome(row["replay"])
                    for row in rows
                    if row["replay"] is not None
                ).items()
            )
        ),
    }
    return funnel, rows


def _stop_date(replay: PositionReplay) -> date | None:
    for day in replay.days:
        if day.exit_reason in STOP_EXIT_REASONS:
            return day.trade_date
    return None


def _terminal_outcome(replay: PositionReplay | None) -> str | None:
    if replay is None:
        return None
    if replay.exit_reason is None:
        return "OPEN_CENSORED"
    return f"CLOSED_{replay.exit_reason.value}"


def _realized_gross_r(replay: PositionReplay | None) -> float | None:
    if replay is None or replay.exit_price is None:
        return None
    return (float(replay.exit_price) - replay.origin.actual_entry) / replay.origin.one_r


def _quote_dates(quotes: Sequence[Quote]) -> dict[date, Quote]:
    result: dict[date, Quote] = {}
    for quote in quotes:
        if quote.trade_date in result:
            raise ValueError(f"duplicate quote date for {quote.symbol}: {quote.trade_date}")
        result[quote.trade_date] = quote
    return result


def _obstacle_path(
    replay: PositionReplay,
    quotes_by_date: Mapping[date, Quote],
    obstacle_price: float | None,
) -> dict[str, Any]:
    """Classify obstacle ordering using Position Management's stop-first days."""

    actual_entry = replay.origin.actual_entry
    if obstacle_price is None or not math.isfinite(float(obstacle_price)):
        return {
            "status": "NO_OBSTACLE_AVAILABLE",
            "gap_above_at_entry": None,
            "cleared_after_entry_before_stop": None,
            "stop_before_obstacle_clear": None,
            "obstacle_clear_date": None,
            "stop_date": _date_text(_stop_date(replay)),
            "same_bar_stop_first_applied": False,
        }
    obstacle = float(obstacle_price)
    if actual_entry > obstacle:
        return {
            "status": "GAP_ABOVE_AT_ENTRY",
            "gap_above_at_entry": True,
            "cleared_after_entry_before_stop": None,
            "stop_before_obstacle_clear": None,
            "obstacle_clear_date": None,
            "stop_date": _date_text(_stop_date(replay)),
            "same_bar_stop_first_applied": False,
        }

    stop_date = _stop_date(replay)
    clear_date: date | None = None
    same_bar_excluded = False
    for day in replay.days:
        quote = quotes_by_date.get(day.trade_date)
        if quote is None:
            raise ValueError(f"position replay day has no matching quote: {day.trade_date}")
        if not day.position_open_at_close:
            if day.exit_reason in STOP_EXIT_REASONS and float(quote.high) >= obstacle:
                same_bar_excluded = True
            continue
        if float(quote.high) >= obstacle:
            clear_date = day.trade_date
            break

    if clear_date is not None and (stop_date is None or clear_date < stop_date):
        status = (
            "CLEARED_BEFORE_STOP"
            if stop_date is not None
            else "CLEARED_BEFORE_TERMINAL_WITHOUT_STOP"
        )
        clear_before_stop = True
        stop_before_clear = False
    elif stop_date is not None:
        status = "STOP_BEFORE_OBSTACLE_CLEAR"
        clear_before_stop = False
        stop_before_clear = True
    else:
        status = "AMBIGUOUS_NO_CLEAR_NO_STOP"
        clear_before_stop = False
        stop_before_clear = False
    return {
        "status": status,
        "gap_above_at_entry": False,
        "cleared_after_entry_before_stop": clear_before_stop,
        "stop_before_obstacle_clear": stop_before_clear,
        "obstacle_clear_date": _date_text(clear_date),
        "stop_date": _date_text(stop_date),
        "same_bar_stop_first_applied": same_bar_excluded,
    }


def _fib_path(
    replay: PositionReplay,
    quotes_by_date: Mapping[date, Quote],
    fib_price: float,
) -> dict[str, Any]:
    stop_date = _stop_date(replay)
    hit_date: date | None = None
    same_bar_excluded = False
    for day in replay.days:
        quote = quotes_by_date.get(day.trade_date)
        if quote is None:
            raise ValueError(f"position replay day has no matching quote: {day.trade_date}")
        if not day.position_open_at_close:
            if day.exit_reason in STOP_EXIT_REASONS and float(quote.high) >= fib_price:
                same_bar_excluded = True
            continue
        if float(quote.high) >= fib_price:
            hit_date = day.trade_date
            break
    if hit_date is not None and (stop_date is None or hit_date < stop_date):
        status = "FIB_HIT_BEFORE_STOP"
        hit_before_stop = True
        stop_before_hit = False
    elif stop_date is not None:
        status = "STOP_BEFORE_FIB_HIT"
        hit_before_stop = False
        stop_before_hit = True
    else:
        status = "FIB_NOT_REACHED_BEFORE_TERMINAL"
        hit_before_stop = False
        stop_before_hit = False
    return {
        "status": status,
        "fib_t1_hit_before_stop": hit_before_stop,
        "stop_before_fib_t1": stop_before_hit,
        "fib_hit_date": _date_text(hit_date),
        "stop_date": _date_text(stop_date),
        "same_bar_stop_first_applied": same_bar_excluded,
    }


def _p1_detail(row: Mapping[str, Any], quotes: Sequence[Quote]) -> dict[str, Any]:
    p0 = row["p0"]
    p1 = row["p1"]
    execution = row["execution"]
    replay = row["replay"]
    if not isinstance(execution, Setup01Execution) or not isinstance(replay, PositionReplay):
        raise ValueError("P1 detail requires an executed research row")
    projection = setup01_target_projection(p0)
    overhead = projection.get("nearest_overhead_confirmed_swing_high")
    overhead_price = _number(projection.get("nearest_overhead_confirmed_swing_high_price"))
    fib_candidate = p1.target_candidates[0] if p1.target_candidates else None
    if fib_candidate is None or overhead_price is None or execution.actual_entry is None:
        raise ValueError("executed P1 row is missing Fib T1 or overhead swing provenance")
    actual_entry = float(execution.actual_entry)
    fib_price = float(fib_candidate.price)
    quote_by_date = _quote_dates(quotes)
    obstacle_path = _obstacle_path(replay, quote_by_date, overhead_price)
    fib_path = _fib_path(replay, quote_by_date, fib_price)
    return {
        "event_identity": execution.event_identity,
        "symbol": execution.symbol,
        "market": execution.market,
        "T_date": _date_text(execution.trade_date),
        "T_plus_1_entry_date": _date_text(execution.execution_date),
        "actual_entry": actual_entry,
        "execution_stop": float(p1.execution_stop) if p1.execution_stop is not None else None,
        "original_overhead_confirmed_swing_high_price": overhead_price,
        "original_overhead_confirmed_swing_high_provenance": overhead.get("provenance", []),
        "overhead_distance": overhead_price - actual_entry,
        "overhead_distance_pct_from_actual_entry": relative_distance_pct(overhead_price, actual_entry),
        "research_fib_t1_price": fib_price,
        "research_fib_t1_ratio": _candidate_extension_ratio(fib_candidate),
        "research_fib_t1_provenance": _candidate_dict(fib_candidate)["provenance"],
        "fib_t1_distance": fib_price - actual_entry,
        "fib_t1_distance_pct_from_actual_entry": relative_distance_pct(fib_price, actual_entry),
        "t_plus_1_open_already_gapped_above_swing_high": obstacle_path["gap_above_at_entry"],
        "swing_high_cleared_after_entry_before_stop": obstacle_path["cleared_after_entry_before_stop"],
        "stop_reached_before_swing_high_cleared": obstacle_path["stop_before_obstacle_clear"],
        "fib_t1_reached_before_stop": fib_path["fib_t1_hit_before_stop"],
        "obstacle_path": obstacle_path,
        "fib_path": fib_path,
        "terminal_outcome": _terminal_outcome(replay),
        "realized_gross_R": _realized_gross_r(replay),
        "holding_sessions": replay.position_days,
        "exit_date": _date_text(replay.exit_date),
        "exit_reason": _value(replay.exit_reason),
        "exit_price": replay.exit_price,
    }


def _p0_executed_detail(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    execution = row["execution"]
    replay = row["replay"]
    if not isinstance(execution, Setup01Execution) or not isinstance(replay, PositionReplay):
        raise ValueError("P0 context detail requires an executed row")
    return {
        "event_identity": execution.event_identity,
        "symbol": execution.symbol,
        "market": execution.market,
        "T_date": _date_text(execution.trade_date),
        "entry_date": _date_text(execution.execution_date),
        "actual_entry": execution.actual_entry,
        "formal_t1": row["p0"].targets[0] if row["p0"].targets else None,
        "terminal_outcome": _terminal_outcome(replay),
        "realized_gross_R": _realized_gross_r(replay),
        "holding_sessions": replay.position_days,
        "exit_date": _date_text(replay.exit_date),
        "exit_reason": _value(replay.exit_reason),
        "exit_price": replay.exit_price,
    }


def _performance_summary(details: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [
        item["realized_gross_R"]
        for item in details
        if _number(item.get("realized_gross_R")) is not None
    ]
    ledger_rows = [
        {
            "event_identity": str(item["event_identity"]),
            "status": "CLOSED" if item.get("realized_gross_R") is not None else "OPEN",
            "realized_r": item.get("realized_gross_R"),
        }
        for item in details
    ]
    stats = calculate_performance(ledger_rows)
    positive = sum(float(value) for value in values if float(value) > 0)
    negative = sum(float(value) for value in values if float(value) < 0)
    holding_sessions = [
        value
        for item in details
        if (value := _number(item.get("holding_sessions"))) is not None
    ]
    stop_outs = sum(
        str(item.get("exit_reason")) in {reason.value for reason in STOP_EXIT_REASONS}
        for item in details
    )
    terminal = Counter(str(item.get("terminal_outcome")) for item in details)
    return {
        "executed": len(details),
        "closed": int(stats.closed),
        "open_censored": int(stats.open),
        "wins": int(stats.wins),
        "losses": int(stats.losses),
        "flats": int(stats.flats),
        "gross_total_R": sum(float(value) for value in values) if values else None,
        "gross_positive_R": positive if values else None,
        "gross_negative_R": negative if values else None,
        "gross_expectancy_R": stats.average_r,
        "median_realized_gross_R": stats.median_r,
        "gross_win_rate": stats.win_rate,
        "gross_profit_factor": (positive / abs(negative) if negative < 0 else None),
        "stop_out_count": stop_outs,
        "stop_out_rate": _rate(stop_outs, len(details)),
        "average_holding_sessions": (
            sum(holding_sessions) / len(holding_sessions)
            if holding_sessions
            else None
        ),
        "terminal_outcome_distribution": dict(sorted(terminal.items())),
        "metrics_are_gross_no_transaction_costs": True,
        "open_censored_excluded_from_closed_performance": True,
    }


def _obstacle_summary(details: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    paths = [item["obstacle_path"] for item in details]
    gap_count = sum(item.get("status") == "GAP_ABOVE_AT_ENTRY" for item in paths)
    usable = [item for item in paths if item.get("status") != "NO_OBSTACLE_AVAILABLE" and not item.get("gap_above_at_entry")]
    clear_count = sum(bool(item.get("cleared_after_entry_before_stop")) for item in usable)
    stop_before_count = sum(bool(item.get("stop_before_obstacle_clear")) for item in usable)
    ambiguous_count = sum(item.get("status", "").startswith("AMBIGUOUS") for item in usable)
    same_bar_count = sum(bool(item.get("same_bar_stop_first_applied")) for item in paths)
    return {
        "executed_with_overhead_obstacle": len(paths),
        "gap_above_obstacle_at_entry_count": gap_count,
        "gap_above_obstacle_at_entry_rate": _rate(gap_count, len(paths)),
        "non_gap_obstacle_path_denominator": len(usable),
        "obstacle_clear_before_stop_count": clear_count,
        "obstacle_clear_before_stop_rate_non_gap": _rate(clear_count, len(usable)),
        "stop_before_obstacle_clear_count": stop_before_count,
        "stop_before_obstacle_clear_rate_non_gap": _rate(stop_before_count, len(usable)),
        "ambiguous_count_non_gap": ambiguous_count,
        "ambiguous_rate_non_gap": _rate(ambiguous_count, len(usable)),
        "same_bar_stop_first_conservative_count": same_bar_count,
        "same_bar_stop_first_contract": "PositionReplay excludes exit-day high when stop exits first",
        "path_status_counts": dict(sorted(Counter(str(item.get("status")) for item in paths).items())),
    }


def _fib_summary(details: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    paths = [item["fib_path"] for item in details]
    hit_count = sum(bool(item.get("fib_t1_hit_before_stop")) for item in paths)
    stop_before_count = sum(bool(item.get("stop_before_fib_t1")) for item in paths)
    ambiguous_count = sum(item.get("status", "").startswith("AMBIGUOUS") for item in paths)
    return {
        "executed_with_research_fib_t1": len(paths),
        "fib_t1_hit_before_stop_count": hit_count,
        "fib_t1_hit_before_stop_rate": _rate(hit_count, len(paths)),
        "stop_before_fib_t1_count": stop_before_count,
        "stop_before_fib_t1_rate": _rate(stop_before_count, len(paths)),
        "ambiguous_count": ambiguous_count,
        "path_status_counts": dict(sorted(Counter(str(item.get("status")) for item in paths).items())),
        "same_bar_stop_first_contract": "PositionReplay excludes exit-day high when stop exits first",
    }


def _segment_summary(
    details: Sequence[Mapping[str, Any]],
    field: str,
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in details:
        groups[str(item.get(field))].append(item)
    return {
        key: _performance_summary(groups[key])
        for key in sorted(groups)
    }


def _add_time_half(
    details: Sequence[Mapping[str, Any]],
    *,
    minimum_date: date,
    maximum_date: date,
) -> list[dict[str, Any]]:
    midpoint = minimum_date + timedelta(days=(maximum_date - minimum_date).days // 2)
    output: list[dict[str, Any]] = []
    for item in details:
        trade_date = date.fromisoformat(str(item["T_date"]))
        copied = dict(item)
        copied["development_time_half"] = (
            "first_half" if trade_date <= midpoint else "second_half"
        )
        output.append(copied)
    return output


def _concentration_summary(details: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for item in details:
        value = _number(item.get("realized_gross_R"))
        if value is not None:
            by_symbol[str(item["symbol"])].append(value)
    net_by_symbol = {
        symbol: sum(values) for symbol, values in by_symbol.items()
    }
    positive_by_symbol = {
        symbol: sum(value for value in values if value > 0)
        for symbol, values in by_symbol.items()
    }
    total_net = sum(net_by_symbol.values())
    total_abs = sum(abs(value) for value in net_by_symbol.values())
    total_positive = sum(positive_by_symbol.values())

    def rows_for(values: Mapping[str, float]) -> list[dict[str, Any]]:
        ordered = sorted(values.items(), key=lambda item: (-abs(item[1]), item[0]))
        rows: list[dict[str, Any]] = []
        for symbol, value in ordered[:5]:
            rows.append(
                {
                    "symbol": symbol,
                    "value_R": value,
                    "share_of_total_net_R": (value / total_net if total_net else None),
                    "share_of_total_absolute_net_R": (abs(value) / total_abs if total_abs else None),
                    "share_of_total_positive_R": (value / total_positive if total_positive else None),
                }
            )
        return rows

    positive_rows = sorted(
        ((symbol, value) for symbol, value in positive_by_symbol.items() if value > 0),
        key=lambda item: (-item[1], item[0]),
    )
    positive_top5 = [
        {
            "symbol": symbol,
            "positive_gross_R": value,
            "share_of_total_positive_R": (value / total_positive if total_positive else None),
        }
        for symbol, value in positive_rows[:5]
    ]
    top_positive_symbol = positive_rows[0][0] if positive_rows else None
    positive_contributors = [symbol for symbol, value in positive_rows if value > 0]
    return {
        "closed_symbol_count": len(by_symbol),
        "gross_total_net_R": total_net if by_symbol else None,
        "gross_total_absolute_net_R": total_abs if by_symbol else None,
        "gross_total_positive_R": total_positive if by_symbol else None,
        "top_5_by_absolute_net_R": rows_for(net_by_symbol),
        "top_5_by_positive_gross_R": positive_top5,
        "top_symbol_by_positive_gross_R": top_positive_symbol,
        "top_symbol_positive_contribution_share": (
            positive_rows[0][1] / total_positive if positive_rows and total_positive else None
        ),
        "single_symbol_is_only_positive_contributor": len(positive_contributors) == 1,
        "positive_contributor_symbols": positive_contributors,
        "concentration_is_descriptive_no_threshold_selected": True,
    }


def _research_detail_records(
    rows: Sequence[Mapping[str, Any]],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
) -> list[dict[str, Any]]:
    return [
        _p1_detail(row, quotes_by_symbol[row["event"].symbol])
        for row in rows
        if row["executed_research"]
    ]


def _p0_context_records(
    decisions: Sequence[Setup01Decision],
    executions: Sequence[Setup01Execution],
    events_by_identity: Mapping[str, Setup01ReplayEvent],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
) -> list[dict[str, Any]]:
    execution_by_identity = {item.event_identity: item for item in executions}
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        execution = execution_by_identity.get(decision.event_identity)
        if execution is None or execution.outcome != EXECUTED:
            continue
        event = events_by_identity[decision.event_identity]
        origin = position_origin_from_execution("SETUP_01", event, decision, execution)
        if origin is None:
            raise ValueError("P0 EXECUTED row did not produce a PositionOrigin")
        replay = replay_position(origin, quotes_by_symbol[event.symbol])
        rows.append(
            _p0_executed_detail(
                {"p0": decision, "execution": execution, "replay": replay}
            )
        )
    return rows


def _render_markdown(document: Mapping[str, Any]) -> str:
    dataset = document["dataset"]
    sample = document["sample"]
    funnel = document["p1_funnel"]
    p1 = document["p1_results"]
    p0 = document["p0_current_context"]
    robustness = document["robustness"]
    lines = [
        "# SETUP_01 CONFIRMED_SWING_HIGH first-reward boundary counterfactual V1",
        "",
        f"Decision classification: **{document['decision']['classification']}**",
        "",
        document["decision"]["reason"],
        "",
        "## Scope and controls",
        "",
        f"- Policy comparison: `{P0_POLICY}` vs `{P1_POLICY}`.",
        f"- Frozen dataset: `{dataset['dataset_version']}`; {dataset['symbol_count']} symbols / {dataset['bar_count']} bars.",
        f"- Sample conservation: NEAR_SWING_ONLY={sample['near_swing_only_count']}, BOTH_NEAR={sample['both_near_count']}, SMALL_WAVE_FIB={sample['small_wave_fib_count']}.",
        f"- On the fixed 117-event sample, P0 has {sample['p0_current_policy_for_fixed_near_swing_sample']['entry_allowed']} ENTRY_ALLOWED rows and {sample['p0_current_policy_for_fixed_near_swing_sample']['decision_gate_reason_counts'].get('TARGET_UPSIDE_BELOW_MINIMUM', 0)} target-upside rejections.",
        "- All P1 performance is GROSS, without a transaction-cost model.",
        "- Final OOS, provider access, production/state/Sheets/broker writes, parameter search, and threshold sweep: none.",
        "",
        "## P0 baseline",
        "",
        "```json",
        json.dumps(document["p0_baseline"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## P1 research funnel",
        "",
        "```json",
        json.dumps(funnel, ensure_ascii=False, indent=2),
        "```",
        "",
        "## P1 obstacle behavior",
        "",
        "```json",
        json.dumps(p1["obstacle_behavior"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## P1 Fib target and gross outcome",
        "",
        "```json",
        json.dumps({
            "fib_outcome": p1["fib_outcome"],
            "gross_performance": p1["gross_performance"],
        }, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Robustness",
        "",
        "```json",
        json.dumps(robustness, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Current formal SETUP_01 context",
        "",
        "```json",
        json.dumps(p0, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Executed P1 detail",
        "",
        "```json",
        json.dumps(p1["executed_details"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Governance conclusion",
        "",
        "This is a research result only. It does not change production Decision semantics, target candidates, entry, stop, Wave, Swing, confirmation, or Paper/production lifecycle behavior.",
        "",
        "Status: `READY_FOR_DECISION`.",
        "",
    ]
    return "\n".join(lines)


def run_counterfactual_research(
    *,
    dataset_manifest_path: Path = DEFAULT_DATASET_MANIFEST,
    replay_input_path: Path = DEFAULT_REPLAY_INPUT,
    replay_wrapper_path: Path = DEFAULT_REPLAY_WRAPPER,
    universe_manifest_path: Path = DEFAULT_UNIVERSE_MANIFEST,
    prior_geometry_path: Path = DEFAULT_PRIOR_GEOMETRY,
    json_output_path: Path = DEFAULT_JSON_OUTPUT,
    markdown_output_path: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    """Run the fixed one-shot Development-only counterfactual research."""

    manifest, symbol_quotes, replay_manifest = load_frozen_holdout(
        dataset_manifest_path,
        replay_input_path,
        replay_wrapper_path,
    )
    universe = load_holdout_universe_manifest(universe_manifest_path)
    prior_geometry, prior_by_identity = _load_prior_geometry(prior_geometry_path)
    events = _replay_events(symbol_quotes)
    confirmed_events = tuple(
        item for item in events if str(_value(item.event_type)) == "CONFIRMED"
    )
    if len(confirmed_events) != EXPECTED_CONFIRMED:
        raise ValueError(f"confirmed event count changed: {len(confirmed_events)}")

    stream = evaluate_setup01_decision_stream(events, symbol_quotes)
    if len(stream.decisions) != EXPECTED_CONFIRMED:
        raise ValueError("P0 Decision row count changed")
    p0_by_identity = {item.event_identity: item for item in stream.decisions}
    events_by_identity = {item.event_identity: item for item in confirmed_events}
    if set(p0_by_identity) != set(events_by_identity):
        raise ValueError("P0 Decision event identity set changed")
    parity = _p0_prior_parity(stream.decisions, prior_by_identity)
    if not parity["gate_action_target_parity"]:
        raise ValueError("P0 output is not identical to the prior geometry-bound baseline")
    p0_signatures_before = tuple(_p0_signature(item) for item in stream.decisions)

    category_counts = Counter(
        str(prior_by_identity[item.event_identity].get("low_t1_category"))
        for item in confirmed_events
    )
    if category_counts.get(NEAR_SWING_ONLY, 0) != EXPECTED_NEAR_SWING_ONLY:
        raise ValueError("NEAR_SWING_ONLY sample count changed")
    if category_counts.get("BOTH_NEAR", 0) != EXPECTED_BOTH_NEAR:
        raise ValueError("BOTH_NEAR comparison count changed")
    if category_counts.get("SMALL_WAVE_FIB", 0) != EXPECTED_SMALL_WAVE_FIB:
        raise ValueError("SMALL_WAVE_FIB comparison count changed")
    sample_events = tuple(
        item for item in confirmed_events
        if prior_by_identity[item.event_identity].get("low_t1_category") == NEAR_SWING_ONLY
    )
    market_sessions = build_market_session_dates(symbol_quotes)
    funnel, p1_rows = _build_p1_funnel(
        sample_events,
        p0_by_identity,
        symbol_quotes,
        market_sessions,
    )
    p1_details = _research_detail_records(p1_rows, symbol_quotes)
    minimum_date = min(quote.trade_date for quotes in symbol_quotes.values() for quote in quotes)
    maximum_date = max(quote.trade_date for quotes in symbol_quotes.values() for quote in quotes)
    p1_details_with_half = _add_time_half(
        p1_details,
        minimum_date=minimum_date,
        maximum_date=maximum_date,
    )
    p0_context_details = _p0_context_records(
        stream.decisions,
        stream.executions,
        events_by_identity,
        symbol_quotes,
    )
    p0_signatures_after = tuple(_p0_signature(item) for item in stream.decisions)
    p0_unchanged = p0_signatures_before == p0_signatures_after
    if not p0_unchanged:
        raise AssertionError("P1 research derivation mutated P0 Decision output")

    p0_execution_by_identity = {item.event_identity: item for item in stream.executions}
    p0_sample_decisions = [
        p0_by_identity[item.event_identity] for item in sample_events
    ]
    p0_sample_executions = [
        p0_execution_by_identity[item.event_identity]
        for item in sample_events
        if item.event_identity in p0_execution_by_identity
    ]

    p1_performance = _performance_summary(p1_details_with_half)
    p1_obstacle = _obstacle_summary(p1_details_with_half)
    p1_fib = _fib_summary(p1_details_with_half)
    document: dict[str, Any] = {
        "artifact_type": "SETUP_01_CONFIRMED_SWING_HIGH_FIRST_REWARD_BOUNDARY_COUNTERFACTUAL",
        "artifact_version": "v1",
        "analysis_date": "2026-09-15",
        "protocol_version": PROTOCOL_VERSION,
        "policies": {
            "P0": {
                "name": P0_POLICY,
                "formal_t1": "nearest existing T-known CONFIRMED_SWING_HIGH or WAVE3_FIB_EXTENSION candidate",
                "gates": "existing MIN_TARGET_UPSIDE_PCT=5% then existing RR>=2",
            },
            "P1": {
                "name": P1_POLICY,
                "formal_t1": "nearest existing T-known WAVE3_FIB_EXTENSION candidate only",
                "overhead_swing": "diagnostic only; no formal T1 participation",
                "gates": "same existing MIN_TARGET_UPSIDE_PCT=5% and RR>=2",
                "entry_stop_wave_confirmation_t1_executor": "unchanged and reused",
                "target_fallback": "none; no T2/T3 substitution and no new target",
            },
        },
        "dataset": {
            "dataset_version": manifest.get("dataset_version"),
            "dataset_manifest_sha256": manifest.get("integrity", {}).get("manifest_sha256"),
            "replay_aggregate_hash": getattr(replay_manifest, "aggregate_hash", None),
            "universe_version": universe.get("universe_version"),
            "universe_manifest_sha256": universe.get("integrity", {}).get("manifest_sha256"),
            "symbol_count": len(symbol_quotes),
            "bar_count": sum(len(quotes) for quotes in symbol_quotes.values()),
            "market_session_identity": DEVELOPMENT_SESSION_IDENTITY,
            "minimum_observed_date": _date_text(minimum_date),
            "maximum_observed_date": _date_text(maximum_date),
            "prior_geometry_artifact_sha256": _sha256_file(prior_geometry_path),
        },
        "sample": {
            "definition": "nearest confirmed swing high upside <5% and nearest Wave3 Fib extension upside >=5%; fixed from prior geometry artifact",
            "near_swing_only_count": category_counts.get(NEAR_SWING_ONLY, 0),
            "both_near_count": category_counts.get("BOTH_NEAR", 0),
            "small_wave_fib_count": category_counts.get("SMALL_WAVE_FIB", 0),
            "all_confirmed_count": len(confirmed_events),
            "category_counts": dict(sorted(category_counts.items())),
            "prior_geometry_summary": {
                "confirmed_count": prior_geometry.get("summary", {}).get("confirmed_count"),
                "formal_t1_lt_5": prior_geometry.get("summary", {}).get("formal_t1_lt_5_count"),
                "category_partition_ok": prior_geometry.get("summary", {}).get("dedup_and_conservation", {}).get("category_partition_ok"),
            },
            "p0_current_policy_for_fixed_near_swing_sample": _p0_funnel(
                p0_sample_decisions,
                p0_sample_executions,
            ),
        },
        "p0_baseline": {
            **_p0_funnel(stream.decisions, stream.executions),
            "ignored_non_confirmed_event_count": stream.ignored_non_confirmed_event_count,
            "duplicate_event_count": stream.duplicate_event_count,
            "prior_geometry_parity": parity,
            "p0_output_unchanged_after_p1_derivation": p0_unchanged,
        },
        "p1_funnel": funnel,
        "p1_results": {
            "executed_details": p1_details_with_half,
            "executed_detail_manifest": {
                "schema": "SETUP-01-BOUNDARY-COUNTERFACTUAL-EXECUTED-DETAIL-v1",
                "count": len(p1_details_with_half),
                "sha256": _sha256_json(p1_details_with_half),
            },
            "obstacle_behavior": p1_obstacle,
            "fib_outcome": p1_fib,
            "gross_performance": p1_performance,
        },
        "robustness": {
            "market": _segment_summary(p1_details_with_half, "market"),
            "development_time_half": _segment_summary(p1_details_with_half, "development_time_half"),
            "symbol_concentration": _concentration_summary(p1_details_with_half),
        },
        "p0_current_context": {
            "definition": "same frozen Development holdout current formal P0 SETUP_01 EXECUTED cohort; descriptive context, not a random control group",
            "gross_performance": _performance_summary(p0_context_details),
            "executed_details": p0_context_details,
        },
        "controls": {
            "development_only": True,
            "final_oos_accessed": False,
            "formal_validation": False,
            "provider_accessed": False,
            "parameter_search": False,
            "threshold_sweep": False,
            "min_target_upside_optimized": False,
            "rr_optimized": False,
            "fib_ratios_modified": False,
            "entry_stop_wave_swing_confirmation_modified": False,
            "future_signal_information_used": False,
            "exact_t_plus_1_open_executor_reused": True,
            "position_replay_reused": True,
            "same_bar_stop_first_contract_reused": True,
            "p0_production_output_modified": False,
            "production_decision_semantics_modified": False,
            "production_sheets_writes": 0,
            "state_writes": 0,
            "broker_orders": 0,
            "t2_t3_fallback_or_new_target": False,
            "pr82_accessed": False,
        },
        "decision": {
            "classification": DECISION_CLASSIFICATION,
            "reason": (
                f"The fixed NEAR_SWING_ONLY run produced {len(p1_details_with_half)} executed P1 research rows: "
                f"{p1_obstacle['obstacle_clear_before_stop_count']} cleared the overhead Swing High before stop, "
                f"{p1_fib['fib_t1_hit_before_stop_count']} reached the research Fib T1, and "
                f"{p1_performance['stop_out_count']} stopped out. The executed sample is small, "
                "the positive gross R is concentrated in one symbol, and CN/US and time-half results diverge. "
                "That is not stable evidence either to retain the Swing High as a protective hard boundary or to remove it as a universally removable boundary; no conditioning variable or distance threshold is searched in this run."
            ),
            "production_change": "none; requires explicit future approval",
        },
        "status": "READY_FOR_DECISION",
    }
    _write_json(json_output_path, document)
    markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_output_path.write_text(_render_markdown(document), encoding="utf-8")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--replay-input", type=Path, default=DEFAULT_REPLAY_INPUT)
    parser.add_argument("--replay-wrapper", type=Path, default=DEFAULT_REPLAY_WRAPPER)
    parser.add_argument("--universe-manifest", type=Path, default=DEFAULT_UNIVERSE_MANIFEST)
    parser.add_argument("--prior-geometry", type=Path, default=DEFAULT_PRIOR_GEOMETRY)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args(argv)
    result = run_counterfactual_research(
        dataset_manifest_path=args.dataset_manifest,
        replay_input_path=args.replay_input,
        replay_wrapper_path=args.replay_wrapper,
        universe_manifest_path=args.universe_manifest,
        prior_geometry_path=args.prior_geometry,
        json_output_path=args.json_output,
        markdown_output_path=args.markdown_output,
    )
    print(json.dumps({
        "status": result["status"],
        "classification": result["decision"]["classification"],
        "p1_funnel": result["p1_funnel"]["stages"],
        "obstacle": result["p1_results"]["obstacle_behavior"],
        "gross_performance": result["p1_results"]["gross_performance"],
    }, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

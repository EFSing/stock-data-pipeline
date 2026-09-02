"""DEVELOPMENT_EXPOSED SETUP_02 Decision/Risk funnel.

This module connects the frozen structural CONFIRMED event stream to the
independent SETUP_02 Decision/Risk evaluator.  It reports only decision,
target provenance, R/R, and exact T+1 OPEN classifications; it has no outcome
or forward-performance calculation.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping, Sequence

from core import Quote
from research.market_sessions import DEVELOPMENT_SESSION_IDENTITY, build_market_session_dates
from trading.models import DecisionAction, SetupState
from trading.setup02_decision import (
    EXECUTED,
    SKIP_NO_T1_BAR,
    Setup02Decision,
    Setup02DecisionStream,
    Setup02Execution,
    Setup02DecisionGateReason,
    SETUP02_DECISION_PROTOCOL_VERSION,
    evaluate_setup02_decision_stream,
    setup02_decision_to_dict,
    setup02_execution_to_dict,
    setup02_structure_geometry_audit,
    setup02_target_provenance_audit,
)
from trading.setup02_replay import Setup02ReplayEvent


DECISION_GATE_REASONS = tuple(item.value for item in Setup02DecisionGateReason)
EXECUTION_OUTCOMES = (
    EXECUTED,
    "SKIP_GAP_BELOW_CONFIRMATION",
    "SKIP_GAP_ABOVE_ENTRY_ZONE",
    "SKIP_BELOW_INVALIDATION",
    SKIP_NO_T1_BAR,
    "SKIP_RR_BELOW_MINIMUM_AT_OPEN",
    "SKIP_DECISION_NOT_ENTRY_ALLOWED",
)


def decision_scope_rows(stream: Setup02DecisionStream) -> list[dict]:
    """Return total, market, and per-symbol conservation rows."""
    execution_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    scopes: dict[str, list[Setup02Decision]] = {"total": list(stream.decisions)}
    for decision in stream.decisions:
        scopes.setdefault(decision.market, []).append(decision)
        scopes.setdefault(decision.symbol, []).append(decision)
    rows: list[dict] = []
    for scope, decisions in sorted(scopes.items()):
        gate_counts = Counter(
            str(getattr(decision.gate_reason, "value", decision.gate_reason))
            for decision in decisions
        )
        executions = [
            execution_by_identity[decision.event_identity]
            for decision in decisions
            if decision.event_identity in execution_by_identity
        ]
        execution_counts = Counter(execution.outcome for execution in executions)
        row = {
            "scope": scope,
            "confirmed": len(decisions),
            "decision_calculable": sum(int(item.decision_calculable) for item in decisions),
            "entry_allowed": sum(item.action is DecisionAction.ENTRY_ALLOWED for item in decisions),
            "no_trade": sum(item.action is DecisionAction.NO_TRADE for item in decisions),
            "t1_execution_attempt": len(executions),
            "executed": execution_counts.get(EXECUTED, 0),
        }
        for reason in DECISION_GATE_REASONS:
            row[f"DECISION:{reason}"] = gate_counts.get(reason, 0)
        for reason in EXECUTION_OUTCOMES:
            row[f"EXECUTION:{reason}"] = execution_counts.get(reason, 0)
        rows.append(row)
    return rows


def _unique_first_confirmed_events(events: Iterable[Setup02ReplayEvent]) -> list[Setup02ReplayEvent]:
    seen: set[str] = set()
    rows: list[Setup02ReplayEvent] = []
    for event in events:
        if event.event_identity in seen:
            continue
        seen.add(event.event_identity)
        if (
            event.event_type is SetupState.CONFIRMED
            and event.setup02.is_new_confirmed_event_as_of
            and event.setup02.confirmed_date == event.trade_date
            and event.setup02.as_of_date == event.trade_date
        ):
            rows.append(event)
    return rows


def event_identity_audit(events: Iterable[Setup02ReplayEvent]) -> dict:
    rows = list(events)
    identities = [event.event_identity for event in rows]
    mismatches = []
    from trading.setup02_replay import setup02_event_identity

    for event in rows:
        expected = setup02_event_identity(
            event.symbol,
            event.trade_date,
            event.event_type,
            event.setup02.lifecycle_index,
        )
        if expected != event.event_identity:
            mismatches.append(
                {
                    "event_identity": event.event_identity,
                    "expected_identity": expected,
                }
            )
    duplicate_count = len(identities) - len(set(identities))
    consumed = _unique_first_confirmed_events(rows)
    consumed_ids = [event.event_identity for event in consumed]
    return {
        "event_count": len(rows),
        "unique_event_identity_count": len(set(identities)),
        "duplicate_identity_count": duplicate_count,
        "identity_mismatch_count": len(mismatches),
        "identity_mismatches": mismatches,
        "first_confirmed_event_count": len(consumed),
        "first_confirmed_unique_identity_count": len(set(consumed_ids)),
        "exactly_once": (
            duplicate_count == 0
            and not mismatches
            and len(consumed_ids) == len(set(consumed_ids))
        ),
    }


def _provenance_summary(
    decisions: Sequence[Setup02Decision],
) -> tuple[dict[str, int], dict[str, int]]:
    candidate_sources: Counter[str] = Counter()
    provenance_sources: Counter[str] = Counter()
    extension_ratios: Counter[str] = Counter()
    for decision in decisions:
        for candidate in decision.target_candidates:
            candidate_sources[candidate.source] += 1
            for item in candidate.provenance:
                provenance_sources[item.source] += 1
                if item.extension_ratio is not None:
                    extension_ratios[str(item.extension_ratio)] += 1
    return (
        dict(sorted(candidate_sources.items())),
        {
            "source_counts": dict(sorted(provenance_sources.items())),
            "extension_ratio_counts": dict(sorted(extension_ratios.items())),
        },
    )


def build_setup02_decision_funnel(
    events: Iterable[Setup02ReplayEvent],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    *,
    risk_capital: float | None = None,
    swing_lookback: int = 5,
    atr_period: int = 14,
    dataset_version: str | None = None,
    dataset_manifest_sha256: str | None = None,
    replay_input_aggregate_hash: str | None = None,
    event_stream_source: str = "CAUSAL_STRUCTURAL_REPLAY",
) -> dict:
    """Build a structure-only funnel document and enforce conservation."""
    event_rows = list(events)
    stream = evaluate_setup02_decision_stream(
        event_rows,
        quotes_by_symbol,
        risk_capital=risk_capital,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    first_confirmed = _unique_first_confirmed_events(event_rows)
    invalid_structure_audit = []
    for event in first_confirmed:
        audit = setup02_structure_geometry_audit(
            event,
            quotes_by_symbol[event.symbol],
        )
        if audit["classification"] != "VALID":
            invalid_structure_audit.append(audit)
    decision_rows = []
    execution_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    target_audits = []
    for decision in stream.decisions:
        execution = execution_by_identity.get(decision.event_identity)
        decision_row = setup02_decision_to_dict(decision)
        decision_row["execution"] = (
            setup02_execution_to_dict(execution) if execution else None
        )
        decision_rows.append(decision_row)
        if decision.target_candidates and decision.targets:
            target_audits.append(setup02_target_provenance_audit(decision, execution))

    gate_counts: Counter[str] = Counter({reason: 0 for reason in DECISION_GATE_REASONS})
    gate_counts.update(
        str(getattr(decision.gate_reason, "value", decision.gate_reason))
        for decision in stream.decisions
    )
    execution_counts: Counter[str] = Counter({reason: 0 for reason in EXECUTION_OUTCOMES})
    execution_counts.update(execution.outcome for execution in stream.executions)
    quality_counts: Counter[str] = Counter(
        decision.rr.quality for decision in stream.decisions if decision.rr is not None
    )
    actual_quality_counts: Counter[str] = Counter(
        execution.actual_rr.quality
        for execution in stream.executions
        if execution.actual_rr is not None
    )
    candidate_source_counts, provenance = _provenance_summary(stream.decisions)
    t1_source_counts = Counter(
        audit["target_t1_source"] for audit in target_audits
    )
    t1_extension_ratio_counts = Counter(
        str(item["extension_ratio"])
        for audit in target_audits
        for item in audit["target_t1_provenance"]
        if item["extension_ratio"] is not None
    )
    market_counts: dict[str, Counter[str]] = {}
    for event in first_confirmed:
        market_counts.setdefault(event.market, Counter())[event.event_type.value] += 1

    entry_allowed = gate_counts[Setup02DecisionGateReason.ENTRY_ALLOWED.value]
    no_trade = sum(
        int(decision.action is DecisionAction.NO_TRADE) for decision in stream.decisions
    )
    attempts = len(stream.executions)
    executed = execution_counts[EXECUTED]
    skipped = attempts - executed
    ledger_invariant = all(
        (execution.actual_entry is not None) == (execution.outcome == EXECUTED)
        for execution in stream.executions
    )
    conservation = {
        "confirmed_equals_unique_first_confirmed_events": (
            len(first_confirmed) == len({event.event_identity for event in first_confirmed})
        ),
        "confirmed_equals_decision_rows": len(first_confirmed) == len(stream.decisions),
        "decision_equals_entry_allowed_plus_no_trade": (
            len(stream.decisions) == entry_allowed + no_trade
        ),
        "entry_allowed_equals_t1_attempts": entry_allowed == attempts,
        "execution_attempts_equals_executed_plus_skipped": (
            attempts == executed + skipped
        ),
        "actual_entry_iff_executed": ledger_invariant,
    }
    if not all(conservation.values()):
        raise AssertionError(f"SETUP_02 funnel conservation failed: {conservation}")

    market_session_dates = build_market_session_dates(quotes_by_symbol)
    identity_audit = event_identity_audit(event_rows)
    document = {
        "protocol_version": SETUP02_DECISION_PROTOCOL_VERSION,
        "mode": "DEVELOPMENT_EXPOSED_DECISION_EXECUTION_FUNNEL",
        "development_session_identity": DEVELOPMENT_SESSION_IDENTITY,
        "dataset_version": dataset_version,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "replay_input_aggregate_hash": replay_input_aggregate_hash,
        "event_stream_source": event_stream_source,
        "risk_capital_input": risk_capital,
        "swing_lookback": swing_lookback,
        "atr_period": atr_period,
        "symbols_requested": len(quotes_by_symbol),
        "confirmed_events": len(first_confirmed),
        "decision_rows": len(stream.decisions),
        "decision_calculable": sum(int(item.decision_calculable) for item in stream.decisions),
        "not_decision_calculable": sum(int(not item.decision_calculable) for item in stream.decisions),
        "entry_allowed": entry_allowed,
        "no_trade": no_trade,
        "decision_gate_reason_counts": dict(sorted(gate_counts.items())),
        "execution_status_counts": dict(sorted(execution_counts.items())),
        "t1_execution_attempts": attempts,
        "executed": executed,
        "skipped": skipped,
        "missing_t1_count": execution_counts[SKIP_NO_T1_BAR],
        "duplicate_event_count": stream.duplicate_event_count,
        "ignored_non_confirmed_event_count": stream.ignored_non_confirmed_event_count,
        "cn_us_event_distribution": {
            market: dict(sorted(counts.items()))
            for market, counts in sorted(market_counts.items())
        },
        "per_symbol": decision_scope_rows(stream),
        "target_candidate_source_counts": candidate_source_counts,
        "target_provenance": provenance,
        "t1_source_counts": dict(sorted(t1_source_counts.items())),
        "t1_extension_ratio_counts": dict(sorted(t1_extension_ratio_counts.items())),
        "target_provenance_audit": target_audits,
        "invalid_structure_audit": invalid_structure_audit,
        "invalid_structure_audit_count": len(invalid_structure_audit),
        "rr_quality_distribution": dict(sorted(quality_counts.items())),
        "actual_open_rr_quality_distribution": dict(sorted(actual_quality_counts.items())),
        "planned_over_5r_count": sum(item["planned_first_target_over_5r"] for item in target_audits),
        "actual_open_over_5r_count": sum(item["actual_open_first_target_over_5r"] for item in target_audits),
        "high_asymmetry_decision_count": sum(
            decision.rr is not None and decision.rr.quality == "HIGH_ASYMMETRY"
            for decision in stream.decisions
        ),
        "target_reasonableness_audit": {
            "checked_count": sum(item.target_reasonableness_checked for item in stream.decisions),
            "passed_count": sum(item.target_reasonableness_passed is True for item in stream.decisions),
            "failed_count": sum(item.target_reasonableness_passed is False for item in stream.decisions),
        },
        "position_size_required_input_count": sum(
            item.position_size_required_input == "risk_capital" for item in stream.decisions
        ),
        "funnel_conservation": conservation,
        "execution_ledger_invariant": ledger_invariant,
        "identity_audit": identity_audit,
        "decisions": decision_rows,
        "market_session_identity_check": bool(market_session_dates),
        "controls": {
            "development_exposed": True,
            "t_day_only_decision": True,
            "t_plus_1_open_only": True,
            "exact_next_market_session": True,
            "same_bar_execution": False,
            "future_t1_high_low_close_accessed": False,
            "returns_accessed": False,
            "forward_returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "pnl_accessed": False,
            "expectancy_accessed": False,
            "profit_factor_accessed": False,
            "final_oos_accessed": False,
            "production_calendar_implemented": False,
            "holdings_or_broker_accessed": False,
            "sheets_written": False,
            "setup02_structural_lifecycle_modified": False,
            "setup01_modified": False,
            "setup03_reopened": False,
        },
        "status": "SUCCESS",
    }
    return document


__all__ = [
    "DECISION_GATE_REASONS",
    "EXECUTION_OUTCOMES",
    "build_setup02_decision_funnel",
    "decision_scope_rows",
    "event_identity_audit",
]

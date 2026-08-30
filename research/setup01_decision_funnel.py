"""Development-only aggregation for the SETUP_01 Decision/Risk funnel.

The funnel consumes the existing first-entry ``CONFIRMED`` replay events and
the frozen quote series. It does not reconstruct structural events and does
not read any outcome or performance fields.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from core import Quote
from research.market_sessions import build_market_session_dates
from trading.models import DecisionAction, SetupState
from trading.setup01_decision import (
    EXECUTED,
    Setup01Decision,
    Setup01DecisionStream,
    Setup01Execution,
    SETUP01_DECISION_PROTOCOL_VERSION,
    evaluate_setup01_decision_stream,
    setup01_decision_to_dict,
    setup01_execution_to_dict,
    setup01_target_provenance_audit,
)
from trading.setup01_replay import Setup01ReplayReport


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _row(
    decision: Setup01Decision,
    execution: Setup01Execution | None,
) -> dict[str, object]:
    decision_row = setup01_decision_to_dict(decision)
    execution_row = (
        setup01_execution_to_dict(execution) if execution is not None else None
    )
    risk_per_share = decision.rr.risk_per_share if decision.rr is not None else None
    return {
        "event_identity": decision.event_identity,
        "symbol": decision.symbol,
        "market": decision.market,
        "confirmed_date": decision.trade_date.isoformat(),
        "decision_calculable": decision.decision_calculable,
        "decision_action": _enum_value(decision.action),
        "decision_gate_reason": _enum_value(decision.gate_reason),
        "t_close": decision.planned_entry,
        "atr14": decision.atr14,
        "confirmation_level": decision.confirmation_level,
        "planned_entry": decision.planned_entry,
        "entry_zone_low": decision.entry_zone_low,
        "entry_zone_high": decision.entry_zone_high,
        "execution_stop": decision.execution_stop,
        "wave_scenario_invalidation": decision.wave_scenario_invalidation,
        "structural_invalidation": decision.structural_invalidation,
        "target_candidates": decision_row["target_candidates"],
        "target_prices": decision_row["targets"],
        "rr": decision_row["rr"],
        "risk_per_share": risk_per_share,
        "position_size_required_input": decision.position_size_required_input,
        "position_size": decision_row["position_size"],
        "execution_status": (
            _enum_value(execution.outcome) if execution is not None else "NOT_ATTEMPTED"
        ),
        "execution_reason": (
            _enum_value(execution.outcome) if execution is not None else "NOT_ATTEMPTED"
        ),
        "t1_date": (
            execution_row["execution_date"] if execution_row is not None else None
        ),
        "t1_open": execution.t1_open if execution is not None else None,
        "actual_entry": execution.actual_entry if execution is not None else None,
        "actual_rr": (
            execution_row["actual_rr"] if execution_row is not None else None
        ),
    }


def _scope_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    scopes: dict[str, list[dict[str, object]]] = {"total": rows}
    for row in rows:
        scopes.setdefault(str(row["market"]), []).append(row)
        scopes.setdefault(str(row["symbol"]), []).append(row)

    output: list[dict[str, object]] = []
    for scope, scoped_rows in sorted(scopes.items()):
        gate_counts = Counter(str(row["decision_gate_reason"]) for row in scoped_rows)
        execution_counts = Counter(
            str(row["execution_status"])
            for row in scoped_rows
            if row["execution_status"] != "NOT_ATTEMPTED"
        )
        item: dict[str, object] = {
            "scope": scope,
            "confirmed": len(scoped_rows),
            "decision_calculable": sum(
                bool(row["decision_calculable"]) for row in scoped_rows
            ),
            "decision_not_calculable": sum(
                not bool(row["decision_calculable"]) for row in scoped_rows
            ),
            "entry_allowed": gate_counts["ENTRY_ALLOWED"],
            "no_trade": sum(
                str(row["decision_action"]) == DecisionAction.NO_TRADE.value
                for row in scoped_rows
            ),
            "t1_execution_attempt": sum(
                row["execution_status"] != "NOT_ATTEMPTED" for row in scoped_rows
            ),
            "executed": execution_counts[EXECUTED],
        }
        for reason, count in sorted(gate_counts.items()):
            item[f"DECISION:{reason}"] = count
        for reason, count in sorted(execution_counts.items()):
            item[f"EXECUTION:{reason}"] = count
        output.append(item)
    return output


def build_setup01_decision_funnel(
    reports: Iterable[Setup01ReplayReport],
    quotes_by_symbol: Mapping[str, list[Quote]],
    *,
    risk_capital: float | None,
    swing_lookback: int = 5,
    atr_period: int = 14,
) -> dict[str, object]:
    """Build a conserved confirmed-event -> decision -> T+1 funnel."""
    reports = tuple(reports)
    input_events = [
        event
        for report in reports
        for event in report.events
        if event.event_type is SetupState.CONFIRMED
        and event.setup01.is_new_confirmed_event_as_of
        and event.setup01.confirmed_date == event.trade_date
        and event.setup01.as_of_date == event.trade_date
    ]
    stream: Setup01DecisionStream = evaluate_setup01_decision_stream(
        input_events,
        quotes_by_symbol,
        risk_capital=risk_capital,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    execution_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    rows = [
        _row(decision, execution_by_identity.get(decision.event_identity))
        for decision in stream.decisions
    ]
    market_session_dates = build_market_session_dates(quotes_by_symbol)
    target_provenance_audit = [
        setup01_target_provenance_audit(
            decision,
            execution_by_identity.get(decision.event_identity),
            market_session_dates=market_session_dates,
        )
        for decision in stream.decisions
        if decision.action is DecisionAction.ENTRY_ALLOWED
    ]
    scope_rows = _scope_rows(rows)
    gate_counts = Counter(str(row["decision_gate_reason"]) for row in rows)
    no_trade_reasons = Counter(
        str(row["decision_gate_reason"])
        for row in rows
        if row["decision_action"] == DecisionAction.NO_TRADE.value
    )
    execution_counts = Counter(
        str(row["execution_status"])
        for row in rows
        if row["execution_status"] != "NOT_ATTEMPTED"
    )
    confirmed = len(input_events)
    unique_confirmed = len({event.event_identity for event in input_events})
    decision_calculable = sum(bool(row["decision_calculable"]) for row in rows)
    entry_allowed = gate_counts["ENTRY_ALLOWED"]
    no_trade = sum(
        row["decision_action"] == DecisionAction.NO_TRADE.value for row in rows
    )
    attempts = sum(execution_counts.values())
    executed = execution_counts[EXECUTED]
    skipped = attempts - executed
    conservation = {
        "confirmed_equals_unique_confirmed_events": confirmed == unique_confirmed,
        "confirmed_equals_decision_rows": confirmed == len(rows),
        "confirmed_equals_calculable_plus_not_calculable": (
            confirmed == decision_calculable + (len(rows) - decision_calculable)
        ),
        "decision_equals_entry_allowed_plus_no_trade": (
            len(rows) == entry_allowed + no_trade
        ),
        "execution_attempts_equals_executed_plus_skipped": (
            attempts == executed + skipped
        ),
    }
    if not all(conservation.values()):
        raise AssertionError(f"SETUP_01 funnel conservation failed: {conservation}")

    return {
        "protocol_version": SETUP01_DECISION_PROTOCOL_VERSION,
        "mode": "DEVELOPMENT_EXPOSED_DECISION_EXECUTION_FUNNEL",
        "risk_capital": risk_capital,
        "swing_lookback": swing_lookback,
        "atr_period": atr_period,
        "confirmed_event_inputs": confirmed,
        "confirmed_event_unique": unique_confirmed,
        "decision_rows": len(rows),
        "decision_calculable": decision_calculable,
        "entry_allowed": entry_allowed,
        "no_trade": no_trade,
        "no_trade_reason_counts": dict(sorted(no_trade_reasons.items())),
        "decision_gate_reason_counts": dict(sorted(gate_counts.items())),
        "t1_execution_attempts": attempts,
        "execution_status_counts": dict(sorted(execution_counts.items())),
        "executed": executed,
        "skipped": skipped,
        "funnel_by_scope": scope_rows,
        "target_provenance_audit": target_provenance_audit,
        "target_provenance_summary": {
            "audit_rows": len(target_provenance_audit),
            "planned_over_5r_rows": sum(
                row["planned_first_target_over_5r"]
                for row in target_provenance_audit
            ),
            "actual_open_over_5r_rows": sum(
                row["actual_open_first_target_over_5r"]
                for row in target_provenance_audit
            ),
            "target_reasonableness_status": (
                "TARGET_REASONABLENESS_NEEDS_SOL_DECISION"
                if any(
                    row["planned_first_target_over_5r"]
                    or row["actual_open_first_target_over_5r"]
                    for row in target_provenance_audit
                )
                else "TARGET_PROVENANCE_NO_NEW_BLOCKER"
            ),
        },
        "rows": rows,
        "ignored_non_confirmed_event_count": stream.ignored_non_confirmed_event_count,
        "duplicate_event_count": stream.duplicate_event_count,
        "conservation": conservation,
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "returns_accessed": False,
            "forward_returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "pnl_accessed": False,
            "final_oos_accessed": False,
            "sheets_written": False,
            "setup02_started": False,
            "setup03_reopened": False,
        },
        "status": "SUCCESS",
    }


__all__ = ["build_setup01_decision_funnel"]

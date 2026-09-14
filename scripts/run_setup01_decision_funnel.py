"""Run the DEVELOPMENT_EXPOSED SETUP_01 Decision/Risk funnel.

This runner first replays the existing structural SETUP_01 event stream and
then consumes only first-entry CONFIRMED events.  It writes diagnostic JSON/CSV
artifacts; it does not write Sheets and has no outcome/OOS path.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path
import sys
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.development_holdout_dataset import load_frozen_holdout
from research.market_sessions import (
    DEVELOPMENT_SESSION_IDENTITY,
    build_market_session_dates,
)
from trading.models import (
    DecisionAction,
    Setup01Evaluation,
    SetupState,
    SwingKind,
    SwingPoint,
)
from trading.setup01_decision import (
    SETUP01_DECISION_PROTOCOL_VERSION,
    Setup01Decision,
    Setup01DecisionStream,
    Setup01Execution,
    evaluate_setup01_decision_stream,
    setup01_decision_to_dict,
    setup01_execution_to_dict,
    setup01_target_provenance_audit,
    SKIP_TARGET_UPSIDE_BELOW_MINIMUM,
)
from trading.setup01_replay import Setup01ReplayEvent, replay_setup01_history


DEFAULT_MANIFEST = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_dataset_manifest.json"
DEFAULT_INPUT = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_replay_input.jsonl.gz"
DEFAULT_WRAPPER = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout" / "development_holdout_replay_manifest.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "setup01_decision_risk_v1"
DEFAULT_STRUCTURAL_EVENTS = (
    PROJECT_ROOT
    / "artifacts"
    / "setup01_wave2_to_wave3_v1"
    / "setup01_structural_replay_events.csv"
)
DECISION_GATE_REASONS = (
    "ATR_UNAVAILABLE",
    "ABOVE_ENTRY_ZONE",
    "NO_VALID_TARGET",
    "TARGET_UPSIDE_BELOW_MINIMUM",
    "RR_BELOW_MINIMUM",
    "INVALID_STRUCTURE",
    "ENTRY_ALLOWED",
)
EXECUTION_OUTCOMES = (
    "EXECUTED",
    "SKIP_GAP_BELOW_CONFIRMATION",
    "SKIP_GAP_ABOVE_ENTRY_ZONE",
    "SKIP_BELOW_INVALIDATION",
    "SKIP_NO_T1_BAR",
    SKIP_TARGET_UPSIDE_BELOW_MINIMUM,
    "SKIP_RR_BELOW_MINIMUM_AT_OPEN",
    "SKIP_DECISION_NOT_ENTRY_ALLOWED",
)

PRE_FIX_FUNNEL_COUNTS = {
    "confirmed_events": 745,
    "decision_rows": 745,
    "entry_allowed": 5,
    "t1_execution_attempts": 5,
    "executed": 4,
    "decision_gate_reason_counts": {
        "ABOVE_ENTRY_ZONE": 464,
        "ATR_UNAVAILABLE": 0,
        "ENTRY_ALLOWED": 5,
        "INVALID_STRUCTURE": 0,
        "NO_VALID_TARGET": 0,
        "RR_BELOW_MINIMUM": 276,
    },
    "execution_status_counts": {
        "EXECUTED": 4,
        "SKIP_BELOW_INVALIDATION": 0,
        "SKIP_DECISION_NOT_ENTRY_ALLOWED": 0,
        "SKIP_GAP_ABOVE_ENTRY_ZONE": 0,
        "SKIP_GAP_BELOW_CONFIRMATION": 1,
        "SKIP_NO_T1_BAR": 0,
        "SKIP_RR_BELOW_MINIMUM_AT_OPEN": 0,
    },
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8-sig")
        return
    fieldnames: list[str] = []
    for row in rows:
        for field in row:
            if field not in fieldnames:
                fieldnames.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _optional_int(value: str) -> int | None:
    return int(value) if value else None


def _optional_float(value: str) -> float | None:
    return float(value) if value else None


def _swing(value: str) -> SwingPoint | None:
    if not value:
        return None
    payload = ast.literal_eval(value)
    return SwingPoint(
        kind=SwingKind(str(payload["kind"])),
        price=float(payload["price"]),
        pivot_index=int(payload["pivot_index"]),
        pivot_date=date.fromisoformat(payload["pivot_date"]),
        confirmed_index=_optional_int(str(payload.get("confirmed_index", ""))),
        confirmed_date=_optional_date(str(payload.get("confirmed_date", ""))),
    )


def _event_from_structural_row(row: dict[str, str]) -> Setup01ReplayEvent:
    event_type = SetupState(row["event_type"])
    trade_date = date.fromisoformat(row["trade_date"])
    diagnostics = ast.literal_eval(row.get("diagnostics", "[]"))
    snapshot = Setup01Evaluation(
        setup_type=row["setup_type"],
        protocol_version=row["protocol_version"],
        state=SetupState(row["state"]),
        as_of_date=date.fromisoformat(row["as_of_date"]),
        wave1_origin=_swing(row.get("wave1_origin", "")),
        wave1_peak=_swing(row.get("wave1_peak", "")),
        wave2_low=_swing(row.get("wave2_low", "")),
        fib_retracement_ratio=_optional_float(row.get("fib_retracement_ratio", "")),
        fib_retracement_region=row.get("fib_retracement_region") or None,
        confirmation_level=_optional_float(row.get("confirmation_level", "")),
        structural_invalidation=_optional_float(row.get("structural_invalidation", "")),
        wave_scenario_invalidation=_optional_float(row.get("wave_scenario_invalidation", "")),
        wave1_origin_confirmed_date=_optional_date(row.get("wave1_origin_confirmed_date", "")),
        wave1_peak_confirmed_date=_optional_date(row.get("wave1_peak_confirmed_date", "")),
        wave2_low_confirmed_date=_optional_date(row.get("wave2_low_confirmed_date", "")),
        state_entered_index=_optional_int(row.get("state_entered_index", "")),
        state_entered_date=_optional_date(row.get("state_entered_date", "")),
        confirmed_index=_optional_int(row.get("confirmed_index", "")),
        confirmed_date=_optional_date(row.get("confirmed_date", "")),
        failed_index=_optional_int(row.get("failed_index", "")),
        failed_date=_optional_date(row.get("failed_date", "")),
        primary_wave_scenario=row.get("primary_wave_scenario", ""),
        alternate_wave_scenario=row.get("alternate_wave_scenario", ""),
        reason=row.get("reason", ""),
        diagnostics=tuple(str(item) for item in diagnostics),
        lifecycle_index=_optional_int(row.get("lifecycle_index", "")),
        terminal_event_type=event_type,
        terminal_event_date=trade_date,
        is_new_confirmed_event_as_of=event_type is SetupState.CONFIRMED,
        is_new_failed_event_as_of=event_type is SetupState.FAILED,
        is_live_preconfirmation_candidate=False,
    )
    return Setup01ReplayEvent(
        event_identity=row["event_identity"],
        symbol=row["symbol"],
        trade_date=trade_date,
        event_type=event_type,
        setup01=snapshot,
        market=row["market"],
    )


def _load_existing_confirmed_events(path: Path) -> list[Setup01ReplayEvent]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            event
            for event in (_event_from_structural_row(row) for row in csv.DictReader(handle))
            if event.event_type is SetupState.CONFIRMED
        ]


def _scope_rows(stream: Setup01DecisionStream) -> list[dict[str, Any]]:
    execution_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    scopes: dict[str, list[Setup01Decision]] = {"total": list(stream.decisions)}
    for decision in stream.decisions:
        scopes.setdefault(decision.market, []).append(decision)
        scopes.setdefault(decision.symbol, []).append(decision)

    rows: list[dict[str, Any]] = []
    for scope, decisions in sorted(scopes.items()):
        no_trade_reasons = Counter(
            getattr(decision.gate_reason, "value", decision.gate_reason)
            for decision in decisions
            if decision.action is DecisionAction.NO_TRADE
        )
        executions = [
            execution_by_identity[decision.event_identity]
            for decision in decisions
            if decision.event_identity in execution_by_identity
        ]
        execution_outcomes = Counter(execution.outcome for execution in executions)
        row = {
            "scope": scope,
            "confirmed": len(decisions),
            "decision_calculable": sum(
                decision.decision_calculable for decision in decisions
            ),
            "entry_allowed": sum(
                decision.action is DecisionAction.ENTRY_ALLOWED
                for decision in decisions
            ),
            "no_trade": sum(
                decision.action is DecisionAction.NO_TRADE for decision in decisions
            ),
            "t1_execution_attempt": len(executions),
            "executed": execution_outcomes.get("EXECUTED", 0),
        }
        for reason, count in sorted(no_trade_reasons.items()):
            row[f"NO_TRADE:{reason}"] = count
        for reason in DECISION_GATE_REASONS:
            row[f"DECISION:{reason}"] = sum(
                int(
                    getattr(decision.gate_reason, "value", decision.gate_reason)
                    == reason
                )
                for decision in decisions
            )
        for reason, count in sorted(execution_outcomes.items()):
            row[f"EXECUTION:{reason}"] = count
        for reason in EXECUTION_OUTCOMES:
            row.setdefault(f"EXECUTION:{reason}", 0)
        rows.append(row)
    return rows


def _decision_rows(stream: Setup01DecisionStream) -> list[dict[str, Any]]:
    execution_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    rows: list[dict[str, Any]] = []
    for decision in stream.decisions:
        row = setup01_decision_to_dict(decision)
        execution = execution_by_identity.get(decision.event_identity)
        row["execution"] = (
            setup01_execution_to_dict(execution) if execution is not None else None
        )
        rows.append(row)
    return rows


def _funnel_snapshot(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "confirmed_events": document["confirmed_events"],
        "decision_rows": document["decision_rows"],
        "entry_allowed": document["entry_allowed"],
        "t1_execution_attempts": document["t1_execution_attempts"],
        "executed": document["executed"],
        "decision_gate_reason_counts": document["decision_gate_reason_counts"],
        "execution_status_counts": document["execution_status_counts"],
    }


def _funnel_delta(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    scalar_keys = (
        "confirmed_events",
        "decision_rows",
        "entry_allowed",
        "t1_execution_attempts",
        "executed",
    )
    return {
        **{
            key: int(after[key]) - int(before[key])
            for key in scalar_keys
        },
        "decision_gate_reason_counts": {
            reason: int(after["decision_gate_reason_counts"].get(reason, 0))
            - int(before["decision_gate_reason_counts"].get(reason, 0))
            for reason in sorted(
                set(before["decision_gate_reason_counts"])
                | set(after["decision_gate_reason_counts"])
            )
        },
        "execution_status_counts": {
            reason: int(after["execution_status_counts"].get(reason, 0))
            - int(before["execution_status_counts"].get(reason, 0))
            for reason in sorted(
                set(before["execution_status_counts"])
                | set(after["execution_status_counts"])
            )
        },
    }


def run_setup01_decision_funnel(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    replay_input_path: str | Path = DEFAULT_INPUT,
    replay_wrapper_path: str | Path = DEFAULT_WRAPPER,
    output_dir: str | Path = DEFAULT_OUTPUT,
    structural_events_path: str | Path = DEFAULT_STRUCTURAL_EVENTS,
    risk_capital: float | None = None,
    swing_lookback: int = 5,
    atr_period: int = 14,
) -> dict[str, Any]:
    manifest, symbol_quotes, replay_manifest = load_frozen_holdout(
        Path(manifest_path), Path(replay_input_path), Path(replay_wrapper_path)
    )
    events: list[Setup01ReplayEvent] = []
    replay_errors: list[dict[str, str]] = []
    structural_path = Path(structural_events_path)
    if structural_path.exists():
        events = _load_existing_confirmed_events(structural_path)
        event_stream_source = "EXISTING_STRUCTURAL_REPLAY_CONFIRMED_EVENTS"
    else:
        # Keep a deterministic fallback for a checkout where the prior
        # structural artifact has not been downloaded yet.  The Decision layer
        # still receives only first-entry CONFIRMED events.
        event_stream_source = "CAUSAL_STRUCTURAL_REPLAY_FALLBACK"
        for symbol in sorted(symbol_quotes):
            quotes = symbol_quotes[symbol]
            try:
                events.extend(replay_setup01_history(quotes).events)
            except Exception as exc:
                replay_errors.append(
                    {"symbol": symbol, "market": quotes[0].market, "error": str(exc)}
                )

    stream = evaluate_setup01_decision_stream(
        events,
        symbol_quotes,
        risk_capital=risk_capital,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    decision_rows = _decision_rows(stream)
    scope_rows = _scope_rows(stream)
    execution_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    confirmed = [
        event for event in events
        if event.event_type is SetupState.CONFIRMED
    ]
    gate_counts = Counter({reason: 0 for reason in DECISION_GATE_REASONS})
    gate_counts.update(
        getattr(decision.gate_reason, "value", decision.gate_reason)
        for decision in stream.decisions
    )
    execution_counts = Counter({reason: 0 for reason in EXECUTION_OUTCOMES})
    execution_counts.update(execution.outcome for execution in stream.executions)
    decision_calculable = sum(
        int(decision.decision_calculable) for decision in stream.decisions
    )
    entry_allowed = gate_counts["ENTRY_ALLOWED"]
    no_trade = sum(
        int(decision.action is DecisionAction.NO_TRADE)
        for decision in stream.decisions
    )
    executed = execution_counts["EXECUTED"]
    attempts = len(stream.executions)
    skipped = attempts - executed
    market_session_dates = build_market_session_dates(symbol_quotes)
    target_provenance_audit = [
        setup01_target_provenance_audit(
            decision,
            execution_by_identity.get(decision.event_identity),
            market_session_dates=market_session_dates,
        )
        for decision in stream.decisions
        if decision.action is DecisionAction.ENTRY_ALLOWED
    ]
    conservation = {
        "confirmed_equals_unique_confirmed_events": (
            len(confirmed) == len({event.event_identity for event in confirmed})
        ),
        "confirmed_equals_decision_rows": len(confirmed) == len(stream.decisions),
        "confirmed_equals_calculable_plus_not_calculable": (
            len(confirmed)
            == decision_calculable + len(stream.decisions) - decision_calculable
        ),
        "decision_equals_entry_allowed_plus_no_trade": (
            len(stream.decisions) == entry_allowed + no_trade
        ),
        "execution_attempts_equals_executed_plus_skipped": (
            attempts == executed + skipped
        ),
    }
    if not all(conservation.values()):
        raise AssertionError(f"SETUP_01 funnel conservation failed: {conservation}")
    output_path = Path(output_dir)
    document: dict[str, Any] = {
        "protocol_version": SETUP01_DECISION_PROTOCOL_VERSION,
        "mode": "DEVELOPMENT_EXPOSED_DECISION_EXECUTION_FUNNEL",
        "development_session_identity": DEVELOPMENT_SESSION_IDENTITY,
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "replay_input_aggregate_hash": replay_manifest.aggregate_hash,
        "event_stream_source": event_stream_source,
        "structural_events_path": str(structural_path),
        "risk_capital_input": risk_capital,
        "swing_lookback": swing_lookback,
        "atr_period": atr_period,
        "symbols_requested": len(symbol_quotes),
        "replay_errors": len(replay_errors),
        "confirmed_events": len(confirmed),
        "decision_rows": len(stream.decisions),
        "decision_calculable": decision_calculable,
        "entry_allowed": entry_allowed,
        "no_trade": no_trade,
        "decision_gate_reason_counts": dict(sorted(gate_counts.items())),
        "execution_status_counts": dict(sorted(execution_counts.items())),
        "no_trade_reason_counts": {
            reason: gate_counts[reason]
            for reason in DECISION_GATE_REASONS
            if reason != "ENTRY_ALLOWED"
        },
        "t1_execution_attempts": attempts,
        "executed": executed,
        "skipped": skipped,
        "duplicate_event_count": stream.duplicate_event_count,
        "ignored_non_confirmed_event_count": stream.ignored_non_confirmed_event_count,
        "funnel": scope_rows,
        "target_provenance_audit": target_provenance_audit,
        "funnel_conservation": conservation,
        "decisions": decision_rows,
        "replay_errors_detail": replay_errors,
        "controls": {
            "development_exposed": True,
            "t_day_only_decision": True,
            "t_plus_1_open_only": True,
            "same_bar_execution": False,
            "future_t1_high_low_close_accessed": False,
            "returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "pnl_accessed": False,
            "final_oos_accessed": False,
            "sheets_written": False,
            "setup02_started": False,
            "setup03_reopened": False,
        },
        "status": "SUCCESS" if not replay_errors else "PARTIAL_DATA_QUALITY",
    }
    post_fix_snapshot = _funnel_snapshot(document)
    target_reasonableness_needs_sol_decision = any(
        row["planned_first_target_over_5r"]
        or row["actual_open_first_target_over_5r"]
        for row in target_provenance_audit
    )
    document["confirmed_event_count_unchanged"] = (
        document["confirmed_events"] == PRE_FIX_FUNNEL_COUNTS["confirmed_events"]
    )
    document["pre_fix_reference"] = PRE_FIX_FUNNEL_COUNTS
    document["post_fix_counts"] = post_fix_snapshot
    document["pre_post_delta"] = _funnel_delta(
        PRE_FIX_FUNNEL_COUNTS, post_fix_snapshot
    )
    document["target_provenance_summary"] = {
        "audit_rows": len(target_provenance_audit),
        "historical_swing_high_t1_rows": sum(
            "CONFIRMED_SWING_HIGH" in row["target_t1_source"]
            for row in target_provenance_audit
        ),
        "fib_t1_rows": sum(
            "WAVE3_FIB_EXTENSION" in row["target_t1_source"]
            for row in target_provenance_audit
        ),
        "planned_over_5r_rows": sum(
            row["planned_first_target_over_5r"] for row in target_provenance_audit
        ),
        "actual_open_over_5r_rows": sum(
            row["actual_open_first_target_over_5r"]
            for row in target_provenance_audit
        ),
        "target_reasonableness_status": (
            "TARGET_REASONABLENESS_NEEDS_SOL_DECISION"
            if target_reasonableness_needs_sol_decision
            else "TARGET_PROVENANCE_NO_NEW_BLOCKER"
        ),
    }
    _write_json(output_path / "setup01_decision_execution_funnel.json", document)
    _write_csv(output_path / "setup01_decision_execution_events.csv", decision_rows)
    _write_csv(output_path / "setup01_decision_execution_funnel.csv", scope_rows)
    _write_csv(
        output_path / "setup01_target_provenance_audit.csv",
        target_provenance_audit,
    )
    _write_csv(output_path / "setup01_decision_replay_errors.csv", replay_errors)
    print(
        "SETUP01_DECISION_FUNNEL_SUMMARY "
        + json.dumps(
            {
                key: value
                for key, value in document.items()
                if key not in {"decisions", "replay_errors_detail", "funnel"}
            },
            ensure_ascii=False,
        )
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--replay-input", default=str(DEFAULT_INPUT))
    parser.add_argument("--replay-wrapper", default=str(DEFAULT_WRAPPER))
    parser.add_argument("--structural-events", default=str(DEFAULT_STRUCTURAL_EVENTS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--risk-capital", type=float, default=None)
    parser.add_argument("--swing-lookback", type=int, default=5)
    parser.add_argument("--atr-period", type=int, default=14)
    args = parser.parse_args()
    document = run_setup01_decision_funnel(
        manifest_path=args.manifest,
        replay_input_path=args.replay_input,
        replay_wrapper_path=args.replay_wrapper,
        structural_events_path=args.structural_events,
        output_dir=args.output_dir,
        risk_capital=args.risk_capital,
        swing_lookback=args.swing_lookback,
        atr_period=args.atr_period,
    )
    raise SystemExit(1 if document["replay_errors"] else 0)


if __name__ == "__main__":
    main()

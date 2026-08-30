"""Run the public synthetic SETUP_01 operational shadow.

This is the default product/integration gate for SETUP_01 Decision/Risk.  It
uses only controlled ``GENERIC.*`` fixtures and never imports credentials,
Sheets clients, or real holdings data.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.market_sessions import DEVELOPMENT_SESSION_IDENTITY
from trading.models import Setup01Evaluation, SetupState, SwingKind, SwingPoint
from trading.setup01_decision import (
    EXECUTED,
    SKIP_GAP_BELOW_CONFIRMATION,
    Setup01DecisionStream,
    evaluate_setup01_decision_stream,
    setup01_decision_to_dict,
    setup01_execution_to_dict,
)
from trading.setup01_replay import Setup01ReplayEvent


DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "setup01_generic_operational_shadow"
FIXTURE_VERSION = "SETUP-01-GENERIC-OPERATIONAL-SHADOW-FIXTURE-2026-08-30-v1"


def _quote(
    symbol: str,
    market: str,
    trade_date: date,
    close: float,
    opening: float | None = None,
) -> Quote:
    opening = close if opening is None else opening
    return Quote(
        symbol=symbol,
        name=f"Synthetic {symbol}",
        market=market,
        trade_date=trade_date,
        source="controlled-public-synthetic-fixture",
        open=opening,
        high=max(opening, close) + 1.0,
        low=min(opening, close) - 1.0,
        close=close,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD" if market == "US" else "CNY",
    )


def _quotes(symbol: str, market: str, t1_open: float) -> list[Quote]:
    start = date(2026, 3, 1)
    values = [100.0 + index * 0.15 for index in range(21)]
    values[-1] = 110.5
    quotes = [
        _quote(symbol, market, start + timedelta(days=index), value)
        for index, value in enumerate(values)
    ]
    quotes.append(_quote(symbol, market, start + timedelta(days=21), 110.0, t1_open))
    return quotes


def _swing(kind: SwingKind, price: float, index: int, start: date) -> SwingPoint:
    pivot_date = start + timedelta(days=index)
    return SwingPoint(kind, price, index, pivot_date, index, pivot_date)


def _confirmed_event(
    symbol: str,
    market: str,
    *,
    event_suffix: str,
    t1_open: float,
) -> tuple[Setup01ReplayEvent, list[Quote]]:
    start = date(2026, 3, 1)
    quotes = _quotes(symbol, market, t1_open)
    trade_date = quotes[-2].trade_date
    origin = _swing(SwingKind.LOW, 100.0, 5, start)
    peak = _swing(SwingKind.HIGH, 110.0, 10, start)
    wave2_low = _swing(SwingKind.LOW, 108.0, 15, start)
    snapshot = Setup01Evaluation(
        setup_type="SETUP_01",
        protocol_version="SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1",
        state=SetupState.CONFIRMED,
        as_of_date=trade_date,
        wave1_origin=origin,
        wave1_peak=peak,
        wave2_low=wave2_low,
        fib_retracement_ratio=0.5,
        fib_retracement_region="0.382-0.5",
        confirmation_level=110.0,
        structural_invalidation=108.0,
        wave_scenario_invalidation=100.0,
        wave1_origin_confirmed_date=origin.confirmed_date,
        wave1_peak_confirmed_date=peak.confirmed_date,
        wave2_low_confirmed_date=wave2_low.confirmed_date,
        state_entered_index=20,
        state_entered_date=trade_date,
        confirmed_index=20,
        confirmed_date=trade_date,
        failed_index=None,
        failed_date=None,
        primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
        alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
        reason="controlled synthetic first CONFIRMED event",
        terminal_event_type=SetupState.CONFIRMED,
        terminal_event_date=trade_date,
        is_new_confirmed_event_as_of=True,
        is_new_failed_event_as_of=False,
        is_live_preconfirmation_candidate=False,
        lifecycle_index=1,
    )
    event = Setup01ReplayEvent(
        event_identity=(
            f"{symbol}|SETUP_01|{trade_date.isoformat()}|CONFIRMED|{event_suffix}"
        ),
        symbol=symbol,
        trade_date=trade_date,
        event_type=SetupState.CONFIRMED,
        setup01=snapshot,
        market=market,
    )
    return event, quotes


def _fixture() -> tuple[list[Setup01ReplayEvent], dict[str, list[Quote]], dict[str, str]]:
    executed, executed_quotes = _confirmed_event(
        "GENERIC.EXEC.US", "US", event_suffix="executed", t1_open=110.75
    )
    skipped, skipped_quotes = _confirmed_event(
        "GENERIC.SKIP.CN", "CN", event_suffix="gap-below", t1_open=109.0
    )
    historical = replace(
        executed,
        event_identity="GENERIC.HIST.US|SETUP_01|historical-terminal",
        setup01=replace(
            executed.setup01,
            confirmed_date=executed.trade_date - timedelta(days=10),
            terminal_event_date=executed.trade_date - timedelta(days=10),
            is_new_confirmed_event_as_of=False,
        ),
    )
    live = replace(
        executed,
        event_identity="GENERIC.LIVE.US|SETUP_01|watch",
        event_type=SetupState.WATCH,
        setup01=replace(
            executed.setup01,
            state=SetupState.WATCH,
            confirmed_date=None,
            terminal_event_type=None,
            terminal_event_date=None,
            is_new_confirmed_event_as_of=False,
            is_live_preconfirmation_candidate=True,
        ),
    )
    failed = replace(
        executed,
        event_identity="GENERIC.FAILED.CN|SETUP_01|failed-terminal",
        event_type=SetupState.FAILED,
        setup01=replace(
            executed.setup01,
            state=SetupState.FAILED,
            confirmed_date=None,
            failed_date=executed.trade_date,
            terminal_event_type=SetupState.FAILED,
            terminal_event_date=executed.trade_date,
            is_new_confirmed_event_as_of=False,
            is_new_failed_event_as_of=True,
            is_live_preconfirmation_candidate=False,
        ),
    )
    malformed = replace(
        executed,
        event_identity="GENERIC.BAD.US|SETUP_01|malformed-confirmed",
        symbol="GENERIC.BAD.US",
        setup01=replace(
            executed.setup01,
            wave1_origin=None,
            wave1_peak=None,
            wave2_low=None,
            confirmation_level=None,
            structural_invalidation=None,
            wave_scenario_invalidation=None,
        ),
    )
    events = [executed, executed, skipped, historical, live, failed, malformed]
    quotes_by_symbol = {
        executed.symbol: executed_quotes,
        skipped.symbol: skipped_quotes,
    }
    classifications = {
        executed.event_identity: "NEW_CONFIRMED",
        skipped.event_identity: "NEW_CONFIRMED",
        historical.event_identity: "HISTORICAL_TERMINAL",
        live.event_identity: "LIVE_PRECONFIRMATION_CANDIDATE",
        failed.event_identity: "FAILED_TERMINAL",
        malformed.event_identity: "MALFORMED_NEW_CONFIRMED",
    }
    return events, quotes_by_symbol, classifications


def _write_report(output_dir: Path, document: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "setup01_generic_operational_shadow.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = document["rows"]
    fieldnames = list(rows[0]) if rows else ["event_identity"]
    with (output_dir / "setup01_generic_operational_shadow.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_setup01_generic_operational_shadow(
    output_dir: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    events, quotes_by_symbol, classifications = _fixture()
    stream: Setup01DecisionStream = evaluate_setup01_decision_stream(
        events, quotes_by_symbol, risk_capital=None
    )
    decisions_by_identity = {
        decision.event_identity: decision for decision in stream.decisions
    }
    executions_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    rows: list[dict[str, Any]] = []
    for event in events:
        decision = decisions_by_identity.get(event.event_identity)
        execution = executions_by_identity.get(event.event_identity)
        rows.append(
            {
                "event_identity": event.event_identity,
                "symbol": event.symbol,
                "market": event.market,
                "event_type": event.event_type.value,
                "fixture_classification": classifications[event.event_identity],
                "decision_generated": decision is not None,
                "decision": setup01_decision_to_dict(decision) if decision else None,
                "execution": (
                    setup01_execution_to_dict(execution) if execution else None
                ),
            }
        )
    executed = sum(item.outcome == EXECUTED for item in stream.executions)
    skipped_gap = sum(
        item.outcome == SKIP_GAP_BELOW_CONFIRMATION for item in stream.executions
    )
    execution_ledger_invariant = all(
        (execution.actual_entry is not None) == (execution.outcome == EXECUTED)
        for execution in stream.executions
    )
    historical_decision = any(
        row["fixture_classification"] == "HISTORICAL_TERMINAL"
        and row["decision_generated"]
        for row in rows
    )
    live_decision = any(
        row["fixture_classification"] == "LIVE_PRECONFIRMATION_CANDIDATE"
        and row["decision_generated"]
        for row in rows
    )
    failed_decision = any(
        row["fixture_classification"] == "FAILED_TERMINAL"
        and row["decision_generated"]
        for row in rows
    )
    malformed = decisions_by_identity["GENERIC.BAD.US|SETUP_01|malformed-confirmed"]
    checks = {
        "exact_once": len(stream.decisions) == 3 and stream.duplicate_event_count == 1,
        "t_close_to_t1_open": (
            executed == 1
            and skipped_gap == 1
            and all(
                execution.execution_date == execution.trade_date + timedelta(days=1)
                for execution in stream.executions
            )
        ),
        "terminal_semantics": (
            not historical_decision and not live_decision and not failed_decision
        ),
        "execution_ledger_invariant": execution_ledger_invariant,
        "fail_closed": (
            not malformed.decision_calculable
            and malformed.action.value == "NO_TRADE"
            and malformed.gate_reason.value == "INVALID_STRUCTURE"
        ),
        "reporting_pipeline": True,
    }
    document: dict[str, Any] = {
        "protocol_version": "SETUP-01-DECISION-RISK-2026-08-30-v1",
        "mode": "GENERIC_OPERATIONAL_SHADOW",
        "development_session_identity": DEVELOPMENT_SESSION_IDENTITY,
        "fixture_version": FIXTURE_VERSION,
        "fixture_source": "CONTROLLED_PUBLIC_SYNTHETIC_HOLDINGS_FIXTURE",
        "events_supplied": len(events),
        "unique_event_identities": len({event.event_identity for event in events}),
        "decision_rows": len(stream.decisions),
        "execution_attempts": len(stream.executions),
        "executed": executed,
        "skipped_gap_below_confirmation": skipped_gap,
        "duplicate_event_count": stream.duplicate_event_count,
        "ignored_non_confirmed_event_count": stream.ignored_non_confirmed_event_count,
        "checks": checks,
        "rows": rows,
        "controls": {
            "synthetic_only": True,
            "real_holdings_read": False,
            "account_secrets_required": False,
            "sheets_written": False,
            "returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "pnl_accessed": False,
            "final_oos_accessed": False,
            "setup02_started": False,
            "setup03_reopened": False,
        },
        "status": "SUCCESS" if all(checks.values()) else "FAILED",
    }
    _write_report(Path(output_dir), document)
    document["checks"]["reporting_pipeline"] = (
        Path(output_dir, "setup01_generic_operational_shadow.json").exists()
        and Path(output_dir, "setup01_generic_operational_shadow.csv").exists()
    )
    document["status"] = "SUCCESS" if all(document["checks"].values()) else "FAILED"
    _write_report(Path(output_dir), document)
    print(
        "SETUP01_GENERIC_OPERATIONAL_SHADOW_SUMMARY "
        + json.dumps(
            {key: value for key, value in document.items() if key not in {"rows"}},
            ensure_ascii=False,
        )
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    summary = run_setup01_generic_operational_shadow(args.output_dir)
    raise SystemExit(0 if summary["status"] == "SUCCESS" else 1)


if __name__ == "__main__":
    main()

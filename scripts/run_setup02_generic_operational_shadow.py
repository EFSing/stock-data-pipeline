"""Run the synthetic-only SETUP_02 generic operational validation.

The fixture is controlled and public.  It validates event consumption,
terminal filtering, exact T+1 OPEN semantics, gap/RR branches, fail-closed
handling, and execution-ledger reporting without real holdings or secrets.
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
from trading.models import SetupState, SwingKind, SwingPoint
from trading.setup02 import Setup02Evaluation
from trading.setup02_decision import (
    EXECUTED,
    SKIP_GAP_BELOW_CONFIRMATION,
    Setup02DecisionStream,
    evaluate_setup02_decision_stream,
    setup02_decision_to_dict,
    setup02_execution_to_dict,
)
from trading.setup02_replay import Setup02ReplayEvent


DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "setup02_generic_operational_shadow"
FIXTURE_VERSION = "SETUP-02-GENERIC-OPERATIONAL-SHADOW-FIXTURE-2026-09-01-v1"


def _quote(
    symbol: str,
    market: str,
    trade_date: date,
    close: float,
    opening: float | None = None,
    *,
    high: float = 130.0,
    low: float = 70.0,
) -> Quote:
    opening = close if opening is None else opening
    return Quote(
        symbol=symbol,
        name=f"Synthetic {symbol}",
        market=market,
        trade_date=trade_date,
        source="controlled-public-synthetic-fixture",
        open=opening,
        high=high,
        low=low,
        close=close,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD" if market == "US" else "CNY",
    )


def _swing(kind: SwingKind, price: float, index: int, start: date) -> SwingPoint:
    pivot_date = start + timedelta(days=index)
    return SwingPoint(kind, price, index, pivot_date, index, pivot_date)


def _confirmed_event(
    symbol: str,
    market: str,
    *,
    event_suffix: str,
    t1_open: float,
) -> tuple[Setup02ReplayEvent, list[Quote]]:
    start = date(2026, 3, 1)
    quotes = [
        _quote(symbol, market, start + timedelta(days=index), 100.0)
        for index in range(21)
    ]
    # This controlled prior high provides a confirmed-swing target above the
    # entry.  The continuation Fib candidates remain independently reported.
    quotes[10] = _quote(symbol, market, quotes[10].trade_date, 100.0, high=300.0)
    # The opposing low makes the high's confirmation available exactly by T.
    quotes[15] = _quote(symbol, market, quotes[15].trade_date, 100.0, low=20.0)
    t_day = quotes[-1].trade_date
    quotes[-1] = _quote(symbol, market, t_day, 140.0, high=150.0, low=70.0)
    quotes.append(
        _quote(
            symbol,
            market,
            t_day + timedelta(days=1),
            100.0,
            opening=t1_open,
        )
    )
    low0 = _swing(SwingKind.LOW, 100.0, 5, start)
    high1 = _swing(SwingKind.HIGH, 110.0, 10, start)
    low2 = _swing(SwingKind.LOW, 108.0, 15, start)
    high3 = _swing(SwingKind.HIGH, 120.0, 18, start)
    snapshot = Setup02Evaluation(
        setup_type="SETUP_02",
        protocol_version="SETUP-02-WAVE3-CONTINUATION-2026-09-01-v1",
        state=SetupState.CONFIRMED,
        as_of_date=t_day,
        continuation_low0=low0,
        continuation_high1=high1,
        continuation_low2=low2,
        continuation_high3=high3,
        fib_retracement_ratio=0.5,
        fib_retracement_region="0.382-0.5",
        confirmation_level=120.0,
        structural_invalidation=108.0,
        state_entered_index=20,
        state_entered_date=t_day,
        confirmed_index=20,
        confirmed_date=t_day,
        failed_index=None,
        failed_date=None,
        primary_wave_scenario="WAVE_3_CONTINUATION_CANDIDATE",
        alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
        reason="controlled synthetic first CONFIRMED event",
        terminal_event_type=SetupState.CONFIRMED,
        terminal_event_date=t_day,
        is_new_confirmed_event_as_of=True,
        is_new_failed_event_as_of=False,
        is_live_preconfirmation_candidate=False,
        lifecycle_index=1,
    )
    return (
        Setup02ReplayEvent(
            event_identity=(
                f"{symbol}|SETUP_02|{t_day.isoformat()}|CONFIRMED|{event_suffix}"
            ),
            symbol=symbol,
            trade_date=t_day,
            event_type=SetupState.CONFIRMED,
            setup02=snapshot,
            market=market,
        ),
        quotes,
    )


def _fixture() -> tuple[list[Setup02ReplayEvent], dict[str, list[Quote]], dict[str, str]]:
    executed, executed_quotes = _confirmed_event(
        "GENERIC.SETUP02.EXEC.US", "US", event_suffix="executed", t1_open=140.5
    )
    skipped, skipped_quotes = _confirmed_event(
        "GENERIC.SETUP02.SKIP.CN", "CN", event_suffix="gap-below", t1_open=119.0
    )
    historical = replace(
        executed,
        event_identity="GENERIC.SETUP02.HIST.US|historical-terminal",
        setup02=replace(
            executed.setup02,
            confirmed_date=executed.trade_date - timedelta(days=10),
            terminal_event_date=executed.trade_date - timedelta(days=10),
            is_new_confirmed_event_as_of=False,
        ),
    )
    live = replace(
        executed,
        event_identity="GENERIC.SETUP02.LIVE.US|watch",
        event_type=SetupState.WATCH,
        setup02=replace(
            executed.setup02,
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
        event_identity="GENERIC.SETUP02.FAILED.CN|failed-terminal",
        event_type=SetupState.FAILED,
        setup02=replace(
            executed.setup02,
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
        event_identity="GENERIC.SETUP02.BAD.US|malformed-confirmed",
        symbol="GENERIC.SETUP02.BAD.US",
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
    (output_dir / "setup02_generic_operational_shadow.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = document["rows"]
    fieldnames = list(rows[0]) if rows else ["event_identity"]
    with (output_dir / "setup02_generic_operational_shadow.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_setup02_generic_operational_shadow(
    output_dir: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    events, quotes_by_symbol, classifications = _fixture()
    stream: Setup02DecisionStream = evaluate_setup02_decision_stream(
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
                "decision": setup02_decision_to_dict(decision) if decision else None,
                "execution": setup02_execution_to_dict(execution) if execution else None,
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
    malformed = decisions_by_identity["GENERIC.SETUP02.BAD.US|malformed-confirmed"]
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
        "protocol_version": "SETUP-02-DECISION-RISK-2026-09-01-v1",
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
            "setup01_modified": False,
            "setup03_reopened": False,
        },
        "status": "SUCCESS" if all(checks.values()) else "FAILED",
    }
    output_path = Path(output_dir)
    _write_report(output_path, document)
    document["checks"]["reporting_pipeline"] = (
        (output_path / "setup02_generic_operational_shadow.json").exists()
        and (output_path / "setup02_generic_operational_shadow.csv").exists()
    )
    document["status"] = "SUCCESS" if all(document["checks"].values()) else "FAILED"
    _write_report(output_path, document)
    print(
        "SETUP02_GENERIC_OPERATIONAL_SHADOW_SUMMARY "
        + json.dumps(
            {key: value for key, value in document.items() if key != "rows"},
            ensure_ascii=False,
        )
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    summary = run_setup02_generic_operational_shadow(args.output_dir)
    raise SystemExit(0 if summary["status"] == "SUCCESS" else 1)


if __name__ == "__main__":
    main()

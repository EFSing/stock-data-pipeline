"""Run a synthetic-only prospective Paper trade lifecycle shadow.

The fixture is controlled and public: it exercises the existing SETUP_01
Decision, exact T+1 execution, PositionOrigin, and Position Management replay.
It never reads real holdings, credentials, Sheets, or a broker.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from scripts.run_setup01_generic_operational_shadow import _confirmed_event
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DATA_OK,
    DailySymbolInput,
)
from trading.paper_lifecycle import (
    PAPER_CLOSED_STATUS,
    PAPER_OPEN_STATUS,
    PAPER_SKIPPED_STATUS,
    InMemoryPaperLedgerStore,
    PaperLifecycleEngine,
    calculate_performance,
    grouped_performance,
)
from trading.setup01_decision import evaluate_setup01_decision
from trading.daily_dashboard import write_dashboard_html


DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "paper_trade_lifecycle_generic_operational_shadow"
FIXTURE_VERSION = "PAPER-TRADE-LIFECYCLE-GENERIC-OPERATIONAL-SHADOW-FIXTURE-2026-09-13-v1"


def _input(event: Any, quotes: list[Quote], as_of: date, next_session: date) -> DailySymbolInput:
    return DailySymbolInput(
        symbol=event.symbol,
        market=event.market,
        as_of_date=as_of,
        qfq_history=tuple(item for item in quotes if item.trade_date <= as_of),
        data_quality_status=DATA_OK,
        completed_session_identity=CompletedSessionIdentity(
            market=event.market,
            trade_date=as_of,
            identity=f"controlled:{event.market}:{as_of.isoformat()}",
            exact_exchange_calendar=True,
            next_session_date=next_session,
            session_dates=(as_of, next_session),
        ),
    )


def _result(event: Any, decision: Any, provenance: str) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=event.symbol,
        market=event.market,
        as_of_date=event.trade_date,
        primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
        individual_decision=decision,
        event_was_new=True,
        new_confirmed_event_identity=event.event_identity,
        new_confirmed_event_identities=(event.event_identity,),
        selected_event=event,
        provenance={"source": provenance},
    )


def _bar(source: Quote, day: date, opening: float, high: float, low: float, close: float) -> Quote:
    return replace(
        source,
        trade_date=day,
        open=opening,
        high=high,
        low=low,
        close=close,
    )


def _run_executed_path() -> tuple[InMemoryPaperLedgerStore, Any, Any, list[Quote]]:
    event, base_quotes = _confirmed_event(
        "GENERIC.PAPER.EXEC", "US", event_suffix="paper-executed", t1_open=110.75
    )
    decision = evaluate_setup01_decision(event, base_quotes)
    signal_date = event.trade_date
    t1 = signal_date + timedelta(days=1)
    t2 = signal_date + timedelta(days=2)
    t3 = signal_date + timedelta(days=3)
    quotes = [
        *base_quotes,
        _bar(base_quotes[-1], t2, 111.0, 130.0, 110.0, 113.0),
        _bar(base_quotes[-1], t3, 115.0, 116.0, 114.0, 115.0),
    ]
    store = InMemoryPaperLedgerStore()
    engine = PaperLifecycleEngine(store)
    result = _result(event, decision, "FORMAL_STRATEGY_POOL")
    engine.process_daily(
        (result,),
        (_input(event, quotes, signal_date, t1),),
        as_of_date=signal_date,
        provenance_by_symbol={event.symbol: {"source": "FORMAL_STRATEGY_POOL"}},
    )
    opened = engine.process_daily(
        (),
        (_input(event, quotes, t1, t2),),
        as_of_date=t1,
    )
    engine.process_daily(
        (),
        (_input(event, quotes, t2, t3),),
        as_of_date=t2,
    )
    closed = engine.process_daily(
        (),
        (_input(event, quotes, t3, t3 + timedelta(days=1)),),
        as_of_date=t3,
    )
    return store, opened, closed, quotes


def _run_skipped_path() -> tuple[InMemoryPaperLedgerStore, Any]:
    event, quotes = _confirmed_event(
        "GENERIC.PAPER.SKIP", "CN", event_suffix="paper-gap", t1_open=109.0
    )
    decision = evaluate_setup01_decision(event, quotes)
    signal_date = event.trade_date
    t1 = signal_date + timedelta(days=1)
    store = InMemoryPaperLedgerStore()
    engine = PaperLifecycleEngine(store)
    engine.process_daily(
        (_result(event, decision, "DYNAMIC_CANDIDATE"),),
        (_input(event, quotes, signal_date, t1),),
        as_of_date=signal_date,
        provenance_by_symbol={event.symbol: {"source": "DYNAMIC_CANDIDATE"}},
    )
    skipped = engine.process_daily(
        (),
        (_input(event, quotes, t1, t1 + timedelta(days=1)),),
        as_of_date=t1,
    )
    return store, skipped


def run_paper_trade_lifecycle_generic_operational_shadow(
    output_dir: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    executed_store, opened, closed, _ = _run_executed_path()
    skipped_store, skipped = _run_skipped_path()
    executed_trade = closed.trades[0]
    skipped_trade = skipped.trades[0]
    checks = {
        "plan_created": any(
            row["lifecycle_event_type"] == "PAPER_PLAN_CREATED"
            for row in executed_store.events
        ),
        "exact_t1_executed": (
            opened.trades[0].status == PAPER_OPEN_STATUS
            and opened.trades[0].execution_date == executed_trade.signal_date + timedelta(days=1)
            and opened.trades[0].actual_entry == 110.75
            and bool(opened.trades[0].position_origin_json)
        ),
        "profit_protection_closed": (
            executed_trade.status == PAPER_CLOSED_STATUS
            and executed_trade.exit_reason == "PROFIT_PROTECTION_EXIT_PENDING"
            and executed_trade.realized_r is not None
            and executed_trade.return_pct is not None
        ),
        "skip_terminal": (
            skipped_trade.status == PAPER_SKIPPED_STATUS
            and skipped_trade.execution_outcome == "SKIP_GAP_BELOW_CONFIRMATION"
            and skipped_trade.actual_entry is None
        ),
        "normalized_performance": (
            closed.performance.closed == 1
            and closed.performance.executed == 1
            and closed.performance.skipped == 0
            and closed.performance.win_rate == 1.0
        ),
        "candidate_not_promoted": (
            skipped_trade.promotion_required
            and not skipped_trade.state_persistence_eligible
            and not skipped_trade.production_execution_eligible
        ),
        "synthetic_only": True,
        "real_holdings_read": False,
        "account_secrets_required": False,
        "sheets_written": False,
        "broker_accessed": False,
        "historical_backfill": False,
    }
    checks_for_status = {
        key: value
        for key, value in checks.items()
        if key in {
            "plan_created",
            "exact_t1_executed",
            "profit_protection_closed",
            "skip_terminal",
            "normalized_performance",
            "candidate_not_promoted",
        }
    }
    document = {
        "protocol_version": "PROSPECTIVE-PAPER-TRADE-LIFECYCLE-2026-09-13-v1",
        "mode": "GENERIC_OPERATIONAL_SHADOW",
        "fixture_version": FIXTURE_VERSION,
        "fixture_source": "CONTROLLED_PUBLIC_SYNTHETIC_HOLDINGS_FIXTURE",
        "checks": checks,
        "executed_events": list(executed_store.events),
        "skipped_events": list(skipped_store.events),
        "closed_trade": executed_trade.to_dict(),
        "skipped_trade": skipped_trade.to_dict(),
        "performance": closed.performance.to_dict(),
        "status": "SUCCESS" if all(checks_for_status.values()) else "FAILED",
    }
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    dashboard_trades = (executed_trade, skipped_trade)
    dashboard_coverage = {
        item.market: item
        for item in (*closed.coverage, *skipped.coverage)
    }
    dashboard_result = {
        "trades": [item.to_dict() for item in dashboard_trades],
        "coverage": [item.to_dict() for item in dashboard_coverage.values()],
        "performance": calculate_performance(dashboard_trades).to_dict(),
        "grouped_performance": {
            dimension: {
                key: value.to_dict()
                for key, value in groups.items()
            }
            for dimension, groups in grouped_performance(dashboard_trades).items()
        },
        "errors": [],
    }
    dashboard_payload = {
        "as_of_date": executed_trade.exit_date,
        "generated_at": "CONTROLLED_SYNTHETIC_SHADOW",
        "demo_label": "Synthetic Paper Lifecycle Shadow",
        "reports": [],
        "paper_tracking": {"enabled": True, "result": dashboard_result},
    }
    dashboard_paths = write_dashboard_html(dashboard_payload, output_path)
    document["dashboard_html"] = [path.name for path in dashboard_paths]
    (output_path / "paper_trade_lifecycle_generic_operational_shadow.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "PAPER_TRADE_LIFECYCLE_GENERIC_OPERATIONAL_SHADOW_SUMMARY "
        + json.dumps(
            {
                "status": document["status"],
                "checks": document["checks"],
                "closed": document["performance"]["closed"],
                "skipped": document["skipped_trade"]["status"] == PAPER_SKIPPED_STATUS,
            },
            ensure_ascii=False,
        )
    )
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    document = run_paper_trade_lifecycle_generic_operational_shadow(args.output_dir)
    return 0 if document["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

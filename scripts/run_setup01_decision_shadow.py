"""Read-only SETUP_01 Decision/Risk shadow for real holdings.

The runner reads the existing watchlist and explicit qfq history source.  It
only creates a Decision when the latest as-of prefix contains a first
CONFIRMED event.  Historical terminal states and WATCH/ARMED context are
reported without re-decision or ``ENTRY_ALLOWED`` publication.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from core import latest_completed_market_session, ordinary_calendar_freshness_guard
from trading.models import SetupState
from trading.setup01 import SETUP01_PROTOCOL_VERSION, setup01_evaluation_to_dict
from trading.setup01_decision import (
    SETUP01_DECISION_PROTOCOL_VERSION,
    evaluate_setup01_decision_stream,
    setup01_decision_to_dict,
    setup01_execution_to_dict,
)
from trading.setup01_replay import replay_setup01_history


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "是"}


def _write_reports(output_dir: Path, document: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "setup01_decision_shadow_report.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = document["rows"]
    fieldnames = list(rows[0]) if rows else ["统一代码", "error"]
    with (output_dir / "setup01_decision_shadow_report.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _error_setup01_row() -> dict[str, Any]:
    return {
        "setup_type": "SETUP_01",
        "protocol_version": SETUP01_PROTOCOL_VERSION,
        "state": None,
        "terminal_event_type": None,
        "terminal_event_date": None,
        "is_new_confirmed_event_as_of": False,
        "is_new_failed_event_as_of": False,
        "is_live_preconfirmation_candidate": False,
    }


def run_setup01_decision_shadow(
    group: str = "all",
    output_dir: str | Path = "artifacts/setup01_decision_shadow",
    *,
    client=None,
    fetched_at: datetime | None = None,
    fetch_history=None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> dict[str, Any]:
    """Run a read-only current-holdings structural/decision shadow."""
    from main import wanted_markets_for_group
    from providers import QFQ_HISTORY_SOURCES, fetch_with_retry
    from sheets_client import SheetsClient

    if client is None:
        client = SheetsClient()
    if fetch_history is None:
        fetch_history = fetch_with_retry
    now = fetched_at or datetime.now().astimezone()
    config = client.config()
    retry_count = int(float(config.get("retry_count", 3)))
    retry_wait = float(config.get("retry_wait_seconds", 5))
    history_days = int(float(config.get("history_days", 1000)))
    end = now.date()
    start = end - timedelta(days=max(history_days * 2, 365))
    wanted_markets = wanted_markets_for_group(group)
    watches = [
        watch
        for watch in client.records("自选清单")
        if _as_bool(watch.get("启用")) and str(watch.get("市场")) in wanted_markets
    ]

    rows: list[dict[str, Any]] = []
    error_count = 0
    classification_counts: dict[str, int] = {}
    decision_count = 0
    entry_allowed_count = 0
    for watch in watches:
        symbol = str(watch.get("统一代码") or "").strip()
        market = str(watch.get("市场") or "")
        source = str(watch.get("历史数据源") or "").strip()
        history_last_date: date | None = None
        latest_completed_session: date | None = None
        try:
            if source not in QFQ_HISTORY_SOURCES:
                raise ValueError(f"历史数据源{source or '<empty>'}不支持qfq shadow")
            quotes = fetch_history(
                source,
                watch,
                "qfq",
                start,
                end,
                retry_count,
                retry_wait,
            )
            if not quotes:
                raise ValueError("qfq历史为空")
            history_last_date = max(quote.trade_date for quote in quotes)
            timezone_name = str(watch.get("时区") or "UTC")
            close_time = str(watch.get("收盘时间") or "23:59")
            latest_completed_session = latest_completed_market_session(
                timezone_name, close_time, now, quotes
            )
            freshness_floor = ordinary_calendar_freshness_guard(
                timezone_name, close_time, now
            )
            if latest_completed_session is None:
                raise ValueError("DATA_STALE: 没有有效的最新已完成市场交易日")
            if history_last_date != latest_completed_session:
                raise ValueError(
                    "DATA_STALE: qfq history_last_date "
                    f"{history_last_date.isoformat()}未对齐"
                    f"{latest_completed_session.isoformat()}"
                )
            if latest_completed_session < freshness_floor:
                raise ValueError(
                    "DATA_STALE: qfq history is older than freshness floor "
                    f"{freshness_floor.isoformat()}"
                )

            report = replay_setup01_history(
                quotes,
                as_of_date=latest_completed_session,
                daily_swing_lookback=daily_swing_lookback,
                weekly_swing_lookback=weekly_swing_lookback,
            )
            current = report.current
            setup01_row = setup01_evaluation_to_dict(current)
            new_confirmed_today = current.is_new_confirmed_event_as_of
            new_failed_today = current.is_new_failed_event_as_of
            live_candidate = current.is_live_preconfirmation_candidate
            decision_payload = None
            execution_payload = None
            if new_confirmed_today:
                current_event = next(
                    event
                    for event in report.events
                    if event.event_type is SetupState.CONFIRMED
                    and event.trade_date == latest_completed_session
                )
                # No reliable NAV is inferred from holdings shadow inputs.
                evaluated = evaluate_setup01_decision_stream(
                    (current_event,),
                    {symbol: quotes},
                    risk_capital=None,
                )
                if len(evaluated.decisions) != 1:
                    raise ValueError(
                        "new CONFIRMED event did not produce exactly one Decision"
                    )
                decision = evaluated.decisions[0]
                decision_payload = setup01_decision_to_dict(decision)
                execution = next(
                    (
                        item
                        for item in evaluated.executions
                        if item.event_identity == decision.event_identity
                    ),
                    None,
                )
                execution_payload = (
                    setup01_execution_to_dict(execution)
                    if execution is not None
                    else None
                )
                classification = "NEW_CONFIRMED_TODAY"
                decision_count += 1
                entry_allowed_count += int(decision.action.value == "ENTRY_ALLOWED")
            elif current.terminal_event_type in {
                SetupState.CONFIRMED,
                SetupState.FAILED,
            }:
                classification = "HISTORICAL_TERMINAL"
            elif live_candidate:
                classification = "LIVE_PRECONFIRMATION_CANDIDATE"
            else:
                classification = "NO_NEW_CONFIRMED_EVENT"
            classification_counts[classification] = classification_counts.get(classification, 0) + 1
            rows.append(
                {
                    "统一代码": symbol,
                    "名称": str(watch.get("名称") or ""),
                    "市场": market,
                    "as_of_date": latest_completed_session.isoformat(),
                    "history_last_date": history_last_date.isoformat(),
                    "freshness_status": "FRESH",
                    "current_structural_state": current.state.value,
                    "terminal_event_type": (
                        current.terminal_event_type.value
                        if current.terminal_event_type is not None
                        else None
                    ),
                    "terminal_event_date": (
                        current.terminal_event_date.isoformat()
                        if current.terminal_event_date is not None
                        else None
                    ),
                    "new_confirmed_today": new_confirmed_today,
                    "new_failed_today": new_failed_today,
                    "live_candidate": live_candidate,
                    "shadow_classification": classification,
                    "decision_generated": decision_payload is not None,
                    "decision": decision_payload,
                    "execution": execution_payload,
                    "SETUP_01": setup01_row,
                    "data_source": source,
                    "error": "",
                }
            )
        except Exception as exc:
            error_count += 1
            classification_counts["FAIL_CLOSED_DATA_QUALITY"] = (
                classification_counts.get("FAIL_CLOSED_DATA_QUALITY", 0) + 1
            )
            rows.append(
                {
                    "统一代码": symbol,
                    "名称": str(watch.get("名称") or ""),
                    "市场": market,
                    "as_of_date": (
                        latest_completed_session.isoformat()
                        if latest_completed_session is not None
                        else None
                    ),
                    "history_last_date": (
                        history_last_date.isoformat() if history_last_date else None
                    ),
                    "freshness_status": "DATA_STALE",
                    "current_structural_state": None,
                    "terminal_event_type": None,
                    "terminal_event_date": None,
                    "new_confirmed_today": False,
                    "new_failed_today": False,
                    "live_candidate": False,
                    "shadow_classification": "FAIL_CLOSED_DATA_QUALITY",
                    "decision_generated": False,
                    "decision": None,
                    "execution": None,
                    "SETUP_01": _error_setup01_row(),
                    "data_source": source,
                    "error": str(exc),
                }
            )

    document = {
        "protocol_version": SETUP01_DECISION_PROTOCOL_VERSION,
        "structural_protocol_version": SETUP01_PROTOCOL_VERSION,
        "mode": "REAL_HOLDINGS_READ_ONLY_DECISION_SHADOW",
        "group": group,
        "symbols_requested": len(watches),
        "evaluated": len(watches) - error_count,
        "errors": error_count,
        "new_confirmed_today": sum(int(row["new_confirmed_today"]) for row in rows),
        "new_failed_today": sum(int(row["new_failed_today"]) for row in rows),
        "live_candidates": sum(int(row["live_candidate"]) for row in rows),
        "historical_terminals": classification_counts.get("HISTORICAL_TERMINAL", 0),
        "decision_generated": decision_count,
        "entry_allowed": entry_allowed_count,
        "classification_counts": classification_counts,
        "risk_capital": None,
        "position_size_required_input": True,
        "returns_accessed": False,
        "oos_accessed": False,
        "sheets_written": False,
        "setup02_started": False,
        "setup03_reopened": False,
        "generated_at": now.isoformat(),
        "rows": rows,
        "status": "SUCCESS" if error_count == 0 else "PARTIAL_DATA_QUALITY",
    }
    _write_reports(Path(output_dir), document)
    print(
        "SETUP01_DECISION_SHADOW_SUMMARY "
        + json.dumps({key: value for key, value in document.items() if key != "rows"}, ensure_ascii=False)
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["asia", "us", "all"], default="all")
    parser.add_argument("--output-dir", default="artifacts/setup01_decision_shadow")
    parser.add_argument("--daily-lookback", type=int, default=5)
    parser.add_argument("--weekly-lookback", type=int, default=5)
    args = parser.parse_args()
    summary = run_setup01_decision_shadow(
        args.group,
        args.output_dir,
        daily_swing_lookback=args.daily_lookback,
        weekly_swing_lookback=args.weekly_lookback,
    )
    raise SystemExit(1 if summary["errors"] else 0)


if __name__ == "__main__":
    main()

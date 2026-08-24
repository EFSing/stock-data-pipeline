from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import expected_latest_trade_date
from main import as_bool, beijing_now, trading_parameters
from providers import QFQ_HISTORY_SOURCES, fetch_with_retry
from sheets_client import SheetsClient
from trading.models import DecisionAction, SetupState
from trading.replay import (
    replay_event_rows,
    replay_setup03_history,
    validate_replay_history,
)


OUTPUT_DIR = Path("artifacts") / "setup03_replay"
SUMMARY_PATH = OUTPUT_DIR / "setup03_replay_summary.csv"
SKIPPED_PATH = OUTPUT_DIR / "setup03_replay_skipped.csv"
EVENTS_PATH = OUTPUT_DIR / "setup03_replay_events.csv"
EVENT_HEADERS = [
    "统一代码",
    "交易日期",
    "事件类型",
    "Setup状态",
    "detected_index",
    "state_entered_index",
    "confirmed_index",
    "突破价",
    "结构失效价",
    "Decision动作",
    "计划入场",
    "执行止损",
    "T1",
    "T1_RR",
    "历史数据源",
    "参数版本",
    "参数快照",
]


def main() -> None:
    client = SheetsClient()
    config = client.config()
    setup_parameters, decision_parameters, risk_capital = trading_parameters(config)
    retry_count = int(float(config.get("retry_count", 3)))
    retry_wait = float(config.get("retry_wait_seconds", 5))
    minimum_rows = int(
        float(
            config.get(
                "replay_min_history_rows",
                max(
                    setup_parameters["platform_window"]
                    + 2 * setup_parameters["swing_lookback"]
                    + 1,
                    decision_parameters["atr_period"] + 1,
                ),
            )
        )
    )
    max_gap_days = int(float(config.get("replay_max_calendar_gap_days", 14)))
    max_latest_lag_days = int(float(config.get("replay_max_latest_lag_days", 14)))
    fetched_at = beijing_now()
    end = fetched_at.date()
    start = end - timedelta(days=365 * 3)
    parameter_snapshot, parameter_version = _parameter_metadata(
        setup_parameters,
        decision_parameters,
        risk_capital,
        minimum_rows,
        max_gap_days,
        max_latest_lag_days,
    )

    rows: list[dict] = []
    skipped: list[dict] = []
    event_rows: list[dict] = []
    enabled_count = 0
    for watch in client.records("自选清单"):
        symbol = str(watch.get("统一代码") or "").strip()
        if not as_bool(watch.get("启用")):
            skipped.append({"统一代码": symbol, "启用": False, "原因": "未启用"})
            continue
        enabled_count += 1
        historical_source = str(watch.get("历史数据源") or "").strip()
        if historical_source not in QFQ_HISTORY_SOURCES:
            skipped.append(
                {
                    "统一代码": symbol,
                    "启用": True,
                    "原因": f"历史数据源{historical_source or '<空>'}不支持qfq",
                }
            )
            continue
        try:
            expected_latest_date = expected_latest_trade_date(
                str(watch["时区"]),
                str(watch["收盘时间"]),
                fetched_at,
            )
            quotes = fetch_with_retry(
                historical_source,
                watch,
                "qfq",
                start,
                end,
                retry_count,
                retry_wait,
                target_trade_date=expected_latest_date,
                preserve_source_order=True,
            )
            validate_replay_history(
                quotes,
                as_of_date=end,
                expected_latest_date=expected_latest_date,
                minimum_rows=minimum_rows,
                max_calendar_gap_days=max_gap_days,
                max_latest_lag_days=max_latest_lag_days,
            )
            report = replay_setup03_history(
                quotes,
                risk_capital,
                setup_parameters,
                decision_parameters,
            )
        except Exception as exc:
            skipped.append({"统一代码": symbol, "启用": True, "原因": str(exc)})
            continue
        row = report.summary_row()
        row["名称"] = str(watch.get("名称") or "")
        row["历史数据源"] = historical_source
        row["起始日期"] = quotes[0].trade_date.isoformat()
        row["结束日期"] = quotes[-1].trade_date.isoformat()
        row["期望最新日期"] = (
            expected_latest_date.isoformat() if expected_latest_date else ""
        )
        row["样本数"] = len(quotes)
        rows.append(row)
        event_rows.extend(
            replay_event_rows(
                report,
                historical_source,
                parameter_version,
                parameter_snapshot,
            )
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(SUMMARY_PATH, rows)
    _write_csv(SKIPPED_PATH, skipped)
    _write_csv(EVENTS_PATH, event_rows, EVENT_HEADERS)
    _print_summary(rows, skipped, enabled_count, len(event_rows))
    if enabled_count == 0 or not rows:
        raise RuntimeError(
            "SETUP_03 replay failed: calculable/enabled coverage is zero "
            f"({len(rows)}/{enabled_count})"
        )


def _write_csv(
    path: Path,
    rows: list[dict],
    empty_fieldnames: list[str] | None = None,
) -> None:
    fieldnames = _fieldnames(rows, empty_fieldnames)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fieldnames(
    rows: list[dict], empty_fieldnames: list[str] | None = None
) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen or list(empty_fieldnames or ["统一代码", "原因"])


def _print_summary(
    rows: list[dict],
    skipped: list[dict],
    enabled_count: int,
    event_count: int,
) -> None:
    coverage = len(rows) / enabled_count if enabled_count else 0.0
    print(
        "SETUP_03 replay completed: "
        f"calculable={len(rows)}, enabled={enabled_count}, "
        f"coverage={coverage:.2%}, skipped={len(skipped)}, events={event_count}"
    )
    print(f"summary_csv={SUMMARY_PATH}")
    print(f"skipped_csv={SKIPPED_PATH}")
    print(f"events_csv={EVENTS_PATH}")
    for row in rows:
        symbol = row["统一代码"]
        name = row.get("名称") or ""
        confirmed = row.get("CONFIRMED事件次数", 0)
        failed = row.get("FAILED事件次数", 0)
        entry_allowed = row.get(f"{DecisionAction.ENTRY_ALLOWED.value}事件次数", 0)
        no_trade = row.get(f"{DecisionAction.NO_TRADE.value}事件次数", 0)
        confirmed_dates = row.get("CONFIRMED事件日期") or "<none>"
        state_days = ", ".join(
            f"{state.value}={row.get(f'{state.value}状态日数', 0)}"
            for state in (
                SetupState.NONE,
                SetupState.WATCH,
                SetupState.ARMED,
                SetupState.CONFIRMED,
                SetupState.FAILED,
            )
        )
        print(
            f"{symbol} {name}: {state_days}; "
            f"CONFIRMED_events={confirmed} [{confirmed_dates}]; "
            f"FAILED_events={failed}; "
            f"ENTRY_ALLOWED={entry_allowed}; NO_TRADE={no_trade}"
        )
    if skipped:
        print("Skipped symbols:")
        for row in skipped:
            print(f"{row.get('统一代码')}: {row.get('原因')}")


def _parameter_metadata(
    setup_parameters: dict,
    decision_parameters: dict,
    risk_capital: float,
    minimum_rows: int,
    max_gap_days: int,
    max_latest_lag_days: int,
) -> tuple[str, str]:
    snapshot = json.dumps(
        {
            "setup": setup_parameters,
            "decision": decision_parameters,
            "risk_capital": risk_capital,
            "replay_quality": {
                "minimum_rows": minimum_rows,
                "max_calendar_gap_days": max_gap_days,
                "max_latest_lag_days": max_latest_lag_days,
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    version = f"sha256:{hashlib.sha256(snapshot.encode('utf-8')).hexdigest()[:12]}"
    return snapshot, version


if __name__ == "__main__":
    main()

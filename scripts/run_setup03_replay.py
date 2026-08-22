from __future__ import annotations

import csv
from datetime import timedelta
from pathlib import Path

from main import as_bool, beijing_now, trading_parameters
from providers import QFQ_HISTORY_SOURCES, fetch_with_retry
from sheets_client import SheetsClient
from trading.models import DecisionAction, SetupState
from trading.replay import replay_setup03_history


OUTPUT_DIR = Path("artifacts") / "setup03_replay"
SUMMARY_PATH = OUTPUT_DIR / "setup03_replay_summary.csv"
SKIPPED_PATH = OUTPUT_DIR / "setup03_replay_skipped.csv"


def main() -> None:
    client = SheetsClient()
    config = client.config()
    setup_parameters, decision_parameters, risk_capital = trading_parameters(config)
    retry_count = int(float(config.get("retry_count", 3)))
    retry_wait = float(config.get("retry_wait_seconds", 5))
    end = beijing_now().date()
    start = end - timedelta(days=365 * 3)

    rows: list[dict] = []
    skipped: list[dict] = []
    for watch in client.records("自选清单"):
        symbol = str(watch.get("统一代码") or "").strip()
        if not as_bool(watch.get("启用")):
            skipped.append({"统一代码": symbol, "原因": "未启用"})
            continue
        historical_source = str(watch.get("历史数据源") or "").strip()
        if historical_source not in QFQ_HISTORY_SOURCES:
            skipped.append(
                {
                    "统一代码": symbol,
                    "原因": f"历史数据源{historical_source or '<空>'}不支持qfq",
                }
            )
            continue
        try:
            quotes = fetch_with_retry(
                historical_source,
                watch,
                "qfq",
                start,
                end,
                retry_count,
                retry_wait,
            )
            report = replay_setup03_history(
                quotes,
                risk_capital,
                setup_parameters,
                decision_parameters,
            )
        except Exception as exc:
            skipped.append({"统一代码": symbol, "原因": str(exc)})
            continue
        row = report.summary_row()
        row["名称"] = str(watch.get("名称") or "")
        row["历史数据源"] = historical_source
        row["起始日期"] = quotes[0].trade_date.isoformat()
        row["结束日期"] = quotes[-1].trade_date.isoformat()
        rows.append(row)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(SUMMARY_PATH, rows)
    _write_csv(SKIPPED_PATH, skipped)
    _print_summary(rows, skipped)


def _write_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = _fieldnames(rows)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fieldnames(rows: list[dict]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen or ["统一代码", "原因"]


def _print_summary(rows: list[dict], skipped: list[dict]) -> None:
    print(f"SETUP_03 replay completed: calculable={len(rows)}, skipped={len(skipped)}")
    print(f"summary_csv={SUMMARY_PATH}")
    print(f"skipped_csv={SKIPPED_PATH}")
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


if __name__ == "__main__":
    main()

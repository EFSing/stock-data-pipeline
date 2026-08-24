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

from core import Quote, expected_latest_trade_date
from main import as_bool, beijing_now, trading_parameters
from providers import QFQ_HISTORY_SOURCES, fetch_with_retry
from research.backtest.setup03 import (
    parameter_sensitivity_rows,
    research_funnel_counts,
    research_trade_outcomes,
)
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
OUTCOMES_PATH = OUTPUT_DIR / "setup03_trade_outcomes.csv"
SENSITIVITY_PATH = OUTPUT_DIR / "setup03_parameter_sensitivity.csv"
EVENT_HEADERS = [
    "统一代码",
    "交易日期",
    "事件类型",
    "signal_date",
    "confirmed_date",
    "signal_close",
    "ATR",
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
    "T2",
    "T2_RR",
    "T3",
    "T3_RR",
    "历史数据源",
    "参数版本",
    "参数快照",
]
OUTCOME_HEADERS = [
    "symbol",
    "market",
    "signal_date",
    "confirmed_date",
    "T+1_date",
    "execution_status",
    "T+1_open",
    "actual_entry",
    "entry_zone_high",
    "stop",
    "T1",
    "T2",
    "T3",
    "5D_return",
    "10D_return",
    "20D_return",
    "MFE_pct",
    "MAE_pct",
    "MFE_R",
    "MAE_R",
    "first_exit_event",
    "first_exit_date",
    "final_R",
    "observation_days",
    "horizon_complete",
    "历史数据源",
    "参数版本",
]
SENSITIVITY_HEADERS = [
    "setup_swing_lookback",
    "platform_window",
    "platform_tolerance_pct",
    "symbol_count",
    "input_bar_count",
    "sample_size",
    "confirmed_count",
    "entry_allowed_count",
    "signal_not_entry_allowed_count",
    "skip_no_t1_count",
    "skip_gap_below_breakout_count",
    "skip_gap_above_entry_zone_count",
    "executed_count",
    "other_execution_status_count",
    "censored_count",
    "win_rate",
    "avg_R",
    "expectancy",
    "profit_factor",
    "MFE",
    "MAE",
    "生产参数版本",
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
    outcome_rows: list[dict] = []
    production_funnel_rows: list[dict[str, int]] = []
    symbol_quotes: dict[str, list[Quote]] = {}
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
        row["参数版本"] = parameter_version
        row["参数快照"] = parameter_snapshot
        event_rows.extend(
            replay_event_rows(
                report,
                historical_source,
                parameter_version,
                parameter_snapshot,
            )
        )
        symbol_quotes[symbol] = quotes
        research_report = research_trade_outcomes(report, quotes)
        symbol_funnel = research_funnel_counts(report, research_report)
        row.update(symbol_funnel)
        production_funnel_rows.append(symbol_funnel)
        rows.append(row)
        for outcome in research_report.outcomes:
            outcome_row = outcome.to_row()
            outcome_row["历史数据源"] = historical_source
            outcome_row["参数版本"] = parameter_version
            outcome_rows.append(outcome_row)

    sensitivity_rows = (
        parameter_sensitivity_rows(
            symbol_quotes,
            risk_capital,
            setup_parameters,
            decision_parameters,
        )
        if symbol_quotes
        else []
    )
    for sensitivity_row in sensitivity_rows:
        sensitivity_row["生产参数版本"] = parameter_version

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(SUMMARY_PATH, rows)
    _write_csv(SKIPPED_PATH, skipped)
    _write_csv(EVENTS_PATH, event_rows, EVENT_HEADERS)
    _write_csv(OUTCOMES_PATH, outcome_rows, OUTCOME_HEADERS)
    _write_csv(SENSITIVITY_PATH, sensitivity_rows, SENSITIVITY_HEADERS)
    production_funnel = {
        key: sum(row[key] for row in production_funnel_rows)
        for key in (
            "confirmed_count",
            "entry_allowed_count",
            "signal_not_entry_allowed_count",
            "skip_no_t1_count",
            "skip_gap_below_breakout_count",
            "skip_gap_above_entry_zone_count",
            "executed_count",
            "other_execution_status_count",
        )
    }
    _print_summary(
        rows,
        skipped,
        enabled_count,
        len(event_rows),
        parameter_version,
        production_funnel,
    )
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
    seen: list[str] = list(empty_fieldnames or [])
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen or ["统一代码", "原因"]


def _print_summary(
    rows: list[dict],
    skipped: list[dict],
    enabled_count: int,
    event_count: int,
    parameter_version: str,
    production_funnel: dict[str, int],
) -> None:
    coverage = len(rows) / enabled_count if enabled_count else 0.0
    print(
        "SETUP_03 replay completed: "
        f"calculable={len(rows)}, enabled={enabled_count}, "
        f"coverage={coverage:.2%}, skipped={len(skipped)}, events={event_count}"
    )
    print(
        "production_parameters_funnel: "
        f"CONFIRMED={production_funnel['confirmed_count']}, "
        f"ENTRY_ALLOWED={production_funnel['entry_allowed_count']}, "
        "SIGNAL_NOT_ENTRY_ALLOWED="
        f"{production_funnel['signal_not_entry_allowed_count']}, "
        f"SKIP_NO_T1={production_funnel['skip_no_t1_count']}, "
        "SKIP_GAP_BELOW_BREAKOUT="
        f"{production_funnel['skip_gap_below_breakout_count']}, "
        "SKIP_GAP_ABOVE_ENTRY_ZONE="
        f"{production_funnel['skip_gap_above_entry_zone_count']}, "
        f"EXECUTED={production_funnel['executed_count']}, "
        f"OTHER={production_funnel['other_execution_status_count']}"
    )
    print(f"summary_csv={SUMMARY_PATH}")
    print(f"skipped_csv={SKIPPED_PATH}")
    print(f"events_csv={EVENTS_PATH}")
    print(f"outcomes_csv={OUTCOMES_PATH}")
    print(f"sensitivity_csv={SENSITIVITY_PATH}")
    print(f"parameter_version={parameter_version}")
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

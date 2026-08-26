from __future__ import annotations

import argparse
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
    DECISION_GATE_REASONS,
    parameter_sensitivity_artifacts,
    research_funnel_counts,
    research_trade_outcomes,
)
from research.frozen_validation import (
    PHASE5E_DATASET_HASH,
    PHASE5E_SOURCE_RUN_ID,
    frozen_validation_artifacts,
    render_frozen_validation_report,
    validate_phase5e_baseline,
)
from research.confirmation_diagnostics import (
    confirmation_gate_artifacts,
    render_confirmation_report,
)
from research.platform_tolerance_sensitivity import (
    platform_tolerance_sensitivity_artifacts,
    render_platform_tolerance_report,
)
from research.replay_input import (
    ManifestChange,
    build_input_manifest,
    compare_input_manifests,
    comparison_rows,
    read_frozen_input,
    read_input_manifest,
    write_frozen_input,
    write_input_manifest,
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
DECISION_GATE_DIAGNOSTICS_PATH = (
    OUTPUT_DIR / "setup03_decision_gate_diagnostics.csv"
)
DECISION_GATE_SUMMARY_PATH = OUTPUT_DIR / "setup03_decision_gate_summary.csv"
INPUT_MANIFEST_JSON_PATH = OUTPUT_DIR / "setup03_replay_input_manifest.json"
INPUT_MANIFEST_CSV_PATH = OUTPUT_DIR / "setup03_replay_input_manifest.csv"
FROZEN_INPUT_PATH = OUTPUT_DIR / "setup03_replay_input.jsonl.gz"
INPUT_COMPARISON_PATH = OUTPUT_DIR / "setup03_replay_input_comparison.csv"
FROZEN_VALIDATION_SUMMARY_PATH = OUTPUT_DIR / "setup03_冻结验证_核心统计.csv"
FROZEN_VALIDATION_REASONS_PATH = OUTPUT_DIR / "setup03_冻结验证_Decision原因.csv"
FROZEN_VALIDATION_DISTRIBUTION_PATH = OUTPUT_DIR / "setup03_冻结验证_分布.csv"
FROZEN_VALIDATION_CONCENTRATION_PATH = OUTPUT_DIR / "setup03_冻结验证_集中度.csv"
FROZEN_VALIDATION_SIGNAL_PATH_PATH = OUTPUT_DIR / "setup03_冻结验证_信号后路径.csv"
FROZEN_VALIDATION_FORWARD_PATH = OUTPUT_DIR / "setup03_冻结验证_Forward_MAE_MFE.csv"
FROZEN_VALIDATION_REPORT_PATH = OUTPUT_DIR / "setup03_冻结验证报告.md"
CONFIRMATION_DETAIL_PATH = OUTPUT_DIR / "setup03_确认门诊断_逐bar.csv"
CONFIRMATION_REASON_PATH = OUTPUT_DIR / "setup03_确认门诊断_terminal_reason.csv"
CONFIRMATION_GATE_PATH = OUTPUT_DIR / "setup03_确认门诊断_完整漏斗.csv"
CONFIRMATION_NEAR_MISS_PATH = OUTPUT_DIR / "setup03_确认门诊断_near_miss.csv"
CONFIRMATION_AUXILIARY_PATH = OUTPUT_DIR / "setup03_确认门诊断_辅助多重失败.csv"
CONFIRMATION_REPORT_PATH = OUTPUT_DIR / "setup03_确认门诊断报告.md"
TOLERANCE_FUNNEL_PATH = OUTPUT_DIR / "setup03_平台容差敏感性_完整漏斗.csv"
TOLERANCE_CONFIRMATION_REASON_PATH = OUTPUT_DIR / "setup03_平台容差敏感性_Confirmation原因.csv"
TOLERANCE_DECISION_REASON_PATH = OUTPUT_DIR / "setup03_平台容差敏感性_Decision原因.csv"
TOLERANCE_DISTRIBUTION_PATH = OUTPUT_DIR / "setup03_平台容差敏感性_标的市场年份分布.csv"
TOLERANCE_FORWARD_PATH = OUTPUT_DIR / "setup03_平台容差敏感性_Forward_MAE_MFE.csv"
TOLERANCE_STRUCTURE_PATH = OUTPUT_DIR / "setup03_平台容差敏感性_结构稳定性.csv"
TOLERANCE_REPORT_PATH = OUTPUT_DIR / "setup03_Phase5G平台容差敏感性报告.md"
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
DECISION_GATE_DIAGNOSTIC_HEADERS = [
    "symbol",
    "signal_date",
    "confirmed_date",
    "setup_swing_lookback",
    "platform_window",
    "platform_tolerance_pct",
    "breakout_price",
    "structural_invalidation",
    "signal_close",
    "ATR",
    "decision_action",
    "decision_gate_reason",
    "planned_entry",
    "entry_zone_low",
    "entry_zone_high",
    "execution_stop",
    "T1",
    "T1_RR",
    "decision_index",
    "confirmed_index",
    "生产参数版本",
]
DECISION_GATE_SUMMARY_HEADERS = [
    "setup_swing_lookback",
    "platform_window",
    "platform_tolerance_pct",
    "CONFIRMED",
    "ENTRY_ALLOWED",
    *[
        field
        for reason in DECISION_GATE_REASONS
        for field in (f"{reason.value}_count", f"{reason.value}_ratio")
    ],
    "生产参数版本",
]
INPUT_MANIFEST_HEADERS = [
    "symbol",
    "bar_count",
    "start_date",
    "end_date",
    "input_hash",
    "aggregate_hash",
    "total_symbol_count",
    "total_bar_count",
    "schema_version",
]
INPUT_COMPARISON_HEADERS = [
    "symbol",
    "status",
    "previous_bar_count",
    "current_bar_count",
    "previous_start_date",
    "current_start_date",
    "previous_end_date",
    "current_end_date",
    "previous_input_hash",
    "current_input_hash",
]
FROZEN_VALIDATION_SIGNAL_PATH_HEADERS = [
    "统一代码",
    "市场",
    "信号日期",
    "年份",
    "季度",
    "信号收盘价",
    "可用后续交易日",
    *[
        field
        for horizon in (5, 10, 20)
        for field in (
            f"{horizon}D完整",
            f"{horizon}D_forward_return",
            f"{horizon}D_MFE",
            f"{horizon}D_MAE",
        )
    ],
]


def main(argv: tuple[str, ...] | list[str] = ()) -> None:
    args = _parse_args(argv)
    frozen_symbol_quotes = None
    frozen_input_manifest = None
    if args.frozen_input is not None:
        frozen_symbol_quotes, frozen_input_manifest = read_frozen_input(
            args.frozen_input
        )
    if args.phase5e and frozen_symbol_quotes is None:
        raise ValueError("Phase 5E requires --frozen-input; live history is forbidden")
    if args.phase5f and not args.phase5e:
        raise ValueError("Phase 5F requires --phase5e on the fixed frozen baseline")
    if args.phase5g and not args.phase5e:
        raise ValueError("Phase 5G requires --phase5e on the fixed frozen baseline")
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
    if args.phase5e:
        assert frozen_input_manifest is not None
        validate_phase5e_baseline(frozen_input_manifest, parameter_version)

    rows: list[dict] = []
    skipped: list[dict] = []
    event_rows: list[dict] = []
    outcome_rows: list[dict] = []
    production_funnel_rows: list[dict[str, int]] = []
    symbol_quotes: dict[str, list[Quote]] = {}
    replay_reports = {}
    research_reports = {}
    enabled_count = 0
    if args.phase5e:
        assert frozen_symbol_quotes is not None
        watch_rows = [
            {
                "启用": True,
                "统一代码": symbol,
                "名称": quotes[0].name,
                "市场": quotes[0].market,
                "历史数据源": quotes[0].source,
            }
            for symbol, quotes in sorted(frozen_symbol_quotes.items())
        ]
    else:
        watch_rows = client.records("自选清单")
    for watch in watch_rows:
        symbol = str(watch.get("统一代码") or "").strip()
        if not as_bool(watch.get("启用")):
            skipped.append({"统一代码": symbol, "启用": False, "原因": "未启用"})
            continue
        enabled_count += 1
        historical_source = str(watch.get("历史数据源") or "").strip()
        if not args.phase5e and historical_source not in QFQ_HISTORY_SOURCES:
            skipped.append(
                {
                    "统一代码": symbol,
                    "启用": True,
                    "原因": f"历史数据源{historical_source or '<空>'}不支持qfq",
                }
            )
            continue
        try:
            if frozen_symbol_quotes is None:
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
                quality_as_of_date = end
                quality_expected_latest_date = expected_latest_date
            else:
                if symbol not in frozen_symbol_quotes:
                    raise ValueError(f"frozen input is missing enabled symbol: {symbol}")
                quotes = list(frozen_symbol_quotes[symbol])
                expected_latest_date = quotes[-1].trade_date
                quality_as_of_date = quotes[-1].trade_date
                quality_expected_latest_date = quotes[-1].trade_date
            validate_replay_history(
                quotes,
                as_of_date=quality_as_of_date,
                expected_latest_date=quality_expected_latest_date,
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
        replay_reports[symbol] = report
        research_reports[symbol] = research_report
        symbol_funnel = research_funnel_counts(report, research_report)
        row.update(symbol_funnel)
        production_funnel_rows.append(symbol_funnel)
        rows.append(row)
        for outcome in research_report.outcomes:
            outcome_row = outcome.to_row()
            outcome_row["历史数据源"] = historical_source
            outcome_row["参数版本"] = parameter_version
            outcome_rows.append(outcome_row)

    if symbol_quotes and not args.phase5e:
        parameter_artifacts = parameter_sensitivity_artifacts(
            symbol_quotes,
            risk_capital,
            setup_parameters,
            decision_parameters,
        )
        sensitivity_rows = [dict(row) for row in parameter_artifacts.sensitivity_rows]
        decision_gate_rows = [
            dict(row) for row in parameter_artifacts.decision_gate_rows
        ]
        decision_gate_summary_rows = [
            dict(row) for row in parameter_artifacts.decision_gate_summary_rows
        ]
    else:
        sensitivity_rows = []
        decision_gate_rows = []
        decision_gate_summary_rows = []
    for artifact_rows in (
        sensitivity_rows,
        decision_gate_rows,
        decision_gate_summary_rows,
    ):
        for artifact_row in artifact_rows:
            artifact_row["生产参数版本"] = parameter_version

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    input_manifest = build_input_manifest(symbol_quotes)
    phase5e_artifacts = None
    phase5f_artifacts = None
    phase5g_artifacts = None
    if args.phase5e:
        phase5e_artifacts = frozen_validation_artifacts(
            replay_reports,
            research_reports,
            symbol_quotes,
            input_manifest,
            parameter_version,
        )
    if args.phase5f:
        phase5f_artifacts = confirmation_gate_artifacts(replay_reports)
    if args.phase5g:
        phase5g_artifacts = platform_tolerance_sensitivity_artifacts(
            symbol_quotes,
            risk_capital,
            setup_parameters,
            decision_parameters,
            input_manifest,
            parameter_version,
        )
    write_input_manifest(INPUT_MANIFEST_JSON_PATH, input_manifest)
    frozen_manifest = write_frozen_input(FROZEN_INPUT_PATH, symbol_quotes)
    if frozen_manifest != input_manifest:
        raise RuntimeError("frozen replay input manifest changed during serialization")
    comparison_data = []
    if args.compare_manifest is not None:
        previous_manifest = read_input_manifest(args.compare_manifest)
        comparison_data = comparison_rows(
            compare_input_manifests(previous_manifest, input_manifest)
        )
    _write_csv(SUMMARY_PATH, rows)
    _write_csv(SKIPPED_PATH, skipped)
    _write_csv(EVENTS_PATH, event_rows, EVENT_HEADERS)
    _write_csv(OUTCOMES_PATH, outcome_rows, OUTCOME_HEADERS)
    _write_csv(SENSITIVITY_PATH, sensitivity_rows, SENSITIVITY_HEADERS)
    _write_csv(
        DECISION_GATE_DIAGNOSTICS_PATH,
        decision_gate_rows,
        DECISION_GATE_DIAGNOSTIC_HEADERS,
    )
    _write_csv(
        DECISION_GATE_SUMMARY_PATH,
        decision_gate_summary_rows,
        DECISION_GATE_SUMMARY_HEADERS,
    )
    _write_csv(
        INPUT_MANIFEST_CSV_PATH,
        input_manifest.csv_rows(),
        INPUT_MANIFEST_HEADERS,
    )
    _write_csv(
        INPUT_COMPARISON_PATH,
        comparison_data,
        INPUT_COMPARISON_HEADERS,
    )
    if phase5e_artifacts is not None:
        _write_csv(
            FROZEN_VALIDATION_SUMMARY_PATH,
            list(phase5e_artifacts.summary_rows),
        )
        _write_csv(
            FROZEN_VALIDATION_REASONS_PATH,
            list(phase5e_artifacts.decision_reason_rows),
        )
        _write_csv(
            FROZEN_VALIDATION_DISTRIBUTION_PATH,
            list(phase5e_artifacts.distribution_rows),
        )
        _write_csv(
            FROZEN_VALIDATION_CONCENTRATION_PATH,
            list(phase5e_artifacts.concentration_rows),
        )
        _write_csv(
            FROZEN_VALIDATION_SIGNAL_PATH_PATH,
            list(phase5e_artifacts.signal_path_rows),
            FROZEN_VALIDATION_SIGNAL_PATH_HEADERS,
        )
        _write_csv(
            FROZEN_VALIDATION_FORWARD_PATH,
            list(phase5e_artifacts.forward_summary_rows),
        )
        FROZEN_VALIDATION_REPORT_PATH.write_text(
            render_frozen_validation_report(phase5e_artifacts),
            encoding="utf-8",
        )
    if phase5f_artifacts is not None:
        _write_csv(CONFIRMATION_DETAIL_PATH, list(phase5f_artifacts.detail_rows))
        _write_csv(CONFIRMATION_REASON_PATH, list(phase5f_artifacts.reason_rows))
        _write_csv(CONFIRMATION_GATE_PATH, list(phase5f_artifacts.gate_rows))
        _write_csv(CONFIRMATION_NEAR_MISS_PATH, list(phase5f_artifacts.near_miss_rows))
        _write_csv(CONFIRMATION_AUXILIARY_PATH, list(phase5f_artifacts.auxiliary_rows))
        CONFIRMATION_REPORT_PATH.write_text(
            render_confirmation_report(phase5f_artifacts, input_manifest.aggregate_hash),
            encoding="utf-8",
        )
    if phase5g_artifacts is not None:
        _write_csv(TOLERANCE_FUNNEL_PATH, list(phase5g_artifacts.funnel_rows))
        _write_csv(
            TOLERANCE_CONFIRMATION_REASON_PATH,
            list(phase5g_artifacts.confirmation_reason_rows),
        )
        _write_csv(
            TOLERANCE_DECISION_REASON_PATH,
            list(phase5g_artifacts.decision_reason_rows),
        )
        _write_csv(
            TOLERANCE_DISTRIBUTION_PATH,
            list(phase5g_artifacts.distribution_rows),
        )
        _write_csv(TOLERANCE_FORWARD_PATH, list(phase5g_artifacts.forward_rows))
        _write_csv(TOLERANCE_STRUCTURE_PATH, list(phase5g_artifacts.structure_rows))
        TOLERANCE_REPORT_PATH.write_text(
            render_platform_tolerance_report(
                phase5g_artifacts, input_manifest.aggregate_hash
            ),
            encoding="utf-8",
        )
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
        input_manifest.aggregate_hash,
        comparison_data,
        args.frozen_input is not None,
    )
    if phase5e_artifacts is not None:
        print(
            "phase5e_frozen_validation: "
            f"source_run_id={PHASE5E_SOURCE_RUN_ID}, "
            f"dataset_hash={PHASE5E_DATASET_HASH}"
        )
        print(f"phase5e_report={FROZEN_VALIDATION_REPORT_PATH}")
    if phase5f_artifacts is not None:
        print(f"phase5f_confirmation_report={CONFIRMATION_REPORT_PATH}")
    if phase5g_artifacts is not None:
        print(f"phase5g_tolerance_report={TOLERANCE_REPORT_PATH}")
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
    aggregate_input_hash: str,
    comparison_data: list[dict],
    frozen_input: bool,
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
    print(f"decision_gate_diagnostics_csv={DECISION_GATE_DIAGNOSTICS_PATH}")
    print(f"decision_gate_summary_csv={DECISION_GATE_SUMMARY_PATH}")
    print(f"input_manifest_json={INPUT_MANIFEST_JSON_PATH}")
    print(f"input_manifest_csv={INPUT_MANIFEST_CSV_PATH}")
    print(f"frozen_input={FROZEN_INPUT_PATH}")
    print(f"input_comparison_csv={INPUT_COMPARISON_PATH}")
    print(f"input_mode={'FROZEN' if frozen_input else 'LIVE'}")
    print(f"aggregate_input_hash={aggregate_input_hash}")
    if comparison_data:
        comparison_counts = {
            status.value: sum(
                row["status"] == status.value for row in comparison_data
            )
            for status in ManifestChange
        }
        print(
            "input_manifest_comparison: "
            + ", ".join(
                f"{status.value}={comparison_counts[status.value]}"
                for status in ManifestChange
            )
        )
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


def _parse_args(argv: tuple[str, ...] | list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only SETUP_03 replay and research diagnostics"
    )
    parser.add_argument(
        "--frozen-input",
        type=Path,
        help="Replay canonical Quote bars from a prior workflow artifact",
    )
    parser.add_argument(
        "--compare-manifest",
        type=Path,
        help="Compare the current input manifest with a prior manifest JSON",
    )
    parser.add_argument(
        "--phase5e",
        action="store_true",
        help="Run descriptive Phase 5E validation on the fixed frozen baseline",
    )
    parser.add_argument(
        "--phase5f",
        action="store_true",
        help="Run production-path confirmation gate diagnostics on Phase 5E",
    )
    parser.add_argument(
        "--phase5g",
        action="store_true",
        help="Run fixed single-parameter platform-tolerance sensitivity on Phase 5E",
    )
    return parser.parse_args(list(argv))


if __name__ == "__main__":
    main(sys.argv[1:])

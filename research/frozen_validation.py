"""Phase 5E descriptive validation on the fixed SETUP_03 frozen dataset.

This module only projects production replay events and research outcomes.  It
does not call the Setup/Decision engines, vary parameters, or define execution
rules.  Forward paths are descriptive observations after a CONFIRMED signal;
they are not simulated entries or production position-management results.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import fmean, median
from typing import Iterable

from core import Quote
from research.backtest.setup03 import (
    DECISION_GATE_REASONS,
    ExecutionStatus,
    Setup03ResearchReport,
)
from research.replay_input import ReplayInputManifest
from trading.decision import DecisionGateReason
from trading.models import DecisionAction, SetupState
from trading.replay import ReplayEvent, SymbolReplayReport


PHASE5E_SOURCE_RUN_ID = 32826696259
PHASE5E_DATASET_HASH = (
    "sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703"
)
PHASE5E_PARAMETER_VERSION = "sha256:abe4d3026892"
FORWARD_HORIZONS = (5, 10, 20)

_REASON_LABELS = {
    DecisionGateReason.ATR_UNAVAILABLE: "ATR不可用",
    DecisionGateReason.BELOW_STRUCTURAL_INVALIDATION: "低于结构失效价",
    DecisionGateReason.BELOW_BREAKOUT: "低于突破价",
    DecisionGateReason.ABOVE_ENTRY_ZONE: "高于入场区上沿",
    DecisionGateReason.NO_VALID_TARGET: "无有效目标价",
    DecisionGateReason.RR_BELOW_MINIMUM: "R/R低于最低要求",
    DecisionGateReason.FUTURE_OR_INVALID_CONFIRMATION_CONTEXT: "确认上下文无效",
    DecisionGateReason.OTHER_NO_TRADE: "其他不交易原因",
    DecisionGateReason.ENTRY_ALLOWED: "允许入场",
}
_DIMENSIONS = ("标的", "市场", "年份", "季度")
_STAGES = ("CONFIRMED", "ENTRY_ALLOWED", "EXECUTED")


@dataclass(frozen=True)
class FrozenValidationArtifacts:
    summary_rows: tuple[dict, ...]
    decision_reason_rows: tuple[dict, ...]
    distribution_rows: tuple[dict, ...]
    concentration_rows: tuple[dict, ...]
    signal_path_rows: tuple[dict, ...]
    forward_summary_rows: tuple[dict, ...]


def validate_phase5e_baseline(
    manifest: ReplayInputManifest,
    parameter_version: str,
) -> None:
    """Fail fast unless both the selected dataset and production config match."""
    if manifest.aggregate_hash != PHASE5E_DATASET_HASH:
        raise ValueError(
            "Phase 5E dataset hash mismatch: "
            f"expected {PHASE5E_DATASET_HASH}, got {manifest.aggregate_hash}"
        )
    if parameter_version != PHASE5E_PARAMETER_VERSION:
        raise ValueError(
            "Phase 5E production parameter version mismatch: "
            f"expected {PHASE5E_PARAMETER_VERSION}, got {parameter_version}"
        )


def frozen_validation_artifacts(
    reports: dict[str, SymbolReplayReport],
    research_reports: dict[str, Setup03ResearchReport],
    symbol_quotes: dict[str, list[Quote]],
    manifest: ReplayInputManifest,
    parameter_version: str,
) -> FrozenValidationArtifacts:
    """Build Chinese, descriptive-only Phase 5E tables from production output."""
    validate_phase5e_baseline(manifest, parameter_version)
    expected_symbols = set(symbol_quotes)
    if set(reports) != expected_symbols or set(research_reports) != expected_symbols:
        raise ValueError("Phase 5E reports must cover every frozen dataset symbol")

    confirmed_events: list[tuple[SymbolReplayReport, ReplayEvent]] = []
    for report in reports.values():
        confirmed_events.extend(
            (report, event)
            for event in report.events
            if event.event_type is SetupState.CONFIRMED
        )
    outcomes = [
        outcome
        for report in research_reports.values()
        for outcome in report.outcomes
    ]
    if len(outcomes) != len(confirmed_events):
        raise ValueError("CONFIRMED events and execution outcomes must conserve")
    executed = [
        outcome
        for outcome in outcomes
        if outcome.execution_status is ExecutionStatus.EXECUTED
    ]
    entry_allowed = sum(
        event.decision is not None
        and event.decision.action is DecisionAction.ENTRY_ALLOWED
        for _, event in confirmed_events
    )

    reason_counts = Counter(_decision_reason(event) for _, event in confirmed_events)
    if sum(reason_counts.values()) != len(confirmed_events):
        raise ValueError("CONFIRMED events and Decision reasons must conserve")
    reason_rows = tuple(
        {
            "原因代码": reason.value,
            "中文说明": _REASON_LABELS[reason],
            "数量": reason_counts[reason],
            "占CONFIRMED比例": (
                reason_counts[reason] / len(confirmed_events)
                if confirmed_events
                else 0.0
            ),
            "分析性质": "描述性诊断（非参数优化）",
        }
        for reason in DECISION_GATE_REASONS
    )

    distribution_rows = tuple(
        _distribution_rows(symbol_quotes, confirmed_events, executed)
    )
    concentration_rows = tuple(_concentration_rows(distribution_rows))
    signal_path_rows = tuple(
        _signal_path_rows(confirmed_events, symbol_quotes)
    )
    forward_rows = tuple(_forward_summary_rows(signal_path_rows))

    setup_state_counts = Counter()
    for report in reports.values():
        setup_state_counts.update(report.state_day_counts)
    if executed:
        edge_conclusion = "仅有描述性执行样本；不足以替代正式样本外验证"
        zero_execution_reason = "存在EXECUTED样本"
    elif confirmed_events:
        edge_conclusion = "无EXECUTED样本，无法评估交易Edge"
        if entry_allowed:
            status_counts = Counter(outcome.execution_status for outcome in outcomes)
            zero_execution_reason = (
                "Decision gate后有ENTRY_ALLOWED，但T+1执行分支均未成交："
                + "、".join(
                    f"{status.value}={status_counts[status]}"
                    for status in ExecutionStatus
                    if status_counts[status]
                )
            )
        else:
            zero_execution_reason = "CONFIRMED事件全部被生产Decision gate拒绝"
    else:
        edge_conclusion = "无CONFIRMED信号，无法评估交易Edge"
        if setup_state_counts[SetupState.NONE] == manifest.total_bar_count:
            zero_execution_reason = (
                f"{manifest.total_bar_count}个冻结状态日全部为NONE，"
                "漏斗在CONFIRMED之前即为0；"
                "Decision gate与T+1 execution均未触发"
            )
        else:
            zero_execution_reason = (
                "生产Setup状态未产生CONFIRMED事件；"
                "Decision gate与T+1 execution均未触发"
            )
    summary = {
        "分析阶段": "Phase 5E Frozen Dataset Validation",
        "分析性质": "描述性诊断（非参数优化）",
        "数据模式": "冻结数据",
        "源workflow_run_id": PHASE5E_SOURCE_RUN_ID,
        "数据集哈希": manifest.aggregate_hash,
        "参数版本": parameter_version,
        "标的数": manifest.total_symbol_count,
        "K线数": manifest.total_bar_count,
        "CONFIRMED": len(confirmed_events),
        "ENTRY_ALLOWED": entry_allowed,
        "EXECUTED": len(executed),
        "NONE状态日数": setup_state_counts[SetupState.NONE],
        "WATCH状态日数": setup_state_counts[SetupState.WATCH],
        "ARMED状态日数": setup_state_counts[SetupState.ARMED],
        "CONFIRMED状态日数": setup_state_counts[SetupState.CONFIRMED],
        "FAILED状态日数": setup_state_counts[SetupState.FAILED],
        "零成交原因": zero_execution_reason,
        "初步Edge结论": edge_conclusion,
        "样本外状态": "未开始；本冻结集已用于开发诊断，不属于最终样本外保留集",
    }
    return FrozenValidationArtifacts(
        (summary,),
        reason_rows,
        distribution_rows,
        concentration_rows,
        signal_path_rows,
        forward_rows,
    )


def render_frozen_validation_report(
    artifacts: FrozenValidationArtifacts,
) -> str:
    """Render the user-facing Phase 5E report in Chinese."""
    summary = artifacts.summary_rows[0]
    reason_rows = [row for row in artifacts.decision_reason_rows if row["数量"]]
    concentration = artifacts.concentration_rows
    lines = [
        "# SETUP_03 Phase 5E 冻结数据集验证报告",
        "",
        "> 本报告仅做描述性诊断，不进行参数优化，不修改生产规则，也不构成正式样本外验证。",
        "",
        "## 冻结基线",
        "",
        f"- 源 workflow run：`{summary['源workflow_run_id']}`",
        f"- Dataset hash：`{summary['数据集哈希']}`",
        f"- 生产参数版本：`{summary['参数版本']}`",
        f"- 覆盖：{summary['标的数']} 个标的，{summary['K线数']} 根 K 线",
        "",
        "## 生产参数漏斗",
        "",
        "| CONFIRMED | ENTRY_ALLOWED | EXECUTED |",
        "|---:|---:|---:|",
        f"| {summary['CONFIRMED']} | {summary['ENTRY_ALLOWED']} | {summary['EXECUTED']} |",
        "",
        f"零成交原因：{summary['零成交原因']}。",
        "",
        "## Decision 原因分布",
        "",
    ]
    if reason_rows:
        lines.extend(("| 原因 | 数量 | 占比 |", "|---|---:|---:|"))
        for row in reason_rows:
            lines.append(
                f"| {row['中文说明']} (`{row['原因代码']}`) | "
                f"{row['数量']} | {row['占CONFIRMED比例']:.2%} |"
            )
    else:
        lines.append("无 CONFIRMED 事件，因此没有可统计的 Decision gate reason。")
    lines.extend(("", "## 时间、标的与市场集中度", ""))
    if summary["CONFIRMED"] == 0:
        lines.append(
            "CONFIRMED、ENTRY_ALLOWED、EXECUTED 均为 0，无法判断结果是否被少数标的、年份或市场环境主导。"
        )
    else:
        for row in concentration:
            if row["阶段"] == "CONFIRMED":
                lines.append(
                    f"- {row['维度']}：{row['判断']}（最高分组：{row['最高分组']}，"
                    f"占比 {row['最高占比']:.2%}）"
                )
    lines.extend(("", "## Forward Return、MAE / MFE", ""))
    if summary["CONFIRMED"] == 0:
        lines.append("无信号样本，forward return、MAE、MFE 均不可评估。")
    else:
        overall = [
            row
            for row in artifacts.forward_summary_rows
            if row["维度"] == "总体"
        ]
        lines.extend(
            (
                "| 周期 | 可观测样本 | 平均收益率 | 正收益比例 | 平均MFE | 平均MAE |",
                "|---:|---:|---:|---:|---:|---:|",
            )
        )
        for row in overall:
            lines.append(
                f"| {row['周期_交易日']} | {row['可观测样本数']} | "
                f"{_percent(row['平均forward_return'])} | "
                f"{_percent(row['正收益比例'])} | "
                f"{_percent(row['平均MFE'])} | {_percent(row['平均MAE'])} |"
            )
    lines.extend(
        (
            "",
            "## 初步 Edge",
            "",
            summary["初步Edge结论"] + "。",
            "",
            "最终样本外验证尚未开始；本阶段不会据此选择参数或放宽任何交易门槛。",
            "",
        )
    )
    return "\n".join(lines)


def _decision_reason(event: ReplayEvent) -> DecisionGateReason:
    action = event.decision.action if event.decision is not None else None
    if event.decision_diagnostics is not None:
        reason = event.decision_diagnostics.reason
    elif action is DecisionAction.ENTRY_ALLOWED:
        reason = DecisionGateReason.ENTRY_ALLOWED
    else:
        reason = DecisionGateReason.OTHER_NO_TRADE
    if (reason is DecisionGateReason.ENTRY_ALLOWED) != (
        action is DecisionAction.ENTRY_ALLOWED
    ):
        raise ValueError("Decision action and gate reason are inconsistent")
    return reason


def _distribution_rows(
    symbol_quotes: dict[str, list[Quote]],
    confirmed_events: list[tuple[SymbolReplayReport, ReplayEvent]],
    executed: list,
) -> list[dict]:
    bars = Counter()
    for symbol, quotes in symbol_quotes.items():
        market = quotes[0].market
        for quote in quotes:
            for dimension, value in _dimension_values(
                symbol, market, quote.trade_date
            ):
                bars[(dimension, value)] += 1
    stages = {stage: Counter() for stage in _STAGES}
    for report, event in confirmed_events:
        event_date = event.confirmed_date or event.trade_date
        for dimension, value in _dimension_values(
            event.symbol, report.market, event_date
        ):
            stages["CONFIRMED"][(dimension, value)] += 1
            if (
                event.decision is not None
                and event.decision.action is DecisionAction.ENTRY_ALLOWED
            ):
                stages["ENTRY_ALLOWED"][(dimension, value)] += 1
    for outcome in executed:
        for dimension, value in _dimension_values(
            outcome.symbol, outcome.market, outcome.confirmed_date
        ):
            stages["EXECUTED"][(dimension, value)] += 1

    totals = {
        (stage, dimension): sum(
            count
            for (row_dimension, _), count in stages[stage].items()
            if row_dimension == dimension
        )
        for stage in _STAGES
        for dimension in _DIMENSIONS
    }
    rows = []
    for dimension in _DIMENSIONS:
        keys = sorted(value for row_dimension, value in bars if row_dimension == dimension)
        for value in keys:
            row = {"维度": dimension, "分组": value, "K线数": bars[(dimension, value)]}
            for stage in _STAGES:
                count = stages[stage][(dimension, value)]
                total = totals[(stage, dimension)]
                row[stage] = count
                row[f"{stage}占该维度比例"] = count / total if total else 0.0
            rows.append(row)
    return rows


def _concentration_rows(distribution_rows: Iterable[dict]) -> list[dict]:
    rows = list(distribution_rows)
    output = []
    for stage in _STAGES:
        for dimension in _DIMENSIONS:
            candidates = [row for row in rows if row["维度"] == dimension]
            total = sum(row[stage] for row in candidates)
            top = max(candidates, key=lambda row: row[stage], default=None)
            top_count = top[stage] if top else 0
            share = top_count / total if total else 0.0
            if total == 0:
                conclusion = "无法评估（该阶段样本为0）"
            elif total < 10:
                conclusion = "样本过少，集中度仅作描述"
            elif share > 0.5:
                conclusion = "可能被单一分组主导"
            else:
                conclusion = "未见单一分组占比超过50%"
            output.append(
                {
                    "阶段": stage,
                    "维度": dimension,
                    "最高分组": top["分组"] if top else "",
                    "最高分组数量": top_count,
                    "阶段总数": total,
                    "最高占比": share,
                    "判断": conclusion,
                }
            )
    return output


def _signal_path_rows(
    confirmed_events: list[tuple[SymbolReplayReport, ReplayEvent]],
    symbol_quotes: dict[str, list[Quote]],
) -> list[dict]:
    rows = []
    for report, event in confirmed_events:
        quotes = symbol_quotes[event.symbol]
        event_date = event.confirmed_date or event.trade_date
        indexes = {
            quote.trade_date: index for index, quote in enumerate(quotes)
        }
        if event_date not in indexes:
            raise ValueError("CONFIRMED date is missing from frozen quote series")
        event_index = indexes[event_date]
        anchor = (
            float(event.signal_close)
            if event.signal_close is not None
            else float(quotes[event_index].close)
        )
        if anchor <= 0:
            raise ValueError("signal path anchor must be positive")
        future = quotes[event_index + 1 : event_index + 1 + max(FORWARD_HORIZONS)]
        row = {
            "统一代码": event.symbol,
            "市场": report.market,
            "信号日期": event_date.isoformat(),
            "年份": str(event_date.year),
            "季度": f"{event_date.year}-Q{(event_date.month - 1) // 3 + 1}",
            "信号收盘价": anchor,
            "可用后续交易日": len(future),
        }
        for horizon in FORWARD_HORIZONS:
            path = future[:horizon]
            complete = len(path) == horizon
            row[f"{horizon}D完整"] = complete
            row[f"{horizon}D_forward_return"] = (
                float(path[-1].close) / anchor - 1.0 if complete else None
            )
            row[f"{horizon}D_MFE"] = (
                max(float(quote.high) for quote in path) / anchor - 1.0
                if complete
                else None
            )
            row[f"{horizon}D_MAE"] = (
                min(float(quote.low) for quote in path) / anchor - 1.0
                if complete
                else None
            )
        rows.append(row)
    return rows


def _forward_summary_rows(signal_path_rows: tuple[dict, ...]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    if not signal_path_rows:
        for horizon in FORWARD_HORIZONS:
            groups[("总体", "全部")]
    for row in signal_path_rows:
        groups[("总体", "全部")].append(row)
        for dimension, field in (
            ("标的", "统一代码"),
            ("市场", "市场"),
            ("年份", "年份"),
            ("季度", "季度"),
        ):
            groups[(dimension, row[field])].append(row)
    output = []
    for (dimension, value), group_rows in sorted(groups.items()):
        for horizon in FORWARD_HORIZONS:
            returns = [
                row[f"{horizon}D_forward_return"]
                for row in group_rows
                if row[f"{horizon}D_forward_return"] is not None
            ]
            mfes = [
                row[f"{horizon}D_MFE"]
                for row in group_rows
                if row[f"{horizon}D_MFE"] is not None
            ]
            maes = [
                row[f"{horizon}D_MAE"]
                for row in group_rows
                if row[f"{horizon}D_MAE"] is not None
            ]
            output.append(
                {
                    "维度": dimension,
                    "分组": value,
                    "周期_交易日": horizon,
                    "信号数": len(group_rows),
                    "可观测样本数": len(returns),
                    "平均forward_return": fmean(returns) if returns else None,
                    "中位forward_return": median(returns) if returns else None,
                    "正收益比例": (
                        sum(value > 0 for value in returns) / len(returns)
                        if returns
                        else None
                    ),
                    "平均MFE": fmean(mfes) if mfes else None,
                    "中位MFE": median(mfes) if mfes else None,
                    "平均MAE": fmean(maes) if maes else None,
                    "中位MAE": median(maes) if maes else None,
                }
            )
    return output


def _dimension_values(symbol: str, market: str, event_date) -> tuple:
    return (
        ("标的", symbol),
        ("市场", market),
        ("年份", str(event_date.year)),
        ("季度", f"{event_date.year}-Q{(event_date.month - 1) // 3 + 1}"),
    )


def _percent(value: float | None) -> str:
    return "不可评估" if value is None else f"{value:.2%}"

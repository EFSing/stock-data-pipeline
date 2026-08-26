"""Phase 5G single-parameter SETUP_03 platform-tolerance sensitivity.

Every cell replays the fixed Phase 5E dataset through the production Setup and
Decision path.  This module only changes ``platform_tolerance_pct`` and only
aggregates existing replay, diagnostics, and execution outputs.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import fmean, median

from core import Quote
from research.backtest.setup03 import (
    DECISION_GATE_REASONS,
    ExecutionStatus,
    research_funnel_counts,
    research_trade_outcomes,
)
from research.frozen_validation import (
    FORWARD_HORIZONS,
    _signal_path_rows,
    validate_phase5e_baseline,
)
from research.replay_input import ReplayInputManifest
from trading.models import DecisionAction, SetupState
from trading.replay import SymbolReplayReport, replay_setup03_history
from trading.setup import SetupGateReason


PLATFORM_TOLERANCES = (0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 0.075, 0.10)


@dataclass(frozen=True)
class PlatformToleranceArtifacts:
    funnel_rows: tuple[dict, ...]
    confirmation_reason_rows: tuple[dict, ...]
    decision_reason_rows: tuple[dict, ...]
    distribution_rows: tuple[dict, ...]
    forward_rows: tuple[dict, ...]
    structure_rows: tuple[dict, ...]


def platform_tolerance_sensitivity_artifacts(
    symbol_quotes: dict[str, list[Quote]],
    risk_capital: float,
    production_setup_parameters: dict,
    decision_parameters: dict,
    manifest: ReplayInputManifest,
    parameter_version: str,
    tolerances: tuple[float, ...] = PLATFORM_TOLERANCES,
) -> PlatformToleranceArtifacts:
    """Replay the declared tolerance sequence without ranking or selection."""
    validate_phase5e_baseline(manifest, parameter_version)
    if tuple(tolerances) != PLATFORM_TOLERANCES:
        raise ValueError("Phase 5G tolerance sequence is frozen")
    if not symbol_quotes or set(symbol_quotes) != {row.symbol for row in manifest.symbols}:
        raise ValueError("Phase 5G requires complete frozen dataset coverage")

    funnel_rows: list[dict] = []
    confirmation_rows: list[dict] = []
    decision_rows: list[dict] = []
    distribution_rows: list[dict] = []
    forward_rows: list[dict] = []
    structure_rows: list[dict] = []
    baseline_detected = None

    for tolerance in tolerances:
        setup_parameters = dict(production_setup_parameters)
        setup_parameters["platform_tolerance_pct"] = tolerance
        reports: dict[str, SymbolReplayReport] = {}
        research_reports = {}
        for symbol, quotes in sorted(symbol_quotes.items()):
            report = replay_setup03_history(
                quotes, risk_capital, setup_parameters, decision_parameters
            )
            reports[symbol] = report
            research_reports[symbol] = research_trade_outcomes(report, quotes)

        days = [day for report in reports.values() for day in report.days]
        events = [
            (report, event)
            for report in reports.values()
            for event in report.events
            if event.event_type is SetupState.CONFIRMED
        ]
        outcomes = [
            outcome
            for report in research_reports.values()
            for outcome in report.outcomes
        ]
        if len(events) != len(outcomes):
            raise ValueError("Phase 5G CONFIRMED/execution conservation failed")
        state_counts = Counter(day.setup_state for day in days)
        detected = sum(
            bool(day.setup_diagnostics and day.setup_diagnostics.platform_detected_this_bar)
            for day in days
        )
        if baseline_detected is None:
            baseline_detected = detected
        funnel_parts = [
            research_funnel_counts(reports[symbol], research_reports[symbol])
            for symbol in sorted(reports)
        ]
        funnel = {
            key: sum(row[key] for row in funnel_parts)
            for key in funnel_parts[0]
        }
        entry_allowed = sum(
            event.decision is not None
            and event.decision.action is DecisionAction.ENTRY_ALLOWED
            for _, event in events
        )
        executed = sum(
            outcome.execution_status is ExecutionStatus.EXECUTED
            for outcome in outcomes
        )
        if entry_allowed != funnel["entry_allowed_count"] or executed != funnel["executed_count"]:
            raise ValueError("Phase 5G funnel projection is inconsistent")
        explosion_ratio = (
            detected / baseline_detected if baseline_detected else (None if detected == 0 else float("inf"))
        )
        funnel_rows.append(
            {
                "platform_tolerance_pct": tolerance,
                "平台识别数量": detected,
                "WATCH状态日数": state_counts[SetupState.WATCH],
                "ARMED状态日数": state_counts[SetupState.ARMED],
                "CONFIRMED事件数": len(events),
                "ENTRY_ALLOWED": entry_allowed,
                "EXECUTED": executed,
                "相对0容差平台数量倍数": explosion_ratio,
                "数量爆炸提示": _explosion_label(explosion_ratio, detected),
                **funnel,
            }
        )

        confirmation_counts = Counter(
            day.setup_diagnostics.reason for day in days if day.setup_diagnostics
        )
        if sum(confirmation_counts.values()) != manifest.total_bar_count:
            raise ValueError("Phase 5G confirmation reasons do not conserve")
        for reason in SetupGateReason:
            confirmation_rows.append(
                {
                    "platform_tolerance_pct": tolerance,
                    "confirmation_reason": reason.value,
                    "数量": confirmation_counts[reason],
                    "占全部bars比例": confirmation_counts[reason] / manifest.total_bar_count,
                }
            )

        decision_counts = Counter(
            event.decision_diagnostics.reason.value
            if event.decision_diagnostics is not None
            else "OTHER_NO_TRADE"
            for _, event in events
        )
        if sum(decision_counts.values()) != len(events):
            raise ValueError("Phase 5G Decision reasons do not conserve")
        for reason in DECISION_GATE_REASONS:
            decision_rows.append(
                {
                    "platform_tolerance_pct": tolerance,
                    "decision_reason": reason.value,
                    "数量": decision_counts[reason.value],
                    "占CONFIRMED比例": decision_counts[reason.value] / len(events) if events else 0.0,
                }
            )

        distribution_rows.extend(_distributions(tolerance, reports, events))
        paths = tuple(_signal_path_rows(events, symbol_quotes))
        forward_rows.extend(_forward_summaries(tolerance, paths))
        structure_rows.append(_structure_summary(tolerance, days, detected))

    return PlatformToleranceArtifacts(
        tuple(funnel_rows), tuple(confirmation_rows), tuple(decision_rows),
        tuple(distribution_rows), tuple(forward_rows), tuple(structure_rows)
    )


def render_platform_tolerance_report(
    artifacts: PlatformToleranceArtifacts, dataset_hash: str
) -> str:
    lines = [
        "# Phase 5G Platform Tolerance Sensitivity Study",
        "",
        "> 单参数、描述性研究；不排名、不选择最佳 tolerance、不修改生产配置、不启动 OOS。",
        "",
        f"- Frozen dataset：`{dataset_hash}`",
        "- 固定 tolerance：`0%、0.5%、1%、1.5%、2%、3%、5%、7.5%、10%`",
        "- 除 `platform_tolerance_pct` 外，所有 production 参数保持不变。",
        "",
        "## 完整漏斗",
        "",
        "| tolerance | 平台识别 | WATCH | ARMED | CONFIRMED | ENTRY_ALLOWED | EXECUTED | 数量提示 |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in artifacts.funnel_rows:
        lines.append(
            f"| {row['platform_tolerance_pct']:.1%} | {row['平台识别数量']} | "
            f"{row['WATCH状态日数']} | {row['ARMED状态日数']} | "
            f"{row['CONFIRMED事件数']} | {row['ENTRY_ALLOWED']} | {row['EXECUTED']} | "
            f"{row['数量爆炸提示']} |"
        )
    lines.extend(("", "## 结构稳定性", ""))
    for row in artifacts.structure_rows:
        lines.append(
            f"- `{row['platform_tolerance_pct']:.1%}`：识别平台 {row['平台识别数量']}；"
            f"high span 中位数 {_pct(row['high_span中位数'])}、P90 {_pct(row['high_span_P90'])}；"
            f"low span 中位数 {_pct(row['low_span中位数'])}、P90 {_pct(row['low_span_P90'])}；"
            f"最大标的占比 {_pct(row['最大标的CONFIRMED占比'])}，最大年份占比 {_pct(row['最大年份CONFIRMED占比'])}。"
        )
    lines.extend((
        "", "## 默认值语义", "",
        "代码中的 `0` 表示两个及以上 Swing High（以及 Low）的归一化 span 必须严格为 0，"
        "即价格必须完全相等；它是有效且确定的数值语义，但在本冻结数据上表现为退化的精确相等门槛。",
        "这首先是“配置默认值是否表达预期平台语义”的问题；哪个非零 tolerance 应用于策略，"
        "则是独立的策略参数选择问题。本阶段不修改默认值，也不作生产参数选择。",
        "", "## 研究边界", "",
        "各 confirmation / decision reason、标的/市场/年份分布，以及 5D/10D/20D forward return、MAE/MFE 完整统计均随 CSV 输出。",
        "本冻结集已经用于诊断，不能作为最终 OOS；本报告不以收益筛选 tolerance。", ""
    ))
    return "\n".join(lines)


def _distributions(tolerance, reports, events):
    counters = {dimension: Counter() for dimension in ("标的", "市场", "年份")}
    groups = {
        "标的": set(reports),
        "市场": {report.market for report in reports.values()},
        "年份": {
            str(day.trade_date.year)
            for report in reports.values()
            for day in report.days
        },
    }
    for report, event in events:
        event_date = event.confirmed_date or event.trade_date
        counters["标的"][event.symbol] += 1
        counters["市场"][report.market] += 1
        counters["年份"][str(event_date.year)] += 1
    rows = []
    total = len(events)
    for dimension, counter in counters.items():
        for group in sorted(groups[dimension]):
            count = counter[group]
            rows.append({"platform_tolerance_pct": tolerance, "维度": dimension, "分组": group, "CONFIRMED": count, "占比": count / total if total else 0.0})
    return rows


def _forward_summaries(tolerance, paths):
    rows = []
    for horizon in FORWARD_HORIZONS:
        returns = [r[f"{horizon}D_forward_return"] for r in paths if r[f"{horizon}D_forward_return"] is not None]
        mfes = [r[f"{horizon}D_MFE"] for r in paths if r[f"{horizon}D_MFE"] is not None]
        maes = [r[f"{horizon}D_MAE"] for r in paths if r[f"{horizon}D_MAE"] is not None]
        rows.append({
            "platform_tolerance_pct": tolerance, "周期_交易日": horizon,
            "信号数": len(paths), "可观测样本数": len(returns),
            "平均forward_return": fmean(returns) if returns else None,
            "中位forward_return": median(returns) if returns else None,
            "正收益比例": sum(v > 0 for v in returns) / len(returns) if returns else None,
            "平均MFE": fmean(mfes) if mfes else None, "中位MFE": median(mfes) if mfes else None,
            "平均MAE": fmean(maes) if maes else None, "中位MAE": median(maes) if maes else None,
        })
    return rows


def _structure_summary(tolerance, days, detected):
    detected_diags = [d.setup_diagnostics for d in days if d.setup_diagnostics and d.setup_diagnostics.platform_detected_this_bar]
    high_spans = sorted(d.high_span for d in detected_diags if d.high_span is not None)
    low_spans = sorted(d.low_span for d in detected_diags if d.low_span is not None)
    confirmed = [d for d in days if d.setup_diagnostics and d.setup_diagnostics.reason is SetupGateReason.CONFIRMED]
    symbol_counts = Counter(d.symbol for d in confirmed)
    year_counts = Counter(str(d.trade_date.year) for d in confirmed)
    total = len(confirmed)
    return {
        "platform_tolerance_pct": tolerance, "平台识别数量": detected,
        "high_span中位数": median(high_spans) if high_spans else None,
        "high_span_P90": _quantile(high_spans, .9),
        "low_span中位数": median(low_spans) if low_spans else None,
        "low_span_P90": _quantile(low_spans, .9),
        "最大标的CONFIRMED占比": max(symbol_counts.values(), default=0) / total if total else None,
        "最大年份CONFIRMED占比": max(year_counts.values(), default=0) / total if total else None,
    }


def _quantile(values, q):
    if not values:
        return None
    position = (len(values) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _explosion_label(ratio, count):
    if count == 0:
        return "无平台"
    if ratio is None or ratio == float("inf"):
        return "0容差基线为0，不能计算倍数；检查绝对数量"
    if ratio >= 10:
        return "相对0容差增加至少10倍"
    if ratio >= 3:
        return "相对0容差增加至少3倍"
    return "未见相对0容差倍数爆炸"


def _pct(value):
    return "不可评估" if value is None else f"{value:.2%}"

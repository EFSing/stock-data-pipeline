"""Phase 5F read-only SETUP_03 confirmation-gate diagnostics."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean

from trading.replay import SymbolReplayReport
from trading.setup import SetupDiagnostics, SetupGateReason


REASON_LABELS = {
    SetupGateReason.NO_NEW_CONFIRMED_SWING: "终态后/当前窗口没有新的已确认 Swing",
    SetupGateReason.INSUFFICIENT_HIGH_SWINGS: "窗口内已确认 Swing High 少于 2 个",
    SetupGateReason.INSUFFICIENT_LOW_SWINGS: "窗口内已确认 Swing Low 少于 2 个",
    SetupGateReason.STRUCTURE_NOT_RANGE_OR_TRANSITION: "结构不是 RANGE/TRANSITION",
    SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE: "平台高点离散度超过容差",
    SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE: "平台低点离散度超过容差",
    SetupGateReason.WATCH_BELOW_ARM_THRESHOLD: "已识别平台但收盘未达到逼近/突破阈值",
    SetupGateReason.ARMED_NOT_BREAKOUT: "已逼近平台上沿但收盘未严格突破",
    SetupGateReason.STRUCTURAL_INVALIDATION: "收盘跌破平台结构失效价",
    SetupGateReason.CONFIRMED: "收盘严格突破平台上沿",
}


@dataclass(frozen=True)
class ConfirmationArtifacts:
    detail_rows: tuple[dict, ...]
    reason_rows: tuple[dict, ...]
    gate_rows: tuple[dict, ...]
    near_miss_rows: tuple[dict, ...]
    auxiliary_rows: tuple[dict, ...]


def render_confirmation_report(
    artifacts: ConfirmationArtifacts,
    dataset_hash: str,
) -> str:
    total = sum(int(row["数量"]) for row in artifacts.reason_rows)
    confirmed = next(
        int(row["数量"])
        for row in artifacts.reason_rows
        if row["terminal_reason"] == SetupGateReason.CONFIRMED.value
    )
    ranked = sorted(
        (
            row
            for row in artifacts.reason_rows
            if row["terminal_reason"] != SetupGateReason.CONFIRMED.value
        ),
        key=lambda row: int(row["数量"]),
        reverse=True,
    )
    lines = [
        "# Phase 5F SETUP_03 Confirmation Gate Diagnostics",
        "",
        f"- 冻结数据集：`{dataset_hash}`",
        f"- 守恒检查：`{total} bars = {total - confirmed} 未确认 + {confirmed} CONFIRMED`",
        "- 口径：terminal reason 来自每个 as-of prefix 的同一次 production Setup 计算。",
        "- 边界：不改参数、不改规则、不优化、不使用 OOS。",
        "",
        "## Terminal reason 分布",
        "",
        "| terminal reason | 中文说明 | 数量 | 占比 |",
        "|---|---|---:|---:|",
    ]
    for row in artifacts.reason_rows:
        lines.append(
            f"| {row['terminal_reason']} | {row['中文说明']} | "
            f"{row['数量']} | {float(row['占全部bars比例']):.2%} |"
        )
    lines.extend(["", "## 根因定位", ""])
    if confirmed == 0 and ranked:
        top = ranked[0]
        lines.append(
            f"生产参数下 0 CONFIRMED 的最大直接阻断是 "
            f"`{top['terminal_reason']}`（{top['数量']} bars，"
            f"{float(top['占全部bars比例']):.2%}）。"
            "该结论是对冻结样本的描述性定位，不构成调参建议。"
        )
    lines.extend(
        [
            "",
            "Near-miss 分布、逐 bar 明细和可同时失败的辅助条件见同一 artifact 中的 CSV。",
            "",
        ]
    )
    return "\n".join(lines)


def confirmation_gate_artifacts(
    reports: dict[str, SymbolReplayReport],
) -> ConfirmationArtifacts:
    detail_rows: list[dict] = []
    diagnostics: list[SetupDiagnostics] = []
    for symbol, report in sorted(reports.items()):
        for day in report.days:
            diag = day.setup_diagnostics
            if diag is None:
                raise ValueError(f"{symbol} {day.trade_date}: missing Setup diagnostics")
            diagnostics.append(diag)
            detail_rows.append(
                {
                    "统一代码": symbol,
                    "市场": report.market,
                    "交易日": day.trade_date.isoformat(),
                    "Setup状态": day.setup_state.value,
                    "terminal_reason": diag.reason.value,
                    "terminal_reason_中文": REASON_LABELS[diag.reason],
                    "已确认High数": diag.high_count,
                    "已确认Low数": diag.low_count,
                    "结构": diag.trend.value if diag.trend is not None else "",
                    "high_span": diag.high_span,
                    "low_span": diag.low_span,
                    "platform_tolerance_pct": diag.platform_tolerance_pct,
                    "close": diag.close,
                    "breakout_price": diag.breakout_price,
                    "arm_threshold": diag.arm_threshold,
                    "当日执行平台搜索": diag.platform_search_evaluated,
                    "当日识别出平台": diag.platform_detected_this_bar,
                    "辅助失败条件": "|".join(
                        reason.value for reason in diag.auxiliary_failed_conditions
                    ),
                }
            )

    total = len(diagnostics)
    counts = Counter(diag.reason for diag in diagnostics)
    if sum(counts.values()) != total:
        raise ValueError("SETUP_03 terminal reason conservation failed")
    reason_rows = tuple(
        {
            "terminal_reason": reason.value,
            "中文说明": REASON_LABELS[reason],
            "数量": counts.get(reason, 0),
            "占全部bars比例": counts.get(reason, 0) / total if total else 0.0,
        }
        for reason in SetupGateReason
    )

    # Sequential platform-search gates. A gate is evaluated only when all prior
    # gates passed; active WATCH/ARMED transitions are reported separately.
    search_reasons = (
        SetupGateReason.NO_NEW_CONFIRMED_SWING,
        SetupGateReason.INSUFFICIENT_HIGH_SWINGS,
        SetupGateReason.INSUFFICIENT_LOW_SWINGS,
        SetupGateReason.STRUCTURE_NOT_RANGE_OR_TRANSITION,
        SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE,
        SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE,
    )
    remaining = sum(diag.platform_search_evaluated for diag in diagnostics)
    gate_rows: list[dict] = []
    for reason in search_reasons:
        eliminated = counts[reason]
        gate_rows.append(
            {
                "路径": "平台搜索",
                "gate": reason.value,
                "中文说明": REASON_LABELS[reason],
                "进入该层": remaining,
                "本层淘汰": eliminated,
                "通过该层": remaining - eliminated,
                "本层淘汰率": eliminated / remaining if remaining else 0.0,
            }
        )
        remaining -= eliminated
    active_total = sum(
        counts[reason]
        for reason in (
            SetupGateReason.WATCH_BELOW_ARM_THRESHOLD,
            SetupGateReason.ARMED_NOT_BREAKOUT,
            SetupGateReason.STRUCTURAL_INVALIDATION,
            SetupGateReason.CONFIRMED,
        )
    )
    for reason in (
        SetupGateReason.WATCH_BELOW_ARM_THRESHOLD,
        SetupGateReason.ARMED_NOT_BREAKOUT,
        SetupGateReason.STRUCTURAL_INVALIDATION,
        SetupGateReason.CONFIRMED,
    ):
        gate_rows.append(
            {
                "路径": "已识别平台状态转移",
                "gate": reason.value,
                "中文说明": REASON_LABELS[reason],
                "进入该层": active_total,
                "本层淘汰": counts[reason] if reason is not SetupGateReason.CONFIRMED else 0,
                "通过该层": counts[SetupGateReason.CONFIRMED],
                "本层淘汰率": counts[reason] / active_total if active_total else 0.0,
            }
        )

    near_miss_groups: dict[tuple[str, str], list[float]] = {}
    for diag in diagnostics:
        for condition, name, value in _near_miss_metrics(diag):
            near_miss_groups.setdefault((condition.value, name), []).append(value)
    near_miss_rows = tuple(
        _distribution_row(reason, metric, values)
        for (reason, metric), values in sorted(near_miss_groups.items())
    )

    auxiliary_counts = Counter(
        reason
        for diag in diagnostics
        for reason in diag.auxiliary_failed_conditions
    )
    auxiliary_rows = tuple(
        {
            "辅助失败条件": reason.value,
            "中文说明": REASON_LABELS[reason],
            "数量": auxiliary_counts.get(reason, 0),
            "注意": "可与其他条件同时失败，不用于守恒求和",
        }
        for reason in search_reasons
    )
    return ConfirmationArtifacts(
        tuple(detail_rows),
        reason_rows,
        tuple(gate_rows),
        near_miss_rows,
        auxiliary_rows,
    )


def _near_miss_metrics(
    diag: SetupDiagnostics,
) -> tuple[tuple[SetupGateReason, str, float], ...]:
    rows: list[tuple[SetupGateReason, str, float]] = []
    failed = set(diag.auxiliary_failed_conditions)
    if SetupGateReason.INSUFFICIENT_HIGH_SWINGS in failed:
        rows.append((SetupGateReason.INSUFFICIENT_HIGH_SWINGS, "距2个High尚缺数量", float(2 - diag.high_count)))
    if SetupGateReason.INSUFFICIENT_LOW_SWINGS in failed:
        rows.append((SetupGateReason.INSUFFICIENT_LOW_SWINGS, "距2个Low尚缺数量", float(2 - diag.low_count)))
    if SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE in failed and diag.high_span is not None:
        rows.append((SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE, "high_span超容差幅度", diag.high_span - diag.platform_tolerance_pct))
    if SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE in failed and diag.low_span is not None:
        rows.append((SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE, "low_span超容差幅度", diag.low_span - diag.platform_tolerance_pct))
    if diag.reason in (
        SetupGateReason.WATCH_BELOW_ARM_THRESHOLD,
        SetupGateReason.ARMED_NOT_BREAKOUT,
    ) and diag.close is not None and diag.breakout_price:
        rows.append((diag.reason, "距突破价百分比", (diag.breakout_price - diag.close) / diag.breakout_price))
    return tuple(rows)


def _distribution_row(reason: str, metric: str, values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "terminal_reason": reason,
        "指标": metric,
        "样本数": len(values),
        "最小值": ordered[0],
        "P25": _quantile(ordered, 0.25),
        "中位数": _quantile(ordered, 0.5),
        "P75": _quantile(ordered, 0.75),
        "P90": _quantile(ordered, 0.9),
        "平均值": mean(ordered),
        "最大值": ordered[-1],
    }


def _quantile(ordered: list[float], q: float) -> float:
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight

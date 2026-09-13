"""Deterministic Chinese explanations for existing Decision/Position fields.

This module is presentation-only.  It reads values already produced by the
SETUP_01/SETUP_02 Decision and Position Management single sources of truth;
it never derives a new price, target, risk gate, or exit condition.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any


EXECUTION_OUTCOME_LABELS = {
    "EXECUTED": "下一交易日开盘满足执行条件，模拟成交",
    "SKIP_GAP_BELOW_CONFIRMATION": "下一交易日低开回到确认价下方，取消模拟入场",
    "SKIP_GAP_ABOVE_ENTRY_ZONE": "下一交易日高开超过允许追价区间，取消模拟入场",
    "SKIP_BELOW_INVALIDATION": "下一交易日开盘已经跌破结构失效位，取消模拟入场",
    "SKIP_RR_BELOW_MINIMUM_AT_OPEN": "按真实开盘价重新计算后，第一目标 R/R 已不足2，取消模拟入场",
    "SKIP_NO_T1_BAR": "无法确认精确下一交易日开盘数据，本次模拟执行失败关闭",
    "SKIP_DECISION_NOT_ENTRY_ALLOWED": "当日方案没有通过入场条件，取消模拟入场",
}

EXIT_REASON_LABELS = {
    "EXIT_GAP_BELOW_STOP": "当日开盘已低于当前保护止损，按开盘价退出",
    "EXIT_STOP_TRIGGERED": "盘中最低价触及当日生效保护止损，按保护止损价退出",
    "STRUCTURAL_EXIT_PENDING": "收盘跌破当前结构保护底线，下一交易日开盘退出",
    "PROFIT_PROTECTION_EXIT_PENDING": "此前浮盈已达到利润保护条件，收盘跌破利润保护线，下一交易日开盘退出",
}

TARGET_STATUS_LABELS = {
    "NOT_REACHED": "尚未触及目标价",
    "T1_REACHED": "已触及第一目标价（仅记录目标状态）",
    "T2_REACHED": "已触及第二目标价（仅记录目标状态）",
    "T3_REACHED": "已触及第三目标价（仅记录目标状态）",
}


@dataclass(frozen=True)
class TradeLogicExplanation:
    """Stable user-facing explanation assembled from existing fields."""

    source_setup: str
    why_plan: str
    when_execute: str
    execution_checks: str
    target_policy: str
    why_hold: str
    why_exit: str

    def to_dict(self) -> dict[str, str]:
        return {
            "why_plan": self.why_plan,
            "when_execute": self.when_execute,
            "execution_checks": self.execution_checks,
            "target_policy": self.target_policy,
            "why_hold": self.why_hold,
            "why_exit": self.why_exit,
            "source_setup": self.source_setup,
        }


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    raw = getattr(value, "value", value)
    if isinstance(raw, (date, datetime)):
        raw = raw.isoformat()
    text = str(raw).strip()
    return text or default


def _number(value: Any, default: str = "未提供") -> str:
    raw = _text(value, "")
    if not raw:
        return default
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return raw
    if not math.isfinite(numeric):
        return default
    rendered = f"{numeric:.4f}".rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _ratio(value: Any, default: str = "未提供") -> str:
    raw = _text(value, "")
    if not raw:
        return default
    try:
        numeric = float(raw)
    except (TypeError, ValueError):
        return raw
    if not math.isfinite(numeric):
        return default
    return f"{numeric:.2f}"


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _setup_name(source_setup: str) -> str:
    return {
        "SETUP_01": "2浪调整结束 → 等待3浪启动",
        "SETUP_02": "3浪延续",
    }.get(source_setup, source_setup or "当前策略")


def _date_text(value: Any) -> str:
    return _text(value, "下一交易日")


def _anchor_text(anchor: Any, name: str) -> str:
    if anchor is None:
        return f"{name}=未提供"
    price = _number(_field(anchor, "price"))
    pivot_date = _date_text(_field(anchor, "pivot_date"))
    return f"{name}={price}（{pivot_date}）"


def _target_sources(decision: Any) -> str:
    candidates = _sequence(_field(decision, "target_candidates"))
    parts: list[str] = []
    for index, candidate in enumerate(candidates[:3], start=1):
        source = _text(_field(candidate, "source"), "既有目标来源")
        reason = _text(_field(candidate, "reason"))
        parts.append(f"T{index}={source}{'：' + reason if reason else ''}")
    if parts:
        return "；".join(parts)
    return "T1/T2/T3 来源沿用既有 Decision target candidates"


def _first_rr(decision: Any) -> str:
    rr = _field(decision, "rr")
    ratios = _sequence(_field(rr, "rr_ratios"))
    return _ratio(ratios[0] if ratios else None, "未提供")


def _planned_entry_sentence(decision: Any) -> str:
    confirmation = _number(_field(decision, "confirmation_level"))
    planned_entry = _number(_field(decision, "planned_entry"))
    low = _number(_field(decision, "entry_zone_low"))
    high = _number(_field(decision, "entry_zone_high"))
    rr = _first_rr(decision)
    action = _text(_field(decision, "action"))
    if action == "ENTRY_ALLOWED":
        zone_sentence = f"收盘 {planned_entry} 位于允许入场区间 {low}–{high}"
    else:
        zone_sentence = f"收盘 {planned_entry} 未满足允许入场区间 {low}–{high}"
    return (
        f"T日收盘突破确认价 {confirmation}；{zone_sentence}；"
        f"第一目标对应 R/R {rr}，因此{'形成交易方案' if action == 'ENTRY_ALLOWED' else '当前不形成可入场方案'}。"
    )


def build_trade_logic_explanation(
    decision: Any,
    *,
    source_setup: str | None = None,
    event: Any | None = None,
) -> TradeLogicExplanation:
    """Build a deterministic explanation without recomputing strategy rules."""

    resolved_setup = source_setup or _text(_field(event, "setup_type"))
    if not resolved_setup and event is not None:
        resolved_setup = "SETUP_01" if _field(event, "setup01") is not None else "SETUP_02"
    if not resolved_setup:
        resolved_setup = "SETUP_01" if _field(decision, "wave1_origin") is not None else "SETUP_02"

    low = _number(_field(decision, "entry_zone_low"))
    high = _number(_field(decision, "entry_zone_high"))
    structural = _number(_field(decision, "structural_invalidation"))
    execution_stop = _number(_field(decision, "execution_stop"))
    targets = _sequence(_field(decision, "targets"))[:3]
    target_text = " / ".join(_number(value) for value in targets) or "既有 Decision 未提供"

    if resolved_setup == "SETUP_01":
        snapshot = _field(event, "setup01") if event is not None else None
        structure = "；".join(
            (
                _anchor_text(_field(snapshot, "wave1_origin"), "Wave1 起点"),
                _anchor_text(_field(snapshot, "wave1_peak"), "Wave1 峰值"),
                _anchor_text(_field(snapshot, "wave2_low"), "Wave2 低点"),
            )
        )
        why_plan = (
            f"当前是{_setup_name(resolved_setup)}；T日收盘突破 Wave1 peak / confirmation。"
            f"{_planned_entry_sentence(decision)}"
        )
        structure_detail = f"Wave 结构来源：{structure}。"
    elif resolved_setup == "SETUP_02":
        snapshot = _field(event, "setup02") if event is not None else None
        anchors = (
            _field(decision, "continuation_low0") or _field(snapshot, "continuation_low0"),
            _field(decision, "continuation_high1") or _field(snapshot, "continuation_high1"),
            _field(decision, "continuation_low2") or _field(snapshot, "continuation_low2"),
            _field(decision, "continuation_high3") or _field(snapshot, "continuation_high3"),
        )
        structure = "；".join(
            _anchor_text(anchor, name)
            for name, anchor in zip(("LOW0", "HIGH1", "LOW2", "HIGH3"), anchors)
        )
        why_plan = (
            f"当前是{_setup_name(resolved_setup)}；T日收盘突破 HIGH3 confirmation。"
            f"{_planned_entry_sentence(decision)}"
        )
        structure_detail = f"LOW0→HIGH1→LOW2→HIGH3 结构来自既有 evaluator：{structure}。"
    else:
        why_plan = _planned_entry_sentence(decision)
        structure_detail = "结构与 Setup 名称沿用既有 Decision/event。"

    when_execute = (
        "最早 exact T+1 market-session OPEN；T日收盘只形成计划，不在同一根K线模拟成交。"
    )
    execution_checks = (
        f"T+1 OPEN 仍需通过现有执行检查：不得跌破结构失效位 {structural}，"
        f"不得低于确认价/入场区间下沿 {low}，不得高于允许追价上沿 {high}，"
        "并且按真实开盘价计算的第一目标 R/R 仍需不少于2；否则记录 SKIP。"
    )
    target_policy = (
        f"T1/T2/T3={target_text}；来源：{_target_sources(decision)}。"
        "Target 用于目标到达状态、风险提示与利润保护参考，不是机械到价自动卖出。"
    )
    why_hold = (
        "继续持有、暂不加仓或保护利润，均以既有 Position Management 的当日 action 为准；"
        "合法的 confirmed higher low 可抬高 structural floor，保护止损只上移、不下移；"
        "MFE 达到2R后可形成利润保护线。"
    )
    why_exit = (
        "只有既有 Position Management 真实产生 EXIT 才算退出；Target reached 本身不等于已止盈。"
    )
    return TradeLogicExplanation(
        source_setup=resolved_setup,
        why_plan=f"{why_plan}{structure_detail}",
        when_execute=when_execute,
        execution_checks=execution_checks,
        target_policy=target_policy,
        why_hold=why_hold,
        why_exit=why_exit,
    )


def explain_execution_outcome(outcome: Any) -> str:
    key = _text(outcome)
    return EXECUTION_OUTCOME_LABELS.get(key, f"T+1 执行结果：{key or '未记录'}")


def explain_exit_reason(reason: Any) -> str:
    key = _text(reason)
    return EXIT_REASON_LABELS.get(key, f"现有持仓管理产生退出：{key or '未记录退出原因'}")


def explain_target_status(status: Any) -> str:
    key = _text(status)
    return TARGET_STATUS_LABELS.get(key, f"目标状态：{key or '未记录'}")


def explain_position_day(day: Any) -> tuple[str, str, str]:
    """Return ``(why_hold, why_protect, why_exit)`` for one existing PositionDay."""

    exit_reason = _text(_field(day, "exit_reason"))
    action = _text(_field(day, "action"))
    secondary = "；".join(_text(value) for value in _sequence(_field(day, "secondary_reasons")) if _text(value))
    target = explain_target_status(_field(day, "target_status"))
    if exit_reason:
        return (
            "该日已进入退出处理，不再继续持有。",
            target,
            explain_exit_reason(exit_reason),
        )
    if action == "PROFIT_PROTECTION":
        protect = "现有 Position Management 正在保护利润或抬高保护止损"
        if secondary:
            protect += f"；依据：{secondary}"
        return ("持仓仍未触发真实 EXIT，按既有规则继续观察。", protect, "尚未产生真实退出")
    if action == "NO_ADD":
        return ("Wave5 candidate 主要给出 NO_ADD 建议，持仓仍按既有规则管理。", target, "尚未产生真实退出")
    return ("现有 Position Management 的 action 允许继续持有。", target, "尚未产生真实退出")


def strategy_rules_for_dashboard() -> tuple[tuple[str, str], ...]:
    """Static rule copy for the dashboard; no runtime values are calculated."""

    return (
        ("SETUP_01 为什么会进入候选？", "2浪调整结束后，价格重新突破1浪高点，并满足价格区间与盈亏比要求。"),
        ("SETUP_02 为什么会进入候选？", "上涨趋势中的3浪延续结构完成，并重新突破确认高点，同时满足价格区间与盈亏比要求。"),
        ("为什么今天有信号却不买？", "可能是确认事件不是今天新出现、收盘价仍不在允许入场区间、第一目标 R/R 不足2、数据或交易日历不完整，或组合风控没有放行。"),
        ("我们什么时候会形成入场方案？", "只有当T日出现新的确认事件，且既有 SETUP_01/SETUP_02 Decision 的 action 为 ENTRY_ALLOWED。"),
        ("什么时候真正模拟买入？", "最早 exact T+1 market-session OPEN；只有真实开盘再次通过既有执行检查才记录模拟成交。"),
        ("什么情况下会取消入场？", "T+1 开盘跌破失效位、回到确认价下方、超过允许入场区间、实际开盘 R/R 不足2，或缺少精确 T+1 bar。"),
        ("结构失效和执行止损有什么区别？", "结构失效是波浪结构被破坏的底线；执行止损是成交后用于模拟风控的初始止损。两者分开保存，成交后的1R=actual_entry−execution_stop。"),
        ("保护止损什么时候会上移？", "confirmed higher low 或 MFE≥2R 形成合法保护线时，沿用 Position Management 只上移、不下移的规则。"),
        ("什么时候真正卖出？为什么？", "只有既有 Position Management 产生 EXIT：开盘/盘中触发保护止损，或收盘确认结构／利润保护失效后在下一交易日开盘退出。"),
        ("T1/T2/T3 是不是自动止盈？", "不是。Target 只记录到达状态、风险提示和利润保护上下文；到达目标价不等于自动止盈，真正退出仍由持仓管理规则产生。"),
    )


__all__ = [
    "EXIT_REASON_LABELS",
    "EXECUTION_OUTCOME_LABELS",
    "TARGET_STATUS_LABELS",
    "TradeLogicExplanation",
    "build_trade_logic_explanation",
    "explain_execution_outcome",
    "explain_exit_reason",
    "explain_position_day",
    "explain_target_status",
    "strategy_rules_for_dashboard",
]

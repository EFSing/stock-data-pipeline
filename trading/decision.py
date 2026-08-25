"""SETUP_03 交易决策最小闭环。

串联 Entry Candidate → Structural Invalidation → Execution Stop → Target →
R/R → Position Size → Decision Action。复用 Setup / Fibonacci / Risk / Swing /
ATR，不重复实现（Single Source of Truth）。

关键约束：
- Target 先独立生成（Swing 前高 + Fib extension），再算 R/R；禁止为满足 R/R 倒推 Target。
- 多头 Execution Stop = breakout_price - atr_buffer * ATR；Structural Invalidation 保持 platform_low。
- planned_entry 用当前 as-of bar close；完整执行 Entry Zone 分档：
  close < inv → NO_TRADE；inv <= close < breakout_price → WAIT_CONFIRMATION；
  [breakout_price, entry_zone_high] 内才继续算交易；超上沿 → NO_TRADE。
- 未 CONFIRMED 的 Setup 不得 ENTRY_ALLOWED；CONFIRMED 但 confirmed_index 晚于
  决策时刻（未来 Setup）不得进入风险计算。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core import Quote
from trading.fibonacci import fibonacci_levels_from_prices
from trading.indicators import atr
from trading.models import (
    Decision,
    DecisionAction,
    EntryPlan,
    PositionSize,
    RiskReward,
    Setup,
    SetupState,
    SwingKind,
    SwingPoint,
)
from trading.risk import NO_TRADE, position_size, risk_reward
from trading.swing import find_swings


class DecisionGateReason(str, Enum):
    """Read-only explanation of the terminal SETUP_03 Decision gate."""

    ATR_UNAVAILABLE = "ATR_UNAVAILABLE"
    BELOW_STRUCTURAL_INVALIDATION = "BELOW_STRUCTURAL_INVALIDATION"
    BELOW_BREAKOUT = "BELOW_BREAKOUT"
    ABOVE_ENTRY_ZONE = "ABOVE_ENTRY_ZONE"
    NO_VALID_TARGET = "NO_VALID_TARGET"
    RR_BELOW_MINIMUM = "RR_BELOW_MINIMUM"
    FUTURE_OR_INVALID_CONFIRMATION_CONTEXT = (
        "FUTURE_OR_INVALID_CONFIRMATION_CONTEXT"
    )
    OTHER_NO_TRADE = "OTHER_NO_TRADE"
    ENTRY_ALLOWED = "ENTRY_ALLOWED"


@dataclass(frozen=True)
class DecisionDiagnostics:
    """Projection of values already produced by one production calculation."""

    reason: DecisionGateReason
    decision_index: int
    confirmed_index: int | None
    planned_entry: float
    breakout_price: float | None
    structural_invalidation: float | None
    atr: float | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    execution_stop: float | None = None
    targets: tuple[float, ...] = ()
    t1_rr: float | None = None


@dataclass(frozen=True)
class DecisionWithDiagnostics:
    """Decision plus observability; ``decision`` remains the production object."""

    decision: Decision
    diagnostics: DecisionDiagnostics | None


def _last_atr(quotes: list[Quote], atr_period: int) -> Optional[float]:
    """返回最后一个非 None 的 ATR 值（决策时刻的波动基准）。"""
    series = atr(quotes, atr_period)
    for value in reversed(series):
        if value is not None:
            return value
    return None


def _t1_swing_high(
    swings: list[SwingPoint], decision_index: int, above_price: float
) -> Optional[float]:
    """截至 decision_index 已 confirmed、价格高于 above_price 的最近 swing high。"""
    candidates = [
        s
        for s in swings
        if s.kind is SwingKind.HIGH
        and s.confirmed_index is not None
        and s.confirmed_index <= decision_index
        and s.price > above_price
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.pivot_index).price


def decide_platform_breakout(
    quotes: list[Quote],
    setup: Setup,
    risk_capital: float,
    swings: Optional[list[SwingPoint]] = None,
    swing_lookback: int = 5,
    atr_period: int = 14,
    atr_buffer: float = 0.5,
    max_chase_atr: float = 0.5,
) -> Decision:
    """根据 SETUP_03 的 Setup 状态生成交易决策（兼容的生产 API）。"""
    return decide_platform_breakout_with_diagnostics(
        quotes,
        setup,
        risk_capital,
        swings=swings,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
        atr_buffer=atr_buffer,
        max_chase_atr=max_chase_atr,
    ).decision


def decide_platform_breakout_with_diagnostics(
    quotes: list[Quote],
    setup: Setup,
    risk_capital: float,
    swings: Optional[list[SwingPoint]] = None,
    swing_lookback: int = 5,
    atr_period: int = 14,
    atr_buffer: float = 0.5,
    max_chase_atr: float = 0.5,
) -> DecisionWithDiagnostics:
    """Calculate the production Decision and its read-only gate projection once."""
    if setup.setup_type != "SETUP_03":
        raise ValueError(f"仅支持 SETUP_03，收到 {setup.setup_type}")

    # 非 CONFIRMED 状态直接映射动作，不进入风险计算
    if setup.state in (SetupState.NONE, SetupState.FAILED):
        return DecisionWithDiagnostics(
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None), None
        )
    if setup.state is SetupState.WATCH:
        return DecisionWithDiagnostics(
            Decision(DecisionAction.WATCH, None, None, None, (), None, None), None
        )
    if setup.state is SetupState.ARMED:
        return DecisionWithDiagnostics(
            Decision(
                DecisionAction.WAIT_CONFIRMATION, None, None, None, (), None, None
            ),
            None,
        )

    # CONFIRMED：进入完整风险计算
    assert setup.state is SetupState.CONFIRMED
    n = len(quotes)
    decision_index = n - 1
    planned_entry = float(quotes[-1].close)

    def result(
        decision: Decision,
        reason: DecisionGateReason,
        *,
        atr_value: float | None = None,
        entry_zone_low: float | None = None,
        entry_zone_high: float | None = None,
        execution_stop: float | None = None,
        targets: tuple[float, ...] = (),
        t1_rr: float | None = None,
    ) -> DecisionWithDiagnostics:
        return DecisionWithDiagnostics(
            decision,
            DecisionDiagnostics(
                reason=reason,
                decision_index=decision_index,
                confirmed_index=setup.confirmed_index,
                planned_entry=planned_entry,
                breakout_price=setup.breakout_price,
                structural_invalidation=setup.structural_invalidation,
                atr=atr_value,
                entry_zone_low=entry_zone_low,
                entry_zone_high=entry_zone_high,
                execution_stop=execution_stop,
                targets=targets,
                t1_rr=t1_rr,
            ),
        )

    # 未来 Setup：confirmed_index 缺失或晚于决策时刻 → 不得进入风险计算
    if setup.confirmed_index is None or setup.confirmed_index > decision_index:
        return result(
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            DecisionGateReason.FUTURE_OR_INVALID_CONFIRMATION_CONTEXT,
        )

    if setup.breakout_price is None or setup.structural_invalidation is None:
        return result(
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            DecisionGateReason.OTHER_NO_TRADE,
        )

    if swings is None:
        swings = find_swings(quotes, lookback=swing_lookback)

    atr_value = _last_atr(quotes, atr_period)
    if atr_value is None:
        # 无波动基准，无法计算 stop/zone
        return result(
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            DecisionGateReason.ATR_UNAVAILABLE,
        )

    breakout_price = setup.breakout_price
    structural_invalidation = setup.structural_invalidation

    # Entry Zone = [breakout_price, breakout_price + max_chase_atr * ATR]
    entry_zone_low = breakout_price
    entry_zone_high = breakout_price + max_chase_atr * atr_value

    # 完整执行 Entry Zone 分档
    if planned_entry < structural_invalidation:
        # 跌破结构失效价
        return result(
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            DecisionGateReason.BELOW_STRUCTURAL_INVALIDATION,
            atr_value=atr_value,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
        )
    if planned_entry < breakout_price:
        # 仍在平台内未突破
        return result(
            Decision(
                DecisionAction.WAIT_CONFIRMATION, None, None, None, (), None, None
            ),
            DecisionGateReason.BELOW_BREAKOUT,
            atr_value=atr_value,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
        )
    if planned_entry > entry_zone_high:
        # 追高，NO_TRADE（不拿 breakout_price 虚假入场）
        return result(
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            DecisionGateReason.ABOVE_ENTRY_ZONE,
            atr_value=atr_value,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
        )

    # 多头 Execution Stop = breakout_price - atr_buffer * ATR
    execution_stop = breakout_price - atr_buffer * atr_value

    # Target candidates：历史前高 + Fib extension，均为候选
    t1_candidate = _t1_swing_high(swings, decision_index, planned_entry)
    fib = fibonacci_levels_from_prices(breakout_price, structural_invalidation)
    fib_1272 = fib.extensions["1.272"]
    fib_1618 = fib.extensions["1.618"]

    # 过滤 None / <= planned_entry，按价格升序，依次为 T1/T2/T3
    targets = sorted(
        [
            c
            for c in (t1_candidate, fib_1272, fib_1618)
            if c is not None and c > planned_entry
        ]
    )
    if not targets:
        return result(
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            DecisionGateReason.NO_VALID_TARGET,
            atr_value=atr_value,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            execution_stop=execution_stop,
        )

    entry_plan = EntryPlan(
        planned_entry=planned_entry,
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        probe_entry=breakout_price,
        confirmation_entry=breakout_price,
        confirmation_conditions=(
            "close 突破 breakout_price 且未追高（close <= entry_zone_high）"
        ),
    )

    rr: RiskReward = risk_reward(planned_entry, execution_stop, targets)
    # quality 使用最近有效目标 T1（升序第一个）的 R/R，不指定历史前高优先
    if rr.quality == NO_TRADE:
        # R/R 不达标（RR < 2）：保留风险画像，但不给仓位、不允许入场
        decision = Decision(
            DecisionAction.NO_TRADE,
            entry_plan,
            structural_invalidation,
            execution_stop,
            tuple(targets),
            rr,
            None,
        )
        return result(
            decision,
            DecisionGateReason.RR_BELOW_MINIMUM,
            atr_value=atr_value,
            entry_zone_low=entry_zone_low,
            entry_zone_high=entry_zone_high,
            execution_stop=execution_stop,
            targets=tuple(targets),
            t1_rr=rr.rr_ratios[0],
        )

    pos: PositionSize = position_size(risk_capital, planned_entry, execution_stop)

    decision = Decision(
        DecisionAction.ENTRY_ALLOWED,
        entry_plan,
        structural_invalidation,
        execution_stop,
        tuple(targets),
        rr,
        pos,
    )
    return result(
        decision,
        DecisionGateReason.ENTRY_ALLOWED,
        atr_value=atr_value,
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        execution_stop=execution_stop,
        targets=tuple(targets),
        t1_rr=rr.rr_ratios[0],
    )

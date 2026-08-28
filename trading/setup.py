"""Setup Engine（Phase 2 首批：仅 SETUP_03 Platform Breakout）。

SETUP_03 Platform Breakout：价格在横盘平台内整理，形成明确阻力（平台高点）与
支撑（平台低点），随后收盘价向上突破平台高点。

复用 Phase 1（Single Source of Truth）：
- Swing 识别：`trading.swing.find_swings`
- Market Structure：`trading.structure.market_structure`
本模块不重新实现 pivot 识别或趋势判定；structure 由内部按 `confirmed_index <= t`
过滤后的 swings 计算，**不接受预计算的 structure**（只可接受预计算 swings）。

时间语义：按 bar 顺序推进状态机，任何状态判定只用 `data <= t`。
CONFIRMED / FAILED 只终止当前 Setup 实例，Detector 会继续扫描后续新平台，
最终返回最新 Setup。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core import Quote
from trading.models import (
    Setup,
    SetupState,
    SwingKind,
    SwingPoint,
    Trend,
    validate_quote_series,
)
from trading.structure import market_structure
from trading.swing import find_swings


class SetupGateReason(str, Enum):
    """Latest-bar terminal reason from the production SETUP_03 state machine."""

    NO_NEW_CONFIRMED_SWING = "NO_NEW_CONFIRMED_SWING"
    INSUFFICIENT_HIGH_SWINGS = "INSUFFICIENT_HIGH_SWINGS"
    INSUFFICIENT_LOW_SWINGS = "INSUFFICIENT_LOW_SWINGS"
    STRUCTURE_NOT_RANGE_OR_TRANSITION = "STRUCTURE_NOT_RANGE_OR_TRANSITION"
    HIGH_SPAN_EXCEEDS_TOLERANCE = "HIGH_SPAN_EXCEEDS_TOLERANCE"
    LOW_SPAN_EXCEEDS_TOLERANCE = "LOW_SPAN_EXCEEDS_TOLERANCE"
    WATCH_BELOW_ARM_THRESHOLD = "WATCH_BELOW_ARM_THRESHOLD"
    ARMED_NOT_BREAKOUT = "ARMED_NOT_BREAKOUT"
    STRUCTURAL_INVALIDATION = "STRUCTURAL_INVALIDATION"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True)
class SetupDiagnostics:
    """Read-only values observed by the latest production Setup calculation."""

    reason: SetupGateReason
    setup_state: SetupState
    index: int
    high_count: int = 0
    low_count: int = 0
    trend: Trend | None = None
    high_span: float | None = None
    low_span: float | None = None
    platform_tolerance_pct: float = 0.0
    close: float | None = None
    breakout_price: float | None = None
    structural_invalidation: float | None = None
    arm_threshold: float | None = None
    auxiliary_failed_conditions: tuple[SetupGateReason, ...] = ()
    platform_search_evaluated: bool = False
    platform_detected_this_bar: bool = False


@dataclass(frozen=True)
class SetupWithDiagnostics:
    setup: Setup
    diagnostics: SetupDiagnostics


def _confirmed_swings_in_window(
    swings: list[SwingPoint], t: int, platform_window: int
) -> list[SwingPoint]:
    """返回 as-of t 时、pivot 发生在窗口 [t-platform_window, t] 内的 CONFIRMED swing。"""
    return [
        s
        for s in swings
        if s.confirmed_index is not None
        and s.confirmed_index <= t
        and s.pivot_index >= t - platform_window
    ]


def _has_new_confirmed_swing(
    window_swings: list[SwingPoint], last_terminal_index: int
) -> bool:
    """窗口内是否存在 pivot 发生在 terminal 之后的新 swing。

    用 pivot_index（swing 发生位置）而非 confirmed_index 判断：避免把「旧 pivot
    因后续数据而晚确认」误判为新 swing，从而在 CONFIRMED 后马上重复识别旧平台。
    """
    return any(s.pivot_index > last_terminal_index for s in window_swings)


def _platform_gate_diagnostics(
    window_swings: list[SwingPoint],
    last_terminal_index: int,
    platform_tolerance_pct: float,
) -> tuple[SetupGateReason | None, dict]:
    """Evaluate the existing platform gates once and expose their operands."""
    highs = [s.price for s in window_swings if s.kind is SwingKind.HIGH]
    lows = [s.price for s in window_swings if s.kind is SwingKind.LOW]
    has_new_swing = _has_new_confirmed_swing(window_swings, last_terminal_index)
    trend = (
        market_structure(window_swings).trend
        if len(highs) >= 2 and len(lows) >= 2
        else None
    )
    high_span = (max(highs) - min(highs)) / max(highs) if len(highs) >= 2 else None
    low_span = (max(lows) - min(lows)) / max(lows) if len(lows) >= 2 else None

    failed: list[SetupGateReason] = []
    if not has_new_swing:
        failed.append(SetupGateReason.NO_NEW_CONFIRMED_SWING)
    if len(highs) < 2:
        failed.append(SetupGateReason.INSUFFICIENT_HIGH_SWINGS)
    if len(lows) < 2:
        failed.append(SetupGateReason.INSUFFICIENT_LOW_SWINGS)
    if trend is not None and trend not in (Trend.RANGE, Trend.TRANSITION):
        failed.append(SetupGateReason.STRUCTURE_NOT_RANGE_OR_TRANSITION)
    if high_span is not None and high_span > platform_tolerance_pct:
        failed.append(SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE)
    if low_span is not None and low_span > platform_tolerance_pct:
        failed.append(SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE)

    # Priority exactly follows the production predicate: new-swing orchestration,
    # high/low sufficiency, structure, high span, then low span.
    priority = (
        SetupGateReason.NO_NEW_CONFIRMED_SWING,
        SetupGateReason.INSUFFICIENT_HIGH_SWINGS,
        SetupGateReason.INSUFFICIENT_LOW_SWINGS,
        SetupGateReason.STRUCTURE_NOT_RANGE_OR_TRANSITION,
        SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE,
        SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE,
    )
    reason = next((candidate for candidate in priority if candidate in failed), None)
    return reason, {
        "high_count": len(highs),
        "low_count": len(lows),
        "trend": trend,
        "high_span": high_span,
        "low_span": low_span,
        "auxiliary_failed_conditions": tuple(failed),
    }


def detect_platform_breakout(
    quotes: list[Quote],
    swing_lookback: int = 5,
    platform_window: int = 40,
    platform_tolerance_pct: float = 0.0,
    arm_proximity_pct: float = 0.0,
    swings: Optional[list[SwingPoint]] = None,
) -> Setup:
    """按时间顺序推进 SETUP_03 状态机，返回截至最后一个 bar 的最新 Setup。

    状态迁移：
    - NONE → WATCH：识别到平台；冻结 breakout_price（=平台高点）与
      structural_invalidation（=平台低点）。
    - WATCH → CONFIRMED：close 突破平台高点（> breakout_price），含识别同一 bar 直接突破。
    - WATCH → ARMED：close 逼近平台高点（≥ breakout_price * (1-arm_proximity_pct)）。
    - ARMED → WATCH：close 回落到逼近阈值以下但未失效（< breakout_price * (1-arm_proximity_pct)）。
    - WATCH/ARMED → FAILED：close 跌破平台低点（< structural_invalidation）。
    - CONFIRMED / FAILED 为当前 Setup 终态；Detector 继续扫描后续新平台。

    platform_tolerance_pct 仅用于平台边界一致性；突破/失效保持严格
    `close > breakout_price` / `close < structural_invalidation`。
    """
    return detect_platform_breakout_with_diagnostics(
        quotes,
        swing_lookback=swing_lookback,
        platform_window=platform_window,
        platform_tolerance_pct=platform_tolerance_pct,
        arm_proximity_pct=arm_proximity_pct,
        swings=swings,
    ).setup


def detect_platform_breakout_with_diagnostics(
    quotes: list[Quote],
    swing_lookback: int = 5,
    platform_window: int = 40,
    platform_tolerance_pct: float = 0.0,
    arm_proximity_pct: float = 0.0,
    swings: Optional[list[SwingPoint]] = None,
    history: Optional[list[SetupWithDiagnostics]] = None,
) -> SetupWithDiagnostics:
    """Run the production state machine once and return read-only gate evidence."""
    validate_quote_series(quotes)
    if platform_window < 1:
        raise ValueError(f"platform_window 必须 >= 1：{platform_window}")
    if platform_tolerance_pct < 0:
        raise ValueError(f"platform_tolerance_pct 不能为负：{platform_tolerance_pct}")
    if arm_proximity_pct < 0:
        raise ValueError(f"arm_proximity_pct 不能为负：{arm_proximity_pct}")

    n = len(quotes)
    if swings is None:
        swings = find_swings(quotes, lookback=swing_lookback)

    state = SetupState.NONE
    breakout_price: Optional[float] = None
    structural_invalidation: Optional[float] = None
    detected_index: Optional[int] = None
    state_entered_index: Optional[int] = None
    confirmed_index: Optional[int] = None
    # 上一个终态 Setup 的终态 bar index（-1 表示尚无终态）
    last_terminal_index = -1
    latest_diagnostics: SetupDiagnostics | None = None

    for t in range(n):
        close_t = float(quotes[t].close)

        if state in (SetupState.NONE, SetupState.CONFIRMED, SetupState.FAILED):
            window = _confirmed_swings_in_window(swings, t, platform_window)
            gate_reason, gate_values = _platform_gate_diagnostics(
                window, last_terminal_index, platform_tolerance_pct
            )
            if gate_reason is None:
                highs = [s.price for s in window if s.kind is SwingKind.HIGH]
                lows = [s.price for s in window if s.kind is SwingKind.LOW]
                breakout_price = max(highs)
                structural_invalidation = min(lows)
                detected_index = t
                confirmed_index = None
                if close_t > breakout_price:
                    # 同一 bar 识别平台即突破 → 直接 CONFIRMED
                    state = SetupState.CONFIRMED
                    confirmed_index = t
                    state_entered_index = t
                    last_terminal_index = t
                    latest_diagnostics = SetupDiagnostics(
                        SetupGateReason.CONFIRMED,
                        state,
                        t,
                        close=close_t,
                        breakout_price=breakout_price,
                        structural_invalidation=structural_invalidation,
                        platform_tolerance_pct=platform_tolerance_pct,
                        platform_search_evaluated=True,
                        platform_detected_this_bar=True,
                        **gate_values,
                    )
                else:
                    state = SetupState.WATCH
                    state_entered_index = t
                    latest_diagnostics = SetupDiagnostics(
                        SetupGateReason.WATCH_BELOW_ARM_THRESHOLD,
                        state,
                        t,
                        close=close_t,
                        breakout_price=breakout_price,
                        structural_invalidation=structural_invalidation,
                        arm_threshold=breakout_price * (1 - arm_proximity_pct),
                        platform_tolerance_pct=platform_tolerance_pct,
                        platform_search_evaluated=True,
                        platform_detected_this_bar=True,
                        **gate_values,
                    )
            else:
                latest_diagnostics = SetupDiagnostics(
                    gate_reason,
                    state,
                    t,
                    close=close_t,
                    breakout_price=breakout_price,
                    structural_invalidation=structural_invalidation,
                    platform_tolerance_pct=platform_tolerance_pct,
                    platform_search_evaluated=True,
                    **gate_values,
                )
        elif state is SetupState.WATCH:
            assert breakout_price is not None and structural_invalidation is not None
            if close_t > breakout_price:
                state = SetupState.CONFIRMED
                confirmed_index = t
                state_entered_index = t
                last_terminal_index = t
                reason = SetupGateReason.CONFIRMED
            elif close_t < structural_invalidation:
                state = SetupState.FAILED
                state_entered_index = t
                last_terminal_index = t
                reason = SetupGateReason.STRUCTURAL_INVALIDATION
            elif close_t >= breakout_price * (1 - arm_proximity_pct):
                state = SetupState.ARMED
                state_entered_index = t
                reason = SetupGateReason.ARMED_NOT_BREAKOUT
            else:
                reason = SetupGateReason.WATCH_BELOW_ARM_THRESHOLD
            latest_diagnostics = SetupDiagnostics(
                reason,
                state,
                t,
                close=close_t,
                breakout_price=breakout_price,
                structural_invalidation=structural_invalidation,
                arm_threshold=breakout_price * (1 - arm_proximity_pct),
                platform_tolerance_pct=platform_tolerance_pct,
            )

        elif state is SetupState.ARMED:
            assert breakout_price is not None and structural_invalidation is not None
            if close_t > breakout_price:
                state = SetupState.CONFIRMED
                confirmed_index = t
                state_entered_index = t
                last_terminal_index = t
                reason = SetupGateReason.CONFIRMED
            elif close_t < structural_invalidation:
                state = SetupState.FAILED
                state_entered_index = t
                last_terminal_index = t
                reason = SetupGateReason.STRUCTURAL_INVALIDATION
            elif close_t < breakout_price * (1 - arm_proximity_pct):
                # 回落到逼近阈值以下但未失效 → 降级回 WATCH
                state = SetupState.WATCH
                state_entered_index = t
                reason = SetupGateReason.WATCH_BELOW_ARM_THRESHOLD
            else:
                reason = SetupGateReason.ARMED_NOT_BREAKOUT
            latest_diagnostics = SetupDiagnostics(
                reason,
                state,
                t,
                close=close_t,
                breakout_price=breakout_price,
                structural_invalidation=structural_invalidation,
                arm_threshold=breakout_price * (1 - arm_proximity_pct),
                platform_tolerance_pct=platform_tolerance_pct,
            )

        if history is not None:
            history.append(
                SetupWithDiagnostics(
                    Setup(
                        setup_type="SETUP_03",
                        state=state,
                        breakout_price=breakout_price,
                        structural_invalidation=structural_invalidation,
                        detected_index=detected_index,
                        state_entered_index=state_entered_index,
                        confirmed_index=confirmed_index,
                    ),
                    latest_diagnostics,
                )
            )

    setup = Setup(
        setup_type="SETUP_03",
        state=state,
        breakout_price=breakout_price,
        structural_invalidation=structural_invalidation,
        detected_index=detected_index,
        state_entered_index=state_entered_index,
        confirmed_index=confirmed_index,
    )
    assert latest_diagnostics is not None
    return SetupWithDiagnostics(setup, latest_diagnostics)


def detect_platform_breakout_history_with_diagnostics(
    quotes: list[Quote],
    swing_lookback: int = 5,
    platform_window: int = 40,
    platform_tolerance_pct: float = 0.0,
    arm_proximity_pct: float = 0.0,
    swings: Optional[list[SwingPoint]] = None,
) -> tuple[SetupWithDiagnostics, ...]:
    """Return one as-of Setup/diagnostics snapshot per input bar.

    This is the same production state-machine loop as
    ``detect_platform_breakout_with_diagnostics``.  It exists so a research
    replay can calculate the causal swing series once instead of recalculating
    every prefix from scratch; it does not expose future swing information to
    any snapshot.
    """
    history: list[SetupWithDiagnostics] = []
    detect_platform_breakout_with_diagnostics(
        quotes,
        swing_lookback=swing_lookback,
        platform_window=platform_window,
        platform_tolerance_pct=platform_tolerance_pct,
        arm_proximity_pct=arm_proximity_pct,
        swings=swings,
        history=history,
    )
    if len(history) != len(quotes):
        raise RuntimeError("SETUP_03 as-of history did not conserve input bars")
    return tuple(history)

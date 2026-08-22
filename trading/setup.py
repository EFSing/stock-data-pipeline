"""Setup Engine（Phase 2 首批：仅 SETUP_03 Platform Breakout）。

SETUP_03 Platform Breakout：价格在横盘平台内整理，形成明确阻力（平台高点）与
支撑（平台低点），随后收盘价向上突破平台高点。

复用 Phase 1（Single Source of Truth）：
- Swing 识别：`trading.swing.find_swings`
- Market Structure：`trading.structure.market_structure`
本模块不重新实现 pivot 识别或趋势判定；structure 由内部按 `confirmed_index <= t`
过滤后的 swings 计算，**不接受预计算的 structure**（只可接受预计算 swings）。

时间语义：按 bar 顺序推进状态机，任何状态判定只用 `data <= t`。
"""
from __future__ import annotations

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


def _is_platform(window_swings: list[SwingPoint]) -> bool:
    """平台判定：至少 2 个 CONFIRMED high + 2 个 CONFIRMED low，且结构为 RANGE/TRANSITION。"""
    highs = [s for s in window_swings if s.kind is SwingKind.HIGH]
    lows = [s for s in window_swings if s.kind is SwingKind.LOW]
    if len(highs) < 2 or len(lows) < 2:
        return False
    return market_structure(window_swings).trend in (Trend.RANGE, Trend.TRANSITION)


def detect_platform_breakout(
    quotes: list[Quote],
    swing_lookback: int = 5,
    platform_window: int = 40,
    boundary_tolerance: float = 0.0,
    swings: Optional[list[SwingPoint]] = None,
) -> Setup:
    """按时间顺序推进 SETUP_03 状态机，返回截至最后一个 bar 的 Setup 状态。

    状态迁移：
    - NONE → WATCH：识别到平台（窗口内 ≥2 CONFIRMED high + ≥2 CONFIRMED low，
      结构 RANGE/TRANSITION）；冻结 breakout_price（=平台高点）与
      structural_invalidation（=平台低点）。
    - WATCH → ARMED：close 逼近平台高点（≥ breakout_price * (1-tolerance)）。
    - ARMED → CONFIRMED：close 突破平台高点（> breakout_price * (1+tolerance)）。
    - WATCH/ARMED → FAILED：close 跌破平台低点（< structural_invalidation * (1-tolerance)）。
    - CONFIRMED / FAILED 为终态（Phase 2 不实现 ACTIVE/COMPLETED）。

    boundary_tolerance 为边界判断的容差比例（默认 0.0 = 严格边界）。
    """
    validate_quote_series(quotes)
    if platform_window < 1:
        raise ValueError(f"platform_window 必须 >= 1：{platform_window}")
    if boundary_tolerance < 0:
        raise ValueError(f"boundary_tolerance 不能为负：{boundary_tolerance}")

    n = len(quotes)
    if swings is None:
        swings = find_swings(quotes, lookback=swing_lookback)

    state = SetupState.NONE
    breakout_price: Optional[float] = None
    structural_invalidation: Optional[float] = None
    detected_index: Optional[int] = None
    state_entered_index: Optional[int] = None
    confirmed_index: Optional[int] = None

    for t in range(n):
        close_t = float(quotes[t].close)

        if state is SetupState.NONE:
            window = _confirmed_swings_in_window(swings, t, platform_window)
            if _is_platform(window):
                highs = [s.price for s in window if s.kind is SwingKind.HIGH]
                lows = [s.price for s in window if s.kind is SwingKind.LOW]
                breakout_price = max(highs)
                structural_invalidation = min(lows)
                state = SetupState.WATCH
                detected_index = t
                state_entered_index = t
        elif state is SetupState.WATCH:
            assert breakout_price is not None and structural_invalidation is not None
            if close_t < structural_invalidation * (1 - boundary_tolerance):
                state = SetupState.FAILED
                state_entered_index = t
            elif close_t >= breakout_price * (1 - boundary_tolerance):
                state = SetupState.ARMED
                state_entered_index = t
        elif state is SetupState.ARMED:
            assert breakout_price is not None and structural_invalidation is not None
            if close_t < structural_invalidation * (1 - boundary_tolerance):
                state = SetupState.FAILED
                state_entered_index = t
            elif close_t > breakout_price * (1 + boundary_tolerance):
                state = SetupState.CONFIRMED
                confirmed_index = t
                state_entered_index = t
        # CONFIRMED / FAILED：终态，不再迁移

    return Setup(
        setup_type="SETUP_03",
        state=state,
        breakout_price=breakout_price,
        structural_invalidation=structural_invalidation,
        detected_index=detected_index,
        state_entered_index=state_entered_index,
        confirmed_index=confirmed_index,
    )

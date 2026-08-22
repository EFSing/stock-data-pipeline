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


def _has_new_confirmed_swing(
    window_swings: list[SwingPoint], last_terminal_index: int
) -> bool:
    """窗口内是否存在 pivot 发生在 terminal 之后的新 swing。

    用 pivot_index（swing 发生位置）而非 confirmed_index 判断：避免把「旧 pivot
    因后续数据而晚确认」误判为新 swing，从而在 CONFIRMED 后马上重复识别旧平台。
    """
    return any(s.pivot_index > last_terminal_index for s in window_swings)


def _is_platform(
    window_swings: list[SwingPoint], platform_tolerance_pct: float
) -> bool:
    """平台判定：至少 2 个 CONFIRMED high + 2 个 CONFIRMED low，结构 RANGE/TRANSITION，
    且 highs 彼此、lows 彼此在 platform_tolerance_pct 内（真实边界一致性）。

    扩张（HH+LL）虽可能判为 TRANSITION，但 highs/lows 离散度超出容差，故不视为平台。
    """
    highs = [s.price for s in window_swings if s.kind is SwingKind.HIGH]
    lows = [s.price for s in window_swings if s.kind is SwingKind.LOW]
    if len(highs) < 2 or len(lows) < 2:
        return False
    if market_structure(window_swings).trend not in (Trend.RANGE, Trend.TRANSITION):
        return False
    high_span = (max(highs) - min(highs)) / max(highs)
    low_span = (max(lows) - min(lows)) / max(lows)
    return high_span <= platform_tolerance_pct and low_span <= platform_tolerance_pct


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
    - WATCH/ARMED → FAILED：close 跌破平台低点（< structural_invalidation）。
    - CONFIRMED / FAILED 为当前 Setup 终态；Detector 继续扫描后续新平台。

    platform_tolerance_pct 仅用于平台边界一致性；突破/失效保持严格
    `close > breakout_price` / `close < structural_invalidation`。
    """
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

    for t in range(n):
        close_t = float(quotes[t].close)

        if state in (SetupState.NONE, SetupState.CONFIRMED, SetupState.FAILED):
            window = _confirmed_swings_in_window(swings, t, platform_window)
            if _has_new_confirmed_swing(window, last_terminal_index) and _is_platform(
                window, platform_tolerance_pct
            ):
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
                else:
                    state = SetupState.WATCH
                    state_entered_index = t
        elif state is SetupState.WATCH:
            assert breakout_price is not None and structural_invalidation is not None
            if close_t > breakout_price:
                state = SetupState.CONFIRMED
                confirmed_index = t
                state_entered_index = t
                last_terminal_index = t
            elif close_t < structural_invalidation:
                state = SetupState.FAILED
                state_entered_index = t
                last_terminal_index = t
            elif close_t >= breakout_price * (1 - arm_proximity_pct):
                state = SetupState.ARMED
                state_entered_index = t
        elif state is SetupState.ARMED:
            assert breakout_price is not None and structural_invalidation is not None
            if close_t > breakout_price:
                state = SetupState.CONFIRMED
                confirmed_index = t
                state_entered_index = t
                last_terminal_index = t
            elif close_t < structural_invalidation:
                state = SetupState.FAILED
                state_entered_index = t
                last_terminal_index = t

    return Setup(
        setup_type="SETUP_03",
        state=state,
        breakout_price=breakout_price,
        structural_invalidation=structural_invalidation,
        detected_index=detected_index,
        state_entered_index=state_entered_index,
        confirmed_index=confirmed_index,
    )

"""Market Structure（市场结构）。

只用 CONFIRMED Swing 识别 HH/HL/LH/LL，推断趋势。
Swing 数量不足 → UNKNOWN；结构不明确 → TRANSITION，禁止强制分类为趋势/区间。

分类规则（比较最近两个 CONFIRMED Swing High 与最近两个 CONFIRMED Swing Low）：
- HH + HL（高点更高 + 低点更高）→ UPTREND
- LH + LL（高点更低 + 低点更低）→ DOWNTREND
- LH + HL（高点更低 + 低点更高，收缩）→ RANGE
- 其余（含 HH + LL 扩张，或高低点持平等边界）→ TRANSITION
"""
from __future__ import annotations

from trading.models import (
    MarketStructure,
    SwingKind,
    SwingPoint,
    SwingState,
    Trend,
)


def _classify_trend(
    highs: tuple[SwingPoint, ...], lows: tuple[SwingPoint, ...]
) -> Trend:
    if len(highs) < 2 or len(lows) < 2:
        return Trend.UNKNOWN

    last_high = highs[-1].price
    prev_high = highs[-2].price
    last_low = lows[-1].price
    prev_low = lows[-2].price

    hh = last_high > prev_high
    lh = last_high < prev_high
    hl = last_low > prev_low
    ll = last_low < prev_low

    if hh and hl:
        return Trend.UPTREND
    if lh and ll:
        return Trend.DOWNTREND
    if lh and hl:
        return Trend.RANGE
    return Trend.TRANSITION


def market_structure(swings: list[SwingPoint]) -> MarketStructure:
    """根据已确认 Swing 计算市场结构。

    自动排除 PROVISIONAL Swing——只有 confirmed_index 已出现的 Swing
    才能参与结构判定，避免把尚未确认的极点当作结构依据。
    """
    confirmed = [s for s in swings if s.state is SwingState.CONFIRMED]
    highs = tuple(s for s in confirmed if s.kind is SwingKind.HIGH)
    lows = tuple(s for s in confirmed if s.kind is SwingKind.LOW)
    return MarketStructure(
        trend=_classify_trend(highs, lows),
        highs=highs,
        lows=lows,
    )

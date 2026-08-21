"""Swing 引擎（causal pivot，禁止事后重绘 ZigZag）。

识别规则（因果，只用 data <= t）：
- bar i 为 Swing High：high_i 严格大于左侧 lookback 根 bar，且大于等于右侧 lookback 根 bar。
- bar i 为 Swing Low：low_i 严格小于左侧 lookback 根 bar，且小于等于右侧 lookback 根 bar。

时间语义：
- pivot_index / pivot_date 表示 Swing 发生的 bar。
- confirmed_index / confirmed_date 表示该 Swing 信息「实际可用」的 bar：
  一个 pivot 被其后的第一个反向 pivot 确认，confirmed_index = 反向 pivot 的
  pivot_index + lookback（反向 pivot 完成识别的最早时刻）。
- 任何 as-of t 的历史决策只能使用 confirmed_index <= t 的 Swing。

PROVISIONAL 可随新数据变化（例如被更高 high 取代），但 CONFIRMED 的 Swing 一旦
确认即冻结，未来数据不得回填修改——这是本引擎与 ZigZag 的根本区别。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from core import Quote
from trading.indicators import atr
from trading.models import SwingKind, SwingPoint, validate_quote_series


def _is_swing_high(highs: list[float], i: int, lookback: int) -> bool:
    return highs[i] > max(highs[i - lookback : i]) and highs[i] >= max(
        highs[i + 1 : i + lookback + 1]
    )


def _is_swing_low(lows: list[float], i: int, lookback: int) -> bool:
    return lows[i] < min(lows[i - lookback : i]) and lows[i] <= min(
        lows[i + 1 : i + lookback + 1]
    )


def _dedupe_alternating(
    pivots: list[tuple[SwingKind, float, int]],
) -> list[tuple[SwingKind, float, int]]:
    """保证 pivot 严格交替；连续同向时保留更极端者。"""
    out: list[tuple[SwingKind, float, int]] = []
    for p in pivots:
        if out and out[-1][0] is p[0]:
            if p[0] is SwingKind.HIGH:
                if p[1] > out[-1][1]:
                    out[-1] = p
            else:
                if p[1] < out[-1][1]:
                    out[-1] = p
        else:
            out.append(p)
    return out


def _apply_excursion_filter(
    pivots: list[tuple[SwingKind, float, int]],
    highs: list[float],
    lows: list[float],
    lookback: int,
    min_excursion_atr: float,
    min_excursion_pct: float,
    atr_series: Optional[list[Optional[float]]],
) -> list[tuple[SwingKind, float, int]]:
    """过滤摆幅不足的噪声 pivot（因果：只用 pivot 后 lookback 根 bar）。"""
    if min_excursion_atr == 0.0 and min_excursion_pct == 0.0:
        return pivots
    out: list[tuple[SwingKind, float, int]] = []
    for kind, price, idx in pivots:
        if kind is SwingKind.HIGH:
            window = lows[idx + 1 : idx + lookback + 1]
            if not window:
                out.append((kind, price, idx))
                continue
            excursion = price - min(window)
        else:
            window = highs[idx + 1 : idx + lookback + 1]
            if not window:
                out.append((kind, price, idx))
                continue
            excursion = max(window) - price

        threshold = 0.0
        if min_excursion_atr > 0.0 and atr_series is not None:
            atr_value = atr_series[idx]
            if atr_value is not None:
                threshold = max(threshold, min_excursion_atr * atr_value)
        if min_excursion_pct > 0.0:
            threshold = max(threshold, min_excursion_pct * price)

        if excursion >= threshold:
            out.append((kind, price, idx))
    return out


def find_swings(
    quotes: list[Quote],
    lookback: int = 5,
    min_excursion_atr: float = 0.0,
    min_excursion_pct: float = 0.0,
    atr_period: int = 14,
) -> list[SwingPoint]:
    """识别 Swing 序列，按 pivot_index 升序返回。

    - min_excursion_atr / min_excursion_pct 为 0 时禁用对应过滤。
    - 序列长度不足 2*lookback+1 时无法形成任何 pivot，返回空列表。
    """
    validate_quote_series(quotes)
    if lookback < 1:
        raise ValueError(f"lookback 必须 >= 1：{lookback}")
    if min_excursion_atr < 0 or min_excursion_pct < 0:
        raise ValueError("excursion 阈值不能为负")
    if atr_period < 1:
        raise ValueError(f"atr_period 必须 >= 1：{atr_period}")

    n = len(quotes)
    highs = [float(q.high) for q in quotes]
    lows = [float(q.low) for q in quotes]

    raw: list[tuple[SwingKind, float, int]] = []
    for i in range(lookback, n - lookback):
        if _is_swing_high(highs, i, lookback):
            raw.append((SwingKind.HIGH, highs[i], i))
        elif _is_swing_low(lows, i, lookback):
            raw.append((SwingKind.LOW, lows[i], i))

    pivots = _dedupe_alternating(raw)
    if not pivots:
        return []

    atr_series = atr(quotes, atr_period) if min_excursion_atr > 0.0 else None
    pivots = _apply_excursion_filter(
        pivots, highs, lows, lookback, min_excursion_atr, min_excursion_pct, atr_series
    )
    pivots = _dedupe_alternating(pivots)

    swings: list[SwingPoint] = []
    for k, (kind, price, idx) in enumerate(pivots):
        confirmed_index: Optional[int] = None
        confirmed_date: Optional[date] = None
        if k + 1 < len(pivots):
            next_idx = pivots[k + 1][2]
            confirmed_index = next_idx + lookback
            confirmed_date = quotes[confirmed_index].trade_date
        swings.append(
            SwingPoint(
                kind=kind,
                price=price,
                pivot_index=idx,
                pivot_date=quotes[idx].trade_date,
                confirmed_index=confirmed_index,
                confirmed_date=confirmed_date,
            )
        )
    return swings

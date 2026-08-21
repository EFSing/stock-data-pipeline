"""Swing 引擎（causal pivot，禁止事后重绘 ZigZag）。

识别规则（因果，只用 data <= t）：
- bar i 为 Swing High：high_i 严格大于左侧 lookback 根 bar，且大于等于右侧 lookback 根 bar。
- bar i 为 Swing Low：low_i 严格小于左侧 lookback 根 bar，且小于等于右侧 lookback 根 bar。

时间语义（按时间顺序的状态机）：
- pivot_index / pivot_date 表示 Swing 发生的 bar。
- confirmed_index / confirmed_date 表示该 Swing 信息「实际可用」的 bar：
  一个 pivot 被其后出现的第一个反向 pivot 确认，confirmed_index = 反向 pivot 的
  pivot_index + lookback（反向 pivot 完成识别的最早时刻）。
- 任何 as-of t 的历史决策只能使用 confirmed_index <= t 的 Swing。

PROVISIONAL 可随新数据变化：连续同向 pivot 中，更极端者只替换最后一个
PROVISIONAL swing。CONFIRMED 的 Swing 一旦确认即冻结，未来数据（含更极端的
同向 pivot）不得回填修改其确认信息——这是本引擎与 ZigZag 的根本区别。
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


def _build_swings(
    pivots: list[tuple[SwingKind, float, int]],
    quotes: list[Quote],
    lookback: int,
) -> list[SwingPoint]:
    """按时间顺序构建 swing 序列（状态机）。

    对每个 pivot（已按 pivot_index 升序）：
    - 与最后一个 swing 反向：确认最后一个 swing（confirmed_index = 当前
      pivot_index + lookback），并把当前 pivot 追加为新的 PROVISIONAL。
    - 与最后一个 swing 同向：更极端者（HIGH 更高 / LOW 更低）只替换最后一个
      PROVISIONAL swing；绝不改动此前已 CONFIRMED 的 swing。

    列表末尾永远是一个 PROVISIONAL，因此同向替换只会作用于 PROVISIONAL，
    不会回填修改任何 CONFIRMED swing 的确认信息。
    """
    swing_list: list[list] = []  # [kind, price, pivot_index, confirmed_index]
    for kind, price, idx in pivots:
        if not swing_list:
            swing_list.append([kind, price, idx, None])
            continue
        last = swing_list[-1]
        if kind is not last[0]:
            # 反向：确认最后一个 swing
            last[3] = idx + lookback
            swing_list.append([kind, price, idx, None])
        else:
            # 同向：更极端者替换最后一个 PROVISIONAL
            if (kind is SwingKind.HIGH and price > last[1]) or (
                kind is SwingKind.LOW and price < last[1]
            ):
                swing_list[-1] = [kind, price, idx, None]
            # 否则忽略当前 pivot

    result: list[SwingPoint] = []
    for kind, price, idx, confirmed_index in swing_list:
        result.append(
            SwingPoint(
                kind=kind,
                price=price,
                pivot_index=idx,
                pivot_date=quotes[idx].trade_date,
                confirmed_index=confirmed_index,
                confirmed_date=(
                    quotes[confirmed_index].trade_date
                    if confirmed_index is not None
                    else None
                ),
            )
        )
    return result


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

    if not raw:
        return []

    atr_series = atr(quotes, atr_period) if min_excursion_atr > 0.0 else None
    pivots = _apply_excursion_filter(
        raw, highs, lows, lookback, min_excursion_atr, min_excursion_pct, atr_series
    )

    return _build_swings(pivots, quotes, lookback)

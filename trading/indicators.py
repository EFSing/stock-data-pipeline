"""技术指标（纯函数）。

约定（固定定义，见 DECISION_LOG.md）：
- ATR 采用 Wilder ATR，RSI 采用 Wilder RSI，EMA 采用标准 2/(N+1)。
- 所有序列指标返回与输入等长的 `list[Optional[float]]`；warm-up 区间为 None。
- 指标只用已出现的 bar 计算，绝不使用未来数据。
"""
from __future__ import annotations

from typing import Optional

from core import Quote
from trading.models import validate_quote_series


def closes(quotes: list[Quote]) -> list[float]:
    return [float(q.close) for q in quotes]


def highs(quotes: list[Quote]) -> list[float]:
    return [float(q.high) for q in quotes]


def lows(quotes: list[Quote]) -> list[float]:
    return [float(q.low) for q in quotes]


def true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    """单根 bar 的真实波幅；无 prev_close 时退化为 high - low。"""
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(quotes: list[Quote], period: int = 14) -> list[Optional[float]]:
    """Wilder ATR。索引 0..period-1 为 None（warm-up）。"""
    validate_quote_series(quotes)
    if period <= 0:
        raise ValueError(f"period 必须为正整数：{period}")
    n = len(quotes)
    result: list[Optional[float]] = [None] * n
    if n < period + 1:
        return result

    trs: list[float] = [0.0] * n
    trs[0] = float(quotes[0].high) - float(quotes[0].low)
    for i in range(1, n):
        trs[i] = true_range(
            float(quotes[i].high), float(quotes[i].low), float(quotes[i - 1].close)
        )

    result[period] = sum(trs[1 : period + 1]) / period
    for i in range(period + 1, n):
        prev = result[i - 1]
        assert prev is not None
        result[i] = (prev * (period - 1) + trs[i]) / period
    return result


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def rsi(quotes: list[Quote], period: int = 14) -> list[Optional[float]]:
    """Wilder RSI。索引 0..period-1 为 None（warm-up）。"""
    validate_quote_series(quotes)
    if period <= 0:
        raise ValueError(f"period 必须为正整数：{period}")
    n = len(quotes)
    result: list[Optional[float]] = [None] * n
    if n < period + 1:
        return result

    gains: list[float] = [0.0] * n
    losses: list[float] = [0.0] * n
    for i in range(1, n):
        delta = float(quotes[i].close) - float(quotes[i - 1].close)
        gains[i] = max(delta, 0.0)
        losses[i] = max(-delta, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    result[period] = _rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i] = _rsi_from(avg_gain, avg_loss)
    return result


def sma(values: list[float], period: int) -> list[Optional[float]]:
    """简单移动平均。索引 0..period-2 为 None，索引 period-1 起有值。"""
    if period <= 0:
        raise ValueError(f"period 必须为正整数：{period}")
    n = len(values)
    result: list[Optional[float]] = [None] * n
    if n < period:
        return result
    running = sum(values[:period])
    result[period - 1] = running / period
    for i in range(period, n):
        running += values[i] - values[i - period]
        result[i] = running / period
    return result


def ema(values: list[float], period: int) -> list[Optional[float]]:
    """指数移动平均，标准平滑系数 2/(N+1)，seed 用前 N 个值的 SMA。

    索引 0..period-2 为 None，索引 period-1 起有值。
    """
    if period <= 0:
        raise ValueError(f"period 必须为正整数：{period}")
    n = len(values)
    result: list[Optional[float]] = [None] * n
    if n < period:
        return result
    alpha = 2.0 / (period + 1)
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, n):
        prev = result[i - 1]
        assert prev is not None
        result[i] = alpha * values[i] + (1 - alpha) * prev
    return result


def rolling_high(values: list[float], window: int) -> list[Optional[float]]:
    """滚动窗口最大值。索引 0..window-2 为 None。"""
    return _rolling_extreme(values, window, is_max=True)


def rolling_low(values: list[float], window: int) -> list[Optional[float]]:
    """滚动窗口最小值。索引 0..window-2 为 None。"""
    return _rolling_extreme(values, window, is_max=False)


def _rolling_extreme(
    values: list[float], window: int, is_max: bool
) -> list[Optional[float]]:
    if window <= 0:
        raise ValueError(f"window 必须为正整数：{window}")
    n = len(values)
    result: list[Optional[float]] = [None] * n
    for i in range(window - 1, n):
        window_values = values[i - window + 1 : i + 1]
        result[i] = max(window_values) if is_max else min(window_values)
    return result

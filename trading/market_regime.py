"""Market Regime Engine V1（纯计算、因果）。

V1 对齐富途 MT-NOW 的六状态语义：
WATCH / PANIC / BOTTOM / HOT / WEAK / RISK。

重要约束：
- 复用 Trading Core 的 Wilder RSI 与标准 EMA，禁止复制第二套指标实现。
- `state(t)` 只使用 `data <= t`，不使用未来函数、不回填过去信号。
- 本模块输出的是“截至当前 bar 收盘”的状态。实时未收盘 bar 可以变化；
  调用方只有在 bar 已确认收盘后，才能把该状态视为正式信号。
- 富途 MT-C 的“一根 bar 延迟”属于展示层处理，不在核心计算层复制。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from core import Quote
from trading.indicators import closes, ema, rsi


class MarketRegimeState(str, Enum):
    NEUTRAL = "NEUTRAL"
    WATCH = "WATCH"
    PANIC = "PANIC"
    BOTTOM = "BOTTOM"
    HOT = "HOT"
    WEAK = "WEAK"
    RISK = "RISK"


_PRIMARY_PRIORITY = (
    MarketRegimeState.RISK,
    MarketRegimeState.BOTTOM,
    MarketRegimeState.PANIC,
    MarketRegimeState.HOT,
    MarketRegimeState.WEAK,
    MarketRegimeState.WATCH,
)


@dataclass(frozen=True)
class MarketRegimeConfig:
    rsi_period: int = 14
    ema_period: int = 20
    memory_window: int = 20
    watch_threshold: float = 30.0
    panic_threshold: float = 22.0
    hot_threshold: float = 78.0

    def __post_init__(self) -> None:
        if self.rsi_period <= 0:
            raise ValueError("rsi_period 必须为正整数")
        if self.ema_period <= 0:
            raise ValueError("ema_period 必须为正整数")
        if self.memory_window <= 0:
            raise ValueError("memory_window 必须为正整数")
        if not (
            0.0
            < self.panic_threshold
            < self.watch_threshold
            < self.hot_threshold
            < 100.0
        ):
            raise ValueError(
                "阈值必须满足 0 < panic_threshold < watch_threshold "
                "< hot_threshold < 100"
            )


@dataclass(frozen=True)
class MarketRegimePoint:
    index: int
    trade_date: date
    close: float
    rsi: Optional[float]
    ema: Optional[float]
    states: tuple[MarketRegimeState, ...]

    @property
    def primary_state(self) -> MarketRegimeState:
        for state in _PRIMARY_PRIORITY:
            if state in self.states:
                return state
        return MarketRegimeState.NEUTRAL

    def has_state(self, state: MarketRegimeState) -> bool:
        return state in self.states


def market_regime(
    quotes: list[Quote],
    config: MarketRegimeConfig | None = None,
) -> list[MarketRegimePoint]:
    """逐 bar 计算 Market Regime 状态。

    状态与富途 V5.2 规则一致：
    - WATCH: 22 <= RSI < 30
    - PANIC: RSI < 22
    - BOTTOM: 近 20 bar 曾 RSI < 30，当前 RSI >= 30，且价格由下向上穿越 EMA20
    - HOT: RSI > 78
    - RISK: 近 20 bar 曾 RSI > 78，且价格由上向下跌破 EMA20
    - WEAK: 价格由上向下跌破 EMA20，但不满足 RISK

    同一 bar 可同时具有多个状态；`primary_state` 按风险/确认优先级给出
    一个用于消息路由的主状态。
    """
    cfg = config or MarketRegimeConfig()
    rsi_values = rsi(quotes, period=cfg.rsi_period)
    ema_values = ema(closes(quotes), period=cfg.ema_period)

    result: list[MarketRegimePoint] = []
    for i, quote in enumerate(quotes):
        rsi_value = rsi_values[i]
        ema_value = ema_values[i]
        states: list[MarketRegimeState] = []

        if rsi_value is not None and ema_value is not None:
            start = max(0, i - cfg.memory_window + 1)
            recent_rsi = [
                value
                for value in rsi_values[start : i + 1]
                if value is not None
            ]
            recent_watch = any(
                value < cfg.watch_threshold for value in recent_rsi
            )
            recent_hot = any(value > cfg.hot_threshold for value in recent_rsi)

            prev_ema = ema_values[i - 1] if i > 0 else None
            prev_close = float(quotes[i - 1].close) if i > 0 else None
            close = float(quote.close)

            price_recover = (
                prev_ema is not None
                and prev_close is not None
                and prev_close <= prev_ema
                and close > ema_value
            )
            price_break = (
                prev_ema is not None
                and prev_close is not None
                and prev_close >= prev_ema
                and close < ema_value
            )

            risk = recent_hot and price_break
            weak = price_break and not risk

            if cfg.panic_threshold <= rsi_value < cfg.watch_threshold:
                states.append(MarketRegimeState.WATCH)
            if rsi_value < cfg.panic_threshold:
                states.append(MarketRegimeState.PANIC)
            if recent_watch and rsi_value >= cfg.watch_threshold and price_recover:
                states.append(MarketRegimeState.BOTTOM)
            if rsi_value > cfg.hot_threshold:
                states.append(MarketRegimeState.HOT)
            if weak:
                states.append(MarketRegimeState.WEAK)
            if risk:
                states.append(MarketRegimeState.RISK)

        result.append(
            MarketRegimePoint(
                index=i,
                trade_date=quote.trade_date,
                close=float(quote.close),
                rsi=rsi_value,
                ema=ema_value,
                states=tuple(states),
            )
        )
    return result

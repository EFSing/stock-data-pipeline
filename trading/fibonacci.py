"""Fibonacci 引擎。

基于一个明确 Swing（HIGH+LOW 两端）计算回撤位与延伸位，不依赖 structure。
提供两个入口：`fibonacci_levels_from_prices(high, low)`（直接消费数值）与
`fibonacci_levels(a, b)`（消费 SwingPoint，内部复用前者）。

- retracement：从 swing_high 向下，price = swing_high - range * ratio。
- extension：从 swing_low 向上延伸，price = swing_low + range * ratio（ratio > 1）。

输入两个 Swing 必须是一 HIGH 一 LOW（明确两端），且摆幅为正，否则 fail fast。
"""
from __future__ import annotations

from trading.models import FibonacciLevels, PriceRegion, SwingKind, SwingPoint

RETRACEMENT_RATIOS: dict[str, float] = {
    "0.382": 0.382,
    "0.5": 0.5,
    "0.618": 0.618,
    "0.786": 0.786,
}

EXTENSION_RATIOS: dict[str, float] = {
    "1.272": 1.272,
    "1.618": 1.618,
    "2.0": 2.0,
    "2.618": 2.618,
}


def fibonacci_levels_from_prices(swing_high: float, swing_low: float) -> FibonacciLevels:
    """基于数值 high/low 直接计算 Fibonacci 水平。

    供无 SwingPoint 的调用方（如 decision）直接使用；`fibonacci_levels` 亦复用本函数。
    """
    rng = swing_high - swing_low
    if rng <= 0:
        raise ValueError(
            f"Fibonacci 摆幅必须为正：swing_high={swing_high}, swing_low={swing_low}"
        )

    retracements = {
        key: swing_high - rng * ratio for key, ratio in RETRACEMENT_RATIOS.items()
    }
    extensions = {
        key: swing_low + rng * ratio for key, ratio in EXTENSION_RATIOS.items()
    }
    return FibonacciLevels(
        swing_high=swing_high,
        swing_low=swing_low,
        retracements=retracements,
        extensions=extensions,
    )


def fibonacci_levels(a: SwingPoint, b: SwingPoint) -> FibonacciLevels:
    """计算 a、b 两个 Swing 端点构成的 Fibonacci 水平。"""
    if a.kind is b.kind:
        raise ValueError(f"Fibonacci 需要 HIGH+LOW 两端，收到 {a.kind.value} + {b.kind.value}")

    return fibonacci_levels_from_prices(
        swing_high=max(a.price, b.price),
        swing_low=min(a.price, b.price),
    )


def fibonacci_regions(levels: FibonacciLevels) -> tuple[tuple[PriceRegion, ...], tuple[PriceRegion, ...]]:
    """把既有 Fibonacci levels 转成相邻 ratio 的候选价格区间。

    计算唯一复用 ``fibonacci_levels_from_prices`` 的结果；本函数不引入
    第二套 ratio 或价格公式。相邻层级按价格排序后组成 inclusive region。
    """
    def regions(values: dict[str, float]) -> tuple[PriceRegion, ...]:
        # Keep the canonical ratio order from RETRACEMENT_RATIOS /
        # EXTENSION_RATIOS; lower/upper are normalized independently below.
        ordered = list(values.items())
        return tuple(
            PriceRegion(
                label=f"{ordered[index][0]}-{ordered[index + 1][0]}",
                lower=min(ordered[index][1], ordered[index + 1][1]),
                upper=max(ordered[index][1], ordered[index + 1][1]),
            )
            for index in range(len(ordered) - 1)
        )

    return regions(levels.retracements), regions(levels.extensions)

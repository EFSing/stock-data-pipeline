"""Fibonacci 引擎。

只消费 SwingPoint（不依赖 structure），基于一个明确 Swing（HIGH+LOW 两端）
计算回撤位与延伸位。

- retracement：从 swing_high 向下，price = swing_high - range * ratio。
- extension：从 swing_low 向上延伸，price = swing_low + range * ratio（ratio > 1）。

输入两个 Swing 必须是一 HIGH 一 LOW（明确两端），且摆幅为正，否则 fail fast。
"""
from __future__ import annotations

from trading.models import FibonacciLevels, SwingKind, SwingPoint

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


def fibonacci_levels(a: SwingPoint, b: SwingPoint) -> FibonacciLevels:
    """计算 a、b 两个 Swing 端点构成的 Fibonacci 水平。"""
    if a.kind is b.kind:
        raise ValueError(f"Fibonacci 需要 HIGH+LOW 两端，收到 {a.kind.value} + {b.kind.value}")

    swing_high = max(a.price, b.price)
    swing_low = min(a.price, b.price)
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

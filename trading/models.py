"""Trading Core 数据模型与输入校验。

所有结构均为 frozen dataclass，保证不可变，避免被下游无意篡改。
输入数据载体复用 `core.Quote`，本模块不新建 Bar 类型。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from core import Quote


class Trend(str, Enum):
    """市场结构分类。证据不足时禁止强制分类为趋势/区间。"""

    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


class SwingState(str, Enum):
    """Swing 的可信状态。

    PROVISIONAL：pivot 已形成但尚未被后续反向结构确认，可能被推翻。
    CONFIRMED：pivot 已被后续数据确认，可用于历史决策（as-of confirmed_index）。
    """

    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"


class SwingKind(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True)
class SwingPoint:
    """一个 Swing 极点。

    - pivot_index / pivot_date：Swing 发生的 bar 位置与交易日（信息尚未可用时）。
    - confirmed_index / confirmed_date：该 Swing 信息实际可用的 bar 位置与交易日；
      PROVISIONAL 时为 None。任何 as-of t 的历史决策只能使用 confirmed_index <= t 的 Swing。
    """

    kind: SwingKind
    price: float
    pivot_index: int
    pivot_date: date
    confirmed_index: Optional[int]
    confirmed_date: Optional[date]

    @property
    def state(self) -> SwingState:
        return (
            SwingState.CONFIRMED
            if self.confirmed_index is not None
            else SwingState.PROVISIONAL
        )

    @property
    def confirmed_at(self) -> Optional[int]:
        """信息可用时刻的 bar index 别名（CONFIRMED 时非 None）。"""
        return self.confirmed_index


@dataclass(frozen=True)
class MarketStructure:
    trend: Trend
    highs: tuple[SwingPoint, ...]
    lows: tuple[SwingPoint, ...]


@dataclass(frozen=True)
class FibonacciLevels:
    swing_high: float
    swing_low: float
    retracements: dict[str, float]
    extensions: dict[str, float]


@dataclass(frozen=True)
class RiskReward:
    entry: float
    execution_stop: float
    risk_per_share: float
    target_prices: tuple[float, ...]
    rr_ratios: tuple[float, ...]
    quality: str


@dataclass(frozen=True)
class PositionSize:
    risk_capital: float
    entry: float
    execution_stop: float
    risk_per_share: float
    theoretical_quantity: float
    max_loss: float


class SetupState(str, Enum):
    """Setup 生命周期状态（Phase 2 只做到 FAILED 为止）。

    ACTIVE / COMPLETED 属于后续交易生命周期，不在本阶段实现。
    """

    NONE = "NONE"
    WATCH = "WATCH"
    ARMED = "ARMED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Setup:
    """一个 Setup 候选（Phase 2 目前仅 SETUP_03 Platform Breakout）。

    - breakout_price：突破触发价（= 平台高点 platform_high）。
    - structural_invalidation：结构失效价（= 平台低点 platform_low）。
    - detected_index：平台被识别（进入 WATCH）的 bar index。
    - state_entered_index：进入当前 state 的 bar index。
    - confirmed_index：突破确认（进入 CONFIRMED）的 bar index。
    Phase 2 暂不输出 execution_stop / entry / target。
    """

    setup_type: str
    state: SetupState
    breakout_price: Optional[float] = None
    structural_invalidation: Optional[float] = None
    detected_index: Optional[int] = None
    state_entered_index: Optional[int] = None
    confirmed_index: Optional[int] = None


class DecisionAction(str, Enum):
    """决策动作（最小闭环）。"""

    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    WAIT_CONFIRMATION = "WAIT_CONFIRMATION"
    ENTRY_ALLOWED = "ENTRY_ALLOWED"


@dataclass(frozen=True)
class EntryPlan:
    """入场计划。

    - planned_entry：V1 用当前 as-of bar close 作为真实决策价格。
    - entry_zone_low / entry_zone_high：入场区间 [breakout_price, breakout_price + max_chase_atr*ATR]。
    """

    planned_entry: float
    entry_zone_low: float
    entry_zone_high: float


@dataclass(frozen=True)
class Decision:
    """一笔决策的完整结果。"""

    action: DecisionAction
    entry_plan: Optional[EntryPlan]
    structural_invalidation: Optional[float]
    execution_stop: Optional[float]
    targets: tuple[float, ...]
    rr: Optional[RiskReward]
    position_size: Optional[PositionSize]


def validate_quote_series(quotes: list[Quote]) -> None:
    """校验 Trading Core 输入序列；违反约束时 fail fast（抛 ValueError）。

    约束：
    - 非空
    - 所有 bar 属于同一 symbol
    - 所有 bar 属于同一 market
    - trade_date 严格升序且无重复

    不静默排序或去重——脏输入应显式失败，交由上游修正。
    """
    if not quotes:
        raise ValueError("交易序列为空")
    symbol = quotes[0].symbol
    market = quotes[0].market
    prev_date: Optional[date] = None
    for i, q in enumerate(quotes):
        if q.symbol != symbol:
            raise ValueError(
                f"序列包含不同 symbol：index 0={symbol}，index {i}={q.symbol}"
            )
        if q.market != market:
            raise ValueError(
                f"序列包含不同 market：index 0={market}，index {i}={q.market}"
            )
        if prev_date is not None and q.trade_date <= prev_date:
            raise ValueError(
                f"trade_date 必须严格升序且无重复："
                f"index {i - 1}={prev_date.isoformat()}，index {i}={q.trade_date.isoformat()}"
            )
        prev_date = q.trade_date

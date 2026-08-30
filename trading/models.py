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


class WaveScenarioFamily(str, Enum):
    """有限的 Wave Scenario v1 taxonomy。

    这些是结构候选而不是 Elliott Wave 的完整自动数浪结果。
    """

    WAVE_2_TO_3_CANDIDATE = "WAVE_2_TO_3_CANDIDATE"
    WAVE_3_CONTINUATION_CANDIDATE = "WAVE_3_CONTINUATION_CANDIDATE"
    ABC_CORRECTION_CANDIDATE = "ABC_CORRECTION_CANDIDATE"
    UPTREND_UNKNOWN_WAVE = "UPTREND_UNKNOWN_WAVE"
    DOWNTREND_OR_INVALID_FOR_LONG = "DOWNTREND_OR_INVALID_FOR_LONG"
    NO_VALID_SCENARIO = "NO_VALID_SCENARIO"


@dataclass(frozen=True)
class PriceRegion:
    """一个可解释的价格候选区间（inclusive）。"""

    label: str
    lower: float
    upper: float


@dataclass(frozen=True)
class WaveLeg:
    """由两个已确认 Swing 构成的结构腿。"""

    start: SwingPoint
    end: SwingPoint
    direction: str


@dataclass(frozen=True)
class WaveScenario:
    """Wave Engine v1 的一个主/备选结构情景。

    ``evidence_score`` 是满足的显式规则数，不是模型概率或收益评分。
    ``setup*_context_eligible`` 只表示结构上下文是否满足，不表示允许入场。
    """

    family: WaveScenarioFamily
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    evidence_score: int
    confirmed_swings: tuple[SwingPoint, ...]
    candidate_impulse_leg: Optional[WaveLeg]
    candidate_retracement_leg: Optional[WaveLeg]
    fibonacci_retracement_regions: tuple[PriceRegion, ...]
    fibonacci_extension_regions: tuple[PriceRegion, ...]
    structural_invalidation: Optional[float]
    scenario_invalidation_reason: str
    setup01_context_eligible: bool
    setup02_context_eligible: bool

    @property
    def confidence_score(self) -> int:
        """兼容用户术语；实际值仍是规则计数而非主观概率。"""
        return self.evidence_score


@dataclass(frozen=True)
class WaveScenarioEvaluation:
    """截至一个交易日的完整 Wave Scenario 评估。"""

    protocol_version: str
    as_of_date: date
    as_of_close: float
    weekly_state: Trend
    daily_state: Trend
    weekly_swings: tuple[SwingPoint, ...]
    daily_swings: tuple[SwingPoint, ...]
    primary_scenario: WaveScenario
    alternate_scenario: WaveScenario


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
    """Setup 生命周期状态。

    The structural setup layer intentionally stops at FAILED.  ACTIVE and
    COMPLETED are later trade-lifecycle concepts and are not represented here.
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


@dataclass(frozen=True)
class Setup01Evaluation:
    """Immutable SETUP_01 Wave 2 → Wave 3 structural snapshot.

    This model is deliberately separate from :class:`Setup`, whose public
    production behavior is SETUP_03 Platform Breakout.  It contains no entry,
    decision, target, execution-stop, or risk fields.
    """

    setup_type: str
    protocol_version: str
    state: SetupState
    as_of_date: date
    wave1_origin: Optional[SwingPoint]
    wave1_peak: Optional[SwingPoint]
    wave2_low: Optional[SwingPoint]
    fib_retracement_ratio: Optional[float]
    fib_retracement_region: Optional[str]
    confirmation_level: Optional[float]
    structural_invalidation: Optional[float]
    wave_scenario_invalidation: Optional[float]
    wave1_origin_confirmed_date: Optional[date]
    wave1_peak_confirmed_date: Optional[date]
    wave2_low_confirmed_date: Optional[date]
    state_entered_index: Optional[int]
    state_entered_date: Optional[date]
    confirmed_index: Optional[int]
    confirmed_date: Optional[date]
    failed_index: Optional[int]
    failed_date: Optional[date]
    primary_wave_scenario: str
    alternate_wave_scenario: str
    reason: str
    diagnostics: tuple[str, ...] = ()
    lifecycle_index: Optional[int] = None


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
    - probe_entry：试探入场价（= breakout_price）。
    - confirmation_entry：确认入场价（V1 简化 = breakout_price）。
    - confirmation_conditions：确认条件（文本描述）。
    """

    planned_entry: float
    entry_zone_low: float
    entry_zone_high: float
    probe_entry: float
    confirmation_entry: float
    confirmation_conditions: str


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

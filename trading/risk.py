"""Risk / Reward 与 Position Size。

- risk_reward() 使用 execution_stop 计算真实 R/R；Structural Invalidation 是
  独立概念（供后续 Setup/Decision 使用），不参与 R/R 计算。
- 必须先有独立得到的 Target 与 Invalidation（execution_stop），再计算赔率；
  禁止为满足 R/R 阈值倒推目标价。
- position_size() 输出 theoretical quantity / risk capital / max loss；
  手数、lot size 等 executable rounding 待市场元数据接入后再做。
"""
from __future__ import annotations

import math
from typing import Sequence

from trading.models import PositionSize, RiskReward

NO_TRADE = "NO_TRADE"
NORMAL = "NORMAL"
HIGH_QUALITY = "HIGH_QUALITY"
HIGH_ASYMMETRY = "HIGH_ASYMMETRY"

# This is the single source of truth for the gross T1 upside eligibility
# floor.  SETUP_01, SETUP_02, and their exact T+1 executors all reuse it.
MIN_TARGET_UPSIDE_PCT = 0.05
PREFERRED_TARGET_UPSIDE_PCT = 0.08
TARGET_UPSIDE_BAND_BELOW_MINIMUM = "BELOW_MINIMUM"
TARGET_UPSIDE_BAND_LOW = "LOW_UPSIDE"
TARGET_UPSIDE_BAND_PREFERRED = "PREFERRED_UPSIDE"


def rr_quality(rr: float) -> str:
    """R/R 质量分级：<2 NO_TRADE；2~3 NORMAL；3~5 HIGH_QUALITY；>5 HIGH_ASYMMETRY。"""
    if rr < 2:
        return NO_TRADE
    if rr < 3:
        return NORMAL
    if rr <= 5:
        return HIGH_QUALITY
    return HIGH_ASYMMETRY


def target_upside_pct(target: float, reference_entry_price: float) -> float:
    """Return gross upside from a positive reference price to a target."""

    target = float(target)
    reference_entry_price = float(reference_entry_price)
    if not math.isfinite(target) or not math.isfinite(reference_entry_price):
        raise ValueError("target and reference_entry_price must be finite")
    if reference_entry_price <= 0:
        raise ValueError("reference_entry_price must be positive")
    return (target - reference_entry_price) / reference_entry_price


def target_upside_band(value: float) -> str:
    """Classify gross T1 upside for presentation/research only."""

    value = float(value)
    if not math.isfinite(value):
        raise ValueError("target upside must be finite")
    if value < MIN_TARGET_UPSIDE_PCT:
        return TARGET_UPSIDE_BAND_BELOW_MINIMUM
    if value < PREFERRED_TARGET_UPSIDE_PCT:
        return TARGET_UPSIDE_BAND_LOW
    return TARGET_UPSIDE_BAND_PREFERRED


def relative_distance_pct(value: float, reference: float) -> float:
    """Return ``(value - reference) / reference`` for causal diagnostics."""

    value = float(value)
    reference = float(reference)
    if not math.isfinite(value) or not math.isfinite(reference):
        raise ValueError("value and reference must be finite")
    if reference == 0:
        raise ValueError("reference must be non-zero")
    return (value - reference) / reference


def risk_reward(
    entry: float,
    execution_stop: float,
    targets: Sequence[float],
) -> RiskReward:
    """计算多头/空头的 R/R。

    方向由 execution_stop 相对 entry 的位置推断：stop 在 entry 下方为多头。
    quality 以第一个 target（最近、最保守）的 R/R 判定。
    """
    if not targets:
        raise ValueError("targets 不能为空")
    risk_per_share = abs(entry - execution_stop)
    if risk_per_share <= 0:
        raise ValueError(f"execution_stop 不能等于 entry：{entry}")

    is_long = execution_stop < entry
    rr_ratios = []
    for target in targets:
        reward = (target - entry) if is_long else (entry - target)
        rr_ratios.append(reward / risk_per_share)

    return RiskReward(
        entry=entry,
        execution_stop=execution_stop,
        risk_per_share=risk_per_share,
        target_prices=tuple(targets),
        rr_ratios=tuple(rr_ratios),
        quality=rr_quality(rr_ratios[0]),
    )


def position_size(
    risk_capital: float,
    entry: float,
    execution_stop: float,
) -> PositionSize:
    """基于 1R 风险资本与 Execution Stop 计算理论仓位。

    theoretical_quantity = risk_capital / |entry - execution_stop|，不取整。
    """
    if risk_capital < 0:
        raise ValueError(f"risk_capital 不能为负：{risk_capital}")
    risk_per_share = abs(entry - execution_stop)
    if risk_per_share <= 0:
        raise ValueError(f"execution_stop 不能等于 entry：{entry}")

    theoretical_quantity = risk_capital / risk_per_share
    return PositionSize(
        risk_capital=risk_capital,
        entry=entry,
        execution_stop=execution_stop,
        risk_per_share=risk_per_share,
        theoretical_quantity=theoretical_quantity,
        max_loss=risk_capital,
    )

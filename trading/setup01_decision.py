"""Independent SETUP_01 Decision/Risk v1 evaluator.

This module consumes only first-entry ``Setup01ReplayEvent`` objects whose
event type is ``CONFIRMED``.  It is deliberately separate from the SETUP_03
``trading.decision`` path: no platform-breakout detector or decision function
is imported here.

The evaluator stops at a T-day plan and a read-only T+1-open feasibility
classification.  It never reads a T+1 high/low/close and it never reads or
calculates an outcome metric.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from typing import Iterable, Mapping, Sequence

from core import Quote
from trading.fibonacci import EXTENSION_RATIOS, project_extension
from trading.indicators import atr
from trading.models import (
    DecisionAction,
    PositionSize,
    RiskReward,
    SetupState,
    SwingKind,
    SwingPoint,
    validate_quote_series,
)
from trading.risk import HIGH_ASYMMETRY, NO_TRADE, position_size, risk_reward
from trading.setup01_replay import Setup01ReplayEvent
from trading.swing import find_swings


SETUP01_DECISION_PROTOCOL_VERSION = (
    "SETUP-01-DECISION-RISK-2026-08-30-v1"
)
SETUP01_ATR_PERIOD = 14
SETUP01_ENTRY_ZONE_ATR = 0.5
SETUP01_EXECUTION_STOP_ATR = 0.5
SETUP01_MINIMUM_RR = 2.0


class Setup01DecisionGateReason(str, Enum):
    """Stable T-day Decision gate reasons for the historical funnel."""

    ATR_UNAVAILABLE = "ATR_UNAVAILABLE"
    ABOVE_ENTRY_ZONE = "ABOVE_ENTRY_ZONE"
    NO_VALID_TARGET = "NO_VALID_TARGET"
    RR_BELOW_MINIMUM = "RR_BELOW_MINIMUM"
    INVALID_STRUCTURE = "INVALID_STRUCTURE"
    ENTRY_ALLOWED = "ENTRY_ALLOWED"


SKIP_GAP_BELOW_CONFIRMATION = "SKIP_GAP_BELOW_CONFIRMATION"
SKIP_GAP_ABOVE_ENTRY_ZONE = "SKIP_GAP_ABOVE_ENTRY_ZONE"
SKIP_BELOW_INVALIDATION = "SKIP_BELOW_INVALIDATION"
SKIP_NO_T1_BAR = "SKIP_NO_T1_BAR"
SKIP_DECISION_NOT_ENTRY_ALLOWED = "SKIP_DECISION_NOT_ENTRY_ALLOWED"
EXECUTED = "EXECUTED"


@dataclass(frozen=True)
class Setup01TargetCandidate:
    price: float
    source: str
    reason: str


@dataclass(frozen=True)
class Setup01Decision:
    protocol_version: str
    event_identity: str
    symbol: str
    market: str
    trade_date: date
    event_type: SetupState
    decision_calculable: bool
    action: DecisionAction
    gate_reason: str
    gate_detail: str
    atr14: float | None
    wave1_origin: float | None
    confirmation_level: float | None
    planned_entry: float | None
    entry_zone_low: float | None
    entry_zone_high: float | None
    structural_invalidation: float | None
    wave_scenario_invalidation: float | None
    execution_stop: float | None
    target_candidates: tuple[Setup01TargetCandidate, ...]
    targets: tuple[float, ...]
    target_reasonableness_checked: bool
    target_reasonableness_passed: bool | None
    rr: RiskReward | None
    position_size: PositionSize | None
    position_size_required_input: str | None


@dataclass(frozen=True)
class Setup01Execution:
    event_identity: str
    symbol: str
    market: str
    trade_date: date
    execution_date: date | None
    t1_open: float | None
    attempted: bool
    outcome: str
    actual_entry: float | None


@dataclass(frozen=True)
class Setup01DecisionStream:
    decisions: tuple[Setup01Decision, ...]
    executions: tuple[Setup01Execution, ...]
    duplicate_event_count: int = 0
    ignored_non_confirmed_event_count: int = 0


def _empty_decision(
    event: Setup01ReplayEvent,
    *,
    decision_calculable: bool,
    gate_reason: str,
    gate_detail: str,
    atr14: float | None = None,
    wave1_origin: float | None = None,
    confirmation_level: float | None = None,
    planned_entry: float | None = None,
    entry_zone_low: float | None = None,
    entry_zone_high: float | None = None,
    structural_invalidation: float | None = None,
    wave_scenario_invalidation: float | None = None,
    execution_stop: float | None = None,
    target_candidates: tuple[Setup01TargetCandidate, ...] = (),
    targets: tuple[float, ...] = (),
    target_reasonableness_checked: bool = False,
    target_reasonableness_passed: bool | None = None,
    rr: RiskReward | None = None,
    position_size_result: PositionSize | None = None,
    position_size_required_input: str | None = None,
) -> Setup01Decision:
    return Setup01Decision(
        protocol_version=SETUP01_DECISION_PROTOCOL_VERSION,
        event_identity=event.event_identity,
        symbol=event.symbol,
        market=_event_market(event),
        trade_date=event.trade_date,
        event_type=event.event_type,
        decision_calculable=decision_calculable,
        action=(
            DecisionAction.ENTRY_ALLOWED
            if gate_reason == Setup01DecisionGateReason.ENTRY_ALLOWED
            else DecisionAction.NO_TRADE
        ),
        gate_reason=gate_reason,
        gate_detail=gate_detail,
        atr14=atr14,
        wave1_origin=wave1_origin,
        confirmation_level=confirmation_level,
        planned_entry=planned_entry,
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        structural_invalidation=structural_invalidation,
        wave_scenario_invalidation=wave_scenario_invalidation,
        execution_stop=execution_stop,
        target_candidates=target_candidates,
        targets=targets,
        target_reasonableness_checked=target_reasonableness_checked,
        target_reasonableness_passed=target_reasonableness_passed,
        rr=rr,
        position_size=position_size_result,
        position_size_required_input=position_size_required_input,
    )


def _event_market(event: Setup01ReplayEvent) -> str:
    """Read market from the replay event without new data access."""
    return str(event.market)


def _validated_event(event: Setup01ReplayEvent) -> None:
    if event.event_type is not SetupState.CONFIRMED:
        raise ValueError("SETUP_01 Decision 只消费 CONFIRMED event")
    snapshot = event.setup01
    if not snapshot.is_new_confirmed_event_as_of:
        raise ValueError(
            "历史 terminal CONFIRMED 不是当前 as-of 的新 CONFIRMED event"
        )
    if snapshot.confirmed_date != event.trade_date:
        raise ValueError("CONFIRMED event date 与 snapshot.confirmed_date 不一致")
    if snapshot.as_of_date != event.trade_date:
        raise ValueError("CONFIRMED event 的 as-of date 必须等于 event T date")


def _prefix_at_event(event: Setup01ReplayEvent, quotes: Sequence[Quote]) -> list[Quote]:
    validate_quote_series(list(quotes))
    if quotes[0].symbol != event.symbol:
        raise ValueError("event symbol 与 quote symbol 不一致")
    prefix = [quote for quote in quotes if quote.trade_date <= event.trade_date]
    if not prefix or prefix[-1].trade_date != event.trade_date:
        raise ValueError("quotes 缺少 event T 日，不能形成严格 as-of 前缀")
    return prefix


def _target_candidates(
    prefix: list[Quote],
    *,
    origin: SwingPoint,
    peak: SwingPoint,
    wave2_low: SwingPoint,
    entry: float,
    swing_lookback: int,
) -> tuple[Setup01TargetCandidate, ...]:
    """Build all T-known targets, then let the caller select T1/T2/T3."""
    candidates: list[Setup01TargetCandidate] = []
    swings = find_swings(prefix, lookback=swing_lookback)
    event_index = len(prefix) - 1
    for swing in swings:
        if (
            swing.kind is SwingKind.HIGH
            and swing.confirmed_index is not None
            and swing.confirmed_index <= event_index
            and swing.price > entry
        ):
            candidates.append(
                Setup01TargetCandidate(
                    price=float(swing.price),
                    source="CONFIRMED_SWING_HIGH",
                    reason=(
                        "T-known confirmed swing high at "
                        f"{swing.pivot_date.isoformat()}"
                    ),
                )
            )

    reference_range = peak.price - origin.price
    if reference_range <= 0:
        return tuple(candidates)
    for ratio_name, ratio in EXTENSION_RATIOS.items():
        projection = project_extension(
            wave2_low.price,
            origin.price,
            peak.price,
            ratio,
        )
        if projection > entry and math.isfinite(projection):
            candidates.append(
                Setup01TargetCandidate(
                    price=float(projection),
                    source="WAVE3_FIB_EXTENSION",
                    reason=(
                        "Wave2 low + (Wave1 peak - Wave1 origin) * "
                        f"existing extension {ratio_name}"
                    ),
                )
            )

    # A price is one target even when a prior high and a projection coincide;
    # retain both explanations in the single candidate's audit reason.
    by_price: dict[float, list[Setup01TargetCandidate]] = {}
    for candidate in candidates:
        by_price.setdefault(candidate.price, []).append(candidate)
    merged: list[Setup01TargetCandidate] = []
    for price, same_price in by_price.items():
        merged.append(
            Setup01TargetCandidate(
                price=price,
                source="+".join(sorted({item.source for item in same_price})),
                reason="; ".join(item.reason for item in same_price),
            )
        )
    return tuple(sorted(merged, key=lambda item: (item.price, item.source)))


def _targets_are_reasonable(
    candidates: Sequence[Setup01TargetCandidate],
    *,
    entry: float,
    origin: float,
    peak: float,
    wave2_low: float,
) -> bool:
    """Sanity-check generated target sources for the >5R branch.

    This is a provenance/geometry check, not an outcome-based target filter.
    """
    if peak <= origin or wave2_low <= origin or wave2_low >= peak:
        return False
    return all(
        math.isfinite(candidate.price)
        and candidate.price > entry
        and candidate.source
        for candidate in candidates
    )


def evaluate_setup01_decision(
    event: Setup01ReplayEvent,
    quotes: Sequence[Quote],
    *,
    risk_capital: float | None = None,
    swing_lookback: int = 5,
    atr_period: int = SETUP01_ATR_PERIOD,
) -> Setup01Decision:
    """Calculate one T-day SETUP_01 Decision/Risk plan, strictly as of T."""
    _validated_event(event)
    prefix = _prefix_at_event(event, quotes)
    snapshot = event.setup01
    origin_swing = snapshot.wave1_origin
    peak_swing = snapshot.wave1_peak
    wave2_swing = snapshot.wave2_low
    if (
        origin_swing is None
        or peak_swing is None
        or wave2_swing is None
        or snapshot.confirmation_level is None
        or snapshot.structural_invalidation is None
        or snapshot.wave_scenario_invalidation is None
    ):
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup01DecisionGateReason.INVALID_STRUCTURE,
            gate_detail="CONFIRMED event 缺少完整 Wave1/Wave2 structural fields",
        )

    origin = float(origin_swing.price)
    peak = float(peak_swing.price)
    wave2_low = float(wave2_swing.price)
    confirmation_level = float(snapshot.confirmation_level)
    structural_invalidation = float(snapshot.structural_invalidation)
    wave_scenario_invalidation = float(snapshot.wave_scenario_invalidation)
    planned_entry = float(prefix[-1].close)
    if not (
        origin < wave2_low < peak
        and confirmation_level == peak
        and structural_invalidation == wave2_low
        and wave_scenario_invalidation == origin
        and planned_entry > confirmation_level
    ):
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup01DecisionGateReason.INVALID_STRUCTURE,
            gate_detail="SETUP_01 Wave1/Wave2/confirmation fields fail structural invariants",
            wave1_origin=origin,
            confirmation_level=confirmation_level,
            planned_entry=planned_entry,
            structural_invalidation=structural_invalidation,
            wave_scenario_invalidation=wave_scenario_invalidation,
        )

    if atr_period <= 0:
        raise ValueError("atr_period 必须为正整数")
    atr_value = atr(prefix, atr_period)[-1]
    if atr_value is None or not math.isfinite(float(atr_value)) or float(atr_value) <= 0:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup01DecisionGateReason.ATR_UNAVAILABLE,
            gate_detail="T 日 as-of Wilder ATR14 尚未 available",
            atr14=atr_value,
            wave1_origin=origin,
            confirmation_level=confirmation_level,
            planned_entry=planned_entry,
            entry_zone_low=confirmation_level,
            structural_invalidation=structural_invalidation,
            wave_scenario_invalidation=wave_scenario_invalidation,
        )
    atr14 = float(atr_value)
    entry_zone_low = confirmation_level
    entry_zone_high = confirmation_level + SETUP01_ENTRY_ZONE_ATR * atr14
    execution_stop = (
        structural_invalidation - SETUP01_EXECUTION_STOP_ATR * atr14
    )

    common = dict(
        atr14=atr14,
        wave1_origin=origin,
        confirmation_level=confirmation_level,
        planned_entry=planned_entry,
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        structural_invalidation=structural_invalidation,
        wave_scenario_invalidation=wave_scenario_invalidation,
        execution_stop=execution_stop,
    )
    if planned_entry > entry_zone_high:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup01DecisionGateReason.ABOVE_ENTRY_ZONE,
            gate_detail="T close 已高于 confirmation + 0.5 * ATR14 entry zone",
            **common,
        )

    candidates = _target_candidates(
        prefix,
        origin=origin_swing,
        peak=peak_swing,
        wave2_low=wave2_swing,
        entry=planned_entry,
        swing_lookback=swing_lookback,
    )
    targets = tuple(candidate.price for candidate in candidates[:3])
    if not targets:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup01DecisionGateReason.NO_VALID_TARGET,
            gate_detail="T 日没有高于 planned_entry 的有效前高或 canonical extension target",
            target_candidates=candidates,
            targets=targets,
            **common,
        )

    rr = risk_reward(planned_entry, execution_stop, targets)
    target_reasonableness_checked = rr.quality == HIGH_ASYMMETRY
    target_reasonableness_passed: bool | None = None
    if target_reasonableness_checked:
        target_reasonableness_passed = _targets_are_reasonable(
            candidates,
            entry=planned_entry,
            origin=origin,
            peak=peak,
            wave2_low=wave2_low,
        )
        if not target_reasonableness_passed:
            return _empty_decision(
                event,
                decision_calculable=True,
                gate_reason=Setup01DecisionGateReason.NO_VALID_TARGET,
                gate_detail=">5R target 未通过 provenance/geometry reasonableness check",
                target_candidates=candidates,
                targets=targets,
                target_reasonableness_checked=True,
                target_reasonableness_passed=False,
                rr=rr,
                **common,
            )

    if rr.quality == NO_TRADE or rr.rr_ratios[0] < SETUP01_MINIMUM_RR:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup01DecisionGateReason.RR_BELOW_MINIMUM,
            gate_detail="T1 first target R/R < 2；Target 先于 R/R 生成",
            target_candidates=candidates,
            targets=targets,
            target_reasonableness_checked=target_reasonableness_checked,
            target_reasonableness_passed=target_reasonableness_passed,
            rr=rr,
            **common,
        )

    size = None
    required_input = None
    if risk_capital is None:
        required_input = "risk_capital"
    else:
        size = position_size(risk_capital, planned_entry, execution_stop)
    return _empty_decision(
        event,
        decision_calculable=True,
        gate_reason=Setup01DecisionGateReason.ENTRY_ALLOWED,
        gate_detail="T close confirmed；plan earliest execution at T+1 OPEN",
        target_candidates=candidates,
        targets=targets,
        target_reasonableness_checked=target_reasonableness_checked,
        target_reasonableness_passed=target_reasonableness_passed,
        rr=rr,
        position_size_result=size,
        position_size_required_input=required_input,
        **common,
    )


def execute_setup01_t1_open(
    decision: Setup01Decision,
    quotes: Sequence[Quote],
) -> Setup01Execution:
    """Classify only the first observed bar after T using its OPEN."""
    validate_quote_series(list(quotes))
    if decision.action is not DecisionAction.ENTRY_ALLOWED:
        return Setup01Execution(
            event_identity=decision.event_identity,
            symbol=decision.symbol,
            market=decision.market,
            trade_date=decision.trade_date,
            execution_date=None,
            t1_open=None,
            attempted=False,
            outcome=SKIP_DECISION_NOT_ENTRY_ALLOWED,
            actual_entry=None,
        )
    next_bars = [quote for quote in quotes if quote.trade_date > decision.trade_date]
    if not next_bars:
        return Setup01Execution(
            event_identity=decision.event_identity,
            symbol=decision.symbol,
            market=decision.market,
            trade_date=decision.trade_date,
            execution_date=None,
            t1_open=None,
            attempted=True,
            outcome=SKIP_NO_T1_BAR,
            actual_entry=None,
        )

    t1 = next_bars[0]
    opening = float(t1.open)
    assert decision.entry_zone_low is not None
    assert decision.entry_zone_high is not None
    assert decision.structural_invalidation is not None
    if opening <= decision.structural_invalidation:
        outcome = SKIP_BELOW_INVALIDATION
        actual_entry = None
    elif opening < decision.entry_zone_low:
        outcome = SKIP_GAP_BELOW_CONFIRMATION
        actual_entry = None
    elif opening > decision.entry_zone_high:
        outcome = SKIP_GAP_ABOVE_ENTRY_ZONE
        actual_entry = None
    else:
        outcome = EXECUTED
        actual_entry = opening
    return Setup01Execution(
        event_identity=decision.event_identity,
        symbol=decision.symbol,
        market=decision.market,
        trade_date=decision.trade_date,
        execution_date=t1.trade_date,
        t1_open=opening,
        attempted=True,
        outcome=outcome,
        actual_entry=actual_entry,
    )


def evaluate_setup01_decision_stream(
    events: Iterable[Setup01ReplayEvent],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    *,
    risk_capital: float | None = None,
    swing_lookback: int = 5,
    atr_period: int = SETUP01_ATR_PERIOD,
) -> Setup01DecisionStream:
    """Evaluate a confirmed event stream with event-identity exactly-once."""
    seen: set[str] = set()
    decisions: list[Setup01Decision] = []
    executions: list[Setup01Execution] = []
    duplicate_count = 0
    ignored_count = 0
    for event in events:
        if event.event_identity in seen:
            duplicate_count += 1
            continue
        seen.add(event.event_identity)
        if event.event_type is not SetupState.CONFIRMED:
            ignored_count += 1
            continue
        if (
            not event.setup01.is_new_confirmed_event_as_of
            or event.setup01.confirmed_date != event.trade_date
            or event.setup01.as_of_date != event.trade_date
        ):
            # A persistent terminal snapshot is historical state, not a new
            # Decision input.  Keep it out of the decision rows entirely.
            ignored_count += 1
            continue
        try:
            decision = evaluate_setup01_decision(
                event,
                quotes_by_symbol[event.symbol],
                risk_capital=risk_capital,
                swing_lookback=swing_lookback,
                atr_period=atr_period,
            )
        except (KeyError, ValueError) as exc:
            decision = _empty_decision(
                event,
                decision_calculable=False,
                gate_reason=Setup01DecisionGateReason.INVALID_STRUCTURE,
                gate_detail=str(exc),
            )
        decisions.append(decision)
        if decision.action is DecisionAction.ENTRY_ALLOWED:
            executions.append(
                execute_setup01_t1_open(decision, quotes_by_symbol[event.symbol])
            )
    return Setup01DecisionStream(
        decisions=tuple(decisions),
        executions=tuple(executions),
        duplicate_event_count=duplicate_count,
        ignored_non_confirmed_event_count=ignored_count,
    )


def _target_to_dict(candidate: Setup01TargetCandidate) -> dict:
    return {
        "price": candidate.price,
        "source": candidate.source,
        "reason": candidate.reason,
    }


def _rr_to_dict(value: RiskReward | None) -> dict | None:
    if value is None:
        return None
    return {
        "entry": value.entry,
        "execution_stop": value.execution_stop,
        "risk_per_share": value.risk_per_share,
        "target_prices": list(value.target_prices),
        "rr_ratios": list(value.rr_ratios),
        "quality": value.quality,
    }


def _position_to_dict(value: PositionSize | None) -> dict | None:
    if value is None:
        return None
    return {
        "risk_capital": value.risk_capital,
        "entry": value.entry,
        "execution_stop": value.execution_stop,
        "risk_per_share": value.risk_per_share,
        "theoretical_quantity": value.theoretical_quantity,
        "max_loss": value.max_loss,
    }


def setup01_decision_to_dict(value: Setup01Decision) -> dict:
    return {
        "protocol_version": value.protocol_version,
        "event_identity": value.event_identity,
        "symbol": value.symbol,
        "market": value.market,
        "trade_date": value.trade_date.isoformat(),
        "event_type": value.event_type.value,
        "decision_calculable": value.decision_calculable,
        "action": value.action.value,
        "gate_reason": getattr(value.gate_reason, "value", value.gate_reason),
        "gate_detail": value.gate_detail,
        "atr14": value.atr14,
        "wave1_origin": value.wave1_origin,
        "confirmation_level": value.confirmation_level,
        "planned_entry": value.planned_entry,
        "entry_zone_low": value.entry_zone_low,
        "entry_zone_high": value.entry_zone_high,
        "structural_invalidation": value.structural_invalidation,
        "wave_scenario_invalidation": value.wave_scenario_invalidation,
        "execution_stop": value.execution_stop,
        "target_candidates": [_target_to_dict(item) for item in value.target_candidates],
        "targets": list(value.targets),
        "T1": value.targets[0] if len(value.targets) > 0 else None,
        "T2": value.targets[1] if len(value.targets) > 1 else None,
        "T3": value.targets[2] if len(value.targets) > 2 else None,
        "target_reasonableness_checked": value.target_reasonableness_checked,
        "target_reasonableness_passed": value.target_reasonableness_passed,
        "rr": _rr_to_dict(value.rr),
        "position_size": _position_to_dict(value.position_size),
        "position_size_required_input": value.position_size_required_input,
    }


def setup01_execution_to_dict(value: Setup01Execution) -> dict:
    return {
        "event_identity": value.event_identity,
        "symbol": value.symbol,
        "market": value.market,
        "trade_date": value.trade_date.isoformat(),
        "execution_date": (
            value.execution_date.isoformat() if value.execution_date else None
        ),
        "t1_open": value.t1_open,
        "attempted": value.attempted,
        "outcome": value.outcome,
        "actual_entry": value.actual_entry,
    }


__all__ = [
    "EXECUTED",
    "SETUP01_ATR_PERIOD",
    "SETUP01_DECISION_PROTOCOL_VERSION",
    "SETUP01_ENTRY_ZONE_ATR",
    "SETUP01_EXECUTION_STOP_ATR",
    "SKIP_BELOW_INVALIDATION",
    "SKIP_DECISION_NOT_ENTRY_ALLOWED",
    "SKIP_GAP_ABOVE_ENTRY_ZONE",
    "SKIP_GAP_BELOW_CONFIRMATION",
    "SKIP_NO_T1_BAR",
    "Setup01Decision",
    "Setup01DecisionGateReason",
    "Setup01DecisionStream",
    "Setup01Execution",
    "Setup01TargetCandidate",
    "evaluate_setup01_decision",
    "evaluate_setup01_decision_stream",
    "execute_setup01_t1_open",
    "setup01_decision_to_dict",
    "setup01_execution_to_dict",
]

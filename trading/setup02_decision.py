"""Independent SETUP_02 Decision/Risk v1 evaluator.

The module consumes only first-entry SETUP_02 ``CONFIRMED`` events.  The
structural invalidation and continuation HIGH3 are copied from the event; the
module does not re-run or mutate the structural lifecycle.  A T-day plan is
formed from the causal quote prefix and, when allowed, only the exact next
market-session OPEN is used for the execution classification.

No outcome, return, holdings, broker, account, or production-calendar path is
present here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from typing import Iterable, Mapping, Sequence

from core import Quote
from research.market_sessions import build_market_session_dates
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
from trading.setup02_replay import Setup02ReplayEvent
from trading.swing import find_swings


SETUP02_DECISION_PROTOCOL_VERSION = "SETUP-02-DECISION-RISK-2026-09-02-v2"
SETUP02_ATR_PERIOD = 14
SETUP02_ENTRY_ZONE_ATR = 0.5
SETUP02_EXECUTION_STOP_ATR = 0.5
SETUP02_MINIMUM_RR = 2.0


class Setup02DecisionGateReason(str, Enum):
    """Stable T-day Decision gate reasons."""

    ATR_UNAVAILABLE = "ATR_UNAVAILABLE"
    ABOVE_ENTRY_ZONE = "ABOVE_ENTRY_ZONE"
    NO_VALID_TARGET = "NO_VALID_TARGET"
    RR_BELOW_MINIMUM = "RR_BELOW_MINIMUM"
    STALE_CONFIRMATION_GEOMETRY = "STALE_CONFIRMATION_GEOMETRY"
    INVALID_STRUCTURE = "INVALID_STRUCTURE"
    ENTRY_ALLOWED = "ENTRY_ALLOWED"


SKIP_GAP_BELOW_CONFIRMATION = "SKIP_GAP_BELOW_CONFIRMATION"
SKIP_GAP_ABOVE_ENTRY_ZONE = "SKIP_GAP_ABOVE_ENTRY_ZONE"
SKIP_BELOW_INVALIDATION = "SKIP_BELOW_INVALIDATION"
SKIP_NO_T1_BAR = "SKIP_NO_T1_BAR"
SKIP_RR_BELOW_MINIMUM_AT_OPEN = "SKIP_RR_BELOW_MINIMUM_AT_OPEN"
SKIP_DECISION_NOT_ENTRY_ALLOWED = "SKIP_DECISION_NOT_ENTRY_ALLOWED"
EXECUTED = "EXECUTED"


@dataclass(frozen=True)
class Setup02TargetProvenance:
    """Machine-readable provenance for one T-known target explanation."""

    source: str
    pivot_date: date | None = None
    confirmed_date: date | None = None
    extension_ratio: float | None = None
    wave1_origin_price: float | None = None
    wave1_peak_price: float | None = None
    wave2_low_price: float | None = None
    formula_identity: str | None = None


@dataclass(frozen=True)
class Setup02TargetCandidate:
    price: float
    source: str
    reason: str
    provenance: tuple[Setup02TargetProvenance, ...] = ()


@dataclass(frozen=True)
class Setup02Decision:
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
    continuation_low0: SwingPoint | None
    continuation_high1: SwingPoint | None
    continuation_low2: SwingPoint | None
    continuation_high3: SwingPoint | None
    confirmation_level: float | None
    planned_entry: float | None
    entry_zone_low: float | None
    entry_zone_high: float | None
    structural_invalidation: float | None
    execution_stop: float | None
    wave1_length: float | None
    target_candidates: tuple[Setup02TargetCandidate, ...]
    targets: tuple[float, ...]
    target_reasonableness_checked: bool
    target_reasonableness_passed: bool | None
    rr: RiskReward | None
    position_size: PositionSize | None
    position_size_required_input: str | None


@dataclass(frozen=True)
class Setup02Execution:
    event_identity: str
    symbol: str
    market: str
    trade_date: date
    execution_date: date | None
    t1_open: float | None
    attempted: bool
    outcome: str
    actual_entry: float | None
    actual_rr: RiskReward | None = None

    def __post_init__(self) -> None:
        if (self.actual_entry is not None) != (self.outcome == EXECUTED):
            raise ValueError(
                "actual_entry must be present if and only if outcome is EXECUTED"
            )


@dataclass(frozen=True)
class Setup02DecisionStream:
    decisions: tuple[Setup02Decision, ...]
    executions: tuple[Setup02Execution, ...]
    duplicate_event_count: int = 0
    ignored_non_confirmed_event_count: int = 0


def _empty_decision(
    event: Setup02ReplayEvent,
    *,
    decision_calculable: bool,
    gate_reason: str,
    gate_detail: str,
    atr14: float | None = None,
    continuation_low0: SwingPoint | None = None,
    continuation_high1: SwingPoint | None = None,
    continuation_low2: SwingPoint | None = None,
    continuation_high3: SwingPoint | None = None,
    confirmation_level: float | None = None,
    planned_entry: float | None = None,
    entry_zone_low: float | None = None,
    entry_zone_high: float | None = None,
    structural_invalidation: float | None = None,
    execution_stop: float | None = None,
    wave1_length: float | None = None,
    target_candidates: tuple[Setup02TargetCandidate, ...] = (),
    targets: tuple[float, ...] = (),
    target_reasonableness_checked: bool = False,
    target_reasonableness_passed: bool | None = None,
    rr: RiskReward | None = None,
    position_size_result: PositionSize | None = None,
    position_size_required_input: str | None = None,
) -> Setup02Decision:
    return Setup02Decision(
        protocol_version=SETUP02_DECISION_PROTOCOL_VERSION,
        event_identity=event.event_identity,
        symbol=event.symbol,
        market=str(event.market),
        trade_date=event.trade_date,
        event_type=event.event_type,
        decision_calculable=decision_calculable,
        action=(
            DecisionAction.ENTRY_ALLOWED
            if gate_reason == Setup02DecisionGateReason.ENTRY_ALLOWED
            else DecisionAction.NO_TRADE
        ),
        gate_reason=gate_reason,
        gate_detail=gate_detail,
        atr14=atr14,
        continuation_low0=continuation_low0,
        continuation_high1=continuation_high1,
        continuation_low2=continuation_low2,
        continuation_high3=continuation_high3,
        confirmation_level=confirmation_level,
        planned_entry=planned_entry,
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        structural_invalidation=structural_invalidation,
        execution_stop=execution_stop,
        wave1_length=wave1_length,
        target_candidates=target_candidates,
        targets=targets,
        target_reasonableness_checked=target_reasonableness_checked,
        target_reasonableness_passed=target_reasonableness_passed,
        rr=rr,
        position_size=position_size_result,
        position_size_required_input=position_size_required_input,
    )


def _validated_event(event: Setup02ReplayEvent) -> None:
    if event.event_type is not SetupState.CONFIRMED:
        raise ValueError("SETUP_02 Decision 只消费 CONFIRMED event")
    snapshot = event.setup02
    if not snapshot.is_new_confirmed_event_as_of:
        raise ValueError(
            "历史 terminal CONFIRMED 不是当前 as-of 的新 CONFIRMED event"
        )
    if snapshot.confirmed_date != event.trade_date:
        raise ValueError("CONFIRMED event date 与 snapshot.confirmed_date 不一致")
    if snapshot.as_of_date != event.trade_date:
        raise ValueError("CONFIRMED event 的 as-of date 必须等于 event T date")


def _prefix_at_event(event: Setup02ReplayEvent, quotes: Sequence[Quote]) -> list[Quote]:
    if not quotes:
        raise ValueError("quotes 为空，不能形成严格 as-of 前缀")
    if quotes[0].symbol != event.symbol:
        raise ValueError("event symbol 与 quote symbol 不一致")
    prefix = [quote for quote in quotes if quote.trade_date <= event.trade_date]
    if not prefix or prefix[-1].trade_date != event.trade_date:
        raise ValueError("quotes 缺少 event T 日，不能形成严格 as-of 前缀")
    # Only the causal prefix is validated and later bars are not inspected.
    validate_quote_series(prefix)
    return prefix


def _structure_fields(
    event: Setup02ReplayEvent, prefix: Sequence[Quote]
) -> tuple[
    SwingPoint,
    SwingPoint,
    SwingPoint,
    SwingPoint,
    float,
    float,
]:
    snapshot = event.setup02
    low0 = snapshot.continuation_low0
    high1 = snapshot.continuation_high1
    low2 = snapshot.continuation_low2
    high3 = snapshot.continuation_high3
    confirmation_level = snapshot.confirmation_level
    structural_invalidation = snapshot.structural_invalidation
    required = (low0, high1, low2, high3)
    if any(item is None for item in required):
        raise ValueError("CONFIRMED event 缺少 LOW0/HIGH1/LOW2/HIGH3")
    if confirmation_level is None or structural_invalidation is None:
        raise ValueError("CONFIRMED event 缺少 confirmation/invalidation")
    assert low0 is not None and high1 is not None
    assert low2 is not None and high3 is not None
    values = (
        low0.price,
        high1.price,
        low2.price,
        high3.price,
        confirmation_level,
        structural_invalidation,
        prefix[-1].close,
    )
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("SETUP_02 structural fields must be finite")
    if not all(
        item.confirmed_index is not None
        and item.confirmed_date is not None
        and item.pivot_index <= len(prefix) - 1
        and item.confirmed_index <= len(prefix) - 1
        and item.pivot_date <= event.trade_date
        and item.confirmed_date <= event.trade_date
        for item in required
    ):
        raise ValueError("CONFIRMED event contains a future or unconfirmed swing")
    return (
        low0,
        high1,
        low2,
        high3,
        float(confirmation_level),
        float(structural_invalidation),
    )


def _structure_invariant_failures(
    low0: SwingPoint,
    high1: SwingPoint,
    low2: SwingPoint,
    high3: SwingPoint,
    confirmation_level: float,
    structural_invalidation: float,
    t_close: float,
) -> tuple[str, ...]:
    """Return deterministic Decision-layer checks without changing structure."""
    failures: list[str] = []
    # This check has priority because an invalidation at/above the old HIGH3
    # makes that confirmation geometry stale for a new Decision plan.
    if structural_invalidation >= high3.price:
        failures.append(
            "STALE_CONFIRMATION_GEOMETRY: structural_invalidation >= HIGH3"
        )
    if not (
        low0.kind is SwingKind.LOW
        and high1.kind is SwingKind.HIGH
        and low2.kind is SwingKind.LOW
        and high3.kind is SwingKind.HIGH
        and low0.pivot_index < high1.pivot_index < low2.pivot_index < high3.pivot_index
    ):
        failures.append("INVALID_SWING_KINDS_OR_ORDER")
    if high3.price <= high1.price:
        failures.append("HIGH3_NOT_ABOVE_HIGH1")
    if low2.price <= low0.price:
        failures.append("LOW2_NOT_ABOVE_LOW0")
    if high3.price != confirmation_level:
        failures.append("CONFIRMATION_LEVEL_NOT_HIGH3")
    if t_close <= confirmation_level:
        failures.append("T_CLOSE_NOT_ABOVE_CONFIRMATION")
    return tuple(failures)


def setup02_structure_geometry_audit(
    event: Setup02ReplayEvent,
    quotes: Sequence[Quote],
) -> dict:
    """Audit the causal structural fields consumed by the Decision layer.

    This is a structure/geometry audit only.  It reads the event fields and
    the T-day quote prefix, and never reads any later bar or outcome field.
    """
    _validated_event(event)
    row = {
        "event_identity": event.event_identity,
        "symbol": event.symbol,
        "market": str(event.market),
        "trade_date": event.trade_date.isoformat(),
        "LOW0": None,
        "HIGH1": None,
        "LOW2": None,
        "HIGH3": None,
        "confirmation_level": None,
        "structural_invalidation": None,
        "t_close": None,
        "failure_reasons": [],
        "exact_invariant_failure_reason": "UNAVAILABLE_STRUCTURE_FIELDS",
        "classification": "INVALID_STRUCTURE",
    }
    try:
        prefix = _prefix_at_event(event, quotes)
        fields = _structure_fields(event, prefix)
    except ValueError as exc:
        row["failure_reasons"] = [str(exc)]
        row["exact_invariant_failure_reason"] = str(exc)
        return row

    low0, high1, low2, high3, confirmation_level, structural_invalidation = fields
    t_close = float(prefix[-1].close)
    failures = _structure_invariant_failures(
        low0,
        high1,
        low2,
        high3,
        confirmation_level,
        structural_invalidation,
        t_close,
    )
    row.update(
        {
            "LOW0": _swing_to_dict(low0),
            "HIGH1": _swing_to_dict(high1),
            "LOW2": _swing_to_dict(low2),
            "HIGH3": _swing_to_dict(high3),
            "confirmation_level": confirmation_level,
            "structural_invalidation": structural_invalidation,
            "t_close": t_close,
            "failure_reasons": list(failures),
            "exact_invariant_failure_reason": failures[0] if failures else "NONE",
            "classification": (
                "STALE_CONFIRMATION_GEOMETRY"
                if failures and failures[0].startswith("STALE_CONFIRMATION_GEOMETRY")
                else "INVALID_STRUCTURE"
                if failures
                else "VALID"
            ),
        }
    )
    return row


def _target_candidates(
    prefix: Sequence[Quote],
    *,
    low0: SwingPoint,
    high1: SwingPoint,
    low2: SwingPoint,
    entry: float,
    swing_lookback: int,
) -> tuple[Setup02TargetCandidate, ...]:
    """Generate all legal T-known candidates before calculating R/R."""
    candidates: list[Setup02TargetCandidate] = []
    event_index = len(prefix) - 1
    for swing in find_swings(list(prefix), lookback=swing_lookback):
        if (
            swing.kind is SwingKind.HIGH
            and swing.confirmed_index is not None
            and swing.confirmed_date is not None
            and swing.confirmed_index <= event_index
            and swing.pivot_index <= event_index
            and swing.pivot_date <= prefix[-1].trade_date
            and swing.confirmed_date <= prefix[-1].trade_date
            and math.isfinite(float(swing.price))
            and swing.price > entry
        ):
            candidates.append(
                Setup02TargetCandidate(
                    price=float(swing.price),
                    source="CONFIRMED_SWING_HIGH",
                    reason=(
                        "T-known confirmed swing high at "
                        f"{swing.pivot_date.isoformat()}"
                    ),
                    provenance=(
                        Setup02TargetProvenance(
                            source="CONFIRMED_SWING_HIGH",
                            pivot_date=swing.pivot_date,
                            confirmed_date=swing.confirmed_date,
                        ),
                    ),
                )
            )

    wave1_length = high1.price - low0.price
    if wave1_length > 0 and math.isfinite(float(wave1_length)):
        for ratio_name, ratio in EXTENSION_RATIOS.items():
            target = project_extension(
                low2.price,
                low0.price,
                high1.price,
                float(ratio),
            )
            if math.isfinite(float(target)) and target > entry:
                candidates.append(
                    Setup02TargetCandidate(
                        price=float(target),
                        source="WAVE3_FIB_EXTENSION",
                        reason=(
                            "LOW2 + (HIGH1 - LOW0) * existing extension "
                            f"{ratio_name}"
                        ),
                        provenance=(
                            Setup02TargetProvenance(
                                source="WAVE3_FIB_EXTENSION",
                                extension_ratio=float(ratio),
                                wave1_origin_price=float(low0.price),
                                wave1_peak_price=float(high1.price),
                                wave2_low_price=float(low2.price),
                                formula_identity=(
                                    "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO"
                                ),
                            ),
                        ),
                    )
                )

    by_price: dict[float, list[Setup02TargetCandidate]] = {}
    for candidate in candidates:
        by_price.setdefault(candidate.price, []).append(candidate)
    merged: list[Setup02TargetCandidate] = []
    for price, same_price in by_price.items():
        provenance = tuple(
            sorted(
                {
                    item
                    for candidate in same_price
                    for item in candidate.provenance
                },
                key=lambda item: (
                    item.source,
                    item.pivot_date or date.min,
                    item.confirmed_date or date.min,
                    item.extension_ratio
                    if item.extension_ratio is not None
                    else -math.inf,
                    item.wave1_origin_price
                    if item.wave1_origin_price is not None
                    else -math.inf,
                ),
            )
        )
        merged.append(
            Setup02TargetCandidate(
                price=price,
                source="+".join(sorted({item.source for item in provenance})),
                reason="; ".join(item.reason for item in same_price),
                provenance=provenance,
            )
        )
    return tuple(sorted(merged, key=lambda item: (item.price, item.source)))


def _target_provenance_is_valid(
    candidate: Setup02TargetCandidate,
    *,
    entry: float,
    as_of_date: date,
) -> bool:
    if not candidate.provenance or not math.isfinite(candidate.price):
        return False
    if candidate.price <= entry:
        return False
    for item in candidate.provenance:
        if item.source == "CONFIRMED_SWING_HIGH":
            if (
                item.pivot_date is None
                or item.confirmed_date is None
                or item.pivot_date > as_of_date
                or item.confirmed_date > as_of_date
                or item.extension_ratio is not None
            ):
                return False
        elif item.source == "WAVE3_FIB_EXTENSION":
            if (
                item.extension_ratio is None
                or item.wave1_origin_price is None
                or item.wave1_peak_price is None
                or item.wave2_low_price is None
                or item.formula_identity
                != "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO"
            ):
                return False
            known_ratios = tuple(float(value) for value in EXTENSION_RATIOS.values())
            if not any(math.isclose(item.extension_ratio, value) for value in known_ratios):
                return False
            if not (
                math.isfinite(item.wave1_origin_price)
                and math.isfinite(item.wave1_peak_price)
                and math.isfinite(item.wave2_low_price)
                and item.wave1_peak_price > item.wave1_origin_price
            ):
                return False
            expected = project_extension(
                item.wave2_low_price,
                item.wave1_origin_price,
                item.wave1_peak_price,
                item.extension_ratio,
            )
            if not math.isclose(candidate.price, expected, rel_tol=0.0, abs_tol=1e-12):
                return False
        else:
            return False
    return True


def _targets_are_reasonable(
    candidates: Sequence[Setup02TargetCandidate],
    *,
    entry: float,
    low0: float,
    high1: float,
    low2: float,
    execution_stop: float,
    as_of_date: date,
) -> bool:
    """Check only frozen geometry and provenance, never historical outcomes."""
    return (
        high1 > low0
        and low2 > low0
        and execution_stop < entry
        and bool(candidates)
        and all(
            _target_provenance_is_valid(
                candidate,
                entry=entry,
                as_of_date=as_of_date,
            )
            for candidate in candidates
        )
    )


def evaluate_setup02_decision(
    event: Setup02ReplayEvent,
    quotes: Sequence[Quote],
    *,
    risk_capital: float | None = None,
    swing_lookback: int = 5,
    atr_period: int = SETUP02_ATR_PERIOD,
) -> Setup02Decision:
    """Calculate one T-day SETUP_02 plan strictly as of the event date."""
    _validated_event(event)
    prefix = _prefix_at_event(event, quotes)
    try:
        low0, high1, low2, high3, confirmation_level, structural_invalidation = (
            _structure_fields(event, prefix)
        )
    except ValueError as exc:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup02DecisionGateReason.INVALID_STRUCTURE,
            gate_detail=str(exc),
        )

    planned_entry = float(prefix[-1].close)
    invariant_failures = _structure_invariant_failures(
        low0,
        high1,
        low2,
        high3,
        confirmation_level,
        structural_invalidation,
        planned_entry,
    )
    common = dict(
        continuation_low0=low0,
        continuation_high1=high1,
        continuation_low2=low2,
        continuation_high3=high3,
        confirmation_level=confirmation_level,
        planned_entry=planned_entry,
        entry_zone_low=confirmation_level,
        structural_invalidation=structural_invalidation,
        wave1_length=high1.price - low0.price,
    )
    if invariant_failures:
        gate_reason = (
            Setup02DecisionGateReason.STALE_CONFIRMATION_GEOMETRY
            if invariant_failures[0].startswith("STALE_CONFIRMATION_GEOMETRY")
            else Setup02DecisionGateReason.INVALID_STRUCTURE
        )
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=gate_reason,
            gate_detail="; ".join(invariant_failures),
            **common,
        )

    if atr_period <= 0:
        raise ValueError("atr_period 必须为正整数")
    atr_value = atr(list(prefix), atr_period)[-1]
    if atr_value is None or not math.isfinite(float(atr_value)) or float(atr_value) <= 0:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup02DecisionGateReason.ATR_UNAVAILABLE,
            gate_detail="T 日 as-of Wilder ATR14 尚未 available",
            atr14=atr_value,
            **common,
        )

    atr14 = float(atr_value)
    entry_zone_high = confirmation_level + SETUP02_ENTRY_ZONE_ATR * atr14
    execution_stop = structural_invalidation - SETUP02_EXECUTION_STOP_ATR * atr14
    common.update(atr14=atr14, entry_zone_high=entry_zone_high, execution_stop=execution_stop)
    if planned_entry > entry_zone_high:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup02DecisionGateReason.ABOVE_ENTRY_ZONE,
            gate_detail="T close 已高于 HIGH3 + 0.5 * ATR14 entry zone",
            **common,
        )

    candidates = _target_candidates(
        prefix,
        low0=low0,
        high1=high1,
        low2=low2,
        entry=planned_entry,
        swing_lookback=swing_lookback,
    )
    targets = tuple(candidate.price for candidate in candidates[:3])
    if not targets:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup02DecisionGateReason.NO_VALID_TARGET,
            gate_detail="T 日没有高于 planned_entry 的有效前高或 continuation Fib target",
            target_candidates=candidates,
            targets=targets,
            **common,
        )

    # Target candidates are complete before this shared R/R calculation.
    rr = risk_reward(planned_entry, execution_stop, targets)
    reasonableness_checked = rr.quality == HIGH_ASYMMETRY
    reasonableness_passed: bool | None = None
    if reasonableness_checked:
        reasonableness_passed = _targets_are_reasonable(
            candidates,
            entry=planned_entry,
            low0=low0.price,
            high1=high1.price,
            low2=low2.price,
            execution_stop=execution_stop,
            as_of_date=event.trade_date,
        )
        if not reasonableness_passed:
            return _empty_decision(
                event,
                decision_calculable=True,
                gate_reason=Setup02DecisionGateReason.INVALID_STRUCTURE,
                gate_detail=">5R target 未通过 provenance/geometry reasonableness check",
                target_candidates=candidates,
                targets=targets,
                target_reasonableness_checked=True,
                target_reasonableness_passed=False,
                rr=rr,
                **common,
            )

    if rr.quality == NO_TRADE or rr.rr_ratios[0] < SETUP02_MINIMUM_RR:
        return _empty_decision(
            event,
            decision_calculable=True,
            gate_reason=Setup02DecisionGateReason.RR_BELOW_MINIMUM,
            gate_detail="T1 first target R/R < 2；Target 先于 R/R 生成",
            target_candidates=candidates,
            targets=targets,
            target_reasonableness_checked=reasonableness_checked,
            target_reasonableness_passed=reasonableness_passed,
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
        gate_reason=Setup02DecisionGateReason.ENTRY_ALLOWED,
        gate_detail="T close confirmed；plan earliest execution at exact T+1 market-session OPEN",
        target_candidates=candidates,
        targets=targets,
        target_reasonableness_checked=reasonableness_checked,
        target_reasonableness_passed=reasonableness_passed,
        rr=rr,
        position_size_result=size,
        position_size_required_input=required_input,
        **common,
    )


def execute_setup02_t1_open(
    decision: Setup02Decision,
    quotes: Sequence[Quote],
    *,
    market_session_dates: Mapping[str, Sequence[date]] | None = None,
) -> Setup02Execution:
    """Use only exact T+1 OPEN for a T-day ENTRY_ALLOWED plan."""
    if decision.action is not DecisionAction.ENTRY_ALLOWED:
        return Setup02Execution(
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
    sessions = tuple(
        market_session_dates.get(decision.market, ())
        if market_session_dates is not None
        else ()
    )
    ordinals = {session_date: index for index, session_date in enumerate(sessions)}
    if (
        not sessions
        or tuple(sorted(set(sessions))) != sessions
        or decision.trade_date not in ordinals
    ):
        expected_date = None
    else:
        next_index = ordinals[decision.trade_date] + 1
        expected_date = sessions[next_index] if next_index < len(sessions) else None
    matches = [
        quote
        for quote in quotes
        if expected_date is not None
        and quote.trade_date == expected_date
        and quote.symbol == decision.symbol
        and quote.market == decision.market
    ]
    # No later bar is a substitute, and duplicate exact-session bars fail closed.
    t1 = matches[0] if len(matches) == 1 else None
    if t1 is None:
        return Setup02Execution(
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

    # Deliberately read no T+1 high/low/close.
    opening = float(t1.open)
    assert decision.entry_zone_low is not None
    assert decision.entry_zone_high is not None
    assert decision.confirmation_level is not None
    assert decision.structural_invalidation is not None
    assert decision.execution_stop is not None
    if opening <= decision.structural_invalidation:
        outcome = SKIP_BELOW_INVALIDATION
        actual_entry = None
        actual_rr = None
    elif opening < decision.confirmation_level:
        outcome = SKIP_GAP_BELOW_CONFIRMATION
        actual_entry = None
        actual_rr = None
    elif opening > decision.entry_zone_high:
        outcome = SKIP_GAP_ABOVE_ENTRY_ZONE
        actual_entry = None
        actual_rr = None
    else:
        actual_rr = risk_reward(opening, decision.execution_stop, decision.targets)
        if actual_rr.rr_ratios[0] < SETUP02_MINIMUM_RR:
            outcome = SKIP_RR_BELOW_MINIMUM_AT_OPEN
            actual_entry = None
        else:
            outcome = EXECUTED
            actual_entry = opening
    return Setup02Execution(
        event_identity=decision.event_identity,
        symbol=decision.symbol,
        market=decision.market,
        trade_date=decision.trade_date,
        execution_date=t1.trade_date,
        t1_open=opening,
        attempted=True,
        outcome=outcome,
        actual_entry=actual_entry,
        actual_rr=actual_rr,
    )


def evaluate_setup02_decision_stream(
    events: Iterable[Setup02ReplayEvent],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    *,
    risk_capital: float | None = None,
    swing_lookback: int = 5,
    atr_period: int = SETUP02_ATR_PERIOD,
) -> Setup02DecisionStream:
    """Consume first-entry CONFIRMED identities exactly once."""
    seen: set[str] = set()
    decisions: list[Setup02Decision] = []
    executions: list[Setup02Execution] = []
    duplicate_count = 0
    ignored_count = 0
    market_session_dates = build_market_session_dates(quotes_by_symbol)
    for event in events:
        if event.event_identity in seen:
            duplicate_count += 1
            continue
        seen.add(event.event_identity)
        if (
            event.event_type is not SetupState.CONFIRMED
            or not event.setup02.is_new_confirmed_event_as_of
            or event.setup02.confirmed_date != event.trade_date
            or event.setup02.as_of_date != event.trade_date
        ):
            ignored_count += 1
            continue
        try:
            decision = evaluate_setup02_decision(
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
                gate_reason=Setup02DecisionGateReason.INVALID_STRUCTURE,
                gate_detail=str(exc),
            )
        decisions.append(decision)
        if decision.action is DecisionAction.ENTRY_ALLOWED:
            executions.append(
                execute_setup02_t1_open(
                    decision,
                    quotes_by_symbol[event.symbol],
                    market_session_dates=market_session_dates,
                )
            )
    return Setup02DecisionStream(
        decisions=tuple(decisions),
        executions=tuple(executions),
        duplicate_event_count=duplicate_count,
        ignored_non_confirmed_event_count=ignored_count,
    )


def _swing_to_dict(swing: SwingPoint | None) -> dict | None:
    if swing is None:
        return None
    return {
        "kind": swing.kind.value,
        "price": swing.price,
        "pivot_index": swing.pivot_index,
        "pivot_date": swing.pivot_date.isoformat(),
        "confirmed_index": swing.confirmed_index,
        "confirmed_date": (
            swing.confirmed_date.isoformat() if swing.confirmed_date else None
        ),
    }


def _target_to_dict(candidate: Setup02TargetCandidate) -> dict:
    return {
        "price": candidate.price,
        "source": candidate.source,
        "reason": candidate.reason,
        "provenance": [
            {
                "source": item.source,
                "pivot_date": item.pivot_date.isoformat() if item.pivot_date else None,
                "confirmed_date": (
                    item.confirmed_date.isoformat()
                    if item.confirmed_date
                    else None
                ),
                "extension_ratio": item.extension_ratio,
                "wave1_origin_price": item.wave1_origin_price,
                "wave1_peak_price": item.wave1_peak_price,
                "wave2_low_price": item.wave2_low_price,
                "formula_identity": item.formula_identity,
            }
            for item in candidate.provenance
        ],
    }


def setup02_target_provenance_audit(
    decision: Setup02Decision,
    execution: Setup02Execution | None = None,
) -> dict:
    """Return descriptive target provenance and planned/open R/R facts."""
    if not decision.target_candidates or not decision.targets:
        raise ValueError("target provenance audit requires a valid T1 target")
    t1 = decision.target_candidates[0]
    actual_rr = execution.actual_rr if execution is not None else None
    planned_first_rr = decision.rr.rr_ratios[0] if decision.rr else None
    actual_first_rr = actual_rr.rr_ratios[0] if actual_rr else None
    provenance = [
        {
            "source": item.source,
            "pivot_date": item.pivot_date.isoformat() if item.pivot_date else None,
            "confirmed_date": (
                item.confirmed_date.isoformat() if item.confirmed_date else None
            ),
            "extension_ratio": item.extension_ratio,
            "wave1_origin_price": item.wave1_origin_price,
            "wave1_peak_price": item.wave1_peak_price,
            "wave2_low_price": item.wave2_low_price,
            "formula_identity": item.formula_identity,
        }
        for item in t1.provenance
    ]
    geometry_check = False
    if (
        decision.planned_entry is not None
        and decision.confirmation_level is not None
        and decision.structural_invalidation is not None
        and decision.execution_stop is not None
        and decision.continuation_low0 is not None
        and decision.continuation_high1 is not None
        and decision.continuation_low2 is not None
    ):
        geometry_check = _targets_are_reasonable(
            decision.target_candidates,
            entry=decision.planned_entry,
            low0=decision.continuation_low0.price,
            high1=decision.continuation_high1.price,
            low2=decision.continuation_low2.price,
            execution_stop=decision.execution_stop,
            as_of_date=decision.trade_date,
        )
    return {
        "event_identity": decision.event_identity,
        "symbol": decision.symbol,
        "market": decision.market,
        "trade_date": decision.trade_date.isoformat(),
        "target_t1_price": t1.price,
        "target_t1_source": t1.source,
        "target_t1_reason": t1.reason,
        "target_t1_provenance": provenance,
        "planned_entry": decision.planned_entry,
        "actual_open": execution.t1_open if execution else None,
        "actual_entry": execution.actual_entry if execution else None,
        "planned_first_target_rr": planned_first_rr,
        "actual_open_first_target_rr": actual_first_rr,
        "planned_rr_quality": decision.rr.quality if decision.rr else None,
        "actual_open_rr_quality": actual_rr.quality if actual_rr else None,
        "planned_first_target_over_5r": (
            planned_first_rr is not None and planned_first_rr > 5.0
        ),
        "actual_open_first_target_over_5r": (
            actual_first_rr is not None and actual_first_rr > 5.0
        ),
        "target_reasonableness_checked": decision.target_reasonableness_checked,
        "target_reasonableness_passed": decision.target_reasonableness_passed,
        "target_provenance_geometry_check": geometry_check,
    }


def _risk_reward_to_dict(value: RiskReward | None) -> dict | None:
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


def _position_size_to_dict(value: PositionSize | None) -> dict | None:
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


def setup02_decision_to_dict(value: Setup02Decision) -> dict:
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
        "continuation_low0": _swing_to_dict(value.continuation_low0),
        "continuation_high1": _swing_to_dict(value.continuation_high1),
        "continuation_low2": _swing_to_dict(value.continuation_low2),
        "continuation_high3": _swing_to_dict(value.continuation_high3),
        "confirmation_level": value.confirmation_level,
        "planned_entry": value.planned_entry,
        "entry_zone_low": value.entry_zone_low,
        "entry_zone_high": value.entry_zone_high,
        "structural_invalidation": value.structural_invalidation,
        "execution_stop": value.execution_stop,
        "wave1_length": value.wave1_length,
        "target_candidates": [_target_to_dict(item) for item in value.target_candidates],
        "targets": list(value.targets),
        "T1": value.targets[0] if len(value.targets) > 0 else None,
        "T2": value.targets[1] if len(value.targets) > 1 else None,
        "T3": value.targets[2] if len(value.targets) > 2 else None,
        "target_reasonableness_checked": value.target_reasonableness_checked,
        "target_reasonableness_passed": value.target_reasonableness_passed,
        "rr": _risk_reward_to_dict(value.rr),
        "position_size": _position_size_to_dict(value.position_size),
        "position_size_required_input": value.position_size_required_input,
    }


def setup02_execution_to_dict(value: Setup02Execution) -> dict:
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
        "actual_rr": _risk_reward_to_dict(value.actual_rr),
    }


__all__ = [
    "EXECUTED",
    "SETUP02_ATR_PERIOD",
    "SETUP02_DECISION_PROTOCOL_VERSION",
    "SETUP02_ENTRY_ZONE_ATR",
    "SETUP02_EXECUTION_STOP_ATR",
    "SETUP02_MINIMUM_RR",
    "SKIP_BELOW_INVALIDATION",
    "SKIP_DECISION_NOT_ENTRY_ALLOWED",
    "SKIP_GAP_ABOVE_ENTRY_ZONE",
    "SKIP_GAP_BELOW_CONFIRMATION",
    "SKIP_NO_T1_BAR",
    "SKIP_RR_BELOW_MINIMUM_AT_OPEN",
    "Setup02Decision",
    "Setup02DecisionGateReason",
    "Setup02DecisionStream",
    "Setup02Execution",
    "Setup02TargetCandidate",
    "Setup02TargetProvenance",
    "evaluate_setup02_decision",
    "evaluate_setup02_decision_stream",
    "execute_setup02_t1_open",
    "setup02_decision_to_dict",
    "setup02_execution_to_dict",
    "setup02_structure_geometry_audit",
    "setup02_target_provenance_audit",
]

"""Mechanical Position Management and Exit for already-executed long entries.

The module consumes frozen SETUP_01/SETUP_02 execution records only when their
outcome is ``EXECUTED``.  It does not rescreen entries, create new entries, or
calculate any performance statistic.  All state is causal through the current
quote prefix; a stop formed at a close becomes active no earlier than the next
market session.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date
from enum import Enum
import math
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from core import Quote
from trading.indicators import atr
from trading.models import SwingKind, SwingPoint, validate_quote_series
from trading.swing import find_swings
from trading.wave5_context import (
    WAVE5_CONTEXT_PROTOCOL_VERSION,
    Wave5ContextState,
    evaluate_wave5_context,
)


POSITION_MANAGEMENT_PROTOCOL_VERSION = (
    "POSITION-MANAGEMENT-EXIT-2026-09-02-v1"
)
EXECUTED = "EXECUTED"
MFE_TRIGGER_R = 2.0
MFE_GIVEBACK_R = 1.0
STRUCTURAL_TRAILING_ATR = 0.5
HIGH_VOLUME_MULTIPLIER = 2.0
STALL_RANGE_FRACTION = 0.25
UPPER_WICK_BODY_MULTIPLIER = 2.0
MOMENTUM_LOOKBACK = 5


class PositionAction(str, Enum):
    HOLD = "HOLD"
    NO_ADD = "NO_ADD"
    PROFIT_PROTECTION = "PROFIT_PROTECTION"
    EXIT = "EXIT"


class TargetReachStatus(str, Enum):
    NOT_REACHED = "NOT_REACHED"
    T1_REACHED = "T1_REACHED"
    T2_REACHED = "T2_REACHED"
    T3_REACHED = "T3_REACHED"


class PositionExitReason(str, Enum):
    EXIT_GAP_BELOW_STOP = "EXIT_GAP_BELOW_STOP"
    EXIT_STOP_TRIGGERED = "EXIT_STOP_TRIGGERED"
    STRUCTURAL_EXIT_PENDING = "STRUCTURAL_EXIT_PENDING"
    PROFIT_PROTECTION_EXIT_PENDING = "PROFIT_PROTECTION_EXIT_PENDING"


@dataclass(frozen=True)
class PositionAnchor:
    """Immutable copy of a source Wave structural anchor."""

    name: str
    kind: str
    price: float
    pivot_index: int
    pivot_date: date
    confirmed_index: int | None
    confirmed_date: date | None

    @classmethod
    def from_swing(cls, name: str, swing: SwingPoint) -> "PositionAnchor":
        return cls(
            name=name,
            kind=swing.kind.value,
            price=float(swing.price),
            pivot_index=int(swing.pivot_index),
            pivot_date=swing.pivot_date,
            confirmed_index=swing.confirmed_index,
            confirmed_date=swing.confirmed_date,
        )


@dataclass(frozen=True)
class PositionTarget:
    """Frozen target price together with the Decision-owned explanation."""

    price: float
    source: str
    provenance: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not self.source or not self.provenance:
            raise ValueError("a frozen target requires source and provenance")
        if not math.isfinite(float(self.price)):
            raise ValueError("frozen target price must be finite")


@dataclass(frozen=True)
class PositionOrigin:
    """Frozen origin and risk geometry for one executed position."""

    source_setup: str
    source_event_identity: str
    symbol: str
    market: str
    entry_date: date
    actual_entry: float
    initial_execution_stop: float
    initial_structural_invalidation: float
    targets: tuple[PositionTarget, ...]
    wave_anchors: tuple[PositionAnchor, ...]
    initial_risk_per_share: float

    def __post_init__(self) -> None:
        values = (
            self.actual_entry,
            self.initial_execution_stop,
            self.initial_structural_invalidation,
            self.initial_risk_per_share,
        )
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("position origin geometry must be finite")
        expected = self.actual_entry - self.initial_execution_stop
        if expected <= 0 or not math.isclose(
            expected, self.initial_risk_per_share, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("initial 1R must equal actual_entry - initial_execution_stop")
        if not self.targets or len(self.targets) > 3:
            raise ValueError("an executed position must retain frozen T1-T3 targets")
        if any(
            not math.isfinite(float(target.price)) or target.price <= self.actual_entry
            for target in self.targets
        ):
            raise ValueError("frozen targets must be finite and above actual entry")
        if not self.wave_anchors:
            raise ValueError("original Wave anchors are required")

    @property
    def one_r(self) -> float:
        return self.initial_risk_per_share

    @property
    def target_prices(self) -> tuple[float, ...]:
        return tuple(float(target.price) for target in self.targets)

    def anchor(self, name: str) -> PositionAnchor | None:
        return next((item for item in self.wave_anchors if item.name == name), None)


@dataclass(frozen=True)
class PositionDay:
    """One causal as-of day while the position is open or exits."""

    source_event_identity: str
    source_setup: str
    trade_date: date
    open: float
    close: float | None
    active_stop_at_open: float
    active_stop_next_session: float
    structural_stop_candidate: float | None
    structural_floor: float
    mfe_floor: float | None
    current_r: float
    mfe_r: float
    mae_r: float
    mfe_drawdown_r: float
    target_status: TargetReachStatus
    wave5_context: Wave5ContextState
    risk_flags: tuple[str, ...]
    action: PositionAction
    secondary_reasons: tuple[str, ...]
    exit_reason: PositionExitReason | None
    exit_price: float | None
    stop_raised: bool
    position_open_at_close: bool


@dataclass(frozen=True)
class PositionReplay:
    origin: PositionOrigin
    days: tuple[PositionDay, ...]
    final_active_stop: float
    exit_date: date | None
    exit_reason: PositionExitReason | None
    exit_price: float | None

    @property
    def position_days(self) -> int:
        return len(self.days)

    @property
    def stop_raise_count(self) -> int:
        return sum(int(day.stop_raised) for day in self.days)


def _anchor_from_snapshot(
    anchors: list[tuple[str, object | None]],
) -> tuple[PositionAnchor, ...]:
    result: list[PositionAnchor] = []
    for name, swing in anchors:
        if swing is not None:
            result.append(PositionAnchor.from_swing(name, swing))
    return tuple(result)


def position_origin_from_execution(
    source_setup: str,
    event: object,
    decision: object,
    execution: object,
) -> PositionOrigin | None:
    """Adapt one frozen SETUP_01/SETUP_02 execution into a position origin.

    Non-``EXECUTED`` records are intentionally ignored.  This adapter only
    carries the already-frozen entry geometry forward and never recomputes it.
    """
    if getattr(execution, "outcome", None) != EXECUTED:
        return None
    actual_entry = getattr(execution, "actual_entry", None)
    entry_date = getattr(execution, "execution_date", None)
    execution_stop = getattr(decision, "execution_stop", None)
    structural_invalidation = getattr(decision, "structural_invalidation", None)
    decision_targets = tuple(float(value) for value in getattr(decision, "targets", ()))
    target_candidates = tuple(getattr(decision, "target_candidates", ()))[:3]
    if (
        actual_entry is None
        or entry_date is None
        or execution_stop is None
        or structural_invalidation is None
        or not decision_targets
        or len(target_candidates) != len(decision_targets)
    ):
        raise ValueError("EXECUTED ledger row is missing immutable position origin fields")
    if tuple(float(candidate.price) for candidate in target_candidates) != decision_targets:
        raise ValueError("Decision target prices and candidates are inconsistent")
    targets = tuple(
        PositionTarget(
            price=float(candidate.price),
            source=str(candidate.source),
            provenance=tuple(candidate.provenance),
        )
        for candidate in target_candidates
    )

    if source_setup == "SETUP_01":
        snapshot = getattr(event, "setup01", None)
        anchors = _anchor_from_snapshot(
            [
                ("LOW0", getattr(snapshot, "wave1_origin", None)),
                ("HIGH1", getattr(snapshot, "wave1_peak", None)),
                ("LOW2", getattr(snapshot, "wave2_low", None)),
            ]
        )
    elif source_setup == "SETUP_02":
        snapshot = getattr(event, "setup02", None)
        anchors = _anchor_from_snapshot(
            [
                ("LOW0", getattr(snapshot, "continuation_low0", None)),
                ("HIGH1", getattr(snapshot, "continuation_high1", None)),
                ("LOW2", getattr(snapshot, "continuation_low2", None)),
                ("HIGH3", getattr(snapshot, "continuation_high3", None)),
            ]
        )
    else:
        raise ValueError(f"unsupported source setup: {source_setup}")

    actual_entry_value = float(actual_entry)
    execution_stop_value = float(execution_stop)
    return PositionOrigin(
        source_setup=source_setup,
        source_event_identity=str(getattr(execution, "event_identity")),
        symbol=str(getattr(execution, "symbol")),
        market=str(getattr(execution, "market")),
        entry_date=entry_date,
        actual_entry=actual_entry_value,
        initial_execution_stop=execution_stop_value,
        initial_structural_invalidation=float(structural_invalidation),
        targets=targets,
        wave_anchors=anchors,
        initial_risk_per_share=actual_entry_value - execution_stop_value,
    )


def _anchor_price(origin: PositionOrigin, name: str, default: float) -> float:
    anchor = origin.anchor(name)
    return float(anchor.price) if anchor is not None else default


def _latest_confirmed_higher_low(
    origin: PositionOrigin,
    quotes: Sequence[Quote],
    as_of_index: int,
    *,
    swing_lookback: int,
    confirmed_swings: Sequence[SwingPoint] | None = None,
) -> SwingPoint | None:
    wave2_low = _anchor_price(origin, "LOW2", origin.initial_structural_invalidation)
    # A full-series swing pass is safe here: only swings whose own pivot and
    # confirmation indices are available at ``as_of_index`` are admitted.
    confirmed = (
        tuple(confirmed_swings)
        if confirmed_swings is not None
        else find_swings(list(quotes[: as_of_index + 1]), lookback=swing_lookback)
    )
    candidates = [
        swing
        for swing in confirmed
        if swing.kind is SwingKind.LOW
        and swing.pivot_date > origin.entry_date
        and swing.price > wave2_low
        and swing.pivot_index <= as_of_index
        and swing.confirmed_index is not None
        and swing.confirmed_index <= as_of_index
        and swing.confirmed_date is not None
        and swing.confirmed_date <= quotes[as_of_index].trade_date
    ]
    return max(candidates, key=lambda item: item.pivot_index) if candidates else None


def _target_status(
    max_high: float, targets: Sequence[PositionTarget]
) -> TargetReachStatus:
    prices = tuple(target.price for target in targets)
    if len(prices) >= 3 and max_high >= prices[2]:
        return TargetReachStatus.T3_REACHED
    if len(prices) >= 2 and max_high >= prices[1]:
        return TargetReachStatus.T2_REACHED
    if max_high >= prices[0]:
        return TargetReachStatus.T1_REACHED
    return TargetReachStatus.NOT_REACHED


def _momentum_divergence(prefix: Sequence[Quote]) -> bool:
    window = MOMENTUM_LOOKBACK
    if len(prefix) < window * 2:
        return False
    previous = prefix[-window * 2 : -window]
    recent = prefix[-window:]
    previous_high = max(float(item.close) for item in previous)
    recent_high = max(float(item.close) for item in recent)
    previous_change = float(previous[-1].close) - float(previous[0].close)
    recent_change = float(recent[-1].close) - float(recent[0].close)
    return recent_high > previous_high and recent_change < previous_change


def _risk_flags(
    quote: Quote,
    prefix: Sequence[Quote],
    *,
    atr14: float | None,
    max_high: float,
    target_status: TargetReachStatus,
    targets: Sequence[PositionTarget],
    wave5_state: Wave5ContextState,
) -> tuple[str, ...]:
    flags: list[str] = []
    if wave5_state is Wave5ContextState.WAVE5_CANDIDATE:
        flags.append("WAVE5_CANDIDATE")
    if target_status is not TargetReachStatus.NOT_REACHED:
        reached = [
            target for target in targets if target.price <= max_high
        ]
        if any(
            any(getattr(item, "source", None) == "WAVE3_FIB_EXTENSION" for item in target.provenance)
            for target in reached
        ):
            flags.append("FIB_TARGET_REACHED")
        if any(
            any(getattr(item, "source", None) == "CONFIRMED_SWING_HIGH" for item in target.provenance)
            for target in reached
        ):
            flags.append("CONFIRMED_SWING_TARGET_REACHED")
    else:
        next_target = targets[0]
        if atr14 is not None and next_target.price - float(quote.close) <= atr14:
            if any(
                getattr(item, "source", None) == "WAVE3_FIB_EXTENSION"
                for item in next_target.provenance
            ):
                flags.append("FIB_TARGET_PROXIMITY")
            if any(
                getattr(item, "source", None) == "CONFIRMED_SWING_HIGH"
                for item in next_target.provenance
            ):
                flags.append("CONFIRMED_SWING_TARGET_PROXIMITY")

    prior_volumes = [
        float(item.volume)
        for item in prefix[:-1][-20:]
        if item.volume is not None and float(item.volume) > 0
    ]
    if (
        quote.volume is not None
        and prior_volumes
        and float(quote.volume) > HIGH_VOLUME_MULTIPLIER * median(prior_volumes)
    ):
        flags.append("ABNORMAL_HIGH_VOLUME")

    day_range = float(quote.high) - float(quote.low)
    body = abs(float(quote.close) - float(quote.open))
    if day_range > 0 and body <= STALL_RANGE_FRACTION * day_range:
        flags.append("PRICE_STALL")
    upper_wick = float(quote.high) - max(float(quote.open), float(quote.close))
    if upper_wick > 0 and upper_wick >= UPPER_WICK_BODY_MULTIPLIER * body:
        flags.append("LONG_UPPER_WICK")
    if _momentum_divergence(prefix):
        flags.append("MOMENTUM_DIVERGENCE")
    return tuple(flags)


def _position_day_for_exit(
    origin: PositionOrigin,
    quote: Quote,
    *,
    active_stop: float,
    max_high: float,
    min_low: float,
    target_status: TargetReachStatus,
    mfe_floor: float | None,
    structural_floor: float,
    reason: PositionExitReason,
    exit_price: float,
    secondary_reasons: tuple[str, ...] = (),
) -> PositionDay:
    current_r = (exit_price - origin.actual_entry) / origin.one_r
    max_high = max(max_high, float(quote.open), exit_price)
    min_low = min(min_low, float(quote.open), exit_price)
    mfe_r = (max_high - origin.actual_entry) / origin.one_r
    mae_r = (min_low - origin.actual_entry) / origin.one_r
    return PositionDay(
        source_event_identity=origin.source_event_identity,
        source_setup=origin.source_setup,
        trade_date=quote.trade_date,
        open=float(quote.open),
        close=None,
        active_stop_at_open=active_stop,
        active_stop_next_session=active_stop,
        structural_stop_candidate=None,
        structural_floor=structural_floor,
        mfe_floor=mfe_floor,
        current_r=current_r,
        mfe_r=mfe_r,
        mae_r=mae_r,
        mfe_drawdown_r=mfe_r - current_r,
        target_status=target_status,
        wave5_context=Wave5ContextState.NO_WAVE5_CONTEXT,
        risk_flags=(),
        action=PositionAction.EXIT,
        secondary_reasons=secondary_reasons,
        exit_reason=reason,
        exit_price=exit_price,
        stop_raised=False,
        position_open_at_close=False,
    )


def replay_position(
    origin: PositionOrigin,
    quotes: Sequence[Quote],
    *,
    swing_lookback: int = 5,
    atr_period: int = 14,
) -> PositionReplay:
    """Replay one already-executed position using strict daily causality."""
    validate_quote_series(list(quotes))
    if quotes[0].symbol != origin.symbol or quotes[0].market != origin.market:
        raise ValueError("position origin and quote series identity differ")
    if swing_lookback < 1 or atr_period < 1:
        raise ValueError("swing_lookback and atr_period must be positive")
    entry_indices = [
        index for index, quote in enumerate(quotes) if quote.trade_date >= origin.entry_date
    ]
    if not entry_indices:
        raise ValueError("entry date is not present in quote series")

    # Both series are causal by index.  Reusing these full-series projections
    # avoids rebuilding O(n) history for every replay day; downstream filters
    # still enforce the as-of boundary for swings.
    quote_list = list(quotes)
    all_swings = tuple(find_swings(quote_list, lookback=swing_lookback))
    atr_series = atr(quote_list, atr_period)

    active_stop = origin.initial_execution_stop
    structural_floor = origin.initial_structural_invalidation
    max_high = origin.actual_entry
    min_low = origin.actual_entry
    mfe_floor: float | None = None
    target_status = TargetReachStatus.NOT_REACHED
    pending_exit: PositionExitReason | None = None
    days: list[PositionDay] = []

    for index in range(entry_indices[0], len(quotes)):
        quote = quotes[index]
        if pending_exit is not None:
            day = _position_day_for_exit(
                origin,
                quote,
                active_stop=active_stop,
                max_high=max_high,
                min_low=min_low,
                target_status=target_status,
                mfe_floor=mfe_floor,
                structural_floor=structural_floor,
                reason=pending_exit,
                exit_price=float(quote.open),
            )
            days.append(day)
            return PositionReplay(
                origin=origin,
                days=tuple(days),
                final_active_stop=active_stop,
                exit_date=quote.trade_date,
                exit_reason=pending_exit,
                exit_price=float(quote.open),
            )

        active_at_open = active_stop
        if float(quote.open) <= active_at_open:
            day = _position_day_for_exit(
                origin,
                quote,
                active_stop=active_at_open,
                max_high=max_high,
                min_low=min_low,
                target_status=target_status,
                mfe_floor=mfe_floor,
                structural_floor=structural_floor,
                reason=PositionExitReason.EXIT_GAP_BELOW_STOP,
                exit_price=float(quote.open),
            )
            days.append(day)
            return PositionReplay(
                origin=origin,
                days=tuple(days),
                final_active_stop=active_stop,
                exit_date=quote.trade_date,
                exit_reason=day.exit_reason,
                exit_price=day.exit_price,
            )
        if float(quote.low) <= active_at_open:
            day = _position_day_for_exit(
                origin,
                quote,
                active_stop=active_at_open,
                max_high=max_high,
                min_low=min_low,
                target_status=target_status,
                mfe_floor=mfe_floor,
                structural_floor=structural_floor,
                reason=PositionExitReason.EXIT_STOP_TRIGGERED,
                exit_price=active_at_open,
            )
            days.append(day)
            return PositionReplay(
                origin=origin,
                days=tuple(days),
                final_active_stop=active_stop,
                exit_date=quote.trade_date,
                exit_reason=day.exit_reason,
                exit_price=day.exit_price,
            )

        prefix = quotes[: index + 1]
        atr_value = atr_series[index]
        atr14 = float(atr_value) if atr_value is not None else None
        max_high = max(max_high, float(quote.high))
        min_low = min(min_low, float(quote.low))
        current_r = (float(quote.close) - origin.actual_entry) / origin.one_r
        mfe_r = (max_high - origin.actual_entry) / origin.one_r
        mae_r = (min_low - origin.actual_entry) / origin.one_r
        if mfe_r >= MFE_TRIGGER_R:
            candidate_floor = origin.actual_entry + (
                mfe_r - MFE_GIVEBACK_R
            ) * origin.one_r
            previous_floor = mfe_floor if mfe_floor is not None else -math.inf
            mfe_floor = max(previous_floor, candidate_floor)

        higher_low = _latest_confirmed_higher_low(
            origin,
            quotes,
            index,
            swing_lookback=swing_lookback,
            confirmed_swings=all_swings,
        )
        structural_stop_candidate: float | None = None
        if higher_low is not None:
            structural_floor = max(structural_floor, float(higher_low.price))
            if atr14 is not None:
                candidate = float(higher_low.price) - STRUCTURAL_TRAILING_ATR * atr14
                if candidate > active_at_open and candidate < float(quote.close):
                    structural_stop_candidate = candidate

        target_status = _target_status(max_high, origin.targets)
        wave5 = evaluate_wave5_context(
            quotes=quotes,
            as_of_index=index,
            wave_anchors=origin.wave_anchors,
            structural_invalidation=structural_floor,
            swing_lookback=swing_lookback,
            confirmed_swings=all_swings,
        )
        flags = _risk_flags(
            quote,
            prefix,
            atr14=atr14,
            max_high=max_high,
            target_status=target_status,
            targets=origin.targets,
            wave5_state=wave5.state,
        )

        pending_reasons: list[str] = []
        if float(quote.close) < structural_floor:
            pending_reasons.append(PositionExitReason.STRUCTURAL_EXIT_PENDING.value)
        if mfe_floor is not None and float(quote.close) < mfe_floor:
            pending_reasons.append(
                PositionExitReason.PROFIT_PROTECTION_EXIT_PENDING.value
            )
        if pending_reasons:
            pending_exit = (
                PositionExitReason.STRUCTURAL_EXIT_PENDING
                if PositionExitReason.STRUCTURAL_EXIT_PENDING.value in pending_reasons
                else PositionExitReason.PROFIT_PROTECTION_EXIT_PENDING
            )

        stop_raised = False
        next_stop = active_at_open
        if not pending_reasons:
            valid_candidates = [
                candidate
                for candidate in (structural_stop_candidate, mfe_floor)
                if candidate is not None and candidate <= float(quote.close)
            ]
            if valid_candidates:
                next_stop = max(active_at_open, *valid_candidates)
                stop_raised = next_stop > active_at_open

        if pending_exit is not None:
            action = PositionAction.PROFIT_PROTECTION
        elif wave5.state is Wave5ContextState.WAVE5_CANDIDATE:
            action = PositionAction.NO_ADD
        elif stop_raised or flags:
            action = PositionAction.PROFIT_PROTECTION
        else:
            action = PositionAction.HOLD
        secondary = tuple(
            [*flags, *pending_reasons]
            + (["PROTECTIVE_STOP_RAISED"] if stop_raised else [])
        )
        day = PositionDay(
            source_event_identity=origin.source_event_identity,
            source_setup=origin.source_setup,
            trade_date=quote.trade_date,
            open=float(quote.open),
            close=float(quote.close),
            active_stop_at_open=active_at_open,
            active_stop_next_session=next_stop,
            structural_stop_candidate=structural_stop_candidate,
            structural_floor=structural_floor,
            mfe_floor=mfe_floor,
            current_r=current_r,
            mfe_r=mfe_r,
            mae_r=mae_r,
            mfe_drawdown_r=mfe_r - current_r,
            target_status=target_status,
            wave5_context=wave5.state,
            risk_flags=flags,
            action=action,
            secondary_reasons=secondary,
            exit_reason=None,
            exit_price=None,
            stop_raised=stop_raised,
            position_open_at_close=True,
        )
        days.append(day)
        if next_stop > active_stop:
            active_stop = next_stop

    return PositionReplay(
        origin=origin,
        days=tuple(days),
        final_active_stop=active_stop,
        exit_date=None,
        exit_reason=None,
        exit_price=None,
    )


def replay_positions(
    origins: Iterable[PositionOrigin],
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    *,
    swing_lookback: int = 5,
    atr_period: int = 14,
) -> tuple[PositionReplay, ...]:
    """Replay origins in deterministic source-setup/event order."""
    ordered = sorted(origins, key=lambda item: (item.entry_date, item.source_event_identity))
    return tuple(
        replay_position(
            origin,
            quotes_by_symbol[origin.symbol],
            swing_lookback=swing_lookback,
            atr_period=atr_period,
        )
        for origin in ordered
    )


def position_replay_to_dict(replay: PositionReplay) -> dict[str, Any]:
    def serialise(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
            return value.isoformat()
        if is_dataclass(value):
            return {
                item.name: serialise(getattr(value, item.name))
                for item in fields(value)
            }
        if isinstance(value, Mapping):
            return {str(key): serialise(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [serialise(item) for item in value]
        return value

    return {
        "source_setup": replay.origin.source_setup,
        "source_event_identity": replay.origin.source_event_identity,
        "symbol": replay.origin.symbol,
        "market": replay.origin.market,
        "entry_date": replay.origin.entry_date.isoformat(),
        "actual_entry": replay.origin.actual_entry,
        "initial_execution_stop": replay.origin.initial_execution_stop,
        "initial_structural_invalidation": replay.origin.initial_structural_invalidation,
        "initial_risk_per_share": replay.origin.initial_risk_per_share,
        "targets": list(replay.origin.target_prices),
        "target_details": [
            {
                "price": target.price,
                "source": target.source,
                "provenance": [serialise(item) for item in target.provenance],
            }
            for target in replay.origin.targets
        ],
        "wave_anchors": [
            {
                "name": item.name,
                "kind": item.kind,
                "price": item.price,
                "pivot_index": item.pivot_index,
                "pivot_date": item.pivot_date.isoformat(),
                "confirmed_index": item.confirmed_index,
                "confirmed_date": (
                    item.confirmed_date.isoformat() if item.confirmed_date else None
                ),
            }
            for item in replay.origin.wave_anchors
        ],
        "final_active_stop": replay.final_active_stop,
        "exit_date": replay.exit_date.isoformat() if replay.exit_date else None,
        "exit_reason": replay.exit_reason.value if replay.exit_reason else None,
        "exit_price": replay.exit_price,
        "position_days": replay.position_days,
        "days": [
            {
                "trade_date": day.trade_date.isoformat(),
                "open": day.open,
                "close": day.close,
                "active_stop_at_open": day.active_stop_at_open,
                "active_stop_next_session": day.active_stop_next_session,
                "structural_stop_candidate": day.structural_stop_candidate,
                "structural_floor": day.structural_floor,
                "mfe_floor": day.mfe_floor,
                "current_r": day.current_r,
                "mfe_r": day.mfe_r,
                "mae_r": day.mae_r,
                "mfe_drawdown_r": day.mfe_drawdown_r,
                "target_status": day.target_status.value,
                "wave5_context": day.wave5_context.value,
                "risk_flags": list(day.risk_flags),
                "action": day.action.value,
                "secondary_reasons": list(day.secondary_reasons),
                "exit_reason": day.exit_reason.value if day.exit_reason else None,
                "exit_price": day.exit_price,
                "stop_raised": day.stop_raised,
                "position_open_at_close": day.position_open_at_close,
            }
            for day in replay.days
        ],
    }


__all__ = [
    "EXECUTED",
    "MFE_GIVEBACK_R",
    "MFE_TRIGGER_R",
    "POSITION_MANAGEMENT_PROTOCOL_VERSION",
    "PositionAction",
    "PositionAnchor",
    "PositionDay",
    "PositionExitReason",
    "PositionOrigin",
    "PositionReplay",
    "PositionTarget",
    "TargetReachStatus",
    "position_origin_from_execution",
    "position_replay_to_dict",
    "replay_position",
    "replay_positions",
]

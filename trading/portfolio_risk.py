"""Conservative Portfolio Risk V1 gate.

This module is deliberately downstream of the individual Decision layer.  It
does not create or rescore signals and never mutates entry, stop, target, or
upstream Decision objects.  The engine reserves a fixed risk unit at decision
time, then either releases that reservation on a failed T+1 attempt or turns
it into one frozen open position on execution.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from enum import Enum
import math
from typing import Any, Iterable, Mapping, Sequence

from trading.models import PositionSize
from trading.risk import position_size


PORTFOLIO_RISK_PROTOCOL_VERSION = "PORTFOLIO-RISK-2026-09-02-v1"
DEVELOPMENT_EXPOSED = "DEVELOPMENT_EXPOSED"
PRODUCTION = "PRODUCTION"
BASE_RISK_FRACTION = 0.005
MAX_TOTAL_OPEN_RISK_FRACTION = 0.02
MAX_RISK_PER_GROUP_FRACTION = 0.01
UNKNOWN_RISK_GROUP = "UNKNOWN"

PORTFOLIO_ALLOWED = "PORTFOLIO_ALLOWED"
PORTFOLIO_NAV_REQUIRED = "PORTFOLIO_NAV_REQUIRED"
BLOCK_TOTAL_RISK_BUDGET = "BLOCK_TOTAL_RISK_BUDGET"
BLOCK_EXISTING_POSITION_SAME_SYMBOL = "BLOCK_EXISTING_POSITION_SAME_SYMBOL"
BLOCK_RISK_GROUP_CONCENTRATION = "BLOCK_RISK_GROUP_CONCENTRATION"
BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION = "BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION"
BLOCK_POSITION_MANAGEMENT_NO_ADD = "BLOCK_POSITION_MANAGEMENT_NO_ADD"
BLOCK_INVALID_RISK_GEOMETRY = "BLOCK_INVALID_RISK_GEOMETRY"
RISK_GROUP_UNKNOWN = "RISK_GROUP_UNKNOWN"
RESERVATION_RELEASED_ON_FAILED_T1 = "RESERVATION_RELEASED_ON_FAILED_T1"


class PortfolioReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    BLOCKED = "BLOCKED"
    RELEASED = "RELEASED"
    EXECUTED = "EXECUTED"


@dataclass(frozen=True)
class PortfolioCandidate:
    """An already-allowed individual Decision competing for capacity."""

    event_identity: str
    source_setup: str
    symbol: str
    market: str
    trade_date: date
    planned_entry: float
    execution_stop: float
    planned_rr: float
    rr_quality: str
    execution_outcome: str | None = None
    execution_date: date | None = None
    actual_entry: float | None = None
    risk_group: str = UNKNOWN_RISK_GROUP
    position_management_action: str | None = None

    def __post_init__(self) -> None:
        if not self.event_identity:
            raise ValueError("portfolio candidate requires event_identity")
        if not self.symbol or not self.market or not self.source_setup:
            raise ValueError("portfolio candidate identity fields are required")
        for name, value in (
            ("planned_entry", self.planned_entry),
            ("execution_stop", self.execution_stop),
            ("planned_rr", self.planned_rr),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.planned_entry <= self.execution_stop:
            raise ValueError("long candidate must have planned_entry above execution_stop")
        if self.actual_entry is not None and not math.isfinite(float(self.actual_entry)):
            raise ValueError("actual_entry must be finite when provided")

    @property
    def canonical_symbol(self) -> str:
        return canonical_symbol(self.symbol, self.market)

    @property
    def normalized_risk_group(self) -> str:
        return normalize_risk_group(self.risk_group)


@dataclass(frozen=True)
class OpenPortfolioPosition:
    """Frozen quantity plus the current protective-stop snapshot."""

    source_event_identity: str
    source_setup: str
    symbol: str
    market: str
    entry_date: date
    quantity: float
    current_price: float
    active_protective_stop: float
    risk_group: str = UNKNOWN_RISK_GROUP
    actual_entry: float | None = None

    def __post_init__(self) -> None:
        if not self.source_event_identity or not self.source_setup:
            raise ValueError("open position source identity is required")
        if not self.symbol or not self.market:
            raise ValueError("open position symbol and market are required")
        for name, value in (
            ("quantity", self.quantity),
            ("current_price", self.current_price),
            ("active_protective_stop", self.active_protective_stop),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if self.quantity < 0:
            raise ValueError("open position quantity cannot be negative")
        if self.actual_entry is not None and not math.isfinite(float(self.actual_entry)):
            raise ValueError("actual_entry must be finite when provided")

    @property
    def canonical_symbol(self) -> str:
        return canonical_symbol(self.symbol, self.market)

    @property
    def normalized_risk_group(self) -> str:
        return normalize_risk_group(self.risk_group)

    def remaining_loss_risk(self, reference_nav: float) -> float:
        """Return non-negative downside risk as a fraction of reference NAV."""
        nav = _require_positive_finite(reference_nav, "reference_nav")
        if (
            self.actual_entry is not None
            and float(self.active_protective_stop) >= float(self.actual_entry)
        ):
            return 0.0
        active_stop_risk_per_share = max(
            float(self.current_price) - float(self.active_protective_stop), 0.0
        )
        return max(float(self.quantity) * active_stop_risk_per_share / nav, 0.0)


@dataclass(frozen=True)
class PortfolioExposure:
    total_open_risk_fraction: float
    risk_by_group: dict[str, float]
    risk_by_market: dict[str, float]
    position_count_by_market: dict[str, int]
    position_count: int


@dataclass(frozen=True)
class PortfolioReservation:
    candidate: PortfolioCandidate
    status: PortfolioReservationStatus
    reason: str
    advisory_flags: tuple[str, ...]
    proposed_initial_risk_fraction: float
    total_risk_before: float
    total_risk_after: float
    group_risk_before: float
    group_risk_after: float
    planned_position_size: PositionSize | None

    @property
    def reservation_id(self) -> str:
        return self.candidate.event_identity


@dataclass(frozen=True)
class PortfolioSettlement:
    reservation: PortfolioReservation
    status: PortfolioReservationStatus
    reason: str
    position_size: PositionSize | None
    position: OpenPortfolioPosition | None


@dataclass(frozen=True)
class PortfolioReservationBatch:
    ordered_candidate_ids: tuple[str, ...]
    reservations: tuple[PortfolioReservation, ...]
    exposure_before: PortfolioExposure
    exposure_after_reservations: PortfolioExposure

    @property
    def approved(self) -> tuple[PortfolioReservation, ...]:
        return tuple(
            item
            for item in self.reservations
            if item.status is PortfolioReservationStatus.RESERVED
        )

    @property
    def blocked(self) -> tuple[PortfolioReservation, ...]:
        return tuple(
            item
            for item in self.reservations
            if item.status is PortfolioReservationStatus.BLOCKED
        )


def _require_positive_finite(value: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return number


def canonical_symbol(symbol: str, market: str | None = None) -> str:
    """Normalize identity spelling without inventing an exchange suffix."""
    value = str(symbol).strip().upper()
    if not value:
        raise ValueError("symbol cannot be empty")
    return value


def normalize_risk_group(risk_group: object | None) -> str:
    value = str(risk_group).strip() if risk_group is not None else ""
    return value.upper() if value else UNKNOWN_RISK_GROUP


def resolve_reference_nav(
    *, mode: str = DEVELOPMENT_EXPOSED, reference_nav: float | None = None
) -> tuple[float | None, str | None]:
    """Resolve the only allowed NAV source for the selected environment."""
    if mode == DEVELOPMENT_EXPOSED:
        if reference_nav is None:
            return 1.0, None
        if not math.isclose(float(reference_nav), 1.0, rel_tol=0.0, abs_tol=1e-12):
            return None, "DEVELOPMENT_REFERENCE_NAV_FIXED_AT_1_0"
        return 1.0, None
    if reference_nav is None:
        return None, PORTFOLIO_NAV_REQUIRED
    try:
        return _require_positive_finite(reference_nav, "reference_nav"), None
    except ValueError:
        return None, PORTFOLIO_NAV_REQUIRED


def initial_risk_capital(reference_nav: float) -> float:
    return _require_positive_finite(reference_nav, "reference_nav") * BASE_RISK_FRACTION


def _quality_rank(value: str) -> int:
    return {
        "HIGH_ASYMMETRY": 0,
        "HIGH_QUALITY": 1,
        "NORMAL": 2,
    }.get(str(value), 3)


def candidate_order_key(candidate: PortfolioCandidate) -> tuple[int, float, str]:
    """Frozen simultaneous-session order; no outcome data participates."""
    return (
        _quality_rank(candidate.rr_quality),
        -float(candidate.planned_rr),
        candidate.canonical_symbol,
    )


def portfolio_exposure(
    positions: Iterable[OpenPortfolioPosition], *, reference_nav: float
) -> PortfolioExposure:
    nav = _require_positive_finite(reference_nav, "reference_nav")
    total = 0.0
    by_group: defaultdict[str, float] = defaultdict(float)
    by_market: defaultdict[str, float] = defaultdict(float)
    count_by_market: defaultdict[str, int] = defaultdict(int)
    count = 0
    for position in positions:
        risk = position.remaining_loss_risk(nav)
        total += risk
        group = position.normalized_risk_group
        if group != UNKNOWN_RISK_GROUP:
            by_group[group] += risk
        by_market[str(position.market).upper()] += risk
        count_by_market[str(position.market).upper()] += 1
        count += 1
    return PortfolioExposure(
        total_open_risk_fraction=total,
        risk_by_group=dict(sorted(by_group.items())),
        risk_by_market=dict(sorted(by_market.items())),
        position_count_by_market=dict(sorted(count_by_market.items())),
        position_count=count,
    )


def candidate_from_decision(
    decision: object,
    *,
    source_setup: str,
    execution: object | None = None,
    risk_group: str | None = None,
    position_management_action: str | None = None,
) -> PortfolioCandidate:
    """Project an ENTRY_ALLOWED decision without changing the source object."""
    action = getattr(getattr(decision, "action", None), "value", getattr(decision, "action", None))
    if action != "ENTRY_ALLOWED":
        raise ValueError("Portfolio Risk only accepts ENTRY_ALLOWED decisions")
    planned_entry = getattr(decision, "planned_entry", None)
    execution_stop = getattr(decision, "execution_stop", None)
    rr = getattr(decision, "rr", None)
    if planned_entry is None or execution_stop is None or rr is None or not rr.rr_ratios:
        raise ValueError("ENTRY_ALLOWED decision is missing risk geometry")
    outcome = getattr(execution, "outcome", None) if execution is not None else None
    actual_entry = getattr(execution, "actual_entry", None) if execution is not None else None
    return PortfolioCandidate(
        event_identity=str(decision.event_identity),
        source_setup=str(source_setup),
        symbol=str(decision.symbol),
        market=str(decision.market),
        trade_date=decision.trade_date,
        planned_entry=float(planned_entry),
        execution_stop=float(execution_stop),
        planned_rr=float(rr.rr_ratios[0]),
        rr_quality=str(rr.quality),
        execution_outcome=str(outcome) if outcome is not None else None,
        execution_date=getattr(execution, "execution_date", None) if execution is not None else None,
        actual_entry=float(actual_entry) if actual_entry is not None else None,
        risk_group=normalize_risk_group(risk_group),
        position_management_action=(
            str(position_management_action)
            if position_management_action is not None
            else None
        ),
    )


class PortfolioRiskEngine:
    """State-light reservation engine with exact-once settlement."""

    def __init__(
        self,
        *,
        mode: str = DEVELOPMENT_EXPOSED,
        reference_nav: float | None = None,
        risk_group_metadata: Mapping[str, str] | None = None,
        existing_positions: Sequence[OpenPortfolioPosition] = (),
    ) -> None:
        self.mode = mode
        self.reference_nav, self.nav_error = resolve_reference_nav(
            mode=mode, reference_nav=reference_nav
        )
        self.risk_group_metadata = {
            canonical_symbol(symbol): normalize_risk_group(group)
            for symbol, group in (risk_group_metadata or {}).items()
        }
        self.existing_positions = tuple(existing_positions)
        self._settled_ids: set[str] = set()

    def _resolved_group(self, candidate: PortfolioCandidate) -> str:
        explicit = candidate.normalized_risk_group
        if explicit != UNKNOWN_RISK_GROUP:
            return explicit
        return self.risk_group_metadata.get(
            candidate.canonical_symbol, UNKNOWN_RISK_GROUP
        )

    def reserve(
        self, candidates: Iterable[PortfolioCandidate]
    ) -> PortfolioReservationBatch:
        ordered = tuple(sorted(tuple(candidates), key=candidate_order_key))
        if len({item.event_identity for item in ordered}) != len(ordered):
            raise ValueError("candidate event identities must be unique")
        if self.reference_nav is None:
            before = _empty_exposure()
        else:
            before = portfolio_exposure(
                self.existing_positions, reference_nav=self.reference_nav
            )
        total = before.total_open_risk_fraction
        groups = defaultdict(float, before.risk_by_group)
        symbols = {item.canonical_symbol for item in self.existing_positions}
        reservations: list[PortfolioReservation] = []
        for candidate in ordered:
            group = self._resolved_group(candidate)
            flags = (RISK_GROUP_UNKNOWN,) if group == UNKNOWN_RISK_GROUP else ()
            group_before = groups.get(group, 0.0)
            planned_size: PositionSize | None = None
            if self.reference_nav is not None:
                try:
                    planned_size = position_size(
                        initial_risk_capital(self.reference_nav),
                        candidate.planned_entry,
                        candidate.execution_stop,
                    )
                except ValueError:
                    planned_size = None

            reason = PORTFOLIO_ALLOWED
            status = PortfolioReservationStatus.RESERVED
            total_after = total + BASE_RISK_FRACTION
            group_after = group_before + BASE_RISK_FRACTION
            if self.nav_error is not None:
                status = PortfolioReservationStatus.BLOCKED
                reason = (
                    self.nav_error
                    if self.nav_error == PORTFOLIO_NAV_REQUIRED
                    else self.nav_error
                )
            elif candidate.position_management_action == "NO_ADD":
                status = PortfolioReservationStatus.BLOCKED
                reason = BLOCK_POSITION_MANAGEMENT_NO_ADD
            elif candidate.canonical_symbol in symbols:
                status = PortfolioReservationStatus.BLOCKED
                reason = BLOCK_EXISTING_POSITION_SAME_SYMBOL
            elif group == UNKNOWN_RISK_GROUP and self.mode == PRODUCTION:
                status = PortfolioReservationStatus.BLOCKED
                reason = BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION
            elif group != UNKNOWN_RISK_GROUP and group_after > MAX_RISK_PER_GROUP_FRACTION:
                status = PortfolioReservationStatus.BLOCKED
                reason = BLOCK_RISK_GROUP_CONCENTRATION
            elif total_after > MAX_TOTAL_OPEN_RISK_FRACTION:
                status = PortfolioReservationStatus.BLOCKED
                reason = BLOCK_TOTAL_RISK_BUDGET

            if status is PortfolioReservationStatus.RESERVED:
                symbols.add(candidate.canonical_symbol)
                total = total_after
                if group != UNKNOWN_RISK_GROUP:
                    groups[group] = group_after
            else:
                total_after = total
                group_after = group_before
            reservations.append(
                PortfolioReservation(
                    candidate=PortfolioCandidate(
                        **{
                            **vars(candidate),
                            "risk_group": group,
                        }
                    ),
                    status=status,
                    reason=reason,
                    advisory_flags=flags,
                    proposed_initial_risk_fraction=BASE_RISK_FRACTION,
                    total_risk_before=(total - BASE_RISK_FRACTION if status is PortfolioReservationStatus.RESERVED else total),
                    total_risk_after=total_after,
                    group_risk_before=group_before,
                    group_risk_after=group_after,
                    planned_position_size=planned_size,
                )
            )
        after_positions = list(self.existing_positions)
        # Reservations are represented as synthetic risk units for the batch
        # snapshot only; no position is created until T+1 execution settles.
        after = _exposure_with_reserved_units(
            before,
            reservations,
        )
        return PortfolioReservationBatch(
            ordered_candidate_ids=tuple(item.event_identity for item in ordered),
            reservations=tuple(reservations),
            exposure_before=before,
            exposure_after_reservations=after,
        )

    def settle(
        self,
        reservation: PortfolioReservation,
        *,
        outcome: str | None = None,
        execution_date: date | None = None,
        actual_entry: float | None = None,
    ) -> PortfolioSettlement:
        """Release failed T+1 reservations or create one executed position."""
        identity = reservation.reservation_id
        if identity in self._settled_ids:
            raise ValueError(f"reservation already settled: {identity}")
        self._settled_ids.add(identity)
        if reservation.status is not PortfolioReservationStatus.RESERVED:
            raise ValueError("only a RESERVED reservation can be settled")
        resolved_outcome = outcome if outcome is not None else reservation.candidate.execution_outcome
        resolved_entry = (
            actual_entry
            if actual_entry is not None
            else reservation.candidate.actual_entry
        )
        if resolved_outcome != "EXECUTED" or resolved_entry is None:
            return PortfolioSettlement(
                reservation=reservation,
                status=PortfolioReservationStatus.RELEASED,
                reason=RESERVATION_RELEASED_ON_FAILED_T1,
                position_size=None,
                position=None,
            )
        if self.reference_nav is None:
            return PortfolioSettlement(
                reservation=reservation,
                status=PortfolioReservationStatus.RELEASED,
                reason=PORTFOLIO_NAV_REQUIRED,
                position_size=None,
                position=None,
            )
        try:
            size = position_size(
                initial_risk_capital(self.reference_nav),
                float(resolved_entry),
                reservation.candidate.execution_stop,
            )
        except ValueError:
            return PortfolioSettlement(
                reservation=reservation,
                status=PortfolioReservationStatus.RELEASED,
                reason=BLOCK_INVALID_RISK_GEOMETRY,
                position_size=None,
                position=None,
            )
        position = OpenPortfolioPosition(
            source_event_identity=identity,
            source_setup=reservation.candidate.source_setup,
            symbol=reservation.candidate.symbol,
            market=reservation.candidate.market,
            entry_date=execution_date or reservation.candidate.execution_date or reservation.candidate.trade_date,
            quantity=size.theoretical_quantity,
            current_price=float(resolved_entry),
            active_protective_stop=reservation.candidate.execution_stop,
            risk_group=reservation.candidate.normalized_risk_group,
            actual_entry=float(resolved_entry),
        )
        return PortfolioSettlement(
            reservation=reservation,
            status=PortfolioReservationStatus.EXECUTED,
            reason="EXECUTED",
            position_size=size,
            position=position,
        )


def _empty_exposure() -> PortfolioExposure:
    return PortfolioExposure(0.0, {}, {}, {}, 0)


def _exposure_with_reserved_units(
    before: PortfolioExposure,
    reservations: Sequence[PortfolioReservation],
) -> PortfolioExposure:
    total = before.total_open_risk_fraction
    groups = defaultdict(float, before.risk_by_group)
    market_risk = defaultdict(float, before.risk_by_market)
    market_counts = defaultdict(int, before.position_count_by_market)
    count = before.position_count
    for item in reservations:
        if item.status is not PortfolioReservationStatus.RESERVED:
            continue
        total += item.proposed_initial_risk_fraction
        group = item.candidate.normalized_risk_group
        if group != UNKNOWN_RISK_GROUP:
            groups[group] += item.proposed_initial_risk_fraction
        market = item.candidate.market.upper()
        market_risk[market] += item.proposed_initial_risk_fraction
        market_counts[market] += 1
        count += 1
    return PortfolioExposure(
        total_open_risk_fraction=total,
        risk_by_group=dict(sorted(groups.items())),
        risk_by_market=dict(sorted(market_risk.items())),
        position_count_by_market=dict(sorted(market_counts.items())),
        position_count=count,
    )


def candidate_to_dict(value: PortfolioCandidate) -> dict[str, Any]:
    return {
        "event_identity": value.event_identity,
        "source_setup": value.source_setup,
        "symbol": value.symbol,
        "canonical_symbol": value.canonical_symbol,
        "market": value.market,
        "trade_date": value.trade_date.isoformat(),
        "planned_entry": value.planned_entry,
        "execution_stop": value.execution_stop,
        "planned_rr": value.planned_rr,
        "rr_quality": value.rr_quality,
        "execution_outcome": value.execution_outcome,
        "execution_date": value.execution_date.isoformat() if value.execution_date else None,
        "actual_entry": value.actual_entry,
        "risk_group": value.normalized_risk_group,
        "position_management_action": value.position_management_action,
    }


def _position_size_to_dict(value: PositionSize | None) -> dict[str, Any] | None:
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


def position_to_dict(value: OpenPortfolioPosition | None, *, reference_nav: float | None = None) -> dict[str, Any] | None:
    if value is None:
        return None
    remaining = None if reference_nav is None else value.remaining_loss_risk(reference_nav)
    return {
        "source_event_identity": value.source_event_identity,
        "source_setup": value.source_setup,
        "symbol": value.symbol,
        "canonical_symbol": value.canonical_symbol,
        "market": value.market,
        "entry_date": value.entry_date.isoformat(),
        "quantity": value.quantity,
        "current_price": value.current_price,
        "active_protective_stop": value.active_protective_stop,
        "actual_entry": value.actual_entry,
        "risk_group": value.normalized_risk_group,
        "remaining_loss_risk_fraction": remaining,
    }


def reservation_to_dict(value: PortfolioReservation) -> dict[str, Any]:
    return {
        "reservation_id": value.reservation_id,
        "candidate": candidate_to_dict(value.candidate),
        "status": value.status.value,
        "reason": value.reason,
        "advisory_flags": list(value.advisory_flags),
        "proposed_initial_risk_fraction": value.proposed_initial_risk_fraction,
        "total_risk_before": value.total_risk_before,
        "total_risk_after": value.total_risk_after,
        "group_risk_before": value.group_risk_before,
        "group_risk_after": value.group_risk_after,
        "planned_position_size": _position_size_to_dict(value.planned_position_size),
    }


def settlement_to_dict(value: PortfolioSettlement, *, reference_nav: float | None = None) -> dict[str, Any]:
    return {
        "reservation_id": value.reservation.reservation_id,
        "status": value.status.value,
        "reason": value.reason,
        "position_size": _position_size_to_dict(value.position_size),
        "position": position_to_dict(value.position, reference_nav=reference_nav),
    }


__all__ = [
    "BASE_RISK_FRACTION",
    "BLOCK_EXISTING_POSITION_SAME_SYMBOL",
    "BLOCK_INVALID_RISK_GEOMETRY",
    "BLOCK_POSITION_MANAGEMENT_NO_ADD",
    "BLOCK_RISK_GROUP_CONCENTRATION",
    "BLOCK_TOTAL_RISK_BUDGET",
    "BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION",
    "DEVELOPMENT_EXPOSED",
    "MAX_RISK_PER_GROUP_FRACTION",
    "MAX_TOTAL_OPEN_RISK_FRACTION",
    "OpenPortfolioPosition",
    "PORTFOLIO_ALLOWED",
    "PORTFOLIO_NAV_REQUIRED",
    "PortfolioCandidate",
    "PortfolioExposure",
    "PortfolioReservation",
    "PortfolioReservationBatch",
    "PortfolioReservationStatus",
    "PortfolioRiskEngine",
    "PortfolioSettlement",
    "PRODUCTION",
    "RISK_GROUP_UNKNOWN",
    "RESERVATION_RELEASED_ON_FAILED_T1",
    "UNKNOWN_RISK_GROUP",
    "candidate_from_decision",
    "candidate_order_key",
    "candidate_to_dict",
    "canonical_symbol",
    "initial_risk_capital",
    "normalize_risk_group",
    "portfolio_exposure",
    "position_to_dict",
    "reservation_to_dict",
    "resolve_reference_nav",
    "settlement_to_dict",
]

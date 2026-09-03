"""Prospective, read-only daily decision orchestration.

The chain composes the frozen Wave, SETUP_01/02 Decision/Risk, Portfolio Risk,
Position Management, and Wave5 contracts.  It deliberately owns no new
trading formula and has no Google Sheets, broker, holdings, or order-writing
path.  Production callers must inject authoritative universe, NAV, risk-group,
position-origin, and exchange-calendar inputs; missing prerequisites remain
visible and fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, datetime
from enum import Enum
from itertools import chain
import json
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from core import Quote
from research.market_sessions import DEVELOPMENT_SESSION_IDENTITY
from trading.models import DecisionAction, SetupState, Trend, validate_quote_series
from trading.portfolio_risk import (
    BASE_RISK_FRACTION,
    PORTFOLIO_ALLOWED,
    PORTFOLIO_NAV_REQUIRED,
    PRODUCTION,
    PortfolioCandidate,
    PortfolioReservation,
    PortfolioReservationStatus,
    PortfolioRiskEngine,
    OpenPortfolioPosition,
    PRODUCTION_OPEN_POSITION_ENTRY_BASIS_REQUIRED_FOR_RISK_ACCOUNTING,
    candidate_from_decision,
    initial_risk_capital,
    normalize_risk_group,
    reservation_to_dict,
    settlement_to_dict,
)
from trading.position_management import (
    POSITION_MANAGEMENT_PROTOCOL_VERSION,
    PositionAction,
    PositionOrigin,
    PositionReplay,
    position_origin_from_execution,
    position_replay_to_dict,
    replay_position,
)
from trading.setup01 import evaluate_setup01
from trading.setup01_decision import (
    Setup01Decision,
    evaluate_setup01_decision,
    execute_setup01_t1_open,
)
from trading.setup01_replay import Setup01ReplayEvent, Setup01ReplayReport, replay_setup01_history
from trading.setup02 import evaluate_setup02
from trading.setup02_decision import (
    Setup02Decision,
    evaluate_setup02_decision,
    execute_setup02_t1_open,
)
from trading.setup02_replay import Setup02ReplayEvent, Setup02ReplayReport, replay_setup02_history
from trading.wave import WAVE_ENGINE_PROTOCOL_VERSION, evaluate_wave_scenario, evaluation_to_dict
from trading.wave5_context import WAVE5_CONTEXT_PROTOCOL_VERSION


DAILY_DECISION_CHAIN_PROTOCOL_VERSION = "PROSPECTIVE-DAILY-DECISION-CHAIN-2026-09-02-v1"
PRODUCTION_STRATEGY_UNIVERSE_REQUIRED = "PRODUCTION_STRATEGY_UNIVERSE_REQUIRED"
PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED = (
    "PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED"
)
POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT = "POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT"
T1_EXECUTION_DATA_REQUIRED = "T1_EXECUTION_DATA_REQUIRED"
DATA_OK = "DATA_OK"
DATA_STALE = "DATA_STALE"
DATA_BAD = "DATA_BAD"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION = (
    "DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION"
)
PORTFOLIO_EXISTING_POSITION_CONFLICT = "PORTFOLIO_EXISTING_POSITION_CONFLICT"
PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED = "PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED"
PORTFOLIO_PENDING_RESERVATION_UNRESOLVED = "PORTFOLIO_PENDING_RESERVATION_UNRESOLVED"
POSITION_MANAGEMENT_OBSERVED = "POSITION_MANAGEMENT_OBSERVED"


class T1ExecutionPhase(str, Enum):
    DECISION_T = "DECISION_T"
    PENDING_T1_EXECUTION_CHECK = "PENDING_T1_EXECUTION_CHECK"
    T1_EXECUTION_OBSERVED = "T1_EXECUTION_OBSERVED"


DailyDecisionEventIdentity = str


@dataclass(frozen=True)
class CompletedSessionIdentity:
    """Identity for the completed T session, not merely a calendar date."""

    market: str
    trade_date: date
    identity: str
    exact_exchange_calendar: bool = False
    next_session_date: date | None = None
    session_dates: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        if not self.market or not self.identity:
            raise ValueError("completed session identity requires market and identity")
        dates = tuple(self.session_dates)
        if dates and (tuple(sorted(set(dates))) != dates or self.trade_date not in dates):
            raise ValueError("session_dates must be sorted, unique, and contain trade_date")
        if self.next_session_date is not None and self.next_session_date <= self.trade_date:
            raise ValueError("next_session_date must be later than trade_date")


@dataclass(frozen=True)
class OpenPositionState:
    """A caller-supplied current-position claim plus optional authority.

    ``origin=None`` is intentional: a holding can be known to exist while its
    system-created strategy origin is unavailable.  The chain never fills that
    gap from average cost, current price, or chart history.
    """

    symbol: str
    market: str
    origin: PositionOrigin | None = None
    portfolio_position: OpenPortfolioPosition | None = None

    @property
    def has_position(self) -> bool:
        return True


@dataclass(frozen=True)
class DailySymbolInput:
    symbol: str
    market: str
    as_of_date: date
    qfq_history: tuple[Quote, ...]
    data_quality_status: str
    completed_session_identity: CompletedSessionIdentity
    risk_group: str | None = None
    open_position_state: OpenPositionState | None = None

    def __post_init__(self) -> None:
        if not self.symbol or not self.market:
            raise ValueError("DailySymbolInput requires symbol and market")
        if self.completed_session_identity.market.upper() != self.market.upper():
            raise ValueError("completed session market differs from symbol input")
        if self.completed_session_identity.trade_date != self.as_of_date:
            raise ValueError("completed session date must equal as_of_date")
        history = tuple(self.qfq_history)
        object.__setattr__(self, "qfq_history", history)
        if history:
            validate_quote_series(list(history))
            if any(quote.symbol.upper() != self.symbol.upper() for quote in history):
                raise ValueError("qfq history contains a different symbol")
            if any(quote.market.upper() != self.market.upper() for quote in history):
                raise ValueError("qfq history contains a different market")
            if any(quote.trade_date > self.as_of_date for quote in history):
                raise ValueError("DailySymbolInput cannot contain data after T")
        position = self.open_position_state
        if position is not None and (
            position.symbol.upper() != self.symbol.upper()
            or position.market.upper() != self.market.upper()
        ):
            raise ValueError("open position identity differs from symbol input")


@dataclass(frozen=True)
class DailyPortfolioResult:
    status: str
    reason: str
    reservation_id: str | None
    advisory_flags: tuple[str, ...]
    total_risk_before: float | None
    total_risk_after: float | None
    group_risk_before: float | None
    group_risk_after: float | None
    proposed_initial_risk_fraction: float | None
    planned_quantity: float | None


@dataclass(frozen=True)
class DailyPositionManagementResult:
    status: str
    action: str | None
    current_r: float | None
    mfe_r: float | None
    mae_r: float | None
    mfe_drawdown_r: float | None
    active_stop_at_open: float | None
    active_stop_next_session: float | None
    target_status: str | None
    wave5_context: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DailyDecisionResult:
    symbol: str
    market: str
    as_of_date: date
    data_status: str
    weekly_state: str
    daily_state: str
    primary_wave_scenario: str
    alternate_wave_scenario: str
    setup01_state: str
    setup02_state: str
    setup01_event_identity: DailyDecisionEventIdentity | None
    setup02_event_identity: DailyDecisionEventIdentity | None
    new_confirmed_event_identity: DailyDecisionEventIdentity | None
    new_confirmed_event_identities: tuple[DailyDecisionEventIdentity, ...]
    event_was_new: bool
    individual_decision: Setup01Decision | Setup02Decision | None
    individual_decision_candidates: tuple[Any, ...]
    portfolio_result: DailyPortfolioResult | None
    position_management: DailyPositionManagementResult | None
    wave5_context: str
    primary_action: str
    execution_phase: T1ExecutionPhase | None
    execution_outcome: str | None
    reasons: tuple[str, ...]
    blocking_prerequisites: tuple[str, ...]
    protocol_versions: dict[str, str]
    generated_at: datetime
    final_status: str


@dataclass(frozen=True)
class DailyTradingDecisionReport:
    as_of_date: date
    results: tuple[DailyDecisionResult, ...]
    generated_at: datetime
    protocol_versions: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        sections: dict[str, list[dict[str, Any]]] = {
            section: [] for section in _REPORT_SECTIONS
        }
        for result in self.results:
            sections[_report_section(result)].append(daily_decision_result_to_dict(result))
        return {
            "protocol_versions": self.protocol_versions,
            "as_of_date": self.as_of_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "results": [daily_decision_result_to_dict(item) for item in self.results],
            "sections": sections,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Daily Trading Decision Report",
            "",
            f"- 日期：{self.as_of_date.isoformat()}",
            f"- 生成时间：{self.generated_at.isoformat()}",
            f"- 协议：{DAILY_DECISION_CHAIN_PROTOCOL_VERSION}",
            "",
        ]
        for section in _REPORT_SECTIONS:
            rows = [result for result in self.results if _report_section(result) == section]
            lines.extend([f"## {section}", ""])
            if not rows:
                lines.extend(["无", ""])
                continue
            for result in rows:
                decision = result.individual_decision
                entry = getattr(decision, "entry_zone_low", None)
                entry_high = getattr(decision, "entry_zone_high", None)
                targets = getattr(decision, "targets", ()) if decision else ()
                rr = getattr(decision, "rr", None)
                portfolio = result.portfolio_result
                pm = result.position_management
                lines.extend([
                    f"### {result.symbol}（{result.market}）",
                    "",
                    f"- 日期：{result.as_of_date.isoformat()}；数据状态：{result.data_status}",
                    f"- 周线：{result.weekly_state}；日线：{result.daily_state}",
                    f"- 主波浪：{result.primary_wave_scenario}；备选：{result.alternate_wave_scenario}",
                    f"- SETUP_01：{result.setup01_state}；SETUP_02：{result.setup02_state}",
                    f"- 决策动作：{result.primary_action}；执行阶段：{_value(result.execution_phase)}；执行结果：{result.execution_outcome or '—'}",
                    f"- Entry Zone：{_range(entry, entry_high)}；Stop：{getattr(decision, 'execution_stop', None) if decision else None}",
                    f"- T1/T2/T3：{_targets(targets)}；T1 RR：{_first_rr(rr)}；RR质量：{getattr(rr, 'quality', None) if rr else None}",
                    f"- Portfolio Risk：{portfolio.status + ' / ' + portfolio.reason if portfolio else '—'}",
                    f"- Position Management：{pm.status + ' / ' + (pm.action or '—') if pm else '—'}",
                    f"- Wave5 Context：{result.wave5_context}",
                    f"- 最终状态：{result.final_status}",
                    f"- 阻塞原因：{_join_reasons((*result.reasons, *result.blocking_prerequisites))}",
                    "",
                ])
        return "\n".join(lines)


class UniverseProvider(Protocol):
    def inputs(self) -> Sequence[DailySymbolInput]: ...


@dataclass(frozen=True)
class StaticUniverseProvider:
    """Synthetic/static adapter used by tests and read-only shadows."""

    values: tuple[DailySymbolInput, ...]

    def inputs(self) -> tuple[DailySymbolInput, ...]:
        return self.values


class DecisionStateStore(Protocol):
    def get_published_event(self, identity: str) -> DailyDecisionResult | None: ...
    def record_published_event(self, identity: str, result: DailyDecisionResult) -> None: ...
    def pending_for_symbol(self, symbol: str) -> tuple["PendingT1Decision", ...]: ...
    def save_pending(self, pending: "PendingT1Decision") -> None: ...
    def settle_pending(self, identity: str, record: "SettlementRecord") -> None: ...
    def get_settlement(self, identity: str) -> "SettlementRecord | None": ...
    def save_position_origin(self, origin: PositionOrigin) -> None: ...
    def get_position_origin(self, identity: str) -> PositionOrigin | None: ...
    def record_daily_result(self, result: DailyDecisionResult) -> None: ...


@dataclass(frozen=True)
class PendingT1Decision:
    event: Setup01ReplayEvent | Setup02ReplayEvent
    decision: Setup01Decision | Setup02Decision
    reservation: PortfolioReservation
    expected_execution_date: date | None


@dataclass(frozen=True)
class SettlementRecord:
    pending: PendingT1Decision
    execution: Any
    settlement: Any
    position_origin: PositionOrigin | None


class InMemoryDecisionStateStore:
    """Test/shadow store; not a claim of production persistence."""

    def __init__(self) -> None:
        self.published_events: dict[str, DailyDecisionResult] = {}
        self.pending: dict[str, PendingT1Decision] = {}
        self.settled: dict[str, SettlementRecord] = {}
        self.position_origins: dict[str, PositionOrigin] = {}
        self.daily_history: list[DailyDecisionResult] = []

    def get_published_event(self, identity: str) -> DailyDecisionResult | None:
        return self.published_events.get(identity)

    def record_published_event(self, identity: str, result: DailyDecisionResult) -> None:
        if identity in self.published_events:
            raise ValueError(f"published event already exists: {identity}")
        self.published_events[identity] = result

    def pending_for_symbol(self, symbol: str) -> tuple[PendingT1Decision, ...]:
        return tuple(
            item for item in self.pending.values() if item.event.symbol.upper() == symbol.upper()
        )

    def save_pending(self, pending: PendingT1Decision) -> None:
        identity = pending.event.event_identity
        if identity in self.pending or identity in self.settled:
            raise ValueError(f"T+1 decision already persisted: {identity}")
        self.pending[identity] = pending

    def settle_pending(self, identity: str, record: SettlementRecord) -> None:
        if identity in self.settled:
            raise ValueError(f"T+1 settlement already exists: {identity}")
        pending = self.pending.pop(identity, None)
        if pending is None:
            raise ValueError(f"pending T+1 decision not found: {identity}")
        if pending != record.pending:
            raise ValueError("settlement pending record differs from stored identity")
        self.settled[identity] = record

    def get_settlement(self, identity: str) -> SettlementRecord | None:
        return self.settled.get(identity)

    def save_position_origin(self, origin: PositionOrigin) -> None:
        if origin.source_event_identity in self.position_origins:
            raise ValueError(f"position origin already exists: {origin.source_event_identity}")
        self.position_origins[origin.source_event_identity] = origin

    def get_position_origin(self, identity: str) -> PositionOrigin | None:
        return self.position_origins.get(identity)

    def record_daily_result(self, result: DailyDecisionResult) -> None:
        self.daily_history.append(result)


@dataclass(frozen=True)
class DailyChainEvaluators:
    wave: Callable[..., Any] | None = None
    setup01: Callable[..., Any] | None = None
    setup02: Callable[..., Any] | None = None


class DailyDecisionChain:
    """Orchestrate one or more T-day prospective decisions."""

    def __init__(
        self,
        *,
        store: DecisionStateStore | None = None,
        evaluators: DailyChainEvaluators | None = None,
    ) -> None:
        self.store = store or InMemoryDecisionStateStore()
        self.evaluators = evaluators or DailyChainEvaluators()

    def evaluate(
        self,
        inputs: Iterable[DailySymbolInput],
        *,
        mode: str = PRODUCTION,
        reference_nav: float | None = None,
        existing_positions: Sequence[OpenPortfolioPosition] = (),
        generated_at: datetime | None = None,
    ) -> DailyTradingDecisionReport:
        values = tuple(inputs)
        if not values:
            raise ValueError("Daily Decision Chain requires at least one input")
        identities = [item.symbol.upper() for item in values]
        if len(set(identities)) != len(identities):
            raise ValueError("Daily Decision Chain input symbols must be unique")
        if len({item.as_of_date for item in values}) != 1:
            raise ValueError("Daily Decision Chain inputs must share one as_of_date")
        values = tuple(sorted(values, key=lambda item: (item.market, item.symbol)))
        generated = generated_at or datetime.now().astimezone()
        nav = self._resolved_nav(mode, reference_nav)
        settlement_context: dict[str, SettlementRecord] = {}
        settlement_blockers: dict[str, list[str]] = {}
        settlement_positions: list[OpenPortfolioPosition] = []
        unresolved_pending: list[PendingT1Decision] = []
        for item in values:
            for pending in self.store.pending_for_symbol(item.symbol):
                blocker = _pending_t1_data_blocker(item, pending)
                if blocker is not None:
                    settlement_blockers.setdefault(item.symbol.upper(), []).append(blocker)
                    unresolved_pending.append(pending)
                    continue
                settled = self._try_settle_pending(item, pending, mode, reference_nav)
                if settled is not None:
                    settlement_context[pending.event.event_identity] = settled
                    if settled.settlement.position is not None:
                        settlement_positions.append(settled.settlement.position)
                elif self.store.get_settlement(pending.event.event_identity) is None:
                    unresolved_pending.append(pending)

        prepared: list[dict[str, Any]] = []
        candidates: list[tuple[str, PortfolioCandidate]] = []
        portfolio_by_identity: dict[str, Any] = {}
        for item in values:
            row = self._evaluate_symbol(item, mode=mode, nav=nav, generated_at=generated)
            for blocker in settlement_blockers.get(item.symbol.upper(), ()):
                if blocker not in row["blocking"]:
                    row["blocking"].append(blocker)
            prepared.append(row)
            decision = row.get("individual_decision")
            event = row.get("selected_event")
            if (
                event is not None
                and row.get("event_was_new")
                and decision is not None
                and decision.action is DecisionAction.ENTRY_ALLOWED
            ):
                if unresolved_pending:
                    portfolio_by_identity[event.event_identity] = ValueError(
                        PORTFOLIO_PENDING_RESERVATION_UNRESOLVED
                    )
                    continue
                if _known_open_position_without_portfolio_risk_state(item):
                    portfolio_by_identity[event.event_identity] = ValueError(
                        PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED
                    )
                    continue
                try:
                    candidates.append((event.event_identity, candidate_from_decision(
                        decision,
                        source_setup=event.setup01.setup_type if hasattr(event, "setup01") else event.setup02.setup_type,
                        risk_group=item.risk_group,
                        position_management_action=(
                            row["position_management"].action
                            if row.get("position_management") is not None
                            else None
                        ),
                    )))
                except ValueError as exc:
                    row["portfolio_error"] = str(exc)

        if candidates:
            try:
                canonical_positions = _merge_authoritative_positions(
                    tuple(existing_positions) + tuple(settlement_positions),
                    values,
                )
                if any(position.actual_entry is None for position in canonical_positions):
                    raise ValueError(PRODUCTION_OPEN_POSITION_ENTRY_BASIS_REQUIRED_FOR_RISK_ACCOUNTING)
                portfolio_engine = PortfolioRiskEngine(
                    mode=mode,
                    reference_nav=reference_nav,
                    existing_positions=canonical_positions,
                )
                batch = portfolio_engine.reserve(candidate for _, candidate in candidates)
                portfolio_by_identity.update({
                    reservation.reservation_id: reservation
                    for reservation in batch.reservations
                })
            except (TypeError, ValueError) as exc:
                for identity, _ in candidates:
                    portfolio_by_identity[identity] = exc

        results: list[DailyDecisionResult] = []
        for item, row in zip(values, prepared):
            identity = row.get("selected_event").event_identity if row.get("selected_event") else None
            settlement = settlement_context.get(identity) if identity else None
            if settlement is None:
                settlement = next(
                    (
                        value
                        for value in settlement_context.values()
                        if value.pending.event.symbol.upper() == item.symbol.upper()
                    ),
                    None,
                )
            result = self._finalize_result(
                item,
                row,
                portfolio_by_identity.get(identity) if identity else None,
                settlement,
                mode=mode,
                generated_at=generated,
            )
            results.append(result)
            if result.event_was_new and result.new_confirmed_event_identities:
                for event_identity in result.new_confirmed_event_identities:
                    self.store.record_published_event(event_identity, result)
                reservation = portfolio_by_identity.get(result.new_confirmed_event_identity)
                if isinstance(reservation, PortfolioReservation) and reservation.status is PortfolioReservationStatus.RESERVED:
                    event = row["selected_event"]
                    expected = item.completed_session_identity.next_session_date
                    self.store.save_pending(PendingT1Decision(
                        event=event,
                        decision=result.individual_decision,
                        reservation=reservation,
                        expected_execution_date=expected,
                    ))
            self.store.record_daily_result(result)

        return DailyTradingDecisionReport(
            as_of_date=values[0].as_of_date,
            results=tuple(results),
            generated_at=generated,
            protocol_versions={
                "daily_chain": DAILY_DECISION_CHAIN_PROTOCOL_VERSION,
                "wave": WAVE_ENGINE_PROTOCOL_VERSION,
                "position_management": POSITION_MANAGEMENT_PROTOCOL_VERSION,
                "wave5": WAVE5_CONTEXT_PROTOCOL_VERSION,
            },
        )

    def _resolved_nav(self, mode: str, reference_nav: float | None) -> float | None:
        if mode == PRODUCTION:
            return reference_nav if reference_nav is not None and reference_nav > 0 else None
        return 1.0

    def _evaluate_symbol(
        self,
        item: DailySymbolInput,
        *,
        mode: str,
        nav: float | None,
        generated_at: datetime,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "wave": None,
            "setup01": None,
            "setup02": None,
            "selected_event": None,
            "individual_decision": None,
            "individual_decision_candidates": (),
            "event_was_new": False,
            "new_confirmed_event_identities": (),
            "reasons": [],
            "blocking": [],
            "position_management": None,
            "execution_phase": None,
            "execution_outcome": None,
        }
        if item.data_quality_status != DATA_OK:
            base["reasons"].append(f"DATA_QUALITY_{item.data_quality_status}")
            return base
        if not item.qfq_history or item.qfq_history[-1].trade_date != item.as_of_date:
            base["reasons"].append("QFQ_HISTORY_MUST_REACH_COMPLETED_SESSION_T")
            return base
        base["position_management"] = self._position_management(item)

        wave_fn = self.evaluators.wave or evaluate_wave_scenario
        setup01_fn = self.evaluators.setup01 or replay_setup01_history
        setup02_fn = self.evaluators.setup02 or replay_setup02_history
        try:
            wave = wave_fn(list(item.qfq_history), as_of_date=item.as_of_date)
            setup01 = setup01_fn(list(item.qfq_history), as_of_date=item.as_of_date)
            setup02 = setup02_fn(list(item.qfq_history), as_of_date=item.as_of_date)
        except (TypeError, ValueError) as exc:
            base["reasons"].append(f"UPSTREAM_EVALUATION_FAILED: {exc}")
            return base
        base.update(wave=wave, setup01=setup01, setup02=setup02)
        event01 = _new_confirmed_event(setup01, item.as_of_date)
        event02 = _new_confirmed_event(setup02, item.as_of_date)
        decisions: list[tuple[Any, Any]] = []
        risk_capital = initial_risk_capital(nav) if nav is not None else None
        for event, evaluator in ((event01, evaluate_setup01_decision), (event02, evaluate_setup02_decision)):
            if event is None:
                continue
            prior = self.store.get_published_event(event.event_identity)
            if prior is not None:
                decisions.append((event, prior.individual_decision))
                base["prior_result"] = prior
                base["reasons"].append(f"DUPLICATE_EVENT_SUPPRESSED: {event.event_identity}")
                continue
            try:
                decision = evaluator(event, item.qfq_history, risk_capital=risk_capital)
            except (TypeError, ValueError) as exc:
                base["reasons"].append(f"DECISION_EVALUATION_FAILED: {exc}")
                continue
            decisions.append((event, decision))
        new_events = tuple(
            event
            for event in (event01, event02)
            if event is not None
            and self.store.get_published_event(event.event_identity) is None
        )
        if len(new_events) > 1:
            identities = tuple(event.event_identity for event in new_events)
            base["reasons"].append(
                f"{DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION}: {', '.join(identities)}"
            )
            base["blocking"].append(DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION)
            base["individual_decision_candidates"] = tuple(
                decision for _, decision in decisions if decision is not None
            )
            base["event_was_new"] = True
            base["new_confirmed_event_identities"] = identities
            return base
        if decisions:
            # An ENTRY_ALLOWED decision is the only candidate for Portfolio Risk.
            # The frozen Wave/Setup contracts make two new CONFIRMED events on
            # one symbol/T unreachable; the guard above fail-closes if observed.
            selected_event, selected_decision = sorted(
                decisions,
                key=lambda pair: (
                    0 if pair[1] is not None and pair[1].action is DecisionAction.ENTRY_ALLOWED else 1,
                    0 if pair[0].event_identity.split("|SETUP_", 1)[-1].startswith("01") else 1,
                    pair[0].event_identity,
                ),
            )[0]
            base["selected_event"] = selected_event
            base["individual_decision"] = selected_decision
            base["individual_decision_candidates"] = tuple(decision for _, decision in decisions if decision is not None)
            base["event_was_new"] = self.store.get_published_event(selected_event.event_identity) is None
        else:
            current01 = setup01.current
            current02 = setup02.current
            if current01.state in {SetupState.WATCH, SetupState.ARMED} or current02.state in {SetupState.WATCH, SetupState.ARMED}:
                base["reasons"].append("等待新的 CONFIRMED event")
            else:
                base["reasons"].append("T 日没有新的 CONFIRMED event")
        return base

    def _position_management(self, item: DailySymbolInput) -> DailyPositionManagementResult | None:
        state = item.open_position_state
        if state is None:
            return None
        if state.origin is None:
            return DailyPositionManagementResult(
                status=POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT,
                action=None,
                current_r=None,
                mfe_r=None,
                mae_r=None,
                mfe_drawdown_r=None,
                active_stop_at_open=None,
                active_stop_next_session=None,
                target_status=None,
                wave5_context="NO_WAVE5_CONTEXT",
                reasons=(POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT,),
            )
        if not item.qfq_history or item.as_of_date < state.origin.entry_date:
            return DailyPositionManagementResult(
                status="POSITION_ENTRY_AFTER_AS_OF",
                action=None,
                current_r=None,
                mfe_r=None,
                mae_r=None,
                mfe_drawdown_r=None,
                active_stop_at_open=None,
                active_stop_next_session=None,
                target_status=None,
                wave5_context="NO_WAVE5_CONTEXT",
                reasons=("POSITION_ENTRY_AFTER_AS_OF",),
            )
        try:
            replay = replay_position(state.origin, item.qfq_history)
        except (TypeError, ValueError) as exc:
            return DailyPositionManagementResult(
                status="POSITION_MANAGEMENT_EVALUATION_FAILED",
                action=None,
                current_r=None,
                mfe_r=None,
                mae_r=None,
                mfe_drawdown_r=None,
                active_stop_at_open=None,
                active_stop_next_session=None,
                target_status=None,
                wave5_context="NO_WAVE5_CONTEXT",
                reasons=(str(exc),),
            )
        if not replay.days:
            return DailyPositionManagementResult(
                status="POSITION_MANAGEMENT_NO_VISIBLE_POSITION_DAY",
                action=None,
                current_r=None,
                mfe_r=None,
                mae_r=None,
                mfe_drawdown_r=None,
                active_stop_at_open=None,
                active_stop_next_session=None,
                target_status=None,
                wave5_context="NO_WAVE5_CONTEXT",
                reasons=("position origin has no visible as-of day",),
            )
        day = replay.days[-1]
        return DailyPositionManagementResult(
            status=POSITION_MANAGEMENT_OBSERVED,
            action=day.action.value,
            current_r=day.current_r,
            mfe_r=day.mfe_r,
            mae_r=day.mae_r,
            mfe_drawdown_r=day.mfe_drawdown_r,
            active_stop_at_open=day.active_stop_at_open,
            active_stop_next_session=day.active_stop_next_session,
            target_status=day.target_status.value,
            wave5_context=day.wave5_context.value,
            reasons=tuple(day.secondary_reasons),
        )

    def _try_settle_pending(
        self,
        item: DailySymbolInput,
        pending: PendingT1Decision,
        mode: str,
        reference_nav: float | None,
    ) -> SettlementRecord | None:
        expected = pending.expected_execution_date
        if not item.completed_session_identity.exact_exchange_calendar or expected is None:
            return None
        if item.as_of_date < expected:
            return None
        if _pending_t1_data_blocker(item, pending) is not None:
            return None
        settled = self.store.get_settlement(pending.event.event_identity)
        if settled is not None:
            return settled
        sessions = {item.market: (pending.event.trade_date, expected)}
        if hasattr(pending.event, "setup01"):
            execution = execute_setup01_t1_open(pending.decision, item.qfq_history, market_session_dates=sessions)
        else:
            execution = execute_setup02_t1_open(pending.decision, item.qfq_history, market_session_dates=sessions)
        if execution.outcome == "SKIP_NO_T1_BAR" and item.as_of_date == expected:
            return None
        try:
            engine = PortfolioRiskEngine(mode=mode, reference_nav=reference_nav)
            settlement = engine.settle(
                pending.reservation,
                outcome=execution.outcome,
                execution_date=execution.execution_date,
                actual_entry=execution.actual_entry,
            )
        except (TypeError, ValueError):
            return None
        origin = None
        if settlement.position is not None:
            source_setup = "SETUP_01" if hasattr(pending.event, "setup01") else "SETUP_02"
            try:
                origin = position_origin_from_execution(source_setup, pending.event, pending.decision, execution)
                if origin is not None:
                    self.store.save_position_origin(origin)
            except (TypeError, ValueError):
                origin = None
        record = SettlementRecord(pending, execution, settlement, origin)
        self.store.settle_pending(pending.event.event_identity, record)
        return record

    def _finalize_result(
        self,
        item: DailySymbolInput,
        row: dict[str, Any],
        portfolio_value: Any,
        settlement: SettlementRecord | None,
        *,
        mode: str,
        generated_at: datetime,
    ) -> DailyDecisionResult:
        wave = row.get("wave")
        setup01 = row.get("setup01")
        setup02 = row.get("setup02")
        decision = row.get("individual_decision")
        selected_event = row.get("selected_event")
        if settlement is not None:
            decision = settlement.pending.decision
            selected_event = settlement.pending.event
            row["event_was_new"] = False
            row["execution_phase"] = T1ExecutionPhase.T1_EXECUTION_OBSERVED
            row["execution_outcome"] = settlement.execution.outcome
            row["reasons"].append(f"T+1 execution observed: {settlement.execution.outcome}")
        portfolio_result = _portfolio_result(portfolio_value)
        prior_result = row.get("prior_result")
        if portfolio_result is None and settlement is None and prior_result is not None:
            portfolio_result = prior_result.portfolio_result
        if row.get("execution_phase") is None and settlement is None and prior_result is not None:
            row["execution_phase"] = prior_result.execution_phase
            row["execution_outcome"] = prior_result.execution_outcome
        if settlement is not None:
            portfolio_result = _portfolio_result(settlement.settlement.reservation)
        if decision is not None and decision.action is DecisionAction.ENTRY_ALLOWED:
            if settlement is None and portfolio_result is not None and portfolio_result.status == PORTFOLIO_ALLOWED:
                row["execution_phase"] = T1ExecutionPhase.PENDING_T1_EXECUTION_CHECK
                if not item.completed_session_identity.exact_exchange_calendar:
                    row["blocking"].append(PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED)
                elif item.completed_session_identity.next_session_date is None:
                    row["blocking"].append(PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED)
            primary_action = decision.action.value
        elif settlement is not None:
            primary_action = decision.action.value if decision is not None else "NO_TRADE"
        elif row.get("position_management") is not None:
            primary_action = row["position_management"].action or "HOLD"
        else:
            current01 = setup01.current.state if setup01 is not None else SetupState.NONE
            current02 = setup02.current.state if setup02 is not None else SetupState.NONE
            primary_action = DecisionAction.WAIT_CONFIRMATION.value if {current01, current02} & {SetupState.WATCH, SetupState.ARMED} else DecisionAction.NO_TRADE.value
        if (
            item.data_quality_status != DATA_OK
            or _position_management_is_prerequisite_failure(row.get("position_management"))
            or DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION in row.get("blocking", ())
            or T1_EXECUTION_DATA_REQUIRED in row.get("blocking", ())
        ):
            final_status = "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED"
        elif decision is not None and decision.action is DecisionAction.ENTRY_ALLOWED:
            final_status = "PORTFOLIO_ALLOWED" if portfolio_result is not None and portfolio_result.status == PORTFOLIO_ALLOWED else "PORTFOLIO_BLOCKED"
        elif row.get("position_management") is not None:
            final_status = "POSITION_MANAGEMENT"
        else:
            final_status = "NO_TRADE"
        setup01_current = setup01.current if setup01 is not None else None
        setup02_current = setup02.current if setup02 is not None else None
        event01 = _new_confirmed_event(setup01, item.as_of_date)
        event02 = _new_confirmed_event(setup02, item.as_of_date)
        selected_identity = selected_event.event_identity if selected_event is not None else None
        if selected_identity and not row.get("event_was_new"):
            published = self.store.get_published_event(selected_identity)
            if published is not None and decision is None:
                decision = published.individual_decision
        if row.get("event_was_new") and selected_identity is not None:
            new_identity = selected_identity
        else:
            new_identity = None
        new_identities = tuple(row.get("new_confirmed_event_identities", ()))
        if not new_identities and new_identity is not None:
            new_identities = (new_identity,)
        return DailyDecisionResult(
            symbol=item.symbol,
            market=item.market,
            as_of_date=item.as_of_date,
            data_status=item.data_quality_status,
            weekly_state=_value(getattr(wave, "weekly_state", Trend.UNKNOWN)),
            daily_state=_value(getattr(wave, "daily_state", Trend.UNKNOWN)),
            primary_wave_scenario=_scenario_family(getattr(wave, "primary_scenario", None)),
            alternate_wave_scenario=_scenario_family(getattr(wave, "alternate_scenario", None)),
            setup01_state=_value(getattr(setup01_current, "state", SetupState.NONE)),
            setup02_state=_value(getattr(setup02_current, "state", SetupState.NONE)),
            setup01_event_identity=event01.event_identity if event01 is not None else None,
            setup02_event_identity=event02.event_identity if event02 is not None else None,
            new_confirmed_event_identity=new_identity,
            new_confirmed_event_identities=new_identities,
            event_was_new=bool(row.get("event_was_new")),
            individual_decision=decision,
            individual_decision_candidates=tuple(row.get("individual_decision_candidates", ())),
            portfolio_result=portfolio_result,
            position_management=row.get("position_management"),
            wave5_context=(row["position_management"].wave5_context if row.get("position_management") else "NOT_APPLICABLE"),
            primary_action=primary_action,
            execution_phase=row.get("execution_phase"),
            execution_outcome=row.get("execution_outcome"),
            reasons=tuple(str(value) for value in row.get("reasons", ())),
            blocking_prerequisites=tuple(str(value) for value in row.get("blocking", ())),
            protocol_versions={
                "daily_chain": DAILY_DECISION_CHAIN_PROTOCOL_VERSION,
                "wave": WAVE_ENGINE_PROTOCOL_VERSION,
                "setup01": getattr(getattr(decision, "protocol_version", None), "__str__", lambda: "SETUP_01")(),
                "setup02": "SETUP-02-DECISION-RISK-2026-09-02-v2",
                "portfolio_risk": "PORTFOLIO-RISK-2026-09-02-v1",
                "position_management": POSITION_MANAGEMENT_PROTOCOL_VERSION,
                "wave5": WAVE5_CONTEXT_PROTOCOL_VERSION,
            },
            generated_at=generated_at,
            final_status=final_status,
        )


_REPORT_SECTIONS = (
    "需要关注",
    "ENTRY_ALLOWED但组合层阻塞",
    "PORTFOLIO_ALLOWED",
    "持仓管理",
    "NO_TRADE",
    "数据/生产前置条件异常",
)


def _new_confirmed_event(report: Any, as_of_date: date) -> Any | None:
    if report is None:
        return None
    events = tuple(
        event for event in getattr(report, "events", ())
        if event.event_type is SetupState.CONFIRMED
        and event.trade_date == as_of_date
        and getattr(
            getattr(event, "setup01", getattr(event, "setup02", None)),
            "is_new_confirmed_event_as_of",
            False,
        )
    )
    return events[0] if events else None


def _portfolio_result(value: Any) -> DailyPortfolioResult | None:
    if value is None:
        return None
    if isinstance(value, Exception):
        return DailyPortfolioResult(
            status="PORTFOLIO_BLOCKED",
            reason=str(value),
            reservation_id=None,
            advisory_flags=(),
            total_risk_before=None,
            total_risk_after=None,
            group_risk_before=None,
            group_risk_after=None,
            proposed_initial_risk_fraction=BASE_RISK_FRACTION,
            planned_quantity=None,
        )
    if isinstance(value, PortfolioReservation):
        planned = value.planned_position_size
        return DailyPortfolioResult(
            status=PORTFOLIO_ALLOWED if value.status is PortfolioReservationStatus.RESERVED else "PORTFOLIO_BLOCKED",
            reason=value.reason,
            reservation_id=value.reservation_id,
            advisory_flags=tuple(value.advisory_flags),
            total_risk_before=value.total_risk_before,
            total_risk_after=value.total_risk_after,
            group_risk_before=value.group_risk_before,
            group_risk_after=value.group_risk_after,
            proposed_initial_risk_fraction=value.proposed_initial_risk_fraction,
            planned_quantity=planned.theoretical_quantity if planned else None,
        )
    return None


def daily_decision_event_identity(event: Setup01ReplayEvent | Setup02ReplayEvent) -> DailyDecisionEventIdentity:
    """Reuse the frozen SETUP event identity; no second key is invented."""
    if event.event_type is not SetupState.CONFIRMED:
        raise ValueError("Daily Decision Chain identity requires CONFIRMED event")
    return event.event_identity


def _merge_authoritative_positions(
    global_positions: Sequence[OpenPortfolioPosition],
    values: Sequence[DailySymbolInput],
) -> tuple[OpenPortfolioPosition, ...]:
    """Merge global and per-symbol authoritative positions exactly once."""
    per_symbol_positions = tuple(
        item.open_position_state.portfolio_position
        for item in values
        if item.open_position_state is not None
        and item.open_position_state.portfolio_position is not None
    )
    merged: dict[str, OpenPortfolioPosition] = {}
    for position in chain(tuple(global_positions), per_symbol_positions):
        identity = position.canonical_symbol
        prior = merged.get(identity)
        if prior is None:
            merged[identity] = position
            continue
        prior_facts = (
            prior.source_event_identity,
            prior.actual_entry,
            prior.quantity,
            prior.active_protective_stop,
            prior.normalized_risk_group,
        )
        current_facts = (
            position.source_event_identity,
            position.actual_entry,
            position.quantity,
            position.active_protective_stop,
            position.normalized_risk_group,
        )
        if prior_facts != current_facts:
            raise ValueError(PORTFOLIO_EXISTING_POSITION_CONFLICT)
    return tuple(merged.values())


def _known_open_position_without_portfolio_risk_state(item: DailySymbolInput) -> bool:
    state = item.open_position_state
    return state is not None and state.has_position and state.portfolio_position is None


def _pending_t1_data_blocker(
    item: DailySymbolInput,
    pending: PendingT1Decision,
) -> str | None:
    expected = pending.expected_execution_date
    if expected is None or item.as_of_date < expected:
        return None
    if item.data_quality_status != DATA_OK:
        return T1_EXECUTION_DATA_REQUIRED
    expected_bars = tuple(
        quote
        for quote in item.qfq_history
        if quote.trade_date == expected
        and quote.symbol.upper() == item.symbol.upper()
        and quote.market.upper() == item.market.upper()
    )
    if len(expected_bars) != 1:
        return T1_EXECUTION_DATA_REQUIRED
    return None


def _position_management_is_prerequisite_failure(
    value: DailyPositionManagementResult | None,
) -> bool:
    return value is not None and value.status != POSITION_MANAGEMENT_OBSERVED


def require_production_universe(provider: UniverseProvider | None) -> tuple[DailySymbolInput, ...]:
    if provider is None:
        raise ValueError(PRODUCTION_STRATEGY_UNIVERSE_REQUIRED)
    values = tuple(provider.inputs())
    if not values:
        raise ValueError(PRODUCTION_STRATEGY_UNIVERSE_REQUIRED)
    return values


def daily_decision_result_to_dict(result: DailyDecisionResult) -> dict[str, Any]:
    return _serialise(result)


def daily_report_json(report: DailyTradingDecisionReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def _report_section(result: DailyDecisionResult) -> str:
    if (
        result.data_status != DATA_OK
        or _position_management_is_prerequisite_failure(result.position_management)
        or DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION in result.blocking_prerequisites
        or T1_EXECUTION_DATA_REQUIRED in result.blocking_prerequisites
    ):
        return "数据/生产前置条件异常"
    if result.position_management is not None:
        return "持仓管理"
    if result.individual_decision is not None and result.individual_decision.action is DecisionAction.ENTRY_ALLOWED:
        return "PORTFOLIO_ALLOWED" if result.final_status == "PORTFOLIO_ALLOWED" else "ENTRY_ALLOWED但组合层阻塞"
    if result.setup01_state in {SetupState.WATCH.value, SetupState.ARMED.value} or result.setup02_state in {SetupState.WATCH.value, SetupState.ARMED.value}:
        return "需要关注"
    return "NO_TRADE"


def _serialise(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _serialise(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _serialise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialise(item) for item in value]
    return value


def _value(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    return str(getattr(value, "value", value))


def _scenario_family(value: Any) -> str:
    return _value(getattr(value, "family", Trend.UNKNOWN))


def _range(low: Any, high: Any) -> str:
    return "—" if low is None or high is None else f"[{low}, {high}]"


def _targets(values: Sequence[Any]) -> str:
    values = tuple(values)
    return "/".join(str(value) for value in (*values[:3],)) or "—"


def _first_rr(value: Any) -> Any:
    ratios = getattr(value, "rr_ratios", ()) if value else ()
    return ratios[0] if ratios else None


def _join_reasons(values: Sequence[Any]) -> str:
    return "；".join(str(value) for value in values if value) or "无"


__all__ = [
    "CompletedSessionIdentity",
    "DATA_BAD",
    "DATA_OK",
    "DATA_STALE",
    "DATA_UNAVAILABLE",
    "DAILY_DECISION_CHAIN_PROTOCOL_VERSION",
    "DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION",
    "DailyChainEvaluators",
    "DailyDecisionChain",
    "DailyDecisionEventIdentity",
    "DailyDecisionResult",
    "DailyPortfolioResult",
    "DailyPositionManagementResult",
    "DailySymbolInput",
    "DailyTradingDecisionReport",
    "DecisionStateStore",
    "InMemoryDecisionStateStore",
    "OpenPositionState",
    "PendingT1Decision",
    "PRODUCTION_STRATEGY_UNIVERSE_REQUIRED",
    "PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED",
    "POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT",
    "PORTFOLIO_EXISTING_POSITION_CONFLICT",
    "PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED",
    "PORTFOLIO_PENDING_RESERVATION_UNRESOLVED",
    "POSITION_MANAGEMENT_OBSERVED",
    "StaticUniverseProvider",
    "T1_EXECUTION_DATA_REQUIRED",
    "T1ExecutionPhase",
    "daily_decision_event_identity",
    "daily_decision_result_to_dict",
    "daily_report_json",
    "require_production_universe",
]

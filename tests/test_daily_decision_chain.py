from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Quote
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DATA_BAD,
    DATA_OK,
    DATA_STALE,
    DATA_UNAVAILABLE,
    STRATEGY_PROPOSAL,
    STRATEGY_PROPOSAL_APPROVAL_REQUIRED,
    DailyChainEvaluators,
    DailyDecisionChain,
    DailySymbolInput,
    DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION,
    InMemoryDecisionStateStore,
    OpenPositionState,
    PORTFOLIO_EXISTING_POSITION_CONFLICT,
    PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED,
    PORTFOLIO_PENDING_RESERVATION_UNRESOLVED,
    POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT,
    PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED,
    T1_EXECUTION_DATA_REQUIRED,
    T1ExecutionPhase,
)
from trading.models import DecisionAction, Setup01Evaluation, SetupState, Trend
from trading.portfolio_risk import OpenPortfolioPosition
from trading.portfolio_risk import ALLOCATION_BUDGET_REQUIRED
from trading.position_management import PositionAnchor, PositionOrigin, PositionTarget
from trading.setup01_replay import Setup01ReplayDay, Setup01ReplayEvent, Setup01ReplayReport


START = date(2026, 1, 5)


def _quote(
    day: date,
    close: float,
    opening: float | None = None,
    *,
    symbol: str = "CHAIN.SYNTH",
) -> Quote:
    opening = close if opening is None else opening
    return Quote(
        symbol=symbol,
        name="Daily chain synthetic",
        market="US",
        trade_date=day,
        source="synthetic",
        open=opening,
        high=max(opening, close) + 1.0,
        low=min(opening, close) - 1.0,
        close=close,
        preclose=None,
        pct_change=None,
        volume=100.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _snapshot(day: date, state: SetupState) -> Setup01Evaluation:
    return Setup01Evaluation(
        setup_type="SETUP_01",
        protocol_version="SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1",
        state=state,
        as_of_date=day,
        wave1_origin=None,
        wave1_peak=None,
        wave2_low=None,
        fib_retracement_ratio=None,
        fib_retracement_region=None,
        confirmation_level=None,
        structural_invalidation=None,
        wave_scenario_invalidation=None,
        wave1_origin_confirmed_date=None,
        wave1_peak_confirmed_date=None,
        wave2_low_confirmed_date=None,
        state_entered_index=0,
        state_entered_date=day,
        confirmed_index=0 if state is SetupState.CONFIRMED else None,
        confirmed_date=day if state is SetupState.CONFIRMED else None,
        failed_index=None,
        failed_date=None,
        primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
        alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
        reason="synthetic",
        terminal_event_type=state if state is SetupState.CONFIRMED else None,
        terminal_event_date=day if state is SetupState.CONFIRMED else None,
        is_new_confirmed_event_as_of=state is SetupState.CONFIRMED,
        is_live_preconfirmation_candidate=state in {SetupState.WATCH, SetupState.ARMED},
        lifecycle_index=1,
    )


def _fixture(*, confirmed: bool = True, t1: bool = False, symbol: str = "CHAIN.SYNTH"):
    t_day = START + timedelta(days=20)
    history = tuple(
        _quote(
            START + timedelta(days=index),
            100.0 + index * 0.1,
            symbol=symbol,
        )
        for index in range(21)
    )
    if t1:
        history += (_quote(t_day + timedelta(days=1), 100.0, opening=100.0, symbol=symbol),)
    snapshot = _snapshot(t_day, SetupState.CONFIRMED if confirmed else SetupState.NONE)
    event = Setup01ReplayEvent(
        event_identity=f"{symbol}|SETUP_01|{t_day.isoformat()}|CONFIRMED|lifecycle=1",
        symbol=symbol,
        trade_date=t_day,
        event_type=SetupState.CONFIRMED,
        setup01=snapshot,
        market="US",
    )
    report = Setup01ReplayReport(
        symbol=symbol,
        market="US",
        days=(Setup01ReplayDay("CHAIN.SYNTH", t_day, snapshot),),
        events=(event,) if confirmed else (),
    )
    no_setup = Setup01ReplayReport(
        symbol=symbol,
        market="US",
        days=(Setup01ReplayDay("CHAIN.SYNTH", t_day, _snapshot(t_day, SetupState.NONE)),),
        events=(),
    )
    wave = SimpleNamespace(
        weekly_state=Trend.UPTREND,
        daily_state=Trend.UPTREND,
        primary_scenario=SimpleNamespace(family="WAVE_2_TO_3_CANDIDATE"),
        alternate_scenario=SimpleNamespace(family="ABC_CORRECTION_CANDIDATE"),
    )
    evaluators = DailyChainEvaluators(
        wave=lambda *_args, **_kwargs: wave,
        setup01=lambda *_args, **_kwargs: report if confirmed else no_setup,
        setup02=lambda *_args, **_kwargs: no_setup,
    )
    return history, t_day, event, evaluators


def _decision(event, *, action=DecisionAction.ENTRY_ALLOWED):
    rr = SimpleNamespace(rr_ratios=(2.5,), quality="NORMAL")
    candidate = SimpleNamespace(price=130.0, source="CONFIRMED_SWING_HIGH", provenance=("synthetic",))
    return SimpleNamespace(
        protocol_version="SETUP-01-DECISION-RISK-SYNTHETIC",
        event_identity=event.event_identity,
        symbol=event.symbol,
        market=event.market,
        trade_date=event.trade_date,
        action=action,
        entry_zone_low=100.0,
        entry_zone_high=105.0,
        planned_entry=102.0,
        execution_stop=90.0,
        structural_invalidation=95.0,
        targets=(130.0, 140.0, 150.0),
        target_candidates=(candidate, candidate, candidate),
        rr=rr,
    )


def _input(history, day, *, quality=DATA_OK, exact=False, next_day=None, risk_group=None, position=None):
    symbol = history[0].symbol if history else "CHAIN.SYNTH"
    return DailySymbolInput(
        symbol=symbol,
        market="US",
        as_of_date=day,
        qfq_history=history,
        data_quality_status=quality,
        completed_session_identity=CompletedSessionIdentity(
            market="US",
            trade_date=day,
            identity="SYNTHETIC_EXACT_SESSION_SET" if exact else "OBSERVED_SESSION_ONLY",
            exact_exchange_calendar=exact,
            next_session_date=next_day,
            session_dates=(day, next_day) if exact and next_day else (day,),
        ),
        risk_group=risk_group,
        open_position_state=position,
    )


def _position_origin(symbol: str = "CHAIN.SYNTH") -> PositionOrigin:
    anchor = PositionAnchor(
        name="LOW0",
        kind="LOW",
        price=90.0,
        pivot_index=0,
        pivot_date=START,
        confirmed_index=0,
        confirmed_date=START,
    )
    return PositionOrigin(
        source_setup="SETUP_01",
        source_event_identity=f"origin-{symbol}",
        symbol=symbol,
        market="US",
        entry_date=START,
        actual_entry=102.0,
        initial_execution_stop=90.0,
        initial_structural_invalidation=95.0,
        targets=(PositionTarget(130.0, "SYNTHETIC", ("test",)),),
        wave_anchors=(anchor,),
        initial_risk_per_share=12.0,
    )


def _portfolio_position(
    symbol: str = "CHAIN.SYNTH",
    *,
    source_event_identity: str = "held-event",
    actual_entry: float = 102.0,
    active_protective_stop: float = 90.0,
    quantity: float = 1.0,
) -> OpenPortfolioPosition:
    return OpenPortfolioPosition(
        source_event_identity=source_event_identity,
        source_setup="SETUP_01",
        symbol=symbol,
        market="US",
        entry_date=START,
        quantity=quantity,
        current_price=105.0,
        active_protective_stop=active_protective_stop,
        risk_group="GROUP_A",
        actual_entry=actual_entry,
    )


class ProtocolOnlyDecisionStore:
    """Protocol adapter intentionally exposing no InMemory concrete fields."""

    def __init__(self) -> None:
        self._delegate = InMemoryDecisionStateStore()

    def get_published_event(self, identity):
        return self._delegate.get_published_event(identity)

    def record_published_event(self, identity, result):
        self._delegate.record_published_event(identity, result)

    def pending_for_symbol(self, symbol):
        return self._delegate.pending_for_symbol(symbol)

    def save_pending(self, pending):
        self._delegate.save_pending(pending)

    def settle_pending(self, identity, record):
        self._delegate.settle_pending(identity, record)

    def get_settlement(self, identity):
        return self._delegate.get_settlement(identity)

    def save_position_origin(self, origin):
        self._delegate.save_position_origin(origin)

    def record_daily_result(self, result):
        self._delegate.record_daily_result(result)


class DailyDecisionChainTests(unittest.TestCase):
    def test_input_rejects_future_bars_and_preserves_as_of_boundary(self):
        history, t_day, _, _ = _fixture()
        with self.assertRaises(ValueError):
            _input(history + (_quote(t_day + timedelta(days=1), 101.0),), t_day)

    def test_no_setup_is_no_trade(self):
        history, t_day, _, evaluators = _fixture(confirmed=False)
        report = DailyDecisionChain(evaluators=evaluators).evaluate(
            [_input(history, t_day)], mode="DEVELOPMENT_EXPOSED", generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
        )
        result = report.results[0]
        self.assertEqual(result.primary_action, "NO_TRADE")
        self.assertIsNone(result.individual_decision)

    def test_new_confirmed_event_is_evaluated_once_and_calendar_disables_t1(self):
        history, t_day, event, evaluators = _fixture()
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = chain.evaluate([_input(history, t_day)], mode="DEVELOPMENT_EXPOSED").results[0]
            duplicate = chain.evaluate([_input(history, t_day)], mode="DEVELOPMENT_EXPOSED").results[0]
        self.assertEqual(result.new_confirmed_event_identity, event.event_identity)
        self.assertEqual(result.execution_phase, T1ExecutionPhase.PENDING_T1_EXECUTION_CHECK)
        self.assertIn(PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED, result.blocking_prerequisites)
        self.assertIsNone(duplicate.new_confirmed_event_identity)
        self.assertIn(event.event_identity, store.published_events)
        self.assertEqual(len(store.published_events), 1)

    def test_strategy_proposal_does_not_require_nav(self):
        history, t_day, event, evaluators = _fixture()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day)], mode="PRODUCTION"
            ).results[0]
        self.assertEqual(result.individual_decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertIsNone(getattr(result.individual_decision, "position_size", None))
        self.assertIsNone(result.portfolio_result)
        self.assertEqual(result.execution_phase, T1ExecutionPhase.DECISION_T)
        self.assertEqual(result.final_status, STRATEGY_PROPOSAL)

    def test_explicit_allocation_budget_is_required_and_applied_after_proposal(self):
        history, t_day, event, evaluators = _fixture()
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            proposal_report = chain.evaluate(
                [_input(history, t_day, risk_group="TECH")], mode="PRODUCTION"
            )
            proposal = proposal_report.results[0]
            self.assertEqual(store.pending, {})
            allocated = chain.evaluate(
                [_input(history, t_day, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
        self.assertEqual(proposal.final_status, STRATEGY_PROPOSAL)
        self.assertIsNone(proposal.portfolio_result)
        self.assertEqual(
            proposal_report.to_dict()["sections"][STRATEGY_PROPOSAL][0]["final_status"],
            STRATEGY_PROPOSAL,
        )
        self.assertEqual(allocated.final_status, "PORTFOLIO_ALLOWED")
        self.assertAlmostEqual(allocated.portfolio_result.planned_quantity, 5000.0 * 0.005 / 12.0)
        self.assertIn(event.event_identity, store.pending)

    def test_budget_is_not_approval(self):
        history, t_day, event, evaluators = _fixture()
        store = InMemoryDecisionStateStore()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(store=store, evaluators=evaluators).evaluate(
                [_input(history, t_day, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(),
            ).results[0]
        self.assertEqual(result.final_status, STRATEGY_PROPOSAL)
        self.assertEqual(result.individual_decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertIsNone(getattr(result.individual_decision, "position_size", None))
        self.assertIsNone(result.portfolio_result)
        self.assertIn(STRATEGY_PROPOSAL_APPROVAL_REQUIRED, result.reasons)
        self.assertEqual(store.pending, {})

    def test_approval_requires_prior_published_proposal(self):
        history, t_day, event, evaluators = _fixture()
        store = InMemoryDecisionStateStore()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(store=store, evaluators=evaluators).evaluate(
                [_input(history, t_day, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
        self.assertEqual(result.final_status, STRATEGY_PROPOSAL)
        self.assertIsNone(result.portfolio_result)
        self.assertEqual(store.pending, {})
        self.assertIn(STRATEGY_PROPOSAL_APPROVAL_REQUIRED, result.reasons)

    def test_approval_without_budget_keeps_proposal_and_does_not_persist(self):
        history, t_day, event, evaluators = _fixture()
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate(
                [_input(history, t_day, risk_group="TECH")], mode="PRODUCTION"
            )
            result = chain.evaluate(
                [_input(history, t_day, risk_group="TECH")],
                mode="PRODUCTION",
                approved_event_identities=(event.event_identity,),
            ).results[0]
        self.assertEqual(result.final_status, STRATEGY_PROPOSAL)
        self.assertIsNone(result.portfolio_result)
        self.assertIn(ALLOCATION_BUDGET_REQUIRED, result.reasons)
        self.assertEqual(store.pending, {})

    def test_selective_approval_allocates_only_the_approved_event_identity(self):
        history_a, t_day, event_a, evaluators_a = _fixture(symbol="SYMBOL_A")
        history_b, _, event_b, evaluators_b = _fixture(symbol="SYMBOL_B")
        store = InMemoryDecisionStateStore()
        evaluators = DailyChainEvaluators(
            wave=evaluators_a.wave,
            setup01=lambda history, **kwargs: (
                evaluators_a.setup01(history, **kwargs)
                if history[0].symbol == "SYMBOL_A"
                else evaluators_b.setup01(history, **kwargs)
            ),
            setup02=evaluators_a.setup02,
        )
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        inputs = [
            _input(history_a, t_day, risk_group="GROUP_A"),
            _input(history_b, t_day, risk_group="GROUP_B"),
        ]
        with patch(
            "trading.daily_decision_chain.evaluate_setup01_decision",
            side_effect=lambda event, *_args, **_kwargs: _decision(event),
        ):
            proposals = chain.evaluate(inputs, mode="PRODUCTION")
            allocated = chain.evaluate(
                inputs,
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event_a.event_identity,),
            )
        results = {result.symbol: result for result in allocated.results}
        self.assertEqual(
            {result.final_status for result in proposals.results},
            {STRATEGY_PROPOSAL},
        )
        self.assertEqual(results["SYMBOL_A"].final_status, "PORTFOLIO_ALLOWED")
        self.assertEqual(results["SYMBOL_A"].portfolio_result.reservation_id, event_a.event_identity)
        self.assertEqual(results["SYMBOL_B"].final_status, STRATEGY_PROPOSAL)
        self.assertIsNone(results["SYMBOL_B"].portfolio_result)
        self.assertIn(STRATEGY_PROPOSAL_APPROVAL_REQUIRED, results["SYMBOL_B"].reasons)
        self.assertEqual(set(store.pending), {event_a.event_identity})
        self.assertNotIn(event_b.event_identity, store.pending)

    def test_existing_position_and_approved_proposal_share_total_budget_denominator(self):
        history, t_day, event, evaluators = _fixture()
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        existing = _portfolio_position(
            symbol="SYSTEM_HELD",
            source_event_identity="held-event",
            actual_entry=100.0,
            active_protective_stop=90.0,
            quantity=1.0,
        )
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate(
                [_input(history, t_day, risk_group="TECH")], mode="PRODUCTION"
            )
            result = chain.evaluate(
                [_input(history, t_day, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event.event_identity,),
                existing_positions=(existing,),
            ).results[0]
        self.assertEqual(result.final_status, "PORTFOLIO_ALLOWED")
        self.assertAlmostEqual(result.portfolio_result.total_risk_before, 10.0 / 5000.0)
        self.assertAlmostEqual(result.portfolio_result.total_risk_after, 10.0 / 5000.0 + 0.005)

    def test_production_t1_reuses_frozen_budget_without_second_budget(self):
        history, t_day, event, evaluators = _fixture(t1=True)
        t1 = t_day + timedelta(days=1)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            proposal = chain.evaluate(
                [_input(history[:21], t_day, exact=True, next_day=t1, risk_group="TECH")],
                mode="PRODUCTION",
            ).results[0]
            allocated = chain.evaluate(
                [_input(history[:21], t_day, exact=True, next_day=t1, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
            self.assertEqual(set(store.pending), {event.event_identity})
            settled = chain.evaluate(
                [_input(history, t1, exact=True)], mode="PRODUCTION"
            ).results[0]
        self.assertEqual(proposal.final_status, STRATEGY_PROPOSAL)
        self.assertEqual(allocated.final_status, "PORTFOLIO_ALLOWED")
        self.assertEqual(settled.execution_phase, T1ExecutionPhase.T1_EXECUTION_OBSERVED)
        self.assertEqual(set(store.settled), {event.event_identity})
        self.assertAlmostEqual(
            store.settled[event.event_identity].settlement.position_size.risk_capital,
            5000.0 * 0.005,
        )

    def test_approval_of_pending_or_settled_identity_fails_closed_without_duplicate(self):
        history, t_day, event, evaluators = _fixture(t1=True)
        t1 = t_day + timedelta(days=1)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate(
                [_input(history[:21], t_day, exact=True, next_day=t1, risk_group="TECH")],
                mode="PRODUCTION",
            )
            allocated = chain.evaluate(
                [_input(history[:21], t_day, exact=True, next_day=t1, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
            self.assertEqual(set(store.pending), {event.event_identity})
            reservation_id = allocated.portfolio_result.reservation_id
            self.assertIsNotNone(reservation_id)
            repeated = chain.evaluate(
                [_input(history[:21], t_day, exact=True, next_day=t1, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
            self.assertEqual(set(store.pending), {event.event_identity})
            self.assertEqual(
                store.pending[event.event_identity].reservation.reservation_id,
                reservation_id,
            )
            self.assertIsNone(repeated.portfolio_result)
            settled = chain.evaluate(
                [_input(history, t1, exact=True)], mode="PRODUCTION"
            ).results[0]
            self.assertEqual(set(store.settled), {event.event_identity})
            self.assertEqual(set(store.pending), set())
            reapproved_after_settlement = chain.evaluate(
                [_input(history[:21], t_day, exact=True, next_day=t1, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=5000.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
        self.assertEqual(settled.execution_phase, T1ExecutionPhase.T1_EXECUTION_OBSERVED)
        self.assertEqual(set(store.pending), set())
        self.assertEqual(set(store.settled), {event.event_identity})
        self.assertIsNone(reapproved_after_settlement.portfolio_result)
        self.assertEqual(reapproved_after_settlement.final_status, STRATEGY_PROPOSAL)

    def test_unknown_group_blocks_production_but_development_allows(self):
        history, t_day, event, evaluators = _fixture()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            store = InMemoryDecisionStateStore()
            chain = DailyDecisionChain(store=store, evaluators=evaluators)
            chain.evaluate([_input(history, t_day)], mode="PRODUCTION")
            production = chain.evaluate(
                [_input(history, t_day)],
                mode="PRODUCTION",
                allocation_budget=1.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
        self.assertEqual(production.portfolio_result.reason, "BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION")
        store = InMemoryDecisionStateStore()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            development = DailyDecisionChain(store=store, evaluators=evaluators).evaluate(
                [_input(history, t_day)], mode="DEVELOPMENT_EXPOSED"
            ).results[0]
        self.assertEqual(development.final_status, "PORTFOLIO_ALLOWED")

    def test_exact_calendar_settles_only_exact_t1_and_is_exact_once(self):
        history, t_day, event, evaluators = _fixture(t1=True)
        t1 = t_day + timedelta(days=1)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with unittest.mock.patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            first = chain.evaluate([_input(history[:21], t_day, exact=True, next_day=t1)], mode="DEVELOPMENT_EXPOSED").results[0]
            settled = chain.evaluate([_input(history, t1, exact=True)], mode="DEVELOPMENT_EXPOSED").results[0]
            rerun = chain.evaluate([_input(history, t1, exact=True)], mode="DEVELOPMENT_EXPOSED").results[0]
        self.assertEqual(first.execution_phase, T1ExecutionPhase.PENDING_T1_EXECUTION_CHECK)
        self.assertEqual(settled.execution_phase, T1ExecutionPhase.T1_EXECUTION_OBSERVED)
        self.assertEqual(settled.execution_outcome, "EXECUTED")
        self.assertEqual(len(store.settled), 1)
        self.assertIsNone(rerun.execution_outcome)

    def test_non_ok_t1_data_keeps_pending_without_execution_settlement_or_origin(self):
        history, t_day, event, evaluators = _fixture(t1=True)
        t1 = t_day + timedelta(days=1)
        for quality in (DATA_BAD, DATA_STALE, DATA_UNAVAILABLE):
            with self.subTest(quality=quality):
                store = InMemoryDecisionStateStore()
                chain = DailyDecisionChain(store=store, evaluators=evaluators)
                with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
                    chain.evaluate(
                        [_input(history[:21], t_day, exact=True, next_day=t1)],
                        mode="DEVELOPMENT_EXPOSED",
                    )
                    with patch(
                        "trading.daily_decision_chain.execute_setup01_t1_open",
                        side_effect=AssertionError("non-OK T+1 data must not execute"),
                    ):
                        result = chain.evaluate(
                            [_input(history, t1, exact=True, quality=quality)],
                            mode="DEVELOPMENT_EXPOSED",
                        ).results[0]
                self.assertIn(T1_EXECUTION_DATA_REQUIRED, result.blocking_prerequisites)
                self.assertEqual(result.final_status, "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED")
                self.assertEqual(set(store.pending), {event.event_identity})
                self.assertEqual(store.settled, {})
                self.assertEqual(store.position_origins, {})

    def test_missing_expected_t1_bar_keeps_pending_without_strategy_skip_settlement(self):
        history, t_day, event, evaluators = _fixture(t1=True)
        t1 = t_day + timedelta(days=1)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate(
                [_input(history[:21], t_day, exact=True, next_day=t1)],
                mode="DEVELOPMENT_EXPOSED",
            )
            with patch(
                "trading.daily_decision_chain.execute_setup01_t1_open",
                side_effect=AssertionError("missing expected T+1 bar must not execute"),
            ):
                result = chain.evaluate(
                    [_input(history[:21], t1, exact=True)],
                    mode="DEVELOPMENT_EXPOSED",
                ).results[0]
        self.assertIn(T1_EXECUTION_DATA_REQUIRED, result.blocking_prerequisites)
        self.assertEqual(result.final_status, "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED")
        self.assertEqual(set(store.pending), {event.event_identity})
        self.assertEqual(store.settled, {})
        self.assertEqual(store.position_origins, {})

    def test_stale_data_never_runs_upstream_chain(self):
        history, t_day, _, evaluators = _fixture()
        position = OpenPositionState(
            "CHAIN.SYNTH",
            "US",
            origin=_position_origin(),
        )
        with patch("trading.daily_decision_chain.replay_position") as replay:
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day, quality=DATA_BAD, position=position)],
                mode="PRODUCTION",
            ).results[0]
        replay.assert_not_called()
        self.assertEqual(result.final_status, "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED")
        self.assertIn("DATA_QUALITY_DATA_BAD", result.reasons)
        self.assertIsNone(result.position_management)

    def test_per_symbol_authoritative_position_blocks_same_symbol_without_global_input(self):
        history, t_day, event, evaluators = _fixture()
        position = _portfolio_position()
        state = OpenPositionState("CHAIN.SYNTH", "US", portfolio_position=position)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day, position=state)],
                mode="DEVELOPMENT_EXPOSED",
            ).results[0]
        self.assertEqual(result.portfolio_result.reason, "BLOCK_EXISTING_POSITION_SAME_SYMBOL")
        self.assertEqual(result.portfolio_result.total_risk_before, position.remaining_loss_risk(1.0))

    def test_global_position_outside_strategy_inputs_still_consumes_risk(self):
        history, t_day, event, evaluators = _fixture()
        outside_position = _portfolio_position(symbol="OUTSIDE.SYNTH", quantity=0.001)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day)],
                mode="DEVELOPMENT_EXPOSED",
                existing_positions=(outside_position,),
            ).results[0]
        self.assertEqual(result.portfolio_result.status, "PORTFOLIO_ALLOWED")
        self.assertEqual(
            result.portfolio_result.total_risk_before,
            outside_position.remaining_loss_risk(1.0),
        )

    def test_global_and_per_symbol_same_position_is_counted_once(self):
        history, t_day, event, evaluators = _fixture()
        position = _portfolio_position()
        state = OpenPositionState("CHAIN.SYNTH", "US", portfolio_position=position)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day, position=state)],
                mode="DEVELOPMENT_EXPOSED",
                existing_positions=(position,),
            ).results[0]
        self.assertEqual(result.portfolio_result.reason, "BLOCK_EXISTING_POSITION_SAME_SYMBOL")
        self.assertEqual(result.portfolio_result.total_risk_before, position.remaining_loss_risk(1.0))

    def test_global_and_per_symbol_conflicting_position_fails_closed(self):
        history, t_day, event, evaluators = _fixture()
        global_position = _portfolio_position(source_event_identity="global-event")
        per_symbol_position = _portfolio_position(
            source_event_identity="per-symbol-event",
            actual_entry=103.0,
        )
        state = OpenPositionState(
            "CHAIN.SYNTH",
            "US",
            portfolio_position=per_symbol_position,
        )
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day, position=state)],
                mode="DEVELOPMENT_EXPOSED",
                existing_positions=(global_position,),
            ).results[0]
        self.assertEqual(result.portfolio_result.reason, PORTFOLIO_EXISTING_POSITION_CONFLICT)

    def test_known_open_position_without_portfolio_risk_state_blocks_new_entry(self):
        history, t_day, event, evaluators = _fixture()
        state = OpenPositionState(
            "CHAIN.SYNTH",
            "US",
            origin=_position_origin(),
            portfolio_position=None,
        )
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day, position=state)],
                mode="DEVELOPMENT_EXPOSED",
            ).results[0]
        self.assertEqual(result.individual_decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertIsNotNone(result.position_management)
        self.assertEqual(result.portfolio_result.status, "PORTFOLIO_BLOCKED")
        self.assertEqual(result.portfolio_result.reason, PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED)
        self.assertNotEqual(result.final_status, "PORTFOLIO_ALLOWED")

    def test_multi_symbol_portfolio_mapping_preserves_blocker_and_reservation(self):
        history_a, t_day, event_a, evaluators_a = _fixture(symbol="SYMBOL_A")
        history_b, _, event_b, evaluators_b = _fixture(symbol="SYMBOL_B")
        known_position = OpenPositionState(
            "SYMBOL_A",
            "US",
            origin=_position_origin("SYMBOL_A"),
            portfolio_position=None,
        )

        def setup01(history, **kwargs):
            evaluator = evaluators_a.setup01 if history[0].symbol == "SYMBOL_A" else evaluators_b.setup01
            return evaluator(history, **kwargs)

        evaluators = DailyChainEvaluators(
            wave=evaluators_a.wave,
            setup01=setup01,
            setup02=evaluators_a.setup02,
        )
        store = InMemoryDecisionStateStore()
        with patch(
            "trading.daily_decision_chain.evaluate_setup01_decision",
            side_effect=lambda event, *_args, **_kwargs: _decision(event),
        ):
            report = DailyDecisionChain(store=store, evaluators=evaluators).evaluate(
                [
                    _input(history_a, t_day, position=known_position),
                    _input(history_b, t_day, risk_group="GROUP_B"),
                ],
                mode="DEVELOPMENT_EXPOSED",
            )

        results = {result.symbol: result for result in report.results}
        result_a = results["SYMBOL_A"]
        result_b = results["SYMBOL_B"]
        self.assertEqual(result_a.portfolio_result.status, "PORTFOLIO_BLOCKED")
        self.assertEqual(result_a.portfolio_result.reason, PORTFOLIO_OPEN_POSITION_RISK_STATE_REQUIRED)
        self.assertIsNone(result_a.portfolio_result.reservation_id)
        self.assertEqual(result_b.portfolio_result.status, "PORTFOLIO_ALLOWED")
        self.assertEqual(result_b.portfolio_result.reservation_id, event_b.event_identity)
        self.assertEqual(set(store.pending), {event_b.event_identity})
        self.assertNotIn(event_a.event_identity, store.pending)

    def test_missing_origin_blocks_pm_but_keeps_authoritative_risk_for_other_symbol(self):
        history_a, t_day, event_a, evaluators_a = _fixture(symbol="SYMBOL_A")
        history_b, _, event_b, evaluators_b = _fixture(symbol="SYMBOL_B")
        held_a = _portfolio_position(symbol="SYMBOL_A", source_event_identity="held-a", quantity=0.001)
        state_a = OpenPositionState("SYMBOL_A", "US", portfolio_position=held_a)

        def setup01(history, **kwargs):
            evaluator = evaluators_a.setup01 if history[0].symbol == "SYMBOL_A" else evaluators_b.setup01
            return evaluator(history, **kwargs)

        evaluators = DailyChainEvaluators(
            wave=evaluators_a.wave,
            setup01=setup01,
            setup02=evaluators_a.setup02,
        )
        with patch(
            "trading.daily_decision_chain.evaluate_setup01_decision",
            side_effect=lambda event, *_args, **_kwargs: _decision(event),
        ):
            report = DailyDecisionChain(evaluators=evaluators).evaluate(
                [
                    _input(history_a, t_day, position=state_a),
                    _input(history_b, t_day, risk_group="GROUP_B"),
                ],
                mode="DEVELOPMENT_EXPOSED",
            )
        results = {result.symbol: result for result in report.results}
        self.assertEqual(results["SYMBOL_A"].position_management.status, POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT)
        self.assertEqual(results["SYMBOL_A"].portfolio_result.reason, "BLOCK_EXISTING_POSITION_SAME_SYMBOL")
        self.assertEqual(results["SYMBOL_B"].portfolio_result.status, "PORTFOLIO_ALLOWED")
        self.assertEqual(
            results["SYMBOL_B"].portfolio_result.total_risk_before,
            held_a.remaining_loss_risk(1.0),
        )

    def test_settlement_position_is_counted_before_same_run_new_reservation(self):
        history_a, t_day, event_a, evaluators_a = _fixture(t1=True, symbol="SYMBOL_A")
        history_b, _, event_b, evaluators_b = _fixture(symbol="SYMBOL_B")
        t1 = t_day + timedelta(days=1)
        history_b_t1 = history_b + (_quote(t1, 100.0, symbol="SYMBOL_B"),)
        event_b_t1 = replace(event_b, event_identity=f"SYMBOL_B|SETUP_01|{t1.isoformat()}|CONFIRMED|lifecycle=1", trade_date=t1)
        report_b_t1 = Setup01ReplayReport(
            symbol="SYMBOL_B", market="US",
            days=(Setup01ReplayDay("SYMBOL_B", t1, event_b_t1.setup01),),
            events=(event_b_t1,),
        )

        store = InMemoryDecisionStateStore()
        initial_chain = DailyDecisionChain(store=store, evaluators=evaluators_a)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", side_effect=lambda event, *_args, **_kwargs: _decision(event)):
            initial_chain.evaluate(
                [_input(history_a[:21], t_day, exact=True, next_day=t1)],
                mode="DEVELOPMENT_EXPOSED",
            )
        self.assertIn(event_a.event_identity, store.pending)

        def setup01(history, **kwargs):
            return report_b_t1 if history[0].symbol == "SYMBOL_B" else evaluators_a.setup01(history, **kwargs)

        evaluators = DailyChainEvaluators(wave=evaluators_a.wave, setup01=setup01, setup02=evaluators_a.setup02)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", side_effect=lambda event, *_args, **_kwargs: _decision(event)):
            report = DailyDecisionChain(store=store, evaluators=evaluators).evaluate(
                [
                    _input(history_a, t1, exact=True, next_day=t1 + timedelta(days=1)),
                    _input(history_b_t1, t1, exact=True, next_day=t1 + timedelta(days=1), risk_group="GROUP_B"),
                ],
                mode="DEVELOPMENT_EXPOSED",
            )
        results = {result.symbol: result for result in report.results}
        settled_position = store.settled[event_a.event_identity].settlement.position
        self.assertIsNotNone(settled_position)
        self.assertEqual(results["SYMBOL_A"].execution_outcome, "EXECUTED")
        self.assertEqual(results["SYMBOL_B"].portfolio_result.status, "PORTFOLIO_ALLOWED")
        self.assertEqual(
            results["SYMBOL_B"].portfolio_result.total_risk_before,
            settled_position.remaining_loss_risk(1.0),
        )
        self.assertIn(event_b_t1.event_identity, store.pending)

    def test_unresolved_pending_reservation_blocks_new_symbol_without_reservation(self):
        history_a, t_day, event_a, evaluators_a = _fixture(t1=True, symbol="SYMBOL_A")
        history_b, _, event_b, evaluators_b = _fixture(symbol="SYMBOL_B")
        t1 = t_day + timedelta(days=1)
        history_b_t1 = history_b + (_quote(t1, 100.0, symbol="SYMBOL_B"),)
        event_b_t1 = replace(event_b, event_identity=f"SYMBOL_B|SETUP_01|{t1.isoformat()}|CONFIRMED|lifecycle=1", trade_date=t1)
        report_b_t1 = Setup01ReplayReport(
            symbol="SYMBOL_B", market="US",
            days=(Setup01ReplayDay("SYMBOL_B", t1, event_b_t1.setup01),),
            events=(event_b_t1,),
        )
        store = InMemoryDecisionStateStore()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", side_effect=lambda event, *_args, **_kwargs: _decision(event)):
            DailyDecisionChain(store=store, evaluators=evaluators_a).evaluate(
                [_input(history_a[:21], t_day, exact=True, next_day=t1)],
                mode="DEVELOPMENT_EXPOSED",
            )

        def setup01(history, **kwargs):
            return report_b_t1 if history[0].symbol == "SYMBOL_B" else evaluators_a.setup01(history, **kwargs)

        evaluators = DailyChainEvaluators(wave=evaluators_a.wave, setup01=setup01, setup02=evaluators_a.setup02)
        with patch("trading.daily_decision_chain.execute_setup01_t1_open", side_effect=AssertionError("missing bar must not execute")), \
             patch("trading.daily_decision_chain.evaluate_setup01_decision", side_effect=lambda event, *_args, **_kwargs: _decision(event)):
            report = DailyDecisionChain(store=store, evaluators=evaluators).evaluate(
                [
                    _input(history_a[:21], t1, exact=True, next_day=t1 + timedelta(days=1)),
                    _input(history_b_t1, t1, exact=True, next_day=t1 + timedelta(days=1), risk_group="GROUP_B"),
                ],
                mode="DEVELOPMENT_EXPOSED",
            )
        results = {result.symbol: result for result in report.results}
        self.assertIn(event_a.event_identity, store.pending)
        self.assertIn(T1_EXECUTION_DATA_REQUIRED, results["SYMBOL_A"].blocking_prerequisites)
        self.assertEqual(results["SYMBOL_B"].portfolio_result.reason, PORTFOLIO_PENDING_RESERVATION_UNRESOLVED)
        self.assertEqual(results["SYMBOL_B"].portfolio_result.reservation_id, None)
        self.assertNotIn(event_b_t1.event_identity, store.pending)

    def test_protocol_only_store_uses_get_settlement_for_exact_once(self):
        history, t_day, event, evaluators = _fixture(t1=True)
        t1 = t_day + timedelta(days=1)
        store = ProtocolOnlyDecisionStore()
        chain = DailyDecisionChain(store=store, evaluators=evaluators)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate([_input(history[:21], t_day, exact=True, next_day=t1)], mode="DEVELOPMENT_EXPOSED")
            settled = chain.evaluate([_input(history, t1, exact=True)], mode="DEVELOPMENT_EXPOSED").results[0]
            rerun = chain.evaluate([_input(history, t1, exact=True)], mode="DEVELOPMENT_EXPOSED").results[0]
        self.assertEqual(settled.execution_phase, T1ExecutionPhase.T1_EXECUTION_OBSERVED)
        self.assertEqual(len(store._delegate.settled), 1)
        self.assertIsNone(rerun.execution_outcome)

    def test_mixed_as_of_dates_fail_fast_before_report_generation(self):
        history, t_day, _, evaluators = _fixture()
        other_history = tuple(
            _quote(START + timedelta(days=index + 1), 101.0 + index * 0.1, symbol="OTHER.SYNTH")
            for index in range(21)
        )
        with self.assertRaisesRegex(ValueError, "share one as_of_date"):
            DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day), _input(other_history, t_day + timedelta(days=1))],
                mode="DEVELOPMENT_EXPOSED",
            )

    def test_dual_new_confirmed_events_fail_closed_without_setup_priority(self):
        history, t_day, event01, evaluators = _fixture()
        setup02_snapshot = SimpleNamespace(
            setup_type="SETUP_02",
            state=SetupState.CONFIRMED,
            is_new_confirmed_event_as_of=True,
        )
        event02 = SimpleNamespace(
            event_identity=f"CHAIN.SYNTH|SETUP_02|{t_day.isoformat()}|CONFIRMED|lifecycle=1",
            symbol="CHAIN.SYNTH",
            trade_date=t_day,
            event_type=SetupState.CONFIRMED,
            setup02=setup02_snapshot,
            market="US",
        )
        setup02_report = SimpleNamespace(current=setup02_snapshot, events=(event02,))
        dual_evaluators = DailyChainEvaluators(
            wave=evaluators.wave,
            setup01=evaluators.setup01,
            setup02=lambda *_args, **_kwargs: setup02_report,
        )
        store = InMemoryDecisionStateStore()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event01)), \
             patch("trading.daily_decision_chain.evaluate_setup02_decision", return_value=_decision(event02)):
            result = DailyDecisionChain(store=store, evaluators=dual_evaluators).evaluate(
                [_input(history, t_day)], mode="DEVELOPMENT_EXPOSED"
            ).results[0]
        self.assertIsNone(result.individual_decision)
        self.assertIsNone(result.portfolio_result)
        self.assertEqual(result.final_status, "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED")
        self.assertIn(DUAL_CONFIRMED_UPSTREAM_INVARIANT_VIOLATION, result.reasons[0])
        self.assertEqual(
            result.new_confirmed_event_identities,
            (event01.event_identity, event02.event_identity),
        )
        self.assertEqual(set(store.published_events), {event01.event_identity, event02.event_identity})
        self.assertEqual(store.pending, {})

    def test_missing_position_origin_fails_closed_without_fake_metrics(self):
        history, t_day, _, evaluators = _fixture(confirmed=False)
        position = OpenPositionState("CHAIN.SYNTH", "US")
        report = DailyDecisionChain(evaluators=evaluators).evaluate(
            [_input(history, t_day, position=position)], mode="PRODUCTION"
        )
        result = report.results[0]
        self.assertEqual(result.position_management.status, POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT)
        self.assertIsNone(result.position_management.current_r)
        self.assertIsNone(result.position_management.active_stop_at_open)
        self.assertEqual(result.final_status, "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED")
        payload = report.to_dict()
        self.assertEqual(len(payload["sections"]["持仓管理"]), 0)
        self.assertEqual(len(payload["sections"]["数据/生产前置条件异常"]), 1)

    def test_markdown_report_has_human_sections_and_machine_json_has_protocols(self):
        history, t_day, _, evaluators = _fixture(confirmed=False)
        report = DailyDecisionChain(evaluators=evaluators).evaluate([_input(history, t_day)], mode="DEVELOPMENT_EXPOSED")
        markdown = report.to_markdown()
        payload = report.to_dict()
        self.assertIn("## NO_TRADE", markdown)
        self.assertIn("protocol_versions", payload)
        self.assertIn("sections", payload)

    def test_read_only_evaluation_never_persists_state(self):
        history, t_day, event, evaluators = _fixture()
        store = InMemoryDecisionStateStore()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(store=store, evaluators=evaluators).evaluate(
                [_input(history, t_day)],
                mode="PRODUCTION",
                persist_state=False,
            ).results[0]
        self.assertEqual(result.final_status, STRATEGY_PROPOSAL)
        self.assertTrue(result.event_was_new)
        self.assertEqual(store.published_events, {})
        self.assertEqual(store.pending, {})
        self.assertEqual(store.daily_history, [])


if __name__ == "__main__":
    unittest.main()

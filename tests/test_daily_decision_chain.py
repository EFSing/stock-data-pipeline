from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Quote
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DATA_BAD,
    DATA_OK,
    DailyChainEvaluators,
    DailyDecisionChain,
    DailySymbolInput,
    InMemoryDecisionStateStore,
    OpenPositionState,
    POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT,
    PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED,
    T1ExecutionPhase,
)
from trading.models import DecisionAction, Setup01Evaluation, SetupState, Trend
from trading.setup01_replay import Setup01ReplayDay, Setup01ReplayEvent, Setup01ReplayReport


START = date(2026, 1, 5)


def _quote(day: date, close: float, opening: float | None = None) -> Quote:
    opening = close if opening is None else opening
    return Quote(
        symbol="CHAIN.SYNTH",
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


def _fixture(*, confirmed: bool = True, t1: bool = False):
    t_day = START + timedelta(days=20)
    history = tuple(_quote(START + timedelta(days=index), 100.0 + index * 0.1) for index in range(21))
    if t1:
        history += (_quote(t_day + timedelta(days=1), 100.0, opening=100.0),)
    snapshot = _snapshot(t_day, SetupState.CONFIRMED if confirmed else SetupState.NONE)
    event = Setup01ReplayEvent(
        event_identity=f"CHAIN.SYNTH|SETUP_01|{t_day.isoformat()}|CONFIRMED|lifecycle=1",
        symbol="CHAIN.SYNTH",
        trade_date=t_day,
        event_type=SetupState.CONFIRMED,
        setup01=snapshot,
        market="US",
    )
    report = Setup01ReplayReport(
        symbol="CHAIN.SYNTH",
        market="US",
        days=(Setup01ReplayDay("CHAIN.SYNTH", t_day, snapshot),),
        events=(event,) if confirmed else (),
    )
    no_setup = Setup01ReplayReport(
        symbol="CHAIN.SYNTH",
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
    return DailySymbolInput(
        symbol="CHAIN.SYNTH",
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

    def test_missing_nav_keeps_individual_decision_visible(self):
        history, t_day, event, evaluators = _fixture()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day)], mode="PRODUCTION", reference_nav=None
            ).results[0]
        self.assertEqual(result.individual_decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertEqual(result.portfolio_result.reason, "PORTFOLIO_NAV_REQUIRED")
        self.assertEqual(result.final_status, "PORTFOLIO_BLOCKED")

    def test_unknown_group_blocks_production_but_development_allows(self):
        history, t_day, event, evaluators = _fixture()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            production = DailyDecisionChain(evaluators=evaluators).evaluate(
                [_input(history, t_day)], mode="PRODUCTION", reference_nav=1.0
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

    def test_stale_data_never_runs_upstream_chain(self):
        history, t_day, _, evaluators = _fixture()
        result = DailyDecisionChain(evaluators=evaluators).evaluate(
            [_input(history, t_day, quality=DATA_BAD)], mode="PRODUCTION"
        ).results[0]
        self.assertEqual(result.final_status, "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED")
        self.assertIn("DATA_QUALITY_DATA_BAD", result.reasons)

    def test_missing_position_origin_fails_closed_without_fake_metrics(self):
        history, t_day, _, evaluators = _fixture(confirmed=False)
        position = OpenPositionState("CHAIN.SYNTH", "US")
        result = DailyDecisionChain(evaluators=evaluators).evaluate(
            [_input(history, t_day, position=position)], mode="PRODUCTION"
        ).results[0]
        self.assertEqual(result.position_management.status, POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT)
        self.assertIsNone(result.position_management.current_r)
        self.assertIsNone(result.position_management.active_stop_at_open)

    def test_markdown_report_has_human_sections_and_machine_json_has_protocols(self):
        history, t_day, _, evaluators = _fixture(confirmed=False)
        report = DailyDecisionChain(evaluators=evaluators).evaluate([_input(history, t_day)], mode="DEVELOPMENT_EXPOSED")
        markdown = report.to_markdown()
        payload = report.to_dict()
        self.assertIn("## NO_TRADE", markdown)
        self.assertIn("protocol_versions", payload)
        self.assertIn("sections", payload)


if __name__ == "__main__":
    unittest.main()

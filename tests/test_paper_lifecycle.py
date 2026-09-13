from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Quote
from tests.test_setup01_decision import _fixture
from tests.test_setup02_decision import _fixture as _setup02_fixture, _swing as _setup02_swing
from trading.daily_decision_chain import CompletedSessionIdentity, DATA_OK, DailySymbolInput
from trading.models import DecisionAction, SwingKind
from trading.paper_lifecycle import (
    PAPER_CLOSED_STATUS,
    PAPER_LEDGER_HEADERS,
    PAPER_OPEN_STATUS,
    PAPER_PLAN_CREATED,
    PAPER_PLAN_STATUS,
    PAPER_SKIPPED_STATUS,
    PAPER_T1_EXECUTED,
    PAPER_T1_SKIPPED,
    InMemoryPaperLedgerStore,
    PaperLifecycleEngine,
    PaperLifecycleError,
    PaperTrade,
    active_paper_symbols,
    calculate_performance,
    paper_ledger_schema,
    paper_trades,
)
from trading.position_management import PositionAction, PositionExitReason, TargetReachStatus
from trading.setup01_decision import evaluate_setup01_decision
from trading.setup02_decision import evaluate_setup02_decision
from trading.trade_logic_explanation import build_trade_logic_explanation


def _input(event, quotes, as_of, next_session):
    return DailySymbolInput(
        symbol=event.symbol,
        market=event.market,
        as_of_date=as_of,
        qfq_history=tuple(item for item in quotes if item.trade_date <= as_of),
        data_quality_status=DATA_OK,
        completed_session_identity=CompletedSessionIdentity(
            market=event.market,
            trade_date=as_of,
            identity=f"synthetic:{as_of.isoformat()}",
            exact_exchange_calendar=True,
            next_session_date=next_session,
            session_dates=(as_of, next_session),
        ),
    )


def _result(
    event,
    decision,
    *,
    provenance="FORMAL_STRATEGY_POOL",
    primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
):
    return SimpleNamespace(
        symbol=event.symbol,
        market=event.market,
        as_of_date=event.trade_date,
        primary_wave_scenario=primary_wave_scenario,
        individual_decision=decision,
        event_was_new=True,
        new_confirmed_event_identity=event.event_identity,
        new_confirmed_event_identities=(event.event_identity,),
        selected_event=event,
        provenance={"source": provenance},
    )


def _trade(**overrides):
    values = {
        "event_identity": "E",
        "symbol": "SYNTH",
        "market": "US",
        "name": "Synthetic",
        "sector": "Technology",
        "source_provenance": "FORMAL_STRATEGY_POOL",
        "source_setup": "SETUP_01",
        "signal_date": date(2026, 1, 1),
        "status": PAPER_CLOSED_STATUS,
        "realized_r": 1.0,
        "return_pct": 0.1,
        "holding_days": 2,
        "final_mfe": 1.5,
        "final_mae": -0.2,
    }
    values.update(overrides)
    return PaperTrade(**values)


class PaperLifecycleTests(unittest.TestCase):
    def test_schema_and_event_identity_are_append_only_exactly_once(self):
        store = InMemoryPaperLedgerStore()
        payload = {"paper_status": PAPER_PLAN_STATUS, "symbol": "SYNTH"}

        self.assertTrue(store.append_event(PAPER_PLAN_CREATED, "E", payload))
        self.assertFalse(store.append_event(PAPER_PLAN_CREATED, "E", payload))
        with self.assertRaises(PaperLifecycleError):
            store.append_event(PAPER_PLAN_CREATED, "E", {"paper_status": "OTHER"})
        self.assertEqual(store.event_count, 1)
        schema = paper_ledger_schema()
        self.assertEqual(schema["identity"], "event_identity + lifecycle_event_type")
        self.assertTrue(
            set(("position_origin_json", "planned_risk_per_share", "initial_risk_per_share", "realized_r", "coverage_gap"))
            .issubset(PAPER_LEDGER_HEADERS)
        )

    def test_new_entry_allowed_event_creates_plan_then_reuses_exact_t1_and_origin(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        signal_date = event.trade_date
        t1 = signal_date + timedelta(days=1)
        item_t = _input(event, quotes, signal_date, t1)
        item_t1 = _input(event, quotes, t1, t1 + timedelta(days=1))
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        result = _result(event, decision)

        first = engine.process_daily(
            (result,), (item_t,), as_of_date=signal_date,
            provenance_by_symbol={event.symbol: {"source": "FORMAL_STRATEGY_POOL"}},
        )
        self.assertEqual(first.trades[0].status, PAPER_PLAN_STATUS)
        self.assertEqual(first.trades[0].source_provenance, "FORMAL_STRATEGY_POOL")
        self.assertEqual(store.event_count, 2)  # plan + market coverage

        second = engine.process_daily((), (item_t1,), as_of_date=t1)
        self.assertEqual(second.trades[0].status, PAPER_OPEN_STATUS)
        self.assertEqual(second.trades[0].execution_outcome, "EXECUTED")
        self.assertEqual(second.trades[0].actual_entry, 110.75)
        self.assertTrue(second.trades[0].position_origin_json)
        self.assertEqual(
            sum(row["lifecycle_event_type"] == PAPER_T1_EXECUTED for row in store.events),
            1,
        )

        before = store.event_count
        repeated = engine.process_daily((), (item_t1,), as_of_date=t1)
        self.assertEqual(repeated.trades[0].status, PAPER_OPEN_STATUS)
        self.assertEqual(store.event_count, before)

    def test_actual_entry_based_one_r_is_separate_from_planned_risk(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        t = event.trade_date
        t1 = t + timedelta(days=1)
        t2 = t + timedelta(days=2)
        quotes = [
            *quotes,
            replace(quotes[-1], trade_date=t2, open=115.0, high=116.0, low=114.0, close=115.0),
        ]
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        engine.process_daily(
            (_result(event, decision),), (_input(event, quotes, t, t1),), as_of_date=t,
        )
        opened = engine.process_daily(
            (), (_input(event, quotes, t1, t2),), as_of_date=t1,
        )
        plan_row = next(row for row in store.events if row["lifecycle_event_type"] == PAPER_PLAN_CREATED)
        executed_row = next(row for row in store.events if row["lifecycle_event_type"] == PAPER_T1_EXECUTED)
        planned_risk = float(plan_row["planned_risk_per_share"])
        actual_risk = float(executed_row["initial_risk_per_share"])
        self.assertNotEqual(planned_risk, actual_risk)
        self.assertAlmostEqual(actual_risk, 110.75 - float(decision.execution_stop))
        self.assertAlmostEqual(
            opened.trades[0].current_r,
            (110.0 - 110.75) / actual_risk,
        )

        day = SimpleNamespace(
            close=115.0,
            current_r=(115.0 - 110.75) / actual_risk,
            mfe_r=1.5,
            mae_r=-0.2,
            mfe_drawdown_r=0.1,
            target_status=TargetReachStatus.T1_REACHED,
            action=PositionAction.EXIT,
            secondary_reasons=(),
            exit_reason=PositionExitReason.EXIT_STOP_TRIGGERED,
        )
        replay = SimpleNamespace(
            days=(day,),
            final_active_stop=float(decision.execution_stop),
            exit_date=t2,
            exit_reason=PositionExitReason.EXIT_STOP_TRIGGERED,
            exit_price=115.0,
            position_days=2,
        )
        with patch("trading.paper_lifecycle.replay_position", return_value=replay):
            closed = engine.process_daily(
                (), (_input(event, quotes, t2, t2 + timedelta(days=1)),), as_of_date=t2,
            )
        trade = closed.trades[0]
        expected_r = (115.0 - 110.75) / actual_risk
        self.assertAlmostEqual(trade.realized_r, expected_r)
        self.assertAlmostEqual(trade.current_r, expected_r)
        self.assertNotAlmostEqual(trade.realized_r, (115.0 - 110.75) / planned_risk)

    def test_persistent_confirmation_and_no_trade_do_not_create_plan(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        item = _input(event, quotes, event.trade_date, event.trade_date + timedelta(days=1))

        persistent = _result(event, decision)
        persistent.event_was_new = False
        persistent.new_confirmed_event_identity = None
        persistent.new_confirmed_event_identities = ()
        first = engine.process_daily(
            (persistent,), (item,), as_of_date=event.trade_date,
        )
        self.assertEqual(first.created_plans, ())
        self.assertFalse(any(row["lifecycle_event_type"] == PAPER_PLAN_CREATED for row in store.events))

        no_trade = _result(event, decision)
        no_trade.individual_decision = replace(decision, action=DecisionAction.NO_TRADE)
        second = engine.process_daily(
            (no_trade,), (item,), as_of_date=event.trade_date,
        )
        self.assertEqual(second.created_plans, ())
        self.assertFalse(any(row["lifecycle_event_type"] == PAPER_PLAN_CREATED for row in store.events))

    def test_new_confirmed_result_from_an_earlier_session_is_not_backfilled(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        t = event.trade_date
        store = InMemoryPaperLedgerStore()
        result = PaperLifecycleEngine(store).process_daily(
            (_result(event, decision),),
            (_input(event, quotes, t, t + timedelta(days=1)),),
            as_of_date=t + timedelta(days=1),
        )
        self.assertEqual(result.created_plans, ())
        self.assertTrue(any("must be processed on signal session" in error for error in result.errors))

    def test_plan_rejects_missing_exact_exchange_calendar(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        item = _input(event, quotes, event.trade_date, event.trade_date + timedelta(days=1))
        item = replace(
            item,
            completed_session_identity=CompletedSessionIdentity(
                market=event.market,
                trade_date=event.trade_date,
                identity="non-exact-calendar",
                exact_exchange_calendar=False,
                next_session_date=event.trade_date + timedelta(days=1),
                session_dates=(event.trade_date, event.trade_date + timedelta(days=1)),
            ),
        )
        store = InMemoryPaperLedgerStore()
        result = PaperLifecycleEngine(store).process_daily(
            (_result(event, decision),), (item,), as_of_date=event.trade_date,
        )
        self.assertEqual(result.created_plans, ())
        self.assertTrue(any("exact exchange-calendar" in error for error in result.errors))

    def test_candidate_only_is_tracked_without_promotion_or_production_eligibility(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        result = engine.process_daily(
            (_result(event, decision, provenance="DYNAMIC_CANDIDATE"),),
            (_input(event, quotes, event.trade_date, event.trade_date + timedelta(days=1)),),
            as_of_date=event.trade_date,
            provenance_by_symbol={event.symbol: {"source": "DYNAMIC_CANDIDATE"}},
        )
        trade = result.trades[0]
        self.assertEqual(trade.source_provenance, "DYNAMIC_CANDIDATE")
        self.assertTrue(trade.promotion_required)
        self.assertFalse(trade.state_persistence_eligible)
        self.assertFalse(trade.production_execution_eligible)
        self.assertEqual(active_paper_symbols(store), (("US", event.symbol.upper()),))

    def test_t1_skip_is_not_counted_as_executed_trade(self):
        event, quotes = _fixture(t1_open=109.0)
        decision = evaluate_setup01_decision(event, quotes)
        t = event.trade_date
        t1 = t + timedelta(days=1)
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        engine.process_daily(
            (_result(event, decision),), (_input(event, quotes, t, t1),),
            as_of_date=t,
        )
        result = engine.process_daily((), (_input(event, quotes, t1, t1 + timedelta(days=1)),), as_of_date=t1)
        self.assertEqual(result.trades[0].status, PAPER_SKIPPED_STATUS)
        self.assertEqual(result.trades[0].actual_entry, None)
        self.assertEqual(result.performance.executed, 0)
        self.assertEqual(result.performance.skipped, 1)
        self.assertEqual(
            sum(row["lifecycle_event_type"] == PAPER_T1_SKIPPED for row in store.events),
            1,
        )

    def test_exact_t1_missing_closes_plan_as_skip_without_falling_forward(self):
        event, quotes = _fixture(t1_open=None)
        decision = evaluate_setup01_decision(event, quotes)
        t = event.trade_date
        t1 = t + timedelta(days=1)
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        engine.process_daily(
            (_result(event, decision),), (_input(event, quotes, t, t1),), as_of_date=t
        )
        result = engine.process_daily(
            (), (_input(event, quotes, t1, t1 + timedelta(days=1)),), as_of_date=t1
        )
        self.assertEqual(result.trades[0].status, PAPER_SKIPPED_STATUS)
        self.assertEqual(result.trades[0].execution_outcome, "SKIP_NO_T1_BAR")
        self.assertIsNone(result.trades[0].actual_entry)

    def test_setup02_plan_uses_setup02_executor_and_actual_open(self):
        event, quotes = _setup02_fixture(wide=True, t_close=140.0, t1_open=140.5)
        high = _setup02_swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            decision = evaluate_setup02_decision(event, quotes)
        t = event.trade_date
        t1 = t + timedelta(days=1)
        engine = PaperLifecycleEngine(InMemoryPaperLedgerStore())
        first = engine.process_daily(
            (_result(
                event,
                decision,
                primary_wave_scenario="WAVE_3_CONTINUATION_CANDIDATE",
            ),),
            (_input(event, quotes, t, t1),),
            as_of_date=t,
        )
        second = engine.process_daily(
            (), (_input(event, quotes, t1, t1 + timedelta(days=1)),), as_of_date=t1
        )
        self.assertEqual(first.trades[0].source_setup, "SETUP_02")
        self.assertEqual(second.trades[0].execution_outcome, "EXECUTED")
        self.assertEqual(second.trades[0].actual_entry, 140.5)

    def test_coverage_gap_remains_visible_after_later_continuous_run(self):
        event, quotes = _fixture(t1_open=None)
        decision = evaluate_setup01_decision(event, quotes)
        t = event.trade_date
        t2 = t + timedelta(days=2)
        t3 = t + timedelta(days=3)
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        engine.process_daily(
            (_result(event, decision),), (_input(event, quotes, t, t + timedelta(days=1)),), as_of_date=t
        )
        gap = engine.process_daily(
            (), (_input(event, quotes, t2, t3),), as_of_date=t2
        )
        self.assertEqual(gap.coverage[0].coverage_status, "GAP_DETECTED")
        continuous_after_gap = engine.process_daily(
            (), (_input(event, quotes, t3, t3 + timedelta(days=1)),), as_of_date=t3
        )
        self.assertEqual(continuous_after_gap.coverage[0].coverage_status, "GAP_DETECTED")
        self.assertTrue(continuous_after_gap.coverage[0].coverage_gap)

    def test_coverage_fails_closed_when_current_qfq_is_unavailable(self):
        event, quotes = _fixture(t1_open=None)
        decision = evaluate_setup01_decision(event, quotes)
        t = event.trade_date
        item = replace(
            _input(event, quotes, t, t + timedelta(days=1)),
            data_quality_status="DATA_UNAVAILABLE",
            qfq_history=(),
        )
        store = InMemoryPaperLedgerStore()
        result = PaperLifecycleEngine(store).process_daily(
            (_result(event, decision),), (item,), as_of_date=t
        )
        self.assertEqual(result.created_plans, ())
        self.assertEqual(result.coverage[0].coverage_status, "GAP_DETECTED")
        self.assertIn("DATA_OK", result.coverage[0].coverage_gap)

    def test_late_run_can_complete_already_recorded_plan_using_exact_t1(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        t = event.trade_date
        t1 = t + timedelta(days=1)
        t2 = t + timedelta(days=2)
        store = InMemoryPaperLedgerStore()
        engine = PaperLifecycleEngine(store)
        engine.process_daily((_result(event, decision),), (_input(event, quotes, t, t1),), as_of_date=t)
        late_input = DailySymbolInput(
            symbol=event.symbol,
            market=event.market,
            as_of_date=t2,
            qfq_history=tuple(quotes),
            data_quality_status=DATA_OK,
            completed_session_identity=CompletedSessionIdentity(
                event.market, t2, "synthetic:t2", True, t2 + timedelta(days=1), (t2, t2 + timedelta(days=1))
            ),
        )
        result = engine.process_daily((), (late_input,), as_of_date=t2)
        self.assertEqual(result.trades[0].status, PAPER_OPEN_STATUS)
        self.assertEqual(result.trades[0].execution_date, t1)
        self.assertEqual(result.trades[0].actual_entry, 110.75)

    def test_normalized_statistics_exclude_open_and_skipped_from_win_loss(self):
        values = (
            _trade(event_identity="WIN", realized_r=1.0, return_pct=0.1),
            _trade(event_identity="LOSS", realized_r=-1.0, return_pct=-0.1),
            _trade(event_identity="FLAT", realized_r=0.0, return_pct=0.0),
            _trade(event_identity="OPEN", status=PAPER_OPEN_STATUS, realized_r=None),
            _trade(event_identity="SKIP", status=PAPER_SKIPPED_STATUS, realized_r=None),
        )
        stats = calculate_performance(values)
        self.assertEqual((stats.plans, stats.executed, stats.skipped, stats.open, stats.closed), (5, 4, 1, 1, 3))
        self.assertEqual((stats.wins, stats.losses, stats.flats), (1, 1, 1))
        self.assertEqual(stats.win_rate, 0.5)
        self.assertEqual(stats.average_r, 0.0)

    def test_explanation_uses_existing_decision_fields_and_says_target_is_not_auto_exit(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        explanation = build_trade_logic_explanation(decision, source_setup="SETUP_01", event=event).to_dict()
        self.assertIn("2浪调整结束", explanation["why_plan"])
        self.assertIn("Wave1 peak", explanation["why_plan"])
        self.assertIn("T+1", explanation["when_execute"])
        self.assertIn("结构失效位", explanation["execution_checks"])
        self.assertIn("不是机械到价自动卖出", explanation["target_policy"])


if __name__ == "__main__":
    unittest.main()

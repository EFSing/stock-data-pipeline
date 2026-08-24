import unittest
from datetime import date, timedelta
from unittest.mock import patch

from core import Quote
from research.backtest.setup03 import (
    ExecutionStatus,
    _performance_metrics,
    parameter_sensitivity_rows,
    research_trade_outcomes,
)
from trading.models import Decision, DecisionAction, EntryPlan, Setup, SetupState
from trading.replay import ReplayEvent, SymbolReplayReport


def q(
    index: int,
    *,
    open_price: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 100.0,
) -> Quote:
    return Quote(
        symbol="T",
        name="T",
        market="US",
        trade_date=date(2026, 1, 1) + timedelta(days=index),
        source="x",
        open=open_price,
        high=high,
        low=low,
        close=close,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def confirmed_event(
    *,
    action: DecisionAction = DecisionAction.ENTRY_ALLOWED,
    entry_zone_high: float = 102.0,
    stop: float = 95.0,
    targets: tuple[float, ...] = (110.0, 120.0, 130.0),
) -> ReplayEvent:
    setup = Setup(
        "SETUP_03",
        SetupState.CONFIRMED,
        breakout_price=100.0,
        structural_invalidation=90.0,
        detected_index=0,
        state_entered_index=0,
        confirmed_index=0,
    )
    entry_plan = (
        EntryPlan(100.5, 100.0, entry_zone_high, 100.0, 100.0, "confirmed")
        if action is DecisionAction.ENTRY_ALLOWED
        else None
    )
    decision = Decision(
        action,
        entry_plan,
        90.0,
        stop if entry_plan else None,
        targets if entry_plan else (),
        None,
        None,
    )
    signal_day = date(2026, 1, 1)
    return ReplayEvent(
        symbol="T",
        trade_date=signal_day,
        event_type=SetupState.CONFIRMED,
        setup=setup,
        decision=decision,
        signal_date=signal_day,
        confirmed_date=signal_day,
        signal_close=100.5,
        signal_atr=4.0,
    )


def report(event: ReplayEvent) -> SymbolReplayReport:
    return SymbolReplayReport("T", "US", (), events=(event,))


class Setup03ExecutionTests(unittest.TestCase):
    def test_t_plus_1_open_three_way_execution_rules(self):
        cases = (
            (99.0, ExecutionStatus.SKIP_GAP_BELOW_BREAKOUT, None),
            (101.0, ExecutionStatus.EXECUTED, 101.0),
            (103.0, ExecutionStatus.SKIP_GAP_ABOVE_ENTRY_ZONE, None),
        )
        for next_open, expected_status, expected_entry in cases:
            with self.subTest(next_open=next_open):
                quotes = [
                    q(0, open_price=99.5, high=101.0, low=99.0, close=100.5),
                    q(1, open_price=next_open, high=108.0, low=96.0, close=104.0),
                ]
                outcome = research_trade_outcomes(
                    report(confirmed_event()), quotes
                ).outcomes[0]

                self.assertEqual(outcome.execution_status, expected_status)
                self.assertEqual(outcome.actual_entry, expected_entry)
                self.assertNotEqual(outcome.actual_entry, quotes[0].close)

    def test_signal_day_no_trade_is_not_executed(self):
        event = confirmed_event(action=DecisionAction.NO_TRADE)
        quotes = [q(0, close=100.5), q(1, open_price=101.0)]

        outcome = research_trade_outcomes(report(event), quotes).outcomes[0]

        self.assertEqual(
            outcome.execution_status,
            ExecutionStatus.SKIP_SIGNAL_NOT_ENTRY_ALLOWED,
        )
        self.assertIsNone(outcome.actual_entry)

    def test_missing_t_plus_1_bar_is_explicitly_skipped(self):
        outcome = research_trade_outcomes(
            report(confirmed_event()), [q(0, close=100.5)]
        ).outcomes[0]

        self.assertEqual(
            outcome.execution_status, ExecutionStatus.SKIP_NO_T_PLUS_1_BAR
        )

    def test_same_bar_stop_and_target_uses_conservative_stop_first(self):
        quotes = [
            q(0, close=100.5),
            q(1, open_price=101.0, high=111.0, low=94.0, close=105.0),
        ]

        outcome = research_trade_outcomes(
            report(confirmed_event()), quotes
        ).outcomes[0]

        self.assertEqual(outcome.first_exit_event, "STOP")
        self.assertEqual(outcome.final_r, -1.0)

    def test_forward_returns_and_twenty_day_mark_to_market(self):
        path = [
            q(
                index,
                open_price=101.0 if index == 1 else 104.0,
                high=121.0,
                low=99.0,
                close=100.0 + index,
            )
            for index in range(1, 21)
        ]
        event = confirmed_event(stop=90.0, targets=(200.0, 220.0, 240.0))

        outcome = research_trade_outcomes(
            report(event), [q(0, close=100.5), *path]
        ).outcomes[0]

        self.assertEqual(outcome.execution_status, ExecutionStatus.EXECUTED)
        self.assertAlmostEqual(outcome.return_5d, 105.0 / 101.0 - 1.0)
        self.assertAlmostEqual(outcome.return_10d, 110.0 / 101.0 - 1.0)
        self.assertAlmostEqual(outcome.return_20d, 120.0 / 101.0 - 1.0)
        self.assertEqual(outcome.first_exit_event, "MARK_TO_MARKET_20D")
        self.assertAlmostEqual(outcome.final_r, (120.0 - 101.0) / 11.0)
        self.assertTrue(outcome.horizon_complete)

    def test_unresolved_short_tail_is_censored(self):
        quotes = [q(0, close=100.5), q(1, open_price=101.0, high=106.0, low=99.0)]
        event = confirmed_event(stop=90.0, targets=(200.0, 220.0, 240.0))

        outcome = research_trade_outcomes(report(event), quotes).outcomes[0]

        self.assertEqual(outcome.first_exit_event, "CENSORED_END_OF_DATA")
        self.assertIsNone(outcome.final_r)
        self.assertFalse(outcome.horizon_complete)


class Setup03SensitivityTests(unittest.TestCase):
    def test_performance_metrics_use_observed_final_r_sample(self):
        metrics = _performance_metrics(
            [2.0, -1.0, 0.5],
            [3.0, 0.0, 1.0],
            [-0.5, -1.0, -0.25],
        )

        self.assertAlmostEqual(metrics["win_rate"], 2 / 3)
        self.assertAlmostEqual(metrics["avg_R"], 0.5)
        self.assertAlmostEqual(metrics["expectancy"], 0.5)
        self.assertAlmostEqual(metrics["profit_factor"], 2.5)
        self.assertAlmostEqual(metrics["MFE"], 4 / 3)
        self.assertAlmostEqual(metrics["MAE"], -1.75 / 3)

    def test_declared_grid_has_54_unranked_research_rows(self):
        quotes = [q(0)]
        empty_report = SymbolReplayReport("T", "US", (), events=())
        production_setup = {
            "swing_lookback": 5,
            "platform_window": 40,
            "platform_tolerance_pct": 0.0,
            "arm_proximity_pct": 0.0,
        }

        with patch(
            "research.backtest.setup03.replay_setup03_history",
            return_value=empty_report,
        ) as replay:
            rows = parameter_sensitivity_rows(
                {"T": quotes},
                1000.0,
                production_setup,
                {"atr_period": 14},
            )

        self.assertEqual(len(rows), 54)
        self.assertEqual(replay.call_count, 54)
        self.assertEqual(production_setup["platform_tolerance_pct"], 0.0)
        self.assertEqual(
            {row["platform_tolerance_pct"] for row in rows},
            {0.005, 0.01, 0.015, 0.02, 0.03, 0.05},
        )
        self.assertTrue(all(row["input_bar_count"] == 1 for row in rows))
        self.assertTrue(all(row["sample_size"] == 0 for row in rows))
        self.assertTrue(all("best" not in key.lower() for row in rows for key in row))


if __name__ == "__main__":
    unittest.main()

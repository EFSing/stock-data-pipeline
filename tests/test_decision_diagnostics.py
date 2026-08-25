import unittest
from datetime import date, timedelta
from unittest.mock import patch

from core import Quote
from research.backtest.setup03 import (
    decision_gate_diagnostic_rows,
    decision_gate_summary_row,
    parameter_sensitivity_artifacts,
)
from trading.decision import (
    DecisionGateReason,
    decide_platform_breakout,
    decide_platform_breakout_with_diagnostics,
)
from trading.events import evaluate_setup03_event
from trading.models import Decision, DecisionAction, Setup, SetupState
from trading.replay import ReplayEvent, SymbolReplayReport, replay_setup03_history
from trading.setup import detect_platform_breakout


def quote(index: int, close: float, high: float | None = None, low: float | None = None) -> Quote:
    high = close if high is None else high
    low = close if low is None else low
    return Quote(
        symbol="T",
        name="test",
        market="US",
        trade_date=date(2026, 1, 1) + timedelta(days=index),
        source="fixture",
        open=close,
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


ENTRY_ALLOWED_CLOSES = [
    90, 94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
    94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
    94, 98, 102, 106, 110, 106, 104, 110.3,
]


class DecisionReasonTests(unittest.TestCase):
    def calculate(
        self,
        quotes: list[Quote],
        *,
        breakout: float | None = 100.0,
        invalidation: float | None = 90.0,
        confirmed_index: int | None = None,
        **kwargs,
    ):
        setup = Setup(
            "SETUP_03",
            SetupState.CONFIRMED,
            breakout_price=breakout,
            structural_invalidation=invalidation,
            confirmed_index=(len(quotes) - 1 if confirmed_index is None else confirmed_index),
        )
        return decide_platform_breakout_with_diagnostics(
            quotes, setup, 1000.0, atr_period=kwargs.pop("atr_period", 1), **kwargs
        )

    def assert_reason(self, result, reason, action=DecisionAction.NO_TRADE):
        self.assertEqual(result.decision.action, action)
        self.assertIsNotNone(result.diagnostics)
        self.assertEqual(result.diagnostics.reason, reason)

    def test_atr_unavailable(self):
        result = self.calculate([quote(0, 100.5)], atr_period=14)
        self.assert_reason(result, DecisionGateReason.ATR_UNAVAILABLE)

    def test_below_structural_invalidation(self):
        result = self.calculate([quote(0, 100), quote(1, 80)])
        self.assert_reason(result, DecisionGateReason.BELOW_STRUCTURAL_INVALIDATION)

    def test_below_breakout(self):
        result = self.calculate([quote(0, 100), quote(1, 95)])
        self.assert_reason(
            result,
            DecisionGateReason.BELOW_BREAKOUT,
            DecisionAction.WAIT_CONFIRMATION,
        )

    def test_above_entry_zone(self):
        result = self.calculate([quote(0, 100), quote(1, 105)])
        self.assert_reason(result, DecisionGateReason.ABOVE_ENTRY_ZONE)

    def test_no_valid_target(self):
        result = self.calculate(
            [quote(0, 104), quote(1, 105)],
            invalidation=99.0,
            max_chase_atr=10.0,
        )
        self.assert_reason(result, DecisionGateReason.NO_VALID_TARGET)

    def test_rr_below_minimum(self):
        result = self.calculate(
            [quote(0, 100), quote(1, 105, high=110, low=100)]
        )
        self.assert_reason(result, DecisionGateReason.RR_BELOW_MINIMUM)
        self.assertLess(result.diagnostics.t1_rr, 2.0)
        self.assertEqual(result.diagnostics.targets, result.decision.targets)

    def test_future_or_invalid_confirmation_context(self):
        result = self.calculate(
            [quote(0, 100), quote(1, 100.5)], confirmed_index=99
        )
        self.assert_reason(
            result, DecisionGateReason.FUTURE_OR_INVALID_CONFIRMATION_CONTEXT
        )

        missing_index_setup = Setup(
            "SETUP_03",
            SetupState.CONFIRMED,
            breakout_price=100.0,
            structural_invalidation=90.0,
            confirmed_index=None,
        )
        missing_index = decide_platform_breakout_with_diagnostics(
            [quote(0, 100), quote(1, 100.5)],
            missing_index_setup,
            1000.0,
            atr_period=1,
        )
        self.assert_reason(
            missing_index, DecisionGateReason.FUTURE_OR_INVALID_CONFIRMATION_CONTEXT
        )

    def test_other_no_trade_is_explicit(self):
        result = self.calculate(
            [quote(0, 100), quote(1, 100.5)], breakout=None
        )
        self.assert_reason(result, DecisionGateReason.OTHER_NO_TRADE)

    def test_entry_allowed_and_decision_output_regression(self):
        quotes = [quote(index, close) for index, close in enumerate(ENTRY_ALLOWED_CLOSES)]
        setup = detect_platform_breakout(
            quotes, swing_lookback=2, platform_window=40
        )

        before = decide_platform_breakout(
            quotes, setup, 1000.0, swing_lookback=2, atr_period=14
        )
        calculated = decide_platform_breakout_with_diagnostics(
            quotes, setup, 1000.0, swing_lookback=2, atr_period=14
        )

        self.assertEqual(calculated.decision, before)
        self.assert_reason(
            calculated, DecisionGateReason.ENTRY_ALLOWED, DecisionAction.ENTRY_ALLOWED
        )
        self.assertAlmostEqual(calculated.decision.entry_plan.planned_entry, 110.3)
        self.assertIsNotNone(calculated.decision.position_size)


class DecisionDiagnosticsIntegrationTests(unittest.TestCase):
    BASE_H = [100, 105, 110, 105, 100, 105, 110, 105, 100, 105, 110, 105, 100]
    BASE_L = [90, 95, 100, 95, 90, 95, 100, 95, 90, 95, 100, 95, 90]

    def fixture(self, extra_closes=(113.5,)) -> list[Quote]:
        quotes = []
        for index, (high, low) in enumerate(zip(self.BASE_H, self.BASE_L)):
            quotes.append(quote(index, (high + low) / 2, high, low))
        for close in extra_closes:
            index = len(quotes)
            quotes.append(quote(index, close, close + 1.5, close - 1.5))
        return quotes

    def test_production_and_replay_share_same_diagnostics(self):
        quotes = self.fixture()
        setup_parameters = {"swing_lookback": 2, "platform_window": 20}
        decision_parameters = {"swing_lookback": 2, "atr_period": 2}

        production = evaluate_setup03_event(
            quotes, 1000.0, setup_parameters, decision_parameters
        )
        replay = replay_setup03_history(
            quotes, 1000.0, setup_parameters, decision_parameters
        )

        self.assertEqual(replay.events[-1].decision, production.decision)
        self.assertEqual(
            replay.events[-1].decision_diagnostics,
            production.decision_diagnostics,
        )

    def test_future_bars_do_not_change_prior_event_diagnostics(self):
        signal_quotes = self.fixture()
        extended_quotes = [*signal_quotes, quote(len(signal_quotes), 114.0)]
        setup_parameters = {"swing_lookback": 2, "platform_window": 20}
        decision_parameters = {"swing_lookback": 2, "atr_period": 2}

        as_of = replay_setup03_history(
            signal_quotes, 1000.0, setup_parameters, decision_parameters
        )
        extended = replay_setup03_history(
            extended_quotes, 1000.0, setup_parameters, decision_parameters
        )

        self.assertEqual(as_of.events[0].trade_date, extended.events[0].trade_date)
        self.assertEqual(
            as_of.events[0].decision_diagnostics,
            extended.events[0].decision_diagnostics,
        )

    def test_unknown_rejection_maps_to_other_and_conserves(self):
        setup = Setup(
            "SETUP_03",
            SetupState.CONFIRMED,
            breakout_price=100.0,
            structural_invalidation=90.0,
            confirmed_index=0,
        )
        event = ReplayEvent(
            "T",
            date(2026, 1, 1),
            SetupState.CONFIRMED,
            setup,
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            signal_date=date(2026, 1, 1),
            confirmed_date=date(2026, 1, 1),
            signal_close=100.5,
        )
        report = SymbolReplayReport("T", "US", (), events=(event,))

        rows = decision_gate_diagnostic_rows((report,), 5, 40, 0.01)
        summary = decision_gate_summary_row(rows, 5, 40, 0.01)

        self.assertEqual(rows[0]["decision_gate_reason"], "OTHER_NO_TRADE")
        self.assertEqual(summary["CONFIRMED"], 1)
        self.assertEqual(summary["OTHER_NO_TRADE_count"], 1)
        self.assertEqual(summary["ENTRY_ALLOWED"], 0)

    def test_fixed_grid_stays_unranked_and_preserves_production_parameters(self):
        setup = Setup(
            "SETUP_03",
            SetupState.CONFIRMED,
            breakout_price=100.0,
            structural_invalidation=90.0,
            confirmed_index=0,
        )
        event = ReplayEvent(
            "T",
            date(2026, 1, 1),
            SetupState.CONFIRMED,
            setup,
            Decision(DecisionAction.NO_TRADE, None, None, None, (), None, None),
            signal_date=date(2026, 1, 1),
            confirmed_date=date(2026, 1, 1),
            signal_close=100.5,
        )
        report = SymbolReplayReport("T", "US", (), events=(event,))
        production = {
            "swing_lookback": 5,
            "platform_window": 40,
            "platform_tolerance_pct": 0.0,
            "arm_proximity_pct": 0.0,
        }

        with patch(
            "research.backtest.setup03.replay_setup03_history",
            return_value=report,
        ) as replay:
            artifacts = parameter_sensitivity_artifacts(
                {"T": [quote(0, 100.5)]}, 1000.0, production, {"atr_period": 14}
            )

        self.assertEqual(replay.call_count, 54)
        self.assertEqual(len(artifacts.sensitivity_rows), 54)
        self.assertEqual(len(artifacts.decision_gate_summary_rows), 54)
        self.assertEqual(len(artifacts.decision_gate_rows), 54)
        self.assertEqual(production["platform_tolerance_pct"], 0.0)
        self.assertTrue(
            all(
                row["CONFIRMED"]
                == sum(
                    value
                    for key, value in row.items()
                    if key.endswith("_count")
                )
                for row in artifacts.decision_gate_summary_rows
            )
        )
        self.assertTrue(
            all(
                "best" not in key.lower()
                for row in artifacts.decision_gate_summary_rows
                for key in row
            )
        )


if __name__ == "__main__":
    unittest.main()

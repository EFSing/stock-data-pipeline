from datetime import date
from types import SimpleNamespace
import unittest

from core import Quote
from trading.models import DecisionAction, RiskReward, SetupState
from trading.risk import risk_reward
from trading.setup01_decision import (
    Setup01Decision,
    Setup01TargetCandidate,
    Setup01TargetProvenance,
)
from research.development.setup01_swing_boundary_counterfactual_v1 import (
    _build_p1_decision,
    _obstacle_path,
    _performance_summary,
)
from trading.position_management import PositionExitReason


class Setup01SwingBoundaryCounterfactualTests(unittest.TestCase):
    def test_p1_uses_one_existing_fib_candidate_without_t2_or_t3(self):
        day = date(2026, 1, 5)
        swing = Setup01TargetCandidate(
            price=110.4,
            source="CONFIRMED_SWING_HIGH",
            reason="synthetic overhead",
            provenance=(Setup01TargetProvenance(source="CONFIRMED_SWING_HIGH"),),
        )
        fib = Setup01TargetCandidate(
            price=120.0,
            source="WAVE3_FIB_EXTENSION",
            reason="synthetic existing Fib",
            provenance=(
                Setup01TargetProvenance(
                    source="WAVE3_FIB_EXTENSION", extension_ratio=1.272
                ),
            ),
        )
        p0 = Setup01Decision(
            protocol_version="test",
            event_identity="synthetic-event",
            symbol="SYNTH",
            market="US",
            trade_date=day,
            event_type=SetupState.CONFIRMED,
            decision_calculable=True,
            action=DecisionAction.NO_TRADE,
            gate_reason="TARGET_UPSIDE_BELOW_MINIMUM",
            gate_detail="synthetic",
            atr14=2.0,
            wave1_origin=100.0,
            confirmation_level=110.0,
            planned_entry=110.0,
            entry_zone_low=110.0,
            entry_zone_high=111.0,
            structural_invalidation=106.0,
            wave_scenario_invalidation=100.0,
            execution_stop=105.0,
            target_candidates=(swing, fib),
            targets=(swing.price, fib.price),
            target_reasonableness_checked=False,
            target_reasonableness_passed=None,
            rr=risk_reward(110.0, 105.0, (swing.price, fib.price)),
            position_size=None,
            position_size_required_input="risk_capital",
            target_upside_pct=0.003636,
            target_upside_band="BELOW_MINIMUM",
        )
        event = SimpleNamespace(
            setup01=SimpleNamespace(
                wave1_peak=SimpleNamespace(price=110.0),
                wave2_low=SimpleNamespace(price=105.0),
            )
        )

        p1 = _build_p1_decision(p0, event)

        self.assertEqual(p1.action, DecisionAction.ENTRY_ALLOWED)
        self.assertEqual(p1.targets, (120.0,))
        self.assertEqual(len(p1.target_candidates), 1)
        self.assertEqual(p1.target_candidates[0].source, "WAVE3_FIB_EXTENSION")
        self.assertAlmostEqual(p1.rr.rr_ratios[0], 2.0)

    def test_obstacle_path_uses_stop_first_when_exit_bar_high_crosses_obstacle(self):
        day = date(2026, 1, 6)
        replay = SimpleNamespace(
            origin=SimpleNamespace(actual_entry=100.0),
            days=(
                SimpleNamespace(
                    trade_date=day,
                    position_open_at_close=False,
                    exit_reason=PositionExitReason.EXIT_STOP_TRIGGERED,
                ),
            ),
        )
        quote = Quote(
            symbol="SYNTH",
            name="Synthetic",
            market="US",
            trade_date=day,
            source="TEST",
            open=100.0,
            high=115.0,
            low=90.0,
            close=95.0,
            preclose=None,
            pct_change=None,
            volume=1.0,
            amount=None,
            turnover_rate=None,
            currency="USD",
        )

        path = _obstacle_path(replay, {day: quote}, 110.0)

        self.assertEqual(path["status"], "STOP_BEFORE_OBSTACLE_CLEAR")
        self.assertTrue(path["stop_before_obstacle_clear"])
        self.assertTrue(path["same_bar_stop_first_applied"])

    def test_performance_summary_excludes_open_censored_rows(self):
        details = [
            {"event_identity": "closed-win", "realized_gross_R": 2.0, "exit_reason": "EXIT_STOP_TRIGGERED", "terminal_outcome": "CLOSED"},
            {"event_identity": "closed-loss", "realized_gross_R": -1.0, "exit_reason": "EXIT_STOP_TRIGGERED", "terminal_outcome": "CLOSED"},
            {"event_identity": "open", "realized_gross_R": None, "exit_reason": None, "terminal_outcome": "OPEN_CENSORED"},
        ]

        result = _performance_summary(details)

        self.assertEqual(result["executed"], 3)
        self.assertEqual(result["closed"], 2)
        self.assertEqual(result["open_censored"], 1)
        self.assertAlmostEqual(result["gross_expectancy_R"], 0.5)
        self.assertAlmostEqual(result["gross_profit_factor"], 2.0)


if __name__ == "__main__":
    unittest.main()

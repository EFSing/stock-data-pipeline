from datetime import date, timedelta
from unittest.mock import patch
import unittest

from core import Quote
from research.legacy_main_replay import (
    LEGACY_MAIN_COMMIT,
    legacy_main_replay_identity,
    legacy_main_replay_setup03_history,
    legacy_main_replay_setup03_history_cached,
)
from trading.events import Setup03Evaluation
from trading.models import Setup, SetupState
from trading.replay import replay_parity_mismatches, replay_setup03_history


def _quotes(count: int = 40) -> list[Quote]:
    return [
        Quote(
            "TEST",
            "Test",
            "US",
            date(2026, 1, 1) + timedelta(days=index),
            "fixture",
            100.0 + index % 7,
            101.0 + index % 7,
            99.0 + index % 7,
            100.5 + index % 7,
            None,
            None,
            1000.0,
            None,
            None,
            "USD",
        )
        for index in range(count)
    ]


class LegacyMainReplayTests(unittest.TestCase):
    SETUP = {
        "swing_lookback": 2,
        "platform_window": 20,
        "platform_tolerance_pct": 0.05,
        "arm_proximity_pct": 0.0,
    }
    DECISION = {"swing_lookback": 2, "atr_period": 2}

    def test_reference_uses_every_strict_prefix_and_original_positional_seam(self):
        quotes = _quotes(6)
        calls = []

        def fake_evaluate(prefix, risk_capital, setup_parameters, decision_parameters):
            calls.append((len(prefix), tuple(item.trade_date for item in prefix)))
            self.assertEqual(risk_capital, 1000.0)
            self.assertEqual(setup_parameters, self.SETUP)
            self.assertEqual(decision_parameters, self.DECISION)
            return Setup03Evaluation(
                setup=Setup("SETUP_03", SetupState.NONE),
                event_type=None,
                event_date=None,
                confirmed_date=None,
                decision=None,
            )

        with patch(
            "research.legacy_main_replay.evaluate_setup03_event",
            side_effect=fake_evaluate,
        ) as evaluator:
            report = legacy_main_replay_setup03_history(
                quotes,
                1000.0,
                self.SETUP,
                self.DECISION,
            )

        self.assertEqual([item[0] for item in calls], list(range(1, 7)))
        self.assertEqual(
            [item[1] for item in calls],
            [tuple(item.trade_date for item in quotes[:index + 1]) for index in range(6)],
        )
        self.assertEqual(evaluator.call_count, len(quotes))
        self.assertEqual(len(report.days), len(quotes))

    def test_identity_pins_the_requested_main_commit(self):
        identity = legacy_main_replay_identity()
        self.assertEqual(LEGACY_MAIN_COMMIT, identity["baseline_commit"])
        self.assertEqual(LEGACY_MAIN_COMMIT, "40a3e5f980bf82a85717748ae106847793d1469f")
        self.assertIn("quotes[:i+1]", identity["semantics"])
        self.assertTrue(identity["reference_source_sha256"].startswith("sha256:"))

    def test_reference_matches_current_shared_path_on_fixture(self):
        quotes = _quotes(120)
        legacy = legacy_main_replay_setup03_history(
            quotes, 100000.0, self.SETUP, self.DECISION
        )
        shared = replay_setup03_history(
            quotes, 100000.0, self.SETUP, self.DECISION
        )
        self.assertEqual(replay_parity_mismatches(legacy, shared), [])

    def test_audit_swing_cache_is_output_identical_to_raw_prefix_reference(self):
        quotes = _quotes(180)
        raw = legacy_main_replay_setup03_history(
            quotes, 100000.0, self.SETUP, self.DECISION
        )
        cached = legacy_main_replay_setup03_history_cached(
            quotes, 100000.0, self.SETUP, self.DECISION
        )
        self.assertEqual(replay_parity_mismatches(raw, cached), [])


if __name__ == "__main__":
    unittest.main()

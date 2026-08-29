from datetime import date, timedelta
import unittest

from core import Quote
from research.phase5j_v4_lifecycle_attribution import (
    build_symbol_trace,
    classify_first_divergence,
    classify_lineage,
    classify_propagation,
    find_divergence_episodes,
)


def _row(**changes):
    row = {
        "market": "US",
        "symbol": "TEST",
        "trade_date": "2026-01-01",
        "bar_index": 10,
        "tolerance": 0.03,
        "confirmed_swing_identities_available_as_of_t": [["HIGH", 1, 3, float(100).hex()]],
        "new_confirmed_swing_eligibility": True,
        "high_swing_count": 2,
        "low_swing_count": 2,
        "market_structure_classification": "RANGE",
        "high_span": 0.035,
        "low_span": 0.02,
        "platform_gate_pass": False,
        "platform_gate_failure_reasons": [],
        "platform_detected_this_bar": False,
        "setup_state": "NONE",
        "detected_index": None,
        "state_entered_index": None,
        "breakout_price": None,
        "structural_invalidation": None,
        "confirmed_index": None,
        "terminal_type": None,
        "terminal_date": None,
        "last_terminal_index": -1,
        "arm_threshold": None,
        "lifecycle_ordinal": None,
    }
    row.update(changes)
    return row


def _lifecycle(ordinal, *, tolerance, detected, root="root", terminal=20, breakout=100.0, invalidation=90.0):
    return {
        "market": "US",
        "symbol": "TEST",
        "tolerance": tolerance,
        "lifecycle_ordinal": ordinal,
        "first_detected_index": detected,
        "first_detected_date": f"2026-01-{detected:02d}",
        "frozen_breakout": breakout,
        "frozen_invalidation": invalidation,
        "terminal_index": terminal,
        "terminal_date": f"2026-02-{terminal - 19:02d}" if terminal is not None else None,
        "terminal_type": "CONFIRMED" if terminal is not None else None,
        "root_swing_identity": [[root, 1, 2, "0x1.0p+0"]],
    }


class Phase5JV4RootClassifierTests(unittest.TestCase):
    def test_simple_high_span_crossing(self):
        lower = _row(platform_gate_failure_reasons=["HIGH_SPAN_EXCEEDS_TOLERANCE"])
        upper = _row(tolerance=0.04, platform_gate_pass=True)
        self.assertEqual(classify_first_divergence(lower, upper)["primary_root_cause"], "HIGH_SPAN_THRESHOLD_CROSSING")

    def test_low_span_crossing(self):
        lower = _row(platform_gate_failure_reasons=["LOW_SPAN_EXCEEDS_TOLERANCE"])
        upper = _row(tolerance=0.04, platform_gate_pass=True)
        self.assertEqual(classify_first_divergence(lower, upper)["primary_root_cause"], "LOW_SPAN_THRESHOLD_CROSSING")

    def test_both_span_crossing(self):
        lower = _row(platform_gate_failure_reasons=["HIGH_SPAN_EXCEEDS_TOLERANCE", "LOW_SPAN_EXCEEDS_TOLERANCE"])
        upper = _row(tolerance=0.04, platform_gate_pass=True)
        self.assertEqual(classify_first_divergence(lower, upper)["primary_root_cause"], "BOTH_SPAN_THRESHOLD_CROSSING")

    def test_first_detection_divergence(self):
        lower = _row()
        upper = _row(tolerance=0.04, platform_detected_this_bar=True, setup_state="WATCH", detected_index=10, state_entered_index=10, breakout_price=100.0, structural_invalidation=90.0)
        self.assertEqual(classify_first_divergence(lower, upper)["primary_root_cause"], "PLATFORM_FIRST_DETECTION_DIVERGENCE")

    def test_breakout_anchor_divergence(self):
        lower = _row(platform_gate_pass=True, platform_detected_this_bar=True, setup_state="WATCH", detected_index=10, state_entered_index=10, breakout_price=100.0, structural_invalidation=90.0)
        upper = _row(tolerance=0.04, platform_gate_pass=True, platform_detected_this_bar=True, setup_state="WATCH", detected_index=10, state_entered_index=10, breakout_price=101.0, structural_invalidation=90.0)
        self.assertEqual(classify_first_divergence(lower, upper)["primary_root_cause"], "FROZEN_BREAKOUT_ANCHOR_DIVERGENCE")

    def test_invalidation_anchor_divergence(self):
        lower = _row(platform_gate_pass=True, platform_detected_this_bar=True, setup_state="WATCH", detected_index=10, state_entered_index=10, breakout_price=100.0, structural_invalidation=90.0)
        upper = _row(tolerance=0.04, platform_gate_pass=True, platform_detected_this_bar=True, setup_state="WATCH", detected_index=10, state_entered_index=10, breakout_price=100.0, structural_invalidation=89.0)
        self.assertEqual(classify_first_divergence(lower, upper)["primary_root_cause"], "FROZEN_INVALIDATION_ANCHOR_DIVERGENCE")

    def test_terminal_state_divergence(self):
        lower = _row(setup_state="WATCH", detected_index=5, state_entered_index=5, breakout_price=100.0, structural_invalidation=90.0)
        upper = _row(tolerance=0.04, setup_state="CONFIRMED", detected_index=5, state_entered_index=10, breakout_price=100.0, structural_invalidation=90.0, confirmed_index=10, terminal_type="CONFIRMED", terminal_date="2026-01-01", last_terminal_index=10)
        self.assertEqual(classify_first_divergence(lower, upper)["primary_root_cause"], "TERMINAL_STATE_DIVERGENCE")

    def test_episode_starts_at_first_real_divergence(self):
        same_lower = _row(bar_index=9, trade_date="2025-12-31")
        same_upper = _row(bar_index=9, trade_date="2025-12-31", tolerance=0.04)
        lower = _row(platform_gate_failure_reasons=["HIGH_SPAN_EXCEEDS_TOLERANCE"])
        upper = _row(tolerance=0.04, platform_gate_pass=True)
        episodes = find_divergence_episodes([same_lower, lower], [same_upper, upper])
        self.assertEqual(episodes[0]["first_divergence_bar"], 10)

    def test_auxiliary_failure_reason_difference_without_gate_fork_is_equivalent(self):
        lower = _row(platform_gate_failure_reasons=["HIGH_SPAN_EXCEEDS_TOLERANCE"])
        upper = _row(tolerance=0.04, platform_gate_failure_reasons=["LOW_SPAN_EXCEEDS_TOLERANCE"])
        self.assertEqual(find_divergence_episodes([lower], [upper]), [])


class Phase5JV4PropagationAndLineageTests(unittest.TestCase):
    def test_terminal_index_cascade(self):
        self.assertEqual(classify_propagation(["terminal_index"], 2), "TERMINAL_INDEX_CASCADE")

    def test_multi_lifecycle_cascade(self):
        self.assertEqual(classify_propagation(["terminal_index", "eligibility"], 3), "MULTI_STAGE_CASCADE")

    def test_lineage_classifies_anchor_and_terminal_differences(self):
        lower = [_lifecycle(1, tolerance=0.03, detected=5)]
        upper = [_lifecycle(1, tolerance=0.04, detected=6, terminal=21, breakout=101.0)]
        rows = classify_lineage(lower, upper, first_divergence_bar=5)
        self.assertEqual(rows[0]["lineage_class"], "SAME_ROOT_DIFFERENT_ANCHOR")

    def test_lineage_classifies_split_and_cascade_descendant(self):
        lower = [_lifecycle(1, tolerance=0.03, detected=5, root="shared")]
        upper = [
            _lifecycle(1, tolerance=0.04, detected=5, root="shared"),
            _lifecycle(2, tolerance=0.04, detected=12, root="shared"),
            _lifecycle(3, tolerance=0.04, detected=15, root="new"),
        ]
        rows = classify_lineage(lower, upper, first_divergence_bar=6)
        self.assertIn("SPLIT", {row["lineage_class"] for row in rows})
        self.assertIn("CASCADE_DESCENDANT", {row["lineage_class"] for row in rows})


class Phase5JV4TraceTests(unittest.TestCase):
    def test_every_bar_trace_contains_required_read_only_fields(self):
        quotes = [
            Quote(
                symbol="TEST", name="Test", market="US",
                trade_date=date(2026, 1, 1) + timedelta(days=index), source="fixture",
                open=100, high=101, low=99, close=100, preclose=100,
                pct_change=0, volume=1000, amount=None, turnover_rate=None, currency="USD",
            )
            for index in range(12)
        ]
        trace = build_symbol_trace(quotes, 0.03)
        self.assertEqual(len(trace["rows"]), len(quotes))
        row = trace["rows"][0]
        for field in (
            "confirmed_swing_identities_available_as_of_t", "new_confirmed_swing_eligibility",
            "platform_gate_pass", "platform_gate_failure_reasons", "last_terminal_index",
        ):
            self.assertIn(field, row)


if __name__ == "__main__":
    unittest.main()

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from core import Quote
from research.phase5j_v4_evidence import (
    anchor_divergence_summary,
    causal_consistency,
    candidate_summaries,
    load_setup_module_from_source,
    origin_main_parity_for_symbol,
    root_cause_summary,
    write_capsule,
)
from research.phase5j_v4_lifecycle_attribution import build_symbol_trace


class Phase5JV4EvidenceTests(unittest.TestCase):
    def test_candidate_summary_conserves_platforms_and_events(self):
        lifecycles = [
            {"market": "CN", "symbol": "C", "tolerance": 0.03, "terminal_type": "CONFIRMED", "terminal_date": "2026-01-02"},
            {"market": "CN", "symbol": "C", "tolerance": 0.04, "terminal_type": "FAILED", "terminal_date": "2026-01-03"},
            {"market": "US", "symbol": "U", "tolerance": 0.05, "terminal_type": "CONFIRMED", "terminal_date": "2026-01-04"},
        ]
        result = candidate_summaries(lifecycles, {"CN": 100, "US": 100}, {"CN": ["C"], "US": ["U"]})
        self.assertEqual(result["3.0%"]["CN"]["platform_count"], 1)
        self.assertEqual(result["3.0%"]["CN"]["confirmed_event_count"], 1)
        self.assertEqual(result["4.0%"]["CN"]["confirmed_event_count"], 0)

    def test_root_summary_includes_frozen_threshold_margins(self):
        episode = {
            "market": "CN", "symbol": "C", "lower_tolerance": 0.03, "upper_tolerance": 0.04,
            "primary_root_cause": "LOW_SPAN_THRESHOLD_CROSSING", "lower_lifecycle_ordinal": None,
            "upper_lifecycle_ordinal": 1,
            "distance_from_lower_frozen_tolerance_threshold": {"high": -0.01, "low": 0.002},
            "distance_from_upper_frozen_tolerance_threshold": {"high": -0.02, "low": -0.008},
        }
        rows = root_cause_summary([episode])
        row = next(item for item in rows if item["market"] == "CN" and item["root_cause"] == "LOW_SPAN_THRESHOLD_CROSSING")
        self.assertEqual(row["threshold_margin_descriptive"]["lower_low"]["median"], 0.002)
        self.assertEqual(row["threshold_margin_use"], "DESCRIPTION_ONLY_NOT_TOLERANCE_DESIGN")

    def test_anchor_summary_and_causal_consistency_are_mechanical(self):
        lineage = [{
            "market": "CN", "adjacent_lower_tolerance": 0.03, "adjacent_upper_tolerance": 0.04,
            "detection_shift": 2, "breakout_anchor_difference": 1.0,
            "invalidation_anchor_difference": -1.0, "terminal_shift": 3,
        }]
        anchors = anchor_divergence_summary(lineage)
        row = next(item for item in anchors if item["market"] == "CN" and item["lower_tolerance"] == 0.03)
        self.assertEqual(row["detection_shift"]["median"], 2)
        roots = [
            {"market": market, "lower_tolerance": lower, "upper_tolerance": upper, "root_cause": cause, "count": count}
            for lower, upper, cause, count in (
                (0.03, 0.04, "LOW_SPAN_THRESHOLD_CROSSING", 2),
                (0.04, 0.05, "HIGH_SPAN_THRESHOLD_CROSSING", 2),
            )
            for market in ("CN", "US", "POOLED")
        ]
        consistency = causal_consistency(roots)
        self.assertTrue(consistency["by_adjacent_pair"]["3.0%→4.0%"]["CN_US_consistent"])
        self.assertFalse(consistency["three_to_four_vs_four_to_five_consistent"])

    def test_origin_main_parity_seam_compares_setup_and_terminal_events(self):
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
        source = (Path(__file__).resolve().parents[1] / "trading" / "setup.py").read_text(encoding="utf-8")
        module = load_setup_module_from_source(source, "phase5j_v4_test_setup")
        parity = origin_main_parity_for_symbol(quotes, 0.03, trace["rows"], module)
        self.assertEqual(parity["setup_mismatches"], 0)
        self.assertEqual(parity["event_mismatches"], 0)

    def test_capsule_hash_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capsule.json"
            first = write_capsule(path, {"status": "TEST", "value": 1})
            second = write_capsule(path, {"value": 1, "status": "TEST"})
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

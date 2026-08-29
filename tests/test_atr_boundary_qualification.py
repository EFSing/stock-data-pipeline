from datetime import date
import unittest

import json

from research.atr_boundary_qualification import (
    CAPSULE_PATH,
    _event_metrics,
    _lifecycle_metrics,
    canonical_payload_digest,
)


class AtrBoundaryQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capsule = json.loads(CAPSULE_PATH.read_text(encoding="utf-8"))

    def test_frozen_qualification_result_is_fail_closed_and_hash_pinned(self):
        self.assertEqual(self.capsule["status"], "STOP_SETUP_03_STRUCTURAL_DEVELOPMENT")
        self.assertEqual(self.capsule["qualification"]["qualified_candidates"], [])
        self.assertIsNone(self.capsule["qualification"]["selected_candidate_atr"])
        self.assertEqual(
            self.capsule["integrity"]["canonical_payload_sha256"],
            canonical_payload_digest(self.capsule),
        )
        self.assertEqual(self.capsule["parity"]["status"], "PASS")
        self.assertEqual(self.capsule["reproducibility"]["status"], "PASS")
        self.assertFalse(self.capsule["controls"]["decision_engine_called"])
        self.assertFalse(self.capsule["controls"]["outcome_metrics_accessed"])

    def test_event_metrics_keep_exact_identity_and_report_shifted_match(self):
        old = [("CN", "000001.SZ", date(2026, 1, 2))]
        new = [("CN", "000001.SZ", date(2026, 1, 5))]
        sessions = {"CN": (date(2026, 1, 2), date(2026, 1, 5))}
        result = _event_metrics(old, new, sessions)
        self.assertEqual(result["retained_exact"], 0)
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["added_event_rate"], 1.0)
        self.assertEqual(result["disappeared_event_rate"], 1.0)
        self.assertEqual(result["trading_session_drift_median"], 1)
        self.assertEqual(result["trading_session_drift_p90"], 1)

    def test_lifecycle_metrics_count_changed_and_unmatched_ordinals(self):
        old = [{
            "canonical_symbol": "A",
            "ordinal": 1,
            "terminal_type": "CONFIRMED",
            "terminal_date": "2026-01-02",
            "detected_index": 10,
            "breakout_price": "0x1.0p+0",
            "structural_invalidation": "0x1.0p+0",
        }]
        current = [{
            "canonical_symbol": "A",
            "ordinal": 1,
            "terminal_type": "CONFIRMED",
            "terminal_date": "2026-01-05",
            "detected_index": 10,
            "breakout_price": "0x1.0p+0",
            "structural_invalidation": "0x1.0p+0",
        }, {
            "canonical_symbol": "A",
            "ordinal": 2,
            "terminal_type": "FAILED",
            "terminal_date": "2026-01-06",
            "detected_index": 15,
            "breakout_price": "0x1.0p+0",
            "structural_invalidation": "0x1.0p+0",
        }]
        result = _lifecycle_metrics(old, current)
        self.assertEqual(result["changed_retained_ordinal_count"], 1)
        self.assertEqual(result["unmatched_current_count"], 1)
        self.assertEqual(result["divergence_count"], 2)
        self.assertEqual(result["divergence_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

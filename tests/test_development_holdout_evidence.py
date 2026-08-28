from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import unittest

from research.development_holdout_evidence import (
    PRODUCTION_TOLERANCES,
    QUALIFICATION_TRANSITIONS,
    TOLERANCE_SEQUENCE,
    _adjacent_summary,
    _build_qualification,
)


def _report(market, symbol, events):
    return {"report": {"market": market, "symbol": symbol, "event_keys": events}}


class DevelopmentHoldoutEvidenceTests(unittest.TestCase):
    def test_adjacent_summary_keeps_exact_and_residual_matching_accounting(self):
        sessions = {"US": tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(20))}
        previous = [_report("US", "T", [("T", "2026-01-02"), ("T", "2026-01-10")])]
        current = [_report("US", "T", [("T", "2026-01-02"), ("T", "2026-01-11")])]
        summary = _adjacent_summary(
            0.03, 0.04, {0.03: previous, 0.04: current}, "US", sessions
        )
        self.assertEqual(summary["retained_exact"], 1)
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["unmatched_previous"], 0)
        self.assertEqual(summary["unmatched_current"], 0)
        self.assertEqual(summary["trading_day_drift_median"], 1)

    def test_tracked_capsule_has_self_consistent_canonical_hash(self):
        path = Path(__file__).resolve().parents[1] / "research" / "development" / "development_holdout_decision_capsule_v1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        stored = payload["integrity"]["canonical_payload_sha256"]
        payload["integrity"]["canonical_payload_sha256"] = None
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        actual = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.assertEqual(stored, actual)
        self.assertEqual(payload["status"], "SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION")

    def test_adjacent_summary_exposes_over_window_events_as_unmatched(self):
        start = date(2026, 1, 1)
        sessions = {"US": tuple(start + timedelta(days=index) for index in range(60))}
        previous = [_report("US", "T", [("T", start.isoformat())])]
        current = [_report("US", "T", [("T", (start + timedelta(days=41)).isoformat())])]
        summary = _adjacent_summary(
            0.03, 0.04, {0.03: previous, 0.04: current}, "US", sessions
        )
        self.assertEqual(summary["matched"], 0)
        self.assertEqual(summary["unmatched_previous"], 1)
        self.assertEqual(summary["unmatched_current"], 1)
        self.assertIsNone(summary["trading_day_drift_median"])

    def test_qualification_matrix_has_frozen_52_rows_and_conservative_selection(self):
        summaries = {}
        for tolerance in TOLERANCE_SEQUENCE:
            summaries[tolerance] = {
                market: {
                    "CONFIRMED_EVENTS": 8,
                    "max_symbol_event_share": 0.25,
                    "CONFIRMED_per_1000_bars": 1.0,
                }
                for market in ("CN", "US")
            }
        adjacent = {
            f"{previous:.1%}→{current:.1%}": {
                market: {
                    "exact_date_jaccard": 0.6,
                    "retention": 0.8,
                    "trading_day_drift_median": 5,
                    "trading_day_drift_P90": 15,
                }
                for market in ("CN", "US")
            }
            for previous, current in QUALIFICATION_TRANSITIONS
        }
        result = _build_qualification(summaries, adjacent)
        self.assertEqual(len(result["matrix"]), 52)
        self.assertEqual(result["qualified_candidates"], list(PRODUCTION_TOLERANCES))
        self.assertEqual(result["lexicographic_candidate"], 0.03)
        self.assertEqual(result["status"], "READY_FOR_SOL_FORMAL_FREEZE_DECISION")


if __name__ == "__main__":
    unittest.main()

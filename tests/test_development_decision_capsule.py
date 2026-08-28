from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.development_decision_capsule import (
    TOLERANCE_SEQUENCE,
    _build_statistics,
    write_capsule,
)


def _compact_reports():
    reports = []
    for tolerance in TOLERANCE_SEQUENCE:
        for market, symbol in (("CN", "CN.TEST"), ("US", "US.TEST")):
            reports.append({
                "platform_tolerance_pct": tolerance,
                "report": {
                    "symbol": symbol,
                    "market": market,
                    "bars": 10,
                    "state_counts": {
                        "NONE": 2,
                        "WATCH": 2,
                        "ARMED": 0,
                        "CONFIRMED": 5,
                        "FAILED": 1,
                    },
                    "terminal_reasons": {},
                    "platform_detected": 2,
                    "confirmed_events": 1,
                    "entry_allowed": 0,
                    "decision_reasons": {},
                    "event_keys": [[symbol, date(2026, 1, 5).isoformat()]],
                    "platform_spans": [{
                        "high_span": 0.02,
                        "low_span": 0.03,
                        "platform_width": 0.04,
                    }],
                },
            })
    return reports


class DecisionCapsuleTests(unittest.TestCase):
    def test_statistics_cover_all_tolerances_markets_and_required_fields(self):
        statistics = _build_statistics(_compact_reports())
        self.assertEqual(
            set(statistics["by_tolerance"]),
            {f"{value:.1%}" for value in TOLERANCE_SEQUENCE},
        )
        for rows in statistics["by_tolerance"].values():
            self.assertEqual(set(rows), {"CN", "US", "ALL"})
            for row in rows.values():
                self.assertTrue({
                    "symbol_count",
                    "bars",
                    "platform_detected",
                    "platform_per_1000_bars",
                    "NONE",
                    "WATCH",
                    "ARMED",
                    "CONFIRMED_STATE_DAYS",
                    "FAILED",
                    "CONFIRMED_EVENTS",
                    "CONFIRMED_per_1000_bars",
                    "ENTRY_ALLOWED",
                    "ENTRY_ALLOWED_per_1000_bars",
                    "symbols_with_zero_confirmed",
                    "symbols_with_1_to_2_confirmed",
                    "max_symbol_event_share",
                    "top_3_symbol_event_share",
                    "high_span_median",
                    "high_span_P90",
                    "low_span_median",
                    "low_span_P90",
                    "platform_width_median",
                    "platform_width_P90",
                }.issubset(row))
        self.assertEqual(
            set(statistics["cross_market_comparison"]),
            {"3.0%", "4.0%", "5.0%"},
        )

    def test_capsule_file_hash_and_content_are_deterministic(self):
        payload = {
            "schema_version": "test",
            "structure_only_statistics": {"value": 1, "nested": ["CN", "US"]},
        }
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"
            first_hashes = write_capsule(first, payload)
            second_hashes = write_capsule(second, payload)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_hashes, second_hashes)
            body = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(
                body["integrity"]["canonical_payload_sha256"],
                first_hashes["canonical_payload_sha256"],
            )
            self.assertNotIn("returns", first.read_text(encoding="utf-8").lower())
            self.assertNotIn("mfe", first.read_text(encoding="utf-8").lower())
            self.assertNotIn("mae", first.read_text(encoding="utf-8").lower())
            self.assertNotIn("p&l", first.read_text(encoding="utf-8").lower())
            self.assertNotIn("winrate", first.read_text(encoding="utf-8").lower())
            self.assertNotIn("final_oos", first.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()

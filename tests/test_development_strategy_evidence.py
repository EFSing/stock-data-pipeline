import copy
from datetime import date, timedelta
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from core import Quote
from research.development_dataset import (
    CN_DEVELOPMENT_ADJUSTMENT_MODE,
    CN_DEVELOPMENT_PROVIDER_ID,
    DEVELOPMENT_ADJUSTMENT_MODE,
    DEVELOPMENT_PROVIDER_ID,
    NUMERICAL_ORDERING_COMPARISON,
    NUMERICAL_ORDERING_MAX_ULPS,
    _normalize_frame,
    acquire_symbol,
    baostock_wire_symbol,
    ieee754_ulp_distance,
)
from research.development_universe import (
    A1_MANIFEST_PATH,
    DEVELOPMENT_LABELS,
    DEVELOPMENT_UNIVERSE_VERSION,
    load_development_universe_manifest,
    manifest_integrity_hash,
)
from trading.replay import replay_setup03_history
from trading.setup import (
    detect_platform_breakout_history_with_diagnostics,
    detect_platform_breakout_with_diagnostics,
)


def _quotes(count=100):
    rows = []
    for index in range(count):
        base = 100.0 + (index % 8) * 2.0
        rows.append(
            Quote(
                "TEST",
                "Test",
                "US",
                date(2017, 1, 1) + timedelta(days=index),
                DEVELOPMENT_PROVIDER_ID,
                base,
                base + 1.0,
                base - 1.0,
                base + 0.25,
                None,
                None,
                1000.0,
                None,
                None,
                "USD",
            )
        )
    return rows


class DevelopmentUniverseTests(unittest.TestCase):
    def test_frozen_universe_is_distinct_from_all_a1_candidates(self):
        manifest = load_development_universe_manifest()
        self.assertEqual(manifest["universe_version"], DEVELOPMENT_UNIVERSE_VERSION)
        self.assertEqual(tuple(manifest["artifact_labels"]), DEVELOPMENT_LABELS)
        self.assertEqual(manifest["a1_exclusion_proof"]["intersection"], [])
        self.assertEqual(manifest["a1_exclusion_proof"]["intersection_count"], 0)
        a1 = json.loads(A1_MANIFEST_PATH.read_text(encoding="utf-8"))
        a1_ids = {(row["market"], row["canonical_identity"]) for row in a1["symbols"]}
        development_ids = {
            (row["market"], row["canonical_identity"])
            for row in manifest["symbols"]
        }
        self.assertTrue(a1_ids.isdisjoint(development_ids))

    def test_same_version_universe_drift_fails_integrity(self):
        manifest = load_development_universe_manifest()
        changed = copy.deepcopy(manifest)
        changed["symbols"][0]["source_name"] = "changed after freeze"
        changed["integrity"]["manifest_sha256"] = manifest_integrity_hash(changed)
        self.assertNotEqual(
            changed["integrity"]["manifest_sha256"],
            manifest["integrity"]["manifest_sha256"],
        )


class DevelopmentDatasetTests(unittest.TestCase):
    def _row(self):
        return {
            "market": "US",
            "canonical_symbol": "TEST",
            "canonical_identity": "US|TEST",
            "yfinance_symbol": "TEST",
            "source_name": "Test",
        }

    def test_yfinance_frame_is_normalized_without_filling_dates(self):
        frame = pd.DataFrame(
            {
                "Date": ["2017-01-03", "2017-01-05"],
                "Open": [10.0, 12.0],
                "High": [11.0, 13.0],
                "Low": [9.0, 11.0],
                "Close": [10.5, 12.5],
                "Volume": [100.0, 200.0],
            }
        ).set_index("Date")
        quotes, normalized, metadata = _normalize_frame(self._row(), frame)
        self.assertEqual([quote.trade_date.isoformat() for quote in quotes], ["2017-01-03", "2017-01-05"])
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["source_provider"], DEVELOPMENT_PROVIDER_ID)
        self.assertEqual(normalized[0]["adjustment_mode"], DEVELOPMENT_ADJUSTMENT_MODE)
        self.assertEqual(metadata["missing_bar_status"], "NOT_INFERRED_NO_FILL")

    def test_conflicting_duplicate_is_fail_closed_and_not_selected(self):
        frame = pd.DataFrame(
            {
                "Date": ["2017-01-03", "2017-01-03"],
                "Open": [10.0, 10.0],
                "High": [11.0, 12.0],
                "Low": [9.0, 9.0],
                "Close": [10.5, 11.5],
                "Volume": [100.0, 100.0],
            }
        ).set_index("Date")
        with TemporaryDirectory() as directory:
            acquired = acquire_symbol(
                self._row(),
                raw_dir=Path(directory) / "raw",
                normalized_dir=Path(directory) / "normalized",
                fetcher=lambda symbol, start, end: (frame, b"raw-response"),
            )
            self.assertEqual(acquired.dataset_row["qc_status"], "PROVIDER_OR_QC_FAILED")
            self.assertIn("DATA_CONFLICT_FAIL_CLOSED", acquired.dataset_row["qc_reason"])
            self.assertEqual(acquired.quotes, ())

    def test_baostock_mapping_and_blank_suspension_volume_are_explicit(self):
        self.assertEqual(baostock_wire_symbol("601390.SH"), "sh.601390")
        self.assertEqual(baostock_wire_symbol("000027.SZ"), "sz.000027")
        frame = pd.DataFrame(
            {
                "Date": ["2022-04-06"],
                "Open": [10.0],
                "High": [10.0],
                "Low": [10.0],
                "Close": [10.0],
                "Volume": [""],
                "amount": [""],
                "turn": [""],
                "pctChg": [""],
            }
        ).set_index("Date")
        quotes, normalized, metadata = _normalize_frame(
            {**self._row(), "market": "CN", "canonical_symbol": "000065.SZ"},
            frame,
            provider_id=CN_DEVELOPMENT_PROVIDER_ID,
            adjustment_mode=CN_DEVELOPMENT_ADJUSTMENT_MODE,
        )
        self.assertEqual(len(quotes), 1)
        self.assertEqual(normalized[0]["volume"], 0.0)
        self.assertEqual(
            metadata["source_blank_suspension_volume_zero_count"], 1
        )
        self.assertEqual(quotes[0].source, CN_DEVELOPMENT_PROVIDER_ID)

    def test_numeric_ordering_rule_accepts_only_the_registered_ulp_boundary(self):
        high = 100.0
        within = high
        for _ in range(NUMERICAL_ORDERING_MAX_ULPS):
            within = math.nextafter(within, math.inf)
        frame = pd.DataFrame(
            {
                "Date": ["2017-01-03"],
                "Open": [90.0],
                "High": [high],
                "Low": [80.0],
                "Close": [within],
                "Volume": [100.0],
            }
        ).set_index("Date")
        _, normalized, metadata = _normalize_frame(
            self._row(),
            frame,
            numeric_ordering_rule={**NUMERICAL_ORDERING_COMPARISON, "enabled": True},
        )
        self.assertEqual(ieee754_ulp_distance(within, high), NUMERICAL_ORDERING_MAX_ULPS)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(metadata["numeric_ordering_tolerance_hit_count"], 1)

        beyond = math.nextafter(within, math.inf)
        frame["Close"] = [beyond]
        with self.assertRaisesRegex(ValueError, "invalid OHLC ordering"):
            _normalize_frame(
                self._row(),
                frame,
                numeric_ordering_rule={**NUMERICAL_ORDERING_COMPARISON, "enabled": True},
            )


class ReplayOptimizationTests(unittest.TestCase):
    def test_history_snapshots_match_each_as_of_prefix(self):
        setup = {
            "swing_lookback": 5,
            "platform_window": 40,
            "platform_tolerance_pct": 0.05,
            "arm_proximity_pct": 0.0,
        }
        quotes = _quotes()
        history = detect_platform_breakout_history_with_diagnostics(quotes, **setup)
        for index, expected_quotes in enumerate(
            (quotes[:index + 1] for index in range(len(quotes)))
        ):
            expected = detect_platform_breakout_with_diagnostics(
                expected_quotes, **setup
            )
            self.assertEqual(history[index], expected)

    def test_precomputed_swings_preserve_existing_replay_result(self):
        setup = {
            "swing_lookback": 5,
            "platform_window": 40,
            "platform_tolerance_pct": 0.05,
            "arm_proximity_pct": 0.0,
        }
        decision = {
            "swing_lookback": 5,
            "atr_period": 14,
            "atr_buffer": 0.5,
            "max_chase_atr": 0.5,
        }
        baseline = replay_setup03_history(_quotes(), 100000.0, setup, decision)
        optimized = replay_setup03_history(
            _quotes(), 100000.0, setup, decision, precompute_swings=True
        )
        self.assertEqual(baseline, optimized)


if __name__ == "__main__":
    unittest.main()

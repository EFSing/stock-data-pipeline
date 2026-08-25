import gzip
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from core import Quote
from research.replay_input import (
    ManifestChange,
    build_input_manifest,
    compare_input_manifests,
    read_frozen_input,
    read_input_manifest,
    write_frozen_input,
    write_input_manifest,
)
from trading.replay import replay_setup03_history


def quote(
    symbol: str,
    index: int,
    close: float,
    *,
    start: date = date(2026, 1, 1),
) -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
        market="US",
        trade_date=start + timedelta(days=index),
        source="fixture",
        open=close - 0.25,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        preclose=close - 0.5,
        pct_change=0.01,
        volume=1000.0 + index,
        amount=100000.0 + index,
        turnover_rate=0.1,
        currency="USD",
    )


class ReplayInputHashTests(unittest.TestCase):
    def test_identical_input_hash_is_stable_and_order_independent(self):
        a = [quote("A", 0, 10.0), quote("A", 1, 11.0)]
        b = [quote("B", 0, 20.0)]

        first = build_input_manifest({"B": b, "A": a})
        second = build_input_manifest({"A": list(a), "B": list(b)})

        self.assertEqual(first, second)
        self.assertTrue(first.aggregate_hash.startswith("sha256:"))
        self.assertEqual([item.symbol for item in first.symbols], ["A", "B"])
        self.assertEqual(first.total_bar_count, 3)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            write_input_manifest(path, first)
            self.assertEqual(read_input_manifest(path), first)

    def test_single_ohlc_revision_changes_hash_with_same_bar_count(self):
        original = [quote("A", 0, 10.0), quote("A", 1, 11.0)]
        revised = [original[0], replace(original[1], high=12.5)]

        previous = build_input_manifest({"A": original})
        current = build_input_manifest({"A": revised})
        comparison = compare_input_manifests(previous, current)

        self.assertNotEqual(previous.aggregate_hash, current.aggregate_hash)
        self.assertNotEqual(
            previous.symbols[0].input_hash, current.symbols[0].input_hash
        )
        self.assertEqual(
            comparison[0].status,
            ManifestChange.CONTENT_CHANGED_WITH_SAME_BAR_COUNT,
        )

    def test_bar_count_and_symbol_add_remove_are_explicit(self):
        previous = build_input_manifest(
            {
                "A": [quote("A", 0, 10.0)],
                "REMOVED": [quote("REMOVED", 0, 20.0)],
            }
        )
        current = build_input_manifest(
            {
                "A": [quote("A", 0, 10.0), quote("A", 1, 11.0)],
                "ADDED": [quote("ADDED", 0, 30.0)],
            }
        )

        statuses = {
            item.symbol: item.status
            for item in compare_input_manifests(previous, current)
        }

        self.assertEqual(statuses["A"], ManifestChange.BAR_COUNT_CHANGED)
        self.assertEqual(statuses["ADDED"], ManifestChange.SYMBOL_ADDED)
        self.assertEqual(statuses["REMOVED"], ManifestChange.SYMBOL_REMOVED)

    def test_date_range_change_with_same_bar_count_is_explicit(self):
        previous = build_input_manifest(
            {"A": [quote("A", 0, 10.0), quote("A", 1, 11.0)]}
        )
        current = build_input_manifest(
            {
                "A": [
                    quote("A", 0, 10.0, start=date(2026, 1, 2)),
                    quote("A", 1, 11.0, start=date(2026, 1, 2)),
                ]
            }
        )

        comparison = compare_input_manifests(previous, current)

        self.assertEqual(comparison[0].status, ManifestChange.DATE_RANGE_CHANGED)

    def test_identical_manifest_comparison_is_explicit(self):
        manifest = build_input_manifest({"A": [quote("A", 0, 10.0)]})

        comparison = compare_input_manifests(manifest, manifest)

        self.assertEqual(comparison[0].status, ManifestChange.IDENTICAL)


class FrozenReplayInputTests(unittest.TestCase):
    ENTRY_ALLOWED_CLOSES = [
        90, 94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
        94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
        94, 98, 102, 106, 110, 106, 104, 110.3,
    ]

    def test_frozen_input_round_trip_and_replay_result_are_identical(self):
        quotes = [
            replace(
                quote("T", index, close),
                open=close,
                high=close,
                low=close,
                close=close,
            )
            for index, close in enumerate(self.ENTRY_ALLOWED_CLOSES)
        ]
        setup_parameters = {"swing_lookback": 2, "platform_window": 40}
        decision_parameters = {"swing_lookback": 2, "atr_period": 14}
        expected_report = replay_setup03_history(
            quotes, 1000.0, setup_parameters, decision_parameters
        )

        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.jsonl.gz"
            second_path = Path(directory) / "second.jsonl.gz"
            expected_manifest = write_frozen_input(first_path, {"T": quotes})
            write_frozen_input(second_path, {"T": list(quotes)})
            loaded, actual_manifest = read_frozen_input(first_path)

            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(actual_manifest, expected_manifest)
            self.assertEqual(loaded["T"], quotes)
            actual_report = replay_setup03_history(
                loaded["T"], 1000.0, setup_parameters, decision_parameters
            )
            self.assertEqual(actual_report, expected_report)

    def test_frozen_input_detects_content_tampering(self):
        quotes = {"A": [quote("A", 0, 10.0)]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl.gz"
            write_frozen_input(path, quotes)
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                records = [json.loads(line) for line in handle]
            records[1]["bar"]["close"] = float(11.0).hex()
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")

            with self.assertRaisesRegex(ValueError, "embedded manifest"):
                read_frozen_input(path)


if __name__ == "__main__":
    unittest.main()

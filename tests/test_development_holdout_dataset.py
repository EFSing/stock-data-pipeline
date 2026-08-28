from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from core import Quote
from research.development_dataset import AcquiredSymbol, DevelopmentDataError, _normalize_frame
from research.development_holdout_dataset import (
    BLOCKER_STATUS,
    READY_STATUS,
    _request_contract,
    build_dataset_manifest,
    dataset_manifest_integrity_hash,
    load_dataset_manifest,
    load_frozen_holdout,
)
from research.development_holdout_universe import load_holdout_universe_manifest
from research.replay_input import ReplayInputManifest, SymbolInputManifest


def _quote(row, *, source="TEST"):
    return Quote(
        symbol=row["canonical_symbol"], name=row["canonical_symbol"], market=row["market"],
        trade_date=date(2026, 1, 2), source=source,
        open=10.0, high=11.0, low=9.0, close=10.5, preclose=None,
        pct_change=None, volume=100.0, amount=None, turnover_rate=None,
        currency="CNY" if row["market"] == "CN" else "USD",
    )


def _replay_manifest_from_wrapper(wrapper):
    raw = wrapper["replay_manifest"]
    return ReplayInputManifest(
        schema_version=raw["schema_version"],
        aggregate_hash=raw["aggregate_hash"],
        total_symbol_count=int(raw["total_symbol_count"]),
        total_bar_count=int(raw["total_bar_count"]),
        symbols=tuple(
            SymbolInputManifest(
                symbol=item["symbol"],
                bar_count=int(item["bar_count"]),
                start_date=date.fromisoformat(item["start_date"]),
                end_date=date.fromisoformat(item["end_date"]),
                input_hash=item["input_hash"],
            )
            for item in raw["symbols"]
        ),
    )


class DevelopmentHoldoutDatasetTests(unittest.TestCase):
    def test_tracked_frozen_dataset_manifest_is_valid(self):
        path = Path(__file__).resolve().parents[1] / "research" / "development_holdout" / "dataset_manifest.json"
        manifest = load_dataset_manifest(path)
        self.assertEqual(manifest["coverage_status"], READY_STATUS)
        self.assertEqual(manifest["aggregate_symbol_count"], 40)
        self.assertEqual(manifest["aggregate_valid_bar_count"], 86305)

    def test_tracked_replay_wrapper_is_cross_bound_and_self_consistent(self):
        root = Path(__file__).resolve().parents[1]
        dataset_path = root / "research" / "development_holdout" / "dataset_manifest.json"
        replay_path = root / "research" / "development_holdout" / "replay_manifest.json"
        wrapper = json.loads(replay_path.read_text(encoding="utf-8"))
        replay_manifest = _replay_manifest_from_wrapper(wrapper)

        with patch(
            "research.development_holdout_dataset.read_frozen_input",
            return_value=({}, replay_manifest),
        ):
            manifest, _, loaded_replay_manifest = load_frozen_holdout(
                dataset_path, root / "unused-frozen-input.jsonl.gz", replay_path
            )

        self.assertEqual(wrapper["dataset_manifest_sha256"], manifest["integrity"]["manifest_sha256"])
        self.assertEqual(wrapper["replay_manifest"]["aggregate_hash"], manifest["replay_input_manifest_sha256"])
        self.assertEqual(wrapper["replay_manifest"], loaded_replay_manifest.to_dict())
        self.assertEqual(wrapper["integrity"]["manifest_sha256"], dataset_manifest_integrity_hash(wrapper))
        self.assertEqual(wrapper["replay_manifest"]["total_symbol_count"], 40)
        self.assertEqual(wrapper["replay_manifest"]["total_bar_count"], 86305)

    def test_replay_cross_binding_mutations_fail_closed(self):
        root = Path(__file__).resolve().parents[1]
        dataset_path = root / "research" / "development_holdout" / "dataset_manifest.json"
        replay_path = root / "research" / "development_holdout" / "replay_manifest.json"
        manifest = load_dataset_manifest(dataset_path)
        wrapper = json.loads(replay_path.read_text(encoding="utf-8"))
        replay_manifest = _replay_manifest_from_wrapper(wrapper)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            for name, mutated in (
                ("dataset-binding", {**wrapper, "dataset_manifest_sha256": "sha256:" + "0" * 64}),
                (
                    "replay-binding",
                    {
                        **wrapper,
                        "replay_manifest": {
                            **wrapper["replay_manifest"],
                            "aggregate_hash": "sha256:" + "1" * 64,
                        },
                    },
                ),
            ):
                mutated = deepcopy(mutated)
                mutated["integrity"] = {
                    "manifest_sha256": dataset_manifest_integrity_hash(mutated),
                }
                mutated_path = temp / f"{name}.json"
                mutated_path.write_text(
                    json.dumps(mutated, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                with self.subTest(name=name):
                    with patch(
                        "research.development_holdout_dataset.read_frozen_input",
                        return_value=({}, replay_manifest),
                    ):
                        with self.assertRaises(ValueError):
                            load_frozen_holdout(dataset_path, temp / "unused-frozen-input.jsonl.gz", mutated_path)

            mutated_dataset = deepcopy(manifest)
            mutated_dataset["replay_input_manifest_sha256"] = "sha256:" + "2" * 64
            mutated_dataset["integrity"] = {
                "manifest_sha256": dataset_manifest_integrity_hash(mutated_dataset),
            }
            mutated_wrapper = deepcopy(wrapper)
            mutated_wrapper["dataset_manifest_sha256"] = mutated_dataset["integrity"]["manifest_sha256"]
            mutated_wrapper["integrity"] = {
                "manifest_sha256": dataset_manifest_integrity_hash(mutated_wrapper),
            }
            mutated_dataset_path = temp / "dataset-replay-binding.json"
            mutated_dataset_path.write_text(
                json.dumps(mutated_dataset, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            mutated_wrapper_path = temp / "dataset-replay-binding-wrapper.json"
            mutated_wrapper_path.write_text(
                json.dumps(mutated_wrapper, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with patch(
                "research.development_holdout_dataset.read_frozen_input",
                return_value=({}, replay_manifest),
            ):
                with self.assertRaises(ValueError):
                    load_frozen_holdout(
                        mutated_dataset_path,
                        temp / "unused-frozen-input.jsonl.gz",
                        mutated_wrapper_path,
                    )

    def test_provider_contract_is_fixed_by_market(self):
        universe = load_holdout_universe_manifest()
        cn = next(row for row in universe["symbols"] if row["market"] == "CN")
        us = next(row for row in universe["symbols"] if row["market"] == "US")
        cn_provider, cn_adjustment, _, cn_contract, _ = _request_contract(cn)
        us_provider, us_adjustment, _, us_contract, _ = _request_contract(us)
        self.assertEqual(cn_provider, "BAOSTOCK_DEVELOPMENT_QFQ")
        self.assertEqual(cn_adjustment, "BAOSTOCK_QFQ_ADJUSTFLAG_2")
        self.assertEqual(cn_contract["method"], "baostock.query_history_k_data_plus")
        self.assertEqual(cn_contract["frequency"], "d")
        self.assertEqual(cn_contract["adjustflag"], "2")
        self.assertEqual(us_provider, "YFINANCE_DEVELOPMENT_HISTORICAL")
        self.assertEqual(us_adjustment, "YFINANCE_AUTO_ADJUST_TRUE")
        self.assertTrue(us_contract["auto_adjust"])
        self.assertFalse(us_contract["repair"])

    def test_baostock_blank_activity_only_normalizes_existing_equal_ohlc_bar(self):
        universe = load_holdout_universe_manifest()
        row = next(item for item in universe["symbols"] if item["market"] == "CN")
        frame = pd.DataFrame(
            [{"date": "2026-01-02", "Open": "10", "High": "10", "Low": "10", "Close": "10",
              "Volume": "", "amount": "", "turn": "", "pctChg": ""}]
        ).set_index("date")
        quotes, normalized, metadata = _normalize_frame(
            row, frame, provider_id="BAOSTOCK_DEVELOPMENT_QFQ",
            adjustment_mode="BAOSTOCK_QFQ_ADJUSTFLAG_2",
            numeric_ordering_rule={"enabled": False},
        )
        self.assertEqual(len(quotes), 1)
        self.assertEqual(normalized[0]["volume"], 0.0)
        self.assertEqual(metadata["source_blank_suspension_volume_zero_count"], 1)

    def test_invalid_ordering_fails_closed(self):
        universe = load_holdout_universe_manifest()
        row = next(item for item in universe["symbols"] if item["market"] == "US")
        frame = pd.DataFrame(
            [{"Date": "2026-01-02", "Open": 10.0, "High": 9.0, "Low": 8.0, "Close": 8.5, "Volume": 100.0}]
        ).set_index("Date")
        with self.assertRaises(DevelopmentDataError):
            _normalize_frame(row, frame, numeric_ordering_rule={"enabled": False})

    def test_coverage_shortfall_is_not_replay_ready(self):
        universe = load_holdout_universe_manifest()
        acquired = []
        for row in (next(item for item in universe["symbols"] if item["market"] == "CN"),
                    next(item for item in universe["symbols"] if item["market"] == "US")):
            normalized = ({
                "market": row["market"], "canonical_symbol": row["canonical_symbol"],
                "date": "2026-01-02", "open": 10.0, "high": 11.0, "low": 9.0,
                "close": 10.5, "volume": 100.0,
                "source_provider": "TEST", "adjustment_mode": "TEST",
            },)
            dataset_row = {
                "market": row["market"], "canonical_symbol": row["canonical_symbol"],
                "canonical_identity": row["canonical_identity"], "yfinance_symbol": row["yfinance_symbol"],
                "provider_id": "TEST", "adjustment_mode": "TEST", "qc_status": "VALID_ACCEPTED",
                "qc_reason": "", "bar_count": 1,
            }
            acquired.append(AcquiredSymbol(row, (_quote(row),), normalized, dataset_row))
        manifest, symbol_quotes, _ = build_dataset_manifest(universe, acquired)
        self.assertEqual(manifest["coverage_status"], BLOCKER_STATUS)
        self.assertNotEqual(manifest["coverage_status"], READY_STATUS)
        self.assertEqual(set(symbol_quotes), {acquired[0].manifest_row["canonical_symbol"], acquired[1].manifest_row["canonical_symbol"]})


if __name__ == "__main__":
    unittest.main()

from datetime import date
from pathlib import Path
import unittest

import pandas as pd

from core import Quote
from research.development_dataset import AcquiredSymbol, DevelopmentDataError, _normalize_frame
from research.development_holdout_dataset import (
    BLOCKER_STATUS,
    READY_STATUS,
    _request_contract,
    build_dataset_manifest,
    load_dataset_manifest,
)
from research.development_holdout_universe import load_holdout_universe_manifest


def _quote(row, *, source="TEST"):
    return Quote(
        symbol=row["canonical_symbol"], name=row["canonical_symbol"], market=row["market"],
        trade_date=date(2026, 1, 2), source=source,
        open=10.0, high=11.0, low=9.0, close=10.5, preclose=None,
        pct_change=None, volume=100.0, amount=None, turnover_rate=None,
        currency="CNY" if row["market"] == "CN" else "USD",
    )


class DevelopmentHoldoutDatasetTests(unittest.TestCase):
    def test_tracked_frozen_dataset_manifest_is_valid(self):
        path = Path(__file__).resolve().parents[1] / "research" / "development_holdout" / "dataset_manifest.json"
        manifest = load_dataset_manifest(path)
        self.assertEqual(manifest["coverage_status"], READY_STATUS)
        self.assertEqual(manifest["aggregate_symbol_count"], 40)
        self.assertEqual(manifest["aggregate_valid_bar_count"], 86305)

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

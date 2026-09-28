from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import unittest

from core import Quote
from research.setup01_d1_prospective import validate_session_snapshot
from research.setup01_d1_source_contract import (
    D1_SOURCE_CONTRACT_VERSION,
    build_d1_snapshot_from_candidate_runtime,
    build_d1_source_contract,
)


@dataclass
class FakeSeed:
    market: str = "US"
    symbol: str = "TEST"
    name: str = "Test"
    sector: str = "Technology"
    asset_class: str = "Equity"
    exchange: str = "XNYS"
    currency: str = "USD"
    source: str = "fixture-seed"
    source_as_of: date = date(2026, 9, 25)
    reference_price: float = 100.0
    board_rule: object | None = None
    metadata_status: str = "OK"
    source_symbol: str = "TEST"
    provenance: tuple[str, ...] = ()


@dataclass
class FakeRecord:
    symbol: str = "TEST"
    included: bool = True

    def to_row(self):
        return {
            "market": "US", "symbol": self.symbol, "name": "Test", "sector": "Technology",
            "included": self.included, "source": "fixture-seed", "history_bar_count": 30,
            "latest_history_date": "2026-09-25",
        }


@dataclass
class FakeUniverse:
    records: tuple[FakeRecord, ...]

    @property
    def included(self):
        return tuple(item for item in self.records if item.included)


class FakeRuntime:
    market = "US"
    as_of_date = date(2026, 9, 25)
    seeds = (FakeSeed(),)
    universe = FakeUniverse((FakeRecord(),))
    deep_histories = {}
    short_histories = {}
    deep_ready_symbols = ("TEST",)
    qfq_contract = {
        "seed": "fixture seed",
        "qfq": "fixture QFQ exact completed session",
    }
    seed_source_as_of = date(2026, 9, 25)
    errors = ()
    status = "SUCCESS"


def _quotes():
    values = []
    start = date(2026, 8, 17)
    for index in range(40):
        day = start + timedelta(days=index)
        close = 100.0 + index * 0.1
        values.append(Quote(
            "TEST", "Test", "US", day, "fixture-qfq",
            close - 0.2, close + 0.6, close - 0.8, close,
            close - 0.1, None, 1000 + index, None, None, "USD",
        ))
    return values


class D1SourceContractTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        quotes = _quotes()
        self.runtime.deep_histories = {"TEST": tuple(quotes)}
        self.runtime.short_histories = {"TEST": tuple(quotes[:30])}

    def test_contract_keeps_raw_qfq_prefix_and_explicit_no_signal(self):
        contract = build_d1_source_contract(
            self.runtime,
            session_identity={
                "market": "US", "trade_date": "2026-09-25",
                "identity": "exchange_calendars:XNYS:2026-09-25",
                "exact_exchange_calendar": True,
            },
            acquired_at="2026-09-26T05:00:00+08:00",
        )
        self.assertEqual(contract["status"], "VERIFIED")
        self.assertEqual(contract["contract_version"], D1_SOURCE_CONTRACT_VERSION)
        self.assertIn("TEST", contract["raw_source_snapshot"]["raw_prefix_by_symbol"])
        self.assertIn("TEST", contract["normalized_prefix_snapshot"]["qfq_prefix_by_symbol"])
        events = contract["research_observation_report"]["observations"]
        self.assertTrue(any(item["event_type"] == "NO_SIGNAL" for item in events))
        self.assertFalse(any(item.get("formal_entry_allowed") for item in events))

    def test_snapshot_embeds_chinese_research_report_and_hashes_contract(self):
        snapshot = build_d1_snapshot_from_candidate_runtime(
            self.runtime,
            session_identity={
                "market": "US", "trade_date": "2026-09-25",
                "identity": "exchange_calendars:XNYS:2026-09-25",
                "exact_exchange_calendar": True,
            },
            acquired_at="2026-09-26T05:00:00+08:00",
        )
        validate_session_snapshot(snapshot)
        report = snapshot["components"]["research_observation_report"]["payload"]
        self.assertIn("# SETUP_01 D1 只读研究观察", report["report_markdown"])
        self.assertFalse(snapshot["production_state_write"])
        self.assertFalse(snapshot["paper_write"])
        self.assertFalse(snapshot["broker_order"])

    def test_incomplete_or_private_source_cannot_become_formal_snapshot(self):
        self.runtime.short_histories = {}
        contract = build_d1_source_contract(
            self.runtime,
            session_identity={
                "market": "US", "trade_date": "2026-09-25",
                "identity": "exchange_calendars:XNYS:2026-09-25",
                "exact_exchange_calendar": True,
            },
            acquired_at="2026-09-26T05:00:00+08:00",
        )
        self.assertEqual(contract["status"], "INCOMPLETE")
        snapshot = build_d1_snapshot_from_candidate_runtime(
            self.runtime,
            session_identity={
                "market": "US", "trade_date": "2026-09-25",
                "identity": "exchange_calendars:XNYS:2026-09-25",
                "exact_exchange_calendar": True,
            },
            acquired_at="2026-09-26T05:00:00+08:00",
        )
        self.assertFalse(snapshot["prospective_eligible"])

        self.runtime.short_histories = {"TEST": tuple(_quotes()[:30])}
        self.runtime.qfq_contract = {
            **self.runtime.qfq_contract,
            "holdings": "forbidden-private-field",
        }
        with self.assertRaisesRegex(ValueError, "private holdings/account"):
            build_d1_snapshot_from_candidate_runtime(
                self.runtime,
                session_identity={
                    "market": "US", "trade_date": "2026-09-25",
                    "identity": "exchange_calendars:XNYS:2026-09-25",
                    "exact_exchange_calendar": True,
                },
                acquired_at="2026-09-26T05:00:00+08:00",
            )


if __name__ == "__main__":
    unittest.main()

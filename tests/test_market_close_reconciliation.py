from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from research.setup01_d1_activation import build_activation_record
from research.setup01_d1_source_contract import source_contract_descriptor
from research.setup01_d1_vps_store import VpsObjectMissing
from scripts.run_market_close_reconcile import reconcile_market
from trading.production_prerequisites import ExactExchangeCalendarProvider


class _Store:
    def __init__(self, activation):
        self.activation = activation
        self.sessions = {}

    def load_activation_record(self, market):
        return self.activation

    def load(self, market, session_date):
        key = (str(market).upper(), session_date.isoformat() if hasattr(session_date, "isoformat") else str(session_date))
        if key not in self.sessions:
            raise VpsObjectMissing(1, "D1_REMOTE_OBJECT_MISSING")
        return self.sessions[key]


def _activation(market="CN"):
    return build_activation_record(
        market=market,
        activation_timestamp="2026-09-01T08:00:00+08:00",
        backend_identity="SETUP01_D1_VPS_SSH_DURABLE_STORAGE",
        backend_version="VPS_D1_DURABLE_BACKEND_V1",
        storage_identity_sha256="a" * 64,
        code_sha="b" * 40,
        source_contract=source_contract_descriptor(),
        observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
    )


class MarketCloseReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.provider = ExactExchangeCalendarProvider()

    def _collector(self, store):
        calls = []

        def collect(market, **kwargs):
            calls.append((market, kwargs["now"]))
            session = self.provider.latest_completed_session(market, now=kwargs["now"])
            payload = {
                "session_date": session.trade_date.isoformat(),
                "event_sha256": "c" * 64,
                "status": "COMMITTED",
            }
            store.sessions[(market, session.trade_date.isoformat())] = payload
            return payload

        return calls, collect

    def test_cn_normal_delayed_and_cross_midnight_resolution(self):
        store = _Store(_activation("CN"))
        calls, collector = self._collector(store)
        for now, expected in (
            (datetime(2026, 9, 29, 9, 30, tzinfo=timezone.utc), "2026-09-29"),
            (datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc), "2026-09-29"),
            (datetime(2026, 9, 29, 17, 46, tzinfo=timezone.utc), "2026-09-29"),
        ):
            receipt = reconcile_market(
                "CN", now=now, store=store, calendar_provider=self.provider, collector=collector,
            )
            self.assertEqual(receipt["session_date"], expected)
        self.assertEqual(len(calls), 1)
        self.assertEqual(store.sessions.keys().__iter__().__next__(), ("CN", "2026-09-29"))

    def test_before_next_open_dispatches_and_after_next_open_misses_without_backfill(self):
        store = _Store(_activation("CN"))
        calls, collector = self._collector(store)
        eligible = reconcile_market(
            "CN", now=datetime(2026, 9, 29, 17, 46, tzinfo=timezone.utc),
            store=store, calendar_provider=self.provider, collector=collector,
        )
        self.assertEqual(eligible["status"], "COMMITTED")
        store.sessions.clear()
        missed = reconcile_market(
            "CN", now=datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc),
            store=store, calendar_provider=self.provider, collector=collector,
        )
        self.assertEqual(missed["status"], "MISSED_PROSPECTIVE_SESSION")
        self.assertEqual(len(calls), 1)

    def test_already_committed_is_noop_and_duplicate_reconciliation_is_safe(self):
        store = _Store(_activation("US"))
        calls, collector = self._collector(store)
        now = datetime(2026, 9, 29, 1, 46, tzinfo=timezone.utc)
        first = reconcile_market(
            "US", now=now, store=store, calendar_provider=self.provider, collector=collector,
        )
        second = reconcile_market(
            "US", now=now, store=store, calendar_provider=self.provider, collector=collector,
        )
        self.assertEqual(first["status"], "COMMITTED")
        self.assertEqual(second["status"], "NOOP_ALREADY_COMMITTED")
        self.assertEqual(len(calls), 1)

    def test_pre_activation_session_is_never_collected(self):
        activation = build_activation_record(
            market="CN",
            activation_timestamp="2026-09-29T12:00:00+08:00",
            backend_identity="SETUP01_D1_VPS_SSH_DURABLE_STORAGE",
            backend_version="VPS_D1_DURABLE_BACKEND_V1",
            storage_identity_sha256="a" * 64,
            code_sha="b" * 40,
            source_contract=source_contract_descriptor(),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        )
        store = _Store(activation)
        calls, collector = self._collector(store)
        receipt = reconcile_market(
            "CN", now=datetime(2026, 9, 29, 9, 30, tzinfo=timezone.utc),
            store=store, calendar_provider=self.provider, collector=collector,
        )
        self.assertEqual(receipt["status"], "NOOP_BEFORE_ACTIVATION")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

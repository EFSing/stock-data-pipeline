from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zoneinfo import ZoneInfo

from core import Quote
from research.setup01_d1_prospective import (
    D1IntegrityError,
    FilesystemD1Store,
    PROTOCOL_VERSION,
    build_session_snapshot,
    prospective_window,
    render_research_report,
    session_event_summary,
    validate_session_snapshot,
)
from research.setup01_dual_path_observer import BreakoutAnchor, observe_dual_path
from scripts.run_setup01_d1_collector import collect


ROOT = Path(__file__).resolve().parents[1]


def _snapshot(*, status="COMPLETE", backfill=False, observations=None):
    return build_session_snapshot(
        market="US", session_date=date(2026, 9, 25),
        acquired_at="2026-09-26T05:15:00+08:00", capture_status=status,
        diagnostic_backfill=backfill,
        source_identity={"provider": "fixture", "source_date": "2026-09-25", "obtained_at": "2026-09-26T05:15:00+08:00"},
        universe_snapshot={"source": "fixture", "members": [{"symbol": "TEST", "market": "US",
                           "membership_status": "INCLUDED", "source_date": "2026-09-25",
                           "sector": "Technology", "tradable": True}]},
        raw_source_snapshot={"provider": "fixture", "payload_hash": "raw-fixture"},
        normalized_prefix_snapshot={"adjustment": "QFQ", "symbols": {"TEST": {"tail": "2026-09-25", "bars": 60}}},
        decision_snapshot={"formal_entry_allowed": [], "research_only": True},
        research_observation_report={"observations": observations or []},
    )


def _quotes(market="US", *, retest=False, cn_stop=False):
    start = date(2026, 8, 20)
    rows = []
    for i in range(25):
        close = 96.0 + i * .1
        rows.append(Quote("TEST", "Test", market, start + timedelta(days=i), "fixture",
                          close - .2, close + .6, close - .8, close,
                          close - .1, None, 1000 + i, None, None,
                          "CNY" if market == "CN" else "USD"))
    previous = rows[-1]
    b_date = start + timedelta(days=25)
    if retest:
        b = Quote("TEST", "Test", market, b_date, "fixture", 100.8, 102.0, 99.8, 101.2,
                  previous.close, None, 2000, None, None, "USD")
        e = Quote("TEST", "Test", market, b_date + timedelta(days=1), "fixture", 99.5, 103.0, 99.0, 102.8,
                  b.close, None, 2200, None, None, "USD")
    else:
        b = Quote("TEST", "Test", market, b_date, "fixture", 99.0, 104.0, 98.0, 103.5,
                  previous.close, None, 2000, None, None, "CNY" if market == "CN" else "USD")
        e_low = 90.0 if cn_stop else 102.0
        e = Quote("TEST", "Test", market, b_date + timedelta(days=1), "fixture", 103.0, 105.0, e_low, 104.0,
                  b.close, None, 2200, None, None, "CNY" if market == "CN" else "USD")
    rows.extend((b, e))
    if cn_stop:
        rows.append(Quote("TEST", "Test", market, b_date + timedelta(days=2), "fixture",
                          92.0, 94.0, 91.0, 93.0, e.close, None, 2500, None, None, "CNY"))
    return rows, b_date


class D1PersistenceTests(unittest.TestCase):
    def test_snapshot_hashes_components_and_separates_research_from_formal(self):
        snapshot = _snapshot(observations=[{
            "symbol": "TEST", "event_type": "PATH_A_SIGNAL", "research_only_candidate": True,
            "formal_entry_allowed": False, "levels": {"entry_trigger": 10, "entry_ceiling": 11,
            "stop": 9, "T1": 12}, "diagnostics": {"five_pct_pass": True, "two_r_pass": True},
            "model_outcome": "RESEARCH_PLAN_CREATED",
        }])
        validate_session_snapshot(snapshot)
        summary = session_event_summary(snapshot)
        self.assertEqual((summary["research_candidates"], summary["formal_entry_allowed"]), (1, 0))
        rendered = render_research_report(snapshot)
        self.assertIn("只读研究观察", rendered)
        self.assertIn("不写策略池、Paper 或 broker", rendered)
        self.assertIn(snapshot["event_sha256"], rendered)

    def test_late_and_backfilled_data_never_become_prospective(self):
        self.assertFalse(_snapshot(status="LATE_SOURCE")["prospective_eligible"])
        self.assertFalse(_snapshot(backfill=True)["prospective_eligible"])
        self.assertTrue(_snapshot()["prospective_eligible"])

    def test_private_holdings_or_account_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "private holdings/account"):
            build_session_snapshot(
                market="US", session_date=date(2026, 9, 25),
                acquired_at="2026-09-26T05:15:00+08:00", capture_status="COMPLETE",
                source_identity={"provider": "fixture", "source_date": "2026-09-25",
                                 "obtained_at": "2026-09-26T05:15:00+08:00"},
                universe_snapshot={"members": []}, raw_source_snapshot={"holdings": []},
                normalized_prefix_snapshot={"adjustment": "QFQ"},
                decision_snapshot={}, research_observation_report={"observations": []})

    def test_commit_is_idempotent_and_conflicting_same_session_fails_closed(self):
        with TemporaryDirectory() as directory:
            store = FilesystemD1Store(directory)
            first = store.commit(_snapshot())
            second = store.commit(_snapshot())
            self.assertEqual((first.status, second.status), ("COMMITTED", "IDEMPOTENT_REPLAY"))
            changed = _snapshot(observations=[{"event_type": "DATA_MISSING"}])
            with self.assertRaises(D1IntegrityError):
                store.commit(changed)

    def test_verify_detects_missing_session_and_hash_tamper(self):
        with TemporaryDirectory() as directory:
            store = FilesystemD1Store(directory)
            committed = store.commit(_snapshot())
            missing = store.verify({"US": [date(2026, 9, 25), date(2026, 9, 28)]})
            self.assertEqual(missing["missing_sessions"], ["US:2026-09-28"])
            object_path = next((Path(directory) / "objects").rglob("*.json"))
            object_path.write_text("{}\n", encoding="utf-8")
            checked = store.verify()
            self.assertEqual(checked["status"], "FAILED")
            self.assertTrue(checked["errors"])
            self.assertTrue(committed.commit_path.exists())

    def test_recovery_to_clean_directory_rechecks_all_hashes(self):
        with TemporaryDirectory() as source, TemporaryDirectory() as parent:
            store = FilesystemD1Store(source)
            store.commit(_snapshot())
            target = Path(parent) / "recovered"
            result = store.recover_to(target)
            self.assertEqual(result["status"], "VERIFIED")
            self.assertEqual(FilesystemD1Store(target).load("US", date(2026, 9, 25))["event_id"],
                             "D1|US|2026-09-25|SESSION_SNAPSHOT")

    def test_cli_collector_input_contract_writes_independent_report(self):
        value = {
            "market": "US", "session_date": "2026-09-25",
            "acquired_at": "2026-09-26T05:15:00+08:00", "capture_status": "COMPLETE",
            "source_identity": {"provider": "fixture", "source_date": "2026-09-25",
                                "obtained_at": "2026-09-26T05:15:00+08:00"},
            "universe_snapshot": {"members": [{"symbol": "TEST", "market": "US",
                "membership_status": "INCLUDED", "source_date": "2026-09-25",
                "sector": "Technology", "tradable": True}]},
            "raw_source_snapshot": {"raw": "fixture"},
            "normalized_prefix_snapshot": {"adjustment": "QFQ"},
            "decision_snapshot": {"formal_entry_allowed": []},
            "research_observation_report": {"observations": []},
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, report_path = root / "input.json", root / "research.md"
            input_path.write_text(json.dumps(value), encoding="utf-8")
            result = collect(input_path, root / "store", report_path)
            self.assertEqual(result["status"], "COMMITTED")
            self.assertTrue(report_path.is_file())
            self.assertNotIn("ENTRY_ALLOWED", result)

    def test_protocol_freeze_has_exact_hash_and_preserves_d2(self):
        protocol_path = ROOT / "research/protocols/setup01_post_breakout_d1_prospective_v1.json"
        freeze = json.loads((ROOT / "research/protocols/setup01_post_breakout_d1_prospective_freeze_v1.json").read_text(encoding="utf-8"))
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        import hashlib
        self.assertEqual(protocol["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(hashlib.sha256(protocol_path.read_bytes()).hexdigest(), freeze["protocol_sha256"])
        self.assertTrue(freeze["d2_history_preserved"])
        self.assertFalse(freeze["formal_collection_started"])

    def test_cn_us_windows_are_independent_fixed_calendar_years(self):
        activation = datetime(2026, 9, 24, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        cn = prospective_window("CN", activation)
        us = prospective_window("US", activation)
        self.assertEqual(cn["start_session_date"], "2026-09-28")
        self.assertEqual(us["start_session_date"], "2026-09-24")
        self.assertEqual(cn["end_boundary_local_date"], "2027-09-28")
        self.assertEqual(us["end_boundary_local_date"], "2027-09-24")
        self.assertEqual(cn["calendar_horizon_status"], "PENDING_FUTURE_EXCHANGE_CALENDAR")
        self.assertEqual(us["last_eligible_session_date"], "2027-09-23")
        self.assertEqual(us["final_cutoff_bjt"], "2027-09-24T04:00:00+08:00")


class DualPathObserverTests(unittest.TestCase):
    def test_breakout_day_is_path_a_and_executes_no_earlier_than_next_session(self):
        rows, b_date = _quotes()
        events = observe_dual_path(rows, BreakoutAnchor("confirmed-1", b_date, 80, 100, 90))
        a = next(item for item in events if item["event_type"] == "PATH_A_SIGNAL")
        execution = next(item for item in events if item["event_type"] == "MODEL_EXECUTION")
        self.assertEqual(a["session_date"], b_date.isoformat())
        self.assertEqual(execution["session_date"], (b_date + timedelta(days=1)).isoformat())
        self.assertFalse(a["formal_entry_allowed"])
        self.assertIn("five_pct_pass", a["diagnostics"])

    def test_path_b_requires_later_actual_retest(self):
        rows, b_date = _quotes(retest=True)
        events = observe_dual_path(rows, BreakoutAnchor("confirmed-2", b_date, 80, 100, 90))
        types = [item["event_type"] for item in events]
        self.assertNotIn("PATH_A_SIGNAL", types)
        self.assertIn("PATH_B_TOUCH", types)
        signal = next(item for item in events if item["event_type"] == "PATH_B_SIGNAL")
        self.assertEqual(signal["session_date"], (b_date + timedelta(days=1)).isoformat())

    def test_cn_entry_day_stop_is_deferred_to_t_plus_one(self):
        rows, b_date = _quotes("CN", cn_stop=True)
        events = observe_dual_path(rows, BreakoutAnchor("confirmed-cn", b_date, 80, 100, 90))
        pending = next(item for item in events if item["event_type"] == "ENTRY_DAY_STOP_BREACH_PENDING")
        exit_event = next(item for item in events if item["event_type"] == "RESEARCH_EXIT")
        self.assertEqual(pending["session_date"], (b_date + timedelta(days=1)).isoformat())
        self.assertEqual(exit_event["session_date"], (b_date + timedelta(days=2)).isoformat())
        self.assertEqual(exit_event["model_outcome"], "CN_T_PLUS_ONE_PENDING_STOP")

    def test_us_buy_stop_stop_target_same_day_is_flagged_and_stop_first(self):
        rows, b_date = _quotes("US")
        rows[-1] = replace(rows[-1], high=120.0, low=90.0, close=110.0)
        events = observe_dual_path(rows, BreakoutAnchor("confirmed-us", b_date, 80, 100, 90))
        execution = next(item for item in events if item["event_type"] == "MODEL_EXECUTION")
        exit_event = next(item for item in events if item["event_type"] == "RESEARCH_EXIT")
        self.assertEqual(execution["ambiguity"], "BUY_STOP_STOP_TARGET_ORDER_UNKNOWN_STOP_FIRST")
        self.assertEqual(exit_event["model_outcome"], "STOP_FIRST")


if __name__ == "__main__":
    unittest.main()

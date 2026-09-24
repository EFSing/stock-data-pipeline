from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.setup01_d1_drive_store import DRIVE_FOLDER_MIME, GoogleDriveD1Store, JSON_MIME
from research.setup01_d1_prospective import D1IntegrityError, build_session_snapshot
from scripts.run_setup01_d1_collector import daily_report_input


class MemoryDriveApi:
    def __init__(self):
        self.counter = 0
        self.items = {
            "root": {
                "id": "root", "name": "D1", "mimeType": DRIVE_FOLDER_MIME,
                "trashed": False, "capabilities": {"canAddChildren": True}, "parents": [],
            }
        }
        self.payloads = {}

    def _id(self):
        self.counter += 1
        return f"id-{self.counter}"

    def metadata(self, file_id):
        return dict(self.items[file_id])

    def list_children(self, parent_id, *, name=None):
        return [dict(item) for item in self.items.values()
                if parent_id in item.get("parents", ()) and (name is None or item["name"] == name)]

    def create_folder(self, parent_id, name):
        item = {"id": self._id(), "name": name, "mimeType": DRIVE_FOLDER_MIME,
                "trashed": False, "capabilities": {"canAddChildren": True}, "parents": [parent_id]}
        self.items[item["id"]] = item
        return dict(item)

    def create_file(self, parent_id, name, payload, *, app_properties):
        item = {"id": self._id(), "name": name, "mimeType": JSON_MIME,
                "parents": [parent_id], "appProperties": dict(app_properties), "size": len(payload)}
        self.items[item["id"]] = item
        self.payloads[item["id"]] = bytes(payload)
        return dict(item)

    def download(self, file_id):
        return self.payloads[file_id]


def _snapshot():
    return build_session_snapshot(
        market="CN", session_date=date(2026, 9, 25),
        acquired_at="2026-09-25T18:00:00+08:00", capture_status="COMPLETE",
        source_identity={"provider": "fixture", "source_date": "2026-09-25",
                         "obtained_at": "2026-09-25T18:00:00+08:00"},
        universe_snapshot={"members": []}, raw_source_snapshot={"fixture": True},
        normalized_prefix_snapshot={"adjustment": "QFQ"}, decision_snapshot={},
        research_observation_report={"observations": []},
    )


class GoogleDriveD1StoreTests(unittest.TestCase):
    def test_access_probe_commit_readback_idempotency_and_clean_recovery(self):
        api = MemoryDriveApi()
        store = GoogleDriveD1Store(api, "root")
        access = store.verify_access(write_probe=True)
        self.assertEqual(access["probe_status"], "CREATED_AND_VERIFIED")
        first, second = store.commit(_snapshot()), store.commit(_snapshot())
        self.assertEqual((first.status, second.status), ("COMMITTED", "IDEMPOTENT_REPLAY"))
        self.assertEqual(store.load("CN", date(2026, 9, 25))["event_id"],
                         "D1|CN|2026-09-25|SESSION_SNAPSHOT")
        self.assertEqual(store.verify()["status"], "VERIFIED")
        with TemporaryDirectory() as parent:
            target = Path(parent) / "new-device"
            self.assertEqual(store.recover_to(target)["status"], "VERIFIED")

    def test_conflicting_same_session_and_readback_tamper_fail_closed(self):
        api = MemoryDriveApi()
        store = GoogleDriveD1Store(api, "root")
        committed = store.commit(_snapshot())
        changed = dict(_snapshot())
        changed["event_sha256"] = "0" * 64
        with self.assertRaises(D1IntegrityError):
            store.commit(changed)
        api.payloads[committed.object_file_id] = b"{}\n"
        with self.assertRaises(D1IntegrityError):
            store.load("CN", date(2026, 9, 25))

    def test_daily_report_adapter_marks_only_complete_natural_session_eligible(self):
        payload = {
            "market": "US", "as_of_date": "2026-09-25", "generated_at": "2026-09-26T05:00:00+08:00",
            "cloud_daily_report": {
                "market": "US", "as_of_date": "2026-09-25", "generated_at": "2026-09-26T05:00:00+08:00",
                "status": "SUCCESS", "data_quality": {"operationally_complete": True},
                "provider_status": {"AAPL": "OK"}, "input_fingerprint": "sha256:test",
                "calendar_gate": "EXACT_COMPLETED_SESSION",
                "session_identity": {"market": "US", "trade_date": "2026-09-25"},
            },
            "prospective_observation": {"observations": [{
                "symbol": "AAPL", "provenance_bucket": "FORMAL_ONLY", "data_status": "DATA_OK",
                "decision": {"action": "REJECTED"},
            }]},
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "daily-report.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            value = daily_report_input(path)
            self.assertEqual(value["capture_status"], "COMPLETE")
            self.assertFalse(value["diagnostic_backfill"])
            self.assertEqual(value["universe_snapshot"]["members"][0]["symbol"], "AAPL")
            self.assertTrue(daily_report_input(path, diagnostic_backfill=True)["diagnostic_backfill"])


if __name__ == "__main__":
    unittest.main()

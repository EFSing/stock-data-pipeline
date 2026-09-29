from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.setup01_d1_activation import validate_activation_record
from research.setup01_d1_gcs_store import (
    GCS_BACKEND_IDENTITY,
    GCS_BACKEND_VERSION,
    GcsObject,
    GcsNotFound,
    GcsPreconditionFailed,
    GoogleCloudStorageD1Store,
)
from research.setup01_d1_prospective import D1IntegrityError, build_session_snapshot
from research.setup01_d1_source_contract import D1_SOURCE_CONTRACT_VERSION, source_contract_descriptor


class MemoryGcsApi:
    def __init__(self):
        self.bucket = {
            "name": "d1-research-test",
            "location": "ASIA-EAST1",
            "storageClass": "STANDARD",
            "iamConfiguration": {
                "uniformBucketLevelAccess": {"enabled": True},
                "publicAccessPrevention": "enforced",
            },
            "versioning": {"enabled": False},
        }
        self.objects: dict[str, GcsObject] = {}
        self.counter = 0

    def bucket_metadata(self, bucket):
        if bucket != self.bucket["name"]:
            raise AssertionError(bucket)
        return dict(self.bucket)

    def create_object(self, bucket, name, payload, *, metadata):
        if name in self.objects:
            raise GcsPreconditionFailed(412, "already exists")
        self.counter += 1
        value = GcsObject(name, str(self.counter), dict(metadata), bytes(payload))
        self.objects[name] = value
        return value

    def get_object(self, bucket, name):
        if name not in self.objects:
            raise GcsNotFound(404, "missing")
        return self.objects[name]

    def list_objects(self, bucket, *, prefix):
        return [
            {"name": value.name, "generation": value.generation, "metadata": dict(value.metadata)}
            for value in self.objects.values()
            if value.name.startswith(prefix)
        ]


def _snapshot(
    *,
    session_date: date,
    activation_hash: str,
    market: str = "CN",
    acquired_at: str = "2026-09-02T18:00:00+08:00",
):
    normalized_market = str(market).upper()
    calendar = "XSHG" if normalized_market == "CN" else "XNYS"
    source = {
        "provider": "fixture",
        "source_date": session_date.isoformat(),
        "obtained_at": acquired_at,
        "session_identity": {
            "market": normalized_market,
            "trade_date": session_date.isoformat(),
            "identity": f"exchange_calendars:{calendar}:{session_date.isoformat()}",
            "exact_exchange_calendar": True,
        },
        "source_contract_version": D1_SOURCE_CONTRACT_VERSION,
        "activation_record_sha256": activation_hash,
    }
    verified = {
        "contract_version": D1_SOURCE_CONTRACT_VERSION,
        "status": "VERIFIED",
    }
    report = {
        **verified,
        "observer_version": "SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        "observations": [],
        "report_markdown": "# D1 只读研究观察\n",
    }
    return build_session_snapshot(
        market=normalized_market,
        session_date=session_date,
        acquired_at=acquired_at,
        capture_status="COMPLETE",
        source_identity=source,
        universe_snapshot={"members": []},
        raw_source_snapshot=verified,
        normalized_prefix_snapshot={"adjustment": "前复权", **verified},
        decision_snapshot=verified,
        research_observation_report=report,
    )


class GoogleCloudStorageD1StoreTests(unittest.TestCase):
    def setUp(self):
        os.environ["D1_GCS_BACKEND_APPROVED_FOR_FORMAL_D1"] = "true"
        self.addCleanup(os.environ.pop, "D1_GCS_BACKEND_APPROVED_FOR_FORMAL_D1", None)
        self.api = MemoryGcsApi()
        self.store = GoogleCloudStorageD1Store(
            self.api, "d1-research-test", project="fixture-project"
        )

    def test_bucket_policy_and_synthetic_validation_are_verified(self):
        result = self.store.validate_durable_storage()
        self.assertEqual(result["backend_identity"], GCS_BACKEND_IDENTITY)
        self.assertEqual(result["backend_version"], GCS_BACKEND_VERSION)
        self.assertTrue(result["different_content_fail_closed"])
        self.assertEqual(result["session_counts"], {"CN": 0, "US": 0})
        replay = self.store.validate_durable_storage()
        self.assertEqual(replay["create_status"], "IDEMPOTENT_REPLAY")

    def test_activation_formal_commit_readback_generation_and_recovery(self):
        record = self.store.create_activation_record(
            market="CN",
            activation_timestamp="2026-09-01T08:00:00+08:00",
            code_sha="a" * 40,
            source_contract=source_contract_descriptor(),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        )
        validate_activation_record(
            record,
            expected_backend_identity=GCS_BACKEND_IDENTITY,
            expected_backend_version=GCS_BACKEND_VERSION,
            expected_storage_identity_sha256=self.store.bucket_identity_sha256,
        )
        snapshot = _snapshot(
            session_date=date(2026, 9, 2),
            activation_hash=record["record_sha256"],
        )
        first = self.store.commit(snapshot)
        replay = self.store.commit(snapshot)
        self.assertEqual((first.status, replay.status), ("COMMITTED", "IDEMPOTENT_REPLAY"))
        loaded = self.store.load("CN", date(2026, 9, 2))
        self.assertEqual(loaded["event_sha256"], snapshot["event_sha256"])
        self.assertEqual(self.store.verify()["session_counts"], {"CN": 1, "US": 0})
        with TemporaryDirectory() as directory:
            target = Path(directory) / "recovered"
            recovered = self.store.recover_to(target)
            self.assertEqual(recovered["status"], "VERIFIED")
            self.assertEqual(recovered["session_counts"], {"CN": 1, "US": 0})

    def test_activation_is_required_and_markets_are_independent(self):
        snapshot = _snapshot(
            market="CN", session_date=date(2026, 9, 2), activation_hash="0" * 64
        )
        with self.assertRaisesRegex(D1IntegrityError, "activation record"):
            self.store.commit(snapshot)

        cn_record = self.store.create_activation_record(
            market="CN",
            activation_timestamp="2026-09-01T08:00:00+08:00",
            code_sha="d" * 40,
            source_contract=source_contract_descriptor(),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        )
        us_record = self.store.create_activation_record(
            market="US",
            activation_timestamp="2026-09-01T08:00:00+08:00",
            code_sha="e" * 40,
            source_contract=source_contract_descriptor(),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        )
        self.store.commit(_snapshot(
            market="CN", session_date=date(2026, 9, 2),
            activation_hash=cn_record["record_sha256"],
        ))
        self.store.commit(_snapshot(
            market="US", session_date=date(2026, 9, 2),
            activation_hash=us_record["record_sha256"],
        ))
        self.assertEqual(self.store.verify()["session_counts"], {"CN": 1, "US": 1})

    def test_pre_activation_session_and_conflicting_pointer_fail_closed(self):
        record = self.store.create_activation_record(
            market="CN",
            activation_timestamp="2026-09-01T08:00:00+08:00",
            code_sha="b" * 40,
            source_contract=source_contract_descriptor(),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        )
        before = _snapshot(session_date=date(2026, 8, 31), activation_hash=record["record_sha256"])
        with self.assertRaisesRegex(D1IntegrityError, "PRE_ACTIVATION"):
            self.store.commit(before)
        snapshot = _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        self.store.commit(snapshot)
        changed = _snapshot(
            session_date=date(2026, 9, 2), activation_hash=record["record_sha256"], acquired_at="2026-09-02T18:01:00+08:00"
        )
        with self.assertRaises(D1IntegrityError):
            self.store.commit(changed)

    def test_generation_and_metadata_mismatch_are_rejected(self):
        record = self.store.create_activation_record(
            market="CN",
            activation_timestamp="2026-09-01T08:00:00+08:00",
            code_sha="c" * 40,
            source_contract=source_contract_descriptor(),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        )
        snapshot = _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        committed = self.store.commit(snapshot)
        value = self.api.objects[committed.object_name]
        self.api.objects[committed.object_name] = GcsObject(
            value.name, str(int(value.generation) + 1), value.metadata, value.payload
        )
        with self.assertRaisesRegex(D1IntegrityError, "generation"):
            self.store.load("CN", date(2026, 9, 2))

        self.api.objects[committed.object_name] = GcsObject(
            value.name, value.generation, {**value.metadata, "d1_sha256": "f" * 64}, value.payload
        )
        with self.assertRaisesRegex(D1IntegrityError, "metadata"):
            self.store.load("CN", date(2026, 9, 2))

    def test_missing_or_corrupt_object_fails_closed(self):
        record = self.store.create_activation_record(
            market="CN",
            activation_timestamp="2026-09-01T08:00:00+08:00",
            code_sha="f" * 40,
            source_contract=source_contract_descriptor(),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
        )
        snapshot = _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        committed = self.store.commit(snapshot)
        del self.api.objects[committed.object_name]
        with self.assertRaisesRegex(D1IntegrityError, "missing"):
            self.store.load("CN", date(2026, 9, 2))

    def test_bucket_policy_rejects_versioning_and_retention(self):
        self.api.bucket["versioning"]["enabled"] = True
        with self.assertRaisesRegex(D1IntegrityError, "versioning"):
            self.store.verify_access()

        self.api.bucket["versioning"]["enabled"] = False
        self.api.bucket["retentionPolicy"] = {"retentionPeriod": "3600"}
        with self.assertRaisesRegex(D1IntegrityError, "RETENTION_POLICY"):
            self.store.verify_access()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from research.setup01_d1_activation import validate_activation_record
from research.setup01_d1_prospective import (
    D1IntegrityError,
    build_session_snapshot,
    content_sha256,
)
from research.setup01_d1_source_contract import (
    D1_SOURCE_CONTRACT_V1,
    D1_SOURCE_CONTRACT_V2,
    D1_SOURCE_CONTRACT_VERSION,
    source_contract_descriptor,
)
from research.setup01_d1_vps_store import (
    VPS_BACKEND_IDENTITY,
    VPS_BACKEND_VERSION,
    VpsCommandError,
    VpsD1Store,
    VpsHop,
    fingerprint_from_public_key,
    hop_from_env,
    known_hosts_fingerprints,
    storage_identity_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "research" / "d1_vps_store_helper.py"


class LocalHelperRunner:
    """Run the repository helper against a local directory.

    This exercises the real remote helper code end to end without a VPS,
    without SSH secrets and without network access.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.calls: list[list[str]] = []

    def __call__(self, command, *, stdin=None, stdout=None):
        argv = [sys.executable, str(HELPER), "--root", str(self.root), *[str(item) for item in command]]
        self.calls.append(argv)
        completed = subprocess.run(
            argv,
            input=stdin,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        out = b"" if stdout is not None else bytes(completed.stdout or b"")
        return int(completed.returncode), out, bytes(completed.stderr or b"")


def _public_key_blob(seed: bytes) -> str:
    return base64.b64encode(seed + b"ssh-ed25519-host-key").decode("ascii")


def _known_hosts_text(host: str, port: int, seed: bytes) -> str:
    token = host if port == 22 else f"[{host}]:{port}"
    return f"{token} ssh-ed25519 {_public_key_blob(seed)} d1-test-host\n"


def _snapshot(
    *,
    session_date: date,
    activation_hash: str,
    market: str = "CN",
    acquired_at: str = "2026-09-02T18:00:00+08:00",
    source_contract_version: str = D1_SOURCE_CONTRACT_VERSION,
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
        "source_contract_version": source_contract_version,
        "activation_record_sha256": activation_hash,
    }
    verified = {
        "contract_version": source_contract_version,
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


class VpsStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = TemporaryDirectory()
        self.root = Path(self._directory.name).resolve()
        self.runner = LocalHelperRunner(self.root)
        self.store = VpsD1Store(self.runner, storage_root=str(self.root))

    def tearDown(self):
        self._directory.cleanup()

    def _store(self, *, root: Path | None = None, **kwargs) -> tuple[VpsD1Store, LocalHelperRunner]:
        target = Path(root or self.root)
        runner = LocalHelperRunner(target)
        return VpsD1Store(runner, storage_root=str(target), **kwargs), runner

    def _activate(
        self,
        market: str = "CN",
        *,
        store: VpsD1Store | None = None,
        code_sha: str = "a" * 40,
        source_contract_version: str = D1_SOURCE_CONTRACT_V1,
    ):
        target = store or self.store
        return target.create_activation_record(
            market=market,
            activation_timestamp="2026-09-01T08:00:00+08:00",
            code_sha=code_sha,
            source_contract=source_contract_descriptor(source_contract_version),
            observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
            source_contract_version=source_contract_version,
        )


class SshHostIdentityTests(unittest.TestCase):
    def _hop(self, *, known_hosts: str, fingerprint: str, port: int = 22) -> tuple[VpsHop, TemporaryDirectory]:
        directory = TemporaryDirectory()
        path = Path(directory.name) / "known_hosts"
        path.write_text(known_hosts, encoding="utf-8")
        hop = VpsHop(
            host="203.0.113.10",
            user="d1store",
            storage_root="/srv/d1-research",
            identity_file=str(Path(directory.name) / "id_ed25519"),
            known_hosts_path=str(path),
            host_key_fingerprint=fingerprint,
            port=port,
        )
        return hop, directory

    def test_known_hosts_entry_is_pinned_and_strict_checking_is_never_disabled(self):
        seed = b"host-key-a"
        fingerprint = fingerprint_from_public_key(_public_key_blob(seed))
        hop, directory = self._hop(known_hosts=_known_hosts_text("203.0.113.10", 22, seed), fingerprint=fingerprint)
        self.addCleanup(directory.cleanup)
        self.assertEqual(hop.verify_known_hosts(), fingerprint)
        argv = hop.ssh_argv(hop.remote_command(["identity"]))
        joined = " ".join(argv)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertNotIn("StrictHostKeyChecking=no", joined)
        self.assertIn(f"UserKnownHostsFile={hop.known_hosts_path}", argv)
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("-i", argv)
        self.assertEqual(argv[-2], "d1store@203.0.113.10")
        self.assertIn("python3 /srv/d1-research/system/d1_vps_store_helper.py", argv[-1])
        self.assertIn("--root /srv/d1-research", argv[-1])

    def test_host_key_is_verified_on_every_connection(self):
        seed = b"host-key-b"
        fingerprint = fingerprint_from_public_key(_public_key_blob(seed))
        hop, directory = self._hop(known_hosts=_known_hosts_text("203.0.113.10", 2222, seed), fingerprint=fingerprint, port=2222)
        self.addCleanup(directory.cleanup)
        self.assertEqual(hop.verify_known_hosts(), fingerprint)

        wrong, wrong_dir = self._hop(known_hosts=_known_hosts_text("203.0.113.10", 22, b"other"), fingerprint=fingerprint)
        self.addCleanup(wrong_dir.cleanup)
        with self.assertRaisesRegex(D1IntegrityError, "FINGERPRINT_MISMATCH"):
            wrong.verify_known_hosts()

        missing, missing_dir = self._hop(known_hosts=_known_hosts_text("198.51.100.4", 22, seed), fingerprint=fingerprint)
        self.addCleanup(missing_dir.cleanup)
        with self.assertRaisesRegex(D1IntegrityError, "KNOWN_HOSTS_ENTRY_MISSING"):
            missing.verify_known_hosts()

    def test_known_hosts_fingerprints_include_revocation_marker_entries(self):
        seed = b"host-key-c"
        text = "@cert-authority " + _known_hosts_text("d1.example", 22, seed)
        self.assertEqual(
            known_hosts_fingerprints(text, "d1.example", 22),
            [fingerprint_from_public_key(_public_key_blob(seed))],
        )

    def test_hop_from_env_requires_every_pinned_secret(self):
        with self.assertRaisesRegex(RuntimeError, "D1_VPS_HOST"):
            hop_from_env({})
        with self.assertRaisesRegex(RuntimeError, "D1_VPS_SSH_PRIVATE_KEY"):
            hop_from_env({
                "D1_VPS_HOST": "203.0.113.10",
                "D1_VPS_KNOWN_HOSTS": _known_hosts_text("203.0.113.10", 22, b"x"),
            })
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        seed = b"host-key-d"
        hop = hop_from_env({
            "D1_VPS_HOST": "203.0.113.10",
            "D1_VPS_KNOWN_HOSTS": _known_hosts_text("203.0.113.10", 22, seed),
            "D1_VPS_HOST_KEY_FINGERPRINT": fingerprint_from_public_key(_public_key_blob(seed)),
            "D1_VPS_SSH_PRIVATE_KEY": "-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n",
            "D1_VPS_STORAGE_ROOT": "/srv/d1-research/",
        })
        self.assertEqual(hop.storage_root, "/srv/d1-research")
        self.assertEqual(hop.user, "d1store")
        self.assertEqual(Path(hop.identity_file).read_text(encoding="utf-8"), "-----BEGIN OPENSSH PRIVATE KEY-----\nfixture\n")
        os.unlink(hop.identity_file)
        os.unlink(hop.known_hosts_path)


class VpsDurableStoreTests(VpsStoreTestCase):
    def test_synthetic_validation_is_verified_and_not_formal_evidence(self):
        result = self.store.validate_durable_storage()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["backend_identity"], VPS_BACKEND_IDENTITY)
        self.assertEqual(result["backend_version"], VPS_BACKEND_VERSION)
        self.assertEqual(result["classification"], "SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE")
        self.assertTrue(result["idempotent_rerun"])
        self.assertTrue(result["different_content_fail_closed"])
        self.assertTrue(result["clean_directory_recovery"])
        self.assertEqual(result["create_status"], "CREATED")
        self.assertEqual(result["replay_status"], "IDEMPOTENT_REPLAY")
        self.assertEqual(result["session_counts"], {"CN": 0, "US": 0})
        self.assertGreater(result["disk"]["total_bytes"], 0)
        self.assertIn(result["disk"]["space_status"], {"D1_STORAGE_OK", "D1_STORAGE_LOW_SPACE"})
        graph = self.store.verify()
        self.assertEqual(graph["session_counts"], {"CN": 0, "US": 0})
        self.assertNotIn(result["object_name"], [item["object_name"] for item in graph["sessions"]])

    def test_activation_commit_readback_and_idempotent_replay(self):
        record = self._activate()
        validate_activation_record(
            record,
            expected_backend_identity=VPS_BACKEND_IDENTITY,
            expected_backend_version=VPS_BACKEND_VERSION,
            expected_storage_identity_sha256=self.store.storage_identity,
        )
        self.assertEqual(record["storage_identity_sha256"], storage_identity_sha256(str(self.root)))
        snapshot = _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        first = self.store.commit(snapshot)
        replay = self.store.commit(snapshot)
        self.assertEqual(first.status, "COMMITTED")
        self.assertEqual(replay.status, "IDEMPOTENT_REPLAY")
        self.assertEqual(first.object_sha256, replay.object_sha256)
        self.assertEqual(first.event_sha256, snapshot["event_sha256"])
        self.assertGreater(first.object_bytes, 0)
        receipt = first.as_receipt()
        for key in (
            "backend_identity",
            "backend_version",
            "object_identity",
            "object_sha256",
            "commit_name",
            "status",
        ):
            self.assertIn(key, receipt)
        self.assertNotIn("D1_VPS_SSH_PRIVATE_KEY", json.dumps(receipt))
        loaded = self.store.load("CN", date(2026, 9, 2))
        self.assertEqual(loaded["event_sha256"], snapshot["event_sha256"])
        self.assertEqual(self.store.verify()["session_counts"], {"CN": 1, "US": 0})

    def test_v1_and_v2_activation_epochs_coexist_and_bind_exact_version(self):
        v1 = self._activate("CN", code_sha="a" * 40)
        v2 = self._activate(
            "CN",
            code_sha="b" * 40,
            source_contract_version=D1_SOURCE_CONTRACT_V2,
        )
        self.assertNotEqual(v1["record_sha256"], v2["record_sha256"])
        self.assertTrue((self.root / "system" / "activation" / "CN.json").exists())
        self.assertTrue(
            (
                self.root
                / "system"
                / "activation_epochs"
                / "CN"
                / f"{D1_SOURCE_CONTRACT_V2}.json"
            ).exists()
        )
        v2_snapshot = _snapshot(
            session_date=date(2026, 9, 2),
            activation_hash=v2["record_sha256"],
            source_contract_version=D1_SOURCE_CONTRACT_V2,
        )
        self.store.commit(v2_snapshot)
        with self.assertRaisesRegex(D1IntegrityError, "hash mismatch"):
            self.store.commit(
                _snapshot(
                    session_date=date(2026, 9, 3),
                    activation_hash=v1["record_sha256"],
                    source_contract_version=D1_SOURCE_CONTRACT_V2,
                )
            )
        graph = self.store.verify()
        self.assertEqual(
            {(item["market"], item["source_contract_version"]) for item in graph["activation_records"]},
            {("CN", D1_SOURCE_CONTRACT_V1), ("CN", D1_SOURCE_CONTRACT_V2)},
        )

    def test_activation_is_required_and_markets_stay_independent(self):
        with self.assertRaisesRegex(D1IntegrityError, "activation record"):
            self.store.commit(
                _snapshot(session_date=date(2026, 9, 2), activation_hash="0" * 64)
            )
        cn = self._activate("CN", code_sha="b" * 40)
        us = self._activate("US", code_sha="c" * 40)
        self.store.commit(_snapshot(session_date=date(2026, 9, 2), activation_hash=cn["record_sha256"]))
        self.store.commit(
            _snapshot(market="US", session_date=date(2026, 9, 2), activation_hash=us["record_sha256"])
        )
        graph = self.store.verify()
        self.assertEqual(graph["session_counts"], {"CN": 1, "US": 1})
        self.assertEqual([item["market"] for item in graph["activation_records"]], ["CN", "US"])
        self.assertTrue(graph["continuation_ready"])
        with self.assertRaisesRegex(D1IntegrityError, "PRE_ACTIVATION"):
            self.store.commit(
                _snapshot(session_date=date(2026, 8, 31), activation_hash=cn["record_sha256"])
            )
        with self.assertRaisesRegex(D1IntegrityError, "activation record hash mismatch"):
            self.store.commit(
                _snapshot(session_date=date(2026, 9, 3), activation_hash=us["record_sha256"])
            )

    def test_foreign_activation_record_is_rejected_as_split_brain(self):
        record = self._activate()
        foreign = dict(record)
        foreign["storage_identity_sha256"] = "f" * 64
        foreign.pop("record_sha256", None)
        foreign["record_sha256"] = content_sha256(foreign)
        path = self.root / "system" / "activation" / "CN.json"
        path.write_bytes(
            (json.dumps(foreign, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        )
        with self.assertRaisesRegex(D1IntegrityError, "storage identity"):
            self.store.load_activation_record(
                "CN", source_contract_version=D1_SOURCE_CONTRACT_V1
            )
        graph = self.store.verify()
        self.assertEqual(graph["status"], "VERIFIED")
        self.assertFalse(graph["continuation_ready"])
        self.store._identity = None
        with self.assertRaisesRegex(D1IntegrityError, "activation record"):
            self.store.commit(
                _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
            )

    def test_pointer_conflict_partial_transfer_and_backfill_fail_closed(self):
        record = self._activate()
        snapshot = _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        self.store.commit(snapshot)
        changed = _snapshot(
            session_date=date(2026, 9, 2),
            activation_hash=record["record_sha256"],
            acquired_at="2026-09-02T18:05:00+08:00",
        )
        with self.assertRaisesRegex(D1IntegrityError, "CONFLICT"):
            self.store.commit(changed)
        self.assertEqual(self.store.verify()["session_counts"], {"CN": 1, "US": 0})

        # A truncated/interrupted upload declares the full-length digest and
        # must leave no partial object or temporary file behind.
        payload = json.dumps({"fixture": "partial"}).encode()
        with self.assertRaises(VpsCommandError) as context:
            self.store._call(
                [
                    "put",
                    "--name", "objects/" + "9" * 64 + ".json",
                    "--sha256", sha256(payload).hexdigest(),
                    "--role", "OBJECT",
                    "--danger-free-bytes", "0",
                ],
                stdin=payload[:5],
            )
        self.assertEqual(context.exception.exit_code, 4)
        self.assertEqual(context.exception.reason, "D1_TRANSFER_HASH_MISMATCH")
        self.assertFalse((self.root / "objects" / ("9" * 64 + ".json")).exists())
        leftovers = list((self.root / "system" / "tmp").glob("*.part"))
        self.assertEqual(leftovers, [])

    def test_corrupted_remote_bytes_and_pointer_tampering_are_detected(self):
        record = self._activate()
        committed = self.store.commit(
            _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        )
        object_path = self.root / committed.object_name
        original = object_path.read_bytes()
        object_path.write_bytes(b"x" * len(original))
        with self.assertRaises(D1IntegrityError):
            self.store.load("CN", date(2026, 9, 2))
        self.assertEqual(self.store.verify(full_objects=True)["status"], "FAILED")
        object_path.write_bytes(original)
        self.assertEqual(self.store.verify(full_objects=True)["status"], "VERIFIED")

        pointer_path = self.root / committed.commit_name
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["event_sha256"] = "f" * 64
        pointer_path.write_text(json.dumps(pointer, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        graph = self.store.verify()
        self.assertEqual(graph["status"], "FAILED")
        self.assertTrue(any("commit hash mismatch" in item for item in graph["errors"]))

    def test_missing_object_duplicate_session_and_orphan_objects_are_reported(self):
        record = self._activate()
        committed = self.store.commit(
            _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        )
        object_path = self.root / committed.object_name
        backup = object_path.read_bytes()
        object_path.unlink()
        graph = self.store.verify()
        self.assertEqual(graph["status"], "FAILED")
        self.assertTrue(any("object is missing" in item for item in graph["errors"]))
        object_path.write_bytes(backup)

        duplicate = self.root / "sessions" / "CN" / "shadow" / "2026-09-02.json"
        duplicate.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.root / committed.commit_name, duplicate)
        graph = self.store.verify()
        self.assertEqual(graph["status"], "FAILED")
        self.assertTrue(any("duplicate session commit" in item for item in graph["errors"]))
        duplicate.unlink()

        self.store.put_bytes(
            "objects/" + "7" * 64 + ".json",
            b"{}\n",
            role="OBJECT",
        )
        graph = self.store.verify()
        self.assertEqual(graph["status"], "VERIFIED")
        self.assertEqual(graph["unreferenced_objects"], ["objects/" + "7" * 64 + ".json"])
        self.assertEqual(graph["referenced_object_count"], 1)

    def test_low_disk_fail_closed_blocks_formal_writes(self):
        record = self._activate()
        blocked, _ = self._store(danger_free_bytes=10**15)
        with self.assertRaises(VpsCommandError) as context:
            blocked.commit(
                _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
            )
        self.assertEqual(context.exception.reason, "D1_STORAGE_LOW_SPACE_FAIL_CLOSED")
        self.assertEqual(self.store.verify()["session_counts"], {"CN": 0, "US": 0})
        status = blocked.status()
        self.assertTrue(status["low_space_danger"])
        self.assertEqual(status["space_status"], "D1_STORAGE_LOW_SPACE_FAIL_CLOSED")
        self.assertLessEqual(status["free_bytes"], status["total_bytes"])

    def test_private_fields_are_rejected_before_any_remote_write(self):
        record = self._activate()
        snapshot = _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        snapshot["components"]["decision_snapshot"]["payload"]["holdings"] = [{"symbol": "512400"}]
        before = len(self.runner.calls)
        with self.assertRaisesRegex(D1IntegrityError, "private holdings/account data"):
            self.store.commit(snapshot)
        self.assertEqual(len(self.runner.calls), before)

    def test_export_recover_manifest_and_migration_round_trip(self):
        cn = self._activate("CN", code_sha="d" * 40)
        us = self._activate("US", code_sha="e" * 40)
        self.store.commit(_snapshot(session_date=date(2026, 9, 2), activation_hash=cn["record_sha256"]))
        self.store.commit(
            _snapshot(market="US", session_date=date(2026, 9, 2), activation_hash=us["record_sha256"])
        )
        published = self.store.publish_manifest()
        self.assertEqual(published["receipt"]["status"], "CREATED")
        self.assertEqual(published["manifest"]["evidence_role"], "DERIVED_INDEX_NOT_FORMAL_SESSION_EVIDENCE")
        self.assertEqual(published["manifest"]["session_counts"], {"CN": 1, "US": 1})

        # The export lives outside the store root: a real migration starts
        # from a verified copy that does not depend on the old VPS.
        side_directory = TemporaryDirectory()
        self.addCleanup(side_directory.cleanup)
        export_root = Path(side_directory.name) / "export"
        exported = self.store.export_to(export_root)
        self.assertEqual(exported["status"], "VERIFIED")
        self.assertEqual(exported["session_counts"], {"CN": 1, "US": 1})
        manifest_path = Path(exported["manifest_path"])
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["session_counts"], {"CN": 1, "US": 1})
        self.assertEqual(len(manifest["sessions"]), 2)
        self.assertTrue((export_root / "system" / "activation" / "CN.json").is_file())
        with self.assertRaisesRegex(D1IntegrityError, "must be empty"):
            self.store.export_to(export_root)

        recover_root = Path(side_directory.name) / "recover"
        recovered = self.store.recover_to(recover_root)
        self.assertEqual(recovered["session_counts"], {"CN": 1, "US": 1})

        # Simulate a new VPS: the frozen storage root is recreated empty and
        # the verified local export is imported into it.
        for child in list(self.root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        fresh, _ = self._store()
        migrated = fresh.migrate_from(export_root)
        self.assertEqual(migrated["status"], "MIGRATED_AND_VERIFIED")
        self.assertEqual(migrated["imported_sessions"], 2)
        graph = fresh.verify(full_objects=True)
        self.assertEqual(graph["status"], "VERIFIED")
        self.assertEqual(graph["session_counts"], {"CN": 1, "US": 1})
        self.assertTrue(graph["continuation_ready"])
        self.assertEqual(
            [(item["market"], item["session_date"]) for item in graph["sessions"]],
            [("CN", "2026-09-02"), ("US", "2026-09-02")],
        )
        with self.assertRaisesRegex(D1IntegrityError, "empty formal D1 store"):
            fresh.migrate_from(export_root)

    def test_migration_rejects_a_different_frozen_storage_root(self):
        record = self._activate()
        self.store.commit(
            _snapshot(session_date=date(2026, 9, 2), activation_hash=record["record_sha256"])
        )
        side_directory = TemporaryDirectory()
        self.addCleanup(side_directory.cleanup)
        export_root = Path(side_directory.name) / "export-other"
        self.store.export_to(export_root)
        other_root = Path(side_directory.name) / "other-root"
        other_root.mkdir(parents=True)
        other, _ = self._store(root=other_root)
        with self.assertRaisesRegex(D1IntegrityError, "STORAGE_IDENTITY_MISMATCH"):
            other.migrate_from(export_root)
        with self.assertRaisesRegex(D1IntegrityError, "missing or incomplete"):
            other.migrate_from(Path(side_directory.name) / "absent")


class GcsBackendApprovalTests(unittest.TestCase):
    def test_retained_gcs_backend_cannot_write_formal_d1_evidence(self):
        from research.setup01_d1_gcs_store import GoogleCloudStorageD1Store

        os.environ.pop("D1_GCS_BACKEND_APPROVED_FOR_FORMAL_D1", None)
        store = GoogleCloudStorageD1Store(object(), "retained-gcs-adapter")
        with self.assertRaisesRegex(D1IntegrityError, "D1_BACKEND_NOT_APPROVED"):
            store.commit({})
        with self.assertRaisesRegex(D1IntegrityError, "D1_BACKEND_NOT_APPROVED"):
            store.create_activation_record(
                market="CN",
                activation_timestamp="2026-09-01T08:00:00+08:00",
                code_sha="a" * 40,
                source_contract=source_contract_descriptor(),
                observer_version="SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1",
                source_contract_version="SETUP01_D1_SOURCE_OBSERVER_CONTRACT_V1",
            )
        os.environ["D1_GCS_BACKEND_APPROVED_FOR_FORMAL_D1"] = "true"
        try:
            with self.assertRaisesRegex(D1IntegrityError, "snapshot schema mismatch"):
                store.commit({})
        finally:
            os.environ.pop("D1_GCS_BACKEND_APPROVED_FOR_FORMAL_D1", None)


if __name__ == "__main__":
    unittest.main()

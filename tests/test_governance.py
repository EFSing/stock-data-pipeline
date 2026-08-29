import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handoff = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
        cls.registry = json.loads(
            (ROOT / "docs" / "FROZEN_ARTIFACT_REGISTRY.json").read_text(encoding="utf-8")
        )
        cls.entry = cls.registry["artifacts"][0]

    def test_handoff_contains_required_sections_in_order(self):
        sections = [
            "## 1. Current Objective",
            "## 2. Current Repository State",
            "## 3. Completed Work",
            "## 4. Pending Work",
            "## 5. Key Decisions And Rationale",
            "## 6. Important Files Changed",
            "## 7. Frozen Identities And Invariants",
            "## 8. Known Issues / Blockers",
            "## 9. Lessons / Pitfalls — DO NOT REPEAT",
            "## 10. Next Action",
            "## 11. Handoff Checklist",
            "## 12. Last Verified",
        ]
        positions = [self.handoff.index(section) for section in sections]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("PROJECT_GOVERNANCE_STATE_CONFLICT", self.handoff)
        self.assertIn("HANDOFF_CURRENT_AND_CONSISTENT", self.handoff)

    def test_registry_has_fail_closed_recovery_gates(self):
        self.assertEqual(self.registry["schema_version"], "repository-frozen-artifact-registry-v1")
        self.assertEqual(self.entry["status"], "FROZEN_ARTIFACT_BACKUP_STAGED_CLOUD_UPLOAD_REQUIRED")
        gates = self.entry["recovery_gates"]
        self.assertTrue(gates["LOCAL_PRESENT"])
        self.assertTrue(gates["HASH_VERIFIED"])
        self.assertFalse(gates["PERSISTENT_BACKUP_PRESENT"])
        self.assertFalse(gates["RECOVERY_VERIFIED"])
        self.assertFalse(gates["FULLY_RECOVERABLE"])
        self.assertIsNone(self.entry["persistent_backup"]["location"])

    def test_tracked_provenance_file_hashes_match_registry(self):
        hashes = self.entry["exact_file_hashes"]
        paths = {
            "tracked_dataset_manifest_file_sha256": "research/development_holdout/dataset_manifest.json",
            "tracked_replay_manifest_file_sha256": "research/development_holdout/replay_manifest.json",
            "tracked_universe_manifest_file_sha256": "research/development_holdout/universe_manifest.json",
            "tracked_capsule_file_sha256": "research/development/development_holdout_decision_capsule_v1.json",
        }
        for registry_key, relative_path in paths.items():
            digest = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
            self.assertEqual(hashes[registry_key], f"sha256:{digest}", relative_path)

    def test_governance_entry_does_not_contain_credentials(self):
        serialized = json.dumps(self.registry, ensure_ascii=False).lower()
        for forbidden in ("google_service_account_json", "api_key", "token", "private_key"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()

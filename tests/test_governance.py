import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cls.handoff = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
        cls.current_status = (ROOT / "docs" / "CURRENT_STATUS.md").read_text(encoding="utf-8")
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

    def test_project_strategy_identity_is_explicit(self):
        for text in (self.agents, self.handoff, self.current_status):
            self.assertIn("docs/TRADING_SYSTEM_SPEC.md", text)
            self.assertIn("SETUP_01", text)
            self.assertIn("SETUP_02", text)
            self.assertIn("SETUP_03", text)
            self.assertIn("SETUP_04", text)
        self.assertIn("不是单一 Platform Breakout", self.agents)
        self.assertIn("SETUP_03` 当前只是正在研究的一个子策略", self.handoff)
        self.assertIn("Wave Scenario", self.handoff)
        self.assertIn("Weekly State", self.handoff)

    def test_atr_boundary_closeout_state_is_recorded(self):
        expected_protocol_sha = "sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4"
        expected_universe_sha = "sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b"
        self.assertIn(expected_protocol_sha, self.handoff)
        self.assertIn(expected_universe_sha, self.handoff)
        self.assertIn("ATR_BOUNDARY_PROTOCOL_FROZEN_NOT_EXECUTED", self.current_status)
        self.assertIn("40/40 frozen clean symbols", self.current_status)
        self.assertIn("STOP_SETUP_03_STRUCTURAL_DEVELOPMENT", self.current_status)

    def test_atr_normalized_mode_is_outside_production_entrypoints(self):
        setup_source = (ROOT / "trading" / "setup.py").read_text(encoding="utf-8")
        for marker in (
            "RESEARCH_ONLY",
            "NOT_PRODUCTION_AUTHORIZED",
            "FAILED_STRUCTURAL_CANDIDATE_FAMILY",
        ):
            self.assertIn(marker, setup_source)

        production_entrypoints = (
            "main.py",
            "trading/events.py",
            ".github/workflows/asia-close.yml",
            ".github/workflows/us-close.yml",
            ".github/workflows/setup03-replay.yml",
        )
        for relative_path in production_entrypoints:
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("ATR_NORMALIZED", source, relative_path)
            self.assertNotIn("platform_boundary_mode", source, relative_path)

    def test_scheduled_workflows_force_latest_and_full_is_manual_only(self):
        for relative_path, group in (
            (".github/workflows/asia-close.yml", "asia"),
            (".github/workflows/us-close.yml", "us"),
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("workflow_dispatch:", source)
            self.assertIn("default: latest", source)
            self.assertIn("- latest", source)
            self.assertIn("- full", source)
            self.assertIn('if [ "$GITHUB_EVENT_NAME" = "schedule" ]; then', source)
            self.assertIn("RUN_MODE=latest", source)
            self.assertIn(f'python main.py --group {group} --mode "$RUN_MODE"', source)
            self.assertIn("tee run-summary.txt", source)

        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("latest_completed_market_session", main_source)
        self.assertIn('"交易日期": chosen.trade_date', main_source)
        self.assertIn('"抓取时间": fetched_at', main_source)

    def test_registry_records_verified_recovery_gates(self):
        self.assertEqual(self.registry["schema_version"], "repository-frozen-artifact-registry-v1")
        self.assertEqual(self.entry["status"], "FULLY_RECOVERABLE")
        gates = self.entry["recovery_gates"]
        self.assertTrue(gates["LOCAL_PRESENT"])
        self.assertTrue(gates["HASH_VERIFIED"])
        self.assertTrue(gates["PERSISTENT_BACKUP_PRESENT"])
        self.assertTrue(gates["RECOVERY_VERIFIED"])
        self.assertTrue(gates["FULLY_RECOVERABLE"])
        self.assertEqual(
            self.entry["persistent_backup"]["immutable_object_id"],
            "119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS",
        )
        self.assertEqual(
            self.entry["recovery_verification"]["recovered_zip_sha256"],
            "sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599",
        )
        self.assertIn("UNRECOVERABLE", self.entry["notes"])

    def test_tracked_provenance_file_hashes_match_registry(self):
        hashes = self.entry["exact_file_hashes"]
        paths = {
            "tracked_dataset_manifest_file_sha256": "research/development_holdout/dataset_manifest.json",
            "tracked_replay_manifest_file_sha256": "research/development_holdout/replay_manifest.json",
            "tracked_universe_manifest_file_sha256": "research/development_holdout/universe_manifest.json",
            "tracked_capsule_file_sha256": "research/development/development_holdout_decision_capsule_v1.json",
        }
        for registry_key, relative_path in paths.items():
            tracked_bytes = (ROOT / relative_path).read_bytes().replace(b"\r\n", b"\n")
            digest = hashlib.sha256(tracked_bytes).hexdigest()
            self.assertEqual(hashes[registry_key], f"sha256:{digest}", relative_path)

    def test_governance_entry_does_not_contain_credentials(self):
        serialized = json.dumps(self.registry, ensure_ascii=False).lower()
        for forbidden in ("google_service_account_json", "api_key", "token", "private_key"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()

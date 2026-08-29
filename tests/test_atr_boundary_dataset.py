import json
import unittest
from pathlib import Path

from research.atr_boundary_dataset import (
    DATASET_MANIFEST_PATH,
    DATASET_STATUS,
    DATASET_VERSION,
    READY_STATUS,
    manifest_integrity_hash,
)


ROOT = Path(__file__).resolve().parents[1]


class AtrBoundaryDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_clean_holdout_manifest_is_ready_and_hash_pinned(self):
        self.assertEqual(self.manifest["dataset_version"], DATASET_VERSION)
        self.assertEqual(self.manifest["status"], DATASET_STATUS)
        self.assertEqual(self.manifest["coverage_status"], READY_STATUS)
        self.assertEqual(self.manifest["integrity"]["manifest_sha256"], manifest_integrity_hash(self.manifest))
        self.assertEqual(self.manifest["aggregate_symbol_count"], 40)
        self.assertEqual(self.manifest["provider_qc_exceptions"], [])
        self.assertEqual(self.manifest["market_coverage"]["CN"]["valid_accepted"], 20)
        self.assertEqual(self.manifest["market_coverage"]["US"]["valid_accepted"], 20)

    def test_clean_holdout_dataset_controls_are_structure_only(self):
        controls = self.manifest["controls"]
        self.assertTrue(controls["development_only"])
        self.assertFalse(controls["formal_validation"])
        self.assertFalse(controls["final_oos_accessed"])
        self.assertFalse(controls["outcome_metrics_accessed"])
        self.assertFalse(controls["ibkr_used"])
        self.assertFalse(controls["result_driven_provider_or_symbol_switch"])


if __name__ == "__main__":
    unittest.main()

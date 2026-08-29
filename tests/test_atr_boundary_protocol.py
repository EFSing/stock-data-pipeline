import json
import unittest
from pathlib import Path

from research.atr_boundary_protocol import (
    EXPECTED_PROTOCOL_SHA256,
    PROTOCOL_VERSION,
    load_protocol,
    protocol_integrity_hash,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "research" / "protocols" / "setup03_atr_boundary_structural_qualification_protocol.json"


class AtrBoundaryProtocolTests(unittest.TestCase):
    def test_protocol_is_hash_pinned_and_bounded(self):
        protocol = load_protocol()
        self.assertEqual(protocol["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(protocol["integrity"]["protocol_sha256"], EXPECTED_PROTOCOL_SHA256)
        self.assertEqual(protocol["integrity"]["protocol_sha256"], protocol_integrity_hash(protocol))
        self.assertEqual(protocol["boundary_semantics"]["candidate_thresholds_atr"], [1.0, 1.5, 2.0, 2.5])
        self.assertEqual(protocol["boundary_semantics"]["candidate_count"], 4)
        self.assertFalse(protocol["qualification"]["production_selection"])
        self.assertFalse(protocol["qualification"]["outcome_metrics"])

    def test_protocol_file_matches_loader_identity(self):
        raw = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw["status"], "ATR_BOUNDARY_PROTOCOL_FROZEN_NOT_EXECUTED")
        self.assertIn("second_volatility_family", raw["prohibited_actions"])
        self.assertEqual(raw["independent_holdout_selection"]["target_counts"]["total"], 40)


if __name__ == "__main__":
    unittest.main()

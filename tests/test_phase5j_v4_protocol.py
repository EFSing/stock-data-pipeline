import copy
import unittest

from research.phase5j_v4_protocol import (
    EXPECTED_PROTOCOL_SHA256,
    EXPECTED_PROTOCOL_VERSION,
    load_protocol,
    protocol_integrity_hash,
    validate_protocol,
)


class Phase5JV4ProtocolTests(unittest.TestCase):
    def test_protocol_is_hash_pinned_and_unexecuted(self):
        protocol = load_protocol()
        self.assertEqual(protocol["protocol_version"], EXPECTED_PROTOCOL_VERSION)
        self.assertEqual(protocol["integrity"]["protocol_sha256"], EXPECTED_PROTOCOL_SHA256)
        self.assertEqual(protocol["status"], "LIFECYCLE_ATTRIBUTION_PROTOCOL_FROZEN_NOT_EXECUTED")

    def test_protocol_binds_exact_holdout_and_adjacent_pairs(self):
        protocol = load_protocol()
        exact = protocol["evidence_scope"]["exact_causal_replay"]
        self.assertEqual((exact["total_symbol_count"], exact["total_bar_count"]), (40, 86305))
        self.assertEqual(protocol["production_semantics"]["adjacent_pairs"], [[0.03, 0.04], [0.04, 0.05]])
        self.assertTrue(protocol["evidence_scope"]["early_development_v1"]["refetch_prohibited"])

    def test_protocol_freezes_root_and_propagation_taxonomies(self):
        protocol = load_protocol()
        roots = [rule["cause"] for rule in protocol["root_cause_taxonomy"]["ordered_primary_rules"]]
        self.assertEqual(len(roots), len(set(roots)))
        self.assertEqual(roots[-1], "OTHER_UNCLASSIFIED")
        self.assertEqual(protocol["propagation_taxonomy"]["classes"][-1], "MULTI_STAGE_CASCADE")

    def test_protocol_prohibits_outcomes_and_production_changes(self):
        protocol = load_protocol()
        self.assertIn("Final OOS", protocol["prohibited_evidence"])
        self.assertIn("P&L", protocol["prohibited_evidence"])
        self.assertIn("modify production SETUP_03", protocol["prohibited_actions"])
        self.assertIn("modify Phase 5J-v3 frozen qualification", protocol["prohibited_actions"])

    def test_same_version_cannot_accept_synchronized_content_change(self):
        protocol = load_protocol()
        changed = copy.deepcopy(protocol)
        changed["production_semantics"]["adjacent_pairs"] = [[0.03, 0.05]]
        changed["integrity"]["protocol_sha256"] = protocol_integrity_hash(changed)
        with self.assertRaisesRegex(ValueError, "bound to a different hash|adjacent tolerance pairs"):
            validate_protocol(changed)


if __name__ == "__main__":
    unittest.main()

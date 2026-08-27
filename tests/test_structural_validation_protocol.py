import ast
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.parameter_freeze import load_frozen_spec
from research.structural_validation_protocol import (
    DIAGNOSTIC_STRESS_BOUNDARIES,
    PRODUCTION_TOLERANCES,
    PROTOCOL_PATH,
    PROTOCOL_STATUS,
    REQUIRED_FORBIDDEN_METRICS,
    audit_arm_proximity_dependency,
    load_protocol,
    protocol_integrity_hash,
    serialize_protocol,
)


EXPECTED_PROTOCOL_VERSION = (
    "SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v1"
)


class StructuralValidationProtocolTests(unittest.TestCase):
    def test_protocol_is_versioned_complete_and_not_executed(self):
        protocol = load_protocol()
        self.assertEqual(protocol["protocol_version"], EXPECTED_PROTOCOL_VERSION)
        self.assertEqual(protocol["phase5j_status"], PROTOCOL_STATUS)
        self.assertEqual(tuple(protocol["production_tolerance_policy"]["allowed_candidate_values_pct"]), PRODUCTION_TOLERANCES)
        self.assertEqual(tuple(protocol["production_tolerance_policy"]["diagnostic_stress_boundaries_pct"]), DIAGNOSTIC_STRESS_BOUNDARIES)
        self.assertFalse(protocol["production_tolerance_policy"]["stress_boundaries_are_production_candidates"])
        self.assertTrue(REQUIRED_FORBIDDEN_METRICS.issubset(protocol["forbidden_metrics"]))
        self.assertEqual(
            protocol["parent_phase5i"]["freeze_version"],
            load_frozen_spec()["freeze_version"],
        )
        self.assertEqual(
            protocol["parent_phase5i"]["integrity"]["critical_values_sha256"],
            load_frozen_spec()["integrity"]["critical_values_sha256"],
        )
        self.assertFalse(protocol["scope"]["validation_executed"])
        self.assertFalse(protocol["scope"]["final_oos_accessed"])
        self.assertFalse(protocol["scope"]["formal_parameter_selected"])

    def test_protocol_contains_exact_future_dataset_and_threshold_contract(self):
        protocol = load_protocol()
        dataset = protocol["development_validation_dataset"]
        self.assertEqual(tuple(dataset["markets"]), ("CN", "HK", "US", "JP", "SE"))
        self.assertEqual(dataset["coverage_requirements"]["per_market_symbol_count_minimum"], 8)
        self.assertEqual(dataset["coverage_requirements"]["total_symbol_count_minimum"], 40)
        self.assertEqual(dataset["coverage_requirements"]["per_market_valid_daily_k_bars_target_minimum"], 6000)
        self.assertEqual(dataset["coverage_requirements"]["failure_status"], "INSUFFICIENT_COVERAGE")
        self.assertTrue(dataset["symbol_selection_rules"]["selection_must_precede_setup03_output"])
        self.assertTrue(dataset["symbol_manifest"]["must_be_frozen_before_phase5k_acquisition"])
        self.assertTrue(dataset["symbol_manifest"]["must_be_hashed_before_phase5k_acquisition"])

        thresholds = {row["id"]: row for row in protocol["structural_validation_thresholds"]}
        self.assertEqual(set(thresholds), {
            "minimum_confirmed_events_per_market_candidate",
            "adjacent_confirmed_jaccard",
            "adjacent_confirmed_retention",
            "matched_confirmed_event_date_drift_median",
            "matched_confirmed_event_date_drift_p90",
            "maximum_market_confirmed_concentration",
            "maximum_symbol_confirmed_concentration",
            "adjacent_confirmed_rate_relative_increase",
        })
        self.assertEqual((thresholds["minimum_confirmed_events_per_market_candidate"]["operator"], thresholds["minimum_confirmed_events_per_market_candidate"]["threshold"]), (">=", 8))
        self.assertEqual((thresholds["adjacent_confirmed_jaccard"]["operator"], thresholds["adjacent_confirmed_jaccard"]["threshold"]), (">=", 0.60))
        self.assertEqual((thresholds["adjacent_confirmed_retention"]["operator"], thresholds["adjacent_confirmed_retention"]["threshold"]), (">=", 0.80))
        self.assertEqual((thresholds["matched_confirmed_event_date_drift_median"]["operator"], thresholds["matched_confirmed_event_date_drift_median"]["threshold"]), ("<=", 5))
        self.assertEqual((thresholds["matched_confirmed_event_date_drift_p90"]["operator"], thresholds["matched_confirmed_event_date_drift_p90"]["threshold"]), ("<=", 15))
        self.assertEqual((thresholds["maximum_market_confirmed_concentration"]["operator"], thresholds["maximum_market_confirmed_concentration"]["threshold"]), ("<=", 0.35))
        self.assertEqual((thresholds["maximum_symbol_confirmed_concentration"]["operator"], thresholds["maximum_symbol_confirmed_concentration"]["threshold"]), ("<=", 0.25))
        self.assertEqual((thresholds["adjacent_confirmed_rate_relative_increase"]["operator"], thresholds["adjacent_confirmed_rate_relative_increase"]["threshold"]), ("<=", 0.50))

    def test_selection_rule_is_conservative_and_does_not_use_returns(self):
        protocol = load_protocol()
        rule = protocol["parameter_selection_rule"]
        self.assertEqual(rule["type"], "LEXICOGRAPHIC_CONSERVATIVE")
        self.assertEqual(tuple(rule["ordered_candidates_pct"]), PRODUCTION_TOLERANCES)
        self.assertEqual(rule["all_candidates_fail_status"], "VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE")
        self.assertEqual(rule["primarily_insufficient_evidence_status"], "INSUFFICIENT_VALIDATION_EVIDENCE")
        self.assertTrue(rule["selection_is_not_executed_in_phase5j"])
        self.assertFalse(rule["performance_metrics_used"])
        self.assertFalse(rule["market_specific_or_regime_specific_selection"])
        self.assertEqual(protocol["parameter_policy"]["setup_swing_lookback"]["v1_incumbent_design_constant"], 5)
        self.assertEqual(protocol["parameter_policy"]["platform_window"]["v1_incumbent_design_constant"], 40)
        self.assertFalse(protocol["parameter_policy"]["setup_swing_lookback"]["claim_of_optimality"])
        self.assertFalse(protocol["parameter_policy"]["platform_window"]["claim_of_optimality"])
        self.assertEqual(
            protocol["parameter_policy"]["arm_proximity_pct"]["audit_conclusion"],
            "V1_KEEP_CLOSED_ARMED_WARNING_ONLY_NO_CONFIRMED_TERMINAL_CHANGE",
        )

    def test_integrity_covers_every_protocol_field_and_rejects_same_version_drift(self):
        protocol = load_protocol()
        self.assertEqual(protocol["integrity"]["protocol_sha256"], protocol_integrity_hash(protocol))
        mutations = (
            ("production candidates", lambda value: value["production_tolerance_policy"]["allowed_candidate_values_pct"].append(0.06)),
            ("diagnostic boundaries", lambda value: value["production_tolerance_policy"]["diagnostic_stress_boundaries_pct"].append(0.11)),
            ("validation markets", lambda value: value["development_validation_dataset"]["markets"].append("AU")),
            ("dataset selection rules", None),
            ("structural thresholds", lambda value: value["structural_validation_thresholds"][0].__setitem__("threshold", 9)),
            ("parameter-selection rule", lambda value: value["parameter_selection_rule"]["ordered_candidates_pct"].reverse()),
            ("forbidden metrics", lambda value: value["forbidden_metrics"].append("return_sharpe")),
            ("OOS prohibition", lambda value: value["prohibitions"].__setitem__("final_oos_access", False)),
            ("Phase 5I parent identity", lambda value: value["parent_phase5i"].__setitem__("freeze_version", "changed")),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                changed = copy.deepcopy(protocol)
                if label == "dataset selection rules":
                    changed["development_validation_dataset"]["symbol_selection_rules"]["allowed_non_signal_metadata"].append("sector")
                else:
                    mutate(changed)
                self._assert_integrity_rejects(changed)

    def test_arm_proximity_static_audit_does_not_touch_terminal_semantics(self):
        audit = audit_arm_proximity_dependency()
        self.assertEqual(audit.formal_confirmation_predicates, ("close_t > breakout_price",))
        self.assertIn("setup.confirmed_index == current_index", audit.terminal_event_predicates)
        self.assertFalse(audit.formal_confirmed_terminal_semantics_affected)
        self.assertEqual(
            audit.conclusion,
            "V1_KEEP_CLOSED_ARMED_WARNING_ONLY_NO_CONFIRMED_TERMINAL_CHANGE",
        )
        source = Path("research/structural_validation_protocol.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(imported_roots.isdisjoint({"main", "providers", "sheets_client", "core", "trading"}))
        self.assertNotIn("replay_setup03_history", source)

    def test_serialization_round_trip(self):
        protocol = load_protocol()
        self.assertEqual(json.loads(serialize_protocol(protocol)), protocol)

    def _assert_integrity_rejects(self, protocol):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(protocol), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                load_protocol(path)
if __name__ == "__main__":
    unittest.main()

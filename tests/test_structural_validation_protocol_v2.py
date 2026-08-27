import ast
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.structural_validation_protocol_v2 import (
    EXPECTED_CANDIDATE_LEVEL_THRESHOLD_IDS,
    EXPECTED_ADJACENT_PAIR_THRESHOLD_IDS,
    EXPECTED_CANDIDATE_QUALIFICATION_MATRIX,
    EXPECTED_PROTOCOL_VERSION,
    EXPECTED_V1_PROTOCOL_SHA256,
    PINNED_PROTOCOL_SHA256_BY_VERSION,
    PRODUCTION_TOLERANCES,
    PROTOCOL_PATH,
    PROTOCOL_STATUS,
    REQUIRED_FORBIDDEN_METRICS,
    load_protocol,
    protocol_integrity_hash,
    serialize_protocol,
)


class StructuralValidationProtocolV2Tests(unittest.TestCase):
    def test_protocol_is_independent_versioned_and_not_executed(self):
        protocol = load_protocol()
        self.assertEqual(protocol["protocol_version"], EXPECTED_PROTOCOL_VERSION)
        self.assertEqual(protocol["phase5j_status"], PROTOCOL_STATUS)
        self.assertEqual(
            protocol["integrity"]["protocol_sha256"],
            PINNED_PROTOCOL_SHA256_BY_VERSION[EXPECTED_PROTOCOL_VERSION],
        )
        self.assertEqual(
            protocol["parent_phase5j_v1"]["protocol_sha256"],
            EXPECTED_V1_PROTOCOL_SHA256,
        )
        self.assertFalse(protocol["scope"]["validation_executed"])
        self.assertFalse(protocol["scope"]["phase5k_validation_ohlcv_accessed"])
        self.assertFalse(protocol["scope"]["setup03_output_accessed"])
        self.assertFalse(protocol["scope"]["final_oos_accessed"])
        self.assertFalse(protocol["scope"]["formal_parameter_selected"])

    def test_scope_is_cn_us_only_and_change_is_pre_data_non_result_driven(self):
        protocol = load_protocol()
        scope = protocol["scope"]
        self.assertEqual(tuple(scope["validation_markets"]), ("CN", "US"))
        self.assertEqual(tuple(scope["excluded_markets"]), ("HK", "JP", "SE"))
        self.assertTrue(scope["deployment_scope_change"]["effective_before_phase5k_data_or_setup03_output"])
        self.assertIn("not result-driven", scope["deployment_scope_change"]["reason"])
        self.assertEqual(
            tuple(scope["deployment_scope_change"]["formal_validation_dataset_markets"]),
            ("CN", "US"),
        )

    def test_cn_scope_registers_only_main_boards_and_keeps_inactive_entries(self):
        cn = load_protocol()["market_scope"]["CN"]
        self.assertEqual(
            {row["status"] for row in cn["enabled_venues"]},
            {"CN_SSE_MAIN_BOARD_ACTIVE", "CN_SZSE_MAIN_BOARD_ACTIVE"},
        )
        inactive = {row["status"]: row for row in cn["registered_inactive_venues"]}
        for status in ("CN_STAR_REGISTERED_INACTIVE", "CN_CHINEXT_REGISTERED_INACTIVE"):
            self.assertIn(status, inactive)
            for key in ("eligible_for_phase5k", "eligible_for_ohlcv", "eligible_for_qualification"):
                self.assertFalse(inactive[status][key])
            self.assertTrue(inactive[status]["activation_requires_protocol_version_upgrade"])
        self.assertEqual(
            [(row["id"], row["source_index_code"], row["primary_quota"]) for row in cn["candidate_universes"]],
            [("CSI300", "000300.SH", 12), ("CSI500", "000905.SH", 14), ("CSI1000", "000852.SH", 14)],
        )
        self.assertEqual((cn["primary_target"], cn["reserve_target"]), (40, 20))

    def test_us_scope_quota_dedup_and_aggregate_instruments(self):
        protocol = load_protocol()
        us = protocol["market_scope"]["US"]
        self.assertEqual(
            [(row["id"], row["primary_quota"]) for row in us["candidate_universes"]],
            [("SP500", 12), ("NASDAQ100", 10), ("SOX", 8), ("IGV", 10)],
        )
        self.assertEqual((us["primary_target"], us["reserve_target"]), (40, 20))
        self.assertEqual(us["deduplication_key"], "canonical_issuer_share_class_identity")
        aggregate = protocol["aggregate_diagnostic_instruments"]
        self.assertEqual(tuple(aggregate["instruments"]), ("QQQ", "SOX_INDEX", "IGV_ETF"))
        self.assertFalse(aggregate["counts_toward_equity_sample_minimum"])
        self.assertFalse(aggregate["counts_toward_candidate_qualification"])
        self.assertFalse(aggregate["may_determine_tolerance"])

    def test_thresholds_preserve_values_remove_only_market_concentration(self):
        thresholds = {row["id"]: row for row in load_protocol()["structural_validation_thresholds"]}
        self.assertNotIn("maximum_market_confirmed_concentration", thresholds)
        self.assertEqual(set(thresholds), {
            "minimum_confirmed_events_per_market_candidate",
            "adjacent_confirmed_jaccard",
            "adjacent_confirmed_retention",
            "matched_confirmed_event_date_drift_median",
            "matched_confirmed_event_date_drift_p90",
            "maximum_symbol_confirmed_concentration",
            "adjacent_confirmed_rate_relative_increase",
        })
        expected = {
            "minimum_confirmed_events_per_market_candidate": (">=", 8),
            "adjacent_confirmed_jaccard": (">=", 0.60),
            "adjacent_confirmed_retention": (">=", 0.80),
            "matched_confirmed_event_date_drift_median": ("<=", 5),
            "matched_confirmed_event_date_drift_p90": ("<=", 15),
            "maximum_symbol_confirmed_concentration": ("<=", 0.25),
            "adjacent_confirmed_rate_relative_increase": ("<=", 0.50),
        }
        self.assertEqual(
            {key: (row["operator"], row["threshold"]) for key, row in thresholds.items()},
            expected,
        )
        for row in thresholds.values():
            self.assertIn("each market independently", row["scope"])

    def test_qualification_is_independent_by_market_and_matrix_is_unchanged(self):
        rule = load_protocol()["parameter_selection_rule"]
        self.assertIn("independently in CN", rule["qualification_semantics"])
        self.assertIn("no market may compensate", rule["qualification_semantics"])
        self.assertEqual(
            rule["candidate_qualification_matrix"],
            [
                {
                    "candidate_pct": row["candidate_pct"],
                    "candidate_level_threshold_ids": list(EXPECTED_CANDIDATE_LEVEL_THRESHOLD_IDS),
                    "adjacent_pair_threshold_ids": list(EXPECTED_ADJACENT_PAIR_THRESHOLD_IDS),
                    "adjacent_pairs": [list(pair) for pair in row["adjacent_pairs"]],
                }
                for row in EXPECTED_CANDIDATE_QUALIFICATION_MATRIX
            ],
        )
        self.assertEqual(tuple(rule["ordered_candidates_pct"]), PRODUCTION_TOLERANCES)
        self.assertFalse(rule["performance_metrics_used"])
        self.assertTrue(REQUIRED_FORBIDDEN_METRICS.issubset(load_protocol()["forbidden_metrics"]))

    def test_integrity_rejects_same_version_drift_and_round_trip_is_stable(self):
        protocol = load_protocol()
        self.assertEqual(json.loads(serialize_protocol(protocol)), protocol)
        changed = copy.deepcopy(protocol)
        changed["market_scope"]["CN"]["primary_target"] = 41
        with TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                load_protocol(path)

        recomputed = copy.deepcopy(protocol)
        recomputed["market_scope"]["CN"]["primary_target"] = 41
        recomputed["integrity"]["protocol_sha256"] = protocol_integrity_hash(recomputed)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "recomputed.json"
            path.write_text(json.dumps(recomputed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bound to a different canonical hash"):
                load_protocol(path)

    def test_module_has_no_data_or_trading_io_dependencies(self):
        source = Path("research/structural_validation_protocol_v2.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(imported_roots.isdisjoint({"main", "providers", "sheets_client", "core", "trading"}))
        self.assertNotIn("import urllib", source)
        self.assertNotIn("import requests", source)


if __name__ == "__main__":
    unittest.main()

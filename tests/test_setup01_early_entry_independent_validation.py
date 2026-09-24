import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research.development.setup01_early_entry_independent_validation_dataset import (
    DATASET_MANIFEST_PATH,
    DATASET_VERSION,
    FROZEN_INPUT_PATH,
    load_validation_sample,
)
from research.development.pre_confirmation_early_entry_causal_research_v1 import _percentile
from research.development.setup01_early_entry_independent_validation_v1 import (
    CLASSIFICATION_INSUFFICIENT,
    CLASSIFICATION_NOT_SUPPORTED,
    CLASSIFICATION_SUPPORTED,
    DEFAULT_JSON_OUTPUT,
    PROTOCOL_PATH,
    _validate_protocol,
    classify_market,
    exact_sign_test_p_value,
)


def _protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def _metrics(**overrides) -> dict:
    values = {
        "anchor_contexts": 300,
        "executable_early_signals": 200,
        "paired_later_confirmed_executable": 100,
        "paired_count": 100,
        "paired_median_gain_R": 0.25,
        "paired_sign_test_p_value": 0.001,
        "structural_invalidation_share_of_executable_signals": 0.20,
        "later_confirmed_share_of_executable_signals": 0.30,
    }
    values.update(overrides)
    return values


def _sha256(path: Path, *, normalize_lf: bool = False) -> str:
    payload = path.read_bytes()
    if normalize_lf:
        payload = payload.replace(b"\r\n", b"\n")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class SignTestTests(unittest.TestCase):
    def test_empty_pair_set_is_not_significant(self):
        self.assertEqual(exact_sign_test_p_value(0, 0), 1.0)

    def test_two_sided_exact_binomial_value(self):
        self.assertAlmostEqual(exact_sign_test_p_value(8, 2), 0.109375, places=12)
        self.assertAlmostEqual(exact_sign_test_p_value(5, 0), 0.0625, places=12)

    def test_direction_symmetry(self):
        self.assertAlmostEqual(exact_sign_test_p_value(3, 7), exact_sign_test_p_value(7, 3))


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.rules = _protocol()["decision_rules"]

    def test_all_gates_pass_supports_second_stage_application(self):
        decision = classify_market(_metrics(), self.rules)
        self.assertEqual(decision["classification"], CLASSIFICATION_SUPPORTED)
        self.assertEqual(decision["failed_gates"], [])
        self.assertEqual(decision["failed_floors"], [])

    def test_sparse_cohort_is_insufficient_evidence(self):
        decision = classify_market(_metrics(anchor_contexts=99), self.rules)
        self.assertEqual(decision["classification"], CLASSIFICATION_INSUFFICIENT)
        self.assertEqual(decision["failed_floors"], ["MIN_ANCHOR_CONTEXTS_PER_MARKET"])

    def test_sparse_paired_population_is_insufficient_evidence(self):
        decision = classify_market(
            _metrics(paired_later_confirmed_executable=24, paired_count=24), self.rules
        )
        self.assertEqual(decision["classification"], CLASSIFICATION_INSUFFICIENT)

    def test_small_price_space_gain_fails_space_gate(self):
        decision = classify_market(_metrics(paired_median_gain_R=0.10), self.rules)
        self.assertEqual(decision["classification"], CLASSIFICATION_NOT_SUPPORTED)
        self.assertIn("SPACE_IMPROVEMENT", decision["failed_gates"])

    def test_insignificant_sign_test_fails_space_gate(self):
        decision = classify_market(_metrics(paired_sign_test_p_value=0.06), self.rules)
        self.assertIn("SPACE_IMPROVEMENT", decision["failed_gates"])

    def test_material_invalidation_cost_fails_control_gate(self):
        decision = classify_market(
            _metrics(structural_invalidation_share_of_executable_signals=0.36), self.rules
        )
        self.assertIn("INVALIDATION_CONTROL", decision["failed_gates"])

    def test_weak_confirmation_yield_fails_control_gate(self):
        decision = classify_market(
            _metrics(later_confirmed_share_of_executable_signals=0.19), self.rules
        )
        self.assertIn("CONFIRMATION_CONTROL", decision["failed_gates"])


class ProtocolFreezeTests(unittest.TestCase):
    def test_registered_protocol_passes_its_own_guard(self):
        _validate_protocol(_protocol())

    def test_changed_experimental_group_is_rejected(self):
        protocol = _protocol()
        protocol["single_experimental_group"]["policy_id"] = "FIRST_BULLISH_RECOVERY"
        with self.assertRaises(ValueError):
            _validate_protocol(protocol)

    def test_weakened_decision_rule_is_rejected(self):
        protocol = _protocol()
        protocol["decision_rules"]["overall_requires_all_markets_to_pass"] = False
        with self.assertRaises(ValueError):
            _validate_protocol(protocol)

    def test_removed_forbidden_boundary_is_rejected(self):
        protocol = _protocol()
        protocol["forbidden"] = [
            item for item in protocol["forbidden"] if item != "milestone search or new filter combinations"
        ]
        with self.assertRaises(ValueError):
            _validate_protocol(protocol)

    def test_final_oos_control_is_required(self):
        protocol = _protocol()
        protocol["governance"]["final_oos_accessed"] = True
        with self.assertRaises(ValueError):
            _validate_protocol(protocol)


class ResultArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(DEFAULT_JSON_OUTPUT.read_text(encoding="utf-8"))

    def test_artifact_binds_the_frozen_protocol_and_sample_manifests(self):
        sources = self.document["source_artifacts"]
        # Tracked JSON provenance files are hashed over Git-normalized LF bytes so
        # the recorded identity is identical on Windows and Linux checkouts.
        self.assertEqual(sources["protocol"]["sha256"], _sha256(PROTOCOL_PATH, normalize_lf=True))
        self.assertEqual(
            sources["dataset_manifest"]["sha256"], _sha256(DATASET_MANIFEST_PATH, normalize_lf=True)
        )
        self.assertEqual(sources["dataset_version"], DATASET_VERSION)
        self.assertEqual(sources["universe_symbol_list_sha256"], _protocol()["sample"]["universe_symbol_list_sha256"])

    def test_only_the_registered_group_and_comparator_are_reported(self):
        self.assertEqual(
            sorted(self.document["policies"]),
            ["ARMED_HALF_RECOVERY", "INCUMBENT_CONFIRMED_CLOSE"],
        )
        self.assertEqual(
            sorted(self.document["decision"]["per_market"]), ["CN", "US"]
        )

    def test_paired_rows_reproduce_the_reported_headline(self):
        rows = self.document["paired_evidence"]["rows"]
        aggregate = self.document["paired_evidence"]["aggregate"]
        self.assertEqual(len(rows), aggregate["paired_count"])
        self.assertEqual(
            len(rows), len({(row["market"], row["candidate_key"]) for row in rows})
        )
        gains = [row["gain_R"] for row in rows]
        positives = sum(row["gain_sign"] > 0 for row in rows)
        negatives = sum(row["gain_sign"] < 0 for row in rows)
        self.assertEqual(positives, aggregate["positive_gain_count"])
        self.assertEqual(negatives, aggregate["negative_gain_count"])
        self.assertAlmostEqual(_percentile(gains, 0.5), aggregate["gain_R"]["median"], places=9)
        self.assertAlmostEqual(
            aggregate["sign_test"]["p_value"], exact_sign_test_p_value(positives, negatives), places=12
        )
        for market, summary in self.document["paired_evidence"]["by_market"].items():
            market_rows = [row for row in rows if row["market"] == market]
            self.assertEqual(len(market_rows), summary["paired_count"])
            self.assertEqual(
                summary["positive_gain_count"], sum(row["gain_sign"] > 0 for row in market_rows)
            )
        self.assertEqual(
            self.document["decision"]["supports_second_stage_application"],
            self.document["status"] == CLASSIFICATION_SUPPORTED,
        )

    def test_every_paired_row_enters_after_the_incumbent_signal(self):
        for row in self.document["paired_evidence"]["rows"]:
            self.assertEqual(row["eventual_status"], "LATER_CONFIRMED")
            self.assertLess(row["signal_date"], row["incumbent_signal_date"])
            self.assertLess(row["early_entry_date"], row["incumbent_entry_date"])

    def test_common_denominator_keeps_failed_unconfirmed_and_censored_lifecycles(self):
        cohort = self.document["cohort_construction"]
        self.assertGreater(cohort["total_candidate_count"], cohort["eventually_confirmed_count"])
        self.assertGreater(cohort["failed_count"], 0)
        self.assertGreater(cohort["never_confirmed_count"], 0)
        self.assertTrue(self.document["validation"]["cohort_eventual_status_conserved"])
        self.assertTrue(self.document["validation"]["cohort_resolution_conserved"])
        early = self.document["policies"]["ARMED_HALF_RECOVERY"]
        self.assertEqual(
            early["signaled_candidate_count"],
            early["eventually_confirmed_count"] + early["failed_count"] + early["never_confirmed_count"],
        )
        self.assertGreater(early["never_confirmed_count"], 0)
        self.assertGreater(early["failed_count"], 0)

    def test_research_controls_remain_closed(self):
        controls = self.document["controls"]
        self.assertFalse(controls["final_oos_accessed"])
        self.assertFalse(controls["real_holdings_accessed"])
        self.assertFalse(controls["execution_cost_or_net_return_computed"])
        self.assertFalse(controls["parameter_search"])
        self.assertFalse(controls["threshold_sweep"])
        self.assertEqual(controls["state_writes"], 0)
        self.assertEqual(controls["sheets_writes"], 0)
        self.assertEqual(controls["broker_orders"], 0)


class DatasetManifestTests(unittest.TestCase):
    def test_tampered_manifest_fails_the_integrity_gate(self):
        manifest = json.loads(DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["aggregate_valid_bar_count"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dataset_manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_validation_sample(dataset_manifest_path=path, frozen_input_path=FROZEN_INPUT_PATH)

    @unittest.skipUnless(
        DATASET_MANIFEST_PATH.exists() and FROZEN_INPUT_PATH.exists(),
        "frozen independent sample payload is not present in this checkout",
    )
    def test_frozen_sample_roster_and_replay_identity(self):
        manifest, quotes, replay_manifest = load_validation_sample()
        self.assertEqual(len(quotes), 40)
        self.assertEqual(manifest["market_coverage"]["CN"]["valid_accepted"], 20)
        self.assertEqual(manifest["market_coverage"]["US"]["valid_accepted"], 20)
        self.assertEqual(replay_manifest.total_bar_count, 88075)
        self.assertEqual(manifest["coverage_status"], "READY_FOR_SETUP01_EARLY_ENTRY_FIRST_STAGE")


if __name__ == "__main__":
    unittest.main()

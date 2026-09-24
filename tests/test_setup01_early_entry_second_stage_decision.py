import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest import mock

from core import Quote
from research.development.pre_confirmation_early_entry_causal_research_v1 import (
    CandidateLifecycle,
)
from research.development.setup01_early_entry_second_stage_decision_v1 import (
    ADMITTED,
    ARTIFACT_VERSION,
    DEFAULT_JSON_OUTPUT,
    PACKAGE_IDS,
    SKIP_ATR_UNAVAILABLE,
    SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP,
    SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION,
    SKIP_OPEN_OUTSIDE_TRIGGER_BAND,
    SKIP_RR_BELOW_MINIMUM_AT_OPEN,
    SKIP_TARGET_UPSIDE_BELOW_MINIMUM,
    STAGE1_JSON_PATH,
    STAGE1_MARKDOWN_PATH,
    STAGE1_PROTOCOL_PATH,
    STATUS_READY_FOR_DECISION,
    _classify_package,
    preconfirmation_target_candidates,
)
from research.development.setup01_early_entry_independent_validation_dataset import (
    DATASET_MANIFEST_PATH,
    FROZEN_INPUT_PATH,
)
from trading.setup01_decision import _target_candidates
from trading.swing import find_swings


def _quote(index: int, close: float, *, symbol: str = "TEST.SYMBOL") -> Quote:
    high = close + 0.5
    low = close - 0.5
    return Quote(
        symbol=symbol,
        name="second stage decision synthetic",
        market="US",
        trade_date=date(2020, 1, 1) + timedelta(days=index),
        source="test",
        open=close,
        high=high,
        low=low,
        close=close,
        preclose=None,
        pct_change=None,
        volume=1000.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _lifecycle(**overrides) -> CandidateLifecycle:
    values = {
        "key": "TEST.SYMBOL|SETUP_01|wave2_context=1/2/3",
        "symbol": "TEST.SYMBOL",
        "market": "US",
        "lifecycle_index": 1,
        "first_observed_index": 10,
        "last_observed_index": 40,
        "ready_index": 12,
        "first_observed_date": date(2020, 1, 11),
        "last_observed_date": date(2020, 2, 10),
        "ready_date": date(2020, 1, 13),
        "origin_price": 100.0,
        "origin_pivot_date": date(2019, 12, 1),
        "peak_price": 120.0,
        "peak_pivot_date": date(2019, 12, 20),
        "wave2_low_price": 110.0,
        "wave2_low_pivot_date": date(2020, 1, 5),
        "wave1_range_R": 20.0,
        "retracement_ratio_r": 0.5,
        "geometry_valid": True,
        "depth_band": "DEEP",
        "time_half": "FIRST_HALF",
        "eventual_status": "LATER_CONFIRMED",
        "resolution": "TERMINAL_CONFIRMED",
        "resolution_index": 30,
        "resolution_date": date(2020, 1, 31),
        "confirmed_index": 30,
        "confirmed_date": date(2020, 1, 31),
        "failed_index": None,
        "failed_date": None,
        "failure_class": None,
        "failure_reason": None,
        "source_visibility": "PRIMARY_ONLY",
        "observations": (),
    }
    values.update(overrides)
    return CandidateLifecycle(**values)


RECOVERY_LEVEL = 115.0


class PackageClassificationTests(unittest.TestCase):
    def _classify(self, package_id: str, *, entry: float, atr14=None, signal_close=116.0):
        return _classify_package(
            package_id,
            candidate=_lifecycle(),
            prefix=[_quote(0, 116.0)],
            entry=entry,
            atr14=atr14,
            recovery_level=RECOVERY_LEVEL,
            signal_close=signal_close,
        )

    def test_structural_package_uses_the_confirmed_wave2_low(self):
        detail = self._classify("PKG_A_STRUCTURAL_RISK_ONLY", entry=111.0)
        self.assertEqual(detail["admission"], ADMITTED)
        self.assertAlmostEqual(detail["risk_per_share"], 1.0)
        self.assertAlmostEqual(detail["risk_pct_of_entry"], 1.0 / 111.0)
        self.assertAlmostEqual(detail["risk_over_R"], 1.0 / 20.0)
        self.assertAlmostEqual(
            detail["notional_over_allocation_budget"], 0.005 * 111.0
        )

    def test_structural_package_skips_an_open_at_or_below_invalidation(self):
        detail = self._classify("PKG_A_STRUCTURAL_RISK_ONLY", entry=110.0)
        self.assertEqual(
            detail["admission"], SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION
        )
        self.assertFalse(detail["admitted"])
        self.assertIsNone(detail["notional_over_allocation_budget"])

    def test_atr_package_places_the_stop_below_the_structural_low(self):
        detail = self._classify("PKG_B_ATR_EXECUTION_STOP", entry=109.0, atr14=4.0)
        self.assertEqual(detail["admission"], ADMITTED)
        self.assertAlmostEqual(detail["execution_stop"], 108.0)
        self.assertAlmostEqual(detail["risk_per_share"], 1.0)

    def test_atr_package_requires_a_causal_atr(self):
        detail = self._classify("PKG_B_ATR_EXECUTION_STOP", entry=109.0, atr14=None)
        self.assertEqual(detail["admission"], SKIP_ATR_UNAVAILABLE)
        self.assertFalse(detail["admitted"])

    def test_atr_package_skips_an_open_at_or_below_the_stop(self):
        detail = self._classify("PKG_B_ATR_EXECUTION_STOP", entry=107.5, atr14=4.0)
        self.assertEqual(detail["admission"], SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP)

    def test_incumbent_discipline_bounds_the_entry_to_the_trigger_band(self):
        below = self._classify(
            "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE", entry=114.0, atr14=4.0
        )
        self.assertEqual(below["admission"], SKIP_OPEN_OUTSIDE_TRIGGER_BAND)
        above = self._classify(
            "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE", entry=123.0, atr14=4.0
        )
        self.assertEqual(above["admission"], SKIP_OPEN_OUTSIDE_TRIGGER_BAND)

    def test_incumbent_discipline_admits_only_when_both_incumbent_gates_pass(self):
        detail = self._classify(
            "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE", entry=116.5, atr14=4.0
        )
        self.assertEqual(detail["admission"], ADMITTED)
        self.assertGreaterEqual(detail["target_upside_pct_at_signal_close"], 0.05)
        self.assertGreaterEqual(detail["rr_at_next_open"], 2.0)
        self.assertAlmostEqual(detail["execution_stop"], 108.0)

    def test_incumbent_discipline_applies_the_five_percent_gate(self):
        with mock.patch(
            "research.development.setup01_early_entry_second_stage_decision_v1."
            "preconfirmation_target_candidates",
            return_value=(116.5,),
        ):
            detail = self._classify(
                "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE", entry=116.0, atr14=4.0
            )
        self.assertEqual(detail["admission"], SKIP_TARGET_UPSIDE_BELOW_MINIMUM)

    def test_incumbent_discipline_applies_the_two_R_gate_at_the_open(self):
        with mock.patch(
            "research.development.setup01_early_entry_second_stage_decision_v1."
            "preconfirmation_target_candidates",
            return_value=(125.0,),
        ):
            detail = self._classify(
                "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE", entry=118.0, atr14=4.0
            )
        self.assertEqual(detail["admission"], SKIP_RR_BELOW_MINIMUM_AT_OPEN)
        self.assertGreaterEqual(detail["target_upside_pct_at_signal_close"], 0.05)
        self.assertLess(detail["rr_at_next_open"], 2.0)


class TargetConstructionMirrorTests(unittest.TestCase):
    def _series(self) -> list[Quote]:
        closes = [100.0] * 60
        for offset, close in enumerate(
            [101, 103, 106, 109, 112, 115, 118, 121, 118, 114, 111, 108, 111, 114, 117, 120,
             123, 126, 122, 118, 115, 112, 116, 120, 124, 128, 132, 129, 125, 121, 124, 127,
             130, 133, 136, 139, 135, 131, 128, 132, 136, 140, 144, 148, 152, 149, 145, 141,
             144, 147, 150, 153, 156, 159, 155, 151, 148, 152, 156, 160]
        ):
            closes[offset] = float(close)
        return [_quote(index, close) for index, close in enumerate(closes)]

    def test_mirror_reproduces_the_production_target_set(self):
        quotes = self._series()
        swings = find_swings(quotes, lookback=5)
        highs = [swing for swing in swings if swing.kind.value == "HIGH"]
        lows = [swing for swing in swings if swing.kind.value == "LOW"]
        self.assertTrue(highs and lows)
        peak = highs[0]
        wave2_low = lows[-1]
        origin = lows[0]
        entry = 120.0
        expected = tuple(
            sorted(
                {
                    candidate.price
                    for candidate in _target_candidates(
                        quotes,
                        origin=origin,
                        peak=peak,
                        wave2_low=wave2_low,
                        entry=entry,
                        swing_lookback=5,
                    )
                }
            )
        )
        mirror = preconfirmation_target_candidates(
            quotes,
            origin_price=origin.price,
            peak_price=peak.price,
            wave2_low_price=wave2_low.price,
            entry=entry,
        )
        self.assertEqual(mirror, expected)
        self.assertTrue(all(price > entry for price in mirror))


class DecisionArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(DEFAULT_JSON_OUTPUT.read_text(encoding="utf-8"))
        cls.stage1 = json.loads(STAGE1_JSON_PATH.read_text(encoding="utf-8"))

    def test_status_and_controls_remain_research_only(self):
        document = self.document
        self.assertEqual(document["artifact_version"], ARTIFACT_VERSION)
        self.assertEqual(document["status"], STATUS_READY_FOR_DECISION)
        self.assertTrue(document["decision_required"])
        self.assertFalse(document["protocol_registered"])
        self.assertFalse(document["production_authorization"])
        self.assertIsNone(document["second_stage_protocol_id"])
        controls = document["controls"]
        for key in (
            "net_return_or_pnl_computed",
            "execution_cost_computed",
            "win_rate_or_expectancy_computed",
            "position_or_allocation_authorized",
            "final_oos_accessed",
            "real_holdings_accessed",
            "provider_or_symbol_switch",
            "sample_replaced_or_extended",
            "parameter_search_or_threshold_sweep",
        ):
            self.assertFalse(controls[key], key)
        self.assertEqual(controls["state_writes"], 0)
        self.assertEqual(controls["sheets_writes"], 0)
        self.assertEqual(controls["broker_orders"], 0)

    def test_first_stage_artifact_is_unchanged_and_referenced(self):
        self.assertEqual(self.stage1["status"], "FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION")
        reference = self.document["stage1_reference"]
        self.assertTrue(reference["immutable"])
        self.assertEqual(reference["status"], self.stage1["status"])
        self.assertEqual(
            reference["overall_classification"], self.stage1["decision"]["overall_classification"]
        )
        self.assertEqual(
            self.document["source_artifacts"]["stage1_protocol"]["path"],
            STAGE1_PROTOCOL_PATH.relative_to(STAGE1_PROTOCOL_PATH.parents[2]).as_posix(),
        )

    def test_denominator_matches_the_frozen_first_stage(self):
        denominator = self.document["denominator"]
        self.assertEqual(
            denominator["anchor_contexts"],
            self.stage1["cohort_construction"]["total_candidate_count"],
        )
        for market in ("CN", "US"):
            self.assertEqual(
                denominator["rebuilt_executable_early_signals"][market],
                self.stage1["market_metrics"][market]["executable_early_signals"],
            )
        facts = self.document["shared_geometry_facts"]["combined"]
        signaled = self.stage1["policies"]["ARMED_HALF_RECOVERY"]["signaled_composition"]
        self.assertEqual(
            facts["eventual_status_composition"],
            {
                "LATER_CONFIRMED": signaled["LATER_CONFIRMED"],
                "FAILED": signaled["FAILED"],
                "NEVER_CONFIRMED": signaled["NEVER_CONFIRMED"],
            },
        )
        self.assertEqual(
            facts["early_signals"],
            self.stage1["policies"]["ARMED_HALF_RECOVERY"]["signaled_candidate_count"],
        )

    def test_every_package_covers_the_executable_denominator_with_conserved_counts(self):
        packages = self.document["candidate_packages"]
        self.assertEqual(tuple(packages), PACKAGE_IDS)
        executable = self.document["shared_geometry_facts"]["combined"][
            "executable_next_session_open"
        ]
        for package_id, package in packages.items():
            combined = package["combined"]
            self.assertEqual(
                combined["signals_with_executable_next_open"], executable, package_id
            )
            self.assertEqual(
                sum(combined["admission_counts"].values()), executable, package_id
            )
            self.assertEqual(
                combined["admitted_count"], combined["admission_counts"].get(ADMITTED, 0)
            )
            self.assertEqual(
                sum(
                    value["signals_with_executable_next_open"]
                    for value in package["per_market"].values()
                ),
                executable,
            )
        self.assertTrue(self.document["validation"]["admission_counts_conserved"])
        self.assertFalse(self.document["validation"]["outcome_metrics_computed"])

    def test_packages_are_mutually_exclusive_definitions(self):
        packages = self.document["candidate_packages"]
        fingerprints = {
            (
                package["definition"]["admission_rule"],
                package["definition"]["pre_confirmation_execution_stop"],
                package["definition"]["pre_confirmation_targets"],
            )
            for package in packages.values()
        }
        self.assertEqual(len(fingerprints), len(PACKAGE_IDS))
        self.assertNotEqual(
            packages["PKG_A_STRUCTURAL_RISK_ONLY"]["definition"][
                "pre_confirmation_execution_stop"
            ],
            packages["PKG_B_ATR_EXECUTION_STOP"]["definition"][
                "pre_confirmation_execution_stop"
            ],
        )
        self.assertEqual(
            packages["PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE"]["definition"][
                "admission_rule"
            ],
            "TRIGGER_BAND_PLUS_INCUMBENT_TARGET_UPSIDE_AND_RR_GATES",
        )

    def test_no_outcome_metric_fields_are_serialised(self):
        banned = (
            "pnl",
            "net_return",
            "return_pct",
            "win_rate",
            "expectancy",
            "sharpe",
            "drawdown",
            "net_R",
        )

        def keys(value, *, skip_controls=True):
            if isinstance(value, dict):
                for key, item in value.items():
                    if skip_controls and key == "controls":
                        continue
                    yield key
                    yield from keys(item)
            elif isinstance(value, list):
                for item in value:
                    yield from keys(item)

        for key in keys(self.document):
            for token in banned:
                self.assertNotIn(token.lower(), key.lower(), key)

    def test_source_hashes_bind_the_frozen_inputs(self):
        def digest(path: Path) -> str:
            payload = path.read_bytes()
            if path.suffix != ".gz":
                payload = payload.replace(b"\r\n", b"\n")
            return f"sha256:{hashlib.sha256(payload).hexdigest()}"

        sources = self.document["source_artifacts"]
        for key, path in (
            ("stage1_protocol", STAGE1_PROTOCOL_PATH),
            ("stage1_json", STAGE1_JSON_PATH),
            ("stage1_markdown", STAGE1_MARKDOWN_PATH),
            ("dataset_manifest", DATASET_MANIFEST_PATH),
        ):
            self.assertEqual(sources[key]["sha256"], digest(path), key)
        if FROZEN_INPUT_PATH.exists():
            self.assertEqual(
                sources["frozen_replay_input"]["sha256"],
                digest(FROZEN_INPUT_PATH),
            )

    def test_residual_decisions_are_registered_before_the_protocol(self):
        decisions = {item["decision_id"] for item in self.document["residual_decisions"]}
        self.assertEqual(
            decisions,
            {
                "PRE_CONFIRMATION_WAITING_BOUND",
                "COST_AND_TRADABILITY_SCENARIOS",
                "POST_CONFIRMATION_HANDOFF_CONFIRMATION",
            },
        )
        for item in self.document["residual_decisions"]:
            self.assertTrue(item["no_default"])
        dimensions = {
            item["dimension"] for item in self.document["determinacy_audit"]["not_determined"]
        }
        self.assertIn("entry_admission_geometry", dimensions)
        self.assertIn("preconfirmation_execution_stop_and_risk_basis", dimensions)
        self.assertIn("preconfirmation_target_and_gate_semantics", dimensions)


if __name__ == "__main__":
    unittest.main()

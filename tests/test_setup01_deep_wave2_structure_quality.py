import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

from research.development.setup01_deep_wave2_structure_quality_v1 import (
    COMMON_HURDLES,
    DEFAULT_JSON_OUTPUT,
    HURDLE_OUTCOMES,
    STRUCTURAL_OUTCOMES,
    _bars_before_structural_invalidation,
    _post_T_quotes,
    _two_by_two,
    classify_hurdle_outcome,
    classify_structural_outcome,
    common_hurdle_level,
    depth_band,
    normalized_common_excursion,
)


class Setup01DeepWave2StructureQualityTests(unittest.TestCase):
    def test_depth_bands_are_fixed_exhaustive_and_boundary_aware(self):
        self.assertEqual(depth_band(0.618), "NORMAL_OR_SHALLOW")
        self.assertEqual(depth_band(0.6180000001), "DEEP")
        self.assertEqual(depth_band(0.786), "DEEP")
        self.assertEqual(depth_band(0.7860000001), "VERY_DEEP")
        self.assertEqual(
            {depth_band(value) for value in (0.4, 0.65, 0.79, 0.99)},
            {"NORMAL_OR_SHALLOW", "DEEP", "VERY_DEEP"},
        )

    def test_structural_ordering_does_not_apply_execution_stop_first(self):
        day_1 = date(2026, 1, 2)
        day_2 = date(2026, 1, 3)
        self.assertEqual(
            classify_structural_outcome(day_1, day_2),
            STRUCTURAL_OUTCOMES[0],
        )
        self.assertEqual(
            classify_structural_outcome(day_2, day_1),
            STRUCTURAL_OUTCOMES[1],
        )
        self.assertEqual(
            classify_structural_outcome(day_1, day_1),
            STRUCTURAL_OUTCOMES[2],
        )
        self.assertEqual(
            classify_structural_outcome(None, None),
            STRUCTURAL_OUTCOMES[3],
        )

    def test_common_hurdles_use_one_shared_scale_independent_of_r(self):
        self.assertAlmostEqual(common_hurdle_level(100.0, 20.0, 0.272), 105.44)
        self.assertAlmostEqual(common_hurdle_level(100.0, 20.0, 0.618), 112.36)
        self.assertEqual(
            tuple(name for name, _ in COMMON_HURDLES),
            ("HURDLE_0272", "HURDLE_0618"),
        )

    def test_normalized_excursion_formula_is_common_scale(self):
        result = normalized_common_excursion(140.0, 135.0, 100.0, 110.0, 20.0)
        self.assertAlmostEqual(result["post_T_peak_extension_from_H1_over_R"], 2.0)
        self.assertAlmostEqual(
            result["post_T_peak_extension_from_planned_entry_over_R"], 1.5
        )
        self.assertAlmostEqual(
            result["post_T_peak_close_extension_from_H1_over_R"], 1.75
        )

    def test_future_path_is_strictly_post_T_and_excludes_invalidation_bar(self):
        day_t = date(2026, 1, 2)
        day_next = date(2026, 1, 5)
        day_invalid = date(2026, 1, 6)
        quotes = tuple(
            SimpleNamespace(trade_date=value)
            for value in (day_t, day_next, day_invalid)
        )
        future = _post_T_quotes(quotes, day_t)
        before_invalidation = _bars_before_structural_invalidation(
            future, day_invalid
        )
        self.assertEqual([item.trade_date for item in future], [day_next, day_invalid])
        self.assertEqual([item.trade_date for item in before_invalidation], [day_next])

    def test_same_bar_hurdle_and_structural_invalidation_is_ambiguous(self):
        day = date(2026, 1, 6)
        self.assertEqual(
            classify_hurdle_outcome(day, day), HURDLE_OUTCOMES[2]
        )

    def test_two_by_two_keeps_unresolved_rows_outside_binary_cells(self):
        rows = [
            {
                "path": SimpleNamespace(outcome=STRUCTURAL_OUTCOMES[0]),
                "planned_entry_to_1272_upside_pct": 0.10,
            },
            {
                "path": SimpleNamespace(outcome=STRUCTURAL_OUTCOMES[0]),
                "planned_entry_to_1272_upside_pct": 0.01,
            },
            {
                "path": SimpleNamespace(outcome=STRUCTURAL_OUTCOMES[1]),
                "planned_entry_to_1272_upside_pct": 0.10,
            },
            {
                "path": SimpleNamespace(outcome=STRUCTURAL_OUTCOMES[3]),
                "planned_entry_to_1272_upside_pct": 0.01,
            },
        ]
        matrix = _two_by_two(rows)
        self.assertEqual(
            matrix["cells"]["STRUCTURE_SUCCESS"]["ENTRY_HEADROOM_GE_5_PCT"]["count"],
            1,
        )
        self.assertEqual(
            matrix["cells"]["STRUCTURE_SUCCESS"]["ENTRY_HEADROOM_LT_5_PCT"]["count"],
            1,
        )
        self.assertEqual(
            matrix["cells"]["STRUCTURE_FAILURE"]["ENTRY_HEADROOM_GE_5_PCT"]["count"],
            1,
        )
        self.assertEqual(matrix["unresolved_outcome_counts"], {STRUCTURAL_OUTCOMES[3]: 1})

    def test_committed_summary_is_compact_and_has_required_bindings(self):
        document = json.loads(Path(DEFAULT_JSON_OUTPUT).read_text(encoding="utf-8"))
        self.assertEqual(document["status"], "READY_FOR_DECISION")
        self.assertEqual(document["scope"]["wave3_fib_near_events"], 81)
        self.assertEqual(document["protocol"]["common_hurdles"], dict(COMMON_HURDLES))
        self.assertEqual(
            sum(item["N"] for item in document["depth_bands"].values()),
            document["scope"]["confirmed_events"],
        )
        for item in document["depth_bands"].values():
            for metric in item["geometry_controlled"]["continuous_metrics"].values():
                self.assertEqual(
                    set(metric["distribution"]),
                    {"n", "p10", "p25", "median", "p75", "p90"},
                )
        self.assertTrue(document["validation"]["common_normalized_excursion_formula_passed"])
        self.assertTrue(document["validation"]["common_hurdle_levels_independent_of_r"])
        self.assertTrue(document["validation"]["hurdle_dates_strictly_post_T"])
        self.assertEqual(document["event_level_detail"]["count"], document["scope"]["confirmed_events"])
        self.assertFalse(document["event_level_detail"]["persisted"])
        self.assertTrue(document["event_level_detail"]["temporary_file_removed"])
        self.assertFalse(document["controls"]["final_oos_accessed"])
        self.assertFalse(document["controls"]["parameter_search"])
        self.assertFalse(document["controls"]["threshold_sweep"])
        self.assertFalse(document["controls"]["production_decision_modified"])
        self.assertEqual(document["controls"]["state_writes"], 0)
        self.assertEqual(document["controls"]["sheets_writes"], 0)
        self.assertEqual(document["controls"]["broker_orders"], 0)


if __name__ == "__main__":
    unittest.main()

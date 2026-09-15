import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest

from research.development.setup01_deep_wave2_structure_quality_v1 import (
    DEFAULT_JSON_OUTPUT,
    STRUCTURAL_OUTCOMES,
    _two_by_two,
    classify_structural_outcome,
    depth_band,
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
        self.assertEqual(
            sum(item["N"] for item in document["depth_bands"].values()),
            document["scope"]["confirmed_events"],
        )
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

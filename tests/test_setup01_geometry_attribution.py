import json
from pathlib import Path
import unittest

from research.development.setup01_wave2_to_wave3_geometry_attribution import (
    DEFAULT_INPUT,
    build_geometry_attribution,
    derive_geometry,
)


class Setup01GeometryAttributionTests(unittest.TestCase):
    def test_requested_fib_identity_and_geometry_fields(self):
        geometry = derive_geometry(
            {
                "wave1_origin_price": 100.0,
                "wave1_peak_price": 110.0,
                "wave2_low_price": 101.0,
                "planned_entry": 111.0,
                "decision_t_atr14": 5.0,
            }
        )

        self.assertAlmostEqual(geometry["R"], 10.0)
        self.assertAlmostEqual(geometry["r"], 0.9)
        self.assertAlmostEqual(geometry["e"], 1.0)
        self.assertAlmostEqual(
            geometry["fib_1_272_remaining_absolute"],
            (1.272 - geometry["r"]) * geometry["R"] - geometry["e"],
        )
        self.assertAlmostEqual(geometry["fib_identity_residual"], 0.0)
        self.assertAlmostEqual(geometry["wave1_gain_pct"], 0.10)
        self.assertAlmostEqual(geometry["wave1_range_over_atr14"], 2.0)
        self.assertAlmostEqual(geometry["confirmation_extension_pct"], 1 / 110)
        self.assertAlmostEqual(geometry["confirmation_extension_over_wave1"], 0.1)
        self.assertAlmostEqual(geometry["fib_headroom_over_wave1"], 0.272)

    def test_current_research_artifact_covers_81_fib_near_events_without_outcomes(self):
        source = json.loads(Path(DEFAULT_INPUT).read_text(encoding="utf-8"))
        artifact = build_geometry_attribution(source)

        self.assertEqual(artifact["scope"]["all_confirmed"], 745)
        self.assertEqual(artifact["scope"]["wave3_fib_near"], 81)
        self.assertEqual(
            artifact["scope"]["wave3_fib_near_category_partition"],
            {
                "SMALL_WAVE_FIB": 18,
                "BOTH_NEAR": 63,
                "NEAR_SWING_ONLY": 117,
            },
        )
        identity = artifact["group_statistics"]["wave3_fib_near"]["metrics"][
            "identity_check"
        ]
        self.assertTrue(identity["passed"])
        self.assertLessEqual(identity["max_absolute_residual"], 1e-9)
        self.assertFalse(artifact["controls"]["final_oos_accessed"])
        self.assertFalse(artifact["controls"]["forward_returns_accessed"])
        self.assertFalse(artifact["controls"]["decision_recomputed"])
        self.assertEqual(
            len(artifact["wave3_fib_near_decomposition"]["detailed_rows"]),
            81,
        )


if __name__ == "__main__":
    unittest.main()

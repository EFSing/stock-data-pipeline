import json
from pathlib import Path
import unittest

from research.development.frozen_development_geometry_attribution_v1 import decompose


ARTIFACT = Path(__file__).resolve().parents[1] / "research/development/frozen_development_geometry_attribution_v1.json"


class FrozenDevelopmentGeometryAttributionTests(unittest.TestCase):
    def test_price_space_decomposition_preserves_stop_identity(self):
        result = decompose({"planned_entry": 110.0, "entry_zone_high": 105.0,
                            "t1": 120.0, "structural_invalidation": 100.0,
                            "execution_stop": 98.0, "atr14": 5.0})
        self.assertEqual(result["zone_extension"], 5.0)
        self.assertEqual(result["target_space"], 10.0)
        self.assertEqual(result["structural_distance"], 10.0)
        self.assertEqual(result["stop_buffer"], 2.0)
        self.assertEqual(result["execution_risk"], 12.0)
        self.assertEqual(result["risk_identity_residual"], 0.0)

    def test_frozen_event_artifact_keeps_common_denominator_and_unknowns(self):
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        rows = artifact["events"]
        self.assertEqual(len(rows), artifact["denominator"])
        self.assertEqual(len(rows), len({(row["setup"], row["identity"]) for row in rows}))
        self.assertEqual(artifact["denominator"], 999)
        self.assertFalse(artifact["forward_outcomes_read"])
        self.assertEqual(sum(item["denominator"] for item in artifact["by_market_setup"].values()), 999)
        self.assertEqual(artifact["summary"]["all_fail"]["RR_BELOW_MINIMUM"], 942)
        self.assertEqual(artifact["summary"]["unknown_by_field"]["t1"], 43)
        self.assertTrue(all("all_rejections" in row for row in rows))


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.run_position_management_generic_operational_shadow import (
    run_position_management_generic_operational_shadow,
)


class PositionManagementGenericOperationalShadowTests(unittest.TestCase):
    def test_position_management_shadow_is_part_of_regression_gate(self):
        with TemporaryDirectory() as temporary_directory:
            result = run_position_management_generic_operational_shadow(
                output_dir=temporary_directory
            )
            output = Path(temporary_directory) / (
                "position_management_generic_operational_shadow.json"
            )
            self.assertTrue(output.exists())

        self.assertEqual(result["status"], "SUCCESS")
        for key in (
            "initial_r_frozen",
            "targets_do_not_auto_exit",
            "target_tracking_reached",
            "stop_never_moves_down",
            "causal_day_count",
        ):
            self.assertTrue(result["checks"][key])
        for key in (
            "broker_accessed",
            "sheets_written",
            "pnl_accessed",
            "final_oos_accessed",
        ):
            self.assertFalse(result["checks"][key])


if __name__ == "__main__":
    unittest.main()

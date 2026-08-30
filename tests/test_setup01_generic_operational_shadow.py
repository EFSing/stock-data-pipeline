import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_setup01_generic_operational_shadow import (
    run_setup01_generic_operational_shadow,
)


class Setup01GenericOperationalShadowTests(unittest.TestCase):
    def test_public_synthetic_shadow_covers_current_operational_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_setup01_generic_operational_shadow(directory)
            report_path = Path(directory, "setup01_generic_operational_shadow.json")
            csv_path = Path(directory, "setup01_generic_operational_shadow.csv")

            self.assertEqual(report["status"], "SUCCESS")
            self.assertTrue(all(report["checks"].values()))
            self.assertEqual(report["events_supplied"], 7)
            self.assertEqual(report["decision_rows"], 3)
            self.assertEqual(report["execution_attempts"], 2)
            self.assertEqual(report["executed"], 1)
            self.assertEqual(report["skipped_gap_below_confirmation"], 1)
            self.assertTrue(report["checks"]["execution_ledger_invariant"])
            self.assertEqual(
                report["development_session_identity"],
                "FROZEN_DATASET_MARKET_SESSION_SET",
            )
            self.assertTrue(report["controls"]["synthetic_only"])
            self.assertFalse(report["controls"]["real_holdings_read"])
            self.assertFalse(report["controls"]["account_secrets_required"])
            self.assertTrue(report_path.exists())
            self.assertTrue(csv_path.exists())
            json.loads(report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

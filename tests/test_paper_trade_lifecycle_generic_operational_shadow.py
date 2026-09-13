import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_paper_trade_lifecycle_generic_operational_shadow import (
    run_paper_trade_lifecycle_generic_operational_shadow,
)


class PaperTradeLifecycleGenericOperationalShadowTests(unittest.TestCase):
    def test_synthetic_shadow_covers_plan_execution_position_close_and_skip(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_paper_trade_lifecycle_generic_operational_shadow(directory)
            report_path = Path(
                directory,
                "paper_trade_lifecycle_generic_operational_shadow.json",
            )

            self.assertEqual(report["status"], "SUCCESS")
            self.assertTrue(
                all(
                    report["checks"][key]
                    for key in (
                        "plan_created",
                        "exact_t1_executed",
                        "profit_protection_closed",
                        "skip_terminal",
                        "normalized_performance",
                        "candidate_not_promoted",
                    )
                )
            )
            self.assertFalse(report["checks"]["real_holdings_read"])
            self.assertFalse(report["checks"]["broker_accessed"])
            self.assertEqual(report["performance"]["closed"], 1)
            self.assertEqual(report["performance"]["win_rate"], 1.0)
            self.assertEqual(report["skipped_trade"]["status"], "SKIPPED")
            self.assertEqual(report["pending_trade"]["name"], "示例科技")
            self.assertEqual(report["open_trade"]["name"], "示例科技")
            self.assertTrue(report_path.exists())
            self.assertTrue(Path(directory, "latest.html").exists())
            html = Path(directory, "latest.html").read_text(encoding="utf-8")
            self.assertIn("模拟交易", html)
            self.assertIn("示例数据 / Synthetic Demo · Paper Lifecycle Shadow", html)
            self.assertIn("示例科技", html)
            self.assertIn("示例制造", html)
            self.assertIn("有没有真正模拟成交", html)
            self.assertIn("样本连续", html)
            self.assertIn("DYNAMIC_CANDIDATE", html)
            json.loads(report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

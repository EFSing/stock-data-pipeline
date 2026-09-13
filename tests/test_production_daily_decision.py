from datetime import date
from pathlib import Path
import tempfile
import unittest

from scripts.run_production_daily_decision import run_production_daily_decision
from tests.test_production_prerequisites import AFTER_CLOSE, T_DAY, _rows


class ProductionDailyDecisionRunnerTests(unittest.TestCase):
    def test_run_is_read_only_by_default_and_keeps_accounts_isolated(self):
        client = _rows()

        result = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            now=AFTER_CLOSE,
        )

        self.assertEqual(result["read behavior"], "READ_ONLY")
        self.assertTrue(result["NO STATE WRITE"])
        self.assertTrue(result["NO Sheets mutation"])
        self.assertEqual(result["broker orders"], "NONE")
        self.assertEqual(
            [item["账户ID"] for item in result["reports"]],
            ["CN-1", "US-1"],
        )
        self.assertTrue(all(item["NO Sheets mutation"] for item in result["reports"]))
        self.assertEqual(client.writes, [])

    def test_stale_qfq_still_emits_fail_closed_daily_rows_without_writing(self):
        client = _rows()
        client.rows["历史行情_前复权"] = [
            dict(row, 交易日期=date(2026, 9, 2).isoformat())
            for row in client.rows["历史行情_前复权"]
        ]

        result = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            now=AFTER_CLOSE,
        )

        self.assertEqual(result["preflight"]["production readiness"], "NOT_READY")
        self.assertEqual(len(result["reports"]), 2)
        for item in result["reports"]:
            row = item["报告"]["results"][0]
            self.assertEqual(row["final_status"], "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED")
            self.assertTrue(row["data_status"] in {"DATA_STALE", "DATA_UNAVAILABLE"})
        self.assertEqual(client.writes, [])

    def test_state_write_requires_explicit_flag(self):
        client = _rows()

        result = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            write_state=True,
            now=AFTER_CLOSE,
        )

        self.assertEqual(result["read behavior"], "STATE_WRITE_AUTHORIZED")
        self.assertFalse(result["NO STATE WRITE"])
        self.assertTrue(client.writes)
        self.assertTrue(all(write[0] == "策略决策状态" for write in client.writes))

    def test_paper_track_is_explicit_and_isolated_from_production_state(self):
        client = _rows()

        result = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            paper_track=True,
            now=AFTER_CLOSE,
        )

        self.assertEqual(result["read behavior"], "READ_ONLY")
        self.assertTrue(result["NO STATE WRITE"])
        self.assertFalse(result["NO Sheets mutation"])
        self.assertTrue(result["paper_tracking"]["enabled"])
        self.assertTrue(result["paper_tracking"]["schema"]["headers"])
        self.assertTrue(client.writes)
        self.assertTrue(all(write[0] == "策略模拟账本" for write in client.writes))
        self.assertFalse(any(write[0] == "策略决策状态" for write in client.writes))

        write_count = len(client.writes)
        second = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            paper_track=True,
            now=AFTER_CLOSE,
        )
        self.assertEqual(len(client.writes), write_count)
        self.assertEqual(second["paper_tracking"]["result"]["created_plans"], [])

    def test_run_can_write_dashboard_without_changing_result_or_sheet_writes(self):
        client = _rows()

        with tempfile.TemporaryDirectory() as directory:
            result = run_production_daily_decision(
                client,
                as_of_date=T_DAY,
                preflight=False,
                now=AFTER_CLOSE,
                dashboard_output=directory,
            )

            self.assertEqual(result["read behavior"], "READ_ONLY")
            self.assertTrue(result["NO Sheets mutation"])
            self.assertEqual(client.writes, [])
            self.assertNotIn(
                "symbol_metadata",
                next(item for item in result["reports"] if item["市场"] == "CN")["universe"],
            )
            self.assertEqual(
                {path.name for path in Path(directory).glob("*.html")},
                {"latest.html", f"{T_DAY.isoformat()}.html"},
            )
            html = (Path(directory) / "latest.html").read_text(encoding="utf-8")
            self.assertIn("每日交易决策工作台", html)
            self.assertIn(">CN<", html)


if __name__ == "__main__":
    unittest.main()

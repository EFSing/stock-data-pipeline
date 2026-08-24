import unittest
from unittest.mock import patch

from scripts import run_setup03_replay as replay_script


def config() -> dict:
    return {
        "retry_count": "1",
        "retry_wait_seconds": "0",
        "setup_swing_lookback": "5",
        "setup_platform_window": "40",
        "setup_platform_tolerance_pct": "0",
        "setup_arm_proximity_pct": "0",
        "decision_swing_lookback": "5",
        "decision_atr_period": "14",
        "decision_atr_buffer": "0.5",
        "decision_max_chase_atr": "0.5",
        "decision_risk_capital": "1000",
    }


class ReplayWorkflowCoverageTests(unittest.TestCase):
    @patch("scripts.run_setup03_replay.SheetsClient")
    def test_zero_calculable_enabled_symbols_fails_after_writing_diagnostics(
        self, client_class
    ):
        client = client_class.return_value
        client.config.return_value = config()
        client.records.return_value = [
            {
                "启用": True,
                "统一代码": "TEST",
                "历史数据源": "Tencent",
                "市场": "US",
                "时区": "America/New_York",
                "收盘时间": "16:00",
            }
        ]

        with patch.object(replay_script, "_write_csv") as write_csv:
            with self.assertRaisesRegex(RuntimeError, "coverage is zero"):
                replay_script.main()

        self.assertEqual(write_csv.call_count, 3)
        skipped_rows = write_csv.call_args_list[1].args[1]
        self.assertEqual(
            skipped_rows[0]["原因"], "历史数据源Tencent不支持qfq"
        )
        event_call = write_csv.call_args_list[2]
        self.assertEqual(event_call.args[0], replay_script.EVENTS_PATH)
        self.assertEqual(event_call.args[1], [])
        self.assertIn("事件类型", event_call.args[2])
        self.assertIn("参数快照", event_call.args[2])

    def test_parameter_version_is_deterministic_and_snapshot_complete(self):
        setup = {"swing_lookback": 5, "platform_window": 40}
        decision = {"atr_period": 14, "atr_buffer": 0.5}

        first = replay_script._parameter_metadata(
            setup, decision, 1000.0, 51, 14, 14
        )
        second = replay_script._parameter_metadata(
            dict(reversed(list(setup.items()))),
            dict(reversed(list(decision.items()))),
            1000.0,
            51,
            14,
            14,
        )

        self.assertEqual(first, second)
        snapshot, version = first
        self.assertIn('"risk_capital":1000.0', snapshot)
        self.assertIn('"replay_quality"', snapshot)
        self.assertTrue(version.startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()

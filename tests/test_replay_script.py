import unittest
from datetime import date
from unittest.mock import patch

from core import Quote
from research.replay_input import build_input_manifest
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

        empty_manifest = build_input_manifest({})
        with (
            patch.object(replay_script, "_write_csv") as write_csv,
            patch.object(replay_script, "write_input_manifest"),
            patch.object(
                replay_script, "write_frozen_input", return_value=empty_manifest
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "coverage is zero"):
                replay_script.main()

        self.assertEqual(write_csv.call_count, 9)
        skipped_rows = write_csv.call_args_list[1].args[1]
        self.assertEqual(
            skipped_rows[0]["原因"], "历史数据源Tencent不支持qfq"
        )
        event_call = write_csv.call_args_list[2]
        self.assertEqual(event_call.args[0], replay_script.EVENTS_PATH)
        self.assertEqual(event_call.args[1], [])
        self.assertIn("事件类型", event_call.args[2])
        self.assertIn("参数快照", event_call.args[2])
        self.assertIn("confirmed_date", event_call.args[2])
        outcome_call = write_csv.call_args_list[3]
        self.assertEqual(outcome_call.args[0], replay_script.OUTCOMES_PATH)
        self.assertIn("actual_entry", outcome_call.args[2])
        sensitivity_call = write_csv.call_args_list[4]
        self.assertEqual(sensitivity_call.args[0], replay_script.SENSITIVITY_PATH)
        self.assertIn("setup_swing_lookback", sensitivity_call.args[2])
        self.assertIn("confirmed_count", sensitivity_call.args[2])
        self.assertIn("entry_allowed_count", sensitivity_call.args[2])
        self.assertIn("signal_not_entry_allowed_count", sensitivity_call.args[2])
        self.assertIn("skip_no_t1_count", sensitivity_call.args[2])
        self.assertIn("skip_gap_below_breakout_count", sensitivity_call.args[2])
        self.assertIn("skip_gap_above_entry_zone_count", sensitivity_call.args[2])
        self.assertIn("executed_count", sensitivity_call.args[2])
        diagnostics_call = write_csv.call_args_list[5]
        self.assertEqual(
            diagnostics_call.args[0], replay_script.DECISION_GATE_DIAGNOSTICS_PATH
        )
        self.assertIn("decision_gate_reason", diagnostics_call.args[2])
        self.assertIn("T1_RR", diagnostics_call.args[2])
        summary_call = write_csv.call_args_list[6]
        self.assertEqual(
            summary_call.args[0], replay_script.DECISION_GATE_SUMMARY_PATH
        )
        self.assertIn("RR_BELOW_MINIMUM_count", summary_call.args[2])
        self.assertIn("RR_BELOW_MINIMUM_ratio", summary_call.args[2])
        manifest_call = write_csv.call_args_list[7]
        self.assertEqual(manifest_call.args[0], replay_script.INPUT_MANIFEST_CSV_PATH)
        self.assertIn("aggregate_hash", manifest_call.args[2])
        comparison_call = write_csv.call_args_list[8]
        self.assertEqual(comparison_call.args[0], replay_script.INPUT_COMPARISON_PATH)
        self.assertIn("status", comparison_call.args[2])

    @patch("scripts.run_setup03_replay.SheetsClient")
    def test_frozen_input_mode_does_not_fetch_live_history(self, client_class):
        frozen_quote = Quote(
            "TEST",
            "Test",
            "US",
            date(2026, 1, 2),
            "fixture",
            10.0,
            11.0,
            9.0,
            10.5,
            10.0,
            0.05,
            1000.0,
            10000.0,
            0.1,
            "USD",
        )
        frozen_quotes = {"TEST": [frozen_quote]}
        manifest = build_input_manifest(frozen_quotes)
        client = client_class.return_value
        client.config.return_value = {
            **config(),
            "replay_min_history_rows": "1",
        }
        client.records.return_value = [
            {
                "启用": True,
                "统一代码": "TEST",
                "名称": "Test",
                "历史数据源": "yfinance",
                "市场": "US",
                "时区": "America/New_York",
                "收盘时间": "16:00",
            }
        ]

        with (
            patch.object(
                replay_script,
                "read_frozen_input",
                return_value=(frozen_quotes, manifest),
            ),
            patch.object(replay_script, "fetch_with_retry") as fetch,
            patch.object(replay_script, "_write_csv"),
            patch.object(replay_script, "write_input_manifest"),
            patch.object(
                replay_script, "write_frozen_input", return_value=manifest
            ),
        ):
            replay_script.main(["--frozen-input", "frozen.jsonl.gz"])

        fetch.assert_not_called()

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

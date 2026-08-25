import unittest
from datetime import date
from unittest.mock import patch

from core import Quote
from research.backtest.setup03 import Setup03ResearchReport
from research.platform_tolerance_sensitivity import (
    PLATFORM_TOLERANCES,
    platform_tolerance_sensitivity_artifacts,
    render_platform_tolerance_report,
)
from research.replay_input import build_input_manifest
from trading.models import SetupState, Trend
from trading.replay import ReplayDay, SymbolReplayReport
from trading.setup import SetupDiagnostics, SetupGateReason


def quote():
    return Quote(
        "TEST", "Test", "US", date(2026, 1, 2), "fixture",
        10.0, 10.5, 9.5, 10.0, 9.8, 0.2, 1000, 10000, 0.1, "USD",
    )


class PlatformToleranceSensitivityTests(unittest.TestCase):
    def test_fixed_sequence_and_zero_event_conservation(self):
        quotes = {"TEST": [quote()]}
        manifest = build_input_manifest(quotes)

        def replay(_quotes, _risk, setup, _decision):
            tolerance = setup["platform_tolerance_pct"]
            detected = tolerance > 0
            diagnostics = SetupDiagnostics(
                SetupGateReason.WATCH_BELOW_ARM_THRESHOLD if detected
                else SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE,
                SetupState.WATCH if detected else SetupState.NONE,
                0,
                high_count=2,
                low_count=2,
                trend=Trend.RANGE,
                high_span=0.004,
                low_span=0.003,
                platform_tolerance_pct=tolerance,
                platform_search_evaluated=True,
                platform_detected_this_bar=detected,
            )
            day = ReplayDay(
                "TEST", date(2026, 1, 2), diagnostics.setup_state,
                setup_diagnostics=diagnostics,
            )
            return SymbolReplayReport(
                "TEST", "US", (day,), state_day_counts={diagnostics.setup_state: 1}
            )

        def research(report, _quotes):
            return Setup03ResearchReport(report.symbol, report.market, 0, ())

        with (
            patch("research.platform_tolerance_sensitivity.validate_phase5e_baseline"),
            patch("research.platform_tolerance_sensitivity.replay_setup03_history", side_effect=replay),
            patch("research.platform_tolerance_sensitivity.research_trade_outcomes", side_effect=research),
        ):
            artifacts = platform_tolerance_sensitivity_artifacts(
                quotes,
                1000.0,
                {"swing_lookback": 5, "platform_window": 40,
                 "platform_tolerance_pct": 0.0, "arm_proximity_pct": 0.0},
                {"swing_lookback": 5, "atr_period": 14,
                 "atr_buffer": 0.5, "max_chase_atr": 0.5},
                manifest,
                "sha256:test",
            )

        self.assertEqual(
            tuple(row["platform_tolerance_pct"] for row in artifacts.funnel_rows),
            PLATFORM_TOLERANCES,
        )
        self.assertEqual(artifacts.funnel_rows[0]["平台识别数量"], 0)
        self.assertEqual(artifacts.funnel_rows[1]["平台识别数量"], 1)
        self.assertEqual(
            len(artifacts.confirmation_reason_rows),
            len(PLATFORM_TOLERANCES) * len(SetupGateReason),
        )
        self.assertEqual(len(artifacts.forward_rows), len(PLATFORM_TOLERANCES) * 3)
        report = render_platform_tolerance_report(artifacts, manifest.aggregate_hash)
        self.assertIn("配置默认值是否表达预期平台语义", report)
        self.assertIn("不排名", report)

    def test_rejects_non_frozen_tolerance_sequence(self):
        quotes = {"TEST": [quote()]}
        with patch("research.platform_tolerance_sensitivity.validate_phase5e_baseline"):
            with self.assertRaisesRegex(ValueError, "sequence is frozen"):
                platform_tolerance_sensitivity_artifacts(
                    quotes, 1000.0, {}, {}, build_input_manifest(quotes),
                    "sha256:test", tolerances=(0.0, 0.01),
                )


if __name__ == "__main__":
    unittest.main()

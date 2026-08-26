import unittest
from datetime import date, timedelta
from unittest.mock import patch

from core import Quote
from research.platform_structure_calibration import (
    CALIBRATION_TOLERANCES,
    platform_structure_calibration_artifacts,
    render_platform_structure_report,
)
from research.replay_input import build_input_manifest
from trading.models import Setup, SetupState, Trend
from trading.replay import ReplayDay, ReplayEvent, SymbolReplayReport
from trading.setup import SetupDiagnostics, SetupGateReason


def quotes():
    start = date(2026, 1, 1)
    return [
        Quote(
            "TEST", "Test", "US", start + timedelta(days=i), "fixture",
            100 + i, 102 + i, 99 + i, 101 + i, 100 + i,
            0.01, 1000, 100000, 0.1, "USD",
        )
        for i in range(30)
    ]


class PlatformStructureCalibrationTests(unittest.TestCase):
    def test_market_conservation_normalization_and_adjacent_drift(self):
        frozen = {"TEST": quotes()}
        manifest = build_input_manifest(frozen)

        def replay(_quotes, _risk, setup_parameters, _decision_parameters):
            tolerance = setup_parameters["platform_tolerance_pct"]
            event_index = 20 if tolerance < 0.04 else 21
            days = []
            for i, quote in enumerate(_quotes):
                detected = i == event_index
                diagnostics = SetupDiagnostics(
                    SetupGateReason.CONFIRMED if detected
                    else SetupGateReason.INSUFFICIENT_HIGH_SWINGS,
                    SetupState.CONFIRMED if detected else SetupState.NONE,
                    i,
                    high_count=3 if detected else 0,
                    low_count=2 if detected else 0,
                    trend=Trend.RANGE if detected else None,
                    high_span=0.02 if detected else None,
                    low_span=0.01 if detected else None,
                    platform_tolerance_pct=tolerance,
                    close=float(quote.close),
                    breakout_price=110.0 if detected else None,
                    structural_invalidation=100.0 if detected else None,
                    platform_search_evaluated=detected,
                    platform_detected_this_bar=detected,
                )
                days.append(ReplayDay(
                    "TEST", quote.trade_date, diagnostics.setup_state,
                    confirmed_event=detected, setup_diagnostics=diagnostics,
                ))
            event_quote = _quotes[event_index]
            event = ReplayEvent(
                "TEST", event_quote.trade_date, SetupState.CONFIRMED,
                Setup("SETUP_03", SetupState.CONFIRMED, 110.0, 100.0,
                      event_index - 2, event_index, event_index),
                confirmed_date=event_quote.trade_date,
            )
            return SymbolReplayReport(
                "TEST", "US", tuple(days), events=(event,),
                confirmed_event_dates=(event_quote.trade_date,),
            )

        with (
            patch("research.platform_structure_calibration.validate_phase5e_baseline"),
            patch("research.platform_structure_calibration.replay_setup03_history", side_effect=replay),
        ):
            artifacts = platform_structure_calibration_artifacts(
                frozen, 1000.0,
                {"platform_tolerance_pct": 0.0},
                {"atr_period": 14}, manifest, "sha256:test",
            )

        all_rows = [row for row in artifacts.market_rows if row["市场"] == "ALL"]
        self.assertEqual(len(all_rows), len(CALIBRATION_TOLERANCES))
        self.assertTrue(all(row["bars"] == 30 for row in all_rows))
        for tolerance in CALIBRATION_TOLERANCES:
            rows = [row for row in artifacts.market_rows if row["platform_tolerance_pct"] == tolerance]
            self.assertEqual(sum(row["bars"] for row in rows if row["市场"] != "ALL"), rows[0]["bars"])
        self.assertAlmostEqual(all_rows[0]["platform_per_1000_bars"], 1000 / 30)
        self.assertEqual(all_rows[0]["swing_high_count_median"], 3)
        self.assertEqual(all_rows[0]["span_asymmetry_median"], 0.01)
        self.assertIsNotNone(all_rows[0]["platform_width_ATR_median"])
        drift = next(
            row for row in artifacts.stability_rows
            if row["市场"] == "ALL"
            and row["前一tolerance"] == 0.035
            and row["当前tolerance"] == 0.04
        )
        self.assertEqual(drift["CONFIRMED_Jaccard"], 0.0)
        self.assertEqual(drift["日期匹配事件"], 1)
        self.assertEqual(drift["日期漂移_median_days"], 1)
        self.assertEqual(
            sum(row["状态"] == "DATE_DRIFT" for row in artifacts.event_change_rows), 1
        )
        report = render_platform_structure_report(artifacts, manifest.aggregate_hash)
        self.assertIn("不选择 production tolerance", report)
        self.assertIn("Wilder ATR", report)

    def test_rejects_non_frozen_sequence(self):
        frozen = {"TEST": quotes()}
        with patch("research.platform_structure_calibration.validate_phase5e_baseline"):
            with self.assertRaisesRegex(ValueError, "sequence is frozen"):
                platform_structure_calibration_artifacts(
                    frozen, 1000.0, {}, {}, build_input_manifest(frozen),
                    "sha256:test", tolerances=(0.03,),
                )


if __name__ == "__main__":
    unittest.main()

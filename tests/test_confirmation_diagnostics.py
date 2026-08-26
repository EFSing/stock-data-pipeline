import unittest
from datetime import date, timedelta

from core import Quote
from research.confirmation_diagnostics import confirmation_gate_artifacts
from trading.models import SetupState, SwingKind, SwingPoint
from trading.replay import replay_setup03_history
from trading.setup import (
    SetupGateReason,
    detect_platform_breakout,
    detect_platform_breakout_with_diagnostics,
)


def quotes(count: int = 6) -> list[Quote]:
    return [
        Quote(
            symbol="T",
            name="test",
            market="US",
            trade_date=date(2026, 1, 1) + timedelta(days=index),
            source="x",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            preclose=None,
            pct_change=None,
            volume=1.0,
            amount=None,
            turnover_rate=None,
            currency="USD",
        )
        for index in range(count)
    ]


class ProductionSetupDiagnosticsTests(unittest.TestCase):
    def test_compatibility_api_and_diagnostic_api_return_identical_setup(self):
        series = quotes()
        production = detect_platform_breakout(series, swing_lookback=2)
        calculated = detect_platform_breakout_with_diagnostics(
            series, swing_lookback=2
        )

        self.assertEqual(production, calculated.setup)
        self.assertEqual(
            calculated.diagnostics.reason,
            SetupGateReason.NO_NEW_CONFIRMED_SWING,
        )

    def test_terminal_priority_is_unique_but_auxiliary_failures_are_retained(self):
        series = quotes(5)
        last_date = series[-1].trade_date
        swings = [
            SwingPoint(SwingKind.HIGH, 101.0, 0, series[0].trade_date, 4, last_date),
            SwingPoint(SwingKind.HIGH, 102.0, 1, series[1].trade_date, 4, last_date),
            SwingPoint(SwingKind.LOW, 99.0, 2, series[2].trade_date, 4, last_date),
            SwingPoint(SwingKind.LOW, 98.0, 3, series[3].trade_date, 4, last_date),
        ]
        calculated = detect_platform_breakout_with_diagnostics(
            series,
            platform_window=20,
            platform_tolerance_pct=0.0,
            swings=swings,
        )

        self.assertEqual(
            calculated.diagnostics.reason,
            SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE,
        )
        self.assertIn(
            SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE,
            calculated.diagnostics.auxiliary_failed_conditions,
        )


class ConfirmationArtifactTests(unittest.TestCase):
    def test_terminal_reasons_conserve_all_replay_bars_and_near_miss_is_descriptive(self):
        report = replay_setup03_history(
            quotes(12),
            1000.0,
            setup_parameters={"swing_lookback": 2},
        )
        artifacts = confirmation_gate_artifacts({"T": report})

        self.assertEqual(
            sum(int(row["数量"]) for row in artifacts.reason_rows),
            12,
        )
        self.assertEqual(len(artifacts.detail_rows), 12)
        self.assertTrue(artifacts.gate_rows)
        self.assertTrue(
            all("terminal_reason" in row for row in artifacts.detail_rows)
        )


if __name__ == "__main__":
    unittest.main()

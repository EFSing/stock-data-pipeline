import unittest
from dataclasses import replace
from datetime import date, timedelta

from core import Quote
from research.backtest.setup03 import research_trade_outcomes
from research.frozen_validation import (
    PHASE5E_DATASET_HASH,
    PHASE5E_PARAMETER_VERSION,
    frozen_validation_artifacts,
    render_frozen_validation_report,
    validate_phase5e_baseline,
)
from research.replay_input import build_input_manifest
from trading.models import Decision, DecisionAction, EntryPlan, Setup, SetupState
from trading.replay import ReplayEvent, SymbolReplayReport


def quote(index: int, *, close: float | None = None) -> Quote:
    close_price = float(100 + index if close is None else close)
    return Quote(
        symbol="T",
        name="测试标的",
        market="US",
        trade_date=date(2025, 1, 1) + timedelta(days=index),
        source="yfinance",
        open=close_price,
        high=close_price + 1.0,
        low=close_price - 1.0,
        close=close_price,
        preclose=None,
        pct_change=None,
        volume=100.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def entry_allowed_event() -> ReplayEvent:
    setup = Setup(
        "SETUP_03",
        SetupState.CONFIRMED,
        breakout_price=99.0,
        structural_invalidation=90.0,
        detected_index=0,
        state_entered_index=0,
        confirmed_index=0,
    )
    entry = EntryPlan(100.0, 99.0, 101.0, 99.0, 99.0, "confirmed")
    decision = Decision(
        DecisionAction.ENTRY_ALLOWED,
        entry,
        90.0,
        95.0,
        (130.0,),
        None,
        None,
    )
    signal_date = date(2025, 1, 1)
    return ReplayEvent(
        symbol="T",
        trade_date=signal_date,
        event_type=SetupState.CONFIRMED,
        setup=setup,
        decision=decision,
        signal_date=signal_date,
        confirmed_date=signal_date,
        signal_close=100.0,
        signal_atr=4.0,
    )


def fixed_manifest(quotes: list[Quote]):
    return replace(
        build_input_manifest({"T": quotes}),
        aggregate_hash=PHASE5E_DATASET_HASH,
    )


class FrozenValidationTests(unittest.TestCase):
    def test_fixed_baseline_rejects_dataset_or_parameter_drift(self):
        quotes = [quote(0)]
        manifest = fixed_manifest(quotes)

        validate_phase5e_baseline(manifest, PHASE5E_PARAMETER_VERSION)
        with self.assertRaisesRegex(ValueError, "dataset hash mismatch"):
            validate_phase5e_baseline(
                replace(manifest, aggregate_hash="sha256:changed"),
                PHASE5E_PARAMETER_VERSION,
            )
        with self.assertRaisesRegex(ValueError, "parameter version mismatch"):
            validate_phase5e_baseline(manifest, "sha256:changed")

    def test_zero_signal_dataset_reports_not_assessable_without_optimization(self):
        quotes = [quote(index) for index in range(25)]
        report = SymbolReplayReport(
            "T",
            "US",
            (),
            state_day_counts={SetupState.NONE: len(quotes)},
        )
        research = research_trade_outcomes(report, quotes)

        artifacts = frozen_validation_artifacts(
            {"T": report},
            {"T": research},
            {"T": quotes},
            fixed_manifest(quotes),
            PHASE5E_PARAMETER_VERSION,
        )

        summary = artifacts.summary_rows[0]
        self.assertEqual(summary["CONFIRMED"], 0)
        self.assertEqual(summary["ENTRY_ALLOWED"], 0)
        self.assertEqual(summary["EXECUTED"], 0)
        self.assertIn("无法评估", summary["初步Edge结论"])
        self.assertEqual(len(artifacts.forward_summary_rows), 3)
        self.assertTrue(
            all(
                row["可观测样本数"] == 0
                for row in artifacts.forward_summary_rows
            )
        )
        self.assertTrue(
            all(
                row["判断"] == "无法评估（该阶段样本为0）"
                for row in artifacts.concentration_rows
            )
        )
        report_markdown = render_frozen_validation_report(artifacts)
        self.assertIn("描述性诊断", report_markdown)
        self.assertIn("不进行参数优化", report_markdown)
        self.assertIn("MAE、MFE 均不可评估", report_markdown)

    def test_signal_paths_and_stage_distribution_use_production_event_contract(self):
        quotes = [quote(index) for index in range(25)]
        event = entry_allowed_event()
        report = SymbolReplayReport(
            "T",
            "US",
            (),
            events=(event,),
            state_day_counts={SetupState.CONFIRMED: 1},
        )
        research = research_trade_outcomes(report, quotes)
        self.assertEqual(research.executed_count, 1)

        artifacts = frozen_validation_artifacts(
            {"T": report},
            {"T": research},
            {"T": quotes},
            fixed_manifest(quotes),
            PHASE5E_PARAMETER_VERSION,
        )

        summary = artifacts.summary_rows[0]
        self.assertEqual(
            (summary["CONFIRMED"], summary["ENTRY_ALLOWED"], summary["EXECUTED"]),
            (1, 1, 1),
        )
        reason = next(
            row
            for row in artifacts.decision_reason_rows
            if row["原因代码"] == "ENTRY_ALLOWED"
        )
        self.assertEqual(reason["数量"], 1)
        path = artifacts.signal_path_rows[0]
        self.assertAlmostEqual(path["5D_forward_return"], 0.05)
        self.assertAlmostEqual(path["5D_MFE"], 0.06)
        self.assertAlmostEqual(path["5D_MAE"], 0.0)
        symbol_distribution = next(
            row
            for row in artifacts.distribution_rows
            if row["维度"] == "标的" and row["分组"] == "T"
        )
        self.assertEqual(symbol_distribution["CONFIRMED"], 1)
        self.assertEqual(symbol_distribution["ENTRY_ALLOWED"], 1)
        self.assertEqual(symbol_distribution["EXECUTED"], 1)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from core import Quote
from trading.fibonacci import project_extension
from trading.models import (
    DecisionAction,
    Setup01Evaluation,
    SetupState,
    SwingKind,
    SwingPoint,
)
from trading.setup01_decision import (
    EXECUTED,
    SETUP01_DECISION_PROTOCOL_VERSION,
    SKIP_BELOW_INVALIDATION,
    SKIP_GAP_ABOVE_ENTRY_ZONE,
    SKIP_GAP_BELOW_CONFIRMATION,
    Setup01DecisionGateReason,
    evaluate_setup01_decision,
    evaluate_setup01_decision_stream,
    execute_setup01_t1_open,
    setup01_decision_to_dict,
)
from trading.setup01_replay import (
    Setup01ReplayDay,
    Setup01ReplayEvent,
    Setup01ReplayReport,
)


def _quote(day: date, close: float, opening: float | None = None) -> Quote:
    opening = close if opening is None else opening
    high = max(opening, close) + 1.0
    low = min(opening, close) - 1.0
    return Quote(
        symbol="SETUP01.DECISION",
        name="Setup 01 decision synthetic",
        market="US",
        trade_date=day,
        source="test",
        open=opening,
        high=high,
        low=low,
        close=close,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _fixture(
    *,
    wave2_low: float = 108.0,
    t_close: float = 110.5,
    t1_open: float | None = 110.75,
    short_history: bool = False,
) -> tuple[Setup01ReplayEvent, list[Quote]]:
    start = date(2026, 3, 1)
    count = 10 if short_history else 21
    quotes = [_quote(start + timedelta(days=index), 100.0 + index * 0.15) for index in range(count)]
    t_day = quotes[-1].trade_date
    quotes[-1] = _quote(t_day, t_close)
    if t1_open is not None:
        quotes.append(_quote(t_day + timedelta(days=1), 110.0, opening=t1_open))

    origin = SwingPoint(SwingKind.LOW, 100.0, 5, start + timedelta(days=5), 5, start + timedelta(days=5))
    peak = SwingPoint(SwingKind.HIGH, 110.0, 10, start + timedelta(days=10), 10, start + timedelta(days=10))
    low = SwingPoint(SwingKind.LOW, wave2_low, 15, start + timedelta(days=15), 15, start + timedelta(days=15))
    snapshot = Setup01Evaluation(
        setup_type="SETUP_01",
        protocol_version="SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1",
        state=SetupState.CONFIRMED,
        as_of_date=t_day,
        wave1_origin=origin,
        wave1_peak=peak,
        wave2_low=low,
        fib_retracement_ratio=0.2,
        fib_retracement_region="0.382-0.5",
        confirmation_level=110.0,
        structural_invalidation=wave2_low,
        wave_scenario_invalidation=100.0,
        wave1_origin_confirmed_date=origin.confirmed_date,
        wave1_peak_confirmed_date=peak.confirmed_date,
        wave2_low_confirmed_date=low.confirmed_date,
        state_entered_index=len(quotes) - (2 if t1_open is not None else 1),
        state_entered_date=t_day,
        confirmed_index=len(quotes) - (2 if t1_open is not None else 1),
        confirmed_date=t_day,
        failed_index=None,
        failed_date=None,
        primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
        alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
        reason="synthetic first CONFIRMED event",
        terminal_event_type=SetupState.CONFIRMED,
        terminal_event_date=t_day,
        is_new_confirmed_event_as_of=True,
        is_new_failed_event_as_of=False,
        is_live_preconfirmation_candidate=False,
        lifecycle_index=1,
    )
    event = Setup01ReplayEvent(
        event_identity=f"SETUP01.DECISION|SETUP_01|{t_day.isoformat()}|CONFIRMED|lifecycle=1",
        symbol="SETUP01.DECISION",
        trade_date=t_day,
        event_type=SetupState.CONFIRMED,
        setup01=snapshot,
        market="US",
    )
    return event, quotes


class Setup01DecisionTests(unittest.TestCase):
    def test_wave3_projection_helper_is_generic_and_uses_supplied_range(self):
        self.assertEqual(project_extension(108.0, 100.0, 110.0, 1.618), 124.18)
        with self.assertRaises(ValueError):
            project_extension(108.0, 110.0, 100.0, 1.618)

    def test_independent_module_does_not_import_platform_breakout_decision(self):
        from pathlib import Path

        source = Path("trading/setup01_decision.py").read_text(encoding="utf-8")
        self.assertNotIn("decide_platform_breakout", source)

    def test_confirmed_event_builds_target_first_then_rr_and_explicit_risk_input(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        self.assertEqual(decision.protocol_version, SETUP01_DECISION_PROTOCOL_VERSION)
        self.assertEqual(decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertEqual(decision.gate_reason, Setup01DecisionGateReason.ENTRY_ALLOWED)
        self.assertEqual(decision.planned_entry, 110.5)
        self.assertEqual(decision.entry_zone_low, 110.0)
        self.assertAlmostEqual(
            decision.entry_zone_high,
            110.0 + 0.5 * decision.atr14,
        )
        self.assertAlmostEqual(
            decision.execution_stop,
            108.0 - 0.5 * decision.atr14,
        )
        self.assertTrue(decision.target_candidates)
        self.assertEqual(decision.targets, tuple(item.price for item in decision.target_candidates[:3]))
        self.assertEqual(decision.position_size_required_input, "risk_capital")
        self.assertIsNone(decision.position_size)
        projection = setup01_decision_to_dict(decision)
        self.assertEqual(projection["T1"], decision.targets[0])
        self.assertIn("source", projection["target_candidates"][0])
        self.assertIn("reason", projection["target_candidates"][0])

    def test_entry_zone_and_gate_reasons_are_not_widened(self):
        event, quotes = _fixture(t_close=112.5)
        decision = evaluate_setup01_decision(event, quotes)
        self.assertEqual(decision.action, DecisionAction.NO_TRADE)
        self.assertEqual(decision.gate_reason, Setup01DecisionGateReason.ABOVE_ENTRY_ZONE)

        event, quotes = _fixture(short_history=True)
        decision = evaluate_setup01_decision(event, quotes)
        self.assertEqual(decision.gate_reason, Setup01DecisionGateReason.ATR_UNAVAILABLE)

    def test_no_valid_target_and_rr_below_minimum_are_explicit(self):
        event, quotes = _fixture()
        with patch("trading.setup01_decision.EXTENSION_RATIOS", {}), patch(
            "trading.setup01_decision.find_swings", return_value=[]
        ):
            decision = evaluate_setup01_decision(event, quotes)
        self.assertEqual(decision.gate_reason, Setup01DecisionGateReason.NO_VALID_TARGET)

        event, quotes = _fixture(wave2_low=101.0)
        decision = evaluate_setup01_decision(event, quotes)
        self.assertEqual(decision.gate_reason, Setup01DecisionGateReason.RR_BELOW_MINIMUM)
        # Target was independently generated before the R/R gate.
        self.assertTrue(decision.targets)
        self.assertIsNotNone(decision.rr)

        invalid_event = replace(event, setup01=replace(event.setup01, structural_invalidation=None))
        decision = evaluate_setup01_decision(invalid_event, quotes)
        self.assertEqual(decision.gate_reason, Setup01DecisionGateReason.INVALID_STRUCTURE)

    def test_t1_execution_uses_first_next_open_only_and_has_three_skip_reasons(self):
        event, quotes = _fixture(t1_open=109.0)
        decision = evaluate_setup01_decision(event, quotes)
        execution = execute_setup01_t1_open(decision, quotes)
        self.assertEqual(execution.outcome, SKIP_GAP_BELOW_CONFIRMATION)
        self.assertEqual(execution.execution_date, event.trade_date + timedelta(days=1))

        event, quotes = _fixture(t1_open=114.0)
        decision = evaluate_setup01_decision(event, quotes)
        self.assertEqual(execute_setup01_t1_open(decision, quotes).outcome, SKIP_GAP_ABOVE_ENTRY_ZONE)

        event, quotes = _fixture(wave2_low=108.0, t1_open=107.0)
        decision = evaluate_setup01_decision(event, quotes)
        self.assertEqual(execute_setup01_t1_open(decision, quotes).outcome, SKIP_BELOW_INVALIDATION)

        event, quotes = _fixture(t1_open=110.75)
        decision = evaluate_setup01_decision(event, quotes)
        execution = execute_setup01_t1_open(decision, quotes)
        self.assertEqual(execution.outcome, EXECUTED)
        self.assertEqual(execution.actual_entry, 110.75)

        no_t1_event, no_t1_quotes = _fixture(t1_open=None)
        no_t1_decision = evaluate_setup01_decision(no_t1_event, no_t1_quotes)
        self.assertEqual(execute_setup01_t1_open(no_t1_decision, no_t1_quotes).outcome, "SKIP_NO_T1_BAR")

    def test_t1_high_low_close_and_same_bar_open_do_not_change_execution(self):
        event, quotes = _fixture(t1_open=110.75)
        decision = evaluate_setup01_decision(event, quotes)
        baseline = execute_setup01_t1_open(decision, quotes)
        t1 = quotes[-1]
        altered_t1 = replace(t1, high=1000.0, low=1.0, close=999.0)
        altered = execute_setup01_t1_open(decision, [*quotes[:-1], altered_t1])
        self.assertEqual(baseline, altered)
        self.assertEqual(baseline.execution_date, event.trade_date + timedelta(days=1))

    def test_event_identity_is_exactly_once_and_historical_confirmed_is_rejected(self):
        event, quotes = _fixture()
        stream = evaluate_setup01_decision_stream(
            [event, event], {event.symbol: quotes}
        )
        self.assertEqual(len(stream.decisions), 1)
        self.assertEqual(len(stream.executions), 1)
        self.assertEqual(stream.duplicate_event_count, 1)

        historical = replace(
            event,
            setup01=replace(
                event.setup01,
                is_new_confirmed_event_as_of=False,
                terminal_event_date=event.trade_date - timedelta(days=10),
            ),
        )
        rejected = evaluate_setup01_decision_stream(
            [historical], {event.symbol: quotes}
        )
        self.assertEqual(len(rejected.decisions), 0)
        self.assertEqual(rejected.ignored_non_confirmed_event_count, 1)

    def test_projection_is_json_ready_and_does_not_read_future_t1_fields(self):
        event, quotes = _fixture()
        decision = evaluate_setup01_decision(event, quotes)
        json.dumps(setup01_decision_to_dict(decision), ensure_ascii=False)
        self.assertEqual(decision.trade_date, event.trade_date)
        self.assertEqual(decision.planned_entry, quotes[-2].close)

    def test_real_holdings_shadow_does_not_redecide_historical_terminal_or_live_context(self):
        from scripts.run_setup01_decision_shadow import run_setup01_decision_shadow

        event, quotes = _fixture()
        as_of = quotes[-1].trade_date
        historical = replace(
            event.setup01,
            as_of_date=as_of,
            state=SetupState.CONFIRMED,
            confirmed_date=as_of - timedelta(days=10),
            terminal_event_type=SetupState.CONFIRMED,
            terminal_event_date=as_of - timedelta(days=10),
            is_new_confirmed_event_as_of=False,
            is_new_failed_event_as_of=False,
            is_live_preconfirmation_candidate=False,
        )
        live = replace(
            event.setup01,
            as_of_date=as_of,
            state=SetupState.ARMED,
            confirmed_date=None,
            terminal_event_type=None,
            terminal_event_date=None,
            is_new_confirmed_event_as_of=False,
            is_new_failed_event_as_of=False,
            is_live_preconfirmation_candidate=True,
        )
        reports = {
            "HISTORICAL": Setup01ReplayReport(
                symbol="HISTORICAL",
                market="US",
                days=(Setup01ReplayDay("HISTORICAL", as_of, historical),),
                events=(),
            ),
            "LIVE": Setup01ReplayReport(
                symbol="LIVE",
                market="US",
                days=(Setup01ReplayDay("LIVE", as_of, live),),
                events=(),
            ),
        }

        class Client:
            def config(self):
                return {"history_days": "100", "retry_count": "1", "retry_wait_seconds": "0"}

            def records(self, sheet_name):
                if sheet_name == "自选清单":
                    return [
                        {
                            "启用": "TRUE",
                            "市场": "US",
                            "统一代码": symbol,
                            "名称": symbol,
                            "历史数据源": "yfinance",
                            "时区": "America/New_York",
                            "收盘时间": "16:00",
                        }
                        for symbol in reports
                    ]
                raise AssertionError(f"unexpected sheet read: {sheet_name}")

        def fetch_history(source, watch, adjust, start, end, retries, wait):
            self.assertEqual((source, adjust), ("yfinance", "qfq"))
            return [replace(quote, symbol=watch["统一代码"]) for quote in quotes]

        def report_for_symbol(symbol_quotes, **kwargs):
            return reports[symbol_quotes[0].symbol]

        with tempfile.TemporaryDirectory() as directory, patch(
            "main.wanted_markets_for_group", return_value={"US"}
        ), patch(
            "scripts.run_setup01_decision_shadow.latest_completed_market_session",
            return_value=as_of,
        ), patch(
            "scripts.run_setup01_decision_shadow.ordinary_calendar_freshness_guard",
            return_value=as_of - timedelta(days=30),
        ), patch(
            "scripts.run_setup01_decision_shadow.replay_setup01_history",
            side_effect=report_for_symbol,
        ):
            summary = run_setup01_decision_shadow(
                client=Client(),
                fetched_at=datetime(2026, 3, 24, 22, 0, tzinfo=timezone.utc),
                fetch_history=fetch_history,
                output_dir=directory,
            )
            report = json.loads(
                Path(directory, "setup01_decision_shadow_report.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["decision_generated"], 0)
        self.assertEqual(summary["entry_allowed"], 0)
        by_symbol = {row["统一代码"]: row for row in summary["rows"]}
        self.assertEqual(by_symbol["HISTORICAL"]["shadow_classification"], "HISTORICAL_TERMINAL")
        self.assertFalse(by_symbol["HISTORICAL"]["new_confirmed_today"])
        self.assertFalse(by_symbol["HISTORICAL"]["decision_generated"])
        self.assertEqual(by_symbol["LIVE"]["shadow_classification"], "LIVE_PRECONFIRMATION_CANDIDATE")
        self.assertTrue(by_symbol["LIVE"]["live_candidate"])
        self.assertFalse(by_symbol["LIVE"]["decision_generated"])
        self.assertFalse(report["returns_accessed"])
        self.assertFalse(report["sheets_written"])


if __name__ == "__main__":
    unittest.main()

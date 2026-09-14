import json
from dataclasses import replace
from datetime import date, timedelta
import inspect
import unittest
from unittest.mock import patch

from core import Quote
from research.market_sessions import build_market_session_dates
from trading.fibonacci import project_extension
from trading.models import DecisionAction, RiskReward, SetupState, SwingKind, SwingPoint
from trading.setup02 import Setup02Evaluation
from trading.setup02_decision import (
    EXECUTED,
    SKIP_BELOW_INVALIDATION,
    SKIP_GAP_ABOVE_ENTRY_ZONE,
    SKIP_GAP_BELOW_CONFIRMATION,
    SKIP_NO_T1_BAR,
    SKIP_RR_BELOW_MINIMUM_AT_OPEN,
    SKIP_TARGET_UPSIDE_BELOW_MINIMUM,
    SETUP02_DECISION_PROTOCOL_VERSION,
    Setup02DecisionGateReason,
    Setup02TargetCandidate,
    evaluate_setup02_decision,
    evaluate_setup02_decision_stream,
    execute_setup02_t1_open,
    setup02_decision_to_dict,
    setup02_structure_geometry_audit,
    setup02_target_provenance_audit,
)
from trading.setup02_replay import Setup02ReplayEvent
from trading.risk import risk_reward as calculate_risk_reward


def _quote(
    symbol: str,
    day: date,
    close: float,
    opening: float | None = None,
    *,
    high: float | None = None,
    low: float | None = None,
) -> Quote:
    opening = close if opening is None else opening
    return Quote(
        symbol=symbol,
        name="Setup 02 decision synthetic",
        market="US",
        trade_date=day,
        source="controlled-test-fixture",
        open=opening,
        high=max(opening, close) + 1.0 if high is None else high,
        low=min(opening, close) - 1.0 if low is None else low,
        close=close,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _swing(kind: SwingKind, price: float, index: int, start: date) -> SwingPoint:
    pivot_date = start + timedelta(days=index)
    return SwingPoint(kind, price, index, pivot_date, index, pivot_date)


def _fixture(
    *,
    t_close: float = 120.5,
    t1_open: float | None = 120.5,
    wide: bool = False,
) -> tuple[Setup02ReplayEvent, list[Quote]]:
    symbol = "SETUP02.DECISION"
    start = date(2026, 3, 1)
    quotes: list[Quote] = []
    for index in range(21):
        day = start + timedelta(days=index)
        if wide:
            quotes.append(_quote(symbol, day, 100.0, high=130.0, low=70.0))
        else:
            quotes.append(_quote(symbol, day, 100.0, high=101.0, low=99.0))
    t_day = quotes[-1].trade_date
    if wide:
        quotes[-1] = _quote(symbol, t_day, t_close, high=150.0, low=70.0)
    else:
        quotes[-1] = _quote(symbol, t_day, t_close)
    if t1_open is not None:
        quotes.append(_quote(symbol, t_day + timedelta(days=1), 100.0, t1_open))

    low0 = _swing(SwingKind.LOW, 100.0, 5, start)
    high1 = _swing(SwingKind.HIGH, 110.0, 10, start)
    low2 = _swing(SwingKind.LOW, 108.0, 15, start)
    high3 = _swing(SwingKind.HIGH, 120.0, 18, start)
    snapshot = Setup02Evaluation(
        setup_type="SETUP_02",
        protocol_version="SETUP-02-WAVE3-CONTINUATION-2026-09-01-v1",
        state=SetupState.CONFIRMED,
        as_of_date=t_day,
        continuation_low0=low0,
        continuation_high1=high1,
        continuation_low2=low2,
        continuation_high3=high3,
        fib_retracement_ratio=0.5,
        fib_retracement_region="0.382-0.5",
        confirmation_level=120.0,
        structural_invalidation=108.0,
        state_entered_index=20,
        state_entered_date=t_day,
        confirmed_index=20,
        confirmed_date=t_day,
        failed_index=None,
        failed_date=None,
        primary_wave_scenario="WAVE_3_CONTINUATION_CANDIDATE",
        alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
        reason="synthetic first CONFIRMED event",
        terminal_event_type=SetupState.CONFIRMED,
        terminal_event_date=t_day,
        is_new_confirmed_event_as_of=True,
        is_new_failed_event_as_of=False,
        is_live_preconfirmation_candidate=False,
        lifecycle_index=1,
    )
    event = Setup02ReplayEvent(
        event_identity=f"{symbol}|SETUP_02|{t_day.isoformat()}|CONFIRMED|lifecycle=1",
        symbol=symbol,
        trade_date=t_day,
        event_type=SetupState.CONFIRMED,
        setup02=snapshot,
        market="US",
    )
    return event, quotes


def _sessions(quotes: list[Quote]) -> dict[str, tuple[date, ...]]:
    return build_market_session_dates({quotes[0].symbol: quotes})


class _OpenOnlyQuote:
    """T+1 object whose non-OPEN fields fail if the executor reads them."""

    symbol = "SETUP02.DECISION"
    market = "US"
    trade_date = date(2026, 3, 22)
    open = 140.5

    @property
    def high(self):
        raise AssertionError("T+1 high must not be consumed")

    @property
    def low(self):
        raise AssertionError("T+1 low must not be consumed")

    @property
    def close(self):
        raise AssertionError("T+1 close must not be consumed")


class Setup02DecisionTests(unittest.TestCase):
    def test_only_first_confirmed_is_consumed_and_historical_terminal_is_ignored(self):
        event, quotes = _fixture()
        historical = replace(
            event,
            event_identity="historical-confirmed",
            setup02=replace(
                event.setup02,
                is_new_confirmed_event_as_of=False,
                confirmed_date=event.trade_date - timedelta(days=5),
                terminal_event_date=event.trade_date - timedelta(days=5),
            ),
        )
        stream = evaluate_setup02_decision_stream(
            [event, event, historical], {event.symbol: quotes}
        )
        self.assertEqual(len(stream.decisions), 1)
        self.assertEqual(stream.duplicate_event_count, 1)
        self.assertEqual(stream.ignored_non_confirmed_event_count, 1)

    def test_atr_unavailable_is_fail_closed(self):
        event, quotes = _fixture()
        short = [*quotes[:10]]
        short[-1] = _quote(short[-1].symbol, short[-1].trade_date, 120.5)
        short_event = replace(event, trade_date=short[-1].trade_date)
        short_event = replace(
            short_event,
            setup02=replace(
                event.setup02,
                as_of_date=short[-1].trade_date,
                confirmed_date=short[-1].trade_date,
                terminal_event_date=short[-1].trade_date,
                continuation_low0=_swing(SwingKind.LOW, 100.0, 1, date(2026, 3, 1)),
                continuation_high1=_swing(SwingKind.HIGH, 110.0, 2, date(2026, 3, 1)),
                continuation_low2=_swing(SwingKind.LOW, 108.0, 3, date(2026, 3, 1)),
                continuation_high3=_swing(SwingKind.HIGH, 120.0, 4, date(2026, 3, 1)),
            ),
        )
        decision = evaluate_setup02_decision(short_event, short)
        self.assertEqual(decision.gate_reason, Setup02DecisionGateReason.ATR_UNAVAILABLE)
        self.assertTrue(decision.decision_calculable)

    def test_stale_confirmation_geometry_fails_closed_without_recomputing_invalidation(self):
        event, quotes = _fixture()
        malformed = replace(
            event,
            setup02=replace(
                event.setup02,
                structural_invalidation=121.0,
            ),
        )
        decision = evaluate_setup02_decision(malformed, quotes)
        self.assertEqual(
            decision.gate_reason,
            Setup02DecisionGateReason.STALE_CONFIRMATION_GEOMETRY,
        )
        self.assertEqual(decision.structural_invalidation, 121.0)
        self.assertEqual(decision.planned_entry, 120.5)
        self.assertIsNone(decision.execution_stop)

        audit = setup02_structure_geometry_audit(malformed, quotes)
        self.assertEqual(audit["classification"], "STALE_CONFIRMATION_GEOMETRY")
        self.assertIn(
            "structural_invalidation >= HIGH3",
            audit["exact_invariant_failure_reason"],
        )
        self.assertEqual(audit["LOW0"]["price"], 100.0)
        self.assertEqual(audit["HIGH1"]["price"], 110.0)
        self.assertEqual(audit["LOW2"]["price"], 108.0)
        self.assertEqual(audit["HIGH3"]["price"], 120.0)
        self.assertEqual(audit["t_close"], 120.5)

    def test_entry_zone_and_atr_stop_are_frozen(self):
        event, quotes = _fixture(t_close=130.0)
        decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(decision.gate_reason, Setup02DecisionGateReason.ABOVE_ENTRY_ZONE)
        self.assertEqual(decision.confirmation_level, 120.0)
        self.assertEqual(decision.structural_invalidation, 108.0)
        self.assertAlmostEqual(decision.entry_zone_low, 120.0)
        self.assertAlmostEqual(decision.entry_zone_high, 120.0 + 0.5 * decision.atr14)
        self.assertAlmostEqual(decision.execution_stop, 108.0 - 0.5 * decision.atr14)

    def test_no_valid_target_is_explicit(self):
        event, quotes = _fixture()
        with patch("trading.setup02_decision.EXTENSION_RATIOS", {}), patch(
            "trading.setup02_decision.find_swings", return_value=[]
        ):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(decision.gate_reason, Setup02DecisionGateReason.NO_VALID_TARGET)
        self.assertEqual(decision.targets, ())

    def test_target_first_before_rr_and_rr_below_minimum(self):
        event, quotes = _fixture()
        candidate = Setup02TargetCandidate(130.0, "SYNTHETIC", "test")
        with patch(
            "trading.setup02_decision.risk_reward",
            wraps=calculate_risk_reward,
        ) as calculate, patch(
            "trading.setup02_decision._target_candidates",
            return_value=(candidate,),
        ):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(decision.gate_reason, Setup02DecisionGateReason.RR_BELOW_MINIMUM)
        self.assertTrue(decision.targets)
        self.assertIsNotNone(decision.rr)
        self.assertEqual(calculate.call_count, 1)
        self.assertEqual(decision.targets, tuple(item.price for item in decision.target_candidates[:3]))

    def test_confirmed_swing_and_continuation_fib_provenance_are_distinct(self):
        event, quotes = _fixture(wide=True, t_close=140.0)
        confirmed_high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[confirmed_high]):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertEqual(decision.target_candidates[0].source, "CONFIRMED_SWING_HIGH")
        self.assertEqual(decision.target_candidates[0].provenance[0].pivot_date, confirmed_high.pivot_date)
        self.assertEqual(decision.target_candidates[0].provenance[0].confirmed_date, confirmed_high.confirmed_date)

        fib_event, fib_quotes = _fixture()
        fib_decision = evaluate_setup02_decision(fib_event, fib_quotes)
        fib = fib_decision.target_candidates[0]
        self.assertEqual(fib.source, "WAVE3_FIB_EXTENSION")
        self.assertEqual(fib.provenance[0].extension_ratio, 1.272)
        self.assertEqual(fib.price, project_extension(108.0, 100.0, 110.0, 1.272))
        self.assertEqual(fib.provenance[0].wave1_origin_price, 100.0)
        self.assertEqual(fib.provenance[0].wave1_peak_price, 110.0)
        self.assertEqual(fib.provenance[0].wave2_low_price, 108.0)
        self.assertEqual(
            fib.provenance[0].formula_identity,
            "LOW2_PLUS_(HIGH1_MINUS_LOW0)_TIMES_EXTENSION_RATIO",
        )
        self.assertNotIn("fib_retracement_ratio", setup02_decision_to_dict(fib_decision))

        changed_diagnostic = replace(
            fib_event,
            setup02=replace(
                fib_event.setup02,
                fib_retracement_ratio=999.0,
                fib_retracement_region="UNRELATED_DIAGNOSTIC",
            ),
        )
        changed_decision = evaluate_setup02_decision(changed_diagnostic, fib_quotes)
        self.assertEqual(changed_decision.targets, fib_decision.targets)
        self.assertEqual(changed_decision.gate_reason, fib_decision.gate_reason)

    def test_remaining_wave3_targets_are_above_entry_and_nearest_is_t1(self):
        event, quotes = _fixture(wide=True, t_close=123.0)
        with patch("trading.setup02_decision.find_swings", return_value=[]):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(
            decision.targets[0],
            project_extension(108.0, 100.0, 110.0, 1.618),
        )
        self.assertTrue(all(target > decision.planned_entry for target in decision.targets))
        self.assertEqual(
            decision.target_candidates[0].provenance[0].extension_ratio,
            1.618,
        )

    def test_nearest_target_rr_failure_does_not_skip_to_distant_target(self):
        event, quotes = _fixture(t_close=120.5)
        event = replace(
            event,
            setup02=replace(event.setup02, structural_invalidation=119.9),
        )
        steady = [
            _quote(event.symbol, quote.trade_date, 120.0, high=121.0, low=119.0)
            for quote in quotes[:20]
        ]
        quotes = [*steady, quotes[20]]
        with patch("trading.setup02_decision.find_swings", return_value=[]):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(
            decision.gate_reason,
            Setup02DecisionGateReason.TARGET_UPSIDE_BELOW_MINIMUM,
        )
        self.assertEqual(
            decision.targets[0],
            project_extension(108.0, 100.0, 110.0, 1.272),
        )
        self.assertLess(decision.rr.rr_ratios[0], 2.0)
        self.assertGreater(decision.rr.rr_ratios[1], 2.0)

    def test_target_upside_boundaries_and_independent_rr_gate(self):
        event, quotes = _fixture(wide=True, t_close=140.0)

        def synthetic_rr(entry, stop, targets):
            return RiskReward(
                entry,
                stop,
                abs(entry - stop),
                tuple(targets),
                tuple(2.5 for _ in targets),
                "NORMAL",
            )

        cases = (
            (1.0499, Setup02DecisionGateReason.TARGET_UPSIDE_BELOW_MINIMUM, "BELOW_MINIMUM"),
            (1.05, Setup02DecisionGateReason.ENTRY_ALLOWED, "LOW_UPSIDE"),
            (1.07, Setup02DecisionGateReason.ENTRY_ALLOWED, "LOW_UPSIDE"),
            (1.08, Setup02DecisionGateReason.ENTRY_ALLOWED, "PREFERRED_UPSIDE"),
        )
        for multiplier, expected_reason, expected_band in cases:
            with self.subTest(multiplier=multiplier):
                candidate = Setup02TargetCandidate(140.0 * multiplier, "SYNTHETIC", "test")
                with patch(
                    "trading.setup02_decision._target_candidates",
                    return_value=(candidate,),
                ), patch("trading.setup02_decision.risk_reward", side_effect=synthetic_rr):
                    decision = evaluate_setup02_decision(event, quotes)
                self.assertEqual(decision.gate_reason, expected_reason)
                self.assertEqual(decision.target_upside_band, expected_band)
                self.assertAlmostEqual(decision.minimum_target_upside_pct, 0.05)

        candidate = Setup02TargetCandidate(140.0 * 1.10, "SYNTHETIC", "test")
        low_rr = RiskReward(140.0, 100.0, 40.0, (candidate.price,), (1.8,), "NO_TRADE")
        with patch(
            "trading.setup02_decision._target_candidates",
            return_value=(candidate,),
        ), patch("trading.setup02_decision.risk_reward", return_value=low_rr):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(decision.gate_reason, Setup02DecisionGateReason.RR_BELOW_MINIMUM)
        self.assertEqual(decision.target_upside_band, "PREFERRED_UPSIDE")

    def test_t1_rechecks_remaining_target_upside_after_entry_zone_checks(self):
        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=141.0)
        candidate = Setup02TargetCandidate(140.0 * 1.055, "SYNTHETIC", "test")

        def synthetic_rr(entry, stop, targets):
            return RiskReward(
                entry,
                stop,
                abs(entry - stop),
                tuple(targets),
                tuple(2.5 for _ in targets),
                "NORMAL",
            )

        with patch(
            "trading.setup02_decision._target_candidates",
            return_value=(candidate,),
        ), patch("trading.setup02_decision.risk_reward", side_effect=synthetic_rr):
            decision = evaluate_setup02_decision(event, quotes)
            execution = execute_setup02_t1_open(
                decision, quotes, market_session_dates=_sessions(quotes)
            )
        self.assertEqual(decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertEqual(execution.outcome, SKIP_TARGET_UPSIDE_BELOW_MINIMUM)
        self.assertIsNone(execution.actual_entry)
        self.assertIsNotNone(execution.actual_rr)
        self.assertLess(execution.remaining_target_upside_pct, 0.05)

        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=160.0)
        with patch(
            "trading.setup02_decision._target_candidates",
            return_value=(candidate,),
        ), patch("trading.setup02_decision.risk_reward", side_effect=synthetic_rr):
            decision = evaluate_setup02_decision(event, quotes)
            execution = execute_setup02_t1_open(
                decision, quotes, market_session_dates=_sessions(quotes)
            )
        self.assertEqual(execution.outcome, "SKIP_GAP_ABOVE_ENTRY_ZONE")
        self.assertLess(execution.remaining_target_upside_pct, 0.05)

    def test_setup02_target_builder_no_longer_contains_old_invalidation_projection(self):
        module = __import__("trading.setup02_decision", fromlist=["_target_candidates"])
        source = inspect.getsource(module._target_candidates)
        self.assertNotIn("structural_invalidation", source)
        self.assertNotIn("HIGH3", source)

    def test_high_asymmetry_runs_geometry_audit_without_historical_gate(self):
        event, quotes = _fixture(wide=True, t_close=140.0)
        confirmed_high = _swing(SwingKind.HIGH, 1000.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[confirmed_high]):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(decision.action, DecisionAction.ENTRY_ALLOWED)
        self.assertTrue(decision.target_reasonableness_checked)
        self.assertTrue(decision.target_reasonableness_passed)
        self.assertGreater(decision.rr.rr_ratios[0], 5.0)
        audit = setup02_target_provenance_audit(decision)
        self.assertTrue(audit["planned_first_target_over_5r"])
        self.assertTrue(audit["target_provenance_geometry_check"])

    def test_position_size_requires_explicit_risk_capital(self):
        event, quotes = _fixture(wide=True, t_close=140.0)
        high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            missing = evaluate_setup02_decision(event, quotes)
            supplied = evaluate_setup02_decision(event, quotes, risk_capital=1000.0)
        self.assertEqual(missing.position_size_required_input, "risk_capital")
        self.assertIsNone(missing.position_size)
        self.assertIsNotNone(supplied.position_size)
        self.assertEqual(supplied.position_size.risk_capital, 1000.0)

    def test_t1_exact_session_and_all_gap_branches(self):
        cases = [
            (107.0, SKIP_BELOW_INVALIDATION),
            (110.0, SKIP_GAP_BELOW_CONFIRMATION),
            (160.0, SKIP_GAP_ABOVE_ENTRY_ZONE),
        ]
        for opening, expected in cases:
            with self.subTest(opening=opening):
                event, quotes = _fixture(wide=True, t_close=140.0, t1_open=opening)
                high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
                with patch("trading.setup02_decision.find_swings", return_value=[high]):
                    decision = evaluate_setup02_decision(event, quotes)
                execution = execute_setup02_t1_open(
                    decision, quotes, market_session_dates=_sessions(quotes)
                )
                self.assertEqual(execution.outcome, expected)
                self.assertEqual(execution.t1_open, opening)
                self.assertIsNone(execution.actual_entry)

        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=120.0)
        high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            decision = evaluate_setup02_decision(event, quotes)
        at_confirmation = execute_setup02_t1_open(
            decision, quotes, market_session_dates=_sessions(quotes)
        )
        self.assertEqual(at_confirmation.outcome, EXECUTED)
        self.assertEqual(at_confirmation.actual_entry, 120.0)

    def test_actual_open_rr_failure_and_executed_ledger(self):
        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=149.0)
        high = _swing(SwingKind.HIGH, 280.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            decision = evaluate_setup02_decision(event, quotes)
        self.assertEqual(decision.action, DecisionAction.ENTRY_ALLOWED)
        skipped = execute_setup02_t1_open(
            decision, quotes, market_session_dates=_sessions(quotes)
        )
        self.assertEqual(skipped.outcome, SKIP_RR_BELOW_MINIMUM_AT_OPEN)
        self.assertIsNone(skipped.actual_entry)
        self.assertIsNotNone(skipped.actual_rr)
        self.assertEqual(skipped.t1_open, 149.0)

        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=140.5)
        high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            decision = evaluate_setup02_decision(event, quotes)
        executed = execute_setup02_t1_open(
            decision, quotes, market_session_dates=_sessions(quotes)
        )
        self.assertEqual(executed.outcome, EXECUTED)
        self.assertEqual(executed.actual_entry, 140.5)

    def test_no_t1_bar_does_not_fall_forward_to_t2(self):
        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=None)
        t2 = _quote(event.symbol, event.trade_date + timedelta(days=2), 100.0, 140.5)
        quotes.append(t2)
        high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            decision = evaluate_setup02_decision(event, quotes)
        sessions = {"US": (event.trade_date, event.trade_date + timedelta(days=1), t2.trade_date)}
        execution = execute_setup02_t1_open(decision, quotes, market_session_dates=sessions)
        self.assertEqual(execution.outcome, SKIP_NO_T1_BAR)
        self.assertIsNone(execution.execution_date)
        self.assertIsNone(execution.t1_open)

    def test_t1_executor_reads_open_only(self):
        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=None)
        open_only = _OpenOnlyQuote()
        quotes.append(open_only)  # type: ignore[arg-type]
        high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            decision = evaluate_setup02_decision(event, quotes)
        sessions = {"US": (event.trade_date, open_only.trade_date)}
        execution = execute_setup02_t1_open(decision, quotes, market_session_dates=sessions)
        self.assertEqual(execution.outcome, EXECUTED)
        self.assertEqual(execution.t1_open, open_only.open)

    def test_actual_entry_iff_executed_and_non_allowed_is_not_attempted(self):
        event, quotes = _fixture(wide=True, t_close=140.0, t1_open=140.5)
        high = _swing(SwingKind.HIGH, 300.0, 10, date(2026, 3, 1))
        with patch("trading.setup02_decision.find_swings", return_value=[high]):
            decision = evaluate_setup02_decision(event, quotes)
        execution = execute_setup02_t1_open(
            decision, quotes, market_session_dates=_sessions(quotes)
        )
        self.assertEqual(execution.actual_entry is not None, execution.outcome == EXECUTED)
        no_trade = evaluate_setup02_decision(event, [*_fixture(t_close=130.0)[1]])
        no_trade_execution = execute_setup02_t1_open(
            no_trade, quotes, market_session_dates=_sessions(quotes)
        )
        self.assertFalse(no_trade_execution.attempted)
        self.assertIsNone(no_trade_execution.actual_entry)

    def test_projection_is_json_ready_and_module_stays_independent(self):
        event, quotes = _fixture()
        decision = evaluate_setup02_decision(event, quotes)
        projection = setup02_decision_to_dict(decision)
        json.dumps(projection, ensure_ascii=False)
        self.assertEqual(decision.protocol_version, SETUP02_DECISION_PROTOCOL_VERSION)
        self.assertEqual(projection["wave1_length"], 10.0)
        self.assertNotIn("setup01", __import__("pathlib").Path("trading/setup02_decision.py").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()

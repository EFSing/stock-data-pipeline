import json
import unittest
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch

from core import Quote
from trading.models import (
    Setup01Evaluation,
    SetupState,
    SwingKind,
    SwingPoint,
    Trend,
    WaveLeg,
    WaveScenario,
    WaveScenarioEvaluation,
    WaveScenarioFamily,
)
from trading.setup01 import (
    SETUP01_PROTOCOL_VERSION,
    SETUP01_RECOVERY_RATIO,
    evaluate_setup01,
    evaluate_setup01_history,
    setup01_evaluation_to_dict,
)
from trading.setup01_replay import replay_setup01_history


def _quote(day: date, kind: str, price: float) -> Quote:
    if kind == "HIGH":
        opening, high, low = price - 2.0, price, price - 5.0
    elif kind == "LOW":
        opening, high, low = price + 2.0, price + 5.0, price
    else:
        opening, high, low = price, price + 1.0, price - 1.0
    return Quote(
        symbol="SETUP01.TEST",
        name="Setup 01 synthetic",
        market="US",
        trade_date=day,
        source="test",
        open=opening,
        high=high,
        low=low,
        close=price,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _timed_points(
    points: list[tuple[date, str, float]], tail_close: float
) -> list[Quote]:
    first_day, first_kind, first_price = points[0]
    leading_price = first_price + 5.0 if first_kind == "LOW" else first_price - 3.0
    output = [_quote(first_day - timedelta(days=7), "NEUTRAL", leading_price)]
    output.extend(_quote(day, kind, price) for day, kind, price in points)
    last_day = points[-1][0]
    output.append(_quote(last_day + timedelta(days=1), "NEUTRAL", tail_close))
    return output


def _wave_candidate_points(tail_close: float = 125.0) -> list[Quote]:
    return _timed_points(
        [
            (date(2026, 1, 2), "LOW", 100.0),
            (date(2026, 1, 3), "HIGH", 140.0),
            (date(2026, 1, 4), "LOW", 115.0),
            (date(2026, 1, 5), "HIGH", 145.0),
        ],
        tail_close,
    )


class Setup01LifecycleTests(unittest.TestCase):
    def test_normal_wave2_recovery_then_strict_break_confirms_once(self):
        quotes = _wave_candidate_points(125.0)
        quotes.append(
            _quote(quotes[-1].trade_date + timedelta(days=1), "NEUTRAL", 130.0)
        )
        quotes.append(
            _quote(quotes[-1].trade_date + timedelta(days=1), "NEUTRAL", 141.0)
        )
        history = evaluate_setup01_history(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(
            [item.state for item in history[-3:]],
            [SetupState.WATCH, SetupState.ARMED, SetupState.CONFIRMED],
        )
        confirmed = history[-1]
        self.assertEqual(confirmed.setup_type, "SETUP_01")
        self.assertEqual(confirmed.protocol_version, SETUP01_PROTOCOL_VERSION)
        self.assertEqual(confirmed.confirmation_level, 140.0)
        self.assertEqual(confirmed.wave_scenario_invalidation, 100.0)
        self.assertEqual(confirmed.structural_invalidation, 115.0)
        self.assertEqual(confirmed.confirmed_index, len(quotes) - 1)
        self.assertEqual(confirmed.confirmed_date, quotes[-1].trade_date)

        report = replay_setup01_history(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual([event.event_type for event in report.events], [SetupState.CONFIRMED])
        self.assertIn("|CONFIRMED|", report.events[0].event_identity)
        self.assertEqual(len(set(event.event_identity for event in report.events)), 1)

    def test_terminal_confirmation_is_not_a_new_event_on_later_as_of_date(self):
        start = date(2026, 2, 1)
        quotes = [
            _quote(start + timedelta(days=index), "NEUTRAL", close)
            for index, close in enumerate((100.0, 120.0, 120.0, 130.0, 141.0, 139.0))
        ]
        origin = SwingPoint(SwingKind.LOW, 100.0, 0, start, 0, start)
        peak = SwingPoint(
            SwingKind.HIGH, 140.0, 1, start + timedelta(days=1), 1,
            start + timedelta(days=1)
        )
        wave2_low = SwingPoint(
            SwingKind.LOW, 115.0, 2, start + timedelta(days=2), 2,
            start + timedelta(days=2)
        )
        primary = WaveScenario(
            family=WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE,
            evidence=("synthetic candidate",),
            counter_evidence=(),
            evidence_score=1,
            confirmed_swings=(origin, peak, wave2_low),
            candidate_impulse_leg=WaveLeg(origin, peak, "UP"),
            candidate_retracement_leg=WaveLeg(peak, wave2_low, "DOWN"),
            fibonacci_retracement_regions=(),
            fibonacci_extension_regions=(),
            structural_invalidation=origin.price,
            scenario_invalidation_reason="synthetic",
            setup01_context_eligible=True,
            setup02_context_eligible=False,
        )
        template = WaveScenarioEvaluation(
            protocol_version="WAVE-SCENARIO-ENGINE-2026-08-30-v1",
            as_of_date=start,
            as_of_close=100.0,
            weekly_state=Trend.UPTREND,
            daily_state=Trend.UPTREND,
            weekly_swings=(),
            daily_swings=(origin, peak, wave2_low),
            primary_scenario=primary,
            alternate_scenario=replace(
                primary,
                family=WaveScenarioFamily.NO_VALID_SCENARIO,
                confirmed_swings=(),
                candidate_impulse_leg=None,
                candidate_retracement_leg=None,
                setup01_context_eligible=False,
                setup02_context_eligible=False,
            ),
        )
        with patch(
            "trading.setup01.evaluate_wave_scenario",
            side_effect=lambda visible, **kwargs: replace(
                template,
                as_of_date=visible[-1].trade_date,
                as_of_close=float(visible[-1].close),
            ),
        ):
            history = evaluate_setup01_history(
                quotes, daily_swing_lookback=1, weekly_swing_lookback=1
            )
        confirmation_index = next(
            index
            for index, snapshot in enumerate(history)
            if snapshot.is_new_confirmed_event_as_of
        )
        confirmed = history[confirmation_index]
        later = history[confirmation_index + 1]
        self.assertEqual(confirmed.state, SetupState.CONFIRMED)
        self.assertEqual(confirmed.terminal_event_type, SetupState.CONFIRMED)
        self.assertEqual(confirmed.terminal_event_date, confirmed.as_of_date)
        self.assertTrue(confirmed.is_new_confirmed_event_as_of)
        self.assertFalse(confirmed.is_new_failed_event_as_of)
        self.assertFalse(confirmed.is_live_preconfirmation_candidate)
        self.assertEqual(later.state, SetupState.CONFIRMED)
        self.assertEqual(later.terminal_event_type, SetupState.CONFIRMED)
        self.assertEqual(later.terminal_event_date, confirmed.as_of_date)
        self.assertFalse(later.is_new_confirmed_event_as_of)
        self.assertFalse(later.is_new_failed_event_as_of)
        self.assertFalse(later.is_live_preconfirmation_candidate)

        with patch(
            "trading.setup01.evaluate_wave_scenario",
            side_effect=lambda visible, **kwargs: replace(
                template,
                as_of_date=visible[-1].trade_date,
                as_of_close=float(visible[-1].close),
            ),
        ):
            report = replay_setup01_history(
                quotes, daily_swing_lookback=1, weekly_swing_lookback=1
            )
        self.assertEqual(
            [event.event_type for event in report.events], [SetupState.CONFIRMED]
        )
        self.assertEqual(len(report.events), 1)

    def test_armed_recovery_is_fixed_and_close_equal_peak_is_not_confirmed(self):
        quotes = _wave_candidate_points(140.0)
        evaluation = evaluate_setup01(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(evaluation.state, SetupState.ARMED)
        self.assertEqual(SETUP01_RECOVERY_RATIO, 0.5)
        self.assertNotEqual(evaluation.state, SetupState.CONFIRMED)
        self.assertIn("causal recovery threshold", evaluation.reason)

    def test_wave2_low_invalidates_active_setup_and_is_separate_from_origin(self):
        quotes = _wave_candidate_points(125.0)
        quotes.append(
            _quote(quotes[-1].trade_date + timedelta(days=1), "NEUTRAL", 114.0)
        )
        evaluation = evaluate_setup01(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(evaluation.state, SetupState.FAILED)
        self.assertEqual(evaluation.structural_invalidation, 115.0)
        self.assertEqual(evaluation.wave_scenario_invalidation, 100.0)
        self.assertIn("TRADE_STRUCTURE_INVALIDATION", evaluation.reason)

        report = replay_setup01_history(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual([event.event_type for event in report.events], [SetupState.FAILED])
        self.assertIn("|FAILED|", report.events[0].event_identity)

    def test_close_at_origin_fails_before_new_lower_swing_is_confirmed(self):
        quotes = _wave_candidate_points(125.0)
        quotes.append(
            _quote(quotes[-1].trade_date + timedelta(days=1), "NEUTRAL", 100.0)
        )
        evaluation = evaluate_setup01(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(evaluation.state, SetupState.FAILED)
        self.assertIn("WAVE_SCENARIO_INVALIDATION", evaluation.reason)
        self.assertFalse(
            any(item.state is SetupState.CONFIRMED for item in evaluate_setup01_history(
                quotes, daily_swing_lookback=1, weekly_swing_lookback=1
            ))
        )

    def test_abc_counter_scenario_cannot_confirm_wave3(self):
        start = date(2026, 1, 1)
        quotes = [
            _quote(start, "NEUTRAL", 105.0),
            _quote(start + timedelta(days=1), "LOW", 100.0),
            _quote(start + timedelta(days=2), "HIGH", 140.0),
            _quote(start + timedelta(days=3), "LOW", 120.0),
            _quote(start + timedelta(days=4), "HIGH", 130.0),
            _quote(start + timedelta(days=5), "LOW", 108.0),
            _quote(start + timedelta(days=6), "HIGH", 125.0),
            _quote(start + timedelta(days=7), "NEUTRAL", 110.0),
        ]
        evaluation = evaluate_setup01(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(
            evaluation.primary_wave_scenario,
            WaveScenarioFamily.ABC_CORRECTION_CANDIDATE.value,
        )
        self.assertNotEqual(evaluation.state, SetupState.CONFIRMED)
        report = replay_setup01_history(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertFalse(any(event.event_type is SetupState.CONFIRMED for event in report.events))

    def test_weekly_downtrend_blocks_daily_rebound(self):
        start = date(2026, 1, 2)
        base = [
            (start + timedelta(days=index * 7), kind, price)
            for index, (kind, price) in enumerate(
                [
                    ("HIGH", 150.0),
                    ("LOW", 120.0),
                    ("HIGH", 140.0),
                    ("LOW", 100.0),
                    ("HIGH", 130.0),
                    ("LOW", 90.0),
                ],
                start=1,
            )
        ]
        last = base[-1][0]
        base.extend(
            [
                (last + timedelta(days=3), "NEUTRAL", 105.0),
                (last + timedelta(days=4), "HIGH", 160.0),
                (last + timedelta(days=5), "LOW", 110.0),
                (last + timedelta(days=6), "HIGH", 170.0),
                (last + timedelta(days=7), "LOW", 120.0),
            ]
        )
        quotes = _timed_points(base, 160.0)
        evaluation = evaluate_setup01(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(
            evaluation.primary_wave_scenario,
            WaveScenarioFamily.DOWNTREND_OR_INVALID_FOR_LONG.value,
        )
        self.assertFalse(any(
            item.state is SetupState.CONFIRMED
            for item in evaluate_setup01_history(
                quotes, daily_swing_lookback=1, weekly_swing_lookback=1
            )
        ))

    def test_confirmed_wave_legs_are_required_not_provisional(self):
        day = date(2026, 1, 1)
        origin = SwingPoint(SwingKind.LOW, 100.0, 0, day, 0, day)
        peak = SwingPoint(SwingKind.HIGH, 140.0, 1, day + timedelta(days=1), 1, day + timedelta(days=1))
        provisional_low = SwingPoint(
            SwingKind.LOW, 115.0, 2, day + timedelta(days=2), None, None
        )
        scenario = WaveScenario(
            family=WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE,
            evidence=("synthetic candidate",),
            counter_evidence=(),
            evidence_score=1,
            confirmed_swings=(origin, peak, provisional_low),
            candidate_impulse_leg=WaveLeg(origin, peak, "UP"),
            candidate_retracement_leg=WaveLeg(peak, provisional_low, "DOWN"),
            fibonacci_retracement_regions=(),
            fibonacci_extension_regions=(),
            structural_invalidation=origin.price,
            scenario_invalidation_reason="synthetic",
            setup01_context_eligible=True,
            setup02_context_eligible=False,
        )
        wave = WaveScenarioEvaluation(
            protocol_version="WAVE-SCENARIO-ENGINE-2026-08-30-v1",
            as_of_date=day + timedelta(days=2),
            as_of_close=125.0,
            weekly_state=Trend.UPTREND,
            daily_state=Trend.UPTREND,
            weekly_swings=(),
            daily_swings=(origin, peak, provisional_low),
            primary_scenario=scenario,
            alternate_scenario=WaveScenario(
                family=WaveScenarioFamily.NO_VALID_SCENARIO,
                evidence=(),
                counter_evidence=(),
                evidence_score=0,
                confirmed_swings=(),
                candidate_impulse_leg=None,
                candidate_retracement_leg=None,
                fibonacci_retracement_regions=(),
                fibonacci_extension_regions=(),
                structural_invalidation=None,
                scenario_invalidation_reason="synthetic",
                setup01_context_eligible=False,
                setup02_context_eligible=False,
            ),
        )
        quotes = [
            _quote(day, "NEUTRAL", 100.0),
            _quote(day + timedelta(days=1), "NEUTRAL", 120.0),
            _quote(day + timedelta(days=2), "NEUTRAL", 125.0),
        ]
        with patch("trading.setup01.evaluate_wave_scenario", return_value=wave):
            evaluation = evaluate_setup01_history(
                quotes, daily_swing_lookback=1, weekly_swing_lookback=1
            )[-1]
        self.assertEqual(evaluation.state, SetupState.NONE)
        self.assertEqual(evaluation.setup_type, "SETUP_01")

    def test_later_low_above_wave1_peak_is_not_a_retracement(self):
        day = date(2026, 1, 1)
        origin = SwingPoint(SwingKind.LOW, 100.0, 0, day, 0, day)
        peak = SwingPoint(
            SwingKind.HIGH, 140.0, 1, day + timedelta(days=1), 1, day + timedelta(days=1)
        )
        later_low = SwingPoint(
            SwingKind.LOW, 145.0, 2, day + timedelta(days=2), 2, day + timedelta(days=2)
        )
        scenario = WaveScenario(
            family=WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE,
            evidence=("synthetic non-retracement",),
            counter_evidence=(),
            evidence_score=1,
            confirmed_swings=(origin, peak, later_low),
            candidate_impulse_leg=WaveLeg(origin, peak, "UP"),
            candidate_retracement_leg=WaveLeg(peak, later_low, "DOWN"),
            fibonacci_retracement_regions=(),
            fibonacci_extension_regions=(),
            structural_invalidation=origin.price,
            scenario_invalidation_reason="synthetic",
            setup01_context_eligible=True,
            setup02_context_eligible=False,
        )
        wave = WaveScenarioEvaluation(
            protocol_version="WAVE-SCENARIO-ENGINE-2026-08-30-v1",
            as_of_date=day + timedelta(days=2),
            as_of_close=145.0,
            weekly_state=Trend.UPTREND,
            daily_state=Trend.UPTREND,
            weekly_swings=(),
            daily_swings=(origin, peak, later_low),
            primary_scenario=scenario,
            alternate_scenario=replace(
                scenario,
                family=WaveScenarioFamily.NO_VALID_SCENARIO,
                confirmed_swings=(),
                candidate_impulse_leg=None,
                candidate_retracement_leg=None,
                setup01_context_eligible=False,
                setup02_context_eligible=False,
            ),
        )
        quotes = [
            _quote(day, "NEUTRAL", 100.0),
            _quote(day + timedelta(days=1), "NEUTRAL", 120.0),
            _quote(day + timedelta(days=2), "NEUTRAL", 145.0),
        ]
        with patch("trading.setup01.evaluate_wave_scenario", return_value=wave):
            evaluation = evaluate_setup01(
                quotes, daily_swing_lookback=1, weekly_swing_lookback=1
            )
        self.assertEqual(evaluation.state, SetupState.NONE)
        self.assertIn("no eligible", evaluation.reason)

    def test_future_append_and_prefix_replay_do_not_rewrite_history(self):
        prefix = _wave_candidate_points(125.0)
        future = prefix + [
            _quote(prefix[-1].trade_date + timedelta(days=1), "LOW", 20.0),
            _quote(prefix[-1].trade_date + timedelta(days=2), "HIGH", 300.0),
        ]
        as_of = prefix[-1].trade_date
        before = evaluate_setup01(
            prefix,
            as_of_date=as_of,
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        after = evaluate_setup01(
            future,
            as_of_date=as_of,
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        self.assertEqual(
            setup01_evaluation_to_dict(before), setup01_evaluation_to_dict(after)
        )
        replay = replay_setup01_history(
            future,
            as_of_date=as_of,
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        self.assertEqual(
            setup01_evaluation_to_dict(replay.current),
            setup01_evaluation_to_dict(before),
        )
        for index, day in enumerate(replay.days):
            prefix_evaluation = evaluate_setup01(
                prefix[: index + 1],
                daily_swing_lookback=1,
                weekly_swing_lookback=1,
            )
            self.assertEqual(
                setup01_evaluation_to_dict(day.setup01),
                setup01_evaluation_to_dict(prefix_evaluation),
            )

    def test_json_projection_has_required_fields_and_no_entry_signal(self):
        evaluation = evaluate_setup01(
            _wave_candidate_points(125.0),
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        projection = setup01_evaluation_to_dict(evaluation)
        for field in (
            "setup_type",
            "protocol_version",
            "state",
            "as_of_date",
            "wave1_origin_price",
            "wave1_origin_date",
            "wave1_origin_confirmed_date",
            "wave1_peak_price",
            "wave1_peak_date",
            "wave1_peak_confirmed_date",
            "wave2_low_price",
            "wave2_low_date",
            "wave2_low_confirmed_date",
            "fib_retracement_ratio",
            "fib_retracement_region",
            "confirmation_level",
            "structural_invalidation",
            "wave_scenario_invalidation",
            "state_entered_date",
            "confirmed_date",
            "failed_date",
            "terminal_event_type",
            "terminal_event_date",
            "is_new_confirmed_event_as_of",
            "is_new_failed_event_as_of",
            "is_live_preconfirmation_candidate",
            "primary_wave_scenario",
            "alternate_wave_scenario",
            "reason",
            "diagnostics",
        ):
            self.assertIn(field, projection)
        self.assertNotIn("ENTRY_ALLOWED", json.dumps(projection))


if __name__ == "__main__":
    unittest.main()

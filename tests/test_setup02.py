import unittest
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch

from core import Quote
from tests.test_wave import timed_pivot_quotes
from trading.models import (
    SetupState,
    SwingKind,
    SwingPoint,
    Trend,
    WaveLeg,
    WaveScenario,
    WaveScenarioEvaluation,
    WaveScenarioFamily,
)
from trading.setup02 import (
    SETUP02_PROTOCOL_VERSION,
    Setup02Evaluation,
    evaluate_setup02,
    evaluate_setup02_history,
    setup02_evaluation_to_dict,
)
from trading.setup02_replay import (
    replay_setup02_history,
    setup02_event_identity,
    setup02_event_rows,
)


def _quotes(closes: list[float], symbol: str = "SETUP02.TEST") -> list[Quote]:
    return [
        Quote(
            symbol=symbol,
            name="SETUP02 test",
            market="US",
            trade_date=date(2026, 1, 1) + timedelta(days=index),
            source="test",
            open=close,
            high=close,
            low=close,
            close=close,
            preclose=None,
            pct_change=None,
            volume=1.0,
            amount=None,
            turnover_rate=None,
            currency="USD",
        )
        for index, close in enumerate(closes)
    ]


def _swing(
    kind: SwingKind,
    price: float,
    pivot_index: int,
    *,
    confirmed_index: int = 0,
) -> SwingPoint:
    pivot_date = date(2025, 12, 1) + timedelta(days=pivot_index)
    confirmed_date = date(2025, 12, 1) + timedelta(days=confirmed_index)
    return SwingPoint(
        kind=kind,
        price=price,
        pivot_index=pivot_index,
        pivot_date=pivot_date,
        confirmed_index=confirmed_index,
        confirmed_date=confirmed_date,
    )


def _wave(
    quote: Quote,
    *,
    family: WaveScenarioFamily = WaveScenarioFamily.WAVE_3_CONTINUATION_CANDIDATE,
    eligible: bool = True,
    weekly: Trend = Trend.UPTREND,
    daily: Trend = Trend.UPTREND,
    context: tuple[float, float, float, float] = (80.0, 110.0, 90.0, 120.0),
    invalidation: float | None = 100.0,
    pivot_offset: int = 0,
) -> WaveScenarioEvaluation:
    low0_price, high1_price, low2_price, high3_price = context
    low0 = _swing(SwingKind.LOW, low0_price, pivot_offset)
    high1 = _swing(SwingKind.HIGH, high1_price, pivot_offset + 1)
    low2 = _swing(SwingKind.LOW, low2_price, pivot_offset + 2)
    high3 = _swing(SwingKind.HIGH, high3_price, pivot_offset + 3)
    primary = WaveScenario(
        family=family,
        evidence=("test structural evidence",),
        counter_evidence=(),
        evidence_score=1,
        confirmed_swings=(low0, high1, low2, high3),
        candidate_impulse_leg=WaveLeg(low0, high3, "UP"),
        candidate_retracement_leg=WaveLeg(high1, low2, "DOWN"),
        fibonacci_retracement_regions=(),
        fibonacci_extension_regions=(),
        structural_invalidation=invalidation,
        scenario_invalidation_reason="test scenario",
        setup01_context_eligible=False,
        setup02_context_eligible=eligible,
    )
    alternate = replace(
        primary,
        family=WaveScenarioFamily.NO_VALID_SCENARIO,
        setup02_context_eligible=False,
        candidate_impulse_leg=None,
        candidate_retracement_leg=None,
        structural_invalidation=None,
    )
    return WaveScenarioEvaluation(
        protocol_version="WAVE-SCENARIO-ENGINE-test",
        as_of_date=quote.trade_date,
        as_of_close=quote.close,
        weekly_state=weekly,
        daily_state=daily,
        weekly_swings=(),
        daily_swings=(),
        primary_scenario=primary,
        alternate_scenario=alternate,
    )


def _wave_sequence(quotes: list[Quote], specs: dict[int, dict]) -> list[WaveScenarioEvaluation]:
    output = []
    for index, quote in enumerate(quotes):
        output.append(_wave(quote, **specs.get(index, {"family": WaveScenarioFamily.NO_VALID_SCENARIO, "eligible": False, "invalidation": None})))
    return output


class Setup02LifecycleTests(unittest.TestCase):
    def test_canonical_valid_continuation_uses_primary_wave_context(self):
        start = date(2026, 1, 2)
        sequence = [
            ("LOW", 80.0), ("HIGH", 110.0), ("LOW", 90.0), ("HIGH", 130.0),
            ("LOW", 105.0), ("HIGH", 150.0), ("LOW", 120.0),
        ]
        points = [
            (start + timedelta(days=index * 7), kind, price)
            for index, (kind, price) in enumerate(sequence, start=1)
        ]
        quotes = timed_pivot_quotes(points, tail_close=160.0)
        evaluation = evaluate_setup02(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )

        self.assertIsInstance(evaluation, Setup02Evaluation)
        self.assertEqual(evaluation.protocol_version, SETUP02_PROTOCOL_VERSION)
        self.assertEqual(evaluation.primary_wave_scenario, "WAVE_3_CONTINUATION_CANDIDATE")
        self.assertEqual(evaluation.continuation_high, 150.0)
        self.assertEqual(evaluation.structural_invalidation, 105.0)
        self.assertEqual(evaluation.state, SetupState.CONFIRMED)
        self.assertAlmostEqual(evaluation.fib_retracement_ratio, 0.625)
        self.assertEqual(evaluation.fib_retracement_region, "0.618-0.786")

    def test_none_watch_armed_watch_confirmed_and_high3_equality(self):
        quotes = _quotes([50, 51, 52, 53, 105, 110, 109, 121])
        waves = _wave_sequence(
            quotes,
            {
                4: {"eligible": True},
                5: {"eligible": True},
                6: {"eligible": True},
                7: {"eligible": True},
            },
        )
        with patch("trading.setup02.evaluate_wave_scenario", side_effect=waves):
            report = replay_setup02_history(quotes)
        snapshots = tuple(day.setup02 for day in report.days)

        self.assertEqual(
            [snapshot.state for snapshot in snapshots],
            [
                SetupState.NONE,
                SetupState.NONE,
                SetupState.NONE,
                SetupState.NONE,
                SetupState.WATCH,
                SetupState.ARMED,
                SetupState.WATCH,
                SetupState.CONFIRMED,
            ],
        )
        self.assertEqual(len(report.events), 1)
        self.assertEqual(report.events[0].event_type, SetupState.CONFIRMED)
        self.assertFalse(snapshots[5].is_new_confirmed_event_as_of)
        self.assertEqual(snapshots[5].continuation_high, 120.0)

    def test_close_equal_high3_is_armed_not_confirmed(self):
        quotes = _quotes([50, 51, 52, 53, 120])
        waves = _wave_sequence(quotes, {4: {"eligible": True}})
        with patch("trading.setup02.evaluate_wave_scenario", side_effect=waves):
            evaluation = evaluate_setup02(quotes)
        self.assertEqual(evaluation.state, SetupState.ARMED)
        self.assertFalse(evaluation.is_new_confirmed_event_as_of)

    def test_structural_invalidation_fails_and_emits_once(self):
        quotes = _quotes([50, 51, 52, 53, 105, 99, 98])
        waves = _wave_sequence(
            quotes,
            {
                4: {"eligible": True},
                5: {"eligible": False},
                6: {"eligible": False},
            },
        )
        with patch("trading.setup02.evaluate_wave_scenario", side_effect=waves):
            report = replay_setup02_history(quotes)
        self.assertEqual(report.days[4].setup02.state, SetupState.WATCH)
        self.assertEqual(report.days[5].setup02.state, SetupState.FAILED)
        self.assertEqual(report.days[6].setup02.state, SetupState.FAILED)
        self.assertEqual(report.failed_event_dates, (quotes[5].trade_date,))
        self.assertEqual(len(report.events), 1)
        self.assertIn("structural invalidation", report.events[0].setup02.reason)

    def test_weekly_daily_abc_and_downtrend_blocks_fail(self):
        cases = (
            ("weekly", {"eligible": False, "weekly": Trend.RANGE}),
            ("daily", {"eligible": False, "daily": Trend.RANGE}),
            ("abc", {"family": WaveScenarioFamily.ABC_CORRECTION_CANDIDATE, "eligible": False}),
            ("down", {"family": WaveScenarioFamily.DOWNTREND_OR_INVALID_FOR_LONG, "eligible": False}),
        )
        for name, blocked in cases:
            with self.subTest(name=name):
                quotes = _quotes([50, 51, 52, 53, 105, 106])
                waves = _wave_sequence(
                    quotes,
                    {4: {"eligible": True}, 5: blocked},
                )
                with patch("trading.setup02.evaluate_wave_scenario", side_effect=waves):
                    report = replay_setup02_history(quotes)
                self.assertEqual(report.days[5].setup02.state, SetupState.FAILED)
                self.assertEqual(len(report.events), 1)
                reason = report.events[0].setup02.reason
                if name == "weekly":
                    self.assertIn("weekly", reason)
                elif name == "daily":
                    self.assertIn("daily", reason)
                elif name == "abc":
                    self.assertIn("ABC", reason)
                else:
                    self.assertIn("DOWNTREND", reason)

    def test_same_context_refresh_does_not_create_failed_or_duplicate_terminal_event(self):
        quotes = _quotes([50, 51, 52, 53, 105, 121, 122, 123])
        waves = _wave_sequence(
            quotes,
            {4: {"eligible": True}, 5: {"eligible": True}, 6: {"eligible": True}, 7: {"eligible": True}},
        )
        with patch("trading.setup02.evaluate_wave_scenario", side_effect=waves):
            report = replay_setup02_history(quotes)
        self.assertEqual(report.confirmed_event_dates, (quotes[5].trade_date,))
        self.assertEqual(len(report.events), 1)
        self.assertTrue(all(day.setup02.state is SetupState.CONFIRMED for day in report.days[5:]))

    def test_new_confirmed_context_starts_new_lifecycle(self):
        quotes = _quotes([50, 51, 52, 53, 105, 121, 106, 131])
        waves = _wave_sequence(
            quotes,
            {
                4: {"eligible": True},
                5: {"eligible": True},
                6: {"eligible": True, "context": (90.0, 120.0, 100.0, 130.0)},
                7: {"eligible": True, "context": (90.0, 120.0, 100.0, 130.0), "pivot_offset": 1},
            },
        )
        with patch("trading.setup02.evaluate_wave_scenario", side_effect=waves):
            report = replay_setup02_history(quotes)
        self.assertEqual([event.event_type for event in report.events], [SetupState.CONFIRMED, SetupState.CONFIRMED])
        self.assertEqual([event.setup02.lifecycle_index for event in report.events], [1, 2])
        self.assertEqual(report.events[0].event_identity.split("|")[1], "SETUP_02")

    def test_primary_only_does_not_accept_alternate_continuation(self):
        quotes = _quotes([50, 51, 52, 53, 105])
        continuation = _wave(quotes[-1], eligible=True)
        alternate = replace(
            continuation.alternate_scenario,
            family=WaveScenarioFamily.WAVE_3_CONTINUATION_CANDIDATE,
            setup02_context_eligible=True,
            candidate_impulse_leg=continuation.primary_scenario.candidate_impulse_leg,
            candidate_retracement_leg=continuation.primary_scenario.candidate_retracement_leg,
            structural_invalidation=100.0,
        )
        blocked = replace(continuation, alternate_scenario=alternate, primary_scenario=replace(continuation.primary_scenario, family=WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE, setup02_context_eligible=False))
        with patch("trading.setup02.evaluate_wave_scenario", side_effect=[blocked] * len(quotes)):
            evaluation = evaluate_setup02(quotes)
        self.assertEqual(evaluation.state, SetupState.NONE)


class Setup02ReplayContractTests(unittest.TestCase):
    def test_event_identity_and_rows_are_deterministic(self):
        quotes = _quotes([50, 51, 52, 53, 105, 121])
        waves = _wave_sequence(quotes, {4: {"eligible": True}, 5: {"eligible": True}})
        with patch("trading.setup02.evaluate_wave_scenario", side_effect=waves):
            report = replay_setup02_history(quotes)
        event = report.events[0]
        self.assertEqual(
            event.event_identity,
            setup02_event_identity(event.symbol, event.trade_date, event.event_type, 1),
        )
        rows = setup02_event_rows([report])
        self.assertEqual(rows[0]["event_identity"], event.event_identity)
        self.assertEqual(rows[0]["setup_type"], "SETUP_02")
        self.assertEqual(setup02_evaluation_to_dict(event.setup02)["state"], "CONFIRMED")

    def test_future_append_invariance_and_no_future_confirmed_swing_leakage(self):
        start = date(2026, 1, 2)
        points = [
            (start + timedelta(days=index * 7), kind, price)
            for index, (kind, price) in enumerate(
                [
                    ("LOW", 80.0), ("HIGH", 110.0), ("LOW", 90.0),
                    ("HIGH", 130.0), ("LOW", 105.0), ("HIGH", 150.0),
                ],
                start=1,
            )
        ]
        historical = timed_pivot_quotes(points, tail_close=145.0)
        future = historical + [
            replace(
                historical[-1],
                trade_date=historical[-1].trade_date + timedelta(days=1),
                close=190.0,
                open=190.0,
                high=190.0,
                low=190.0,
            )
        ]
        as_of = historical[-1].trade_date
        short = replay_setup02_history(
            historical,
            as_of_date=as_of,
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        appended = replay_setup02_history(
            future,
            as_of_date=as_of,
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        self.assertEqual(setup02_evaluation_to_dict(short.current), setup02_evaluation_to_dict(appended.current))
        self.assertEqual([event.event_identity for event in short.events], [event.event_identity for event in appended.events])
        for swing in (
            short.current.continuation_low0,
            short.current.continuation_high1,
            short.current.continuation_low2,
            short.current.continuation_high3,
        ):
            if swing is not None and swing.confirmed_index is not None:
                self.assertLessEqual(swing.confirmed_index, len(historical) - 1)


if __name__ == "__main__":
    unittest.main()

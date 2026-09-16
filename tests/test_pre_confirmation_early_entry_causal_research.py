import unittest
from datetime import date, timedelta

from core import Quote
from trading.models import SwingKind, SwingPoint, Trend

from research.development.pre_confirmation_early_entry_causal_research_v1 import (
    CandidateLifecycle,
    PolicySignal,
    WaveCandidateObservation,
    _cohort_composition,
    _depth_band,
    _hurdle_outcome,
    _signal_path_metrics,
    _validate_protocol,
    evaluate_policy_signals,
)


def _quote(index, *, open_price=100.0, high=105.0, low=95.0, close=100.0):
    return Quote(
        symbol="TEST",
        name="Test",
        market="US",
        trade_date=date(2020, 1, 2) + timedelta(days=index),
        source="fixture",
        open=open_price,
        high=high,
        low=low,
        close=close,
        preclose=None,
        pct_change=None,
        volume=None,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _candidate(*, eventual_status="LATER_CONFIRMED", resolution="TERMINAL_CONFIRMED", confirmed_index=3):
    origin = SwingPoint(SwingKind.LOW, 90.0, 0, date(2020, 1, 2), 0, date(2020, 1, 2))
    peak = SwingPoint(SwingKind.HIGH, 110.0, 1, date(2020, 1, 3), 1, date(2020, 1, 3))
    wave2 = SwingPoint(SwingKind.LOW, 100.0, 2, date(2020, 1, 4), 2, date(2020, 1, 4))
    observations = tuple(
        WaveCandidateObservation(
            index=index,
            sources=("PRIMARY",),
            close=100.0,
            origin=origin,
            peak=peak,
            wave2_low=wave2,
            daily_state=Trend.RANGE,
            weekly_state=Trend.RANGE,
        )
        for index in range(5)
    )
    return CandidateLifecycle(
        key="TEST|SETUP_01|lifecycle=1",
        symbol="TEST",
        market="US",
        lifecycle_index=1,
        first_observed_index=0,
        last_observed_index=4,
        ready_index=2,
        first_observed_date=date(2020, 1, 2),
        last_observed_date=date(2020, 1, 6),
        ready_date=date(2020, 1, 4),
        origin_price=90.0,
        origin_pivot_date=date(2020, 1, 2),
        peak_price=110.0,
        peak_pivot_date=date(2020, 1, 3),
        wave2_low_price=100.0,
        wave2_low_pivot_date=date(2020, 1, 4),
        wave1_range_R=20.0,
        retracement_ratio_r=0.5,
        geometry_valid=True,
        depth_band="NORMAL_OR_SHALLOW",
        time_half="FIRST_HALF",
        eventual_status=eventual_status,
        resolution=resolution,
        resolution_index=confirmed_index if confirmed_index is not None else 4,
        resolution_date=date(2020, 1, 2) + timedelta(days=confirmed_index if confirmed_index is not None else 4),
        confirmed_index=confirmed_index,
        confirmed_date=(date(2020, 1, 2) + timedelta(days=confirmed_index)) if confirmed_index is not None else None,
        failed_index=None,
        failed_date=None,
        failure_class=None,
        failure_reason=None,
        source_visibility="PRIMARY_ONLY",
        observations=observations,
    )


class PreConfirmationEarlyEntryResearchTests(unittest.TestCase):
    def test_depth_bands_are_fixed_and_exhaustive(self):
        self.assertEqual(_depth_band(0.618), "NORMAL_OR_SHALLOW")
        self.assertEqual(_depth_band(0.786), "DEEP")
        self.assertEqual(_depth_band(0.7860001), "VERY_DEEP")

    def test_protocol_keeps_registered_policy_set_and_forbidden_boundaries(self):
        import json
        from pathlib import Path

        path = Path("research/protocols/pre_confirmation_early_entry_causal_research_v1.json")
        _validate_protocol(json.loads(path.read_text(encoding="utf-8")))

    def test_first_bullish_policy_is_strictly_pre_confirmation_and_next_open(self):
        candidate = _candidate(confirmed_index=4)
        quotes = [
            _quote(0, close=100.0),
            _quote(1, close=100.0),
            _quote(2, close=101.0),
            _quote(3, open_price=102.0, close=103.0),
            _quote(4, open_price=104.0, close=111.0),
        ]
        signals = evaluate_policy_signals(
            "FIRST_BULLISH_RECOVERY",
            (candidate,),
            {"TEST": quotes},
            {"US": tuple(quote.trade_date for quote in quotes)},
        )
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].signal_index, 2)
        self.assertEqual(signals[0].entry_index, 3)
        self.assertLess(signals[0].signal_index, candidate.confirmed_index)
        self.assertEqual(signals[0].entry_price, 102.0)

    def test_incumbent_uses_confirmation_day_and_exact_next_open(self):
        candidate = _candidate(confirmed_index=3)
        quotes = [_quote(index, open_price=100.0 + index) for index in range(5)]
        signals = evaluate_policy_signals(
            "INCUMBENT_CONFIRMED_CLOSE",
            (candidate,),
            {"TEST": quotes},
            {"US": tuple(quote.trade_date for quote in quotes)},
        )
        self.assertEqual(signals[0].signal_index, 3)
        self.assertEqual(signals[0].entry_index, 4)
        self.assertEqual(signals[0].entry_price, 104.0)

    def test_invalid_wave2_geometry_is_retained_but_cannot_signal(self):
        candidate = _candidate(confirmed_index=None, eventual_status="NEVER_CONFIRMED", resolution="TIMEOUT_UNRESOLVED_AT_DATA_END")
        candidate = CandidateLifecycle(**{**candidate.__dict__, "geometry_valid": False, "depth_band": "INVALID_WAVE2_GEOMETRY"})
        quotes = [_quote(index, close=101.0) for index in range(5)]
        signals = evaluate_policy_signals(
            "FIRST_BULLISH_RECOVERY",
            (candidate,),
            {"TEST": quotes},
            {"US": tuple(quote.trade_date for quote in quotes)},
        )
        self.assertEqual(signals, ())

    def test_missing_exact_next_session_is_not_replaced(self):
        candidate = _candidate(confirmed_index=3)
        quotes = [_quote(index) for index in range(4)]
        sessions = tuple(
            quote.trade_date + timedelta(days=1)
            for quote in quotes
        )
        signals = evaluate_policy_signals(
            "INCUMBENT_CONFIRMED_CLOSE",
            (candidate,),
            {"TEST": quotes},
            {"US": sessions},
        )
        self.assertIsNone(signals[0].entry_index)
        self.assertIsNone(signals[0].entry_price)

    def test_same_bar_hurdle_and_invalidation_is_ambiguous(self):
        candidate = _candidate(confirmed_index=None, eventual_status="FAILED", resolution="TERMINAL_FAILED")
        quotes = [_quote(0, high=120.0, low=80.0, close=85.0)]
        outcome = _hurdle_outcome(candidate, quotes, 0, 0, False, 115.44)
        self.assertEqual(outcome, "SAME_BAR_AMBIGUOUS")

    def test_hurdle_continues_after_confirmation_for_later_confirmed_candidate(self):
        candidate = _candidate(confirmed_index=2)
        quotes = [
            _quote(0, close=105.0, low=103.0),
            _quote(1, open_price=106.0, close=109.0, high=110.0, low=105.0),
            _quote(2, open_price=110.0, close=112.0, high=113.0, low=108.0),
            _quote(3, open_price=112.0, close=120.0, high=120.0, low=111.0),
            _quote(4, open_price=120.0, close=120.0, high=120.0, low=115.0),
        ]
        signal = PolicySignal(
            policy_id="FIRST_BULLISH_RECOVERY",
            candidate_key=candidate.key,
            symbol="TEST",
            market="US",
            signal_index=0,
            signal_date=quotes[0].trade_date,
            signal_close=quotes[0].close,
            entry_index=1,
            entry_date=quotes[1].trade_date,
            entry_price=quotes[1].open,
            eventual_status=candidate.eventual_status,
            resolution=candidate.resolution,
            confirmed_index=candidate.confirmed_index,
            confirmed_date=candidate.confirmed_date,
        )
        metrics = _signal_path_metrics(signal, candidate, quotes)
        self.assertEqual(metrics["hurdles"]["HURDLE_0272"], "HURDLE_BEFORE_RESOLUTION")

    def test_cohort_composition_retains_non_confirmed_rows(self):
        confirmed = _candidate(confirmed_index=3)
        failed = _candidate(eventual_status="FAILED", resolution="TERMINAL_FAILED", confirmed_index=None)
        failed = CandidateLifecycle(**{**failed.__dict__, "key": "TEST|SETUP_01|lifecycle=2", "failed_index": 4, "failed_date": date(2020, 1, 6), "failure_class": "STRUCTURAL_INVALIDATION"})
        never = CandidateLifecycle(**{**failed.__dict__, "key": "TEST|SETUP_01|lifecycle=3", "eventual_status": "NEVER_CONFIRMED", "resolution": "TIMEOUT_UNRESOLVED_AT_DATA_END", "failed_index": None, "failed_date": None, "failure_class": None})
        composition = _cohort_composition((confirmed, failed, never))
        self.assertEqual(composition["total_candidate_count"], 3)
        self.assertEqual(composition["eventually_confirmed_count"], 1)
        self.assertEqual(composition["failed_count"], 1)
        self.assertEqual(composition["never_confirmed_count"], 1)
        self.assertEqual(composition["preconfirmation_window"]["counts"]["WITH_LIVE_WATCH_OR_ARMED_OBSERVATION"], 3)


if __name__ == "__main__":
    unittest.main()

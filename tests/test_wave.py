import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from core import Quote
from trading.models import Trend, WaveScenarioFamily
from trading.wave import (
    WAVE_ENGINE_PROTOCOL_VERSION,
    aggregate_completed_weekly_quotes,
    evaluate_wave_scenario,
    evaluation_to_dict,
)


def _quote(day: date, kind: str, price: float, close: float | None = None) -> Quote:
    if kind == "HIGH":
        opening, high, low = price - 2.0, price, price - 5.0
    elif kind == "LOW":
        opening, high, low = price + 2.0, price + 5.0, price
    else:
        opening, high, low = price, price + 1.0, price - 1.0
    return Quote(
        symbol="WAVE.TEST",
        name="Wave synthetic",
        market="US",
        trade_date=day,
        source="test",
        open=opening,
        high=high,
        low=low,
        close=price if close is None else close,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def pivot_quotes(sequence: list[tuple[str, float]], start: date = date(2026, 1, 1)) -> list[Quote]:
    """Build a causal lookback=1 series with a safe leading/trailing bar."""
    points = [_quote(start, "NEUTRAL", sequence[0][1] + 5.0)]
    for index, (kind, price) in enumerate(sequence, start=1):
        points.append(_quote(start + timedelta(days=index), kind, price))
    last_kind, last_price = sequence[-1]
    if last_kind == "HIGH":
        points.append(_quote(start + timedelta(days=len(sequence) + 1), "NEUTRAL", last_price - 15.0))
    else:
        points.append(_quote(start + timedelta(days=len(sequence) + 1), "NEUTRAL", last_price + 3.0))
    return points


def timed_pivot_quotes(points: list[tuple[date, str, float]], tail_close: float | None = None) -> list[Quote]:
    first_day = points[0][0]
    first_kind, first_price = points[0][1], points[0][2]
    leading_price = first_price + 5.0 if first_kind == "LOW" else first_price - 3.0
    output = [_quote(first_day - timedelta(days=7), "NEUTRAL", leading_price)]
    output.extend(_quote(day, kind, price) for day, kind, price in points)
    last_day, last_kind, last_price = points[-1]
    tail_day = last_day + timedelta(days=3 if last_day.weekday() == 4 else 1)
    if tail_close is None:
        tail_price = last_price - 3.0 if last_kind == "HIGH" else last_price + 3.0
        output.append(_quote(tail_day, "NEUTRAL", tail_price))
    else:
        output.append(_quote(tail_day, "NEUTRAL", tail_close, close=tail_close))
    return output


class WaveScenarioEngineTests(unittest.TestCase):
    def test_clean_impulse_retracement_is_watch_like_wave2_candidate(self):
        quotes = pivot_quotes([
            ("LOW", 100.0), ("HIGH", 140.0), ("LOW", 115.0), ("HIGH", 150.0)
        ])
        evaluation = evaluate_wave_scenario(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(
            evaluation.primary_scenario.family,
            WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE,
        )
        self.assertTrue(evaluation.primary_scenario.setup01_context_eligible)
        self.assertFalse(evaluation.primary_scenario.setup02_context_eligible)
        self.assertTrue(any("WATCH-like" in item for item in evaluation.primary_scenario.evidence))
        self.assertEqual(evaluation.protocol_version, WAVE_ENGINE_PROTOCOL_VERSION)

    def test_retracement_breaking_impulse_origin_never_qualifies_wave2(self):
        quotes = pivot_quotes([
            ("LOW", 100.0), ("HIGH", 140.0), ("LOW", 90.0), ("HIGH", 120.0)
        ])
        evaluation = evaluate_wave_scenario(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertNotEqual(
            evaluation.primary_scenario.family,
            WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE,
        )
        all_text = " ".join(
            evaluation.primary_scenario.evidence + evaluation.primary_scenario.counter_evidence
        )
        self.assertIn("broke the impulse origin", all_text)
        self.assertFalse(evaluation.primary_scenario.setup01_context_eligible)

    def test_strong_continuation_requires_weekly_and_daily_structure(self):
        start = date(2026, 1, 2)  # Friday; each following pivot is the next week.
        sequence = [
            ("LOW", 80.0), ("HIGH", 110.0), ("LOW", 90.0), ("HIGH", 130.0),
            ("LOW", 105.0), ("HIGH", 150.0), ("LOW", 120.0),
        ]
        points = [
            (start + timedelta(days=index * 7), kind, price)
            for index, (kind, price) in enumerate(sequence, start=1)
        ]
        quotes = timed_pivot_quotes(points, tail_close=160.0)
        evaluation = evaluate_wave_scenario(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(evaluation.weekly_state, Trend.UPTREND)
        self.assertEqual(evaluation.daily_state, Trend.UPTREND)
        self.assertEqual(
            evaluation.primary_scenario.family,
            WaveScenarioFamily.WAVE_3_CONTINUATION_CANDIDATE,
        )
        self.assertTrue(evaluation.primary_scenario.setup02_context_eligible)

    def test_abc_rebound_is_primary_alternate_to_wave3_interpretation(self):
        quotes = pivot_quotes([
            ("LOW", 100.0), ("HIGH", 140.0), ("LOW", 120.0),
            ("HIGH", 130.0), ("LOW", 108.0), ("HIGH", 125.0),
        ])
        evaluation = evaluate_wave_scenario(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertEqual(
            evaluation.primary_scenario.family,
            WaveScenarioFamily.ABC_CORRECTION_CANDIDATE,
        )
        self.assertNotEqual(
            evaluation.primary_scenario.family,
            evaluation.alternate_scenario.family,
        )
        self.assertFalse(evaluation.primary_scenario.setup01_context_eligible)

    def test_ambiguous_structure_is_unknown_not_forced_into_wave_count(self):
        quotes = pivot_quotes([("LOW", 100.0), ("HIGH", 105.0)])
        evaluation = evaluate_wave_scenario(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertIn(
            evaluation.primary_scenario.family,
            {
                WaveScenarioFamily.NO_VALID_SCENARIO,
                WaveScenarioFamily.UPTREND_UNKNOWN_WAVE,
            },
        )
        self.assertFalse(evaluation.primary_scenario.setup01_context_eligible)
        self.assertFalse(evaluation.primary_scenario.setup02_context_eligible)

    def test_weekly_up_parent_and_daily_pullback_are_separate_states(self):
        start = date(2026, 1, 2)  # Friday
        base = [
            (start + timedelta(days=index * 7), kind, price)
            for index, (kind, price) in enumerate([
                ("LOW", 80.0), ("HIGH", 110.0), ("LOW", 90.0),
                ("HIGH", 130.0), ("LOW", 105.0), ("HIGH", 150.0),
            ], start=1)
        ]
        last = base[-1][0]
        current = [
            (last + timedelta(days=3), "NEUTRAL", 135.0),
            (last + timedelta(days=4), "LOW", 120.0),
            (last + timedelta(days=5), "HIGH", 140.0),
            (last + timedelta(days=6), "LOW", 125.0),
        ]
        evaluation = evaluate_wave_scenario(
            timed_pivot_quotes(base + current),
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        self.assertEqual(evaluation.weekly_state, Trend.UPTREND)
        self.assertEqual(evaluation.daily_state, Trend.RANGE)

    def test_weekly_down_parent_rejects_daily_rebound_for_long(self):
        start = date(2026, 1, 2)
        base_sequence = [
            ("HIGH", 150.0), ("LOW", 120.0), ("HIGH", 140.0),
            ("LOW", 100.0), ("HIGH", 130.0), ("LOW", 90.0),
        ]
        base = [
            (start + timedelta(days=index * 7), kind, price)
            for index, (kind, price) in enumerate(base_sequence, start=1)
        ]
        last = base[-1][0]
        current = [
            (last + timedelta(days=3), "NEUTRAL", 105.0),
            (last + timedelta(days=4), "HIGH", 160.0),
            (last + timedelta(days=5), "LOW", 110.0),
            (last + timedelta(days=6), "HIGH", 170.0),
            (last + timedelta(days=7), "LOW", 120.0),
        ]
        evaluation = evaluate_wave_scenario(
            timed_pivot_quotes(base + current, tail_close=160.0),
            as_of_date=current[-1][0],
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        self.assertEqual(evaluation.weekly_state, Trend.DOWNTREND)
        self.assertEqual(evaluation.daily_state, Trend.UPTREND)
        self.assertEqual(
            evaluation.primary_scenario.family,
            WaveScenarioFamily.DOWNTREND_OR_INVALID_FOR_LONG,
        )
        self.assertFalse(evaluation.primary_scenario.setup01_context_eligible)
        self.assertFalse(evaluation.primary_scenario.setup02_context_eligible)

    def test_current_week_is_excluded_from_weekly_parent_state(self):
        start = date(2026, 1, 2)
        completed = [
            _quote(start + timedelta(days=index * 7), kind, price)
            for index, (kind, price) in enumerate([
                ("LOW", 80.0), ("HIGH", 110.0), ("LOW", 90.0),
                ("HIGH", 130.0), ("LOW", 105.0), ("HIGH", 150.0),
            ], start=1)
        ]
        current_week = [
            _quote(completed[-1].trade_date + timedelta(days=3), "HIGH", 250.0),
            _quote(completed[-1].trade_date + timedelta(days=4), "LOW", 20.0),
        ]
        weekly = aggregate_completed_weekly_quotes(
            completed + current_week,
            current_week[-1].trade_date,
        )
        self.assertEqual(weekly[-1].trade_date, completed[-1].trade_date)
        self.assertNotIn(current_week[-1].trade_date, [item.trade_date for item in weekly])

    def test_only_confirmed_swings_are_exposed_and_fib_regions_reuse_levels(self):
        quotes = pivot_quotes([
            ("LOW", 100.0), ("HIGH", 140.0), ("LOW", 115.0), ("HIGH", 150.0)
        ])
        evaluation = evaluate_wave_scenario(
            quotes, daily_swing_lookback=1, weekly_swing_lookback=1
        )
        self.assertTrue(all(swing.confirmed_index is not None for swing in evaluation.daily_swings))
        regions = evaluation.primary_scenario.fibonacci_retracement_regions
        self.assertTrue(any(region.label == "0.5-0.618" for region in regions))
        target = next(region for region in regions if region.label == "0.5-0.618")
        self.assertAlmostEqual(target.lower, 115.28)
        self.assertAlmostEqual(target.upper, 120.0)

    def test_future_bars_cannot_rewrite_historical_wave_scenario(self):
        prefix = pivot_quotes([
            ("LOW", 100.0), ("HIGH", 140.0), ("LOW", 115.0), ("HIGH", 150.0)
        ])
        future = prefix + [
            _quote(prefix[-1].trade_date + timedelta(days=1), "LOW", 80.0),
            _quote(prefix[-1].trade_date + timedelta(days=2), "HIGH", 220.0),
        ]
        as_of = prefix[-1].trade_date
        before = evaluate_wave_scenario(
            prefix,
            as_of_date=as_of,
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        after = evaluate_wave_scenario(
            future,
            as_of_date=as_of,
            daily_swing_lookback=1,
            weekly_swing_lookback=1,
        )
        self.assertEqual(evaluation_to_dict(before), evaluation_to_dict(after))
        self.assertLessEqual(max(q.trade_date for q in future if q.trade_date <= as_of), as_of)


class WaveShadowReportTests(unittest.TestCase):
    def test_shadow_report_is_read_only_and_json_ready(self):
        from scripts.run_wave_shadow import run_wave_shadow

        class Client:
            def config(self):
                return {"history_days": "100", "retry_count": "1", "retry_wait_seconds": "0"}

            def records(self, sheet_name):
                if sheet_name == "自选清单":
                    return [{
                        "启用": "TRUE", "市场": "US", "统一代码": "WAVE.TEST",
                        "名称": "Wave synthetic", "历史数据源": "yfinance",
                    }]
                raise AssertionError(f"unexpected sheet read: {sheet_name}")

        def fetch_history(source, watch, adjust, start, end, retries, wait):
            self.assertEqual((source, adjust), ("yfinance", "qfq"))
            return pivot_quotes([
                ("LOW", 100.0), ("HIGH", 140.0), ("LOW", 115.0), ("HIGH", 150.0)
            ])

        with tempfile.TemporaryDirectory() as directory:
            summary = run_wave_shadow(
                client=Client(),
                fetched_at=None,
                fetch_history=fetch_history,
                output_dir=directory,
                daily_swing_lookback=1,
                weekly_swing_lookback=1,
            )
            self.assertEqual(summary["symbols_requested"], 1)
            self.assertTrue(summary["sheets_written"] is False)
            self.assertFalse(summary["returns_accessed"])
            report = json.loads(Path(directory, "wave_shadow_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["rows"][0]["primary_scenario"]["family"], "WAVE_2_TO_3_CANDIDATE")


if __name__ == "__main__":
    unittest.main()

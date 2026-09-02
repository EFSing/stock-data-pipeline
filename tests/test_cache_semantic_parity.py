from datetime import date, timedelta
import unittest

from core import Quote
from trading.setup01 import evaluate_setup01_history, setup01_evaluation_to_dict
from trading.setup02 import evaluate_setup02_history, setup02_evaluation_to_dict
from trading.swing import find_swings
from trading.wave import (
    aggregate_completed_weekly_quotes,
    evaluation_to_dict,
    evaluate_wave_scenario,
)


def _quotes() -> list[Quote]:
    closes = (
        100.0,
        101.0,
        104.0,
        102.0,
        99.0,
        101.0,
        105.0,
        103.0,
        100.0,
        102.0,
        107.0,
        104.0,
        101.0,
        103.0,
        108.0,
        106.0,
        102.0,
        104.0,
        109.0,
        107.0,
        103.0,
        105.0,
        110.0,
        108.0,
        104.0,
        106.0,
        111.0,
        109.0,
        105.0,
        107.0,
        112.0,
        110.0,
        106.0,
        108.0,
        113.0,
        111.0,
        107.0,
        109.0,
        114.0,
        112.0,
    )
    start = date(2026, 1, 5)
    return [
        Quote(
            symbol="SYNTH",
            name="Synthetic",
            market="US",
            trade_date=start + timedelta(days=index),
            source="SYNTHETIC",
            open=close,
            high=close + 0.75,
            low=close - 0.75,
            close=close,
            preclose=None,
            pct_change=None,
            volume=100.0,
            amount=None,
            turnover_rate=None,
            currency="USD",
        )
        for index, close in enumerate(closes)
    ]


class CacheSemanticParityTests(unittest.TestCase):
    def test_wave_strict_prefix_and_cached_as_of_are_exactly_equal(self):
        quotes = _quotes()
        daily_swings = tuple(find_swings(quotes, lookback=2))
        weekly_quotes = aggregate_completed_weekly_quotes(
            quotes, quotes[-1].trade_date
        )
        weekly_swings = tuple(find_swings(weekly_quotes, lookback=2))
        weekly_dates = tuple(quote.trade_date for quote in weekly_quotes)

        strict = [
            evaluate_wave_scenario(
                quotes[: index + 1],
                as_of_date=quote.trade_date,
                daily_swing_lookback=2,
                weekly_swing_lookback=2,
            )
            for index, quote in enumerate(quotes)
        ]
        cached = [
            evaluate_wave_scenario(
                quotes,
                as_of_date=quote.trade_date,
                daily_swing_lookback=2,
                weekly_swing_lookback=2,
                _as_of_index=index,
                _daily_swings_all=daily_swings,
                _weekly_swings_all=weekly_swings,
                _weekly_quote_dates=weekly_dates,
                _skip_validation=True,
            )
            for index, quote in enumerate(quotes)
        ]
        self.assertEqual(
            [evaluation_to_dict(item) for item in strict],
            [evaluation_to_dict(item) for item in cached],
        )

    def test_setup01_strict_and_cached_histories_are_exactly_equal(self):
        quotes = _quotes()
        strict = evaluate_setup01_history(
            quotes,
            daily_swing_lookback=2,
            weekly_swing_lookback=2,
            _use_cache=False,
        )
        cached = evaluate_setup01_history(
            quotes,
            daily_swing_lookback=2,
            weekly_swing_lookback=2,
            _use_cache=True,
        )
        self.assertEqual(
            [setup01_evaluation_to_dict(item) for item in strict],
            [setup01_evaluation_to_dict(item) for item in cached],
        )

    def test_setup02_strict_and_cached_histories_are_exactly_equal(self):
        quotes = _quotes()
        strict = evaluate_setup02_history(
            quotes,
            daily_swing_lookback=2,
            weekly_swing_lookback=2,
            _use_cache=False,
        )
        cached = evaluate_setup02_history(
            quotes,
            daily_swing_lookback=2,
            weekly_swing_lookback=2,
            _use_cache=True,
        )
        self.assertEqual(
            [setup02_evaluation_to_dict(item) for item in strict],
            [setup02_evaluation_to_dict(item) for item in cached],
        )


if __name__ == "__main__":
    unittest.main()

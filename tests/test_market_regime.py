import unittest
from datetime import date, timedelta

from core import Quote
from trading.market_regime import MarketRegimeConfig, MarketRegimeState, market_regime


def series(closes: list[float]) -> list[Quote]:
    start = date(2026, 1, 1)
    return [Quote('TEST', '测试', 'US', start + timedelta(days=i), 'test', c, c + 1, c - 1, c, None, None, 1, None, None, 'USD') for i, c in enumerate(closes)]


SMALL = MarketRegimeConfig(rsi_period=2, ema_period=2, memory_window=3)


class MarketRegimeTests(unittest.TestCase):
    def test_panic_and_bottom(self):
        points = market_regime(series([10, 9, 8, 9, 10]), SMALL)
        self.assertTrue(points[2].has_state(MarketRegimeState.PANIC))
        self.assertTrue(points[3].has_state(MarketRegimeState.BOTTOM))

    def test_hot_and_risk(self):
        points = market_regime(series([10, 11, 12, 11]), SMALL)
        self.assertTrue(points[2].has_state(MarketRegimeState.HOT))
        self.assertTrue(points[3].has_state(MarketRegimeState.RISK))

    def test_weak_without_hot(self):
        points = market_regime(series([10, 9, 8, 9, 8]), SMALL)
        self.assertTrue(points[4].has_state(MarketRegimeState.WEAK))
        self.assertFalse(points[4].has_state(MarketRegimeState.RISK))

    def test_no_future_repaint(self):
        quotes = series([10, 9, 8, 9, 10, 11, 10, 9])
        full = market_regime(quotes, SMALL)
        for i in range(len(quotes)):
            self.assertEqual(market_regime(quotes[:i+1], SMALL)[-1], full[i])


if __name__ == '__main__':
    unittest.main()

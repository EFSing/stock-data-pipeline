from datetime import date, timedelta
import unittest

from core import Quote
from trading.models import SwingKind, SwingPoint
from trading.position_management import PositionAnchor
from trading.wave5_context import Wave5ContextState, evaluate_wave5_context


def _quote(day: date, close: float) -> Quote:
    return Quote(
        symbol="SYNTH",
        name="Synthetic",
        market="US",
        trade_date=day,
        source="SYNTHETIC",
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        preclose=None,
        pct_change=None,
        volume=100.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def _swing(kind: SwingKind, price: float, index: int, day: date) -> SwingPoint:
    return SwingPoint(
        kind=kind,
        price=price,
        pivot_index=index,
        pivot_date=day,
        confirmed_index=index,
        confirmed_date=day,
    )


class Wave5ContextTests(unittest.TestCase):
    def test_missing_sequence_is_no_context_and_preserves_invalidation(self):
        start = date(2026, 1, 1)
        anchors = (
            PositionAnchor.from_swing("HIGH1", _swing(SwingKind.HIGH, 110.0, 0, start)),
            PositionAnchor.from_swing("LOW2", _swing(SwingKind.LOW, 100.0, 1, start)),
        )
        context = evaluate_wave5_context(
            quotes=[_quote(start, 105.0)],
            as_of_index=0,
            wave_anchors=anchors,
            structural_invalidation=99.0,
            confirmed_swings=(),
        )
        self.assertEqual(context.state, Wave5ContextState.NO_WAVE5_CONTEXT)
        self.assertEqual(context.invalidation, 99.0)

    def test_low4_must_be_above_original_wave2_low(self):
        start = date(2026, 1, 1)
        anchors = (
            PositionAnchor.from_swing("HIGH3", _swing(SwingKind.HIGH, 110.0, 0, start)),
            PositionAnchor.from_swing("LOW2", _swing(SwingKind.LOW, 100.0, 1, start)),
        )
        high3 = _swing(SwingKind.HIGH, 120.0, 2, start + timedelta(days=2))
        invalid_low4 = _swing(SwingKind.LOW, 99.0, 3, start + timedelta(days=3))
        context = evaluate_wave5_context(
            quotes=[
                _quote(start + timedelta(days=i), close)
                for i, close in enumerate((105.0, 106.0, 119.0, 101.0))
            ],
            as_of_index=3,
            wave_anchors=anchors,
            structural_invalidation=99.0,
            confirmed_swings=(high3, invalid_low4),
        )
        self.assertEqual(context.state, Wave5ContextState.NO_WAVE5_CONTEXT)

    def test_strict_close_break_is_required_for_wave5_candidate(self):
        start = date(2026, 1, 1)
        anchors = (
            PositionAnchor.from_swing("HIGH3", _swing(SwingKind.HIGH, 110.0, 0, start)),
            PositionAnchor.from_swing("LOW2", _swing(SwingKind.LOW, 100.0, 1, start)),
        )
        high3 = _swing(SwingKind.HIGH, 120.0, 1, start + timedelta(days=1))
        low4 = _swing(SwingKind.LOW, 105.0, 2, start + timedelta(days=2))
        quotes = [
            _quote(start + timedelta(days=i), close)
            for i, close in enumerate((105.0, 106.0, 119.0, 121.0))
        ]
        pullback = evaluate_wave5_context(
            quotes=quotes,
            as_of_index=2,
            wave_anchors=anchors,
            structural_invalidation=99.0,
            confirmed_swings=(high3, low4),
        )
        candidate = evaluate_wave5_context(
            quotes=quotes,
            as_of_index=3,
            wave_anchors=anchors,
            structural_invalidation=99.0,
            confirmed_swings=(high3, low4),
        )
        self.assertEqual(pullback.state, Wave5ContextState.WAVE4_PULLBACK_CONTEXT)
        self.assertEqual(candidate.state, Wave5ContextState.WAVE5_CANDIDATE)
        self.assertEqual(candidate.high3.pivot_index, 1)
        self.assertEqual(candidate.low4.pivot_index, 2)


if __name__ == "__main__":
    unittest.main()

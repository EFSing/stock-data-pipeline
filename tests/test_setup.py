import unittest
from datetime import date, timedelta

from core import Quote

from trading.models import SetupState
from trading.setup import detect_platform_breakout
from trading.swing import find_swings


def q(day: date, h: float, l: float) -> Quote:
    return Quote(
        symbol="T",
        name="t",
        market="US",
        trade_date=day,
        source="x",
        open=(h + l) / 2,
        high=h,
        low=l,
        close=(h + l) / 2,
        preclose=None,
        pct_change=None,
        volume=1.0,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def ser(highs: list[float], lows: list[float]) -> list[Quote]:
    start = date(2026, 1, 1)
    return [q(start + timedelta(days=i), h, l) for i, (h, l) in enumerate(zip(highs, lows))]


class PlatformBreakoutTests(unittest.TestCase):
    # 横盘平台：110/90 震荡，lookback=2 产生 HIGH@2/LOW@4/HIGH@6/LOW@8
    BASE_H = [100, 105, 110, 105, 100, 105, 110, 105, 100, 105, 110, 105, 100]
    BASE_L = [90, 95, 100, 95, 90, 95, 100, 95, 90, 95, 100, 95, 90]
    BREAK_H = [115, 118, 120, 122]
    BREAK_L = [112, 115, 117, 119]
    BREAKDOWN_H = [95, 92, 88, 85]
    BREAKDOWN_L = [92, 89, 85, 82]

    def test_no_setup_without_platform(self):
        # 单边上涨，无横盘平台
        highs = [100, 105, 110, 115, 120, 125, 130, 135, 140]
        lows = [95, 100, 105, 110, 115, 120, 125, 130, 135]
        s = detect_platform_breakout(ser(highs, lows), swing_lookback=2, platform_window=20)
        self.assertEqual(s.state, SetupState.NONE)
        self.assertIsNone(s.breakout_price)

    def test_detects_platform_watch(self):
        s = detect_platform_breakout(
            ser(self.BASE_H, self.BASE_L), swing_lookback=2, platform_window=20
        )
        self.assertEqual(s.state, SetupState.WATCH)
        self.assertEqual(s.breakout_price, 110.0)
        self.assertEqual(s.structural_invalidation, 90.0)
        self.assertEqual(s.detected_index, 12)

    def test_breakout_confirmed(self):
        s = detect_platform_breakout(
            ser(self.BASE_H + self.BREAK_H, self.BASE_L + self.BREAK_L),
            swing_lookback=2,
            platform_window=20,
        )
        self.assertEqual(s.state, SetupState.CONFIRMED)
        self.assertEqual(s.breakout_price, 110.0)
        self.assertIsNotNone(s.confirmed_index)

    def test_breakdown_failed(self):
        s = detect_platform_breakout(
            ser(self.BASE_H + self.BREAKDOWN_H, self.BASE_L + self.BREAKDOWN_L),
            swing_lookback=2,
            platform_window=20,
        )
        self.assertEqual(s.state, SetupState.FAILED)
        self.assertEqual(s.structural_invalidation, 90.0)

    def test_platform_fields_frozen_after_future_data(self):
        """冻结字段（detected/breakout/invalidation）不因未来突破数据改变。"""
        full = detect_platform_breakout(
            ser(self.BASE_H + self.BREAK_H, self.BASE_L + self.BREAK_L),
            swing_lookback=2,
            platform_window=20,
        )
        trunc = detect_platform_breakout(
            ser(self.BASE_H, self.BASE_L), swing_lookback=2, platform_window=20
        )
        self.assertEqual(trunc.state, SetupState.WATCH)
        self.assertEqual(trunc.detected_index, full.detected_index)
        self.assertEqual(trunc.breakout_price, full.breakout_price)
        self.assertEqual(trunc.structural_invalidation, full.structural_invalidation)

    def test_accepts_precomputed_swings(self):
        quotes = ser(self.BASE_H, self.BASE_L)
        swings = find_swings(quotes, lookback=2)
        s = detect_platform_breakout(
            quotes, swing_lookback=2, platform_window=20, swings=swings
        )
        self.assertEqual(s.state, SetupState.WATCH)

    def test_boundary_tolerance_relaxes_breakout(self):
        # close 突破到 112（介于 110 与 110*1.05=115.5 之间）
        highs = self.BASE_H + [114, 114]
        lows = self.BASE_L + [110, 110]
        # tolerance=0：112 > 110 → 突破 CONFIRMED
        s0 = detect_platform_breakout(
            ser(highs, lows), swing_lookback=2, platform_window=20, boundary_tolerance=0.0
        )
        self.assertEqual(s0.state, SetupState.CONFIRMED)
        # tolerance=0.05：需 close > 115.5 才突破，112 未达 → 保持 ARMED
        s1 = detect_platform_breakout(
            ser(highs, lows), swing_lookback=2, platform_window=20, boundary_tolerance=0.05
        )
        self.assertEqual(s1.state, SetupState.ARMED)


if __name__ == "__main__":
    unittest.main()

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

    def test_expansion_not_platform(self):
        """扩张（HH+LL）虽判为 TRANSITION，但高低点离散度超容差，不视为平台。"""
        highs = [100, 105, 110, 105, 100, 105, 120, 105, 100, 105, 120, 105, 100]
        lows = [90, 95, 100, 95, 90, 95, 100, 95, 80, 95, 100, 95, 90]
        s = detect_platform_breakout(
            ser(highs, lows),
            swing_lookback=2,
            platform_window=30,
            platform_tolerance_pct=0.05,
        )
        self.assertEqual(s.state, SetupState.NONE)

    def test_new_platform_after_failed(self):
        """旧 FAILED 后出现新平台突破，最终返回新 CONFIRMED（不重复识别旧平台）。"""
        # 平台1（110/90）→ 跌破 FAILED → 平台2（90/60）→ 突破
        highs = (
            self.BASE_H
            + self.BREAKDOWN_H
            + [80, 85, 90, 85, 80, 85, 90, 85, 80, 85, 90, 85, 80]
            + [95, 98, 100]
        )
        lows = (
            self.BASE_L
            + self.BREAKDOWN_L
            + [60, 65, 70, 65, 60, 65, 70, 65, 60, 65, 70, 65, 60]
            + [92, 95, 97]
        )
        s = detect_platform_breakout(
            ser(highs, lows),
            swing_lookback=2,
            platform_window=20,
            platform_tolerance_pct=0.05,
        )
        self.assertEqual(s.state, SetupState.CONFIRMED)
        # 新平台的 breakout = 平台2 高点 90，detected 晚于平台1 的 detected(12)
        self.assertEqual(s.breakout_price, 90.0)
        self.assertGreater(s.detected_index, 12)

    def test_direct_breakout_confirmed(self):
        """WATCH 后单根 bar 直接突破，confirmed_index 即突破 bar index（不经 ARM 延迟）。"""
        s = detect_platform_breakout(
            ser(self.BASE_H + [115], self.BASE_L + [112]),
            swing_lookback=2,
            platform_window=20,
        )
        self.assertEqual(s.state, SetupState.CONFIRMED)
        self.assertEqual(s.detected_index, 12)
        self.assertEqual(s.confirmed_index, 13)


if __name__ == "__main__":
    unittest.main()

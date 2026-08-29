import unittest
from datetime import date, timedelta

from core import Quote

from trading.models import SetupState, SwingKind, SwingPoint
from trading.setup import (
    ATR_NORMALIZED_BOUNDARY_AUTHORIZATION,
    ATR_NORMALIZED_BOUNDARY_MODE,
    ATR_NORMALIZED_BOUNDARY_SCOPE,
    ATR_NORMALIZED_BOUNDARY_STATUS,
    detect_platform_breakout,
    detect_platform_breakout_history_with_diagnostics,
)
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

    def test_atr_normalized_mode_is_explicitly_research_only(self):
        self.assertEqual(ATR_NORMALIZED_BOUNDARY_SCOPE, "RESEARCH_ONLY")
        self.assertEqual(
            ATR_NORMALIZED_BOUNDARY_AUTHORIZATION,
            "NOT_PRODUCTION_AUTHORIZED",
        )
        self.assertEqual(
            ATR_NORMALIZED_BOUNDARY_STATUS,
            "FAILED_STRUCTURAL_CANDIDATE_FAMILY",
        )

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

    def test_platform_recognition_bar_can_confirm_immediately(self):
        """平台信息首次可用的同一 bar 已突破时，识别与确认索引相同。"""
        quotes = ser(
            [100, 100, 100, 100, 111],
            [90, 90, 90, 90, 109],
        )
        confirmed_date = quotes[4].trade_date
        swings = [
            SwingPoint(
                SwingKind.HIGH,
                100.0,
                0,
                quotes[0].trade_date,
                4,
                confirmed_date,
            ),
            SwingPoint(
                SwingKind.LOW,
                90.0,
                1,
                quotes[1].trade_date,
                4,
                confirmed_date,
            ),
            SwingPoint(
                SwingKind.HIGH,
                100.0,
                2,
                quotes[2].trade_date,
                4,
                confirmed_date,
            ),
            SwingPoint(
                SwingKind.LOW,
                90.0,
                3,
                quotes[3].trade_date,
                4,
                confirmed_date,
            ),
        ]

        setup = detect_platform_breakout(
            quotes,
            swing_lookback=2,
            platform_window=20,
            swings=swings,
        )

        self.assertEqual(setup.state, SetupState.CONFIRMED)
        self.assertEqual(
            (setup.detected_index, setup.state_entered_index, setup.confirmed_index),
            (4, 4, 4),
        )

    def test_armed_downgrades_to_watch(self):
        """先逼近阻力进入 ARMED，再回落但不失效 → 降级回 WATCH。"""
        # arm_proximity_pct=0.05：逼近阈值 = 110*0.95 = 104.5
        # close@13 = (108+106)/2 = 107 >= 104.5 → ARMED
        # close@14 = (100+98)/2 = 99 < 104.5 且 > 90 → 降级 WATCH
        s = detect_platform_breakout(
            ser(self.BASE_H + [108, 100], self.BASE_L + [106, 98]),
            swing_lookback=2,
            platform_window=20,
            arm_proximity_pct=0.05,
        )
        self.assertEqual(s.state, SetupState.WATCH)
        self.assertEqual(s.breakout_price, 110.0)
        self.assertEqual(s.structural_invalidation, 90.0)

    def test_atr_normalized_boundary_exposes_causal_operands(self):
        quotes = ser(self.BASE_H + [108], self.BASE_L + [106])
        history = detect_platform_breakout_history_with_diagnostics(
            quotes,
            swing_lookback=2,
            platform_window=20,
            platform_boundary_mode=ATR_NORMALIZED_BOUNDARY_MODE,
            platform_atr_period=2,
            platform_boundary_threshold_atr=1.0,
        )
        latest = history[-1]
        self.assertEqual(latest.diagnostics.platform_boundary_mode, ATR_NORMALIZED_BOUNDARY_MODE)
        self.assertEqual(latest.diagnostics.platform_atr_period, 2)
        self.assertIsNotNone(latest.diagnostics.causal_atr)
        self.assertIsNotNone(latest.diagnostics.high_cluster_width_atr)
        self.assertIsNotNone(latest.diagnostics.low_cluster_width_atr)
        self.assertEqual(latest.diagnostics.platform_boundary_threshold, 1.0)

    def test_atr_boundary_is_causal_when_future_bars_are_appended(self):
        prefix = ser(self.BASE_H + [108], self.BASE_L + [106])
        future = ser([120, 122, 124], [112, 114, 116])
        # Keep dates strictly increasing while making the future bars explicit.
        future = [q(prefix[-1].trade_date + timedelta(days=i + 1), item.high, item.low) for i, item in enumerate(future)]
        kwargs = {
            "swing_lookback": 2,
            "platform_window": 20,
            "platform_boundary_mode": ATR_NORMALIZED_BOUNDARY_MODE,
            "platform_atr_period": 2,
            "platform_boundary_threshold_atr": 1.0,
        }
        short = detect_platform_breakout_history_with_diagnostics(prefix, **kwargs)
        full = detect_platform_breakout_history_with_diagnostics(prefix + future, **kwargs)
        for before, after in zip(short, full):
            self.assertEqual(before.setup, after.setup)
            self.assertEqual(before.diagnostics.causal_atr, after.diagnostics.causal_atr)
            self.assertEqual(before.diagnostics.high_cluster_width_atr, after.diagnostics.high_cluster_width_atr)
            self.assertEqual(before.diagnostics.low_cluster_width_atr, after.diagnostics.low_cluster_width_atr)

    def test_atr_boundary_requires_positive_threshold(self):
        with self.assertRaisesRegex(ValueError, "threshold_atr"):
            detect_platform_breakout_history_with_diagnostics(
                ser(self.BASE_H, self.BASE_L),
                swing_lookback=2,
                platform_window=20,
                platform_boundary_mode=ATR_NORMALIZED_BOUNDARY_MODE,
                platform_atr_period=2,
                platform_boundary_threshold_atr=0.0,
            )


if __name__ == "__main__":
    unittest.main()

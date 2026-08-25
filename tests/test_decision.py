import unittest
from datetime import date, timedelta

from core import Quote

from trading.decision import decide_platform_breakout
from trading.models import DecisionAction, Setup, SetupState, SwingKind, SwingPoint
from trading.setup import detect_platform_breakout
from trading.swing import find_swings
from trading.risk import NO_TRADE


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


def ser_close(closes: list[float]) -> list[Quote]:
    """构造 high=low=close 的序列，用于精确控制真实波幅（TR = |close 差|）。"""
    start = date(2026, 1, 1)
    return [q(start + timedelta(days=i), c, c) for i, c in enumerate(closes)]


ENTRY_ALLOWED_CLOSES = [
    90, 94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
    94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
    94, 98, 102, 106, 110, 106, 104, 110.3,
]


class DecisionTests(unittest.TestCase):
    BASE_H = [100, 105, 110, 105, 100, 105, 110, 105, 100, 105, 110, 105, 100]
    BASE_L = [90, 95, 100, 95, 90, 95, 100, 95, 90, 95, 100, 95, 90]

    def _confirmed_setup(self, bk_h, bk_l):
        quotes = ser(self.BASE_H + bk_h, self.BASE_L + bk_l)
        setup = detect_platform_breakout(quotes, swing_lookback=2, platform_window=20)
        return quotes, setup

    def test_action_mapping_none_failed_no_trade(self):
        quotes = ser([100], [90])
        for state in (SetupState.NONE, SetupState.FAILED):
            setup = Setup("SETUP_03", state)
            d = decide_platform_breakout(quotes, setup, 1000)
            self.assertEqual(d.action, DecisionAction.NO_TRADE)

    def test_action_mapping_watch(self):
        quotes = ser([100], [90])
        setup = Setup("SETUP_03", SetupState.WATCH)
        d = decide_platform_breakout(quotes, setup, 1000)
        self.assertEqual(d.action, DecisionAction.WATCH)

    def test_action_mapping_armed_wait_confirmation(self):
        quotes = ser([100], [90])
        setup = Setup("SETUP_03", SetupState.ARMED)
        d = decide_platform_breakout(quotes, setup, 1000)
        self.assertEqual(d.action, DecisionAction.WAIT_CONFIRMATION)

    def test_confirmed_rr_low_no_trade(self):
        quotes, setup = self._confirmed_setup([115], [112])
        self.assertEqual(setup.state, SetupState.CONFIRMED)
        d = decide_platform_breakout(quotes, setup, 1000, swing_lookback=2, atr_period=2)
        self.assertEqual(d.action, DecisionAction.NO_TRADE)
        self.assertEqual(d.rr.quality, NO_TRADE)
        self.assertIsNone(d.position_size)

    def test_confirmed_chase_no_trade(self):
        # 突破 bar close 远超 Entry Zone 上沿 → 追高，NO_TRADE
        quotes, setup = self._confirmed_setup([125], [124])
        d = decide_platform_breakout(quotes, setup, 1000, swing_lookback=2, atr_period=2)
        self.assertEqual(d.action, DecisionAction.NO_TRADE)
        self.assertIsNone(d.entry_plan)

    def test_execution_stop_formula(self):
        # stop = breakout_price - atr_buffer * ATR = 110 - 0.5*15 = 102.5
        quotes, setup = self._confirmed_setup([115], [112])
        d = decide_platform_breakout(
            quotes, setup, 1000, swing_lookback=2, atr_period=2, atr_buffer=0.5
        )
        self.assertAlmostEqual(d.structural_invalidation, 90.0)
        self.assertAlmostEqual(d.execution_stop, 102.5)

    def test_targets_are_fib_extensions(self):
        # T2 = 90 + 20*1.272, T3 = 90 + 20*1.618；独立于 R/R
        quotes, setup = self._confirmed_setup([115], [112])
        d = decide_platform_breakout(quotes, setup, 1000, swing_lookback=2, atr_period=2)
        self.assertAlmostEqual(d.targets[0], 90.0 + 20.0 * 1.272)
        self.assertAlmostEqual(d.targets[1], 90.0 + 20.0 * 1.618)

    def test_no_trade_when_nearest_fib_below_2r(self):
        """历史前高 4R、但更近 Fib target <2R → quality 用最近目标 T1，必须 NO_TRADE。"""
        quotes, setup = self._confirmed_setup([115], [112])
        swings = find_swings(quotes, lookback=2)
        # 前高 237.5 → RR = (237.5-113.5)/31 ≈ 4R
        swings.append(
            SwingPoint(
                kind=SwingKind.HIGH,
                price=237.5,
                pivot_index=12,
                pivot_date=date(2026, 1, 13),
                confirmed_index=13,
                confirmed_date=date(2026, 1, 14),
            )
        )
        d = decide_platform_breakout(
            quotes, setup, 1000, swings=swings, swing_lookback=2, atr_period=2
        )
        # targets 升序：T1 = Fib 1.272 = 115.44（RR < 2）
        self.assertEqual(d.targets[0], 90.0 + 20.0 * 1.272)
        self.assertEqual(d.action, DecisionAction.NO_TRADE)
        self.assertEqual(d.rr.quality, NO_TRADE)

    def test_targets_exclude_below_entry(self):
        # 前高低于 planned_entry 应被过滤，仅剩 fib target
        quotes, setup = self._confirmed_setup([115], [112])
        swings = find_swings(quotes, lookback=2)
        swings.append(
            SwingPoint(
                kind=SwingKind.HIGH,
                price=100.0,  # 低于 planned_entry=113.5，应被过滤
                pivot_index=12,
                pivot_date=date(2026, 1, 13),
                confirmed_index=13,
                confirmed_date=date(2026, 1, 14),
            )
        )
        d = decide_platform_breakout(
            quotes, setup, 1000, swings=swings, swing_lookback=2, atr_period=2
        )
        self.assertNotIn(100.0, d.targets)

    def test_entry_allowed_real_scenario(self):
        """真实正向场景：platform [90,110]、ATR≈4、planned_entry≈110.3 → ENTRY_ALLOWED。

        证明系统不是 mathematically dead：Execution Stop 用 breakout_price - 0.5*ATR，
        risk≈2.3、reward≈5.1，RR(T1=Fib 1.272)≈2.2 达标。
        """
        quotes = ser_close(ENTRY_ALLOWED_CLOSES)
        setup = detect_platform_breakout(quotes, swing_lookback=2, platform_window=40)
        self.assertEqual(setup.state, SetupState.CONFIRMED)
        self.assertEqual(setup.breakout_price, 110.0)
        self.assertEqual(setup.structural_invalidation, 90.0)

        d = decide_platform_breakout(
            quotes, setup, 1000, swing_lookback=2, atr_period=14
        )
        self.assertEqual(d.action, DecisionAction.ENTRY_ALLOWED)
        self.assertAlmostEqual(d.entry_plan.planned_entry, 110.3)
        # execution_stop = breakout_price - 0.5*ATR ≈ 108
        self.assertAlmostEqual(d.execution_stop, 108.0, delta=0.5)
        # T1 = Fib 1.272 = 90 + 20*1.272 = 115.44
        self.assertAlmostEqual(d.targets[0], 90.0 + 20.0 * 1.272)
        # RR(T1) 应约 2.2
        self.assertGreater(d.rr.rr_ratios[0], 2.0)
        self.assertLess(d.rr.rr_ratios[0], 2.4)
        self.assertIsNotNone(d.position_size)

    def test_future_setup_no_trade(self):
        """CONFIRMED 但 confirmed_index 晚于决策时刻（未来 Setup）→ 不得进入风险计算。"""
        quotes, setup = self._confirmed_setup([115], [112])
        # 伪造一个 confirmed_index 在未来的 Setup
        future_setup = Setup(
            setup_type="SETUP_03",
            state=SetupState.CONFIRMED,
            breakout_price=110.0,
            structural_invalidation=90.0,
            detected_index=12,
            state_entered_index=13,
            confirmed_index=99,  # 晚于 decision_index
        )
        d = decide_platform_breakout(
            quotes, future_setup, 1000, swing_lookback=2, atr_period=2
        )
        self.assertEqual(d.action, DecisionAction.NO_TRADE)
        self.assertIsNone(d.entry_plan)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date

from core import Quote

from trading.models import (
    FibonacciLevels,
    MarketStructure,
    PositionSize,
    RiskReward,
    SwingKind,
    SwingPoint,
    SwingState,
    Trend,
    validate_quote_series,
)
from trading.indicators import (
    atr,
    closes,
    ema,
    highs,
    lows,
    rsi,
    rolling_high,
    rolling_low,
    sma,
    true_range,
)
from trading.swing import find_swings
from trading.structure import market_structure
from trading.fibonacci import fibonacci_levels
from trading.risk import (
    HIGH_ASYMMETRY,
    HIGH_QUALITY,
    NORMAL,
    NO_TRADE,
    position_size,
    risk_reward,
    rr_quality,
)


def q(
    day: date,
    o: float = 100.0,
    h: float = 110.0,
    l: float = 95.0,
    c: float = 105.0,
    v: float = 1_000_000.0,
    symbol: str = "TEST",
    market: str = "US",
) -> Quote:
    return Quote(
        symbol=symbol,
        name="测试标的",
        market=market,
        trade_date=day,
        source="test",
        open=o,
        high=h,
        low=l,
        close=c,
        preclose=None,
        pct_change=None,
        volume=v,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def series(
    closes: list[float],
    start: date = date(2026, 1, 1),
    ohl: tuple[float, float, float] = (100.0, 110.0, 95.0),
) -> list[Quote]:
    """按工作日构造连续序列，close 由参数给定，OHL 用固定三元组。"""
    from datetime import timedelta

    o, h, l = ohl
    out = []
    for i, c in enumerate(closes):
        out.append(q(start + timedelta(days=i), o=o, h=h, l=l, c=c))
    return out


class ModelValidationTests(unittest.TestCase):
    def test_accepts_valid_series(self):
        quotes = series([100.0, 101.0, 102.0])
        validate_quote_series(quotes)  # 不抛异常

    def test_rejects_empty_series(self):
        with self.assertRaises(ValueError):
            validate_quote_series([])

    def test_rejects_mixed_symbol(self):
        quotes = series([100.0, 101.0])
        quotes[1] = q(date(2026, 1, 2), c=101.0, symbol="OTHER")
        with self.assertRaises(ValueError):
            validate_quote_series(quotes)

    def test_rejects_mixed_market(self):
        quotes = series([100.0, 101.0])
        quotes[1] = q(date(2026, 1, 2), c=101.0, market="CN")
        with self.assertRaises(ValueError):
            validate_quote_series(quotes)

    def test_rejects_duplicate_date(self):
        quotes = series([100.0, 101.0, 102.0])
        quotes[2] = q(date(2026, 1, 2), c=102.0)
        with self.assertRaises(ValueError):
            validate_quote_series(quotes)

    def test_rejects_non_ascending_date(self):
        quotes = series([100.0, 101.0, 102.0])
        quotes[2] = q(date(2025, 12, 31), c=102.0)
        with self.assertRaises(ValueError):
            validate_quote_series(quotes)

    def test_swing_state_derived_from_confirmed_index(self):
        provisional = SwingPoint(
            kind=SwingKind.HIGH, price=110.0, pivot_index=3,
            pivot_date=date(2026, 1, 4), confirmed_index=None, confirmed_date=None,
        )
        confirmed = SwingPoint(
            kind=SwingKind.HIGH, price=110.0, pivot_index=3,
            pivot_date=date(2026, 1, 4), confirmed_index=7,
            confirmed_date=date(2026, 1, 8),
        )
        self.assertEqual(provisional.state, SwingState.PROVISIONAL)
        self.assertEqual(confirmed.state, SwingState.CONFIRMED)
        self.assertEqual(confirmed.confirmed_at, 7)


class IndicatorTests(unittest.TestCase):
    def test_true_range_without_prev_close(self):
        self.assertEqual(true_range(110.0, 95.0, None), 15.0)

    def test_true_range_with_prev_close(self):
        # high-low=7, |high-prev|=5, |low-prev|=2 -> 7
        self.assertEqual(true_range(105.0, 98.0, 100.0), 7.0)
        # gap up 覆盖 high-low
        self.assertEqual(true_range(110.0, 105.0, 100.0), 10.0)

    def test_atr_warmup_and_wilder(self):
        # period=2：warm-up 索引 0..1 为 None，索引 2 起有值
        quotes = [
            q(date(2026, 1, 1), h=110.0, l=95.0, c=100.0),
            q(date(2026, 1, 2), h=105.0, l=98.0, c=102.0),
            q(date(2026, 1, 3), h=108.0, l=101.0, c=107.0),
        ]
        result = atr(quotes, period=2)
        self.assertEqual(len(result), 3)
        self.assertIsNone(result[0])
        self.assertIsNone(result[1])
        # TR1=7, TR2=7 -> ATR2 = 7
        self.assertAlmostEqual(result[2], 7.0)

    def test_atr_aligned_length_and_short_series(self):
        quotes = series([100.0, 101.0])
        result = atr(quotes, period=14)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(x is None for x in result))

    def test_rsi_all_gains_is_100(self):
        quotes = series([100.0, 101.0, 102.0, 103.0])
        result = rsi(quotes, period=2)
        self.assertEqual(len(result), 4)
        self.assertIsNone(result[0])
        self.assertIsNone(result[1])
        self.assertAlmostEqual(result[2], 100.0)
        self.assertAlmostEqual(result[3], 100.0)

    def test_rsi_all_losses_is_0(self):
        quotes = series([103.0, 102.0, 101.0, 100.0])
        result = rsi(quotes, period=2)
        self.assertAlmostEqual(result[2], 0.0)
        self.assertAlmostEqual(result[3], 0.0)

    def test_rsi_mixed_wilder(self):
        quotes = series([100.0, 110.0, 105.0])
        result = rsi(quotes, period=2)
        # avg_gain=(10+0)/2=5, avg_loss=(0+5)/2=2.5, RS=2, RSI=66.67
        self.assertAlmostEqual(result[2], 100.0 - 100.0 / 3.0, places=4)

    def test_sma_aligned(self):
        result = sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        self.assertEqual(result, [None, None, 2.0, 3.0, 4.0])

    def test_ema_standard_alpha(self):
        result = ema([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        self.assertEqual(result[:2], [None, None])
        self.assertAlmostEqual(result[2], 2.0)
        self.assertAlmostEqual(result[3], 3.0)
        self.assertAlmostEqual(result[4], 4.0)

    def test_ema_short_series_all_none(self):
        self.assertEqual(ema([1.0, 2.0], 3), [None, None])

    def test_rolling_high_low(self):
        values = [1.0, 3.0, 2.0, 4.0]
        self.assertEqual(rolling_high(values, 2), [None, 3.0, 3.0, 4.0])
        self.assertEqual(rolling_low(values, 2), [None, 1.0, 2.0, 2.0])

    def test_closes_highs_lows(self):
        quotes = series([100.0, 101.0, 102.0])
        self.assertEqual(closes(quotes), [100.0, 101.0, 102.0])
        self.assertEqual(highs(quotes), [110.0, 110.0, 110.0])
        self.assertEqual(lows(quotes), [95.0, 95.0, 95.0])

    def test_period_validation(self):
        quotes = series([100.0, 101.0])
        with self.assertRaises(ValueError):
            atr(quotes, period=0)
        with self.assertRaises(ValueError):
            rsi(quotes, period=-1)
        with self.assertRaises(ValueError):
            sma([1.0], 0)


def series_ohlc(
    highs: list[float],
    lows: list[float],
    start: date = date(2026, 1, 1),
) -> list[Quote]:
    """按工作日构造指定 high/low 序列，close 取高低中值。"""
    from datetime import timedelta

    out = []
    for i, (h, l) in enumerate(zip(highs, lows)):
        out.append(q(start + timedelta(days=i), h=h, l=l, c=(h + l) / 2))
    return out


class SwingTests(unittest.TestCase):
    # lookback=2 的示例序列：HIGH@2, LOW@4, HIGH@6
    HIGHS = [10, 11, 12, 11, 10, 11, 12, 11, 10]
    LOWS = [8, 9, 10, 9, 8, 9, 10, 9, 8]

    def test_finds_alternating_swings(self):
        quotes = series_ohlc(self.HIGHS, self.LOWS)
        swings = find_swings(quotes, lookback=2)
        kinds = [s.kind for s in swings]
        self.assertEqual(kinds, [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH])
        self.assertEqual([s.pivot_index for s in swings], [2, 4, 6])

    def test_last_swing_is_provisional(self):
        quotes = series_ohlc(self.HIGHS, self.LOWS)
        swings = find_swings(quotes, lookback=2)
        self.assertEqual(swings[-1].state, SwingState.PROVISIONAL)
        self.assertIsNone(swings[-1].confirmed_index)
        self.assertEqual(swings[0].state, SwingState.CONFIRMED)
        self.assertEqual(swings[1].state, SwingState.CONFIRMED)

    def test_confirmed_index_is_next_pivot_plus_lookback(self):
        quotes = series_ohlc(self.HIGHS, self.LOWS)
        swings = find_swings(quotes, lookback=2)
        # HIGH@2 被 LOW@4 确认 -> 4 + 2 = 6
        self.assertEqual(swings[0].confirmed_index, 6)
        # LOW@4 被 HIGH@6 确认 -> 6 + 2 = 8
        self.assertEqual(swings[1].confirmed_index, 8)

    def test_as_of_t_confirmed_swing_never_changes(self):
        """核心 look-ahead 测试：截断到 confirmed_index，确认的 swing 字段不变。"""
        quotes = series_ohlc(self.HIGHS, self.LOWS)
        full = find_swings(quotes, lookback=2)
        for swing in full:
            if swing.state is not SwingState.CONFIRMED:
                continue
            t = swing.confirmed_index
            truncated = find_swings(quotes[: t + 1], lookback=2)
            match = next(
                (s for s in truncated if s.pivot_index == swing.pivot_index), None
            )
            self.assertIsNotNone(match, f"截断后丢失 pivot@{swing.pivot_index}")
            self.assertEqual(match.kind, swing.kind)
            self.assertEqual(match.price, swing.price)
            self.assertEqual(match.confirmed_index, swing.confirmed_index)
            self.assertEqual(match.state, SwingState.CONFIRMED)

    def test_short_series_returns_empty(self):
        quotes = series_ohlc([10, 11, 12, 11, 10], [8, 9, 10, 9, 8])
        self.assertEqual(find_swings(quotes, lookback=3), [])

    def test_lookback_validation(self):
        quotes = series_ohlc(self.HIGHS, self.LOWS)
        with self.assertRaises(ValueError):
            find_swings(quotes, lookback=0)

    def test_excursion_filter_removes_noise_swing(self):
        # 构造一个「大 swing 之间夹小噪声」的序列，用百分比过滤
        highs = [10, 11, 12, 11, 10, 11, 12, 11, 10]
        lows = [8, 9, 10, 9, 8, 9, 10, 9, 8]
        quotes = series_ohlc(highs, lows)
        # 默认不过滤：3 个 swing
        self.assertEqual(len(find_swings(quotes, lookback=2)), 3)
        # 用极小 excursion 不应删除 swing（摆幅足够大）
        filtered = find_swings(quotes, lookback=2, min_excursion_pct=0.01)
        self.assertEqual(len(filtered), 3)

    def test_tie_high_picks_earliest(self):
        # 两个相邻 bar 相同 high：应识别更早的那个为 swing high
        highs = [10, 11, 12, 12, 11, 10, 11, 12, 11, 10]
        lows = [8, 9, 10, 10, 9, 8, 9, 10, 9, 8]
        quotes = series_ohlc(highs, lows)
        swings = find_swings(quotes, lookback=2)
        highs_only = [s for s in swings if s.kind is SwingKind.HIGH]
        self.assertEqual([s.pivot_index for s in highs_only], [2, 7])

    def test_confirmed_swing_not_repainted_by_extreme_dup(self):
        """回归：连续同向 raw pivot 中，更极端者不得回填修改已 CONFIRMED swing。

        highs 在 index 2 见顶后一路下行，lows 在 index 4、7 形成两个连续同向
        LOW（中间无 HIGH pivot）。修复前 dedupe 会用 LOW@7 替换 LOW@4，把
        HIGH@2 的 confirmed_index 从 6 改成 9（confirmed repaint）。
        """
        highs = [10, 11, 12, 11, 10, 9, 8, 7, 6, 5]
        lows = [8, 9, 10, 8, 4, 6, 7, 3, 4, 4.5]
        full = series_ohlc(highs, lows)
        full_by_idx = {s.pivot_index: s for s in find_swings(full, lookback=2)}

        # 截断到 t=6（含 index 6）：HIGH@2 已被 LOW@4 确认
        truncated = series_ohlc(highs[:7], lows[:7])
        trunc_confirmed = [
            s for s in find_swings(truncated, lookback=2)
            if s.state is SwingState.CONFIRMED
        ]

        self.assertTrue(any(s.pivot_index == 2 for s in trunc_confirmed))
        for s_trunc in trunc_confirmed:
            s_full = full_by_idx[s_trunc.pivot_index]
            self.assertEqual(s_full.kind, s_trunc.kind)
            self.assertEqual(s_full.price, s_trunc.price)
            self.assertEqual(s_full.pivot_index, s_trunc.pivot_index)
            self.assertEqual(s_full.confirmed_index, s_trunc.confirmed_index)
            self.assertEqual(s_full.confirmed_date, s_trunc.confirmed_date)


def sp(
    kind: SwingKind,
    price: float,
    idx: int,
    confirmed_idx: int | None = None,
) -> SwingPoint:
    """构造 SwingPoint；confirmed_idx=None 表示 PROVISIONAL。"""
    return SwingPoint(
        kind=kind,
        price=price,
        pivot_index=idx,
        pivot_date=date(2026, 1, 1 + idx),
        confirmed_index=confirmed_idx,
        confirmed_date=date(2026, 1, 1 + confirmed_idx) if confirmed_idx is not None else None,
    )


class StructureTests(unittest.TestCase):
    def _structure(self, highs, lows):
        swings = [sp(SwingKind.HIGH, p, i * 2, i * 2 + 1) for i, p in enumerate(highs)]
        swings += [sp(SwingKind.LOW, p, i * 2 + 1, i * 2 + 2) for i, p in enumerate(lows)]
        return market_structure(swings)

    def test_uptrend(self):
        struct = self._structure([100.0, 110.0], [80.0, 90.0])
        self.assertEqual(struct.trend, Trend.UPTREND)

    def test_downtrend(self):
        struct = self._structure([110.0, 100.0], [90.0, 80.0])
        self.assertEqual(struct.trend, Trend.DOWNTREND)

    def test_range_contraction(self):
        struct = self._structure([110.0, 105.0], [90.0, 92.0])
        self.assertEqual(struct.trend, Trend.RANGE)

    def test_transition_expansion(self):
        struct = self._structure([100.0, 110.0], [90.0, 85.0])
        self.assertEqual(struct.trend, Trend.TRANSITION)

    def test_unknown_when_insufficient_swings(self):
        struct = self._structure([100.0], [90.0])
        self.assertEqual(struct.trend, Trend.UNKNOWN)

    def test_excludes_provisional_swings(self):
        # 只有 1 个 CONFIRMED high + 1 个 PROVISIONAL high，不足以分类 -> UNKNOWN
        swings = [
            sp(SwingKind.HIGH, 100.0, 0, 1),
            sp(SwingKind.HIGH, 110.0, 2, None),  # PROVISIONAL，应被排除
            sp(SwingKind.LOW, 90.0, 1, 3),
        ]
        struct = market_structure(swings)
        self.assertEqual(struct.trend, Trend.UNKNOWN)
        self.assertEqual(len(struct.highs), 1)
        self.assertEqual(len(struct.lows), 1)


class FibonacciTests(unittest.TestCase):
    def test_retracements(self):
        high = sp(SwingKind.HIGH, 100.0, 2, 4)
        low = sp(SwingKind.LOW, 60.0, 4, 6)
        levels = fibonacci_levels(high, low)
        self.assertEqual(levels.swing_high, 100.0)
        self.assertEqual(levels.swing_low, 60.0)
        self.assertAlmostEqual(levels.retracements["0.5"], 80.0)
        self.assertAlmostEqual(levels.retracements["0.618"], 100.0 - 40.0 * 0.618)

    def test_extensions(self):
        high = sp(SwingKind.HIGH, 100.0, 2, 4)
        low = sp(SwingKind.LOW, 60.0, 4, 6)
        levels = fibonacci_levels(high, low)
        self.assertAlmostEqual(levels.extensions["1.618"], 60.0 + 40.0 * 1.618)

    def test_same_kind_raises(self):
        high1 = sp(SwingKind.HIGH, 100.0, 0, 1)
        high2 = sp(SwingKind.HIGH, 90.0, 2, 3)
        with self.assertRaises(ValueError):
            fibonacci_levels(high1, high2)

    def test_zero_range_raises(self):
        high = sp(SwingKind.HIGH, 100.0, 0, 1)
        low = sp(SwingKind.LOW, 100.0, 1, 2)
        with self.assertRaises(ValueError):
            fibonacci_levels(high, low)


class RiskTests(unittest.TestCase):
    def test_risk_reward_long(self):
        rr = risk_reward(entry=100.0, execution_stop=90.0, targets=[120.0, 130.0])
        self.assertEqual(rr.risk_per_share, 10.0)
        self.assertEqual(rr.rr_ratios, (2.0, 3.0))
        self.assertEqual(rr.quality, NORMAL)

    def test_risk_reward_short(self):
        rr = risk_reward(entry=100.0, execution_stop=110.0, targets=[80.0])
        self.assertEqual(rr.risk_per_share, 10.0)
        self.assertEqual(rr.rr_ratios, (2.0,))

    def test_quality_boundaries(self):
        self.assertEqual(rr_quality(1.9), NO_TRADE)
        self.assertEqual(rr_quality(2.0), NORMAL)
        self.assertEqual(rr_quality(2.9), NORMAL)
        self.assertEqual(rr_quality(3.0), HIGH_QUALITY)
        self.assertEqual(rr_quality(5.0), HIGH_QUALITY)
        self.assertEqual(rr_quality(5.1), HIGH_ASYMMETRY)

    def test_risk_reward_stop_equals_entry_raises(self):
        with self.assertRaises(ValueError):
            risk_reward(entry=100.0, execution_stop=100.0, targets=[120.0])

    def test_risk_reward_empty_targets_raises(self):
        with self.assertRaises(ValueError):
            risk_reward(entry=100.0, execution_stop=90.0, targets=[])

    def test_position_size_basic(self):
        ps = position_size(risk_capital=1000.0, entry=100.0, execution_stop=90.0)
        self.assertEqual(ps.risk_per_share, 10.0)
        self.assertEqual(ps.theoretical_quantity, 100.0)
        self.assertEqual(ps.max_loss, 1000.0)

    def test_position_size_stop_equals_entry_raises(self):
        with self.assertRaises(ValueError):
            position_size(risk_capital=1000.0, entry=100.0, execution_stop=100.0)

    def test_position_size_negative_risk_capital_raises(self):
        with self.assertRaises(ValueError):
            position_size(risk_capital=-1.0, entry=100.0, execution_stop=90.0)


class HardeningTests(unittest.TestCase):
    """Phase 1.1 加固：补夜间审计发现的测试缺口。

    覆盖：excursion filter（pct/atr 分支）、PROVISIONAL 可变性、confirmed 冻结、
    Market Structure as-of t 稳定性。
    """

    # 噪声 swing 序列：HIGH@2 冲高后几乎未回落，excursion 极小
    NOISE_HIGHS = [10, 11, 12, 11.7, 11.8, 11, 10]
    NOISE_LOWS = [8, 9, 10, 11.5, 11.6, 9, 8]

    def test_excursion_pct_filters_noise_swing(self):
        quotes = series_ohlc(self.NOISE_HIGHS, self.NOISE_LOWS)
        # 无过滤：识别出 1 个 HIGH@2
        self.assertEqual(len(find_swings(quotes, lookback=2)), 1)
        # excursion = 12 - 11.5 = 0.5 < 0.05 * 12 = 0.6，噪声被过滤
        filtered = find_swings(quotes, lookback=2, min_excursion_pct=0.05)
        self.assertEqual(filtered, [])

    def test_excursion_atr_filters_noise_swing(self):
        quotes = series_ohlc(self.NOISE_HIGHS, self.NOISE_LOWS)
        # ATR(period=2)@2 = 2.0；excursion=0.5 < 1.0 * 2.0，被过滤
        filtered = find_swings(
            quotes, lookback=2, min_excursion_atr=1.0, atr_period=2
        )
        self.assertEqual(filtered, [])

    def test_provisional_becomes_confirmed_with_new_data(self):
        s1_highs = [10, 11, 12, 11, 10, 11, 12, 11, 10]
        s1_lows = [8, 9, 10, 9, 8, 9, 10, 9, 8]
        s1 = series_ohlc(s1_highs, s1_lows)
        last1 = find_swings(s1, lookback=2)[-1]
        # 追加前：最后一个 swing HIGH@6 是 PROVISIONAL
        self.assertEqual(last1.pivot_index, 6)
        self.assertEqual(last1.state, SwingState.PROVISIONAL)

        # 追加 4 根，出现 LOW@9 反向 pivot，确认 HIGH@6
        s2 = series_ohlc(s1_highs + [9, 10, 11, 12], s1_lows + [7, 8, 9, 10])
        swings2 = find_swings(s2, lookback=2)
        high6 = next(s for s in swings2 if s.pivot_index == 6)
        self.assertEqual(high6.state, SwingState.CONFIRMED)
        self.assertEqual(high6.confirmed_index, 11)

    def test_confirmed_swing_fields_frozen_after_append(self):
        s1_highs = [10, 11, 12, 11, 10, 11, 12, 11, 10]
        s1_lows = [8, 9, 10, 9, 8, 9, 10, 9, 8]
        s1 = series_ohlc(s1_highs, s1_lows)
        confirmed1 = {
            s.pivot_index: s
            for s in find_swings(s1, lookback=2)
            if s.state is SwingState.CONFIRMED
        }

        s2 = series_ohlc(s1_highs + [9, 10, 11, 12], s1_lows + [7, 8, 9, 10])
        confirmed2 = {
            s.pivot_index: s
            for s in find_swings(s2, lookback=2)
            if s.state is SwingState.CONFIRMED
        }

        # 追加数据前已 confirmed 的 swing，字段必须完全一致
        for idx in (2, 4):
            a, b = confirmed1[idx], confirmed2[idx]
            self.assertEqual(a.kind, b.kind)
            self.assertEqual(a.price, b.price)
            self.assertEqual(a.pivot_index, b.pivot_index)
            self.assertEqual(a.confirmed_index, b.confirmed_index)

    def test_market_structure_as_of_t_not_affected_by_future(self):
        as_of_t4 = [
            sp(SwingKind.HIGH, 100.0, 0, 1),
            sp(SwingKind.LOW, 90.0, 1, 2),
            sp(SwingKind.HIGH, 110.0, 2, 3),
            sp(SwingKind.LOW, 95.0, 3, 4),
        ]
        struct_before = market_structure(as_of_t4)
        self.assertEqual(struct_before.trend, Trend.UPTREND)

        # 追加未来 confirmed swing（confirmed_index > 4），暗示趋势反转
        future = as_of_t4 + [
            sp(SwingKind.HIGH, 90.0, 4, 5),
            sp(SwingKind.LOW, 80.0, 5, 6),
        ]
        # as-of t=4 视图：只取 confirmed_index <= 4 的 swing
        as_of_t4_after = [
            s
            for s in future
            if s.confirmed_index is not None and s.confirmed_index <= 4
        ]
        struct_after = market_structure(as_of_t4_after)
        self.assertEqual(struct_after.trend, Trend.UPTREND)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from core import Quote
from trading.decision import decide_platform_breakout
from trading.models import DecisionAction, SetupState
from trading.replay import (
    replay_setup03_history,
    replay_setup03_symbols,
    replay_summary_rows,
)
from trading.setup import detect_platform_breakout


def q(day: date, h: float, l: float, symbol: str = "T") -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
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


def ser(highs: list[float], lows: list[float], symbol: str = "T") -> list[Quote]:
    start = date(2026, 1, 1)
    return [
        q(start + timedelta(days=i), h, l, symbol)
        for i, (h, l) in enumerate(zip(highs, lows))
    ]


class Setup03ReplayTests(unittest.TestCase):
    BASE_H = [100, 105, 110, 105, 100, 105, 110, 105, 100, 105, 110, 105, 100]
    BASE_L = [90, 95, 100, 95, 90, 95, 100, 95, 90, 95, 100, 95, 90]

    def test_replay_uses_only_as_of_prefix_for_each_day(self):
        quotes = ser(self.BASE_H + [115], self.BASE_L + [112])
        seen_lengths = []

        def spy_detect(as_of_quotes, **kwargs):
            seen_lengths.append(len(as_of_quotes))
            return detect_platform_breakout(as_of_quotes, **kwargs)

        with patch("trading.replay.detect_platform_breakout", side_effect=spy_detect):
            replay_setup03_history(
                quotes,
                risk_capital=1000.0,
                setup_parameters={"swing_lookback": 2, "platform_window": 20},
                decision_parameters={"swing_lookback": 2, "atr_period": 2},
            )

        self.assertEqual(seen_lengths, list(range(1, len(quotes) + 1)))

    def test_future_breakout_does_not_change_past_replay_states(self):
        quotes = ser(self.BASE_H + [115], self.BASE_L + [112])
        report = replay_setup03_history(
            quotes,
            risk_capital=1000.0,
            setup_parameters={"swing_lookback": 2, "platform_window": 20},
            decision_parameters={"swing_lookback": 2, "atr_period": 2},
        )

        pre_breakout = report.days[-2]
        breakout = report.days[-1]
        self.assertEqual(pre_breakout.setup_state, SetupState.WATCH)
        self.assertEqual(breakout.setup_state, SetupState.CONFIRMED)
        self.assertEqual(
            report.state_dates[SetupState.WATCH][-1], pre_breakout.trade_date
        )
        self.assertNotIn(pre_breakout.trade_date, report.confirmed_event_dates)

    def test_decision_runs_only_on_confirmed_replay_days(self):
        quotes = ser(self.BASE_H + [115], self.BASE_L + [112])
        decision_dates = []

        def spy_decide(as_of_quotes, setup, risk_capital, **kwargs):
            decision_dates.append(as_of_quotes[-1].trade_date)
            return decide_platform_breakout(as_of_quotes, setup, risk_capital, **kwargs)

        with patch("trading.replay.decide_platform_breakout", side_effect=spy_decide):
            report = replay_setup03_history(
                quotes,
                risk_capital=1000.0,
                setup_parameters={"swing_lookback": 2, "platform_window": 20},
                decision_parameters={"swing_lookback": 2, "atr_period": 2},
            )

        self.assertEqual(decision_dates, list(report.confirmed_event_dates))
        self.assertEqual(
            sum(report.decision_counts.values()),
            len(report.confirmed_event_dates),
        )
        self.assertEqual(report.decision_counts[DecisionAction.NO_TRADE], 1)

    def test_confirmed_terminal_state_does_not_repeat_confirmed_event(self):
        quotes = ser(
            self.BASE_H + [115, 116, 117, 118],
            self.BASE_L + [112, 113, 114, 115],
        )
        decision_dates = []

        def spy_decide(as_of_quotes, setup, risk_capital, **kwargs):
            decision_dates.append(as_of_quotes[-1].trade_date)
            return decide_platform_breakout(as_of_quotes, setup, risk_capital, **kwargs)

        with patch("trading.replay.decide_platform_breakout", side_effect=spy_decide):
            report = replay_setup03_history(
                quotes,
                risk_capital=1000.0,
                setup_parameters={"swing_lookback": 2, "platform_window": 20},
                decision_parameters={"swing_lookback": 2, "atr_period": 2},
            )

        self.assertGreaterEqual(report.state_day_counts[SetupState.CONFIRMED], 4)
        self.assertEqual(len(report.confirmed_event_dates), 1)
        self.assertEqual(len(decision_dates), 1)
        self.assertEqual(decision_dates, list(report.confirmed_event_dates))

    def test_failed_terminal_state_does_not_repeat_failed_event(self):
        quotes = ser(
            self.BASE_H + [85, 84, 83, 82],
            self.BASE_L + [82, 81, 80, 79],
        )
        report = replay_setup03_history(
            quotes,
            risk_capital=1000.0,
            setup_parameters={"swing_lookback": 2, "platform_window": 20},
            decision_parameters={"swing_lookback": 2, "atr_period": 2},
        )

        self.assertGreaterEqual(report.state_day_counts[SetupState.FAILED], 4)
        self.assertEqual(len(report.failed_event_dates), 1)
        self.assertEqual(report.failed_event_dates[0], date(2026, 1, 14))

    def test_summary_rows_include_counts_and_state_dates_per_symbol(self):
        reports = replay_setup03_symbols(
            {
                "A": ser(self.BASE_H, self.BASE_L, "A"),
                "B": ser(self.BASE_H + [115], self.BASE_L + [112], "B"),
            },
            risk_capital=1000.0,
            setup_parameters={"swing_lookback": 2, "platform_window": 20},
            decision_parameters={"swing_lookback": 2, "atr_period": 2},
        )

        rows = replay_summary_rows(reports.values())
        by_symbol = {row["统一代码"]: row for row in rows}
        self.assertEqual(by_symbol["A"]["CONFIRMED事件次数"], 0)
        self.assertEqual(by_symbol["B"]["CONFIRMED事件次数"], 1)
        self.assertIn("2026-01-13", by_symbol["B"]["WATCH状态日期"])
        self.assertEqual(by_symbol["B"]["NO_TRADE事件次数"], 1)
        self.assertEqual(by_symbol["B"]["ENTRY_ALLOWED事件次数"], 0)


if __name__ == "__main__":
    unittest.main()

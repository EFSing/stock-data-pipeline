import unittest
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch

from core import Quote
from main import decision_row, evaluate_set03_decision
from trading.decision import decide_platform_breakout
from trading.events import Setup03Evaluation
from trading.models import Decision, DecisionAction, Setup, SetupState
from trading.replay import (
    replay_event_rows,
    replay_setup03_history,
    replay_setup03_symbols,
    replay_summary_rows,
    validate_replay_history,
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

        with patch("trading.events.detect_platform_breakout", side_effect=spy_detect):
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

        with patch("trading.events.decide_platform_breakout", side_effect=spy_decide):
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

    def test_confirmed_event_carries_same_as_of_signal_context(self):
        quotes = ser(self.BASE_H + [115], self.BASE_L + [112])
        report = replay_setup03_history(
            quotes,
            risk_capital=1000.0,
            setup_parameters={"swing_lookback": 2, "platform_window": 20},
            decision_parameters={"swing_lookback": 2, "atr_period": 2},
        )

        event = report.events[-1]
        self.assertEqual(event.event_type, SetupState.CONFIRMED)
        self.assertEqual(event.signal_date, event.trade_date)
        self.assertEqual(event.confirmed_date, event.trade_date)
        self.assertEqual(event.signal_close, quotes[-1].close)
        self.assertIsNotNone(event.signal_atr)
        row = replay_event_rows(report, "yfinance", "sha256:test", "{}")[-1]
        self.assertEqual(row["signal_date"], event.signal_date)
        self.assertEqual(row["confirmed_date"], event.confirmed_date)
        self.assertEqual(row["signal_close"], event.signal_close)
        self.assertEqual(row["ATR"], event.signal_atr)

    def test_confirmed_terminal_state_does_not_repeat_confirmed_event(self):
        quotes = ser(
            self.BASE_H + [115, 116, 117, 118],
            self.BASE_L + [112, 113, 114, 115],
        )
        decision_dates = []

        def spy_decide(as_of_quotes, setup, risk_capital, **kwargs):
            decision_dates.append(as_of_quotes[-1].trade_date)
            return decide_platform_breakout(as_of_quotes, setup, risk_capital, **kwargs)

        with patch("trading.events.decide_platform_breakout", side_effect=spy_decide):
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


class ReplayLifecycleTests(unittest.TestCase):
    BASE_H = Setup03ReplayTests.BASE_H
    BASE_L = Setup03ReplayTests.BASE_L

    def _evaluation(
        self,
        day: date,
        state: SetupState,
        detected_index: int | None,
        state_entered_index: int | None,
        confirmed_index: int | None = None,
        event_type: SetupState | None = None,
    ) -> Setup03Evaluation:
        setup = Setup(
            "SETUP_03",
            state,
            110.0 if detected_index is not None else None,
            90.0 if detected_index is not None else None,
            detected_index,
            state_entered_index,
            confirmed_index,
        )
        decision = (
            Decision(DecisionAction.NO_TRADE, None, 90.0, None, (), None, None)
            if event_type is SetupState.CONFIRMED
            else None
        )
        return Setup03Evaluation(
            setup,
            event_type,
            day if event_type else None,
            day if confirmed_index is not None else None,
            decision,
        )

    def _two_lifecycle_evaluations(
        self,
        quotes: list[Quote],
        first: SetupState,
        second: SetupState,
    ) -> list[Setup03Evaluation]:
        first_confirmed = 2 if first is SetupState.CONFIRMED else None
        second_confirmed = 6 if second is SetupState.CONFIRMED else None
        return [
            self._evaluation(quotes[0].trade_date, SetupState.NONE, None, None),
            self._evaluation(quotes[1].trade_date, SetupState.WATCH, 1, 1),
            self._evaluation(
                quotes[2].trade_date, first, 1, 2, first_confirmed, first
            ),
            self._evaluation(
                quotes[3].trade_date, first, 1, 2, first_confirmed
            ),
            self._evaluation(quotes[4].trade_date, SetupState.WATCH, 4, 4),
            self._evaluation(quotes[5].trade_date, SetupState.WATCH, 4, 4),
            self._evaluation(
                quotes[6].trade_date, second, 4, 6, second_confirmed, second
            ),
            self._evaluation(
                quotes[7].trade_date, second, 4, 6, second_confirmed
            ),
        ]

    def test_all_terminal_combinations_form_two_strictly_ordered_events(self):
        quotes = ser([100] * 8, [90] * 8)
        combinations = (
            (SetupState.CONFIRMED, SetupState.CONFIRMED),
            (SetupState.FAILED, SetupState.FAILED),
            (SetupState.CONFIRMED, SetupState.FAILED),
            (SetupState.FAILED, SetupState.CONFIRMED),
        )
        for first, second in combinations:
            with self.subTest(first=first.value, second=second.value):
                evaluations = self._two_lifecycle_evaluations(
                    quotes, first, second
                )
                with patch(
                    "trading.replay.evaluate_setup03_event",
                    side_effect=evaluations,
                ):
                    report = replay_setup03_history(quotes, 1000.0)

                self.assertEqual(
                    [event.event_type for event in report.events],
                    [first, second],
                )
                event_dates = [event.trade_date for event in report.events]
                self.assertEqual(len(event_dates), len(set(event_dates)))
                self.assertTrue(
                    all(a < b for a, b in zip(event_dates, event_dates[1:]))
                )
                for event in report.events:
                    index = quotes.index(
                        next(q for q in quotes if q.trade_date == event.trade_date)
                    )
                    if event.event_type is SetupState.CONFIRMED:
                        self.assertEqual(event.setup.confirmed_index, index)
                    else:
                        self.assertEqual(event.setup.state_entered_index, index)

    def test_real_core_replays_all_two_lifecycle_terminal_combinations(self):
        second_h = [80, 85, 90, 85, 80, 85, 90, 85, 80, 85, 90, 85, 80] * 2
        second_l = [60, 65, 70, 65, 60, 65, 70, 65, 60, 65, 70, 65, 60] * 2
        first_terminal = {
            SetupState.CONFIRMED: (115, 112),
            SetupState.FAILED: (85, 82),
        }
        second_terminal = {
            SetupState.CONFIRMED: (95, 92),
            SetupState.FAILED: (55, 52),
        }
        combinations = (
            (SetupState.CONFIRMED, SetupState.CONFIRMED),
            (SetupState.FAILED, SetupState.FAILED),
            (SetupState.CONFIRMED, SetupState.FAILED),
            (SetupState.FAILED, SetupState.CONFIRMED),
        )
        setup_parameters = {
            "swing_lookback": 2,
            "platform_window": 20,
            "platform_tolerance_pct": 0.05,
            "arm_proximity_pct": 0.0,
        }
        decision_parameters = {"swing_lookback": 2, "atr_period": 2}
        for first, second in combinations:
            with self.subTest(first=first.value, second=second.value):
                first_h, first_l = first_terminal[first]
                second_end_h, second_end_l = second_terminal[second]
                quotes = ser(
                    self.BASE_H + [first_h] + second_h + [second_end_h],
                    self.BASE_L + [first_l] + second_l + [second_end_l],
                )
                report = replay_setup03_history(
                    quotes,
                    1000.0,
                    setup_parameters,
                    decision_parameters,
                )

                self.assertEqual(
                    [event.event_type for event in report.events],
                    [first, second],
                )
                self.assertGreater(
                    report.events[1].setup.detected_index,
                    report.events[0].setup.state_entered_index,
                )
                event_dates = [event.trade_date for event in report.events]
                self.assertEqual(len(event_dates), len(set(event_dates)))
                self.assertTrue(event_dates[0] < event_dates[1])
                for event in report.events:
                    event_index = next(
                        index
                        for index, quote in enumerate(quotes)
                        if quote.trade_date == event.trade_date
                    )
                    terminal_index = (
                        event.setup.confirmed_index
                        if event.event_type is SetupState.CONFIRMED
                        else event.setup.state_entered_index
                    )
                    self.assertEqual(terminal_index, event_index)

    def test_watch_armed_watch_confirmed_emits_only_confirmation(self):
        quotes = ser(
            self.BASE_H + [108, 100, 115],
            self.BASE_L + [106, 98, 112],
        )
        report = replay_setup03_history(
            quotes,
            1000.0,
            {
                "swing_lookback": 2,
                "platform_window": 20,
                "arm_proximity_pct": 0.05,
            },
            {"swing_lookback": 2, "atr_period": 2},
        )

        self.assertEqual([day.setup_state for day in report.days[-4:]], [
            SetupState.WATCH,
            SetupState.ARMED,
            SetupState.WATCH,
            SetupState.CONFIRMED,
        ])
        self.assertEqual(len(report.events), 1)
        self.assertEqual(report.events[0].setup.confirmed_index, len(quotes) - 1)

    def test_platform_detected_and_confirmed_on_same_day_is_one_event(self):
        quotes = ser([115], [112])
        evaluation = self._evaluation(
            quotes[0].trade_date,
            SetupState.CONFIRMED,
            0,
            0,
            0,
            SetupState.CONFIRMED,
        )
        with patch(
            "trading.replay.evaluate_setup03_event", return_value=evaluation
        ):
            report = replay_setup03_history(quotes, 1000.0)

        self.assertEqual(len(report.events), 1)
        setup = report.events[0].setup
        self.assertEqual(
            (setup.detected_index, setup.state_entered_index, setup.confirmed_index),
            (0, 0, 0),
        )


class ReplayDataQualityTests(unittest.TestCase):
    def _validate(self, quotes: list[Quote], **overrides) -> None:
        latest = quotes[-1].trade_date if quotes else date(2026, 1, 10)
        validate_replay_history(
            quotes,
            as_of_date=overrides.get("as_of_date", latest),
            expected_latest_date=overrides.get("expected_latest_date", latest),
            minimum_rows=overrides.get("minimum_rows", max(1, len(quotes))),
            max_calendar_gap_days=overrides.get("max_calendar_gap_days", 14),
            max_latest_lag_days=overrides.get("max_latest_lag_days", 14),
        )

    def test_rejects_empty_duplicate_and_out_of_order_history(self):
        with self.assertRaisesRegex(ValueError, "历史数据为空"):
            self._validate([])

        quotes = ser([100, 101, 102], [90, 91, 92])
        duplicate = [quotes[0], replace(quotes[1], trade_date=quotes[0].trade_date)]
        with self.assertRaisesRegex(ValueError, "重复日期"):
            self._validate(duplicate)

        out_of_order = [quotes[1], quotes[0]]
        with self.assertRaisesRegex(ValueError, "日期乱序"):
            self._validate(out_of_order)

    def test_rejects_insufficient_stale_and_abnormally_gapped_history(self):
        quotes = ser([100, 101], [90, 91])
        with self.assertRaisesRegex(ValueError, "历史样本不足"):
            self._validate(quotes, minimum_rows=3)
        with self.assertRaisesRegex(ValueError, "最新日期"):
            self._validate(
                quotes,
                as_of_date=date(2026, 1, 10),
                expected_latest_date=date(2026, 1, 10),
            )

        gapped = [quotes[0], replace(quotes[1], trade_date=date(2026, 1, 20))]
        with self.assertRaisesRegex(ValueError, "异常缺口"):
            self._validate(gapped, max_calendar_gap_days=7)


class ReplayProductionConsistencyTests(unittest.TestCase):
    def test_replay_and_production_share_setup_decision_and_prices(self):
        closes = [
            90, 94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
            94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
            94, 98, 102, 106, 110, 106, 104, 110.3,
        ]
        start = date(2026, 1, 1)
        quotes = [
            replace(
                q(start + timedelta(days=index), close, close),
                open=close,
                high=close,
                low=close,
                close=close,
            )
            for index, close in enumerate(closes)
        ]
        setup_parameters = {
            "swing_lookback": 2,
            "platform_window": 40,
            "platform_tolerance_pct": 0.0,
            "arm_proximity_pct": 0.0,
        }
        decision_parameters = {
            "swing_lookback": 2,
            "atr_period": 14,
            "atr_buffer": 0.5,
            "max_chase_atr": 0.5,
        }
        report = replay_setup03_history(
            quotes, 1000.0, setup_parameters, decision_parameters
        )
        production, note = evaluate_set03_decision(
            quotes,
            quotes[-1].trade_date,
            True,
            1000.0,
            setup_parameters,
            decision_parameters,
        )

        self.assertEqual(note, "")
        self.assertIsNotNone(production)
        setup, decision, confirmed_date = production
        event = report.events[-1]
        self.assertEqual(event.setup, setup)
        self.assertEqual(event.decision, decision)
        self.assertEqual(confirmed_date, quotes[setup.confirmed_index].trade_date)

        production_row = decision_row(
            quotes[-1],
            setup,
            decision,
            date(2026, 2, 1),
            confirmed_date,
            1000.0,
            "yfinance",
        )
        artifact_row = replay_event_rows(
            report, "yfinance", "sha256:test", "{}"
        )[-1]
        self.assertEqual(artifact_row["Setup状态"], production_row["Setup状态"])
        self.assertEqual(artifact_row["Decision动作"], production_row["决策动作"])
        for field in ("计划入场", "结构失效价", "执行止损", "T1", "T1_RR"):
            self.assertEqual(artifact_row[field], production_row[field])
        self.assertEqual(artifact_row["signal_date"], event.signal_date)
        self.assertEqual(artifact_row["confirmed_date"], confirmed_date)
        self.assertEqual(artifact_row["signal_close"], quotes[-1].close)
        self.assertIsNotNone(artifact_row["ATR"])


if __name__ == "__main__":
    unittest.main()

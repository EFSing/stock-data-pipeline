import inspect
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch

from core import Quote
from main import (
    decision_row,
    evaluate_set03_decision,
    run,
    trading_parameters,
)
from providers import QFQ_HISTORY_SOURCES
from sheets_client import DECISION_HEADERS, SheetsClient
from trading.events import (
    Setup03Evaluation,
    evaluate_setup03_event,
    setup03_decision_key,
)
from trading.models import (
    Decision,
    DecisionAction,
    EntryPlan,
    PositionSize,
    RiskReward,
    Setup,
    SetupState,
)
from trading.setup import (
    PERCENTAGE_BOUNDARY_MODE,
    SetupDiagnostics,
    SetupGateReason,
    SetupWithDiagnostics,
    detect_platform_breakout_with_diagnostics,
)


def quote(day: date = date(2026, 8, 21), source: str = "yfinance") -> Quote:
    return Quote(
        symbol="TEST",
        name="测试标的",
        market="US",
        trade_date=day,
        source=source,
        open=109.0,
        high=111.0,
        low=108.0,
        close=110.3,
        preclose=109.0,
        pct_change=1.19,
        volume=1_000_000,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


def confirmed_setup() -> Setup:
    return Setup(
        setup_type="SETUP_03",
        state=SetupState.CONFIRMED,
        breakout_price=110.0,
        structural_invalidation=90.0,
        detected_index=0,
        state_entered_index=0,
        confirmed_index=0,
    )


def entry_allowed_decision() -> Decision:
    entry = EntryPlan(110.3, 110.0, 112.0, 110.0, 110.0, "close确认突破")
    rr = RiskReward(110.3, 107.98, 2.32, (115.44, 122.36), (2.22, 5.2), "NORMAL")
    position = PositionSize(1000.0, 110.3, 107.98, 2.32, 431.034, 1000.0)
    return Decision(
        DecisionAction.ENTRY_ALLOWED,
        entry,
        90.0,
        107.98,
        (115.44, 122.36),
        rr,
        position,
    )


class DecisionParameterTests(unittest.TestCase):
    def test_snapshot_sources_are_not_qfq_history_sources(self):
        self.assertEqual(QFQ_HISTORY_SOURCES, {"BaoStock", "yfinance"})
        self.assertNotIn("Tencent", QFQ_HISTORY_SOURCES)
        self.assertNotIn("Sina", QFQ_HISTORY_SOURCES)

    def test_all_parameters_are_read_explicitly(self):
        config = {
            "setup_swing_lookback": "5",
            "setup_platform_window": "40",
            "setup_platform_tolerance_pct": "0%",
            "setup_arm_proximity_pct": "0%",
            "decision_swing_lookback": "5",
            "decision_atr_period": "14",
            "decision_atr_buffer": "0.5",
            "decision_max_chase_atr": "0.5",
            "decision_risk_capital": "1000",
        }
        setup, decision, risk_capital = trading_parameters(config)
        self.assertEqual(
            setup,
            {
                "swing_lookback": 5,
                "platform_window": 40,
                "platform_tolerance_pct": 0.0,
                "arm_proximity_pct": 0.0,
            },
        )
        self.assertEqual(
            decision,
            {
                "swing_lookback": 5,
                "atr_period": 14,
                "atr_buffer": 0.5,
                "max_chase_atr": 0.5,
            },
        )
        self.assertEqual(risk_capital, 1000.0)

    @patch("trading.events.detect_platform_breakout_with_diagnostics")
    def test_production_event_path_uses_percentage_default_not_atr_mode(self, detect):
        setup_parameters = {
            "swing_lookback": 5,
            "platform_window": 40,
            "platform_tolerance_pct": 0.0,
            "arm_proximity_pct": 0.0,
        }
        decision_parameters = {
            "swing_lookback": 5,
            "atr_period": 14,
            "atr_buffer": 0.5,
            "max_chase_atr": 0.5,
        }
        detect.return_value = SetupWithDiagnostics(
            Setup("SETUP_03", SetupState.NONE),
            SetupDiagnostics(
                SetupGateReason.INSUFFICIENT_HIGH_SWINGS,
                SetupState.NONE,
                0,
            ),
        )

        evaluation = evaluate_setup03_event(
            [quote()], 1000.0, setup_parameters, decision_parameters
        )

        self.assertEqual(evaluation.setup.state, SetupState.NONE)
        detect.assert_called_once_with([quote()], **setup_parameters)
        self.assertNotIn("platform_boundary_mode", detect.call_args.kwargs)
        self.assertEqual(
            inspect.signature(detect_platform_breakout_with_diagnostics)
            .parameters["platform_boundary_mode"]
            .default,
            PERCENTAGE_BOUNDARY_MODE,
        )

    def test_missing_decision_parameter_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "setup_swing_lookback"):
            trading_parameters({})


class DecisionGateTests(unittest.TestCase):
    @patch("main.evaluate_setup03_event")
    def test_unconfirmed_close_does_not_call_core(self, evaluate):
        result, note = evaluate_set03_decision(
            [quote()], date(2026, 8, 21), False, 1000.0, {}, {}
        )
        self.assertIsNone(result)
        self.assertIn("尚非正式收盘", note)
        evaluate.assert_not_called()

    @patch("main.evaluate_setup03_event")
    def test_stale_qfq_does_not_call_core(self, evaluate):
        result, note = evaluate_set03_decision(
            [quote(date(2026, 8, 20))], date(2026, 8, 21), True, 1000.0, {}, {}
        )
        self.assertIsNone(result)
        self.assertIn("不一致", note)
        evaluate.assert_not_called()

    @patch("main.evaluate_setup03_event")
    def test_valid_gate_passes_every_explicit_parameter(self, evaluate):
        setup = confirmed_setup()
        decision = entry_allowed_decision()
        evaluate.return_value = Setup03Evaluation(
            setup,
            SetupState.CONFIRMED,
            date(2026, 8, 21),
            date(2026, 8, 21),
            decision,
        )
        setup_parameters = {"swing_lookback": 5, "platform_window": 40}
        decision_parameters = {"atr_period": 14, "atr_buffer": 0.5}

        result, note = evaluate_set03_decision(
            [quote()],
            date(2026, 8, 21),
            True,
            1000.0,
            setup_parameters,
            decision_parameters,
        )

        self.assertEqual(result, (setup, decision, date(2026, 8, 21)))
        self.assertEqual(note, "")
        evaluate.assert_called_once_with(
            [quote()],
            1000.0,
            setup_parameters,
            decision_parameters,
            (),
        )

    @patch("main.evaluate_setup03_event")
    def test_non_event_terminal_state_is_not_published(self, evaluate):
        setup = confirmed_setup()
        evaluate.return_value = Setup03Evaluation(
            setup, None, None, date(2026, 8, 21), None
        )

        result, note = evaluate_set03_decision(
            [quote()], date(2026, 8, 21), True, 1000.0, {}, {}
        )

        self.assertIsNone(result)
        self.assertIn("无新CONFIRMED事件", note)


class SharedEventSemanticsTests(unittest.TestCase):
    @patch("trading.events.detect_platform_breakout")
    @patch("trading.events.decide_platform_breakout_with_diagnostics")
    def test_persistent_confirmed_state_does_not_recalculate_decision(
        self, decide, detect
    ):
        setup = confirmed_setup()
        detect.return_value = setup
        quotes = [quote(date(2026, 8, 21)), quote(date(2026, 8, 22))]

        evaluation = evaluate_setup03_event(quotes, 1000.0)

        self.assertIsNone(evaluation.event_type)
        self.assertIsNone(evaluation.decision)
        decide.assert_not_called()

    @patch("trading.events.detect_platform_breakout")
    @patch("trading.events.decide_platform_breakout_with_diagnostics")
    def test_same_day_published_event_is_idempotent_without_recalculation(
        self, decide, detect
    ):
        detect.return_value = confirmed_setup()
        key = setup03_decision_key("TEST", date(2026, 8, 21))

        evaluation = evaluate_setup03_event(
            [quote()], 1000.0, published_decision_keys={key}
        )

        self.assertEqual(evaluation.event_type, SetupState.CONFIRMED)
        self.assertTrue(evaluation.duplicate)
        self.assertIsNone(evaluation.decision)
        decide.assert_not_called()


class DecisionRowTests(unittest.TestCase):
    def test_entry_allowed_is_projected_without_recalculation(self):
        fetched_at = datetime(2026, 8, 22, 18, 0)
        row = decision_row(
            quote(),
            confirmed_setup(),
            entry_allowed_decision(),
            fetched_at,
            date(2026, 8, 21),
            1000.0,
            "YahooChart",
        )
        self.assertEqual(set(row), set(DECISION_HEADERS))
        self.assertEqual(row["决策动作"], "ENTRY_ALLOWED")
        self.assertEqual(row["计划入场"], 110.3)
        self.assertEqual(row["执行止损"], 107.98)
        self.assertEqual(row["T1"], 115.44)
        self.assertEqual(row["T1_RR"], 2.22)
        self.assertEqual(row["风险资本"], 1000.0)
        self.assertEqual(row["数据源"], "YahooChart")
        self.assertEqual(row["确认日期"], date(2026, 8, 21))

    def test_no_trade_keeps_optional_fields_empty(self):
        decision = Decision(
            DecisionAction.NO_TRADE, None, None, None, (), None, None
        )
        row = decision_row(
            quote(),
            Setup("SETUP_03", SetupState.NONE),
            decision,
            datetime(2026, 8, 22, 18, 0),
            None,
            1000.0,
            "yfinance",
        )
        self.assertIsNone(row["计划入场"])
        self.assertIsNone(row["T1"])
        self.assertIsNone(row["T1_RR"])
        self.assertIsNone(row["理论数量"])


class DecisionSheetUpsertTests(unittest.TestCase):
    def test_decision_upsert_replaces_same_key_and_keeps_other_dates(self):
        client = object.__new__(SheetsClient)
        existing = [
            {"统一代码": "TEST", "交易日期": "2026-08-21", "Setup类型": "SETUP_03", "决策动作": "WATCH"},
            {"统一代码": "TEST", "交易日期": "2026-08-20", "Setup类型": "SETUP_03", "决策动作": "NO_TRADE"},
        ]
        client.records = Mock(return_value=existing)
        client._replace = Mock()
        incoming = {
            "统一代码": "TEST",
            "交易日期": "2026-08-21",
            "Setup类型": "SETUP_03",
            "决策动作": "ENTRY_ALLOWED",
        }

        changed = client.upsert_decisions([incoming])

        self.assertEqual(changed, 1)
        client._replace.assert_called_once()
        sheet_name, headers, rows = client._replace.call_args.args
        self.assertEqual(sheet_name, "交易决策")
        self.assertEqual(headers, DECISION_HEADERS)
        self.assertEqual(len(rows), 2)
        current = next(row for row in rows if row["交易日期"] == "2026-08-21")
        self.assertEqual(current["决策动作"], "ENTRY_ALLOWED")


class DecisionPipelineTests(unittest.TestCase):
    def test_real_entry_allowed_chain_projects_to_sheet(self):
        closes = [
            90, 94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
            94, 98, 102, 106, 110, 106, 102, 98, 94, 90,
            94, 98, 102, 106, 110, 106, 104, 110.3,
        ]
        start = date(2026, 1, 1)
        quotes = [
            replace(
                quote(start + timedelta(days=index)),
                open=close,
                high=close,
                low=close,
                close=close,
            )
            for index, close in enumerate(closes)
        ]
        result, note = evaluate_set03_decision(
            quotes,
            quotes[-1].trade_date,
            True,
            1000.0,
            {
                "swing_lookback": 2,
                "platform_window": 40,
                "platform_tolerance_pct": 0.0,
                "arm_proximity_pct": 0.0,
            },
            {
                "swing_lookback": 2,
                "atr_period": 14,
                "atr_buffer": 0.5,
                "max_chase_atr": 0.5,
            },
        )
        self.assertEqual(note, "")
        setup, decision, confirmed_date = result
        row = decision_row(
            quotes[-1],
            setup,
            decision,
            datetime(2026, 2, 1, 18, 0),
            confirmed_date,
            1000.0,
            "yfinance",
        )
        self.assertEqual(row["决策动作"], "ENTRY_ALLOWED")
        self.assertAlmostEqual(row["计划入场"], 110.3)
        self.assertAlmostEqual(row["T1"], 115.44)
        self.assertGreater(row["T1_RR"], 2.0)
        self.assertIsNotNone(row["理论数量"])

    @patch("main.evaluate_set03_decision")
    @patch("main.market_close_confirmed", return_value=True)
    @patch("main.expected_latest_trade_date", return_value=date(2026, 8, 21))
    @patch("main.beijing_now", return_value=datetime(2026, 8, 22, 18, 0))
    @patch("providers.fetch_with_retry")
    @patch("sheets_client.SheetsClient")
    def test_run_uses_explicit_history_source_for_qfq(
        self, client_class, fetch, _now, _expected_date, _confirmed, evaluate
    ):
        config = {
            "history_days": "1000",
            "retry_count": "1",
            "retry_wait_seconds": "0",
            "close_tolerance_pct": "0.05%",
            "volume_tolerance_pct": "2%",
            "write_adjusted": "true",
            "setup_swing_lookback": "5",
            "setup_platform_window": "40",
            "setup_platform_tolerance_pct": "0",
            "setup_arm_proximity_pct": "0",
            "decision_swing_lookback": "5",
            "decision_atr_period": "14",
            "decision_atr_buffer": "0.5",
            "decision_max_chase_atr": "0.5",
            "decision_risk_capital": "1000",
        }
        watch = {
            "启用": True,
            "市场": "US",
            "主数据源": "yfinance",
            "校验数据源": "BaoStock",
            "历史数据源": "yfinance",
            "时区": "America/New_York",
            "收盘时间": "16:00",
            "统一代码": "TEST",
        }
        client = client_class.return_value
        client.config.return_value = config
        client.records.return_value = [watch]
        client.upsert_latest.return_value = 0
        client.upsert_history.return_value = 0
        client.upsert_decisions.return_value = 1
        evaluate.return_value = (
            (
                confirmed_setup(),
                entry_allowed_decision(),
                date(2026, 8, 21),
            ),
            "",
        )

        def fetch_result(source, _watch, adjustment, *_args, **_kwargs):
            if adjustment == "qfq":
                return [quote(source=source)]
            return [quote(source=source)]

        fetch.side_effect = fetch_result

        run("us")

        qfq_calls = [call for call in fetch.call_args_list if call.args[2] == "qfq"]
        self.assertEqual(len(qfq_calls), 1)
        self.assertEqual(qfq_calls[0].args[0], "yfinance")
        self.assertNotIn(qfq_calls[0].args[0], {"Tencent", "Sina"})
        decision_rows = client.upsert_decisions.call_args.args[0]
        self.assertEqual(len(decision_rows), 1)
        self.assertEqual(decision_rows[0]["数据源"], "yfinance")

    @patch("main.market_close_confirmed", return_value=True)
    @patch("main.expected_latest_trade_date", return_value=date(2026, 8, 21))
    @patch("main.beijing_now", return_value=datetime(2026, 8, 22, 18, 0))
    @patch("providers.fetch_with_retry")
    @patch("sheets_client.SheetsClient")
    def test_one_decision_failure_does_not_stop_other_symbols_or_market_writes(
        self, client_class, fetch, _now, _expected_date, _confirmed
    ):
        config = {
            "history_days": "1000",
            "retry_count": "1",
            "retry_wait_seconds": "0",
            "close_tolerance_pct": "0.05%",
            "volume_tolerance_pct": "2%",
            "write_adjusted": "true",
            "setup_swing_lookback": "5",
            "setup_platform_window": "40",
            "setup_platform_tolerance_pct": "0",
            "setup_arm_proximity_pct": "0",
            "decision_swing_lookback": "5",
            "decision_atr_period": "14",
            "decision_atr_buffer": "0.5",
            "decision_max_chase_atr": "0.5",
            "decision_risk_capital": "1000",
        }
        watches = [
            {
                "启用": True,
                "市场": "US",
                "主数据源": "yfinance",
                "校验数据源": "BaoStock",
                "历史数据源": "yfinance",
                "时区": "America/New_York",
                "收盘时间": "16:00",
                "统一代码": symbol,
            }
            for symbol in ("FAIL", "PASS")
        ]
        client = client_class.return_value
        client.config.return_value = config
        client.records.return_value = watches
        client.upsert_latest.return_value = 2
        client.upsert_history.return_value = 2
        client.upsert_decisions.return_value = 1

        def fetch_result(source, watch, _adjustment, *_args, **_kwargs):
            return [replace(quote(source=source), symbol=watch["统一代码"])]

        fetch.side_effect = fetch_result
        successful_result = (
            confirmed_setup(),
            entry_allowed_decision(),
            date(2026, 8, 21),
        )
        with patch(
            "main.evaluate_set03_decision",
            side_effect=[RuntimeError("broken core input"), (successful_result, "")],
        ):
            run("us")

        decision_rows = client.upsert_decisions.call_args.args[0]
        self.assertEqual(len(decision_rows), 1)
        self.assertEqual(decision_rows[0]["统一代码"], "PASS")

        latest_rows = client.upsert_latest.call_args.args[0]
        self.assertEqual({row["统一代码"] for row in latest_rows}, {"FAIL", "PASS"})
        history_sheets = [call.args[0] for call in client.upsert_history.call_args_list]
        self.assertEqual(history_sheets, ["历史行情_未复权", "历史行情_前复权"])

        validation_call, log_call = client.append_rows.call_args_list
        self.assertEqual(validation_call.args[0], "校验记录")
        self.assertEqual(len(validation_call.args[2]), 2)
        self.assertEqual(log_call.args[0], "运行日志")
        self.assertEqual(len(log_call.args[2]), 2)
        self.assertIn("SETUP_03 Decision失败：broken core input", log_call.args[2][0]["消息"])


class LatestOnlyPipelineTests(unittest.TestCase):
    @staticmethod
    def config():
        return {
            "retry_count": "1",
            "retry_wait_seconds": "0",
            "close_tolerance_pct": "0.05%",
            "volume_tolerance_pct": "2%",
        }

    @staticmethod
    def watch(symbol="TEST"):
        return {
            "启用": True,
            "市场": "US",
            "主数据源": "yfinance",
            "校验数据源": "Tencent",
            "时区": "America/New_York",
            "收盘时间": "16:00",
            "统一代码": symbol,
        }

    def test_latest_row_uses_quote_trade_date_not_beijing_run_date(self):
        watch = self.watch()
        fetched_at = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
        with (
            patch("sheets_client.SheetsClient") as client_class,
            patch("providers.fetch_latest_with_retry") as latest_fetch,
            patch("providers.fetch_with_retry") as full_fetch,
            patch("main.evaluate_set03_decision") as evaluate,
            patch("main.beijing_now", return_value=fetched_at),
        ):
            client = client_class.return_value
            client.config.return_value = self.config()
            client.records.return_value = [watch]
            client.upsert_latest.return_value = 1
            latest_fetch.side_effect = lambda source, current_watch, *_args: [
                replace(
                    quote(day=date(2026, 8, 28), source=source),
                    symbol=current_watch["统一代码"],
                )
            ]

            summary = run("us", mode="latest")

        row = client.upsert_latest.call_args.args[0][0]
        self.assertEqual(row["交易日期"], date(2026, 8, 28))
        self.assertEqual(row["抓取时间"], fetched_at)
        self.assertNotEqual(row["交易日期"], fetched_at.date())
        self.assertEqual(row["校验状态"], "已验证")
        self.assertEqual(summary["status"], "SUCCESS")
        self.assertEqual(summary["history_rows_written"], 0)
        self.assertEqual(summary["decision_rows_written"], 0)
        full_fetch.assert_not_called()
        evaluate.assert_not_called()
        client.upsert_history.assert_not_called()
        client.upsert_decisions.assert_not_called()

    def test_latest_source_date_mismatch_selects_newer_source_but_stays_pending(self):
        watches = [self.watch("PRIMARY_FRIDAY"), self.watch("VERIFIER_FRIDAY")]
        fetched_at = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
        with (
            patch("sheets_client.SheetsClient") as client_class,
            patch("providers.fetch_latest_with_retry") as latest_fetch,
            patch("main.beijing_now", return_value=fetched_at),
        ):
            client = client_class.return_value
            client.config.return_value = self.config()
            client.records.return_value = watches

            def fetch_result(source, current_watch, *_args):
                symbol = current_watch["统一代码"]
                if symbol == "PRIMARY_FRIDAY":
                    day = date(2026, 8, 28) if source == "yfinance" else date(2026, 8, 27)
                else:
                    day = date(2026, 8, 27) if source == "yfinance" else date(2026, 8, 28)
                return [replace(quote(day=day, source=source), symbol=symbol)]

            latest_fetch.side_effect = fetch_result
            summary = run("us", mode="latest")

        rows = {row["统一代码"]: row for row in client.upsert_latest.call_args.args[0]}
        self.assertEqual(rows["PRIMARY_FRIDAY"]["交易日期"], date(2026, 8, 28))
        self.assertEqual(rows["PRIMARY_FRIDAY"]["主数据源"], "yfinance")
        self.assertEqual(rows["VERIFIER_FRIDAY"]["交易日期"], date(2026, 8, 28))
        self.assertEqual(rows["PRIMARY_FRIDAY"]["校验状态"], "待复核")
        self.assertEqual(rows["VERIFIER_FRIDAY"]["校验状态"], "待复核")
        self.assertEqual(summary["single_source_current"], 2)
        self.assertEqual(summary["pending_review"], 2)

    def test_latest_future_quote_is_rejected_and_old_quote_is_written(self):
        watch = self.watch("FUTURE")
        fetched_at = datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc)
        with (
            patch("sheets_client.SheetsClient") as client_class,
            patch("providers.fetch_latest_with_retry") as latest_fetch,
            patch("main.beijing_now", return_value=fetched_at),
        ):
            client = client_class.return_value
            client.config.return_value = self.config()
            client.records.return_value = [watch]

            def fetch_result(source, current_watch, *_args):
                day = date(2026, 9, 1) if source == "yfinance" else date(2026, 8, 28)
                return [replace(quote(day=day, source=source), symbol=current_watch["统一代码"])]

            latest_fetch.side_effect = fetch_result
            summary = run("us", mode="latest")

        row = client.upsert_latest.call_args.args[0][0]
        self.assertEqual(row["交易日期"], date(2026, 8, 28))
        self.assertEqual(row["校验状态"], "待复核")
        self.assertIn("未来交易日行情已拒绝", row["备注"])
        self.assertEqual(summary["stale_sources_rejected"], 1)
        self.assertEqual(summary["status"], "PARTIAL_DATA_QUALITY")

    def test_latest_provider_failure_marks_previous_row_unavailable(self):
        watch = self.watch("FAILED")
        existing = {
            "统一代码": "FAILED",
            "名称": "Failed symbol",
            "市场": "US",
            "交易日期": date(2026, 8, 28),
            "抓取时间": datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc),
            "正式收盘": True,
            "校验状态": "已验证",
            "收盘": 100.0,
            "币种": "USD",
        }
        fetched_at = datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc)
        with (
            patch("sheets_client.SheetsClient") as client_class,
            patch("providers.fetch_latest_with_retry", return_value=[]),
            patch("main.beijing_now", return_value=fetched_at),
        ):
            client = client_class.return_value

            def records(sheet_name):
                if sheet_name == "自选清单":
                    return [watch]
                if sheet_name == "最新行情":
                    return [existing]
                return []

            client.config.return_value = self.config()
            client.records.side_effect = records
            client.upsert_latest.return_value = 1

            summary = run("us", mode="latest")

        row = client.upsert_latest.call_args.args[0][0]
        self.assertEqual(row["校验状态"], "数据不可用")
        self.assertFalse(row["正式收盘"])
        self.assertEqual(row["收盘"], 100.0)
        self.assertEqual(row["交易日期"], date(2026, 8, 28))
        self.assertIn("禁止下游监控当作当前新鲜数据", row["备注"])
        self.assertEqual(summary["latest_failure_markers"], 1)
        self.assertEqual(summary["freshest_rows_written"], 0)
        self.assertEqual(summary["status"], "PARTIAL_DATA_QUALITY")

        log_rows = client.append_rows.call_args_list[-1].args[2]
        self.assertEqual(log_rows[0]["执行状态"], "失败")

    def test_latest_mode_never_reads_or_writes_history_or_decision(self):
        watch = self.watch()
        fetched_at = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
        with (
            patch("sheets_client.SheetsClient") as client_class,
            patch("providers.fetch_latest_with_retry") as latest_fetch,
            patch("providers.fetch_with_retry") as full_fetch,
            patch("main.evaluate_set03_decision") as evaluate,
            patch("main.trading_parameters") as parameters,
            patch("main.beijing_now", return_value=fetched_at),
        ):
            client = client_class.return_value
            client.config.return_value = self.config()
            client.records.return_value = [watch]
            client.upsert_latest.return_value = 1
            latest_fetch.side_effect = lambda source, current_watch, *_args: [
                replace(quote(day=date(2026, 8, 28), source=source), symbol=current_watch["统一代码"])
            ]

            summary = run("us", mode="latest")

        self.assertEqual(summary["history_rows_written"], 0)
        self.assertEqual(summary["decision_rows_written"], 0)
        full_fetch.assert_not_called()
        evaluate.assert_not_called()
        parameters.assert_not_called()
        client.records.assert_called_once_with("自选清单")
        client.upsert_history.assert_not_called()
        client.upsert_decisions.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in client.append_rows.call_args_list],
            ["校验记录", "运行日志"],
        )


if __name__ == "__main__":
    unittest.main()

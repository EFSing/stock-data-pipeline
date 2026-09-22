from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core import Quote
from scripts.run_cloud_daily_report import (
    main as cloud_report_main,
    _notification_text,
    _status_from_result,
    resolve_cloud_trade_date,
    run_cloud_daily_report,
)
from trading.daily_dashboard import build_dashboard_projection, render_dashboard_html
from trading.daily_report_email import render_daily_report_email_html
from trading.ephemeral_market_data import (
    EXACT_QFQ_MIN_RETRY_ATTEMPTS,
    EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION,
    EphemeralMarketDataSnapshot,
    load_ephemeral_market_data,
)
from trading.production_prerequisites import ExactExchangeCalendarProvider, build_production_snapshot

from tests.test_production_prerequisites import (
    AFTER_CLOSE,
    T_DAY,
    _history,
    _latest,
    _rows,
)


FIXTURE = Path(__file__).with_name("fixtures") / "daily_dashboard_v1.json"
US_T_DAY = date(2026, 9, 15)
US_AFTER_CLOSE = datetime(2026, 9, 15, 21, 0, tzinfo=timezone.utc)


def _quote(symbol, market, trade_date, source, currency, preclose=101.0, close=102.0):
    return Quote(
        symbol=symbol,
        name=symbol,
        market=market,
        trade_date=trade_date,
        source=source,
        open=100.0,
        high=105.0,
        low=95.0,
        close=close,
        preclose=preclose,
        pct_change=0.99,
        volume=1000.0,
        amount=100000.0,
        turnover_rate=1.0,
        currency=currency,
    )


def _cloud_client():
    client = _rows()
    client.rows["自选清单"] = [{
        "启用": "TRUE",
        "市场": "CN",
        "统一代码": "600000",
        "名称": "CN",
        "币种": "CNY",
        "主数据源": "Tencent",
        "校验数据源": "Sina",
        "历史数据源": "yfinance",
        "时区": "Asia/Shanghai",
        "收盘时间": "15:00",
        "BaoStock代码": "sh.600000",
        "yfinance代码": "600000.SS",
    }]
    client.header_rows["自选清单"] = tuple(client.rows["自选清单"][0])
    return client


def _cloud_us_client():
    client = _rows()
    client.rows["自选清单"] = [{
        "启用": "TRUE",
        "市场": "US",
        "统一代码": "AAPL",
        "名称": "AAPL",
        "币种": "USD",
        "主数据源": "yfinance",
        "校验数据源": "Tencent",
        "历史数据源": "yfinance",
        "时区": "America/New_York",
        "收盘时间": "16:00",
        "yfinance代码": "AAPL",
    }]
    client.header_rows["自选清单"] = tuple(client.rows["自选清单"][0])
    return client


class CloudDailyReportTests(unittest.TestCase):
    def test_notification_uses_explicit_confirmation_and_position_semantics(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["cloud_daily_report"] = {"market": "US", "status": "SUCCESS"}

        _, body = _notification_text(payload)

        self.assertIn("等待确认：", body)
        self.assertIn("策略跟踪持仓：", body)
        self.assertNotIn("接近确认：", body)
        self.assertNotIn("\n持仓：", body)

    def test_automatic_trade_date_uses_exchange_local_date_and_completed_session(self):
        provider = ExactExchangeCalendarProvider()
        cases = (
            (
                "US",
                datetime(2026, 9, 15, 0, 46, tzinfo=timezone.utc),
                date(2026, 9, 14),
            ),
            (
                "US",
                datetime(2026, 9, 3, 20, 1, tzinfo=timezone.utc),
                date(2026, 9, 3),
            ),
            (
                "CN",
                datetime(2026, 9, 3, 8, 1, tzinfo=timezone.utc),
                T_DAY,
            ),
        )

        for market, now, expected in cases:
            with self.subTest(market=market, now=now):
                resolved = resolve_cloud_trade_date(
                    market, now=now, calendar_provider=provider
                )
                self.assertEqual(resolved, expected)
                identity = provider.completed_session(market, resolved, now=now)
                self.assertEqual(identity.trade_date, expected)

    def test_explicit_trade_date_bypasses_automatic_calendar_resolution(self):
        class ExplodingAutoDateProvider(ExactExchangeCalendarProvider):
            def market_local_date(self, market, *, now):
                raise AssertionError("explicit date must not resolve automatic date")

        explicit = date(2026, 9, 3)
        self.assertEqual(
            resolve_cloud_trade_date(
                "US",
                explicit,
                now=datetime(2026, 9, 15, 0, 46, tzinfo=timezone.utc),
                calendar_provider=ExplodingAutoDateProvider(),
            ),
            explicit,
        )

    def test_automatic_market_holiday_keeps_local_non_session_date_and_skips(self):
        provider = ExactExchangeCalendarProvider()
        now = datetime(2026, 7, 4, 0, 46, tzinfo=timezone.utc)
        resolved = resolve_cloud_trade_date("US", now=now, calendar_provider=provider)
        self.assertEqual(resolved, date(2026, 7, 3))

        class ExplodingClient:
            def records(self, sheet_name):
                raise AssertionError("non-session must not read Sheets")

        with TemporaryDirectory() as directory:
            payload = run_cloud_daily_report(
                market="US",
                as_of_date=resolved,
                output_dir=directory,
                now=now,
                client=ExplodingClient(),
                calendar_provider=provider,
                notify=False,
            )
        self.assertEqual(payload["cloud_daily_report"]["status"], "SKIPPED_NON_SESSION")

    def test_market_scope_ignores_malformed_other_market_rows(self):
        client = _rows()
        client.rows["策略账户"].append({
            "账户ID": "US-BAD",
            "启用": "TRUE",
            "市场": "US",
            "币种": "CNY",
            "参考净值": "not-a-number",
            "净值日期": "not-a-date",
            "备注": "malformed other market",
        })
        snapshot = build_production_snapshot(
            client,
            as_of_date=T_DAY,
            now=AFTER_CLOSE,
            market="CN",
            ephemeral_latest_rows=[_latest("600000", "CN", "CNY")],
            ephemeral_qfq_rows=[_history("600000", "CN", "CNY")],
        )
        self.assertEqual([item.account_id for item in snapshot.preflight.accounts], ["CN-1"])
        self.assertEqual(snapshot.preflight.errors, ())
        self.assertEqual(len(snapshot.account_runs), 1)
        self.assertEqual({item.market for item in snapshot.account_runs[0].inputs}, {"CN"})

    def test_ephemeral_rows_match_legacy_sheet_rows_without_fallback(self):
        client = _rows()
        legacy = build_production_snapshot(client, as_of_date=T_DAY, now=AFTER_CLOSE, market="CN")
        injected = build_production_snapshot(
            client,
            as_of_date=T_DAY,
            now=AFTER_CLOSE,
            market="CN",
            ephemeral_latest_rows=[_latest("600000", "CN", "CNY")],
            ephemeral_qfq_rows=[_history("600000", "CN", "CNY")],
        )
        left = legacy.account_runs[0].inputs[0]
        right = injected.account_runs[0].inputs[0]
        self.assertEqual(left.data_quality_status, right.data_quality_status)
        self.assertEqual(left.qfq_history, right.qfq_history)
        self.assertEqual(injected.preflight.ready, legacy.preflight.ready)

    def test_optional_none_preclose_does_not_fail_cloud_preflight(self):
        client = _rows()
        latest = _latest("600000", "CN", "CNY")
        latest["昨收"] = None
        snapshot = build_production_snapshot(
            client,
            as_of_date=T_DAY,
            now=AFTER_CLOSE,
            market="CN",
            ephemeral_latest_rows=[latest],
            ephemeral_qfq_rows=[_history("600000", "CN", "CNY")],
        )

        self.assertTrue(snapshot.preflight.ready)

    def test_ephemeral_path_does_not_read_legacy_market_data_sheets(self):
        client = _rows()
        original_records = client.records

        def records(sheet_name):
            if sheet_name in {"最新行情", "历史行情_前复权"}:
                raise AssertionError(f"ephemeral path must not read {sheet_name}")
            return original_records(sheet_name)

        client.records = records
        snapshot = build_production_snapshot(
            client,
            as_of_date=T_DAY,
            now=AFTER_CLOSE,
            market="CN",
            ephemeral_latest_rows=[_latest("600000", "CN", "CNY")],
            ephemeral_qfq_rows=[_history("600000", "CN", "CNY")],
        )
        self.assertTrue(snapshot.preflight.ready)

    def test_ephemeral_loader_uses_existing_provider_and_projection_contract(self):
        client = _cloud_client()
        history_calls = []

        def latest(source, watch, end, retry_count, retry_wait, **kwargs):
            return [_quote("600000", "CN", T_DAY, source, "CNY")]

        def history(source, watch, adjustment, start, end, *args, **kwargs):
            history_calls.append((source, watch["统一代码"], args, kwargs))
            return [_quote("600000", "CN", T_DAY, source, "CNY")]

        with patch("trading.ephemeral_market_data.fetch_latest_with_retry", side_effect=latest), \
             patch("trading.ephemeral_market_data.fetch_with_retry", side_effect=history):
            snapshot = load_ephemeral_market_data(
                client, market="CN", as_of_date=T_DAY, now=AFTER_CLOSE
            )
        self.assertEqual(snapshot.required_symbols, ("600000",))
        self.assertEqual(len(snapshot.latest_rows), 1)
        self.assertEqual(len(snapshot.qfq_rows), 1)
        self.assertEqual(snapshot.errors, ())
        self.assertEqual(history_calls[0][3]["target_trade_date"], T_DAY)
        self.assertEqual(history_calls[0][2][0], EXACT_QFQ_MIN_RETRY_ATTEMPTS)
        metadata = snapshot.to_dict()
        self.assertEqual(metadata["protocol_version"], EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION)
        self.assertNotIn("latest_rows", metadata)
        self.assertNotIn("qfq_rows", metadata)
        self.assertFalse(metadata["raw_market_data_persisted"])

    def test_ephemeral_loader_completes_missing_selected_preclose_from_same_session_peer(self):
        client = _cloud_client()

        def latest(source, watch, end, retry_count, retry_wait, **kwargs):
            preclose = None if source == "Tencent" else 101.0
            return [_quote("600000", "CN", T_DAY, source, "CNY", preclose=preclose)]

        def history(source, watch, adjustment, start, end, *args, **kwargs):
            return [_quote("600000", "CN", T_DAY, source, "CNY")]

        with patch("trading.ephemeral_market_data.fetch_latest_with_retry", side_effect=latest), \
             patch("trading.ephemeral_market_data.fetch_with_retry", side_effect=history):
            snapshot = load_ephemeral_market_data(
                client, market="CN", as_of_date=T_DAY, now=AFTER_CLOSE
            )

        self.assertEqual(snapshot.errors, ())
        self.assertEqual(snapshot.latest_rows[0]["昨收"], 101.0)
        self.assertEqual(
            snapshot.provider_status["600000"]["latest_preclose_source"],
            "Sina",
        )

    def test_ephemeral_loader_completes_missing_preclose_from_selected_source_history(self):
        client = _cloud_client()

        def latest(source, watch, end, retry_count, retry_wait, **kwargs):
            del watch, end, retry_count, retry_wait, kwargs
            if source == "Tencent":
                return [
                    _quote(
                        "600000",
                        "CN",
                        T_DAY - timedelta(days=1),
                        source,
                        "CNY",
                        close=99.0,
                    ),
                    _quote("600000", "CN", T_DAY, source, "CNY", preclose=None),
                ]
            return [_quote("600000", "CN", T_DAY, source, "CNY", preclose=None)]

        def history(source, watch, adjustment, start, end, *args, **kwargs):
            del source, watch, adjustment, start, end, args, kwargs
            return [_quote("600000", "CN", T_DAY, "yfinance", "CNY")]

        with patch("trading.ephemeral_market_data.fetch_latest_with_retry", side_effect=latest), \
             patch("trading.ephemeral_market_data.fetch_with_retry", side_effect=history):
            snapshot = load_ephemeral_market_data(
                client, market="CN", as_of_date=T_DAY, now=AFTER_CLOSE
            )

        self.assertEqual(snapshot.errors, ())
        self.assertEqual(snapshot.latest_rows[0]["昨收"], 99.0)
        self.assertEqual(
            snapshot.provider_status["600000"]["latest_preclose_source"],
            "Tencent",
        )

    def test_ephemeral_loader_selects_next_independent_source_after_primary_fallback(self):
        client = _cloud_us_client()
        latest_calls = []

        def latest(source, watch, end, retry_count, retry_wait, **kwargs):
            del watch, end, retry_count, retry_wait
            excluded = tuple(sorted(kwargs.get("excluded_sources", ())))
            latest_calls.append((source, excluded))
            if source == "yfinance":
                return [_quote("AAPL", "US", US_T_DAY, "Tencent", "USD")]
            self.assertEqual(source, "Tencent")
            self.assertEqual(excluded, ("Tencent",))
            return [_quote("AAPL", "US", US_T_DAY, "Sina", "USD")]

        def history(source, watch, adjustment, start, end, *args, **kwargs):
            del source, watch, adjustment, start, end, args, kwargs
            return [_quote("AAPL", "US", US_T_DAY, "yfinance", "USD")]

        with patch("trading.ephemeral_market_data.fetch_latest_with_retry", side_effect=latest), \
             patch("trading.ephemeral_market_data.fetch_with_retry", side_effect=history):
            snapshot = load_ephemeral_market_data(
                client, market="US", as_of_date=US_T_DAY, now=US_AFTER_CLOSE
            )

        self.assertEqual(latest_calls, [
            ("yfinance", ()),
            ("Tencent", ("Tencent",)),
        ])
        self.assertEqual(snapshot.errors, ())
        self.assertEqual(snapshot.latest_rows[0]["主数据源"], "Tencent")
        self.assertEqual(snapshot.latest_rows[0]["校验数据源"], "Sina")
        provider_status = snapshot.provider_status["AAPL"]
        self.assertEqual(provider_status["latest_actual_primary_source"], "Tencent")
        self.assertEqual(provider_status["latest_actual_verifier_source"], "Sina")
        self.assertIn("主数据源yfinance回退至Tencent", provider_status["latest_fallback_notes"])
        self.assertIn("校验数据源Tencent回退至Sina", provider_status["latest_fallback_notes"])

    def test_ephemeral_loader_keeps_single_source_when_independent_fallback_fails(self):
        client = _cloud_us_client()

        def latest(source, watch, end, retry_count, retry_wait, **kwargs):
            del watch, end, retry_count, retry_wait
            if source == "yfinance":
                return [_quote("AAPL", "US", US_T_DAY, "Tencent", "USD")]
            self.assertEqual(tuple(sorted(kwargs.get("excluded_sources", ()))), ("Tencent",))
            raise RuntimeError("Sina unavailable")

        def history(source, watch, adjustment, start, end, *args, **kwargs):
            del source, watch, adjustment, start, end, args, kwargs
            return [_quote("AAPL", "US", US_T_DAY, "yfinance", "USD")]

        with patch("trading.ephemeral_market_data.fetch_latest_with_retry", side_effect=latest), \
             patch("trading.ephemeral_market_data.fetch_with_retry", side_effect=history):
            snapshot = load_ephemeral_market_data(
                client, market="US", as_of_date=US_T_DAY, now=US_AFTER_CLOSE
            )

        self.assertEqual(snapshot.latest_rows[0]["主数据源"], "Tencent")
        self.assertEqual(snapshot.latest_rows[0]["校验数据源"], "Tencent")
        self.assertEqual(snapshot.provider_status["AAPL"]["latest_status"], "单源可用")
        self.assertIsNone(snapshot.provider_status["AAPL"]["latest_actual_verifier_source"])
        self.assertTrue(any("latest validation: 单源可用" in error for error in snapshot.errors))

    def test_ephemeral_loader_keeps_normal_dual_source_validation(self):
        client = _cloud_us_client()

        def latest(source, watch, end, retry_count, retry_wait, **kwargs):
            del watch, end, retry_count, retry_wait, kwargs
            return [_quote("AAPL", "US", US_T_DAY, source, "USD")]

        def history(source, watch, adjustment, start, end, *args, **kwargs):
            del source, watch, adjustment, start, end, args, kwargs
            return [_quote("AAPL", "US", US_T_DAY, "yfinance", "USD")]

        with patch("trading.ephemeral_market_data.fetch_latest_with_retry", side_effect=latest), \
             patch("trading.ephemeral_market_data.fetch_with_retry", side_effect=history):
            snapshot = load_ephemeral_market_data(
                client, market="US", as_of_date=US_T_DAY, now=US_AFTER_CLOSE
            )

        self.assertEqual(snapshot.errors, ())
        self.assertEqual(snapshot.provider_status["AAPL"]["latest_status"], "已验证")
        self.assertEqual(snapshot.latest_rows[0]["主数据源"], "yfinance")
        self.assertEqual(snapshot.latest_rows[0]["校验数据源"], "Tencent")

    def test_runner_market_scope_is_read_only_and_does_not_require_other_market(self):
        client = _rows()
        client.rows["策略账户"][1]["币种"] = "CNY"
        from scripts.run_production_daily_decision import run_production_daily_decision

        result = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            now=AFTER_CLOSE,
            market="CN",
            ephemeral_latest_rows=[_latest("600000", "CN", "CNY")],
            ephemeral_qfq_rows=[_history("600000", "CN", "CNY")],
        )
        self.assertEqual([item["市场"] for item in result["reports"]], ["CN"])
        self.assertTrue(result["NO STATE WRITE"])
        self.assertEqual(client.writes, [])

    def test_holiday_skips_without_constructing_sheets_client(self):
        class ExplodingClient:
            def records(self, sheet_name):
                raise AssertionError("holiday must not read Sheets")

        with TemporaryDirectory() as directory:
            payload = run_cloud_daily_report(
                market="CN",
                as_of_date=datetime(2026, 9, 6, tzinfo=timezone.utc).date(),
                output_dir=directory,
                now=AFTER_CLOSE,
                client=ExplodingClient(),
                notify=False,
            )
            self.assertEqual(payload["cloud_daily_report"]["status"], "SKIPPED_NON_SESSION")
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), [
                "daily-report.html", "daily-report.json"
            ])
            html = Path(directory, "daily-report.html").read_text(encoding="utf-8")
            self.assertIn("不使用上一交易日替代", html)
            self.assertNotIn('<span class="market-name">US</span>', html)

    def test_incomplete_session_fails_closed_and_still_writes_final_artifacts(self):
        class ExplodingClient:
            def records(self, sheet_name):
                raise AssertionError("incomplete session must not fetch market data")

        before_cn_close = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as directory:
            payload = run_cloud_daily_report(
                market="CN", as_of_date=T_DAY, output_dir=directory,
                now=before_cn_close, client=ExplodingClient(), notify=False,
            )
            self.assertEqual(payload["cloud_daily_report"]["status"], "INCOMPLETE_SESSION")
            self.assertTrue(payload["cloud_daily_report"]["errors"])
            self.assertIn("本日不生成新的交易信号", Path(directory, "daily-report.html").read_text(encoding="utf-8"))

    def test_ordinary_artifact_allowlist_and_bark_are_isolated_from_core_result(self):
        fixture_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fake_ephemeral = EphemeralMarketDataSnapshot(
            market="CN", as_of_date=T_DAY, fetched_at=AFTER_CLOSE,
            required_symbols=("600000",), active_paper_symbols=(),
            latest_rows=(), qfq_rows=(), symbol_status={}, provider_status={},
            errors=(), input_fingerprint="fingerprint", retry_count=1, history_days=1000,
        )
        with TemporaryDirectory() as directory, \
             patch("scripts.run_cloud_daily_report.load_ephemeral_market_data", return_value=fake_ephemeral), \
             patch("scripts.run_cloud_daily_report.run_production_daily_decision", return_value=fixture_payload), \
             patch("scripts.run_cloud_daily_report.send_bark", return_value={"status": "SENT"}) as bark, \
             patch("scripts.run_cloud_daily_report.send_optional_email", return_value={"status": "NOT_CONFIGURED"}) as email:
            payload = run_cloud_daily_report(
                market="CN", as_of_date=T_DAY, output_dir=directory,
                now=AFTER_CLOSE, client=object(), notify=True,
            )
            json_path = Path(directory, "daily-report.json")
            html_path = Path(directory, "daily-report.html")
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()), [
                "daily-report.html", "daily-report.json"
            ])
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["cloud_daily_report"]["artifact_allowlist"], [
                "daily-report.json", "daily-report.html"
            ])
            self.assertFalse(saved["cloud_daily_report"]["raw_market_data_persisted"])
            self.assertNotIn("qfq_history", json_path.read_text(encoding="utf-8"))
            self.assertIn("收盘交易决策日报", html_path.read_text(encoding="utf-8"))
            bark.assert_called_once()
            email.assert_called_once()
            email_html = email.call_args.kwargs["html_body"]
            self.assertEqual(email_html, render_daily_report_email_html(payload))
            self.assertEqual(
                email.call_args.kwargs["html_attachment"],
                html_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                email.call_args.kwargs["attachment_filename"],
                "A股交易日报_2026-09-03.html",
            )
            self.assertNotEqual(email_html, html_path.read_text(encoding="utf-8"))
            self.assertNotIn("<script", email_html.lower())
            self.assertNotIn("<select", email_html.lower())
            self.assertEqual(payload["cloud_daily_report"]["notifications"]["bark"]["status"], "SENT")

    def test_partial_data_quality_is_persisted_and_unproven_completion_fails_closed(self):
        fixture_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fake_ephemeral = EphemeralMarketDataSnapshot(
            market="US", as_of_date=US_T_DAY, fetched_at=US_AFTER_CLOSE,
            required_symbols=("AAPL",), active_paper_symbols=(),
            latest_rows=(), qfq_rows=(),
            symbol_status={"AAPL": {"latest": "单源可用", "qfq": "OK", "errors": ["latest validation: 单源可用"]}},
            provider_status={"AAPL": {"latest_status": "单源可用"}},
            errors=("US|AAPL: latest validation: 单源可用",),
            input_fingerprint="fingerprint", retry_count=1, history_days=1000,
        )
        with TemporaryDirectory() as directory, \
             patch("scripts.run_cloud_daily_report.load_ephemeral_market_data", return_value=fake_ephemeral), \
             patch("scripts.run_cloud_daily_report.run_production_daily_decision", return_value=fixture_payload), \
             patch("scripts.run_cloud_daily_report.send_bark", return_value={"status": "SENT"}), \
             patch("scripts.run_cloud_daily_report.send_optional_email", return_value={"status": "SENT"}) as email:
            payload = run_cloud_daily_report(
                market="US", as_of_date=US_T_DAY, output_dir=directory,
                now=US_AFTER_CLOSE, client=object(), notify=True,
            )
            saved = json.loads(Path(directory, "daily-report.json").read_text(encoding="utf-8"))
            dashboard_html = Path(directory, "daily-report.html").read_text(encoding="utf-8")

        self.assertEqual(payload["cloud_daily_report"]["status"], "PARTIAL_DATA_QUALITY")
        self.assertEqual(saved["cloud_daily_report"]["status"], "PARTIAL_DATA_QUALITY")
        self.assertIn("PARTIAL_DATA_QUALITY", dashboard_html)
        self.assertIn("部分数据异常", email.call_args.kwargs["html_body"])

        with patch(
            "scripts.run_cloud_daily_report.resolve_cloud_trade_date",
            return_value=US_T_DAY,
        ), patch(
            "scripts.run_cloud_daily_report.run_cloud_daily_report",
            return_value={"cloud_daily_report": {"status": "PARTIAL_DATA_QUALITY"}},
        ):
            exit_code = cloud_report_main([
                "--market", "US", "--date", US_T_DAY.isoformat(),
                "--output", "unused-output",
            ])
        self.assertEqual(exit_code, 1)

    def test_partial_completion_uses_exact_usable_data_and_rejects_core_failure(self):
        snapshot = EphemeralMarketDataSnapshot(
            market="US", as_of_date=US_T_DAY, fetched_at=US_AFTER_CLOSE,
            required_symbols=("TEST",), active_paper_symbols=(),
            latest_rows=({"统一代码": "TEST", "市场": "US", "交易日期": US_T_DAY,
                          "校验状态": "单源可用"},),
            qfq_rows=({"统一代码": "TEST", "市场": "US", "交易日期": US_T_DAY},),
            symbol_status={"TEST": {"errors": ["latest validation: 单源可用"]}},
            provider_status={"TEST": {"latest_status": "单源可用", "actual_source": "Tencent"}},
            errors=("single source",), input_fingerprint="test", retry_count=1, history_days=1000)
        result = {"preflight": {"production readiness": "READY"},
                  "reports": [{"报告": {"results": [{"market": "US",
                     "as_of_date": US_T_DAY.isoformat(), "data_status": "DATA_BAD", "reasons": []}]}}]}
        status, quality = _status_from_result(result, snapshot)
        self.assertEqual(status, "PARTIAL_DATA_QUALITY")
        self.assertTrue(quality["operationally_complete"])
        row = result["reports"][0]["报告"]["results"][0]
        row["reasons"] = ["UPSTREAM_EVALUATION_FAILED: controlled"]
        self.assertFalse(_status_from_result(result, snapshot)[1]["operationally_complete"])
        row["reasons"] = []
        row["position_management"] = {"status": "POSITION_MANAGEMENT_EVALUATION_FAILED"}
        self.assertFalse(_status_from_result(result, snapshot)[1]["operationally_complete"])
        row["position_management"] = None
        from dataclasses import replace
        stale = replace(snapshot, qfq_rows=({"统一代码": "TEST", "市场": "US", "交易日期": "2020-01-01"},))
        self.assertFalse(_status_from_result(result, stale)[1]["operationally_complete"])
        self.assertFalse(_status_from_result({"reports": []}, snapshot)[1]["operationally_complete"])

    def test_candidate_failure_cannot_be_reported_as_success_with_formal_rows(self):
        snapshot = EphemeralMarketDataSnapshot(
            market="US", as_of_date=US_T_DAY, fetched_at=US_AFTER_CLOSE,
            required_symbols=("AAPL",), active_paper_symbols=(),
            latest_rows=({"统一代码": "AAPL", "市场": "US", "交易日期": US_T_DAY.isoformat(), "校验状态": "已验证"},),
            qfq_rows=({"统一代码": "AAPL", "市场": "US", "交易日期": US_T_DAY.isoformat()},),
            symbol_status={}, provider_status={}, errors=(), input_fingerprint="test",
            retry_count=1, history_days=1000,
        )
        result = {
            "preflight": {"production readiness": "READY"},
            "candidate_markets": {"US": {
                "status": "FAILED",
                "candidate_selection_outcome": "DISCOVERY_FAILED",
                "errors": ["CANDIDATE_SHORT_HISTORY_INCOMPLETE"],
            }},
            "reports": [{"报告": {"results": [{
                "market": "US", "as_of_date": US_T_DAY.isoformat(),
                "data_status": "DATA_OK", "symbol": "AAPL",
            }]}}],
        }

        status, quality = _status_from_result(result, snapshot)

        self.assertEqual(status, "PARTIAL_DATA_QUALITY")
        self.assertTrue(quality["candidate_runtime_failed"])
        self.assertTrue(any("DISCOVERY_FAILED" in error for error in quality["candidate_quality_errors"]))

    def test_legacy_success_zero_candidate_without_outcome_is_not_reported_as_success(self):
        snapshot = EphemeralMarketDataSnapshot(
            market="CN", as_of_date=T_DAY, fetched_at=US_AFTER_CLOSE,
            required_symbols=("600000.SH",), active_paper_symbols=(),
            latest_rows=({"统一代码": "600000.SH", "市场": "CN", "交易日期": T_DAY.isoformat(), "校验状态": "已验证"},),
            qfq_rows=({"统一代码": "600000.SH", "市场": "CN", "交易日期": T_DAY.isoformat()},),
            symbol_status={}, provider_status={}, errors=(), input_fingerprint="test",
            retry_count=1, history_days=1000,
        )
        result = {
            "preflight": {"production readiness": "READY"},
            "candidate_markets": {"CN": {
                "status": "SUCCESS",
                "candidate_included_count": 0,
            }},
            "reports": [{"报告": {"results": [{
                "market": "CN", "as_of_date": T_DAY.isoformat(),
                "data_status": "DATA_OK", "symbol": "600000.SH",
            }]}}],
        }

        status, quality = _status_from_result(result, snapshot)

        self.assertEqual(status, "PARTIAL_DATA_QUALITY")
        self.assertTrue(quality["candidate_runtime_failed"])
        self.assertIn("CN Candidate outcome: NOT_REPORTED", quality["candidate_quality_errors"])

    def test_not_run_candidate_without_reports_is_not_misclassified(self):
        snapshot = EphemeralMarketDataSnapshot(
            market="CN", as_of_date=T_DAY, fetched_at=US_AFTER_CLOSE,
            required_symbols=(), active_paper_symbols=(), latest_rows=(), qfq_rows=(),
            symbol_status={}, provider_status={}, errors=(), input_fingerprint="test",
            retry_count=1, history_days=1000,
        )
        result = {
            "preflight": {"production readiness": "READY"},
            "candidate_markets": {"CN": {
                "status": "NOT_RUN",
                "candidate_selection_outcome": "NOT_RUN",
            }},
            "reports": [],
        }

        status, quality = _status_from_result(result, snapshot)

        self.assertEqual(status, "SUCCESS")
        self.assertFalse(quality["candidate_runtime_failed"])

    def test_cli_partial_completion_requires_exact_session_and_final_artifacts(self):
        for complete, gate, files, expected in (
            (True, "EXACT_COMPLETED_SESSION", True, 0),
            (False, "EXACT_COMPLETED_SESSION", True, 1),
            (True, "INCOMPLETE_SESSION", True, 1),
            (True, "EXACT_COMPLETED_SESSION", False, 1),
        ):
            with self.subTest(complete=complete, gate=gate, files=files), TemporaryDirectory() as directory:
                if files:
                    for name in ("daily-report.json", "daily-report.html"):
                        Path(directory, name).write_text("final", encoding="utf-8")
                payload = {"cloud_daily_report": {"status": "PARTIAL_DATA_QUALITY",
                           "calendar_gate": gate, "data_quality": {"operationally_complete": complete}}}
                with patch("scripts.run_cloud_daily_report.resolve_cloud_trade_date", return_value=US_T_DAY), \
                     patch("scripts.run_cloud_daily_report.run_cloud_daily_report", return_value=payload):
                    self.assertEqual(cloud_report_main(["--market", "US", "--output", directory]), expected)
                self.assertEqual(payload["cloud_daily_report"]["status"], "PARTIAL_DATA_QUALITY")

    def test_mobile_dashboard_uses_human_wave_mapping_and_collapsed_raw_data(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        projection = build_dashboard_projection(payload)
        rows = {row["symbol"]: row for row in projection["rows"]}
        self.assertEqual(rows["600001.SH"]["current_wave_label"], "2浪调整中｜继续观察")
        self.assertEqual(rows["600002.SH"]["current_wave_label"], "3浪进行中｜等待延续确认")
        self.assertEqual(rows["600003.SH"]["current_wave_label"], "3浪结构策略跟踪持仓中")
        self.assertEqual(rows["AAA"]["current_wave_label"], "3浪启动条件已确认")
        self.assertEqual(rows["600002.SH"]["missing_condition"], "还差：收盘价有效突破前一段上涨高点 123.45")
        html = render_dashboard_html(payload)
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', html)
        self.assertIn('font:16px/1.5', html)
        self.assertNotIn("<table", html)
        self.assertIn("查看交易依据", html)
        self.assertIn("开发者原始数据", html)
        self.assertIn("2浪调整中｜继续观察", html)
        self.assertIn("<details class=\"technical-details\">", html)
        self.assertNotIn("event_identity", html.split('<details class="technical-details">', 1)[0])


if __name__ == "__main__":
    unittest.main()

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from core import Quote
from scripts.run_cloud_daily_report import run_cloud_daily_report
from trading.daily_dashboard import build_dashboard_projection, render_dashboard_html
from trading.ephemeral_market_data import (
    EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION,
    EphemeralMarketDataSnapshot,
    load_ephemeral_market_data,
)
from trading.production_prerequisites import build_production_snapshot

from tests.test_production_prerequisites import (
    AFTER_CLOSE,
    T_DAY,
    _history,
    _latest,
    _rows,
)


FIXTURE = Path(__file__).with_name("fixtures") / "daily_dashboard_v1.json"


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


class CloudDailyReportTests(unittest.TestCase):
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

        def latest(source, watch, end, retry_count, retry_wait, **kwargs):
            return [_quote("600000", "CN", T_DAY, source, "CNY")]

        def history(source, watch, adjustment, start, end, *args, **kwargs):
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
             patch("scripts.run_cloud_daily_report.send_optional_email", return_value={"status": "NOT_CONFIGURED"}):
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
            self.assertEqual(payload["cloud_daily_report"]["notifications"]["bark"]["status"], "SENT")

    def test_mobile_dashboard_uses_human_wave_mapping_and_collapsed_raw_data(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        projection = build_dashboard_projection(payload)
        rows = {row["symbol"]: row for row in projection["rows"]}
        self.assertEqual(rows["600001.SH"]["current_wave_label"], "2浪调整中｜继续观察")
        self.assertEqual(rows["600002.SH"]["current_wave_label"], "3浪进行中｜等待延续确认")
        self.assertEqual(rows["600003.SH"]["current_wave_label"], "3浪结构持仓管理中")
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

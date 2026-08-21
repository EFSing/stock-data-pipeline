import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from core import Quote, expected_latest_trade_date, fresher_quote, quote_sanity_issue, validate_quotes
from main import as_ratio, beijing_now, select_history_series, wanted_markets_for_group
from providers import PROVIDERS, fetch_sina, fetch_tencent, fetch_with_retry, fetch_yfinance
from sheets_client import SheetsClient


def quote(source: str, close: float = 100.0, volume: float = 1_000_000, day: date = date(2026, 8, 14)) -> Quote:
    return Quote(
        symbol="TEST",
        name="测试标的",
        market="US",
        trade_date=day,
        source=source,
        open=99.0,
        high=101.0,
        low=98.0,
        close=close,
        preclose=98.5,
        pct_change=1.52,
        volume=volume,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


class ValidationTests(unittest.TestCase):
    def test_pipeline_timestamp_uses_beijing_time(self):
        current = beijing_now()
        self.assertEqual(current.utcoffset(), timedelta(hours=8))
        self.assertEqual(current.tzinfo.key, "Asia/Shanghai")

    def test_sheet_datetime_is_numeric_beijing_time(self):
        utc_value = datetime(2026, 8, 17, 9, 52, 28, tzinfo=timezone.utc)
        beijing_value = datetime(2026, 8, 17, 17, 52, 28)
        expected = (beijing_value - datetime(1899, 12, 30)).total_seconds() / 86400
        self.assertEqual(SheetsClient._clean(utc_value), expected)

    def test_scheduled_groups_cover_japan_and_sweden(self):
        self.assertEqual(wanted_markets_for_group("asia"), {"CN", "HK", "JP"})
        self.assertEqual(wanted_markets_for_group("us"), {"US", "SE"})
        self.assertEqual(wanted_markets_for_group("all"), {"CN", "HK", "JP", "US", "SE"})

    def test_parses_percentage_tolerance(self):
        self.assertEqual(as_ratio("0.05%", 0.0), 0.0005)
        self.assertEqual(as_ratio("2%", 0.0), 0.02)

    def test_keeps_decimal_tolerance(self):
        self.assertEqual(as_ratio("0.0005", 0.0), 0.0005)

    def test_passes_within_tolerance(self):
        result = validate_quotes(quote("主源"), quote("校验源", close=100.02, volume=1_010_000), 0.0005, 0.02)
        self.assertEqual(result.status, "已验证")

    def test_rejects_date_mismatch(self):
        result = validate_quotes(quote("主源"), quote("校验源", day=date(2026, 8, 13)), 0.0005, 0.02)
        self.assertEqual(result.status, "待复核")
        self.assertFalse(result.date_match)

    def test_rejects_volume_mismatch(self):
        result = validate_quotes(quote("主源"), quote("校验源", volume=900_000), 0.0005, 0.02)
        self.assertEqual(result.status, "待复核")
        self.assertFalse(result.volume_pass)

    def test_single_source_is_not_verified(self):
        result = validate_quotes(quote("主源"), None, 0.0005, 0.02)
        self.assertEqual(result.status, "单源可用")

    def test_same_fallback_source_is_not_double_verified(self):
        result = validate_quotes(quote("Tencent"), quote("Tencent"), 0.0005, 0.02)
        self.assertEqual(result.status, "单源可用")
        self.assertIn("同一数据源", result.note)

    def test_uses_verifier_when_its_trade_date_is_newer(self):
        primary = quote("主源", day=date(2026, 8, 14))
        verifier = quote("校验源", day=date(2026, 8, 17))
        self.assertIs(fresher_quote(primary, verifier), verifier)

    def test_keeps_primary_when_trade_dates_match(self):
        primary = quote("主源")
        verifier = quote("校验源")
        self.assertIs(fresher_quote(primary, verifier), primary)

    def test_expects_same_day_after_weekday_close_buffer(self):
        fetched_at = datetime(2026, 8, 17, 8, 21, tzinfo=timezone.utc)
        self.assertEqual(
            expected_latest_trade_date("Asia/Shanghai", "16:00", fetched_at),
            date(2026, 8, 17),
        )

    def test_does_not_expect_same_day_before_close_buffer(self):
        fetched_at = datetime(2026, 8, 17, 8, 5, tzinfo=timezone.utc)
        self.assertIsNone(expected_latest_trade_date("Asia/Shanghai", "16:00", fetched_at))

    def test_rejects_open_outside_daily_range(self):
        invalid = replace(quote("主源"), open=97.0, low=98.0)
        self.assertEqual(quote_sanity_issue(invalid), "行情字段异常：开盘价不在最低价和最高价之间")

    def test_accepts_consistent_ohlcv(self):
        self.assertIsNone(quote_sanity_issue(quote("主源")))

    def test_yfinance_rate_limit_uses_chart_fallback(self):
        class RateLimitedTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, **kwargs):
                raise RuntimeError("rate limited")

        fallback = [quote("YahooChart")]
        fake_yfinance = SimpleNamespace(Ticker=RateLimitedTicker)
        watch = {
            "统一代码": "BABA", "名称": "阿里巴巴", "市场": "US",
            "yfinance代码": "BABA", "币种": "USD",
        }
        with patch.dict("sys.modules", {"yfinance": fake_yfinance}), patch(
            "providers._fetch_yahoo_chart", return_value=fallback
        ) as chart:
            result = fetch_yfinance(watch, "raw", date(2026, 8, 1), date(2026, 8, 17))
        self.assertEqual(result, fallback)
        chart.assert_called_once_with(watch, "raw", date(2026, 8, 1), date(2026, 8, 17))

    def test_tencent_snapshot_parser(self):
        payload = (
            'v_sh603199="1~九华旅游~603199~33.45~34.00~34.26~34717~0~0~'
            + "~" * 21
            + '20260821154510~-0.55~-1.62~34.26~33.12~33.45/34717/116318671~34717~11632~3.14";'
        )
        watch = {"统一代码": "603199.SH", "AKShare代码": "603199", "名称": "九华旅游", "市场": "CN", "币种": "CNY"}
        with patch("providers._read_public_quote", return_value=payload):
            result = fetch_tencent(watch, "raw", date(2026, 8, 1), date(2026, 8, 21))
        self.assertEqual(result[0].trade_date, date(2026, 8, 21))
        self.assertEqual(result[0].close, 33.45)
        self.assertEqual(result[0].volume, 3_471_700)
        self.assertEqual(result[0].amount, 116_318_671)

    def test_sina_snapshot_parser(self):
        payload = 'var hq_str_sh603199="九华旅游,34.260,34.000,33.450,34.260,33.120,33.450,33.500,3471692,116318671.000,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2026-08-21,15:34:58,00,D";'
        watch = {"统一代码": "603199.SH", "AKShare代码": "603199", "名称": "九华旅游", "市场": "CN", "币种": "CNY"}
        with patch("providers._read_public_quote", return_value=payload):
            result = fetch_sina(watch, "raw", date(2026, 8, 1), date(2026, 8, 21))
        self.assertEqual(result[0].trade_date, date(2026, 8, 21))
        self.assertEqual(result[0].volume, 3_471_692)
        self.assertEqual(result[0].amount, 116_318_671)

    def test_tencent_us_snapshot_uses_regular_session_fields(self):
        fields = [""] * 39
        fields[1], fields[3], fields[4], fields[5] = "阿里巴巴", "130.53", "128.90", "123.47"
        fields[30], fields[33], fields[34] = "2026-08-20 16:04:56", "130.62", "121.88"
        fields[36], fields[37], fields[38] = "28101555", "3563771342", "1.17"
        payload = 'v_usBABA="' + "~".join(fields) + '";'
        watch = {"统一代码": "BABA", "yfinance代码": "BABA", "名称": "阿里巴巴", "市场": "US", "币种": "USD"}
        with patch("providers._read_public_quote", return_value=payload):
            result = fetch_tencent(watch, "raw", date(2026, 8, 1), date(2026, 8, 21))
        self.assertEqual(result[0].trade_date, date(2026, 8, 20))
        self.assertEqual(result[0].close, 130.53)
        self.assertEqual(result[0].volume, 28_101_555)

    def test_tencent_hk_snapshot_parser(self):
        fields = [""] * 39
        fields[1], fields[3], fields[4], fields[5] = "阿里巴巴-W", "123.000", "126.200", "129.200"
        fields[30], fields[33], fields[34] = "2026/08/21 16:08:14", "129.800", "121.500"
        fields[36], fields[37], fields[38] = "146890540", "18249523099.440", "0"
        payload = 'v_r_hk09988="' + "~".join(fields) + '";'
        watch = {"统一代码": "09988.HK", "yfinance代码": "9988.HK", "名称": "阿里巴巴-W", "市场": "HK", "币种": "HKD"}
        with patch("providers._read_public_quote", return_value=payload):
            result = fetch_tencent(watch, "raw", date(2026, 8, 1), date(2026, 8, 21))
        self.assertEqual(result[0].trade_date, date(2026, 8, 21))
        self.assertEqual(result[0].close, 123.0)
        self.assertEqual(result[0].volume, 146_890_540)

    def test_sina_us_snapshot_ignores_premarket_price_and_date(self):
        payload = 'var hq_str_gb_baba="阿里巴巴,130.5300,1.26,2026-08-21 17:35:39,1.6300,123.4700,130.6200,121.8800,191.6200,91.9900,28101435,11278330,313147814671,6.41,20.36,0,0,0,0,2399048607,40,125.9200,-3.58,-4.67,Aug 21 05:35AM EDT,Aug 20 04:02PM EDT,128.9000,346865,1,2026,3560820111.3686";'
        watch = {"统一代码": "BABA", "yfinance代码": "BABA", "名称": "阿里巴巴", "市场": "US", "币种": "USD"}
        with patch("providers._read_public_quote", return_value=payload):
            result = fetch_sina(watch, "raw", date(2026, 8, 1), date(2026, 8, 21))
        self.assertEqual(result[0].trade_date, date(2026, 8, 20))
        self.assertEqual(result[0].close, 130.53)
        self.assertNotEqual(result[0].close, 125.92)

    def test_sina_hk_snapshot_parser(self):
        payload = 'var hq_str_hk09988="BABA-W,阿里巴巴-W,129.200,126.200,129.800,121.500,123.000,-3.200,-2.536,123.00000,123.10000,18249523099,146890540,0,0,184.566,88.650,2026/08/21,16:08";'
        watch = {"统一代码": "09988.HK", "yfinance代码": "9988.HK", "名称": "阿里巴巴-W", "市场": "HK", "币种": "HKD"}
        with patch("providers._read_public_quote", return_value=payload):
            result = fetch_sina(watch, "raw", date(2026, 8, 1), date(2026, 8, 21))
        self.assertEqual(result[0].trade_date, date(2026, 8, 21))
        self.assertEqual(result[0].close, 123.0)
        self.assertEqual(result[0].volume, 146_890_540)

    def test_akshare_is_not_an_active_provider(self):
        self.assertNotIn("AKShare", PROVIDERS)

    def test_legacy_akshare_us_config_routes_to_tencent(self):
        watch = {"统一代码": "BABA", "市场": "US"}
        fallback = [quote("Tencent")]
        with patch.dict("providers.PROVIDERS", {
            "Tencent": lambda *args: fallback,
            "Sina": lambda *args: [quote("Sina")],
        }, clear=True):
            result = fetch_with_retry("AKShare", watch, "raw", date(2026, 8, 1), date(2026, 8, 21), 1, 0)
        self.assertEqual(result, fallback)

    def test_us_source_falls_back_when_regular_close_date_is_stale(self):
        watch = {"统一代码": "BABA", "市场": "US"}
        stale = [quote("yfinance", day=date(2026, 8, 19))]
        current = [quote("Tencent", day=date(2026, 8, 20))]
        with patch.dict("providers.PROVIDERS", {
            "yfinance": lambda *args: stale,
            "Tencent": lambda *args: current,
            "Sina": lambda *args: [quote("Sina", day=date(2026, 8, 20))],
        }, clear=True):
            result = fetch_with_retry(
                "yfinance", watch, "raw", date(2026, 8, 1), date(2026, 8, 21),
                1, 0, target_trade_date=date(2026, 8, 20),
            )
        self.assertEqual(result, current)

    def test_sweden_does_not_use_tencent_or_sina_fallbacks(self):
        watch = {"统一代码": "SIVE.SE", "市场": "SE"}
        calls = []
        with patch.dict("providers.PROVIDERS", {
            "yfinance": lambda *args: calls.append("yfinance") or (_ for _ in ()).throw(RuntimeError("down")),
            "Tencent": lambda *args: calls.append("Tencent") or [quote("Tencent")],
            "Sina": lambda *args: calls.append("Sina") or [quote("Sina")],
        }, clear=True):
            with self.assertRaises(RuntimeError):
                fetch_with_retry("yfinance", watch, "raw", date(2026, 8, 1), date(2026, 8, 21), 1, 0)
        self.assertEqual(calls, ["yfinance"])

    def test_history_selection_prefers_full_series_over_snapshot(self):
        snapshot = [quote("Tencent", day=date(2026, 8, 21))]
        history = [quote("yfinance", day=date(2026, 8, 19)), quote("yfinance", day=date(2026, 8, 20))]
        source, result = select_history_series("AKShare", snapshot, "yfinance", history, snapshot[0])
        self.assertEqual(source, "yfinance")
        self.assertEqual(
            [item.trade_date for item in result],
            [date(2026, 8, 19), date(2026, 8, 20), date(2026, 8, 21)],
        )

    def test_cn_provider_falls_back_to_tencent(self):
        watch = {"统一代码": "603199.SH", "市场": "CN"}
        fallback = [quote("Tencent")]
        with patch.dict("providers.PROVIDERS", {
            "yfinance": lambda *args: (_ for _ in ()).throw(RuntimeError("down")),
            "Tencent": lambda *args: fallback,
            "Sina": lambda *args: [quote("Sina")],
        }, clear=True):
            result = fetch_with_retry("AKShare", watch, "raw", date(2026, 8, 1), date(2026, 8, 21), 1, 0)
        self.assertEqual(result, fallback)

    def test_cn_provider_falls_back_when_source_date_is_stale(self):
        watch = {"统一代码": "603199.SH", "市场": "CN"}
        calls = {"BaoStock": 0}

        def stale_baostock(*args):
            calls["BaoStock"] += 1
            return [quote("BaoStock", day=date(2026, 8, 20))]

        sina = [quote("Sina", day=date(2026, 8, 21))]
        with patch.dict("providers.PROVIDERS", {
            "BaoStock": stale_baostock,
            "Sina": lambda *args: sina,
            "Tencent": lambda *args: [quote("Tencent", day=date(2026, 8, 21))],
        }, clear=True):
            result = fetch_with_retry(
                "BaoStock", watch, "raw", date(2026, 8, 1), date(2026, 8, 21),
                3, 0, target_trade_date=date(2026, 8, 21),
            )
        self.assertEqual(result, sina)
        self.assertEqual(calls["BaoStock"], 1)

    def test_stale_date_is_allowed_without_target_trade_date(self):
        watch = {"统一代码": "603199.SH", "市场": "CN"}
        stale = [quote("BaoStock", day=date(2026, 8, 20))]
        with patch.dict("providers.PROVIDERS", {
            "BaoStock": lambda *args: stale,
            "Sina": lambda *args: [quote("Sina", day=date(2026, 8, 21))],
            "Tencent": lambda *args: [quote("Tencent", day=date(2026, 8, 21))],
        }, clear=True):
            result = fetch_with_retry(
                "BaoStock", watch, "raw", date(2026, 8, 1), date(2026, 8, 21), 1, 0
            )
        self.assertEqual(result, stale)


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace
from datetime import date, datetime, timezone

from core import Quote, expected_latest_trade_date, fresher_quote, quote_sanity_issue, validate_quotes
from main import as_ratio, wanted_markets_for_group
from providers import fetch_yfinance


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


if __name__ == "__main__":
    unittest.main()

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from core import (
    Quote,
    expected_latest_trade_date,
    fresher_quote,
    latest_completed_market_session,
    ordinary_calendar_freshness_guard,
    quote_sanity_issue,
    validate_quotes,
)
from main import as_ratio, beijing_now, select_history_series, wanted_markets_for_group
from latest_snapshot import (
    evaluate_latest_snapshot,
    latest_row_is_monitorable,
    project_latest_failure_row,
    project_latest_row,
)
from providers import (
    PROVIDERS,
    _as_date,
    _fetch_yahoo_chart_latest,
    fetch_latest_with_retry,
    fetch_sina,
    fetch_tencent,
    fetch_with_retry,
    fetch_yfinance,
    fetch_yfinance_latest,
)
from sheets_client import SheetsClient


def quote(
    source: str,
    close: float = 100.0,
    volume: float | None = 1_000_000,
    day: date = date(2026, 8, 14),
    preclose: float | None = 98.5,
) -> Quote:
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
        preclose=preclose,
        pct_change=1.52,
        volume=volume,
        amount=None,
        turnover_rate=None,
        currency="USD",
    )


class ValidationTests(unittest.TestCase):
    def test_shared_latest_snapshot_matches_verified_scheduled_projection(self):
        fetched_at = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
        snapshot = evaluate_latest_snapshot(
            [quote("yfinance", day=date(2026, 8, 28))],
            [quote("Tencent", day=date(2026, 8, 28))],
            fetched_at=fetched_at,
            timezone_name="America/New_York",
            close_time_text="16:00",
            close_tolerance=0.0005,
            volume_tolerance=0.02,
            primary_source="yfinance",
            verifier_source="Tencent",
        )

        self.assertEqual(snapshot.completed_trade_date, date(2026, 8, 28))
        self.assertEqual(snapshot.displayed_status, "已验证")
        self.assertTrue(snapshot.confirmed)
        row = project_latest_row(snapshot, fetched_at)
        self.assertEqual(row["交易日期"], date(2026, 8, 28))
        self.assertEqual(row["抓取时间"], fetched_at)

    def test_shared_latest_snapshot_keeps_volume_warning_non_blocking(self):
        fetched_at = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
        snapshot = evaluate_latest_snapshot(
            [quote("yfinance", day=date(2026, 8, 28))],
            [quote("Tencent", volume=900_000, day=date(2026, 8, 28))],
            fetched_at=fetched_at,
            timezone_name="America/New_York",
            close_time_text="16:00",
            close_tolerance=0.0005,
            volume_tolerance=0.02,
            primary_source="yfinance",
            verifier_source="Tencent",
        )

        self.assertEqual(snapshot.validation.status, "已验证")
        self.assertEqual(snapshot.displayed_status, "已验证")
        self.assertTrue(snapshot.confirmed)
        self.assertFalse(snapshot.validation.volume_pass)
        self.assertIsNotNone(snapshot.validation.volume_diff)
        self.assertIn("成交量差异超限或缺失", snapshot.validation.note)
        self.assertIn("仅提示，不影响行情可用性", snapshot.validation.note)

    def test_shared_latest_snapshot_allows_current_single_source_pending_semantics(self):
        fetched_at = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
        snapshot = evaluate_latest_snapshot(
            [quote("yfinance", day=date(2026, 8, 28))],
            [quote("Tencent", day=date(2026, 8, 27))],
            fetched_at=fetched_at,
            timezone_name="America/New_York",
            close_time_text="16:00",
            close_tolerance=0.0005,
            volume_tolerance=0.02,
            primary_source="yfinance",
            verifier_source="Tencent",
        )

        self.assertEqual(snapshot.validation.status, "待复核")
        self.assertEqual(snapshot.chosen.trade_date, date(2026, 8, 28))
        self.assertEqual(snapshot.displayed_status, "待复核")
        self.assertTrue(snapshot.publishable)

    def test_shared_latest_snapshot_rejects_calendar_stale_source_for_lifecycle(self):
        fetched_at = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
        snapshot = evaluate_latest_snapshot(
            [quote("yfinance", day=date(2026, 8, 26))],
            [quote("Tencent", day=date(2026, 8, 26))],
            fetched_at=fetched_at,
            timezone_name="America/New_York",
            close_time_text="16:00",
            close_tolerance=0.0005,
            volume_tolerance=0.02,
            primary_source="yfinance",
            verifier_source="Tencent",
        )

        self.assertFalse(snapshot.publishable)
        self.assertIn("freshness guard", snapshot.blocking_reason)

    def test_monitor_freshness_contract_rejects_unavailable_or_old_rows(self):
        expected = date(2026, 8, 28)
        row = {
            "统一代码": "TEST",
            "正式收盘": True,
            "校验状态": "已验证",
            "交易日期": expected,
        }
        self.assertTrue(latest_row_is_monitorable(row, expected, require_verified=True))
        self.assertFalse(
            latest_row_is_monitorable(
                {**row, "交易日期": date(2026, 8, 27)},
                expected,
                require_verified=True,
            )
        )
        unavailable = project_latest_failure_row(
            row,
            row,
            datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc),
            "provider unavailable",
        )
        self.assertFalse(latest_row_is_monitorable(unavailable, expected))
        self.assertEqual(unavailable["交易日期"], expected)

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
        self.assertEqual(
            result.note,
            "校验源日期滞后，已采用更新来源；最新交易日仅单源可用",
        )

    def test_accepts_volume_mismatch_as_verified(self):
        result = validate_quotes(quote("主源"), quote("校验源", volume=900_000), 0.0005, 0.02)
        self.assertEqual(result.status, "已验证")
        self.assertTrue(result.date_match)
        self.assertTrue(result.close_pass)
        self.assertFalse(result.volume_pass)
        self.assertAlmostEqual(result.volume_diff, 0.1)
        self.assertIn("仅提示，不影响行情可用性", result.note)

    def test_accepts_missing_volume_as_verified_with_warning(self):
        result = validate_quotes(
            quote("主源"), quote("校验源", volume=None), 0.0005, 0.02
        )
        self.assertEqual(result.status, "已验证")
        self.assertTrue(result.date_match)
        self.assertTrue(result.close_pass)
        self.assertFalse(result.volume_pass)
        self.assertIsNone(result.volume_diff)
        self.assertIn("成交量差异超限或缺失", result.note)
        self.assertIn("仅提示，不影响行情可用性", result.note)

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

    def test_newer_verifier_is_selected_but_not_marked_verified(self):
        primary = quote("yfinance", day=date(2026, 8, 27))
        verifier = quote("Tencent", day=date(2026, 8, 28))
        self.assertIs(fresher_quote(primary, verifier), verifier)
        result = validate_quotes(primary, verifier, 0.0005, 0.02)
        self.assertEqual(result.status, "待复核")
        self.assertIn("主源日期滞后", result.note)
        self.assertIn("仅单源可用", result.note)

    def test_newer_primary_is_selected_but_not_marked_verified(self):
        primary = quote("yfinance", day=date(2026, 8, 28))
        verifier = quote("Tencent", day=date(2026, 8, 27))
        self.assertIs(fresher_quote(primary, verifier), primary)
        result = validate_quotes(primary, verifier, 0.0005, 0.02)
        self.assertEqual(result.status, "待复核")
        self.assertIn("校验源日期滞后", result.note)

    def test_keeps_primary_when_trade_dates_match(self):
        primary = quote("主源")
        verifier = quote("校验源")
        self.assertIs(fresher_quote(primary, verifier), primary)

    def test_uses_sane_verifier_when_same_day_primary_open_is_invalid(self):
        primary = replace(quote("yfinance"), open=102.0, high=101.0)
        verifier = quote("Tencent")
        self.assertIs(fresher_quote(primary, verifier), verifier)

    def test_keeps_primary_when_both_same_day_quotes_are_invalid(self):
        primary = replace(quote("yfinance"), open=102.0, high=101.0)
        verifier = replace(quote("Tencent"), low=102.0, high=101.0)
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

    def test_cn_friday_close_to_saturday_delay_keeps_friday_session(self):
        fetched_at = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
        observed = [
            quote("yfinance", day=date(2026, 8, 28)),
            quote("Tencent", day=date(2026, 8, 28)),
        ]
        self.assertEqual(
            latest_completed_market_session(
                "Asia/Shanghai", "15:00", fetched_at, observed
            ),
            date(2026, 8, 28),
        )

    def test_us_friday_close_to_beijing_saturday_keeps_us_session_date(self):
        fetched_at = datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc)
        observed = [
            quote("yfinance", day=date(2026, 8, 28)),
            quote("Tencent", day=date(2026, 8, 28)),
        ]
        self.assertEqual(
            latest_completed_market_session(
                "America/New_York", "16:00", fetched_at, observed
            ),
            date(2026, 8, 28),
        )

    def test_latest_completed_session_before_after_close_and_weekend(self):
        previous = quote("Tencent", day=date(2026, 8, 27))
        current = quote("Tencent", day=date(2026, 8, 28))
        before_close = datetime(2026, 8, 28, 19, 0, tzinfo=timezone.utc)
        after_close = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
        weekend = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(
            latest_completed_market_session(
                "America/New_York", "16:00", before_close, [previous, current]
            ),
            date(2026, 8, 27),
        )
        self.assertEqual(
            latest_completed_market_session(
                "America/New_York", "16:00", after_close, [previous, current]
            ),
            date(2026, 8, 28),
        )
        self.assertEqual(
            latest_completed_market_session(
                "America/New_York", "16:00", weekend, [previous, current]
            ),
            date(2026, 8, 28),
        )

    def test_ordinary_calendar_guard_covers_weekday_and_weekend(self):
        self.assertEqual(
            ordinary_calendar_freshness_guard(
                "America/New_York", "16:00",
                datetime(2026, 8, 28, 19, 30, tzinfo=timezone.utc),
            ),
            date(2026, 8, 27),
        )
        self.assertEqual(
            ordinary_calendar_freshness_guard(
                "America/New_York", "16:00",
                datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc),
            ),
            date(2026, 8, 28),
        )
        self.assertEqual(
            ordinary_calendar_freshness_guard(
                "America/New_York", "16:00",
                datetime(2026, 8, 28, 19, 0, tzinfo=timezone.utc),
            ),
            date(2026, 8, 27),
        )

    def test_future_dated_quote_is_not_a_completed_session(self):
        future = quote("yfinance", day=date(2026, 8, 29))
        self.assertIsNone(
            latest_completed_market_session(
                "America/New_York", "16:00",
                datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc),
                [future],
            )
        )

    def test_provider_timestamp_uses_market_local_session_date(self):
        self.assertEqual(
            _as_date("2026-08-29T00:30:00Z", "America/New_York"),
            date(2026, 8, 28),
        )
        self.assertEqual(
            _as_date(datetime(2026, 8, 29, 0, 30, tzinfo=timezone.utc), "America/New_York"),
            date(2026, 8, 28),
        )
        self.assertEqual(
            _as_date("2026-08-28T07:30:00Z", "Asia/Shanghai"),
            date(2026, 8, 28),
        )

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

    def test_yfinance_historical_incomplete_tail_uses_chart_instead_of_stale_row(self):
        calls = []

        class IncompleteTailTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, **kwargs):
                calls.append(kwargs)
                return pd.DataFrame(
                    {
                        "Open": [99.0, 101.0],
                        "High": [101.0, 103.0],
                        "Low": [98.0, 100.0],
                        "Close": [100.0, None],
                        "Volume": [1_000_000, 2_000_000],
                    },
                    index=pd.to_datetime(["2026-08-27", "2026-08-28"]),
                )

        fallback = [quote("YahooChart", close=102.0, day=date(2026, 8, 28))]
        fake_yfinance = SimpleNamespace(Ticker=IncompleteTailTicker)
        watch = {
            "统一代码": "BABA", "名称": "阿里巴巴", "市场": "US",
            "yfinance代码": "BABA", "币种": "USD", "时区": "America/New_York",
        }
        with patch.dict("sys.modules", {"yfinance": fake_yfinance}), patch(
            "providers._fetch_yahoo_chart", return_value=fallback
        ) as chart:
            result = fetch_yfinance(watch, "qfq", date(2026, 8, 1), date(2026, 8, 28))

        self.assertEqual(result, fallback)
        self.assertTrue(calls[0]["auto_adjust"])
        chart.assert_called_once_with(watch, "qfq", date(2026, 8, 1), date(2026, 8, 28))

    def test_yfinance_qfq_stale_complete_payload_uses_chart_for_exact_target(self):
        calls = []

        class StaleTailTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, **kwargs):
                calls.append(kwargs)
                frame = pd.DataFrame(
                    {
                        "Open": [99.0, 101.0],
                        "High": [101.0, 103.0],
                        "Low": [98.0, 100.0],
                        "Close": [100.0, 102.0],
                        "Volume": [1_000_000, 2_000_000],
                    },
                    index=pd.to_datetime(["2026-09-12", "2026-09-14"]),
                )
                frame.index.name = "Date"
                return frame

        target = date(2026, 9, 15)
        fallback = [quote("YahooChart", day=target)]
        fake_yfinance = SimpleNamespace(Ticker=StaleTailTicker)
        watch = {
            "统一代码": "BABA", "名称": "阿里巴巴", "市场": "US",
            "yfinance代码": "BABA", "币种": "USD", "时区": "America/New_York",
        }
        with patch.dict("sys.modules", {"yfinance": fake_yfinance}), patch(
            "providers._fetch_yahoo_chart", return_value=fallback
        ) as chart:
            result = fetch_with_retry(
                "yfinance", watch, "qfq", date(2026, 9, 1), target,
                1, 0, target_trade_date=target,
            )

        self.assertEqual(result, fallback)
        self.assertTrue(calls[0]["auto_adjust"])
        chart.assert_called_once_with(watch, "qfq", date(2026, 9, 1), target)

    def test_yfinance_qfq_stale_chart_remains_fail_closed(self):
        class StaleTailTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, **kwargs):
                frame = pd.DataFrame(
                    {
                        "Open": [99.0, 101.0],
                        "High": [101.0, 103.0],
                        "Low": [98.0, 100.0],
                        "Close": [100.0, 102.0],
                        "Volume": [1_000_000, 2_000_000],
                    },
                    index=pd.to_datetime(["2026-09-12", "2026-09-14"]),
                )
                frame.index.name = "Date"
                return frame

        target = date(2026, 9, 15)
        fallback = [quote("YahooChart", day=date(2026, 9, 14))]
        fake_yfinance = SimpleNamespace(Ticker=StaleTailTicker)
        watch = {
            "统一代码": "BABA", "名称": "阿里巴巴", "市场": "US",
            "yfinance代码": "BABA", "币种": "USD", "时区": "America/New_York",
        }
        with patch.dict("sys.modules", {"yfinance": fake_yfinance}), patch(
            "providers._fetch_yahoo_chart", return_value=fallback
        ) as chart:
            with self.assertRaisesRegex(
                RuntimeError,
                r"2026-09-14.*2026-09-15",
            ):
                fetch_with_retry(
                    "yfinance", watch, "qfq", date(2026, 9, 1), target,
                    1, 0, target_trade_date=target,
                )

        chart.assert_called_once_with(watch, "qfq", date(2026, 9, 1), target)

    def test_yfinance_latest_uses_bounded_window_when_period_tail_is_incomplete(self):
        calls = []

        class IncompleteTailTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, **kwargs):
                calls.append(kwargs)
                return pd.DataFrame(
                    {
                        "Open": [36.8, 29.24],
                        "High": [38.5, 31.38],
                        "Low": [36.12, 26.86],
                        "Close": [36.16, None],
                        "Volume": [4_677_985, 20_084_657],
                    },
                    index=pd.to_datetime(["2026-08-27", "2026-08-28"]),
                )

        fallback = [quote("YahooChart", close=27.32, day=date(2026, 8, 28))]
        fake_yfinance = SimpleNamespace(Ticker=IncompleteTailTicker)
        watch = {
            "统一代码": "SIVE.SE", "名称": "Sivers Semiconductors", "市场": "SE",
            "yfinance代码": "SIVE.ST", "币种": "SEK", "时区": "Europe/Stockholm",
        }
        with patch.dict("sys.modules", {"yfinance": fake_yfinance}), patch(
            "providers._fetch_yahoo_chart_latest", return_value=fallback
        ) as chart:
            result = fetch_yfinance_latest(watch, date(2026, 8, 30))

        self.assertEqual(result, fallback)
        self.assertEqual(calls[0]["start"], "2026-08-23")
        self.assertEqual(calls[0]["end"], "2026-08-31")
        self.assertNotIn("period", calls[0])
        chart.assert_called_once_with(watch, date(2026, 8, 30))

    def test_yahoo_chart_latest_probe_keeps_prior_close_in_bounded_window(self):
        watch = {
            "统一代码": "512400.SH", "名称": "ETF", "市场": "CN",
            "yfinance代码": "512400.SS", "币种": "CNY",
        }
        calls = []
        expected = [quote("YahooChart", day=date(2026, 8, 28))]

        def chart(watch_row, adjust, start, end):
            calls.append((watch_row, adjust, start, end))
            return expected

        with patch("providers._fetch_yahoo_chart", side_effect=chart):
            result = _fetch_yahoo_chart_latest(watch, date(2026, 8, 28))

        self.assertEqual(result, expected)
        self.assertEqual(
            calls,
            [(watch, "raw", date(2026, 8, 21), date(2026, 8, 28))],
        )

    def test_yahoo_chart_latest_keeps_probing_when_first_current_row_lacks_preclose(self):
        watch = {
            "统一代码": "BABA", "名称": "阿里巴巴", "市场": "US",
            "yfinance代码": "BABA", "币种": "USD",
        }
        calls = []
        current = quote("YahooChart", close=102.0, day=date(2026, 8, 28), preclose=None)
        prior = quote("YahooChart", close=99.0, day=date(2026, 8, 27))

        def chart(watch_row, adjust, start, end):
            calls.append((watch_row, adjust, start, end))
            return [current] if len(calls) == 1 else [prior]

        with patch("providers._fetch_yahoo_chart", side_effect=chart):
            result = _fetch_yahoo_chart_latest(watch, date(2026, 8, 28))

        self.assertEqual(result[-1].trade_date, date(2026, 8, 28))
        self.assertEqual(result[-1].preclose, 99.0)
        self.assertEqual(len(calls), 2)

    def test_yfinance_latest_uses_chart_lookback_when_single_row_lacks_preclose(self):
        class SingleRowTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, **kwargs):
                return pd.DataFrame(
                    {
                        "Open": [101.0],
                        "High": [103.0],
                        "Low": [99.0],
                        "Close": [102.0],
                        "Volume": [1_000_000],
                    },
                    index=pd.to_datetime(["2026-08-28"]),
                )

        fallback = [quote("YahooChart", day=date(2026, 8, 28))]
        fake_yfinance = SimpleNamespace(Ticker=SingleRowTicker)
        watch = {
            "统一代码": "BABA", "名称": "阿里巴巴", "市场": "US",
            "yfinance代码": "BABA", "币种": "USD", "时区": "America/New_York",
        }
        with patch.dict("sys.modules", {"yfinance": fake_yfinance}), patch(
            "providers._fetch_yahoo_chart_latest", return_value=fallback
        ) as chart:
            result = fetch_yfinance_latest(watch, date(2026, 8, 28))

        self.assertEqual(result, fallback)
        chart.assert_called_once_with(watch, date(2026, 8, 28))

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

    def test_history_selection_replaces_invalid_same_day_bar_with_chosen_quote(self):
        invalid_latest = replace(
            quote("yfinance", day=date(2026, 8, 21)),
            open=102.0,
            high=101.0,
        )
        history = [
            quote("yfinance", day=date(2026, 8, 20)),
            invalid_latest,
        ]
        chosen = quote("Tencent", day=date(2026, 8, 21))

        source, result = select_history_series(
            "yfinance",
            history,
            "Tencent",
            [chosen],
            chosen,
        )

        self.assertEqual(source, "yfinance")
        self.assertIs(result[-1], chosen)
        self.assertIsNone(quote_sanity_issue(result[-1]))

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

    def test_latest_source_falls_back_when_exact_session_is_stale(self):
        watch = {"统一代码": "BABA", "市场": "US"}
        stale = [quote("yfinance", day=date(2026, 8, 19))]
        current = [quote("Tencent", day=date(2026, 8, 20))]
        with patch.dict("providers.LATEST_PROVIDERS", {
            "yfinance": lambda *args: stale,
            "Tencent": lambda *args: current,
            "Sina": lambda *args: [quote("Sina", day=date(2026, 8, 20))],
        }, clear=True):
            result = fetch_latest_with_retry(
                "yfinance", watch, date(2026, 8, 20), 1, 0,
                target_trade_date=date(2026, 8, 20),
            )
        self.assertEqual(result, current)

    def test_latest_source_fallback_skips_excluded_actual_source(self):
        watch = {"统一代码": "BABA", "市场": "US"}
        t_day = date(2026, 8, 20)
        current = [quote("Sina", day=t_day)]
        with patch.dict("providers.LATEST_PROVIDERS", {
            "Tencent": lambda *args: [quote("Tencent", day=t_day)],
            "Sina": lambda *args: current,
        }, clear=True):
            result = fetch_latest_with_retry(
                "Tencent", watch, t_day, 1, 0,
                target_trade_date=t_day,
                excluded_sources={"Tencent"},
            )
        self.assertEqual(result, current)

    def test_latest_source_fallback_rejects_internal_collision_before_returning(self):
        watch = {"统一代码": "BABA", "市场": "US"}
        t_day = date(2026, 8, 20)
        with patch.dict("providers.LATEST_PROVIDERS", {
            "yfinance": lambda *args: [quote("YahooChart", day=t_day)],
            "Tencent": lambda *args: [quote("Tencent", day=t_day)],
            "Sina": lambda *args: [quote("Sina", day=t_day)],
        }, clear=True):
            result = fetch_latest_with_retry(
                "yfinance", watch, t_day, 1, 0,
                target_trade_date=t_day,
                excluded_sources={"YahooChart"},
            )
        self.assertEqual(result[0].source, "Tencent")

    def test_replay_fetch_can_preserve_source_order_for_quality_gate(self):
        watch = {"统一代码": "603199.SH", "市场": "CN"}
        newest = quote("BaoStock", day=date(2026, 8, 21))
        older = quote("BaoStock", day=date(2026, 8, 20))
        source_order = [newest, older]
        with patch.dict(
            "providers.PROVIDERS",
            {"BaoStock": lambda *args: source_order},
            clear=True,
        ):
            result = fetch_with_retry(
                "BaoStock",
                watch,
                "qfq",
                date(2026, 8, 1),
                date(2026, 8, 21),
                1,
                0,
                preserve_source_order=True,
            )

        self.assertEqual(result, source_order)


if __name__ == "__main__":
    unittest.main()

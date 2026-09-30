from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from unittest import TestCase
from unittest.mock import patch

from core import Quote
from market_data_contract import (
    CN_ADJUSTMENT_ENGINE_VERSION,
    CN_ETF_ADJUSTMENT_ENGINE_VERSION,
    DATA_ADJUSTMENT_UNVERIFIED,
    CN_SINGLE_SOURCE_PROVIDER,
    DATA_OK,
    DATA_INVALID,
    DATA_MISSING,
    DATA_STALE,
    DATA_UNAVAILABLE_FOR_DECISION,
    AdjustmentUnverifiedError,
    ProviderGlobalFailure,
    ProviderSymbolError,
    SINGLE_SOURCE_MARKET_DATA_VERSION,
    US_ADJUSTMENT_ENGINE_VERSION,
    US_SINGLE_SOURCE_PROVIDER,
    unavailable_reason,
    source_provenance,
    validate_single_source_quotes,
)
from providers import (
    SingleSourceFetchResult,
    fetch_hithink_with_provenance,
    fetch_yahoo_chart_with_provenance,
)
from trading.ephemeral_market_data import load_ephemeral_market_data


T_DAY = date(2026, 9, 28)
AFTER_CLOSE = datetime(2026, 9, 28, 16, 0).astimezone()


def _quotes(symbol: str, market: str, source: str, end: date = T_DAY, count: int = 65) -> tuple[Quote, ...]:
    values = []
    for index in range(count):
        trade_date = end - timedelta(days=count - index - 1)
        close = 10.0 + index * 0.1
        values.append(
            Quote(
                symbol, symbol, market, trade_date, source,
                close - 0.1, close + 0.2, close - 0.2, close,
                close - 0.05, 1.0, 1000 + index, close * 1000, 1.0,
                "CNY" if market == "CN" else "USD",
            )
        )
    return tuple(values)


class _FakeSheets:
    def __init__(self, symbols: tuple[str, ...], market: str = "CN"):
        market = market.upper()
        provider = CN_SINGLE_SOURCE_PROVIDER if market == "CN" else US_SINGLE_SOURCE_PROVIDER
        currency = "CNY" if market == "CN" else "USD"
        self.rows = {
            "策略账户": [{"账户ID": "MAIN", "启用": "TRUE", "市场": market}],
            "策略股票池": [
                {"账户ID": "MAIN", "启用": "TRUE", "市场": market, "统一代码": symbol}
                for symbol in symbols
            ],
            "策略持仓": [],
            "策略模拟账本": [],
            "自选清单": [
                {
                    "启用": "TRUE", "市场": market, "统一代码": symbol,
                    "名称": symbol, "主数据源": provider,
                    "校验数据源": "", "历史数据源": provider,
                    **({"HITHINK代码": symbol} if market == "CN" else {"yfinance代码": symbol}),
                    "时区": "Asia/Shanghai" if market == "CN" else "America/New_York",
                    "收盘时间": "15:00" if market == "CN" else "16:00", "币种": currency,
                }
                for symbol in symbols
            ],
        }

    def config(self):
        return {"history_days": "1000", "retry_count": "1", "retry_wait_seconds": "0"}

    def records(self, sheet_name: str):
        return list(self.rows.get(sheet_name, []))


class SingleSourceMarketDataTests(TestCase):
    def test_hithink_qfq_uses_raw_bars_and_internal_action_chain(self):
        raw_items = [
            {
                "date_ms": int(datetime(2026, 9, 25, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).timestamp() * 1000),
                "open_price": 10, "high_price": 11, "low_price": 9, "close_price": 10,
                "volume": 1000, "turnover": 10000,
            },
            {
                "date_ms": int(datetime(2026, 9, 28, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).timestamp() * 1000),
                "open_price": 5, "high_price": 6, "low_price": 4, "close_price": 5,
                "volume": 1100, "turnover": 5500,
            },
        ]
        action_items = [{
            "ex_date_ms": int(datetime(2026, 9, 28, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).timestamp() * 1000),
            "dividend_per_share": 1,
            "per_share_bonus": 0,
        }]

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        def urlopen(request, timeout):
            del timeout
            payload = {"code": 0, "data": {"item": action_items if "corporate-actions" in request.full_url else raw_items}}
            return Response(payload)

        watch = {
            "统一代码": "600000.SH", "名称": "fixture", "市场": "CN", "币种": "CNY",
            "HITHINK代码": "600000.SH",
            "HITHINK资产类型": "a-share",
        }
        with patch.dict(os.environ, {"HITHINK_FINANCE_API_KEY": "fixture"}, clear=False), \
             patch("providers.urlopen", side_effect=urlopen):
            result = fetch_hithink_with_provenance(
                watch, "qfq", date(2026, 9, 25), T_DAY
            )
        self.assertEqual(result.provider, CN_SINGLE_SOURCE_PROVIDER)
        self.assertEqual(result.provenance["adjustment_engine_version"], CN_ADJUSTMENT_ENGINE_VERSION)
        self.assertEqual(result.api_requests, 2)
        self.assertEqual(result.quotes[0].close, 9.0)
        self.assertEqual(result.quotes[1].close, 5.0)

    def test_contract_rejects_future_duplicate_and_negative_volume(self):
        values = list(_quotes("600000.SH", "CN", CN_SINGLE_SOURCE_PROVIDER, count=2))
        values[1] = Quote(
            values[1].symbol, values[1].name, values[1].market,
            values[0].trade_date, values[1].source,
            values[1].open, values[1].high, values[1].low, values[1].close,
            values[1].preclose, values[1].pct_change, -1, values[1].amount,
            values[1].turnover_rate, values[1].currency,
        )
        errors = validate_single_source_quotes(
            (*values, values[0]),
            expected_symbol="600000.SH",
            expected_market="CN",
            max_trade_date=T_DAY,
        )
        self.assertIn("DUPLICATE_SESSION", errors)
        self.assertIn("DATES_NOT_STRICTLY_INCREASING", errors)
        self.assertIn("NEGATIVE_VOLUME", errors)

        invalid_date = values[0]
        invalid_date = Quote(
            invalid_date.symbol, invalid_date.name, invalid_date.market, None,
            invalid_date.source, invalid_date.open, invalid_date.high, invalid_date.low,
            invalid_date.close, invalid_date.preclose, invalid_date.pct_change,
            invalid_date.volume, invalid_date.amount, invalid_date.turnover_rate,
            invalid_date.currency,
        )
        invalid_errors = validate_single_source_quotes(
            (invalid_date,),
            expected_symbol="600000.SH",
            expected_market="CN",
            target_trade_date=T_DAY,
        )
        self.assertIn("DATE_MISSING", invalid_errors)
        self.assertIn("TARGET_SESSION_MISSING", invalid_errors)

    def test_etf_routes_to_same_vendor_fund_endpoint(self):
        calls = []

        def hithink_json(path, params):
            calls.append((path, dict(params)))
            if path == "/api/meta/tickers/search":
                return {"code": 0, "data": {"item": [{
                    "thscode": params["q"], "asset_type": "fund-etf",
                }]}}
            if path == "/api/fund/market/historical":
                return {"code": 0, "data": {"item": [{
                    "date": "2026-09-28", "open_price": 10, "high_price": 11,
                    "low_price": 9, "close_price": 10, "volume": 100,
                }]}}
            self.fail(f"unexpected endpoint: {path}")

        for symbol in ("512400.SH", "159866.SZ"):
            with self.subTest(symbol=symbol):
                calls.clear()
                watch = {
                    "统一代码": symbol, "名称": "fixture ETF", "市场": "CN", "币种": "CNY",
                    "HITHINK代码": symbol,
                }
                with patch("providers._hithink_json", side_effect=hithink_json):
                    result = fetch_hithink_with_provenance(
                        watch, "qfq", date(2026, 9, 25), T_DAY
                    )
                self.assertEqual(result.provider, CN_SINGLE_SOURCE_PROVIDER)
                self.assertEqual(
                    result.provenance["adjustment_engine_version"],
                    CN_ETF_ADJUSTMENT_ENGINE_VERSION,
                )
                self.assertEqual(result.provenance["asset_type"], "fund-etf")
                self.assertEqual(
                    [path for path, _params in calls],
                    ["/api/meta/tickers/search", "/api/fund/market/historical"],
                )

    def test_asset_type_metadata_not_code_prefix_selects_stock_endpoint(self):
        calls = []

        def hithink_json(path, params):
            calls.append(path)
            if path == "/api/meta/tickers/search":
                return {"code": 0, "data": {"item": [{
                    "thscode": "500001.SH", "asset_type": "a-share",
                }]}}
            if path == "/api/a-share/prices/historical":
                return {"code": 0, "data": {"item": [{
                    "date": "2026-09-28", "open_price": 10, "high_price": 11,
                    "low_price": 9, "close_price": 10, "volume": 100,
                }]}}
            self.fail(f"unexpected endpoint: {path}")

        watch = {
            "统一代码": "500001.SH", "名称": "fixture stock", "市场": "CN", "币种": "CNY",
            "HITHINK代码": "500001.SH",
        }
        with patch("providers._hithink_json", side_effect=hithink_json):
            result = fetch_hithink_with_provenance(
                watch, "raw", date(2026, 9, 25), T_DAY
            )
        self.assertEqual(result.provenance["asset_type"], "a-share")
        self.assertIn("/api/a-share/prices/historical", calls)
        self.assertNotIn("/api/fund/market/historical", calls)

    def test_hithink_schema_break_is_provider_global(self):
        watch = {
            "统一代码": "600000.SH", "名称": "fixture", "市场": "CN", "币种": "CNY",
            "HITHINK代码": "600000.SH", "HITHINK资产类型": "a-share",
        }
        with patch(
            "providers._hithink_json",
            return_value={"code": 0, "data": {"item": "not-a-list"}},
        ):
            with self.assertRaises(ProviderGlobalFailure):
                fetch_hithink_with_provenance(
                    watch, "raw", date(2026, 9, 25), T_DAY
                )

    def test_hithink_action_dataset_not_ready_is_adjustment_unverified(self):
        watch = {
            "统一代码": "688981.SH", "名称": "fixture", "市场": "CN", "币种": "CNY",
            "HITHINK代码": "688981.SH", "HITHINK资产类型": "a-share",
        }
        raw_payload = {"code": 0, "data": {"item": [{
            "date": "2026-09-28", "open_price": 10, "high_price": 11,
            "low_price": 9, "close_price": 10, "volume": 100,
        }]}}

        def hithink_json(path, _params):
            if path == "/api/a-share/prices/historical":
                return raw_payload
            raise ProviderSymbolError("HITHINK_SYMBOL_ERROR:3002")

        with patch("providers._hithink_json", side_effect=hithink_json):
            with self.assertRaises(AdjustmentUnverifiedError):
                fetch_hithink_with_provenance(
                    watch, "qfq", date(2026, 9, 25), T_DAY
                )

    def test_hithink_invalid_key_business_code_is_provider_global(self):
        with patch(
            "providers._hithink_json",
            side_effect=ProviderGlobalFailure("HITHINK_PROVIDER_ERROR:2003"),
        ):
            with self.assertRaises(ProviderGlobalFailure):
                fetch_hithink_with_provenance(
                    {
                        "统一代码": "600000.SH", "名称": "fixture", "市场": "CN", "币种": "CNY",
                        "HITHINK代码": "600000.SH", "HITHINK资产类型": "a-share",
                    },
                    "raw",
                    date(2026, 9, 25),
                    T_DAY,
                )

    def test_yahoo_chart_symbol_error_isolated_and_qfq_provenance_is_explicit(self):
        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        symbol_watch = {
            "统一代码": "BAD.US", "名称": "fixture", "市场": "US", "币种": "USD",
            "yfinance代码": "BAD.US",
        }
        not_found = {
            "chart": {"result": [], "error": {"code": "Not Found", "description": "No data found"}}
        }
        with patch("providers.urlopen", return_value=Response(not_found)):
            with self.assertRaises(ProviderSymbolError):
                fetch_yahoo_chart_with_provenance(
                    symbol_watch, "raw", date(2026, 9, 25), T_DAY
                )

        timestamp = int(datetime(2026, 9, 28, 13, tzinfo=timezone.utc).timestamp())
        good = {
            "chart": {
                "error": None,
                "result": [{
                    "timestamp": [timestamp],
                    "meta": {"exchangeTimezoneName": "America/New_York"},
                    "indicators": {
                        "quote": [{
                            "open": [10.0], "high": [11.0], "low": [9.0],
                            "close": [10.0], "volume": [100.0],
                        }],
                        "adjclose": [{"adjclose": [9.0]}],
                    },
                }],
            }
        }
        with patch("providers.urlopen", return_value=Response(good)):
            result = fetch_yahoo_chart_with_provenance(
                {
                    "统一代码": "AAPL", "名称": "fixture", "市场": "US", "币种": "USD",
                    "yfinance代码": "AAPL",
                },
                "qfq",
                date(2026, 9, 25),
                T_DAY,
            )
        self.assertEqual(result.quotes[0].open, 9.0)
        self.assertIn("adjclose", result.provenance["adjusted_ohlcv_source"])

    def test_yahoo_chart_network_failure_is_provider_global(self):
        with patch("providers.urlopen", side_effect=RuntimeError("outage")):
            with self.assertRaises(ProviderGlobalFailure):
                fetch_yahoo_chart_with_provenance(
                    {
                        "统一代码": "AAPL", "名称": "fixture", "市场": "US", "币种": "USD",
                        "yfinance代码": "AAPL",
                    },
                    "raw",
                    date(2026, 9, 25),
                    T_DAY,
                )

    def test_one_stale_symbol_is_blocked_without_blocking_peer(self):
        client = _FakeSheets(("512400.SH", "600000.SH"))

        def fetch(market, watch, adjustment, start, end, *_args, **_kwargs):
            del market, start
            symbol = watch["统一代码"]
            if symbol == "512400.SH":
                raise LookupError("provider tail is 2026-09-24")
            values = _quotes(symbol, "CN", CN_SINGLE_SOURCE_PROVIDER, end=end)
            return SingleSourceFetchResult(
                values,
                CN_SINGLE_SOURCE_PROVIDER,
                source_provenance(
                    market="CN", provider=CN_SINGLE_SOURCE_PROVIDER,
                    adjustment=adjustment,
                    adjustment_engine_version=CN_ADJUSTMENT_ENGINE_VERSION,
                ),
            )

        with patch("trading.ephemeral_market_data.fetch_single_source_with_retry", side_effect=fetch):
            snapshot = load_ephemeral_market_data(
                client, market="CN", as_of_date=T_DAY, now=AFTER_CLOSE
            )
        self.assertEqual(snapshot.symbol_status["600000.SH"]["status"], DATA_OK)
        self.assertEqual(snapshot.symbol_status["512400.SH"]["status"], DATA_STALE)
        self.assertEqual([row["统一代码"] for row in snapshot.latest_rows], ["600000.SH"])
        metadata = snapshot.to_dict()
        self.assertEqual(metadata["market_data_contract"], SINGLE_SOURCE_MARKET_DATA_VERSION)
        self.assertEqual(metadata["coverage_pct"], 50.0)
        self.assertIn("512400.SH", metadata["failed_by_reason"][DATA_STALE])

    def test_provider_global_failure_is_explicit(self):
        client = _FakeSheets(("600000.SH",))
        with patch(
            "trading.ephemeral_market_data.fetch_single_source_with_retry",
            side_effect=ProviderGlobalFailure("auth"),
        ):
            snapshot = load_ephemeral_market_data(
                client, market="CN", as_of_date=T_DAY, now=AFTER_CLOSE
            )
        self.assertEqual(snapshot.symbol_status["600000.SH"]["status"], "PROVIDER_GLOBAL_FAILURE")
        self.assertTrue(snapshot.to_dict()["provider_global_failure"])
        self.assertNotIn("NO_SIGNAL", DATA_UNAVAILABLE_FOR_DECISION)

    def test_provider_global_failure_does_not_fan_out_to_every_symbol(self):
        client = _FakeSheets(tuple(f"600{index:03d}.SH" for index in range(50)))
        with patch(
            "trading.ephemeral_market_data.fetch_single_source_with_retry",
            side_effect=ProviderGlobalFailure("auth"),
        ):
            snapshot = load_ephemeral_market_data(
                client, market="CN", as_of_date=T_DAY, now=AFTER_CLOSE
            )
        self.assertTrue(snapshot.to_dict()["provider_global_failure"])
        self.assertEqual(len(snapshot.provider_status), 1)
        self.assertEqual(len(snapshot.errors), 1)

    def test_missing_data_maps_to_decision_block_not_no_signal(self):
        self.assertEqual(
            unavailable_reason(DATA_MISSING),
            f"{DATA_UNAVAILABLE_FOR_DECISION}:{DATA_MISSING}",
        )
        self.assertNotEqual(DATA_MISSING, "NO_SIGNAL")
        self.assertNotEqual(
            unavailable_reason(DATA_ADJUSTMENT_UNVERIFIED),
            "NO_SIGNAL",
        )

    def test_us_symbol_failure_isolated(self):
        client = _FakeSheets(("AAPL", "BAD.US"), market="US")

        def fetch(market, watch, adjustment, start, end, *_args, **_kwargs):
            del market, start
            if watch["统一代码"] == "BAD.US":
                raise ProviderSymbolError("unknown symbol")
            values = _quotes(watch["统一代码"], "US", US_SINGLE_SOURCE_PROVIDER, end=end)
            return SingleSourceFetchResult(
                values,
                US_SINGLE_SOURCE_PROVIDER,
                source_provenance(
                    market="US", provider=US_SINGLE_SOURCE_PROVIDER,
                    adjustment=adjustment,
                    adjustment_engine_version=US_ADJUSTMENT_ENGINE_VERSION,
                ),
            )

        with patch("trading.ephemeral_market_data.fetch_single_source_with_retry", side_effect=fetch):
            snapshot = load_ephemeral_market_data(
                client,
                market="US",
                as_of_date=T_DAY,
                now=datetime(2026, 9, 29, 1, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(snapshot.symbol_status["AAPL"]["status"], DATA_OK)
        self.assertEqual(snapshot.symbol_status["BAD.US"]["status"], "PROVIDER_SYMBOL_ERROR")
        self.assertEqual(len(snapshot.latest_rows), 1)

    def test_one_fifty_and_three_hundred_failures_do_not_stop_peer(self):
        for failure_count in (1, 50, 300):
            with self.subTest(failure_count=failure_count):
                symbols = tuple(
                    [f"BAD{index:03d}.SH" for index in range(failure_count)]
                    + ["600000.SH"]
                )
                client = _FakeSheets(symbols)

                def fetch(market, watch, adjustment, start, end, *_args, **_kwargs):
                    del market, start
                    if watch["统一代码"].startswith("BAD"):
                        raise ProviderSymbolError("fixture symbol failure")
                    values = _quotes("600000.SH", "CN", CN_SINGLE_SOURCE_PROVIDER, end=end)
                    return SingleSourceFetchResult(
                        values,
                        CN_SINGLE_SOURCE_PROVIDER,
                        source_provenance(
                            market="CN", provider=CN_SINGLE_SOURCE_PROVIDER,
                            adjustment=adjustment,
                            adjustment_engine_version=CN_ADJUSTMENT_ENGINE_VERSION,
                        ),
                    )

                with patch(
                    "trading.ephemeral_market_data.fetch_single_source_with_retry",
                    side_effect=fetch,
                ):
                    snapshot = load_ephemeral_market_data(
                        client, market="CN", as_of_date=T_DAY, now=AFTER_CLOSE
                    )
                self.assertEqual(snapshot.symbol_status["600000.SH"]["status"], DATA_OK)
                self.assertEqual(len(snapshot.latest_rows), 1)
                self.assertEqual(snapshot.to_dict()["coverage_pct"], round(100 / (failure_count + 1), 2))
                self.assertEqual(
                    len(snapshot.to_dict()["failed_by_reason"]["PROVIDER_SYMBOL_ERROR"]),
                    failure_count,
                )


if __name__ == "__main__":
    import unittest

    unittest.main()

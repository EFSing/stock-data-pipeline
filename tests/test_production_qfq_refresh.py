import json
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

from core import Quote
from scripts.refresh_production_qfq import (
    ProductionQfqRefreshError,
    refresh_production_qfq,
)


ROOT = Path(__file__).resolve().parents[1]
TARGET = date(2026, 9, 3)
FETCHED_AT = datetime(2026, 9, 4, 1, 0)


def watch(symbol: str, market: str, source: str = "yfinance") -> dict:
    return {
        "启用": "TRUE",
        "市场": market,
        "统一代码": symbol,
        "名称": symbol,
        "历史数据源": source,
        "yfinance代码": symbol,
        "BaoStock代码": f"sz.{symbol[:6]}",
        "币种": "CNY" if market == "CN" else "USD",
        "时区": "Asia/Shanghai" if market == "CN" else "America/New_York",
    }


def account(account_id: str, market: str, enabled: str = "TRUE") -> dict:
    return {"账户ID": account_id, "启用": enabled, "市场": market}


def pool(symbol: str, market: str, account_id: str = "CN_MAIN", enabled: str = "TRUE") -> dict:
    return {
        "启用": enabled,
        "账户ID": account_id,
        "市场": market,
        "统一代码": symbol,
        "名称": symbol,
    }


def latest(symbol: str, market: str, trade_date: date = TARGET) -> dict:
    return {"市场": market, "统一代码": symbol, "交易日期": trade_date}


def quote(symbol: str, market: str, trade_date: date, source: str) -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
        market=market,
        trade_date=trade_date,
        source=source,
        open=10.0,
        high=11.0,
        low=9.0,
        close=10.5,
        preclose=10.0,
        pct_change=5.0,
        volume=1000,
        amount=10500,
        turnover_rate=1.0,
        currency="CNY" if market == "CN" else "USD",
    )


class FakeSheetsClient:
    def __init__(self, records: dict[str, list[dict]], config: dict | None = None):
        self._records = records
        self._config = config or {
            "history_days": "2",
            "retry_count": "1",
            "retry_wait_seconds": "0",
        }
        self.reads = []
        self.writes = []

    def records(self, sheet_name: str):
        self.reads.append(sheet_name)
        return list(self._records.get(sheet_name, []))

    def config(self):
        self.reads.append("参数设置")
        return dict(self._config)

    def upsert_history(self, sheet_name: str, rows):
        self.writes.append((sheet_name, list(rows)))
        return len(self.writes[-1][1])


def workbook(
    *,
    symbols=(("000725.SZ", "CN", "CN_MAIN", "BaoStock"),),
    watch_rows=None,
    latest_rows=None,
    account_rows=None,
    pool_rows=None,
):
    accounts = account_rows if account_rows is not None else [account("CN_MAIN", "CN")]
    pools = (
        pool_rows
        if pool_rows is not None
        else [pool(symbol, market, account_id) for symbol, market, account_id, _ in symbols]
    )
    watches = (
        watch_rows
        if watch_rows is not None
        else [watch(symbol, market, source) for symbol, market, _, source in symbols]
    )
    latests = (
        latest_rows
        if latest_rows is not None
        else [latest(symbol, market) for symbol, market, _, _ in symbols]
    )
    return FakeSheetsClient(
        {
            "策略账户": accounts,
            "策略股票池": pools,
            "自选清单": watches,
            "最新行情": latests,
        }
    )


def successful_fetch(calls):
    def fetch(source, row, adjust, start, end, retry_count, retry_wait, *, target_trade_date):
        calls.append(
            {
                "source": source,
                "symbol": row["统一代码"],
                "adjust": adjust,
                "start": start,
                "end": end,
                "retry_count": retry_count,
                "retry_wait": retry_wait,
                "target": target_trade_date,
            }
        )
        return [
            quote(row["统一代码"], row["市场"], target_trade_date - timedelta(days=1), source),
            quote(row["统一代码"], row["市场"], target_trade_date, source),
        ]

    return fetch


class ProductionQfqRefreshTests(unittest.TestCase):
    def run_failure(self, client, fetch=None):
        with redirect_stdout(StringIO()), self.assertRaises(ProductionQfqRefreshError) as raised:
            refresh_production_qfq(
                "all",
                client=client,
                fetch_history=fetch,
                fetched_at=FETCHED_AT,
            )
        return str(raised.exception)

    def test_enabled_formal_symbols_are_refreshed(self):
        client = workbook(
            symbols=(
                ("000725.SZ", "CN", "CN_MAIN", "BaoStock"),
                ("BABA", "US", "US_MAIN", "yfinance"),
            ),
            account_rows=[account("CN_MAIN", "CN"), account("US_MAIN", "US")],
        )
        calls = []
        summary = refresh_production_qfq(
            "all", client=client, fetch_history=successful_fetch(calls), fetched_at=FETCHED_AT
        )
        self.assertEqual(summary["symbols_requested"], 2)
        self.assertEqual(summary["symbols_updated"], 2)
        self.assertEqual(summary["status"], "SUCCESS")
        self.assertEqual({call["symbol"] for call in calls}, {"000725.SZ", "BABA"})
        self.assertTrue(all(call["adjust"] == "qfq" for call in calls))

    def test_dram_disabled_is_skipped(self):
        client = workbook(
            symbols=(("DRAM", "US", "US_MAIN", "yfinance"),),
            account_rows=[account("US_MAIN", "US")],
            pool_rows=[pool("DRAM", "US", "US_MAIN", enabled="FALSE")],
        )
        calls = []
        summary = refresh_production_qfq(
            "us", client=client, fetch_history=successful_fetch(calls), fetched_at=FETCHED_AT
        )
        self.assertEqual(summary, {
            "group": "us",
            "symbols_requested": 0,
            "symbols_updated": 0,
            "rows_written": 0,
            "stale_or_failed_symbols": [],
            "status": "SUCCESS",
        })
        self.assertEqual(calls, [])
        self.assertEqual(client.writes, [])

    def test_non_formal_watchlist_symbol_is_skipped(self):
        client = workbook(
            symbols=(),
            watch_rows=[watch("WATCH_ONLY", "CN", "BaoStock")],
            latest_rows=[latest("WATCH_ONLY", "CN")],
            account_rows=[account("CN_MAIN", "CN")],
            pool_rows=[],
        )
        calls = []
        summary = refresh_production_qfq(
            "asia", client=client, fetch_history=successful_fetch(calls), fetched_at=FETCHED_AT
        )
        self.assertEqual(summary["symbols_requested"], 0)
        self.assertEqual(calls, [])
        self.assertEqual(client.writes, [])

    def test_disabled_account_symbol_is_skipped(self):
        client = workbook(
            symbols=(("000725.SZ", "CN", "CN_MAIN", "BaoStock"),),
            account_rows=[account("CN_MAIN", "CN", enabled="FALSE")],
        )
        calls = []
        summary = refresh_production_qfq(
            "asia", client=client, fetch_history=successful_fetch(calls), fetched_at=FETCHED_AT
        )
        self.assertEqual(summary["symbols_requested"], 0)
        self.assertEqual(calls, [])
        self.assertEqual(client.writes, [])

    def test_missing_source_config_fails_closed(self):
        client = workbook(watch_rows=[])
        error = self.run_failure(client)
        self.assertIn("PRODUCTION_QFQ_SOURCE_CONFIG_REQUIRED:CN|000725.SZ", error)
        self.assertEqual(client.writes, [])

    def test_duplicate_source_config_fails_closed(self):
        base = watch("000725.SZ", "CN", "BaoStock")
        client = workbook(watch_rows=[base, dict(base)])
        error = self.run_failure(client)
        self.assertIn("PRODUCTION_QFQ_SOURCE_CONFIG_DUPLICATE:CN|000725.SZ", error)
        self.assertEqual(client.writes, [])

    def test_missing_latest_row_fails_closed(self):
        client = workbook(latest_rows=[])
        error = self.run_failure(client)
        self.assertIn("PRODUCTION_QFQ_LATEST_REQUIRED:CN|000725.SZ", error)
        self.assertEqual(client.writes, [])

    def test_duplicate_latest_row_fails_closed(self):
        client = workbook(latest_rows=[latest("000725.SZ", "CN"), latest("000725.SZ", "CN")])
        error = self.run_failure(client)
        self.assertIn("PRODUCTION_QFQ_LATEST_DUPLICATE:CN|000725.SZ", error)
        self.assertEqual(client.writes, [])

    def test_provider_stale_data_fails_closed(self):
        client = workbook()

        def stale_fetch(*args, **kwargs):
            row = args[1]
            target = kwargs["target_trade_date"]
            return [quote(row["统一代码"], row["市场"], target - timedelta(days=1), args[0])]

        error = self.run_failure(client, stale_fetch)
        self.assertIn("PRODUCTION_QFQ_PROVIDER_STALE:CN|000725.SZ", error)
        self.assertEqual(client.writes, [])

    def test_success_uses_latest_trade_date_exactly(self):
        target = date(2026, 9, 2)
        client = workbook(latest_rows=[latest("000725.SZ", "CN", target)])
        calls = []
        refresh_production_qfq(
            "asia", client=client, fetch_history=successful_fetch(calls), fetched_at=FETCHED_AT
        )
        self.assertEqual(calls[0]["target"], target)
        self.assertEqual(calls[0]["end"], target)
        written = client.writes[0][1]
        self.assertEqual({row["交易日期"] for row in written}, {target - timedelta(days=1), target})

    def test_only_qfq_history_is_written(self):
        client = workbook()
        refresh_production_qfq(
            "asia", client=client, fetch_history=successful_fetch([]), fetched_at=FETCHED_AT
        )
        self.assertEqual([sheet for sheet, _ in client.writes], ["历史行情_前复权"])
        self.assertNotIn("交易决策", client.reads)
        self.assertNotIn("策略决策状态", client.reads)

    def test_all_formal_symbols_must_succeed_before_any_write(self):
        client = workbook(
            symbols=(
                ("000725.SZ", "CN", "CN_MAIN", "BaoStock"),
                ("002156.SZ", "CN", "CN_MAIN", "BaoStock"),
            )
        )

        def one_fails(source, row, *args, **kwargs):
            if row["统一代码"] == "002156.SZ":
                raise LookupError("provider down")
            return successful_fetch([])(source, row, *args, **kwargs)

        error = self.run_failure(client, one_fails)
        self.assertIn("002156.SZ", error)
        self.assertEqual(client.writes, [])

    def test_group_scope_is_cn_or_us_only(self):
        client = workbook(
            symbols=(
                ("000725.SZ", "CN", "CN_MAIN", "BaoStock"),
                ("BABA", "US", "US_MAIN", "yfinance"),
            ),
            account_rows=[account("CN_MAIN", "CN"), account("US_MAIN", "US")],
        )
        calls = []
        refresh_production_qfq(
            "asia", client=client, fetch_history=successful_fetch(calls), fetched_at=FETCHED_AT
        )
        self.assertEqual([call["symbol"] for call in calls], ["000725.SZ"])

    def test_workflows_call_refresher_after_latest_and_keep_manual_full(self):
        for relative_path, group in (
            (".github/workflows/asia-close.yml", "asia"),
            (".github/workflows/us-close.yml", "us"),
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn(f"python scripts/refresh_production_qfq.py --group {group}", source)
            self.assertIn('if [ "$RUN_MODE" = "latest" ]; then', source)
            self.assertLess(
                source.index('python main.py --group'),
                source.index(f"python scripts/refresh_production_qfq.py --group {group}"),
            )
            self.assertIn("RUN_MODE=latest", source)
            self.assertIn("- full", source)

    def test_scheduled_crons_are_unchanged(self):
        self.assertIn(
            'cron: "30 9 * * 1-5"',
            (ROOT / ".github/workflows/asia-close.yml").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'cron: "30 22 * * 1-5"',
            (ROOT / ".github/workflows/us-close.yml").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from core import Quote
from holdings_data_manager import (
    HoldingsDataManager,
    HoldingsDataManagerError,
    Operation,
    ResultStatus,
    normalize_holding,
    parse_natural_language,
)
from sheets_client import SheetsClient


BEIJING = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 8, 28)
START = date(2025, 8, 28)


def quote(symbol, market, day, source="yfinance", close=100.0):
    return Quote(
        symbol=symbol,
        name=symbol,
        market=market,
        trade_date=day,
        source=source,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        preclose=close - 0.5,
        pct_change=0.5,
        volume=1000.0,
        amount=None,
        turnover_rate=None,
        currency="USD" if market == "US" else "CNY",
    )


class FakeSheetsClient:
    def __init__(self, watchlist=None, raw=None, adjusted=None):
        self.watchlist = list(watchlist or [])
        self.histories = {
            "历史行情_未复权": list(raw or []),
            "历史行情_前复权": list(adjusted or []),
        }
        self.audit_rows = []
        self.watchlist_writes = []

    def records(self, sheet_name):
        if sheet_name == "自选清单":
            return list(self.watchlist)
        if sheet_name in self.histories:
            return list(self.histories[sheet_name])
        return []

    def upsert_watchlist(self, row):
        self.watchlist_writes.append(dict(row))
        identity = (row.get("统一代码"), row.get("市场"))
        for index, existing in enumerate(self.watchlist):
            if (existing.get("统一代码"), existing.get("市场")) == identity:
                merged = dict(existing)
                merged.update(row)
                self.watchlist[index] = merged
                return 1
        self.watchlist.append(dict(row))
        return 1

    def upsert_history(self, sheet_name, rows):
        incoming = list(rows)
        current = {
            (row.get("统一代码"), row.get("交易日期")): row
            for row in self.histories[sheet_name]
        }
        current.update({(row.get("统一代码"), row.get("交易日期")): row for row in incoming})
        self.histories[sheet_name] = list(current.values())
        return len(incoming)

    def append_rows(self, sheet_name, headers, rows):
        self.audit_rows.extend(rows)
        return len(rows)


def us_watch(enabled=False):
    return {
        "启用": enabled,
        "市场": "US",
        "主数据源": "yfinance",
        "校验数据源": "Tencent",
        "历史数据源": "yfinance",
        "时区": "America/New_York",
        "收盘时间": "16:00",
        "统一代码": "MU",
        "名称": "MU",
        "币种": "USD",
        "yfinance代码": "MU",
        "BaoStock代码": "",
    }


def history_row(symbol, market, day, adjustment):
    return {
        "统一代码": symbol,
        "市场": market,
        "交易日期": day.isoformat(),
        "复权方式": adjustment,
    }


def business_history(symbol, market, first, last, adjustment):
    rows = []
    cursor = first
    while cursor <= last:
        if cursor.weekday() < 5:
            rows.append(history_row(symbol, market, cursor, adjustment))
        cursor += timedelta(days=1)
    return rows


class HoldingsDataManagerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 29, 18, 0, tzinfo=BEIJING)

    def manager(self, client, fetch_history=None, fetch_latest=None):
        return HoldingsDataManager(
            client=client,
            fetch_history=fetch_history or self.fetch_history,
            fetch_latest=fetch_latest or self.fetch_latest,
            now_fn=lambda: self.now,
        )

    def fetch_latest(self, source, watch, end, retry_count, retry_wait):
        return [quote(watch["统一代码"], watch["市场"], TARGET, source)]

    def fetch_history(self, source, watch, adjustment, start, end, *args, **kwargs):
        self.history_calls.append((source, adjustment, start, end, kwargs))
        rows = [quote(watch["统一代码"], watch["市场"], start, source)]
        if end != start:
            rows.append(quote(watch["统一代码"], watch["市场"], end, source))
        return rows

    def test_first_add_initializes_one_year_raw_and_qfq_before_enabling(self):
        self.history_calls = []
        client = FakeSheetsClient()
        result = self.manager(client).execute_text("添加 MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(result.symbol, "MU")
        self.assertEqual(result.market, "US")
        self.assertTrue(client.watchlist[0]["启用"])
        self.assertEqual(result.history_rows_written, 4)
        self.assertEqual(
            [(call[1], call[2], call[3]) for call in self.history_calls],
            [("raw", START, TARGET), ("qfq", START, TARGET)],
        )
        self.assertEqual(len(client.audit_rows), 1)
        self.assertIn("action=ADD", client.audit_rows[0]["消息"])
        self.assertEqual(client.audit_rows[0]["运行时间"].tzinfo, BEIJING)

    def test_repeated_add_is_idempotent_without_history_refetch(self):
        self.history_calls = []
        client = FakeSheetsClient()
        manager = self.manager(client)
        first = manager.execute_text("添加 MU")
        self.assertTrue(first.ok)
        self.history_calls.clear()

        result = manager.execute(Operation.ADD, "MU")

        self.assertEqual(result.status, ResultStatus.IDEMPOTENT.value)
        self.assertEqual(self.history_calls, [])
        self.assertTrue(client.watchlist[0]["启用"])

    def test_close_preserves_all_history_and_repeated_close_is_idempotent(self):
        self.history_calls = []
        client = FakeSheetsClient()
        manager = self.manager(client)
        manager.execute_text("添加 MU")
        before = {name: list(rows) for name, rows in client.histories.items()}

        first = manager.execute_text("MU 已清仓")
        self.assertEqual(first.status, ResultStatus.SUCCESS.value)
        self.assertEqual(client.histories, before)
        self.assertFalse(client.watchlist[0]["启用"])
        self.assertEqual(self.history_calls, [("yfinance", "raw", START, TARGET, {"target_trade_date": TARGET}), ("yfinance", "qfq", START, TARGET, {"target_trade_date": TARGET})])

        second = manager.execute(Operation.CLOSE, "MU")
        self.assertEqual(second.status, ResultStatus.IDEMPOTENT.value)
        self.assertEqual(client.histories, before)

    def test_reenter_only_fetches_trailing_gap(self):
        self.history_calls = []
        old = TARGET - timedelta(days=1)
        client = FakeSheetsClient(
            watchlist=[us_watch(False)],
            raw=business_history("MU", "US", START, old, "未复权"),
            adjusted=business_history("MU", "US", START, old, "前复权"),
        )
        result = self.manager(client).execute_text("重新买回 MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertTrue(client.watchlist[0]["启用"])
        self.assertEqual(
            [(call[1], call[2], call[3]) for call in self.history_calls],
            [("raw", TARGET, TARGET), ("qfq", TARGET, TARGET)],
        )

    def test_complete_history_reenter_does_not_refetch_history(self):
        self.history_calls = []
        client = FakeSheetsClient(
            watchlist=[us_watch(False)],
            raw=business_history("MU", "US", START, TARGET, "未复权"),
            adjusted=business_history("MU", "US", START, TARGET, "前复权"),
        )
        result = self.manager(client).execute(Operation.REENTER, "MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(self.history_calls, [])
        self.assertTrue(client.watchlist[0]["启用"])

    def test_ambiguity_fails_closed(self):
        with self.assertRaises(HoldingsDataManagerError):
            normalize_holding("512400", "US")
        with self.assertRaises(HoldingsDataManagerError):
            parse_natural_language("添加 MU 和 INTC")

    def test_provider_failure_does_not_enable_new_symbol(self):
        client = FakeSheetsClient()
        latest = Mock(side_effect=RuntimeError("provider down"))
        result = self.manager(client, fetch_latest=latest).execute(Operation.ADD, "INTC")

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(client.histories["历史行情_未复权"], [])

    def test_qfq_history_failure_does_not_enable_or_write_raw_history(self):
        self.history_calls = []
        client = FakeSheetsClient()

        def qfq_failure(source, watch, adjustment, start, end, *args, **kwargs):
            if adjustment == "qfq":
                raise RuntimeError("qfq provider down")
            return self.fetch_history(source, watch, adjustment, start, end, *args, **kwargs)

        result = self.manager(client, fetch_history=qfq_failure).execute(Operation.ADD, "INTC")

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(client.histories["历史行情_未复权"], [])
        self.assertEqual(client.histories["历史行情_前复权"], [])
        self.assertIn("qfq历史抓取失败", client.audit_rows[0]["消息"])

    def test_duplicate_history_date_fails_closed_and_does_not_enable(self):
        client = FakeSheetsClient()
        def duplicate_fetch(source, watch, adjustment, start, end, *args, **kwargs):
            return [quote(watch["统一代码"], watch["市场"], start, source)] * 2

        result = self.manager(client, fetch_history=duplicate_fetch).execute(Operation.ADD, "INTC")

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertIn("重复日期", client.audit_rows[0]["消息"])

    def test_existing_duplicate_history_date_fails_closed(self):
        client = FakeSheetsClient(
            watchlist=[us_watch(False)],
            raw=[history_row("MU", "US", START, "未复权"), history_row("MU", "US", START, "未复权")],
            adjusted=business_history("MU", "US", START, TARGET, "前复权"),
        )

        result = self.manager(client).execute(Operation.REENTER, "MU")

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertFalse(client.watchlist[0]["启用"])
        self.assertIn("历史行情存在重复日期", client.audit_rows[0]["消息"])

    def test_natural_language_examples_are_deterministic(self):
        self.assertEqual(parse_natural_language("我买了 512400"), parse_natural_language("添加 512400"))
        self.assertEqual(parse_natural_language("重新买回 INTC").operation, Operation.REENTER)
        self.assertEqual(parse_natural_language("NOK 已清仓").operation, Operation.CLOSE)
        self.assertEqual(normalize_holding("512400").symbol, "512400.SH")

    def test_sync_fills_history_without_changing_current_enabled_state(self):
        self.history_calls = []
        old = TARGET - timedelta(days=1)
        client = FakeSheetsClient(
            watchlist=[us_watch(True)],
            raw=business_history("MU", "US", START, old, "未复权"),
            adjusted=business_history("MU", "US", START, old, "前复权"),
        )
        result = self.manager(client).execute(Operation.SYNC, "MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertTrue(client.watchlist[0]["启用"])
        self.assertEqual(result.history_rows_written, 2)


class SheetsWatchlistTests(unittest.TestCase):
    def test_watchlist_upsert_preserves_uninterpreted_columns(self):
        class Worksheet:
            def __init__(self):
                self.values = [["启用", "市场", "统一代码", "未核实列"], ["TRUE", "US", "MU", "keep"]]
                self.updated = None

            def get_all_values(self):
                return self.values

            def update(self, values, range_name, value_input_option=None):
                self.updated = (values, range_name, value_input_option)
                self.values[1] = values[0]

            def append_row(self, values, value_input_option=None):
                self.values.append(values)

        worksheet = Worksheet()
        client = object.__new__(SheetsClient)
        client.book = type("Book", (), {"worksheet": lambda self, name: worksheet})()

        client.upsert_watchlist({"启用": False, "市场": "US", "统一代码": "MU"})

        self.assertEqual(worksheet.values[1][3], "keep")
        self.assertEqual(worksheet.updated[1], "A2")


if __name__ == "__main__":
    unittest.main()

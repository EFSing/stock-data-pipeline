import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from core import Quote
from holdings_data_manager import (
    HoldingsDataManager,
    HoldingsDataManagerError,
    MIN_ONE_YEAR_BARS,
    Operation,
    ResultStatus,
    history_coverage_report,
    normalize_holding,
    parse_natural_language,
)
from sheets_client import SheetsClient


BEIJING = ZoneInfo("Asia/Shanghai")
TARGET = date(2026, 8, 28)
START = date(2025, 8, 28)

# Test-only observed-session fixtures.  Production code must not use a hand-
# maintained holiday table; these dates model the closed sessions that a real
# provider would omit so the manager's session-date logic is exercised.
US_HOLIDAYS = {
    date(2025, 9, 1), date(2025, 11, 27), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3),
}
CN_HOLIDAYS = {
    date(2025, 10, 1), date(2025, 10, 2), date(2025, 10, 3),
    date(2025, 10, 6), date(2025, 10, 7),
    date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17),
    date(2026, 2, 18), date(2026, 2, 19), date(2026, 2, 20),
    date(2026, 4, 6), date(2026, 5, 1), date(2026, 6, 19),
}


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
            (row.get("市场"), row.get("统一代码"), row.get("交易日期")): row
            for row in self.histories[sheet_name]
        }
        current.update({
            (row.get("市场"), row.get("统一代码"), row.get("交易日期")): row
            for row in incoming
        })
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


def cn_watch(enabled=False):
    return {
        "启用": enabled,
        "市场": "CN",
        "主数据源": "yfinance",
        "校验数据源": "BaoStock",
        "历史数据源": "yfinance",
        "时区": "Asia/Shanghai",
        "收盘时间": "15:00",
        "统一代码": "512400.SH",
        "名称": "512400.SH",
        "币种": "CNY",
        "yfinance代码": "512400.SS",
        "BaoStock代码": "sh.512400",
    }


def history_row(symbol, market, day, adjustment):
    return {
        "统一代码": symbol,
        "市场": market,
        "交易日期": day.isoformat(),
        "复权方式": adjustment,
    }


def fixture_session_dates(market, first, last):
    holidays = US_HOLIDAYS if market == "US" else CN_HOLIDAYS
    rows = []
    cursor = first
    while cursor <= last:
        if cursor.weekday() < 5 and cursor not in holidays:
            rows.append(cursor)
        cursor += timedelta(days=1)
    return rows


def session_history(symbol, market, first, last, adjustment):
    rows = []
    for day in fixture_session_dates(market, first, last):
        rows.append(history_row(symbol, market, day, adjustment))
    return rows


def session_quotes(symbol, market, first, last, source="yfinance"):
    return [
        quote(symbol, market, day, source, close=100.0 + index / 100.0)
        for index, day in enumerate(fixture_session_dates(market, first, last))
    ]


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
        return session_quotes(
            watch["统一代码"], watch["市场"], start, end, source
        )

    def test_first_add_initializes_one_year_raw_and_qfq_before_enabling(self):
        self.history_calls = []
        client = FakeSheetsClient()
        result = self.manager(client).execute_text("添加 MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(result.symbol, "MU")
        self.assertEqual(result.market, "US")
        self.assertTrue(client.watchlist[0]["启用"])
        expected_bars = len(fixture_session_dates("US", START, TARGET))
        self.assertEqual(result.history_rows_written, expected_bars * 2)
        self.assertGreaterEqual(expected_bars, MIN_ONE_YEAR_BARS)
        self.assertEqual(
            len({row["交易日期"] for row in client.histories["历史行情_未复权"]}),
            expected_bars,
        )
        self.assertEqual(
            {
                row["交易日期"] for row in client.histories["历史行情_未复权"]
            },
            {
                row["交易日期"] for row in client.histories["历史行情_前复权"]
            },
        )
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
            raw=session_history("MU", "US", START, old, "未复权"),
            adjusted=session_history("MU", "US", START, old, "前复权"),
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
            raw=session_history("MU", "US", START, TARGET, "未复权"),
            adjusted=session_history("MU", "US", START, TARGET, "前复权"),
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
            adjusted=session_history("MU", "US", START, TARGET, "前复权"),
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
            raw=session_history("MU", "US", START, old, "未复权"),
            adjusted=session_history("MU", "US", START, old, "前复权"),
        )
        result = self.manager(client).execute(Operation.SYNC, "MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertTrue(client.watchlist[0]["启用"])
        self.assertEqual(result.history_rows_written, 2)

    def test_two_endpoint_provider_payload_fails_coverage(self):
        self.history_calls = []

        def endpoints_only(source, watch, adjustment, start, end, *args, **kwargs):
            self.history_calls.append((source, adjustment, start, end, kwargs))
            return [
                quote(watch["统一代码"], watch["市场"], start, source),
                quote(watch["统一代码"], watch["市场"], end, source),
            ]

        client = FakeSheetsClient()
        result = self.manager(client, fetch_history=endpoints_only).execute(
            Operation.ADD, "INTC"
        )

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(client.histories["历史行情_未复权"], [])
        self.assertIn("稀疏", result.message)

    def test_middle_large_gap_fails_closed(self):
        self.history_calls = []
        missing_start = date(2026, 1, 5)
        missing_end = date(2026, 2, 20)

        def middle_gap(source, watch, adjustment, start, end, *args, **kwargs):
            self.history_calls.append((source, adjustment, start, end, kwargs))
            return [
                item for item in session_quotes(
                    watch["统一代码"], watch["市场"], start, end, source
                )
                if not missing_start <= item.trade_date <= missing_end
            ]

        client = FakeSheetsClient()
        result = self.manager(client, fetch_history=middle_gap).execute(
            Operation.ADD, "INTC"
        )

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertIn("中段", result.message)

    def test_provider_truncating_recent_days_fails_closed(self):
        self.history_calls = []
        truncation_end = TARGET - timedelta(days=10)

        def truncated(source, watch, adjustment, start, end, *args, **kwargs):
            self.history_calls.append((source, adjustment, start, end, kwargs))
            return session_quotes(
                watch["统一代码"], watch["市场"], start,
                min(end, truncation_end), source
            )

        client = FakeSheetsClient()
        result = self.manager(client, fetch_history=truncated).execute(
            Operation.ADD, "INTC"
        )

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertIn("目标末日", result.message)

    def test_raw_qfq_session_date_mismatch_fails_closed(self):
        mismatch_date = date(2026, 1, 5)

        def mismatched(source, watch, adjustment, start, end, *args, **kwargs):
            rows = session_quotes(
                watch["统一代码"], watch["市场"], start, end, source
            )
            if adjustment == "qfq":
                rows = [item for item in rows if item.trade_date != mismatch_date]
            return rows

        client = FakeSheetsClient()
        result = self.manager(client, fetch_history=mismatched).execute(
            Operation.ADD, "INTC"
        )

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertIn("session-date 集合不一致", result.message)

    def test_complete_us_holiday_history_sync_does_not_refetch(self):
        self.history_calls = []
        raw_dates = fixture_session_dates("US", START, TARGET)
        client = FakeSheetsClient(
            watchlist=[us_watch(True)],
            raw=session_history("MU", "US", START, TARGET, "未复权"),
            adjusted=session_history("MU", "US", START, TARGET, "前复权"),
        )

        result = self.manager(client).execute(Operation.SYNC, "MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(result.history_rows_written, 0)
        self.assertEqual(self.history_calls, [])
        self.assertNotIn(date(2025, 12, 25), raw_dates)
        self.assertNotIn(date(2026, 1, 1), raw_dates)

    def test_complete_cn_holiday_history_reenter_does_not_refetch(self):
        self.history_calls = []
        raw_dates = fixture_session_dates("CN", START, TARGET)
        client = FakeSheetsClient(
            watchlist=[cn_watch(False)],
            raw=session_history("512400.SH", "CN", START, TARGET, "未复权"),
            adjusted=session_history("512400.SH", "CN", START, TARGET, "前复权"),
        )

        result = self.manager(client).execute(Operation.REENTER, "512400.SH")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(result.history_rows_written, 0)
        self.assertEqual(self.history_calls, [])
        self.assertNotIn(date(2025, 10, 2), raw_dates)
        self.assertNotIn(date(2026, 2, 17), raw_dates)

    def test_add_after_close_natural_language_auto_reenters_and_fills_gap(self):
        self.history_calls = []
        client = FakeSheetsClient()
        manager = self.manager(client)
        self.assertEqual(manager.execute(Operation.ADD, "MU").status, ResultStatus.SUCCESS.value)
        manager.execute(Operation.CLOSE, "MU")

        retained = fixture_session_dates("US", START, TARGET)[:-3]
        client.histories["历史行情_未复权"] = [
            history_row("MU", "US", day, "未复权") for day in retained
        ]
        client.histories["历史行情_前复权"] = [
            history_row("MU", "US", day, "前复权") for day in retained
        ]
        self.history_calls.clear()

        result = manager.execute_text("我买了 MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertTrue(client.watchlist[0]["启用"])
        self.assertIn("按REENTER语义", result.message)
        self.assertEqual(
            [(call[1], call[2], call[3]) for call in self.history_calls],
            [("raw", date(2026, 8, 26), TARGET), ("qfq", date(2026, 8, 26), TARGET)],
        )
        self.assertEqual(
            len(client.histories["历史行情_未复权"]),
            len(set(fixture_session_dates("US", START, TARGET))),
        )

    def test_coverage_report_rejects_duplicate_and_accepts_observed_holidays(self):
        dates = fixture_session_dates("US", START, TARGET)
        report = history_coverage_report(dates, dates, START, TARGET)
        self.assertTrue(report.ok)
        self.assertEqual(report.raw_only_dates, ())
        duplicate_report = history_coverage_report(
            dates + [dates[10]], dates, START, TARGET
        )
        self.assertFalse(duplicate_report.ok)
        self.assertIn("日期重复", duplicate_report.reason)


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

    def test_history_upsert_identity_includes_market(self):
        client = object.__new__(SheetsClient)
        client.records = lambda sheet_name: [{
            "市场": "CN",
            "统一代码": "000001.SZ",
            "交易日期": "2026-08-28",
        }]
        client._replace = Mock()

        written = client.upsert_history("历史行情_未复权", [{
            "市场": "US",
            "统一代码": "000001.SZ",
            "交易日期": "2026-08-28",
        }])

        self.assertEqual(written, 1)
        rows = client._replace.call_args.args[2]
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()

import unittest
from dataclasses import replace
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
        self.latest_rows = []
        self.validation_rows = []
        self.audit_rows = []
        self.watchlist_writes = []
        self.events = []

    def records(self, sheet_name):
        if sheet_name == "自选清单":
            return list(self.watchlist)
        if sheet_name in self.histories:
            return list(self.histories[sheet_name])
        if sheet_name == "最新行情":
            return list(self.latest_rows)
        if sheet_name == "校验记录":
            return list(self.validation_rows)
        return []

    def upsert_watchlist(self, row):
        self.events.append("upsert_watchlist")
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
        self.events.append(f"upsert_history:{sheet_name}")
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

    def upsert_latest(self, rows):
        self.events.append("upsert_latest")
        incoming = list(rows)
        current = {row.get("统一代码"): row for row in self.latest_rows}
        current.update({row.get("统一代码"): row for row in incoming})
        self.latest_rows = list(current.values())
        return len(incoming)

    def append_rows(self, sheet_name, headers, rows):
        self.events.append(f"append_rows:{sheet_name}")
        if sheet_name == "校验记录":
            self.validation_rows.extend(rows)
        elif sheet_name == "运行日志":
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
        self.assertEqual(client.latest_rows[0]["交易日期"], TARGET)
        self.assertEqual(client.validation_rows[0]["交易日期"], TARGET)
        self.assertEqual(
            client.events[:5],
            [
                "upsert_history:历史行情_未复权",
                "upsert_history:历史行情_前复权",
                "upsert_latest",
                "append_rows:校验记录",
                "upsert_watchlist",
            ],
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
        client.events.clear()

        result = manager.execute(Operation.ADD, "MU")

        self.assertEqual(result.status, ResultStatus.IDEMPOTENT.value)
        self.assertEqual(self.history_calls, [])
        self.assertNotIn("upsert_latest", client.events)
        self.assertNotIn("append_rows:校验记录", client.events)
        self.assertNotIn("upsert_watchlist", client.events)
        self.assertTrue(client.watchlist[0]["启用"])

    def test_repeated_add_repairs_missing_latest_without_refetching_complete_history(self):
        self.history_calls = []
        client = FakeSheetsClient()
        manager = self.manager(client)
        self.assertEqual(manager.execute(Operation.ADD, "MU").status, ResultStatus.SUCCESS.value)
        client.latest_rows.clear()
        client.validation_rows.clear()
        self.history_calls.clear()

        result = manager.execute(Operation.ADD, "MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(self.history_calls, [])
        self.assertEqual(client.latest_rows[0]["交易日期"], TARGET)
        self.assertEqual(client.validation_rows[0]["交易日期"], TARGET)
        self.assertTrue(client.watchlist[0]["启用"])

    def test_add_retry_after_watchlist_enable_failure_repairs_only_identity(self):
        self.history_calls = []
        client = FakeSheetsClient()
        manager = self.manager(client)
        original_upsert_watchlist = client.upsert_watchlist
        watchlist_attempts = [0]

        def fail_first_watchlist_write(row):
            watchlist_attempts[0] += 1
            if watchlist_attempts[0] == 1:
                raise RuntimeError("watchlist down")
            return original_upsert_watchlist(row)

        client.upsert_watchlist = fail_first_watchlist_write
        first = manager.execute(Operation.ADD, "MU")
        self.assertEqual(first.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(len(client.latest_rows), 1)
        self.assertEqual(len(client.validation_rows), 1)
        self.assertGreater(len(client.histories["历史行情_未复权"]), 0)
        self.assertGreater(len(client.histories["历史行情_前复权"]), 0)

        self.history_calls.clear()
        second = manager.execute(Operation.ADD, "MU")

        self.assertEqual(second.status, ResultStatus.SUCCESS.value)
        self.assertEqual(self.history_calls, [])
        self.assertEqual(len(client.latest_rows), 1)
        self.assertEqual(len(client.validation_rows), 1)
        self.assertTrue(client.watchlist[0]["启用"])
        self.assertEqual(
            [event for event in client.events if event != "append_rows:运行日志"].count(
                "upsert_latest"
            ),
            1,
        )
        self.assertEqual(
            [event for event in client.events if event == "append_rows:校验记录"],
            ["append_rows:校验记录"],
        )

    def test_disabled_reenter_with_complete_state_only_reenables_identity(self):
        self.history_calls = []
        client = FakeSheetsClient()
        manager = self.manager(client)
        self.assertEqual(manager.execute(Operation.ADD, "MU").status, ResultStatus.SUCCESS.value)
        self.assertEqual(manager.execute(Operation.CLOSE, "MU").status, ResultStatus.SUCCESS.value)
        client.events.clear()
        client.audit_rows.clear()
        validation_count = len(client.validation_rows)

        result = manager.execute(Operation.REENTER, "MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(self.history_calls, [("yfinance", "raw", START, TARGET, {"target_trade_date": TARGET}), ("yfinance", "qfq", START, TARGET, {"target_trade_date": TARGET})])
        self.assertEqual(len(client.validation_rows), validation_count)
        self.assertEqual(client.events[0], "upsert_watchlist")
        self.assertNotIn("upsert_history:历史行情_未复权", client.events)
        self.assertNotIn("upsert_history:历史行情_前复权", client.events)
        self.assertNotIn("upsert_latest", client.events)
        self.assertNotIn("append_rows:校验记录", client.events)
        self.assertTrue(client.watchlist[0]["启用"])

    def test_validation_failure_retry_repairs_only_validation_and_enable(self):
        self.history_calls = []
        client = FakeSheetsClient()
        manager = self.manager(client)
        original_append_rows = client.append_rows
        validation_attempts = [0]

        def fail_first_validation_append(sheet_name, headers, rows):
            if sheet_name == "校验记录":
                validation_attempts[0] += 1
                if validation_attempts[0] == 1:
                    raise RuntimeError("validation sheet down")
            return original_append_rows(sheet_name, headers, rows)

        client.append_rows = fail_first_validation_append
        first = manager.execute(Operation.ADD, "MU")
        self.assertEqual(first.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(client.validation_rows, [])
        self.assertEqual(len(client.latest_rows), 1)
        self.assertGreater(len(client.histories["历史行情_未复权"]), 0)
        self.assertGreater(len(client.histories["历史行情_前复权"]), 0)

        self.history_calls.clear()
        second = manager.execute(Operation.ADD, "MU")

        self.assertEqual(second.status, ResultStatus.SUCCESS.value)
        self.assertEqual(self.history_calls, [])
        self.assertEqual(len(client.latest_rows), 1)
        self.assertEqual(len(client.validation_rows), 1)
        self.assertTrue(client.watchlist[0]["启用"])
        self.assertEqual(client.events.count("upsert_latest"), 1)
        self.assertEqual(client.events.count("append_rows:校验记录"), 1)

    def test_first_add_is_enable_last_after_latest_and_validation(self):
        self.history_calls = []
        client = FakeSheetsClient()
        result = self.manager(client).execute(Operation.ADD, "INTC")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertFalse(any(event == "upsert_watchlist" for event in client.events[:4]))
        self.assertEqual(client.events[2:5], [
            "upsert_latest",
            "append_rows:校验记录",
            "upsert_watchlist",
        ])

    def test_reenter_publishes_latest_and_validation_before_reenabling(self):
        self.history_calls = []
        client = FakeSheetsClient(
            watchlist=[us_watch(False)],
            raw=session_history("MU", "US", START, TARGET, "未复权"),
            adjusted=session_history("MU", "US", START, TARGET, "前复权"),
        )

        result = self.manager(client).execute(Operation.REENTER, "MU")

        self.assertEqual(result.status, ResultStatus.SUCCESS.value)
        self.assertEqual(client.latest_rows[0]["交易日期"], TARGET)
        self.assertEqual(client.validation_rows[0]["交易日期"], TARGET)
        self.assertEqual(client.events[-4:-1], [
            "upsert_latest",
            "append_rows:校验记录",
            "upsert_watchlist",
        ])

    def test_latest_failure_does_not_enable_after_history_is_valid(self):
        self.history_calls = []
        client = FakeSheetsClient()

        def latest_failure(rows):
            raise RuntimeError("latest sheet down")

        client.upsert_latest = latest_failure
        result = self.manager(client).execute(Operation.ADD, "INTC")

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(client.validation_rows, [])
        self.assertGreater(len(client.histories["历史行情_未复权"]), 0)
        self.assertIn("latest sheet down", result.message)

    def test_latest_sanity_failure_does_not_enable_or_publish(self):
        client = FakeSheetsClient()

        def invalid_latest(source, watch, end, retry_count, retry_wait):
            return [replace(
                quote(watch["统一代码"], watch["市场"], TARGET, source),
                open=999.0,
            )]

        result = self.manager(client, fetch_latest=invalid_latest).execute(
            Operation.ADD, "INTC"
        )

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(client.latest_rows, [])
        self.assertEqual(client.validation_rows, [])
        self.assertEqual(client.histories["历史行情_未复权"], [])

    def test_future_latest_is_fail_closed_when_no_completed_snapshot_exists(self):
        client = FakeSheetsClient()

        def future_latest(source, watch, end, retry_count, retry_wait):
            return [quote(watch["统一代码"], watch["市场"], TARGET + timedelta(days=2), source)]

        result = self.manager(client, fetch_latest=future_latest).execute(
            Operation.ADD, "INTC"
        )

        self.assertEqual(result.status, ResultStatus.FAILED.value)
        self.assertEqual(client.watchlist, [])
        self.assertEqual(client.latest_rows, [])
        self.assertEqual(client.histories["历史行情_未复权"], [])

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
        self.assertEqual(client.latest_rows, [])
        self.assertEqual(client.validation_rows, [])
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

    def test_hk_yfinance_ticker_mapping_removes_only_one_padding_zero(self):
        cases = (
            ("00700.HK", "0700.HK"),
            ("09618.HK", "9618.HK"),
            ("03690.HK", "3690.HK"),
            ("09888.HK", "9888.HK"),
            ("00005.HK", "0005.HK"),
            ("12345.HK", "12345.HK"),
        )
        for symbol, expected_yfinance in cases:
            with self.subTest(symbol=symbol):
                normalized = normalize_holding(symbol)
                self.assertEqual(normalized.yfinance_symbol, expected_yfinance)

        self.assertEqual(normalize_holding("512400").yfinance_symbol, "512400.SS")
        self.assertEqual(normalize_holding("MU").yfinance_symbol, "MU")

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

    def test_reenter_rerun_is_idempotent_after_gap_fill(self):
        self.history_calls = []
        old = TARGET - timedelta(days=1)
        client = FakeSheetsClient(
            watchlist=[us_watch(False)],
            raw=session_history("MU", "US", START, old, "未复权"),
            adjusted=session_history("MU", "US", START, old, "前复权"),
        )
        manager = self.manager(client)

        first = manager.execute(Operation.REENTER, "MU")
        history_after_first = {
            name: list(rows) for name, rows in client.histories.items()
        }
        self.history_calls.clear()
        second = manager.execute(Operation.REENTER, "MU")

        self.assertEqual(first.history_rows_written, 2)
        self.assertEqual(second.status, ResultStatus.IDEMPOTENT.value)
        self.assertEqual(second.history_rows_written, 0)
        self.assertEqual(client.histories, history_after_first)
        self.assertEqual(self.history_calls, [])

    def test_sync_rerun_does_not_duplicate_session_rows(self):
        self.history_calls = []
        old = TARGET - timedelta(days=1)
        client = FakeSheetsClient(
            watchlist=[us_watch(True)],
            raw=session_history("MU", "US", START, old, "未复权"),
            adjusted=session_history("MU", "US", START, old, "前复权"),
        )
        manager = self.manager(client)

        first = manager.execute(Operation.SYNC, "MU")
        history_after_first = {
            name: list(rows) for name, rows in client.histories.items()
        }
        self.history_calls.clear()
        second = manager.execute(Operation.SYNC, "MU")

        self.assertEqual(first.history_rows_written, 2)
        self.assertEqual(second.status, ResultStatus.SUCCESS.value)
        self.assertEqual(second.history_rows_written, 0)
        self.assertEqual(client.histories, history_after_first)
        self.assertEqual(self.history_calls, [])

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

    def test_new_watchlist_row_expands_real_table_through_p_column_and_copies_format(self):
        headers = [
            "启用", "市场", "主数据源", "校验数据源", "时区", "收盘时间",
            "统一代码", "名称", "币种", "BaoStock代码", "yfinance代码",
            "AKShare代码", "重试次数", "重试等待秒", "未管理列", "历史数据源",
        ]

        class Worksheet:
            title = "自选清单"

            def __init__(self):
                self.values = [headers, ["TRUE", "US", "yfinance", "Tencent", "America/New_York", "16:00", "MU", "MU", "USD", "", "MU", "", "3", "5", "keep", "yfinance"]]
                self.updates = []

            def get_all_values(self):
                return self.values

            def update(self, values, range_name, value_input_option=None):
                self.updates.append((values, range_name, value_input_option))
                row_number = int(range_name[1:])
                while len(self.values) < row_number:
                    self.values.append([])
                self.values[row_number - 1] = values[0]

            def append_row(self, values, value_input_option=None):
                raise AssertionError("new identities must be written inside WatchlistTable")

        class Book:
            def __init__(self, worksheet):
                self._worksheet = worksheet
                self.batch_requests = []

            def worksheet(self, name):
                self.assert_name = name
                return self._worksheet

            def fetch_sheet_metadata(self):
                return {
                    "sheets": [{
                        "properties": {"sheetId": 731, "title": "自选清单"},
                        "tables": [{
                            "tableId": "table-from-metadata",
                            "name": "WatchlistTable",
                            "range": {
                                "sheetId": 731,
                                "startRowIndex": 0,
                                "endRowIndex": 2,
                                "startColumnIndex": 0,
                                "endColumnIndex": 15,
                            },
                        }],
                    }]
                }

            def batch_update(self, body):
                self.batch_requests.append(body)

        worksheet = Worksheet()
        book = Book(worksheet)
        client = object.__new__(SheetsClient)
        client.book = book

        client.upsert_watchlist({
            "启用": True,
            "市场": "CN",
            "统一代码": "000001.SZ",
            "历史数据源": "yfinance",
        })

        update_request = book.batch_requests[0]["requests"][0]["updateTable"]
        self.assertEqual(update_request["table"]["tableId"], "table-from-metadata")
        self.assertEqual(update_request["table"]["range"]["endColumnIndex"], len(headers))
        self.assertEqual(update_request["table"]["range"]["endRowIndex"], 3)
        copy_request = book.batch_requests[1]["requests"][0]["copyPaste"]
        self.assertEqual(copy_request["source"]["sheetId"], 731)
        self.assertEqual(copy_request["destination"]["sheetId"], 731)
        self.assertEqual(copy_request["pasteType"], "PASTE_FORMAT")
        self.assertFalse(any("addBanding" in request for body in book.batch_requests for request in body["requests"]))
        self.assertEqual(worksheet.updates[0][1], "A3")
        self.assertEqual(worksheet.updates[0][2], "RAW")
        self.assertEqual(worksheet.values[2][6], "000001.SZ")
        self.assertEqual(worksheet.values[2][15], "yfinance")
        self.assertEqual(worksheet.values[2][14], "")

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

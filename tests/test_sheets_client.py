import unittest
from unittest.mock import patch

from sheets_client import SheetsClient


class _QuotaError(Exception):
    pass


class _Worksheet:
    def __init__(self, records=None, failures=0):
        self.records = list(records or [])
        self.failures = failures
        self.read_calls = 0

    def get_all_records(self, **kwargs):
        self.read_calls += 1
        if self.failures:
            self.failures -= 1
            raise _QuotaError("[429] Quota exceeded")
        return list(self.records)


class _Book:
    def __init__(self, worksheet):
        self.worksheet_value = worksheet
        self.worksheet_calls = 0

    def worksheet(self, name):
        self.worksheet_calls += 1
        return self.worksheet_value


class SheetsClientReadTests(unittest.TestCase):
    def make_client(self, worksheet):
        client = object.__new__(SheetsClient)
        client.book = _Book(worksheet)
        client._worksheet_cache = {}
        return client

    def test_worksheet_lookup_is_cached_and_record_read_retries_quota(self):
        worksheet = _Worksheet([{"统一代码": "BABA"}], failures=2)
        client = self.make_client(worksheet)

        with patch("sheets_client.time.sleep") as sleep:
            self.assertEqual(client.records("最新行情"), [{"统一代码": "BABA"}])
            self.assertEqual(client.records("最新行情"), [{"统一代码": "BABA"}])

        self.assertEqual(client.book.worksheet_calls, 1)
        self.assertEqual(worksheet.read_calls, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0])

    def test_opportunity_summary_upsert_preserves_other_market_and_same_run_is_noop(self):
        from unittest.mock import Mock
        headers = ["market", "session_date", "payload_json"]
        old = {"market": "CN", "session_date": "2026-10-08", "payload_json": "old"}
        other = {"market": "US", "session_date": "2026-10-08", "payload_json": "other"}
        worksheet = _Worksheet([other, old])
        worksheet.update = Mock()
        client = self.make_client(worksheet)
        self.assertEqual(client.upsert_opportunity_summary(old, headers), 0)
        worksheet.update.assert_not_called()
        new = old | {"payload_json": "new"}
        self.assertEqual(client.upsert_opportunity_summary(new, headers), 1)
        worksheet.update.assert_called_once_with([["CN", "2026-10-08", "new"]], "A3", value_input_option="RAW")
        self.assertEqual(worksheet.records[0], other)
        client.append_rows = Mock(return_value=1)
        self.assertEqual(client.upsert_opportunity_summary(new | {"session_date": "2026-10-09"}, headers), 1)
        client.append_rows.assert_called_once()

    def test_lost_append_response_invalidates_snapshot_for_idempotent_retry(self):
        from unittest.mock import Mock
        worksheet = _Worksheet([])
        client = self.make_client(worksheet)
        self.assertEqual(client.records("机会观察账本"), [])
        def accepted_then_response_lost(*args, **kwargs):
            worksheet.records.append({"opportunity_id": "US|event"})
            raise RuntimeError("response lost")
        worksheet.append_rows = Mock(side_effect=accepted_then_response_lost)
        with self.assertRaisesRegex(RuntimeError, "response lost"):
            client.append_rows("机会观察账本", ["opportunity_id"], [{"opportunity_id": "US|event"}])
        self.assertEqual(client.records("机会观察账本"), [{"opportunity_id": "US|event"}])


if __name__ == "__main__":
    unittest.main()

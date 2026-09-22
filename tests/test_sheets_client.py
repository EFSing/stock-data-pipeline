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


if __name__ == "__main__":
    unittest.main()

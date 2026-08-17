import unittest
from datetime import date

from core import Quote, validate_quotes
from main import as_ratio


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


if __name__ == "__main__":
    unittest.main()

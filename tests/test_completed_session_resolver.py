from __future__ import annotations

from datetime import datetime, timezone
import unittest

from scripts.run_cloud_daily_report import (
    _reliability_classification,
    _automatic_scheduler_delay,
    resolve_cloud_trade_date,
)
from trading.production_prerequisites import ExactExchangeCalendarProvider


class CompletedSessionResolverTests(unittest.TestCase):
    def setUp(self):
        self.provider = ExactExchangeCalendarProvider()

    def test_cn_close_delay_cross_midnight_and_next_open_boundary(self):
        cases = (
            (datetime(2026, 9, 29, 9, 30, tzinfo=timezone.utc), "2026-09-29", True),
            (datetime(2026, 9, 29, 14, 0, tzinfo=timezone.utc), "2026-09-29", True),
            (datetime(2026, 9, 29, 17, 46, tzinfo=timezone.utc), "2026-09-29", True),
            (datetime(2026, 9, 30, 1, 31, tzinfo=timezone.utc), "2026-09-29", False),
        )
        for now, expected, window_open in cases:
            with self.subTest(now=now):
                identity = self.provider.latest_completed_session("CN", now=now)
                self.assertEqual(identity.trade_date.isoformat(), expected)
                window = self.provider.completed_session_window("CN", identity.trade_date, now=now)
                self.assertEqual(window.collection_window_open, window_open)

    def test_cn_holiday_uses_last_real_session_not_calendar_minus_one(self):
        now = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        identity = self.provider.latest_completed_session("CN", now=now)
        self.assertEqual(identity.trade_date.isoformat(), "2026-09-30")
        self.assertEqual(resolve_cloud_trade_date("CN", now=now, calendar_provider=self.provider), identity.trade_date)

    def test_us_dst_and_standard_time_closes(self):
        edt = self.provider.latest_completed_session(
            "US", now=datetime(2026, 9, 3, 20, 1, tzinfo=timezone.utc)
        )
        est = self.provider.latest_completed_session(
            "US", now=datetime(2026, 1, 2, 22, 1, tzinfo=timezone.utc)
        )
        self.assertEqual(edt.trade_date.isoformat(), "2026-09-03")
        self.assertEqual(est.trade_date.isoformat(), "2026-01-02")

    def test_us_weekend_and_observed_holiday_skip_to_last_completed_session(self):
        identity = self.provider.latest_completed_session(
            "US", now=datetime(2026, 7, 4, 0, 46, tzinfo=timezone.utc)
        )
        self.assertEqual(identity.trade_date.isoformat(), "2026-07-02")

    def test_delayed_automatic_report_is_classified_without_changing_t(self):
        now = datetime(2026, 9, 30, 1, 46, tzinfo=timezone.utc)
        target = resolve_cloud_trade_date("CN", now=now, calendar_provider=self.provider)
        self.assertEqual(target.isoformat(), "2026-09-29")
        self.assertTrue(_automatic_scheduler_delay(self.provider, "CN", target, now))
        self.assertEqual(
            _reliability_classification(
                status="SUCCESS", result={"reports": []}, automatic_scheduler_delay=True
            ),
            "SCHEDULER_DELAY",
        )

    def test_report_reliability_classes_are_distinct(self):
        self.assertEqual(
            _reliability_classification(status="INCOMPLETE_SESSION", result={}),
            "INCOMPLETE_SESSION",
        )
        self.assertEqual(
            _reliability_classification(status="PARTIAL_DATA_QUALITY", result={}),
            "DATA_QUALITY_PARTIAL",
        )
        self.assertEqual(
            _reliability_classification(status="FAILED", result={}),
            "PROVIDER_FAILURE",
        )
        self.assertEqual(
            _reliability_classification(status="SUCCESS", result={"reports": []}),
            "NO_SIGNAL",
        )
        self.assertEqual(
            _reliability_classification(
                status="FAILED", result={}, resolution_error=True
            ),
            "SESSION_RESOLUTION_ERROR",
        )


if __name__ == "__main__":
    unittest.main()

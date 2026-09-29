from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.run_cloud_daily_report import _notify
from trading.operational_markers import claim_report_notification


class _MarkerStore:
    def __init__(self):
        self.calls = []

    def put_bytes(self, name, payload, **kwargs):
        self.calls.append((name, payload, kwargs))
        return {"status": "CREATED" if len(self.calls) == 1 else "IDEMPOTENT_REPLAY"}


def _payload():
    return {
        "market": "CN",
        "as_of_date": "2026-09-29",
        "cloud_daily_report": {
            "market": "CN",
            "as_of_date": "2026-09-29",
            "protocol_version": "CLOUD-DAILY-REPORT-MOBILE-V1-2026-09-14",
            "status": "SUCCESS",
        },
    }


class OperationalMarkerTests(unittest.TestCase):
    def test_report_identity_is_create_only_and_outside_d1_session_namespace(self):
        store = _MarkerStore()
        first = claim_report_notification(_payload(), store=store)
        second = claim_report_notification(_payload(), store=store)
        self.assertEqual(first["status"], "CLAIMED")
        self.assertEqual(second["status"], "NOOP_REPORT_ALREADY_SENT")
        self.assertIn("system/operational/daily-report-notifications/", store.calls[0][0])
        self.assertNotIn("sessions/", store.calls[0][0])
        self.assertEqual(store.calls[0][2]["role"], "OPERATIONAL_REPORT_NOTIFICATION_CLAIM")

    def test_unconfigured_marker_store_does_not_read_a_token(self):
        result = claim_report_notification(_payload(), environ={})
        self.assertEqual(result["status"], "NOT_CONFIGURED")

    def test_noop_marker_suppresses_bark_and_email_retry(self):
        payload = _payload()
        with patch(
            "scripts.run_cloud_daily_report.claim_report_notification",
            return_value={"status": "NOOP_REPORT_ALREADY_SENT", "configured": True},
        ), patch("scripts.run_cloud_daily_report.send_bark") as bark, patch(
            "scripts.run_cloud_daily_report.send_optional_email"
        ) as email:
            _notify(payload, dashboard_html="<html></html>")
        bark.assert_not_called()
        email.assert_not_called()
        self.assertEqual(
            payload["cloud_daily_report"]["notifications"]["email"]["status"],
            "NOOP_REPORT_ALREADY_SENT",
        )


if __name__ == "__main__":
    unittest.main()

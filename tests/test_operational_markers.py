from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from scripts.run_cloud_daily_report import _notify
from trading.operational_markers import (
    claim_final_report_notification,
    claim_report_notification,
)


class _MarkerStore:
    def __init__(self):
        self.calls = []
        self.objects = {}

    def put_bytes(self, name, payload, **kwargs):
        self.calls.append((name, payload, kwargs))
        if name in self.objects:
            return {"status": "IDEMPOTENT_REPLAY"}
        self.objects[name] = bytes(payload)
        return {"status": "CREATED"}

    def scan(self, prefix="", *, with_hash=False):
        del with_hash
        return [{"name": name} for name in sorted(self.objects) if name.startswith(prefix)]

    def read_bytes(self, name, **kwargs):
        del kwargs
        payload = self.objects[name]
        return payload, {"sha256": ""}

    def add_legacy(
        self, *, market="US", session_date="2026-10-05",
        protocol="CLOUD-DAILY-REPORT-MOBILE-V1-2026-09-14", readiness=None,
    ):
        name = f"system/operational/daily-report-notifications/{market}/{session_date}/{protocol}.json"
        marker = {
            "schema_version": "DAILY_REPORT_NOTIFICATION_IDEMPOTENCY_V1",
            "identity": f"{market}|{session_date}|{protocol}",
            "market": market,
            "session_date": session_date,
            "report_protocol_version": protocol,
            "policy": "AT_MOST_ONE_NORMAL_NOTIFICATION",
        }
        if readiness:
            marker["delivery_readiness_state"] = readiness
        self.objects[name] = json.dumps(
            marker, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        return f"{market}|{session_date}|{protocol}"


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


def _us_payload(*, recovery_identity=None):
    payload = _payload()
    payload["market"] = "US"
    payload["as_of_date"] = "2026-10-05"
    payload["cloud_daily_report"].update({
        "market": "US",
        "as_of_date": "2026-10-05",
        "delivery_readiness": "FINAL_REPORT_ELIGIBLE",
    })
    if recovery_identity is not None:
        payload["cloud_daily_report"]["legacy_recovery_identity"] = recovery_identity
    return payload


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

    def test_valid_legacy_v1_marker_blocks_automatic_v2_duplicate(self):
        store = _MarkerStore()
        identity = store.add_legacy()

        result = claim_report_notification(_us_payload(), store=store)

        self.assertEqual(result["status"], "LEGACY_V1_MARKER_PRESENT")
        self.assertEqual(result["legacy_marker_identities"], [identity])
        self.assertFalse(any("final-v2" in name for name, _, _ in store.calls))

    def test_legacy_degraded_v1_marker_blocks_without_recovery_authorization(self):
        store = _MarkerStore()
        store.add_legacy(readiness="DEGRADED_DIAGNOSTIC_ONLY")
        payload = _us_payload()

        result = claim_final_report_notification(payload, store=store)

        self.assertEqual(result["status"], "LEGACY_V1_MARKER_PRESENT")
        self.assertEqual(store.calls, [])

    def test_explicit_us_legacy_recovery_is_audited_and_exactly_once(self):
        store = _MarkerStore()
        identity = store.add_legacy()
        payload = _us_payload(recovery_identity=identity)

        first = claim_report_notification(payload, store=store)
        second = claim_report_notification(payload, store=store)

        self.assertEqual(first["status"], "CLAIMED")
        self.assertEqual(second["status"], "NOOP_REPORT_ALREADY_SENT")
        migration_calls = [
            call for call in store.calls
            if "v1-to-v2" in call[0]
        ]
        final_calls = [
            call for call in store.calls
            if "final-v2" in call[0]
        ]
        self.assertEqual(len(migration_calls), 2)
        self.assertEqual(len(final_calls), 2)
        migration = json.loads(migration_calls[0][1].decode("utf-8"))
        self.assertEqual(migration["schema_version"], "DAILY_REPORT_LEGACY_V1_TO_V2_RECOVERY_V1")
        self.assertEqual(migration["legacy_marker_identity"], identity)

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

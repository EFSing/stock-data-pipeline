from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from research.setup01_d1_vps_store import VpsD1Store, VpsObjectMissing
from scripts.run_cloud_daily_report import _notify
from tests.test_setup01_d1_vps_store import LocalHelperRunner
from trading.operational_markers import (
    FINAL_SESSION_ALREADY_COMPLETED,
    claim_email_delivery_failure_alert,
    claim_corrected_final_recovery,
    claim_final_report_notification,
    claim_ledger_error_alert,
    claim_report_notification,
    final_report_session_status,
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
    def test_real_vps_missing_v2_and_legacy_markers_allow_first_session(self):
        with TemporaryDirectory() as directory:
            store = VpsD1Store(LocalHelperRunner(Path(directory)), storage_root=directory)
            for payload in (_payload(), _us_payload()):
                with self.subTest(market=payload["market"]):
                    # Use the actual helper -> VpsD1Store exception contract.
                    name = (
                        "system/operational/daily-report-notifications/final-v2/"
                        f"{payload['market']}/{payload['as_of_date']}/"
                        "DAILY_REPORT_FINAL_NOTIFICATION_IDEMPOTENCY_V2.json"
                    )
                    with self.assertRaises(VpsObjectMissing):
                        store.read_bytes(name)
                    legacy_prefix = (
                        "system/operational/daily-report-notifications/"
                        f"{payload['market']}/{payload['as_of_date']}/"
                    )
                    self.assertEqual(store.scan(legacy_prefix), [])
                    self.assertEqual(
                        final_report_session_status(payload, store=store)["status"],
                        "NO_FINAL_REPORT_MARKER",
                    )

    def test_real_vps_valid_final_marker_is_terminal(self):
        with TemporaryDirectory() as directory:
            store = VpsD1Store(LocalHelperRunner(Path(directory)), storage_root=directory)
            payload = _us_payload()
            claimed = claim_final_report_notification(payload, store=store)
            self.assertEqual(claimed["status"], "CLAIMED")
            self.assertEqual(
                final_report_session_status(payload, store=store)["status"],
                FINAL_SESSION_ALREADY_COMPLETED,
            )

    def test_real_vps_transport_identity_hash_and_read_errors_fail_closed(self):
        with TemporaryDirectory() as directory:
            local = LocalHelperRunner(Path(directory))
            for reason in (
                "D1_VPS_HELPER_FAILED", "D1_STORAGE_IDENTITY_MISMATCH",
                "D1_HASH_MISMATCH", "D1_REMOTE_READ_FAILED",
            ):
                for command in ("identity", "read", "scan"):
                    with self.subTest(reason=reason, command=command):
                        def runner(args, **kwargs):
                            if args[0] == command:
                                return 6, b"", json.dumps({"reason": reason}).encode()
                            return local(args, **kwargs)

                        store = VpsD1Store(runner, storage_root=directory)
                        result = final_report_session_status(_us_payload(), store=store)
                        self.assertEqual(result["status"], "IDEMPOTENCY_UNAVAILABLE")
                        self.assertIn(reason, result["error"])

    def test_real_vps_invalid_final_payload_still_fails_closed(self):
        with TemporaryDirectory() as directory:
            store = VpsD1Store(LocalHelperRunner(Path(directory)), storage_root=directory)
            payload = _us_payload()
            claimed = claim_final_report_notification(payload, store=store)
            path = Path(directory) / claimed["marker_name"]
            path.write_bytes(b"invalid JSON")
            self.assertEqual(
                final_report_session_status(payload, store=store)["status"],
                "FINAL_MARKER_INVALID",
            )

    def test_scanned_legacy_marker_missing_on_read_remains_fail_closed(self):
        store = _MarkerStore()
        store.add_legacy()
        store.read_bytes = Mock(side_effect=VpsObjectMissing(6, "D1_REMOTE_OBJECT_MISSING"))
        result = final_report_session_status(_us_payload(), store=store)
        self.assertEqual(result["status"], "IDEMPOTENCY_UNAVAILABLE")
        self.assertIn("legacy_marker_prefix", result)

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

    def test_finality_preflight_recognizes_legacy_final_evidence(self):
        store = _MarkerStore()
        identity = store.add_legacy()
        result = final_report_session_status(_us_payload(), store=store)
        self.assertEqual(result["status"], FINAL_SESSION_ALREADY_COMPLETED)
        self.assertEqual(result["marker_identities"], [identity])

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

    def test_report_ready_ledger_failure_claims_final_email_and_independent_bark(self):
        store = _MarkerStore()
        payload = _us_payload()
        payload["cloud_daily_report"].update({
            "OPPORTUNITY_LEDGER_STATUS": "FAILED",
            "opportunity_ledger_error": "controlled ledger failure",
            "final_delivery_eligibility": "FINAL_DELIVERY_BLOCKED_LEDGER",
            "final_delivery_reason": "OPPORTUNITY_LEDGER_FAILED",
            "report_data_readiness": "FINAL_REPORT_ELIGIBLE",
            "delivery_scope": "NATURAL",
            "delivery_notification_mode": "FINAL_WITH_LEDGER_ERROR",
            "data_quality": {"formal_exact_t_coverage_pct": 100},
        })
        with patch("scripts.run_cloud_daily_report.send_bark", return_value={"status": "SENT"}) as bark, patch(
            "scripts.run_cloud_daily_report.send_optional_email",
            return_value={"status": "SENT"},
        ) as email:
            _notify(payload, dashboard_html="<html></html>", marker_store=store)
            self.assertTrue(any("daily-report-alerts" in name for name in store.objects))
            self.assertTrue(any("final-v2" in name for name in store.objects))
            _notify(payload, dashboard_html="<html></html>", marker_store=store)
            self.assertEqual(bark.call_count, 1)
            self.assertEqual(email.call_count, 1)

        payload["cloud_daily_report"].update({
            "OPPORTUNITY_LEDGER_STATUS": "SUCCESS",
            "opportunity_ledger_error": None,
            "final_delivery_eligibility": "FINAL_DELIVERY_ELIGIBLE",
            "final_delivery_reason": "REPORT_DATA_AND_LEDGER_READY",
            "delivery_notification_mode": "FINAL",
        })
        with patch("scripts.run_cloud_daily_report.send_bark", return_value={"status": "SENT"}) as bark, patch(
            "scripts.run_cloud_daily_report.send_optional_email",
            return_value={"status": "SENT"},
        ) as email:
            _notify(payload, dashboard_html="<html></html>", marker_store=store)
            _notify(payload, dashboard_html="<html></html>", marker_store=store)
            bark.assert_not_called()
            email.assert_not_called()
        self.assertTrue(any("final-v2" in name for name in store.objects))

    def test_final_marker_guard_suppresses_degraded_alert_after_final(self):
        store = _MarkerStore()
        final = claim_final_report_notification(_us_payload(), store=store)
        self.assertEqual(final["status"], "CLAIMED")
        degraded = _us_payload()
        degraded["cloud_daily_report"].update({
            "delivery_readiness": "UPSTREAM_NOT_READY",
            "delivery_readiness_reason": "NO_USABLE_SYMBOLS",
            "delivery_notification_mode": "ALERT",
        })
        with patch("scripts.run_cloud_daily_report.send_bark") as bark, patch(
            "scripts.run_cloud_daily_report.send_optional_email"
        ) as email:
            _notify(degraded, dashboard_html="<html></html>", marker_store=store)
        bark.assert_not_called()
        email.assert_not_called()
        self.assertEqual(
            degraded["cloud_daily_report"]["notification_idempotency"]["status"],
            FINAL_SESSION_ALREADY_COMPLETED,
        )

    def test_ledger_and_email_failure_alert_identities_are_independent(self):
        store = _MarkerStore()
        payload = _us_payload()
        payload["cloud_daily_report"].update({
            "OPPORTUNITY_LEDGER_STATUS": "FAILED",
            "opportunity_ledger_error": "controlled ledger failure",
            "report_data_readiness": "FINAL_REPORT_ELIGIBLE",
            "delivery_scope": "NATURAL",
        })
        ledger = claim_ledger_error_alert(payload, store=store)
        email = claim_email_delivery_failure_alert(payload, store=store)
        self.assertEqual(ledger["status"], "CLAIMED")
        self.assertEqual(email["status"], "CLAIMED")
        self.assertNotEqual(ledger["marker_name"], email["marker_name"])
        self.assertEqual(final_report_session_status(payload, store=store)["status"], "NO_FINAL_REPORT_MARKER")

    def test_smtp_failure_is_recorded_and_emits_only_one_bark_alert(self):
        store = _MarkerStore()
        payload = _us_payload()
        with patch(
            "scripts.run_cloud_daily_report.send_optional_email",
            return_value={"status": "FAILED", "error": "SMTP unavailable"},
        ) as email, patch(
            "scripts.run_cloud_daily_report.send_bark",
            return_value={"status": "SENT"},
        ) as bark:
            _notify(payload, dashboard_html="<html></html>", marker_store=store)
            _notify(payload, dashboard_html="<html></html>", marker_store=store)

        email.assert_called_once()
        bark.assert_called_once()
        cloud = payload["cloud_daily_report"]
        self.assertEqual(cloud["email_delivery_status"], "EMAIL_DELIVERY_FAILED")
        self.assertEqual(cloud["email_failure_bark"]["status"], "SENT")
        self.assertIn("SMTP unavailable", bark.call_args.kwargs["body"])

    def test_bark_failure_is_recorded_without_email_fallback(self):
        store = _MarkerStore()
        payload = _us_payload()
        payload["cloud_daily_report"].update({
            "report_data_readiness": "UPSTREAM_NOT_READY",
            "delivery_readiness": "UPSTREAM_NOT_READY",
            "delivery_readiness_reason": "NO_USABLE_SYMBOLS",
            "delivery_notification_mode": "ALERT",
        })
        with patch(
            "scripts.run_cloud_daily_report.send_bark",
            return_value={"status": "FAILED", "error": "Bark unavailable"},
        ) as bark, patch(
            "scripts.run_cloud_daily_report.send_optional_email",
        ) as email:
            _notify(payload, dashboard_html="<html></html>", marker_store=store)

        bark.assert_called_once()
        email.assert_not_called()
        self.assertEqual(
            payload["cloud_daily_report"]["bark_delivery_status"],
            "BARK_DELIVERY_FAILED",
        )
        self.assertEqual(
            payload["cloud_daily_report"]["notifications"]["email"]["status"],
            "NOT_SENT_ERROR_BARK_ONLY",
        )

    def test_v2_corrected_final_recovery_is_explicit_audited_and_exactly_once(self):
        store = _MarkerStore()
        payload = _us_payload()
        payload["cloud_daily_report"].update({
            "final_delivery_eligibility": "FINAL_DELIVERY_ELIGIBLE",
            "delivery_scope": "NATURAL",
        })
        original = claim_final_report_notification(payload, store=store)
        recovery_identity = original["identity"]

        first = claim_corrected_final_recovery(
            payload, recovery_identity=recovery_identity, store=store,
        )
        second = claim_corrected_final_recovery(
            payload, recovery_identity=recovery_identity, store=store,
        )
        self.assertEqual(first["status"], "CORRECTED_FINAL_RECOVERY_CLAIMED")
        self.assertEqual(second["status"], "NOOP_CORRECTED_FINAL_ALREADY_SENT")
        self.assertFalse(first["send_performed"])
        self.assertTrue(any("v2-correction-audit" in name for name in store.objects))
        self.assertTrue(any("v2-corrected-final" in name for name in store.objects))
        self.assertEqual(
            claim_corrected_final_recovery(
                payload,
                recovery_identity="US|2026-10-05|WRONG",
                store=store,
            )["status"],
            "CORRECTED_FINAL_RECOVERY_IDENTITY_MISMATCH",
        )

    def test_diagnostic_scope_does_not_claim_natural_final_identity(self):
        store = _MarkerStore()
        payload = _us_payload()
        payload["cloud_daily_report"].update({
            "delivery_scope": "DIAGNOSTIC",
            "final_delivery_eligibility": "FINAL_DELIVERY_NOT_APPLICABLE_DIAGNOSTIC",
        })
        result = claim_report_notification(payload, store=store)
        self.assertEqual(result["status"], "NOT_NOTIFYABLE_DIAGNOSTIC")
        self.assertEqual(store.calls, [])


if __name__ == "__main__":
    unittest.main()

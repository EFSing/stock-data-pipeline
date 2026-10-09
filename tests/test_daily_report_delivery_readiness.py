from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.run_cloud_daily_report import (
    DEFAULT_RETRY_NOT_READY_ATTEMPTS,
    DEFAULT_RETRY_NOT_READY_DELAY_SECONDS,
    CANDIDATE_BROAD_STALE_RATIO,
    DEGRADED_DIAGNOSTIC_ONLY,
    FINAL_REPORT_ELIGIBLE,
    UPSTREAM_NOT_READY,
    _delivery_readiness,
    _finalize_delivery_eligibility,
    bounded_readiness_attempt_offsets,
    main as cloud_report_main,
    run_cloud_daily_report,
)
from trading.operational_markers import (
    claim_degraded_alert,
    claim_final_report_notification,
)


class _MarkerStore:
    def __init__(self):
        self.names = set()
        self.objects = {}

    def put_bytes(self, name, payload, **kwargs):
        if name in self.names:
            return {"status": "IDEMPOTENT_REPLAY"}
        self.names.add(name)
        self.objects[name] = bytes(payload)
        return {"status": "CREATED"}

    def scan(self, prefix="", *, with_hash=False):
        del with_hash
        return [{"name": name} for name in sorted(self.objects) if name.startswith(prefix)]

    def read_bytes(self, name, **kwargs):
        del kwargs
        return self.objects[name], {"sha256": ""}


def _result(
    market="US", *, candidate_status="SUCCESS", included=2,
    dynamic_analysis=2, selection="CANDIDATES_INCLUDED", formal_rows=2,
):
    return {
        "candidate_markets": {
            market: {
                "candidate_status": candidate_status,
                "status": "SUCCESS" if candidate_status == "SUCCESS" else candidate_status,
                "candidate_selection_outcome": selection,
                "candidate_included_count": included,
                "strategy_analysis_count": dynamic_analysis,
            }
        },
        "reports": [
            {
                "市场": market,
                "universe": {
                    "analysis_scope_counts": {
                        "formal_strategy_pool": formal_rows,
                        "dynamic_candidate_strategy_analysis": dynamic_analysis,
                    }
                },
                "报告": {
                    "results": [
                        {
                            "market": market,
                            "as_of_date": "2026-10-05",
                            "data_status": "DATA_OK",
                        }
                        for _ in range(formal_rows)
                    ],
                },
            }
        ],
    }


def _quality(
    *, run_status="COMPLETED", data_status="OK", candidate_status="SUCCESS",
    analyzed=2, operational=True, provider_global=False,
    formal_attempted=0, formal_usable=0, candidate_broad_stale=False,
):
    return {
        "run_status": run_status,
        "data_status": data_status,
        "candidate_status": candidate_status,
        "strategy_analyzed_count": analyzed,
        "operationally_complete": operational,
        "provider_global_failure": provider_global,
        "formal_exact_t_attempted_count": formal_attempted,
        "formal_exact_t_usable_count": formal_usable,
        "candidate_broad_stale": candidate_broad_stale,
    }


def _payload(readiness, *, reason="CANDIDATE_UNAVAILABLE_NO_ANALYSIS"):
    return {
        "market": "US",
        "as_of_date": "2026-10-05",
        "cloud_daily_report": {
            "market": "US",
            "as_of_date": "2026-10-05",
            "protocol_version": "CLOUD-DAILY-REPORT-MOBILE-V1-2026-09-14",
            "delivery_readiness": readiness,
            "delivery_readiness_reason": reason,
            "delivery_notification_mode": "ALERT" if readiness != FINAL_REPORT_ELIGIBLE else "FINAL",
        },
    }


class DailyReportDeliveryReadinessTests(unittest.TestCase):
    def test_case_a_early_us_is_upstream_not_ready_and_never_final(self):
        readiness = _delivery_readiness(
            market="US",
            status="PARTIAL_DATA_QUALITY",
            session_identity=object(),
            result=_result(candidate_status="UNAVAILABLE", included=0, dynamic_analysis=0, formal_rows=0),
            data_quality=_quality(
                run_status="COMPLETED_NO_USABLE_SYMBOLS",
                data_status="NO_USABLE_SYMBOLS",
                candidate_status="UNAVAILABLE",
                analyzed=0,
            ),
        )
        self.assertEqual(readiness["classification"], UPSTREAM_NOT_READY)
        self.assertFalse(readiness["final_report_eligible"])

    def test_case_b_recovered_us_is_final_eligible(self):
        readiness = _delivery_readiness(
            market="US",
            status="SUCCESS",
            session_identity=object(),
            result=_result(),
            data_quality=_quality(),
        )
        self.assertEqual(readiness["classification"], FINAL_REPORT_ELIGIBLE)
        self.assertTrue(readiness["final_report_eligible"])

    def test_formal_zero_coverage_cannot_be_upgraded_by_dynamic_analysis(self):
        readiness = _delivery_readiness(
            market="US",
            status="PARTIAL_DATA_QUALITY",
            session_identity=object(),
            result=_result(candidate_status="PARTIAL", included=701, dynamic_analysis=701),
            data_quality=_quality(
                data_status="PARTIAL", candidate_status="PARTIAL", analyzed=701,
                formal_attempted=2, formal_usable=0,
            ),
        )
        self.assertEqual(readiness["classification"], UPSTREAM_NOT_READY)
        self.assertEqual(readiness["reason"], "FORMAL_EXACT_T_NOT_READY")
        self.assertFalse(readiness["final_report_eligible"])

    def test_broad_candidate_stale_is_retryable_but_isolated_symbol_failure_is_final(self):
        broad = _delivery_readiness(
            market="US",
            status="PARTIAL_DATA_QUALITY",
            session_identity=object(),
            result=_result(candidate_status="PARTIAL", included=701, dynamic_analysis=701),
            data_quality=_quality(
                data_status="PARTIAL", candidate_status="PARTIAL", analyzed=701,
                formal_attempted=2, formal_usable=2, candidate_broad_stale=True,
            ),
        )
        self.assertEqual(broad["classification"], UPSTREAM_NOT_READY)
        self.assertEqual(broad["reason"], "CANDIDATE_EXACT_T_BROADLY_STALE")
        self.assertTrue(broad["retryable"])

        isolated = _delivery_readiness(
            market="US",
            status="PARTIAL_DATA_QUALITY",
            session_identity=object(),
            result=_result(candidate_status="PARTIAL", included=1002, dynamic_analysis=1002),
            data_quality=_quality(
                data_status="PARTIAL", candidate_status="PARTIAL", analyzed=1002,
                formal_attempted=2, formal_usable=2,
                candidate_broad_stale=False,
            ),
        )
        self.assertEqual(isolated["classification"], FINAL_REPORT_ELIGIBLE)
        self.assertGreater(CANDIDATE_BROAD_STALE_RATIO, 0)

    def test_case_c_degraded_alert_does_not_block_recovered_final_claim(self):
        store = _MarkerStore()
        degraded = claim_degraded_alert(_payload(UPSTREAM_NOT_READY), store=store)
        final = claim_final_report_notification(_payload(FINAL_REPORT_ELIGIBLE), store=store)
        self.assertEqual(degraded["status"], "CLAIMED")
        self.assertEqual(final["status"], "CLAIMED")
        self.assertNotEqual(degraded["marker_name"], final["marker_name"])

    def test_case_d_same_degraded_state_alert_is_exactly_once(self):
        store = _MarkerStore()
        first = claim_degraded_alert(_payload(DEGRADED_DIAGNOSTIC_ONLY, reason="CANDIDATE_UNAVAILABLE_FORMAL_ONLY"), store=store)
        second = claim_degraded_alert(_payload(DEGRADED_DIAGNOSTIC_ONLY, reason="CANDIDATE_UNAVAILABLE_FORMAL_ONLY"), store=store)
        self.assertEqual(first["status"], "CLAIMED")
        self.assertEqual(second["status"], "NOOP_DEGRADED_ALERT_ALREADY_SENT")

    def test_case_e_final_report_is_exactly_once(self):
        store = _MarkerStore()
        first = claim_final_report_notification(_payload(FINAL_REPORT_ELIGIBLE), store=store)
        second = claim_final_report_notification(_payload(FINAL_REPORT_ELIGIBLE), store=store)
        self.assertEqual(first["status"], "CLAIMED")
        self.assertEqual(second["status"], "NOOP_REPORT_ALREADY_SENT")

    def test_final_report_and_failed_ledger_keep_email_eligibility_separate(self):
        payload = _payload(FINAL_REPORT_ELIGIBLE)
        payload["cloud_daily_report"].update({
            "delivery_scope": "NATURAL",
            "OPPORTUNITY_LEDGER_STATUS": "FAILED",
        })
        _finalize_delivery_eligibility(payload, "FAILED")
        cloud = payload["cloud_daily_report"]
        self.assertEqual(cloud["final_delivery_eligibility"], "FINAL_DELIVERY_ELIGIBLE")
        self.assertTrue(cloud["final_delivery_eligible"])
        self.assertTrue(cloud["report_email_eligible"])
        self.assertTrue(cloud["opportunity_ledger_alert_required"])
        self.assertEqual(cloud["delivery_notification_mode"], "FINAL_WITH_LEDGER_ERROR")

    def test_case_f_cn_partial_symbol_quality_remains_final_eligible(self):
        readiness = _delivery_readiness(
            market="CN",
            status="PARTIAL_DATA_QUALITY",
            session_identity=object(),
            result=_result(
                market="CN", candidate_status="PARTIAL", included=735,
                dynamic_analysis=735, formal_rows=735,
            ),
            data_quality=_quality(
                data_status="PARTIAL", candidate_status="PARTIAL", analyzed=735,
            ),
        )
        self.assertEqual(readiness["classification"], FINAL_REPORT_ELIGIBLE)

    def test_nonzero_formal_partial_coverage_remains_final_when_candidate_is_usable(self):
        readiness = _delivery_readiness(
            market="CN",
            status="PARTIAL_DATA_QUALITY",
            session_identity=object(),
            result=_result(
                market="CN", candidate_status="PARTIAL", included=735,
                dynamic_analysis=735, formal_rows=2,
            ),
            data_quality=_quality(
                data_status="PARTIAL", candidate_status="PARTIAL", analyzed=735,
                formal_attempted=3, formal_usable=2,
            ),
        )
        self.assertEqual(readiness["classification"], FINAL_REPORT_ELIGIBLE)

    def test_case_g_incomplete_session_defers_without_final(self):
        readiness = _delivery_readiness(
            market="CN",
            status="INCOMPLETE_SESSION",
            session_identity=None,
            result={"reports": []},
            data_quality=_quality(run_status="INCOMPLETE_SESSION", data_status="INCOMPLETE_SESSION", analyzed=0),
        )
        self.assertEqual(readiness["classification"], UPSTREAM_NOT_READY)
        self.assertTrue(readiness["retryable"])

    def test_non_final_readiness_does_not_write_opportunity_ledger(self):
        ephemeral = SimpleNamespace(
            latest_rows=(), qfq_rows=(), symbol_status={}, active_paper_symbols=(),
            to_dict=lambda: {},
        )
        result = _result(candidate_status="UNAVAILABLE", included=0, dynamic_analysis=0, formal_rows=0)
        quality = _quality(
            run_status="COMPLETED_NO_USABLE_SYMBOLS",
            data_status="NO_USABLE_SYMBOLS",
            candidate_status="UNAVAILABLE",
            analyzed=0,
        )
        client = Mock()
        with TemporaryDirectory() as directory, \
                patch("scripts.run_cloud_daily_report.load_ephemeral_market_data", return_value=ephemeral), \
                patch("scripts.run_cloud_daily_report.run_production_daily_decision", return_value=result), \
                patch("scripts.run_cloud_daily_report._status_from_result", return_value=("PARTIAL_DATA_QUALITY", quality)):
            payload = run_cloud_daily_report(
                market="US",
                as_of_date=date(2026, 10, 5),
                now=datetime(2026, 10, 6, 7, tzinfo=timezone.utc),
                output_dir=directory,
                client=client,
                notify=False,
            )
        self.assertEqual(payload["cloud_daily_report"]["delivery_readiness"], UPSTREAM_NOT_READY)
        self.assertEqual(payload["cloud_daily_report"]["OPPORTUNITY_LEDGER_STATUS"], "NOT_ELIGIBLE_DELIVERY_READINESS")
        client.ensure_worksheet.assert_not_called()

    def test_observed_us_twenty_five_minute_lag_has_a_final_retry_attempt(self):
        offsets = bounded_readiness_attempt_offsets(
            DEFAULT_RETRY_NOT_READY_ATTEMPTS,
            DEFAULT_RETRY_NOT_READY_DELAY_SECONDS,
        )
        self.assertEqual(offsets, (0.0, 300.0, 600.0, 900.0, 1200.0, 1500.0))
        calls = []
        sleeps = []

        def fake_run(**kwargs):
            calls.append(kwargs)
            ready = offsets[len(calls) - 1] >= 1500.0
            return {
                "cloud_daily_report": {
                    "status": "SUCCESS" if ready else "PARTIAL_DATA_QUALITY",
                    "delivery_readiness": FINAL_REPORT_ELIGIBLE if ready else UPSTREAM_NOT_READY,
                    "delivery_readiness_retryable": not ready,
                    "run_status": "COMPLETED",
                    "data_status": "OK" if ready else "NO_USABLE_SYMBOLS",
                }
            }

        with TemporaryDirectory() as directory, \
                patch("scripts.run_cloud_daily_report.resolve_cloud_trade_date", return_value=date(2026, 10, 5)), \
                patch("scripts.run_cloud_daily_report.run_cloud_daily_report", side_effect=fake_run), \
                patch("scripts.run_cloud_daily_report.time.sleep", side_effect=sleeps.append):
            exit_code = cloud_report_main(["--market", "US", "--output", directory])

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 6)
        self.assertEqual(sleeps, [300.0] * 5)
        self.assertTrue(all(call["notify"] is False for call in calls))

    def test_internal_retry_is_silent_and_only_terminal_payload_is_notified(self):
        calls = []

        def fake_run(**kwargs):
            calls.append(kwargs)
            output = Path(kwargs["output_dir"])
            output.mkdir(parents=True, exist_ok=True)
            (output / "daily-report.html").write_text("<html></html>", encoding="utf-8")
            (output / "daily-report.json").write_text("{}", encoding="utf-8")
            ready = len(calls) == 2
            return {
                "cloud_daily_report": {
                    "status": "SUCCESS" if ready else "PARTIAL_DATA_QUALITY",
                    "delivery_readiness": FINAL_REPORT_ELIGIBLE if ready else UPSTREAM_NOT_READY,
                    "delivery_readiness_retryable": not ready,
                    "run_status": "COMPLETED",
                    "data_status": "OK" if ready else "NO_USABLE_SYMBOLS",
                }
            }

        with TemporaryDirectory() as directory, \
                patch("scripts.run_cloud_daily_report.resolve_cloud_trade_date", return_value=date(2026, 10, 5)), \
                patch("scripts.run_cloud_daily_report.run_cloud_daily_report", side_effect=fake_run), \
                patch("scripts.run_cloud_daily_report.time.sleep"), \
                patch("scripts.run_cloud_daily_report._notify") as notify:
            exit_code = cloud_report_main([
                "--market", "US", "--output", directory,
                "--retry-not-ready-delay-seconds", "0",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call["notify"] is False for call in calls))
        notify.assert_called_once()

    def test_observed_lag_trigger_order_model_keeps_a_bounded_recovery_path(self):
        offsets = bounded_readiness_attempt_offsets()
        trigger_orders = {
            "workflow_run_first": (0.0, 3600.0, 0.0),
            "fallback_first": (0.0, 600.0, 0.0),
            "both_before_provider_ready": (0.0, 300.0, 0.0),
            "close_delayed_hours": (3600.0, 14400.0, 14400.0),
        }
        for name, (fallback_start, workflow_start, close_time) in trigger_orders.items():
            with self.subTest(name=name):
                attempt_times = [
                    fallback_start + offset for offset in offsets
                ] + [
                    workflow_start + offset for offset in offsets
                ]
                self.assertTrue(any(
                    timestamp >= close_time + 1500.0
                    for timestamp in attempt_times
                ))


if __name__ == "__main__":
    unittest.main()

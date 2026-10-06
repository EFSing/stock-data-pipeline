from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.run_cloud_daily_report import (
    DEGRADED_DIAGNOSTIC_ONLY,
    FINAL_REPORT_ELIGIBLE,
    UPSTREAM_NOT_READY,
    _delivery_readiness,
    run_cloud_daily_report,
)
from trading.operational_markers import (
    claim_degraded_alert,
    claim_final_report_notification,
)


class _MarkerStore:
    def __init__(self):
        self.names = set()

    def put_bytes(self, name, payload, **kwargs):
        if name in self.names:
            return {"status": "IDEMPOTENT_REPLAY"}
        self.names.add(name)
        return {"status": "CREATED"}


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
):
    return {
        "run_status": run_status,
        "data_status": data_status,
        "candidate_status": candidate_status,
        "strategy_analyzed_count": analyzed,
        "operationally_complete": operational,
        "provider_global_failure": provider_global,
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


if __name__ == "__main__":
    unittest.main()

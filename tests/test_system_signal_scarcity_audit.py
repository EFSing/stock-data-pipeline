import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest

from research.development import system_signal_scarcity_audit_v1 as audit
from trading.models import DecisionAction
from trading.risk import risk_reward, target_upside_pct
from trading.setup01_decision import Setup01TargetCandidate, Setup01TargetProvenance


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _decision_record(
    *,
    action: DecisionAction,
    first_fail: str | None,
    all_fail_gates: tuple[str, ...],
    symbol: str = "TEST",
    market: str = "US",
    trade_date: date = date(2026, 1, 2),
    geometry: object | None = None,
) -> audit.DecisionRecord:
    event = SimpleNamespace(event_identity=f"{symbol}-{trade_date.isoformat()}")
    decision = SimpleNamespace(
        event_identity=event.event_identity,
        symbol=symbol,
        market=market,
        trade_date=trade_date,
        action=action,
        gate_reason=first_fail or "ENTRY_ALLOWED",
        decision_calculable=True,
    )
    return audit.DecisionRecord(
        setup_type=audit.SETUP01,
        event=event,
        decision=decision,
        execution=None,
        geometry=geometry,
        first_fail=first_fail,
        all_fail_gates=all_fail_gates,
    )


def _valid_entry_zone_record() -> tuple[audit.DecisionRecord, object, dict[str, list[SimpleNamespace]]]:
    day = date(2026, 1, 2)
    next_day = day + timedelta(days=1)
    candidate = Setup01TargetCandidate(
        price=175.0,
        source="WAVE3_FIB_EXTENSION",
        reason="controlled test candidate",
    )
    geometry = audit.GeometrySnapshot(
        setup_type=audit.SETUP01,
        calculable=True,
        reason="ABOVE_ENTRY_ZONE",
        atr14=20.0,
        planned_entry=115.0,
        entry_zone_low=100.0,
        entry_zone_high=110.0,
        structural_invalidation=90.0,
        execution_stop=85.0,
        confirmation_level=100.0,
        target_candidates=(candidate,),
        targets=(175.0,),
        rr=risk_reward(115.0, 85.0, (175.0,)),
        target_upside_pct=target_upside_pct(175.0, 115.0),
        target_reasonableness_failed=False,
        structure_values=(90.0, 100.0, 95.0),
        as_of_date=day,
    )
    record = _decision_record(
        action=DecisionAction.NO_TRADE,
        first_fail="ABOVE_ENTRY_ZONE",
        all_fail_gates=("ABOVE_ENTRY_ZONE",),
        symbol="TEST",
        market="US",
        trade_date=day,
        geometry=geometry,
    )
    quotes = {
        "TEST": [
            SimpleNamespace(symbol="TEST", market="US", trade_date=day, open=115.0),
            SimpleNamespace(symbol="TEST", market="US", trade_date=next_day, open=115.0),
        ]
    }
    return record, geometry, quotes


class SystemSignalScarcityAuditTests(unittest.TestCase):
    def test_protocol_identity_matches_recorded_hash(self) -> None:
        protocol, canonical_hash, file_hash = audit._protocol_identity()
        self.assertEqual(protocol["integrity"]["protocol_sha256"], canonical_hash)
        self.assertTrue(file_hash.startswith("sha256:"))
        self.assertEqual(protocol["protocol_version"], audit.PROTOCOL_VERSION)

    def test_checked_in_artifact_self_hash_and_compactness(self) -> None:
        path = PROJECT_ROOT / "research" / "development" / "system_signal_scarcity_audit_v1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = deepcopy(payload)
        recorded = body["integrity"]["canonical_payload_sha256"]
        body["integrity"]["canonical_payload_sha256"] = None
        self.assertEqual(recorded, audit._sha256_bytes(audit._canonical_json(body).encode("utf-8")))
        self.assertLess(path.stat().st_size, 200_000)
        self.assertEqual(payload["integrity"]["event_level_rows_persisted"], 0)
        self.assertFalse(payload["controls"]["final_oos_accessed"])
        self.assertFalse(payload["controls"]["parameter_search"])
        self.assertFalse(payload["controls"]["threshold_sweep"])
        self.assertFalse(payload["controls"]["production_rule_change"])

    def test_zero_denominator_rate_is_none(self) -> None:
        self.assertIsNone(audit._rate(1, 0))
        self.assertIsNone(audit._round(None))

    def test_distribution_is_deterministic_and_reports_requested_quantiles(self) -> None:
        summary = audit._distribution((1, 2, 3, 4, 5))
        self.assertEqual(summary["count"], 5)
        self.assertEqual(summary["median"], 3.0)
        self.assertEqual(summary["p10"], 1.4)
        self.assertEqual(summary["p90"], 4.6)
        self.assertIsNone(audit._distribution((None, float("nan")))["median"])

    def test_rr_failure_component_attribution_uses_fixed_counterfactuals(self) -> None:
        self.assertEqual(
            audit._rr_component_attribution(100, 90, 80, (125, 140))["category"],
            "EXECUTION_STOP_DISTANCE_TOO_LARGE",
        )
        self.assertEqual(
            audit._rr_component_attribution(100, 90, 90, (115, 130))["category"],
            "FIRST_FORMAL_TARGET_DISTANCE_TOO_CLOSE",
        )
        self.assertEqual(
            audit._rr_component_attribution(100, 90, 80, (115, 130))["category"],
            "BOTH_STOP_AND_TARGET_DISTANCE",
        )
        self.assertEqual(
            audit._rr_component_attribution(100, 90, 80, (115,))["category"],
            "INSUFFICIENT_COMPONENT_EVIDENCE",
        )

    def test_entry_zone_diagnostic_preserves_existing_strict_gate(self) -> None:
        record, _, _ = _valid_entry_zone_record()
        result = audit._entry_zone_diagnostics(
            (record,),
            {"US": {date(2026, 1, 2): "EARLY"}},
        )
        total = result["total"]
        self.assertEqual(total["confirmed_events"], 1)
        self.assertEqual(total["above_entry_zone_events"], 1)
        self.assertEqual(total["above_entry_zone_rate_of_confirmed_pct"], 100.0)
        self.assertGreater(total["overshoot_atr_normalized"]["median"], 0)

    def test_dashboard_contract_marks_armed_result_gap_without_renderer_math(self) -> None:
        contract = audit._dashboard_contract_audit()
        fields = contract["causal_availability_in_structural_evaluator"]
        self.assertTrue(fields["confirmation_trigger_price"]["available"])
        self.assertFalse(fields["confirmation_trigger_price"]["current_daily_result_exposed"])
        self.assertTrue(fields["structural_invalidation"]["available"])
        self.assertFalse(fields["current_close"]["current_daily_result_exposed"])
        self.assertFalse(contract["dashboard_current_behavior"]["renderer_recomputes_trade_math"])

    def test_overlap_conservation_and_pair_triple_intersection(self) -> None:
        records = (
            _decision_record(
                action=DecisionAction.NO_TRADE,
                first_fail="ABOVE_ENTRY_ZONE",
                all_fail_gates=("ABOVE_ENTRY_ZONE",),
            ),
            _decision_record(
                action=DecisionAction.NO_TRADE,
                first_fail="RR_BELOW_MINIMUM",
                all_fail_gates=("ABOVE_ENTRY_ZONE", "RR_BELOW_MINIMUM"),
                symbol="TEST2",
            ),
            _decision_record(
                action=DecisionAction.NO_TRADE,
                first_fail="RR_BELOW_MINIMUM",
                all_fail_gates=("RR_BELOW_MINIMUM", "TARGET_UPSIDE_BELOW_MINIMUM"),
                symbol="TEST3",
            ),
            _decision_record(
                action=DecisionAction.NO_TRADE,
                first_fail="ABOVE_ENTRY_ZONE",
                all_fail_gates=(
                    "ABOVE_ENTRY_ZONE",
                    "RR_BELOW_MINIMUM",
                    "TARGET_UPSIDE_BELOW_MINIMUM",
                ),
                symbol="TEST4",
            ),
            _decision_record(
                action=DecisionAction.ENTRY_ALLOWED,
                first_fail=None,
                all_fail_gates=(),
                symbol="TEST5",
            ),
        )
        overlap = audit._overlap_diagnostics(records)
        self.assertEqual(overlap["failed_decision_events"], 4)
        for row in overlap["gate_rows"]:
            self.assertEqual(
                row["raw_rejection_count"],
                row["unique_only_failure_count"] + row["overlap_rejection_count"],
            )
        triple = overlap["triple_overlap"]
        self.assertEqual(triple[0]["intersection_count"], 1)

    def test_setup_summary_uses_event_date_for_time_half(self) -> None:
        early = date(2026, 1, 2)
        late = date(2026, 1, 5)
        observations = (
            audit.SessionObservation(
                symbol="TEST",
                market="US",
                trade_date=early,
                time_half="EARLY",
                history_sufficient=True,
                weekly_state="UPTREND",
                daily_state="UPTREND",
                primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
                wave_primary_valid=True,
                setup01_wave_context_eligible=True,
                setup02_wave_context_eligible=False,
                setup01_state="CONFIRMED",
                setup02_state="NONE",
            ),
            audit.SessionObservation(
                symbol="TEST",
                market="US",
                trade_date=late,
                time_half="LATE",
                history_sufficient=True,
                weekly_state="UPTREND",
                daily_state="UPTREND",
                primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
                wave_primary_valid=True,
                setup01_wave_context_eligible=True,
                setup02_wave_context_eligible=False,
                setup01_state="CONFIRMED",
                setup02_state="NONE",
            ),
        )
        records = (
            _decision_record(action=DecisionAction.ENTRY_ALLOWED, first_fail=None, all_fail_gates=(), trade_date=early),
            _decision_record(action=DecisionAction.NO_TRADE, first_fail="RR_BELOW_MINIMUM", all_fail_gates=("RR_BELOW_MINIMUM",), trade_date=late, symbol="TEST-LATE"),
        )
        summary = audit._setup_summary(
            audit.SETUP01,
            observations,
            (),
            records,
            {"US": {early: "EARLY", late: "LATE"}},
        )
        self.assertEqual(summary["by_time_half"]["EARLY"]["confirmed_events"], 1)
        self.assertEqual(summary["by_time_half"]["LATE"]["confirmed_events"], 1)

    def test_entry_zone_ablation_maps_to_above_entry_zone_overlap_gate(self) -> None:
        record = _decision_record(
            action=DecisionAction.NO_TRADE,
            first_fail="ABOVE_ENTRY_ZONE",
            all_fail_gates=("ABOVE_ENTRY_ZONE",),
            geometry=SimpleNamespace(calculable=False, reason="STRUCTURAL_ISSUE"),
        )
        overlap = audit._overlap_diagnostics((record,))
        ablation = audit._single_gate_ablation(
            (record,),
            overlap,
            {},
            {"US": {record.decision.trade_date: "EARLY"}},
            {"US": [record.decision.trade_date]},
            {"policies": {"INCUMBENT_CONFIRMED_CLOSE": {"cohort": 0, "signaled": 0, "not_signaled": 0}}},
            1,
        )
        self.assertEqual(ablation["gates"]["ENTRY_ZONE"]["raw_rejection_count"], 1)
        self.assertEqual(ablation["gates"]["ENTRY_ZONE"]["unique_only_failure_count"], 1)

    def test_swing_high_ablation_preserves_independent_same_price_provenance(self) -> None:
        candidate = Setup01TargetCandidate(
            price=175.0,
            source="CONFIRMED_SWING_HIGH+WAVE3_FIB_EXTENSION",
            reason="merged explanations",
            provenance=(
                Setup01TargetProvenance(source="CONFIRMED_SWING_HIGH", pivot_date=date(2026, 1, 1)),
                Setup01TargetProvenance(source="WAVE3_FIB_EXTENSION", extension_ratio=1.618),
            ),
        )
        remaining = audit._remove_candidate_source(candidate, "CONFIRMED_SWING_HIGH")
        self.assertIsNotNone(remaining)
        self.assertEqual(remaining.source, "WAVE3_FIB_EXTENSION")
        self.assertEqual(tuple(item.source for item in remaining.provenance), ("WAVE3_FIB_EXTENSION",))

    def test_one_gate_ablation_does_not_mutate_source_and_only_entry_zone_adds_event(self) -> None:
        record, geometry, quotes = _valid_entry_zone_record()
        source_candidates = geometry.target_candidates
        overlap = audit._overlap_diagnostics((record,))
        ablation = audit._single_gate_ablation(
            (record,),
            overlap,
            quotes,
            {"US": {date(2026, 1, 2): "EARLY", date(2026, 1, 3): "LATE"}},
            {"US": [date(2026, 1, 2), date(2026, 1, 3)]},
            {"policies": {"INCUMBENT_CONFIRMED_CLOSE": {"cohort": 0, "signaled": 0, "not_signaled": 0}}},
            2,
        )
        self.assertEqual(ablation["gates"]["ENTRY_ZONE"]["incremental_entry_allowed"], 1)
        self.assertEqual(ablation["gates"]["ENTRY_ZONE"]["incremental_t1_executable"], 1)
        self.assertEqual(ablation["gates"]["RR_BELOW_MINIMUM"]["incremental_entry_allowed"], 0)
        self.assertEqual(ablation["gates"]["FORMAL_T1_CONFIRMED_SWING_HIGH"]["incremental_entry_allowed"], 0)
        self.assertEqual(geometry.target_candidates, source_candidates)
        self.assertEqual(record.all_fail_gates, ("ABOVE_ENTRY_ZONE",))

    def test_recent_context_without_reports_is_explicitly_insufficient(self) -> None:
        context = audit._recent_live_context(PROJECT_ROOT / "does-not-exist-reports")
        self.assertEqual(context["status"], "INSUFFICIENT_RECENT_LIVE_SAMPLE")
        self.assertFalse(context["production_reports_used"])

    def test_checked_in_artifact_reports_required_controls_and_ready_state(self) -> None:
        payload = json.loads(
            (PROJECT_ROOT / "research" / "development" / "system_signal_scarcity_audit_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["status"], "READY_FOR_DECISION")
        self.assertEqual(
            payload["decision"]["classification_code"],
            "STRUCTURAL_GATE_COLLISION_OBSERVED",
        )
        self.assertEqual(
            payload["decision"]["classification"],
            "STRUCTURAL_GATE_COLLISION_OBSERVED",
        )
        self.assertEqual(payload["validation"]["current_production_funnel_parity"], True)
        self.assertEqual(payload["validation"]["source_event_snapshot_unchanged"], True)
        self.assertEqual(payload["validation"]["cn_us_symbol_session_conservation"], True)
        self.assertEqual(payload["validation"]["single_gate_ablation_one_at_a_time"], True)
        self.assertIn("top_bottlenecks", payload)
        self.assertIn("confirmation_diagnostics", payload)
        self.assertIn("entry_zone_diagnostics", payload)
        self.assertIn("rr_diagnostics", payload)
        self.assertIn("target_upside_gate_contribution", payload)
        self.assertEqual(payload["funnel"]["aggregate"]["candidate_lifecycles"], 2050)
        self.assertEqual(payload["funnel"]["aggregate"]["confirmed_events"], 999)
        self.assertEqual(payload["funnel"]["aggregate"]["entry_allowed"], 8)
        self.assertEqual(payload["funnel"]["aggregate"]["executed"], 4)
        self.assertEqual(
            payload["entry_zone_diagnostics"]["aggregate"]["total"]["above_entry_zone_events"],
            595,
        )
        self.assertEqual(
            payload["target_upside_gate_contribution"]["one_gate_counterfactual_incremental_entry_allowed"],
            0,
        )


if __name__ == "__main__":
    unittest.main()

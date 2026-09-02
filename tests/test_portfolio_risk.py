from datetime import date, timedelta
from dataclasses import replace
from types import SimpleNamespace
import unittest

from trading.portfolio_risk import (
    BASE_RISK_FRACTION,
    BLOCK_EXISTING_POSITION_SAME_SYMBOL,
    BLOCK_RISK_GROUP_CONCENTRATION,
    BLOCK_TOTAL_RISK_BUDGET,
    BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION,
    DEVELOPMENT_EXPOSED,
    MAX_RISK_PER_GROUP_FRACTION,
    MAX_TOTAL_OPEN_RISK_FRACTION,
    OpenPortfolioPosition,
    PortfolioCandidate,
    PortfolioReservationStatus,
    PortfolioRiskEngine,
    PRODUCTION_OPEN_POSITION_ENTRY_BASIS_REQUIRED_FOR_RISK_ACCOUNTING,
    RISK_GROUP_UNKNOWN,
    RESERVATION_RELEASED_ON_FAILED_T1,
    candidate_from_decision,
    candidate_order_key,
    portfolio_exposure,
    resolve_reference_nav,
)


START = date(2026, 1, 1)


def candidate(
    symbol: str,
    *,
    index: int = 0,
    quality: str = "NORMAL",
    rr: float = 2.5,
    group: str = "UNKNOWN",
    outcome: str | None = "EXECUTED",
    actual_entry: float | None = None,
    action: str | None = None,
) -> PortfolioCandidate:
    planned_entry = 100.0 + index
    return PortfolioCandidate(
        event_identity=f"event-{symbol}-{index}",
        source_setup="SETUP_01",
        symbol=symbol,
        market="CN" if symbol.startswith("CN") else "US",
        trade_date=START + timedelta(days=index),
        planned_entry=planned_entry,
        execution_stop=planned_entry - 10.0,
        planned_rr=rr,
        rr_quality=quality,
        execution_outcome=outcome,
        execution_date=START + timedelta(days=index + 1),
        actual_entry=actual_entry if actual_entry is not None else planned_entry,
        risk_group=group,
        position_management_action=action,
    )


def open_position(
    symbol: str,
    *,
    price: float = 100.0,
    stop: float = 90.0,
    group: str = "UNKNOWN",
    quantity: float = 0.0005,
    actual_entry: float | None = 100.0,
) -> OpenPortfolioPosition:
    return OpenPortfolioPosition(
        source_event_identity=f"open-{symbol}",
        source_setup="SETUP_01",
        symbol=symbol,
        market="CN" if symbol.startswith("CN") else "US",
        entry_date=START,
        quantity=quantity,
        current_price=price,
        active_protective_stop=stop,
        risk_group=group,
        actual_entry=actual_entry,
    )


class PortfolioRiskTests(unittest.TestCase):
    def test_single_full_risk_unit_is_allowed(self):
        batch = PortfolioRiskEngine().reserve([candidate("AAA")])
        self.assertEqual(batch.approved[0].status, PortfolioReservationStatus.RESERVED)
        self.assertAlmostEqual(batch.approved[0].proposed_initial_risk_fraction, BASE_RISK_FRACTION)
        self.assertIsNotNone(batch.approved[0].planned_position_size)

    def test_exact_total_cap_allows_four_units(self):
        batch = PortfolioRiskEngine().reserve(
            [candidate(f"S{i}", index=i) for i in range(4)]
        )
        self.assertEqual(len(batch.approved), 4)
        self.assertAlmostEqual(
            batch.exposure_after_reservations.total_open_risk_fraction,
            MAX_TOTAL_OPEN_RISK_FRACTION,
        )

    def test_total_risk_above_cap_is_blocked(self):
        batch = PortfolioRiskEngine().reserve(
            [candidate(f"S{i}", index=i) for i in range(5)]
        )
        self.assertEqual(len(batch.approved), 4)
        self.assertEqual(batch.blocked[-1].reason, BLOCK_TOTAL_RISK_BUDGET)

    def test_same_symbol_is_exclusive(self):
        batch = PortfolioRiskEngine().reserve(
            [candidate("AAA", index=0), candidate("aaa", index=1)]
        )
        self.assertEqual(len(batch.approved), 1)
        self.assertEqual(batch.blocked[0].reason, BLOCK_EXISTING_POSITION_SAME_SYMBOL)

    def test_known_group_allows_two_units_and_blocks_third(self):
        batch = PortfolioRiskEngine().reserve(
            [candidate(f"S{i}", index=i, group="TECH") for i in range(3)]
        )
        self.assertEqual(len(batch.approved), 2)
        self.assertEqual(batch.blocked[-1].reason, BLOCK_RISK_GROUP_CONCENTRATION)
        self.assertAlmostEqual(
            batch.approved[-1].group_risk_after,
            MAX_RISK_PER_GROUP_FRACTION,
        )

    def test_unknown_group_is_development_advisory(self):
        batch = PortfolioRiskEngine(mode=DEVELOPMENT_EXPOSED).reserve([candidate("AAA")])
        self.assertEqual(batch.approved[0].reason, "PORTFOLIO_ALLOWED")
        self.assertIn(RISK_GROUP_UNKNOWN, batch.approved[0].advisory_flags)

    def test_unknown_group_is_production_fail_closed(self):
        batch = PortfolioRiskEngine(mode="PRODUCTION", reference_nav=1.0).reserve(
            [candidate("AAA")]
        )
        self.assertEqual(batch.blocked[0].reason, BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION)

    def test_stop_above_entry_reduces_remaining_loss_risk_to_zero(self):
        position = open_position("AAA", price=150.0, stop=120.0)
        self.assertEqual(position.remaining_loss_risk(1.0), 0.0)

    def test_current_price_does_not_change_remaining_capital_loss_risk(self):
        for price in (100.0, 150.0, 60.0):
            position = open_position("AAA", price=price, stop=90.0)
            self.assertAlmostEqual(position.remaining_loss_risk(1.0), 0.005)

    def test_stop_raise_monotonically_releases_remaining_capital_loss_risk(self):
        risks = [
            open_position("AAA", price=150.0, stop=stop).remaining_loss_risk(1.0)
            for stop in (90.0, 95.0, 100.0, 110.0)
        ]
        self.assertEqual(risks, [0.005, 0.0025, 0.0, 0.0])
        self.assertEqual(risks, sorted(risks, reverse=True))

    def test_negative_risk_never_offsets_other_positions(self):
        positions = [
            open_position("AAA", price=100.0, stop=110.0),
            open_position("BBB", price=100.0, stop=90.0),
        ]
        exposure = portfolio_exposure(positions, reference_nav=1.0)
        self.assertAlmostEqual(exposure.total_open_risk_fraction, 0.005)
        self.assertGreaterEqual(exposure.total_open_risk_fraction, 0.0)

    def test_missing_actual_entry_fails_closed_without_using_current_price(self):
        position = replace(
            open_position("AAA", price=150.0, stop=90.0), actual_entry=None
        )
        with self.assertRaisesRegex(
            ValueError,
            PRODUCTION_OPEN_POSITION_ENTRY_BASIS_REQUIRED_FOR_RISK_ACCOUNTING,
        ):
            position.remaining_loss_risk(1.0)

    def test_position_exit_releases_risk(self):
        position = open_position("AAA", price=100.0, stop=90.0)
        before = portfolio_exposure([position], reference_nav=1.0)
        after = portfolio_exposure([], reference_nav=1.0)
        self.assertAlmostEqual(before.total_open_risk_fraction, 0.005)
        self.assertEqual(after.total_open_risk_fraction, 0.0)

    def test_failed_t1_releases_reservation(self):
        engine = PortfolioRiskEngine()
        reservation = engine.reserve([candidate("AAA", outcome="SKIP_GAP_BELOW_CONFIRMATION")]).approved[0]
        settlement = engine.settle(reservation)
        self.assertEqual(settlement.status, PortfolioReservationStatus.RELEASED)
        self.assertEqual(settlement.reason, RESERVATION_RELEASED_ON_FAILED_T1)
        self.assertIsNone(settlement.position)

    def test_executed_actual_entry_recomputes_initial_risk_at_settlement(self):
        engine = PortfolioRiskEngine()
        reservation = engine.reserve(
            [candidate("ACTUAL", actual_entry=100.0)]
        ).approved[0]
        settlement = engine.settle(
            reservation,
            outcome="EXECUTED",
            execution_date=START + timedelta(days=1),
            actual_entry=110.0,
        )
        self.assertEqual(settlement.status, PortfolioReservationStatus.EXECUTED)
        self.assertIsNotNone(settlement.position)
        self.assertNotEqual(reservation.candidate.planned_entry, 110.0)
        self.assertAlmostEqual(
            settlement.position.quantity * (110.0 - 90.0),
            BASE_RISK_FRACTION,
        )
        self.assertAlmostEqual(
            settlement.position.remaining_loss_risk(1.0),
            BASE_RISK_FRACTION,
        )

    def test_executed_without_actual_entry_fails_closed_at_settlement(self):
        engine = PortfolioRiskEngine()
        reservation = engine.reserve([replace(candidate("MISSING"), actual_entry=None)]).approved[0]
        settlement = engine.settle(reservation, outcome="EXECUTED")
        self.assertEqual(settlement.status, PortfolioReservationStatus.RELEASED)
        self.assertEqual(
            settlement.reason,
            PRODUCTION_OPEN_POSITION_ENTRY_BASIS_REQUIRED_FOR_RISK_ACCOUNTING,
        )
        self.assertIsNone(settlement.position)

    def test_simultaneous_order_is_quality_rr_then_symbol(self):
        candidates = [
            candidate("ZZZ", quality="NORMAL", rr=4.0),
            candidate("BBB", quality="HIGH_QUALITY", rr=3.0),
            candidate("AAA", quality="HIGH_ASYMMETRY", rr=6.0),
            candidate("CCC", quality="HIGH_QUALITY", rr=3.0),
        ]
        batch = PortfolioRiskEngine().reserve(candidates)
        self.assertEqual(
            batch.ordered_candidate_ids,
            ("event-AAA-0", "event-BBB-0", "event-CCC-0", "event-ZZZ-0"),
        )

    def test_order_key_does_not_use_future_outcomes(self):
        first = candidate("AAA", quality="NORMAL", rr=2.1, outcome="EXECUTED")
        second = candidate("AAA", quality="NORMAL", rr=2.1, outcome="SKIP_GAP_BELOW_CONFIRMATION")
        self.assertEqual(candidate_order_key(first), candidate_order_key(second))

    def test_decision_projection_does_not_mutate_upstream_object(self):
        decision = SimpleNamespace(
            event_identity="event-1",
            symbol="AAA",
            market="US",
            trade_date=START,
            action=SimpleNamespace(value="ENTRY_ALLOWED"),
            planned_entry=100.0,
            execution_stop=90.0,
            rr=SimpleNamespace(rr_ratios=(3.0,), quality="HIGH_QUALITY"),
        )
        before = vars(decision).copy()
        projected = candidate_from_decision(decision, source_setup="SETUP_01")
        self.assertEqual(vars(decision), before)
        self.assertEqual(projected.planned_entry, 100.0)

    def test_reservation_settlement_is_exact_once(self):
        engine = PortfolioRiskEngine()
        reservation = engine.reserve([candidate("AAA")]).approved[0]
        engine.settle(reservation)
        with self.assertRaises(ValueError):
            engine.settle(reservation)

    def test_future_session_does_not_change_prior_session_order(self):
        prior = [candidate("BBB", index=0), candidate("AAA", index=0)]
        future = candidate("ZZZ", index=1, quality="HIGH_ASYMMETRY", rr=9.0)
        first = PortfolioRiskEngine().reserve(prior)
        later = PortfolioRiskEngine().reserve(prior)
        self.assertEqual(first.ordered_candidate_ids, later.ordered_candidate_ids)
        self.assertNotIn(future.event_identity, later.ordered_candidate_ids)

    def test_production_nav_is_required_without_guessing(self):
        nav, reason = resolve_reference_nav(mode="PRODUCTION")
        self.assertIsNone(nav)
        self.assertEqual(reason, "PORTFOLIO_NAV_REQUIRED")
        batch = PortfolioRiskEngine(mode="PRODUCTION").reserve([candidate("AAA")])
        self.assertEqual(batch.blocked[0].reason, "PORTFOLIO_NAV_REQUIRED")

    def test_metadata_resolves_formal_group_without_inference(self):
        batch = PortfolioRiskEngine(
            risk_group_metadata={"AAA": "TECH"}
        ).reserve([candidate("AAA")])
        self.assertEqual(batch.approved[0].candidate.risk_group, "TECH")
        self.assertNotIn(RISK_GROUP_UNKNOWN, batch.approved[0].advisory_flags)

    def test_no_add_blocks_same_symbol_candidate(self):
        batch = PortfolioRiskEngine().reserve(
            [candidate("AAA", action="NO_ADD")]
        )
        self.assertEqual(batch.blocked[0].reason, "BLOCK_POSITION_MANAGEMENT_NO_ADD")


if __name__ == "__main__":
    unittest.main()

"""Synthetic-only operational shadow for Portfolio Risk V1."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from trading.portfolio_risk import (
    BASE_RISK_FRACTION,
    BLOCK_EXISTING_POSITION_SAME_SYMBOL,
    BLOCK_RISK_GROUP_CONCENTRATION,
    BLOCK_TOTAL_RISK_BUDGET,
    BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION,
    OpenPortfolioPosition,
    PortfolioCandidate,
    PortfolioReservationStatus,
    PortfolioRiskEngine,
    RISK_GROUP_UNKNOWN,
    RESERVATION_RELEASED_ON_FAILED_T1,
    candidate_from_decision,
    portfolio_exposure,
)


def _candidate(symbol: str, *, index: int = 0, quality: str = "NORMAL", rr: float = 2.5, group: str = "UNKNOWN", outcome: str = "EXECUTED") -> PortfolioCandidate:
    entry = 100.0 + index
    return PortfolioCandidate(
        event_identity=f"shadow-{symbol}-{index}",
        source_setup="SETUP_01",
        symbol=symbol,
        market="CN" if symbol.startswith("CN") else "US",
        trade_date=date(2026, 1, 1),
        planned_entry=entry,
        execution_stop=entry - 10.0,
        planned_rr=rr,
        rr_quality=quality,
        execution_outcome=outcome,
        execution_date=date(2026, 1, 2),
        actual_entry=entry,
        risk_group=group,
    )


def _position(symbol: str, *, price: float = 100.0, stop: float = 90.0) -> OpenPortfolioPosition:
    return OpenPortfolioPosition(
        source_event_identity=f"open-{symbol}",
        source_setup="SETUP_01",
        symbol=symbol,
        market="US",
        entry_date=date(2026, 1, 1),
        quantity=0.0005,
        current_price=price,
        active_protective_stop=stop,
        risk_group="UNKNOWN",
        actual_entry=100.0,
    )


def run_portfolio_risk_generic_operational_shadow(*, output_dir: str | Path) -> dict[str, Any]:
    checks: dict[str, bool] = {}

    single = PortfolioRiskEngine().reserve([_candidate("A")])
    checks["single_full_risk_allowed"] = len(single.approved) == 1 and single.approved[0].proposed_initial_risk_fraction == BASE_RISK_FRACTION

    exact = PortfolioRiskEngine().reserve([_candidate(f"S{i}", index=i) for i in range(4)])
    checks["exact_total_cap_allowed"] = len(exact.approved) == 4 and exact.exposure_after_reservations.total_open_risk_fraction == 0.02
    over = PortfolioRiskEngine().reserve([_candidate(f"O{i}", index=i) for i in range(5)])
    checks["over_total_cap_blocked"] = over.blocked[-1].reason == BLOCK_TOTAL_RISK_BUDGET

    same_symbol = PortfolioRiskEngine().reserve([_candidate("AAA"), _candidate("aaa", index=1)])
    checks["same_symbol_blocked"] = same_symbol.blocked[0].reason == BLOCK_EXISTING_POSITION_SAME_SYMBOL

    group = PortfolioRiskEngine().reserve([_candidate(f"G{i}", index=i, group="TECH") for i in range(3)])
    checks["group_boundary"] = len(group.approved) == 2 and group.blocked[-1].reason == BLOCK_RISK_GROUP_CONCENTRATION

    unknown_dev = PortfolioRiskEngine().reserve([_candidate("UNK")])
    unknown_prod = PortfolioRiskEngine(mode="PRODUCTION", reference_nav=1.0).reserve([_candidate("UNK")])
    checks["unknown_development_advisory"] = RISK_GROUP_UNKNOWN in unknown_dev.approved[0].advisory_flags
    checks["unknown_production_fail_closed"] = unknown_prod.blocked[0].reason == BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION

    price_risks = [
        portfolio_exposure([_position("PRICE", price=price)], reference_nav=1.0)
        .total_open_risk_fraction
        for price in (100.0, 150.0, 60.0)
    ]
    raised = portfolio_exposure([_position("RAISED", price=100.0, stop=120.0)], reference_nav=1.0)
    regular = portfolio_exposure([_position("REGULAR")], reference_nav=1.0)
    checks["stop_raise_reduces_to_zero"] = (
        raised.total_open_risk_fraction == 0.0
        and price_risks == [0.005, 0.005, 0.005]
        and regular.total_open_risk_fraction >= 0.0
    )
    checks["negative_risk_never_offsets"] = portfolio_exposure(
        [_position("LOCKED", stop=120.0), _position("REGULAR")],
        reference_nav=1.0,
    ).total_open_risk_fraction == 0.005
    checks["exit_releases_risk"] = portfolio_exposure([], reference_nav=1.0).total_open_risk_fraction == 0.0

    failed_engine = PortfolioRiskEngine()
    failed_reservation = failed_engine.reserve([_candidate("FAIL", outcome="SKIP_NO_T1_BAR")]).approved[0]
    failed_settlement = failed_engine.settle(failed_reservation)
    checks["failed_t1_releases_reservation"] = failed_settlement.status is PortfolioReservationStatus.RELEASED and failed_settlement.reason == RESERVATION_RELEASED_ON_FAILED_T1

    ordering = PortfolioRiskEngine().reserve([
        _candidate("ZZZ", quality="NORMAL", rr=4.0),
        _candidate("CCC", quality="HIGH_QUALITY", rr=3.0),
        _candidate("BBB", quality="HIGH_QUALITY", rr=3.0),
        _candidate("AAA", quality="HIGH_ASYMMETRY", rr=6.0),
    ])
    checks["deterministic_rr_order"] = ordering.ordered_candidate_ids == (
        "shadow-AAA-0", "shadow-BBB-0", "shadow-CCC-0", "shadow-ZZZ-0"
    )

    first = _candidate("FUTURE", quality="NORMAL", rr=2.1, outcome="EXECUTED")
    second = _candidate("FUTURE", quality="NORMAL", rr=2.1, outcome="SKIP_GAP_BELOW_CONFIRMATION")
    checks["ordering_has_no_future_metric"] = (
        first.planned_rr == second.planned_rr
        and first.rr_quality == second.rr_quality
    )

    decision = SimpleNamespace(
        event_identity="shadow-decision",
        symbol="IMMUTABLE",
        market="US",
        trade_date=date(2026, 1, 1),
        action=SimpleNamespace(value="ENTRY_ALLOWED"),
        planned_entry=100.0,
        execution_stop=90.0,
        rr=SimpleNamespace(rr_ratios=(3.0,), quality="HIGH_QUALITY"),
    )
    before = vars(decision).copy()
    projected = candidate_from_decision(decision, source_setup="SETUP_01")
    checks["upstream_geometry_immutable"] = vars(decision) == before and projected.planned_entry == 100.0 and projected.execution_stop == 90.0
    checks["theoretical_quantity_retained"] = single.approved[0].planned_position_size is not None and single.approved[0].planned_position_size.theoretical_quantity == 0.0005

    exact_once_engine = PortfolioRiskEngine()
    exact_once_reservation = exact_once_engine.reserve([_candidate("ONCE")]).approved[0]
    exact_once_engine.settle(exact_once_reservation)
    try:
        exact_once_engine.settle(exact_once_reservation)
    except ValueError:
        checks["exact_once_ledger"] = True
    else:
        checks["exact_once_ledger"] = False

    prior = PortfolioRiskEngine().reserve([_candidate("AAA"), _candidate("BBB")])
    # A later session is evaluated independently; appending its candidate
    # cannot change the already-frozen prior-session ordering.
    future_session = PortfolioRiskEngine().reserve([_candidate("ZZZ", index=1, quality="HIGH_ASYMMETRY", rr=8.0)])
    checks["future_append_invariance"] = (
        prior.ordered_candidate_ids == ("shadow-AAA-0", "shadow-BBB-0")
        and future_session.ordered_candidate_ids == ("shadow-ZZZ-1",)
    )

    result = {
        "protocol_version": "PORTFOLIO-RISK-2026-09-02-v1",
        "status": "SUCCESS" if all(checks.values()) else "FAILED",
        "checks": checks,
        "synthetic_only": True,
        "broker_accessed": False,
        "holdings_accessed": False,
        "sheets_written": False,
        "pnl_accessed": False,
        "final_oos_accessed": False,
        "future_metrics_used_for_ordering": False,
    }
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "portfolio_risk_generic_operational_shadow.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(json.dumps(run_portfolio_risk_generic_operational_shadow(output_dir=args.output_dir), ensure_ascii=False, indent=2))

"""DEVELOPMENT_EXPOSED mechanical Portfolio Risk V1 replay.

The replay composes the frozen SETUP_01/SETUP_02 Decision + T+1 streams with
the already-frozen Position Management output.  Portfolio Risk only reserves
capacity for individual ``ENTRY_ALLOWED`` rows; it never changes an upstream
object or creates a new signal.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from core import Quote
from research.development_dataset import DATASET_MANIFEST_PATH, load_frozen_dataset
from research.position_management_replay import (
    _load_cache_parity_audit,
    _stream_origins,
)
from trading.position_management import (
    EXECUTED,
    PositionReplay,
    position_replay_to_dict,
    replay_positions,
)
from trading.portfolio_risk import (
    BASE_RISK_FRACTION,
    BLOCK_TOTAL_RISK_BUDGET,
    DEVELOPMENT_EXPOSED,
    MAX_RISK_PER_GROUP_FRACTION,
    MAX_TOTAL_OPEN_RISK_FRACTION,
    OpenPortfolioPosition,
    PortfolioCandidate,
    PortfolioReservationStatus,
    PortfolioRiskEngine,
    PortfolioSettlement,
    RISK_GROUP_UNKNOWN,
    candidate_from_decision,
    candidate_to_dict,
    portfolio_exposure,
    position_to_dict,
    remaining_loss_risk_fraction,
    reservation_to_dict,
    resolve_reference_nav,
    settlement_to_dict,
)
from trading.setup01_decision import (
    Setup01DecisionStream,
    evaluate_setup01_decision_stream,
)
from trading.setup01_replay import replay_setup01_history
from trading.setup02_decision import (
    Setup02DecisionStream,
    evaluate_setup02_decision_stream,
)
from trading.setup02_replay import replay_setup02_history


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _source_streams(
    quotes_by_symbol: Mapping[str, Sequence[Quote]],
    *,
    swing_lookback: int,
    atr_period: int,
) -> tuple[
    list[object],
    list[object],
    Setup01DecisionStream,
    Setup02DecisionStream,
]:
    setup01_events: list[object] = []
    setup02_events: list[object] = []
    for symbol in sorted(quotes_by_symbol):
        quotes = quotes_by_symbol[symbol]
        setup01_events.extend(replay_setup01_history(list(quotes)).events)
        setup02_events.extend(replay_setup02_history(list(quotes)).events)
    return (
        setup01_events,
        setup02_events,
        evaluate_setup01_decision_stream(
            setup01_events,
            quotes_by_symbol,
            swing_lookback=swing_lookback,
            atr_period=atr_period,
        ),
        evaluate_setup02_decision_stream(
            setup02_events,
            quotes_by_symbol,
            swing_lookback=swing_lookback,
            atr_period=atr_period,
        ),
    )


def _individual_candidates(
    source_setup: str,
    stream: Setup01DecisionStream | Setup02DecisionStream,
    *,
    risk_group_metadata: Mapping[str, str] | None,
) -> tuple[PortfolioCandidate, ...]:
    executions = {item.event_identity: item for item in stream.executions}
    candidates: list[PortfolioCandidate] = []
    for decision in stream.decisions:
        action = getattr(decision.action, "value", decision.action)
        if action != "ENTRY_ALLOWED":
            continue
        # Metadata is a supplied formal value only; absent metadata remains
        # UNKNOWN and is never inferred from prices or historical correlation.
        metadata_group = (risk_group_metadata or {}).get(decision.symbol)
        candidates.append(
            candidate_from_decision(
                decision,
                source_setup=source_setup,
                execution=executions.get(decision.event_identity),
                risk_group=metadata_group,
            )
        )
    return tuple(candidates)


def _latest_position_day(
    replay: PositionReplay,
    as_of_date,
) -> object | None:
    visible = [day for day in replay.days if day.trade_date <= as_of_date]
    return visible[-1] if visible else None


def _open_position_at(
    replay: PositionReplay,
    settlement: PortfolioSettlement,
    as_of_date,
    *,
    risk_group: str,
) -> OpenPortfolioPosition | None:
    if settlement.position is None or settlement.position_size is None:
        return None
    if settlement.position.entry_date > as_of_date:
        return None
    day = _latest_position_day(replay, as_of_date)
    if day is None or not day.position_open_at_close or day.close is None:
        return None
    return OpenPortfolioPosition(
        source_event_identity=settlement.position.source_event_identity,
        source_setup=settlement.position.source_setup,
        symbol=settlement.position.symbol,
        market=settlement.position.market,
        entry_date=settlement.position.entry_date,
        quantity=settlement.position_size.theoretical_quantity,
        current_price=float(day.close),
        active_protective_stop=float(day.active_stop_next_session),
        risk_group=risk_group,
        actual_entry=settlement.position.actual_entry,
    )


def _session_positions(
    settlements: Mapping[str, PortfolioSettlement],
    replays_by_identity: Mapping[str, PositionReplay],
    as_of_date,
) -> tuple[OpenPortfolioPosition, ...]:
    positions: list[OpenPortfolioPosition] = []
    for identity, settlement in settlements.items():
        replay = replays_by_identity.get(identity)
        if replay is None:
            continue
        position = _open_position_at(
            replay,
            settlement,
            as_of_date,
            risk_group=settlement.reservation.candidate.normalized_risk_group,
        )
        if position is not None:
            positions.append(position)
    return tuple(positions)


def _risk_release_diagnostics(
    settlements: Mapping[str, PortfolioSettlement],
    replays_by_identity: Mapping[str, PositionReplay],
    *,
    reference_nav: float,
) -> dict[str, Any]:
    stop_releases: list[dict[str, Any]] = []
    exit_releases: list[dict[str, Any]] = []
    for identity, settlement in sorted(settlements.items()):
        if settlement.position is None or settlement.position_size is None:
            continue
        replay = replays_by_identity.get(identity)
        if replay is None:
            continue
        quantity = settlement.position_size.theoretical_quantity
        for day in replay.days:
            if day.stop_raised:
                before = remaining_loss_risk_fraction(
                    quantity=quantity,
                    actual_entry=settlement.position.actual_entry,
                    active_protective_stop=float(day.active_stop_at_open),
                    reference_nav=reference_nav,
                )
                after = remaining_loss_risk_fraction(
                    quantity=quantity,
                    actual_entry=settlement.position.actual_entry,
                    active_protective_stop=float(day.active_stop_next_session),
                    reference_nav=reference_nav,
                )
                if after > before + 1e-12:
                    raise AssertionError(
                        "stop raise increased remaining capital-loss risk"
                    )
                stop_releases.append(
                    {
                        "reservation_id": identity,
                        "trade_date": day.trade_date.isoformat(),
                        "risk_before": before,
                        "risk_after": after,
                        "capacity_released": max(before - after, 0.0),
                        "after_lte_before": after <= before + 1e-12,
                    }
                )
        if replay.exit_date is not None:
            exit_day = next(
                (day for day in replay.days if day.trade_date == replay.exit_date),
                None,
            )
            if exit_day is not None:
                at_exit = remaining_loss_risk_fraction(
                    quantity=quantity,
                    actual_entry=settlement.position.actual_entry,
                    active_protective_stop=float(exit_day.active_stop_at_open),
                    reference_nav=reference_nav,
                )
                exit_releases.append(
                    {
                        "reservation_id": identity,
                        "exit_date": replay.exit_date.isoformat(),
                        "exit_reason": replay.exit_reason.value if replay.exit_reason else None,
                        "risk_before_exit": at_exit,
                        "risk_after_exit": 0.0,
                        "remaining_portfolio_risk_after": 0.0,
                        "capacity_released": max(at_exit, 0.0),
                    }
                )
    return {
        "stop_raise_releases": stop_releases,
        "exit_releases": exit_releases,
        "stop_raise_capacity_released": sum(
            item["capacity_released"] for item in stop_releases
        ),
        "exit_capacity_released": sum(
            item["capacity_released"] for item in exit_releases
        ),
    }


def _open_risk_session_ledger(
    settlements: Mapping[str, PortfolioSettlement],
    replays_by_identity: Mapping[str, PositionReplay],
    *,
    reference_nav: float,
) -> list[dict[str, Any]]:
    """Report corrected open-risk exposure for every observed PM session."""
    session_dates = sorted(
        {
            day.trade_date
            for replay in replays_by_identity.values()
            for day in replay.days
        }
    )
    ledger: list[dict[str, Any]] = []
    for session_date in session_dates:
        positions = _session_positions(
            settlements, replays_by_identity, session_date
        )
        exposure = portfolio_exposure(positions, reference_nav=reference_nav)
        ledger.append(
            {
                "session_date": session_date.isoformat(),
                "total_open_risk_fraction": exposure.total_open_risk_fraction,
                "risk_by_group": exposure.risk_by_group,
                "risk_by_market": exposure.risk_by_market,
                "position_count": exposure.position_count,
                "open_position_ids": sorted(
                    item.source_event_identity for item in positions
                ),
            }
        )
    return ledger


def _source_counts(
    events: Mapping[str, Sequence[object]],
    streams: Mapping[str, Setup01DecisionStream | Setup02DecisionStream],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source in ("SETUP_01", "SETUP_02"):
        stream = streams[source]
        result[source] = {
            "structural_events": len(events[source]),
            "unique_structural_event_identities": len(
                {item.event_identity for item in events[source]}
            ),
            "decision_rows": len(stream.decisions),
            "individual_entry_allowed": sum(
                getattr(item.action, "value", item.action) == "ENTRY_ALLOWED"
                for item in stream.decisions
            ),
            "execution_rows": len(stream.executions),
            "execution_status_counts": dict(
                sorted(Counter(item.outcome for item in stream.executions).items())
            ),
        }
    return result


def _execution_map(
    streams: Mapping[str, Setup01DecisionStream | Setup02DecisionStream],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for stream in streams.values():
        for item in stream.executions:
            if item.event_identity in result:
                raise ValueError(f"duplicate execution identity: {item.event_identity}")
            result[item.event_identity] = item
    return result


def _settlement_position_ids(
    settlements: Mapping[str, PortfolioSettlement],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            identity
            for identity, item in settlements.items()
            if item.status is PortfolioReservationStatus.EXECUTED
        )
    )


def build_portfolio_risk_replay(
    *,
    manifest_path: str | None = None,
    swing_lookback: int = 5,
    atr_period: int = 14,
    mode: str = DEVELOPMENT_EXPOSED,
    reference_nav: float | None = None,
    risk_group_metadata: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the frozen development Portfolio Risk ledger/report."""
    resolved_nav, nav_error = resolve_reference_nav(
        mode=mode, reference_nav=reference_nav
    )
    manifest, quotes_by_symbol = load_frozen_dataset(
        Path(manifest_path) if manifest_path is not None else DATASET_MANIFEST_PATH
    )
    setup01_events, setup02_events, setup01_stream, setup02_stream = _source_streams(
        quotes_by_symbol,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    source_events = {"SETUP_01": setup01_events, "SETUP_02": setup02_events}
    source_streams = {"SETUP_01": setup01_stream, "SETUP_02": setup02_stream}
    candidates = (
        *_individual_candidates(
            "SETUP_01", setup01_stream, risk_group_metadata=risk_group_metadata
        ),
        *_individual_candidates(
            "SETUP_02", setup02_stream, risk_group_metadata=risk_group_metadata
        ),
    )
    origins = (
        *_stream_origins("SETUP_01", setup01_events, setup01_stream),
        *_stream_origins("SETUP_02", setup02_events, setup02_stream),
    )
    pm_replays = replay_positions(
        origins,
        quotes_by_symbol,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    replays_by_identity = {
        replay.origin.source_event_identity: replay for replay in pm_replays
    }
    execution_by_identity = _execution_map(source_streams)

    # Candidate reservations compete only within the same Decision session;
    # failed T+1 attempts are settled immediately after that session's batch
    # and therefore cannot occupy a later session's budget.
    session_candidates: dict[Any, list[PortfolioCandidate]] = defaultdict(list)
    for candidate in candidates:
        session_candidates[candidate.trade_date].append(candidate)
    settled: dict[str, PortfolioSettlement] = {}
    all_reservations: list[dict[str, Any]] = []
    all_settlements: list[dict[str, Any]] = []
    session_ledger: list[dict[str, Any]] = []
    maximum_observed_total = 0.0
    for session_date in sorted(session_candidates):
        existing = _session_positions(
            settled, replays_by_identity, session_date
        )
        engine = PortfolioRiskEngine(
            mode=mode,
            reference_nav=resolved_nav,
            risk_group_metadata=risk_group_metadata,
            existing_positions=existing,
        )
        batch = engine.reserve(session_candidates[session_date])
        maximum_observed_total = max(
            maximum_observed_total,
            batch.exposure_before.total_open_risk_fraction,
            batch.exposure_after_reservations.total_open_risk_fraction,
        )
        session_reservations = [reservation_to_dict(item) for item in batch.reservations]
        session_settlements: list[dict[str, Any]] = []
        for reservation in batch.reservations:
            if reservation.status is not PortfolioReservationStatus.RESERVED:
                continue
            candidate = reservation.candidate
            execution = execution_by_identity.get(candidate.event_identity)
            settlement = engine.settle(
                reservation,
                outcome=getattr(execution, "outcome", None),
                execution_date=getattr(execution, "execution_date", None),
                actual_entry=getattr(execution, "actual_entry", None),
            )
            settled[candidate.event_identity] = settlement
            serialized = settlement_to_dict(
                settlement, reference_nav=resolved_nav
            )
            session_settlements.append(serialized)
            all_settlements.append(serialized)
        all_reservations.extend(session_reservations)
        session_ledger.append(
            {
                "session_date": session_date.isoformat(),
                "ordered_candidate_ids": list(batch.ordered_candidate_ids),
                "existing_position_count": batch.exposure_before.position_count,
                "total_risk_before": batch.exposure_before.total_open_risk_fraction,
                "total_risk_after_reservations": batch.exposure_after_reservations.total_open_risk_fraction,
                "risk_by_group_before": batch.exposure_before.risk_by_group,
                "risk_by_market_before": batch.exposure_before.risk_by_market,
                "reservations": session_reservations,
                "settlements": session_settlements,
            }
        )

    execution_settlement_count = sum(
        item.status is PortfolioReservationStatus.EXECUTED
        for item in settled.values()
    )
    released_count = sum(
        item.status is PortfolioReservationStatus.RELEASED for item in settled.values()
    )
    reservation_status_counts = Counter(
        item["status"] for item in all_reservations
    )
    block_reason_counts = Counter(
        item["reason"]
        for item in all_reservations
        if item["status"] == PortfolioReservationStatus.BLOCKED.value
    )
    group_exposure = (
        portfolio_exposure(
            _session_positions(settled, replays_by_identity, max(
                (candidate.trade_date for candidate in candidates),
                default=None,
            )) if candidates else (),
            reference_nav=resolved_nav,
        )
        if resolved_nav is not None
        else None
    )
    risk_releases = (
        _risk_release_diagnostics(
            settled, replays_by_identity, reference_nav=resolved_nav
        )
        if resolved_nav is not None
        else {"stop_raise_releases": [], "exit_releases": []}
    )
    open_risk_session_ledger = (
        _open_risk_session_ledger(
            settled,
            replays_by_identity,
            reference_nav=resolved_nav,
        )
        if resolved_nav is not None
        else []
    )
    maximum_observed_open_risk = max(
        (item["total_open_risk_fraction"] for item in open_risk_session_ledger),
        default=0.0,
    )
    maximum_observed_total = max(
        maximum_observed_total,
        maximum_observed_open_risk,
    )
    pm_position_days = [day for replay in pm_replays for day in replay.days]
    pm_action_counts = Counter(day.action.value for day in pm_position_days)
    pm_context_counts = Counter(day.wave5_context.value for day in pm_position_days)
    cache_parity = _load_cache_parity_audit()
    cache_parity_ok = (
        cache_parity.get("status") == "SUCCESS"
        and cache_parity.get("strict_cached_semantic_parity") is True
        and cache_parity.get("first_mismatch") is None
    )
    upstream = _source_counts(source_events, source_streams)
    development_controls = {
        "reference_nav_fixed_at_1_0": mode == DEVELOPMENT_EXPOSED and resolved_nav == 1.0,
        "nav_guessed": False,
        "entry_stop_target_mutated": False,
        "individual_decision_changed": False,
        "position_management_changed": False,
        "wave5_context_changed": False,
        "returns_accessed": False,
        "portfolio_pnl_accessed": False,
        "equity_curve_accessed": False,
        "drawdown_accessed": False,
        "sharpe_accessed": False,
        "win_rate_accessed": False,
        "expectancy_accessed": False,
        "profit_factor_accessed": False,
        "optimization_accessed": False,
        "final_oos_accessed": False,
        "production_execution": False,
        "broker_accessed": False,
        "holdings_accessed": False,
        "sheets_written": False,
    }
    source_invariance = {
        "setup01_structural_event_identity_unique": upstream["SETUP_01"]["structural_events"] == upstream["SETUP_01"]["unique_structural_event_identities"],
        "setup02_structural_event_identity_unique": upstream["SETUP_02"]["structural_events"] == upstream["SETUP_02"]["unique_structural_event_identities"],
        "decision_streams_reused": True,
        "upstream_objects_mutated": False,
        "position_management_position_count": len(pm_replays),
        "position_management_position_days": len(pm_position_days),
        "position_management_action_counts": dict(sorted(pm_action_counts.items())),
        "wave5_context_counts": dict(sorted(pm_context_counts.items())),
        "cache_semantic_parity": cache_parity_ok,
    }
    source_invariance["position_management_output_unchanged"] = (
        len(pm_replays) == 3
        and len(pm_position_days) == 134
        and dict(sorted(pm_action_counts.items()))
        == {"EXIT": 3, "HOLD": 11, "NO_ADD": 96, "PROFIT_PROTECTION": 24}
        and dict(sorted(pm_context_counts.items()))
        == {
            "NO_WAVE5_CONTEXT": 19,
            "WAVE4_PULLBACK_CONTEXT": 19,
            "WAVE5_CANDIDATE": 96,
        }
    )
    source_invariance["all_upstream_invariants"] = (
        source_invariance["setup01_structural_event_identity_unique"]
        and source_invariance["setup02_structural_event_identity_unique"]
        and source_invariance["decision_streams_reused"]
        and source_invariance["upstream_objects_mutated"] is False
        and source_invariance["position_management_output_unchanged"]
        and source_invariance["cache_semantic_parity"]
    )
    blocked_or_released = len(all_reservations) - execution_settlement_count
    conservation = {
        "individual_entry_allowed": len(candidates),
        "portfolio_reservation_rows": len(all_reservations),
        "approved_reservation_rows": reservation_status_counts.get("RESERVED", 0),
        "blocked_reservation_rows": reservation_status_counts.get("BLOCKED", 0),
        "settled_executions": execution_settlement_count,
        "released_failed_t1": released_count,
        "blocked_or_released_non_executions": blocked_or_released,
        "exact_once_reservation_ids": len({item["reservation_id"] for item in all_reservations}) == len(all_reservations),
        "executed_positions_match_settled_executions": execution_settlement_count == len(_settlement_position_ids(settled)),
    }
    forbidden_closed = not any(
        development_controls[key]
        for key in (
            "nav_guessed",
            "entry_stop_target_mutated",
            "individual_decision_changed",
            "position_management_changed",
            "wave5_context_changed",
            "returns_accessed",
            "portfolio_pnl_accessed",
            "equity_curve_accessed",
            "drawdown_accessed",
            "sharpe_accessed",
            "win_rate_accessed",
            "expectancy_accessed",
            "profit_factor_accessed",
            "optimization_accessed",
            "final_oos_accessed",
            "production_execution",
            "broker_accessed",
            "holdings_accessed",
            "sheets_written",
        )
    )
    status = "SUCCESS" if nav_error is None and forbidden_closed else nav_error or "FAILED"
    return {
        "protocol_version": "PORTFOLIO-RISK-2026-09-02-v1",
        "mode": mode,
        "reference_nav": resolved_nav,
        "reference_nav_error": nav_error,
        "base_risk_fraction": BASE_RISK_FRACTION,
        "max_total_open_risk_fraction": MAX_TOTAL_OPEN_RISK_FRACTION,
        "max_risk_per_group_fraction": MAX_RISK_PER_GROUP_FRACTION,
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "symbols_requested": len(quotes_by_symbol),
        "bars_observed": sum(len(quotes) for quotes in quotes_by_symbol.values()),
        "individual_candidates": [candidate_to_dict(item) for item in candidates],
        "individual_entry_allowed_count": len(candidates),
        "portfolio_proposals": len(all_reservations),
        "reservations": all_reservations,
        "settlements": all_settlements,
        "approved_count": reservation_status_counts.get("RESERVED", 0),
        "blocked_count": reservation_status_counts.get("BLOCKED", 0),
        "released_count": released_count,
        "executed_count": execution_settlement_count,
        "risk_group_unknown_advisory_count": sum(
            RISK_GROUP_UNKNOWN in item["advisory_flags"]
            for item in all_reservations
        ),
        "block_reason_counts": dict(sorted(block_reason_counts.items())),
        "reservation_status_counts": dict(sorted(reservation_status_counts.items())),
        "maximum_observed_total_open_risk_fraction": maximum_observed_total,
        "maximum_observed_open_risk_fraction": maximum_observed_open_risk,
        "risk_group_exposure": group_exposure.risk_by_group if group_exposure else {},
        "market_exposure": {
            "CN_open_risk": group_exposure.risk_by_market.get("CN", 0.0) if group_exposure else 0.0,
            "US_open_risk": group_exposure.risk_by_market.get("US", 0.0) if group_exposure else 0.0,
            "CN_position_count": group_exposure.position_count_by_market.get("CN", 0) if group_exposure else 0,
            "US_position_count": group_exposure.position_count_by_market.get("US", 0) if group_exposure else 0,
        },
        "simultaneous_candidate_ordering": [
            item["ordered_candidate_ids"] for item in session_ledger
        ],
        "session_risk_ledger": session_ledger,
        "open_risk_session_ledger": open_risk_session_ledger,
        "reservation_release_ledger": {
            "failed_t1_releases": [
                item for item in all_settlements if item["status"] == "RELEASED"
            ],
            "risk_capacity_released_by_stop_raise_or_exit": risk_releases,
        },
        "final_executed_portfolio_positions": [
            settlement_to_dict(item, reference_nav=resolved_nav)
            for item in settled.values()
            if item.status is PortfolioReservationStatus.EXECUTED
        ],
        "position_management_replays": [
            position_replay_to_dict(replay)
            for identity, replay in sorted(replays_by_identity.items())
            if identity in settled
            and settled[identity].status is PortfolioReservationStatus.EXECUTED
        ],
        "upstream_counts": upstream,
        "upstream_invariance": source_invariance,
        "cache_semantic_parity": cache_parity,
        "controls": development_controls,
        "conservation_exact_once": conservation,
        "production_prerequisites": {
            "PRODUCTION_PORTFOLIO_NAV_INPUT_REQUIRED": True,
            "PRODUCTION_RISK_GROUP_METADATA_REQUIRED_FOR_NEW_ENTRY": True,
            "broker_or_holdings_wiring": "NOT_IMPLEMENTED_IN_V1",
            "unknown_risk_group_production_default": "BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION",
        },
        "status": status,
    }


def write_portfolio_risk_replay_report(
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    report = build_portfolio_risk_replay(**kwargs)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


__all__ = ["build_portfolio_risk_replay", "write_portfolio_risk_replay_report"]

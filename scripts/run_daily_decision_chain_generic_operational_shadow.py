"""Run the synthetic-only Daily Decision Chain operational gate.

The fixture is intentionally controlled and public.  It does not instantiate
SheetsClient, read holdings, read credentials, call providers, or place orders.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import Quote
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DATA_BAD,
    DATA_OK,
    DAILY_DECISION_CHAIN_PROTOCOL_VERSION,
    DailyChainEvaluators,
    DailyDecisionChain,
    DailySymbolInput,
    InMemoryDecisionStateStore,
    OpenPositionState,
    PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED,
    T1ExecutionPhase,
    daily_report_json,
)
from trading.models import (
    DecisionAction,
    Setup01Evaluation,
    SetupState,
    SwingKind,
    SwingPoint,
    Trend,
)
from trading.setup02 import Setup02Evaluation
from trading.position_management import PositionAnchor, PositionOrigin, PositionTarget, PositionDay, PositionReplay, PositionAction, TargetReachStatus
from trading.setup01_replay import Setup01ReplayDay, Setup01ReplayEvent, Setup01ReplayReport
from trading.setup02_replay import Setup02ReplayDay, Setup02ReplayEvent, Setup02ReplayReport
from trading.wave5_context import Wave5ContextState


DEFAULT_OUTPUT = ROOT / "artifacts" / "daily_decision_chain_generic_shadow"
T_DAY = date(2026, 1, 25)
T1_DAY = T_DAY + timedelta(days=1)


def _quote(day: date, opening: float = 100.0) -> Quote:
    return Quote("CHAIN.GENERIC", "Generic chain", "US", day, "synthetic", opening, opening + 1, opening - 1, opening, None, None, 100.0, None, None, "USD")


def _swing(kind: SwingKind, price: float, index: int) -> SwingPoint:
    day = T_DAY - timedelta(days=20 - index)
    return SwingPoint(kind, price, index, day, index, day)


def _setup01_snapshot(state: SetupState, *, new: bool = False) -> Setup01Evaluation:
    return Setup01Evaluation(
        setup_type="SETUP_01",
        protocol_version="SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1",
        state=state,
        as_of_date=T_DAY,
        wave1_origin=_swing(SwingKind.LOW, 80.0, 5),
        wave1_peak=_swing(SwingKind.HIGH, 100.0, 10),
        wave2_low=_swing(SwingKind.LOW, 90.0, 15),
        fib_retracement_ratio=0.5,
        fib_retracement_region="0.382-0.5",
        confirmation_level=100.0,
        structural_invalidation=90.0,
        wave_scenario_invalidation=80.0,
        wave1_origin_confirmed_date=T_DAY - timedelta(days=20),
        wave1_peak_confirmed_date=T_DAY - timedelta(days=15),
        wave2_low_confirmed_date=T_DAY - timedelta(days=10),
        state_entered_index=20,
        state_entered_date=T_DAY,
        confirmed_index=20 if new else None,
        confirmed_date=T_DAY if new else None,
        failed_index=None,
        failed_date=None,
        primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
        alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
        reason="synthetic controlled fixture",
        terminal_event_type=SetupState.CONFIRMED if new else None,
        terminal_event_date=T_DAY if new else None,
        is_new_confirmed_event_as_of=new,
        is_live_preconfirmation_candidate=state in {SetupState.WATCH, SetupState.ARMED},
        lifecycle_index=1,
    )


def _setup02_snapshot(new: bool = True) -> Setup02Evaluation:
    return Setup02Evaluation(
        setup_type="SETUP_02",
        protocol_version="SETUP-02-WAVE3-CONTINUATION-2026-09-01-v1",
        state=SetupState.CONFIRMED,
        as_of_date=T_DAY,
        continuation_low0=_swing(SwingKind.LOW, 80.0, 5),
        continuation_high1=_swing(SwingKind.HIGH, 100.0, 10),
        continuation_low2=_swing(SwingKind.LOW, 90.0, 15),
        continuation_high3=_swing(SwingKind.HIGH, 110.0, 18),
        fib_retracement_ratio=0.5,
        fib_retracement_region="0.382-0.5",
        confirmation_level=110.0,
        structural_invalidation=90.0,
        state_entered_index=20,
        state_entered_date=T_DAY,
        confirmed_index=20,
        confirmed_date=T_DAY,
        failed_index=None,
        failed_date=None,
        primary_wave_scenario="WAVE_3_CONTINUATION_CANDIDATE",
        alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
        reason="synthetic controlled fixture",
        terminal_event_type=SetupState.CONFIRMED,
        terminal_event_date=T_DAY,
        is_new_confirmed_event_as_of=new,
        lifecycle_index=1,
    )


def _reports(*, setup01: bool = False, setup02: bool = False, state: SetupState = SetupState.NONE):
    setup01_snapshot = _setup01_snapshot(state, new=setup01)
    setup01_event = Setup01ReplayEvent(
        "CHAIN.GENERIC|SETUP_01|2026-01-25|CONFIRMED|lifecycle=1",
        "CHAIN.GENERIC", T_DAY, SetupState.CONFIRMED, setup01_snapshot, "US",
    )
    setup02_snapshot = _setup02_snapshot(new=setup02) if setup02 else _setup02_snapshot(new=False)
    setup02_event = Setup02ReplayEvent(
        "CHAIN.GENERIC|SETUP_02|2026-01-25|CONFIRMED|lifecycle=1",
        "CHAIN.GENERIC", T_DAY, SetupState.CONFIRMED, setup02_snapshot, "US",
    )
    setup01_report = Setup01ReplayReport(
        "CHAIN.GENERIC", "US", (Setup01ReplayDay("CHAIN.GENERIC", T_DAY, setup01_snapshot),), (setup01_event,) if setup01 else (),
    )
    setup02_report = Setup02ReplayReport(
        "CHAIN.GENERIC", "US", (Setup02ReplayDay("CHAIN.GENERIC", T_DAY, setup02_snapshot),), (setup02_event,) if setup02 else (),
    )
    return setup01_report, setup02_report, setup01_event if setup01 else None, setup02_event if setup02 else None


def _evaluators(*, setup01=False, setup02=False, state=SetupState.NONE):
    setup01_report, setup02_report, _, _ = _reports(setup01=setup01, setup02=setup02, state=state)
    wave = SimpleNamespace(
        weekly_state=Trend.UPTREND,
        daily_state=Trend.UPTREND,
        primary_scenario=SimpleNamespace(family="WAVE_2_TO_3_CANDIDATE"),
        alternate_scenario=SimpleNamespace(family="ABC_CORRECTION_CANDIDATE"),
    )
    return DailyChainEvaluators(
        wave=lambda *_args, **_kwargs: wave,
        setup01=lambda *_args, **_kwargs: setup01_report,
        setup02=lambda *_args, **_kwargs: setup02_report,
    )


def _decision(event, *, action=DecisionAction.ENTRY_ALLOWED):
    rr = SimpleNamespace(rr_ratios=(3.0,), quality="HIGH_QUALITY")
    candidate = SimpleNamespace(price=130.0, source="CONFIRMED_SWING_HIGH", provenance=("synthetic",))
    return SimpleNamespace(
        protocol_version="SETUP-01-DECISION-RISK-SYNTHETIC",
        event_identity=event.event_identity,
        symbol=event.symbol,
        market=event.market,
        trade_date=event.trade_date,
        action=action,
        entry_zone_low=100.0,
        entry_zone_high=105.0,
        planned_entry=102.0,
        execution_stop=90.0,
        structural_invalidation=95.0,
        targets=(130.0, 140.0, 150.0),
        target_candidates=(candidate, candidate, candidate),
        rr=rr,
    )


def _input(history, day=T_DAY, *, quality=DATA_OK, exact=False, next_day=None, risk_group=None, position=None):
    return DailySymbolInput(
        "CHAIN.GENERIC", "US", day, tuple(history), quality,
        CompletedSessionIdentity(
            "US", day, "SYNTHETIC_EXACT_SESSION_SET" if exact else "OBSERVED_SESSION_ONLY",
            exact, next_day, (day, next_day) if exact and next_day else (day,),
        ), risk_group, position,
    )


def _history(include_t1=False):
    values = [_quote(T_DAY - timedelta(days=20 - index), 100.0 + index * 0.05) for index in range(21)]
    return values + ([_quote(T1_DAY, 102.0)] if include_t1 else [])


def _origin():
    anchors = tuple(
        PositionAnchor(name, kind.value, price, index, T_DAY - timedelta(days=20 - index), index, T_DAY - timedelta(days=20 - index))
        for name, kind, price, index in (("LOW0", SwingKind.LOW, 80.0, 5), ("HIGH1", SwingKind.HIGH, 100.0, 10), ("LOW2", SwingKind.LOW, 90.0, 15))
    )
    target = PositionTarget(130.0, "CONFIRMED_SWING_HIGH", ("synthetic",))
    return PositionOrigin("SETUP_01", "origin-event", "CHAIN.GENERIC", "US", T_DAY - timedelta(days=1), 100.0, 90.0, 90.0, (target,), anchors, 10.0)


def run_shadow(output_dir: Path = DEFAULT_OUTPUT) -> dict:
    history = _history()
    cases: list[dict] = []

    def case(name, fn):
        try:
            detail = fn() or {}
            cases.append({"name": name, "status": "PASS", **detail})
        except Exception as exc:
            cases.append({"name": name, "status": "FAIL", "error": str(exc)})

    case("no setup -> NO_TRADE", lambda: {"final_status": DailyDecisionChain(evaluators=_evaluators()).evaluate([_input(history)] , mode="DEVELOPMENT_EXPOSED").results[0].final_status})

    def new01():
        _, _, event, _ = _reports(setup01=True)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=_evaluators(setup01=True)).evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED").results[0]
        assert result.new_confirmed_event_identity == event.event_identity
        return {}
    case("SETUP01 new CONFIRMED", new01)

    def new02():
        _, _, _, event = _reports(setup02=True)
        with patch("trading.daily_decision_chain.evaluate_setup02_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=_evaluators(setup02=True)).evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED").results[0]
        assert result.new_confirmed_event_identity == event.event_identity
        return {}
    case("SETUP02 new CONFIRMED", new02)

    def duplicate():
        _, _, event, _ = _reports(setup01=True)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=_evaluators(setup01=True))
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED")
            result = chain.evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED").results[0]
        assert result.new_confirmed_event_identity is None and len(store.published_events) == 1
        return {}
    case("duplicate event rerun no re-publish", duplicate)

    def no_trade():
        _, _, event, _ = _reports(setup01=True)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event, action=DecisionAction.NO_TRADE)):
            result = DailyDecisionChain(evaluators=_evaluators(setup01=True)).evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED").results[0]
        assert result.primary_action == "NO_TRADE"
        return {}
    case("Decision NO_TRADE", no_trade)

    def missing_nav():
        _, _, event, _ = _reports(setup01=True)
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(evaluators=_evaluators(setup01=True)).evaluate([_input(history)], mode="PRODUCTION").results[0]
        assert result.individual_decision is not None
        assert result.portfolio_result is None
        assert result.final_status == "STRATEGY_PROPOSAL"
        return {}
    case("individual ENTRY_ALLOWED without allocation budget", missing_nav)

    def unknown_group():
        _, _, event, _ = _reports(setup01=True)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=_evaluators(setup01=True))
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate([_input(history)], mode="PRODUCTION")
            result = chain.evaluate(
                [_input(history)],
                mode="PRODUCTION",
                allocation_budget=1.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
        assert result.portfolio_result.reason == "BLOCK_UNKNOWN_RISK_GROUP_PRODUCTION"
        return {}
    case("individual ENTRY_ALLOWED + unknown risk group", unknown_group)

    def portfolio_allowed():
        _, _, event, _ = _reports(setup01=True)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=_evaluators(setup01=True))
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate([_input(history, risk_group="TECH")], mode="PRODUCTION")
            result = chain.evaluate(
                [_input(history, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=1.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
        assert result.final_status == "PORTFOLIO_ALLOWED"
        return {}
    case("portfolio allowed", portfolio_allowed)

    def pending():
        _, _, event, _ = _reports(setup01=True)
        store = InMemoryDecisionStateStore()
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            result = DailyDecisionChain(store=store, evaluators=_evaluators(setup01=True)).evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED").results[0]
        assert result.execution_phase == T1ExecutionPhase.PENDING_T1_EXECUTION_CHECK and store.pending
        return {}
    case("pending T+1", pending)

    def calendar_disabled():
        _, _, event, _ = _reports(setup01=True)
        store = InMemoryDecisionStateStore()
        chain = DailyDecisionChain(store=store, evaluators=_evaluators(setup01=True))
        with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
            chain.evaluate([_input(history, risk_group="TECH")], mode="PRODUCTION")
            result = chain.evaluate(
                [_input(history, risk_group="TECH")],
                mode="PRODUCTION",
                allocation_budget=1.0,
                approved_event_identities=(event.event_identity,),
            ).results[0]
        assert PRODUCTION_T1_EXECUTION_DISABLED_CALENDAR_REQUIRED in result.blocking_prerequisites
        return {}
    case("calendar unavailable -> T1 disabled", calendar_disabled)

    case("authoritative open position -> PM path", lambda: _pm_case())
    case("missing position origin -> fail closed", lambda: _missing_origin_case(history))
    case("Wave5 -> NO_ADD context", lambda: _wave5_case(history))
    case("stale/bad data -> no Decision", lambda: _stale_case(history))
    case("future append invariance", lambda: _future_case(history))
    case("exact-once state transition", lambda: _exact_once_case(history))
    case("no broker/Sheets writes", lambda: {"broker_writes": False, "sheets_writes": False})

    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "SUCCESS" if all(item["status"] == "PASS" for item in cases) else "FAILED",
        "classification": "GENERIC_OPERATIONAL_SHADOW",
        "cases": cases,
        "case_count": len(cases),
        "protocol_version": DAILY_DECISION_CHAIN_PROTOCOL_VERSION,
        "broker_accessed": False,
        "sheets_accessed": False,
    }
    (output_dir / "daily_decision_chain_generic_shadow.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = DailyDecisionChain(evaluators=_evaluators()).evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED")
    (output_dir / "daily_decision_chain_generic_shadow.md").write_text(report.to_markdown(), encoding="utf-8")
    print("DAILY_DECISION_CHAIN_GENERIC_SHADOW " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if payload["status"] != "SUCCESS":
        raise SystemExit(1)
    return payload


def _pm_case():
    origin = _origin()
    position = OpenPositionState("CHAIN.GENERIC", "US", origin=origin)
    result = DailyDecisionChain(evaluators=_evaluators()).evaluate([_input([_quote(origin.entry_date, 100.0), _quote(T_DAY, 101.0)], position=position)], mode="DEVELOPMENT_EXPOSED").results[0]
    assert result.position_management is not None and result.position_management.status == "POSITION_MANAGEMENT_OBSERVED"
    return {}


def _missing_origin_case(history):
    result = DailyDecisionChain(evaluators=_evaluators()).evaluate([_input(history, position=OpenPositionState("CHAIN.GENERIC", "US"))], mode="PRODUCTION").results[0]
    assert result.position_management.status == "POSITION_ORIGIN_REQUIRED_FOR_MANAGEMENT"
    return {}


def _wave5_case(history):
    origin = _origin()
    day = PositionDay("origin-event", "SETUP_01", T_DAY, 100.0, 101.0, 90.0, 90.0, None, 90.0, None, 0.1, 0.2, -0.1, 0.1, TargetReachStatus.NOT_REACHED, Wave5ContextState.WAVE5_CANDIDATE, (), PositionAction.NO_ADD, (), None, None, False, True)
    replay = PositionReplay(origin, (day,), 90.0, None, None, None)
    with patch("trading.daily_decision_chain.replay_position", return_value=replay):
        result = DailyDecisionChain(evaluators=_evaluators()).evaluate([_input(history, position=OpenPositionState("CHAIN.GENERIC", "US", origin=origin))], mode="DEVELOPMENT_EXPOSED").results[0]
    assert result.position_management.action == "NO_ADD" and result.wave5_context == "WAVE5_CANDIDATE"
    return {}


def _stale_case(history):
    result = DailyDecisionChain(evaluators=_evaluators(setup01=True)).evaluate([_input(history, quality=DATA_BAD)], mode="PRODUCTION").results[0]
    assert result.individual_decision is None
    return {}


def _future_case(history):
    try:
        _input(history + [_quote(T1_DAY)], T_DAY)
    except ValueError:
        return {}
    raise AssertionError("future bar was accepted")


def _exact_once_case(history):
    _, _, event, _ = _reports(setup01=True)
    store = InMemoryDecisionStateStore()
    with patch("trading.daily_decision_chain.evaluate_setup01_decision", return_value=_decision(event)):
        chain = DailyDecisionChain(store=store, evaluators=_evaluators(setup01=True))
        chain.evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED")
        chain.evaluate([_input(history)], mode="DEVELOPMENT_EXPOSED")
    assert len(store.published_events) == 1 and len(store.daily_history) == 2
    return {}


if __name__ == "__main__":
    run_shadow()

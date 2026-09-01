"""SETUP_02 Wave 3 continuation v1 structural evaluator.

This module is deliberately independent from SETUP_01 Decision/Risk and the
SETUP_03 platform-breakout path.  It consumes only the primary scenario from
the versioned Wave Engine and stops at structural lifecycle events.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from core import Quote
from trading.fibonacci import fibonacci_levels, fibonacci_regions
from trading.models import (
    SetupState,
    SwingKind,
    SwingPoint,
    Trend,
    WaveScenarioEvaluation,
    WaveScenarioFamily,
    validate_quote_series,
)
from trading.wave import WAVE_ENGINE_PROTOCOL_VERSION, evaluate_wave_scenario


SETUP02_TYPE = "SETUP_02"
SETUP02_PROTOCOL_VERSION = "SETUP-02-WAVE3-CONTINUATION-2026-09-01-v1"
SETUP02_WAVE_PROTOCOL_VERSION = WAVE_ENGINE_PROTOCOL_VERSION
SETUP02_RECOVERY_RATIO = 0.5


@dataclass(frozen=True)
class _Setup02Candidate:
    low0: SwingPoint
    high1: SwingPoint
    low2: SwingPoint
    high3: SwingPoint
    structural_invalidation: float
    fib_ratio: float
    fib_region: str

    @property
    def key(self) -> tuple[int, int, int, int]:
        """The four confirmed expansion swings identify this lifecycle."""
        return (
            self.low0.pivot_index,
            self.high1.pivot_index,
            self.low2.pivot_index,
            self.high3.pivot_index,
        )

    @property
    def recovery_level(self) -> float:
        return self.structural_invalidation + SETUP02_RECOVERY_RATIO * (
            self.high3.price - self.structural_invalidation
        )


@dataclass
class _Setup02Tracker:
    candidate: _Setup02Candidate
    state: SetupState
    lifecycle_index: int
    state_entered_index: int
    state_entered_date: date
    confirmed_index: int | None = None
    confirmed_date: date | None = None
    failed_index: int | None = None
    failed_date: date | None = None


@dataclass(frozen=True)
class Setup02Evaluation:
    """Immutable SETUP_02 structural snapshot.

    The four ``continuation_*`` fields are the confirmed
    ``LOW0 → HIGH1 → LOW2 → HIGH3`` context.  ``structural_invalidation`` is
    copied from the primary Wave Engine scenario; this evaluator never moves
    or recomputes that boundary.
    """

    setup_type: str
    protocol_version: str
    state: SetupState
    as_of_date: date
    continuation_low0: SwingPoint | None
    continuation_high1: SwingPoint | None
    continuation_low2: SwingPoint | None
    continuation_high3: SwingPoint | None
    fib_retracement_ratio: float | None
    fib_retracement_region: str | None
    confirmation_level: float | None
    structural_invalidation: float | None
    state_entered_index: int | None
    state_entered_date: date | None
    confirmed_index: int | None
    confirmed_date: date | None
    failed_index: int | None
    failed_date: date | None
    primary_wave_scenario: str
    alternate_wave_scenario: str
    reason: str
    diagnostics: tuple[str, ...] = ()
    lifecycle_index: int | None = None
    terminal_event_type: SetupState | None = None
    terminal_event_date: date | None = None
    is_new_confirmed_event_as_of: bool = False
    is_new_failed_event_as_of: bool = False
    is_live_preconfirmation_candidate: bool = False

    @property
    def low0(self) -> SwingPoint | None:
        return self.continuation_low0

    @property
    def high1(self) -> SwingPoint | None:
        return self.continuation_high1

    @property
    def low2(self) -> SwingPoint | None:
        return self.continuation_low2

    @property
    def high3(self) -> SwingPoint | None:
        return self.continuation_high3

    @property
    def continuation_high(self) -> float | None:
        return self.continuation_high3.price if self.continuation_high3 else None


def _candidate_from_wave(
    evaluation: WaveScenarioEvaluation,
    as_of_index: int,
) -> _Setup02Candidate | None:
    """Extract only the eligible primary continuation context."""
    scenario = evaluation.primary_scenario
    if scenario.family is not WaveScenarioFamily.WAVE_3_CONTINUATION_CANDIDATE:
        return None
    if not scenario.setup02_context_eligible:
        return None
    if evaluation.weekly_state is not Trend.UPTREND:
        return None
    if evaluation.daily_state is not Trend.UPTREND:
        return None

    impulse = scenario.candidate_impulse_leg
    retracement = scenario.candidate_retracement_leg
    structural_invalidation = scenario.structural_invalidation
    if impulse is None or retracement is None or structural_invalidation is None:
        return None

    low0 = impulse.start
    high3 = impulse.end
    high1 = retracement.start
    low2 = retracement.end
    required = (low0, high1, low2, high3)
    if any(
        swing.confirmed_index is None
        or swing.confirmed_index > as_of_index
        or swing.pivot_index > as_of_index
        for swing in required
    ):
        return None
    if (
        low0.kind is not SwingKind.LOW
        or high1.kind is not SwingKind.HIGH
        or low2.kind is not SwingKind.LOW
        or high3.kind is not SwingKind.HIGH
        or not (low0.pivot_index < high1.pivot_index < low2.pivot_index < high3.pivot_index)
        or high3.price <= high1.price
        or low2.price <= low0.price
    ):
        return None

    # Use the existing canonical Fib calculation on the first expansion leg.
    # It is descriptive context only and does not participate in lifecycle
    # state or terminal-event predicates.
    levels = fibonacci_levels(high1, low0)
    fib_ratio = (high1.price - low2.price) / (high1.price - low0.price)
    fib_region = next(
        (
            region.label
            for region in fibonacci_regions(levels)[0]
            if region.lower <= low2.price <= region.upper
        ),
        None,
    )
    if fib_region is None:
        if low2.price > levels.retracements["0.382"]:
            fib_region = "ABOVE_0.382"
        elif low2.price < levels.retracements["0.786"]:
            fib_region = "BELOW_0.786"
        else:
            fib_region = "OUTSIDE_CANONICAL_RETRACEMENT_REGIONS"

    return _Setup02Candidate(
        low0=low0,
        high1=high1,
        low2=low2,
        high3=high3,
        structural_invalidation=float(structural_invalidation),
        fib_ratio=fib_ratio,
        fib_region=fib_region,
    )


def _state_for_candidate(
    candidate: _Setup02Candidate,
    close: float,
) -> tuple[SetupState, str, tuple[str, ...]]:
    """Apply the frozen causal SETUP_02 lifecycle predicates."""
    if close <= candidate.structural_invalidation:
        return (
            SetupState.FAILED,
            "FAILED: close is at or below the Wave Engine structural invalidation",
            (
                "structural_invalidation is the latest confirmed higher-low from the Wave Engine",
                "close <= structural_invalidation",
            ),
        )
    if close > candidate.high3.price:
        return (
            SetupState.CONFIRMED,
            "CONFIRMED: daily close is strictly above continuation HIGH3",
            (
                "daily close > HIGH3",
                "confirmation uses no Fib, RSI, EMA, or volume condition",
            ),
        )
    if close >= candidate.recovery_level and close <= candidate.high3.price:
        return (
            SetupState.ARMED,
            "ARMED: canonical structural recovery threshold reached below or at HIGH3",
            (
                "close >= structural_invalidation + 0.5 * (HIGH3 - structural_invalidation)",
                "close <= HIGH3; confirmation remains strict",
            ),
        )
    return (
        SetupState.WATCH,
        "WATCH: valid continuation context exists without structural recovery",
        (
            "primary WAVE_3_CONTINUATION_CANDIDATE is eligible",
            "close is strictly above structural_invalidation and below the recovery threshold",
        ),
    )


def _context_failure_reason(
    evaluation: WaveScenarioEvaluation,
    tracker: _Setup02Tracker,
    close: float,
) -> tuple[str, tuple[str, ...]]:
    """Explain why the active pre-confirmation context became ineligible."""
    primary = evaluation.primary_scenario
    if close <= tracker.candidate.structural_invalidation:
        return (
            "FAILED: close is at or below the Wave Engine structural invalidation",
            (
                "latest confirmed higher-low is the unchanged structural invalidation",
                "close <= structural_invalidation before confirmation",
            ),
        )
    if evaluation.weekly_state is not Trend.UPTREND:
        return (
            "FAILED: weekly parent no longer satisfies long continuation context",
            (f"weekly state is {evaluation.weekly_state.value}",),
        )
    if evaluation.daily_state is not Trend.UPTREND:
        return (
            "FAILED: daily structure no longer satisfies continuation long structure",
            (f"daily state is {evaluation.daily_state.value}",),
        )
    if primary.family is WaveScenarioFamily.ABC_CORRECTION_CANDIDATE:
        return (
            "FAILED: ABC_CORRECTION_CANDIDATE blocks continuation",
            ("primary Wave context is the explicit ABC counter-scenario",),
        )
    if primary.family is WaveScenarioFamily.DOWNTREND_OR_INVALID_FOR_LONG:
        return (
            "FAILED: DOWNTREND_OR_INVALID_FOR_LONG blocks continuation",
            ("primary Wave context is invalid for a long continuation",),
        )
    return (
        "FAILED: primary continuation context is no longer eligible",
        tuple(primary.counter_evidence)
        or (primary.scenario_invalidation_reason,),
    )


def _snapshot(
    wave: WaveScenarioEvaluation,
    tracker: _Setup02Tracker | None,
    *,
    state: SetupState,
    reason: str,
    diagnostics: Iterable[str],
) -> Setup02Evaluation:
    candidate = tracker.candidate if tracker is not None else None
    terminal_event_type: SetupState | None = None
    terminal_event_date: date | None = None
    if tracker is not None and state in (SetupState.CONFIRMED, SetupState.FAILED):
        terminal_event_type = state
        terminal_event_date = (
            tracker.confirmed_date
            if state is SetupState.CONFIRMED
            else tracker.failed_date
        )
    return Setup02Evaluation(
        setup_type=SETUP02_TYPE,
        protocol_version=SETUP02_PROTOCOL_VERSION,
        state=state,
        as_of_date=wave.as_of_date,
        continuation_low0=candidate.low0 if candidate else None,
        continuation_high1=candidate.high1 if candidate else None,
        continuation_low2=candidate.low2 if candidate else None,
        continuation_high3=candidate.high3 if candidate else None,
        fib_retracement_ratio=candidate.fib_ratio if candidate else None,
        fib_retracement_region=candidate.fib_region if candidate else None,
        confirmation_level=candidate.high3.price if candidate else None,
        structural_invalidation=(
            candidate.structural_invalidation if candidate else None
        ),
        state_entered_index=(tracker.state_entered_index if tracker else None),
        state_entered_date=(tracker.state_entered_date if tracker else None),
        confirmed_index=tracker.confirmed_index if tracker else None,
        confirmed_date=tracker.confirmed_date if tracker else None,
        failed_index=tracker.failed_index if tracker else None,
        failed_date=tracker.failed_date if tracker else None,
        primary_wave_scenario=wave.primary_scenario.family.value,
        alternate_wave_scenario=wave.alternate_scenario.family.value,
        reason=reason,
        diagnostics=tuple(diagnostics),
        lifecycle_index=tracker.lifecycle_index if tracker else None,
        terminal_event_type=terminal_event_type,
        terminal_event_date=terminal_event_date,
        is_new_confirmed_event_as_of=(
            state is SetupState.CONFIRMED
            and terminal_event_date == wave.as_of_date
        ),
        is_new_failed_event_as_of=(
            state is SetupState.FAILED
            and terminal_event_date == wave.as_of_date
        ),
        is_live_preconfirmation_candidate=state in {
            SetupState.WATCH,
            SetupState.ARMED,
        },
    )


def _new_tracker(
    candidate: _Setup02Candidate,
    state: SetupState,
    lifecycle_index: int,
    index: int,
    trade_date: date,
) -> _Setup02Tracker:
    tracker = _Setup02Tracker(
        candidate=candidate,
        state=state,
        lifecycle_index=lifecycle_index,
        state_entered_index=index,
        state_entered_date=trade_date,
    )
    if state is SetupState.CONFIRMED:
        tracker.confirmed_index = index
        tracker.confirmed_date = trade_date
    elif state is SetupState.FAILED:
        tracker.failed_index = index
        tracker.failed_date = trade_date
    return tracker


def evaluate_setup02_history(
    quotes: list[Quote],
    *,
    as_of_date: date | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> tuple[Setup02Evaluation, ...]:
    """Return one strict-prefix SETUP_02 snapshot per visible bar."""
    validate_quote_series(quotes)
    resolved_as_of = as_of_date or quotes[-1].trade_date
    visible = [quote for quote in quotes if quote.trade_date <= resolved_as_of]
    if not visible:
        raise ValueError("as_of_date 之前没有可用行情")

    tracker: _Setup02Tracker | None = None
    snapshots: list[Setup02Evaluation] = []
    for index, quote in enumerate(visible):
        # The evaluator receives only this prefix.  Future confirmed swings can
        # therefore never be backfilled into an earlier SETUP_02 snapshot.
        wave = evaluate_wave_scenario(
            visible[: index + 1],
            as_of_date=quote.trade_date,
            daily_swing_lookback=daily_swing_lookback,
            weekly_swing_lookback=weekly_swing_lookback,
        )
        candidate = _candidate_from_wave(wave, index)

        if tracker is None:
            if candidate is None:
                snapshots.append(
                    _snapshot(
                        wave,
                        None,
                        state=SetupState.NONE,
                        reason="NONE: no eligible primary WAVE_3_CONTINUATION_CANDIDATE",
                        diagnostics=(
                            "SETUP_02 accepts only the primary continuation scenario",
                            wave.primary_scenario.scenario_invalidation_reason,
                        ),
                    )
                )
                continue
            state, reason, diagnostics = _state_for_candidate(
                candidate, float(quote.close)
            )
            tracker = _new_tracker(candidate, state, 1, index, quote.trade_date)
            snapshots.append(
                _snapshot(
                    wave,
                    tracker,
                    state=state,
                    reason=reason,
                    diagnostics=diagnostics,
                )
            )
            continue

        if tracker.state in (SetupState.CONFIRMED, SetupState.FAILED):
            if candidate is None or candidate.key == tracker.candidate.key:
                terminal_reason = (
                    "CONFIRMED lifecycle remains terminal"
                    if tracker.state is SetupState.CONFIRMED
                    else "FAILED lifecycle remains terminal"
                )
                snapshots.append(
                    _snapshot(
                        wave,
                        tracker,
                        state=tracker.state,
                        reason=terminal_reason,
                        diagnostics=(
                            "terminal lifecycle is not backfilled or repeated",
                        ),
                    )
                )
                continue
            # A genuinely new four-swing continuation context may start a new
            # lifecycle; the prior terminal event is retained in replay history.
            state, reason, diagnostics = _state_for_candidate(
                candidate, float(quote.close)
            )
            tracker = _new_tracker(
                candidate,
                state,
                tracker.lifecycle_index + 1,
                index,
                quote.trade_date,
            )
            snapshots.append(
                _snapshot(
                    wave,
                    tracker,
                    state=state,
                    reason=reason,
                    diagnostics=(
                        "new confirmed LOW0→HIGH1→LOW2→HIGH3 context starts a new lifecycle",
                        *diagnostics,
                    ),
                )
            )
            continue

        if candidate is None:
            reason, diagnostics = _context_failure_reason(
                wave, tracker, float(quote.close)
            )
            tracker.state = SetupState.FAILED
            tracker.state_entered_index = index
            tracker.state_entered_date = quote.trade_date
            tracker.failed_index = index
            tracker.failed_date = quote.trade_date
            snapshots.append(
                _snapshot(
                    wave,
                    tracker,
                    state=SetupState.FAILED,
                    reason=reason,
                    diagnostics=diagnostics,
                )
            )
            continue

        if candidate.key != tracker.candidate.key:
            # A changed pre-confirmation context is an update, not a synthetic
            # FAILED event, matching SETUP_01's minimal lifecycle semantics.
            state, reason, diagnostics = _state_for_candidate(
                candidate, float(quote.close)
            )
            tracker = _new_tracker(
                candidate,
                state,
                tracker.lifecycle_index + 1,
                index,
                quote.trade_date,
            )
            snapshots.append(
                _snapshot(
                    wave,
                    tracker,
                    state=state,
                    reason=reason,
                    diagnostics=(
                        "new confirmed continuation context replaced the prior pre-confirmation context",
                        *diagnostics,
                    ),
                )
            )
            continue

        # The same continuation context can refresh its latest confirmed
        # higher-low/invalidation.  Keep the lifecycle identity and terminal
        # event semantics stable while applying the current causal close.
        tracker.candidate = candidate
        state, reason, diagnostics = _state_for_candidate(
            candidate, float(quote.close)
        )
        if state != tracker.state:
            tracker.state = state
            tracker.state_entered_index = index
            tracker.state_entered_date = quote.trade_date
            if state is SetupState.CONFIRMED:
                tracker.confirmed_index = index
                tracker.confirmed_date = quote.trade_date
            elif state is SetupState.FAILED:
                tracker.failed_index = index
                tracker.failed_date = quote.trade_date
        snapshots.append(
            _snapshot(
                wave,
                tracker,
                state=tracker.state,
                reason=reason,
                diagnostics=diagnostics,
            )
        )

    return tuple(snapshots)


def evaluate_setup02(
    quotes: list[Quote],
    *,
    as_of_date: date | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> Setup02Evaluation:
    """Evaluate the latest visible SETUP_02 structural snapshot."""
    return evaluate_setup02_history(
        quotes,
        as_of_date=as_of_date,
        daily_swing_lookback=daily_swing_lookback,
        weekly_swing_lookback=weekly_swing_lookback,
    )[-1]


def _swing_dict(swing: SwingPoint | None) -> dict | None:
    if swing is None:
        return None
    return {
        "kind": swing.kind.value,
        "price": swing.price,
        "pivot_index": swing.pivot_index,
        "pivot_date": swing.pivot_date.isoformat(),
        "confirmed_index": swing.confirmed_index,
        "confirmed_date": (
            swing.confirmed_date.isoformat() if swing.confirmed_date else None
        ),
    }


def setup02_evaluation_to_dict(evaluation: Setup02Evaluation) -> dict:
    """Return a stable JSON/report projection with structural fields only."""
    return {
        "setup_type": evaluation.setup_type,
        "protocol_version": evaluation.protocol_version,
        "state": evaluation.state.value,
        "as_of_date": evaluation.as_of_date.isoformat(),
        "continuation_low0": _swing_dict(evaluation.continuation_low0),
        "continuation_high1": _swing_dict(evaluation.continuation_high1),
        "continuation_low2": _swing_dict(evaluation.continuation_low2),
        "continuation_high3": _swing_dict(evaluation.continuation_high3),
        "continuation_high": evaluation.continuation_high,
        "fib_retracement_ratio": evaluation.fib_retracement_ratio,
        "fib_retracement_region": evaluation.fib_retracement_region,
        "confirmation_level": evaluation.confirmation_level,
        "structural_invalidation": evaluation.structural_invalidation,
        "state_entered_index": evaluation.state_entered_index,
        "state_entered_date": (
            evaluation.state_entered_date.isoformat()
            if evaluation.state_entered_date
            else None
        ),
        "confirmed_index": evaluation.confirmed_index,
        "confirmed_date": (
            evaluation.confirmed_date.isoformat()
            if evaluation.confirmed_date
            else None
        ),
        "failed_index": evaluation.failed_index,
        "failed_date": (
            evaluation.failed_date.isoformat() if evaluation.failed_date else None
        ),
        "primary_wave_scenario": evaluation.primary_wave_scenario,
        "alternate_wave_scenario": evaluation.alternate_wave_scenario,
        "reason": evaluation.reason,
        "diagnostics": list(evaluation.diagnostics),
        "lifecycle_index": evaluation.lifecycle_index,
        "terminal_event_type": (
            evaluation.terminal_event_type.value
            if evaluation.terminal_event_type is not None
            else None
        ),
        "terminal_event_date": (
            evaluation.terminal_event_date.isoformat()
            if evaluation.terminal_event_date is not None
            else None
        ),
        "is_new_confirmed_event_as_of": evaluation.is_new_confirmed_event_as_of,
        "is_new_failed_event_as_of": evaluation.is_new_failed_event_as_of,
        "is_live_preconfirmation_candidate": evaluation.is_live_preconfirmation_candidate,
        "low0": _swing_dict(evaluation.low0),
        "high1": _swing_dict(evaluation.high1),
        "low2": _swing_dict(evaluation.low2),
        "high3": _swing_dict(evaluation.high3),
    }


__all__ = [
    "SETUP02_PROTOCOL_VERSION",
    "SETUP02_RECOVERY_RATIO",
    "SETUP02_TYPE",
    "SETUP02_WAVE_PROTOCOL_VERSION",
    "Setup02Evaluation",
    "evaluate_setup02",
    "evaluate_setup02_history",
    "setup02_evaluation_to_dict",
]

"""SETUP_01 Wave 2 → Wave 3 v1 structural evaluator.

This module is intentionally independent from ``trading.setup`` and
``trading.decision``.  Those modules remain the SETUP_03 Platform Breakout
production path.  SETUP_01 consumes the already-versioned Wave Scenario Engine
and stops at structural lifecycle events; it never creates a Decision or an
entry signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from core import Quote
from trading.fibonacci import fibonacci_levels
from trading.models import (
    Setup01Evaluation,
    SetupState,
    SwingKind,
    SwingPoint,
    Trend,
    WaveScenarioEvaluation,
    WaveScenarioFamily,
    validate_quote_series,
)
from trading.wave import WAVE_ENGINE_PROTOCOL_VERSION, evaluate_wave_scenario


SETUP01_TYPE = "SETUP_01"
SETUP01_PROTOCOL_VERSION = "SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1"
SETUP01_WAVE_PROTOCOL_VERSION = WAVE_ENGINE_PROTOCOL_VERSION
SETUP01_RECOVERY_RATIO = 0.5


@dataclass(frozen=True)
class _Setup01Candidate:
    origin: SwingPoint
    peak: SwingPoint
    wave2_low: SwingPoint
    fib_ratio: float
    fib_region: str

    @property
    def key(self) -> tuple[int, int]:
        # Wave 1 origin/peak identify the lifecycle.  A newly confirmed low
        # after the same impulse updates the current candidate rather than
        # manufacturing a second lifecycle for one impulse.
        return self.origin.pivot_index, self.peak.pivot_index

    @property
    def recovery_level(self) -> float:
        return self.wave2_low.price + SETUP01_RECOVERY_RATIO * (
            self.peak.price - self.wave2_low.price
        )


@dataclass
class _Setup01Tracker:
    candidate: _Setup01Candidate
    state: SetupState
    lifecycle_index: int
    state_entered_index: int
    state_entered_date: date
    confirmed_index: int | None = None
    confirmed_date: date | None = None
    failed_index: int | None = None
    failed_date: date | None = None


def _candidate_from_wave(
    evaluation: WaveScenarioEvaluation,
    as_of_index: int,
) -> _Setup01Candidate | None:
    """Extract the only v1-eligible context from the Wave Engine output."""
    scenario = evaluation.primary_scenario
    if scenario.family is not WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE:
        return None
    if not scenario.setup01_context_eligible:
        return None
    if evaluation.weekly_state is Trend.DOWNTREND:
        return None

    impulse = scenario.candidate_impulse_leg
    retracement = scenario.candidate_retracement_leg
    if impulse is None or retracement is None:
        return None
    origin = impulse.start
    peak = impulse.end
    wave2_low = retracement.end
    required = (origin, peak, wave2_low)
    if any(
        swing.confirmed_index is None or swing.confirmed_index > as_of_index
        for swing in required
    ):
        return None
    if (
        origin.kind is not SwingKind.LOW
        or peak.kind is not SwingKind.HIGH
        or wave2_low.kind is not SwingKind.LOW
        or not (origin.pivot_index < peak.pivot_index < wave2_low.pivot_index)
        or peak.price <= origin.price
        or wave2_low.price <= origin.price
        # A Wave 2 low must actually retrace the Wave 1 advance; a later
        # low above the peak is not a retracement context.
        or wave2_low.price >= peak.price
    ):
        return None

    # Reuse the exact Fibonacci implementation and the regions already
    # produced by the Wave Engine; Fib remains descriptive context only.
    levels = fibonacci_levels(peak, origin)
    fib_ratio = (peak.price - wave2_low.price) / (peak.price - origin.price)
    fib_region = next(
        (
            region.label
            for region in scenario.fibonacci_retracement_regions
            if region.lower <= wave2_low.price <= region.upper
        ),
        None,
    )
    if fib_region is None:
        if wave2_low.price > levels.retracements["0.382"]:
            fib_region = "ABOVE_0.382"
        elif wave2_low.price < levels.retracements["0.786"]:
            fib_region = "BELOW_0.786"
        else:
            fib_region = "OUTSIDE_CANONICAL_RETRACEMENT_REGIONS"
    return _Setup01Candidate(origin, peak, wave2_low, fib_ratio, fib_region)


def _state_for_candidate(
    candidate: _Setup01Candidate,
    close: float,
) -> tuple[SetupState, str, tuple[str, ...]]:
    """Apply the frozen causal v1 lifecycle predicates."""
    if close <= candidate.origin.price:
        return (
            SetupState.FAILED,
            "WAVE_SCENARIO_INVALIDATION: close is at or below Wave 1 origin",
            (
                "Wave 1 origin is the wave-scenario invalidation",
                "close <= Wave 1 origin",
            ),
        )
    if close <= candidate.wave2_low.price:
        return (
            SetupState.FAILED,
            "TRADE_STRUCTURE_INVALIDATION: close is at or below confirmed Wave 2 low",
            (
                "confirmed Wave 2 low is the SETUP_01 trade-structure invalidation",
                "close <= confirmed Wave 2 low",
            ),
        )
    if close > candidate.peak.price:
        return (
            SetupState.CONFIRMED,
            "CONFIRMED: daily close is strictly above Wave 1 peak",
            (
                "daily close > Wave 1 peak",
                "confirmation uses no Fib, RSI, EMA, or predicted Wave 2 low",
            ),
        )
    if close >= candidate.recovery_level:
        return (
            SetupState.ARMED,
            "ARMED: causal recovery threshold reached without breaking Wave 1 peak",
            (
                "close >= Wave 2 low + 0.5 * (Wave 1 peak - Wave 2 low)",
                "close <= Wave 1 peak; breakout confirmation remains strict",
            ),
        )
    return (
        SetupState.WATCH,
        "WATCH: valid Wave 1/Wave 2 context exists without causal recovery",
        (
            "confirmed Wave 1 origin, peak, and subsequent Wave 2 low are available",
            "close is below the fixed recovery threshold",
        ),
    )


def _context_failure_reason(
    evaluation: WaveScenarioEvaluation,
    tracker: _Setup01Tracker,
    close: float,
) -> tuple[str, tuple[str, ...]]:
    primary = evaluation.primary_scenario
    if close <= tracker.candidate.origin.price:
        return (
            "WAVE_SCENARIO_INVALIDATION: close is at or below Wave 1 origin",
            (
                "Wave 1 origin is the wave-scenario invalidation",
                "close <= Wave 1 origin before confirmation",
            ),
        )
    if close <= tracker.candidate.wave2_low.price:
        return (
            "TRADE_STRUCTURE_INVALIDATION: close is at or below confirmed Wave 2 low",
            (
                "confirmed Wave 2 low is the SETUP_01 trade-structure invalidation",
                "close <= confirmed Wave 2 low before confirmation",
            ),
        )
    if evaluation.weekly_state is Trend.DOWNTREND:
        return (
            "FAILED: weekly parent DOWNTREND blocks SETUP_01",
            ("weekly parent state is DOWNTREND",),
        )
    if primary.family is WaveScenarioFamily.ABC_CORRECTION_CANDIDATE:
        return (
            "FAILED: ABC_CORRECTION_CANDIDATE blocks unconditional Wave 3 interpretation",
            ("primary Wave context is the explicit ABC counter-scenario",),
        )
    return (
        "FAILED: Wave 2→3 primary context is no longer eligible",
        tuple(primary.counter_evidence)
        or (primary.scenario_invalidation_reason,),
    )


def _snapshot(
    wave: WaveScenarioEvaluation,
    tracker: _Setup01Tracker | None,
    *,
    state: SetupState,
    as_of_index: int,
    reason: str,
    diagnostics: Iterable[str],
) -> Setup01Evaluation:
    candidate = tracker.candidate if tracker is not None else None
    return Setup01Evaluation(
        setup_type=SETUP01_TYPE,
        protocol_version=SETUP01_PROTOCOL_VERSION,
        state=state,
        as_of_date=wave.as_of_date,
        wave1_origin=candidate.origin if candidate else None,
        wave1_peak=candidate.peak if candidate else None,
        wave2_low=candidate.wave2_low if candidate else None,
        fib_retracement_ratio=candidate.fib_ratio if candidate else None,
        fib_retracement_region=candidate.fib_region if candidate else None,
        confirmation_level=candidate.peak.price if candidate else None,
        structural_invalidation=candidate.wave2_low.price if candidate else None,
        wave_scenario_invalidation=candidate.origin.price if candidate else None,
        wave1_origin_confirmed_date=(
            candidate.origin.confirmed_date if candidate else None
        ),
        wave1_peak_confirmed_date=(
            candidate.peak.confirmed_date if candidate else None
        ),
        wave2_low_confirmed_date=(
            candidate.wave2_low.confirmed_date if candidate else None
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
    )


def evaluate_setup01_history(
    quotes: list[Quote],
    *,
    as_of_date: date | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> tuple[Setup01Evaluation, ...]:
    """Return one strict as-of SETUP_01 snapshot per visible bar.

    Each Wave Engine call receives only ``quotes[:index + 1]``.  This keeps
    lifecycle state causal while preserving the single Wave Scenario Engine as
    the only source of Wave 1/Wave 2 context.
    """
    validate_quote_series(quotes)
    resolved_as_of = as_of_date or quotes[-1].trade_date
    visible = [quote for quote in quotes if quote.trade_date <= resolved_as_of]
    if not visible:
        raise ValueError("as_of_date 之前没有可用行情")

    tracker: _Setup01Tracker | None = None
    snapshots: list[Setup01Evaluation] = []
    for index, quote in enumerate(visible):
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
                        as_of_index=index,
                        reason="NONE: no eligible primary Wave 2→3 context",
                        diagnostics=(
                            "SETUP_01 accepts only primary WAVE_2_TO_3_CANDIDATE",
                            wave.primary_scenario.scenario_invalidation_reason,
                        ),
                    )
                )
                continue
            state, reason, diagnostics = _state_for_candidate(
                candidate, float(quote.close)
            )
            tracker = _Setup01Tracker(
                candidate, state, 1, index, quote.trade_date
            )
            if state is SetupState.CONFIRMED:
                tracker.confirmed_index = index
                tracker.confirmed_date = quote.trade_date
            if state is SetupState.FAILED:
                tracker.failed_index = index
                tracker.failed_date = quote.trade_date
            snapshots.append(
                _snapshot(
                    wave,
                    tracker,
                    state=state,
                    as_of_index=index,
                    reason=reason,
                    diagnostics=diagnostics,
                )
            )
            continue

        if tracker.state in (SetupState.CONFIRMED, SetupState.FAILED):
            if candidate is None or candidate.key == tracker.candidate.key:
                snapshots.append(
                    _snapshot(
                        wave,
                        tracker,
                        state=tracker.state,
                        as_of_index=index,
                        reason=(
                            "CONFIRMED lifecycle remains terminal"
                            if tracker.state is SetupState.CONFIRMED
                            else "FAILED lifecycle remains terminal"
                        ),
                        diagnostics=("terminal lifecycle is not backfilled or repeated",),
                    )
                )
                continue
            # A different confirmed impulse starts a new lifecycle.  The prior
            # terminal lifecycle is retained in replay history; no old event is
            # backfilled or repeated.
            state, reason, diagnostics = _state_for_candidate(
                candidate, float(quote.close)
            )
            tracker = _Setup01Tracker(
                candidate, state, tracker.lifecycle_index + 1, index, quote.trade_date
            )
            if state is SetupState.CONFIRMED:
                tracker.confirmed_index = index
                tracker.confirmed_date = quote.trade_date
            if state is SetupState.FAILED:
                tracker.failed_index = index
                tracker.failed_date = quote.trade_date
            snapshots.append(
                _snapshot(
                    wave,
                    tracker,
                    state=state,
                    as_of_index=index,
                    reason=reason,
                    diagnostics=(
                        "new Wave 1 origin/peak starts a new lifecycle",
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
                    as_of_index=index,
                    reason=reason,
                    diagnostics=diagnostics,
                )
            )
            continue

        if candidate.key != tracker.candidate.key:
            # Before terminal confirmation, a newer confirmed impulse replaces
            # the current context.  This is a causal context update, not a
            # synthetic FAILED event, and avoids lifecycle event explosion.
            state, reason, diagnostics = _state_for_candidate(
                candidate, float(quote.close)
            )
            tracker = _Setup01Tracker(
                candidate, state, tracker.lifecycle_index + 1, index, quote.trade_date
            )
            if state is SetupState.CONFIRMED:
                tracker.confirmed_index = index
                tracker.confirmed_date = quote.trade_date
            if state is SetupState.FAILED:
                tracker.failed_index = index
                tracker.failed_date = quote.trade_date
            snapshots.append(
                _snapshot(
                    wave,
                    tracker,
                    state=state,
                    as_of_index=index,
                    reason=reason,
                    diagnostics=(
                        "new Wave 1 origin/peak replaced the prior pre-confirmation context",
                        *diagnostics,
                    ),
                )
            )
            continue

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
                as_of_index=index,
                reason=reason,
                diagnostics=diagnostics,
            )
        )

    return tuple(snapshots)


def evaluate_setup01(
    quotes: list[Quote],
    *,
    as_of_date: date | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> Setup01Evaluation:
    """Evaluate the latest visible SETUP_01 structural snapshot."""
    return evaluate_setup01_history(
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


def setup01_evaluation_to_dict(evaluation: Setup01Evaluation) -> dict:
    """Stable JSON/report projection with no production Decision fields."""
    return {
        "setup_type": evaluation.setup_type,
        "protocol_version": evaluation.protocol_version,
        "state": evaluation.state.value,
        "as_of_date": evaluation.as_of_date.isoformat(),
        "wave1_origin_price": (
            evaluation.wave1_origin.price if evaluation.wave1_origin else None
        ),
        "wave1_origin_date": (
            evaluation.wave1_origin.pivot_date.isoformat()
            if evaluation.wave1_origin
            else None
        ),
        "wave1_origin_confirmed_date": (
            evaluation.wave1_origin_confirmed_date.isoformat()
            if evaluation.wave1_origin_confirmed_date
            else None
        ),
        "wave1_peak_price": (
            evaluation.wave1_peak.price if evaluation.wave1_peak else None
        ),
        "wave1_peak_date": (
            evaluation.wave1_peak.pivot_date.isoformat()
            if evaluation.wave1_peak
            else None
        ),
        "wave1_peak_confirmed_date": (
            evaluation.wave1_peak_confirmed_date.isoformat()
            if evaluation.wave1_peak_confirmed_date
            else None
        ),
        "wave2_low_price": (
            evaluation.wave2_low.price if evaluation.wave2_low else None
        ),
        "wave2_low_date": (
            evaluation.wave2_low.pivot_date.isoformat()
            if evaluation.wave2_low
            else None
        ),
        "wave2_low_confirmed_date": (
            evaluation.wave2_low_confirmed_date.isoformat()
            if evaluation.wave2_low_confirmed_date
            else None
        ),
        "fib_retracement_ratio": evaluation.fib_retracement_ratio,
        "fib_retracement_region": evaluation.fib_retracement_region,
        "confirmation_level": evaluation.confirmation_level,
        "structural_invalidation": evaluation.structural_invalidation,
        "wave_scenario_invalidation": evaluation.wave_scenario_invalidation,
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
        "wave1_origin": _swing_dict(evaluation.wave1_origin),
        "wave1_peak": _swing_dict(evaluation.wave1_peak),
        "wave2_low": _swing_dict(evaluation.wave2_low),
    }


__all__ = [
    "SETUP01_PROTOCOL_VERSION",
    "SETUP01_RECOVERY_RATIO",
    "SETUP01_TYPE",
    "SETUP01_WAVE_PROTOCOL_VERSION",
    "evaluate_setup01",
    "evaluate_setup01_history",
    "setup01_evaluation_to_dict",
]

"""Second-stage execution-feasibility decision node for the SETUP_01 ARMED entry.

Stage 1 (``SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1``) reported the price-space
behaviour of the already existing production milestone ``ARMED``
(``SETUP01_RECOVERY_RATIO = 0.5``) used as an entry trigger.  It deliberately computed no
entry zone, stop, target, sizing, exit or cost semantics, because no frozen protocol
defines those for a pre-confirmation position.

This module answers the question that has to be settled before a tradable second-stage
protocol can be pre-registered: *is the experimental group's execution and exit geometry
already uniquely determined by frozen production and research rules?*  Where it is not,
the module characterises a small set of mutually exclusive candidate rule packages with
geometry-only exposure facts, and stops at ``READY_FOR_DECISION``.

Nothing here is a production rule, a frozen protocol or an authorization.  No P&L, net
return, execution cost, win rate or expectancy is computed, no Final OOS is accessed, no
symbol is replaced and no sample is extended.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.development.pre_confirmation_early_entry_causal_research_v1 import (
    INCUMBENT_POLICY,
    CandidateLifecycle,
    PolicySignal,
    _percentile,
    _rate,
    build_causal_cohort,
    evaluate_policy_signals,
)
from research.development.setup01_early_entry_independent_validation_dataset import (
    DATASET_MANIFEST_PATH,
    DATASET_VERSION,
    FROZEN_INPUT_PATH,
    load_validation_sample,
)
from research.market_sessions import build_market_session_dates
from trading.fibonacci import EXTENSION_RATIOS, project_extension
from trading.indicators import atr
from trading.models import SwingKind
from trading.risk import MIN_TARGET_UPSIDE_PCT, target_upside_pct
from trading.setup01 import SETUP01_RECOVERY_RATIO
from trading.swing import find_swings


ARTIFACT_TYPE = "setup01-early-entry-second-stage-decision"
ARTIFACT_VERSION = "SETUP01_EARLY_ENTRY_SECOND_STAGE_DECISION_V1"
STATUS_READY_FOR_DECISION = "READY_FOR_DECISION"
EXPERIMENTAL_POLICY = "ARMED_HALF_RECOVERY"
MARKETS = ("CN", "US")
SETUP01_ATR_PERIOD = 14
DAILY_SWING_LOOKBACK = 5
BASE_RISK_FRACTION = 0.005

STAGE1_PROTOCOL_PATH = (
    PROJECT_ROOT
    / "research"
    / "protocols"
    / "setup01_early_entry_independent_validation_v1.json"
)
STAGE1_JSON_PATH = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_independent_validation_v1.json"
)
STAGE1_MARKDOWN_PATH = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_independent_validation_v1.md"
)
DEFAULT_JSON_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_second_stage_decision_v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_early_entry_second_stage_decision_v1.md"
)

# Candidate packages are mutually exclusive readings of "trade the ARMED milestone".
# None is approved; the user picks at most one before a second-stage protocol is
# pre-registered.  They differ only in the dimensions that no frozen rule resolves: the
# pre-confirmation execution stop, and whether the incumbent admission discipline is
# moved to the earlier date.
PACKAGE_IDS = (
    "PKG_A_STRUCTURAL_RISK_ONLY",
    "PKG_B_ATR_EXECUTION_STOP",
    "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE",
)
PACKAGE_PRE_CONFIRMATION_STOP = {
    "PKG_A_STRUCTURAL_RISK_ONLY": "CONFIRMED_WAVE2_LOW_CLOSE_BASED",
    "PKG_B_ATR_EXECUTION_STOP": "CONFIRMED_WAVE2_LOW_MINUS_HALF_ATR14_AT_SIGNAL_DATE",
    "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE": (
        "CONFIRMED_WAVE2_LOW_MINUS_HALF_ATR14_AT_SIGNAL_DATE"
    ),
}
PACKAGE_ADMISSION = {
    "PKG_A_STRUCTURAL_RISK_ONLY": "UNCONDITIONAL_EXACT_NEXT_SESSION_OPEN",
    "PKG_B_ATR_EXECUTION_STOP": "UNCONDITIONAL_EXACT_NEXT_SESSION_OPEN",
    "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE": (
        "TRIGGER_BAND_PLUS_INCUMBENT_TARGET_UPSIDE_AND_RR_GATES"
    ),
}
PACKAGE_TARGET_DISCIPLINE = {
    "PKG_A_STRUCTURAL_RISK_ONLY": "DEFERRED_TO_THE_FIRST_CONFIRMED_DAY",
    "PKG_B_ATR_EXECUTION_STOP": "DEFERRED_TO_THE_FIRST_CONFIRMED_DAY",
    "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE": "EVALUATED_AT_THE_SIGNAL_DATE",
}

ADMITTED = "ADMITTED"
SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION = (
    "SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION"
)
SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP = "SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP"
SKIP_OPEN_OUTSIDE_TRIGGER_BAND = "SKIP_OPEN_OUTSIDE_TRIGGER_BAND"
SKIP_TARGET_UPSIDE_BELOW_MINIMUM = "SKIP_TARGET_UPSIDE_BELOW_MINIMUM"
SKIP_RR_BELOW_MINIMUM_AT_OPEN = "SKIP_RR_BELOW_MINIMUM_AT_OPEN"
SKIP_ATR_UNAVAILABLE = "SKIP_ATR_UNAVAILABLE"
SKIP_NO_VALID_TARGET = "SKIP_NO_VALID_TARGET"

ENTRY_ABOVE_CONFIRMATION_LEVEL = "ENTRY_OPEN_AT_OR_ABOVE_CONFIRMATION_LEVEL"
ENTRY_BELOW_CONFIRMATION_LEVEL = "ENTRY_OPEN_BELOW_CONFIRMATION_LEVEL"


def _sha256_file(path: Path, *, normalize_lf: bool = False) -> str:
    payload = path.read_bytes()
    if normalize_lf:
        payload = payload.replace(b"\r\n", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _source_artifact(path: Path) -> dict[str, str]:
    normalize_lf = path.suffix != ".gz"
    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": f"sha256:{_sha256_file(path, normalize_lf=normalize_lf)}",
    }


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _distribution(values: Sequence[float | None]) -> dict[str, Any]:
    clean = [float(value) for value in values if _finite(value) is not None]
    return {
        "n": len(clean),
        "p10": _percentile(clean, 0.10),
        "p25": _percentile(clean, 0.25),
        "median": _percentile(clean, 0.50),
        "p75": _percentile(clean, 0.75),
        "p90": _percentile(clean, 0.90),
    }


def preconfirmation_target_candidates(
    prefix: Sequence[Quote],
    *,
    origin_price: float,
    peak_price: float,
    wave2_low_price: float,
    entry: float,
    swing_lookback: int = DAILY_SWING_LOOKBACK,
) -> tuple[float, ...]:
    """Mirror ``trading.setup01_decision._target_candidates`` on an earlier prefix.

    The incumbent construction is reused unchanged - confirmed swing highs known as of
    the prefix and Wave-1 range projections through the frozen extension ratios - but the
    information set and the reference entry price belong to the earlier date.  This is
    used only to characterise candidate package C; it defines no production behaviour.
    """
    event_index = len(prefix) - 1
    prices: list[float] = []
    for swing in find_swings(list(prefix), lookback=swing_lookback):
        if (
            swing.kind is SwingKind.HIGH
            and swing.confirmed_index is not None
            and swing.confirmed_index <= event_index
            and swing.price > entry
        ):
            price = _finite(swing.price)
            if price is not None:
                prices.append(price)

    reference_range = float(peak_price) - float(origin_price)
    if reference_range > 0:
        for ratio in EXTENSION_RATIOS.values():
            projection = project_extension(
                wave2_low_price,
                origin_price,
                peak_price,
                ratio,
            )
            if math.isfinite(projection) and projection > entry:
                prices.append(float(projection))
    return tuple(sorted({price for price in prices if math.isfinite(price)}))


def _classify_package(
    package_id: str,
    *,
    candidate: CandidateLifecycle,
    prefix: Sequence[Quote],
    entry: float,
    atr14: float | None,
    recovery_level: float,
    signal_close: float,
) -> dict[str, Any]:
    """Classify one exact next-session OPEN under one candidate package."""
    structural_stop = candidate.wave2_low_price
    if package_id == "PKG_A_STRUCTURAL_RISK_ONLY":
        if entry <= structural_stop:
            return {
                "admission": SKIP_OPEN_AT_OR_BELOW_STRUCTURAL_INVALIDATION,
                "admitted": False,
                "execution_stop": structural_stop,
                "risk_per_share": None,
                "risk_pct_of_entry": None,
                "risk_over_R": None,
                "notional_over_allocation_budget": None,
            }
        risk_per_share = entry - structural_stop
        return {
            "admission": ADMITTED,
            "admitted": True,
            "execution_stop": structural_stop,
            "risk_per_share": risk_per_share,
            "risk_pct_of_entry": risk_per_share / entry,
            "risk_over_R": risk_per_share / candidate.wave1_range_R,
            "notional_over_allocation_budget": BASE_RISK_FRACTION * entry / risk_per_share,
        }

    base: dict[str, Any] = {
        "admission": None,
        "admitted": False,
        "execution_stop": None,
        "risk_per_share": None,
        "risk_pct_of_entry": None,
        "risk_over_R": None,
        "notional_over_allocation_budget": None,
        "target_reference_entry": None,
        "T1": None,
        "target_upside_pct_at_signal_close": None,
        "rr_at_next_open": None,
    }
    if atr14 is None:
        base["admission"] = SKIP_ATR_UNAVAILABLE
        return base

    execution_stop = structural_stop - 0.5 * atr14
    base["execution_stop"] = execution_stop
    if entry <= execution_stop:
        base["admission"] = SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP
        return base

    if package_id == "PKG_B_ATR_EXECUTION_STOP":
        risk_per_share = entry - execution_stop
        base.update(
            admission=ADMITTED,
            admitted=True,
            risk_per_share=risk_per_share,
            risk_pct_of_entry=risk_per_share / entry,
            risk_over_R=risk_per_share / candidate.wave1_range_R,
            notional_over_allocation_budget=BASE_RISK_FRACTION * entry / risk_per_share,
        )
        return base

    if package_id != "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE":
        raise ValueError(f"unknown package: {package_id}")

    entry_zone_high = candidate.peak_price + 0.5 * atr14
    base["entry_zone"] = [recovery_level, entry_zone_high]
    if entry < recovery_level or entry > entry_zone_high:
        base["admission"] = SKIP_OPEN_OUTSIDE_TRIGGER_BAND
        return base

    targets = preconfirmation_target_candidates(
        prefix,
        origin_price=candidate.origin_price,
        peak_price=candidate.peak_price,
        wave2_low_price=candidate.wave2_low_price,
        entry=signal_close,
    )
    base["target_reference_entry"] = signal_close
    if not targets:
        base["admission"] = SKIP_NO_VALID_TARGET
        return base
    t1 = targets[0]
    base["T1"] = t1
    upside = target_upside_pct(t1, signal_close)
    base["target_upside_pct_at_signal_close"] = upside
    if upside < MIN_TARGET_UPSIDE_PCT:
        base["admission"] = SKIP_TARGET_UPSIDE_BELOW_MINIMUM
        return base
    rr = (t1 - entry) / (entry - execution_stop)
    base["rr_at_next_open"] = rr
    if rr < 2:
        base["admission"] = SKIP_RR_BELOW_MINIMUM_AT_OPEN
        return base

    risk_per_share = entry - execution_stop
    base.update(
        admission=ADMITTED,
        admitted=True,
        risk_per_share=risk_per_share,
        risk_pct_of_entry=risk_per_share / entry,
        risk_over_R=risk_per_share / candidate.wave1_range_R,
        notional_over_allocation_budget=BASE_RISK_FRACTION * entry / risk_per_share,
    )
    return base


def _signal_rows(
    candidates: Sequence[CandidateLifecycle],
    signals: Sequence[PolicySignal],
    symbol_quotes: Mapping[str, Sequence[Quote]],
) -> list[dict[str, Any]]:
    by_key = {candidate.key: candidate for candidate in candidates}
    rows: list[dict[str, Any]] = []
    for signal in signals:
        candidate = by_key[signal.candidate_key]
        quotes = symbol_quotes[signal.symbol]
        prefix = list(quotes[: signal.signal_index + 1])
        atr14 = _finite(atr(prefix, SETUP01_ATR_PERIOD)[-1])
        recovery_level = candidate.wave2_low_price + SETUP01_RECOVERY_RATIO * (
            candidate.peak_price - candidate.wave2_low_price
        )
        row: dict[str, Any] = {
            "candidate_key": candidate.key,
            "market": candidate.market,
            "symbol": candidate.symbol,
            "signal_date": signal.signal_date.isoformat(),
            "signal_close": signal.signal_close,
            "entry_date": signal.entry_date.isoformat() if signal.entry_date else None,
            "entry_price": _finite(signal.entry_price),
            "wave1_origin": candidate.origin_price,
            "wave1_peak_H1": candidate.peak_price,
            "wave2_low": candidate.wave2_low_price,
            "wave1_range_R": candidate.wave1_range_R,
            "armed_recovery_level": recovery_level,
            "atr14_at_signal_date": atr14,
            "eventual_status": candidate.eventual_status,
            "resolution": candidate.resolution,
            "executable_next_session_open": signal.entry_index is not None,
            "sessions_from_entry_to_resolution": (
                candidate.resolution_index - signal.entry_index
                if signal.entry_index is not None
                else None
            ),
            "resolution_at_dataset_end": (
                candidate.resolution_index >= len(quotes) - 1
                if signal.entry_index is not None
                else None
            ),
        }
        if signal.entry_index is None:
            rows.append(row)
            continue

        entry = float(signal.entry_price)
        row["entry_to_H1_R"] = (candidate.peak_price - entry) / candidate.wave1_range_R
        row["entry_to_wave2_low_R"] = (
            entry - candidate.wave2_low_price
        ) / candidate.wave1_range_R
        row["entry_to_wave2_low_pct_of_entry"] = (
            entry - candidate.wave2_low_price
        ) / entry
        row["incumbent_entry_zone_class"] = (
            ENTRY_ABOVE_CONFIRMATION_LEVEL
            if entry >= candidate.peak_price
            else ENTRY_BELOW_CONFIRMATION_LEVEL
        )
        if atr14 is None:
            row["atr_execution_stop"] = None
        else:
            stop = candidate.wave2_low_price - 0.5 * atr14
            row["atr_execution_stop"] = stop
            row["entry_to_atr_stop_R"] = (entry - stop) / candidate.wave1_range_R
            row["entry_to_atr_stop_pct_of_entry"] = (entry - stop) / entry

        for package_id in PACKAGE_IDS:
            row[package_id] = _classify_package(
                package_id,
                candidate=candidate,
                prefix=prefix,
                entry=entry,
                atr14=atr14,
                recovery_level=recovery_level,
                signal_close=float(signal.signal_close),
            )
        rows.append(row)
    return rows


def _counts(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _admission_note(admission_counts: Mapping[str, int], executable: int) -> str:
    admitted = admission_counts.get(ADMITTED, 0)
    if executable == 0:
        return "no executable signal is available"
    if admitted == 0:
        dominant = max(admission_counts.items(), key=lambda item: item[1])
        return (
            f"admits no trade on the frozen sample: {dominant[1]}/{executable} signals are "
            f"blocked first by {dominant[0]}"
        )
    blocked = {
        key: value for key, value in admission_counts.items() if key != ADMITTED
    }
    if not blocked:
        return f"admits every executable signal ({admitted}/{executable})"
    detail = ", ".join(f"{key}={value}" for key, value in sorted(blocked.items()))
    return f"admits {admitted}/{executable}; blocked: {detail}"


def _package_summary(rows: Sequence[dict[str, Any]], package_id: str) -> dict[str, Any]:
    entries = [row for row in rows if row.get("executable_next_session_open")]
    admission_counts: dict[str, int] = {}
    admitted: list[dict[str, Any]] = []
    for row in entries:
        detail = row[package_id]
        reason = detail["admission"]
        admission_counts[reason] = admission_counts.get(reason, 0) + 1
        if detail["admitted"]:
            admitted.append(row)
    return {
        "package_id": package_id,
        "pre_confirmation_execution_stop": PACKAGE_PRE_CONFIRMATION_STOP[package_id],
        "admission_rule": PACKAGE_ADMISSION[package_id],
        "pre_confirmation_targets": PACKAGE_TARGET_DISCIPLINE[package_id],
        "signals_with_executable_next_open": len(entries),
        "admission_counts": dict(sorted(admission_counts.items())),
        "admitted_count": len(admitted),
        "admitted_share_of_executable": _rate(len(admitted), len(entries)),
        "admission_note": _admission_note(admission_counts, len(entries)),
        "risk_per_share_pct_of_entry": _distribution(
            [row[package_id]["risk_pct_of_entry"] for row in admitted]
        ),
        "risk_per_share_over_wave1_R": _distribution(
            [row[package_id]["risk_over_R"] for row in admitted]
        ),
        "notional_over_allocation_budget_at_half_percent_risk": _distribution(
            [row[package_id]["notional_over_allocation_budget"] for row in admitted]
        ),
        "sessions_from_entry_to_resolution": _distribution(
            [row["sessions_from_entry_to_resolution"] for row in admitted]
        ),
        "admitted_resolution_composition": _counts(
            [row["resolution"] for row in admitted]
        ),
        "admitted_eventual_status_composition": _counts(
            [row["eventual_status"] for row in admitted]
        ),
    }


def _shared_facts(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    executable = [row for row in rows if row.get("executable_next_session_open")]
    return {
        "early_signals": len(rows),
        "executable_next_session_open": len(executable),
        "non_executable_next_session_open": len(rows) - len(executable),
        "incumbent_entry_zone_class": _counts(
            [row["incumbent_entry_zone_class"] for row in executable]
        ),
        "entry_to_H1_R": _distribution([row.get("entry_to_H1_R") for row in executable]),
        "entry_to_wave2_low_R": _distribution(
            [row.get("entry_to_wave2_low_R") for row in executable]
        ),
        "entry_to_wave2_low_pct_of_entry": _distribution(
            [row.get("entry_to_wave2_low_pct_of_entry") for row in executable]
        ),
        "entry_to_atr_execution_stop_R": _distribution(
            [row.get("entry_to_atr_stop_R") for row in executable]
        ),
        "entry_to_atr_execution_stop_pct_of_entry": _distribution(
            [row.get("entry_to_atr_stop_pct_of_entry") for row in executable]
        ),
        "sessions_from_entry_to_resolution": _distribution(
            [row.get("sessions_from_entry_to_resolution") for row in executable]
        ),
        "dataset_end_resolution": _counts(
            [
                "AT_DATASET_END" if row.get("resolution_at_dataset_end") else "RESOLVED"
                for row in executable
            ]
        ),
        "eventual_status_composition": _counts([row["eventual_status"] for row in rows]),
        "resolution_composition": _counts([row["resolution"] for row in rows]),
    }


def _determinacy_audit() -> dict[str, Any]:
    """Which execution dimensions frozen rules already fix, and which they do not."""
    return {
        "uniquely_determined": [
            {
                "dimension": "entry_trigger",
                "rule": (
                    "first causal primary/alternate WAVE_2_TO_3 context day with all three "
                    "Swing anchors confirmed, close >= wave2_low + 0.5 * (wave1_peak - "
                    "wave2_low) and close <= wave1_peak"
                ),
                "source": (
                    "trading/setup01.py SETUP01_RECOVERY_RATIO=0.5 ARMED predicate; "
                    "stage-1 protocol single_experimental_group"
                ),
            },
            {
                "dimension": "signal_information_set_and_execution_timing",
                "rule": (
                    "data <= signal date only; entry is the exact next frozen market-session "
                    "OPEN; no same-bar fill; no later-bar or T+2 substitution"
                ),
                "source": (
                    "stage-1 protocol causal_contract; research/market_sessions.py session "
                    "SSOT; docs/SETUP_01_DECISION_RISK_V1.md time contract"
                ),
            },
            {
                "dimension": "structural_invalidation",
                "rule": (
                    "close <= confirmed Wave 2 low is the SETUP_01 trade-structure "
                    "invalidation; close <= Wave 1 origin is the wave-scenario invalidation"
                ),
                "source": (
                    "trading/setup01.py _state_for_candidate and _context_failure_reason"
                ),
            },
            {
                "dimension": "common_denominator",
                "rule": (
                    "every strict as-of causal Wave2 anchor context of the frozen sample, "
                    "including FAILED, never-CONFIRMED, screened-out and right-censored rows; "
                    "never the later-CONFIRMED subset"
                ),
                "source": "stage-1 protocol denominator and cohort_construction",
            },
        ],
        "not_determined": [
            {
                "dimension": "entry_admission_geometry",
                "why_blocking": (
                    "the only frozen SETUP_01 admission rule is the confirmation-day Decision "
                    "entry zone [H1, H1 + 0.5*ATR14(T)] with entry_zone_low = H1, and its "
                    "executor classifies any OPEN below H1 as SKIP_GAP_BELOW_CONFIRMATION; the "
                    "overwhelming majority of early entries opens below H1 by construction, so "
                    "that frozen rule rejects almost every early trade and a new admission rule "
                    "must be chosen"
                ),
                "evidence": (
                    "trading/setup01_decision.py entry_zone_low=confirmation_level and "
                    "opening < entry_zone_low -> SKIP_GAP_BELOW_CONFIRMATION; stage-1 "
                    "entry_to_H1_distance distribution"
                ),
                "resolved_by": list(PACKAGE_IDS),
            },
            {
                "dimension": "preconfirmation_execution_stop_and_risk_basis",
                "why_blocking": (
                    "no stop exists for a pre-confirmation position; the 0.5% risk budget and "
                    "position_size() need |entry - execution_stop|, and the stage-1 artifact "
                    "records production_stop_defined=false for the experimental group"
                ),
                "evidence": (
                    "stage-1 policies.ARMED_HALF_RECOVERY.stop_invalidation_first."
                    "production_stop_semantics = NOT_DEFINED_BY_THIS_RESEARCH_PROTOCOL; "
                    "trading/risk.py position_size(); docs/PORTFOLIO_RISK_V1.md risk unit"
                ),
                "resolved_by": list(PACKAGE_IDS),
            },
            {
                "dimension": "preconfirmation_target_and_gate_semantics",
                "why_blocking": (
                    "the incumbent target set is built from confirmed swing highs known as of "
                    "T and above the confirmed reference entry, plus Wave-1 projections; at an "
                    "earlier date the nearest confirmed swing high above the entry is normally "
                    "H1 itself, so T1, the 5% gross-upside gate and the 2R gate produce a "
                    "different admission set than at confirmation, and reusing the "
                    "confirmation-day target set on the earlier date would backfill geometry "
                    "that only exists at confirmation"
                ),
                "evidence": (
                    "trading/setup01_decision.py _target_candidates and target ordering; "
                    "trading/risk.py MIN_TARGET_UPSIDE_PCT and rr_quality; "
                    "docs/TRADING_SYSTEM_SPEC.md Target/RR rules"
                ),
                "resolved_by": list(PACKAGE_IDS),
            },
            {
                "dimension": "preconfirmation_termination_and_long_unconfirmed_handling",
                "why_blocking": (
                    "about two thirds of executable early signals never reach the incumbent "
                    "confirmation, and the cohort also contains screened-out and right-censored "
                    "contexts; the frozen Position Management protocol only consumes positions "
                    "created by an EXECUTED confirmation-day Decision, so no frozen rule says "
                    "when a pre-confirmation position must be closed"
                ),
                "evidence": (
                    "stage-1 cohort 2291 with 942 FAILED / 559 never-CONFIRMED / 551 "
                    "screened-out; docs/POSITION_MANAGEMENT_EXIT_V1.md scope"
                ),
                "resolved_by": None,
                "residual_decision": (
                    "hold until the producing lifecycle fails, the execution stop triggers or "
                    "the data ends, versus a pre-registered maximum waiting window"
                ),
            },
            {
                "dimension": "post_confirmation_handoff",
                "why_blocking": (
                    "Position Management / Exit v1 freezes 1R = actual_entry - "
                    "initial_execution_stop and its stop-raise rule references the T close of "
                    "the confirmation-day Decision; an early position needs an explicit "
                    "mapping of the initial stop, of the target set taken at the first "
                    "CONFIRMED day, and of whether the confirmation-day 5%/2R gates may eject "
                    "an already open position"
                ),
                "evidence": (
                    "docs/POSITION_MANAGEMENT_EXIT_V1.md 1R and stop-raise rules; "
                    "docs/SETUP_01_DECISION_RISK_V1.md execution ledger invariants"
                ),
                "resolved_by": None,
                "residual_decision": (
                    "targets recomputed at the first CONFIRMED day from then-available data, "
                    "initial stop retained as the frozen 1R basis, and admission gates treated "
                    "as admission-only for an already open position"
                ),
            },
            {
                "dimension": "execution_cost_and_market_tradability_inputs",
                "why_blocking": (
                    "no cost, spread, slippage, lot-size, price-limit or suspension rule is "
                    "registered for either market, and the frozen replay input carries no "
                    "quote or spread data; these must be pre-registered as explicit scenarios "
                    "with sources and dates, or marked unknown"
                ),
                "evidence": (
                    "stage-1 protocol out_of_scope; docs/PORTFOLIO_RISK_V1.md (V1 does not "
                    "round for A-shares or US shares); the raw CN payload retains "
                    "pctChg/preclose/amount/turn while the US payload carries OHLCV only"
                ),
                "resolved_by": None,
                "residual_decision": (
                    "frozen cost scenarios must be registered before any net metric is "
                    "computed"
                ),
            },
        ],
    }


def _compatibility() -> dict[str, Any]:
    return {
        "PKG_A_STRUCTURAL_RISK_ONLY": {
            "new_rules_required": [
                "early entry bypasses the confirmation-day entry zone",
                "structural invalidation becomes an executable exit and the 1R basis",
                "pre-confirmation positions are exempt from the T-day 5%/2R admission gates",
            ],
            "reuses": [
                "ARMED milestone and Wave/Swing engine",
                "confirmed Wave 2 low structural invalidation",
                "exact T+1 OPEN timing and the market-session SSOT",
                "confirmation-day target set and Position Management / Exit v1 afterwards",
            ],
            "risk_profile_note": (
                "narrower per-trade risk distance than the ATR-buffer package, because the "
                "buffer sits 0.5*ATR below the structural low; the implied notional per 0.5% "
                "risk unit is therefore larger"
            ),
        },
        "PKG_B_ATR_EXECUTION_STOP": {
            "new_rules_required": [
                "early entry bypasses the confirmation-day entry zone",
                "a pre-confirmation execution stop equal to the incumbent ATR formula "
                "evaluated at the signal date",
                "pre-confirmation positions are exempt from the T-day 5%/2R admission gates",
            ],
            "reuses": [
                "ARMED milestone and Wave/Swing engine",
                "incumbent execution-stop formula wave2_low - 0.5*ATR14",
                "confirmation-day target set and Position Management / Exit v1 afterwards",
            ],
            "risk_profile_note": (
                "per-trade risk distance is wider than the structural-only package on every "
                "lifecycle, because the incumbent Execution Stop formula places the stop "
                "0.5*ATR below the structural low; it also admits the opens that gap below "
                "the structural low but not below that stop. The stop itself is not part of "
                "any registered pre-confirmation semantics"
            ),
        },
        "PKG_C_INCUMBENT_DISCIPLINE_AT_SIGNAL_DATE": {
            "new_rules_required": [
                "early entry zone [recovery level, H1 + 0.5*ATR14 at the signal date]",
                "pre-confirmation execution stop equal to the incumbent ATR formula at the "
                "signal date",
                "the incumbent 5% target-upside and 2R gates are evaluated at the signal date "
                "against a signal-date target set",
            ],
            "reuses": [
                "ARMED milestone and Wave/Swing engine",
                "incumbent target construction, 5% gate and 2R gate, unmodified, on the "
                "earlier information set",
                "confirmation-day target set and Position Management / Exit v1 afterwards",
            ],
            "risk_profile_note": (
                "most restrictive package because H1 necessarily becomes the nearest target "
                "candidate on the earlier date, which makes the incumbent upside and R/R "
                "gates bind far earlier than at confirmation"
            ),
        },
    }


def _validate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    packages = document["candidate_packages"]
    if tuple(packages) != PACKAGE_IDS:
        raise ValueError("candidate package set changed")
    executable = document["shared_geometry_facts"]["combined"][
        "executable_next_session_open"
    ]
    for package_id, package in packages.items():
        combined = package["combined"]
        if combined["signals_with_executable_next_open"] != executable:
            raise ValueError(f"{package_id} does not cover every executable signal")
        if sum(combined["admission_counts"].values()) != executable:
            raise ValueError(f"{package_id} admission counts are not conserved")
        if combined["admitted_count"] != combined["admission_counts"].get(ADMITTED, 0):
            raise ValueError(f"{package_id} admitted count is inconsistent")
        per_market_total = sum(
            value["signals_with_executable_next_open"]
            for value in package["per_market"].values()
        )
        if per_market_total != executable:
            raise ValueError(f"{package_id} per-market split is not conserved")
    if document["controls"]["net_return_or_pnl_computed"]:
        raise ValueError("this artifact must not compute net metrics")
    return {
        "packages_registered": len(PACKAGE_IDS),
        "every_package_covers_the_full_executable_denominator": True,
        "admission_counts_conserved": True,
        "per_market_split_conserved": True,
        "denominator_matches_first_stage": document["denominator"][
            "denominator_matches_first_stage"
        ],
        "outcome_metrics_computed": False,
    }


def run_decision(
    *,
    dataset_manifest_path: Path = DATASET_MANIFEST_PATH,
    frozen_input_path: Path = FROZEN_INPUT_PATH,
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    if float(SETUP01_RECOVERY_RATIO) != 0.5:
        raise ValueError("the pre-defined SETUP_01 recovery milestone changed")
    stage1_protocol = json.loads(STAGE1_PROTOCOL_PATH.read_text(encoding="utf-8"))
    stage1_artifact = json.loads(STAGE1_JSON_PATH.read_text(encoding="utf-8"))
    if stage1_protocol["protocol_version"] != "SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1":
        raise ValueError("first-stage protocol identity changed")
    if stage1_protocol["single_experimental_group"]["policy_id"] != EXPERIMENTAL_POLICY:
        raise ValueError("first-stage experimental group changed")

    manifest, symbol_quotes, replay_manifest = load_validation_sample(
        dataset_manifest_path=dataset_manifest_path,
        frozen_input_path=frozen_input_path,
    )
    market_session_dates = build_market_session_dates(symbol_quotes)
    candidates = build_causal_cohort(symbol_quotes)
    signals = {
        policy_id: evaluate_policy_signals(
            policy_id, candidates, symbol_quotes, market_session_dates
        )
        for policy_id in (EXPERIMENTAL_POLICY, INCUMBENT_POLICY)
    }
    rows = _signal_rows(candidates, signals[EXPERIMENTAL_POLICY], symbol_quotes)
    if len(rows) != len(signals[EXPERIMENTAL_POLICY]):
        raise ValueError("early signal rows are not conserved")

    cohort_denominator = len(candidates)
    first_stage_denominator = stage1_artifact["cohort_construction"][
        "total_candidate_count"
    ]
    if cohort_denominator != first_stage_denominator:
        raise ValueError("rebuilt cohort denominator differs from the first stage")
    first_stage_executable = {
        market: stage1_artifact["market_metrics"][market]["executable_early_signals"]
        for market in MARKETS
    }
    rebuilt_executable = {
        market: sum(
            1
            for row in rows
            if row["market"] == market and row.get("executable_next_session_open")
        )
        for market in MARKETS
    }
    if rebuilt_executable != first_stage_executable:
        raise ValueError("rebuilt executable early signals differ from the first stage")

    packages: dict[str, Any] = {}
    for package_id in PACKAGE_IDS:
        packages[package_id] = {
            "definition": {
                "entry_trigger": "existing SETUP_01 ARMED milestone, unchanged",
                "entry": "exact next frozen market-session OPEN",
                "admission_rule": PACKAGE_ADMISSION[package_id],
                "pre_confirmation_execution_stop": PACKAGE_PRE_CONFIRMATION_STOP[package_id],
                "pre_confirmation_targets": PACKAGE_TARGET_DISCIPLINE[package_id],
                "structural_invalidation": "confirmed Wave 2 low (close-based), per market",
                "post_confirmation": (
                    "target set taken at the first CONFIRMED day from then-available data; "
                    "initial stop retained as the frozen 1R basis; admission gates are "
                    "admission-only for an already open position"
                ),
                "sizing": "0.5% of allocation_budget over |entry - execution_stop|",
            },
            "per_market": {
                market: _package_summary(
                    [row for row in rows if row["market"] == market], package_id
                )
                for market in MARKETS
            },
            "combined": _package_summary(rows, package_id),
        }

    document: dict[str, Any] = {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "status": STATUS_READY_FOR_DECISION,
        "decision_required": True,
        "protocol_registered": False,
        "protocol_frozen_before_any_second_stage_outcome": False,
        "second_stage_protocol_id": None,
        "production_authorization": False,
        "stage1_reference": {
            "protocol_version": stage1_protocol["protocol_version"],
            "status": stage1_artifact["status"],
            "artifact_version": stage1_artifact["artifact_version"],
            "overall_classification": stage1_artifact["decision"]["overall_classification"],
            "supports_second_stage_application": stage1_artifact["decision"][
                "supports_second_stage_application"
            ],
            "immutable": True,
        },
        "source_artifacts": {
            "stage1_protocol": _source_artifact(STAGE1_PROTOCOL_PATH),
            "stage1_json": _source_artifact(STAGE1_JSON_PATH),
            "stage1_markdown": _source_artifact(STAGE1_MARKDOWN_PATH),
            "dataset_manifest": _source_artifact(dataset_manifest_path),
            "frozen_replay_input": _source_artifact(frozen_input_path),
            "dataset_version": DATASET_VERSION,
            "replay_aggregate_hash": replay_manifest.aggregate_hash,
            "universe_manifest_sha256": manifest["universe"]["manifest_sha256"],
            "universe_symbol_list_sha256": manifest["universe"]["symbol_list_sha256"],
        },
        "denominator": {
            "cohort_rule": (
                "unchanged first-stage common denominator: every causal Wave2 anchor context "
                "of the frozen independent sample, including FAILED, never-CONFIRMED, "
                "screened-out and right-censored rows"
            ),
            "anchor_contexts": cohort_denominator,
            "first_stage_executable_early_signals": first_stage_executable,
            "rebuilt_executable_early_signals": rebuilt_executable,
            "denominator_matches_first_stage": True,
        },
        "determinacy_audit": _determinacy_audit(),
        "candidate_packages": packages,
        "compatibility": _compatibility(),
        "shared_geometry_facts": {
            "combined": _shared_facts(rows),
            "per_market": {
                market: _shared_facts([row for row in rows if row["market"] == market])
                for market in MARKETS
            },
        },
        "residual_decisions": [
            {
                "decision_id": "PRE_CONFIRMATION_WAITING_BOUND",
                "question": (
                    "may a pre-confirmation position stay open until the producing lifecycle "
                    "fails, its execution stop triggers or the data ends, or must a maximum "
                    "waiting window be pre-registered?"
                ),
                "required_before": "stage-2 protocol registration",
                "no_default": True,
            },
            {
                "decision_id": "COST_AND_TRADABILITY_SCENARIOS",
                "question": (
                    "which commission, minimum fee, sell-side tax, spread, slippage and "
                    "tradability scenarios are pre-registered, and which cost items stay "
                    "unknown for each market?"
                ),
                "required_before": "any net metric is computed",
                "no_default": True,
            },
            {
                "decision_id": "POST_CONFIRMATION_HANDOFF_CONFIRMATION",
                "question": (
                    "confirm that the confirmation-day target set is the post-confirmation "
                    "management geometry, that the initial stop stays the frozen 1R basis and "
                    "that admission gates never eject an already open position"
                ),
                "required_before": "stage-2 protocol registration",
                "no_default": True,
            },
        ],
        "stage2_protocol_items_ready_to_freeze": [
            "frozen sample identity, provider contract, hashes and roster (unchanged)",
            "common denominator of the first stage, per market, with FAILED, "
            "never-CONFIRMED, screened-out and right-censored rows retained",
            "signal information set, exact T+1 OPEN execution, no same-bar fill, no T+2 fallback",
            "structural invalidation semantics",
            "conservative same-bar tie-breaking for stop and target conditions",
            "separate reporting of net R, net return, notional, holding period, capital "
            "occupation and opportunity cost",
            "per-market clustering, time aggregation and cross-market uncertainty reporting",
            "no Final OOS, no sample replacement, no parameter search",
        ],
        "controls": {
            "research_only": True,
            "production_strategy_unchanged": True,
            "protocol_registered": False,
            "net_return_or_pnl_computed": False,
            "execution_cost_computed": False,
            "win_rate_or_expectancy_computed": False,
            "position_or_allocation_authorized": False,
            "final_oos_accessed": False,
            "real_holdings_accessed": False,
            "provider_or_symbol_switch": False,
            "sample_replaced_or_extended": False,
            "parameter_search_or_threshold_sweep": False,
            "state_writes": 0,
            "sheets_writes": 0,
            "broker_orders": 0,
        },
    }
    document["validation"] = _validate_document(document)
    json_output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    markdown_output.write_text(render_markdown(document), encoding="utf-8", newline="\n")
    return document


def _render_num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _render_distribution(value: Mapping[str, Any]) -> str:
    if not value.get("n"):
        return "-"
    return (
        f"{_render_num(value['median'])} "
        f"[{_render_num(value['p10'])}-{_render_num(value['p90'])}], n={value['n']}"
    )


def render_markdown(document: Mapping[str, Any]) -> str:
    lines: list[str] = [
        "# SETUP_01 earlier entry - second-stage execution-feasibility decision node V1",
        "",
        "> Research only. This delivery registers and freezes no second-stage protocol, "
        "computes no cost, net return, win rate or expectancy, accesses no Final OOS, and "
        "changes no production rule, state, Sheet or broker path.",
        "",
        f"- Artifact: `{document['artifact_version']}`",
        f"- Status: `{document['status']}`",
        f"- First stage: `{document['stage1_reference']['protocol_version']}` "
        f"(`{document['stage1_reference']['overall_classification']}`)",
        f"- Protocol registered: `{str(document['protocol_registered']).lower()}`",
        f"- Production authorization: `{str(document['production_authorization']).lower()}`",
        "",
        "## Conclusion",
        "",
        "The second stage cannot uniquely determine a tradable definition of the "
        "experimental group from the frozen rules, so it stops at this decision node:",
        "",
    ]
    for item in document["determinacy_audit"]["not_determined"]:
        lines.append(f"- `{item['dimension']}`: {item['why_blocking']}")
    lines.extend(
        [
            "",
            "The three packages below are mutually exclusive candidate implementations. The "
            "research selects none of them and does not rank them by outcome; only after the "
            "user chooses or rejects them can a second-stage protocol be pre-registered.",
            "",
            "## Already uniquely determined by frozen rules",
            "",
            "| dimension | rule | source |",
            "|---|---|---|",
        ]
    )
    for item in document["determinacy_audit"]["uniquely_determined"]:
        lines.append(f"| `{item['dimension']}` | {item['rule']} | {item['source']} |")

    lines.extend(
        [
            "",
            "## Candidate packages (mutually exclusive, none selected)",
            "",
            "| package | admission | pre-confirmation stop | pre-confirmation targets |",
            "|---|---|---|---|",
        ]
    )
    for package_id, package in document["candidate_packages"].items():
        definition = package["definition"]
        lines.append(
            f"| `{package_id}` | {definition['admission_rule']} | "
            f"{definition['pre_confirmation_execution_stop']} | "
            f"{definition['pre_confirmation_targets']} |"
        )

    lines.extend(
        [
            "",
            "### Information availability",
            "",
            "- All three packages share the same entry trigger, the same exact next-session "
            "OPEN execution and the same structural invalidation definition.",
            "- A and B use pre-confirmation targets and the 5%/2R gates only after the first "
            "CONFIRMED day; the signal date reads no geometry that exists only at "
            "confirmation.",
            "- C evaluates the incumbent 5% and 2R gates at the signal date against "
            "signal-date confirmed swing highs and Wave-1 Fib projections; it backfills "
            "nothing from the confirmation day.",
            "",
            "### Executability and composition (geometry only, no cost or return)",
            "",
            "| package | market | executable | admitted | admission composition |",
            "|---|---|---:|---:|---|",
        ]
    )
    for package_id, package in document["candidate_packages"].items():
        for market in MARKETS:
            summary = package["per_market"][market]
            counts = ", ".join(
                f"{key}={value}" for key, value in summary["admission_counts"].items()
            )
            lines.append(
                f"| `{package_id}` | {market} | "
                f"{summary['signals_with_executable_next_open']} | "
                f"{summary['admitted_count']} | {counts} |"
            )

    lines.extend(["", "### Admission notes", ""])
    for package_id, package in document["candidate_packages"].items():
        lines.append(f"- `{package_id}`: {package['combined']['admission_note']}")
        lines.append(
            f"  - CN: {package['per_market']['CN']['admission_note']}; "
            f"US: {package['per_market']['US']['admission_note']}"
        )
    lines.extend(
        [
            "",
            "A package that admits no trade on the frozen sample is not a usable second-stage "
            "candidate as written; it must be rejected or re-specified by the user before "
            "any protocol is registered.",
        ]
    )

    lines.extend(
        [
            "",
            "### Compatibility with the existing system",
            "",
            "| package | new rules required | reused | risk-profile note |",
            "|---|---|---|---|",
        ]
    )
    for package_id, package in document["candidate_packages"].items():
        compatibility = document["compatibility"][package_id]
        lines.append(
            f"| `{package_id}` | {'; '.join(compatibility['new_rules_required'])} | "
            f"{'; '.join(compatibility['reuses'])} | {compatibility['risk_profile_note']} |"
        )

    lines.extend(
        [
            "",
            "### Potential loss (per-trade 1R distance) and capital occupation (0.5% risk)",
            "",
            "| package | market | risk/share %entry | risk/share / Wave1 R | notional / allocation_budget | sessions to resolution |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for package_id, package in document["candidate_packages"].items():
        for market in MARKETS:
            summary = package["per_market"][market]
            lines.append(
                f"| `{package_id}` | {market} | "
                f"{_render_distribution(summary['risk_per_share_pct_of_entry'])} | "
                f"{_render_distribution(summary['risk_per_share_over_wave1_R'])} | "
                f"{_render_distribution(summary['notional_over_allocation_budget_at_half_percent_risk'])} | "
                f"{_render_distribution(summary['sessions_from_entry_to_resolution'])} |"
            )

    facts = document["shared_geometry_facts"]
    lines.extend(
        [
            "",
            "### Shared geometry facts",
            "",
            "| market | executable | incumbent entry-zone class | entry->H1 /R | entry->Wave2 low %entry | entry->ATR stop %entry |",
            "|---|---:|---|---:|---:|---:|",
        ]
    )
    for market in MARKETS:
        detail = facts["per_market"][market]
        zone = ", ".join(
            f"{key}={value}" for key, value in detail["incumbent_entry_zone_class"].items()
        )
        lines.append(
            f"| {market} | {detail['executable_next_session_open']} | {zone} | "
            f"{_render_distribution(detail['entry_to_H1_R'])} | "
            f"{_render_distribution(detail['entry_to_wave2_low_pct_of_entry'])} | "
            f"{_render_distribution(detail['entry_to_atr_execution_stop_pct_of_entry'])} |"
        )
    combined = facts["combined"]
    lines.extend(
        [
            "",
            f"- Frozen common denominator: {combined['early_signals']} ARMED signals, "
            f"{combined['executable_next_session_open']} with an executable exact "
            f"next-session OPEN ({combined['non_executable_next_session_open']} not "
            f"executable); eventual status {combined['eventual_status_composition']}.",
            f"- Resolution composition: {combined['resolution_composition']}; "
            f"dataset-end rows {combined['dataset_end_resolution']}.",
            "",
            "## Residual parameters that still need an explicit user decision",
            "",
            "| decision | question | required before |",
            "|---|---|---|",
        ]
    )
    for item in document["residual_decisions"]:
        lines.append(
            f"| `{item['decision_id']}` | {item['question']} | {item['required_before']} |"
        )

    lines.extend(["", "## Stage-2 protocol items already ready to freeze", ""])
    for item in document["stage2_protocol_items_ready_to_freeze"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- This artifact rebuilds only the already frozen first-stage cohort and the same "
            "ARMED signals; it adds no sample, replaces no symbol, extends no window and "
            "searches no milestone or threshold.",
            "- It computes no P&L, net R, net return, cost, win rate, expectancy or portfolio "
            "drawdown, and touches no Final OOS, real holdings, production state, Sheets or "
            "broker path.",
            "- All three packages are candidate implementations only; the choice must be made "
            "by the user before any cost or net-return result is read.",
            "",
            f"Status: `{document['status']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-manifest", type=Path, default=DATASET_MANIFEST_PATH)
    parser.add_argument("--frozen-input", type=Path, default=FROZEN_INPUT_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args(argv)
    document = run_decision(
        dataset_manifest_path=args.dataset_manifest,
        frozen_input_path=args.frozen_input,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    print(
        json.dumps(
            {
                "status": document["status"],
                "denominator": document["denominator"]["anchor_contexts"],
                "executable_early_signals": document["shared_geometry_facts"]["combined"][
                    "executable_next_session_open"
                ],
                "admitted": {
                    package_id: package["combined"]["admitted_count"]
                    for package_id, package in document["candidate_packages"].items()
                },
                "protocol_registered": document["protocol_registered"],
                "final_oos_accessed": document["controls"]["final_oos_accessed"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

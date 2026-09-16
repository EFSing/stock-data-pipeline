"""Development-only SETUP_01 deep Wave2 structure-quality study.

This module answers one descriptive research question: whether a deep Wave2
is associated with weaker Wave2 -> Wave3 structural continuation, or whether
the existing breakout confirmation / planned-entry geometry leaves too little
1.272 headroom.

The module is intentionally an adapter around the frozen holdout loader, the
causal SETUP_01 replay, the existing SETUP_01 Decision evaluator, the
canonical Fibonacci projection helper, and the existing Position Management
replay for secondary execution context.  It does not modify production code,
parameters, Decision semantics, state, Sheets, or broker paths.

The primary structural outcome starts strictly after T.  A target and a
structural invalidation on the same future bar are ``SAME_BAR_AMBIGUOUS``:
the existing stop-first ordering is an execution-stop contract and is not
silently applied to structural target/invalidation ordering.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import sys
from statistics import median
import tempfile
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote
from research.development_holdout_dataset import load_frozen_holdout
from research.market_sessions import (
    DEVELOPMENT_SESSION_IDENTITY,
    build_market_session_dates,
    trading_day_distance,
)
from trading.fibonacci import EXTENSION_RATIOS, project_extension
from trading.models import DecisionAction, SetupState
from trading.paper_lifecycle import calculate_performance
from trading.position_management import (
    PositionExitReason,
    position_origin_from_execution,
    replay_position,
)
from trading.setup01_decision import (
    EXECUTED,
    MIN_TARGET_UPSIDE_PCT,
    Setup01Decision,
    Setup01Execution,
    evaluate_setup01_decision_stream,
    setup01_target_projection,
)
from trading.setup01_replay import Setup01ReplayEvent, replay_setup01_history


PROTOCOL_VERSION = "SETUP-01-DEEP-WAVE2-STRUCTURE-QUALITY-2026-09-16-v1"
FIB_1_272_RATIO = float(EXTENSION_RATIOS["1.272"])
FIB_1_618_RATIO = float(EXTENSION_RATIOS["1.618"])
DEPTH_BANDS = (
    "NORMAL_OR_SHALLOW",
    "DEEP",
    "VERY_DEEP",
)
STRUCTURAL_OUTCOMES = (
    "FIB1272_BEFORE_STRUCTURAL_INVALIDATION",
    "STRUCTURAL_INVALIDATION_BEFORE_FIB1272",
    "SAME_BAR_AMBIGUOUS",
    "CENSORED_INSUFFICIENT_PATH",
)
NEAR_CATEGORIES = frozenset(("SMALL_WAVE_FIB", "BOTH_NEAR"))
EVENT_DETAIL_SCHEMA_VERSION = "setup01-deep-wave2-structure-quality-record-v2"
COMMON_HURDLES = (
    ("HURDLE_0272", 0.272),
    ("HURDLE_0618", 0.618),
)
HURDLE_OUTCOMES = (
    "HURDLE_BEFORE_STRUCTURAL_INVALIDATION",
    "STRUCTURAL_INVALIDATION_BEFORE_HURDLE",
    "SAME_BAR_AMBIGUOUS",
    "CENSORED_INSUFFICIENT_PATH",
)

# These are cross-binding expectations from the already accepted PR #86
# artifact, not searched or selected thresholds.
PRIOR_CATEGORY_COUNTS = {
    "NEAR_SWING_ONLY": 117,
    "SMALL_WAVE_FIB": 18,
    "BOTH_NEAR": 63,
}

DEFAULT_MANIFEST = PROJECT_ROOT / "research" / "development_holdout" / "dataset_manifest.json"
DEFAULT_REPLAY_INPUT = (
    PROJECT_ROOT
    / "artifacts"
    / "phase5j_v3_development_holdout"
    / "development_holdout_replay_input.jsonl.gz"
)
DEFAULT_REPLAY_WRAPPER = PROJECT_ROOT / "research" / "development_holdout" / "replay_manifest.json"
DEFAULT_PRIOR_STRUCTURE = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_wave2_to_wave3_structure_scale_diagnostic_v1.json"
)
DEFAULT_PRIOR_GEOMETRY = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_wave2_to_wave3_geometry_attribution_v1.json"
)
DEFAULT_JSON_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_deep_wave2_structure_quality_v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_deep_wave2_structure_quality_v1.md"
)

STOP_EXIT_REASONS = frozenset(
    {
        PositionExitReason.EXIT_GAP_BELOW_STOP,
        PositionExitReason.EXIT_STOP_TRIGGERED,
    }
)


@dataclass(frozen=True)
class StructuralPath:
    target_1272_date: date | None
    target_1618_date: date | None
    structural_invalidation_date: date | None
    scenario_invalidation_date: date | None
    outcome: str
    fib_1618_before_structural_invalidation: bool
    sessions_to_1272: int | None
    sessions_to_structural_invalidation: int | None
    scenario_relation: str
    target_reached_on_t_bar: bool


@dataclass(frozen=True)
class HurdlePath:
    level: float
    hit_date: date | None
    outcome: str


@dataclass(frozen=True)
class GeometryControlledPath:
    max_high_before_structural_invalidation: float | None
    max_close_before_structural_invalidation: float | None
    post_T_peak_extension_from_H1_over_R: float | None
    post_T_peak_extension_from_planned_entry_over_R: float | None
    post_T_peak_close_extension_from_H1_over_R: float | None
    observed_quote_count: int
    hurdle_0272: HurdlePath
    hurdle_0618: HurdlePath


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _finite_number(value: Any, name: str) -> float:
    result = _number(value)
    if result is None:
        raise ValueError(f"missing finite value: {name}")
    return result


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _stats(values: Sequence[float | int]) -> dict[str, Any]:
    clean = [float(value) for value in values if _number(value) is not None]
    return {
        "n": len(clean),
        "p25": _percentile(clean, 0.25),
        "median": float(median(clean)) if clean else None,
        "p75": _percentile(clean, 0.75),
    }


def _distribution_stats(values: Sequence[float | int]) -> dict[str, Any]:
    clean = [float(value) for value in values if _number(value) is not None]
    return {
        "n": len(clean),
        "p10": _percentile(clean, 0.10),
        "p25": _percentile(clean, 0.25),
        "median": float(median(clean)) if clean else None,
        "p75": _percentile(clean, 0.75),
        "p90": _percentile(clean, 0.90),
    }


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _repo_relative_path(path: Path) -> str:
    """Keep tracked report provenance portable across local checkouts."""

    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def depth_band(retracement_ratio: float) -> str:
    """Return the pre-registered, mutually exclusive Wave2 depth band."""

    ratio = float(retracement_ratio)
    if not math.isfinite(ratio):
        raise ValueError("Wave2 retracement ratio must be finite")
    if ratio <= 0.618:
        return "NORMAL_OR_SHALLOW"
    if ratio <= 0.786:
        return "DEEP"
    return "VERY_DEEP"


def classify_structural_outcome(
    target_date: date | None,
    structural_invalidation_date: date | None,
) -> str:
    """Apply the registered target-vs-structural ordering contract."""

    if target_date is not None and (
        structural_invalidation_date is None
        or target_date < structural_invalidation_date
    ):
        return STRUCTURAL_OUTCOMES[0]
    if structural_invalidation_date is not None and (
        target_date is None
        or structural_invalidation_date < target_date
    ):
        return STRUCTURAL_OUTCOMES[1]
    if (
        target_date is not None
        and structural_invalidation_date is not None
        and target_date == structural_invalidation_date
    ):
        return STRUCTURAL_OUTCOMES[2]
    return STRUCTURAL_OUTCOMES[3]


def classify_hurdle_outcome(
    hurdle_hit_date: date | None,
    structural_invalidation_date: date | None,
) -> str:
    """Apply the same strict ordering contract to a common hurdle."""

    if hurdle_hit_date is not None and (
        structural_invalidation_date is None
        or hurdle_hit_date < structural_invalidation_date
    ):
        return HURDLE_OUTCOMES[0]
    if structural_invalidation_date is not None and (
        hurdle_hit_date is None
        or structural_invalidation_date < hurdle_hit_date
    ):
        return HURDLE_OUTCOMES[1]
    if (
        hurdle_hit_date is not None
        and structural_invalidation_date is not None
        and hurdle_hit_date == structural_invalidation_date
    ):
        return HURDLE_OUTCOMES[2]
    return HURDLE_OUTCOMES[3]


def normalized_common_excursion(
    max_future_high: float | None,
    max_future_close: float | None,
    wave1_high: float,
    planned_entry: float,
    reference_range: float,
) -> dict[str, float | None]:
    """Normalize observed post-T maxima by the common Wave1 range ``R``."""

    if reference_range <= 0 or not math.isfinite(float(reference_range)):
        raise ValueError("Wave1 range must be positive and finite")
    return {
        "post_T_peak_extension_from_H1_over_R": (
            (float(max_future_high) - float(wave1_high)) / float(reference_range)
            if max_future_high is not None
            else None
        ),
        "post_T_peak_extension_from_planned_entry_over_R": (
            (float(max_future_high) - float(planned_entry)) / float(reference_range)
            if max_future_high is not None
            else None
        ),
        "post_T_peak_close_extension_from_H1_over_R": (
            (float(max_future_close) - float(wave1_high)) / float(reference_range)
            if max_future_close is not None
            else None
        ),
    }


def common_hurdle_level(
    wave1_high: float,
    reference_range: float,
    normalized_distance: float,
) -> float:
    """Return a common H1 + kR hurdle, independent of Wave2 depth ``r``."""

    if reference_range <= 0 or not math.isfinite(float(reference_range)):
        raise ValueError("Wave1 range must be positive and finite")
    return float(wave1_high) + float(normalized_distance) * float(reference_range)


def _post_T_quotes(quotes: Sequence[Quote], trade_date: date) -> tuple[Quote, ...]:
    """Return only future bars strictly after the signal/confirmation date."""

    return tuple(quote for quote in quotes if quote.trade_date > trade_date)


def _bars_before_structural_invalidation(
    future_quotes: Sequence[Quote],
    structural_invalidation_date: date | None,
) -> tuple[Quote, ...]:
    """Exclude the invalidation bar when its intraday ordering is unknown."""

    if structural_invalidation_date is None:
        return tuple(future_quotes)
    return tuple(
        quote
        for quote in future_quotes
        if quote.trade_date < structural_invalidation_date
    )


def _outcome_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["path"].outcome) for row in rows)
    return {
        outcome: {
            "count": counts.get(outcome, 0),
            "rate": _rate(counts.get(outcome, 0), len(rows)),
        }
        for outcome in STRUCTURAL_OUTCOMES
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"research artifact is not an object: {path}")
    return value


def _validate_prior_artifacts(
    prior_structure: Mapping[str, Any],
    prior_geometry: Mapping[str, Any],
    *,
    prior_structure_path: Path,
    manifest: Mapping[str, Any],
    replay_manifest: Any,
) -> dict[str, Any]:
    if prior_structure.get("artifact_type") != "SETUP_01_WAVE2_WAVE3_STRUCTURE_SCALE_DIAGNOSTIC":
        raise ValueError("PR #86 structure artifact type changed")
    if prior_geometry.get("artifact_type") != "SETUP_01_WAVE2_WAVE3_GEOMETRY_ATTRIBUTION":
        raise ValueError("PR #86 geometry artifact type changed")

    forbidden = (
        "final_oos_accessed",
        "outcome_accessed",
        "t_plus_1_executor_called",
        "production_parameters_modified",
        "production_semantics_modified",
        "new_production_gate_added",
        "new_threshold_selected",
        "target_redefined",
        "t2_or_t3_substituted",
    )
    for artifact in (prior_structure, prior_geometry):
        controls = artifact.get("controls", {})
        if any(bool(controls.get(name)) for name in forbidden):
            raise ValueError("PR #86 source artifact contains a prohibited control")
        if controls.get("final_oos_accessed"):
            raise ValueError("PR #86 source artifact accessed Final OOS")

    dataset = prior_structure.get("dataset", {})
    expected_dataset = {
        "dataset_version": manifest.get("dataset_version"),
        "dataset_manifest_sha256": manifest.get("integrity", {}).get("manifest_sha256"),
        "replay_input_aggregate_hash": replay_manifest.aggregate_hash,
        "symbol_count": replay_manifest.total_symbol_count,
        "bar_count": replay_manifest.total_bar_count,
    }
    if any(dataset.get(key) != value for key, value in expected_dataset.items()):
        raise ValueError("PR #86 structure artifact frozen dataset binding changed")

    geometry_dataset = prior_geometry.get("source_artifact", {}).get("dataset", {})
    if any(geometry_dataset.get(key) != value for key, value in expected_dataset.items()):
        raise ValueError("PR #86 geometry artifact frozen dataset binding changed")

    source_hash = prior_geometry.get("source_artifact", {}).get("sha256")
    if source_hash != _sha256_file(prior_structure_path):
        raise ValueError("PR #86 geometry artifact source hash does not match structure artifact")

    prior_summary = prior_structure.get("summary", {})
    prior_count = int(prior_summary.get("confirmed_count", -1))
    prior_rows = prior_structure.get("events")
    if not isinstance(prior_rows, list) or len(prior_rows) != prior_count:
        raise ValueError("PR #86 structure artifact event count is inconsistent")
    prior_by_identity: dict[str, Mapping[str, Any]] = {}
    for row in prior_rows:
        identity = str(row.get("event_identity", ""))
        if not identity or identity in prior_by_identity:
            raise ValueError("PR #86 structure artifact event identities are not unique")
        prior_by_identity[identity] = row

    observed_categories = {
        name: int(prior_summary.get("category_results", {}).get(name, {}).get("count", -1))
        for name in PRIOR_CATEGORY_COUNTS
    }
    if observed_categories != PRIOR_CATEGORY_COUNTS:
        raise ValueError(f"PR #86 category conservation changed: {observed_categories}")
    if sum(observed_categories.values()) != int(prior_summary.get("formal_t1_lt_5_count", -1)):
        raise ValueError("PR #86 117/63/18 category partition no longer sums to low-T1 count")

    geometry_scope = prior_geometry.get("scope", {})
    near_count = int(geometry_scope.get("wave3_fib_near", -1))
    detailed_rows = prior_geometry.get("wave3_fib_near_decomposition", {}).get("detailed_rows", [])
    if not isinstance(detailed_rows, list) or len(detailed_rows) != near_count:
        raise ValueError("PR #86 geometry near-sample detail is inconsistent")
    expected_near_count = PRIOR_CATEGORY_COUNTS["SMALL_WAVE_FIB"] + PRIOR_CATEGORY_COUNTS["BOTH_NEAR"]
    if near_count != expected_near_count:
        raise ValueError("PR #86 Wave3 Fib-near count is not the bound category sum")
    if geometry_scope.get("wave3_fib_near_category_partition") != PRIOR_CATEGORY_COUNTS:
        raise ValueError("PR #86 117/63/18 geometry category binding changed")
    if int(geometry_scope.get("all_confirmed", -1)) != prior_count:
        raise ValueError("PR #86 geometry all-confirmed binding changed")
    detailed_ids = {str(row.get("event_identity", "")) for row in detailed_rows}
    category_ids = {
        identity
        for identity, row in prior_by_identity.items()
        if row.get("low_t1_category") in NEAR_CATEGORIES
    }
    if detailed_ids != category_ids:
        raise ValueError("PR #86 Wave3 Fib-near identity binding changed")

    return {
        "confirmed_count": prior_count,
        "prior_by_identity": prior_by_identity,
        "near_event_identities": detailed_ids,
        "prior_category_counts": observed_categories,
        "wave3_fib_near_count": near_count,
        "structure_artifact_sha256": _sha256_file(prior_structure_path),
    }


def _replay_confirmed_events(
    symbol_quotes: Mapping[str, Sequence[Quote]],
) -> tuple[Setup01ReplayEvent, ...]:
    events: list[Setup01ReplayEvent] = []
    for symbol in sorted(symbol_quotes):
        report = replay_setup01_history(list(symbol_quotes[symbol]))
        events.extend(
            event
            for event in report.events
            if event.event_type is SetupState.CONFIRMED
            and event.setup01.is_new_confirmed_event_as_of
            and event.setup01.confirmed_date == event.trade_date
            and event.setup01.as_of_date == event.trade_date
        )
    ordered = tuple(
        sorted(events, key=lambda item: (item.trade_date, item.market, item.symbol, item.event_identity))
    )
    identities = [event.event_identity for event in ordered]
    if len(identities) != len(set(identities)):
        raise ValueError("replayed CONFIRMED event identities are not unique")
    return ordered


def _decision_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _close(a: Any, b: Any, *, tolerance: float = 1e-9) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tolerance)
    except (TypeError, ValueError):
        return a == b


def _decision_cross_binding(
    decisions: Sequence[Setup01Decision],
    prior_by_identity: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    if len(decisions) != len(prior_by_identity):
        raise ValueError("current Decision count does not match PR #86 artifact")
    for decision in decisions:
        identity = decision.event_identity
        prior = prior_by_identity.get(identity)
        if prior is None:
            mismatches.append({"event_identity": identity, "field": "missing_prior_row"})
            continue
        checks = (
            ("symbol", decision.symbol, prior.get("symbol")),
            ("market", decision.market, prior.get("market")),
            ("trade_date", decision.trade_date.isoformat(), prior.get("trade_date")),
            ("formal_decision_gate_reason", str(_decision_value(decision.gate_reason)), prior.get("formal_decision_gate_reason")),
            ("formal_decision_action", str(_decision_value(decision.action)), prior.get("formal_decision_action")),
            ("planned_entry", decision.planned_entry, prior.get("planned_entry")),
            ("atr14", decision.atr14, prior.get("decision_t_atr14")),
        )
        for field, current, expected in checks:
            equal = _close(current, expected) if isinstance(current, (int, float)) or isinstance(expected, (int, float)) else current == expected
            if not equal:
                mismatches.append({"event_identity": identity, "field": field, "current": current, "prior": expected})

        current_t1 = decision.targets[0] if decision.targets else None
        if not _close(current_t1, prior.get("formal_t1_price")):
            mismatches.append({"event_identity": identity, "field": "formal_t1_price", "current": current_t1, "prior": prior.get("formal_t1_price")})
        projection = setup01_target_projection(decision)
        if not _close(projection.get("current_effective_t1"), current_t1):
            mismatches.append({"event_identity": identity, "field": "target_projection_current_effective_t1", "current": projection.get("current_effective_t1"), "prior": current_t1})
    return {
        "decision_count": len(decisions),
        "gate_action_target_parity": not mismatches,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:20],
    }


def _path_result(
    event: Setup01ReplayEvent,
    quotes: Sequence[Quote],
    market_session_dates: Mapping[str, Sequence[date]],
) -> tuple[StructuralPath, float, float]:
    snapshot = event.setup01
    if snapshot.wave1_origin is None or snapshot.wave1_peak is None or snapshot.wave2_low is None:
        raise ValueError("CONFIRMED event is missing Wave1/Wave2 anchors")
    origin = float(snapshot.wave1_origin.price)
    peak = float(snapshot.wave1_peak.price)
    wave2_low = float(snapshot.wave2_low.price)
    reference_range = peak - origin
    if not origin < wave2_low < peak or reference_range <= 0:
        raise ValueError("CONFIRMED event violates existing Wave1/Wave2 geometry")
    target_1272 = project_extension(wave2_low, origin, peak, FIB_1_272_RATIO)
    target_1618 = project_extension(wave2_low, origin, peak, FIB_1_618_RATIO)
    t_bar = next((quote for quote in quotes if quote.trade_date == event.trade_date), None)
    if t_bar is None:
        raise ValueError("event T bar is missing from frozen quotes")

    # Strictly after T: T high is recorded only as a causal diagnostic and is
    # deliberately not credited to the primary post-confirmation outcome.
    future = _post_T_quotes(quotes, event.trade_date)
    target_date = next((quote.trade_date for quote in future if float(quote.high) >= target_1272), None)
    target_1618_date = next((quote.trade_date for quote in future if float(quote.high) >= target_1618), None)
    structural_date = next((quote.trade_date for quote in future if float(quote.close) <= wave2_low), None)
    scenario_date = next((quote.trade_date for quote in future if float(quote.close) <= origin), None)

    outcome = classify_structural_outcome(target_date, structural_date)

    if scenario_date is None:
        scenario_relation = "NOT_OBSERVED"
    elif structural_date is None:
        scenario_relation = "SCENARIO_ONLY_NO_STRUCTURAL_DATE"
    elif scenario_date < structural_date:
        scenario_relation = "SCENARIO_BEFORE_STRUCTURAL"
    elif scenario_date == structural_date:
        scenario_relation = "SCENARIO_SAME_DATE_AS_STRUCTURAL"
    else:
        scenario_relation = "SCENARIO_AFTER_STRUCTURAL"

    def distance(value: date | None) -> int | None:
        if value is None:
            return None
        return trading_day_distance(
            event.trade_date,
            value,
            market=event.market,
            market_session_dates=market_session_dates,
        )

    path = StructuralPath(
        target_1272_date=target_date,
        target_1618_date=target_1618_date,
        structural_invalidation_date=structural_date,
        scenario_invalidation_date=scenario_date,
        outcome=outcome,
        fib_1618_before_structural_invalidation=(
            target_1618_date is not None
            and (structural_date is None or target_1618_date < structural_date)
        ),
        sessions_to_1272=distance(target_date),
        sessions_to_structural_invalidation=distance(structural_date),
        scenario_relation=scenario_relation,
        target_reached_on_t_bar=float(t_bar.high) >= target_1272,
    )
    return path, target_1272, target_1618


def _geometry_controlled_path(
    event: Setup01ReplayEvent,
    decision: Setup01Decision,
    quotes: Sequence[Quote],
    structural_path: StructuralPath,
) -> GeometryControlledPath:
    """Measure common-scale continuation without an r-dependent target."""

    snapshot = event.setup01
    if snapshot.wave1_origin is None or snapshot.wave1_peak is None or snapshot.wave2_low is None:
        raise ValueError("CONFIRMED event is missing Wave1/Wave2 anchors")
    wave1_high = float(snapshot.wave1_peak.price)
    wave1_origin = float(snapshot.wave1_origin.price)
    reference_range = wave1_high - wave1_origin
    planned_entry = _finite_number(decision.planned_entry, "planned_entry")
    future = _post_T_quotes(quotes, event.trade_date)
    before_invalidation = _bars_before_structural_invalidation(
        future, structural_path.structural_invalidation_date
    )
    max_high = max(
        (float(quote.high) for quote in before_invalidation),
        default=None,
    )
    max_close = max(
        (float(quote.close) for quote in before_invalidation),
        default=None,
    )
    normalized = normalized_common_excursion(
        max_high,
        max_close,
        wave1_high,
        planned_entry,
        reference_range,
    )
    hurdles: list[HurdlePath] = []
    for _, normalized_distance in COMMON_HURDLES:
        level = common_hurdle_level(
            wave1_high,
            reference_range,
            normalized_distance,
        )
        hit_date = next(
            (
                quote.trade_date
                for quote in future
                if float(quote.high) >= level
            ),
            None,
        )
        hurdles.append(
            HurdlePath(
                level=level,
                hit_date=hit_date,
                outcome=classify_hurdle_outcome(
                    hit_date,
                    structural_path.structural_invalidation_date,
                ),
            )
        )
    return GeometryControlledPath(
        max_high_before_structural_invalidation=max_high,
        max_close_before_structural_invalidation=max_close,
        post_T_peak_extension_from_H1_over_R=normalized[
            "post_T_peak_extension_from_H1_over_R"
        ],
        post_T_peak_extension_from_planned_entry_over_R=normalized[
            "post_T_peak_extension_from_planned_entry_over_R"
        ],
        post_T_peak_close_extension_from_H1_over_R=normalized[
            "post_T_peak_close_extension_from_H1_over_R"
        ],
        observed_quote_count=len(before_invalidation),
        hurdle_0272=hurdles[0],
        hurdle_0618=hurdles[1],
    )


def _geometry_record(
    event: Setup01ReplayEvent,
    decision: Setup01Decision,
    prior: Mapping[str, Any],
    path: StructuralPath,
    geometry_controlled: GeometryControlledPath,
    target_1272: float,
    target_1618: float,
) -> dict[str, Any]:
    snapshot = event.setup01
    origin = _finite_number(snapshot.wave1_origin.price if snapshot.wave1_origin else None, "Wave1 origin")
    peak = _finite_number(snapshot.wave1_peak.price if snapshot.wave1_peak else None, "Wave1 high")
    wave2_low = _finite_number(snapshot.wave2_low.price if snapshot.wave2_low else None, "Wave2 low")
    planned_entry = _finite_number(decision.planned_entry, "planned_entry")
    atr14 = _finite_number(decision.atr14, "T ATR14")
    reference_range = peak - origin
    r = (peak - wave2_low) / reference_range
    extension = planned_entry - peak
    residual = (target_1272 - planned_entry) - ((FIB_1_272_RATIO - r) * reference_range - extension)
    return {
        "event_identity": event.event_identity,
        "symbol": event.symbol,
        "market": event.market,
        "T_date": event.trade_date,
        "wave1_origin": origin,
        "wave1_high": peak,
        "wave2_low": wave2_low,
        "wave1_gain_pct": reference_range / origin,
        "wave1_range": reference_range,
        "T_ATR14": atr14,
        "wave1_range_over_T_ATR14": reference_range / atr14,
        "r": r,
        "planned_entry": planned_entry,
        "e": extension,
        "e_over_R": extension / reference_range,
        "pre_confirmation_consumption_1272": r / FIB_1_272_RATIO,
        "pre_confirmation_consumption_1618": r / FIB_1_618_RATIO,
        "post_confirmation_headroom_over_R_1272": FIB_1_272_RATIO - r - extension / reference_range,
        "post_confirmation_headroom_over_R_1618": FIB_1_618_RATIO - r - extension / reference_range,
        "fib_1272_price": target_1272,
        "fib_1618_price": target_1618,
        "planned_entry_to_1272_upside_pct": target_1272 / planned_entry - 1.0,
        "planned_entry_to_1618_upside_pct": target_1618 / planned_entry - 1.0,
        "fib_identity_residual_1272": residual,
        "depth_band": depth_band(r),
        "prior_low_t1_category": prior.get("low_t1_category"),
        "path": path,
        "geometry_controlled": geometry_controlled,
        "decision": decision,
    }


def _summarize_band(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    success = sum(row["path"].outcome == STRUCTURAL_OUTCOMES[0] for row in rows)
    failure = sum(row["path"].outcome == STRUCTURAL_OUTCOMES[1] for row in rows)
    ambiguous = sum(row["path"].outcome == STRUCTURAL_OUTCOMES[2] for row in rows)
    censored = sum(row["path"].outcome == STRUCTURAL_OUTCOMES[3] for row in rows)
    return {
        "N": count,
        "geometry": {
            "r": _stats([row["r"] for row in rows]),
            "wave1_gain_pct": _stats([row["wave1_gain_pct"] for row in rows]),
            "wave1_range_over_T_ATR14": _stats([row["wave1_range_over_T_ATR14"] for row in rows]),
            "e": _stats([row["e"] for row in rows]),
            "e_over_R": _stats([row["e_over_R"] for row in rows]),
            "planned_entry_to_1272_upside_pct": _stats([row["planned_entry_to_1272_upside_pct"] for row in rows]),
            "planned_entry_to_1618_upside_pct": _stats([row["planned_entry_to_1618_upside_pct"] for row in rows]),
            "pre_confirmation_consumption_1272_median": median(row["pre_confirmation_consumption_1272"] for row in rows) if rows else None,
            "pre_confirmation_consumption_1618_median": median(row["pre_confirmation_consumption_1618"] for row in rows) if rows else None,
            "post_confirmation_headroom_over_R_1272_median": median(row["post_confirmation_headroom_over_R_1272"] for row in rows) if rows else None,
            "post_confirmation_headroom_over_R_1618_median": median(row["post_confirmation_headroom_over_R_1618"] for row in rows) if rows else None,
            "fib_1272_upside_below_5_count": sum(row["planned_entry_to_1272_upside_pct"] < MIN_TARGET_UPSIDE_PCT for row in rows),
            "fib_1272_upside_below_5_share": _rate(sum(row["planned_entry_to_1272_upside_pct"] < MIN_TARGET_UPSIDE_PCT for row in rows), count),
            "fib_1618_upside_below_5_count": sum(row["planned_entry_to_1618_upside_pct"] < MIN_TARGET_UPSIDE_PCT for row in rows),
            "fib_1618_upside_below_5_share": _rate(sum(row["planned_entry_to_1618_upside_pct"] < MIN_TARGET_UPSIDE_PCT for row in rows), count),
        },
        "structural_continuation": {
            "outcomes": _outcome_counts(rows),
            "fib1272_before_structural_invalidation_count": success,
            "fib1272_before_structural_invalidation_rate": _rate(success, count),
            "structural_invalidation_before_fib1272_count": failure,
            "structural_invalidation_before_fib1272_rate": _rate(failure, count),
            "same_bar_ambiguous_count": ambiguous,
            "censored_count": censored,
            "fib1618_before_structural_invalidation_count": sum(
                row["path"].fib_1618_before_structural_invalidation for row in rows
            ),
            "fib1618_before_structural_invalidation_rate": _rate(
                sum(row["path"].fib_1618_before_structural_invalidation for row in rows), count
            ),
            "sessions_to_fib1272": _stats(
                [row["path"].sessions_to_1272 for row in rows if row["path"].sessions_to_1272 is not None]
            ),
            "sessions_to_structural_invalidation": _stats(
                [row["path"].sessions_to_structural_invalidation for row in rows if row["path"].sessions_to_structural_invalidation is not None]
            ),
            "scenario_invalidation_relation": dict(
                sorted(Counter(row["path"].scenario_relation for row in rows).items())
            ),
            "scenario_invalidation_before_structural_count": sum(
                row["path"].scenario_relation == "SCENARIO_BEFORE_STRUCTURAL" for row in rows
            ),
            "target_reached_on_T_bar_not_credited_count": sum(
                row["path"].target_reached_on_t_bar for row in rows
            ),
        },
    }


def _hurdle_outcome_summary(
    rows: Sequence[Mapping[str, Any]],
    hurdle_attribute: str,
) -> dict[str, Any]:
    counts = Counter(
        getattr(row["geometry_controlled"], hurdle_attribute).outcome
        for row in rows
    )
    return {
        outcome: {
            "count": counts.get(outcome, 0),
            "rate": _rate(counts.get(outcome, 0), len(rows)),
        }
        for outcome in HURDLE_OUTCOMES
    }


def _geometry_controlled_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hurdle_distances = dict(COMMON_HURDLES)
    metrics = (
        "post_T_peak_extension_from_H1_over_R",
        "post_T_peak_extension_from_planned_entry_over_R",
        "post_T_peak_close_extension_from_H1_over_R",
    )
    continuous: dict[str, Any] = {}
    for metric in metrics:
        values = [
            getattr(row["geometry_controlled"], metric)
            for row in rows
            if getattr(row["geometry_controlled"], metric) is not None
        ]
        continuous[metric] = {
            "N_total": len(rows),
            "N_observed": len(values),
            "censored_or_empty_path_N": len(rows) - len(values),
            "distribution": _distribution_stats(values),
        }
    return {
        "continuous_path_definition": (
            "max over strictly post-T bars before the close-based structural invalidation bar; "
            "when no invalidation occurs, use bars through frozen dataset end"
        ),
        "continuous_metrics": continuous,
        "hurdles": {
            "HURDLE_0272": {
                "normalized_distance_from_H1_over_R": hurdle_distances["HURDLE_0272"],
                "outcomes": _hurdle_outcome_summary(rows, "hurdle_0272"),
                "success_count": sum(
                    row["geometry_controlled"].hurdle_0272.outcome == HURDLE_OUTCOMES[0]
                    for row in rows
                ),
                "success_rate": _rate(
                    sum(
                        row["geometry_controlled"].hurdle_0272.outcome == HURDLE_OUTCOMES[0]
                        for row in rows
                    ),
                    len(rows),
                ),
            },
            "HURDLE_0618": {
                "normalized_distance_from_H1_over_R": hurdle_distances["HURDLE_0618"],
                "outcomes": _hurdle_outcome_summary(rows, "hurdle_0618"),
                "success_count": sum(
                    row["geometry_controlled"].hurdle_0618.outcome == HURDLE_OUTCOMES[0]
                    for row in rows
                ),
                "success_rate": _rate(
                    sum(
                        row["geometry_controlled"].hurdle_0618.outcome == HURDLE_OUTCOMES[0]
                        for row in rows
                    ),
                    len(rows),
                ),
            },
        },
    }


def _two_by_two(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cells = Counter()
    for row in rows:
        outcome = row["path"].outcome
        structure = (
            "STRUCTURE_SUCCESS"
            if outcome == STRUCTURAL_OUTCOMES[0]
            else "STRUCTURE_FAILURE"
            if outcome == STRUCTURAL_OUTCOMES[1]
            else "UNRESOLVED"
        )
        headroom = (
            "ENTRY_HEADROOM_GE_5_PCT"
            if row["planned_entry_to_1272_upside_pct"] >= MIN_TARGET_UPSIDE_PCT
            else "ENTRY_HEADROOM_LT_5_PCT"
        )
        cells[(structure, headroom)] += 1
    structures = ("STRUCTURE_SUCCESS", "STRUCTURE_FAILURE", "UNRESOLVED")
    headrooms = ("ENTRY_HEADROOM_GE_5_PCT", "ENTRY_HEADROOM_LT_5_PCT")
    return {
        "cells": {
            structure: {
                headroom: {
                    "count": cells[(structure, headroom)],
                    "share_of_band": _rate(cells[(structure, headroom)], len(rows)),
                }
                for headroom in headrooms
            }
            for structure in structures
        },
        "unresolved_outcome_counts": dict(
            sorted(
                Counter(
                    row["path"].outcome
                    for row in rows
                    if row["path"].outcome not in {
                        STRUCTURAL_OUTCOMES[0],
                        STRUCTURAL_OUTCOMES[1],
                    }
                ).items()
            )
        ),
        "resolved_success_count": cells[("STRUCTURE_SUCCESS", headrooms[0])] + cells[("STRUCTURE_SUCCESS", headrooms[1])],
        "resolved_failure_count": cells[("STRUCTURE_FAILURE", headrooms[0])] + cells[("STRUCTURE_FAILURE", headrooms[1])],
    }


def _production_funnel(
    rows: Sequence[Mapping[str, Any]],
    executions_by_identity: Mapping[str, Setup01Execution],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for band in DEPTH_BANDS:
        scoped = [row for row in rows if row["depth_band"] == band]
        gate_counts = Counter(str(_decision_value(row["decision"].gate_reason)) for row in scoped)
        execution_counts = Counter(
            str(executions_by_identity[row["event_identity"]].outcome)
            for row in scoped
            if row["event_identity"] in executions_by_identity
        )
        confirmed = len(scoped)
        entry_allowed = gate_counts.get("ENTRY_ALLOWED", 0)
        executed = execution_counts.get(EXECUTED, 0)
        if entry_allowed != sum(execution_counts.values()):
            raise AssertionError(f"T+1 attempt conservation failed for {band}")
        output[band] = {
            "CONFIRMED": confirmed,
            "ABOVE_ENTRY_ZONE": gate_counts.get("ABOVE_ENTRY_ZONE", 0),
            "TARGET_UPSIDE_BELOW_MINIMUM": gate_counts.get("TARGET_UPSIDE_BELOW_MINIMUM", 0),
            "RR_BELOW_MINIMUM": gate_counts.get("RR_BELOW_MINIMUM", 0),
            "ENTRY_ALLOWED": entry_allowed,
            "T+1_EXECUTED": executed,
            "T+1_SKIPPED": entry_allowed - executed,
            "other_decision_gate_reasons": {
                key: value
                for key, value in sorted(gate_counts.items())
                if key not in {"ABOVE_ENTRY_ZONE", "TARGET_UPSIDE_BELOW_MINIMUM", "RR_BELOW_MINIMUM", "ENTRY_ALLOWED"}
            },
            "t_plus_1_outcome_counts": dict(sorted(execution_counts.items())),
            "excluded_by_current_T_day_gates": confirmed - entry_allowed,
            "excluded_by_current_T_day_gates_share": _rate(confirmed - entry_allowed, confirmed),
            "excluded_after_T_plus_1_open": entry_allowed - executed,
            "entry_allowed_share": _rate(entry_allowed, confirmed),
            "executed_share_of_confirmed": _rate(executed, confirmed),
        }
    return output


def _secondary_performance(
    rows: Sequence[Mapping[str, Any]],
    symbol_quotes: Mapping[str, Sequence[Quote]],
    executions_by_identity: Mapping[str, Setup01Execution],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for band in DEPTH_BANDS:
        scoped = [
            row
            for row in rows
            if row["depth_band"] == band
            and row["event_identity"] in executions_by_identity
            and executions_by_identity[row["event_identity"]].outcome == EXECUTED
        ]
        ledger_rows: list[dict[str, Any]] = []
        stop_out_count = 0
        terminal_counts: Counter[str] = Counter()
        for row in scoped:
            execution = executions_by_identity[row["event_identity"]]
            origin = position_origin_from_execution(
                "SETUP_01", row["event"], row["decision"], execution
            )
            if origin is None:
                raise ValueError("EXECUTED row did not produce a position origin")
            replay = replay_position(origin, symbol_quotes[row["symbol"]])
            exit_key = replay.exit_reason.value if replay.exit_reason is not None else "OPEN_CENSORED"
            terminal_counts[exit_key] += 1
            if replay.exit_reason in STOP_EXIT_REASONS:
                stop_out_count += 1
            realized_r = None
            if replay.exit_price is not None:
                realized_r = (float(replay.exit_price) - origin.actual_entry) / origin.one_r
            ledger_rows.append(
                {
                    "event_identity": row["event_identity"],
                    "status": "CLOSED" if realized_r is not None else "OPEN",
                    "realized_r": realized_r,
                }
            )
        stats = calculate_performance(ledger_rows)
        realized = [row["realized_r"] for row in ledger_rows if row["realized_r"] is not None]
        positive = sum(float(value) for value in realized if float(value) > 0)
        negative = sum(float(value) for value in realized if float(value) < 0)
        output[band] = {
            "executed": len(scoped),
            "closed": int(stats.closed),
            "open_censored": int(stats.open),
            "gross_expectancy_R": stats.average_r,
            "gross_win_rate": stats.win_rate,
            "gross_profit_factor": positive / abs(negative) if negative < 0 else None,
            "stop_out_count": stop_out_count,
            "stop_out_rate": _rate(stop_out_count, len(scoped)),
            "terminal_outcome_distribution": dict(sorted(terminal_counts.items())),
            "metrics_are_secondary_context": True,
            "small_executed_sample_not_gate_evidence": len(scoped) < 20,
        }
    return output


def _market_robustness(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for market in sorted({str(row["market"]) for row in rows}):
        output[market] = {}
        for band in DEPTH_BANDS:
            scoped = [row for row in rows if row["market"] == market and row["depth_band"] == band]
            outcomes = _outcome_counts(scoped)
            output[market][band] = {
                "N": len(scoped),
                "outcomes": outcomes,
                "structural_success_rate": outcomes[STRUCTURAL_OUTCOMES[0]]["rate"],
                "fib1618_before_structural_invalidation_rate": _rate(
                    sum(row["path"].fib_1618_before_structural_invalidation for row in scoped), len(scoped)
                ),
            }
    return output


def _geometry_controlled_market_robustness(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for market in sorted({str(row["market"]) for row in rows}):
        output[market] = {}
        for band in DEPTH_BANDS:
            scoped = [
                row
                for row in rows
                if row["market"] == market and row["depth_band"] == band
            ]
            output[market][band] = {
                "N": len(scoped),
                **_geometry_controlled_summary(scoped),
            }
    return output


def _time_half_robustness(
    rows: Sequence[Mapping[str, Any]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    cutoffs = {
        market: market_session_dates[market][(len(market_session_dates[market]) - 1) // 2]
        for market in sorted(market_session_dates)
    }
    output: dict[str, Any] = {}
    for half_name in ("FIRST_HALF", "SECOND_HALF"):
        output[half_name] = {}
        for band in DEPTH_BANDS:
            scoped = [
                row
                for row in rows
                if row["depth_band"] == band
                and (
                    row["T_date"] <= cutoffs[row["market"]]
                    if half_name == "FIRST_HALF"
                    else row["T_date"] > cutoffs[row["market"]]
                )
            ]
            outcomes = _outcome_counts(scoped)
            output[half_name][band] = {
                "N": len(scoped),
                "outcomes": outcomes,
                "structural_success_rate": outcomes[STRUCTURAL_OUTCOMES[0]]["rate"],
            }
    return {
        "split_definition": "Within each market, frozen market-session ordinal midpoint; aggregate by half after the split",
        "cutoff_by_market": {market: _date_text(value) for market, value in cutoffs.items()},
        "results": output,
    }


def _geometry_controlled_time_half_robustness(
    rows: Sequence[Mapping[str, Any]],
    market_session_dates: Mapping[str, Sequence[date]],
) -> dict[str, Any]:
    cutoffs = {
        market: market_session_dates[market][(len(market_session_dates[market]) - 1) // 2]
        for market in sorted(market_session_dates)
    }
    output: dict[str, Any] = {}
    for half_name in ("FIRST_HALF", "SECOND_HALF"):
        output[half_name] = {}
        for band in DEPTH_BANDS:
            scoped = [
                row
                for row in rows
                if row["depth_band"] == band
                and (
                    row["T_date"] <= cutoffs[row["market"]]
                    if half_name == "FIRST_HALF"
                    else row["T_date"] > cutoffs[row["market"]]
                )
            ]
            output[half_name][band] = {
                "N": len(scoped),
                **_geometry_controlled_summary(scoped),
            }
    return {
        "split_definition": "Within each market, frozen market-session ordinal midpoint; aggregate by half after the split",
        "cutoff_by_market": {market: _date_text(value) for market, value in cutoffs.items()},
        "results": output,
    }


def _concentration(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for band in DEPTH_BANDS:
        scoped = [row for row in rows if row["depth_band"] == band]
        counts = Counter(str(row["symbol"]) for row in scoped)
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        n = len(scoped)
        top5 = ordered[:5]
        top_symbol = ordered[0][0] if ordered else None
        without_top = [row for row in scoped if row["symbol"] != top_symbol]
        output[band] = {
            "symbol_count": len(counts),
            "top_5_symbols_by_event_count": [
                {"symbol": symbol, "N": count, "share": _rate(count, n)}
                for symbol, count in top5
            ],
            "top_5_event_share": _rate(sum(count for _, count in top5), n),
            "max_symbol_event_share": _rate(ordered[0][1], n) if ordered else None,
            "event_count_hhi": sum((count / n) ** 2 for count in counts.values()) if n else None,
            "structural_success_rate_excluding_top_symbol": _rate(
                sum(row["path"].outcome == STRUCTURAL_OUTCOMES[0] for row in without_top),
                len(without_top),
            ),
            "geometry_controlled_excluding_top_symbol": _geometry_controlled_summary(without_top),
        }
    return output


def _near_sample(
    rows: Sequence[Mapping[str, Any]],
    near_event_identities: set[str],
) -> dict[str, Any]:
    scoped = [row for row in rows if row["event_identity"] in near_event_identities]
    if len(scoped) != len(near_event_identities):
        raise ValueError("current replay is missing a PR #86 Fib-near identity")
    category_counts = Counter(str(row["prior_low_t1_category"]) for row in scoped)
    if category_counts.get("SMALL_WAVE_FIB", 0) != PRIOR_CATEGORY_COUNTS["SMALL_WAVE_FIB"]:
        raise ValueError("current Fib-near SMALL_WAVE_FIB binding changed")
    if category_counts.get("BOTH_NEAR", 0) != PRIOR_CATEGORY_COUNTS["BOTH_NEAR"]:
        raise ValueError("current Fib-near BOTH_NEAR binding changed")
    return {
        "N": len(scoped),
        "category_counts": dict(sorted(category_counts.items())),
        "very_deep_count": sum(row["depth_band"] == "VERY_DEEP" for row in scoped),
        "headroom_ge_5_count": sum(row["planned_entry_to_1272_upside_pct"] >= MIN_TARGET_UPSIDE_PCT for row in scoped),
        "headroom_lt_5_count": sum(row["planned_entry_to_1272_upside_pct"] < MIN_TARGET_UPSIDE_PCT for row in scoped),
        "strict_post_T_outcomes": _outcome_counts(scoped),
        "fib1272_before_structural_invalidation_count": sum(
            row["path"].outcome == STRUCTURAL_OUTCOMES[0] for row in scoped
        ),
        "fib1272_before_structural_invalidation_rate": _rate(
            sum(row["path"].outcome == STRUCTURAL_OUTCOMES[0] for row in scoped), len(scoped)
        ),
        "two_by_two": _two_by_two(scoped),
        "geometry_controlled": _geometry_controlled_summary(scoped),
        "strict_post_T_target_crossing_not_credited_on_T_bar": True,
    }


def _event_detail_record(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project one in-memory audit row without retaining it in the artifact."""

    path = row["path"]
    controlled = row["geometry_controlled"]
    return {
        "event_identity": row["event_identity"],
        "symbol": row["symbol"],
        "market": row["market"],
        "T_date": _date_text(row["T_date"]),
        "wave1_origin": row["wave1_origin"],
        "wave1_high": row["wave1_high"],
        "wave2_low": row["wave2_low"],
        "wave1_gain_pct": row["wave1_gain_pct"],
        "wave1_range": row["wave1_range"],
        "T_ATR14": row["T_ATR14"],
        "wave1_range_over_T_ATR14": row["wave1_range_over_T_ATR14"],
        "r": row["r"],
        "planned_entry": row["planned_entry"],
        "e": row["e"],
        "e_over_R": row["e_over_R"],
        "pre_confirmation_consumption_1272": row["pre_confirmation_consumption_1272"],
        "pre_confirmation_consumption_1618": row["pre_confirmation_consumption_1618"],
        "post_confirmation_headroom_over_R_1272": row["post_confirmation_headroom_over_R_1272"],
        "post_confirmation_headroom_over_R_1618": row["post_confirmation_headroom_over_R_1618"],
        "fib_1272_price": row["fib_1272_price"],
        "fib_1618_price": row["fib_1618_price"],
        "planned_entry_to_1272_upside_pct": row["planned_entry_to_1272_upside_pct"],
        "planned_entry_to_1618_upside_pct": row["planned_entry_to_1618_upside_pct"],
        "depth_band": row["depth_band"],
        "prior_low_t1_category": row["prior_low_t1_category"],
        "formal_decision_gate_reason": str(_decision_value(row["decision"].gate_reason)),
        "formal_decision_action": str(_decision_value(row["decision"].action)),
        "structural_outcome": path.outcome,
        "fib1272_date": _date_text(path.target_1272_date),
        "structural_invalidation_date": _date_text(path.structural_invalidation_date),
        "scenario_invalidation_date": _date_text(path.scenario_invalidation_date),
        "fib1618_before_structural_invalidation": path.fib_1618_before_structural_invalidation,
        "sessions_to_fib1272": path.sessions_to_1272,
        "sessions_to_structural_invalidation": path.sessions_to_structural_invalidation,
        "post_T_peak_extension_from_H1_over_R": controlled.post_T_peak_extension_from_H1_over_R,
        "post_T_peak_extension_from_planned_entry_over_R": controlled.post_T_peak_extension_from_planned_entry_over_R,
        "post_T_peak_close_extension_from_H1_over_R": controlled.post_T_peak_close_extension_from_H1_over_R,
        "HURDLE_0272_outcome": controlled.hurdle_0272.outcome,
        "HURDLE_0618_outcome": controlled.hurdle_0618.outcome,
    }


def _ephemeral_event_detail_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Hash a temporary JSONL audit projection, then remove the local file."""

    projected = [_event_detail_record(row) for row in rows]
    raw = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in projected
    ).encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="setup01-deep-wave2-",
            suffix=".jsonl",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(raw)
        digest = hashlib.sha256()
        with temporary_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {
            "count": len(projected),
            "schema_version": EVENT_DETAIL_SCHEMA_VERSION,
            "sha256": f"sha256:{digest.hexdigest()}",
            "persisted": False,
            "temporary_file_removed": True,
        }
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _validate_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    prior_count: int,
    near_event_identities: set[str],
) -> dict[str, Any]:
    if len(rows) != prior_count:
        raise ValueError("current geometry row count does not match frozen confirmed count")
    residuals = [abs(float(row["fib_identity_residual_1272"])) for row in rows]
    bands = Counter(str(row["depth_band"]) for row in rows)
    identities = {str(row["event_identity"]) for row in rows}
    near_current = {
        str(row["event_identity"])
        for row in rows
        if row["prior_low_t1_category"] in NEAR_CATEGORIES
    }
    category_conservation = {
        name: sum(row["prior_low_t1_category"] == name for row in rows)
        for name in PRIOR_CATEGORY_COUNTS
    }
    if category_conservation != PRIOR_CATEGORY_COUNTS:
        raise ValueError(f"current 117/63/18 category conservation changed: {category_conservation}")
    common_scale_ok = True
    common_hurdle_level_ok = True
    hurdle_future_date_ok = True
    for row in rows:
        controlled = row["geometry_controlled"]
        expected = normalized_common_excursion(
            controlled.max_high_before_structural_invalidation,
            controlled.max_close_before_structural_invalidation,
            row["wave1_high"],
            row["planned_entry"],
            row["wave1_range"],
        )
        common_scale_ok = common_scale_ok and all(
            _close(getattr(controlled, name), expected[name])
            for name in expected
        )
        for hurdle_name, distance in COMMON_HURDLES:
            hurdle = getattr(controlled, hurdle_name.lower())
            common_hurdle_level_ok = common_hurdle_level_ok and _close(
                hurdle.level,
                common_hurdle_level(row["wave1_high"], row["wave1_range"], distance),
            )
            hurdle_future_date_ok = hurdle_future_date_ok and (
                hurdle.hit_date is None or hurdle.hit_date > row["T_date"]
            )
    signal_as_of_ok = True
    for row in rows:
        event = row["event"]
        quote_index = next(
            (index for index, quote in enumerate(row["quotes"]) if quote.trade_date == row["T_date"]),
            None,
        )
        anchors = (
            event.setup01.wave1_origin,
            event.setup01.wave1_peak,
            event.setup01.wave2_low,
        )
        signal_as_of_ok = signal_as_of_ok and quote_index is not None and all(
            anchor is not None
            and anchor.pivot_index <= quote_index
            and anchor.confirmed_index is not None
            and anchor.confirmed_index <= quote_index
            for anchor in anchors
        )
    return {
        "frozen_hash_binding_verified": True,
        "confirmed_rebuilt_count": len(rows),
        "confirmed_count_matches_prior_artifact": len(rows) == prior_count,
        "event_identity_set_matches_prior_near_binding": near_current == near_event_identities,
        "wave3_fib_near_rebuilt_count": len(near_current),
        "prior_117_63_18_category_conservation": {
            name: category_conservation[name]
            for name in PRIOR_CATEGORY_COUNTS
        },
        "fib_identity_1272": {
            "n": len(residuals),
            "max_absolute_residual": max(residuals) if residuals else None,
            "passed": bool(residuals) and max(residuals) <= 1e-9,
        },
        "depth_band_counts": dict((band, bands.get(band, 0)) for band in DEPTH_BANDS),
        "depth_band_mutually_exclusive": sum(bands.values()) == len(rows),
        "depth_band_exhaustive": set(bands).issubset(set(DEPTH_BANDS)) and sum(bands.values()) == len(rows),
        "signal_T_uses_data_at_or_before_T": signal_as_of_ok and all(
            row["T_date"] >= row["event"].setup01.wave1_origin.pivot_date
            and row["T_date"] >= row["event"].setup01.wave1_peak.pivot_date
            and row["T_date"] >= row["event"].setup01.wave2_low.pivot_date
            and row["event"].setup01.as_of_date == row["T_date"]
            for row in rows
        ),
        "future_path_strictly_after_T": all(
            row["path"].target_1272_date is None or row["path"].target_1272_date > row["T_date"]
            for row in rows
        ),
        "future_path_used_only_for_outcome_evaluation": True,
        "common_normalized_excursion_formula_passed": common_scale_ok,
        "common_hurdle_levels_independent_of_r": common_hurdle_level_ok,
        "hurdle_dates_strictly_post_T": hurdle_future_date_ok,
        "unique_event_identity_count": len(identities),
    }


def _render_pct(value: Any, digits: int = 1) -> str:
    number = _number(value)
    return "—" if number is None else f"{number * 100:.{digits}f}%"


def _render_num(value: Any, digits: int = 3) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.{digits}f}"


def _render_outcome_table(lines: list[str], summaries: Mapping[str, Any]) -> None:
    lines.extend(
        [
            "| depth band | N | 1.272 before structural invalidation | structural invalidation first | ambiguous | censored | Fib1.618 before invalidation | median sessions to 1.272 | median sessions to invalidation |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for band in DEPTH_BANDS:
        summary = summaries[band]
        structural = summary["structural_continuation"]
        lines.append(
            f"| {band} | {summary['N']} | {structural['fib1272_before_structural_invalidation_count']} ({_render_pct(structural['fib1272_before_structural_invalidation_rate'])}) | "
            f"{structural['structural_invalidation_before_fib1272_count']} ({_render_pct(structural['structural_invalidation_before_fib1272_rate'])}) | {structural['same_bar_ambiguous_count']} | {structural['censored_count']} | "
            f"{structural['fib1618_before_structural_invalidation_count']} ({_render_pct(structural['fib1618_before_structural_invalidation_rate'])}) | "
            f"{_render_num(structural['sessions_to_fib1272']['median'], 1)} | {_render_num(structural['sessions_to_structural_invalidation']['median'], 1)} |"
        )


def render_markdown(document: Mapping[str, Any]) -> str:
    bands = document["depth_bands"]
    lines = [
        "# SETUP_01 Deep Wave2 Structure Quality V1",
        "",
        "> Development research only. This report does not propose or implement a Wave2 depth gate or an early-entry rule.",
        "",
        "## Research question and fixed protocol",
        "",
        "This study asks whether a deep Wave2 mainly indicates weaker Wave2→Wave3 structure, or whether the existing breakout confirmation / planned-entry geometry consumes most of the projected Wave3 space.",
        "",
        f"- Protocol: `{document['protocol_version']}`; scope: `{document['scope']['confirmed_events']}` existing SETUP_01 CONFIRMED events.",
        f"- Frozen session identity: `{document['scope']['development_session_identity']}`; bands are fixed at `r ≤ 0.618`, `0.618 < r ≤ 0.786`, and `r > 0.786`.",
        "- Primary structure outcome starts strictly after T. Target high and structural/scenario invalidation close use the existing contracts. Same future-bar target/invalidation is ambiguous; execution stop-first is not reused.",
        "- The 81-event Fib-near sample is the exact PR #86 category binding `SMALL_WAVE_FIB + BOTH_NEAR`, not a result-selected reclassification.",
        "",
        "## Frozen binding and controls",
        "",
        f"- Rebuilt confirmed events: **{document['validation']['confirmed_rebuilt_count']}**; PR #86 bound count: **{document['scope']['prior_confirmed_events']}**.",
        f"- PR #86 category conservation: `NEAR_SWING_ONLY={document['scope']['prior_category_counts']['NEAR_SWING_ONLY']}`, `SMALL_WAVE_FIB={document['scope']['prior_category_counts']['SMALL_WAVE_FIB']}`, `BOTH_NEAR={document['scope']['prior_category_counts']['BOTH_NEAR']}`; Fib-near = **{document['scope']['wave3_fib_near_events']}**.",
        f"- Fib identity max residual: `{document['validation']['fib_identity_1272']['max_absolute_residual']:.3e}`; passed = `{document['validation']['fib_identity_1272']['passed']}`.",
        "- Final OOS: not accessed. Parameter search: false. Threshold sweep: false. Production Decision/parameters: unchanged. State/Sheets writes and broker orders: 0.",
        "",
        "## Pure geometry decomposition",
        "",
        "`pre_confirmation_consumption` is the fraction of the projected Wave3 length consumed by the retracement before re-breaking Wave1 high. `post_confirmation_headroom_over_R` is the remaining normalized space after the T-day planned-entry extension.",
        "",
        "| depth band | N | r P25 / median / P75 | Wave1 gain median | Wave1 / ATR14 median | pre-consumption 1.272 median | pre-consumption 1.618 median | post-headroom 1.272 median | post-headroom 1.618 median | Fib1.272 upside <5% | Fib1.618 upside <5% |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for band in DEPTH_BANDS:
        geometry = bands[band]["geometry"]
        r_stats = geometry["r"]
        lines.append(
            f"| {band} | {bands[band]['N']} | {_render_num(r_stats['p25'])} / {_render_num(r_stats['median'])} / {_render_num(r_stats['p75'])} | {_render_pct(geometry['wave1_gain_pct']['median'])} | {_render_num(geometry['wave1_range_over_T_ATR14']['median'])} | {_render_pct(geometry['pre_confirmation_consumption_1272_median'])} | {_render_pct(geometry['pre_confirmation_consumption_1618_median'])} | {_render_num(geometry['post_confirmation_headroom_over_R_1272_median'])}R | {_render_num(geometry['post_confirmation_headroom_over_R_1618_median'])}R | {geometry['fib_1272_upside_below_5_count']} ({_render_pct(geometry['fib_1272_upside_below_5_share'])}) | {geometry['fib_1618_upside_below_5_count']} ({_render_pct(geometry['fib_1618_upside_below_5_share'])}) |"
        )
    lines.extend(
        [
            "",
            "## Geometry-controlled structural continuation",
            "",
            "These continuous outcomes use the common normalized distance from Wave1 high or planned_entry. The maximum is taken over strictly post-T bars before the structural-invalidation bar; if no invalidation occurs, bars through the frozen dataset end are used. Empty pre-invalidation paths are reported as censored/empty.",
            "",
            "| depth band | metric | N observed / total | P10 | P25 | median | P75 | P90 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    controlled_metrics = (
        "post_T_peak_extension_from_H1_over_R",
        "post_T_peak_extension_from_planned_entry_over_R",
        "post_T_peak_close_extension_from_H1_over_R",
    )
    metric_labels = {
        "post_T_peak_extension_from_H1_over_R": "max HIGH − H1 / R",
        "post_T_peak_extension_from_planned_entry_over_R": "max HIGH − planned_entry / R",
        "post_T_peak_close_extension_from_H1_over_R": "max CLOSE − H1 / R",
    }
    for band in DEPTH_BANDS:
        controlled = bands[band]["geometry_controlled"]["continuous_metrics"]
        for metric in controlled_metrics:
            item = controlled[metric]
            distribution = item["distribution"]
            lines.append(
                f"| {band} | {metric_labels[metric]} | {item['N_observed']} / {item['N_total']} | {_render_num(distribution['p10'])} | {_render_num(distribution['p25'])} | {_render_num(distribution['median'])} | {_render_num(distribution['p75'])} | {_render_num(distribution['p90'])} |"
            )
    lines.extend(
        [
            "",
            "### Common normalized hurdles",
            "",
            "The only pre-registered common hurdles are `H1 + 0.272R` and `H1 + 0.618R`; hurdle hit on the structural-invalidation bar is `SAME_BAR_AMBIGUOUS`.",
            "",
            "| depth band | hurdle | success | invalidation first | ambiguous | censored |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for band in DEPTH_BANDS:
        hurdles = bands[band]["geometry_controlled"]["hurdles"]
        for hurdle_name in ("HURDLE_0272", "HURDLE_0618"):
            item = hurdles[hurdle_name]
            outcomes = item["outcomes"]
            lines.append(
                f"| {band} | {hurdle_name} | {item['success_count']} ({_render_pct(item['success_rate'])}) | {outcomes['STRUCTURAL_INVALIDATION_BEFORE_HURDLE']['count']} ({_render_pct(outcomes['STRUCTURAL_INVALIDATION_BEFORE_HURDLE']['rate'])}) | {outcomes['SAME_BAR_AMBIGUOUS']['count']} | {outcomes['CENSORED_INSUFFICIENT_PATH']['count']} |"
            )
    lines.extend(["", "## Structural continuation by fixed depth band", ""])
    _render_outcome_table(lines, bands)
    lines.extend(
        [
            "",
            "Scenario invalidation is tracked separately. Under the existing close-based contract, Wave1 origin is below Wave2 low, so a distinct scenario-before-structural ordering is not expected; same-date relations remain visible in the JSON.",
            "",
            "## Structure quality × entry geometry",
            "",
            "The binary structure dimension is `FIB1272_BEFORE_STRUCTURAL_INVALIDATION` versus `STRUCTURAL_INVALIDATION_BEFORE_FIB1272`; ambiguous/censored rows remain outside the binary cells and are reported separately.",
            "",
            "| depth band | success + headroom ≥5% | success + headroom <5% | failure + headroom ≥5% | failure + headroom <5% | unresolved |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for band in DEPTH_BANDS:
        matrix = bands[band]["two_by_two"]["cells"]
        unresolved = sum(
            value["count"]
            for value in matrix["UNRESOLVED"].values()
        )
        lines.append(
            f"| {band} | {matrix['STRUCTURE_SUCCESS']['ENTRY_HEADROOM_GE_5_PCT']['count']} | {matrix['STRUCTURE_SUCCESS']['ENTRY_HEADROOM_LT_5_PCT']['count']} | {matrix['STRUCTURE_FAILURE']['ENTRY_HEADROOM_GE_5_PCT']['count']} | {matrix['STRUCTURE_FAILURE']['ENTRY_HEADROOM_LT_5_PCT']['count']} | {unresolved} |"
        )
    near = document["fib_near_81"]
    lines.extend(
        [
            "",
            "### Fixed 81-event Fib-near sample",
            "",
            f"- N = **{near['N']}**; category mix: `{near['category_counts']}`; VERY_DEEP = **{near['very_deep_count']}**.",
            f"- Strictly after T: **{near['fib1272_before_structural_invalidation_count']}** reached Fib1.272 before structural invalidation ({_render_pct(near['fib1272_before_structural_invalidation_rate'])}); headroom <5% = **{near['headroom_lt_5_count']}**, headroom ≥5% = **{near['headroom_ge_5_count']}**.",
            f"- Strict outcomes: `{near['strict_post_T_outcomes']}`. T-bar target crossings are not credited to this post-T continuation count.",
            f"- Geometry-controlled hurdle success: HURDLE_0272 `{near['geometry_controlled']['hurdles']['HURDLE_0272']['success_count']}/{near['N']}` ({_render_pct(near['geometry_controlled']['hurdles']['HURDLE_0272']['success_rate'])}); HURDLE_0618 `{near['geometry_controlled']['hurdles']['HURDLE_0618']['success_count']}/{near['N']}` ({_render_pct(near['geometry_controlled']['hurdles']['HURDLE_0618']['success_rate'])}).",
            "",
            "## Existing production Decision funnel",
            "",
            "These are the existing production Decision and exact T+1 OPEN classifications, grouped by the research-only depth bands. They are secondary context and are not used to relabel structural outcomes.",
            "",
            "| depth band | CONFIRMED | ABOVE_ENTRY_ZONE | TARGET_UPSIDE_BELOW_MINIMUM | RR_BELOW_MINIMUM | ENTRY_ALLOWED | T+1 EXECUTED | already excluded by T-day gates |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for band in DEPTH_BANDS:
        funnel = document["production_funnel"][band]
        lines.append(
            f"| {band} | {funnel['CONFIRMED']} | {funnel['ABOVE_ENTRY_ZONE']} | {funnel['TARGET_UPSIDE_BELOW_MINIMUM']} | {funnel['RR_BELOW_MINIMUM']} | {funnel['ENTRY_ALLOWED']} | {funnel['T+1_EXECUTED']} | {funnel['excluded_by_current_T_day_gates']} ({_render_pct(funnel['excluded_by_current_T_day_gates_share'])}) |"
        )
    lines.extend(
        [
            "",
            f"VERY_DEEP has `{document['production_funnel']['VERY_DEEP']['ENTRY_ALLOWED']}` ENTRY_ALLOWED and `{document['production_funnel']['VERY_DEEP']['T+1_EXECUTED']}` EXECUTED rows in this development funnel; a new depth gate would therefore have no incremental effect on this sample after the existing gates.",
            "",
            "## Robustness",
            "",
            "### CN / US",
            "",
            "| market | depth band | N | structural success rate | Fib1.618 before invalidation rate |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for market in sorted(document["robustness"]["market"]):
        for band in DEPTH_BANDS:
            item = document["robustness"]["market"][market][band]
            lines.append(
                f"| {market} | {band} | {item['N']} | {_render_pct(item['structural_success_rate'])} | {_render_pct(item['fib1618_before_structural_invalidation_rate'])} |"
            )
    lines.extend(
        [
            "",
            "### Development time halves",
            "",
            f"Split definition: {document['robustness']['time_half']['split_definition']}. Cutoffs: `{document['robustness']['time_half']['cutoff_by_market']}`.",
            "",
            "| half | depth band | N | structural success rate |",
            "|---|---|---:|---:|",
        ]
    )
    for half_name in ("FIRST_HALF", "SECOND_HALF"):
        for band in DEPTH_BANDS:
            item = document["robustness"]["time_half"]["results"][half_name][band]
            lines.append(f"| {half_name} | {band} | {item['N']} | {_render_pct(item['structural_success_rate'])} |")
    lines.extend(["", "### Symbol concentration", "", "| depth band | symbol count | top-5 event share | max symbol share | HHI | success rate excluding top symbol |", "|---|---:|---:|---:|---:|---:|"])
    for band in DEPTH_BANDS:
        item = document["robustness"]["symbol_concentration"][band]
        lines.append(
            f"| {band} | {item['symbol_count']} | {_render_pct(item['top_5_event_share'])} | {_render_pct(item['max_symbol_event_share'])} | {_render_num(item['event_count_hhi'], 4)} | {_render_pct(item['structural_success_rate_excluding_top_symbol'])} |"
        )
    lines.extend(
        [
            "",
            "### Geometry-controlled CN / US",
            "",
            "| market | depth band | N | H1 max-HIGH median / R | planned-entry max-HIGH median / R | max-CLOSE median / R | HURDLE_0272 | HURDLE_0618 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in sorted(document["robustness"]["geometry_controlled"]["market"]):
        for band in DEPTH_BANDS:
            item = document["robustness"]["geometry_controlled"]["market"][market][band]
            metrics = item["continuous_metrics"]
            lines.append(
                f"| {market} | {band} | {item['N']} | {_render_num(metrics['post_T_peak_extension_from_H1_over_R']['distribution']['median'])} | {_render_num(metrics['post_T_peak_extension_from_planned_entry_over_R']['distribution']['median'])} | {_render_num(metrics['post_T_peak_close_extension_from_H1_over_R']['distribution']['median'])} | {_render_pct(item['hurdles']['HURDLE_0272']['success_rate'])} | {_render_pct(item['hurdles']['HURDLE_0618']['success_rate'])} |"
            )
    lines.extend(
        [
            "",
            "### Geometry-controlled development time halves",
            "",
            "| half | depth band | N | H1 max-HIGH median / R | max-CLOSE median / R | HURDLE_0272 | HURDLE_0618 |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for half_name in ("FIRST_HALF", "SECOND_HALF"):
        for band in DEPTH_BANDS:
            item = document["robustness"]["geometry_controlled"]["time_half"]["results"][half_name][band]
            metrics = item["continuous_metrics"]
            lines.append(
                f"| {half_name} | {band} | {item['N']} | {_render_num(metrics['post_T_peak_extension_from_H1_over_R']['distribution']['median'])} | {_render_num(metrics['post_T_peak_close_extension_from_H1_over_R']['distribution']['median'])} | {_render_pct(item['hurdles']['HURDLE_0272']['success_rate'])} | {_render_pct(item['hurdles']['HURDLE_0618']['success_rate'])} |"
            )
    lines.extend(
        [
            "",
            "### Geometry-controlled symbol concentration check",
            "",
            "The existing top-5/max-share/HHI concentration table is retained above. The following corrected metric is recomputed after excluding the count-leading symbol in each band (the symbol is selected by event count, not by outcome).",
            "",
            "| depth band | H1 max-HIGH median / R excluding top symbol | max-CLOSE median / R excluding top symbol | HURDLE_0272 excluding top symbol | HURDLE_0618 excluding top symbol |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for band in DEPTH_BANDS:
        item = document["robustness"]["symbol_concentration"][band]["geometry_controlled_excluding_top_symbol"]
        metrics = item["continuous_metrics"]
        lines.append(
            f"| {band} | {_render_num(metrics['post_T_peak_extension_from_H1_over_R']['distribution']['median'])} | {_render_num(metrics['post_T_peak_close_extension_from_H1_over_R']['distribution']['median'])} | {_render_pct(item['hurdles']['HURDLE_0272']['success_rate'])} | {_render_pct(item['hurdles']['HURDLE_0618']['success_rate'])} |"
        )
    lines.extend(
        [
            "",
            "## Secondary executed-performance context",
            "",
            "This section is not the primary test, is not a random control, and is not evidence for selecting a depth rule. Executed samples are especially small.",
            "",
            "| depth band | executed | closed | open/censored | gross expectancy R | win rate | profit factor | stop-out |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for band in DEPTH_BANDS:
        item = document["secondary_executed_performance"][band]
        lines.append(
            f"| {band} | {item['executed']} | {item['closed']} | {item['open_censored']} | {_render_num(item['gross_expectancy_R'], 3)} | {_render_pct(item['gross_win_rate'])} | {_render_num(item['gross_profit_factor'], 3)} | {item['stop_out_count']} ({_render_pct(item['stop_out_rate'])}) |"
        )
    lines.extend(
        [
            "",
            "## Evidence judgment",
            "",
            f"**{document['decision']['classification']}**",
            "",
            document["decision"]["reason"],
            "",
            "This is a research prioritization signal only. It does not change Wave2 eligibility, confirmation, Entry Zone, Stop, Target, R/R, production Decision, or execution. Any early-entry work would require a separate causal research protocol; the current study does not create an early-entry rule.",
            "",
            "## Controls",
            "",
            "- Final OOS access: `false`",
            "- Parameter search: `false`; threshold sweep: `false`",
            "- Production strategy / Decision modified: `false`",
            "- Production/state/Sheets writes: `0`; broker orders: `0`",
            "- PR #82 mixed in: `false`",
            "",
            f"Status: `{document['status']}`.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_research(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    replay_input_path: Path = DEFAULT_REPLAY_INPUT,
    replay_wrapper_path: Path = DEFAULT_REPLAY_WRAPPER,
    prior_structure_path: Path = DEFAULT_PRIOR_STRUCTURE,
    prior_geometry_path: Path = DEFAULT_PRIOR_GEOMETRY,
    json_output_path: Path = DEFAULT_JSON_OUTPUT,
    markdown_output_path: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    manifest, symbol_quotes, replay_manifest = load_frozen_holdout(
        manifest_path, replay_input_path, replay_wrapper_path
    )
    prior_structure = _load_json(prior_structure_path)
    prior_geometry = _load_json(prior_geometry_path)
    prior = _validate_prior_artifacts(
        prior_structure,
        prior_geometry,
        prior_structure_path=prior_structure_path,
        manifest=manifest,
        replay_manifest=replay_manifest,
    )

    events = _replay_confirmed_events(symbol_quotes)
    if len(events) != prior["confirmed_count"]:
        raise ValueError(
            f"frozen confirmed count changed: replay={len(events)}, prior={prior['confirmed_count']}"
        )
    event_by_identity = {event.event_identity: event for event in events}
    if set(event_by_identity) != set(prior["prior_by_identity"]):
        raise ValueError("current replay event identity set does not match PR #86")

    decision_stream = evaluate_setup01_decision_stream(events, symbol_quotes)
    decisions = tuple(decision_stream.decisions)
    decisions_by_identity = {decision.event_identity: decision for decision in decisions}
    executions_by_identity = {execution.event_identity: execution for execution in decision_stream.executions}
    parity = _decision_cross_binding(decisions, prior["prior_by_identity"])
    if not parity["gate_action_target_parity"]:
        raise ValueError(f"current Decision parity failed: {parity['mismatches'][:3]}")

    sessions = build_market_session_dates(symbol_quotes)
    records: list[dict[str, Any]] = []
    for event in events:
        decision = decisions_by_identity[event.event_identity]
        path, target_1272, target_1618 = _path_result(event, symbol_quotes[event.symbol], sessions)
        geometry_controlled = _geometry_controlled_path(
            event,
            decision,
            symbol_quotes[event.symbol],
            path,
        )
        record = _geometry_record(
            event,
            decision,
            prior["prior_by_identity"][event.event_identity],
            path,
            geometry_controlled,
            target_1272,
            target_1618,
        )
        record["event"] = event
        record["quotes"] = symbol_quotes[event.symbol]
        records.append(record)

    validation = _validate_records(
        records,
        prior_count=prior["confirmed_count"],
        near_event_identities=prior["near_event_identities"],
    )
    if not all(
        (
            validation["confirmed_count_matches_prior_artifact"],
            validation["event_identity_set_matches_prior_near_binding"],
            validation["fib_identity_1272"]["passed"],
            validation["depth_band_mutually_exclusive"],
            validation["depth_band_exhaustive"],
            validation["signal_T_uses_data_at_or_before_T"],
            validation["future_path_strictly_after_T"],
            validation["common_normalized_excursion_formula_passed"],
            validation["common_hurdle_levels_independent_of_r"],
            validation["hurdle_dates_strictly_post_T"],
        )
    ):
        raise AssertionError(f"research validation failed: {validation}")

    by_band = {
        band: [row for row in records if row["depth_band"] == band]
        for band in DEPTH_BANDS
    }
    depth_summaries = {band: _summarize_band(by_band[band]) for band in DEPTH_BANDS}
    for band in DEPTH_BANDS:
        depth_summaries[band]["two_by_two"] = _two_by_two(by_band[band])
        depth_summaries[band]["geometry_controlled"] = _geometry_controlled_summary(
            by_band[band]
        )

    near_sample = _near_sample(records, prior["near_event_identities"])
    production_funnel = _production_funnel(records, executions_by_identity)
    secondary_performance = _secondary_performance(records, symbol_quotes, executions_by_identity)

    normal_success = depth_summaries["NORMAL_OR_SHALLOW"]["structural_continuation"]["fib1272_before_structural_invalidation_rate"]
    very_success = depth_summaries["VERY_DEEP"]["structural_continuation"]["fib1272_before_structural_invalidation_rate"]
    controlled_normal = depth_summaries["NORMAL_OR_SHALLOW"]["geometry_controlled"]
    controlled_deep = depth_summaries["DEEP"]["geometry_controlled"]
    controlled_very = depth_summaries["VERY_DEEP"]["geometry_controlled"]
    controlled_normal_h1 = controlled_normal["continuous_metrics"][
        "post_T_peak_extension_from_H1_over_R"
    ]["distribution"]["median"]
    controlled_deep_h1 = controlled_deep["continuous_metrics"][
        "post_T_peak_extension_from_H1_over_R"
    ]["distribution"]["median"]
    controlled_very_h1 = controlled_very["continuous_metrics"][
        "post_T_peak_extension_from_H1_over_R"
    ]["distribution"]["median"]
    controlled_normal_h272 = controlled_normal["hurdles"]["HURDLE_0272"]["success_rate"]
    controlled_deep_h272 = controlled_deep["hurdles"]["HURDLE_0272"]["success_rate"]
    controlled_very_h272 = controlled_very["hurdles"]["HURDLE_0272"]["success_rate"]
    controlled_normal_h618 = controlled_normal["hurdles"]["HURDLE_0618"]["success_rate"]
    controlled_deep_h618 = controlled_deep["hurdles"]["HURDLE_0618"]["success_rate"]
    controlled_very_h618 = controlled_very["hurdles"]["HURDLE_0618"]["success_rate"]
    early_entry_reason = (
        f"The original Fib1.272 continuation rates ({normal_success:.1%} / {depth_summaries['DEEP']['structural_continuation']['fib1272_before_structural_invalidation_rate']:.1%} / {very_success:.1%}) are not used as independent quality evidence because the target distance shrinks mechanically with r. "
        f"After controlling the common normalized distance, H1-extension medians are {controlled_normal_h1:.3f}R / {controlled_deep_h1:.3f}R / {controlled_very_h1:.3f}R, and HURDLE_0272 success is {controlled_normal_h272:.1%} / {controlled_deep_h272:.1%} / {controlled_very_h272:.1%}; HURDLE_0618 success is {controlled_normal_h618:.1%} / {controlled_deep_h618:.1%} / {controlled_very_h618:.1%}. "
        "These descriptive geometry-controlled results do not show weaker post-confirmation continuation for deep Wave2, conditional on having reached CONFIRMED. "
        f"The fixed 81-event Fib-near sample remains {near_sample['fib1272_before_structural_invalidation_count']}/{near_sample['N']} strict post-T Fib1.272 successes, including {near_sample['very_deep_count']} VERY_DEEP, but confirmed-only outcomes do not prove pre-confirmation early-entry effectiveness. "
        "They support prioritizing a separate PRE-CONFIRMATION causal study as a research hypothesis, not deleting deep Wave2 contexts. "
        f"At the same time, existing T-day gates already exclude all {production_funnel['VERY_DEEP']['CONFIRMED'] - production_funnel['VERY_DEEP']['ENTRY_ALLOWED']} VERY_DEEP events from ENTRY_ALLOWED in this development funnel, "
        "so a new depth gate would be redundant here; no production change is authorized by this result."
    )

    document: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "artifact_type": "SETUP_01_DEEP_WAVE2_STRUCTURE_QUALITY",
        "artifact_version": "v1",
        "analysis_date": "2026-09-16",
        "status": "READY_FOR_DECISION",
        "protocol": {
            "primary_outcome_scope": "strictly post-T future path until existing close-based structural invalidation or frozen-dataset censoring",
            "depth_bands": {
                "NORMAL_OR_SHALLOW": "r <= 0.618",
                "DEEP": "0.618 < r <= 0.786",
                "VERY_DEEP": "r > 0.786",
            },
            "common_hurdles": dict(COMMON_HURDLES),
            "target_1272_ratio": FIB_1_272_RATIO,
            "target_1618_ratio": FIB_1_618_RATIO,
            "same_bar_ordering": "AMBIGUOUS unless an existing structural ordering contract applies; execution stop-first is not reused",
            "threshold_search": False,
            "parameter_search": False,
        },
        "scope": {
            "confirmed_events": len(events),
            "prior_confirmed_events": prior["confirmed_count"],
            "development_session_identity": DEVELOPMENT_SESSION_IDENTITY,
            "depth_bands": {
                "NORMAL_OR_SHALLOW": "r <= 0.618",
                "DEEP": "0.618 < r <= 0.786",
                "VERY_DEEP": "r > 0.786",
            },
            "prior_category_counts": prior["prior_category_counts"],
            "wave3_fib_near_events": prior["wave3_fib_near_count"],
        },
        "source_artifacts": {
            "dataset_manifest": {
                "path": _repo_relative_path(manifest_path),
                "dataset_version": manifest["dataset_version"],
                "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
                "replay_input_aggregate_hash": replay_manifest.aggregate_hash,
                "symbol_count": replay_manifest.total_symbol_count,
                "bar_count": replay_manifest.total_bar_count,
            },
            "prior_structure_scale": {
                "path": _repo_relative_path(prior_structure_path),
                "sha256": prior["structure_artifact_sha256"],
            },
            "prior_geometry_attribution": {
                "path": _repo_relative_path(prior_geometry_path),
                "sha256": _sha256_file(prior_geometry_path),
            },
        },
        "depth_bands": depth_summaries,
        "fib_near_81": near_sample,
        "production_funnel": production_funnel,
        "secondary_executed_performance": secondary_performance,
        "robustness": {
            "market": _market_robustness(records),
            "time_half": _time_half_robustness(records, sessions),
            "symbol_concentration": _concentration(records),
            "geometry_controlled": {
                "market": _geometry_controlled_market_robustness(records),
                "time_half": _geometry_controlled_time_half_robustness(records, sessions),
            },
        },
        "event_level_detail": _ephemeral_event_detail_summary(records),
        "validation": {
            **validation,
            "prior_decision_gate_action_target_parity": parity,
        },
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "parameter_search": False,
            "threshold_sweep": False,
            "signal_T_uses_future_data": False,
            "future_path_used_only_for_post_T_outcome_evaluation": True,
            "t_plus_1_open_used_only_for_secondary_production_funnel": True,
            "production_decision_modified": False,
            "production_parameters_modified": False,
            "new_production_gate_added": False,
            "new_threshold_selected": False,
            "target_redefined": False,
            "wave_or_swing_semantics_modified": False,
            "state_writes": 0,
            "sheets_writes": 0,
            "broker_orders": 0,
            "pr82_mixed_in": False,
            "event_level_detail_persisted": False,
            "event_level_detail_schema": EVENT_DETAIL_SCHEMA_VERSION,
        },
        "decision": {
            "classification": "EARLY_ENTRY_RESEARCH_CANDIDATE",
            "reason": early_entry_reason,
            "production_change": "none; requires a separately approved causal research protocol",
        },
    }
    _write_json(json_output_path, document)
    markdown_output_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_output_path.write_text(render_markdown(document), encoding="utf-8")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--replay-input", type=Path, default=DEFAULT_REPLAY_INPUT)
    parser.add_argument("--replay-wrapper", type=Path, default=DEFAULT_REPLAY_WRAPPER)
    parser.add_argument("--prior-structure", type=Path, default=DEFAULT_PRIOR_STRUCTURE)
    parser.add_argument("--prior-geometry", type=Path, default=DEFAULT_PRIOR_GEOMETRY)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args(argv)
    document = run_research(
        manifest_path=args.manifest,
        replay_input_path=args.replay_input,
        replay_wrapper_path=args.replay_wrapper,
        prior_structure_path=args.prior_structure,
        prior_geometry_path=args.prior_geometry,
        json_output_path=args.json_output,
        markdown_output_path=args.markdown_output,
    )
    print(
        "SETUP01_DEEP_WAVE2_STRUCTURE_QUALITY_SUMMARY "
        + json.dumps(
            {
                "status": document["status"],
                "classification": document["decision"]["classification"],
                "confirmed": document["scope"]["confirmed_events"],
                "depth_counts": {
                    band: document["depth_bands"][band]["N"] for band in DEPTH_BANDS
                },
                "fib_near_81": document["fib_near_81"]["N"],
                "controls": document["controls"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

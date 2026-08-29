"""Read-only lifecycle attribution for the frozen Phase 5J-v4 protocol.

The actual trace is emitted by the production SETUP_03 state-machine loop with
additive diagnostics.  This module classifies differences; it does not contain
platform, swing, structure, breakout, or invalidation formulas.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from core import Quote
from research.phase5j_v4_protocol import EXPECTED_PROTOCOL_SHA256, canonical_json, load_protocol
from trading.models import SetupState
from trading.setup import SetupGateReason, detect_platform_breakout_history_with_diagnostics
from trading.swing import find_swings


TRACE_SCHEMA_VERSION = "setup03-phase5j-v4-lifecycle-trace-v1"
ATTRIBUTION_SCHEMA_VERSION = "setup03-phase5j-v4-lifecycle-attribution-v1"
TOLERANCES = (0.03, 0.04, 0.05)
ADJACENT_PAIRS = ((0.03, 0.04), (0.04, 0.05))
SETUP_PARAMETERS = {"swing_lookback": 5, "platform_window": 40, "arm_proximity_pct": 0.0}

ROOT_CAUSES = (
    "HIGH_SPAN_THRESHOLD_CROSSING",
    "LOW_SPAN_THRESHOLD_CROSSING",
    "BOTH_SPAN_THRESHOLD_CROSSING",
    "STRUCTURE_INPUT_DIVERGENCE",
    "NEW_SWING_ELIGIBILITY_DIVERGENCE",
    "PLATFORM_FIRST_DETECTION_DIVERGENCE",
    "FROZEN_BREAKOUT_ANCHOR_DIVERGENCE",
    "FROZEN_INVALIDATION_ANCHOR_DIVERGENCE",
    "TERMINAL_STATE_DIVERGENCE",
    "OTHER_UNCLASSIFIED",
)
PROPAGATION_CLASSES = (
    "NO_CASCADE",
    "TERMINAL_INDEX_CASCADE",
    "ANCHOR_PROPAGATION",
    "ELIGIBILITY_CASCADE",
    "MULTI_STAGE_CASCADE",
)

_CORRECTNESS_FIELDS = (
    "confirmed_swing_identities_available_as_of_t",
    "new_confirmed_swing_eligibility",
    "high_swing_count",
    "low_swing_count",
    "market_structure_classification",
    "high_span",
    "low_span",
    "platform_gate_pass",
    "platform_gate_failure_reasons",
    "platform_detected_this_bar",
    "setup_state",
    "detected_index",
    "state_entered_index",
    "breakout_price",
    "structural_invalidation",
    "confirmed_index",
    "terminal_type",
    "terminal_date",
    "last_terminal_index",
    "arm_threshold",
)


def _float_hex(value: float | None) -> str | None:
    return None if value is None else float(value).hex()


def _terminal_type(index: int, setup: Any, diagnostics: Any) -> str | None:
    if setup.state is SetupState.CONFIRMED and setup.confirmed_index == index:
        return SetupState.CONFIRMED.value
    if (
        setup.state is SetupState.FAILED
        and setup.state_entered_index == index
        and diagnostics.reason is SetupGateReason.STRUCTURAL_INVALIDATION
    ):
        return SetupState.FAILED.value
    return None


def build_symbol_trace(
    quotes: list[Quote],
    tolerance: float,
) -> dict[str, Any]:
    """Build an every-bar trace from the production state-machine history."""
    if tolerance not in TOLERANCES:
        raise ValueError(f"Phase 5J-v4 trace tolerance is not frozen: {tolerance}")
    protocol = load_protocol()
    if protocol["integrity"]["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Phase 5J-v4 protocol pin changed")
    swings = find_swings(quotes, lookback=SETUP_PARAMETERS["swing_lookback"])
    history = detect_platform_breakout_history_with_diagnostics(
        quotes,
        **SETUP_PARAMETERS,
        platform_tolerance_pct=tolerance,
        swings=swings,
    )
    rows: list[dict[str, Any]] = []
    active_ordinal: int | None = None
    next_ordinal = 1
    for index, (quote, calculation) in enumerate(zip(quotes, history)):
        setup, diagnostics = calculation.setup, calculation.diagnostics
        terminal_type = _terminal_type(index, setup, diagnostics)
        if diagnostics.platform_detected_this_bar:
            active_ordinal = next_ordinal
            next_ordinal += 1
        failure_reasons = (
            [reason.value for reason in diagnostics.auxiliary_failed_conditions]
            if diagnostics.platform_search_evaluated
            else []
        )
        row = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "market": quote.market,
            "symbol": quote.symbol,
            "trade_date": quote.trade_date.isoformat(),
            "bar_index": index,
            "tolerance": tolerance,
            "confirmed_swing_identities_available_as_of_t": [
                list(identity)
                for identity in diagnostics.confirmed_swing_identities_available_as_of_t
            ],
            "new_confirmed_swing_eligibility": diagnostics.new_confirmed_swing_eligibility,
            "high_swing_count": diagnostics.high_count,
            "low_swing_count": diagnostics.low_count,
            "market_structure_classification": diagnostics.trend.value if diagnostics.trend else None,
            "high_span": diagnostics.high_span,
            "low_span": diagnostics.low_span,
            "platform_gate_pass": diagnostics.platform_gate_pass,
            "platform_gate_failure_reasons": failure_reasons,
            "platform_search_evaluated": diagnostics.platform_search_evaluated,
            "platform_detected_this_bar": diagnostics.platform_detected_this_bar,
            "setup_state": setup.state.value,
            "detected_index": setup.detected_index,
            "state_entered_index": setup.state_entered_index,
            "breakout_price": setup.breakout_price,
            "structural_invalidation": setup.structural_invalidation,
            "confirmed_index": setup.confirmed_index,
            "terminal_type": terminal_type,
            "terminal_date": quote.trade_date.isoformat() if terminal_type else None,
            "last_terminal_index": diagnostics.last_terminal_index,
            "arm_threshold": diagnostics.arm_threshold,
            "lifecycle_ordinal": active_ordinal,
            "close": float(quote.close),
        }
        rows.append(row)
        if terminal_type:
            active_ordinal = None
    lifecycles = extract_lifecycles(rows)
    return {"rows": rows, "lifecycles": lifecycles}


def extract_lifecycles(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project platform detections and their terminal states into identities."""
    lifecycles: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for row in rows:
        if row["platform_detected_this_bar"]:
            if active is not None:
                raise ValueError("new platform detected before the active lifecycle terminated")
            active = {
                "market": row["market"],
                "symbol": row["symbol"],
                "tolerance": row["tolerance"],
                "lifecycle_ordinal": row["lifecycle_ordinal"],
                "first_detected_index": row["bar_index"],
                "first_detected_date": row["trade_date"],
                "frozen_breakout": row["breakout_price"],
                "frozen_invalidation": row["structural_invalidation"],
                "terminal_index": None,
                "terminal_date": None,
                "terminal_type": None,
                "root_swing_identity": deepcopy(row["confirmed_swing_identities_available_as_of_t"]),
            }
        if row["terminal_type"] is not None:
            if active is None:
                raise ValueError("terminal state has no detected lifecycle")
            active["terminal_index"] = row["bar_index"]
            active["terminal_date"] = row["terminal_date"]
            active["terminal_type"] = row["terminal_type"]
            lifecycles.append(active)
            active = None
    if active is not None:
        lifecycles.append(active)
    ordinals = [item["lifecycle_ordinal"] for item in lifecycles]
    if ordinals != list(range(1, len(lifecycles) + 1)):
        raise ValueError("lifecycle ordinals are not deterministic and conserved")
    return lifecycles


def correctness_view(row: Mapping[str, Any]) -> tuple[Any, ...]:
    values: list[Any] = []
    for field in _CORRECTNESS_FIELDS:
        value = row.get(field)
        if field == "platform_gate_failure_reasons":
            # Auxiliary reasons explain a failed search, but two tolerances that
            # both fail have not yet forked the platform/state/lifecycle.  The
            # exact reasons remain in the trace and are consumed when gate pass
            # differs; equivalence uses the effective production outcome.
            value = ("GATE_FAILED",) if row.get("platform_gate_pass") is False else ()
        if field in {"high_span", "low_span", "breakout_price", "structural_invalidation", "arm_threshold"}:
            value = _float_hex(value)
        elif isinstance(value, list):
            value = tuple(tuple(item) if isinstance(item, list) else item for item in value)
        values.append(value)
    return tuple(values)


def _condition_causes(lower: Mapping[str, Any], upper: Mapping[str, Any]) -> list[str]:
    lower_fail = set(lower.get("platform_gate_failure_reasons", ()))
    upper_fail = set(upper.get("platform_gate_failure_reasons", ()))
    high_cross = (SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE.value in lower_fail) != (
        SetupGateReason.HIGH_SPAN_EXCEEDS_TOLERANCE.value in upper_fail
    )
    low_cross = (SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE.value in lower_fail) != (
        SetupGateReason.LOW_SPAN_EXCEEDS_TOLERANCE.value in upper_fail
    )
    causes: list[str] = []
    if high_cross and low_cross:
        causes.append("BOTH_SPAN_THRESHOLD_CROSSING")
    elif high_cross:
        causes.append("HIGH_SPAN_THRESHOLD_CROSSING")
    elif low_cross:
        causes.append("LOW_SPAN_THRESHOLD_CROSSING")
    structure_fields = (
        "confirmed_swing_identities_available_as_of_t",
        "high_swing_count",
        "low_swing_count",
        "market_structure_classification",
    )
    if any(lower.get(field) != upper.get(field) for field in structure_fields) and lower.get(
        "new_confirmed_swing_eligibility"
    ) == upper.get("new_confirmed_swing_eligibility"):
        causes.append("STRUCTURE_INPUT_DIVERGENCE")
    if lower.get("new_confirmed_swing_eligibility") != upper.get("new_confirmed_swing_eligibility"):
        causes.append("NEW_SWING_ELIGIBILITY_DIVERGENCE")
    if (
        lower.get("platform_detected_this_bar") != upper.get("platform_detected_this_bar")
        or lower.get("detected_index") != upper.get("detected_index")
    ):
        causes.append("PLATFORM_FIRST_DETECTION_DIVERGENCE")
    if _float_hex(lower.get("breakout_price")) != _float_hex(upper.get("breakout_price")):
        causes.append("FROZEN_BREAKOUT_ANCHOR_DIVERGENCE")
    if _float_hex(lower.get("structural_invalidation")) != _float_hex(upper.get("structural_invalidation")):
        causes.append("FROZEN_INVALIDATION_ANCHOR_DIVERGENCE")
    terminal_fields = ("setup_state", "confirmed_index", "terminal_type", "terminal_date", "last_terminal_index")
    if any(lower.get(field) != upper.get(field) for field in terminal_fields):
        causes.append("TERMINAL_STATE_DIVERGENCE")
    return causes


def classify_first_divergence(
    lower: Mapping[str, Any], upper: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply the frozen ordered taxonomy at one FIRST_DIVERGENCE_BAR."""
    if correctness_view(lower) == correctness_view(upper):
        raise ValueError("root classification requires a real correctness-relevant divergence")
    observed = _condition_causes(lower, upper)
    primary = next((cause for cause in ROOT_CAUSES[:-1] if cause in observed), "OTHER_UNCLASSIFIED")
    return {
        "primary_root_cause": primary,
        "secondary_causes": [cause for cause in observed if cause != primary],
    }


def find_divergence_episodes(
    lower_rows: Sequence[Mapping[str, Any]],
    upper_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if len(lower_rows) != len(upper_rows):
        raise ValueError("adjacent lifecycle traces are not bar-aligned")
    episodes: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for lower, upper in zip(lower_rows, upper_rows):
        if (lower["market"], lower["symbol"], lower["trade_date"], lower["bar_index"]) != (
            upper["market"], upper["symbol"], upper["trade_date"], upper["bar_index"]
        ):
            raise ValueError("adjacent lifecycle trace identity alignment failed")
        divergent = correctness_view(lower) != correctness_view(upper)
        if divergent and active is None:
            classification = classify_first_divergence(lower, upper)
            active = {
                "episode_ordinal": len(episodes) + 1,
                "market": lower["market"],
                "symbol": lower["symbol"],
                "lower_tolerance": lower["tolerance"],
                "upper_tolerance": upper["tolerance"],
                "first_divergence_bar": lower["bar_index"],
                "first_divergence_date": lower["trade_date"],
                "last_divergence_bar": lower["bar_index"],
                "last_divergence_date": lower["trade_date"],
                "divergent_bar_count": 1,
                "lower_lifecycle_ordinal": lower.get("lifecycle_ordinal"),
                "upper_lifecycle_ordinal": upper.get("lifecycle_ordinal"),
                "high_span": lower.get("high_span"),
                "low_span": lower.get("low_span"),
                "distance_from_lower_frozen_tolerance_threshold": {
                    "high": None if lower.get("high_span") is None else lower["high_span"] - lower["tolerance"],
                    "low": None if lower.get("low_span") is None else lower["low_span"] - lower["tolerance"],
                },
                "distance_from_upper_frozen_tolerance_threshold": {
                    "high": None if lower.get("high_span") is None else lower["high_span"] - upper["tolerance"],
                    "low": None if lower.get("low_span") is None else lower["low_span"] - upper["tolerance"],
                },
                **classification,
            }
        elif divergent:
            assert active is not None
            active["last_divergence_bar"] = lower["bar_index"]
            active["last_divergence_date"] = lower["trade_date"]
            active["divergent_bar_count"] += 1
        elif active is not None:
            episodes.append(active)
            active = None
    if active is not None:
        episodes.append(active)
    return episodes


def _signature(lifecycle: Mapping[str, Any]) -> str:
    return canonical_json(lifecycle.get("root_swing_identity", []))


def classify_lineage(
    lower_lifecycles: Sequence[Mapping[str, Any]],
    upper_lifecycles: Sequence[Mapping[str, Any]],
    *,
    first_divergence_bar: int | None,
) -> list[dict[str, Any]]:
    """Classify deterministic lifecycle lineage by frozen swing-root identity."""
    lower_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    upper_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in lower_lifecycles:
        lower_groups[_signature(item)].append(item)
    for item in upper_lifecycles:
        upper_groups[_signature(item)].append(item)
    rows: list[dict[str, Any]] = []
    for signature in sorted(set(lower_groups) | set(upper_groups)):
        lower = sorted(lower_groups.get(signature, []), key=lambda item: item["lifecycle_ordinal"])
        upper = sorted(upper_groups.get(signature, []), key=lambda item: item["lifecycle_ordinal"])
        if len(lower) == 1 and len(upper) == 1:
            left, right = lower[0], upper[0]
            same_anchor = (
                _float_hex(left["frozen_breakout"]) == _float_hex(right["frozen_breakout"])
                and _float_hex(left["frozen_invalidation"]) == _float_hex(right["frozen_invalidation"])
            )
            same_terminal = (left["terminal_date"], left["terminal_type"]) == (
                right["terminal_date"], right["terminal_type"]
            )
            if same_anchor and same_terminal:
                lineage_class = "SAME_ROOT_SAME_TERMINAL"
            elif same_anchor:
                lineage_class = "SAME_ROOT_SHIFTED_TERMINAL"
            else:
                lineage_class = "SAME_ROOT_DIFFERENT_ANCHOR"
            rows.append(_lineage_row(signature, left, right, lineage_class))
            continue
        if lower and upper:
            lineage_class = "SPLIT" if len(upper) > len(lower) else "MERGE" if len(lower) > len(upper) else "SAME_ROOT_SHIFTED_TERMINAL"
            for index in range(max(len(lower), len(upper))):
                rows.append(_lineage_row(signature, lower[index] if index < len(lower) else None, upper[index] if index < len(upper) else None, lineage_class))
            continue
        items = lower or upper
        for item in items:
            is_descendant = first_divergence_bar is not None and item["first_detected_index"] > first_divergence_bar
            lineage_class = "CASCADE_DESCENDANT" if is_descendant else (
                "DISAPPEARED_LIFECYCLE" if lower else "ADDED_LIFECYCLE"
            )
            rows.append(_lineage_row(signature, item if lower else None, item if upper else None, lineage_class))
    rows.sort(key=lambda row: (
        row["lower_lifecycle_ordinal"] or 10**9,
        row["upper_lifecycle_ordinal"] or 10**9,
        row["lineage_class"],
    ))
    return rows


def _lineage_row(
    signature: str,
    lower: Mapping[str, Any] | None,
    upper: Mapping[str, Any] | None,
    lineage_class: str,
) -> dict[str, Any]:
    sample = lower or upper
    assert sample is not None
    return {
        "market": sample["market"],
        "symbol": sample["symbol"],
        "root_swing_identity_sha256": f"sha256:{hashlib.sha256(signature.encode('utf-8')).hexdigest()}",
        "lower_tolerance": lower["tolerance"] if lower else None,
        "upper_tolerance": upper["tolerance"] if upper else None,
        "lower_lifecycle_ordinal": lower["lifecycle_ordinal"] if lower else None,
        "upper_lifecycle_ordinal": upper["lifecycle_ordinal"] if upper else None,
        "lower_first_detected_index": lower["first_detected_index"] if lower else None,
        "upper_first_detected_index": upper["first_detected_index"] if upper else None,
        "lower_terminal_index": lower["terminal_index"] if lower else None,
        "upper_terminal_index": upper["terminal_index"] if upper else None,
        "breakout_anchor_difference": None if not (lower and upper) else upper["frozen_breakout"] - lower["frozen_breakout"],
        "invalidation_anchor_difference": None if not (lower and upper) else upper["frozen_invalidation"] - lower["frozen_invalidation"],
        "detection_shift": None if not (lower and upper) else upper["first_detected_index"] - lower["first_detected_index"],
        "terminal_shift": None if not (lower and upper) or lower["terminal_index"] is None or upper["terminal_index"] is None else upper["terminal_index"] - lower["terminal_index"],
        "lineage_class": lineage_class,
    }


def classify_propagation(mechanisms: Iterable[str], downstream_count: int) -> str:
    if downstream_count == 0:
        return "NO_CASCADE"
    observed = set(mechanisms)
    if observed == {"terminal_index"}:
        return "TERMINAL_INDEX_CASCADE"
    if observed == {"anchor"}:
        return "ANCHOR_PROPAGATION"
    if observed == {"eligibility"}:
        return "ELIGIBILITY_CASCADE"
    return "MULTI_STAGE_CASCADE"


def summarize_propagation(
    episodes: Sequence[Mapping[str, Any]],
    lineage: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered_episodes = sorted(episodes, key=lambda row: row["first_divergence_bar"])
    for episode_index, episode in enumerate(ordered_episodes):
        next_root_bar = (
            ordered_episodes[episode_index + 1]["first_divergence_bar"]
            if episode_index + 1 < len(ordered_episodes)
            else None
        )
        descendants = [
            row for row in lineage
            if row["lineage_class"] in {"CASCADE_DESCENDANT", "SPLIT", "MERGE"}
            and max(row.get("lower_first_detected_index") or -1, row.get("upper_first_detected_index") or -1) > episode["first_divergence_bar"]
            and (
                next_root_bar is None
                or max(row.get("lower_first_detected_index") or -1, row.get("upper_first_detected_index") or -1) < next_root_bar
            )
        ]
        mechanisms: set[str] = set()
        if episode["primary_root_cause"] in {"TERMINAL_STATE_DIVERGENCE"} or any(
            row.get("lower_terminal_index") != row.get("upper_terminal_index") for row in descendants
        ):
            mechanisms.add("terminal_index")
        if episode["primary_root_cause"] in {"FROZEN_BREAKOUT_ANCHOR_DIVERGENCE", "FROZEN_INVALIDATION_ANCHOR_DIVERGENCE"} or any(
            row.get("breakout_anchor_difference") not in (None, 0.0)
            or row.get("invalidation_anchor_difference") not in (None, 0.0)
            for row in descendants
        ):
            mechanisms.add("anchor")
        if episode["primary_root_cause"] == "NEW_SWING_ELIGIBILITY_DIVERGENCE":
            mechanisms.add("eligibility")
        downstream = len(descendants)
        rows.append({
            "market": episode["market"],
            "symbol": episode["symbol"],
            "lower_tolerance": episode["lower_tolerance"],
            "upper_tolerance": episode["upper_tolerance"],
            "root_episode_ordinal": episode["episode_ordinal"],
            "root_lifecycle": {
                "lower": episode.get("lower_lifecycle_ordinal"),
                "upper": episode.get("upper_lifecycle_ordinal"),
            },
            "propagation_class": classify_propagation(mechanisms, downstream),
            "downstream_divergent_lifecycle_count": downstream,
            "cascade_depth": downstream,
            "amplification_ratio": float(downstream),
        })
    return rows


def counterfactual_summary(
    lineage: Sequence[Mapping[str, Any]],
    propagation: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    descendants = [row for row in lineage if row["lineage_class"] == "CASCADE_DESCENDANT"]
    terminal_descendants = sum(
        row["downstream_divergent_lifecycle_count"]
        for row in propagation
        if row["propagation_class"] in {"TERMINAL_INDEX_CASCADE", "MULTI_STAGE_CASCADE"}
    )
    different_anchor = [row for row in lineage if row["lineage_class"] == "SAME_ROOT_DIFFERENT_ANCHOR"]
    shifted_terminal_with_same_anchor = [
        row for row in lineage
        if row["lineage_class"] == "SAME_ROOT_SHIFTED_TERMINAL"
        and row.get("terminal_shift") not in (None, 0)
    ]
    return [
        {
            "counterfactual": "A",
            "intervention": "FIX_LOWER_LAST_TERMINAL_INDEX_CHANGE_TOLERANCE_GATE_ONLY",
            "downstream_divergence_reduction": terminal_descendants,
            "rationale": "descendants attributed to terminal-index or multi-stage propagation are removed at the frozen propagation seam",
            "intervention_method": "FROZEN_CAUSAL_GRAPH_EDGE_INTERVENTION",
            "labels": ["RESEARCH_CAUSAL_DIAGNOSTIC_ONLY", "NOT_A_CANDIDATE_RULE"],
        },
        {
            "counterfactual": "B",
            "intervention": "FIX_FIRST_DETECTION_BAR",
            "anchor_divergence_reduction": sum(row.get("detection_shift") not in (None, 0) for row in different_anchor),
            "baseline_anchor_divergent_lineages": len(different_anchor),
            "intervention_method": "FROZEN_CAUSAL_GRAPH_EDGE_INTERVENTION",
            "labels": ["RESEARCH_CAUSAL_DIAGNOSTIC_ONLY", "NOT_A_CANDIDATE_RULE"],
        },
        {
            "counterfactual": "C",
            "intervention": "FIX_BREAKOUT_AND_INVALIDATION_ANCHORS",
            "terminal_divergence_remains_count": len(shifted_terminal_with_same_anchor),
            "terminal_divergence_remains": bool(shifted_terminal_with_same_anchor),
            "rationale": "same-root lineages whose anchors are already identical but terminal dates differ are invariant to an anchor-fixing intervention",
            "intervention_method": "FROZEN_CAUSAL_GRAPH_EDGE_INTERVENTION",
            "labels": ["RESEARCH_CAUSAL_DIAGNOSTIC_ONLY", "NOT_A_CANDIDATE_RULE"],
        },
        {
            "counterfactual": "D",
            "intervention": "SUPPRESS_TERMINAL_INDEX_PROPAGATION",
            "added_or_disappeared_lifecycles_restored": min(len(descendants), terminal_descendants),
            "intervention_method": "FROZEN_CAUSAL_GRAPH_EDGE_INTERVENTION",
            "labels": ["RESEARCH_CAUSAL_DIAGNOSTIC_ONLY", "NOT_A_CANDIDATE_RULE"],
        },
    ]


def write_deterministic_trace_gzip(path: Path, rows: Iterable[Mapping[str, Any]]) -> str:
    """Write canonical JSONL with deterministic gzip metadata and return SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as stream:
        for row in rows:
            stream.write(canonical_json(row).encode("utf-8"))
            stream.write(b"\n")
    payload = buffer.getvalue()
    path.write_bytes(payload)
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: canonical_json(value) if isinstance(value, (dict, list, tuple)) else value for key, value in row.items()})
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


__all__ = [
    "ADJACENT_PAIRS", "ATTRIBUTION_SCHEMA_VERSION", "PROPAGATION_CLASSES",
    "ROOT_CAUSES", "SETUP_PARAMETERS", "TOLERANCES", "build_symbol_trace",
    "classify_first_divergence", "classify_lineage", "classify_propagation",
    "correctness_view", "counterfactual_summary", "extract_lifecycles",
    "find_divergence_episodes", "summarize_propagation",
    "write_csv", "write_deterministic_trace_gzip",
]

"""DEVELOPMENT_EXPOSED mechanical replay for Position Management / Exit.

The runner evaluates the existing SETUP_01 and corrected SETUP_02 decision
streams over the frozen development bars, then adapts only rows already
classified ``EXECUTED`` into immutable position origins.  It never rescreens
entries or emits performance statistics.
"""
from __future__ import annotations

from collections import Counter
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from core import Quote
from research.development_dataset import DATASET_MANIFEST_PATH, load_frozen_dataset
from trading.position_management import (
    POSITION_MANAGEMENT_PROTOCOL_VERSION,
    EXECUTED,
    PositionOrigin,
    PositionReplay,
    position_origin_from_execution,
    position_replay_to_dict,
    replay_position,
    replay_positions,
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
from trading.wave5_context import WAVE5_CONTEXT_PROTOCOL_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP02_GEOMETRY_AUDIT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "setup02_decision_risk_v1"
    / "setup02_invalid_structure_geometry_audit.csv"
)
CACHE_PARITY_AUDIT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "cache_semantic_parity"
    / "frozen_replay_cache_semantic_parity.json"
)

# Counts captured from the pre-hardening replay artifact.  They are retained
# only as an advisory-label comparison baseline; no position-management rule
# is derived from them.
LEGACY_TARGET_LABEL_COUNTS = {
    "FIB_TARGET_PROXIMITY": 2,
    "FIB_TARGET_REACHED": 33,
    "CONFIRMED_SWING_TARGET_PROXIMITY": 0,
    "CONFIRMED_SWING_TARGET_REACHED": 0,
}
LEGACY_ACTION_COUNTS = {
    "EXIT": 3,
    "HOLD": 11,
    "NO_ADD": 96,
    "PROFIT_PROTECTION": 24,
}


def _stream_origins(
    source_setup: str,
    events: Sequence[object],
    stream: Setup01DecisionStream | Setup02DecisionStream,
) -> tuple[PositionOrigin, ...]:
    events_by_identity = {event.event_identity: event for event in events}
    executions_by_identity = {
        execution.event_identity: execution for execution in stream.executions
    }
    origins: list[PositionOrigin] = []
    for decision in stream.decisions:
        execution = executions_by_identity.get(decision.event_identity)
        event = events_by_identity.get(decision.event_identity)
        if execution is None or event is None:
            continue
        origin = position_origin_from_execution(
            source_setup,
            event,
            decision,
            execution,
        )
        if origin is not None:
            origins.append(origin)
    return tuple(origins)


def _replay_prefix_is_invariant(
    replay: PositionReplay,
    quotes: Sequence[Quote],
) -> bool:
    if replay.position_days < 2:
        return True
    entry_index = next(
        index for index, quote in enumerate(quotes)
        if quote.trade_date == replay.origin.entry_date
    )
    split_index = min(entry_index + 2, len(quotes) - 1)
    short = replay_position(replay.origin, quotes[: split_index + 1])
    full_prefix = replay.days[: len(short.days)]
    return short.days == full_prefix


def _target_provenance_summary(
    stream: Setup01DecisionStream | Setup02DecisionStream,
) -> dict[str, dict[str, int]]:
    target_sources: Counter[str] = Counter()
    t1_sources: Counter[str] = Counter()
    extension_ratios: Counter[str] = Counter()
    for decision in stream.decisions:
        if decision.target_candidates:
            t1_sources[decision.target_candidates[0].source] += 1
        for candidate in decision.target_candidates:
            target_sources[candidate.source] += 1
            for provenance in candidate.provenance:
                if provenance.extension_ratio is not None:
                    extension_ratios[str(float(provenance.extension_ratio))] += 1
    return {
        "target_candidate_source_counts": dict(sorted(target_sources.items())),
        "t1_source_counts": dict(sorted(t1_sources.items())),
        "extension_ratio_counts": dict(sorted(extension_ratios.items())),
    }


def _load_setup02_geometry_audit() -> dict[str, Any]:
    if not SETUP02_GEOMETRY_AUDIT_PATH.exists():
        return {
            "source": "LOCAL_FROZEN_PR50_ARTIFACT_NOT_PRESENT",
            "row_count": 0,
            "root_cause_counts": {},
            "rows": [],
        }
    with SETUP02_GEOMETRY_AUDIT_PATH.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    root_causes = Counter(
        row.get("exact_invariant_failure_reason", "UNKNOWN") for row in rows
    )
    return {
        "source": str(SETUP02_GEOMETRY_AUDIT_PATH),
        "row_count": len(rows),
        "root_cause_counts": dict(sorted(root_causes.items())),
        "rows": rows,
    }


def _load_cache_parity_audit() -> dict[str, Any]:
    if not CACHE_PARITY_AUDIT_PATH.exists():
        return {
            "source": "LOCAL_CACHE_PARITY_ARTIFACT_NOT_PRESENT",
            "status": "ABSENT",
            "strict_cached_semantic_parity": None,
        }
    with CACHE_PARITY_AUDIT_PATH.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    report["source"] = str(CACHE_PARITY_AUDIT_PATH)
    return report


def build_position_management_replay(
    *,
    manifest_path: str | None = None,
    swing_lookback: int = 5,
    atr_period: int = 14,
) -> dict[str, Any]:
    """Build the position-management mechanical report from frozen bars."""
    manifest, quotes_by_symbol = load_frozen_dataset(
        Path(manifest_path) if manifest_path is not None else DATASET_MANIFEST_PATH
    )
    setup01_events: list[object] = []
    setup02_events: list[object] = []
    for symbol in sorted(quotes_by_symbol):
        quotes = quotes_by_symbol[symbol]
        setup01_events.extend(replay_setup01_history(quotes).events)
        setup02_events.extend(replay_setup02_history(quotes).events)

    setup01_stream = evaluate_setup01_decision_stream(
        setup01_events,
        quotes_by_symbol,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    setup02_stream = evaluate_setup02_decision_stream(
        setup02_events,
        quotes_by_symbol,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )
    origins = (
        *_stream_origins("SETUP_01", setup01_events, setup01_stream),
        *_stream_origins("SETUP_02", setup02_events, setup02_stream),
    )
    replays = replay_positions(
        origins,
        quotes_by_symbol,
        swing_lookback=swing_lookback,
        atr_period=atr_period,
    )

    source_streams = {"SETUP_01": setup01_stream, "SETUP_02": setup02_stream}
    source_events = {"SETUP_01": setup01_events, "SETUP_02": setup02_events}
    source_execution_counts: dict[str, dict[str, int]] = {}
    source_decision_counts: dict[str, int] = {}
    for source, stream in source_streams.items():
        source_execution_counts[source] = dict(
            sorted(Counter(item.outcome for item in stream.executions).items())
        )
        source_decision_counts[source] = len(stream.decisions)

    position_days = [day for replay in replays for day in replay.days]
    exit_reasons = Counter(
        replay.exit_reason.value for replay in replays if replay.exit_reason is not None
    )
    actions = Counter(day.action.value for day in position_days)
    risk_flags = Counter(
        flag for day in position_days for flag in day.risk_flags
    )
    contexts = Counter(day.wave5_context.value for day in position_days)
    targets = Counter(day.target_status.value for day in position_days)
    per_source_positions = Counter(replay.origin.source_setup for replay in replays)
    per_source_days = Counter(
        day.source_setup for day in position_days
    )
    stop_raises = sum(replay.stop_raise_count for replay in replays)
    structural_pending = sum(
        day.secondary_reasons.count("STRUCTURAL_EXIT_PENDING")
        for day in position_days
    )
    mfe_pending = sum(
        day.secondary_reasons.count("PROFIT_PROTECTION_EXIT_PENDING")
        for day in position_days
    )
    future_append_invariance = all(
        _replay_prefix_is_invariant(replay, quotes_by_symbol[replay.origin.symbol])
        for replay in replays
    )
    executed_count = sum(
        counts.get(EXECUTED, 0) for counts in source_execution_counts.values()
    )
    identity_counts = {
        source: {
            "structural_event_count": len(source_events[source]),
            "unique_structural_event_identity_count": len(
                {event.event_identity for event in source_events[source]}
            ),
            "decision_rows": source_decision_counts[source],
            "executed_ledger_rows": source_execution_counts[source].get(EXECUTED, 0),
        }
        for source in source_events
    }
    target_provenance = {
        source: _target_provenance_summary(stream)
        for source, stream in source_streams.items()
    }
    cache_semantic_parity = _load_cache_parity_audit()
    corrected_target_label_counts = {
        label: risk_flags.get(label, 0)
        for label in LEGACY_TARGET_LABEL_COUNTS
    }
    target_label_delta = {
        label: corrected_target_label_counts[label] - baseline
        for label, baseline in LEGACY_TARGET_LABEL_COUNTS.items()
    }
    target_provenance_correction = {
        "position_origin_targets_are_immutable": True,
        "target_prices_and_order_recomputed": False,
        "target_prices_and_order_copied_from_decision_candidates": True,
        "legacy_target_label_counts": LEGACY_TARGET_LABEL_COUNTS,
        "corrected_target_label_counts": corrected_target_label_counts,
        "target_label_delta": target_label_delta,
        "legacy_action_counts": LEGACY_ACTION_COUNTS,
        "corrected_action_counts": dict(sorted(actions.items())),
        "action_counts_unchanged": dict(sorted(actions.items())) == LEGACY_ACTION_COUNTS,
        "interpretation": (
            "advisory target-label provenance correction only; target prices, "
            "target order, stop, MFE/MAE, Wave5, and exit rules are unchanged"
        ),
    }
    decision_gate_counts = {
        source: dict(
            sorted(
                Counter(
                    str(getattr(item.gate_reason, "value", item.gate_reason))
                    for item in stream.decisions
                ).items()
            )
        )
        for source, stream in source_streams.items()
    }
    execution_status_counts = {
        source: dict(
            sorted(Counter(item.outcome for item in stream.executions).items())
        )
        for source, stream in source_streams.items()
    }
    setup02_corrected_funnel = {
        "confirmed_events": len(setup02_stream.decisions),
        "decision_rows": len(setup02_stream.decisions),
        "entry_allowed": sum(
            item.action.value == "ENTRY_ALLOWED" for item in setup02_stream.decisions
        ),
        "t1_execution_attempts": len(setup02_stream.executions),
        "executed": execution_status_counts["SETUP_02"].get(EXECUTED, 0),
        "execution_status_counts": execution_status_counts["SETUP_02"],
        "decision_gate_reason_counts": decision_gate_counts["SETUP_02"],
    }
    controls = {
        "development_exposed": True,
        "post_entry_bars_allowed": True,
        "returns_accessed": False,
        "mfe_accessed": True,
        "mae_accessed": True,
        "win_rate_accessed": False,
        "expectancy_accessed": False,
        "profit_factor_accessed": False,
        "pnl_accessed": False,
        "sharpe_accessed": False,
        "strategy_optimization": False,
        "parameter_grid": False,
        "final_oos_accessed": False,
        "production_execution": False,
        "broker_accessed": False,
        "holdings_accessed": False,
        "sheets_written": False,
        "new_entry_generated": False,
        "new_setup_generated": False,
    }
    forbidden_controls_closed = not any(
        controls[name]
        for name in (
            "returns_accessed",
            "win_rate_accessed",
            "expectancy_accessed",
            "profit_factor_accessed",
            "pnl_accessed",
            "sharpe_accessed",
            "strategy_optimization",
            "parameter_grid",
            "final_oos_accessed",
            "production_execution",
            "broker_accessed",
            "holdings_accessed",
            "sheets_written",
            "new_entry_generated",
            "new_setup_generated",
        )
    )
    return {
        "protocol_version": POSITION_MANAGEMENT_PROTOCOL_VERSION,
        "wave5_context_protocol_version": WAVE5_CONTEXT_PROTOCOL_VERSION,
        "mode": "DEVELOPMENT_EXPOSED_POSITION_MANAGEMENT_MECHANICAL_REPLAY",
        "development_session_identity": "FROZEN_DATASET_MARKET_SESSION_SET",
        "dataset_version": manifest["dataset_version"],
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "symbols_requested": len(quotes_by_symbol),
        "source_decision_counts": source_decision_counts,
        "source_execution_counts": source_execution_counts,
        "positions_opened": len(replays),
        "positions_opened_by_setup": dict(sorted(per_source_positions.items())),
        "position_days": len(position_days),
        "position_days_by_setup": dict(sorted(per_source_days.items())),
        "stop_raise_count": stop_raises,
        "structural_exit_pending_count": structural_pending,
        "mfe_protection_pending_count": mfe_pending,
        "exit_reason_counts": dict(sorted(exit_reasons.items())),
        "target_reach_counts": dict(sorted(targets.items())),
        "wave5_context_counts": dict(sorted(contexts.items())),
        "action_counts": dict(sorted(actions.items())),
        "risk_flag_counts": dict(sorted(risk_flags.items())),
        "identity_audit": identity_counts,
        "decision_gate_reason_counts": decision_gate_counts,
        "execution_status_counts": execution_status_counts,
        "target_provenance": target_provenance,
        "target_provenance_correction": target_provenance_correction,
        "cache_semantic_parity": cache_semantic_parity,
        "setup02_corrected_funnel": setup02_corrected_funnel,
        "setup02_geometry_correction_audit": _load_setup02_geometry_audit(),
        "source_stream_provenance": {
            "mode": "FROZEN_DEVELOPMENT_BARS_TO_SETUP_DECISION_STREAMS",
            "position_origin_policy": "ONLY_EXECUTED_ROWS",
            "entry_rescreened": False,
        },
        "causal_invariants": {
            "frozen_execution_ledger_reused": True,
            "entries_rescreened": False,
            "executed_ledger_equals_positions_opened": executed_count == len(replays),
            "initial_r_equals_actual_entry_minus_initial_stop": all(
                math.isclose(
                    replay.origin.initial_risk_per_share,
                    replay.origin.actual_entry - replay.origin.initial_execution_stop,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                for replay in replays
            ),
            "stop_never_moves_down": all(
                day.active_stop_next_session >= day.active_stop_at_open
                for day in position_days
            ),
            "actual_entry_is_frozen": True,
            "future_append_invariance": future_append_invariance,
            "structural_event_identity_unique": {
                "SETUP_01": (
                    identity_counts["SETUP_01"]["structural_event_count"]
                    == identity_counts["SETUP_01"]["unique_structural_event_identity_count"]
                ),
                "SETUP_02": (
                    identity_counts["SETUP_02"]["structural_event_count"]
                    == identity_counts["SETUP_02"]["unique_structural_event_identity_count"]
                ),
            },
            "strict_cached_semantic_parity": cache_semantic_parity.get(
                "strict_cached_semantic_parity"
            ),
        },
        "controls": controls,
        "governance_consistency": forbidden_controls_closed
        and controls["development_exposed"]
        and controls["post_entry_bars_allowed"],
        "positions": [position_replay_to_dict(replay) for replay in replays],
        "status": "SUCCESS",
    }


__all__ = ["build_position_management_replay"]

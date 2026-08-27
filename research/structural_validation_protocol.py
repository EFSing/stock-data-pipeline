"""Phase 5J SETUP_03 structural validation protocol registration.

This module is deliberately a protocol reader and static-audit boundary.  It
does not fetch data, call Replay, run Trading Core, write Sheets, or inspect
the final OOS dataset.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


PROTOCOL_PATH = Path(__file__).with_name("setup03_structural_validation_protocol.json")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_SOURCE_PATH = PROJECT_ROOT / "trading" / "setup.py"
EVENTS_SOURCE_PATH = PROJECT_ROOT / "trading" / "events.py"

PROTOCOL_STATUS = "VALIDATION_PROTOCOL_REGISTERED_NOT_EXECUTED"
PRODUCTION_TOLERANCES = (0.03, 0.04, 0.05)
DIAGNOSTIC_STRESS_BOUNDARIES = (0.025, 0.055, 0.075, 0.10)
VALIDATION_MARKETS = ("CN", "HK", "US", "JP", "SE")
REQUIRED_FORBIDDEN_METRICS = {
    "forward_return",
    "MFE",
    "MAE",
    "win_rate",
    "P&L",
}
REQUIRED_THRESHOLD_IDS = {
    "minimum_confirmed_events_per_market_candidate",
    "adjacent_confirmed_jaccard",
    "adjacent_confirmed_retention",
    "matched_confirmed_event_date_drift_median",
    "matched_confirmed_event_date_drift_p90",
    "maximum_market_confirmed_concentration",
    "maximum_symbol_confirmed_concentration",
    "adjacent_confirmed_rate_relative_increase",
}


@dataclass(frozen=True)
class ArmProximityAudit:
    source_files: tuple[str, ...]
    parameter_functions: tuple[str, ...]
    observed_effect_scope: tuple[str, ...]
    formal_confirmation_predicates: tuple[str, ...]
    terminal_event_predicates: tuple[str, ...]
    formal_confirmed_terminal_semantics_affected: bool
    conclusion: str


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    """Load and validate the registered machine-readable Phase 5J protocol."""
    protocol = json.loads(path.read_text(encoding="utf-8"))
    _validate_protocol(protocol)
    return protocol


def protocol_integrity_hash(protocol: dict[str, Any]) -> str:
    """Hash every protocol field except the stored integrity envelope."""
    payload = dict(protocol)
    payload.pop("integrity", None)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def serialize_protocol(protocol: dict[str, Any]) -> str:
    """Return the stable repository representation of the protocol."""
    return json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"


def audit_arm_proximity_dependency(
    setup_source_path: Path = SETUP_SOURCE_PATH,
    events_source_path: Path = EVENTS_SOURCE_PATH,
) -> ArmProximityAudit:
    """Audit arm proximity statically without executing any trading code.

    The audit establishes that arm proximity is referenced by the intermediate
    WATCH/ARMED state machine and diagnostics, while strict confirmation and
    terminal-event predicates remain independent of it.
    """
    setup_tree = ast.parse(setup_source_path.read_text(encoding="utf-8"))
    events_tree = ast.parse(events_source_path.read_text(encoding="utf-8"))
    wrapper = _find_function(setup_tree, "detect_platform_breakout")
    detector = _find_function(setup_tree, "detect_platform_breakout_with_diagnostics")
    terminal = _find_function(events_tree, "terminal_event_type")

    parameter_functions = tuple(
        name
        for name, function in (
            ("detect_platform_breakout", wrapper),
            ("detect_platform_breakout_with_diagnostics", detector),
        )
        if _contains_name(function, "arm_proximity_pct")
    )
    if parameter_functions != (
        "detect_platform_breakout",
        "detect_platform_breakout_with_diagnostics",
    ):
        raise ValueError("arm_proximity dependency moved outside the expected Setup functions")

    confirmation_predicates = tuple(
        sorted(
            {
                ast.unparse(node)
                for node in ast.walk(detector)
                if _is_comparison(node, "close_t", "breakout_price", ast.Gt)
            }
        )
    )
    expected_confirmation = ("close_t > breakout_price",)
    if confirmation_predicates != expected_confirmation:
        raise ValueError("SETUP_03 confirmation predicate changed during arm proximity audit")

    terminal_predicates = tuple(
        sorted(
            {
                ast.unparse(node)
                for node in ast.walk(terminal)
                if isinstance(node, ast.Compare)
            }
        )
    )
    expected_terminal = (
        "setup.confirmed_index == current_index",
        "setup.state is SetupState.CONFIRMED",
        "setup.state is SetupState.FAILED",
        "setup.state_entered_index == current_index",
    )
    if terminal_predicates != expected_terminal:
        raise ValueError("terminal event predicates changed during arm proximity audit")
    if _contains_name(terminal, "arm_proximity_pct"):
        raise ValueError("terminal event semantics unexpectedly depend on arm proximity")

    return ArmProximityAudit(
        source_files=(
            _display_path(setup_source_path),
            _display_path(events_source_path),
        ),
        parameter_functions=parameter_functions,
        observed_effect_scope=(
            "WATCH/ARMED proximity threshold transitions",
            "ARMED_NOT_BREAKOUT and WATCH_BELOW_ARM_THRESHOLD diagnostics",
            "parameter validation and forwarding",
        ),
        formal_confirmation_predicates=confirmation_predicates,
        terminal_event_predicates=terminal_predicates,
        formal_confirmed_terminal_semantics_affected=False,
        conclusion="V1_KEEP_CLOSED_ARMED_WARNING_ONLY_NO_CONFIRMED_TERMINAL_CHANGE",
    )


def _validate_protocol(protocol: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "protocol_version",
        "phase",
        "setup_type",
        "phase5j_status",
        "parent_phase5i",
        "scope",
        "production_tolerance_policy",
        "parameter_policy",
        "arm_proximity_static_audit",
        "development_validation_dataset",
        "structural_validation_thresholds",
        "parameter_selection_rule",
        "forbidden_metrics",
        "prohibitions",
        "integrity",
    }
    missing = required - set(protocol)
    if missing:
        raise ValueError(f"structural validation protocol missing keys: {sorted(missing)}")

    expected_hash = protocol["integrity"].get("protocol_sha256")
    actual_hash = protocol_integrity_hash(protocol)
    if expected_hash != actual_hash:
        raise ValueError(
            "structural validation protocol integrity mismatch; same-version changes fail"
        )

    if protocol["phase5j_status"] != PROTOCOL_STATUS:
        raise ValueError("Phase 5J protocol status must remain not executed")
    if protocol["phase"] != "Phase 5J" or protocol["setup_type"] != "SETUP_03":
        raise ValueError("protocol phase/setup identity mismatch")

    parent = protocol["parent_phase5i"]
    if parent["freeze_version"] != "SETUP_03-FREEZE-2026-08-26-v1":
        raise ValueError("Phase 5I parent freeze version mismatch")
    if parent["integrity"]["critical_values_sha256"] != (
        "sha256:447b20182f54b8c994042227bbfbaf94c50b2a9b4ade7332058a014915390a15"
    ):
        raise ValueError("Phase 5I parent integrity identity mismatch")
    if parent["freeze_decision"] != "NOT_READY_FOR_FORMAL_PARAMETER_FREEZE":
        raise ValueError("Phase 5I parent freeze decision mismatch")

    policy = protocol["production_tolerance_policy"]
    candidates = tuple(policy["allowed_candidate_values_pct"])
    boundaries = tuple(policy["diagnostic_stress_boundaries_pct"])
    if candidates != PRODUCTION_TOLERANCES:
        raise ValueError("production tolerance candidates are not the frozen 3/4/5% set")
    if boundaries != DIAGNOSTIC_STRESS_BOUNDARIES:
        raise ValueError("diagnostic stress boundaries are not the frozen set")
    if set(candidates) & set(boundaries):
        raise ValueError("diagnostic boundary cannot also be a production candidate")
    if policy["stress_boundaries_are_production_candidates"]:
        raise ValueError("stress boundaries must not be production candidates")
    if policy["all_unlisted_tolerance_values_are_production_candidates"]:
        raise ValueError("unlisted tolerance values must not become production candidates")

    parameter_policy = protocol["parameter_policy"]
    for key, value in {
        "setup_swing_lookback": 5,
        "platform_window": 40,
    }.items():
        item = parameter_policy[key]
        if item["v1_incumbent_design_constant"] != value:
            raise ValueError(f"{key} incumbent design constant changed")
        if item["search_in_phase5j"] or item["claim_of_optimality"]:
            raise ValueError(f"{key} may not be searched or called optimal in Phase 5J")
    for key in (
        "market_specific_platform_tolerance",
        "regime_specific_platform_rule",
        "volatility_normalized_platform_decision_rule",
    ):
        item = parameter_policy[key]
        if item["v1_enabled"] or item["production_candidate_allowed"]:
            raise ValueError(f"{key} must remain disabled in v1")
    arm = parameter_policy["arm_proximity_pct"]
    if arm["v1_value"] != 0.0 or arm["research_mode"] != "STATIC_CODE_DEPENDENCY_AUDIT_ONLY":
        raise ValueError("arm_proximity_pct must remain a static-only audit at zero")
    if arm["formal_confirmed_terminal_semantics_affected"] or not arm["v1_keep_closed"]:
        raise ValueError("arm_proximity_pct audit cannot authorize a terminal semantic change")

    dataset = protocol["development_validation_dataset"]
    if dataset["role"] != "DEVELOPMENT_VALIDATION_NOT_FINAL_OOS":
        raise ValueError("Phase 5K dataset must not be final OOS")
    if tuple(dataset["markets"]) != VALIDATION_MARKETS:
        raise ValueError("development validation markets changed")
    coverage = dataset["coverage_requirements"]
    if coverage["per_market_symbol_count_minimum"] != 8:
        raise ValueError("per-market symbol coverage minimum changed")
    if coverage["total_symbol_count_minimum"] != 40:
        raise ValueError("total symbol coverage minimum changed")
    if coverage["per_market_valid_daily_k_bars_target_minimum"] != 6000:
        raise ValueError("per-market valid-bar coverage target changed")
    if coverage["failure_status"] != "INSUFFICIENT_COVERAGE":
        raise ValueError("coverage shortfall status changed")
    selection = dataset["symbol_selection_rules"]
    if not selection["selection_must_precede_setup03_output"]:
        raise ValueError("symbol selection must precede SETUP_03 output")
    if selection["signal_dependent_selection"] or selection["replace_add_or_remove_after_setup03_output"]:
        raise ValueError("symbol universe may not depend on SETUP_03 output")
    manifest = dataset["symbol_manifest"]
    if not manifest["must_be_frozen_before_phase5k_acquisition"]:
        raise ValueError("symbol manifest must freeze before Phase 5K acquisition")
    if not manifest["must_be_hashed_before_phase5k_acquisition"]:
        raise ValueError("symbol manifest must hash before Phase 5K acquisition")

    thresholds = protocol["structural_validation_thresholds"]
    threshold_ids = {row.get("id") for row in thresholds}
    if threshold_ids != REQUIRED_THRESHOLD_IDS:
        raise ValueError("structural threshold set changed")
    expected_values = {
        "minimum_confirmed_events_per_market_candidate": (">=", 8),
        "adjacent_confirmed_jaccard": (">=", 0.60),
        "adjacent_confirmed_retention": (">=", 0.80),
        "matched_confirmed_event_date_drift_median": ("<=", 5),
        "matched_confirmed_event_date_drift_p90": ("<=", 15),
        "maximum_market_confirmed_concentration": ("<=", 0.35),
        "maximum_symbol_confirmed_concentration": ("<=", 0.25),
        "adjacent_confirmed_rate_relative_increase": ("<=", 0.50),
    }
    for row in thresholds:
        if (row["operator"], row["threshold"]) != expected_values[row["id"]]:
            raise ValueError(f"structural threshold changed: {row['id']}")
    minimum = next(
        row for row in thresholds if row["id"] == "minimum_confirmed_events_per_market_candidate"
    )
    if minimum["failure_status"] != "INSUFFICIENT_VALIDATION_EVIDENCE":
        raise ValueError("insufficient CONFIRMED evidence status changed")

    selection_rule = protocol["parameter_selection_rule"]
    if selection_rule["type"] != "LEXICOGRAPHIC_CONSERVATIVE":
        raise ValueError("parameter selection rule must remain lexicographic conservative")
    if tuple(selection_rule["ordered_candidates_pct"]) != PRODUCTION_TOLERANCES:
        raise ValueError("selection candidate order changed")
    if selection_rule["all_candidates_fail_status"] != "VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE":
        raise ValueError("all-candidates-fail status changed")
    if selection_rule["primarily_insufficient_evidence_status"] != "INSUFFICIENT_VALIDATION_EVIDENCE":
        raise ValueError("insufficient-evidence status changed")
    if selection_rule["performance_metrics_used"] or selection_rule["market_specific_or_regime_specific_selection"]:
        raise ValueError("selection rule may not use performance or market/regime parameters")

    if not REQUIRED_FORBIDDEN_METRICS.issubset(set(protocol["forbidden_metrics"])):
        raise ValueError("required forbidden performance metrics are missing")
    prohibitions = protocol["prohibitions"]
    required_prohibitions = {
        "replay_execution",
        "live_fetch",
        "new_historical_data_fetch",
        "new_parameter_grid",
        "production_setup03_modification",
        "trading_core_modification",
        "decision_or_execution_modification",
        "google_sheets_write",
        "final_oos_access",
        "final_oos_start",
        "formal_production_parameter_selection",
        "new_production_candidate",
    }
    if any(not prohibitions.get(key, False) for key in required_prohibitions):
        raise ValueError("Phase 5J prohibition was weakened")

def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise ValueError(f"static audit function not found: {name}")


def _contains_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(node))


def _is_comparison(node: ast.AST, left_name: str, right_name: str, operator: type) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == left_name
        and len(node.ops) == 1
        and isinstance(node.ops[0], operator)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Name)
        and node.comparators[0].id == right_name
    )


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()

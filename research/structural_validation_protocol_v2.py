"""Phase 5J-v2 CN/US scope revision for the SETUP_03 protocol.

This is an independent, metadata-only governance contract.  It does not
modify or replace the Phase 5J v1 protocol, fetch validation data, call
Replay/Trading Core, read Sheets, or access final OOS.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


PROTOCOL_PATH = Path(__file__).with_name("setup03_structural_validation_protocol_v2.json")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_PROTOCOL_PATH = PROJECT_ROOT / "research" / "setup03_structural_validation_protocol.json"

PROTOCOL_STATUS = "SCOPE_REVISION_REGISTERED_NOT_EXECUTED"
EXPECTED_PROTOCOL_VERSION = "SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v2-CN-US"
EXPECTED_V1_PROTOCOL_VERSION = "SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v1"
EXPECTED_V1_PROTOCOL_SHA256 = "sha256:b0fe288b66ff5a86b127d57c1cb2493b583d252dcb169edbc86fab52830948bd"
PINNED_PROTOCOL_SHA256_BY_VERSION = MappingProxyType(
    {EXPECTED_PROTOCOL_VERSION: "sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0"}
)
PRODUCTION_TOLERANCES = (0.03, 0.04, 0.05)
DIAGNOSTIC_STRESS_BOUNDARIES = (0.025, 0.055, 0.075, 0.10)
VALIDATION_MARKETS = ("CN", "US")
EXCLUDED_MARKETS = ("HK", "JP", "SE")
REQUIRED_FORBIDDEN_METRICS = {
    "forward_return", "MFE", "MAE", "win_rate", "P&L", "profit_factor", "expectancy"
}
REQUIRED_THRESHOLD_IDS = {
    "minimum_confirmed_events_per_market_candidate",
    "adjacent_confirmed_jaccard",
    "adjacent_confirmed_retention",
    "matched_confirmed_event_date_drift_median",
    "matched_confirmed_event_date_drift_p90",
    "maximum_symbol_confirmed_concentration",
    "adjacent_confirmed_rate_relative_increase",
}
EXPECTED_CANDIDATE_LEVEL_THRESHOLD_IDS = (
    "minimum_confirmed_events_per_market_candidate",
    "maximum_symbol_confirmed_concentration",
)
EXPECTED_ADJACENT_PAIR_THRESHOLD_IDS = (
    "adjacent_confirmed_jaccard",
    "adjacent_confirmed_retention",
    "matched_confirmed_event_date_drift_median",
    "matched_confirmed_event_date_drift_p90",
    "adjacent_confirmed_rate_relative_increase",
)
EXPECTED_CANDIDATE_QUALIFICATION_MATRIX = (
    {"candidate_pct": 0.03, "adjacent_pairs": ((0.03, 0.04),)},
    {"candidate_pct": 0.04, "adjacent_pairs": ((0.03, 0.04), (0.04, 0.05))},
    {"candidate_pct": 0.05, "adjacent_pairs": ((0.04, 0.05),)},
)


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    """Load and validate the independent Phase 5J-v2 contract."""
    protocol = json.loads(path.read_text(encoding="utf-8"))
    _validate_protocol(protocol, path)
    return protocol


def protocol_integrity_hash(protocol: Mapping[str, Any]) -> str:
    """Hash every protocol field except the stored integrity envelope."""
    payload = deepcopy(dict(protocol))
    payload.pop("integrity", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def serialize_protocol(protocol: Mapping[str, Any]) -> str:
    """Return the stable repository representation of the protocol."""
    return json.dumps(protocol, ensure_ascii=False, indent=2) + "\n"


def _validate_protocol(protocol: Mapping[str, Any], path: Path) -> None:
    required = {
        "schema_version", "protocol_version", "phase", "setup_type",
        "phase5j_status", "parent_phase5j_v1", "parent_phase5i", "scope",
        "market_scope", "aggregate_diagnostic_instruments",
        "production_tolerance_policy", "parameter_policy",
        "development_validation_dataset", "structural_validation_thresholds",
        "parameter_selection_rule", "forbidden_metrics", "prohibitions", "integrity",
    }
    missing = required - set(protocol)
    if missing:
        raise ValueError(f"Phase 5J-v2 protocol missing keys: {sorted(missing)}")

    expected_hash = protocol["integrity"].get("protocol_sha256")
    actual_hash = protocol_integrity_hash(protocol)
    if expected_hash != actual_hash:
        raise ValueError("Phase 5J-v2 protocol integrity mismatch")
    pinned_hash = PINNED_PROTOCOL_SHA256_BY_VERSION.get(protocol["protocol_version"])
    if pinned_hash is None:
        raise ValueError("Phase 5J-v2 protocol version has no pinned hash contract")
    if expected_hash != pinned_hash:
        raise ValueError("Phase 5J-v2 protocol version is bound to a different canonical hash")
    if protocol["protocol_version"] != EXPECTED_PROTOCOL_VERSION:
        raise ValueError("unexpected Phase 5J-v2 protocol version")
    if protocol["phase5j_status"] != PROTOCOL_STATUS:
        raise ValueError("Phase 5J-v2 protocol must remain not executed")
    if protocol["phase"] != "Phase 5J-v2" or protocol["setup_type"] != "SETUP_03":
        raise ValueError("Phase 5J-v2 phase/setup identity mismatch")

    _validate_v1_parent(protocol["parent_phase5j_v1"])
    _validate_scope(protocol["scope"])
    _validate_markets(protocol["market_scope"])
    _validate_aggregate_instruments(protocol["aggregate_diagnostic_instruments"])
    _validate_parameter_policy(protocol["production_tolerance_policy"], protocol["parameter_policy"])
    _validate_dataset(protocol["development_validation_dataset"])
    _validate_thresholds(protocol["structural_validation_thresholds"])
    _validate_selection_rule(protocol["parameter_selection_rule"])
    if not REQUIRED_FORBIDDEN_METRICS.issubset(set(protocol["forbidden_metrics"])):
        raise ValueError("required forbidden performance metrics are missing")
    required_prohibitions = {
        "replay_execution", "live_fetch", "new_historical_data_fetch",
        "formal_phase5k_dataset_generation", "symbol_manifest_generation",
        "new_parameter_grid", "production_setup03_modification", "trading_core_modification",
        "decision_or_execution_modification", "google_sheets_write", "final_oos_access",
        "final_oos_start", "formal_production_parameter_selection", "new_production_candidate",
    }
    if any(not protocol["prohibitions"].get(key, False) for key in required_prohibitions):
        raise ValueError("Phase 5J-v2 prohibition was weakened")


def _validate_v1_parent(parent: Mapping[str, Any]) -> None:
    if parent.get("protocol_version") != EXPECTED_V1_PROTOCOL_VERSION:
        raise ValueError("v2 parent is not the registered Phase 5J v1 protocol")
    if parent.get("protocol_sha256") != EXPECTED_V1_PROTOCOL_SHA256:
        raise ValueError("v2 parent Phase 5J v1 hash changed")
    actual = json.loads(V1_PROTOCOL_PATH.read_text(encoding="utf-8"))
    if actual.get("protocol_version") != EXPECTED_V1_PROTOCOL_VERSION:
        raise ValueError("repository Phase 5J v1 version changed")
    if actual.get("integrity", {}).get("protocol_sha256") != EXPECTED_V1_PROTOCOL_SHA256:
        raise ValueError("repository Phase 5J v1 stored hash changed")
    if _v1_integrity_hash(actual) != EXPECTED_V1_PROTOCOL_SHA256:
        raise ValueError("repository Phase 5J v1 canonical hash changed")


def _v1_integrity_hash(protocol: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(protocol))
    payload.pop("integrity", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _validate_scope(scope: Mapping[str, Any]) -> None:
    if tuple(scope["validation_markets"]) != VALIDATION_MARKETS:
        raise ValueError("v2 validation markets must be CN/US")
    if tuple(scope["excluded_markets"]) != EXCLUDED_MARKETS:
        raise ValueError("v2 excluded markets changed")
    change = scope["deployment_scope_change"]
    if not change["effective_before_phase5k_data_or_setup03_output"]:
        raise ValueError("scope change must precede validation data and SETUP_03 output")
    if "result-driven" not in change["reason"]:
        raise ValueError("scope change must be explicitly non-result-driven")
    if tuple(change["formal_validation_dataset_markets"]) != VALIDATION_MARKETS:
        raise ValueError("formal validation dataset markets changed")
    for key in (
        "validation_executed", "phase5k_validation_ohlcv_accessed", "setup03_output_accessed",
        "confirmed_events_accessed", "final_oos_accessed", "formal_parameter_selected",
        "production_configuration_modified", "thresholds_or_tolerance_researched",
    ):
        if scope[key]:
            raise ValueError(f"Phase 5J-v2 scope flag {key} must remain false")


def _validate_markets(markets: Mapping[str, Any]) -> None:
    cn = markets["CN"]
    enabled = {item["status"] for item in cn["enabled_venues"]}
    if enabled != {"CN_SSE_MAIN_BOARD_ACTIVE", "CN_SZSE_MAIN_BOARD_ACTIVE"}:
        raise ValueError("CN enabled venues must be SSE/SZSE Main Board only")
    inactive = {item["status"]: item for item in cn["registered_inactive_venues"]}
    for status in ("CN_STAR_REGISTERED_INACTIVE", "CN_CHINEXT_REGISTERED_INACTIVE"):
        item = inactive.get(status)
        if item is None or any(item[key] for key in ("eligible_for_phase5k", "eligible_for_ohlcv", "eligible_for_qualification")):
            raise ValueError(f"inactive CN venue {status} was enabled")
        if not item["activation_requires_protocol_version_upgrade"]:
            raise ValueError(f"inactive CN venue {status} lacks version gate")
    if tuple(item["id"] for item in cn["candidate_universes"]) != ("CSI300", "CSI500", "CSI1000"):
        raise ValueError("CN candidate universes changed")
    if tuple(item["primary_quota"] for item in cn["candidate_universes"]) != (12, 14, 14):
        raise ValueError("CN primary quotas changed")
    if cn["primary_target"] != 40 or cn["reserve_target"] != 20:
        raise ValueError("CN target counts changed")
    if "never SETUP_03 output" not in cn["selection_inputs"] or "returns" not in cn["selection_inputs"]:
        raise ValueError("CN selection-input prohibition is missing")

    us = markets["US"]
    if tuple(item["id"] for item in us["candidate_universes"]) != ("SP500", "NASDAQ100", "SOX", "IGV"):
        raise ValueError("US candidate universes changed")
    if tuple(item["primary_quota"] for item in us["candidate_universes"]) != (12, 10, 8, 10):
        raise ValueError("US primary quotas changed")
    if us["primary_target"] != 40 or us["reserve_target"] != 20:
        raise ValueError("US target counts changed")
    if us["deduplication_key"] != "canonical_issuer_share_class_identity":
        raise ValueError("US deduplication key changed")
    if "never SETUP_03 output" not in us["selection_inputs"] or "returns" not in us["selection_inputs"]:
        raise ValueError("US selection-input prohibition is missing")


def _validate_aggregate_instruments(instruments: Mapping[str, Any]) -> None:
    if tuple(instruments["instruments"]) != ("QQQ", "SOX_INDEX", "IGV_ETF"):
        raise ValueError("aggregate diagnostic instrument set changed")
    for key in ("counts_toward_equity_sample_minimum", "counts_toward_candidate_qualification", "may_determine_tolerance"):
        if instruments[key]:
            raise ValueError(f"aggregate instrument may not affect formal sample: {key}")


def _validate_parameter_policy(policy: Mapping[str, Any], parameters: Mapping[str, Any]) -> None:
    if tuple(policy["allowed_candidate_values_pct"]) != PRODUCTION_TOLERANCES:
        raise ValueError("production tolerance candidates changed")
    if tuple(policy["diagnostic_stress_boundaries_pct"]) != DIAGNOSTIC_STRESS_BOUNDARIES:
        raise ValueError("diagnostic stress boundaries changed")
    if policy["stress_boundaries_are_production_candidates"] or policy["all_unlisted_tolerance_values_are_production_candidates"] or policy["search_in_phase5j_v2"]:
        raise ValueError("tolerance search or boundary promotion is enabled")
    for key, value in (("setup_swing_lookback", 5), ("platform_window", 40)):
        item = parameters[key]
        if item["v1_incumbent_design_constant"] != value or item["search_in_phase5j_v2"] or item["claim_of_optimality"]:
            raise ValueError(f"{key} was searched or called optimal")
    for key in ("market_specific_platform_tolerance", "regime_specific_platform_rule", "volatility_normalized_platform_decision_rule"):
        if parameters[key]["v1_enabled"] or parameters[key]["production_candidate_allowed"]:
            raise ValueError(f"{key} must remain disabled")
    arm = parameters["arm_proximity_pct"]
    if arm["v1_value"] != 0.0 or arm["research_mode"] != "STATIC_CODE_DEPENDENCY_AUDIT_ONLY" or arm["formal_confirmed_terminal_semantics_affected"] or not arm["v1_keep_closed"]:
        raise ValueError("arm proximity policy changed")


def _validate_dataset(dataset: Mapping[str, Any]) -> None:
    if dataset["role"] != "DEVELOPMENT_VALIDATION_NOT_FINAL_OOS" or tuple(dataset["markets"]) != VALIDATION_MARKETS:
        raise ValueError("v2 dataset identity changed")
    coverage = dataset["coverage_requirements"]
    if coverage["per_market_symbol_count_minimum"] != 8 or coverage["total_symbol_count_minimum"] != 40 or coverage["per_market_valid_daily_k_bars_target_minimum"] != 6000 or coverage["failure_status"] != "INSUFFICIENT_COVERAGE":
        raise ValueError("v2 coverage requirements changed")
    rules = dataset["symbol_selection_rules"]
    for key in ("selection_must_precede_setup03_output", "selection_must_precede_phase5k_ohlcv_access", "market_qualification_is_independent"):
        if not rules[key]:
            raise ValueError(f"selection rule {key} weakened")
    if rules["signal_dependent_selection"] or rules["replace_add_or_remove_after_setup03_output"] or rules["market_compensation_allowed"]:
        raise ValueError("signal-driven selection or market compensation enabled")
    manifest = dataset["symbol_manifest"]
    if not manifest["must_be_frozen_before_phase5k_acquisition"] or not manifest["must_be_hashed_before_phase5k_acquisition"] or not manifest["must_use_current_snapshot_only_when_source_lacks_historical_membership"] or manifest["historical_membership_may_be_fabricated"]:
        raise ValueError("symbol manifest provenance rule changed")


def _validate_thresholds(thresholds: list[Mapping[str, Any]]) -> None:
    ids = {row["id"] for row in thresholds}
    if ids != REQUIRED_THRESHOLD_IDS or "maximum_market_confirmed_concentration" in ids:
        raise ValueError("v2 threshold set must remove market concentration only")
    expected = {
        "minimum_confirmed_events_per_market_candidate": (">=", 8),
        "adjacent_confirmed_jaccard": (">=", 0.60),
        "adjacent_confirmed_retention": (">=", 0.80),
        "matched_confirmed_event_date_drift_median": ("<=", 5),
        "matched_confirmed_event_date_drift_p90": ("<=", 15),
        "maximum_symbol_confirmed_concentration": ("<=", 0.25),
        "adjacent_confirmed_rate_relative_increase": ("<=", 0.50),
    }
    for row in thresholds:
        if (row["operator"], row["threshold"]) != expected[row["id"]]:
            raise ValueError(f"threshold changed: {row['id']}")
        if row["id"] != "maximum_symbol_confirmed_concentration" and row["scope"].split(", ")[0] != "each market independently":
            raise ValueError(f"threshold {row['id']} is not market-independent")
    symbol = next(row for row in thresholds if row["id"] == "maximum_symbol_confirmed_concentration")
    if symbol["aggregation"] != "PER_MARKET_PER_CANDIDATE_INDEPENDENT" or not symbol["candidate_event_sets_must_not_be_combined"]:
        raise ValueError("symbol concentration must be independently evaluated by market/candidate")


def _validate_selection_rule(rule: Mapping[str, Any]) -> None:
    if rule["type"] != "LEXICOGRAPHIC_CONSERVATIVE" or tuple(rule["ordered_candidates_pct"]) != PRODUCTION_TOLERANCES:
        raise ValueError("selection rule changed")
    if "independently in CN" not in rule["qualification_semantics"] or "no market may compensate" not in rule["qualification_semantics"]:
        raise ValueError("CN/US independent qualification semantics missing")
    if not rule["selection_is_not_executed_in_phase5j_v2"] or rule["performance_metrics_used"] or rule["market_specific_or_regime_specific_selection"]:
        raise ValueError("selection is executable or performance-driven")
    matrix = rule["candidate_qualification_matrix"]
    if len(matrix) != 3:
        raise ValueError("candidate qualification matrix changed")
    for row, expected in zip(matrix, EXPECTED_CANDIDATE_QUALIFICATION_MATRIX):
        if row["candidate_pct"] != expected["candidate_pct"] or tuple(row["candidate_level_threshold_ids"]) != EXPECTED_CANDIDATE_LEVEL_THRESHOLD_IDS or tuple(row["adjacent_pair_threshold_ids"]) != EXPECTED_ADJACENT_PAIR_THRESHOLD_IDS or tuple(tuple(pair) for pair in row["adjacent_pairs"]) != expected["adjacent_pairs"]:
            raise ValueError("candidate qualification matrix changed")


__all__ = [
    "DIAGNOSTIC_STRESS_BOUNDARIES", "EXPECTED_PROTOCOL_VERSION", "EXPECTED_V1_PROTOCOL_SHA256",
    "EXPECTED_CANDIDATE_LEVEL_THRESHOLD_IDS", "EXPECTED_ADJACENT_PAIR_THRESHOLD_IDS",
    "EXPECTED_CANDIDATE_QUALIFICATION_MATRIX", "PINNED_PROTOCOL_SHA256_BY_VERSION",
    "PRODUCTION_TOLERANCES", "PROTOCOL_PATH", "PROTOCOL_STATUS", "REQUIRED_FORBIDDEN_METRICS",
    "VALIDATION_MARKETS", "load_protocol", "protocol_integrity_hash", "serialize_protocol",
]

"""Integrity loader for the frozen Phase 5J-v4 attribution protocol."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_PATH = Path(__file__).with_name("protocols") / "setup03_phase5j_v4_lifecycle_attribution_protocol.json"
EXPECTED_PROTOCOL_VERSION = "SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1"
EXPECTED_PROTOCOL_SHA256 = "sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def protocol_integrity_hash(protocol: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(protocol))
    payload.pop("integrity", None)
    return f"sha256:{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    return protocol


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("protocol_version") != EXPECTED_PROTOCOL_VERSION:
        raise ValueError("Phase 5J-v4 protocol version changed")
    stored = protocol.get("integrity", {}).get("protocol_sha256")
    if stored != protocol_integrity_hash(protocol):
        raise ValueError("Phase 5J-v4 protocol integrity mismatch")
    if stored != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Phase 5J-v4 protocol version is bound to a different hash")
    if protocol.get("status") != "LIFECYCLE_ATTRIBUTION_PROTOCOL_FROZEN_NOT_EXECUTED":
        raise ValueError("Phase 5J-v4 protocol execution state changed")
    exact = protocol.get("evidence_scope", {}).get("exact_causal_replay", {})
    if (
        exact.get("total_symbol_count") != 40
        or exact.get("total_bar_count") != 86305
        or exact.get("replay_aggregate_sha256") != "sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2"
    ):
        raise ValueError("Phase 5J-v4 frozen holdout binding changed")
    semantics = protocol.get("production_semantics", {})
    if semantics.get("adjacent_pairs") != [[0.03, 0.04], [0.04, 0.05]]:
        raise ValueError("Phase 5J-v4 adjacent tolerance pairs changed")
    if semantics.get("instrumentation_must_not_change_output") is not True:
        raise ValueError("Phase 5J-v4 production parity requirement weakened")
    root_rules = protocol.get("root_cause_taxonomy", {}).get("ordered_primary_rules", [])
    expected_roots = [
        "HIGH_SPAN_THRESHOLD_CROSSING", "LOW_SPAN_THRESHOLD_CROSSING",
        "BOTH_SPAN_THRESHOLD_CROSSING", "STRUCTURE_INPUT_DIVERGENCE",
        "NEW_SWING_ELIGIBILITY_DIVERGENCE", "PLATFORM_FIRST_DETECTION_DIVERGENCE",
        "FROZEN_BREAKOUT_ANCHOR_DIVERGENCE", "FROZEN_INVALIDATION_ANCHOR_DIVERGENCE",
        "TERMINAL_STATE_DIVERGENCE", "OTHER_UNCLASSIFIED",
    ]
    if [rule.get("cause") for rule in root_rules] != expected_roots:
        raise ValueError("Phase 5J-v4 root-cause taxonomy changed")
    prohibited_evidence = set(protocol.get("prohibited_evidence", []))
    if not {"Final OOS", "forward returns", "MFE", "MAE", "P&L", "winrate", "profit factor", "expectancy"}.issubset(prohibited_evidence):
        raise ValueError("Phase 5J-v4 prohibited evidence weakened")
    stop = protocol.get("stop_and_decision_states", {})
    if stop.get("final_state") != "PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION" or stop.get("merge_prohibited") is not True:
        raise ValueError("Phase 5J-v4 stop state changed")


__all__ = ["EXPECTED_PROTOCOL_SHA256", "EXPECTED_PROTOCOL_VERSION", "canonical_json", "load_protocol", "protocol_integrity_hash", "validate_protocol"]

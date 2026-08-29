"""Hash-pinned protocol loader for the bounded ATR boundary redesign."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


PROTOCOL_PATH = Path(__file__).parent / "protocols" / "setup03_atr_boundary_structural_qualification_protocol.json"
PROTOCOL_VERSION = "SETUP_03-ATR-BOUNDARY-STRUCTURAL-QUALIFICATION-2026-08-29-v1"
EXPECTED_PROTOCOL_SHA256: str | None = "sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def protocol_integrity_hash(protocol: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(protocol))
    integrity = dict(payload.get("integrity", {}))
    integrity["protocol_sha256"] = None
    payload["integrity"] = integrity
    return f"sha256:{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"


def load_protocol(path: Path = PROTOCOL_PATH) -> dict[str, Any]:
    protocol = json.loads(path.read_text(encoding="utf-8"))
    _validate(protocol)
    return protocol


def _validate(protocol: Mapping[str, Any]) -> None:
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("ATR boundary protocol version changed")
    if protocol.get("status") != "ATR_BOUNDARY_PROTOCOL_FROZEN_NOT_EXECUTED":
        raise ValueError("ATR boundary protocol must remain frozen")
    stored = protocol.get("integrity", {}).get("protocol_sha256")
    if stored != protocol_integrity_hash(protocol):
        raise ValueError("ATR boundary protocol integrity mismatch")
    if EXPECTED_PROTOCOL_SHA256 is not None and stored != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("ATR boundary protocol hash changed")
    boundary = protocol.get("boundary_semantics", {})
    atr = boundary.get("atr", {})
    if boundary.get("mode") != "ATR_NORMALIZED" or atr.get("indicator") != "WILDER_ATR" or atr.get("period") != 14:
        raise ValueError("ATR boundary semantics changed")
    if boundary.get("candidate_thresholds_atr") != [1.0, 1.5, 2.0, 2.5]:
        raise ValueError("ATR candidate family changed")
    if boundary.get("candidate_count") != 4:
        raise ValueError("ATR candidate count changed")
    if boundary.get("fixed_setup_parameters") != {"swing_lookback": 5, "platform_window": 40, "arm_proximity_pct": 0.0}:
        raise ValueError("ATR fixed setup parameters changed")
    selection = protocol.get("independent_holdout_selection", {})
    if selection.get("target_counts") != {"CN": 20, "US": 20, "total": 40} or not selection.get("ranking", {}).get("result_independent"):
        raise ValueError("clean holdout selection contract changed")
    qualification = protocol.get("qualification", {})
    if qualification.get("scope") != "CN and US independently; no market compensation":
        raise ValueError("market qualification independence changed")
    if qualification.get("production_selection") is not False or qualification.get("outcome_metrics") is not False:
        raise ValueError("qualification boundary weakened")
    if protocol.get("boundaries", {}).get("provider_access_before_universe_freeze") is not False:
        raise ValueError("provider-before-freeze boundary weakened")
    if "second_volatility_family" not in protocol.get("prohibited_actions", []):
        raise ValueError("second volatility family prohibition missing")


__all__ = ["EXPECTED_PROTOCOL_SHA256", "PROTOCOL_PATH", "PROTOCOL_VERSION", "canonical_json", "load_protocol", "protocol_integrity_hash"]

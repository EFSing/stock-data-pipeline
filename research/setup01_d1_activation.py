"""Immutable activation records for the SETUP_01 D1 prospective collector.

An activation record is deliberately separate from the frozen D1 protocol.  It
binds one market to the durable backend, source/observer contract, and the
first eligible natural exchange session.  No historical or diagnostic input
can satisfy this contract.
"""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Mapping

from research.setup01_d1_prospective import (
    D1IntegrityError,
    PROTOCOL_VERSION,
    content_sha256,
    prospective_window,
    verify_frozen_protocol,
)


ACTIVATION_SCHEMA_VERSION = "setup01-d1-activation-record-v1"
ACTIVATION_SCHEMA_VERSION_V2 = "setup01-d1-activation-record-v2"
SOURCE_CONTRACT_V1 = "SETUP01_D1_SOURCE_OBSERVER_CONTRACT_V1"
SOURCE_CONTRACT_V2 = "SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2"
ACTIVATION_LEGACY_PREFIX = "system/activation"
ACTIVATION_EPOCH_PREFIX = "system/activation_epochs"
ACTIVATION_STATUS = "D1_ACTIVATION_READY_FOR_FIRST_ELIGIBLE_SESSION"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)
SOURCE_CONTRACT_VERSION_RE = re.compile(
    r"^SETUP01_D1_[A-Z0-9]+(?:_[A-Z0-9]+)*_V[0-9]+$"
)


def _aware_iso(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("activation_timestamp must be timezone-aware")
    return parsed.isoformat()


def _sha(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return text


def _code_sha(value: Any) -> str:
    text = str(value or "").strip()
    if not GIT_SHA_RE.fullmatch(text):
        raise ValueError("code_sha must be a Git commit SHA")
    return text


def normalize_source_contract_version(value: Any) -> str:
    """Normalize the explicit source-contract identity used by D1 epochs."""

    text = str(value or "").strip()
    if not SOURCE_CONTRACT_VERSION_RE.fullmatch(text):
        raise ValueError("source_contract_version must be a versioned SETUP01_D1 contract")
    return text


def activation_path(market: str, source_contract_version: str) -> str:
    """Return the immutable storage path for one market/contract epoch.

    V1 keeps its historical path byte-for-byte.  Every later contract gets a
    separate append-only epoch path; there is intentionally no ``current`` or
    mtime selector.
    """

    normalized_market = str(market or "").strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError("activation market must be CN or US")
    version = normalize_source_contract_version(source_contract_version)
    if version == SOURCE_CONTRACT_V1:
        return f"{ACTIVATION_LEGACY_PREFIX}/{normalized_market}.json"
    return f"{ACTIVATION_EPOCH_PREFIX}/{normalized_market}/{version}.json"


def parse_activation_path(name: str) -> tuple[str, str]:
    """Parse a canonical activation path, rejecting ambiguous layouts."""

    # Storage names are relative canonical keys.  Do not normalize away a
    # leading/trailing slash: accepting it would make malformed external
    # names indistinguishable from the immutable layout.
    text = str(name or "").strip()
    legacy = re.fullmatch(rf"{re.escape(ACTIVATION_LEGACY_PREFIX)}/(CN|US)\.json", text)
    if legacy:
        return legacy.group(1), SOURCE_CONTRACT_V1
    epoch = re.fullmatch(
        rf"{re.escape(ACTIVATION_EPOCH_PREFIX)}/(CN|US)/([^/]+)\.json",
        text,
    )
    if epoch:
        version = normalize_source_contract_version(epoch.group(2))
        if version == SOURCE_CONTRACT_V1:
            raise D1IntegrityError("V1 activation must use the legacy activation path")
        return epoch.group(1), version
    raise D1IntegrityError("activation path is outside the immutable activation layout")


def activation_path_for_record(record: Mapping[str, Any]) -> str:
    """Return the only canonical path authorized by a validated record."""

    market = str(record.get("market") or "").strip().upper()
    source = record.get("source_contract")
    source_version = record.get("source_contract_version")
    if source_version is None and isinstance(source, Mapping):
        source_version = source.get("contract_version")
    return activation_path(market, normalize_source_contract_version(source_version))


def _iso_date(value: Any, field: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise D1IntegrityError(f"activation record {field} is not an ISO date") from exc
    return parsed.isoformat()


def _frozen_package() -> dict[str, Any]:
    root = verify_frozen_protocol()
    import json
    from pathlib import Path

    protocol_path = Path(__file__).resolve().parents[1] / "research" / "protocols" / "setup01_post_breakout_d1_prospective_v1.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    selected = dict(protocol.get("selected_package") or {})
    return {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": root["protocol_sha256"],
        "signal_stop_exit_gate": selected,
    }


def build_activation_record(
    *,
    market: str,
    activation_timestamp: str,
    backend_identity: str,
    backend_version: str,
    storage_identity_sha256: str,
    code_sha: str,
    source_contract: Mapping[str, Any],
    observer_version: str,
    source_contract_version: str,
) -> dict[str, Any]:
    """Build an activation record without performing any storage write."""

    normalized_market = str(market).strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError("activation market must be CN or US")
    if not str(backend_identity).strip() or not str(backend_version).strip():
        raise ValueError("backend identity and version are required")
    if not str(observer_version).strip():
        raise ValueError("observer_version is required")
    if not isinstance(source_contract, Mapping):
        raise ValueError("source_contract is required")
    if source_contract.get("status") != "VERIFIED":
        raise D1IntegrityError("D1_SOURCE_ACTIVATION_CONTRACT_PENDING")
    if not source_contract.get("contract_version"):
        raise ValueError("source contract version is required")
    selected_contract_version = normalize_source_contract_version(source_contract_version)
    if selected_contract_version not in {SOURCE_CONTRACT_V1, SOURCE_CONTRACT_V2}:
        raise ValueError("unsupported D1 source contract version")
    if source_contract.get("contract_version") != selected_contract_version:
        raise ValueError("source contract version does not match source contract")

    activation = _aware_iso(activation_timestamp)
    window = prospective_window(normalized_market, datetime.fromisoformat(activation))
    frozen = _frozen_package()
    record = {
        "schema_version": (
            ACTIVATION_SCHEMA_VERSION_V2
            if selected_contract_version == SOURCE_CONTRACT_V2
            else ACTIVATION_SCHEMA_VERSION
        ),
        "status": ACTIVATION_STATUS,
        "market": normalized_market,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": frozen["protocol_sha256"],
        "backend_identity": str(backend_identity),
        "backend_version": str(backend_version),
        "storage_identity_sha256": _sha(storage_identity_sha256, "storage_identity_sha256"),
        "code_sha": _code_sha(code_sha),
        "signal_stop_exit_gate_frozen": frozen["signal_stop_exit_gate"],
        "activation_timestamp": activation,
        "first_eligible_full_exchange_session": window["start_session_date"],
        "end_boundary_local_date": window["end_boundary_local_date"],
        "last_eligible_session_date": window["last_eligible_session_date"],
        "final_cutoff_bjt": window["final_cutoff_bjt"],
        "calendar_horizon_status": window["calendar_horizon_status"],
        "source_contract": dict(source_contract),
        "cost_scenario": dict(source_contract.get("cost_scenario") or {}),
        "observer_version": str(observer_version),
        "research_only": True,
        "formal_entry_allowed": False,
        "real_fill_evidence": False,
        "production_state_write": False,
        "paper_write": False,
        "broker_order": False,
    }
    # The V1 record shape is frozen.  Only the new epoch schema carries the
    # explicit version field; old V1 activation bytes and hashes remain valid.
    if selected_contract_version == SOURCE_CONTRACT_V2:
        record["source_contract_version"] = selected_contract_version
    record["record_sha256"] = content_sha256(record)
    return record


def validate_activation_record(
    record: Mapping[str, Any],
    *,
    expected_backend_identity: str | None = None,
    expected_backend_version: str | None = None,
    expected_storage_identity_sha256: str | None = None,
) -> None:
    """Validate an activation record before it can authorize a commit."""

    schema_version = record.get("schema_version")
    if schema_version not in {ACTIVATION_SCHEMA_VERSION, ACTIVATION_SCHEMA_VERSION_V2}:
        raise D1IntegrityError("activation record schema mismatch")
    without_hash = dict(record)
    actual = without_hash.pop("record_sha256", None)
    if actual != content_sha256(without_hash):
        raise D1IntegrityError("activation record hash mismatch")
    market = str(record.get("market") or "").upper()
    if market not in {"CN", "US"}:
        raise D1IntegrityError("activation record market mismatch")
    if record.get("status") != ACTIVATION_STATUS:
        raise D1IntegrityError("activation record is not ready")
    if record.get("protocol_version") != PROTOCOL_VERSION:
        raise D1IntegrityError("activation record protocol mismatch")
    frozen = verify_frozen_protocol()
    if record.get("protocol_sha256") != frozen["protocol_sha256"]:
        raise D1IntegrityError("activation record frozen protocol mismatch")
    if expected_backend_identity is not None and record.get("backend_identity") != expected_backend_identity:
        raise D1IntegrityError("activation record backend identity mismatch")
    if expected_backend_version is not None and record.get("backend_version") != expected_backend_version:
        raise D1IntegrityError("activation record backend version mismatch")
    if (
        expected_storage_identity_sha256 is not None
        and record.get("storage_identity_sha256") != expected_storage_identity_sha256
    ):
        raise D1IntegrityError("activation record storage identity mismatch")
    _sha(record.get("storage_identity_sha256"), "storage_identity_sha256")
    _code_sha(record.get("code_sha"))
    _aware_iso(str(record.get("activation_timestamp") or ""))
    first_session = _iso_date(
        record.get("first_eligible_full_exchange_session"),
        "first_eligible_full_exchange_session",
    )
    end_boundary = _iso_date(record.get("end_boundary_local_date"), "end_boundary_local_date")
    if first_session >= end_boundary:
        raise D1IntegrityError("activation record window is empty")
    source = record.get("source_contract")
    if not isinstance(source, Mapping) or source.get("status") != "VERIFIED":
        raise D1IntegrityError("activation record source contract mismatch")
    expected_contract_version = (
        SOURCE_CONTRACT_V2
        if schema_version == ACTIVATION_SCHEMA_VERSION_V2
        else SOURCE_CONTRACT_V1
    )
    record_version = record.get("source_contract_version", source.get("contract_version"))
    try:
        normalized_record_version = normalize_source_contract_version(record_version)
    except ValueError as exc:
        raise D1IntegrityError("activation record source contract version is invalid") from exc
    if normalized_record_version != expected_contract_version:
        raise D1IntegrityError("activation record source contract version mismatch")
    if source.get("contract_version") != expected_contract_version:
        raise D1IntegrityError("activation source contract version mismatch")
    if not record.get("observer_version"):
        raise D1IntegrityError("activation record observer version missing")
    if not isinstance(record.get("cost_scenario"), Mapping):
        raise D1IntegrityError("activation record cost scenario missing")


def session_is_in_activation_window(record: Mapping[str, Any], session_date: str) -> bool:
    """Return whether a local exchange session is inside the frozen window."""

    validate_activation_record(record)
    value = _iso_date(session_date, "session_date")
    return (
        str(record["first_eligible_full_exchange_session"]) <= value
        < str(record["end_boundary_local_date"])
    )


__all__ = [
    "ACTIVATION_SCHEMA_VERSION",
    "ACTIVATION_SCHEMA_VERSION_V2",
    "ACTIVATION_EPOCH_PREFIX",
    "ACTIVATION_LEGACY_PREFIX",
    "ACTIVATION_STATUS",
    "SOURCE_CONTRACT_V1",
    "SOURCE_CONTRACT_V2",
    "activation_path",
    "activation_path_for_record",
    "build_activation_record",
    "normalize_source_contract_version",
    "parse_activation_path",
    "session_is_in_activation_window",
    "validate_activation_record",
]

"""Phase 5K-B1-A IBKR provider readiness and contract identity freeze.

This module is deliberately limited to provider preflight, US contract
identity resolution, and ``reqHeadTimeStamp`` capability probes.  It never
requests historical bars and it has no dependency on the production quote,
HiThink, replay, SETUP_03, Decision, Sheets, or execution paths.

The live adapter imports the official ``ibapi`` package lazily.  The rest of
the module is pure and testable without TWS/IB Gateway or the package being
installed.  A readiness manifest is only considered frozen when its version
is bound to an externally pinned canonical SHA-256; rebuilding a hash inside
the same version is intentionally insufficient.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, Sequence

from research.phase5k_a1_universe import load_manifest
from research.phase5k_b0_dataset_contract import (
    CONTRACT_STATUS as B0_STATUS,
    CONTRACT_VERSION as B0_VERSION,
    EXPECTED_MANIFEST_SHA256,
    EXPECTED_MANIFEST_STATUS,
    EXPECTED_MANIFEST_VERSION,
    PINNED_CONTRACT_SHA256 as B0_SHA256,
    load_contract,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "artifacts" / "phase5k_b1a_ibkr_provider_readiness.json"

SCHEMA_VERSION = "setup03-phase5k-b1a-ibkr-provider-readiness-manifest-v1"
MANIFEST_VERSION = "SETUP_03-PHASE5K-B1-A-IBKR-PROVIDER-READINESS-2026-08-28-v1"
FROZEN_STATUS = "IBKR_US_PROVIDER_READINESS_FROZEN_NOT_ACQUIRED"
PROVIDER_NOT_READY_STATUS = "US_PROVIDER_NOT_READY"
CONNECTION_NOT_READY_STATUS = "IBKR_CONNECTION_NOT_READY"
VERSION_NOT_PROVEN_STATUS = "IBKR_VERSION_NOT_PROVEN"

IDENTITY_UNIQUE_STATUS = "UNIQUE_RESOLVED"
IDENTITY_NOT_RESOLVABLE_STATUS = "SYMBOL_NOT_RESOLVABLE"
IDENTITY_AMBIGUOUS_STATUS = "CONTRACT_IDENTITY_NOT_UNIQUE"
HEAD_READY_STATUS = "UNIQUE_RESOLVED_ADJUSTED_LAST_READY"
HEAD_UNAVAILABLE_STATUS = "ADJUSTED_LAST_UNAVAILABLE"
PERMISSION_STATUS = "NO_IBKR_PERMISSION"

REQ_CONTRACT_DETAILS = "reqContractDetails"
REQ_HEAD_TIMESTAMP = "reqHeadTimeStamp"
WHAT_TO_SHOW = "ADJUSTED_LAST"
USE_RTH = 1
FORMAT_DATE = 1
SEC_TYPE = "STK"
EXCHANGE = "SMART"
CURRENCY = "USD"

NORMALIZATION_RULE_VERSION = "IBKR-US-SYMBOL-NORMALIZATION-2026-08-28-v1"
NORMALIZATION_RULE = MappingProxyType(
    {
        "version": NORMALIZATION_RULE_VERSION,
        "input": "A1 canonical_symbol",
        "operations": ["strip_ascii_whitespace", "uppercase_ascii", "replace_literal_period_with_single_space"],
        "purpose": "provider syntax/share-class normalization only",
        "alias_table": [],
        "manual_symbol_mapping_allowed": False,
        "invalid_input": "fail_closed",
    }
)

# This is intentionally empty until a real, reviewed B1-A capture is
# committed.  A generated manifest must be added here in the same change as
# its frozen artifact; callers may pass an immutable expected mapping in tests
# or during the review step.  The loader never treats a self-rehashed value as
# a pin.
PINNED_MANIFEST_SHA256_BY_VERSION = MappingProxyType({})

PERMISSION_ERROR_CODES = frozenset({354, 10167, 10276})
PERMISSION_ERROR_FRAGMENTS = (
    "not subscribed",
    "no market data permissions",
    "permission",
    "not authorized",
)
REQUEST_TERMINAL_ERROR_CODES = frozenset({162, 200, 321, 354, 420, 10167, 10276})


class ReadinessError(RuntimeError):
    """A fail-closed B1-A stop with a machine-readable status."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ConnectionConfig:
    """Non-secret connection configuration read from the required env vars."""

    host: str
    port: int
    client_id: int
    application: str

    @property
    def host_role(self) -> str:
        lowered = self.host.lower().strip("[]")
        if lowered in {"localhost", "127.0.0.1", "::1"}:
            return "localhost"
        return "remote_host"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ConnectionConfig":
        env = os.environ if environ is None else environ
        missing = [name for name in ("IBKR_HOST", "IBKR_PORT", "IBKR_CLIENT_ID") if not env.get(name)]
        if missing:
            raise ReadinessError(CONNECTION_NOT_READY_STATUS, "missing required IBKR connection environment variable")
        try:
            port = int(env["IBKR_PORT"])
            client_id = int(env["IBKR_CLIENT_ID"])
        except (TypeError, ValueError) as exc:
            raise ReadinessError(CONNECTION_NOT_READY_STATUS, "IBKR_PORT and IBKR_CLIENT_ID must be integers") from exc
        if not (1 <= port <= 65535) or client_id < 0:
            raise ReadinessError(CONNECTION_NOT_READY_STATUS, "IBKR connection port/client id is invalid")
        application = str(env.get("IBKR_APPLICATION", "")).strip().upper()
        if application not in {"TWS", "IB_GATEWAY"}:
            raise ReadinessError(
                VERSION_NOT_PROVEN_STATUS,
                "IBKR_APPLICATION must identify TWS or IB_GATEWAY; the API does not reliably expose this identity",
            )
        return cls(host=str(env["IBKR_HOST"]).strip(), port=port, client_id=client_id, application=application)


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_json(value: Mapping[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("integrity", None)
    return sha256_json(payload)


def _safe_text(value: Any) -> str:
    """Return provider text with common secret/account forms redacted."""
    text = str(value or "")
    text = re.sub(r"(?i)(password|passwd|secret|token|session)[\s:=]+[^\s,;]+", r"\1=<redacted>", text)
    text = re.sub(r"\b(?:DU|U|FA|F)\d{5,}\b", "<account-redacted>", text, flags=re.IGNORECASE)
    return text


def normalize_ibkr_symbol(canonical_symbol: str) -> str:
    """Apply the one pre-registered mechanical provider syntax rule."""
    if not isinstance(canonical_symbol, str):
        raise ValueError("canonical_symbol must be a string")
    source = canonical_symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]+(?:[.][A-Z0-9]+)*", source):
        raise ValueError("canonical_symbol is outside the registered IBKR normalization grammar")
    normalized = source.replace(".", " ")
    if not re.fullmatch(r"[A-Z0-9]+(?: [A-Z0-9]+)*", normalized):
        raise ValueError("normalized IBKR symbol is invalid")
    return normalized


def validate_parent_pins() -> tuple[dict[str, Any], dict[str, Any]]:
    """Load B0 and A1 through their own immutable contracts and recheck pins."""
    b0 = load_contract()
    a1 = load_manifest()
    if (
        b0.get("contract_version") != B0_VERSION
        or b0.get("status") != B0_STATUS
        or b0.get("integrity", {}).get("contract_sha256") != B0_SHA256
        or b0.get("parent_a1_manifest", {}).get("version") != EXPECTED_MANIFEST_VERSION
        or b0.get("parent_a1_manifest", {}).get("sha256") != EXPECTED_MANIFEST_SHA256
        or b0.get("parent_a1_manifest", {}).get("status") != EXPECTED_MANIFEST_STATUS
    ):
        raise ReadinessError(PROVIDER_NOT_READY_STATUS, "B0 v2 exact pin is not active")
    if (
        a1.get("manifest_version") != EXPECTED_MANIFEST_VERSION
        or a1.get("integrity", {}).get("manifest_sha256") != EXPECTED_MANIFEST_SHA256
        or a1.get("status") != EXPECTED_MANIFEST_STATUS
    ):
        raise ReadinessError(PROVIDER_NOT_READY_STATUS, "A1 v2 exact pin is not active")
    return b0, a1


def load_us_candidates(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Require exactly the frozen A1 40 PRIMARY + 20 RESERVE US roster."""
    rows = [dict(row) for row in manifest.get("symbols", []) if row.get("market") == "US"]
    if len(rows) != 60:
        raise ValueError("A1 input must contain exactly 60 US candidates")
    if sum(row.get("intended_role") == "PRIMARY" for row in rows) != 40:
        raise ValueError("A1 input must contain exactly 40 US PRIMARY candidates")
    if sum(row.get("intended_role") == "RESERVE" for row in rows) != 20:
        raise ValueError("A1 input must contain exactly 20 US RESERVE candidates")
    symbols = [row.get("canonical_symbol") for row in rows]
    ranks = [row.get("manifest_rank") for row in rows]
    if any(not isinstance(symbol, str) or not symbol for symbol in symbols) or len(set(symbols)) != 60:
        raise ValueError("A1 US canonical symbols must be unique and non-empty")
    if sorted(ranks) != list(range(1, 61)):
        raise ValueError("A1 US manifest ranks must be exactly 1..60")
    return sorted(rows, key=lambda row: row["manifest_rank"])


def build_contract_request(canonical_symbol: str) -> dict[str, Any]:
    """Return the exact identity-resolution request projection."""
    return {
        "method": REQ_CONTRACT_DETAILS,
        "contract": {
            "symbol": normalize_ibkr_symbol(canonical_symbol),
            "secType": SEC_TYPE,
            "exchange": EXCHANGE,
            "currency": CURRENCY,
        },
    }


def build_head_timestamp_request(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact capability-probe request; no historical bars are requested."""
    required = ("ibkr_symbol", "conId", "secType", "exchange", "primaryExchange", "currency")
    missing = [field for field in required if not identity.get(field)]
    if missing:
        raise ValueError(f"resolved identity missing required fields: {missing}")
    if identity["secType"] != SEC_TYPE or identity["exchange"] != EXCHANGE or identity["currency"] != CURRENCY:
        raise ValueError("resolved identity does not satisfy the registered US stock contract rule")
    return {
        "method": REQ_HEAD_TIMESTAMP,
        "contract": {
            "symbol": str(identity["ibkr_symbol"]),
            "conId": int(identity["conId"]),
            "secType": SEC_TYPE,
            "exchange": EXCHANGE,
            "primaryExchange": str(identity["primaryExchange"]),
            "currency": CURRENCY,
        },
        "whatToShow": WHAT_TO_SHOW,
        "useRTH": USE_RTH,
        "formatDate": FORMAT_DATE,
    }


def _field(value: Any, name: str, default: Any = "") -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _jsonable(value: Any, seen: set[int] | None = None) -> Any:
    """Convert an ibapi details object into a complete deterministic snapshot."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("contract-details snapshot contains a non-finite number")
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if seen is None:
        seen = set()
    object_id = id(value)
    if object_id in seen:
        raise ValueError("contract-details snapshot contains a cyclic object")
    if isinstance(value, Mapping):
        seen.add(object_id)
        result = {str(key): _jsonable(item, seen) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
        seen.remove(object_id)
        return result
    if isinstance(value, (list, tuple)):
        seen.add(object_id)
        result = [_jsonable(item, seen) for item in value]
        seen.remove(object_id)
        return result
    if isinstance(value, (set, frozenset)):
        items = [_jsonable(item, seen) for item in value]
        return sorted(items, key=lambda item: canonical_json({"value": item}))
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        seen.add(object_id)
        result = {
            str(key): _jsonable(item, seen)
            for key, item in sorted(attributes.items(), key=lambda pair: str(pair[0]))
            if not callable(item)
        }
        seen.remove(object_id)
        return {value.__class__.__name__: result}
    raise ValueError(f"unsupported contract-details field type: {type(value).__name__}")


def contract_details_snapshot(details: Any) -> dict[str, Any]:
    """Serialize all public object state and return its SHA-256 hash."""
    snapshot = _jsonable(details)
    if not isinstance(snapshot, dict):
        raise ValueError("contract-details snapshot must be an object")
    return {"snapshot": snapshot, "snapshot_sha256": sha256_json(snapshot)}


def _candidate_identity(details: Any) -> dict[str, Any]:
    contract = _field(details, "contract", {})
    raw_con_id = _field(contract, "conId", 0)
    try:
        con_id = int(raw_con_id)
    except (TypeError, ValueError):
        con_id = 0
    return {
        "ibkr_symbol": str(_field(contract, "symbol", "")),
        "conId": con_id,
        "secType": str(_field(contract, "secType", "")),
        "exchange": str(_field(contract, "exchange", "")),
        "primaryExchange": str(_field(contract, "primaryExchange", "")),
        "currency": str(_field(contract, "currency", "")),
        "localSymbol": str(_field(contract, "localSymbol", "")),
        "tradingClass": str(_field(contract, "tradingClass", "")),
        "validExchanges": str(_field(details, "validExchanges", "")),
        "longName": str(_field(details, "longName", "")),
    }


def _valid_candidate(identity: Mapping[str, Any], expected_symbol: str) -> bool:
    valid_exchanges = {part.strip().upper() for part in str(identity.get("validExchanges", "")).split(",") if part.strip()}
    return (
        identity.get("ibkr_symbol") == expected_symbol
        and isinstance(identity.get("conId"), int)
        and identity["conId"] > 0
        and identity.get("secType") == SEC_TYPE
        and identity.get("exchange") == EXCHANGE
        and bool(identity.get("primaryExchange"))
        and identity.get("currency") == CURRENCY
        and (not valid_exchanges or EXCHANGE in valid_exchanges)
    )


def _classify_error(code: Any, message: Any) -> str:
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = -1
    text = str(message or "").lower()
    if numeric_code in PERMISSION_ERROR_CODES or any(fragment in text for fragment in PERMISSION_ERROR_FRAGMENTS):
        return PERMISSION_STATUS
    return IDENTITY_NOT_RESOLVABLE_STATUS


def _safe_error(error: Mapping[str, Any] | Sequence[Any]) -> dict[str, Any]:
    if isinstance(error, Mapping):
        code = error.get("code", error.get("error_code", ""))
        message = error.get("message", error.get("error_message", ""))
    else:
        code = error[0] if len(error) > 0 else ""
        message = error[1] if len(error) > 1 else ""
    return {"code": code, "message": _safe_text(message)}


def resolve_identity_candidates(
    canonical_symbol: str,
    details: Iterable[Any],
    errors: Iterable[Mapping[str, Any] | Sequence[Any]] = (),
) -> dict[str, Any]:
    """Select zero/one/many candidates fail-closed, with no manual choice."""
    expected_symbol = normalize_ibkr_symbol(canonical_symbol)
    snapshots: list[dict[str, Any]] = []
    valid: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for details_item in details:
        snapshot = contract_details_snapshot(details_item)
        identity = _candidate_identity(details_item)
        snapshots.append(snapshot)
        if _valid_candidate(identity, expected_symbol):
            valid.append((identity, snapshot))
    safe_errors = [_safe_error(error) for error in errors]
    error_statuses = {_classify_error(error["code"], error["message"]) for error in safe_errors}
    if PERMISSION_STATUS in error_statuses and not valid:
        status = PERMISSION_STATUS
    elif len(valid) == 0:
        status = IDENTITY_NOT_RESOLVABLE_STATUS
    elif len(valid) > 1:
        status = IDENTITY_AMBIGUOUS_STATUS
    else:
        status = IDENTITY_UNIQUE_STATUS
    selected_identity = dict(valid[0][0]) if status == IDENTITY_UNIQUE_STATUS else None
    selected_snapshot = dict(valid[0][1]) if status == IDENTITY_UNIQUE_STATUS else None
    return {
        "status": status,
        "identity": selected_identity,
        "selected_snapshot": selected_snapshot,
        "candidate_count": len(valid),
        "candidate_snapshots": snapshots,
        "errors": safe_errors,
    }


class ReadinessSession(Protocol):
    def preflight_metadata(self) -> Mapping[str, Any]: ...

    def resolve_contract(self, canonical_symbol: str, ibkr_symbol: str) -> Mapping[str, Any]: ...

    def probe_head_timestamp(self, identity: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _validate_connection_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    required = ("application", "api_version", "server_version", "tws_version", "host_role", "connection_timestamp")
    if any(not metadata.get(field) for field in required):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API/server/TWS version metadata is not reliably proven")
    if str(metadata["application"]).upper() not in {"TWS", "IB_GATEWAY"}:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "connected application is not proven to be TWS or IB Gateway")
    try:
        if int(metadata["server_version"]) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR server version is invalid") from exc
    return {
        "application": str(metadata["application"]).upper(),
        "api_client_version": str(metadata.get("api_client_version", metadata["api_version"])),
        "api_version": str(metadata["api_version"]),
        "server_version": int(metadata["server_version"]),
        "tws_version": str(metadata["tws_version"]),
        "tws_version_source": str(metadata.get("tws_version_source", "ibapi")),
        "host_role": str(metadata["host_role"]),
        "connection_timestamp": str(metadata["connection_timestamp"]),
    }


def _candidate_record(a1_row: Mapping[str, Any], normalized_symbol: str, timestamp: str) -> dict[str, Any]:
    return {
        "market": "US",
        "canonical_symbol": a1_row["canonical_symbol"],
        "canonical_identity": a1_row["canonical_identity"],
        "source_cohort": a1_row["source_cohort"],
        "intended_role": a1_row["intended_role"],
        "manifest_rank": a1_row["manifest_rank"],
        "ibkr_symbol": normalized_symbol,
        "identity_request_timestamp": timestamp,
        "identity_status": None,
        "contract_identity": None,
        "selected_contract_details_snapshot": None,
        "selected_contract_details_snapshot_sha256": None,
        "all_contract_details_snapshots": [],
        "identity_errors": [],
        "adjusted_last_probe": None,
        "readiness_status": None,
    }


def _readiness_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def counts(role: str) -> dict[str, int]:
        subset = [row for row in records if row["intended_role"] == role]
        return {
            "candidates": len(subset),
            "unique_resolved": sum(row["identity_status"] == IDENTITY_UNIQUE_STATUS for row in subset),
            "adjusted_last_ready": sum(row["readiness_status"] == HEAD_READY_STATUS for row in subset),
        }

    primary = counts("PRIMARY")
    reserve = counts("RESERVE")
    return {
        "primary_40": primary,
        "reserve_20": reserve,
        "total_candidate_pool": sum(row["readiness_status"] == HEAD_READY_STATUS for row in records),
        "all_60_unique_resolved": all(row["identity_status"] == IDENTITY_UNIQUE_STATUS for row in records),
        "all_60_adjusted_last_ready": all(row["readiness_status"] == HEAD_READY_STATUS for row in records),
    }


def build_readiness_manifest(
    *,
    b0: Mapping[str, Any],
    a1: Mapping[str, Any],
    connection: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the B1-A snapshot without promoting or replacing any roster row."""
    summary = _readiness_summary(records)
    all_ready = summary["all_60_unique_resolved"] and summary["all_60_adjusted_last_ready"]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": MANIFEST_VERSION,
        "phase": "Phase 5K-B1-A",
        "status": FROZEN_STATUS if all_ready else PROVIDER_NOT_READY_STATUS,
        "parent_b0": {
            "version": b0["contract_version"],
            "sha256": b0["integrity"]["contract_sha256"],
            "status": b0["status"],
            "path": "research/phase5k_b0_dataset_acquisition_contract_v2.json",
        },
        "parent_a1": {
            "version": a1["manifest_version"],
            "sha256": a1["integrity"]["manifest_sha256"],
            "status": a1["status"],
            "path": "research/phase5k_a1_universe_manifest_v2.json",
        },
        "connection": dict(connection),
        "identity_resolution_rule": {
            "method": REQ_CONTRACT_DETAILS,
            "input_count": 60,
            "required_input_roles": {"PRIMARY": 40, "RESERVE": 20},
            "contract_filter": {"secType": SEC_TYPE, "exchange": EXCHANGE, "currency": CURRENCY},
            "valid_candidate_rule": "exactly one valid returned contract; zero or more than one fails closed",
            "manual_contract_choice_allowed": False,
            "required_frozen_fields": [
                "canonical_symbol", "ibkr_symbol", "conId", "secType", "exchange", "primaryExchange",
                "currency", "localSymbol", "tradingClass", "validExchanges", "longName",
            ],
        },
        "symbol_normalization_rule": dict(NORMALIZATION_RULE),
        "candidates": [dict(record) for record in records],
        "reqHeadTimeStamp_contract": {
            "method": REQ_HEAD_TIMESTAMP,
            "whatToShow": WHAT_TO_SHOW,
            "useRTH": USE_RTH,
            "formatDate": FORMAT_DATE,
            "purpose": "historical service and ADJUSTED_LAST capability only",
            "ohlcv_requested": False,
        },
        "readiness_summary": summary,
        "unresolved_ambiguous_audit": [
            {
                "canonical_symbol": row["canonical_symbol"],
                "identity_status": row["identity_status"],
                "readiness_status": row["readiness_status"],
                "identity_errors": row["identity_errors"],
                "candidate_count": len(row["all_contract_details_snapshots"]),
            }
            for row in records
            if row["readiness_status"] != HEAD_READY_STATUS
        ],
        "prohibitions": [
            "reqHistoricalData",
            "formal validation OHLCV",
            "HiThink formal OHLCV",
            "B1 dataset construction",
            "SETUP_03",
            "CONFIRMED",
            "final OOS",
            "parameter modification",
            "Google Sheets",
            "trading or order submission",
            "PRIMARY/RESERVE replacement in B1-A",
        ],
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest["integrity"] = {
        "hash_algorithm": "SHA-256",
        "canonicalization": "UTF-8 JSON, sorted keys, compact separators, excluding integrity envelope",
        "manifest_sha256": manifest_integrity_hash(manifest),
    }
    return manifest


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    expected_hash_by_version: Mapping[str, str] | None = None,
) -> None:
    """Validate a frozen artifact against an immutable version/hash contract."""
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("B1-A readiness manifest schema version changed")
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError("unexpected B1-A readiness manifest version")
    stored = manifest.get("integrity", {}).get("manifest_sha256")
    actual = manifest_integrity_hash(manifest)
    if stored != actual:
        raise ValueError("B1-A readiness manifest integrity mismatch")
    pinned = (expected_hash_by_version or PINNED_MANIFEST_SHA256_BY_VERSION).get(MANIFEST_VERSION)
    if not pinned:
        raise ValueError("B1-A readiness manifest version has no immutable SHA-256 pin")
    if stored != pinned:
        raise ValueError("B1-A readiness manifest version is bound to a different canonical hash")
    if manifest.get("parent_b0", {}).get("version") != B0_VERSION or manifest.get("parent_b0", {}).get("sha256") != B0_SHA256:
        raise ValueError("B1-A readiness manifest B0 parent pin changed")
    if manifest.get("parent_b0", {}).get("status") != B0_STATUS:
        raise ValueError("B1-A readiness manifest B0 parent status changed")
    if manifest.get("parent_a1", {}).get("version") != EXPECTED_MANIFEST_VERSION or manifest.get("parent_a1", {}).get("sha256") != EXPECTED_MANIFEST_SHA256:
        raise ValueError("B1-A readiness manifest A1 parent pin changed")
    if manifest.get("parent_a1", {}).get("status") != EXPECTED_MANIFEST_STATUS:
        raise ValueError("B1-A readiness manifest A1 parent status changed")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 60:
        raise ValueError("B1-A readiness manifest must contain exactly 60 candidates")
    if sum(row.get("intended_role") == "PRIMARY" for row in candidates) != 40:
        raise ValueError("B1-A readiness manifest must contain 40 PRIMARY candidates")
    if sum(row.get("intended_role") == "RESERVE" for row in candidates) != 20:
        raise ValueError("B1-A readiness manifest must contain 20 RESERVE candidates")
    if sorted(row.get("manifest_rank") for row in candidates) != list(range(1, 61)):
        raise ValueError("B1-A readiness manifest candidate ranks must be exactly 1..60")
    if len({row.get("canonical_symbol") for row in candidates}) != 60:
        raise ValueError("B1-A readiness manifest canonical symbols must be unique")
    allowed_identity = {
        IDENTITY_UNIQUE_STATUS,
        IDENTITY_NOT_RESOLVABLE_STATUS,
        IDENTITY_AMBIGUOUS_STATUS,
        PERMISSION_STATUS,
    }
    allowed_readiness = allowed_identity | {HEAD_READY_STATUS, HEAD_UNAVAILABLE_STATUS}
    for row in candidates:
        if row.get("identity_status") not in allowed_identity:
            raise ValueError("B1-A readiness manifest contains an invalid identity status")
        if row.get("readiness_status") not in allowed_readiness:
            raise ValueError("B1-A readiness manifest contains an invalid readiness status")
    if manifest.get("status") not in {FROZEN_STATUS, PROVIDER_NOT_READY_STATUS}:
        raise ValueError("B1-A readiness manifest status is invalid")
    if manifest.get("symbol_normalization_rule") != dict(NORMALIZATION_RULE):
        raise ValueError("B1-A symbol normalization rule changed")
    probe_contract = manifest.get("reqHeadTimeStamp_contract", {})
    if {
        "method": probe_contract.get("method"),
        "whatToShow": probe_contract.get("whatToShow"),
        "useRTH": probe_contract.get("useRTH"),
        "formatDate": probe_contract.get("formatDate"),
    } != {
        "method": REQ_HEAD_TIMESTAMP,
        "whatToShow": WHAT_TO_SHOW,
        "useRTH": USE_RTH,
        "formatDate": FORMAT_DATE,
    } or probe_contract.get("ohlcv_requested") is not False:
        raise ValueError("B1-A reqHeadTimeStamp contract changed")
    required_identity = ("ibkr_symbol", "conId", "secType", "exchange", "primaryExchange", "currency")
    for row in candidates:
        identity = row.get("contract_identity")
        if row["identity_status"] == IDENTITY_UNIQUE_STATUS:
            if not isinstance(identity, Mapping) or any(not identity.get(field) for field in required_identity):
                raise ValueError("B1-A unique identity is missing a required contract field")
            if identity["secType"] != SEC_TYPE or identity["exchange"] != EXCHANGE or identity["currency"] != CURRENCY:
                raise ValueError("B1-A unique identity contract fields changed")
            selected = row.get("selected_contract_details_snapshot")
            if not isinstance(selected, Mapping) or sha256_json(selected.get("snapshot", {})) != selected.get("snapshot_sha256"):
                raise ValueError("B1-A selected contract-details snapshot hash mismatch")
        elif identity is not None:
            raise ValueError("B1-A non-unique identity must not select a contract")


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_readiness(session: ReadinessSession) -> dict[str, Any]:
    """Resolve all A1 US candidates and probe ADJUSTED_LAST capability."""
    b0, a1 = validate_parent_pins()
    candidates = load_us_candidates(a1)
    connection = _validate_connection_metadata(session.preflight_metadata())
    records: list[dict[str, Any]] = []
    for row in candidates:
        canonical_symbol = row["canonical_symbol"]
        normalized_symbol = normalize_ibkr_symbol(canonical_symbol)
        identity_request_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record = _candidate_record(row, normalized_symbol, identity_request_time)
        response = session.resolve_contract(canonical_symbol, normalized_symbol)
        resolution = resolve_identity_candidates(
            canonical_symbol,
            response.get("details", []),
            response.get("errors", []),
        )
        record["identity_status"] = resolution["status"]
        record["contract_identity"] = resolution["identity"]
        record["selected_contract_details_snapshot"] = resolution["selected_snapshot"]
        record["selected_contract_details_snapshot_sha256"] = (
            resolution["selected_snapshot"].get("snapshot_sha256") if resolution["selected_snapshot"] else None
        )
        record["all_contract_details_snapshots"] = resolution["candidate_snapshots"]
        record["identity_errors"] = resolution["errors"]
        if resolution["status"] != IDENTITY_UNIQUE_STATUS:
            record["readiness_status"] = resolution["status"]
            records.append(record)
            continue
        identity = dict(resolution["identity"])
        probe = dict(session.probe_head_timestamp(identity))
        probe["whatToShow"] = WHAT_TO_SHOW
        probe["useRTH"] = USE_RTH
        probe["formatDate"] = FORMAT_DATE
        probe["request_contract"] = build_head_timestamp_request(identity)["contract"]
        if probe.get("success") is True and probe.get("head_timestamp"):
            record["readiness_status"] = HEAD_READY_STATUS
        else:
            code = probe.get("error_code", probe.get("code", ""))
            message = probe.get("error_message", probe.get("message", ""))
            probe["error_message"] = _safe_text(message)
            record["readiness_status"] = PERMISSION_STATUS if _classify_error(code, message) == PERMISSION_STATUS else HEAD_UNAVAILABLE_STATUS
        record["adjusted_last_probe"] = probe
        records.append(record)
    return build_readiness_manifest(b0=b0, a1=a1, connection=connection, records=records)


class _PendingRequest:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.details: list[Any] = []
        self.errors: list[dict[str, Any]] = []
        self.head_timestamp: str | None = None


class OfficialIbapiSession:
    """Small official ibapi adapter used only by the B1-A readiness runner."""

    def __init__(self, config: ConnectionConfig, timeout_seconds: float = 15.0) -> None:
        try:
            from ibapi.client import EClient
            from ibapi.contract import Contract
            from ibapi.wrapper import EWrapper
        except ImportError as exc:
            raise ReadinessError(CONNECTION_NOT_READY_STATUS, "official ibapi package is not installed") from exc
        try:
            api_version = importlib.metadata.version("ibapi")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "ibapi package version is not available") from exc

        session = self

        class App(EWrapper, EClient):
            def __init__(self) -> None:
                EClient.__init__(self, self)
                self.ready_event = threading.Event()
                self.connection_error: dict[str, Any] | None = None
                self.pending: dict[int, _PendingRequest] = {}
                self.pending_lock = threading.Lock()

            def nextValidId(self, orderId: int) -> None:  # noqa: N802 - official ibapi callback
                self.ready_event.set()

            def contractDetails(self, reqId: int, contractDetails: Any) -> None:  # noqa: N802
                with self.pending_lock:
                    pending = self.pending.get(reqId)
                    if pending is not None:
                        pending.details.append(contractDetails)

            def contractDetailsEnd(self, reqId: int) -> None:  # noqa: N802
                with self.pending_lock:
                    pending = self.pending.get(reqId)
                    if pending is not None:
                        pending.event.set()

            def headTimestamp(self, reqId: int, headTimestamp: str) -> None:  # noqa: N802, A002
                with self.pending_lock:
                    pending = self.pending.get(reqId)
                    if pending is not None:
                        pending.head_timestamp = str(headTimestamp)
                        pending.event.set()

            def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = "") -> None:  # noqa: N802
                with self.pending_lock:
                    pending = self.pending.get(reqId)
                    if pending is not None:
                        pending.errors.append({"code": errorCode, "message": _safe_text(errorString)})
                        if reqId >= 0 and errorCode in REQUEST_TERMINAL_ERROR_CODES:
                            pending.event.set()
                    elif reqId < 0:
                        session.connection_error = {"code": errorCode, "message": _safe_text(errorString)}

        self._Contract = Contract
        self._app = App()
        self._config = config
        self._timeout = timeout_seconds
        self._api_version = api_version
        self._thread: threading.Thread | None = None
        self._next_request_id = 1
        self._request_lock = threading.Lock()

    def __enter__(self) -> "OfficialIbapiSession":
        try:
            self._app.connect(self._config.host, self._config.port, self._config.client_id)
        except Exception as exc:  # pragma: no cover - requires local TWS/IBG
            raise ReadinessError(CONNECTION_NOT_READY_STATUS, "IBKR TWS/IB Gateway connection failed") from exc
        self._thread = threading.Thread(target=self._app.run, name="ibkr-readiness-api", daemon=True)
        self._thread.start()
        if not self._app.ready_event.wait(self._timeout):
            self.close()
            raise ReadinessError(CONNECTION_NOT_READY_STATUS, "IBKR nextValidId was not received before timeout")
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self._app, "isConnected", lambda: False)():
            self._app.disconnect()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _request_id(self) -> int:
        with self._request_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            return request_id

    def preflight_metadata(self) -> Mapping[str, Any]:
        try:
            server_version = int(self._app.serverVersion())
        except (AttributeError, TypeError, ValueError) as exc:
            raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR server version is not reliably available") from exc
        tws_version = None
        tws_source = None
        for name in ("tws_version", "twsVersion", "twsVersionString"):
            value = getattr(self._app, name, None)
            if value and not callable(value):
                tws_version = str(value)
                tws_source = f"ibapi.{name}"
                break
        if not tws_version:
            raise ReadinessError(
                VERSION_NOT_PROVEN_STATUS,
                "official ibapi transport did not expose a reliable TWS/IB Gateway version",
            )
        return {
            "application": self._config.application,
            "api_client_version": self._api_version,
            "api_version": self._api_version,
            "server_version": server_version,
            "tws_version": tws_version,
            "tws_version_source": tws_source,
            "host_role": self._config.host_role,
            "connection_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def _contract_object(self, wire: Mapping[str, Any]) -> Any:
        contract = self._Contract()
        for key, value in wire.items():
            setattr(contract, key, value)
        return contract

    def resolve_contract(self, canonical_symbol: str, ibkr_symbol: str) -> Mapping[str, Any]:
        request_id = self._request_id()
        pending = _PendingRequest()
        with self._app.pending_lock:
            self._app.pending[request_id] = pending
        wire = build_contract_request(canonical_symbol)["contract"]
        wire["symbol"] = ibkr_symbol
        try:
            self._app.reqContractDetails(request_id, self._contract_object(wire))
            pending.event.wait(self._timeout)
            return {"details": list(pending.details), "errors": list(pending.errors)}
        finally:
            with self._app.pending_lock:
                self._app.pending.pop(request_id, None)

    def probe_head_timestamp(self, identity: Mapping[str, Any]) -> Mapping[str, Any]:
        request_id = self._request_id()
        pending = _PendingRequest()
        with self._app.pending_lock:
            self._app.pending[request_id] = pending
        request = build_head_timestamp_request(identity)
        request_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            contract = self._contract_object(request["contract"])
            self._app.reqHeadTimestamp(request_id, contract, WHAT_TO_SHOW, USE_RTH, FORMAT_DATE)
            completed = pending.event.wait(self._timeout)
            response: dict[str, Any] = {
                "request_timestamp": request_timestamp,
                "success": bool(completed and pending.head_timestamp and not pending.errors),
                "head_timestamp": pending.head_timestamp,
            }
            if pending.errors:
                response["error_code"] = pending.errors[-1]["code"]
                response["error_message"] = pending.errors[-1]["message"]
            return response
        finally:
            with self._app.pending_lock:
                self._app.pending.pop(request_id, None)


__all__ = [
    "B0_SHA256",
    "B0_STATUS",
    "B0_VERSION",
    "ConnectionConfig",
    "CONNECTION_NOT_READY_STATUS",
    "CURRENCY",
    "EXCHANGE",
    "FROZEN_STATUS",
    "FORMAT_DATE",
    "HEAD_READY_STATUS",
    "HEAD_UNAVAILABLE_STATUS",
    "IDENTITY_AMBIGUOUS_STATUS",
    "IDENTITY_NOT_RESOLVABLE_STATUS",
    "IDENTITY_UNIQUE_STATUS",
    "MANIFEST_VERSION",
    "NORMALIZATION_RULE",
    "NORMALIZATION_RULE_VERSION",
    "PINNED_MANIFEST_SHA256_BY_VERSION",
    "PROVIDER_NOT_READY_STATUS",
    "REQ_CONTRACT_DETAILS",
    "REQ_HEAD_TIMESTAMP",
    "ReadinessError",
    "SEC_TYPE",
    "VERSION_NOT_PROVEN_STATUS",
    "WHAT_TO_SHOW",
    "build_contract_request",
    "build_head_timestamp_request",
    "build_readiness_manifest",
    "canonical_json",
    "contract_details_snapshot",
    "load_us_candidates",
    "manifest_integrity_hash",
    "normalize_ibkr_symbol",
    "resolve_identity_candidates",
    "run_readiness",
    "sha256_json",
    "validate_manifest",
    "validate_parent_pins",
    "write_manifest",
]

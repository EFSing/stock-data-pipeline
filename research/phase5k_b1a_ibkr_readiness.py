"""Phase 5K-B1-A IBKR provider readiness and contract identity freeze.

This module is deliberately limited to provider preflight, US contract
identity resolution, and ``reqHeadTimeStamp`` capability probes.  It never
requests historical bars and it has no dependency on the production quote,
HiThink, replay, SETUP_03, Decision, Sheets, or execution paths.

The live adapter imports ``ibapi`` lazily only from an operator-declared
official IBKR TWS API distribution path.  It never installs or falls back to
a PyPI package or a third-party wrapper.  The rest of the module is pure and
testable without TWS/IB Gateway or the client being installed.  A readiness
manifest is only considered frozen when its version is bound to an externally
pinned canonical SHA-256; rebuilding a hash inside the same version is
intentionally insufficient.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import threading
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, Sequence
from urllib.parse import urlparse

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
CAPTURE_MODE = "capture"
VALIDATE_EXISTING_MODE = "validate-existing"
FROZEN_STATUS = "IBKR_US_PROVIDER_READINESS_FROZEN"
FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS = "IBKR_PROVIDER_READINESS_FROZEN_NOT_ACQUIRED"
PROVIDER_NOT_READY_STATUS = "US_PROVIDER_NOT_READY"
CONNECTION_NOT_READY_STATUS = "IBKR_CONNECTION_NOT_READY"
VERSION_NOT_PROVEN_STATUS = "IBKR_VERSION_NOT_PROVEN"

IDENTITY_UNIQUE_STATUS = "UNIQUE_RESOLVED"
IDENTITY_NOT_RESOLVABLE_STATUS = "SYMBOL_NOT_RESOLVABLE"
IDENTITY_AMBIGUOUS_STATUS = "CONTRACT_IDENTITY_NOT_UNIQUE"
HEAD_READY_STATUS = "UNIQUE_RESOLVED_ADJUSTED_LAST_READY"
HEAD_UNAVAILABLE_STATUS = "ADJUSTED_LAST_UNAVAILABLE"
PERMISSION_STATUS = "NO_IBKR_PERMISSION"
FROZEN_CANDIDATE_STATUSES = frozenset(
    {
        IDENTITY_NOT_RESOLVABLE_STATUS,
        IDENTITY_AMBIGUOUS_STATUS,
        HEAD_READY_STATUS,
        HEAD_UNAVAILABLE_STATUS,
        PERMISSION_STATUS,
    }
)

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

OFFICIAL_API_PROVIDER = "Interactive Brokers"
OFFICIAL_API_SOURCE_CLASS = "IBKR_OFFICIAL_TWS_API_DISTRIBUTION"
API_PYTHON_PATH_ENV = "IBKR_TWS_API_PYTHON_PATH"
API_PROVENANCE_FILE_ENV = "IBKR_API_PROVENANCE_FILE"
HOST_VERSION_EVIDENCE_FILE_ENV = "IBKR_HOST_VERSION_EVIDENCE_FILE"
HOST_VERSION_SOURCE_CLASSES = frozenset(
    {
        "IBKR_TWS_ABOUT_DIALOG",
        "IBKR_IB_GATEWAY_ABOUT_DIALOG",
        "IBKR_OFFICIAL_INSTALLER_METADATA",
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
# IBKR sends normal farm-status notices through error(reqId=-1).  They must
# not be mistaken for transport failure before nextValidId or between probes.
NON_FAILURE_SYSTEM_ERROR_CODES = frozenset({2104, 2106, 2107, 2108, 2158})


class ReadinessError(RuntimeError):
    """A fail-closed B1-A stop with a machine-readable status."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR provenance evidence file is not readable") from exc


def _official_package_source_sha256(package_root: Path) -> str:
    """Hash Python source files in an official client package deterministically."""
    try:
        source_files = sorted(
            path for path in package_root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".py", ".pyi"}
        )
        entries = {
            path.relative_to(package_root).as_posix(): _sha256_file(path)
            for path in source_files
        }
    except OSError as exc:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "official IBKR Python client source is not readable") from exc
    return sha256_json(entries)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, f"{label} is not readable machine-readable JSON") from exc
    if not isinstance(value, dict):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, f"{label} must contain a JSON object")
    return value


def _absolute_path(
    value: Any,
    env_name: str,
    *,
    missing_status: str = VERSION_NOT_PROVEN_STATUS,
) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ReadinessError(missing_status, f"{env_name} is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ReadinessError(missing_status, f"{env_name} must be an absolute path")
    return path.resolve()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_official_ibkr_reference(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme in {"http", "https"} and (
        host in {"interactivebrokers.com", "interactivebrokers.github.io"}
        or host.endswith(".interactivebrokers.com")
    )


def _validate_api_provenance(
    provenance: Mapping[str, Any],
    *,
    python_root: Path,
    package_root: Path,
) -> dict[str, Any]:
    required = (
        "provider",
        "source_class",
        "package_name",
        "package_version",
        "package_source_sha256",
        "source_reference",
        "recorded_at",
    )
    if any(not provenance.get(field) for field in required):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR official API provenance is incomplete")
    if provenance["provider"] != OFFICIAL_API_PROVIDER or provenance["source_class"] != OFFICIAL_API_SOURCE_CLASS:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API provenance is not an official TWS API distribution")
    if provenance["package_name"] != "ibapi":
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API provenance package is not ibapi")
    package_version = str(provenance["package_version"]).strip()
    if not package_version or any(char.isspace() for char in package_version):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR official API package version is invalid")
    source_hash = str(provenance["package_source_sha256"])
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", source_hash):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR official API source hash is invalid")
    source_reference = str(provenance["source_reference"]).strip()
    if not _is_official_ibkr_reference(source_reference):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API provenance source is not an IBKR reference")
    if not _path_is_within(package_root, python_root):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR Python client package is outside the declared source root")
    actual_source_hash = _official_package_source_sha256(package_root)
    if actual_source_hash != source_hash:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR official API source hash does not match the declared provenance")
    return {
        "provider": OFFICIAL_API_PROVIDER,
        "source_class": OFFICIAL_API_SOURCE_CLASS,
        "package_name": "ibapi",
        "package_version": package_version,
        "package_source_sha256": actual_source_hash,
        "source_reference": source_reference,
        "recorded_at": str(provenance["recorded_at"]),
    }


def _validate_host_version_evidence(
    evidence: Mapping[str, Any],
    *,
    expected_application: str,
) -> dict[str, Any]:
    required = ("application", "version", "source_class", "source_reference", "recorded_at")
    if any(not evidence.get(field) for field in required):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway version evidence is incomplete")
    application = str(evidence["application"]).strip().upper()
    if application != expected_application:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway version evidence does not match IBKR_APPLICATION")
    version = str(evidence["version"]).strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+._A-Za-z0-9]+)?", version):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway application version is invalid")
    source_class = str(evidence["source_class"]).strip()
    if source_class not in HOST_VERSION_SOURCE_CLASSES:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway version source is not an approved evidence class")
    return {
        "application": application,
        "version": version,
        "source_class": source_class,
        "source_reference": str(evidence["source_reference"]).strip(),
        "recorded_at": str(evidence["recorded_at"]),
    }


@dataclass(frozen=True)
class ConnectionConfig:
    """Non-secret connection and provenance configuration read from env vars."""

    host: str
    port: int
    client_id: int
    application: str
    api_python_path: Path
    api_provenance_file: Path
    host_version_evidence_file: Path

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
        api_python_path = _absolute_path(
            env.get(API_PYTHON_PATH_ENV), API_PYTHON_PATH_ENV, missing_status=PROVIDER_NOT_READY_STATUS,
        )
        api_provenance_file = _absolute_path(env.get(API_PROVENANCE_FILE_ENV), API_PROVENANCE_FILE_ENV)
        host_version_evidence_file = _absolute_path(
            env.get(HOST_VERSION_EVIDENCE_FILE_ENV), HOST_VERSION_EVIDENCE_FILE_ENV,
        )
        return cls(
            host=str(env["IBKR_HOST"]).strip(),
            port=port,
            client_id=client_id,
            application=application,
            api_python_path=api_python_path,
            api_provenance_file=api_provenance_file,
            host_version_evidence_file=host_version_evidence_file,
        )


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
        error_time = error.get("error_time")
        code = error.get("code", error.get("error_code", ""))
        message = error.get("message", error.get("error_message", ""))
    else:
        error_time = None
        code = error[0] if len(error) > 0 else ""
        message = error[1] if len(error) > 1 else ""
    result = {"code": code, "message": _safe_text(message)}
    if error_time is not None:
        result["error_time"] = error_time
    return result


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
    required = (
        "application",
        "api_client_version",
        "api_version",
        "api_provenance",
        "server_version",
        "tws_version",
        "tws_version_provenance",
        "tws_version_source",
        "tws_version_evidence_sha256",
        "host_role",
        "connection_timestamp",
    )
    if any(not metadata.get(field) for field in required):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API/server/TWS version metadata is not reliably proven")
    if str(metadata["application"]).upper() not in {"TWS", "IB_GATEWAY"}:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "connected application is not proven to be TWS or IB Gateway")
    api_provenance = metadata["api_provenance"]
    if not isinstance(api_provenance, Mapping):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API provenance metadata is invalid")
    if (
        api_provenance.get("provider") != OFFICIAL_API_PROVIDER
        or api_provenance.get("source_class") != OFFICIAL_API_SOURCE_CLASS
        or api_provenance.get("package_name") != "ibapi"
        or not api_provenance.get("package_version")
        or not api_provenance.get("package_source_sha256")
        or not _is_official_ibkr_reference(str(api_provenance.get("source_reference", "")))
    ):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API provenance metadata is not official and complete")
    if (
        str(api_provenance["package_version"]) != str(metadata["api_client_version"])
        or str(api_provenance["package_version"]) != str(metadata["api_version"])
    ):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API version metadata does not match its provenance")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(api_provenance["package_source_sha256"])):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR API provenance source hash is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(metadata["tws_version_evidence_sha256"])):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway version evidence hash is invalid")
    host_provenance = metadata["tws_version_provenance"]
    if not isinstance(host_provenance, Mapping):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway version provenance metadata is invalid")
    if (
        str(host_provenance.get("application", "")).upper() != str(metadata["application"]).upper()
        or host_provenance.get("version") != metadata["tws_version"]
        or host_provenance.get("source_class") != metadata["tws_version_source"]
        or host_provenance.get("evidence_file_sha256") != metadata["tws_version_evidence_sha256"]
        or not host_provenance.get("source_reference")
        or not host_provenance.get("recorded_at")
    ):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway version provenance metadata is incomplete")
    if host_provenance["source_class"] not in HOST_VERSION_SOURCE_CLASSES:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway version source class is invalid")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+._A-Za-z0-9]+)?", str(metadata["tws_version"])):
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "TWS/IB Gateway application version is invalid")
    try:
        if int(metadata["server_version"]) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "IBKR server version is invalid") from exc
    return {
        "application": str(metadata["application"]).upper(),
        "api_client_version": str(metadata["api_client_version"]),
        "api_version": str(metadata["api_version"]),
        "api_provenance": {
            "provider": OFFICIAL_API_PROVIDER,
            "source_class": OFFICIAL_API_SOURCE_CLASS,
            "package_name": "ibapi",
            "package_version": str(api_provenance["package_version"]),
            "package_source_sha256": str(api_provenance["package_source_sha256"]),
            "source_reference": str(api_provenance["source_reference"]),
            "recorded_at": str(api_provenance.get("recorded_at", "")),
        },
        "server_version": int(metadata["server_version"]),
        "tws_version": str(metadata["tws_version"]),
        "tws_version_provenance": {
            "application": str(host_provenance["application"]).upper(),
            "version": str(host_provenance["version"]),
            "source_class": str(host_provenance["source_class"]),
            "source_reference": str(host_provenance["source_reference"]),
            "recorded_at": str(host_provenance["recorded_at"]),
            "evidence_file_sha256": str(host_provenance["evidence_file_sha256"]),
        },
        "tws_version_source": str(metadata["tws_version_source"]),
        "tws_version_evidence_sha256": str(metadata["tws_version_evidence_sha256"]),
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
    all_60_terminal = len(records) == 60 and all(
        row.get("readiness_status") in FROZEN_CANDIDATE_STATUSES for row in records
    )
    return {
        "primary_40": primary,
        "reserve_20": reserve,
        "total_candidate_pool": sum(row["readiness_status"] == HEAD_READY_STATUS for row in records),
        "all_60_unique_resolved": all(row["identity_status"] == IDENTITY_UNIQUE_STATUS for row in records),
        "all_60_adjusted_last_ready": all(row["readiness_status"] == HEAD_READY_STATUS for row in records),
        "all_60_terminal": all_60_terminal,
        "provider_capture_complete": all_60_terminal,
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
    capture_complete = summary["provider_capture_complete"]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": MANIFEST_VERSION,
        "phase": "Phase 5K-B1-A",
        # This is the provider-level capture result. Formal acceptance still
        # requires the immutable version pin and validate_manifest().
        "status": FROZEN_STATUS if capture_complete else PROVIDER_NOT_READY_STATUS,
        "freeze_artifact_status": FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS,
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
    if manifest.get("freeze_artifact_status") != FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS:
        raise ValueError("B1-A freeze artifact status changed")
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
    allowed_readiness = FROZEN_CANDIDATE_STATUSES
    for row in candidates:
        if row.get("identity_status") not in allowed_identity:
            raise ValueError("B1-A readiness manifest contains an invalid identity status")
        if row.get("readiness_status") not in allowed_readiness:
            raise ValueError("B1-A readiness manifest contains an invalid readiness status")
    if manifest.get("status") not in {FROZEN_STATUS, PROVIDER_NOT_READY_STATUS}:
        raise ValueError("B1-A readiness manifest status is invalid")
    summary = manifest.get("readiness_summary")
    expected_capture_complete = all(
        row.get("readiness_status") in FROZEN_CANDIDATE_STATUSES for row in candidates
    )
    if (
        not isinstance(summary, Mapping)
        or summary.get("all_60_terminal") is not expected_capture_complete
        or summary.get("provider_capture_complete") is not expected_capture_complete
    ):
        raise ValueError("B1-A provider capture completeness summary is invalid")
    if manifest["status"] == FROZEN_STATUS and not expected_capture_complete:
        raise ValueError("B1-A frozen provider status requires terminal status for all 60 candidates")
    if manifest["status"] == PROVIDER_NOT_READY_STATUS and expected_capture_complete:
        raise ValueError("B1-A provider-not-ready status contradicts a complete candidate capture")
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


def load_saved_manifest(path: Path) -> dict[str, Any]:
    """Read a previously written manifest without contacting a provider."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(
            FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS,
            "saved B1-A readiness manifest is not readable machine-readable JSON",
        ) from exc
    if not isinstance(value, dict):
        raise ReadinessError(
            FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS,
            "saved B1-A readiness manifest must contain a JSON object",
        )
    return value


def accept_frozen_manifest(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept a saved capture only after the committed immutable pin validates."""
    try:
        if manifest.get("status") != FROZEN_STATUS:
            raise ValueError("provider readiness capture is incomplete")
        # Do not accept a caller-supplied self-hash here. The production gate
        # must use the immutable version->SHA contract committed in this module.
        validate_manifest(manifest)
    except (TypeError, ValueError) as exc:
        raise ReadinessError(
            FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS,
            "saved provider readiness capture has not passed immutable pin validation",
        ) from exc
    return manifest


def validate_existing_manifest(path: Path) -> Mapping[str, Any]:
    """Validate an existing capture using only the committed version/hash pin.

    This function intentionally has no session/configuration argument.  Its
    only input is the saved JSON file, so the validate-existing operation
    cannot connect to TWS/IB Gateway or issue either readiness request.
    """
    return accept_frozen_manifest(load_saved_manifest(path))


def _transport_blocker(response: Mapping[str, Any], operation: str) -> str | None:
    """Return a provider-level blocker for a non-terminal API response."""
    if not isinstance(response, Mapping):
        return f"{operation} response is not machine-readable"
    if response.get("transport_error"):
        return f"{operation} transport failure"
    if response.get("provider_error"):
        return f"{operation} provider failure"
    if response.get("terminal") is not True or response.get("completed") is False:
        return f"{operation} did not receive a terminal response"
    return None


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
        blocker = _transport_blocker(response, REQ_CONTRACT_DETAILS)
        if blocker:
            raise ReadinessError(PROVIDER_NOT_READY_STATUS, blocker)
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
        probe_response = session.probe_head_timestamp(identity)
        blocker = _transport_blocker(probe_response, REQ_HEAD_TIMESTAMP)
        if blocker:
            raise ReadinessError(PROVIDER_NOT_READY_STATUS, blocker)
        probe = dict(probe_response)
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
        self.terminal_response = False
        self.transport_error: dict[str, Any] | None = None


def _load_official_ibapi(config: ConnectionConfig) -> tuple[Any, Any, Any, dict[str, Any]]:
    """Load only the ibapi package under the declared official distribution root."""
    python_root = config.api_python_path
    package_root = python_root / "ibapi"
    if not python_root.is_dir() or not package_root.is_dir():
        raise ReadinessError(PROVIDER_NOT_READY_STATUS, "official IBKR TWS API Python client path is unavailable")
    provenance = _validate_api_provenance(
        _read_json_object(config.api_provenance_file, "IBKR API provenance file"),
        python_root=python_root,
        package_root=package_root,
    )
    existing = sys.modules.get("ibapi")
    existing_file = getattr(existing, "__file__", None) if existing is not None else None
    if existing_file and not _path_is_within(Path(existing_file), python_root):
        raise ReadinessError(PROVIDER_NOT_READY_STATUS, "an ibapi module outside the declared official distribution is already loaded")
    if existing is None:
        sys.path.insert(0, str(python_root))
    try:
        importlib.invalidate_caches()
        ibapi = importlib.import_module("ibapi")
        client = importlib.import_module("ibapi.client")
        contract = importlib.import_module("ibapi.contract")
        wrapper = importlib.import_module("ibapi.wrapper")
    except (ImportError, OSError) as exc:
        raise ReadinessError(PROVIDER_NOT_READY_STATUS, "official IBKR TWS API Python client cannot be imported") from exc
    for module in (ibapi, client, contract, wrapper):
        module_file = getattr(module, "__file__", None)
        if not module_file or not _path_is_within(Path(module_file), python_root):
            raise ReadinessError(PROVIDER_NOT_READY_STATUS, "loaded IBKR Python client is outside the declared official distribution")
    declared_module_version = getattr(ibapi, "__version__", None)
    if declared_module_version and str(declared_module_version) != provenance["package_version"]:
        raise ReadinessError(VERSION_NOT_PROVEN_STATUS, "loaded IBKR Python client version disagrees with its provenance")
    return client.EClient, contract.Contract, wrapper.EWrapper, provenance


class OfficialIbapiSession:
    """Small official-distribution ibapi adapter used only by B1-A."""

    def __init__(self, config: ConnectionConfig, timeout_seconds: float = 15.0) -> None:
        EClient, Contract, EWrapper, api_provenance = _load_official_ibapi(config)
        host_evidence_raw = _read_json_object(config.host_version_evidence_file, "TWS/IB Gateway version evidence file")
        host_evidence = _validate_host_version_evidence(
            host_evidence_raw,
            expected_application=config.application,
        )
        host_evidence["evidence_file_sha256"] = _sha256_file(config.host_version_evidence_file)

        session = self

        class App(EWrapper, EClient):
            def __init__(self) -> None:
                EClient.__init__(self, self)
                self.ready_event = threading.Event()
                self.connection_error: dict[str, Any] | None = None
                self.pending: dict[int, _PendingRequest] = {}
                self.pending_lock = threading.Lock()

            def _fail_transport(self, error: Mapping[str, Any]) -> None:
                failure = dict(error)
                with self.pending_lock:
                    session.connection_error = failure
                    for pending in self.pending.values():
                        pending.transport_error = dict(failure)
                        pending.event.set()
                    self.ready_event.set()

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
                        pending.terminal_response = True
                        pending.event.set()

            def headTimestamp(self, reqId: int, headTimestamp: str) -> None:  # noqa: N802, A002
                with self.pending_lock:
                    pending = self.pending.get(reqId)
                    if pending is not None:
                        pending.head_timestamp = str(headTimestamp)
                        pending.terminal_response = True
                        pending.event.set()

            def connectionClosed(self) -> None:  # noqa: N802
                self._fail_transport({
                    "status": "CONNECTION_LOST",
                    "message": "IBKR API connection closed",
                })

            def error(
                self,
                reqId: int,
                errorTime: int,
                errorCode: int,
                errorString: str,
                advancedOrderRejectJson: str = "",
            ) -> None:  # noqa: N802, N803
                error: dict[str, Any] | None = None
                with self.pending_lock:
                    pending = self.pending.get(reqId)
                    if pending is not None:
                        pending.errors.append({
                            "error_time": errorTime,
                            "code": errorCode,
                            "message": _safe_text(errorString),
                        })
                        if reqId >= 0 and errorCode in REQUEST_TERMINAL_ERROR_CODES:
                            pending.terminal_response = True
                            pending.event.set()
                    elif reqId < 0 and errorCode not in NON_FAILURE_SYSTEM_ERROR_CODES:
                        error = {
                            "error_time": errorTime,
                            "code": errorCode,
                            "message": _safe_text(errorString),
                        }
                    else:
                        error = None
                if error is not None:
                    self._fail_transport(error)

        self._Contract = Contract
        self._app = App()
        self._config = config
        self._timeout = timeout_seconds
        self._api_provenance = api_provenance
        self._host_evidence = host_evidence
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
        if not self._app.ready_event.wait(self._timeout) or self._app.connection_error is not None:
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
        return {
            "application": self._host_evidence["application"],
            "api_client_version": self._api_provenance["package_version"],
            "api_version": self._api_provenance["package_version"],
            "api_provenance": dict(self._api_provenance),
            "server_version": server_version,
            "tws_version": self._host_evidence["version"],
            "tws_version_provenance": dict(self._host_evidence),
            "tws_version_source": self._host_evidence["source_class"],
            "tws_version_evidence_sha256": self._host_evidence["evidence_file_sha256"],
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
            try:
                self._app.reqContractDetails(request_id, self._contract_object(wire))
            except Exception:
                return {
                    "details": [],
                    "errors": [],
                    "terminal": False,
                    "transport_error": {
                        "status": "REQUEST_SUBMISSION_FAILED",
                        "message": "IBKR contract-details request could not be submitted",
                    },
                }
            completed = pending.event.wait(self._timeout)
            if pending.transport_error:
                return {
                    "details": [],
                    "errors": [],
                    "terminal": False,
                    "transport_error": dict(pending.transport_error),
                }
            if not completed or not pending.terminal_response:
                return {
                    "details": [],
                    "errors": [],
                    "terminal": False,
                    "transport_error": {
                        "status": "REQUEST_TIMEOUT",
                        "message": "IBKR contract-details request did not reach a terminal response",
                    },
                }
            return {
                "details": list(pending.details),
                "errors": list(pending.errors),
                "terminal": True,
            }
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
            try:
                self._app.reqHeadTimestamp(request_id, contract, WHAT_TO_SHOW, USE_RTH, FORMAT_DATE)
            except Exception:
                return {
                    "request_timestamp": request_timestamp,
                    "success": False,
                    "head_timestamp": None,
                    "terminal": False,
                    "transport_error": {
                        "status": "REQUEST_SUBMISSION_FAILED",
                        "message": "IBKR head-timestamp request could not be submitted",
                    },
                }
            completed = pending.event.wait(self._timeout)
            if pending.transport_error:
                return {
                    "request_timestamp": request_timestamp,
                    "success": False,
                    "head_timestamp": None,
                    "terminal": False,
                    "transport_error": dict(pending.transport_error),
                }
            if not completed or not pending.terminal_response:
                return {
                    "request_timestamp": request_timestamp,
                    "success": False,
                    "head_timestamp": None,
                    "terminal": False,
                    "transport_error": {
                        "status": "REQUEST_TIMEOUT",
                        "message": "IBKR head-timestamp request did not reach a terminal response",
                    },
                }
            response: dict[str, Any] = {
                "request_timestamp": request_timestamp,
                "terminal": True,
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
    "API_PROVENANCE_FILE_ENV",
    "API_PYTHON_PATH_ENV",
    "CAPTURE_MODE",
    "ConnectionConfig",
    "CONNECTION_NOT_READY_STATUS",
    "CURRENCY",
    "EXCHANGE",
    "FROZEN_STATUS",
    "FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS",
    "FORMAT_DATE",
    "HEAD_READY_STATUS",
    "HEAD_UNAVAILABLE_STATUS",
    "HOST_VERSION_EVIDENCE_FILE_ENV",
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
    "VALIDATE_EXISTING_MODE",
    "WHAT_TO_SHOW",
    "build_contract_request",
    "build_head_timestamp_request",
    "build_readiness_manifest",
    "accept_frozen_manifest",
    "canonical_json",
    "contract_details_snapshot",
    "load_us_candidates",
    "manifest_integrity_hash",
    "normalize_ibkr_symbol",
    "resolve_identity_candidates",
    "run_readiness",
    "sha256_json",
    "load_saved_manifest",
    "validate_existing_manifest",
    "validate_manifest",
    "validate_parent_pins",
    "write_manifest",
]

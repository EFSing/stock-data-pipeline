"""Phase 5K-A0 security-metadata provenance foundation.

This module is deliberately metadata-only.  It defines the canonical security
metadata contract, validates field-level provenance, and provides a deterministic
raw-snapshot freeze/reproduction envelope.  It never imports providers, Replay,
Trading Core, Sheets, or any historical OHLCV path.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = Path(__file__).with_name("metadata_provenance_registry.json")

SCHEMA_VERSION = "canonical-security-metadata-v1"
SNAPSHOT_SCHEMA_VERSION = "security-metadata-raw-snapshot-v1"
REGISTRY_SCHEMA_VERSION = "metadata-provenance-source-registry-v1"
AUDIT_VERSION = "PHASE5K-A0-METADATA-PROVENANCE-2026-08-27-v1"
FINAL_READY = "METADATA_PROVENANCE_READY_FOR_MANIFEST_FREEZE"
FINAL_UNAVAILABLE = "METADATA_PROVENANCE_UNAVAILABLE"
VALID_MARKETS = ("CN", "HK", "US", "JP", "SE")

# These are metadata fields only.  Historical bars, returns, and trading
# diagnostics are intentionally outside this schema.
REQUIRED_CANONICAL_FIELDS = (
    "security_identity",
    "exchange",
    "security_type",
    "primary_listing",
    "listing_date",
    "active_status",
    "issuer_share_class_identity",
    "sector",
    "industry",
    "provider_availability",
)
OPTIONAL_CANONICAL_FIELDS = ("liquidity_metadata",)
ALL_CANONICAL_FIELDS = REQUIRED_CANONICAL_FIELDS + OPTIONAL_CANONICAL_FIELDS

_FORBIDDEN_RAW_KEYS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj close",
        "adjusted_close",
        "ohlcv",
        "bars",
        "history",
        "historical",
        "history_length",
        "liquidity_rank",
        "return",
        "mfe",
        "mae",
        "p&l",
    }
)
_COVERAGE_STATUSES = frozenset(
    {"VERIFIED", "DERIVABLE", "NOT_PROVEN", "NOT_AVAILABLE"}
)
_DERIVATIONS = frozenset({"direct", "deterministic_derivation"})
_SHA256_PREFIX = "sha256:"


class ProvenanceError(ValueError):
    """Raised when a metadata record cannot pass the provenance contract."""


class SnapshotIntegrityError(ValueError):
    """Raised when a frozen metadata snapshot has changed or is inconsistent."""


@dataclass(frozen=True)
class SourceSnapshotIdentity:
    """Identity for a raw source payload, independent of canonical records."""

    source_id: str
    raw_snapshot_sha256: str
    retrieved_at: str
    as_of: str
    as_of_semantics: str


def _canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProvenanceError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def sha256_hex(value: Any) -> str:
    """Return a stable SHA-256 identity for a JSON-safe value."""
    return f"{_SHA256_PREFIX}{hashlib.sha256(_canonical_bytes(value)).hexdigest()}"


def _without_registry_hash(registry: Mapping[str, Any]) -> dict[str, Any]:
    payload = deepcopy(dict(registry))
    integrity = dict(payload.get("integrity", {}))
    integrity.pop("registry_sha256", None)
    payload["integrity"] = integrity
    return payload


def registry_integrity_hash(registry: Mapping[str, Any]) -> str:
    """Hash the source registry excluding its stored self-hash."""
    return sha256_hex(_without_registry_hash(registry))


def _reject_forbidden_keys(value: Any, path: str = "record") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_RAW_KEYS:
                raise ProvenanceError(
                    f"{path}.{key} is outside security metadata scope"
                )
            _reject_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_keys(child, f"{path}[{index}]")


def _sort_lists(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sort_lists(child) for key, child in value.items()}
    if isinstance(value, list):
        normalized = [_sort_lists(child) for child in value]
        def list_key(item: Any) -> tuple[str, str]:
            if isinstance(item, Mapping) and "provider" in item:
                return (str(item["provider"]), _canonical_bytes(item).decode("utf-8"))
            if isinstance(item, Mapping) and "source_id" in item:
                return (str(item["source_id"]), _canonical_bytes(item).decode("utf-8"))
            return ("", _canonical_bytes(item).decode("utf-8"))

        return sorted(normalized, key=list_key)
    return value


def _normalize_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ProvenanceError("listing_date must be an ISO date string")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ProvenanceError("listing_date must be an ISO date string") from exc


def _validate_provenance(field: str, provenance: Mapping[str, Any]) -> None:
    if not isinstance(provenance, Mapping):
        raise ProvenanceError(f"missing provenance object for {field}")
    required = (
        "source_id",
        "provider_source_name",
        "raw_snapshot_sha256",
        "retrieved_at",
        "as_of",
        "as_of_semantics",
        "derivation",
        "manual",
    )
    missing = [key for key in required if key not in provenance]
    if missing:
        raise ProvenanceError(
            f"{field} provenance missing required keys: {', '.join(missing)}"
        )
    if not provenance["source_id"] or not provenance["provider_source_name"]:
        raise ProvenanceError(f"{field} provenance source identity is empty")
    raw_hash = str(provenance["raw_snapshot_sha256"])
    if not raw_hash.startswith(_SHA256_PREFIX) or len(raw_hash) != 71:
        raise ProvenanceError(f"{field} provenance raw snapshot hash is invalid")
    if provenance["derivation"] not in _DERIVATIONS:
        raise ProvenanceError(f"{field} provenance derivation is invalid")
    if provenance["manual"] is not False:
        raise ProvenanceError(
            f"{field} contains a manual value; selection-driving metadata must be sourced"
        )
    if not str(provenance["retrieved_at"]).strip():
        raise ProvenanceError(f"{field} provenance retrieved_at is empty")
    if not str(provenance["as_of"]).strip():
        raise ProvenanceError(f"{field} provenance as_of is empty")
    if not str(provenance["as_of_semantics"]).strip():
        raise ProvenanceError(f"{field} provenance as_of_semantics is empty")


def validate_canonical_record(record: Mapping[str, Any]) -> None:
    """Validate one canonical record and every field's non-manual provenance."""
    if not isinstance(record, Mapping):
        raise ProvenanceError("canonical record must be an object")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ProvenanceError("canonical record schema version mismatch")
    for field in REQUIRED_CANONICAL_FIELDS:
        if field not in record:
            raise ProvenanceError(f"canonical record missing {field}")
    for field in OPTIONAL_CANONICAL_FIELDS:
        if field in record and record[field] is not None:
            if field == "liquidity_metadata":
                _reject_forbidden_keys(record[field], field)
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ProvenanceError("canonical record provenance is missing")
    for field in REQUIRED_CANONICAL_FIELDS:
        _validate_provenance(field, provenance.get(field, {}))
    if record.get("liquidity_metadata") is not None:
        _validate_provenance(
            "liquidity_metadata", provenance.get("liquidity_metadata", {})
        )
    identity = record["security_identity"]
    if not isinstance(identity, Mapping) or not str(identity.get("canonical_id", "")):
        raise ProvenanceError("security_identity.canonical_id is required")
    if not isinstance(record["provider_availability"], list):
        raise ProvenanceError("provider_availability must be a list")
    listing_date = record["listing_date"]
    _normalize_date(listing_date)
    _reject_forbidden_keys(record)


def canonicalize_security_metadata(
    raw_record: Mapping[str, Any],
    field_provenance: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Create canonical metadata without allowing manual or OHLCV-derived values.

    ``raw_record`` must already contain values supplied by the source adapter.
    This function only normalizes dates, sorts unordered lists, and attaches the
    supplied field-level source evidence; it never calculates liquidity or
    history completeness.
    """
    if not isinstance(raw_record, Mapping):
        raise ProvenanceError("raw security metadata record must be an object")
    _reject_forbidden_keys(raw_record)
    missing = [field for field in REQUIRED_CANONICAL_FIELDS if field not in raw_record]
    if missing:
        raise ProvenanceError(f"raw record missing required fields: {', '.join(missing)}")
    if not isinstance(field_provenance, Mapping):
        raise ProvenanceError("field provenance must be an object")
    canonical: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    for field in REQUIRED_CANONICAL_FIELDS:
        if field not in field_provenance:
            raise ProvenanceError(f"field provenance missing {field}")
        value = raw_record[field]
        canonical[field] = (
            _normalize_date(value)
            if field == "listing_date"
            else _sort_lists(deepcopy(value))
        )
    if "liquidity_metadata" in raw_record and raw_record["liquidity_metadata"] is not None:
        canonical["liquidity_metadata"] = _sort_lists(
            deepcopy(raw_record["liquidity_metadata"])
        )
        if "liquidity_metadata" not in field_provenance:
            raise ProvenanceError("liquidity_metadata requires field provenance")
    canonical["provenance"] = {
        field: deepcopy(dict(field_provenance[field]))
        for field in field_provenance
        if field in ALL_CANONICAL_FIELDS and field in canonical
    }
    validate_canonical_record(canonical)
    return canonical


def canonical_record_key(record: Mapping[str, Any]) -> str:
    validate_canonical_record(record)
    return str(record["security_identity"]["canonical_id"])


def canonical_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return records in stable identity order and reject duplicates."""
    normalized = [deepcopy(dict(record)) for record in records]
    for record in normalized:
        validate_canonical_record(record)
    normalized.sort(key=canonical_record_key)
    keys = [canonical_record_key(record) for record in normalized]
    if len(keys) != len(set(keys)):
        raise ProvenanceError("duplicate canonical security identity")
    return normalized


def canonical_records_hash(records: Iterable[Mapping[str, Any]]) -> str:
    return sha256_hex(canonical_records(records))


def freeze_metadata_snapshot(
    raw_source_snapshot: Mapping[str, Any],
    raw_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic freeze envelope from source payloads and raw records."""
    if not isinstance(raw_source_snapshot, Mapping):
        raise ProvenanceError("raw source snapshot must be an object")
    _reject_forbidden_keys(raw_source_snapshot, "raw_source_snapshot")
    frozen_raw_records = [deepcopy(dict(item)) for item in raw_records]
    generated = [
        canonicalize_security_metadata(
            item["raw_record"], item["field_provenance"]
        )
        for item in frozen_raw_records
    ]
    generated = canonical_records(generated)
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "raw_source_snapshot": deepcopy(dict(raw_source_snapshot)),
        "raw_records": frozen_raw_records,
        "canonical_records": generated,
        "integrity": {
            "raw_source_snapshot_sha256": sha256_hex(raw_source_snapshot),
            "canonical_records_sha256": canonical_records_hash(generated),
            "canonical_record_count": len(generated),
        },
    }


def reproduce_canonical_records(frozen_snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Regenerate canonical records from a frozen source snapshot and verify hashes."""
    if frozen_snapshot.get("snapshot_schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotIntegrityError("metadata snapshot schema version mismatch")
    raw_source_snapshot = frozen_snapshot.get("raw_source_snapshot")
    raw_records = frozen_snapshot.get("raw_records")
    expected = frozen_snapshot.get("integrity")
    if not isinstance(raw_source_snapshot, Mapping) or not isinstance(raw_records, list):
        raise SnapshotIntegrityError("metadata snapshot payload is incomplete")
    if not isinstance(expected, Mapping):
        raise SnapshotIntegrityError("metadata snapshot integrity is missing")
    actual_raw_hash = sha256_hex(raw_source_snapshot)
    if expected.get("raw_source_snapshot_sha256") != actual_raw_hash:
        raise SnapshotIntegrityError("raw source snapshot hash mismatch")
    regenerated = [
        canonicalize_security_metadata(
            item["raw_record"], item["field_provenance"]
        )
        for item in raw_records
    ]
    regenerated = canonical_records(regenerated)
    if expected.get("canonical_records_sha256") != canonical_records_hash(regenerated):
        raise SnapshotIntegrityError("canonical record hash mismatch")
    if expected.get("canonical_record_count") != len(regenerated):
        raise SnapshotIntegrityError("canonical record count mismatch")
    if frozen_snapshot.get("canonical_records") != regenerated:
        raise SnapshotIntegrityError("frozen canonical records differ from reproduction")
    return regenerated


def _validate_source_entry(source: Mapping[str, Any]) -> None:
    required = (
        "source_id",
        "provider_source_name",
        "source_role",
        "official_urls",
        "retrieval_mechanism",
        "source_timestamp_as_of_semantics",
        "information_cutoff_compatibility",
        "raw_snapshot_identity",
        "license_availability_constraints",
        "programmatically_reproducible",
        "field_coverage",
    )
    missing = [key for key in required if key not in source]
    if missing:
        raise ProvenanceError(
            f"source {source.get('source_id', '<unknown>')} missing: {', '.join(missing)}"
        )
    coverage = source["field_coverage"]
    for field in ALL_CANONICAL_FIELDS:
        if field not in coverage:
            raise ProvenanceError(
                f"source {source['source_id']} has no coverage entry for {field}"
            )
        if coverage[field]["status"] not in _COVERAGE_STATUSES:
            raise ProvenanceError(
                f"source {source['source_id']} has invalid {field} coverage status"
            )
    snapshot = source["raw_snapshot_identity"]
    if snapshot.get("status") == "FROZEN":
        snapshot_hash = str(snapshot.get("sha256", ""))
        if not snapshot_hash.startswith(_SHA256_PREFIX) or len(snapshot_hash) != 71:
            raise ProvenanceError(
                f"source {source['source_id']} frozen snapshot hash is invalid"
            )
    if source["programmatically_reproducible"] not in (True, False, None):
        raise ProvenanceError(
            f"source {source['source_id']} reproducibility must be true/false/unknown"
        )


def validate_source_registry(registry: Mapping[str, Any]) -> None:
    """Validate the machine-readable source audit and its fail-closed boundary."""
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ProvenanceError("source registry schema version mismatch")
    if registry.get("audit_version") != AUDIT_VERSION:
        raise ProvenanceError("source registry audit version mismatch")
    if tuple(registry.get("markets", ())) != VALID_MARKETS:
        raise ProvenanceError("source registry market order changed")
    required_fields = tuple(registry.get("required_canonical_fields", ()))
    if required_fields != REQUIRED_CANONICAL_FIELDS:
        raise ProvenanceError("source registry canonical field contract changed")
    sources = registry.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ProvenanceError("source registry has no source candidates")
    source_ids = set()
    for source in sources:
        _validate_source_entry(source)
        source_id = source["source_id"]
        if source_id in source_ids:
            raise ProvenanceError(f"duplicate source id: {source_id}")
        source_ids.add(source_id)
    assessments = registry.get("market_assessments")
    if not isinstance(assessments, Mapping):
        raise ProvenanceError("market assessments are missing")
    for market in VALID_MARKETS:
        assessment = assessments.get(market)
        if not isinstance(assessment, Mapping):
            raise ProvenanceError(f"missing assessment for {market}")
        if assessment.get("conclusion") not in (FINAL_READY, FINAL_UNAVAILABLE):
            raise ProvenanceError(f"invalid assessment conclusion for {market}")
        if any(source_id not in source_ids for source_id in assessment["source_ids"]):
            raise ProvenanceError(f"{market} assessment references an unknown source")
        for field in ALL_CANONICAL_FIELDS:
            status = assessment["field_coverage"][field]["status"]
            if status not in _COVERAGE_STATUSES:
                raise ProvenanceError(f"invalid {market} aggregate coverage for {field}")
    final_conclusion = registry.get("final_conclusion")
    if final_conclusion not in (FINAL_READY, FINAL_UNAVAILABLE):
        raise ProvenanceError("invalid final provenance conclusion")
    if final_conclusion == FINAL_READY and any(
        assessment["conclusion"] != FINAL_READY
        for assessment in assessments.values()
    ):
        raise ProvenanceError("READY requires every market assessment to be READY")


def load_source_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    validate_source_registry(registry)
    stored_hash = registry.get("integrity", {}).get("registry_sha256")
    if stored_hash != registry_integrity_hash(registry):
        raise SnapshotIntegrityError("source registry integrity hash mismatch")
    return registry


def ready_for_manifest_freeze(registry: Mapping[str, Any]) -> bool:
    """Return true only when every market has complete, frozen, non-manual evidence."""
    validate_source_registry(registry)
    if registry.get("final_conclusion") != FINAL_READY:
        return False
    for assessment in registry["market_assessments"].values():
        if assessment.get("conclusion") != FINAL_READY:
            return False
        if assessment.get("raw_security_metadata_snapshot", {}).get("status") != "FROZEN":
            return False
        if any(
            assessment["field_coverage"][field]["status"]
            not in {"VERIFIED", "DERIVABLE"}
            for field in REQUIRED_CANONICAL_FIELDS
        ):
            return False
        if assessment.get("manual_values_present") is not False:
            return False
    return True


def source_snapshot_identity(
    source_id: str,
    raw_payload: Mapping[str, Any],
    retrieved_at: str,
    as_of: str,
    as_of_semantics: str,
) -> SourceSnapshotIdentity:
    """Create a source identity without interpreting or deriving security fields."""
    _reject_forbidden_keys(raw_payload, f"source[{source_id}]")
    return SourceSnapshotIdentity(
        source_id=source_id,
        raw_snapshot_sha256=sha256_hex(raw_payload),
        retrieved_at=retrieved_at,
        as_of=as_of,
        as_of_semantics=as_of_semantics,
    )

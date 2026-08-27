"""Phase 5K-A development-validation symbol manifest governance.

This module is intentionally metadata-only.  It accepts a provider's security
metadata snapshot, applies the pre-registered eligibility and deterministic
selection rules, and freezes a canonical symbol manifest.  It does not import
the market-data providers, replay, Trading Core, Decision, or SETUP_03 code.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

from research.structural_validation_protocol import (
    EXPECTED_PROTOCOL_VERSION,
    PINNED_PROTOCOL_SHA256_BY_VERSION,
    PROTOCOL_PATH,
    PROTOCOL_STATUS,
    load_protocol,
)


MANIFEST_PATH = Path(__file__).with_name(
    "development_validation_symbol_manifest.json"
)
MANIFEST_SCHEMA_VERSION = "setup03-development-validation-symbol-manifest-v1"
MANIFEST_VERSION = (
    "SETUP_03-DEVELOPMENT-VALIDATION-SYMBOL-MANIFEST-2026-08-27-v1"
)
MANIFEST_STATUS = "MANIFEST_FROZEN_NOT_FETCHED"
INFORMATION_CUTOFF = date(2026, 8, 26)
VALIDATION_START = date(2018, 1, 1)
VALIDATION_END = INFORMATION_CUTOFF
VALIDATION_MARKETS = ("CN", "HK", "US", "JP", "SE")
TARGET_SYMBOLS_PER_MARKET = 14
PRIMARY_SYMBOLS_PER_MARKET = 10
RESERVE_SYMBOLS_PER_MARKET = 4
MIN_ACTIVE_SYMBOLS_PER_MARKET = 8
MIN_ACTIVE_SYMBOLS_TOTAL = 40
SECTOR_CAP = 2
ALLOWED_SECURITY_TYPES = frozenset({"COMMON_STOCK", "ORDINARY_SHARE"})
NORMAL_SPECIAL_STATUSES = frozenset({"NORMAL", "REGULAR"})

# This is the immutable version -> canonical-content contract.  The JSON
# integrity field catches an unsynchronized stored hash; this contract also
# rejects a modified payload whose new hash was written back under v1.
PINNED_MANIFEST_SHA256_BY_VERSION = MappingProxyType(
    {
        MANIFEST_VERSION: "sha256:83320949df306bcc2b310c1e114521ccb839fbe31b9103f89bf43e145c0bd3d9",
    }
)

EXPECTED_PARENT_PHASE5J_IDENTITY = MappingProxyType(
    {
        "protocol_version": EXPECTED_PROTOCOL_VERSION,
        "protocol_sha256": PINNED_PROTOCOL_SHA256_BY_VERSION[
            EXPECTED_PROTOCOL_VERSION
        ],
        "phase5j_status": PROTOCOL_STATUS,
    }
)

SELECTION_METADATA_FIELDS = (
    "market",
    "exchange",
    "security_type",
    "primary_listing",
    "listing_date",
    "active_status",
    "liquidity_rank",
    "history_length",
    "data_completeness",
    "broad_sector",
    "industry",
    "issuer_id",
    "share_class",
    "provider_metadata_available",
    "is_adr",
    "special_trading_status",
    "symbol",
)

# Key fragments forbidden in an input metadata record.  These are field-name
# checks, not values: the selection implementation cannot accidentally accept
# a signal/result column while still documenting the prohibition in the JSON
# policy.
FORBIDDEN_SELECTION_FIELD_FRAGMENTS = frozenset(
    {
        "watch",
        "armed",
        "confirmed",
        "signal",
        "breakout",
        "platform",
        "tolerance",
        "forward",
        "return",
        "mfe",
        "mae",
        "win_rate",
        "p&l",
        "pnl",
        "profit_factor",
        "expectancy",
        "entry_allowed",
        "setup03",
    }
)


@dataclass(frozen=True)
class SecurityMetadata:
    """Provider-neutral metadata accepted by the Phase 5K-A selector."""

    market: str
    symbol: str
    issuer_id: str
    exchange: str
    security_type: str
    primary_listing: bool
    listing_date: date
    active_status: str
    liquidity_rank: int
    history_length: int
    broad_sector: str
    provider_metadata_available: bool = True
    share_class: str = "COMMON"
    is_adr: bool = False
    special_trading_status: str = "NORMAL"


class MetadataProvider(Protocol):
    """The only provider contract used while building a manifest."""

    def list_security_metadata(
        self, *, information_cutoff: date
    ) -> Iterable[Mapping[str, Any]]:
        """Return metadata rows only; no bars or derived signal output."""


def build_manifest_from_provider(provider: MetadataProvider) -> dict[str, Any]:
    """Build a manifest using the provider's metadata endpoint only."""
    rows = provider.list_security_metadata(information_cutoff=INFORMATION_CUTOFF)
    return build_manifest(rows)


def build_manifest(
    records: Iterable[SecurityMetadata | Mapping[str, Any]],
    *,
    parent_protocol: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select and rank the frozen universe from metadata, deterministically.

    The input is materialized, normalized, eligibility-filtered, issuer
    deduplicated, sorted by the registered metadata ranking, and finally
    constrained by the broad-sector cap.  No input ordering is observable in
    the result.
    """
    actual_protocol = load_protocol()
    if parent_protocol is not None:
        _validate_parent_protocol(parent_protocol)
        if dict(parent_protocol) != actual_protocol:
            raise ValueError("provided parent Phase 5J protocol is not the actual frozen protocol")
    protocol = actual_protocol
    _validate_parent_protocol(protocol)
    normalized = [_normalize_metadata(record) for record in records]
    _reject_duplicate_symbols(normalized)

    selected_symbols: list[dict[str, Any]] = []
    for market in VALIDATION_MARKETS:
        eligible = [
            row
            for row in normalized
            if row["market"] == market and _is_eligible(row)
        ]
        selected = _select_market(eligible, market)
        selected_symbols.extend(selected)

    manifest = _manifest_skeleton(protocol)
    manifest["symbols"] = selected_symbols
    manifest["integrity"]["symbol_manifest_sha256"] = manifest_integrity_hash(manifest)
    _validate_manifest(manifest, protocol, require_pinned_hash=False)
    return manifest


def load_manifest(
    path: Path = MANIFEST_PATH,
    *,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    """Load the frozen manifest after validating its actual Phase 5J parent."""
    protocol = load_protocol(protocol_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _validate_manifest(manifest, protocol)
    return manifest


def validate_manifest(
    manifest: Mapping[str, Any], *, protocol_path: Path = PROTOCOL_PATH
) -> None:
    """Validate an in-memory manifest against the actual frozen parent."""
    _validate_manifest(manifest, load_protocol(protocol_path))


def manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    """Hash every manifest field except the complete integrity envelope."""
    payload = dict(manifest)
    payload.pop("integrity", None)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def serialize_manifest(manifest: Mapping[str, Any]) -> str:
    """Return the stable repository representation of a manifest."""
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _manifest_skeleton(protocol: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "phase": "Phase 5K-A",
        "status": MANIFEST_STATUS,
        "parent_phase5j": {
            "protocol_version": protocol["protocol_version"],
            "protocol_sha256": protocol["integrity"]["protocol_sha256"],
            "phase5j_status": protocol["phase5j_status"],
        },
        "information_cutoff": INFORMATION_CUTOFF.isoformat(),
        "validation_window": {
            "start": VALIDATION_START.isoformat(),
            "end": VALIDATION_END.isoformat(),
        },
        "markets": list(VALIDATION_MARKETS),
        "selection_policy": {
            "selection_stage": "BEFORE_ANY_SETUP_03_OUTPUT",
            "selection_is_non_signal_metadata_only": True,
            "allowed_metadata_fields": list(SELECTION_METADATA_FIELDS),
            "forbidden_selection_fields": sorted(FORBIDDEN_SELECTION_FIELD_FRAGMENTS),
            "eligibility": {
                "ordinary_listed_equity_only": True,
                "primary_listing_required": True,
                "active_status_required_as_of_cutoff": True,
                "listing_date_at_or_before": "2022-08-26",
                "provider_metadata_available_required": True,
                "allowed_security_types": sorted(ALLOWED_SECURITY_TYPES),
                "us_adr_excluded": True,
                "cn_st_and_star_st_excluded": True,
                "excluded_security_types": [
                    "ETF",
                    "FUND",
                    "BOND",
                    "WARRANT",
                    "PREFERRED_STOCK",
                    "SPAC",
                    "STRUCTURED_PRODUCT",
                    "ADR",
                ],
                "same_issuer_same_market_share_class_policy": (
                    "Keep one row per issuer and market; the deterministic ranking "
                    "selects the winning share class."
                ),
            },
            "ranking": [
                "liquidity_rank ASC",
                "history_length DESC",
                "canonical_symbol LEXICAL_ASC",
            ],
            "deduplication_before_sector_cap": True,
            "sector_cap_applies_to_selected_universe": True,
            "selection_must_not_use_signal_or_return_information": True,
        },
        "sector_cap": {
            "scope": "each market selected universe",
            "maximum_symbols_per_broad_sector": SECTOR_CAP,
        },
        "counts": {
            "target_per_market": TARGET_SYMBOLS_PER_MARKET,
            "primary_per_market": PRIMARY_SYMBOLS_PER_MARKET,
            "reserve_per_market": RESERVE_SYMBOLS_PER_MARKET,
            "future_hard_minimum_active_per_market": MIN_ACTIVE_SYMBOLS_PER_MARKET,
            "future_hard_minimum_active_total": MIN_ACTIVE_SYMBOLS_TOTAL,
        },
        "phase5k_controls": {
            "historical_ohlcv_fetched": False,
            "setup03_evaluated": False,
            "validation_started": False,
            "final_oos_accessed": False,
            "manifest_is_authoritative_before_acquisition": True,
        },
        "symbols": [],
        "integrity": {
            "algorithm": "SHA-256",
            "canonicalization": (
                "JSON with ensure_ascii=false, sort_keys=true, "
                "separators=(',', ':'), hashing the complete top-level object "
                "after removing only integrity."
            ),
            "symbol_manifest_sha256": "",
        },
    }


def _normalize_metadata(
    record: SecurityMetadata | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(record, SecurityMetadata):
        raw = asdict(record)
    elif isinstance(record, Mapping):
        raw = dict(record)
    else:
        raise TypeError("metadata record must be SecurityMetadata or a mapping")

    _reject_forbidden_selection_fields(raw)
    market = _text(raw, "market").upper()
    symbol = _text(raw, "symbol").upper()
    issuer_id = _text(raw, "issuer_id")
    exchange = _text(raw, "exchange").upper()
    security_type = _text(raw, "security_type").upper()
    primary_listing = _required_bool(raw, "primary_listing")
    listing_date = _parse_date(raw.get("listing_date"), "listing_date")
    active_status = _text(raw, "active_status").upper()
    liquidity_rank = _positive_int(raw.get("liquidity_rank"), "liquidity_rank")
    history_length = _positive_int(raw.get("history_length"), "history_length")
    broad_sector = _text(raw, "broad_sector")
    provider_metadata_available = _required_bool(
        raw, "provider_metadata_available"
    )
    share_class = str(raw.get("share_class", "COMMON")).strip().upper()
    if not share_class:
        raise ValueError("metadata share_class must not be empty")
    is_adr = _optional_bool(raw.get("is_adr", False), "is_adr")
    special_status = str(
        raw.get("special_trading_status", "NORMAL")
    ).strip().upper()
    if not special_status:
        raise ValueError("metadata special_trading_status must not be empty")
    security_name = str(raw.get("security_name", raw.get("name", ""))).strip()
    return {
        "market": market,
        "symbol": symbol,
        "issuer_id": issuer_id,
        "exchange": exchange,
        "security_type": security_type,
        "primary_listing": primary_listing,
        "listing_date": listing_date.isoformat(),
        "active_status": active_status,
        "liquidity_rank": liquidity_rank,
        "history_length": history_length,
        "broad_sector": broad_sector,
        "provider_metadata_available": provider_metadata_available,
        "share_class": share_class,
        "is_adr": is_adr,
        "special_trading_status": special_status,
        "security_name": security_name,
    }


def _select_market(eligible: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    ordered = sorted(eligible, key=_ranking_key)
    winners_by_issuer: dict[str, dict[str, Any]] = {}
    for row in ordered:
        winners_by_issuer.setdefault(row["issuer_id"], row)

    selected: list[dict[str, Any]] = []
    sector_counts: Counter[str] = Counter()
    for row in sorted(winners_by_issuer.values(), key=_ranking_key):
        if sector_counts[row["broad_sector"]] >= SECTOR_CAP:
            continue
        selected.append(row)
        sector_counts[row["broad_sector"]] += 1
        if len(selected) == TARGET_SYMBOLS_PER_MARKET:
            break
    if len(selected) != TARGET_SYMBOLS_PER_MARKET:
        raise ValueError(
            f"{market} has only {len(selected)} eligible symbols after issuer/share-class "
            f"deduplication and sector cap; {TARGET_SYMBOLS_PER_MARKET} required"
        )

    result = []
    for rank, row in enumerate(selected, start=1):
        result.append(
            {
                "market": row["market"],
                "symbol": row["symbol"],
                "issuer_id": row["issuer_id"],
                "exchange": row["exchange"],
                "security_type": row["security_type"],
                "primary_listing": row["primary_listing"],
                "active_status": row["active_status"],
                "provider_metadata_available": row["provider_metadata_available"],
                "share_class": row["share_class"],
                "is_adr": row["is_adr"],
                "special_trading_status": row["special_trading_status"],
                "broad_sector": row["broad_sector"],
                "listing_date": row["listing_date"],
                "history_length": row["history_length"],
                "liquidity_rank": row["liquidity_rank"],
                "manifest_rank": rank,
                "intended_role": (
                    "PRIMARY" if rank <= PRIMARY_SYMBOLS_PER_MARKET else "RESERVE"
                ),
            }
        )
    return result


def _ranking_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row["liquidity_rank"], -row["history_length"], row["symbol"])


def _is_eligible(row: Mapping[str, Any]) -> bool:
    if row["market"] not in VALIDATION_MARKETS:
        return False
    if not row["primary_listing"] or row["active_status"] != "ACTIVE":
        return False
    if date.fromisoformat(row["listing_date"]) > date(2022, 8, 26):
        return False
    if not row["provider_metadata_available"]:
        return False
    if row["security_type"] not in ALLOWED_SECURITY_TYPES:
        return False
    if row["is_adr"] or row["special_trading_status"] not in NORMAL_SPECIAL_STATUSES:
        return False
    if row["market"] == "CN" and _is_cn_special_trading_name(row):
        return False
    return True


def _is_cn_special_trading_name(row: Mapping[str, Any]) -> bool:
    """Recognize ST/*ST when a metadata source exposes the security name."""
    name = str(row.get("security_name", row.get("name", ""))).strip().upper()
    return name.startswith("ST") or name.startswith("*ST")


def _validate_parent_protocol(protocol: Mapping[str, Any]) -> None:
    # load_protocol() performs the actual Phase 5J content and parent Phase 5I
    # validation.  These explicit checks bind this manifest to the known v1
    # protocol identity as well, rather than trusting copied JSON metadata.
    if protocol.get("protocol_version") != EXPECTED_PARENT_PHASE5J_IDENTITY[
        "protocol_version"
    ]:
        raise ValueError("manifest parent Phase 5J protocol version mismatch")
    actual_hash = protocol.get("integrity", {}).get("protocol_sha256")
    if actual_hash != EXPECTED_PARENT_PHASE5J_IDENTITY["protocol_sha256"]:
        raise ValueError("manifest parent Phase 5J protocol hash mismatch")
    if protocol.get("phase5j_status") != PROTOCOL_STATUS:
        raise ValueError("manifest parent Phase 5J must remain not executed")
    if tuple(protocol.get("development_validation_dataset", {}).get("markets", ())) != VALIDATION_MARKETS:
        raise ValueError("manifest parent Phase 5J market contract mismatch")
    dataset = protocol.get("development_validation_dataset", {})
    symbol_manifest = dataset.get("symbol_manifest", {})
    if not symbol_manifest.get("must_be_frozen_before_phase5k_acquisition"):
        raise ValueError("Phase 5J does not require manifest freeze before acquisition")
    if not symbol_manifest.get("must_be_hashed_before_phase5k_acquisition"):
        raise ValueError("Phase 5J does not require manifest hash before acquisition")


def _validate_manifest(
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
    *,
    require_pinned_hash: bool = True,
) -> None:
    required = {
        "schema_version",
        "manifest_version",
        "phase",
        "status",
        "parent_phase5j",
        "information_cutoff",
        "validation_window",
        "markets",
        "selection_policy",
        "sector_cap",
        "counts",
        "phase5k_controls",
        "symbols",
        "integrity",
    }
    missing = required - set(manifest)
    if missing:
        raise ValueError(f"symbol manifest missing keys: {sorted(missing)}")
    _validate_parent_protocol(protocol)

    integrity = manifest["integrity"]
    stored_hash = integrity.get("symbol_manifest_sha256")
    actual_hash = manifest_integrity_hash(manifest)
    if stored_hash != actual_hash:
        raise ValueError("symbol manifest integrity mismatch; same-version changes fail")
    version = manifest["manifest_version"]
    if require_pinned_hash:
        pinned_hash = PINNED_MANIFEST_SHA256_BY_VERSION.get(version)
        if pinned_hash is None:
            raise ValueError("symbol manifest version has no pinned canonical hash contract")
        if stored_hash != pinned_hash:
            raise ValueError("symbol manifest version is bound to a different canonical hash")

    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise ValueError("symbol manifest schema version mismatch")
    if manifest["phase"] != "Phase 5K-A" or manifest["status"] != MANIFEST_STATUS:
        raise ValueError("symbol manifest phase/status mismatch")
    if manifest["information_cutoff"] != INFORMATION_CUTOFF.isoformat():
        raise ValueError("information cutoff changed")
    if manifest["validation_window"] != {
        "start": VALIDATION_START.isoformat(),
        "end": VALIDATION_END.isoformat(),
    }:
        raise ValueError("validation window changed")
    if tuple(manifest["markets"]) != VALIDATION_MARKETS:
        raise ValueError("manifest market set/order changed")

    parent = manifest["parent_phase5j"]
    if dict(parent) != dict(EXPECTED_PARENT_PHASE5J_IDENTITY):
        raise ValueError("manifest parent Phase 5J identity mismatch")
    if parent["protocol_version"] != protocol["protocol_version"] or parent[
        "protocol_sha256"
    ] != protocol["integrity"]["protocol_sha256"]:
        raise ValueError("manifest parent does not match actual Phase 5J protocol")

    counts = manifest["counts"]
    expected_counts = {
        "target_per_market": TARGET_SYMBOLS_PER_MARKET,
        "primary_per_market": PRIMARY_SYMBOLS_PER_MARKET,
        "reserve_per_market": RESERVE_SYMBOLS_PER_MARKET,
        "future_hard_minimum_active_per_market": MIN_ACTIVE_SYMBOLS_PER_MARKET,
        "future_hard_minimum_active_total": MIN_ACTIVE_SYMBOLS_TOTAL,
    }
    if counts != expected_counts:
        raise ValueError("manifest target/minimum/reserve counts changed")
    if manifest["sector_cap"] != {
        "scope": "each market selected universe",
        "maximum_symbols_per_broad_sector": SECTOR_CAP,
    }:
        raise ValueError("manifest sector cap changed")

    policy = manifest["selection_policy"]
    if tuple(policy["allowed_metadata_fields"]) != SELECTION_METADATA_FIELDS:
        raise ValueError("allowed selection metadata fields changed")
    if policy["selection_is_non_signal_metadata_only"] is not True:
        raise ValueError("selection must be non-signal metadata only")
    if policy["selection_stage"] != "BEFORE_ANY_SETUP_03_OUTPUT":
        raise ValueError("selection stage must precede SETUP_03 output")
    if policy["forbidden_selection_fields"] != sorted(FORBIDDEN_SELECTION_FIELD_FRAGMENTS):
        raise ValueError("forbidden selection fields changed")
    if policy["ranking"] != [
        "liquidity_rank ASC",
        "history_length DESC",
        "canonical_symbol LEXICAL_ASC",
    ]:
        raise ValueError("manifest ranking policy changed")
    if policy["selection_must_not_use_signal_or_return_information"] is not True:
        raise ValueError("signal/return-dependent selection was enabled")
    if policy["deduplication_before_sector_cap"] is not True:
        raise ValueError("issuer/share-class deduplication order changed")

    controls = manifest["phase5k_controls"]
    if any(controls.get(key) is not False for key in (
        "historical_ohlcv_fetched",
        "setup03_evaluated",
        "validation_started",
        "final_oos_accessed",
    )):
        raise ValueError("Phase 5K-A controls indicate forbidden work was started")
    if controls.get("manifest_is_authoritative_before_acquisition") is not True:
        raise ValueError("manifest is not authoritative before acquisition")

    symbols = manifest["symbols"]
    expected_total = len(VALIDATION_MARKETS) * TARGET_SYMBOLS_PER_MARKET
    if len(symbols) != expected_total:
        raise ValueError("manifest symbol count is not 70")
    by_market: dict[str, list[Mapping[str, Any]]] = {
        market: [row for row in symbols if row.get("market") == market]
        for market in VALIDATION_MARKETS
    }
    if set(row.get("market") for row in symbols) != set(VALIDATION_MARKETS):
        raise ValueError("manifest contains an unknown or missing market")
    for market in VALIDATION_MARKETS:
        rows = by_market[market]
        if len(rows) != TARGET_SYMBOLS_PER_MARKET:
            raise ValueError(f"{market} does not contain exactly 14 symbols")
        if [row["manifest_rank"] for row in rows] != list(range(1, 15)):
            raise ValueError(f"{market} manifest ranks are not 1..14")
        if [row["intended_role"] for row in rows] != [
            "PRIMARY"
        ] * PRIMARY_SYMBOLS_PER_MARKET + ["RESERVE"] * RESERVE_SYMBOLS_PER_MARKET:
            raise ValueError(f"{market} primary/reserve role split changed")
        if len({row["symbol"] for row in rows}) != TARGET_SYMBOLS_PER_MARKET:
            raise ValueError(f"{market} contains duplicate symbols")
        if len({row["issuer_id"] for row in rows}) != TARGET_SYMBOLS_PER_MARKET:
            raise ValueError(f"{market} contains duplicate issuers/share classes")
        ranking_keys = [
            (row["liquidity_rank"], -row["history_length"], row["symbol"])
            for row in rows
        ]
        if ranking_keys != sorted(ranking_keys):
            raise ValueError(f"{market} rows are not in deterministic ranking order")
        sectors = Counter(row["broad_sector"] for row in rows)
        if any(count > SECTOR_CAP for count in sectors.values()):
            raise ValueError(f"{market} exceeds broad-sector cap")
        for row in rows:
            _validate_manifest_symbol(row, market)


def _validate_manifest_symbol(row: Mapping[str, Any], market: str) -> None:
    required = {
        "market",
        "symbol",
        "issuer_id",
        "exchange",
        "security_type",
        "primary_listing",
        "active_status",
        "provider_metadata_available",
        "share_class",
        "is_adr",
        "special_trading_status",
        "broad_sector",
        "listing_date",
        "history_length",
        "liquidity_rank",
        "manifest_rank",
        "intended_role",
    }
    missing = required - set(row)
    if missing:
        raise ValueError(f"{market} manifest symbol missing keys: {sorted(missing)}")
    if row["market"] != market:
        raise ValueError("manifest symbol market mismatch")
    if row["security_type"] not in ALLOWED_SECURITY_TYPES:
        raise ValueError("manifest contains a non-ordinary equity security")
    if row["primary_listing"] is not True or row["active_status"] != "ACTIVE":
        raise ValueError("manifest contains a non-primary or inactive symbol")
    if not row["provider_metadata_available"] or row["is_adr"]:
        raise ValueError("manifest contains unsupported provider metadata or ADR")
    if row["special_trading_status"] not in NORMAL_SPECIAL_STATUSES:
        raise ValueError("manifest contains a special-trading-status symbol")
    if date.fromisoformat(row["listing_date"]) > date(2022, 8, 26):
        raise ValueError("manifest contains a symbol listed after the age cutoff")
    if row["intended_role"] not in {"PRIMARY", "RESERVE"}:
        raise ValueError("manifest role is invalid")
    _positive_int(row["liquidity_rank"], "manifest liquidity_rank")
    _positive_int(row["history_length"], "manifest history_length")


def _reject_duplicate_symbols(rows: Iterable[Mapping[str, Any]]) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["market"], row["symbol"])
        if key in seen:
            raise ValueError(f"duplicate metadata symbol: {key[0]}/{key[1]}")
        seen.add(key)


def _reject_forbidden_selection_fields(raw: Mapping[str, Any]) -> None:
    for field in raw:
        normalized = str(field).strip().lower().replace("-", "_")
        if any(fragment in normalized for fragment in FORBIDDEN_SELECTION_FIELD_FRAGMENTS):
            raise ValueError(f"forbidden signal/result metadata field: {field}")


def _text(raw: Mapping[str, Any], field: str) -> str:
    value = raw.get(field)
    if value is None or not str(value).strip():
        raise ValueError(f"metadata field {field} is required")
    return str(value).strip()


def _required_bool(raw: Mapping[str, Any], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"metadata field {field} must be boolean")
    return value


def _optional_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"metadata field {field} must be boolean")
    return value


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata field {field} must be an ISO date") from exc


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"metadata field {field} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata field {field} must be a positive integer") from exc
    if result <= 0 or str(value).strip() not in {str(result), f"{result}.0"}:
        raise ValueError(f"metadata field {field} must be a positive integer")
    return result

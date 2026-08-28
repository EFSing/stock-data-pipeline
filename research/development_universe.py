"""Development-only universe selection kept separate from Phase 5K-A1.

The selector consumes only the already committed A1 source snapshots.  It
removes every A1 formal candidate before applying a new, fixed SHA-256 rank.
No OHLCV, SETUP_03 output, or performance field is imported here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from research.phase5k_a1_universe import (
    CN_COHORTS,
    CN_MAIN_ACTIVE,
    MANIFEST_PATH as A1_MANIFEST_PATH,
    MANIFEST_VERSION as A1_MANIFEST_VERSION,
    SNAPSHOT_DIR as A1_SNAPSHOT_DIR,
    US_COHORTS,
    _rank_key,
    load_manifest as load_a1_manifest,
    load_snapshot_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_DIR = Path(__file__).with_name("development")
DEVELOPMENT_UNIVERSE_PATH = DEVELOPMENT_DIR / "universe_manifest.json"

DEVELOPMENT_UNIVERSE_SCHEMA_VERSION = "setup03-development-universe-manifest-v1"
DEVELOPMENT_UNIVERSE_VERSION = (
    "SETUP_03-DEVELOPMENT-UNIVERSE-CN-US-2026-08-28-v1"
)
DEVELOPMENT_SELECTION_SPEC_VERSION = (
    "SETUP_03-DEVELOPMENT-SELECTION-CN-US-2026-08-28-v1"
)
DEVELOPMENT_FIXED_SEED = "SETUP_03-DEVELOPMENT-CN-US-FIXED-SHA256-SEED-2026-08-28-v1"
CN_COHORT_ORDER = CN_COHORTS
US_COHORT_ORDER = US_COHORTS
DEVELOPMENT_COHORT_ORDER = {"CN": CN_COHORT_ORDER, "US": US_COHORT_ORDER}
DEVELOPMENT_PRIMARY_QUOTAS = MappingProxyType(
    {
        "CN": MappingProxyType({"CSI300": 6, "CSI500": 7, "CSI1000": 7}),
        "US": MappingProxyType({"SP500": 5, "NASDAQ100": 5, "SOX": 5, "IGV": 5}),
    }
)
DEVELOPMENT_TOTAL_BY_MARKET = MappingProxyType({"CN": 20, "US": 20})

# These are governance pins, not replacements for the actual A1 loader checks.
PINNED_A1_MANIFEST_SHA256 = (
    "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433"
)
PINNED_DEVELOPMENT_UNIVERSE_MANIFEST_SHA256 = (
    "sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046"
)
DEVELOPMENT_LABELS = (
    "DEVELOPMENT_ONLY",
    "NOT_FORMAL_VALIDATION",
    "NOT_FINAL_OOS",
)


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("integrity", None)
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def symbol_list_hash(symbols: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "market": row["market"],
            "canonical_symbol": row["canonical_symbol"],
            "canonical_identity": row["canonical_identity"],
            "source_cohort": row["source_cohort"],
            "yfinance_symbol": row["yfinance_symbol"],
            "ranking_digest": row["ranking_digest"],
        }
        for row in symbols
    ]
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def yfinance_symbol(market: str, canonical_symbol: str) -> str:
    if market == "CN":
        ticker, exchange = canonical_symbol.split(".", 1)
        exchange_map = {"SH": "SS", "SZ": "SZ"}
        if exchange not in exchange_map:
            raise ValueError(f"unsupported CN exchange for yfinance: {canonical_symbol}")
        return f"{ticker}.{exchange_map[exchange]}"
    if market == "US":
        return canonical_symbol
    raise ValueError(f"development universe only supports CN/US: {market}")


def _source_record(provenance: Mapping[str, Any], cohort: str) -> dict[str, Any]:
    records = [
        record
        for record in provenance.get("source_snapshots", [])
        if record.get("cohort") == cohort
    ]
    if len(records) != 1:
        raise ValueError(f"A1 source snapshot identity is not unique: {cohort}")
    record = dict(records[0])
    return {
        "source_id": record["source_id"],
        "source_identity": record["source_identity"],
        "source_role": record["source_role"],
        "raw_snapshot_path": record["raw_snapshot_path"],
        "raw_snapshot_sha256": record["raw_snapshot_sha256"],
        "retrieval_timestamp": record["retrieval_timestamp"],
        "constituent_count": record["constituent_count"],
        "cohort": cohort,
    }


def _ranked_remaining(
    market: str,
    cohort: str,
    rows: Sequence[Mapping[str, Any]],
    formal_identities: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], int]:
    ranked = sorted(
        (dict(row) for row in rows),
        key=lambda row: _rank_key(
            row,
            fixed_seed=DEVELOPMENT_FIXED_SEED,
            market=market,
            cohort=cohort,
        ),
    )
    remaining: list[dict[str, Any]] = []
    formal_excluded = 0
    claimed: set[str] = set()
    for row in ranked:
        identity = str(row["canonical_identity"])
        if (market, identity) in formal_identities:
            formal_excluded += 1
            continue
        if identity in claimed:
            continue
        claimed.add(identity)
        digest, _ = _rank_key(
            row,
            fixed_seed=DEVELOPMENT_FIXED_SEED,
            market=market,
            cohort=cohort,
        )
        row["ranking_digest"] = digest
        remaining.append(row)
    return remaining, formal_excluded


def _select_market(
    market: str,
    cohorts: Mapping[str, Sequence[Mapping[str, Any]]],
    formal_identities: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected: list[dict[str, Any]] = []
    claimed: set[str] = set()
    remaining_by_cohort: dict[str, int] = {}
    for cohort in DEVELOPMENT_COHORT_ORDER[market]:
        ranked, formal_excluded = _ranked_remaining(
            market, cohort, cohorts.get(cohort, ()), formal_identities
        )
        remaining_by_cohort[cohort] = len(ranked)
        quota = DEVELOPMENT_PRIMARY_QUOTAS[market][cohort]
        if len(ranked) < quota:
            raise ValueError(f"{market}/{cohort} cannot fill development quota")
        position = 0
        for row in ranked:
            identity = str(row["canonical_identity"])
            if identity in claimed:
                continue
            claimed.add(identity)
            position += 1
            if position > quota:
                break
            output = {
                "market": market,
                "canonical_symbol": row["canonical_symbol"],
                "canonical_identity": identity,
                "source_cohort": cohort,
                "source_name": row.get("source_name", ""),
                "ranking_digest": row["ranking_digest"],
                "cohort_rank": position,
                "yfinance_symbol": yfinance_symbol(market, str(row["canonical_symbol"])),
            }
            if market == "CN":
                if row.get("board_status") not in CN_MAIN_ACTIVE:
                    raise ValueError("inactive CN board entered development universe")
                output["board_status"] = row["board_status"]
                output["source_ticker"] = row.get("source_ticker", "")
            else:
                output["source_sector"] = row.get("source_sector", "")
                output["source_asset_class"] = row.get("source_asset_class", "Equity")
            selected.append(output)
            if position == quota:
                break
        if position != quota:
            raise ValueError(f"{market}/{cohort} cannot fill unique development quota")
    return selected, remaining_by_cohort


def build_development_universe_manifest(
    *,
    a1_manifest: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    cn_cohorts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    us_cohorts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    frozen_at: str = "2026-08-28",
) -> dict[str, Any]:
    """Build the deterministic development-only universe from A1 snapshots."""
    formal = dict(a1_manifest or load_a1_manifest(A1_MANIFEST_PATH))
    if formal["manifest_version"] != A1_MANIFEST_VERSION:
        raise ValueError("development universe must bind to active A1 v2")
    if formal["integrity"]["manifest_sha256"] != PINNED_A1_MANIFEST_SHA256:
        raise ValueError("active A1 manifest hash is not pinned")
    formal_rows = list(formal["symbols"])
    formal_identities = {
        (str(row["market"]), str(row["canonical_identity"])) for row in formal_rows
    }
    if len(formal_rows) != 120 or len(formal_identities) != 120:
        raise ValueError("A1 formal candidate set is not exactly 120 unique identities")

    if provenance is None or cn_cohorts is None or us_cohorts is None:
        loaded_provenance, loaded_cn, loaded_us = load_snapshot_bundle(A1_SNAPSHOT_DIR)
        provenance = loaded_provenance
        cn_cohorts = loaded_cn
        us_cohorts = loaded_us

    cn_selected, cn_remaining = _select_market("CN", cn_cohorts, formal_identities)
    us_selected, us_remaining = _select_market("US", us_cohorts, formal_identities)
    symbols = cn_selected + us_selected
    for rank, row in enumerate(symbols, start=1):
        row["universe_rank"] = rank

    selected_identities = {
        (row["market"], row["canonical_identity"]) for row in symbols
    }
    overlap = sorted(selected_identities & formal_identities)
    if overlap:
        raise ValueError(f"development universe overlaps A1 formal universe: {overlap}")

    source_records = [
        _source_record(provenance, cohort)
        for cohort in (*CN_COHORT_ORDER, *US_COHORT_ORDER)
    ]
    selection_spec = {
        "selection_spec_version": DEVELOPMENT_SELECTION_SPEC_VERSION,
        "fixed_seed": DEVELOPMENT_FIXED_SEED,
        "cohort_order": {
            "CN": list(CN_COHORT_ORDER),
            "US": list(US_COHORT_ORDER),
        },
        "quota_by_market_and_cohort": {
            market: dict(DEVELOPMENT_PRIMARY_QUOTAS[market])
            for market in ("CN", "US")
        },
        "ranking": {
            "algorithm": "SHA-256",
            "input_template": "fixed_seed|market|cohort|canonical_symbol",
            "sort_order": "digest_ascending_then_canonical_symbol_ascending",
            "selection_inputs_are_non_signal_only": True,
        },
        "exclusion": "remove every A1 v2 formal canonical identity before ranking",
        "duplicate_attribution": "first declared cohort claims canonical identity",
        "cn_board_scope": list(CN_MAIN_ACTIVE),
        "forbidden_inputs": [
            "SETUP_03 output", "returns", "MFE", "MAE", "win_rate", "P&L", "OOS"
        ],
    }
    selection_spec["selection_spec_sha256"] = sha256_bytes(
        canonical_json(selection_spec).encode("utf-8")
    )
    manifest = {
        "schema_version": DEVELOPMENT_UNIVERSE_SCHEMA_VERSION,
        "universe_version": DEVELOPMENT_UNIVERSE_VERSION,
        "status": "DEVELOPMENT_UNIVERSE_FROZEN_NOT_FORMAL_VALIDATION",
        "artifact_labels": list(DEVELOPMENT_LABELS),
        "frozen_at": frozen_at,
        "parent_a1": {
            "manifest_path": str(A1_MANIFEST_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "manifest_version": A1_MANIFEST_VERSION,
            "manifest_sha256": PINNED_A1_MANIFEST_SHA256,
            "formal_candidate_count": len(formal_rows),
        },
        "source_snapshot_bundle": {
            "path": str(A1_SNAPSHOT_DIR.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "source_snapshot_identities": source_records,
            "identity": sha256_bytes(
                canonical_json(source_records).encode("utf-8")
            ),
        },
        "selection_spec": selection_spec,
        "candidate_pool_after_a1_exclusion": {
            "CN": cn_remaining,
            "US": us_remaining,
            "total_unique_selected": len(symbols),
        },
        "a1_exclusion_proof": {
            "formal_identity_count": len(formal_identities),
            "development_identity_count": len(selected_identities),
            "intersection": overlap,
            "intersection_count": len(overlap),
            "intersection_is_empty": not overlap,
            "comparison_key": "(market, canonical_identity)",
        },
        "counts": {
            "CN": len(cn_selected),
            "US": len(us_selected),
            "total": len(symbols),
        },
        "symbols": symbols,
        "symbol_list_sha256": symbol_list_hash(symbols),
        "controls": {
            "historical_ohlcv_accessed": False,
            "setup03_output_accessed": False,
            "final_oos_accessed": False,
            "selection_precedes_ohlcv": True,
            "result_driven_replacement_allowed": False,
        },
    }
    manifest["integrity"] = {"manifest_sha256": manifest_integrity_hash(manifest)}
    return manifest


def validate_development_universe_manifest(
    manifest: Mapping[str, Any],
    *,
    a1_manifest: Mapping[str, Any] | None = None,
) -> None:
    if manifest.get("schema_version") != DEVELOPMENT_UNIVERSE_SCHEMA_VERSION:
        raise ValueError("unsupported development universe schema")
    if manifest.get("universe_version") != DEVELOPMENT_UNIVERSE_VERSION:
        raise ValueError("development universe version changed")
    if tuple(manifest.get("artifact_labels", ())) != DEVELOPMENT_LABELS:
        raise ValueError("development artifact labels changed")
    if manifest.get("integrity", {}).get("manifest_sha256") != manifest_integrity_hash(manifest):
        raise ValueError("development universe integrity mismatch")
    if manifest["integrity"]["manifest_sha256"] != PINNED_DEVELOPMENT_UNIVERSE_MANIFEST_SHA256:
        raise ValueError("development universe version is bound to a different hash")
    if not manifest.get("a1_exclusion_proof", {}).get("intersection_is_empty"):
        raise ValueError("A1 exclusion proof is not empty")
    if manifest["a1_exclusion_proof"].get("intersection") != []:
        raise ValueError("development universe has an A1 intersection")
    if manifest["counts"] != {"CN": 20, "US": 20, "total": 40}:
        raise ValueError("development universe quota changed")
    formal = dict(a1_manifest or load_a1_manifest(A1_MANIFEST_PATH))
    formal_ids = {
        (str(row["market"]), str(row["canonical_identity"]))
        for row in formal["symbols"]
    }
    selected_ids = {
        (str(row["market"]), str(row["canonical_identity"]))
        for row in manifest["symbols"]
    }
    if selected_ids & formal_ids:
        raise ValueError("computed A1/development intersection is not empty")
    if manifest.get("symbol_list_sha256") != symbol_list_hash(manifest["symbols"]):
        raise ValueError("development symbol list hash mismatch")


def load_development_universe_manifest(
    path: Path = DEVELOPMENT_UNIVERSE_PATH,
) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_development_universe_manifest(manifest)
    return manifest


def write_development_universe_manifest(
    path: Path = DEVELOPMENT_UNIVERSE_PATH,
) -> dict[str, Any]:
    manifest = build_development_universe_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    result = write_development_universe_manifest()
    print(json.dumps({
        "universe_version": result["universe_version"],
        "symbol_list_sha256": result["symbol_list_sha256"],
        "manifest_sha256": result["integrity"]["manifest_sha256"],
        "a1_intersection": result["a1_exclusion_proof"]["intersection"],
    }, ensure_ascii=False))

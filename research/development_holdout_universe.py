"""Freeze the second independent development universe for Phase 5J-v3.

Only the committed A1 v2 source snapshots and metadata manifests are read.
This module intentionally has no OHLCV, replay, SETUP_03, or outcome-metric
dependency.  The holdout is selected before any historical data is acquired.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from research.development_universe import (
    DEVELOPMENT_UNIVERSE_VERSION as DEVELOPMENT_V1_VERSION,
    load_development_universe_manifest,
)
from research.phase5k_a1_universe import (
    CN_COHORTS,
    CN_MAIN_ACTIVE,
    MANIFEST_PATH as A1_MANIFEST_PATH,
    MANIFEST_VERSION as A1_MANIFEST_VERSION,
    SNAPSHOT_DIR as A1_SNAPSHOT_DIR,
    US_COHORTS,
    load_manifest as load_a1_manifest,
    load_snapshot_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOLDOUT_DIR = Path(__file__).with_name("development_holdout")
HOLDOUT_UNIVERSE_PATH = HOLDOUT_DIR / "universe_manifest.json"
HOLDOUT_SCHEMA_VERSION = "setup03-development-holdout-universe-manifest-v1"
HOLDOUT_UNIVERSE_VERSION = "SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-2026-08-29-v2"
HOLDOUT_SELECTION_SPEC_VERSION = "SETUP_03-DEVELOPMENT-HOLDOUT-SELECTION-CN-US-2026-08-29-v1"
HOLDOUT_FIXED_SEED = "SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-FIXED-SHA256-SEED-2026-08-29-v1"
HOLDOUT_LABELS = ("DEVELOPMENT_ONLY", "NOT_FORMAL_VALIDATION", "NOT_FINAL_OOS")
PINNED_A1_MANIFEST_SHA256 = "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433"
PINNED_DEVELOPMENT_V1_MANIFEST_SHA256 = "sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046"
PINNED_HOLDOUT_UNIVERSE_MANIFEST_SHA256 = "sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65"
CN_COHORT_ORDER = tuple(CN_COHORTS)
US_COHORT_ORDER = tuple(US_COHORTS)
HOLDOUT_COHORT_ORDER = {"CN": CN_COHORT_ORDER, "US": US_COHORT_ORDER}
HOLDOUT_PRIMARY_QUOTAS = MappingProxyType(
    {
        "CN": MappingProxyType({"CSI300": 6, "CSI500": 7, "CSI1000": 7}),
        "US": MappingProxyType({"SP500": 5, "NASDAQ100": 5, "SOX": 5, "IGV": 5}),
    }
)
HOLDOUT_COUNTS = {"CN": 20, "US": 20, "total": 40}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(manifest))
    payload.pop("integrity", None)
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def symbol_list_hash(symbols: Sequence[Mapping[str, Any]]) -> str:
    projection = [
        {
            "market": row["market"],
            "canonical_symbol": row["canonical_symbol"],
            "canonical_identity": row["canonical_identity"],
            "source_cohort": row["source_cohort"],
            "ranking_digest": row["ranking_digest"],
            "yfinance_symbol": row["yfinance_symbol"],
        }
        for row in symbols
    ]
    return sha256_bytes(canonical_json(projection).encode("utf-8"))


def _rank_key(row: Mapping[str, Any], *, market: str, cohort: str) -> tuple[str, str]:
    symbol = str(row["canonical_symbol"])
    material = f"{HOLDOUT_FIXED_SEED}|{market}|{cohort}|{symbol}".encode("utf-8")
    return hashlib.sha256(material).hexdigest(), symbol


def _yfinance_symbol(market: str, canonical_symbol: str) -> str:
    if market == "CN":
        ticker, exchange = canonical_symbol.split(".", 1)
        if exchange == "SH":
            return f"{ticker}.SS"
        if exchange == "SZ":
            return f"{ticker}.SZ"
        raise ValueError(f"unsupported CN exchange: {canonical_symbol}")
    if market == "US":
        return canonical_symbol
    raise ValueError(f"unsupported holdout market: {market}")


def _identity_set(rows: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {(str(row["market"]), str(row["canonical_identity"])) for row in rows}


def _select_market(
    market: str,
    cohorts: Mapping[str, Sequence[Mapping[str, Any]]],
    excluded: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected: list[dict[str, Any]] = []
    claimed: set[str] = set()
    pool_counts: dict[str, int] = {}
    for cohort in HOLDOUT_COHORT_ORDER[market]:
        ranked = sorted(
            (dict(row) for row in cohorts.get(cohort, ())),
            key=lambda row: _rank_key(row, market=market, cohort=cohort),
        )
        available: list[dict[str, Any]] = []
        for row in ranked:
            identity = str(row["canonical_identity"])
            if (market, identity) in excluded or identity in claimed:
                continue
            available.append(row)
        pool_counts[cohort] = len(available)
        quota = int(HOLDOUT_PRIMARY_QUOTAS[market][cohort])
        if len(available) < quota:
            raise ValueError(f"{market}/{cohort} cannot fill independent holdout quota")
        for position, row in enumerate(available[:quota], start=1):
            identity = str(row["canonical_identity"])
            claimed.add(identity)
            digest, _ = _rank_key(row, market=market, cohort=cohort)
            output = {
                "market": market,
                "canonical_symbol": row["canonical_symbol"],
                "canonical_identity": identity,
                "source_cohort": cohort,
                "source_name": row.get("source_name", ""),
                "ranking_digest": digest,
                "cohort_rank": position,
                "yfinance_symbol": _yfinance_symbol(market, str(row["canonical_symbol"])),
            }
            if market == "CN":
                if row.get("board_status") not in CN_MAIN_ACTIVE:
                    raise ValueError("inactive CN board entered independent holdout")
                output["board_status"] = row["board_status"]
                output["source_ticker"] = row.get("source_ticker", "")
            else:
                output["source_sector"] = row.get("source_sector", "")
                output["source_asset_class"] = row.get("source_asset_class", "Equity")
            selected.append(output)
    if len(selected) != HOLDOUT_COUNTS[market]:
        raise ValueError(f"{market} independent holdout count changed")
    return selected, pool_counts


def _source_snapshot_identities(provenance: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = provenance.get("source_snapshots")
    if not isinstance(records, list) or len(records) != 7:
        raise ValueError("A1 source bundle must contain exactly seven snapshots")
    return [
        {
            "source_id": record["source_id"],
            "source_identity": record["source_identity"],
            "source_role": record["source_role"],
            "raw_snapshot_path": record["raw_snapshot_path"],
            "raw_snapshot_sha256": record["raw_snapshot_sha256"],
            "retrieval_timestamp": record["retrieval_timestamp"],
            "constituent_count": record["constituent_count"],
            "cohort": record["cohort"],
        }
        for record in records
    ]


def build_holdout_universe_manifest(
    *,
    a1_manifest: Mapping[str, Any] | None = None,
    development_v1_manifest: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    cn_cohorts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    us_cohorts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    frozen_at: str = "2026-08-29",
) -> dict[str, Any]:
    formal = dict(a1_manifest or load_a1_manifest(A1_MANIFEST_PATH))
    if formal.get("manifest_version") != A1_MANIFEST_VERSION or formal.get("integrity", {}).get("manifest_sha256") != PINNED_A1_MANIFEST_SHA256:
        raise ValueError("active A1 v2 manifest is not pinned")
    formal_rows = list(formal.get("symbols", ()))
    if len(formal_rows) != 120:
        raise ValueError("A1 formal universe must contain exactly 120 symbols")

    development_v1 = dict(development_v1_manifest or load_development_universe_manifest())
    if development_v1.get("universe_version") != DEVELOPMENT_V1_VERSION or development_v1.get("integrity", {}).get("manifest_sha256") != PINNED_DEVELOPMENT_V1_MANIFEST_SHA256:
        raise ValueError("development v1 manifest is not pinned")
    development_v1_rows = list(development_v1.get("symbols", ()))
    if len(development_v1_rows) != 40:
        raise ValueError("development v1 universe must contain exactly 40 symbols")

    formal_ids = _identity_set(formal_rows)
    development_v1_ids = _identity_set(development_v1_rows)
    if formal_ids & development_v1_ids:
        raise ValueError("A1 formal and development v1 identities unexpectedly overlap")
    excluded = formal_ids | development_v1_ids

    if provenance is None or cn_cohorts is None or us_cohorts is None:
        loaded_provenance, loaded_cn, loaded_us = load_snapshot_bundle(A1_SNAPSHOT_DIR)
        provenance, cn_cohorts, us_cohorts = loaded_provenance, loaded_cn, loaded_us

    cn_selected, cn_pool = _select_market("CN", cn_cohorts, excluded)
    us_selected, us_pool = _select_market("US", us_cohorts, excluded)
    symbols = cn_selected + us_selected
    for rank, row in enumerate(symbols, start=1):
        row["holdout_rank"] = rank
    selected_ids = _identity_set(symbols)
    if selected_ids & formal_ids or selected_ids & development_v1_ids:
        raise ValueError("independent holdout exclusion proof is not empty")

    selection_spec = {
        "selection_spec_version": HOLDOUT_SELECTION_SPEC_VERSION,
        "fixed_seed": HOLDOUT_FIXED_SEED,
        "cohort_order": {"CN": list(CN_COHORT_ORDER), "US": list(US_COHORT_ORDER)},
        "quota_by_market_and_cohort": {
            market: dict(HOLDOUT_PRIMARY_QUOTAS[market]) for market in ("CN", "US")
        },
        "ranking": {
            "algorithm": "SHA-256",
            "input_template": "fixed_seed|market|cohort|canonical_symbol",
            "sort_order": "digest_ascending_then_canonical_symbol_ascending",
            "result_independent": True,
            "selection_inputs_are_metadata_only": True,
        },
        "exclusions_before_ranking": {
            "a1_formal_identity_count": len(formal_ids),
            "development_v1_identity_count": len(development_v1_ids),
            "combined_identity_count": len(excluded),
        },
        "forbidden_inputs": [
            "SETUP_03 output", "event", "signal", "returns", "MFE", "MAE",
            "P&L", "win rate", "profit factor", "expectancy", "Final OOS",
        ],
    }
    selection_spec["selection_spec_sha256"] = sha256_bytes(canonical_json(selection_spec).encode("utf-8"))
    source_records = _source_snapshot_identities(provenance)
    manifest = {
        "schema_version": HOLDOUT_SCHEMA_VERSION,
        "universe_version": HOLDOUT_UNIVERSE_VERSION,
        "status": "DEVELOPMENT_HOLDOUT_UNIVERSE_FROZEN_NOT_ACQUIRED",
        "artifact_labels": list(HOLDOUT_LABELS),
        "frozen_at": frozen_at,
        "parent_a1": {
            "manifest_path": str(A1_MANIFEST_PATH.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "manifest_version": A1_MANIFEST_VERSION,
            "manifest_sha256": PINNED_A1_MANIFEST_SHA256,
            "formal_candidate_count": len(formal_ids),
        },
        "excluded_development_v1": {
            "manifest_path": "research/development/universe_manifest.json",
            "universe_version": DEVELOPMENT_V1_VERSION,
            "manifest_sha256": PINNED_DEVELOPMENT_V1_MANIFEST_SHA256,
            "symbol_count": len(development_v1_ids),
        },
        "source_snapshot_bundle": {
            "path": str(A1_SNAPSHOT_DIR.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "source_snapshot_identities": source_records,
            "identity": sha256_bytes(canonical_json(source_records).encode("utf-8")),
        },
        "selection_spec": selection_spec,
        "candidate_pool_after_exclusions": {"CN": cn_pool, "US": us_pool},
        "exclusion_proofs": {
            "a1_formal_120": {
                "excluded_count": len(formal_ids),
                "intersection": sorted(_identity_set(symbols) & formal_ids),
                "intersection_count": len(_identity_set(symbols) & formal_ids),
                "intersection_is_empty": not bool(_identity_set(symbols) & formal_ids),
                "comparison_key": "(market, canonical_identity)",
            },
            "development_v1_40": {
                "excluded_count": len(development_v1_ids),
                "intersection": sorted(_identity_set(symbols) & development_v1_ids),
                "intersection_count": len(_identity_set(symbols) & development_v1_ids),
                "intersection_is_empty": not bool(_identity_set(symbols) & development_v1_ids),
                "comparison_key": "(market, canonical_identity)",
            },
        },
        "counts": dict(HOLDOUT_COUNTS),
        "symbols": symbols,
        "symbol_list_sha256": symbol_list_hash(symbols),
        "controls": {
            "historical_ohlcv_accessed": False,
            "setup03_output_accessed": False,
            "event_or_signal_output_accessed": False,
            "final_oos_accessed": False,
            "selection_precedes_ohlcv": True,
            "result_driven_ranking_or_replacement_allowed": False,
        },
    }
    manifest["integrity"] = {"manifest_sha256": manifest_integrity_hash(manifest)}
    return manifest


def validate_holdout_universe_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != HOLDOUT_SCHEMA_VERSION:
        raise ValueError("holdout universe schema changed")
    if manifest.get("universe_version") != HOLDOUT_UNIVERSE_VERSION:
        raise ValueError("holdout universe version changed")
    if tuple(manifest.get("artifact_labels", ())) != HOLDOUT_LABELS:
        raise ValueError("holdout labels changed")
    if manifest.get("integrity", {}).get("manifest_sha256") != manifest_integrity_hash(manifest):
        raise ValueError("holdout universe integrity mismatch")
    if manifest["integrity"]["manifest_sha256"] != PINNED_HOLDOUT_UNIVERSE_MANIFEST_SHA256:
        raise ValueError("holdout universe version is bound to a different hash")
    if manifest.get("counts") != HOLDOUT_COUNTS:
        raise ValueError("holdout universe quota changed")
    proofs = manifest.get("exclusion_proofs", {})
    for name in ("a1_formal_120", "development_v1_40"):
        proof = proofs.get(name, {})
        if proof.get("intersection") != [] or proof.get("intersection_count") != 0 or proof.get("intersection_is_empty") is not True:
            raise ValueError(f"holdout exclusion proof failed: {name}")
    if manifest.get("symbol_list_sha256") != symbol_list_hash(manifest["symbols"]):
        raise ValueError("holdout symbol list hash mismatch")
    formal = load_a1_manifest(A1_MANIFEST_PATH)
    formal_ids = _identity_set(formal["symbols"])
    v1 = load_development_universe_manifest()
    v1_ids = _identity_set(v1["symbols"])
    selected_ids = _identity_set(manifest["symbols"])
    if selected_ids & formal_ids or selected_ids & v1_ids:
        raise ValueError("computed holdout exclusion intersection is not empty")
    if not manifest.get("controls", {}).get("selection_precedes_ohlcv") or manifest["controls"].get("result_driven_ranking_or_replacement_allowed"):
        raise ValueError("holdout selection control weakened")


def load_holdout_universe_manifest(path: Path = HOLDOUT_UNIVERSE_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_holdout_universe_manifest(manifest)
    return manifest


def write_holdout_universe_manifest(path: Path = HOLDOUT_UNIVERSE_PATH) -> dict[str, Any]:
    manifest = build_holdout_universe_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = write_holdout_universe_manifest()
    print(json.dumps({
        "universe_version": result["universe_version"],
        "symbol_list_sha256": result["symbol_list_sha256"],
        "manifest_sha256": result["integrity"]["manifest_sha256"],
        "a1_intersection": result["exclusion_proofs"]["a1_formal_120"]["intersection"],
        "development_v1_intersection": result["exclusion_proofs"]["development_v1_40"]["intersection"],
    }, ensure_ascii=False))

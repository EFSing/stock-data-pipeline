"""Select the last clean development holdout from frozen metadata snapshots only."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from research.atr_boundary_protocol import PROTOCOL_VERSION, load_protocol
from research.development_holdout_universe import load_holdout_universe_manifest
from research.development_universe import load_development_universe_manifest, yfinance_symbol
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
UNIVERSE_PATH = PROJECT_ROOT / "research" / "atr_boundary_universe_manifest.json"
SCHEMA_VERSION = "setup03-atr-boundary-clean-holdout-universe-v1"
UNIVERSE_VERSION = "SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-CN-US-2026-08-29-v1"
SELECTION_SPEC_VERSION = "SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-SELECTION-2026-08-29-v1"
FIXED_SEED = "SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-SHA256-SEED-2026-08-29-v1"
LABELS = ("DEVELOPMENT_ONLY", "NOT_FORMAL_VALIDATION", "NOT_FINAL_OOS")
COHORT_ORDER = {"CN": tuple(CN_COHORTS), "US": tuple(US_COHORTS)}
QUOTAS = MappingProxyType({
    "CN": MappingProxyType({"CSI300": 6, "CSI500": 7, "CSI1000": 7}),
    "US": MappingProxyType({"SP500": 5, "NASDAQ100": 5, "SOX": 5, "IGV": 5}),
})
TARGET_COUNTS = {"CN": 20, "US": 20, "total": 40}
A1_HASH = "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433"
DEVELOPMENT_V1_HASH = "sha256:0dde6a822ae57a7f048aa7b5097a69624138e3b8566602ad1fba25ee3b473046"
SECOND_HOLDOUT_HASH = "sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


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


def _identity_set(rows: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {(str(row["market"]), str(row["canonical_identity"])) for row in rows}


def _rank_key(market: str, cohort: str, identity: str) -> tuple[str, str]:
    digest = hashlib.sha256(f"{FIXED_SEED}|{market}|{cohort}|{identity}".encode("utf-8")).hexdigest()
    return digest, identity


def _source_snapshot_records(provenance: Mapping[str, Any]) -> list[dict[str, Any]]:
    records = provenance.get("source_snapshots")
    if not isinstance(records, list) or len(records) != 7:
        raise ValueError("A1 source bundle must contain exactly seven snapshots")
    return [dict(record) for record in records]


def _select_market(
    market: str,
    cohorts: Mapping[str, Sequence[Mapping[str, Any]]],
    excluded: set[tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected: list[dict[str, Any]] = []
    claimed: set[str] = set()
    pools: dict[str, int] = {}
    for cohort in COHORT_ORDER[market]:
        ranked = sorted(
            (dict(row) for row in cohorts.get(cohort, ())),
            key=lambda row: _rank_key(market, cohort, str(row["canonical_identity"])),
        )
        available = [
            row for row in ranked
            if (market, str(row["canonical_identity"])) not in excluded
            and str(row["canonical_identity"]) not in claimed
        ]
        pools[cohort] = len(available)
        quota = int(QUOTAS[market][cohort])
        if len(available) < quota:
            raise ValueError(f"{market}/{cohort} cannot fill clean holdout quota")
        for position, row in enumerate(available[:quota], start=1):
            identity = str(row["canonical_identity"])
            claimed.add(identity)
            output = {
                "market": market,
                "canonical_symbol": str(row["canonical_symbol"]),
                "canonical_identity": identity,
                "source_cohort": cohort,
                "source_name": row.get("source_name", ""),
                "ranking_digest": _rank_key(market, cohort, identity)[0],
                "cohort_rank": position,
                "yfinance_symbol": yfinance_symbol(market, str(row["canonical_symbol"])),
            }
            if market == "CN":
                if row.get("board_status") not in CN_MAIN_ACTIVE:
                    raise ValueError("inactive CN board entered clean holdout")
                output["board_status"] = row["board_status"]
                output["source_ticker"] = row.get("source_ticker", "")
            else:
                output["source_sector"] = row.get("source_sector", "")
                output["source_asset_class"] = row.get("source_asset_class", "Equity")
            selected.append(output)
    if len(selected) != TARGET_COUNTS[market]:
        raise ValueError(f"{market} clean holdout count changed")
    return selected, pools


def build_universe_manifest(
    *,
    a1_manifest: Mapping[str, Any] | None = None,
    development_v1_manifest: Mapping[str, Any] | None = None,
    second_holdout_manifest: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    cn_cohorts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    us_cohorts: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    frozen_at: str = "2026-08-29",
) -> dict[str, Any]:
    protocol = load_protocol()
    formal = dict(a1_manifest or load_a1_manifest(A1_MANIFEST_PATH))
    dev_v1 = dict(development_v1_manifest or load_development_universe_manifest())
    second = dict(second_holdout_manifest or load_holdout_universe_manifest())
    if formal.get("manifest_version") != A1_MANIFEST_VERSION or formal.get("integrity", {}).get("manifest_sha256") != A1_HASH:
        raise ValueError("A1 formal manifest is not pinned")
    if dev_v1.get("integrity", {}).get("manifest_sha256") != DEVELOPMENT_V1_HASH:
        raise ValueError("development v1 manifest is not pinned")
    if second.get("integrity", {}).get("manifest_sha256") != SECOND_HOLDOUT_HASH:
        raise ValueError("second holdout manifest is not pinned")
    if len(formal.get("symbols", ())) != 120 or len(dev_v1.get("symbols", ())) != 40 or len(second.get("symbols", ())) != 40:
        raise ValueError("clean holdout exclusion counts changed")
    formal_ids = _identity_set(formal["symbols"])
    dev_ids = _identity_set(dev_v1["symbols"])
    second_ids = _identity_set(second["symbols"])
    excluded = formal_ids | dev_ids | second_ids
    if len(excluded) != 200:
        raise ValueError("clean holdout exclusion identities overlap unexpectedly")
    if provenance is None or cn_cohorts is None or us_cohorts is None:
        provenance, cn_cohorts, us_cohorts = load_snapshot_bundle(A1_SNAPSHOT_DIR)
    cn_selected, cn_pool = _select_market("CN", cn_cohorts, excluded)
    us_selected, us_pool = _select_market("US", us_cohorts, excluded)
    symbols = cn_selected + us_selected
    for rank, row in enumerate(symbols, start=1):
        row["holdout_rank"] = rank
    selected_ids = _identity_set(symbols)
    proofs = {
        "a1_formal_120": sorted(selected_ids & formal_ids),
        "development_v1_40": sorted(selected_ids & dev_ids),
        "second_development_holdout_40": sorted(selected_ids & second_ids),
    }
    if any(proofs.values()):
        raise ValueError("clean holdout exclusion proof is not empty")
    selection_spec = {
        "selection_spec_version": SELECTION_SPEC_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "fixed_seed": FIXED_SEED,
        "cohort_order": {market: list(COHORT_ORDER[market]) for market in ("CN", "US")},
        "quota_by_market_and_cohort": {market: dict(QUOTAS[market]) for market in ("CN", "US")},
        "ranking": {
            "algorithm": "SHA-256",
            "input_template": "new_seed|market|cohort|canonical_identity",
            "sort_order": "digest_ascending_then_canonical_identity_ascending",
            "result_independent": True,
            "metadata_only": True,
        },
        "exclusions": {
            "a1_formal_manifest_sha256": A1_HASH,
            "development_v1_manifest_sha256": DEVELOPMENT_V1_HASH,
            "second_holdout_manifest_sha256": SECOND_HOLDOUT_HASH,
            "combined_identity_count": len(excluded),
        },
    }
    selection_spec["selection_spec_sha256"] = sha256_bytes(canonical_json(selection_spec).encode("utf-8"))
    source_records = _source_snapshot_records(provenance)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "universe_version": UNIVERSE_VERSION,
        "status": "ATR_BOUNDARY_CLEAN_HOLDOUT_UNIVERSE_FROZEN_NOT_ACQUIRED",
        "artifact_labels": list(LABELS),
        "frozen_at": frozen_at,
        "protocol": {"version": PROTOCOL_VERSION, "sha256": protocol["integrity"]["protocol_sha256"]},
        "parent_source_bundle": {
            "path": str(A1_SNAPSHOT_DIR.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "source_snapshot_identities": source_records,
            "identity": sha256_bytes(canonical_json(source_records).encode("utf-8")),
        },
        "exclusions": {
            "a1_formal": {"manifest_sha256": A1_HASH, "count": len(formal_ids)},
            "development_v1": {"manifest_sha256": DEVELOPMENT_V1_HASH, "count": len(dev_ids)},
            "second_development_holdout": {"manifest_sha256": SECOND_HOLDOUT_HASH, "count": len(second_ids)},
        },
        "selection_spec": selection_spec,
        "candidate_pool_after_exclusions": {"CN": cn_pool, "US": us_pool},
        "exclusion_proofs": {
            name: {"intersection": value, "intersection_count": len(value), "intersection_is_empty": not bool(value)}
            for name, value in proofs.items()
        },
        "counts": dict(TARGET_COUNTS),
        "symbols": symbols,
        "symbol_list_sha256": symbol_list_hash(symbols),
        "controls": {
            "historical_ohlcv_accessed": False,
            "setup03_output_accessed": False,
            "event_or_signal_output_accessed": False,
            "outcome_metrics_accessed": False,
            "final_oos_accessed": False,
            "selection_precedes_ohlcv": True,
            "result_driven_ranking_or_replacement_allowed": False,
        },
    }
    manifest["integrity"] = {"manifest_sha256": manifest_integrity_hash(manifest)}
    return manifest


def validate_universe_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("universe_version") != UNIVERSE_VERSION:
        raise ValueError("ATR boundary clean holdout identity changed")
    if tuple(manifest.get("artifact_labels", ())) != LABELS:
        raise ValueError("ATR clean holdout labels changed")
    if manifest.get("integrity", {}).get("manifest_sha256") != manifest_integrity_hash(manifest):
        raise ValueError("ATR clean holdout integrity mismatch")
    if manifest.get("counts") != TARGET_COUNTS or manifest.get("symbol_list_sha256") != symbol_list_hash(manifest["symbols"]):
        raise ValueError("ATR clean holdout counts or symbol hash changed")
    if manifest.get("protocol", {}).get("version") != PROTOCOL_VERSION:
        raise ValueError("ATR clean holdout protocol binding changed")
    if any(proof.get("intersection") for proof in manifest.get("exclusion_proofs", {}).values()):
        raise ValueError("ATR clean holdout exclusion proof failed")
    controls = manifest.get("controls", {})
    if controls.get("selection_precedes_ohlcv") is not True or controls.get("result_driven_ranking_or_replacement_allowed") is not False:
        raise ValueError("ATR clean holdout selection controls weakened")


def load_universe_manifest(path: Path = UNIVERSE_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_universe_manifest(manifest)
    return manifest


def write_universe_manifest(path: Path = UNIVERSE_PATH) -> dict[str, Any]:
    manifest = build_universe_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


__all__ = ["FIXED_SEED", "LABELS", "TARGET_COUNTS", "UNIVERSE_PATH", "UNIVERSE_VERSION", "build_universe_manifest", "load_universe_manifest", "manifest_integrity_hash", "symbol_list_hash", "validate_universe_manifest", "write_universe_manifest"]

"""Acquire and freeze the second development holdout dataset.

The selected holdout universe is immutable before this module is called.  CN
uses BaoStock qfq and US uses yfinance adjusted historical data.  Provider or
QC failures remain in the manifest and prevent replay; no fallback, date
filling, symbol replacement, or signal-driven action is allowed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from core import Quote
from research.development_dataset import (
    BAOSTOCK_REQUEST_METHOD,
    BAOSTOCK_WIRE_FIELDS,
    CN_DEVELOPMENT_ADJUSTMENT_MODE,
    CN_DEVELOPMENT_PROVIDER_ID,
    DEVELOPMENT_ADJUSTMENT_MODE,
    DEVELOPMENT_PROVIDER_ID,
    DevelopmentDataError,
    NUMERICAL_ORDERING_COMPARISON,
    acquire_symbol,
    baostock_wire_symbol,
    close_baostock_session,
    fetch_baostock_frame,
    fetch_yfinance_frame,
    sha256_bytes,
    _normalized_hash,
)
from research.replay_input import build_input_manifest, read_frozen_input, write_frozen_input
from research.development_holdout_universe import (
    HOLDOUT_LABELS,
    HOLDOUT_UNIVERSE_PATH,
    PINNED_A1_MANIFEST_SHA256,
    PINNED_DEVELOPMENT_V1_MANIFEST_SHA256,
    PINNED_HOLDOUT_UNIVERSE_MANIFEST_SHA256,
    load_holdout_universe_manifest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOLDOUT_ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "phase5j_v3_development_holdout"
DATASET_MANIFEST_PATH = HOLDOUT_ARTIFACT_DIR / "development_holdout_dataset_manifest.json"
REPLAY_MANIFEST_PATH = HOLDOUT_ARTIFACT_DIR / "development_holdout_replay_manifest.json"
FROZEN_INPUT_PATH = HOLDOUT_ARTIFACT_DIR / "development_holdout_replay_input.jsonl.gz"
DATASET_SCHEMA_VERSION = "setup03-phase5j-v3-development-holdout-dataset-manifest-v1"
DATASET_VERSION = "SETUP_03-DEVELOPMENT-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1"
REPLAY_MANIFEST_SCHEMA_VERSION = "setup03-phase5j-v3-development-holdout-replay-manifest-v1"
DATASET_STATUS = "DEVELOPMENT_HOLDOUT_DATASET_FROZEN_NOT_FORMAL_VALIDATION"
READY_STATUS = "DEVELOPMENT_HOLDOUT_READY_FOR_V3_REPLAY"
BLOCKER_STATUS = "DEVELOPMENT_HOLDOUT_PROVIDER_OR_QC_BLOCKER_FAIL_CLOSED"
START_DATE = date(2017, 1, 1)
END_DATE = date(2026, 8, 26)
REQUIRED_SYMBOLS_BY_MARKET = {"CN": 20, "US": 20}
EXPECTED_HOLDOUT_SYMBOL_COUNT = 40
EXPECTED_HOLDOUT_BAR_COUNT = 86305


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def dataset_manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(manifest))
    payload.pop("integrity", None)
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _aggregate_dataset_hash(rows_by_symbol: Mapping[str, tuple[dict[str, Any], ...]]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{DATASET_SCHEMA_VERSION}\n".encode("utf-8"))
    for symbol in sorted(rows_by_symbol):
        digest.update(f"{symbol}\n".encode("utf-8"))
        for row in rows_by_symbol[symbol]:
            hashed = dict(row)
            for field in ("open", "high", "low", "close", "volume"):
                hashed[field] = float(row[field]).hex()
            digest.update(canonical_json(hashed).encode("utf-8"))
            digest.update(b"\n")
    return sha256_bytes(digest.digest())


def _source_records(universe: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(universe["source_snapshot_bundle"]["source_snapshot_identities"])


def _request_contract(row: Mapping[str, Any]) -> tuple[str, str, Callable[..., Any], dict[str, Any], dict[str, Any]]:
    market = str(row["market"])
    if market == "CN":
        return (
            CN_DEVELOPMENT_PROVIDER_ID,
            CN_DEVELOPMENT_ADJUSTMENT_MODE,
            fetch_baostock_frame,
            {
                "method": BAOSTOCK_REQUEST_METHOD,
                "wire_symbol": baostock_wire_symbol(str(row["canonical_symbol"])),
                "fields": list(BAOSTOCK_WIRE_FIELDS),
                "start_date": START_DATE.isoformat(),
                "end_date": END_DATE.isoformat(),
                "frequency": "d",
                "adjustflag": "2",
                "local_trading_date_timezone": "Asia/Shanghai",
            },
            {**NUMERICAL_ORDERING_COMPARISON, "enabled": False},
        )
    if market == "US":
        return (
            DEVELOPMENT_PROVIDER_ID,
            DEVELOPMENT_ADJUSTMENT_MODE,
            fetch_yfinance_frame,
            {
                "method": "yfinance.Ticker.history",
                "symbol": str(row["yfinance_symbol"]),
                "start": START_DATE.isoformat(),
                "end": END_DATE.isoformat(),
                "end_wire_is_exclusive": True,
                "interval": "1d",
                "auto_adjust": True,
                "actions": False,
                "repair": False,
                "local_trading_date_timezone": "America/New_York",
            },
            {**NUMERICAL_ORDERING_COMPARISON, "enabled": True},
        )
    raise DevelopmentDataError(f"unsupported development holdout market: {market}")


def build_dataset_manifest(
    universe: Mapping[str, Any],
    acquired: list[Any],
    *,
    replay_manifest_hash: str | None = None,
    frozen_at: str = "2026-08-29",
) -> tuple[dict[str, Any], dict[str, list[Quote]], dict[str, tuple[dict[str, Any], ...]]]:
    rows = [item.dataset_row for item in acquired]
    valid = [item for item in acquired if item.dataset_row["qc_status"] == "VALID_ACCEPTED"]
    symbol_quotes = {
        item.manifest_row["canonical_symbol"]: list(item.quotes)
        for item in valid
    }
    normalized_by_symbol = {
        item.manifest_row["canonical_symbol"]: item.normalized_rows
        for item in valid
    }
    valid_by_market = {
        market: sum(item.dataset_row["qc_status"] == "VALID_ACCEPTED" and item.manifest_row["market"] == market for item in acquired)
        for market in ("CN", "US")
    }
    coverage_ok = all(valid_by_market[market] == required for market, required in REQUIRED_SYMBOLS_BY_MARKET.items()) and len(valid) == 40
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "status": DATASET_STATUS,
        "coverage_status": READY_STATUS if coverage_ok else BLOCKER_STATUS,
        "artifact_labels": list(HOLDOUT_LABELS),
        "frozen_at": frozen_at,
        "universe": {
            "universe_version": universe["universe_version"],
            "symbol_list_sha256": universe["symbol_list_sha256"],
            "manifest_sha256": universe["integrity"]["manifest_sha256"],
        },
        "protocol": {
            "version": "SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1",
            "sha256": "sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816",
        },
        "formal_exclusions": {
            "a1_manifest_sha256": PINNED_A1_MANIFEST_SHA256,
            "development_v1_manifest_sha256": PINNED_DEVELOPMENT_V1_MANIFEST_SHA256,
            "a1_intersection": universe["exclusion_proofs"]["a1_formal_120"]["intersection"],
            "development_v1_intersection": universe["exclusion_proofs"]["development_v1_40"]["intersection"],
        },
        "source_snapshot_identities": _source_records(universe),
        "provider_split": {
            "CN": CN_DEVELOPMENT_PROVIDER_ID,
            "US": DEVELOPMENT_PROVIDER_ID,
        },
        "provider_contract": {
            "CN": {
                "provider_id": CN_DEVELOPMENT_PROVIDER_ID,
                "query_method": BAOSTOCK_REQUEST_METHOD,
                "wire_fields": list(BAOSTOCK_WIRE_FIELDS),
                "frequency": "d",
                "adjustflag": "2",
                "adjustment_mode": CN_DEVELOPMENT_ADJUSTMENT_MODE,
                "date_window": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat(), "inclusive": True},
                "local_trading_date_timezone": "Asia/Shanghai",
            },
            "US": {
                "provider_id": DEVELOPMENT_PROVIDER_ID,
                "query_method": "yfinance.Ticker.history",
                "adjusted_historical": True,
                "auto_adjust": True,
                "repair": False,
                "date_window": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat(), "inclusive": True},
                "local_trading_date_timezone": "America/New_York",
            },
        },
        "qc_contract": {
            "missing_dates": "NOT_INFERRED_NO_FILL",
            "interpolation": False,
            "synthetic_suspension_bars": False,
            "history_splice": False,
            "provider_switching": False,
            "result_driven_symbol_replacement": False,
            "ohlc_mutation": False,
            "ieee754_ulp_tolerance": "QC comparison only; no clip, round, or mutation",
            "baostock_blank_activity": "existing valid equal-OHLC row only may normalize volume=0; no new bar",
        },
        "symbols": rows,
        "market_coverage": {
            market: {
                "selected": REQUIRED_SYMBOLS_BY_MARKET[market],
                "valid_accepted": valid_by_market[market],
                "valid_bar_count": sum(row["bar_count"] for row in rows if row["market"] == market and row["qc_status"] == "VALID_ACCEPTED"),
            }
            for market in ("CN", "US")
        },
        "aggregate_symbol_count": len(valid),
        "aggregate_valid_bar_count": sum(row["bar_count"] for row in rows if row["qc_status"] == "VALID_ACCEPTED"),
        "aggregate_dataset_sha256": _aggregate_dataset_hash(normalized_by_symbol),
        "replay_input_manifest_sha256": replay_manifest_hash,
        "provider_qc_exceptions": [
            {
                "market": row["market"],
                "canonical_symbol": row["canonical_symbol"],
                "provider_id": row["provider_id"],
                "status": row["qc_status"],
                "reason": row["qc_reason"],
            }
            for row in rows if row["qc_status"] != "VALID_ACCEPTED"
        ],
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "ibkr_used": False,
            "setup03_accessed_before_freeze": False,
            "result_driven_provider_or_symbol_switch": False,
        },
    }
    manifest["integrity"] = {"manifest_sha256": dataset_manifest_integrity_hash(manifest)}
    return manifest, symbol_quotes, normalized_by_symbol


def validate_dataset_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != DATASET_SCHEMA_VERSION or manifest.get("dataset_version") != DATASET_VERSION:
        raise ValueError("holdout dataset identity changed")
    if tuple(manifest.get("artifact_labels", ())) != HOLDOUT_LABELS:
        raise ValueError("holdout dataset labels changed")
    if manifest.get("status") != DATASET_STATUS:
        raise ValueError("holdout dataset status changed")
    if manifest.get("integrity", {}).get("manifest_sha256") != dataset_manifest_integrity_hash(manifest):
        raise ValueError("holdout dataset integrity mismatch")
    if manifest.get("universe", {}).get("manifest_sha256") != PINNED_HOLDOUT_UNIVERSE_MANIFEST_SHA256:
        raise ValueError("holdout universe binding changed")
    if manifest.get("provider_split") != {"CN": CN_DEVELOPMENT_PROVIDER_ID, "US": DEVELOPMENT_PROVIDER_ID}:
        raise ValueError("holdout provider split changed")
    if manifest.get("formal_exclusions", {}).get("a1_intersection") != [] or manifest.get("formal_exclusions", {}).get("development_v1_intersection") != []:
        raise ValueError("holdout exclusion proof changed")
    if manifest.get("controls", {}).get("result_driven_provider_or_symbol_switch"):
        raise ValueError("result-driven provider or symbol switch is prohibited")


def load_dataset_manifest(path: Path = DATASET_MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_dataset_manifest(manifest)
    return manifest


def validate_replay_manifest(
    replay_wrapper: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    replay_input_manifest: Any | None = None,
) -> None:
    """Validate the one-way dataset -> replay wrapper freeze bindings."""
    if replay_wrapper.get("schema_version") != REPLAY_MANIFEST_SCHEMA_VERSION:
        raise ValueError("holdout replay wrapper schema changed")
    if replay_wrapper.get("dataset_version") != DATASET_VERSION:
        raise ValueError("holdout replay wrapper dataset identity changed")
    if replay_wrapper.get("dataset_manifest_sha256") != dataset_manifest.get("integrity", {}).get("manifest_sha256"):
        raise ValueError("holdout replay wrapper dataset binding changed")
    if replay_wrapper.get("integrity", {}).get("manifest_sha256") != dataset_manifest_integrity_hash(replay_wrapper):
        raise ValueError("holdout replay wrapper integrity mismatch")
    if replay_wrapper.get("controls") != {
        "development_only": True,
        "formal_validation": False,
        "final_oos_accessed": False,
        "provider_split": {"CN": CN_DEVELOPMENT_PROVIDER_ID, "US": DEVELOPMENT_PROVIDER_ID},
    }:
        raise ValueError("holdout replay wrapper controls changed")

    embedded_replay = replay_wrapper.get("replay_manifest")
    if not isinstance(embedded_replay, Mapping):
        raise ValueError("holdout replay wrapper is missing its replay manifest")
    if embedded_replay.get("aggregate_hash") != dataset_manifest.get("replay_input_manifest_sha256"):
        raise ValueError("holdout replay wrapper replay aggregate binding changed")
    if int(embedded_replay.get("total_symbol_count", -1)) != EXPECTED_HOLDOUT_SYMBOL_COUNT:
        raise ValueError("holdout replay wrapper symbol count changed")
    if int(embedded_replay.get("total_bar_count", -1)) != EXPECTED_HOLDOUT_BAR_COUNT:
        raise ValueError("holdout replay wrapper bar count changed")
    if dataset_manifest.get("aggregate_symbol_count") != EXPECTED_HOLDOUT_SYMBOL_COUNT:
        raise ValueError("holdout dataset symbol count changed")
    if dataset_manifest.get("aggregate_valid_bar_count") != EXPECTED_HOLDOUT_BAR_COUNT:
        raise ValueError("holdout dataset bar count changed")
    if replay_input_manifest is not None and embedded_replay != replay_input_manifest.to_dict():
        raise ValueError("holdout replay wrapper does not match frozen replay input")


def _write_replay_manifest(path: Path, dataset_manifest: Mapping[str, Any], replay_manifest: Any) -> None:
    if dataset_manifest.get("coverage_status") != READY_STATUS:
        raise ValueError("cannot write a replay wrapper for a non-ready dataset")
    if dataset_manifest.get("replay_input_manifest_sha256") != replay_manifest.aggregate_hash:
        raise ValueError("final dataset manifest must bind the replay input before writing its wrapper")
    payload = {
        "schema_version": REPLAY_MANIFEST_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "dataset_manifest_sha256": dataset_manifest["integrity"]["manifest_sha256"],
        "replay_manifest": replay_manifest.to_dict(),
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "provider_split": {"CN": CN_DEVELOPMENT_PROVIDER_ID, "US": DEVELOPMENT_PROVIDER_ID},
        },
    }
    payload["integrity"] = {"manifest_sha256": dataset_manifest_integrity_hash(payload)}
    validate_replay_manifest(payload, dataset_manifest, replay_manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def acquire_and_freeze_holdout(
    universe_path: Path = HOLDOUT_UNIVERSE_PATH,
    output_dir: Path = HOLDOUT_ARTIFACT_DIR,
    *,
    fetcher: Callable[[str, date, date], tuple[Any, bytes]] | None = None,
) -> tuple[dict[str, Any], dict[str, list[Quote]]]:
    universe = load_holdout_universe_manifest(universe_path)
    acquired: list[Any] = []
    raw_dir_by_market = {"CN": output_dir / "raw_baostock", "US": output_dir / "raw_yfinance"}
    normalized_dir = output_dir / "normalized_bars"
    try:
        for row in universe["symbols"]:
            provider_id, adjustment_mode, default_fetcher, request_contract, numeric_rule = _request_contract(row)
            acquired.append(
                acquire_symbol(
                    row,
                    raw_dir=raw_dir_by_market[row["market"]],
                    normalized_dir=normalized_dir,
                    fetcher=fetcher or default_fetcher,
                    provider_id=provider_id,
                    adjustment_mode=adjustment_mode,
                    request_contract=request_contract,
                    numeric_ordering_rule=numeric_rule,
                )
            )
    finally:
        close_baostock_session()

    provisional, symbol_quotes, _ = build_dataset_manifest(universe, acquired)
    output_dir.mkdir(parents=True, exist_ok=True)
    if provisional["coverage_status"] != READY_STATUS:
        path = output_dir / "development_holdout_dataset_manifest.json"
        path.write_text(json.dumps(provisional, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return provisional, symbol_quotes

    replay_manifest = build_input_manifest(symbol_quotes)
    frozen_manifest = write_frozen_input(output_dir / FROZEN_INPUT_PATH.name, symbol_quotes)
    if frozen_manifest != replay_manifest:
        raise ValueError("holdout replay input changed during serialization")
    manifest, symbol_quotes, _ = build_dataset_manifest(
        universe, acquired, replay_manifest_hash=replay_manifest.aggregate_hash
    )
    (output_dir / DATASET_MANIFEST_PATH.name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_replay_manifest(output_dir / REPLAY_MANIFEST_PATH.name, manifest, replay_manifest)
    return manifest, symbol_quotes


def load_frozen_holdout(
    manifest_path: Path = DATASET_MANIFEST_PATH,
    replay_input_path: Path = FROZEN_INPUT_PATH,
    replay_manifest_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, list[Quote]], Any]:
    manifest = load_dataset_manifest(manifest_path)
    if manifest["coverage_status"] != READY_STATUS:
        raise DevelopmentDataError(f"holdout dataset is not replay-ready: {manifest['coverage_status']}")
    symbol_quotes, replay_manifest = read_frozen_input(replay_input_path)
    wrapper_path = replay_manifest_path or manifest_path.with_name(REPLAY_MANIFEST_PATH.name)
    replay_wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    validate_replay_manifest(replay_wrapper, manifest, replay_manifest)
    if manifest.get("replay_input_manifest_sha256") != replay_manifest.aggregate_hash:
        raise ValueError("holdout replay input manifest hash changed")
    if replay_manifest.total_symbol_count != EXPECTED_HOLDOUT_SYMBOL_COUNT:
        raise ValueError("holdout replay symbol count changed")
    if replay_manifest.total_bar_count != EXPECTED_HOLDOUT_BAR_COUNT:
        raise ValueError("holdout replay bar count changed")
    return manifest, symbol_quotes, replay_manifest


__all__ = [
    "BLOCKER_STATUS", "DATASET_MANIFEST_PATH", "DATASET_STATUS", "DATASET_VERSION",
    "FROZEN_INPUT_PATH", "HOLDOUT_ARTIFACT_DIR", "READY_STATUS", "REPLAY_MANIFEST_PATH",
    "acquire_and_freeze_holdout", "build_dataset_manifest", "load_dataset_manifest",
    "load_frozen_holdout", "validate_dataset_manifest", "validate_replay_manifest",
]

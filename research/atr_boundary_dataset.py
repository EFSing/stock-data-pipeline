"""Acquire and freeze the final independent development holdout for ATR research.

This module is deliberately separate from the historical Phase 5J-v3 holdout.
The roster and protocol are loaded and validated before any provider call.  The
existing development acquisition/QC implementation is reused; no provider
fallback, date fill, synthetic bar, signal-driven replacement, or outcome
calculation is performed here.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from core import Quote
from research.atr_boundary_protocol import PROTOCOL_VERSION, load_protocol
from research.atr_boundary_universe import load_universe_manifest
from research.development_dataset import (
    BAOSTOCK_REQUEST_METHOD,
    BAOSTOCK_WIRE_FIELDS,
    CN_DEVELOPMENT_ADJUSTMENT_MODE,
    CN_DEVELOPMENT_PROVIDER_ID,
    DEVELOPMENT_ADJUSTMENT_MODE,
    DEVELOPMENT_PROVIDER_ID,
    DevelopmentDataError,
    NUMERICAL_ORDERING_COMPARISON,
    START_DATE,
    END_DATE,
    acquire_symbol,
    baostock_wire_symbol,
    close_baostock_session,
    fetch_baostock_frame,
    fetch_yfinance_frame,
    sha256_bytes,
)
from research.replay_input import build_input_manifest, write_frozen_input


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "atr_boundary_clean_holdout"
RESEARCH_MANIFEST_DIR = PROJECT_ROOT / "research" / "atr_boundary_clean_holdout"
DATASET_MANIFEST_PATH = RESEARCH_MANIFEST_DIR / "dataset_manifest.json"
REPLAY_MANIFEST_PATH = RESEARCH_MANIFEST_DIR / "replay_manifest.json"
FROZEN_INPUT_PATH = ARTIFACT_DIR / "replay_input.jsonl.gz"
DATASET_SCHEMA_VERSION = "setup03-atr-boundary-clean-holdout-dataset-v1"
REPLAY_WRAPPER_SCHEMA_VERSION = "setup03-atr-boundary-clean-holdout-replay-manifest-v1"
DATASET_VERSION = "SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1"
DATASET_STATUS = "ATR_BOUNDARY_CLEAN_HOLDOUT_DATASET_FROZEN_NOT_FORMAL_VALIDATION"
READY_STATUS = "READY_FOR_ATR_BOUNDARY_STRUCTURE_ONLY"
BLOCKER_STATUS = "ATR_BOUNDARY_CLEAN_HOLDOUT_PROVIDER_OR_QC_BLOCKER_FAIL_CLOSED"
LABELS = ("DEVELOPMENT_ONLY", "NOT_FORMAL_VALIDATION", "NOT_FINAL_OOS")
EXPECTED_COUNTS = {"CN": 20, "US": 20, "total": 40}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("integrity", None)
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _aggregate_normalized_hash(rows_by_symbol: Mapping[str, tuple[dict[str, Any], ...]]) -> str:
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


def _artifact_path(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


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
    raise DevelopmentDataError(f"unsupported ATR boundary holdout market: {market}")


def _source_records(universe: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(universe["parent_source_bundle"]["source_snapshot_identities"])


def _build_dataset_manifest(
    universe: Mapping[str, Any],
    acquired: list[Any],
    *,
    replay_manifest_hash: str | None = None,
    frozen_at: str = "2026-08-29",
) -> tuple[dict[str, Any], dict[str, list[Quote]]]:
    rows = [item.dataset_row for item in acquired]
    valid = [item for item in acquired if item.dataset_row["qc_status"] == "VALID_ACCEPTED"]
    valid_by_market = {
        market: sum(
            item.dataset_row["qc_status"] == "VALID_ACCEPTED"
            and item.manifest_row["market"] == market
            for item in acquired
        )
        for market in ("CN", "US")
    }
    coverage_ok = valid_by_market == {"CN": 20, "US": 20} and len(valid) == 40
    symbol_quotes = {
        item.manifest_row["canonical_symbol"]: list(item.quotes)
        for item in valid
    }
    normalized_by_symbol = {
        item.manifest_row["canonical_symbol"]: item.normalized_rows
        for item in valid
    }
    protocol = load_protocol()
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "status": DATASET_STATUS,
        "coverage_status": READY_STATUS if coverage_ok else BLOCKER_STATUS,
        "artifact_labels": list(LABELS),
        "frozen_at": frozen_at,
        "protocol": {"version": PROTOCOL_VERSION, "sha256": protocol["integrity"]["protocol_sha256"]},
        "universe": {
            "universe_version": universe["universe_version"],
            "symbol_list_sha256": universe["symbol_list_sha256"],
            "manifest_sha256": universe["integrity"]["manifest_sha256"],
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
                "actions": False,
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
                "selected": EXPECTED_COUNTS[market],
                "valid_accepted": valid_by_market[market],
                "valid_bar_count": sum(
                    row["bar_count"]
                    for row in rows
                    if row["market"] == market and row["qc_status"] == "VALID_ACCEPTED"
                ),
            }
            for market in ("CN", "US")
        },
        "aggregate_symbol_count": len(valid),
        "aggregate_valid_bar_count": sum(
            row["bar_count"] for row in rows if row["qc_status"] == "VALID_ACCEPTED"
        ),
        "aggregate_normalized_sha256": _aggregate_normalized_hash(normalized_by_symbol),
        "replay_input_manifest_sha256": replay_manifest_hash,
        "provider_qc_exceptions": [
            {
                "market": row["market"],
                "canonical_symbol": row["canonical_symbol"],
                "provider_id": row["provider_id"],
                "status": row["qc_status"],
                "reason": row["qc_reason"],
            }
            for row in rows
            if row["qc_status"] != "VALID_ACCEPTED"
        ],
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "outcome_metrics_accessed": False,
            "ibkr_used": False,
            "setup03_accessed_before_universe_freeze": False,
            "result_driven_provider_or_symbol_switch": False,
        },
    }
    manifest["integrity"] = {"manifest_sha256": manifest_integrity_hash(manifest)}
    return manifest, symbol_quotes


def _write_replay_wrapper(
    manifest: Mapping[str, Any],
    replay_manifest: Any,
    path: Path,
) -> None:
    if manifest["coverage_status"] != READY_STATUS:
        raise ValueError("cannot write replay wrapper for a non-ready dataset")
    if manifest["replay_input_manifest_sha256"] != replay_manifest.aggregate_hash:
        raise ValueError("dataset must bind replay input before writing wrapper")
    payload = {
        "schema_version": REPLAY_WRAPPER_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "dataset_manifest_sha256": manifest["integrity"]["manifest_sha256"],
        "replay_manifest": replay_manifest.to_dict(),
        "controls": {
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "outcome_metrics_accessed": False,
            "provider_split": {"CN": CN_DEVELOPMENT_PROVIDER_ID, "US": DEVELOPMENT_PROVIDER_ID},
        },
    }
    payload["integrity"] = {"manifest_sha256": manifest_integrity_hash(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def acquire_and_freeze(
    *,
    universe_path: Path | None = None,
    artifact_dir: Path = ARTIFACT_DIR,
    dataset_manifest_path: Path = DATASET_MANIFEST_PATH,
    replay_manifest_path: Path = REPLAY_MANIFEST_PATH,
    frozen_input_path: Path = FROZEN_INPUT_PATH,
    fetcher: Callable[..., Any] | None = None,
    progress: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fetch every frozen roster row and write a ready or blocker manifest."""
    universe = load_universe_manifest(universe_path) if universe_path else load_universe_manifest()
    acquired: list[Any] = []
    raw_dirs = {"CN": artifact_dir / "raw_baostock", "US": artifact_dir / "raw_yfinance"}
    normalized_dir = artifact_dir / "normalized_bars"
    try:
        for row in universe["symbols"]:
            provider_id, adjustment_mode, default_fetcher, request_contract, numeric_rule = _request_contract(row)
            acquired_symbol = acquire_symbol(
                row,
                raw_dir=raw_dirs[row["market"]],
                normalized_dir=normalized_dir,
                fetcher=fetcher or default_fetcher,
                provider_id=provider_id,
                adjustment_mode=adjustment_mode,
                request_contract=request_contract,
                numeric_ordering_rule=numeric_rule,
            )
            acquired.append(acquired_symbol)
            if progress is not None:
                progress(acquired_symbol.dataset_row)
    finally:
        close_baostock_session()

    provisional, symbol_quotes = _build_dataset_manifest(universe, acquired)
    dataset_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if provisional["coverage_status"] != READY_STATUS:
        dataset_manifest_path.write_text(json.dumps(provisional, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return provisional

    replay_manifest = build_input_manifest(symbol_quotes)
    serialized_manifest = write_frozen_input(frozen_input_path, symbol_quotes)
    if serialized_manifest != replay_manifest:
        raise ValueError("replay input changed during serialization")
    manifest, _ = _build_dataset_manifest(
        universe,
        acquired,
        replay_manifest_hash=replay_manifest.aggregate_hash,
    )
    dataset_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_replay_wrapper(manifest, replay_manifest, replay_manifest_path)
    return manifest


__all__ = [
    "ARTIFACT_DIR",
    "BLOCKER_STATUS",
    "DATASET_MANIFEST_PATH",
    "DATASET_STATUS",
    "DATASET_VERSION",
    "FROZEN_INPUT_PATH",
    "READY_STATUS",
    "REPLAY_MANIFEST_PATH",
    "acquire_and_freeze",
    "canonical_json",
    "manifest_integrity_hash",
]

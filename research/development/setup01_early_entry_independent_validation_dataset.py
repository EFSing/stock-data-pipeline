"""Freeze the independent CN/US sample for the SETUP_01 earlier-entry validation.

The roster and provider contract are validated before any provider call.  The
module reuses the existing development acquisition/QC/normalization primitives
and writes a *new* dataset identity; it never writes into the frozen Phase
5J-v3 development holdout or the frozen ATR clean-holdout directories.

The sample universe is the already frozen clean-holdout roster
``SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-CN-US-2026-08-29-v1``, whose tracked
manifest proves empty intersections with the A1 formal 120, the earlier
development universe v1 and the second development holdout used by the
SETUP_01/02 research.  Only the roster (metadata) is reused; the price payload
is re-acquired under the same frozen provider contract and re-frozen with its
own hashes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from core import Quote
from research.atr_boundary_universe import (
    UNIVERSE_PATH,
    UNIVERSE_VERSION,
    load_universe_manifest,
)
from research.development_dataset import (
    BAOSTOCK_REQUEST_METHOD,
    BAOSTOCK_WIRE_FIELDS,
    CN_DEVELOPMENT_ADJUSTMENT_MODE,
    CN_DEVELOPMENT_PROVIDER_ID,
    DEVELOPMENT_ADJUSTMENT_MODE,
    DEVELOPMENT_PROVIDER_ID,
    NUMERICAL_ORDERING_COMPARISON,
    _normalized_hash,
    acquire_symbol,
    baostock_wire_symbol,
    close_baostock_session,
    fetch_baostock_frame,
    fetch_yfinance_frame,
    sha256_bytes,
)
from research.replay_input import build_input_manifest, read_frozen_input, write_frozen_input


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "setup01_early_entry_independent_validation_v1"
MANIFEST_DIR = PROJECT_ROOT / "research" / "early_entry_validation_sample"
DATASET_MANIFEST_PATH = MANIFEST_DIR / "dataset_manifest.json"
REPLAY_MANIFEST_PATH = MANIFEST_DIR / "replay_manifest.json"
FROZEN_INPUT_PATH = ARTIFACT_DIR / "independent_validation_replay_input.jsonl.gz"
DATASET_SCHEMA_VERSION = "setup01-early-entry-independent-validation-dataset-v1"
DATASET_VERSION = (
    "SETUP01-EARLY-ENTRY-INDEPENDENT-VALIDATION-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-09-24-v1"
)
DATASET_STATUS = "INDEPENDENT_VALIDATION_DATASET_FROZEN_NOT_FORMAL_VALIDATION"
READY_STATUS = "READY_FOR_SETUP01_EARLY_ENTRY_FIRST_STAGE"
BLOCKER_STATUS = "INDEPENDENT_VALIDATION_PROVIDER_OR_QC_BLOCKER_FAIL_CLOSED"
LABELS = ("INDEPENDENT_VALIDATION_SAMPLE", "NOT_FORMAL_VALIDATION", "NOT_FINAL_OOS")
START_DATE = date(2017, 1, 1)
END_DATE = date(2026, 8, 26)
EXPECTED_COUNTS = {"CN": 20, "US": 20, "total": 40}
PINNED_UNIVERSE_MANIFEST_SHA256 = "sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b"
PINNED_UNIVERSE_SYMBOL_LIST_SHA256 = "sha256:a00cdd73e6976546df43ea92a6e5e48f64124af974ff20c7812ee6c350399e58"
FROZEN_ATR_DATASET_MANIFEST_PATH = (
    PROJECT_ROOT / "research" / "atr_boundary_clean_holdout" / "dataset_manifest.json"
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(manifest))
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
    raise ValueError(f"unsupported independent validation market: {market}")


def recovery_check(rows: list[Mapping[str, Any]], reference_path: Path | None = None) -> dict[str, Any]:
    """Compare re-acquired payload hashes with the frozen 2026-08-29 clean holdout.

    This is an informational consistency check only: a mismatch is recorded, never
    substituted, and never silently rendered as the frozen clean-holdout identity.
    """
    path = reference_path or FROZEN_ATR_DATASET_MANIFEST_PATH
    if not path.exists():
        return {"reference": _artifact_path(path), "status": "REFERENCE_MANIFEST_UNAVAILABLE", "symbols": []}
    reference = json.loads(path.read_text(encoding="utf-8"))
    known = {
        str(item["canonical_symbol"]): item
        for item in reference.get("symbols", ())
    }
    comparisons = []
    for row in rows:
        symbol = str(row["canonical_symbol"])
        prior = known.get(symbol)
        comparisons.append(
            {
                "canonical_symbol": symbol,
                "market": row["market"],
                "reference_manifest_present": prior is not None,
                "normalized_data_sha256_match": bool(
                    prior and prior.get("normalized_data_sha256") == row.get("normalized_data_sha256")
                ),
                "bar_count_match": bool(prior and prior.get("bar_count") == row.get("bar_count")),
                "reference_normalized_data_sha256": prior.get("normalized_data_sha256") if prior else None,
                "acquired_normalized_data_sha256": row.get("normalized_data_sha256"),
            }
        )
    matched = sum(
        item["normalized_data_sha256_match"] and item["bar_count_match"] for item in comparisons
    )
    return {
        "reference": _artifact_path(path),
        "reference_dataset_version": reference.get("dataset_version"),
        "status": (
            "PAYLOAD_CONSISTENT_WITH_FROZEN_CLEAN_HOLDOUT"
            if matched == len(comparisons) and comparisons
            else "PAYLOAD_DIFFERS_FROM_FROZEN_CLEAN_HOLDOUT"
        ),
        "matched_symbol_count": matched,
        "compared_symbol_count": len(comparisons),
        "symbols": comparisons,
    }


def _build_dataset_manifest(
    universe: Mapping[str, Any],
    acquired: list[Any],
    *,
    replay_manifest_hash: str | None = None,
    frozen_at: str = "2026-09-24",
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
    coverage_ok = valid_by_market == {"CN": 20, "US": 20} and len(valid) == EXPECTED_COUNTS["total"]
    symbol_quotes = {item.manifest_row["canonical_symbol"]: list(item.quotes) for item in valid}
    normalized_by_symbol = {
        item.manifest_row["canonical_symbol"]: item.normalized_rows for item in valid
    }
    manifest = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "dataset_version": DATASET_VERSION,
        "status": DATASET_STATUS,
        "coverage_status": READY_STATUS if coverage_ok else BLOCKER_STATUS,
        "artifact_labels": list(LABELS),
        "frozen_at": frozen_at,
        "universe": {
            "universe_version": UNIVERSE_VERSION,
            "universe_manifest_path": _artifact_path(UNIVERSE_PATH),
            "manifest_sha256": universe["integrity"]["manifest_sha256"],
            "symbol_list_sha256": universe["symbol_list_sha256"],
            "exclusion_proofs": {
                name: proof["intersection_count"]
                for name, proof in universe["exclusion_proofs"].items()
            },
        },
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
            "independent_validation_sample": True,
            "reused_for_development_research": False,
            "formal_validation": False,
            "final_oos_accessed": False,
            "outcome_metrics_accessed": False,
            "signal_computed_before_freeze": False,
            "result_driven_provider_or_symbol_switch": False,
        },
    }
    manifest["integrity"] = {"manifest_sha256": manifest_integrity_hash(manifest)}
    return manifest, symbol_quotes


def _recovery_rows(acquired: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "market": item.manifest_row["market"],
            "canonical_symbol": item.manifest_row["canonical_symbol"],
            "normalized_data_sha256": item.dataset_row.get("normalized_data_sha256"),
            "bar_count": item.dataset_row.get("bar_count"),
        }
        for item in acquired
    ]


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
    """Fetch every frozen roster row once and freeze the resulting sample."""
    universe = load_universe_manifest(universe_path) if universe_path else load_universe_manifest()
    if universe["integrity"]["manifest_sha256"] != PINNED_UNIVERSE_MANIFEST_SHA256:
        raise ValueError("independent validation universe manifest is not pinned")
    if universe["symbol_list_sha256"] != PINNED_UNIVERSE_SYMBOL_LIST_SHA256:
        raise ValueError("independent validation symbol list is not pinned")
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
    provisional["recovery_check_vs_frozen_2026_08_29"] = recovery_check(_recovery_rows(acquired))
    provisional["integrity"] = {"manifest_sha256": manifest_integrity_hash(provisional)}
    if provisional["coverage_status"] != READY_STATUS:
        dataset_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        dataset_manifest_path.write_text(
            json.dumps(provisional, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
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
    manifest["recovery_check_vs_frozen_2026_08_29"] = recovery_check(_recovery_rows(acquired))
    manifest["integrity"] = {"manifest_sha256": manifest_integrity_hash(manifest)}
    dataset_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    replay_manifest_path.write_text(
        json.dumps(replay_manifest.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def load_validation_sample(
    *,
    dataset_manifest_path: Path = DATASET_MANIFEST_PATH,
    frozen_input_path: Path = FROZEN_INPUT_PATH,
) -> tuple[dict[str, Any], dict[str, list[Quote]], Any]:
    """Load and verify the frozen independent sample; fail closed on any drift."""
    manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != DATASET_SCHEMA_VERSION:
        raise ValueError("independent validation dataset schema changed")
    if manifest.get("dataset_version") != DATASET_VERSION:
        raise ValueError("independent validation dataset identity changed")
    if manifest.get("coverage_status") != READY_STATUS:
        raise ValueError("independent validation dataset is not ready")
    if manifest["integrity"]["manifest_sha256"] != manifest_integrity_hash(manifest):
        raise ValueError("independent validation dataset integrity mismatch")
    if manifest["universe"]["manifest_sha256"] != PINNED_UNIVERSE_MANIFEST_SHA256:
        raise ValueError("independent validation universe binding changed")
    if any(manifest["universe"]["exclusion_proofs"].values()):
        raise ValueError("independent validation exclusion proof is not empty")
    symbol_quotes, replay_manifest = read_frozen_input(frozen_input_path)
    if replay_manifest.aggregate_hash != manifest["replay_input_manifest_sha256"]:
        raise ValueError("replay input does not match the frozen dataset manifest")
    if replay_manifest.total_symbol_count != EXPECTED_COUNTS["total"]:
        raise ValueError("independent validation sample symbol count changed")
    coverage = manifest["market_coverage"]
    if coverage["CN"]["valid_accepted"] != EXPECTED_COUNTS["CN"] or coverage["US"]["valid_accepted"] != EXPECTED_COUNTS["US"]:
        raise ValueError("independent validation market coverage changed")
    if sorted(symbol_quotes) != sorted(item["canonical_symbol"] for item in manifest["symbols"]):
        raise ValueError("replay input symbol roster does not match the manifest")
    if manifest["controls"]["signal_computed_before_freeze"] is not False:
        raise ValueError("sample freeze control weakened")
    return manifest, symbol_quotes, replay_manifest


__all__ = [
    "ARTIFACT_DIR",
    "DATASET_MANIFEST_PATH",
    "DATASET_VERSION",
    "FROZEN_INPUT_PATH",
    "MANIFEST_DIR",
    "READY_STATUS",
    "REPLAY_MANIFEST_PATH",
    "acquire_and_freeze",
    "load_validation_sample",
    "manifest_integrity_hash",
    "recovery_check",
]

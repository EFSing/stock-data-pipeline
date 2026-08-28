"""Development-only yfinance acquisition and immutable dataset manifest.

This module deliberately has one historical provider: the existing yfinance
capability.  Tencent/Sina are not used here because they are snapshot sources
and cannot be silently mixed into a historical series.  Every failed symbol is
kept in the manifest rather than being replaced after looking at SETUP_03
output.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from core import Quote
from research.development_universe import (
    DEVELOPMENT_LABELS,
    DEVELOPMENT_UNIVERSE_PATH,
    DEVELOPMENT_UNIVERSE_VERSION,
    load_development_universe_manifest,
    manifest_integrity_hash as universe_manifest_integrity_hash,
)
from research.replay_input import build_input_manifest, write_frozen_input


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "development_strategy_stability"
DATASET_MANIFEST_PATH = DEVELOPMENT_ARTIFACT_DIR / "development_dataset_manifest.json"
REPLAY_MANIFEST_PATH = DEVELOPMENT_ARTIFACT_DIR / "development_replay_manifest.json"
FROZEN_INPUT_PATH = DEVELOPMENT_ARTIFACT_DIR / "development_replay_input.jsonl.gz"

DEVELOPMENT_DATASET_SCHEMA_VERSION = "setup03-development-dataset-manifest-v1"
DEVELOPMENT_DATASET_VERSION = "SETUP_03-DEVELOPMENT-DATASET-CN-US-YFINANCE-2026-08-28-v1"
DEVELOPMENT_DATASET_STATUS = "DEVELOPMENT_DATASET_FROZEN_NOT_FORMAL_VALIDATION"
DEVELOPMENT_PROVIDER_ID = "YFINANCE_DEVELOPMENT_HISTORICAL"
DEVELOPMENT_ADJUSTMENT_MODE = "YFINANCE_AUTO_ADJUST_TRUE"
START_DATE = date(2017, 1, 1)
END_DATE = date(2026, 8, 26)
MIN_VALID_SYMBOLS_PER_MARKET = 8
MIN_VALID_SYMBOLS_TOTAL = 40

PINNED_FORMAL_CONTRACTS = {
    "a1_manifest_sha256": "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433",
    "b0_v2_contract_sha256": "sha256:0fdfef827d48ef6deec8e58c1de1e0e470d3adb6567a1e74d25c44d8a3137588",
    "phase5j_v2_protocol_sha256": "sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0",
}
PINNED_DEVELOPMENT_DATASET_MANIFEST_SHA256 = (
    "sha256:253c02fba6eb7273588af571f367c19695056261b9985a181f46a42072f2cf67"
)


class DevelopmentDataError(ValueError):
    """A provider or normalized-bar QC failure for one development symbol."""


@dataclass(frozen=True)
class AcquiredSymbol:
    manifest_row: dict[str, Any]
    quotes: tuple[Quote, ...]
    normalized_rows: tuple[dict[str, Any], ...]
    dataset_row: dict[str, Any]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def dataset_manifest_integrity_hash(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("integrity", None)
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _safe_path_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _artifact_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _exchange_timezone(market: str) -> ZoneInfo:
    return ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")


def _date_value(value: Any, market: str) -> date:
    if hasattr(value, "tz_convert") and getattr(value, "tzinfo", None) is not None:
        value = value.tz_convert(_exchange_timezone(market))
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DevelopmentDataError(f"{field} is not numeric") from exc
    if not math.isfinite(number):
        raise DevelopmentDataError(f"{field} is not finite")
    return number


def _raw_frame_bytes(frame: Any) -> bytes:
    try:
        return frame.to_csv(index=True, lineterminator="\n").encode("utf-8")
    except Exception as exc:
        raise DevelopmentDataError(f"yfinance response cannot be serialized: {exc}") from exc


def fetch_yfinance_frame(yfinance_symbol_value: str, start: date = START_DATE, end: date = END_DATE) -> tuple[Any, bytes]:
    """Fetch one adjusted daily DataFrame through the existing yfinance API."""
    try:
        import yfinance as yf

        frame = yf.Ticker(yfinance_symbol_value).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=True,
            actions=False,
            repair=False,
        )
    except Exception as exc:
        raise DevelopmentDataError(f"yfinance provider exception: {type(exc).__name__}: {exc}") from exc
    if frame is None or frame.empty:
        raise DevelopmentDataError("yfinance returned no daily bars")
    return frame, _raw_frame_bytes(frame)


def _row_value(row: Any, field: str) -> Any:
    if field in row:
        return row[field]
    # A single-ticker yfinance response can occasionally retain a one-level
    # MultiIndex after reset_index().  Keep the extraction deterministic.
    for key in row.index:
        if str(key).split(",")[-1].strip("() '") == field:
            return row[key]
    raise DevelopmentDataError(f"yfinance response missing {field}")


def _normalized_hash(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        hashed = dict(row)
        for field in ("open", "high", "low", "close", "volume"):
            hashed[field] = float(row[field]).hex()
        digest.update(canonical_json(hashed).encode("utf-8"))
        digest.update(b"\n")
    return sha256_bytes(digest.digest())


def _aggregate_dataset_hash(rows_by_symbol: Mapping[str, tuple[dict[str, Any], ...]]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{DEVELOPMENT_DATASET_SCHEMA_VERSION}\n".encode("utf-8"))
    for symbol in sorted(rows_by_symbol):
        digest.update(f"{symbol}\n".encode("utf-8"))
        for row in rows_by_symbol[symbol]:
            hashed = dict(row)
            for field in ("open", "high", "low", "close", "volume"):
                hashed[field] = float(row[field]).hex()
            digest.update(canonical_json(hashed).encode("utf-8"))
            digest.update(b"\n")
    return sha256_bytes(digest.digest())


def _normalize_frame(
    manifest_row: Mapping[str, Any], frame: Any
) -> tuple[tuple[Quote, ...], tuple[dict[str, Any], ...], dict[str, Any]]:
    market = str(manifest_row["market"])
    symbol = str(manifest_row["canonical_symbol"])
    name = str(manifest_row.get("source_name") or symbol)
    currency = "CNY" if market == "CN" else "USD"
    indexed = frame.reset_index()
    date_column = "Date" if "Date" in indexed.columns else "Datetime"
    if date_column not in indexed.columns:
        date_column = str(indexed.columns[0])
    by_date: dict[date, dict[str, Any]] = {}
    exact_duplicate_count = 0
    filtered_out_count = 0
    for _, row in indexed.iterrows():
        trade_date = _date_value(row[date_column], market)
        if not START_DATE <= trade_date <= END_DATE:
            filtered_out_count += 1
            continue
        values = {
            "open": _finite(_row_value(row, "Open"), "open"),
            "high": _finite(_row_value(row, "High"), "high"),
            "low": _finite(_row_value(row, "Low"), "low"),
            "close": _finite(_row_value(row, "Close"), "close"),
            "volume": _finite(_row_value(row, "Volume"), "volume"),
        }
        if any(values[field] <= 0 for field in ("open", "high", "low", "close")):
            raise DevelopmentDataError("invalid non-positive OHLC")
        if values["volume"] < 0:
            raise DevelopmentDataError("invalid negative volume")
        if not (
            values["low"] <= values["open"] <= values["high"]
            and values["low"] <= values["close"] <= values["high"]
            and values["low"] <= values["high"]
        ):
            raise DevelopmentDataError("invalid OHLC ordering")
        normalized = {
            "market": market,
            "canonical_symbol": symbol,
            "date": trade_date.isoformat(),
            **values,
            "source_provider": DEVELOPMENT_PROVIDER_ID,
            "adjustment_mode": DEVELOPMENT_ADJUSTMENT_MODE,
        }
        previous = by_date.get(trade_date)
        if previous is not None:
            if previous == normalized:
                exact_duplicate_count += 1
                continue
            raise DevelopmentDataError(
                f"DATA_CONFLICT_FAIL_CLOSED: conflicting duplicate bar {trade_date.isoformat()}"
            )
        by_date[trade_date] = normalized

    ordered_rows = [by_date[key] for key in sorted(by_date)]
    if not ordered_rows:
        raise DevelopmentDataError("no valid daily bars after local-date filtering")
    quotes = tuple(
        Quote(
            symbol=symbol,
            name=name,
            market=market,
            trade_date=date.fromisoformat(row["date"]),
            source=DEVELOPMENT_PROVIDER_ID,
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            preclose=None,
            pct_change=None,
            volume=row["volume"],
            amount=None,
            turnover_rate=None,
            currency=currency,
        )
        for row in ordered_rows
    )
    gaps = [
        (current - previous).days
        for previous, current in zip(
            (quote.trade_date for quote in quotes),
            (quote.trade_date for quote in quotes[1:]),
        )
    ]
    metadata = {
        "bar_count": len(ordered_rows),
        "first_local_trading_date": ordered_rows[0]["date"],
        "last_local_trading_date": ordered_rows[-1]["date"],
        "filtered_out_of_window_rows": filtered_out_count,
        "duplicate_count": exact_duplicate_count,
        "duplicate_conflict_handling": (
            "EXACT_NORMALIZED_DUPLICATE_DEDUPED" if exact_duplicate_count else "NO_DUPLICATES"
        ),
        "observed_calendar_gap_count_gt_3_days": sum(gap > 3 for gap in gaps),
        "observed_calendar_gap_max_days": max(gaps, default=0),
        "missing_bar_status": "NOT_INFERRED_NO_FILL",
        "missing_bar_reason": (
            "Exchange holiday and suspension calendars are not inferred; absent dates remain absent."
        ),
    }
    return quotes, tuple(ordered_rows), metadata


def acquire_symbol(
    manifest_row: Mapping[str, Any],
    *,
    raw_dir: Path,
    normalized_dir: Path,
    fetcher: Callable[[str, date, date], tuple[Any, bytes]] = fetch_yfinance_frame,
) -> AcquiredSymbol:
    """Acquire and QC one symbol without provider switching or row fabrication."""
    row = dict(manifest_row)
    market = str(row["market"])
    symbol = str(row["canonical_symbol"])
    y_symbol = str(row["yfinance_symbol"])
    safe_market = _safe_path_part(market)
    safe_symbol = _safe_path_part(symbol)
    raw_path = raw_dir / safe_market / f"{safe_symbol}.csv"
    normalized_path = normalized_dir / safe_market / f"{safe_symbol}.jsonl"
    retrieved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    base = {
        "market": market,
        "canonical_symbol": symbol,
        "canonical_identity": row["canonical_identity"],
        "yfinance_symbol": y_symbol,
        "provider_id": DEVELOPMENT_PROVIDER_ID,
        "adjustment_mode": DEVELOPMENT_ADJUSTMENT_MODE,
        "retrieval_timestamp": retrieved_at,
        "request_contract": {
            "method": "yfinance.Ticker.history",
            "symbol": y_symbol,
            "start": START_DATE.isoformat(),
            "end": END_DATE.isoformat(),
            "end_wire_is_exclusive": True,
            "interval": "1d",
            "auto_adjust": True,
            "actions": False,
            "repair": False,
            "local_trading_date_timezone": "Asia/Shanghai" if market == "CN" else "America/New_York",
        },
        "raw_response_path": _artifact_path(raw_path),
        "normalized_path": _artifact_path(normalized_path),
    }
    try:
        frame, raw_bytes = fetcher(y_symbol, START_DATE, END_DATE)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw_bytes)
        quotes, normalized_rows, qc_metadata = _normalize_frame(row, frame)
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        with normalized_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json({"artifact_labels": list(DEVELOPMENT_LABELS), "record_type": "manifest", "symbol": symbol}) + "\n")
            for normalized in normalized_rows:
                handle.write(canonical_json(normalized) + "\n")
        dataset_row = {
            **base,
            "raw_response_sha256": sha256_bytes(raw_bytes),
            "normalized_data_sha256": _normalized_hash(list(normalized_rows)),
            "qc_status": "VALID_ACCEPTED",
            "qc_reason": "",
            **qc_metadata,
        }
        return AcquiredSymbol(row, quotes, normalized_rows, dataset_row)
    except Exception as exc:
        message = str(exc).replace("HITHINK_FINANCE_API_KEY", "<redacted-secret-name>")
        dataset_row = {
            **base,
            "raw_response_sha256": sha256_bytes(raw_path.read_bytes()) if raw_path.exists() else None,
            "normalized_data_sha256": None,
            "bar_count": 0,
            "first_local_trading_date": None,
            "last_local_trading_date": None,
            "qc_status": "PROVIDER_OR_QC_FAILED",
            "qc_reason": message,
            "missing_bar_status": "NOT_ASSESSED_PROVIDER_OR_QC_FAILURE",
        }
        return AcquiredSymbol(row, (), (), dataset_row)


def _market_aggregate(rows: list[Mapping[str, Any]], market: str) -> dict[str, Any]:
    selected = [row for row in rows if row["market"] == market]
    valid = [row for row in selected if row["qc_status"] == "VALID_ACCEPTED"]
    failed = [row for row in selected if row["qc_status"] != "VALID_ACCEPTED"]
    return {
        "selected_symbol_count": len(selected),
        "valid_symbol_count": len(valid),
        "valid_bar_count": sum(int(row["bar_count"]) for row in valid),
        "excluded_symbol_count": len(failed),
        "exclusions": [
            {
                "canonical_symbol": row["canonical_symbol"],
                "status": row["qc_status"],
                "reason": row["qc_reason"],
            }
            for row in failed
        ],
    }


def build_dataset_manifest(
    universe: Mapping[str, Any],
    acquired: list[AcquiredSymbol],
    *,
    replay_manifest_hash: str | None = None,
    frozen_at: str = "2026-08-28",
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
    total_valid = len(valid)
    coverage_status = (
        "DEVELOPMENT_DATASET_READY_FOR_STABILITY_DIAGNOSTICS"
        if total_valid >= MIN_VALID_SYMBOLS_TOTAL
        and all(len([item for item in valid if item.manifest_row["market"] == market]) >= MIN_VALID_SYMBOLS_PER_MARKET for market in ("CN", "US"))
        else "DEVELOPMENT_DATASET_COVERAGE_SHORTFALL_REQUIRES_REVIEW"
    )
    manifest = {
        "schema_version": DEVELOPMENT_DATASET_SCHEMA_VERSION,
        "dataset_version": DEVELOPMENT_DATASET_VERSION,
        "status": DEVELOPMENT_DATASET_STATUS,
        "coverage_status": coverage_status,
        "artifact_labels": list(DEVELOPMENT_LABELS),
        "frozen_at": frozen_at,
        "universe": {
            "universe_version": universe["universe_version"],
            "symbol_list_sha256": universe["symbol_list_sha256"],
            "manifest_sha256": universe["integrity"]["manifest_sha256"],
        },
        "formal_contract_pins": dict(PINNED_FORMAL_CONTRACTS),
        "provider_contract": {
            "provider_id": DEVELOPMENT_PROVIDER_ID,
            "provider_capability": "existing yfinance daily history interface",
            "adjustment_semantics": DEVELOPMENT_ADJUSTMENT_MODE,
            "history_is_single_provider": True,
            "snapshot_sources_are_not_mixed_into_history": True,
            "ticker_mapping": "CN canonical .SH -> .SS; CN canonical .SZ -> .SZ; US unchanged",
            "date_semantics": "security local exchange trading date",
            "raw_response_representation": "exact UTF-8 bytes of the yfinance DataFrame CSV serialization before normalization",
            "normalized_data_hash_semantics": "canonical JSONL of validated normalized bars with float.hex hash projection",
        },
        "date_window": {
            "start_date": START_DATE.isoformat(),
            "end_date": END_DATE.isoformat(),
            "inclusive": True,
            "local_trading_date_timezone": {"CN": "Asia/Shanghai", "US": "America/New_York"},
        },
        "qc_contract": {
            "forward_fill": False,
            "interpolation": False,
            "synthetic_bars": False,
            "suspension_day_fabrication": False,
            "conflicting_duplicate_action": "DATA_CONFLICT_FAIL_CLOSED",
            "exact_duplicate_action": "DETERMINISTIC_DEDUPE",
            "missing_dates": "retained_as_missing; no calendar inference",
        },
        "symbols": rows,
        "market_aggregate": {
            market: _market_aggregate(rows, market) for market in ("CN", "US")
        },
        "aggregate_symbol_count": total_valid,
        "aggregate_bar_count": sum(row["bar_count"] for row in rows),
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
            for row in rows
            if row["qc_status"] != "VALID_ACCEPTED"
        ],
        "controls": {
            "development_only": True,
            "formal_phase5k_validation": False,
            "final_oos_accessed": False,
            "ibkr_used": False,
            "result_driven_symbol_replacement": False,
            "mixed_history_repair": False,
        },
    }
    manifest["integrity"] = {"manifest_sha256": dataset_manifest_integrity_hash(manifest)}
    return manifest, symbol_quotes, normalized_by_symbol


def write_dataset_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_dataset_manifest(path: Path = DATASET_MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != DEVELOPMENT_DATASET_SCHEMA_VERSION:
        raise ValueError("unsupported development dataset schema")
    if manifest.get("dataset_version") != DEVELOPMENT_DATASET_VERSION:
        raise ValueError("development dataset version changed")
    if tuple(manifest.get("artifact_labels", ())) != DEVELOPMENT_LABELS:
        raise ValueError("development dataset labels changed")
    if manifest.get("status") != DEVELOPMENT_DATASET_STATUS:
        raise ValueError("development dataset status changed")
    if manifest.get("integrity", {}).get("manifest_sha256") != dataset_manifest_integrity_hash(manifest):
        raise ValueError("development dataset manifest integrity mismatch")
    if manifest["integrity"]["manifest_sha256"] != PINNED_DEVELOPMENT_DATASET_MANIFEST_SHA256:
        raise ValueError("development dataset version is bound to a different hash")
    if manifest.get("formal_contract_pins") != PINNED_FORMAL_CONTRACTS:
        raise ValueError("formal contract pin changed")
    return manifest


def load_frozen_dataset(
    manifest_path: Path = DATASET_MANIFEST_PATH,
) -> tuple[dict[str, Any], dict[str, list[Quote]]]:
    """Reload only the previously frozen normalized bars; never refetch history."""
    manifest = load_dataset_manifest(manifest_path)
    universe = load_development_universe_manifest()
    names = {
        str(row["canonical_symbol"]): str(row.get("source_name") or row["canonical_symbol"])
        for row in universe["symbols"]
    }
    symbol_quotes: dict[str, list[Quote]] = {}
    normalized_by_symbol: dict[str, tuple[dict[str, Any], ...]] = {}
    for row in manifest["symbols"]:
        if row["qc_status"] != "VALID_ACCEPTED":
            continue
        path = Path(row["normalized_path"])
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()[1:]
            if line.strip()
        ]
        if _normalized_hash(records) != row["normalized_data_sha256"]:
            raise ValueError(f"frozen normalized hash mismatch: {row['canonical_symbol']}")
        symbol = str(row["canonical_symbol"])
        market = str(row["market"])
        currency = "CNY" if market == "CN" else "USD"
        normalized_by_symbol[symbol] = tuple(records)
        symbol_quotes[symbol] = [
            Quote(
                symbol=symbol,
                name=names.get(symbol, symbol),
                market=market,
                trade_date=date.fromisoformat(record["date"]),
                source=DEVELOPMENT_PROVIDER_ID,
                open=float(record["open"]),
                high=float(record["high"]),
                low=float(record["low"]),
                close=float(record["close"]),
                preclose=None,
                pct_change=None,
                volume=float(record["volume"]),
                amount=None,
                turnover_rate=None,
                currency=currency,
            )
            for record in records
        ]
    replay_manifest = build_input_manifest(symbol_quotes)
    expected_replay_hash = manifest.get("replay_input_manifest_sha256")
    if expected_replay_hash is not None and replay_manifest.aggregate_hash != expected_replay_hash:
        raise ValueError("frozen replay input hash mismatch")
    if _aggregate_dataset_hash(normalized_by_symbol) != manifest["aggregate_dataset_sha256"]:
        raise ValueError("frozen aggregate dataset hash mismatch")
    return manifest, symbol_quotes


def acquire_and_freeze_dataset(
    universe_path: Path = DEVELOPMENT_UNIVERSE_PATH,
    output_dir: Path = DEVELOPMENT_ARTIFACT_DIR,
    *,
    fetcher: Callable[[str, date, date], tuple[Any, bytes]] = fetch_yfinance_frame,
) -> tuple[dict[str, Any], dict[str, list[Quote]]]:
    universe = load_development_universe_manifest(universe_path)
    raw_dir = output_dir / "raw_yfinance"
    normalized_dir = output_dir / "normalized_bars"
    acquired = [
        acquire_symbol(
            row,
            raw_dir=raw_dir,
            normalized_dir=normalized_dir,
            fetcher=fetcher,
        )
        for row in universe["symbols"]
    ]
    provisional, symbol_quotes, _ = build_dataset_manifest(universe, acquired)
    replay_manifest = build_input_manifest(symbol_quotes)
    frozen_manifest = write_frozen_input(output_dir / "development_replay_input.jsonl.gz", symbol_quotes)
    if frozen_manifest != replay_manifest:
        raise ValueError("development replay input changed during serialization")
    replay_payload = {
        "schema_version": "setup03-development-replay-manifest-v1",
        "artifact_labels": list(DEVELOPMENT_LABELS),
        "dataset_version": DEVELOPMENT_DATASET_VERSION,
        "dataset_manifest_sha256": provisional["integrity"]["manifest_sha256"],
        "replay_manifest": replay_manifest.to_dict(),
        "controls": {
            "development_only": True,
            "formal_phase5k_validation": False,
            "final_oos_accessed": False,
        },
    }
    replay_payload["integrity"] = {"manifest_sha256": dataset_manifest_integrity_hash(replay_payload)}
    output_dir.mkdir(parents=True, exist_ok=True)
    replay_manifest_path = output_dir / "development_replay_manifest.json"
    replay_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    replay_manifest_path.write_text(json.dumps(replay_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest, symbol_quotes, _ = build_dataset_manifest(
        universe,
        acquired,
        replay_manifest_hash=replay_manifest.aggregate_hash,
    )
    write_dataset_manifest(output_dir / "development_dataset_manifest.json", manifest)
    return manifest, symbol_quotes

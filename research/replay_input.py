"""Deterministic manifests and frozen inputs for historical replay.

This module serializes the exact ``core.Quote`` objects that enter replay. It
does not fetch data or implement any Setup/Decision logic.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Iterable

from core import Quote
from trading.models import validate_quote_series


SCHEMA_VERSION = "setup03-replay-input-v1"
HASH_PREFIX = "sha256:"
_OPTIONAL_FLOAT_FIELDS = (
    "preclose",
    "pct_change",
    "volume",
    "amount",
    "turnover_rate",
)


@dataclass(frozen=True)
class SymbolInputManifest:
    symbol: str
    bar_count: int
    start_date: date
    end_date: date
    input_hash: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "bar_count": self.bar_count,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "input_hash": self.input_hash,
        }


@dataclass(frozen=True)
class ReplayInputManifest:
    schema_version: str
    aggregate_hash: str
    total_symbol_count: int
    total_bar_count: int
    symbols: tuple[SymbolInputManifest, ...]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "aggregate_hash": self.aggregate_hash,
            "total_symbol_count": self.total_symbol_count,
            "total_bar_count": self.total_bar_count,
            "symbols": [item.to_dict() for item in self.symbols],
        }

    def csv_rows(self) -> list[dict]:
        return [
            {
                **item.to_dict(),
                "aggregate_hash": self.aggregate_hash,
                "total_symbol_count": self.total_symbol_count,
                "total_bar_count": self.total_bar_count,
                "schema_version": self.schema_version,
            }
            for item in self.symbols
        ]


class ManifestChange(str, Enum):
    IDENTICAL = "IDENTICAL"
    BAR_COUNT_CHANGED = "BAR_COUNT_CHANGED"
    DATE_RANGE_CHANGED = "DATE_RANGE_CHANGED"
    CONTENT_CHANGED_WITH_SAME_BAR_COUNT = "CONTENT_CHANGED_WITH_SAME_BAR_COUNT"
    SYMBOL_ADDED = "SYMBOL_ADDED"
    SYMBOL_REMOVED = "SYMBOL_REMOVED"


@dataclass(frozen=True)
class ManifestComparison:
    symbol: str
    status: ManifestChange
    previous_bar_count: int | None
    current_bar_count: int | None
    previous_start_date: date | None
    current_start_date: date | None
    previous_end_date: date | None
    current_end_date: date | None
    previous_input_hash: str | None
    current_input_hash: str | None

    def to_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "status": self.status.value,
            "previous_bar_count": self.previous_bar_count,
            "current_bar_count": self.current_bar_count,
            "previous_start_date": self.previous_start_date,
            "current_start_date": self.current_start_date,
            "previous_end_date": self.previous_end_date,
            "current_end_date": self.current_end_date,
            "previous_input_hash": self.previous_input_hash,
            "current_input_hash": self.current_input_hash,
        }


def canonical_bar(quote: Quote) -> dict:
    """Return an exact, JSON-safe representation of one replay input bar."""
    row = {
        "symbol": str(quote.symbol),
        "name": str(quote.name),
        "market": str(quote.market),
        "trade_date": quote.trade_date.isoformat(),
        "source": str(quote.source),
        "open": _float_hex(quote.open, "open"),
        "high": _float_hex(quote.high, "high"),
        "low": _float_hex(quote.low, "low"),
        "close": _float_hex(quote.close, "close"),
        "currency": str(quote.currency),
    }
    for field in _OPTIONAL_FLOAT_FIELDS:
        value = getattr(quote, field)
        row[field] = None if value is None else _float_hex(value, field)
    return row


def quote_from_canonical_bar(row: dict) -> Quote:
    """Reconstruct one Quote exactly from ``canonical_bar`` output."""
    required = {
        "symbol",
        "name",
        "market",
        "trade_date",
        "source",
        "open",
        "high",
        "low",
        "close",
        "currency",
        *_OPTIONAL_FLOAT_FIELDS,
    }
    if set(row) != required:
        missing = sorted(required - set(row))
        extra = sorted(set(row) - required)
        raise ValueError(f"canonical bar fields mismatch: missing={missing}, extra={extra}")
    optional = {
        field: None if row[field] is None else float.fromhex(str(row[field]))
        for field in _OPTIONAL_FLOAT_FIELDS
    }
    return Quote(
        symbol=str(row["symbol"]),
        name=str(row["name"]),
        market=str(row["market"]),
        trade_date=date.fromisoformat(str(row["trade_date"])),
        source=str(row["source"]),
        open=float.fromhex(str(row["open"])),
        high=float.fromhex(str(row["high"])),
        low=float.fromhex(str(row["low"])),
        close=float.fromhex(str(row["close"])),
        preclose=optional["preclose"],
        pct_change=optional["pct_change"],
        volume=optional["volume"],
        amount=optional["amount"],
        turnover_rate=optional["turnover_rate"],
        currency=str(row["currency"]),
    )


def build_input_manifest(
    symbol_quotes: dict[str, list[Quote]],
) -> ReplayInputManifest:
    """Hash each validated symbol series and its stable aggregate projection."""
    symbol_manifests: list[SymbolInputManifest] = []
    for symbol in sorted(symbol_quotes):
        quotes = symbol_quotes[symbol]
        validate_quote_series(quotes)
        if quotes[0].symbol != symbol:
            raise ValueError(
                f"symbol_quotes key does not match Quote symbol: {symbol}!={quotes[0].symbol}"
            )
        digest = hashlib.sha256()
        digest.update(f"{SCHEMA_VERSION}\n".encode("utf-8"))
        for quote in quotes:
            digest.update(_json_bytes(canonical_bar(quote)))
            digest.update(b"\n")
        symbol_manifests.append(
            SymbolInputManifest(
                symbol=symbol,
                bar_count=len(quotes),
                start_date=quotes[0].trade_date,
                end_date=quotes[-1].trade_date,
                input_hash=f"{HASH_PREFIX}{digest.hexdigest()}",
            )
        )

    aggregate_payload = {
        "schema_version": SCHEMA_VERSION,
        "symbols": [item.to_dict() for item in symbol_manifests],
    }
    aggregate_hash = (
        f"{HASH_PREFIX}{hashlib.sha256(_json_bytes(aggregate_payload)).hexdigest()}"
    )
    return ReplayInputManifest(
        schema_version=SCHEMA_VERSION,
        aggregate_hash=aggregate_hash,
        total_symbol_count=len(symbol_manifests),
        total_bar_count=sum(item.bar_count for item in symbol_manifests),
        symbols=tuple(symbol_manifests),
    )


def write_input_manifest(path: Path, manifest: ReplayInputManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(manifest.to_dict()) + b"\n")


def read_input_manifest(path: Path) -> ReplayInputManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported replay input schema: {raw.get('schema_version')}")
    symbols = tuple(
        SymbolInputManifest(
            symbol=str(item["symbol"]),
            bar_count=int(item["bar_count"]),
            start_date=date.fromisoformat(str(item["start_date"])),
            end_date=date.fromisoformat(str(item["end_date"])),
            input_hash=str(item["input_hash"]),
        )
        for item in raw["symbols"]
    )
    manifest = ReplayInputManifest(
        schema_version=SCHEMA_VERSION,
        aggregate_hash=str(raw["aggregate_hash"]),
        total_symbol_count=int(raw["total_symbol_count"]),
        total_bar_count=int(raw["total_bar_count"]),
        symbols=symbols,
    )
    _validate_manifest_shape(manifest)
    return manifest


def write_frozen_input(
    path: Path, symbol_quotes: dict[str, list[Quote]]
) -> ReplayInputManifest:
    """Write deterministic gzip JSONL and return its embedded manifest."""
    manifest = build_input_manifest(symbol_quotes)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw_handle:
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", filename="", mtime=0) as handle:
            handle.write(
                _json_bytes(
                    {
                        "record_type": "manifest",
                        "manifest": manifest.to_dict(),
                    }
                )
                + b"\n"
            )
            for symbol in sorted(symbol_quotes):
                for quote in symbol_quotes[symbol]:
                    handle.write(
                        _json_bytes(
                            {
                                "record_type": "bar",
                                "bar": canonical_bar(quote),
                            }
                        )
                        + b"\n"
                    )
    return manifest


def read_frozen_input(
    path: Path,
) -> tuple[dict[str, list[Quote]], ReplayInputManifest]:
    """Load a frozen input and fail if its embedded manifest does not match."""
    symbol_quotes: dict[str, list[Quote]] = {}
    embedded_manifest: ReplayInputManifest | None = None
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            record_type = record.get("record_type")
            if line_number == 1 and record_type == "manifest":
                embedded_manifest = _manifest_from_dict(record["manifest"])
                continue
            if record_type != "bar":
                raise ValueError(
                    f"unexpected frozen input record at line {line_number}: {record_type}"
                )
            quote = quote_from_canonical_bar(record["bar"])
            symbol_quotes.setdefault(quote.symbol, []).append(quote)
    if embedded_manifest is None:
        raise ValueError("frozen input is missing its manifest header")
    actual_manifest = build_input_manifest(symbol_quotes)
    if actual_manifest != embedded_manifest:
        raise ValueError("frozen input content does not match its embedded manifest")
    return symbol_quotes, actual_manifest


def compare_input_manifests(
    previous: ReplayInputManifest,
    current: ReplayInputManifest,
) -> tuple[ManifestComparison, ...]:
    """Classify each symbol deterministically, with one explicit primary status."""
    previous_by_symbol = {item.symbol: item for item in previous.symbols}
    current_by_symbol = {item.symbol: item for item in current.symbols}
    comparisons: list[ManifestComparison] = []
    for symbol in sorted(previous_by_symbol.keys() | current_by_symbol.keys()):
        old = previous_by_symbol.get(symbol)
        new = current_by_symbol.get(symbol)
        if old is None:
            status = ManifestChange.SYMBOL_ADDED
        elif new is None:
            status = ManifestChange.SYMBOL_REMOVED
        elif old.bar_count != new.bar_count:
            status = ManifestChange.BAR_COUNT_CHANGED
        elif (old.start_date, old.end_date) != (new.start_date, new.end_date):
            status = ManifestChange.DATE_RANGE_CHANGED
        elif old.input_hash != new.input_hash:
            status = ManifestChange.CONTENT_CHANGED_WITH_SAME_BAR_COUNT
        else:
            status = ManifestChange.IDENTICAL
        comparisons.append(
            ManifestComparison(
                symbol=symbol,
                status=status,
                previous_bar_count=old.bar_count if old else None,
                current_bar_count=new.bar_count if new else None,
                previous_start_date=old.start_date if old else None,
                current_start_date=new.start_date if new else None,
                previous_end_date=old.end_date if old else None,
                current_end_date=new.end_date if new else None,
                previous_input_hash=old.input_hash if old else None,
                current_input_hash=new.input_hash if new else None,
            )
        )
    return tuple(comparisons)


def comparison_rows(comparisons: Iterable[ManifestComparison]) -> list[dict]:
    return [comparison.to_row() for comparison in comparisons]


def _manifest_from_dict(raw: dict) -> ReplayInputManifest:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported replay input schema: {raw.get('schema_version')}")
    manifest = ReplayInputManifest(
        schema_version=SCHEMA_VERSION,
        aggregate_hash=str(raw["aggregate_hash"]),
        total_symbol_count=int(raw["total_symbol_count"]),
        total_bar_count=int(raw["total_bar_count"]),
        symbols=tuple(
            SymbolInputManifest(
                symbol=str(item["symbol"]),
                bar_count=int(item["bar_count"]),
                start_date=date.fromisoformat(str(item["start_date"])),
                end_date=date.fromisoformat(str(item["end_date"])),
                input_hash=str(item["input_hash"]),
            )
            for item in raw["symbols"]
        ),
    )
    _validate_manifest_shape(manifest)
    return manifest


def _validate_manifest_shape(manifest: ReplayInputManifest) -> None:
    symbols = tuple(item.symbol for item in manifest.symbols)
    if symbols != tuple(sorted(symbols)) or len(symbols) != len(set(symbols)):
        raise ValueError("manifest symbols must be unique and sorted")
    if manifest.total_symbol_count != len(manifest.symbols):
        raise ValueError("manifest symbol count is inconsistent")
    if manifest.total_bar_count != sum(item.bar_count for item in manifest.symbols):
        raise ValueError("manifest bar count is inconsistent")
    aggregate_payload = {
        "schema_version": manifest.schema_version,
        "symbols": [item.to_dict() for item in manifest.symbols],
    }
    expected_hash = (
        f"{HASH_PREFIX}{hashlib.sha256(_json_bytes(aggregate_payload)).hexdigest()}"
    )
    if manifest.aggregate_hash != expected_hash:
        raise ValueError("manifest aggregate hash is inconsistent")


def _float_hex(value: float, field: str) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite replay input value: {field}={value}")
    return number.hex()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

"""Development-only historical acquisition and immutable dataset manifest.

The active development split is BaoStock qfq for CN and the existing yfinance
historical capability for US. Tencent/Sina are not used here because they are
snapshot sources and cannot be silently mixed into a historical series. Every
failed symbol is kept in the manifest rather than being replaced after looking
at SETUP_03 output.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
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
HISTORICAL_V1_ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "development_strategy_stability"
DEVELOPMENT_ARTIFACT_DIR = PROJECT_ROOT / "artifacts" / "development_strategy_stability_v2"
DATASET_MANIFEST_PATH = DEVELOPMENT_ARTIFACT_DIR / "development_dataset_manifest.json"
REPLAY_MANIFEST_PATH = DEVELOPMENT_ARTIFACT_DIR / "development_replay_manifest.json"
FROZEN_INPUT_PATH = DEVELOPMENT_ARTIFACT_DIR / "development_replay_input.jsonl.gz"

HISTORICAL_V1_DATASET_SCHEMA_VERSION = "setup03-development-dataset-manifest-v1"
HISTORICAL_V1_DATASET_VERSION = "SETUP_03-DEVELOPMENT-DATASET-CN-US-YFINANCE-2026-08-28-v1"
HISTORICAL_V1_DATASET_MANIFEST_SHA256 = (
    "sha256:253c02fba6eb7273588af571f367c19695056261b9985a181f46a42072f2cf67"
)
DEVELOPMENT_DATASET_SCHEMA_VERSION = "setup03-development-dataset-manifest-v2"
DEVELOPMENT_DATASET_VERSION = "SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2"
DEVELOPMENT_DATASET_STATUS = "DEVELOPMENT_DATASET_FROZEN_NOT_FORMAL_VALIDATION"
DEVELOPMENT_PROVIDER_ID = "YFINANCE_DEVELOPMENT_HISTORICAL"
DEVELOPMENT_ADJUSTMENT_MODE = "YFINANCE_AUTO_ADJUST_TRUE"
CN_DEVELOPMENT_PROVIDER_ID = "BAOSTOCK_DEVELOPMENT_QFQ"
CN_DEVELOPMENT_ADJUSTMENT_MODE = "BAOSTOCK_QFQ_ADJUSTFLAG_2"
YFINANCE_REQUEST_METHOD = "yfinance.Ticker.history"
BAOSTOCK_REQUEST_METHOD = "baostock.query_history_k_data_plus"
BAOSTOCK_WIRE_FIELDS = (
    "date", "open", "high", "low", "close", "volume", "amount", "turn",
    "pctChg", "preclose",
)
NUMERICAL_ORDERING_RULE_VERSION = "OHLC_ORDERING_NUMERICAL_COMPARISON-IEEE754-ULP-2026-08-28-v1"
NUMERICAL_ORDERING_MAX_ULPS = 8
NUMERICAL_ORDERING_COMPARISON = {
    "rule_version": NUMERICAL_ORDERING_RULE_VERSION,
    "method": "IEEE-754 binary64 ordered-bit ULP distance",
    "max_ulps": NUMERICAL_ORDERING_MAX_ULPS,
    "price_tolerance_percent": None,
    "modifies_source_prices": False,
    "scope": "QC comparison only; no clip, round, fill, or price mutation",
}
START_DATE = date(2017, 1, 1)
END_DATE = date(2026, 8, 26)
MIN_VALID_SYMBOLS_PER_MARKET = 8
MIN_VALID_SYMBOLS_TOTAL = 40

PINNED_FORMAL_CONTRACTS = {
    "a1_manifest_sha256": "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433",
    "b0_v2_contract_sha256": "sha256:0fdfef827d48ef6deec8e58c1de1e0e470d3adb6567a1e74d25c44d8a3137588",
    "phase5j_v2_protocol_sha256": "sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0",
}
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


def ieee754_ulp_distance(first: float, second: float) -> int | None:
    """Return the exact binary64 representable-step distance for finite values."""
    first = float(first)
    second = float(second)
    if not math.isfinite(first) or not math.isfinite(second):
        return None

    def ordered_bits(value: float) -> int:
        bits = struct.unpack(">Q", struct.pack(">d", value))[0]
        sign = 1 << 63
        # Map negative binary64 values below positive values while preserving
        # adjacent representable ordering on both sides of zero.
        return (~bits + 1) & ((1 << 64) - 1) if bits & sign else bits | sign

    return abs(ordered_bits(first) - ordered_bits(second))


_ORDERING_COMPARISONS = (
    ("open > high", "open", "high"),
    ("close > high", "close", "high"),
    ("open < low", "open", "low"),
    ("close < low", "close", "low"),
    ("low > high", "low", "high"),
)


def ohlc_ordering_violations(values: Mapping[str, float]) -> list[dict[str, Any]]:
    """Describe every strict OHLC ordering violation without applying tolerance."""
    predicates = {
        "open > high": values["open"] > values["high"],
        "close > high": values["close"] > values["high"],
        "open < low": values["open"] < values["low"],
        "close < low": values["close"] < values["low"],
        "low > high": values["low"] > values["high"],
    }
    operands = {
        name: (values[left], values[right])
        for name, left, right in _ORDERING_COMPARISONS
    }
    return [
        {
            "violation_type": name,
            "left_field": left,
            "right_field": right,
            "left_value": float(operands[name][0]),
            "right_value": float(operands[name][1]),
            "absolute_violation": abs(operands[name][0] - operands[name][1]),
            "relative_violation": (
                abs(operands[name][0] - operands[name][1])
                / max(abs(operands[name][0]), abs(operands[name][1]))
                if max(abs(operands[name][0]), abs(operands[name][1]))
                else 0.0
            ),
            "ieee754_ulp_distance": ieee754_ulp_distance(
                operands[name][0], operands[name][1]
            ),
        }
        for name, left, right in _ORDERING_COMPARISONS
        if predicates[name]
    ]


def _ordering_is_valid(values: Mapping[str, float]) -> bool:
    return not ohlc_ordering_violations(values)


def _ordering_is_valid_with_numeric_rule(
    values: Mapping[str, float],
    numeric_rule: Mapping[str, Any] | None,
) -> tuple[bool, bool]:
    """Return (valid, tolerance_hit) for QC comparison only."""
    violations = ohlc_ordering_violations(values)
    if not violations:
        return True, False
    if not numeric_rule or not numeric_rule.get("enabled", True):
        return False, False
    max_ulps = int(numeric_rule.get("max_ulps", NUMERICAL_ORDERING_MAX_ULPS))
    if numeric_rule.get("rule_version") != NUMERICAL_ORDERING_RULE_VERSION:
        raise DevelopmentDataError("unsupported numerical ordering rule version")
    allowed = all(
        item["ieee754_ulp_distance"] is not None
        and item["ieee754_ulp_distance"] <= max_ulps
        for item in violations
    )
    return allowed, allowed


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


def _flatten_yfinance_download(frame: Any, symbol: str) -> Any:
    if frame is None or frame.empty:
        return frame
    columns = getattr(frame, "columns", None)
    if columns is not None and getattr(columns, "nlevels", 1) > 1:
        try:
            frame = frame.xs(symbol, axis=1, level=1)
        except (KeyError, ValueError):
            try:
                frame = frame.xs(symbol, axis=1, level=0)
            except (KeyError, ValueError) as exc:
                raise DevelopmentDataError(
                    f"yfinance download response cannot select {symbol}"
                ) from exc
    return frame


def fetch_yfinance_unadjusted_frame(
    yfinance_symbol_value: str,
    start: date = START_DATE,
    end: date = END_DATE,
) -> tuple[Any, bytes]:
    """Fetch raw OHLC plus Adj Close for provider/QC diagnosis.

    ``repair=True`` is deliberately never used.  A chart download fallback is
    used only when the ordinary Ticker history lookup returns an empty frame,
    so the raw evidence remains an unadjusted yfinance response.
    """
    try:
        import yfinance as yf

        frame = yf.Ticker(yfinance_symbol_value).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=True,
            repair=False,
        )
        method = YFINANCE_REQUEST_METHOD
        if frame is None or frame.empty:
            frame = yf.download(
                yfinance_symbol_value,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=True,
                repair=False,
                threads=False,
                progress=False,
            )
            frame = _flatten_yfinance_download(frame, yfinance_symbol_value)
            method = "yfinance.download"
    except Exception as exc:
        raise DevelopmentDataError(
            f"yfinance raw provider exception: {type(exc).__name__}: {exc}"
        ) from exc
    if frame is None or frame.empty:
        raise DevelopmentDataError("yfinance raw response has no daily bars")
    # The caller records this exact method separately where useful; the bytes
    # are always the exact DataFrame serialization returned by the request.
    frame.attrs["development_fetch_method"] = method
    return frame, _raw_frame_bytes(frame)


_BAOSTOCK_SESSION: Any | None = None


def baostock_wire_symbol(canonical_symbol: str) -> str:
    ticker, exchange = str(canonical_symbol).split(".", 1)
    exchange_code = {"SH": "sh", "SZ": "sz"}.get(exchange)
    if exchange_code is None:
        raise DevelopmentDataError(f"unsupported BaoStock exchange: {canonical_symbol}")
    return f"{exchange_code}.{ticker}"


def _baostock_session() -> Any:
    global _BAOSTOCK_SESSION
    if _BAOSTOCK_SESSION is not None:
        return _BAOSTOCK_SESSION
    try:
        import baostock as bs
        login = bs.login()
    except Exception as exc:
        raise DevelopmentDataError(
            f"BaoStock provider exception: {type(exc).__name__}: {exc}"
        ) from exc
    if str(login.error_code) != "0":
        raise DevelopmentDataError(f"BaoStock login failed: {login.error_msg}")
    _BAOSTOCK_SESSION = bs
    return bs


def close_baostock_session() -> None:
    global _BAOSTOCK_SESSION
    if _BAOSTOCK_SESSION is not None:
        try:
            _BAOSTOCK_SESSION.logout()
        finally:
            _BAOSTOCK_SESSION = None


def fetch_baostock_frame(
    canonical_symbol: str,
    start: date = START_DATE,
    end: date = END_DATE,
) -> tuple[Any, bytes]:
    """Fetch one CN daily qfq series under the frozen BaoStock contract."""
    try:
        import pandas as pd

        bs = _baostock_session()
        wire_symbol = baostock_wire_symbol(canonical_symbol)
        fields = ",".join(BAOSTOCK_WIRE_FIELDS)
        result = bs.query_history_k_data_plus(
            wire_symbol,
            fields,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="2",
        )
        rows: list[list[str]] = []
        while result.next():
            rows.append(result.get_row_data())
        if str(result.error_code) != "0":
            raise DevelopmentDataError(
                f"BaoStock query failed: {result.error_code} {result.error_msg}"
            )
        raw_payload = {
            "provider_id": CN_DEVELOPMENT_PROVIDER_ID,
            "query_method": BAOSTOCK_REQUEST_METHOD,
            "wire_symbol": wire_symbol,
            "fields": list(BAOSTOCK_WIRE_FIELDS),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "frequency": "d",
            "adjustflag": "2",
            "rows": rows,
        }
        raw_bytes = (canonical_json(raw_payload) + "\n").encode("utf-8")
        frame = pd.DataFrame(rows, columns=list(BAOSTOCK_WIRE_FIELDS))
        frame = frame.rename(columns={
            "date": "Date", "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        }).set_index("Date")
    except DevelopmentDataError:
        raise
    except Exception as exc:
        raise DevelopmentDataError(
            f"BaoStock provider exception: {type(exc).__name__}: {exc}"
        ) from exc
    if frame.empty:
        raise DevelopmentDataError("BaoStock returned no daily bars")
    return frame, raw_bytes


def _row_value(row: Any, field: str) -> Any:
    if isinstance(row, Mapping):
        if field in row:
            return row[field]
        for key, value in row.items():
            if str(key).split(",")[-1].strip("() '") == field:
                return value
        raise DevelopmentDataError(f"yfinance response missing {field}")
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
    manifest_row: Mapping[str, Any],
    frame: Any,
    *,
    provider_id: str = DEVELOPMENT_PROVIDER_ID,
    adjustment_mode: str = DEVELOPMENT_ADJUSTMENT_MODE,
    numeric_ordering_rule: Mapping[str, Any] | None = None,
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
    numeric_ordering_tolerance_hit_count = 0
    source_blank_suspension_volume_zero_count = 0
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
        }
        raw_volume = _row_value(row, "Volume")
        if (
            provider_id == CN_DEVELOPMENT_PROVIDER_ID
            and raw_volume == ""
            and all(
                _row_value(row, field) == ""
                for field in ("amount", "turn", "pctChg")
                if field in row
            )
            and values["open"] == values["high"] == values["low"] == values["close"]
        ):
            # BaoStock represents an existing suspension/no-transaction bar
            # with valid repeated OHLC and blank activity fields.  Preserve the
            # provider date/bar and normalize only that explicit zero-activity
            # semantic; never create a row or infer a missing date.
            values["volume"] = 0.0
            source_blank_suspension_volume_zero_count += 1
        else:
            values["volume"] = _finite(raw_volume, "volume")
        if any(values[field] <= 0 for field in ("open", "high", "low", "close")):
            raise DevelopmentDataError("invalid non-positive OHLC")
        if values["volume"] < 0:
            raise DevelopmentDataError("invalid negative volume")
        ordering_valid, tolerance_hit = _ordering_is_valid_with_numeric_rule(
            values, numeric_ordering_rule
        )
        if not ordering_valid:
            violations = ohlc_ordering_violations(values)
            detail = ", ".join(
                f"{item['violation_type']}={item['ieee754_ulp_distance']}ULP"
                for item in violations
            )
            raise DevelopmentDataError(f"invalid OHLC ordering ({detail})")
        if tolerance_hit:
            numeric_ordering_tolerance_hit_count += 1
        normalized = {
            "market": market,
            "canonical_symbol": symbol,
            "date": trade_date.isoformat(),
            **values,
            "source_provider": provider_id,
            "adjustment_mode": adjustment_mode,
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
            source=provider_id,
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
        "numeric_ordering_tolerance_hit_count": numeric_ordering_tolerance_hit_count,
        "source_blank_suspension_volume_zero_count": source_blank_suspension_volume_zero_count,
        "numeric_ordering_rule": (
            dict(numeric_ordering_rule)
            if numeric_ordering_rule is not None
            else {**NUMERICAL_ORDERING_COMPARISON, "enabled": False}
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
    provider_id: str = DEVELOPMENT_PROVIDER_ID,
    adjustment_mode: str = DEVELOPMENT_ADJUSTMENT_MODE,
    request_contract: Mapping[str, Any] | None = None,
    numeric_ordering_rule: Mapping[str, Any] | None = None,
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
        "provider_id": provider_id,
        "adjustment_mode": adjustment_mode,
        "retrieval_timestamp": retrieved_at,
        "request_contract": {
            "method": YFINANCE_REQUEST_METHOD,
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
    if request_contract is not None:
        base["request_contract"] = dict(request_contract)
    try:
        fetch_symbol = symbol if provider_id == CN_DEVELOPMENT_PROVIDER_ID else y_symbol
        frame, raw_bytes = fetcher(fetch_symbol, START_DATE, END_DATE)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw_bytes)
        quotes, normalized_rows, qc_metadata = _normalize_frame(
            row,
            frame,
            provider_id=provider_id,
            adjustment_mode=adjustment_mode,
            numeric_ordering_rule=numeric_ordering_rule,
        )
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


def _resolved_artifact_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _frame_by_local_date(frame: Any, market: str) -> dict[date, Any]:
    indexed = frame.reset_index()
    date_column = "Date" if "Date" in indexed.columns else "Datetime"
    if date_column not in indexed.columns:
        date_column = str(indexed.columns[0])
    return {
        _date_value(row[date_column], market): row
        for _, row in indexed.iterrows()
    }


def _action_value(row: Any, field: str) -> float:
    try:
        value = _row_value(row, field)
    except DevelopmentDataError:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def audit_historical_yfinance_ordering(
    *,
    historical_manifest_path: Path = HISTORICAL_V1_ARTIFACT_DIR / "development_dataset_manifest.json",
    output_dir: Path = DEVELOPMENT_ARTIFACT_DIR,
    raw_fetcher: Callable[[str, date, date], tuple[Any, bytes]] = fetch_yfinance_unadjusted_frame,
) -> dict[str, Any]:
    """Audit every v1 adjusted ordering violation against same-day raw yfinance.

    The function reads only the old v1 adjusted/raw artifact and yfinance raw
    OHLC evidence.  It never imports or calls Trading Core, Replay, Decision,
    or any research result.
    """
    historical = load_historical_v1_dataset_manifest(historical_manifest_path)
    failed = [
        row for row in historical.get("symbols", [])
        if row.get("qc_reason") == "invalid OHLC ordering"
    ]
    if len(failed) != 14:
        raise DevelopmentDataError(
            f"historical v1 ordering-failure symbol count changed: {len(failed)}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_audit_dir = output_dir / "raw_yfinance_unadjusted_audit"
    records: list[dict[str, Any]] = []
    symbol_stats: dict[str, dict[str, Any]] = {}
    raw_fetch_metadata: dict[str, dict[str, Any]] = {}
    for manifest_row in failed:
        market = str(manifest_row["market"])
        symbol = str(manifest_row["canonical_symbol"])
        y_symbol = str(manifest_row["yfinance_symbol"])
        adjusted_path = _resolved_artifact_path(manifest_row["raw_response_path"])
        try:
            import csv
            with adjusted_path.open("r", encoding="utf-8", newline="") as handle:
                adjusted_records = list(csv.DictReader(handle))
        except Exception as exc:
            raise DevelopmentDataError(
                f"cannot read historical v1 adjusted artifact for {symbol}: {exc}"
            ) from exc
        adjusted_by_date = {
            _date_value(record["Date"], market): record
            for record in adjusted_records
        }
        raw_frame, raw_bytes = raw_fetcher(y_symbol, START_DATE, END_DATE)
        raw_by_date = _frame_by_local_date(raw_frame, market)
        raw_path = raw_audit_dir / market / f"{_safe_path_part(symbol)}.csv"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw_bytes)
        raw_fetch_metadata[symbol] = {
            "market": market,
            "yfinance_symbol": y_symbol,
            "raw_response_path": _artifact_path(raw_path),
            "raw_response_sha256": sha256_bytes(raw_bytes),
            "fetch_method": str(getattr(raw_frame, "attrs", {}).get(
                "development_fetch_method", YFINANCE_REQUEST_METHOD
            )),
            "raw_bar_count": len(raw_by_date),
        }
        stats = {
            "market": market,
            "canonical_symbol": symbol,
            "yfinance_symbol": y_symbol,
            "violating_bar_count": 0,
            "numeric_rounding_only_bar_count": 0,
            "material_bar_count": 0,
            "raw_ordering_invalid_bar_count": 0,
            "raw_missing_bar_count": 0,
        }
        for trade_date, adjusted_row in sorted(adjusted_by_date.items()):
            adjusted_values = {
                field.lower(): _finite(
                    _row_value(adjusted_row, field), f"adjusted_{field.lower()}"
                )
                for field in ("Open", "High", "Low", "Close")
            }
            violations = ohlc_ordering_violations(adjusted_values)
            if not violations:
                continue
            stats["violating_bar_count"] += 1
            raw_row = raw_by_date.get(trade_date)
            if raw_row is None:
                stats["raw_missing_bar_count"] += 1
            raw_values: dict[str, float] | None = None
            raw_ordering_violations: list[dict[str, Any]] = []
            raw_close: float | None = None
            adj_close: float | None = None
            factor: float | None = None
            dividend = math.nan
            stock_split = math.nan
            adjustment_computation: dict[str, int | None] = {}
            expected_adjusted: dict[str, float] | None = None
            if raw_row is not None:
                raw_values = {
                    field.lower(): _finite(
                        _row_value(raw_row, field), f"raw_{field.lower()}"
                    )
                    for field in ("Open", "High", "Low", "Close")
                }
                raw_ordering_violations = ohlc_ordering_violations(raw_values)
                raw_close = raw_values["close"]
                adj_close = _finite(_row_value(raw_row, "Adj Close"), "raw_adj_close")
                factor = adj_close / raw_close if raw_close else math.nan
                dividend = _action_value(raw_row, "Dividends")
                stock_split = _action_value(raw_row, "Stock Splits")
                if math.isfinite(factor):
                    expected_adjusted = {
                        field: raw_values[field] * factor
                        for field in ("open", "high", "low", "close")
                    }
                    adjustment_computation = {
                        field: ieee754_ulp_distance(
                            adjusted_values[field], expected_adjusted[field]
                        )
                        for field in ("open", "high", "low", "close")
                    }
            factor_finite_positive = factor is not None and math.isfinite(factor) and factor > 0
            factor_reasonable = factor_finite_positive and 0.01 <= factor <= 100.0
            corporate_action_present = (
                math.isfinite(dividend) and dividend != 0.0
            ) or (math.isfinite(stock_split) and stock_split != 0.0)
            max_adjustment_ulp = max(
                (value for value in adjustment_computation.values() if value is not None),
                default=None,
            )
            numeric_only = all(
                item["ieee754_ulp_distance"] is not None
                and item["ieee754_ulp_distance"] <= NUMERICAL_ORDERING_MAX_ULPS
                for item in violations
            ) and bool(
                raw_values is not None
                and not raw_ordering_violations
                and factor_reasonable
                and not corporate_action_present
                and max_adjustment_ulp is not None
                and max_adjustment_ulp <= NUMERICAL_ORDERING_MAX_ULPS
            )
            classification = (
                "NUMERIC_ADJUSTMENT_ROUNDING_ONLY"
                if numeric_only
                else "MATERIAL_PROVIDER_OR_RAW_OHLC"
            )
            if numeric_only:
                stats["numeric_rounding_only_bar_count"] += 1
            else:
                stats["material_bar_count"] += 1
            if raw_ordering_violations:
                stats["raw_ordering_invalid_bar_count"] += 1
            for violation in violations:
                records.append({
                    "market": market,
                    "canonical_symbol": symbol,
                    "yfinance_symbol": y_symbol,
                    "date": trade_date.isoformat(),
                    **violation,
                    "adjusted_ohlc": adjusted_values,
                    "raw_ohlc": raw_values,
                    "raw_ohlc_ordering_valid": (
                        raw_values is not None and not raw_ordering_violations
                    ),
                    "raw_ohlc_violations": raw_ordering_violations,
                    "raw_close": raw_close,
                    "adj_close": adj_close,
                    "implied_adjustment_factor": factor,
                    "adjustment_factor_finite_positive": factor_finite_positive,
                    "adjustment_factor_reasonable_0_01_to_100": factor_reasonable,
                    "raw_dividends": dividend,
                    "raw_stock_splits": stock_split,
                    "corporate_action_present_on_bar": corporate_action_present,
                    "expected_adjusted_ohlc_raw_times_factor": expected_adjusted,
                    "adjustment_computation_ulp_distance": adjustment_computation,
                    "adjustment_computation_max_ulp_distance": max_adjustment_ulp,
                    "yfinance_auto_adjust_float_explanation": numeric_only,
                    "classification": classification,
                    "raw_response_sha256": raw_fetch_metadata[symbol]["raw_response_sha256"],
                    "raw_response_path": raw_fetch_metadata[symbol]["raw_response_path"],
                })
        symbol_stats[symbol] = stats

    records.sort(key=lambda row: (row["market"], row["canonical_symbol"], row["date"], row["violation_type"]))
    distinct_bars = {
        (row["market"], row["canonical_symbol"], row["date"])
        for row in records
    }
    summary = {
        "failed_symbol_count": len(failed),
        "violating_bar_count": len(distinct_bars),
        "violation_record_count": len(records),
        "numeric_ordering_tolerance_hit_count": sum(
            value["numeric_rounding_only_bar_count"] for value in symbol_stats.values()
        ),
        "classification_counts": {
            label: sum(row["classification"] == label for row in records)
            for label in ("NUMERIC_ADJUSTMENT_ROUNDING_ONLY", "MATERIAL_PROVIDER_OR_RAW_OHLC")
        },
        "violation_type_counts": {
            label: sum(row["violation_type"] == label for row in records)
            for label, _, _ in _ORDERING_COMPARISONS
        },
        "market_counts": {
            market: sum(row["market"] == market for row in records)
            for market in ("CN", "US")
        },
        "symbol_stats": symbol_stats,
    }
    payload = {
        "schema_version": "setup03-yfinance-ohlc-ordering-diagnostic-v1",
        "diagnostic_version": "SETUP_03-YFINANCE-OHLC-ORDERING-DIAGNOSTIC-2026-08-28-v1",
        "artifact_labels": list(DEVELOPMENT_LABELS),
        "source_dataset": {
            "dataset_version": historical["dataset_version"],
            "dataset_manifest_sha256": historical["integrity"]["manifest_sha256"],
            "aggregate_dataset_sha256": historical["aggregate_dataset_sha256"],
            "immutable_historical_evidence": True,
        },
        "scope": {
            "markets": ["CN", "US"],
            "failed_symbols": [row["canonical_symbol"] for row in failed],
            "setup03_results_read": False,
            "formal_phase5k_results_read": False,
            "final_oos_read": False,
        },
        "raw_request_contract": {
            "method": "yfinance.Ticker.history (fallback yfinance.download only when empty)",
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
            "repair": False,
            "date_window": {"start": START_DATE.isoformat(), "end": END_DATE.isoformat(), "inclusive": True},
            "local_trading_date_semantics": {"CN": "Asia/Shanghai", "US": "America/New_York"},
        },
        "numerical_ordering_rule": {
            **NUMERICAL_ORDERING_COMPARISON,
            "enabled": True,
            "classification_requires_raw_valid_and_no_material_anomaly": True,
        },
        "summary": summary,
        "raw_fetch_metadata": raw_fetch_metadata,
        "violations": records,
    }
    payload["integrity"] = {
        "artifact_sha256": sha256_bytes(canonical_json(payload).encode("utf-8"))
    }
    json_path = output_dir / "yfinance_ohlc_ordering_diagnostic.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_fields = [
        "market", "canonical_symbol", "yfinance_symbol", "date", "violation_type",
        "left_field", "right_field", "left_value", "right_value",
        "absolute_violation", "relative_violation", "ieee754_ulp_distance",
        "adjusted_ohlc", "raw_ohlc", "raw_ohlc_ordering_valid", "raw_ohlc_violations",
        "raw_close", "adj_close", "implied_adjustment_factor",
        "adjustment_factor_finite_positive", "adjustment_factor_reasonable_0_01_to_100",
        "raw_dividends", "raw_stock_splits", "corporate_action_present_on_bar",
        "expected_adjusted_ohlc_raw_times_factor", "adjustment_computation_ulp_distance",
        "adjustment_computation_max_ulp_distance", "yfinance_auto_adjust_float_explanation",
        "classification", "raw_response_sha256", "raw_response_path",
    ]
    import csv
    csv_path = output_dir / "yfinance_ohlc_ordering_diagnostic.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                field: (
                    json.dumps(record[field], ensure_ascii=False, sort_keys=True)
                    if isinstance(record.get(field), (dict, list))
                    else record.get(field)
                )
                for field in csv_fields
            })
    return {
        "diagnostic_version": payload["diagnostic_version"],
        "artifact_path": _artifact_path(json_path),
        "artifact_sha256": payload["integrity"]["artifact_sha256"],
        "csv_path": _artifact_path(csv_path),
        "csv_sha256": sha256_bytes(csv_path.read_bytes()),
        "summary": summary,
    }


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
    ordering_diagnostic: Mapping[str, Any] | None = None,
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
        "provider_split": {
            "CN": CN_DEVELOPMENT_PROVIDER_ID,
            "US": DEVELOPMENT_PROVIDER_ID,
        },
        "provider_contract": {
            "CN": {
                "provider_id": CN_DEVELOPMENT_PROVIDER_ID,
                "query_method": BAOSTOCK_REQUEST_METHOD,
                "symbol_mapping": "canonical .SH -> sh.<ticker>; canonical .SZ -> sz.<ticker>",
                "date_window": {
                    "start": START_DATE.isoformat(),
                    "end": END_DATE.isoformat(),
                    "inclusive": True,
                },
                "frequency": "d",
                "qfq": True,
                "adjustflag": "2",
                "local_trading_date_semantics": "Asia/Shanghai security-local calendar date",
                "raw_provenance": "canonical UTF-8 JSON of exact query fields and BaoStock get_row_data strings in provider order",
                "normalized_hash": "canonical JSONL of validated normalized bars with float.hex hash projection",
                "snapshot_sources_are_not_mixed_into_history": True,
            },
            "US": {
                "provider_id": DEVELOPMENT_PROVIDER_ID,
                "query_method": YFINANCE_REQUEST_METHOD,
                "symbol_mapping": "canonical US symbol unchanged",
                "date_window": {
                    "start": START_DATE.isoformat(),
                    "end": END_DATE.isoformat(),
                    "inclusive": True,
                },
                "interval": "1d",
                "auto_adjust": True,
                "actions": False,
                "repair": False,
                "local_trading_date_semantics": "America/New_York security-local calendar date",
                "raw_provenance": "exact UTF-8 bytes of the yfinance DataFrame CSV serialization before normalization",
                "normalized_hash": "canonical JSONL of validated normalized bars with float.hex hash projection",
                "snapshot_sources_are_not_mixed_into_history": True,
            },
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
            "baostock_blank_suspension_volume": (
                "existing provider bar with valid equal OHLC and all activity fields blank is normalized to volume=0; no row is fabricated"
            ),
            "ohlc_ordering_comparison": {
                **NUMERICAL_ORDERING_COMPARISON,
                "enabled_for_yfinance_qc": True,
                "enabled_for_baostock_qc": False,
            },
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
        "historical_yfinance_ohlc_diagnostic": dict(ordering_diagnostic) if ordering_diagnostic else None,
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
            "cn_provider_uniform_across_frozen_universe": True,
            "provider_selected_before_setup03": True,
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
    if manifest.get("formal_contract_pins") != PINNED_FORMAL_CONTRACTS:
        raise ValueError("formal contract pin changed")
    if manifest.get("provider_split") != {
        "CN": CN_DEVELOPMENT_PROVIDER_ID,
        "US": DEVELOPMENT_PROVIDER_ID,
    }:
        raise ValueError("development provider split changed")
    return manifest


def load_historical_v1_dataset_manifest(
    path: Path = HISTORICAL_V1_ARTIFACT_DIR / "development_dataset_manifest.json",
) -> dict[str, Any]:
    """Load the old yfinance-only manifest as immutable audit evidence."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != HISTORICAL_V1_DATASET_SCHEMA_VERSION:
        raise ValueError("historical v1 dataset schema changed")
    if manifest.get("dataset_version") != HISTORICAL_V1_DATASET_VERSION:
        raise ValueError("historical v1 dataset version changed")
    if manifest.get("integrity", {}).get("manifest_sha256") != dataset_manifest_integrity_hash(manifest):
        raise ValueError("historical v1 dataset manifest integrity mismatch")
    if manifest["integrity"]["manifest_sha256"] != HISTORICAL_V1_DATASET_MANIFEST_SHA256:
        raise ValueError("historical v1 dataset manifest hash changed")
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
                 source=str(row.get("provider_id") or record.get("source_provider") or DEVELOPMENT_PROVIDER_ID),
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
    fetcher: Callable[[str, date, date], tuple[Any, bytes]] | None = None,
    ordering_diagnostic: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[Quote]]]:
    universe = load_development_universe_manifest(universe_path)
    raw_dir_by_provider = {
        "CN": output_dir / "raw_baostock",
        "US": output_dir / "raw_yfinance",
    }
    normalized_dir = output_dir / "normalized_bars"
    acquired: list[AcquiredSymbol] = []
    try:
        for row in universe["symbols"]:
            market = str(row["market"])
            if market == "CN":
                provider_id = CN_DEVELOPMENT_PROVIDER_ID
                adjustment_mode = CN_DEVELOPMENT_ADJUSTMENT_MODE
                provider_fetcher = fetcher or fetch_baostock_frame
                request_contract = {
                    "method": BAOSTOCK_REQUEST_METHOD,
                    "wire_symbol": baostock_wire_symbol(str(row["canonical_symbol"])),
                    "fields": list(BAOSTOCK_WIRE_FIELDS),
                    "start_date": START_DATE.isoformat(),
                    "end_date": END_DATE.isoformat(),
                    "frequency": "d",
                    "adjustflag": "2",
                    "local_trading_date_timezone": "Asia/Shanghai",
                }
                numeric_rule = {**NUMERICAL_ORDERING_COMPARISON, "enabled": False}
            elif market == "US":
                provider_id = DEVELOPMENT_PROVIDER_ID
                adjustment_mode = DEVELOPMENT_ADJUSTMENT_MODE
                provider_fetcher = fetcher or fetch_yfinance_frame
                request_contract = {
                    "method": YFINANCE_REQUEST_METHOD,
                    "symbol": str(row["yfinance_symbol"]),
                    "start": START_DATE.isoformat(),
                    "end": END_DATE.isoformat(),
                    "end_wire_is_exclusive": True,
                    "interval": "1d",
                    "auto_adjust": True,
                    "actions": False,
                    "repair": False,
                    "local_trading_date_timezone": "America/New_York",
                }
                numeric_rule = {**NUMERICAL_ORDERING_COMPARISON, "enabled": True}
            else:
                raise DevelopmentDataError(f"unsupported development market: {market}")
            acquired.append(
                acquire_symbol(
                    row,
                    raw_dir=raw_dir_by_provider[market],
                    normalized_dir=normalized_dir,
                    fetcher=provider_fetcher,
                    provider_id=provider_id,
                    adjustment_mode=adjustment_mode,
                    request_contract=request_contract,
                    numeric_ordering_rule=numeric_rule,
                )
            )
    finally:
        close_baostock_session()
    provisional, symbol_quotes, _ = build_dataset_manifest(
        universe, acquired, ordering_diagnostic=ordering_diagnostic
    )
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
            "provider_split": {"CN": CN_DEVELOPMENT_PROVIDER_ID, "US": DEVELOPMENT_PROVIDER_ID},
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
        ordering_diagnostic=ordering_diagnostic,
    )
    write_dataset_manifest(output_dir / "development_dataset_manifest.json", manifest)
    return manifest, symbol_quotes

"""Phase 5K-B0 development-validation dataset acquisition contract.

This module freezes the acquisition, normalization, QC, replacement, coverage,
and warmup rules for the future development-validation dataset.  It deliberately
contains no network client and does not import production quote, replay, or
trading modules.  B1 may consume these pure validators after the contract and
the A1 roster have been independently reviewed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from research.phase5k_a1_universe import load_manifest
from research.structural_validation_protocol_v2 import load_protocol


HISTORICAL_CONTRACT_V1_PATH = Path(__file__).with_name("phase5k_b0_dataset_acquisition_contract.json")
CONTRACT_PATH = Path(__file__).with_name("phase5k_b0_dataset_acquisition_contract_v2.json")
CONTRACT_SCHEMA_VERSION = "setup03-phase5k-b0-dataset-acquisition-contract-v2"
CONTRACT_VERSION = "SETUP_03-PHASE5K-B0-DATASET-ACQUISITION-CONTRACT-2026-08-27-v2"
CONTRACT_STATUS = "DATASET_ACQUISITION_CONTRACT_FROZEN_NOT_ACQUIRED"
HISTORICAL_CONTRACT_V1_VERSION = "SETUP_03-PHASE5K-B0-DATASET-ACQUISITION-CONTRACT-2026-08-27-v1"
HISTORICAL_CONTRACT_V1_SHA256 = "sha256:daed425278bf7b2cca00ede87b56dddc3bc9d47be51508a6800369105f2da039"

EXPECTED_PROTOCOL_VERSION = "SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v2-CN-US"
EXPECTED_PROTOCOL_SHA256 = "sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0"
EXPECTED_MANIFEST_VERSION = "SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v2"
EXPECTED_MANIFEST_SHA256 = "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433"
EXPECTED_MANIFEST_STATUS = "MANIFEST_FROZEN_NOT_FETCHED"

DATE_START = date(2017, 1, 1)
DATE_END = date(2026, 8, 26)
CN_CONVERSION_TIMEZONE = "Asia/Shanghai"
US_CONVERSION_TIMEZONE = "US/Eastern"
VALIDATION_MARKETS = ("CN", "US")
TARGET_ROSTER_BY_MARKET = {"CN": 40, "US": 40}
RESERVE_TARGET_BY_MARKET = {"CN": 20, "US": 20}
MIN_VALID_SYMBOLS_PER_MARKET = 8
MIN_VALID_SYMBOLS_TOTAL = 40
MIN_VALID_DAILY_BARS_PER_MARKET = 6000
PLATFORM_WINDOW = 40
SETUP_SWING_LOOKBACK = 5
WARMUP_BARS = max(PLATFORM_WINDOW, 2 * SETUP_SWING_LOOKBACK)
PROVIDER_BY_MARKET = {
    "CN": "HITHINK_A_SHARE_HISTORICAL_FORWARD_ADJUSTED",
    "US": "IBKR_TWS_API_ADJUSTED_LAST",
}
ADJUSTMENT_MODE_BY_MARKET = {"CN": "forward", "US": "ADJUSTED_LAST"}
VALID_ACCEPTED_STATUS = "VALID_ACCEPTED"
FINAL_ROSTER_VALIDITY_MISMATCH_STATUS = "FINAL_ROSTER_VALIDITY_MISMATCH"
TARGET_ROSTER_SHORTFALL_STATUS = "TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW"
INSUFFICIENT_COVERAGE_STATUS = "INSUFFICIENT_COVERAGE"
DATASET_READINESS_STATUS = "DATASET_READINESS_OK"


class ContractViolation(ValueError):
    """Raised when a B0 contract, bar, roster, or coverage invariant fails."""


def local_datetime_to_unix_ms(value: datetime, timezone_name: str) -> int:
    """Convert a naive local wall-clock datetime to deterministic Unix ms."""
    if value.tzinfo is not None:
        raise ContractViolation("wire boundary must be a naive local datetime")
    local = value.replace(tzinfo=ZoneInfo(timezone_name))
    utc = local.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = utc - epoch
    return (delta.days * 86_400_000) + (delta.seconds * 1_000) + (delta.microseconds // 1_000)


CN_WIRE_START_MS = local_datetime_to_unix_ms(
    datetime(2017, 1, 1, 0, 0, 0, 0), CN_CONVERSION_TIMEZONE
)
CN_WIRE_END_MS = local_datetime_to_unix_ms(
    datetime(2026, 8, 26, 23, 59, 59, 999_000), CN_CONVERSION_TIMEZONE
)
IBKR_DURATION_STR = "1 Y"
IBKR_BAR_SIZE_SETTING = "1 day"
IBKR_WHAT_TO_SHOW = "ADJUSTED_LAST"

CANONICAL_BAR_FIELDS = (
    "market",
    "canonical_symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source_provider",
    "adjustment_mode",
)
PRICE_FIELDS = ("open", "high", "low", "close")
VALUE_FIELDS = PRICE_FIELDS + ("volume",)

ALLOWED_REPLACEMENT_REASONS = (
    "SYMBOL_NOT_RESOLVABLE",
    "PROVIDER_NO_DATA",
    "FATAL_OHLC_INTEGRITY_FAILURE",
    "DUPLICATE_IDENTITY_CONFLICT",
    "INSUFFICIENT_FOR_REQUIRED_WARMUP",
)
FORBIDDEN_REPLACEMENT_REASONS = (
    "CONFIRMED_COUNT",
    "SIGNAL_QUALITY",
    "PERFORMANCE",
    "RETURN",
    "MFE",
    "MAE",
    "WIN_RATE",
    "P_AND_L",
    "PARAMETER_RESULT",
)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def contract_integrity_hash(contract: Mapping[str, Any]) -> str:
    """Hash every contract field except the stored integrity envelope."""
    payload = dict(contract)
    payload.pop("integrity", None)
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def serialize_contract(contract: Mapping[str, Any]) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2) + "\n"


def _validate_historical_v1(path: Path = HISTORICAL_CONTRACT_V1_PATH) -> dict[str, Any]:
    historical = json.loads(path.read_text(encoding="utf-8"))
    if historical.get("contract_version") != HISTORICAL_CONTRACT_V1_VERSION:
        raise ContractViolation("historical B0 v1 contract version changed")
    if historical.get("integrity", {}).get("contract_sha256") != HISTORICAL_CONTRACT_V1_SHA256:
        raise ContractViolation("historical B0 v1 stored hash changed")
    if contract_integrity_hash(historical) != HISTORICAL_CONTRACT_V1_SHA256:
        raise ContractViolation("historical B0 v1 canonical hash changed")
    return historical


def _validate_parent_bindings(contract: Mapping[str, Any]) -> None:
    protocol = load_protocol()
    parent_protocol = contract["parent_protocol"]
    if (
        protocol["protocol_version"] != EXPECTED_PROTOCOL_VERSION
        or protocol["integrity"]["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256
        or parent_protocol["version"] != EXPECTED_PROTOCOL_VERSION
        or parent_protocol["sha256"] != EXPECTED_PROTOCOL_SHA256
        or parent_protocol["status"] != protocol["phase5j_status"]
    ):
        raise ContractViolation("parent protocol exact pinned identity changed")

    manifest = load_manifest()
    parent_manifest = contract["parent_a1_manifest"]
    if (
        manifest["manifest_version"] != EXPECTED_MANIFEST_VERSION
        or manifest["integrity"]["manifest_sha256"] != EXPECTED_MANIFEST_SHA256
        or manifest["status"] != EXPECTED_MANIFEST_STATUS
        or parent_manifest["version"] != EXPECTED_MANIFEST_VERSION
        or parent_manifest["sha256"] != EXPECTED_MANIFEST_SHA256
        or parent_manifest["status"] != EXPECTED_MANIFEST_STATUS
    ):
        raise ContractViolation("A1 manifest v2 exact pinned identity changed")


def _validate_contract_shape(contract: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "contract_version",
        "phase",
        "status",
        "historical_contract_v1",
        "parent_protocol",
        "parent_a1_manifest",
        "date_window",
        "providers",
        "canonical_bar_schema",
        "raw_source_metadata",
        "qc_rules",
        "duplicate_rules",
        "missing_bar_rules",
        "reserve_activation_rules",
        "coverage_rules",
        "warmup_rules",
        "b1_manifest_schema",
        "forbidden_metrics_and_actions",
        "integrity",
    }
    missing = required.difference(contract)
    if missing:
        raise ContractViolation(f"B0 contract missing keys: {sorted(missing)}")
    historical = contract["historical_contract_v1"]
    if (
        historical["version"] != HISTORICAL_CONTRACT_V1_VERSION
        or historical["sha256"] != HISTORICAL_CONTRACT_V1_SHA256
        or historical["path"] != "research/phase5k_b0_dataset_acquisition_contract.json"
    ):
        raise ContractViolation("historical B0 v1 binding changed")
    _validate_historical_v1()
    if contract["schema_version"] != CONTRACT_SCHEMA_VERSION:
        raise ContractViolation("B0 contract schema version changed")
    if contract["contract_version"] != CONTRACT_VERSION:
        raise ContractViolation("B0 contract version changed")
    if contract["phase"] != "Phase 5K-B0":
        raise ContractViolation("B0 phase identity changed")
    if contract["status"] != CONTRACT_STATUS:
        raise ContractViolation("B0 contract must remain frozen and not acquired")
    if contract["integrity"].get("contract_sha256") != contract_integrity_hash(contract):
        raise ContractViolation("B0 contract integrity mismatch")
    if contract["integrity"].get("contract_sha256") != PINNED_CONTRACT_SHA256:
        raise ContractViolation("B0 contract version is bound to a different canonical hash")

    _validate_parent_bindings(contract)

    window = contract["date_window"]
    if (
        window["start_date"] != DATE_START.isoformat()
        or window["end_date"] != DATE_END.isoformat()
        or window["inclusive"] is not True
        or window["date_semantics"] != "security_local_exchange_trading_date"
    ):
        raise ContractViolation("B0 date window changed")

    schema = contract["canonical_bar_schema"]
    if tuple(schema["fields"]) != CANONICAL_BAR_FIELDS:
        raise ContractViolation("canonical bar schema changed")
    if schema["forward_fill_allowed"] is not False or schema["interpolation_allowed"] is not False or schema["synthetic_bars_allowed"] is not False:
        raise ContractViolation("canonical bar schema prohibition flags changed")

    providers = contract["providers"]
    cn = providers["CN"]
    cn_request = cn["request_contract"]
    if (
        cn["provider_id"] != "HITHINK_A_SHARE_HISTORICAL_FORWARD_ADJUSTED"
        or cn["endpoint_path"] != "/api/a-share/prices/historical"
        or cn_request["wire_parameters"] != ["thscode", "interval", "start", "end", "adjust"]
        or cn_request["thscode_binding"] != "canonical_symbol"
        or cn_request["interval"] != "1d"
        or cn_request["start"] != CN_WIRE_START_MS
        or cn_request["end"] != CN_WIRE_END_MS
        or cn_request["adjust"] != "forward"
        or cn_request["conversion_timezone"] != CN_CONVERSION_TIMEZONE
        or cn_request["response_local_date_filter"] != {
            "field": "security_local_exchange_trading_date",
            "start_date": DATE_START.isoformat(),
            "end_date": DATE_END.isoformat(),
            "inclusive": True,
        }
        or cn["api_key_env"] != "HITHINK_FINANCE_API_KEY"
        or cn["formal_fallback_allowed"] is not False
    ):
        raise ContractViolation("CN provider contract changed")
    us = providers["US"]
    us_request = us["request_contract"]
    us_contract = us["contract_wire_fields"]
    if (
        us["provider_id"] != "IBKR_TWS_API_ADJUSTED_LAST"
        or us_contract != {
            "symbol": "canonical_symbol",
            "conId": "B1-resolved-unique-conId-frozen-before-first-history-request",
            "secType": "STK",
            "exchange": "SMART",
            "primaryExchange": "B1-resolved-frozen-primaryExchange",
            "currency": "B1-resolved-frozen-currency",
        }
        or us_request["wire_parameters"] != [
            "endDateTime", "durationStr", "barSizeSetting", "whatToShow",
            "useRTH", "formatDate", "keepUpToDate", "chartOptions",
        ]
        or us_request["barSizeSetting"] != IBKR_BAR_SIZE_SETTING
        or us_request["whatToShow"] != IBKR_WHAT_TO_SHOW
        or us_request["useRTH"] != 1
        or us_request["formatDate"] != 1
        or us_request["keepUpToDate"] is not False
        or us_request["chartOptions"] != []
        or us_request["timezone"] != US_CONVERSION_TIMEZONE
        or us_request["durationStr"] != IBKR_DURATION_STR
        or us["identity_resolution"]["required_before_first_history_request"] is not True
        or us["identity_resolution"]["api_version_field"] != "api_version"
        or us["identity_resolution"]["tws_version_field"] != "tws_version"
        or us["identity_resolution"]["contract_identity_source"] != "B1_IBKR_RESOLVED_CONTRACT_DETAILS"
        or us["identity_resolution"]["freeze_before_first_history_request"] is not True
        or us["calendar_chunking"]["dynamic_return_driven_chunk_selection"] is not False
        or us["calendar_chunking"]["overlap_rule"] != "only exact normalized duplicate bars may be deduplicated deterministically; any conflict fails closed"
    ):
        raise ContractViolation("US provider contract changed")
    chunks = us["calendar_chunking"]["chunks"]
    if tuple(
        {"chunk_id": row["chunk_id"], "start_date": row["start_date"], "end_date": row["end_date"]}
        for row in chunks
    ) != IBKR_CALENDAR_CHUNKS or any(
        row["wire"] != {
            "endDateTime": build_ibkr_req_historical_data_wire(row)["endDateTime"],
            "durationStr": build_ibkr_req_historical_data_wire(row)["durationStr"],
        }
        for row in chunks
    ):
        raise ContractViolation("IBKR calendar chunk wire conversion changed")

    coverage = contract["coverage_rules"]
    if (
        coverage["markets"] != list(VALIDATION_MARKETS)
        or coverage["target_roster_by_market"] != TARGET_ROSTER_BY_MARKET
        or coverage["reserve_target_by_market"] != RESERVE_TARGET_BY_MARKET
        or coverage["minimum_valid_symbols_per_market"] != MIN_VALID_SYMBOLS_PER_MARKET
        or coverage["minimum_valid_symbols_total"] != MIN_VALID_SYMBOLS_TOTAL
        or coverage["minimum_valid_daily_bars_per_market"] != MIN_VALID_DAILY_BARS_PER_MARKET
        or coverage["market_compensation_allowed"] is not False
        or coverage["final_roster_must_contain_only_valid_accepted_symbols"] is not True
        or coverage["final_roster_count_equals_valid_symbols_invariant"] is not True
        or coverage["dataset_readiness_requires_target_roster_per_market"] is not True
    ):
        raise ContractViolation("coverage requirements changed")

    warmup = contract["warmup_rules"]
    if (
        warmup["platform_window"] != PLATFORM_WINDOW
        or warmup["setup_swing_lookback"] != SETUP_SWING_LOOKBACK
        or warmup["excluded_prefix_bars"] != WARMUP_BARS
        or warmup["warmup_bars_count_as_evaluable_state_days"] is not False
    ):
        raise ContractViolation("warmup dependency changed")

    replacement = contract["reserve_activation_rules"]
    if tuple(replacement["allowed_replacement_reasons"]) != ALLOWED_REPLACEMENT_REASONS:
        raise ContractViolation("allowed replacement reasons changed")
    if tuple(replacement["forbidden_signal_or_performance_reasons"]) != FORBIDDEN_REPLACEMENT_REASONS:
        raise ContractViolation("signal/performance replacement prohibition changed")
    if replacement["strict_frozen_rank_order"] is not True:
        raise ContractViolation("reserve rank ordering was weakened")
    if replacement["final_roster_lock_status"] != "FINAL_DATASET_ROSTER_LOCKED":
        raise ContractViolation("final roster lock status changed")

    b1 = contract["b1_manifest_schema"]
    if b1["success_status"] != "DEVELOPMENT_VALIDATION_DATASET_FROZEN_NOT_EVALUATED":
        raise ContractViolation("B1 success status changed")
    if b1["must_bind_active_contract_version"] != CONTRACT_VERSION:
        raise ContractViolation("B1 must bind the active B0 v2 contract")
    if b1["must_not_be_generated_in_b0"] is not True:
        raise ContractViolation("B0 must not generate B1 status was weakened")


# This is intentionally a literal immutable version/hash contract.  Once the
# JSON is finalized, changing content requires a new contract version.
PINNED_CONTRACT_SHA256 = "sha256:0fdfef827d48ef6deec8e58c1de1e0e470d3adb6567a1e74d25c44d8a3137588"


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    _validate_contract_shape(contract)
    return contract


def load_historical_contract_v1(path: Path = HISTORICAL_CONTRACT_V1_PATH) -> dict[str, Any]:
    """Load only the immutable v1 audit evidence, never as the active contract."""
    return _validate_historical_v1(path)


def _as_local_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        raise ContractViolation(f"{field} must be a security local date, not datetime")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ContractViolation(f"{field} is not an ISO date") from exc
    raise ContractViolation(f"{field} is not an ISO date")


def build_cn_wire_request(canonical_symbol: str) -> dict[str, Any]:
    """Return the exact frozen HiThink query parameters for one symbol."""
    if not isinstance(canonical_symbol, str) or not canonical_symbol:
        raise ContractViolation("CN wire request requires a canonical symbol")
    return {
        "thscode": canonical_symbol,
        "interval": "1d",
        "start": CN_WIRE_START_MS,
        "end": CN_WIRE_END_MS,
        "adjust": "forward",
    }


def filter_security_local_date_rows(
    rows: Iterable[Mapping[str, Any]],
    start_date: date | str,
    end_date: date | str,
) -> list[Mapping[str, Any]]:
    """Apply the final inclusive security-local date filter without filling rows."""
    start = _as_local_date(start_date, "filter start_date")
    end = _as_local_date(end_date, "filter end_date")
    if start > end:
        raise ContractViolation("local date filter range is inverted")
    filtered: list[Mapping[str, Any]] = []
    for row in rows:
        row_date = _as_local_date(row["date"], "row date")
        if start <= row_date <= end:
            filtered.append(row)
    return filtered


def filter_cn_response_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Filter a HiThink response after converting its date to the local date."""
    return filter_security_local_date_rows(rows, DATE_START, DATE_END)


def _registered_ibkr_chunks() -> tuple[dict[str, str], ...]:
    chunks: list[dict[str, str]] = []
    for year in range(DATE_START.year, DATE_END.year + 1):
        chunk_start = date(year, 1, 1)
        chunk_end = DATE_END if year == DATE_END.year else date(year, 12, 31)
        chunks.append({
            "chunk_id": str(year),
            "start_date": chunk_start.isoformat(),
            "end_date": chunk_end.isoformat(),
        })
    return tuple(chunks)


IBKR_CALENDAR_CHUNKS = _registered_ibkr_chunks()


def _registered_ibkr_chunk(chunk: Mapping[str, Any]) -> dict[str, str]:
    chunk_id = str(chunk.get("chunk_id", ""))
    expected = next((row for row in IBKR_CALENDAR_CHUNKS if row["chunk_id"] == chunk_id), None)
    if expected is None or {
        "chunk_id": chunk_id,
        "start_date": _as_local_date(chunk.get("start_date"), "chunk start_date").isoformat(),
        "end_date": _as_local_date(chunk.get("end_date"), "chunk end_date").isoformat(),
    } != expected:
        raise ContractViolation("IBKR calendar chunk is not the pre-registered deterministic chunk")
    return expected


def build_ibkr_contract_wire(
    canonical_symbol: str,
    con_id: int,
    primary_exchange: str,
    currency: str,
) -> dict[str, Any]:
    """Return the resolved/frozen IBKR Contract fields used by B1."""
    if not isinstance(canonical_symbol, str) or not canonical_symbol:
        raise ContractViolation("IBKR contract requires a canonical symbol")
    if isinstance(con_id, bool) or not isinstance(con_id, int) or con_id <= 0:
        raise ContractViolation("IBKR contract requires a positive unique conId")
    if not isinstance(primary_exchange, str) or not primary_exchange:
        raise ContractViolation("IBKR contract requires a frozen primaryExchange")
    if not isinstance(currency, str) or not currency:
        raise ContractViolation("IBKR contract requires a frozen currency")
    return {
        "symbol": canonical_symbol,
        "conId": con_id,
        "secType": "STK",
        "exchange": "SMART",
        "primaryExchange": primary_exchange,
        "currency": currency,
    }


def build_ibkr_req_historical_data_wire(chunk: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete deterministic reqHistoricalData argument contract."""
    registered = _registered_ibkr_chunk(chunk)
    return {
        "endDateTime": f"{registered['end_date'].replace('-', '')} 23:59:59 {US_CONVERSION_TIMEZONE}",
        "durationStr": IBKR_DURATION_STR,
        "barSizeSetting": IBKR_BAR_SIZE_SETTING,
        "whatToShow": IBKR_WHAT_TO_SHOW,
        "useRTH": 1,
        "formatDate": 1,
        "keepUpToDate": False,
        "chartOptions": [],
    }


def build_ibkr_wire_request(
    canonical_symbol: str,
    con_id: int,
    primary_exchange: str,
    currency: str,
    chunk: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the frozen Contract plus reqHistoricalData wire arguments."""
    return {
        "contract": build_ibkr_contract_wire(canonical_symbol, con_id, primary_exchange, currency),
        "reqHistoricalData": build_ibkr_req_historical_data_wire(chunk),
    }


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractViolation(f"INVALID_OHLC_FAIL_CLOSED: {field} is not numeric")
    try:
        numeric = float(value)
    except (OverflowError, ValueError) as exc:
        raise ContractViolation(f"INVALID_OHLC_FAIL_CLOSED: {field} is not finite") from exc
    if not math.isfinite(numeric):
        raise ContractViolation(f"INVALID_OHLC_FAIL_CLOSED: {field} is not finite")
    return numeric


def normalize_bar(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Project one provider record to the frozen canonical bar schema.

    Extra provider fields are intentionally excluded and must be retained in
    the separate raw-source metadata record.  No date rows are generated.
    """
    missing = set(CANONICAL_BAR_FIELDS).difference(raw)
    if missing:
        raise ContractViolation(f"canonical bar missing fields: {sorted(missing)}")
    bar = {
        "market": str(raw["market"]),
        "canonical_symbol": str(raw["canonical_symbol"]),
        "date": _as_local_date(raw["date"], "date").isoformat(),
        "open": _finite_number(raw["open"], "open"),
        "high": _finite_number(raw["high"], "high"),
        "low": _finite_number(raw["low"], "low"),
        "close": _finite_number(raw["close"], "close"),
        "volume": _finite_number(raw["volume"], "volume"),
        "source_provider": str(raw["source_provider"]),
        "adjustment_mode": str(raw["adjustment_mode"]),
    }
    if bar["market"] not in VALIDATION_MARKETS:
        raise ContractViolation("unsupported validation market")
    if (
        bar["source_provider"] != PROVIDER_BY_MARKET[bar["market"]]
        or bar["adjustment_mode"] != ADJUSTMENT_MODE_BY_MARKET[bar["market"]]
    ):
        raise ContractViolation("ADJUSTMENT_SEMANTICS_FAIL_CLOSED: provider semantics are mixed")
    if any(bar[field] <= 0 for field in PRICE_FIELDS):
        raise ContractViolation("INVALID_OHLC_FAIL_CLOSED: OHLC must be > 0")
    if bar["volume"] < 0:
        raise ContractViolation("INVALID_OHLC_FAIL_CLOSED: volume must be >= 0")
    if not (
        bar["low"] <= bar["open"] <= bar["high"]
        and bar["low"] <= bar["close"] <= bar["high"]
        and bar["low"] <= bar["high"]
    ):
        raise ContractViolation("INVALID_OHLC_FAIL_CLOSED: OHLC ordering is invalid")
    bar_date = date.fromisoformat(bar["date"])
    if not (DATE_START <= bar_date <= DATE_END):
        raise ContractViolation("bar date is outside the frozen inclusive date window")
    return bar


def validate_bars(bars: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate bars without deduplicating them; duplicate dates fail closed."""
    normalized = [normalize_bar(bar) for bar in bars]
    seen: set[tuple[str, str, str]] = set()
    for bar in normalized:
        key = (bar["market"], bar["canonical_symbol"], bar["date"])
        if key in seen:
            raise ContractViolation("duplicate symbol/date is not allowed before dedupe")
        seen.add(key)
    return sorted(normalized, key=lambda item: (item["canonical_symbol"], item["date"]))


def _value_tuple(bar: Mapping[str, Any]) -> tuple[float, ...]:
    return tuple(float(bar[field]) for field in VALUE_FIELDS)


def deduplicate_bars(bars: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministically dedupe exact canonical values and reject conflicts."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in bars:
        bar = normalize_bar(raw)
        key = (bar["market"], bar["canonical_symbol"], bar["date"])
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = bar
        elif _value_tuple(existing) != _value_tuple(bar):
            raise ContractViolation("DATA_CONFLICT_FAIL_CLOSED: conflicting duplicate symbol/date")
    return sorted(by_key.values(), key=lambda item: (item["canonical_symbol"], item["date"]))


def normalize_bars(bars: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize and exact-dedupe provider rows without filling missing dates."""
    return deduplicate_bars(bars)


def filter_ibkr_chunk_rows(
    rows: Iterable[Mapping[str, Any]],
    chunk: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    """Strictly filter one IBKR response to its pre-registered local-date chunk."""
    registered = _registered_ibkr_chunk(chunk)
    return filter_security_local_date_rows(
        rows,
        registered["start_date"],
        registered["end_date"],
    )


def merge_ibkr_chunk_bars(
    rows_by_chunk: Mapping[str, Iterable[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Filter all registered chunks, then exact-dedupe overlaps or fail conflicts."""
    rows: list[Mapping[str, Any]] = []
    for chunk in IBKR_CALENDAR_CHUNKS:
        chunk_rows = rows_by_chunk.get(chunk["chunk_id"], ())
        rows.extend(filter_ibkr_chunk_rows(chunk_rows, chunk))
    return deduplicate_bars(rows)


def reserve_rows_for_failures(
    manifest: Mapping[str, Any],
    market: str,
    failures_by_symbol: Mapping[str, str],
    *,
    setup03_evaluation_started: bool = False,
) -> list[dict[str, Any]]:
    """Return the first N frozen reserve rows for objective primary failures."""
    if setup03_evaluation_started:
        raise ContractViolation("FINAL_DATASET_ROSTER_LOCKED")
    if market not in VALIDATION_MARKETS:
        raise ContractViolation("unsupported replacement market")
    rows = [row for row in manifest["symbols"] if row.get("market") == market]
    primary = [row for row in rows if row.get("intended_role") == "PRIMARY"]
    reserves = sorted(
        (row for row in rows if row.get("intended_role") == "RESERVE"),
        key=lambda row: row["manifest_rank"],
    )
    primary_symbols = {row["canonical_symbol"] for row in primary}
    if not set(failures_by_symbol).issubset(primary_symbols):
        raise ContractViolation("replacement failure must identify a frozen primary symbol")
    if len(set(failures_by_symbol)) != len(failures_by_symbol):
        raise ContractViolation("duplicate primary failure identity")
    for reason in failures_by_symbol.values():
        if reason not in ALLOWED_REPLACEMENT_REASONS:
            raise ContractViolation(f"replacement reason is not objective and allowed: {reason}")
    if len(failures_by_symbol) > len(reserves):
        raise ContractViolation("TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW")
    return [dict(row) for row in reserves[: len(failures_by_symbol)]]


def build_final_roster(
    manifest: Mapping[str, Any],
    market: str,
    validation_status_by_symbol: Mapping[str, str],
    *,
    setup03_evaluation_started: bool = False,
) -> list[dict[str, Any]]:
    """Build a final roster from symbols that passed the same B1 validation.

    ``validation_status_by_symbol`` must contain every primary and every reserve
    considered by the frozen roster.  Only ``VALID_ACCEPTED`` rows can enter the
    result; objective failures activate the next frozen-rank reserve, whose own
    provider/QC/warmup result must also be ``VALID_ACCEPTED``.
    """
    if setup03_evaluation_started:
        raise ContractViolation("FINAL_DATASET_ROSTER_LOCKED")
    if market not in VALIDATION_MARKETS:
        raise ContractViolation("unsupported final roster market")

    market_rows = [row for row in manifest["symbols"] if row.get("market") == market]
    primary = sorted(
        (row for row in market_rows if row.get("intended_role") == "PRIMARY"),
        key=lambda row: row["manifest_rank"],
    )
    reserves = sorted(
        (row for row in market_rows if row.get("intended_role") == "RESERVE"),
        key=lambda row: row["manifest_rank"],
    )
    final: list[dict[str, Any]] = []
    reserve_index = 0

    def status_for(row: Mapping[str, Any]) -> str:
        symbol = row["canonical_symbol"]
        if symbol not in validation_status_by_symbol:
            raise ContractViolation("FINAL_ROSTER_VALIDATION_REQUIRED")
        status = validation_status_by_symbol[symbol]
        if status != VALID_ACCEPTED_STATUS and status not in ALLOWED_REPLACEMENT_REASONS:
            raise ContractViolation("FINAL_ROSTER_VALIDATION_INVALID_FAIL_CLOSED")
        return status

    for row in primary:
        if status_for(row) == VALID_ACCEPTED_STATUS:
            final.append(dict(row))
            continue
        while reserve_index < len(reserves):
            reserve = reserves[reserve_index]
            reserve_index += 1
            if status_for(reserve) == VALID_ACCEPTED_STATUS:
                final.append(dict(reserve))
                break
        else:
            raise ContractViolation(TARGET_ROSTER_SHORTFALL_STATUS)

    if len(final) != TARGET_ROSTER_BY_MARKET[market]:
        raise ContractViolation(TARGET_ROSTER_SHORTFALL_STATUS)
    if any(status_for(row) != VALID_ACCEPTED_STATUS for row in final):
        raise ContractViolation(FINAL_ROSTER_VALIDITY_MISMATCH_STATUS)
    return final


def evaluate_coverage(metrics_by_market: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    """Apply hard minimum and 40-valid-symbol readiness gates independently."""
    market_results: dict[str, dict[str, Any]] = {}
    for market in VALIDATION_MARKETS:
        if market not in metrics_by_market:
            raise ContractViolation(f"coverage metrics missing market: {market}")
        metrics = metrics_by_market[market]
        required = ("final_roster_count", "valid_symbols", "valid_daily_bars")
        missing = set(required).difference(metrics)
        if missing:
            raise ContractViolation(f"coverage metrics missing {market}: {sorted(missing)}")
        roster = int(metrics["final_roster_count"])
        symbols = int(metrics["valid_symbols"])
        bars = int(metrics["valid_daily_bars"])
        meets_hard_minimums = (
            symbols >= MIN_VALID_SYMBOLS_PER_MARKET
            and bars >= MIN_VALID_DAILY_BARS_PER_MARKET
        )
        if roster != symbols:
            status = FINAL_ROSTER_VALIDITY_MISMATCH_STATUS
        elif roster < TARGET_ROSTER_BY_MARKET[market]:
            status = TARGET_ROSTER_SHORTFALL_STATUS
        elif not meets_hard_minimums:
            status = INSUFFICIENT_COVERAGE_STATUS
        else:
            status = "COVERAGE_OK"
        market_results[market] = {
            "status": status,
            "final_roster_count": roster,
            "valid_symbols": symbols,
            "valid_daily_bars": bars,
            "meets_market_minimums": status == "COVERAGE_OK",
            "meets_hard_minimums": meets_hard_minimums,
            "dataset_readiness": status == "COVERAGE_OK" and symbols == TARGET_ROSTER_BY_MARKET[market],
        }
    total_symbols = sum(row["valid_symbols"] for row in market_results.values())
    statuses = [row["status"] for row in market_results.values()]
    if FINAL_ROSTER_VALIDITY_MISMATCH_STATUS in statuses:
        status = FINAL_ROSTER_VALIDITY_MISMATCH_STATUS
    elif TARGET_ROSTER_SHORTFALL_STATUS in statuses:
        status = TARGET_ROSTER_SHORTFALL_STATUS
    elif INSUFFICIENT_COVERAGE_STATUS in statuses or total_symbols < MIN_VALID_SYMBOLS_TOTAL:
        status = INSUFFICIENT_COVERAGE_STATUS
    else:
        status = "COVERAGE_OK"
    hard_minimum_eligible = all(
        row["meets_hard_minimums"] for row in market_results.values()
    ) and total_symbols >= MIN_VALID_SYMBOLS_TOTAL
    dataset_readiness_eligible = all(
        row["dataset_readiness"] for row in market_results.values()
    )
    return {
        "status": status,
        "eligible": dataset_readiness_eligible and status == "COVERAGE_OK",
        "valid_symbols_total": total_symbols,
        "market_results": market_results,
        "market_compensation_allowed": False,
        "hard_minimum_status": "HARD_MINIMUM_OK" if hard_minimum_eligible else INSUFFICIENT_COVERAGE_STATUS,
        "hard_minimum_eligible": hard_minimum_eligible,
        "dataset_readiness_status": DATASET_READINESS_STATUS if dataset_readiness_eligible else status,
        "dataset_readiness_eligible": dataset_readiness_eligible and status == "COVERAGE_OK",
    }


def required_warmup_bars(
    platform_window: int = PLATFORM_WINDOW,
    setup_swing_lookback: int = SETUP_SWING_LOOKBACK,
) -> int:
    if platform_window != PLATFORM_WINDOW or setup_swing_lookback != SETUP_SWING_LOOKBACK:
        raise ContractViolation("B0 warmup parameters changed")
    return max(platform_window, 2 * setup_swing_lookback)


def evaluable_bars_after_warmup(
    bars: Iterable[Any],
    platform_window: int = PLATFORM_WINDOW,
    setup_swing_lookback: int = SETUP_SWING_LOOKBACK,
) -> list[Any]:
    """Exclude the dependency prefix; return no state day for an insufficient series."""
    sequence = list(bars)
    boundary = required_warmup_bars(platform_window, setup_swing_lookback)
    if len(sequence) <= boundary:
        raise ContractViolation("INSUFFICIENT_FOR_REQUIRED_WARMUP")
    return sequence[boundary:]


__all__ = [
    "ALLOWED_REPLACEMENT_REASONS",
    "CANONICAL_BAR_FIELDS",
    "CN_CONVERSION_TIMEZONE",
    "CN_WIRE_END_MS",
    "CN_WIRE_START_MS",
    "CONTRACT_PATH",
    "CONTRACT_SCHEMA_VERSION",
    "CONTRACT_STATUS",
    "CONTRACT_VERSION",
    "ContractViolation",
    "DATASET_READINESS_STATUS",
    "DATE_END",
    "DATE_START",
    "EXPECTED_MANIFEST_SHA256",
    "EXPECTED_MANIFEST_VERSION",
    "EXPECTED_PROTOCOL_SHA256",
    "EXPECTED_PROTOCOL_VERSION",
    "FINAL_ROSTER_VALIDITY_MISMATCH_STATUS",
    "FORBIDDEN_REPLACEMENT_REASONS",
    "HISTORICAL_CONTRACT_V1_PATH",
    "HISTORICAL_CONTRACT_V1_SHA256",
    "HISTORICAL_CONTRACT_V1_VERSION",
    "IBKR_BAR_SIZE_SETTING",
    "IBKR_CALENDAR_CHUNKS",
    "IBKR_DURATION_STR",
    "IBKR_WHAT_TO_SHOW",
    "PINNED_CONTRACT_SHA256",
    "TARGET_ROSTER_SHORTFALL_STATUS",
    "US_CONVERSION_TIMEZONE",
    "VALID_ACCEPTED_STATUS",
    "build_final_roster",
    "build_cn_wire_request",
    "build_ibkr_contract_wire",
    "build_ibkr_req_historical_data_wire",
    "build_ibkr_wire_request",
    "contract_integrity_hash",
    "deduplicate_bars",
    "evaluable_bars_after_warmup",
    "evaluate_coverage",
    "filter_cn_response_rows",
    "filter_ibkr_chunk_rows",
    "filter_security_local_date_rows",
    "load_contract",
    "load_historical_contract_v1",
    "local_datetime_to_unix_ms",
    "merge_ibkr_chunk_bars",
    "normalize_bar",
    "normalize_bars",
    "required_warmup_bars",
    "reserve_rows_for_failures",
    "serialize_contract",
    "validate_bars",
]

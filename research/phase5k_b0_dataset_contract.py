"""Phase 5K-B0 development-validation dataset acquisition contract.

This module freezes the acquisition, normalization, QC, replacement, coverage,
and warmup rules for the future development-validation dataset.  It deliberately
contains no network client and does not import production quote, replay, or
trading modules.  B1 may consume these pure validators after the contract and
the A1 roster have been independently reviewed.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from research.phase5k_a1_universe import load_manifest
from research.structural_validation_protocol_v2 import load_protocol


CONTRACT_PATH = Path(__file__).with_name("phase5k_b0_dataset_acquisition_contract.json")
CONTRACT_SCHEMA_VERSION = "setup03-phase5k-b0-dataset-acquisition-contract-v1"
CONTRACT_VERSION = "SETUP_03-PHASE5K-B0-DATASET-ACQUISITION-CONTRACT-2026-08-27-v1"
CONTRACT_STATUS = "DATASET_ACQUISITION_CONTRACT_FROZEN_NOT_ACQUIRED"

EXPECTED_PROTOCOL_VERSION = "SETUP_03-STRUCTURAL-VALIDATION-PROTOCOL-2026-08-27-v2-CN-US"
EXPECTED_PROTOCOL_SHA256 = "sha256:d7b216b43980fbedb4f24a389891141931092a78063f5203f79a97e8bd451aa0"
EXPECTED_MANIFEST_VERSION = "SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v2"
EXPECTED_MANIFEST_SHA256 = "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433"
EXPECTED_MANIFEST_STATUS = "MANIFEST_FROZEN_NOT_FETCHED"

DATE_START = date(2017, 1, 1)
DATE_END = date(2026, 8, 26)
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


class ContractViolation(ValueError):
    """Raised when a B0 contract, bar, roster, or coverage invariant fails."""


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
    if (
        cn["provider_id"] != "HITHINK_A_SHARE_HISTORICAL_FORWARD_ADJUSTED"
        or cn["endpoint_path"] != "/api/a-share/prices/historical"
        or cn["request_contract"]["interval"] != "1d"
        or cn["request_contract"]["adjust"] != "forward"
        or cn["api_key_env"] != "HITHINK_FINANCE_API_KEY"
    ):
        raise ContractViolation("CN provider contract changed")
    us = providers["US"]
    if (
        us["provider_id"] != "IBKR_TWS_API_ADJUSTED_LAST"
        or us["request_contract"]["security_type"] != "STK"
        or us["request_contract"]["bar_size"] != "1 day"
        or us["request_contract"]["what_to_show"] != "ADJUSTED_LAST"
        or us["request_contract"]["use_rth"] != 1
        or us["request_contract"]["keep_up_to_date"] is not False
        or us["request_contract"]["end_cutoff"] != DATE_END.isoformat()
        or us["identity_resolution"]["required_before_first_history_request"] is not True
    ):
        raise ContractViolation("US provider contract changed")

    coverage = contract["coverage_rules"]
    if (
        coverage["markets"] != list(VALIDATION_MARKETS)
        or coverage["target_roster_by_market"] != TARGET_ROSTER_BY_MARKET
        or coverage["reserve_target_by_market"] != RESERVE_TARGET_BY_MARKET
        or coverage["minimum_valid_symbols_per_market"] != MIN_VALID_SYMBOLS_PER_MARKET
        or coverage["minimum_valid_symbols_total"] != MIN_VALID_SYMBOLS_TOTAL
        or coverage["minimum_valid_daily_bars_per_market"] != MIN_VALID_DAILY_BARS_PER_MARKET
        or coverage["market_compensation_allowed"] is not False
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
    if b1["must_not_be_generated_in_b0"] is not True:
        raise ContractViolation("B0 must not generate B1 status was weakened")


# This is intentionally a literal immutable version/hash contract.  Once the
# JSON is finalized, changing content requires a new contract version.
PINNED_CONTRACT_SHA256 = "sha256:daed425278bf7b2cca00ede87b56dddc3bc9d47be51508a6800369105f2da039"


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    _validate_contract_shape(contract)
    return contract


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
    failures_by_symbol: Mapping[str, str],
    *,
    setup03_evaluation_started: bool = False,
) -> list[dict[str, Any]]:
    """Build a market roster and enforce the 40-symbol lock before B1."""
    replacement_rows = reserve_rows_for_failures(
        manifest,
        market,
        failures_by_symbol,
        setup03_evaluation_started=setup03_evaluation_started,
    )
    rows = [
        dict(row)
        for row in manifest["symbols"]
        if row.get("market") == market
        and row.get("intended_role") == "PRIMARY"
        and row["canonical_symbol"] not in failures_by_symbol
    ]
    final = rows + replacement_rows
    if len(final) != TARGET_ROSTER_BY_MARKET[market]:
        raise ContractViolation("TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW")
    return final


def evaluate_coverage(metrics_by_market: Mapping[str, Mapping[str, int]]) -> dict[str, Any]:
    """Apply independent market gates and never compensate one market with another."""
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
        if roster < TARGET_ROSTER_BY_MARKET[market]:
            status = "TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW"
        elif symbols < MIN_VALID_SYMBOLS_PER_MARKET or bars < MIN_VALID_DAILY_BARS_PER_MARKET:
            status = "INSUFFICIENT_COVERAGE"
        else:
            status = "COVERAGE_OK"
        market_results[market] = {
            "status": status,
            "final_roster_count": roster,
            "valid_symbols": symbols,
            "valid_daily_bars": bars,
            "meets_market_minimums": status == "COVERAGE_OK",
        }
    total_symbols = sum(row["valid_symbols"] for row in market_results.values())
    statuses = [row["status"] for row in market_results.values()]
    if "TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW" in statuses:
        status = "TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW"
    elif "INSUFFICIENT_COVERAGE" in statuses or total_symbols < MIN_VALID_SYMBOLS_TOTAL:
        status = "INSUFFICIENT_COVERAGE"
    else:
        status = "COVERAGE_OK"
    return {
        "status": status,
        "eligible": status == "COVERAGE_OK",
        "valid_symbols_total": total_symbols,
        "market_results": market_results,
        "market_compensation_allowed": False,
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
    "CONTRACT_PATH",
    "CONTRACT_SCHEMA_VERSION",
    "CONTRACT_STATUS",
    "CONTRACT_VERSION",
    "ContractViolation",
    "DATE_END",
    "DATE_START",
    "EXPECTED_MANIFEST_SHA256",
    "EXPECTED_MANIFEST_VERSION",
    "EXPECTED_PROTOCOL_SHA256",
    "EXPECTED_PROTOCOL_VERSION",
    "FORBIDDEN_REPLACEMENT_REASONS",
    "PINNED_CONTRACT_SHA256",
    "build_final_roster",
    "contract_integrity_hash",
    "deduplicate_bars",
    "evaluable_bars_after_warmup",
    "evaluate_coverage",
    "load_contract",
    "normalize_bar",
    "normalize_bars",
    "required_warmup_bars",
    "reserve_rows_for_failures",
    "serialize_contract",
    "validate_bars",
]

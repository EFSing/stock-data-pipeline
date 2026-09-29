"""Shared production market-data contract for the single-source V1 plane.

This module deliberately contains no provider imports.  Provider adapters and
the report boundary use the constants and validation helpers here so that a
symbol-level data problem cannot be confused with a strategy ``NO_SIGNAL``.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Iterable, Mapping


SINGLE_SOURCE_MARKET_DATA_VERSION = "SINGLE_SOURCE_MARKET_DATA_V1"
SINGLE_SOURCE_CONTRACT_NAME = "ONE_MARKET_ONE_MARKET_DATA_VENDOR"

CN_SINGLE_SOURCE_PROVIDER = "HITHINK_FINANCIAL_API"
US_SINGLE_SOURCE_PROVIDER = "YAHOO_CHART"

CN_ADJUSTMENT_ENGINE_VERSION = "CN_FORWARD_ADJUSTMENT_ENGINE_V1"
# HiThink's fund-market historical endpoint is a separate, same-vendor
# contract.  It returns ETF prices in the provider-documented forward-adjusted
# form and must not be represented as the stock raw+corporate-action chain.
CN_ETF_ADJUSTMENT_ENGINE_VERSION = "HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1"
US_ADJUSTMENT_ENGINE_VERSION = "YAHOO_CHART_ADJCLOSE_ENGINE_V1"

DATA_OK = "DATA_OK"
DATA_MISSING = "DATA_MISSING"
DATA_STALE = "DATA_STALE"
DATA_INVALID = "DATA_INVALID"
DATA_ADJUSTMENT_UNVERIFIED = "DATA_ADJUSTMENT_UNVERIFIED"
PROVIDER_SYMBOL_ERROR = "PROVIDER_SYMBOL_ERROR"
DATA_UNAVAILABLE_FOR_DECISION = "DATA_UNAVAILABLE_FOR_DECISION"
PROVIDER_GLOBAL_FAILURE = "PROVIDER_GLOBAL_FAILURE"

SYMBOL_FAILURE_STATUSES = frozenset(
    {
        DATA_MISSING,
        DATA_STALE,
        DATA_INVALID,
        DATA_ADJUSTMENT_UNVERIFIED,
        PROVIDER_SYMBOL_ERROR,
    }
)


class ProviderGlobalFailure(RuntimeError):
    """A provider-wide failure that must not be relabeled as one bad symbol."""


class ProviderSymbolError(RuntimeError):
    """A provider rejected or could not serve one symbol identity."""


class AdjustmentUnverifiedError(ValueError):
    """Corporate-action data was insufficient to prove the adjustment chain."""


def canonical_provider_for_market(market: str) -> str:
    normalized = str(market).strip().upper()
    if normalized == "CN":
        return CN_SINGLE_SOURCE_PROVIDER
    if normalized == "US":
        return US_SINGLE_SOURCE_PROVIDER
    raise ValueError(f"single-source production market unsupported: {market}")


def adjustment_engine_for_market(market: str) -> str:
    normalized = str(market).strip().upper()
    if normalized == "CN":
        return CN_ADJUSTMENT_ENGINE_VERSION
    if normalized == "US":
        return US_ADJUSTMENT_ENGINE_VERSION
    raise ValueError(f"single-source adjustment market unsupported: {market}")


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate_single_source_quotes(
    quotes: Iterable[Any],
    *,
    expected_symbol: str,
    expected_market: str,
    target_trade_date: date | None = None,
    max_trade_date: date | None = None,
    minimum_bars: int = 0,
) -> tuple[str, ...]:
    """Return deterministic contract errors for one provider result.

    The function intentionally validates the returned series only.  It never
    compares another provider and it never invents a target price.
    """

    values = tuple(quotes)
    symbol = str(expected_symbol).strip().upper()
    market = str(expected_market).strip().upper()
    errors: list[str] = []
    seen: set[date] = set()
    valid_dates: list[date] = []
    previous: date | None = None
    for quote in values:
        quote_symbol = str(getattr(quote, "symbol", "")).strip().upper()
        quote_market = str(getattr(quote, "market", "")).strip().upper()
        if quote_symbol != symbol or quote_market != market:
            errors.append("IDENTITY_MISMATCH")
        trade_date = getattr(quote, "trade_date", None)
        if not isinstance(trade_date, date):
            errors.append("DATE_MISSING")
            continue
        valid_dates.append(trade_date)
        if trade_date in seen:
            errors.append("DUPLICATE_SESSION")
        seen.add(trade_date)
        if previous is not None and trade_date <= previous:
            errors.append("DATES_NOT_STRICTLY_INCREASING")
        previous = trade_date
        if max_trade_date is not None and trade_date > max_trade_date:
            errors.append("FUTURE_BAR")
        opening = _number(getattr(quote, "open", None))
        high = _number(getattr(quote, "high", None))
        low = _number(getattr(quote, "low", None))
        close = _number(getattr(quote, "close", None))
        volume = _number(getattr(quote, "volume", None))
        if any(value is None for value in (opening, high, low, close, volume)):
            errors.append("SCHEMA_INCOMPLETE")
            continue
        if min(opening, high, low, close) <= 0 or high < max(opening, close) or low > min(opening, close) or low > high:
            errors.append("OHLC_SANITY")
        if volume < 0:
            errors.append("NEGATIVE_VOLUME")
    if not values:
        errors.append("EMPTY_RESULT")
    if minimum_bars and len(values) < minimum_bars:
        errors.append("INSUFFICIENT_HISTORY")
    if target_trade_date is not None:
        if not valid_dates or max(valid_dates) != target_trade_date:
            errors.append("TARGET_SESSION_MISSING")
    return tuple(dict.fromkeys(errors))


def status_from_contract_errors(errors: Iterable[str], *, empty_status: str = DATA_MISSING) -> str:
    values = tuple(str(error) for error in errors if error)
    if not values:
        return DATA_OK
    if "TARGET_SESSION_MISSING" in values:
        return DATA_STALE
    if "EMPTY_RESULT" in values:
        return empty_status
    return DATA_INVALID


def unavailable_reason(status: str) -> str:
    normalized = str(status).strip().upper()
    if normalized == DATA_OK:
        return ""
    return f"{DATA_UNAVAILABLE_FOR_DECISION}:{normalized}"


def source_provenance(
    *,
    market: str,
    provider: str,
    adjustment: str,
    adjustment_engine_version: str,
    session_identity: str | None = None,
    acquired_at: str | None = None,
    raw_source: str | None = None,
    corporate_action_source: str | None = None,
    adjustment_chain_sha256: str | None = None,
    asset_type: str | None = None,
    adjustment_source: str | None = None,
) -> dict[str, Any]:
    """Build the compact provenance block attached to each symbol result."""

    return {
        "market": str(market).strip().upper(),
        "provider_identity": str(provider),
        "raw_source": raw_source or str(provider),
        "corporate_action_source": corporate_action_source,
        "adjustment": str(adjustment),
        "adjustment_engine_version": str(adjustment_engine_version),
        "adjustment_chain_sha256": adjustment_chain_sha256,
        "asset_type": asset_type,
        "adjustment_source": adjustment_source,
        "session_identity": session_identity,
        "acquired_at": acquired_at,
    }


__all__ = [
    "AdjustmentUnverifiedError",
    "CN_ADJUSTMENT_ENGINE_VERSION",
    "CN_ETF_ADJUSTMENT_ENGINE_VERSION",
    "CN_SINGLE_SOURCE_PROVIDER",
    "DATA_ADJUSTMENT_UNVERIFIED",
    "DATA_INVALID",
    "DATA_MISSING",
    "DATA_OK",
    "DATA_STALE",
    "DATA_UNAVAILABLE_FOR_DECISION",
    "PROVIDER_GLOBAL_FAILURE",
    "ProviderGlobalFailure",
    "ProviderSymbolError",
    "PROVIDER_SYMBOL_ERROR",
    "SINGLE_SOURCE_CONTRACT_NAME",
    "SINGLE_SOURCE_MARKET_DATA_VERSION",
    "SYMBOL_FAILURE_STATUSES",
    "US_ADJUSTMENT_ENGINE_VERSION",
    "US_SINGLE_SOURCE_PROVIDER",
    "adjustment_engine_for_market",
    "canonical_provider_for_market",
    "source_provenance",
    "status_from_contract_errors",
    "unavailable_reason",
    "validate_single_source_quotes",
]

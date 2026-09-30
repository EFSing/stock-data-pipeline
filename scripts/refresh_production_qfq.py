"""Refresh production qfq history without entering the decision pipeline.

The scheduled latest path deliberately does not run the manual ``full`` mode,
because ``full`` also enters the legacy SETUP_03/Decision path.  This command
is the narrow scheduled companion: it reads the formal strategy universe and
the already-published latest trade date, then writes only qfq history.

Root-cause marker: ``PRODUCTION_QFQ_NOT_REFRESHED_BY_SCHEDULED_LATEST_MODE``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from latest_snapshot import latest_row_is_monitorable, quote_row
from main import as_bool, beijing_now


ROOT_CAUSE_MARKER = "PRODUCTION_QFQ_NOT_REFRESHED_BY_SCHEDULED_LATEST_MODE"
EXACT_QFQ_MIN_RETRY_ATTEMPTS = 2

PRODUCTION_MARKETS = {
    "asia": frozenset({"CN"}),
    "us": frozenset({"US"}),
    "all": frozenset({"CN", "US"}),
}


class ProductionQfqRefreshError(RuntimeError):
    """Raised when the scheduled qfq refresh cannot complete fail-closed."""


def _identity(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("市场") or "").strip(),
        str(row.get("统一代码") or "").strip(),
    )


def _account_identity(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("账户ID") or "").strip(),
        str(row.get("市场") or "").strip(),
    )


def _parse_trade_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("交易日期为空")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError(f"交易日期不可解析：{text}") from exc


def _formal_universe(client: Any, markets: frozenset[str]) -> list[dict[str, Any]]:
    enabled_accounts = {
        _account_identity(row)
        for row in client.records("策略账户")
        if as_bool(row.get("启用"))
        and _account_identity(row)[0]
        and _account_identity(row)[1] in markets
    }
    return [
        row
        for row in client.records("策略股票池")
        if as_bool(row.get("启用"))
        and _identity(row)[0] in markets
        and _account_identity(row) in enabled_accounts
    ]


def _active_paper_plans(client: Any, markets: frozenset[str]) -> list[dict[str, Any]]:
    """Return non-terminal Paper plans without creating historical backfill."""

    try:
        rows = client.records("策略模拟账本")
    except Exception:
        # The worksheet is created only by the explicit --paper-track path.
        # No worksheet means no active Paper scope for the scheduled refresher.
        return []
    plans: dict[str, dict[str, Any]] = {}
    terminal: set[str] = set()
    for row in rows:
        event_type = str(row.get("lifecycle_event_type") or "").strip()
        market = str(row.get("market") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        identity = str(row.get("event_identity") or "").strip()
        if market not in markets or not symbol:
            continue
        if not identity:
            continue
        if event_type == "PAPER_PLAN_CREATED":
            plans[identity] = dict(row)
        elif event_type in {"PAPER_T1_SKIPPED", "PAPER_CLOSED"}:
            terminal.add(identity)
    active = [plans[key] for key in sorted(plans) if key not in terminal]
    # One QFQ refresh request per market/symbol is sufficient even when a
    # symbol has more than one independent event identity.
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for plan in active:
        key = _identity(plan)
        selected.setdefault(key, plan)
    return [selected[key] for key in sorted(selected)]


def _default_paper_watch(plan: dict[str, Any]) -> dict[str, Any]:
    """Build provider identity only; all prices still come from QFQ provider."""

    market = str(plan.get("market") or "").strip().upper()
    symbol = str(plan.get("symbol") or "").strip().upper()
    if market == "CN":
        code, separator, exchange = symbol.partition(".")
        if not separator:
            exchange = "SH" if code.startswith(("5", "6", "9")) else "SZ"
        elif exchange.upper() in {"SSE", "XSHG"}:
            exchange = "SH"
        elif exchange.upper() in {"SZSE", "XSHE"}:
            exchange = "SZ"
        yfinance_symbol = f"{code}.SS" if exchange == "SH" else f"{code}.SZ"
        baostock_symbol = f"{exchange.lower()}.{code}"
        timezone_name = "Asia/Shanghai"
        currency = "CNY"
    else:
        yfinance_symbol = symbol.replace("/", "-").replace(".", "-")
        baostock_symbol = yfinance_symbol
        timezone_name = "America/New_York"
        currency = "USD"
    return {
        "启用": "TRUE",
        "统一代码": symbol,
        "名称": str(plan.get("name") or symbol),
        "市场": market,
        "主数据源": "HITHINK_FINANCIAL_API" if market == "CN" else "YAHOO_CHART",
        "校验数据源": "",
        "历史数据源": "HITHINK_FINANCIAL_API" if market == "CN" else "YAHOO_CHART",
        "yfinance代码": yfinance_symbol,
        "BaoStock代码": baostock_symbol,
        "HITHINK代码": symbol,
        "币种": currency,
        "时区": timezone_name,
    }


def _latest_market_target(
    latest_rows: list[dict[str, Any]], market: str
) -> date:
    values: list[date] = []
    for row in latest_rows:
        if str(row.get("市场") or "").strip().upper() != market.upper():
            continue
        try:
            values.append(_parse_trade_date(row.get("交易日期")))
        except ValueError:
            continue
    if not values:
        raise ProductionQfqRefreshError(
            f"PRODUCTION_QFQ_LATEST_DATE_REQUIRED:{market}|PAPER_TRACKED"
        )
    return max(values)


def _single_match(
    rows: list[dict[str, Any]],
    identity: tuple[str, str],
    *,
    sheet_name: str,
) -> dict[str, Any]:
    matches = [_row for _row in rows if _identity(_row) == identity]
    market, symbol = identity
    if not matches:
        raise ProductionQfqRefreshError(
            f"PRODUCTION_QFQ_{sheet_name}_REQUIRED:{market}|{symbol}"
        )
    if len(matches) > 1:
        raise ProductionQfqRefreshError(
            f"PRODUCTION_QFQ_{sheet_name}_DUPLICATE:{market}|{symbol}"
        )
    return matches[0]


def _summary(
    group: str,
    symbols_requested: int,
    symbols_updated: int,
    rows_written: int,
    stale_or_failed_symbols: list[str],
    status: str,
) -> dict[str, Any]:
    return {
        "group": group,
        "symbols_requested": symbols_requested,
        "symbols_updated": symbols_updated,
        "rows_written": rows_written,
        "stale_or_failed_symbols": stale_or_failed_symbols,
        "status": status,
    }


def _require_verified_latest_row(
    row: dict[str, Any],
    *,
    market: str,
    symbol: str,
    target_trade_date: date,
) -> None:
    """Reject a stale or unavailable latest row as a QFQ target."""

    if not latest_row_is_monitorable(
        row,
        target_trade_date,
        require_verified=True,
    ):
        status = str(row.get("校验状态") or "<missing>").strip()
        raise ProductionQfqRefreshError(
            "PRODUCTION_QFQ_LATEST_NOT_FRESH:"
            f"{market}|{symbol}:date={target_trade_date.isoformat()},status={status}"
        )


def _fail(
    group: str,
    symbols_requested: int,
    failed_symbols: list[str],
    errors: list[str],
) -> None:
    summary = _summary(
        group,
        symbols_requested,
        0,
        0,
        failed_symbols,
        "FAILED",
    )
    print("PRODUCTION_QFQ_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    raise ProductionQfqRefreshError("；".join(errors))


def _is_single_source_runtime(client: Any, requested_rows: list[dict[str, Any]]) -> bool:
    try:
        from sheets_client import SheetsClient

        if isinstance(client, SheetsClient):
            return True
    except Exception:
        pass
    return any(
        str(row.get("主数据源") or row.get("历史数据源") or "").strip()
        in {"HITHINK_FINANCIAL_API", "YAHOO_CHART"}
        for row in requested_rows
    )


def _refresh_single_source_qfq(
    group: str,
    *,
    client: Any,
    requested_rows: list[dict[str, Any]],
    paper_identities: set[tuple[str, str]],
    fetched_at: datetime | None,
) -> dict[str, Any]:
    """Tolerant V1 refresh: one failed symbol is isolated from the write."""

    from market_data_contract import (
        AdjustmentUnverifiedError,
        DATA_ADJUSTMENT_UNVERIFIED,
        DATA_INVALID,
        DATA_MISSING,
        DATA_STALE,
        ProviderGlobalFailure,
        ProviderSymbolError,
        canonical_provider_for_market,
        status_from_contract_errors,
        validate_single_source_quotes,
    )
    from providers import fetch_single_source_with_retry

    watchlist = client.records("自选清单")
    latest_rows = client.records("最新行情")
    try:
        config = client.config()
        history_days = int(float(config.get("history_days", 1000)))
        retry_count = int(float(config.get("retry_count", 3)))
        retry_wait = float(config.get("retry_wait_seconds", 5))
        if history_days <= 0:
            raise ValueError("history_days必须为正数")
    except Exception as exc:
        raise ProductionQfqRefreshError(f"PRODUCTION_QFQ_CONFIG_INVALID:{exc}") from exc

    identities = [_identity(row) for row in requested_rows]
    plans: list[tuple[dict[str, Any], date, tuple[str, str]]] = []
    failed: list[str] = []
    failed_by_reason: dict[str, list[str]] = {}

    def fail_symbol(market: str, symbol: str, reason: str) -> None:
        failed.append(symbol)
        failed_by_reason.setdefault(reason, []).append(symbol)

    for requested in requested_rows:
        market, symbol = _identity(requested)
        try:
            configured = [row for row in watchlist if _identity(row) == (market, symbol)]
            if len(configured) > 1:
                raise ProductionQfqRefreshError("SOURCE_CONFIG_DUPLICATE")
            if (market, symbol) in paper_identities:
                watch = configured[0] if configured else _default_paper_watch(requested)
                matching_latest = [row for row in latest_rows if _identity(row) == (market, symbol)]
                if len(matching_latest) > 1:
                    raise ProductionQfqRefreshError("LATEST_DUPLICATE")
                target = (
                    _parse_trade_date(matching_latest[0].get("交易日期"))
                    if matching_latest
                    else _latest_market_target(latest_rows, market)
                )
            else:
                if not configured:
                    raise ProductionQfqRefreshError("SOURCE_CONFIG_REQUIRED")
                watch = configured[0]
                latest = _single_match(latest_rows, (market, symbol), sheet_name="LATEST")
                target = _parse_trade_date(latest.get("交易日期"))
                _require_verified_latest_row(
                    latest, market=market, symbol=symbol, target_trade_date=target
                )
            effective = dict(watch)
            provider = canonical_provider_for_market(market)
            effective["主数据源"] = provider
            effective["校验数据源"] = ""
            effective["历史数据源"] = provider
            effective.setdefault("HITHINK代码", symbol)
            plans.append((effective, target, (market, symbol)))
        except Exception as exc:
            reason = str(exc).split(":", 1)[0] or type(exc).__name__
            fail_symbol(market, symbol, reason)

    existing_history = client.records("历史行情_前复权")
    now = fetched_at or beijing_now()
    rows_to_write: list[dict[str, Any]] = []
    successful_identities: list[tuple[str, str]] = []
    global_errors: list[str] = []
    for watch, target, identity in plans:
        market, symbol = identity
        start = target - timedelta(days=max(history_days * 2, 365))
        try:
            result = fetch_single_source_with_retry(
                market,
                watch,
                "qfq",
                start,
                target,
                max(retry_count, EXACT_QFQ_MIN_RETRY_ATTEMPTS),
                retry_wait,
                target_trade_date=target,
            )
            contract_errors = validate_single_source_quotes(
                result.quotes,
                expected_symbol=symbol,
                expected_market=market,
                target_trade_date=target,
                max_trade_date=target,
                minimum_bars=min(60, history_days),
            )
            if contract_errors:
                status = status_from_contract_errors(contract_errors)
                fail_symbol(market, symbol, status)
                continue
            rows_to_write.extend(
                quote_row(quote, now, "前复权")
                for quote in result.quotes[-history_days:]
            )
            successful_identities.append(identity)
        except ProviderGlobalFailure as exc:
            global_errors.append(f"{market}|{symbol}:PROVIDER_GLOBAL_FAILURE:{exc}")
        except (AdjustmentUnverifiedError, ProviderSymbolError) as exc:
            status = DATA_ADJUSTMENT_UNVERIFIED if isinstance(exc, AdjustmentUnverifiedError) else "PROVIDER_SYMBOL_ERROR"
            fail_symbol(market, symbol, status)
        except LookupError:
            fail_symbol(market, symbol, DATA_STALE)
        except Exception as exc:
            fail_symbol(market, symbol, DATA_INVALID)

    if global_errors:
        _fail(group, len(requested_rows), sorted(set(failed + [symbol for _, symbol in identities])), global_errors)

    rows_written = 0
    if rows_to_write and successful_identities:
        result = client.replace_history_series(
            rows_to_write,
            successful_identities,
            existing=existing_history,
        )
        rows_written = result if isinstance(result, int) else len(rows_to_write)
    symbols_updated = len(successful_identities)
    data_status = "OK" if not failed else "NO_USABLE_SYMBOLS" if symbols_updated == 0 else "PARTIAL"
    status = "SUCCESS" if data_status == "OK" else "COMPLETED_NO_USABLE_SYMBOLS" if data_status == "NO_USABLE_SYMBOLS" else "COMPLETED_WITH_DATA_ERRORS"
    summary = {
        "group": group,
        "symbols_requested": len(requested_rows),
        "symbols_updated": symbols_updated,
        "rows_written": rows_written,
        "stale_or_failed_symbols": sorted(set(failed)),
        "failed_by_reason": {key: sorted(set(values)) for key, values in sorted(failed_by_reason.items())},
        "coverage_pct": round(symbols_updated / len(requested_rows) * 100, 2) if requested_rows else 100.0,
        "data_status": data_status,
        "status": status,
    }
    print("PRODUCTION_QFQ_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return summary


def refresh_production_qfq(
    group: str = "all",
    *,
    client: Any = None,
    fetch_history: Callable[..., list[Any]] | None = None,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Refresh the formal CN/US universe through each row's exact target date."""
    if group not in PRODUCTION_MARKETS:
        raise ValueError(f"未知生产刷新组：{group}")
    from providers import (
        QFQ_HISTORY_SOURCES,
        SINGLE_SOURCE_QFQ_SOURCES,
        fetch_with_retry,
    )
    from sheets_client import SheetsClient

    custom_fetch = fetch_history is not None
    if client is None:
        client = SheetsClient()
    if fetch_history is None:
        fetch_history = fetch_with_retry

    markets = PRODUCTION_MARKETS[group]
    formal_rows = _formal_universe(client, markets)
    formal_identities = {_identity(row) for row in formal_rows}
    paper_plans = _active_paper_plans(client, markets)
    paper_rows = [
        _default_paper_watch(plan)
        for plan in paper_plans
        if _identity(plan) not in formal_identities
    ]
    # An injected fetcher is the compatibility seam used by tests and manual
    # callers.  Generated paper rows carry the production source identity, but
    # they must not silently opt that seam into the canonical branch when the
    # formal universe itself is still legacy-configured.
    canonical_requested = any(
        str(row.get("主数据源") or row.get("历史数据源") or "").strip()
        in SINGLE_SOURCE_QFQ_SOURCES
        for row in (formal_rows if custom_fetch else (*formal_rows, *paper_rows))
    )
    if custom_fetch and not canonical_requested:
        # Preserve the injectable legacy test/manual fetch contract.  The
        # unattended Sheets path below never supplies this override and uses
        # the canonical provider identity.
        for row in paper_rows:
            row["历史数据源"] = "yfinance"
    requested_rows = formal_rows + paper_rows
    paper_identities = {_identity(row) for row in paper_rows}
    symbols_requested = len(requested_rows)
    identities = [_identity(row) for row in requested_rows]
    duplicate_universe = sorted(
        {identity for identity in identities if identities.count(identity) > 1}
    )
    if duplicate_universe:
        _fail(
            group,
            symbols_requested,
            [symbol for _, symbol in duplicate_universe],
            [
                f"PRODUCTION_QFQ_STRATEGY_DUPLICATE:{market}|{symbol}"
                for market, symbol in duplicate_universe
            ],
        )
    if _is_single_source_runtime(client, requested_rows) and not custom_fetch:
        return _refresh_single_source_qfq(
            group,
            client=client,
            requested_rows=requested_rows,
            paper_identities=paper_identities,
            fetched_at=fetched_at,
        )
    if not requested_rows:
        summary = _summary(group, 0, 0, 0, [], "SUCCESS")
        print("PRODUCTION_QFQ_SUMMARY " + json.dumps(summary, ensure_ascii=False))
        return summary

    watchlist = client.records("自选清单")
    latest_rows = client.records("最新行情")
    plans: list[tuple[dict[str, Any], date]] = []
    planning_errors: list[str] = []
    failed_symbols: list[str] = []
    for identity in identities:
        market, symbol = identity
        try:
            if identity in paper_identities:
                configured = [row for row in watchlist if _identity(row) == identity]
                if len(configured) > 1:
                    raise ProductionQfqRefreshError(
                        f"PRODUCTION_QFQ_SOURCE_CONFIG_DUPLICATE:{market}|{symbol}"
                    )
                watch = configured[0] if configured else next(
                    row for row in paper_rows if _identity(row) == identity
                )
                matching_latest = [
                    row for row in latest_rows if _identity(row) == identity
                ]
                if len(matching_latest) > 1:
                    raise ProductionQfqRefreshError(
                        f"PRODUCTION_QFQ_LATEST_DUPLICATE:{market}|{symbol}"
                    )
                try:
                    target_trade_date = (
                        _parse_trade_date(matching_latest[0].get("交易日期"))
                        if matching_latest
                        else _latest_market_target(latest_rows, market)
                    )
                except ValueError as exc:
                    raise ProductionQfqRefreshError(
                        f"PRODUCTION_QFQ_LATEST_DATE_REQUIRED:{market}|{symbol}:{exc}"
                    ) from exc
            else:
                watch = _single_match(
                    watchlist, identity, sheet_name="SOURCE_CONFIG"
                )
                latest = _single_match(latest_rows, identity, sheet_name="LATEST")
                try:
                    target_trade_date = _parse_trade_date(latest.get("交易日期"))
                except ValueError as exc:
                    raise ProductionQfqRefreshError(
                        f"PRODUCTION_QFQ_LATEST_DATE_REQUIRED:{market}|{symbol}:{exc}"
                    ) from exc
                _require_verified_latest_row(
                    latest,
                    market=market,
                    symbol=symbol,
                    target_trade_date=target_trade_date,
                )
            source = str(watch.get("历史数据源") or "").strip()
            if not source:
                raise ProductionQfqRefreshError(
                    f"PRODUCTION_QFQ_SOURCE_CONFIG_REQUIRED:{market}|{symbol}"
                )
            if source not in QFQ_HISTORY_SOURCES and source not in SINGLE_SOURCE_QFQ_SOURCES:
                raise ProductionQfqRefreshError(
                    f"PRODUCTION_QFQ_SOURCE_UNSUPPORTED:{market}|{symbol}:{source}"
                )
            if not target_trade_date:
                raise ProductionQfqRefreshError(
                    f"PRODUCTION_QFQ_LATEST_DATE_REQUIRED:{market}|{symbol}"
                )
            plans.append((watch, target_trade_date))
        except ProductionQfqRefreshError as exc:
            planning_errors.append(str(exc))
            failed_symbols.append(symbol)

    if planning_errors:
        _fail(group, symbols_requested, sorted(set(failed_symbols)), planning_errors)

    try:
        config = client.config()
        history_days = int(float(config.get("history_days", 1000)))
        retry_count = int(float(config.get("retry_count", 3)))
        retry_wait = float(config.get("retry_wait_seconds", 5))
        if history_days <= 0:
            raise ValueError("history_days必须为正数")
    except Exception as exc:
        _fail(
            group,
            symbols_requested,
            [symbol for _, symbol in identities],
            [f"PRODUCTION_QFQ_CONFIG_INVALID:{exc}"],
        )

    existing_history = client.records("历史行情_前复权")
    now = fetched_at or beijing_now()
    rows_to_write: list[dict[str, Any]] = []
    fetch_errors: list[str] = []
    for watch, target_trade_date in plans:
        market, symbol = _identity(watch)
        start = target_trade_date - timedelta(days=max(history_days * 2, 365))
        try:
            quotes = fetch_history(
                str(watch["历史数据源"]).strip(),
                watch,
                "qfq",
                start,
                target_trade_date,
                max(retry_count, EXACT_QFQ_MIN_RETRY_ATTEMPTS),
                retry_wait,
                target_trade_date=target_trade_date,
            )
            bounded_quotes = sorted(
                [quote for quote in quotes if quote.trade_date <= target_trade_date],
                key=lambda quote: quote.trade_date,
            )
            if not bounded_quotes or bounded_quotes[-1].trade_date != target_trade_date:
                last_date = (
                    bounded_quotes[-1].trade_date.isoformat()
                    if bounded_quotes
                    else "<empty>"
                )
                raise ProductionQfqRefreshError(
                    "PRODUCTION_QFQ_PROVIDER_STALE:"
                    f"{market}|{symbol}:last={last_date},target={target_trade_date.isoformat()}"
                )
            rows_to_write.extend(
                quote_row(quote, now, "前复权")
                for quote in bounded_quotes[-history_days:]
            )
        except Exception as exc:
            fetch_errors.append(f"PRODUCTION_QFQ_FETCH_FAILED:{market}|{symbol}:{exc}")
            failed_symbols.append(symbol)

    if fetch_errors:
        _fail(group, symbols_requested, sorted(set(failed_symbols)), fetch_errors)

    result = client.replace_history_series(
        rows_to_write,
        identities,
        existing=existing_history,
    )
    rows_written = result if isinstance(result, int) else len(rows_to_write)
    summary = _summary(
        group,
        symbols_requested,
        len(plans),
        rows_written,
        [],
        "SUCCESS",
    )
    print("PRODUCTION_QFQ_SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=sorted(PRODUCTION_MARKETS), default="all")
    args = parser.parse_args(argv)
    try:
        refresh_production_qfq(args.group)
    except ProductionQfqRefreshError as exc:
        print(f"PRODUCTION_QFQ_ERROR {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

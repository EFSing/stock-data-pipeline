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

from latest_snapshot import quote_row
from main import as_bool, beijing_now


ROOT_CAUSE_MARKER = "PRODUCTION_QFQ_NOT_REFRESHED_BY_SCHEDULED_LATEST_MODE"

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
        "历史数据源": "yfinance",
        "yfinance代码": yfinance_symbol,
        "BaoStock代码": baostock_symbol,
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
    from providers import QFQ_HISTORY_SOURCES, fetch_with_retry
    from sheets_client import SheetsClient

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
            source = str(watch.get("历史数据源") or "").strip()
            if not source:
                raise ProductionQfqRefreshError(
                    f"PRODUCTION_QFQ_SOURCE_CONFIG_REQUIRED:{market}|{symbol}"
                )
            if source not in QFQ_HISTORY_SOURCES:
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
                retry_count,
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

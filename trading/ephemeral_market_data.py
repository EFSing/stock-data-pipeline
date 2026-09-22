"""Ephemeral market-data boundary for the unattended daily report.

The production strategy continues to read configuration, decision state,
positions, and the paper ledger from Sheets.  This module changes only where
the current day's market evidence lives: provider results are projected into
the existing latest/QFQ row contract, passed to the existing production
adapter in memory, and never written back to Sheets or included in the report
metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from latest_snapshot import evaluate_latest_snapshot, project_latest_row, quote_row
from providers import (
    LATEST_PROVIDERS,
    PROVIDERS,
    QFQ_HISTORY_SOURCES,
    fetch_latest_with_retry,
    fetch_with_retry,
)
from trading.paper_lifecycle import (
    SheetsPaperLedgerStore,
    active_paper_symbols,
)
from trading.production_prerequisites import (
    STRATEGY_ACCOUNT_SHEET,
    STRATEGY_POSITION_SHEET,
    STRATEGY_UNIVERSE_SHEET,
)


WATCHLIST_SHEET = "自选清单"
EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION = "EPHEMERAL-MARKET-DATA-2026-09-14-v1"
SUPPORTED_MARKETS = frozenset({"CN", "US"})
# ``AKShare`` is retained as a configuration alias by the existing provider
# layer.  It must remain acceptable here as well, otherwise a legacy Sheet
# row would fail before that layer can route it to its supported fallback.
LEGACY_PROVIDER_ALIASES = frozenset({"AKShare"})
DEFAULT_HISTORY_DAYS = 1000
DEFAULT_RETRY_COUNT = 1
DEFAULT_RETRY_WAIT_SECONDS = 0.0
# The exact-T QFQ path must tolerate one transient provider-tail lag while
# remaining fail-closed.  This only raises the minimum QFQ attempt count; the
# configured retry wait and upper bound remain owned by the existing config.
EXACT_QFQ_MIN_RETRY_ATTEMPTS = 2
DEFAULT_CLOSE_TOLERANCE = 0.0005
DEFAULT_VOLUME_TOLERANCE = 0.02
MAX_RETRY_COUNT = 5
MAX_RETRY_WAIT_SECONDS = 30.0


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key, "")
    return str(value).strip() if value is not None else ""


def _enabled(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是", "启用"}


def _safe_error(exc: BaseException | str) -> str:
    value = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if value:
        return value[:300]
    return type(exc).__name__ if isinstance(exc, BaseException) else "unknown error"


def _config_value(config: Mapping[str, Any], key: str, default: Any) -> Any:
    value = config.get(key, default)
    return default if value is None or not str(value).strip() else value


def _ratio(value: Any, default: float) -> float:
    try:
        text = str(value).strip()
        if value is None or not text:
            return default
        return float(text[:-1]) / 100 if text.endswith("%") else float(text)
    except (TypeError, ValueError):
        raise ValueError(f"invalid ratio configuration: {value}") from None


def _config_numbers(client: Any) -> tuple[int, float, int, float, float]:
    try:
        config = dict(client.config()) if callable(getattr(client, "config", None)) else {}
    except Exception as exc:
        raise ValueError(f"provider configuration unavailable: {_safe_error(exc)}") from exc
    try:
        retry_count = max(
            1,
            min(MAX_RETRY_COUNT, int(float(_config_value(config, "retry_count", DEFAULT_RETRY_COUNT)))),
        )
        retry_wait = max(
            0.0,
            min(MAX_RETRY_WAIT_SECONDS, float(_config_value(config, "retry_wait_seconds", DEFAULT_RETRY_WAIT_SECONDS))),
        )
        history_days = max(1, int(float(_config_value(config, "history_days", DEFAULT_HISTORY_DAYS))))
        close_tolerance = _ratio(config.get("close_tolerance_pct"), DEFAULT_CLOSE_TOLERANCE)
        volume_tolerance = _ratio(config.get("volume_tolerance_pct"), DEFAULT_VOLUME_TOLERANCE)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"provider configuration malformed: {_safe_error(exc)}") from exc
    return retry_count, retry_wait, history_days, close_tolerance, volume_tolerance


def _records(client: Any, sheet_name: str, errors: list[str]) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in client.records(sheet_name)]
    except Exception as exc:
        errors.append(f"{sheet_name}: {_safe_error(exc)}")
        return []


def _required_symbols(
    client: Any,
    market: str,
    errors: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Collect formal, active-position, and paper-continuation identities."""

    accounts = _records(client, STRATEGY_ACCOUNT_SHEET, errors)
    universe = _records(client, STRATEGY_UNIVERSE_SHEET, errors)
    positions = _records(client, STRATEGY_POSITION_SHEET, errors)
    enabled_accounts = {
        _text(row, "账户ID")
        for row in accounts
        if _enabled(row.get("启用")) and _text(row, "市场").upper() == market
    }
    symbols: set[str] = set()
    for row in universe:
        if (
            _enabled(row.get("启用"))
            and _text(row, "账户ID") in enabled_accounts
            and _text(row, "市场").upper() == market
            and _text(row, "统一代码")
        ):
            symbols.add(_text(row, "统一代码").upper())
    for row in positions:
        if (
            _enabled(row.get("启用"))
            and _text(row, "账户ID") in enabled_accounts
            and _text(row, "市场").upper() == market
            and _text(row, "统一代码")
        ):
            symbols.add(_text(row, "统一代码").upper())

    paper_symbols: tuple[str, ...] = ()
    try:
        paper_store = SheetsPaperLedgerStore(client, write_enabled=False)
        paper_symbols = tuple(
            sorted(symbol for paper_market, symbol in active_paper_symbols(paper_store)
                   if paper_market == market)
        )
        symbols.update(paper_symbols)
    except Exception:
        # The paper ledger is optional for an ordinary report.  A missing or
        # unreadable paper sheet must not turn a read-only report into a write
        # path or hide formal/position data.
        paper_symbols = ()
    return tuple(sorted(symbols)), paper_symbols


def _watch_configurations(client: Any, market: str, errors: list[str]) -> dict[str, dict[str, Any]]:
    rows = _records(client, WATCHLIST_SHEET, errors)
    result: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        if not _enabled(row.get("启用")) or _text(row, "市场").upper() != market:
            continue
        symbol = _text(row, "统一代码").upper()
        if not symbol:
            errors.append(f"{WATCHLIST_SHEET}: provider configuration missing symbol")
            continue
        if symbol in result:
            duplicates.add(symbol)
            continue
        result[symbol] = dict(row)
    for symbol in sorted(duplicates):
        result.pop(symbol, None)
        errors.append(f"EPHEMERAL_PROVIDER_CONFIG_DUPLICATE:{market}|{symbol}")
    return result


def _provider_config_errors(watch: Mapping[str, Any]) -> tuple[str, ...]:
    required = ("主数据源", "校验数据源", "历史数据源", "时区", "收盘时间", "币种")
    missing = [field for field in required if not _text(watch, field)]
    primary = _text(watch, "主数据源")
    verifier = _text(watch, "校验数据源")
    history = _text(watch, "历史数据源")
    for source, field_set in (
        (primary, LATEST_PROVIDERS),
        (verifier, LATEST_PROVIDERS),
        (history, PROVIDERS),
    ):
        if source and source not in field_set and source not in LEGACY_PROVIDER_ALIASES:
            missing.append(f"unknown provider {source}")
    if history and history not in QFQ_HISTORY_SOURCES and history not in LEGACY_PROVIDER_ALIASES:
        missing.append(f"qfq provider {history} unsupported")
    for source in {primary, verifier, history}:
        if source == "BaoStock" and not _text(watch, "BaoStock代码"):
            missing.append("BaoStock代码")
        if source == "yfinance" and not _text(watch, "yfinance代码"):
            missing.append("yfinance代码")
    try:
        if _text(watch, "时区"):
            ZoneInfo(_text(watch, "时区"))
    except Exception:
        missing.append(f"invalid timezone {_text(watch, '时区')}")
    return tuple(dict.fromkeys(f"provider configuration missing/invalid: {item}" for item in missing))


def _quote_identity_is_valid(quote: Any, watch: Mapping[str, Any]) -> bool:
    return (
        str(getattr(quote, "symbol", "")).strip().upper() == _text(watch, "统一代码").upper()
        and str(getattr(quote, "market", "")).strip().upper() == _text(watch, "市场").upper()
    )


def _complete_latest_preclose(
    snapshot: Any,
    primary_quotes: Sequence[Any] = (),
    verifier_quotes: Sequence[Any] = (),
) -> tuple[Any, str | None]:
    """Fill only a missing selected-source preclose from the same-session peer.

    The existing latest validation contract compares close/volume across the
    two sources, while the production adapter requires the projected latest
    row to carry ``昨收``.  Some bounded provider responses omit that optional
    field on the selected source even though the same-date peer has it.  Use
    that peer only for the missing field; never cross a session boundary or
    replace the selected OHLC quote.
    """

    chosen = snapshot.chosen
    if chosen is None or chosen.preclose is not None:
        return snapshot, None
    peers = (
        snapshot.verifier if chosen is snapshot.primary else snapshot.primary,
    )
    peer = next(
        (
            quote
            for quote in peers
            if quote is not None
            and quote.trade_date == chosen.trade_date
            and quote.preclose is not None
        ),
        None,
    )
    if peer is None:
        selected_quotes = primary_quotes if chosen is snapshot.primary else verifier_quotes
        prior = max(
            (
                quote
                for quote in selected_quotes
                if quote is not None
                and quote.trade_date < chosen.trade_date
                and quote.close is not None
            ),
            key=lambda quote: quote.trade_date,
            default=None,
        )
        if prior is None:
            return snapshot, None
        return replace(snapshot, chosen=replace(chosen, preclose=prior.close)), prior.source
    return replace(snapshot, chosen=replace(chosen, preclose=peer.preclose)), peer.source


@dataclass(frozen=True)
class EphemeralMarketDataSnapshot:
    market: str
    as_of_date: date
    fetched_at: datetime
    required_symbols: tuple[str, ...]
    active_paper_symbols: tuple[str, ...]
    latest_rows: tuple[dict[str, Any], ...]
    qfq_rows: tuple[dict[str, Any], ...]
    symbol_status: Mapping[str, Mapping[str, Any]]
    provider_status: Mapping[str, Mapping[str, Any]]
    errors: tuple[str, ...]
    input_fingerprint: str
    retry_count: int
    history_days: int

    def to_dict(self) -> dict[str, Any]:
        """Return report-safe metadata without any market-data rows."""

        return {
            "protocol_version": EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION,
            "market": self.market,
            "as_of_date": self.as_of_date.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "required_symbol_count": len(self.required_symbols),
            "required_symbols": list(self.required_symbols),
            "active_paper_symbols": list(self.active_paper_symbols),
            "latest_row_count": len(self.latest_rows),
            "qfq_row_count": len(self.qfq_rows),
            "symbol_status": {
                symbol: dict(status) for symbol, status in sorted(self.symbol_status.items())
            },
            "provider_status": {
                symbol: dict(status) for symbol, status in sorted(self.provider_status.items())
            },
            "errors": list(self.errors),
            "input_fingerprint": self.input_fingerprint,
            "retry_count": self.retry_count,
            "history_days": self.history_days,
            "raw_market_data_persisted": False,
            "qfq_persisted": False,
        }


def _fingerprint(
    market: str,
    as_of_date: date,
    latest_rows: Sequence[Mapping[str, Any]],
    qfq_rows: Sequence[Mapping[str, Any]],
    statuses: Mapping[str, Mapping[str, Any]],
) -> str:
    def clean(value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Mapping):
            return {str(key): clean(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        return value

    payload = {
        "market": market,
        "as_of_date": as_of_date.isoformat(),
        "latest": [clean(row) for row in latest_rows],
        "qfq": [clean(row) for row in qfq_rows],
        "statuses": clean(statuses),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_ephemeral_market_data(
    client: Any,
    *,
    market: str,
    as_of_date: date,
    now: datetime | None = None,
) -> EphemeralMarketDataSnapshot:
    """Fetch only the target market's required rows into memory.

    The provider fallback and latest/QFQ validation contracts are deliberately
    delegated to ``providers`` and ``latest_snapshot``.  A provider failure
    creates a fail-closed status for that identity; it never substitutes T-1.
    """

    normalized_market = str(market).strip().upper()
    if normalized_market not in SUPPORTED_MARKETS:
        raise ValueError(f"unsupported cloud market: {normalized_market}")
    fetched_at = now or datetime.now(timezone.utc)
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("cloud report requires timezone-aware now")

    errors: list[str] = []
    try:
        retry_count, retry_wait, history_days, close_tolerance, volume_tolerance = _config_numbers(client)
    except ValueError as exc:
        retry_count, retry_wait, history_days = DEFAULT_RETRY_COUNT, DEFAULT_RETRY_WAIT_SECONDS, DEFAULT_HISTORY_DAYS
        close_tolerance, volume_tolerance = DEFAULT_CLOSE_TOLERANCE, DEFAULT_VOLUME_TOLERANCE
        errors.append(_safe_error(exc))

    required_symbols, paper_symbols = _required_symbols(client, normalized_market, errors)
    watches = _watch_configurations(client, normalized_market, errors)
    latest_rows: list[dict[str, Any]] = []
    qfq_rows: list[dict[str, Any]] = []
    symbol_status: dict[str, dict[str, Any]] = {}
    provider_status: dict[str, dict[str, Any]] = {}

    start_date = as_of_date - timedelta(days=max(history_days * 2, 365))
    for symbol in required_symbols:
        key = f"{normalized_market}|{symbol}"
        watch = watches.get(symbol)
        status = {"latest": "UNAVAILABLE", "qfq": "UNAVAILABLE"}
        provider_detail: dict[str, Any] = {}
        symbol_errors: list[str] = []
        if watch is None:
            symbol_errors.append(f"EPHEMERAL_PROVIDER_CONFIG_REQUIRED:{key}")
        else:
            config_errors = _provider_config_errors(watch)
            if config_errors:
                symbol_errors.extend(config_errors)
            primary_source = _text(watch, "主数据源")
            verifier_source = _text(watch, "校验数据源")
            primary_quotes: list[Any] = []
            verifier_quotes: list[Any] = []
            if not config_errors:
                try:
                    quotes = fetch_latest_with_retry(
                        primary_source, dict(watch), as_of_date, retry_count, retry_wait,
                        target_trade_date=as_of_date,
                    )
                    if any(not _quote_identity_is_valid(quote, watch) for quote in quotes):
                        raise ValueError("latest provider identity mismatch")
                    primary_quotes.extend(quotes)
                    provider_detail[f"latest_{primary_source}"] = "OK"
                except Exception as exc:
                    provider_detail[f"latest_{primary_source}"] = f"FAILED:{type(exc).__name__}"
                    symbol_errors.append(f"latest {primary_source}: {_safe_error(exc)}")

                excluded_verifier_sources = tuple(sorted({
                    str(quote.source).strip()
                    for quote in primary_quotes
                    if str(getattr(quote, "source", "")).strip()
                }))
                provider_detail["latest_verifier_excluded_sources"] = list(excluded_verifier_sources)
                try:
                    quotes = fetch_latest_with_retry(
                        verifier_source, dict(watch), as_of_date, retry_count, retry_wait,
                        target_trade_date=as_of_date,
                        excluded_sources=excluded_verifier_sources,
                    )
                    if any(not _quote_identity_is_valid(quote, watch) for quote in quotes):
                        raise ValueError("latest provider identity mismatch")
                    verifier_quotes.extend(quotes)
                    provider_detail[f"latest_{verifier_source}"] = "OK"
                except Exception as exc:
                    provider_detail[f"latest_{verifier_source}"] = f"FAILED:{type(exc).__name__}"
                    symbol_errors.append(f"latest {verifier_source}: {_safe_error(exc)}")
                try:
                    latest_snapshot = evaluate_latest_snapshot(
                        primary_quotes,
                        verifier_quotes,
                        fetched_at=fetched_at,
                        timezone_name=_text(watch, "时区"),
                        close_time_text=_text(watch, "收盘时间"),
                        close_tolerance=close_tolerance,
                        volume_tolerance=volume_tolerance,
                        primary_source=primary_source,
                        verifier_source=verifier_source,
                        expected_symbol=symbol,
                        expected_market=normalized_market,
                        apply_calendar_freshness=False,
                    )
                    if latest_snapshot.chosen is None:
                        symbol_errors.append("latest unavailable: no completed quote")
                    else:
                        projected_snapshot, preclose_source = _complete_latest_preclose(
                            latest_snapshot,
                            primary_quotes=primary_quotes,
                            verifier_quotes=verifier_quotes,
                        )
                        latest_rows.append(project_latest_row(projected_snapshot, fetched_at))
                        if preclose_source:
                            provider_detail["latest_preclose_source"] = preclose_source
                        status["latest"] = latest_snapshot.displayed_status or "UNAVAILABLE"
                        provider_detail["latest_status"] = status["latest"]
                        provider_detail["latest_configured_primary_source"] = primary_source
                        provider_detail["latest_configured_verifier_source"] = verifier_source
                        provider_detail["latest_actual_primary_source"] = (
                            latest_snapshot.primary.source if latest_snapshot.primary else None
                        )
                        provider_detail["latest_actual_verifier_source"] = (
                            latest_snapshot.verifier.source if latest_snapshot.verifier else None
                        )
                        if latest_snapshot.fallback_notes:
                            provider_detail["latest_fallback_notes"] = list(latest_snapshot.fallback_notes)
                        if latest_snapshot.chosen.trade_date != as_of_date:
                            symbol_errors.append(
                                f"latest date {latest_snapshot.chosen.trade_date.isoformat()} != T {as_of_date.isoformat()}"
                            )
                        if status["latest"] != "已验证":
                            symbol_errors.append(f"latest validation: {status['latest']}")
                except Exception as exc:
                    symbol_errors.append(f"latest evaluation: {_safe_error(exc)}")

                history_source = _text(watch, "历史数据源")
                try:
                    quotes = fetch_with_retry(
                        history_source,
                        dict(watch),
                        "qfq",
                        start_date,
                        as_of_date,
                        max(retry_count, EXACT_QFQ_MIN_RETRY_ATTEMPTS),
                        retry_wait,
                        target_trade_date=as_of_date,
                    )
                    if any(not _quote_identity_is_valid(quote, watch) for quote in quotes):
                        raise ValueError("qfq provider identity mismatch")
                    bounded_quotes = tuple(
                        sorted((quote for quote in quotes if quote.trade_date <= as_of_date), key=lambda quote: quote.trade_date)
                    )
                    if not bounded_quotes or bounded_quotes[-1].trade_date != as_of_date:
                        last_date = bounded_quotes[-1].trade_date.isoformat() if bounded_quotes else "none"
                        raise ValueError(f"qfq last date {last_date} != T {as_of_date.isoformat()}")
                    qfq_rows.extend(quote_row(quote, fetched_at, "前复权") for quote in bounded_quotes)
                    status["qfq"] = "OK"
                    provider_detail["qfq"] = f"OK:{history_source}"
                except Exception as exc:
                    provider_detail["qfq"] = f"FAILED:{type(exc).__name__}"
                    symbol_errors.append(f"qfq {history_source}: {_safe_error(exc)}")

        if symbol_errors:
            symbol_errors = list(dict.fromkeys(symbol_errors))
            errors.extend(f"{key}: {item}" for item in symbol_errors)
        else:
            status["latest"] = status["latest"] or "OK"
        symbol_status[symbol] = {**status, "errors": symbol_errors}
        provider_status[symbol] = provider_detail

    errors = list(dict.fromkeys(errors))
    fingerprint = _fingerprint(normalized_market, as_of_date, latest_rows, qfq_rows, symbol_status)
    return EphemeralMarketDataSnapshot(
        market=normalized_market,
        as_of_date=as_of_date,
        fetched_at=fetched_at,
        required_symbols=required_symbols,
        active_paper_symbols=paper_symbols,
        latest_rows=tuple(latest_rows),
        qfq_rows=tuple(qfq_rows),
        symbol_status=symbol_status,
        provider_status=provider_status,
        errors=tuple(errors),
        input_fingerprint=fingerprint,
        retry_count=retry_count,
        history_days=history_days,
    )


__all__ = [
    "EXACT_QFQ_MIN_RETRY_ATTEMPTS",
    "EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION",
    "EphemeralMarketDataSnapshot",
    "load_ephemeral_market_data",
]

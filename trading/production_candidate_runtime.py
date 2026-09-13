"""Read-only production Candidate -> Daily Chain input runtime.

This module is intentionally a small adapter around the existing Candidate
selector and the existing production history providers.  It does not write
Sheets, persist Candidate rows, approve events, allocate capital, or submit
orders.  The only output that survives the call is the in-memory result used
by the caller for that day's Daily Decision Chain run.

The runtime uses two data stages:

* Candidate screening: official seed metadata plus one batched raw-history
  request per yfinance chunk, with the existing 60-bar/20D/60D selector.
* Strategy analysis: the selected Candidate symbols only, using the existing
  yfinance QFQ history path and exact completed-session-T validation.

Formal strategy-pool and open-position history remains owned by
``ProductionInputAdapter`` and is merged by the production runner.  This
module never replaces that data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import math
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

from core import Quote
from trading.candidate_universe import (
    CandidateRecord,
    CandidateUniverse,
    MIN_HISTORY_BARS,
    SeedSecurity,
    TOP_N_PER_SECTOR,
    select_candidate_universe,
)
from trading.candidate_universe_sources import (
    BaoStockCandidateSeedAdapter,
    IwbOfficialHoldingsAdapter,
)
from trading.daily_decision_chain import (
    DATA_BAD,
    DATA_OK,
    DATA_STALE,
    DATA_UNAVAILABLE,
    CompletedSessionIdentity,
    DailySymbolInput,
)
from trading.models import validate_quote_series


STRATEGY_HISTORY_BARS = 1000
YFINANCE_BATCH_CHUNK = 80
# yfinance accepts an explicit integer thread bound.  Keep the bound small and
# stable so Stage A gains transport parallelism without opening an unbounded
# client-side fan-out or changing the batch/normalization contract.
YFINANCE_BATCH_THREADS = 8
# Stage B still uses one existing per-symbol QFQ provider request.  A small,
# explicit pool overlaps network wait while keeping the request fan-out
# bounded and the result/error order deterministic.
YFINANCE_DEEP_HISTORY_WORKERS = 4
US_HISTORICAL_QFQ_ASOF_UNVERIFIED = "US_HISTORICAL_QFQ_ASOF_UNVERIFIED"
US_COMPLETED_SESSION_REQUIRED = "US_COMPLETED_SESSION_REQUIRED"
PRODUCTION_CANDIDATE_ACCOUNT_ROUTING_REQUIRED = (
    "READY_FOR_DECISION_CANDIDATE_ACCOUNT_ROUTING"
)


class CandidateRuntimeError(RuntimeError):
    """A Candidate runtime contract could not be completed safely."""


@dataclass(frozen=True)
class HistoryLoadResult:
    """Normalized output of one history-loading stage.

    ``histories`` is keyed by canonical ``(market, symbol)``-local symbol
    identity.  Errors are stage-level or batch-level messages; individual
    missing symbols remain data-quality exclusions and do not abort the other
    symbols in the same market.
    """

    histories: Mapping[str, Sequence[Quote]]
    api_requests: int = 0
    rows: int = 0
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized = {
            str(symbol).strip().upper(): tuple(values)
            for symbol, values in self.histories.items()
        }
        object.__setattr__(self, "histories", normalized)
        object.__setattr__(self, "api_requests", int(self.api_requests))
        object.__setattr__(self, "rows", int(self.rows))
        object.__setattr__(self, "errors", tuple(str(error) for error in self.errors))


SeedLoader = Callable[[date], Any]
HistoryLoader = Callable[
    [tuple[Any, ...], date, date], HistoryLoadResult
]
SessionWindowLoader = Callable[[str, date, int], tuple[date, ...]]


@dataclass(frozen=True)
class CandidateMarketRuntimeResult:
    """One independent CN or US Candidate market run."""

    market: str
    as_of_date: date
    seed_source_as_of: date | None
    seeds: tuple[Any, ...]
    universe: CandidateUniverse
    deep_histories: Mapping[str, tuple[Quote, ...]]
    deep_errors: Mapping[str, tuple[str, ...]]
    stage_timings: Mapping[str, Mapping[str, Any]]
    errors: tuple[str, ...]
    status: str
    qfq_contract: Mapping[str, Any]
    deep_requested_symbols: tuple[str, ...] = ()
    paper_active_symbols: tuple[str, ...] = ()
    paper_seeds: tuple[Any, ...] = ()

    @property
    def seed_count(self) -> int:
        return len(self.seeds)

    @property
    def data_qualified_count(self) -> int:
        return sum(
            record.history_bar_count >= MIN_HISTORY_BARS
            and record.latest_history_date is not None
            for record in self.universe.records
        )

    @property
    def included_records(self) -> tuple[CandidateRecord, ...]:
        return self.universe.included

    @property
    def included_symbols(self) -> tuple[str, ...]:
        return tuple(record.symbol for record in self.included_records)

    @property
    def deep_ready_symbols(self) -> tuple[str, ...]:
        return tuple(
            symbol
            for symbol in self.included_symbols
            if _deep_data_status(
                self.deep_histories.get(symbol, ()),
                as_of_date=self.as_of_date,
                expected_market=self.market,
                expected_symbol=symbol,
                expected_currency=_seed_currency(self.seeds, symbol),
            )
            == DATA_OK
        )

    @property
    def paper_deep_ready_symbols(self) -> tuple[str, ...]:
        return tuple(
            symbol
            for symbol in self.paper_active_symbols
            if _deep_data_status(
                self.deep_histories.get(symbol, ()),
                as_of_date=self.as_of_date,
                expected_market=self.market,
                expected_symbol=symbol,
                expected_currency=_seed_currency(self.paper_seeds, symbol),
            )
            == DATA_OK
        )

    def daily_inputs(
        self, session_identity: CompletedSessionIdentity
    ) -> tuple[DailySymbolInput, ...]:
        """Project selected candidates into existing Daily Chain inputs.

        A failed deep load is represented by an empty, DATA_* input so the
        existing chain emits its ordinary fail-closed data row.  It is never
        silently dropped from the daily analysis universe.
        """

        seed_by_symbol = {
            str(seed.symbol).strip().upper(): seed for seed in self.seeds
        }
        seed_by_symbol.update(
            {str(seed.symbol).strip().upper(): seed for seed in self.paper_seeds}
        )
        paper_keys = {
            canonical_key(self.market, symbol)
            for symbol in self.paper_active_symbols
        }
        projected_symbols: list[tuple[str, bool]] = [
            (record.symbol, canonical_key(self.market, record.symbol) in paper_keys)
            for record in self.included_records
        ]
        projected_keys = {
            canonical_key(self.market, symbol) for symbol, _ in projected_symbols
        }
        projected_symbols.extend(
            (symbol, True)
            for symbol in self.paper_active_symbols
            if canonical_key(self.market, symbol) not in projected_keys
        )
        values: list[DailySymbolInput] = []
        for symbol, paper_tracked in projected_symbols:
            seed = seed_by_symbol.get(symbol.upper())
            history = tuple(self.deep_histories.get(symbol.upper(), ()))
            status = _deep_data_status(
                history,
                as_of_date=self.as_of_date,
                expected_market=self.market,
                expected_symbol=symbol,
                expected_currency=getattr(seed, "currency", None),
            )
            if status != DATA_OK:
                history = ()
            values.append(
                DailySymbolInput(
                    symbol=symbol,
                    market=self.market,
                    as_of_date=self.as_of_date,
                    qfq_history=history,
                    data_quality_status=status,
                    completed_session_identity=session_identity,
                    paper_tracked=paper_tracked,
                )
            )
        return tuple(values)

    def to_dict(self) -> dict[str, Any]:
        reason_counts: dict[str, int] = {}
        for record in self.universe.records:
            reason = record.exclusion_reason or "INCLUDED"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        deep_ready = self.deep_ready_symbols
        return {
            "market": self.market,
            "as_of_date": self.as_of_date.isoformat(),
            "seed_source_as_of": (
                self.seed_source_as_of.isoformat()
                if self.seed_source_as_of is not None
                else None
            ),
            "seed_count": self.seed_count,
            "candidate_data_qualified_count": self.data_qualified_count,
            "candidate_included_count": len(self.included_records),
            "candidate_included_symbols": list(self.included_symbols),
            "paper_active_count": len(self.paper_active_symbols),
            "paper_active_symbols": list(self.paper_active_symbols),
            "candidate_exclusion_reason_counts": dict(sorted(reason_counts.items())),
            "deep_history_requested_count": len(self.deep_requested_symbols),
            "deep_history_requested_symbols": list(self.deep_requested_symbols),
            "deep_history_ready_count": len(deep_ready),
            "deep_history_ready_symbols": list(deep_ready),
            "paper_deep_history_ready_count": len(self.paper_deep_ready_symbols),
            "paper_deep_history_ready_symbols": list(self.paper_deep_ready_symbols),
            "deep_history_errors": {
                symbol: list(errors)
                for symbol, errors in sorted(self.deep_errors.items())
            },
            "stage_timings": {
                name: dict(values)
                for name, values in self.stage_timings.items()
            },
            "errors": list(self.errors),
            "status": self.status,
            "qfq_contract": dict(self.qfq_contract),
            "read_only": True,
            "sheets_write": False,
            "strategy_pool_write": False,
        }


def _new_stage_timings() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "elapsed_seconds": 0.0,
            "api_requests": 0,
            "symbols": 0,
            "rows": 0,
            "usable_count": 0,
            "failed_count": 0,
            "status": "NOT_RUN",
        }
        for name in (
            "seed_metadata",
            "candidate_short_history",
            "candidate_selector",
            "deep_history",
            "total",
        )
    }


def _record_stage(
    timings: dict[str, dict[str, Any]],
    name: str,
    *,
    started: float,
    api_requests: int = 0,
    symbols: int = 0,
    rows: int = 0,
    usable_count: int = 0,
    failed_count: int = 0,
    status: str = "SUCCESS",
    **extra: Any,
) -> None:
    timings[name] = {
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "api_requests": int(api_requests),
        "symbols": int(symbols),
        "rows": int(rows),
        "usable_count": int(usable_count),
        "failed_count": int(failed_count),
        "status": status,
        **extra,
    }


def _seed_currency(seeds: Sequence[Any], symbol: str) -> str | None:
    target = str(symbol).strip().upper()
    for seed in seeds:
        if str(getattr(seed, "symbol", "")).strip().upper() == target:
            return str(getattr(seed, "currency", "") or "").strip() or None
    return None


def canonical_key(market: str, symbol: str) -> tuple[str, str]:
    """Return one market-aware identity for Sheets and Candidate inputs."""

    normalized_market = str(market).strip().upper()
    value = str(symbol).strip().upper()
    if normalized_market == "CN":
        code, separator, suffix = value.partition(".")
        if code.isdigit() and len(code) == 6:
            if not separator:
                suffix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
            elif suffix in {"SSE", "XSHG"}:
                suffix = "SH"
            elif suffix in {"SZSE", "XSHE"}:
                suffix = "SZ"
            if suffix in {"SH", "SZ"}:
                value = f"{code}.{suffix}"
    return normalized_market, value


def _paper_continuation_seed(
    market: str,
    symbol: str,
    official_seeds: Sequence[Any],
) -> SeedSecurity:
    """Create metadata-only continuation identity for an active paper plan.

    The seed is not a price fixture and never bypasses the QFQ loader.  When
    the symbol is present in the official seed set, retain its provider
    metadata while preserving the ledger's exact symbol identity.
    """

    normalized_market = str(market).strip().upper()
    normalized_symbol = str(symbol).strip().upper()
    target_key = canonical_key(normalized_market, normalized_symbol)
    matched = next(
        (
            seed
            for seed in official_seeds
            if canonical_key(normalized_market, str(seed.symbol).strip().upper())
            == target_key
        ),
        None,
    )
    if matched is not None:
        return replace(
            matched,
            symbol=normalized_symbol,
            source="PAPER_TRACKED",
            name=str(getattr(matched, "name", "") or normalized_symbol),
        )
    if normalized_market == "CN":
        code, separator, exchange = normalized_symbol.partition(".")
        if not separator:
            exchange = "SH" if code.startswith(("5", "6", "9")) else "SZ"
        elif exchange.upper() in {"SSE", "XSHG"}:
            exchange = "SH"
        elif exchange.upper() in {"SZSE", "XSHE"}:
            exchange = "SZ"
        source_symbol = f"{exchange.lower()}.{code}"
        currency = "CNY"
    else:
        source_symbol = normalized_symbol
        currency = "USD"
        exchange = None
    return SeedSecurity(
        market=normalized_market,
        symbol=normalized_symbol,
        source_symbol=source_symbol,
        name=normalized_symbol,
        sector=None,
        asset_class="Equity",
        exchange=exchange,
        currency=currency,
        source="PAPER_TRACKED",
        metadata_status="PAPER_CONTINUATION_IDENTITY_ONLY",
        provenance=("策略模拟账本", "PAPER_TRACKED"),
    )


def _deep_data_status(
    history: Sequence[Quote],
    *,
    as_of_date: date,
    expected_market: str,
    expected_symbol: str,
    expected_currency: str | None,
) -> str:
    if not history:
        return DATA_UNAVAILABLE
    values = tuple(sorted(history, key=lambda item: item.trade_date))
    try:
        validate_quote_series(list(values))
    except (TypeError, ValueError):
        return DATA_BAD
    if any(item.trade_date > as_of_date for item in values):
        return DATA_BAD
    if values[-1].trade_date < as_of_date:
        return DATA_STALE
    if values[-1].trade_date > as_of_date:
        return DATA_BAD
    if any(
        item.market.upper() != expected_market.upper()
        or item.symbol.upper() != expected_symbol.upper()
        or (
            expected_currency is not None
            and item.currency.upper() != expected_currency.upper()
        )
        or any(
            not math.isfinite(float(number))
            for number in (item.open, item.high, item.low, item.close)
        )
        for item in values
    ):
        return DATA_BAD
    if len(values) < MIN_HISTORY_BARS:
        return DATA_BAD
    return DATA_OK


def _normalise_seed_payload(value: Any) -> tuple[date | None, tuple[Any, ...]]:
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and (value[0] is None or isinstance(value[0], date))
        and isinstance(value[1], (tuple, list))
    ):
        return value[0], tuple(value[1])
    return None, tuple(value)


def _normalise_history_result(value: Any) -> HistoryLoadResult:
    if isinstance(value, HistoryLoadResult):
        return value
    if isinstance(value, Mapping):
        return HistoryLoadResult(value)
    raise TypeError("history loader must return HistoryLoadResult or mapping")


def _completed_session_window(
    market: str, as_of_date: date, bars: int
) -> tuple[date, ...]:
    try:
        import exchange_calendars as xc
        import pandas as pd
        from trading.production_prerequisites import ExactExchangeCalendarProvider

        calendar_name = ExactExchangeCalendarProvider().calendar_name(market)
        calendar = xc.get_calendar(calendar_name)
        lookback_days = max(180, bars * 3 + 30)
        sessions = calendar.sessions_in_range(
            pd.Timestamp(as_of_date) - pd.Timedelta(days=lookback_days),
            pd.Timestamp(as_of_date),
        )
        values = tuple(session.date() for session in sessions)
    except (ImportError, KeyError, TypeError, ValueError) as exc:
        raise CandidateRuntimeError("COMPLETED_SESSION_WINDOW_SETUP_FAILED") from exc
    if len(values) < bars:
        raise CandidateRuntimeError("COMPLETED_SESSION_WINDOW_INSUFFICIENT")
    return values[-bars:]


def _normalise_ticker(value: str) -> str:
    return str(value).strip().upper().replace(".", "-").replace("/", "-")


def _yfinance_ticker(seed: Any) -> str:
    symbol = str(seed.symbol).strip().upper()
    market = str(seed.market).strip().upper()
    if market == "CN":
        code, _, exchange = symbol.partition(".")
        exchange = exchange.upper()
        if exchange in {"SH", "SSE", "XSHG"}:
            return f"{code}.SS"
        if exchange in {"SZ", "SZSE", "XSHE"}:
            return f"{code}.SZ"
        if code.isdigit() and len(code) == 6:
            return f"{code}.SS" if code.startswith(("5", "6", "9")) else f"{code}.SZ"
    return symbol.replace("/", "-").replace(".", "-")


def _provider_watch(seed: Any) -> dict[str, str]:
    ticker = _yfinance_ticker(seed)
    source_symbol = str(getattr(seed, "source_symbol", "") or "").strip()
    market = str(seed.market).strip().upper()
    return {
        "统一代码": str(seed.symbol).strip().upper(),
        "名称": str(getattr(seed, "name", "") or seed.symbol),
        "市场": market,
        "币种": str(seed.currency).strip().upper(),
        "yfinance代码": ticker,
        "BaoStock代码": source_symbol or ticker,
        "时区": "America/New_York" if market == "US" else "Asia/Shanghai",
    }


def _empty_frame_like(frame: Any) -> Any:
    try:
        return frame.iloc[:, 0:0]
    except AttributeError:
        return frame


def _download_symbol_frame(frame: Any, ticker: str) -> Any:
    """Select a ticker from either yfinance MultiIndex column layout."""

    try:
        import pandas as pd
    except ImportError:
        return _empty_frame_like(frame)
    if not isinstance(getattr(frame, "columns", None), pd.MultiIndex):
        return frame
    target = _normalise_ticker(ticker)
    for level in range(frame.columns.nlevels):
        for label in tuple(dict.fromkeys(frame.columns.get_level_values(level))):
            if _normalise_ticker(str(label)) != target:
                continue
            selected = frame.xs(label, axis=1, level=level, drop_level=True)
            columns = {
                str(column).strip().lower(): column
                for column in getattr(selected, "columns", ())
            }
            if {"open", "high", "low", "close"}.issubset(columns):
                return selected
    return _empty_frame_like(frame)


def _as_frame_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _batch_quotes(
    frame: Any,
    seed: Any,
    *,
    ticker: str,
    start_date: date,
    end_date: date,
) -> tuple[Quote, ...]:
    """Project one symbol from a batched yfinance frame.

    The frame selection is Candidate-specific; quote normalization stays in
    the existing provider helper so raw yfinance semantics do not diverge from
    the formal history path.
    """

    selected = _download_symbol_frame(frame, ticker)
    selected_columns = getattr(selected, "columns", None)
    if selected_columns is None or len(selected_columns) == 0:
        return ()
    try:
        selected = selected.sort_index().reset_index()
        columns = {
            str(column).strip().lower(): column
            for column in getattr(selected, "columns", ())
        }
        date_column = columns.get("日期") or columns.get("date") or columns.get("index")
        required = {
            field: columns.get(field) for field in ("open", "high", "low", "close")
        }
        if date_column is None or any(value is None for value in required.values()):
            return ()
        selected["日期"] = selected[date_column].map(_as_frame_date)
        selected = selected[
            (selected["日期"] >= start_date) & (selected["日期"] <= end_date)
        ]
        rename = {
            column: field.title()
            for field, column in required.items()
        }
        volume_column = columns.get("volume")
        if volume_column is not None:
            rename[volume_column] = "Volume"
        selected = selected.rename(columns=rename)
        from providers import _records_to_quotes

        return tuple(_records_to_quotes(selected, _provider_watch(seed), "yfinance"))
    except (AttributeError, KeyError, TypeError, ValueError):
        return ()


def _default_short_history_loader(
    seeds: tuple[Any, ...], start_date: date, end_date: date
) -> HistoryLoadResult:
    """Use the existing yfinance provider in fixed, bounded batches."""

    import yfinance as yf

    histories: dict[str, tuple[Quote, ...]] = {
        str(seed.symbol).strip().upper(): () for seed in seeds
    }
    errors: list[str] = []
    rows = 0
    requests = 0
    for offset in range(0, len(seeds), YFINANCE_BATCH_CHUNK):
        chunk = seeds[offset : offset + YFINANCE_BATCH_CHUNK]
        tickers = [_yfinance_ticker(seed) for seed in chunk]
        try:
            frame = yf.download(
                tickers=tickers,
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                repair=False,
                group_by="ticker",
                threads=YFINANCE_BATCH_THREADS,
                progress=False,
            )
            for seed, ticker in zip(chunk, tickers):
                quotes = _batch_quotes(
                    frame,
                    seed,
                    ticker=ticker,
                    start_date=start_date,
                    end_date=end_date,
                )
                histories[str(seed.symbol).strip().upper()] = quotes
                rows += len(quotes)
        except Exception as exc:
            errors.append(f"BATCH_{type(exc).__name__}")
        requests += 1
    return HistoryLoadResult(histories, requests, rows, tuple(errors))


def _default_deep_qfq_history_loader(
    seeds: tuple[Any, ...], start_date: date, end_date: date
) -> HistoryLoadResult:
    """Reuse the existing formal yfinance QFQ provider per selected symbol."""

    def load_one(seed: Any) -> tuple[str, tuple[Quote, ...], str | None]:
        from providers import fetch_with_retry

        symbol = str(seed.symbol).strip().upper()
        try:
            quotes = fetch_with_retry(
                "yfinance",
                _provider_watch(seed),
                "qfq",
                start_date,
                end_date,
                retry_count=1,
                retry_wait_seconds=0.0,
                target_trade_date=end_date,
            )
            return symbol, tuple(quotes), None
        except Exception as exc:
            return symbol, (), f"{symbol}:{type(exc).__name__}"

    # executor.map() yields results in input order even when requests finish
    # out of order, preserving the old deterministic histories/error contract.
    with ThreadPoolExecutor(
        max_workers=YFINANCE_DEEP_HISTORY_WORKERS,
        thread_name_prefix="candidate-qfq",
    ) as executor:
        completed = tuple(executor.map(load_one, seeds))

    histories: dict[str, tuple[Quote, ...]] = {}
    errors: list[str] = []
    rows = 0
    for symbol, quotes, error in completed:
        if error is not None:
            errors.append(error)
            continue
        histories[symbol] = quotes
        rows += len(quotes)
    return HistoryLoadResult(histories, len(seeds), rows, tuple(errors))


def _latest_completed_us_session(now: datetime) -> date:
    if now.tzinfo is None or now.utcoffset() is None:
        raise CandidateRuntimeError(US_COMPLETED_SESSION_REQUIRED)
    try:
        import exchange_calendars as xc
        import pandas as pd
        from trading.production_prerequisites import ExactExchangeCalendarProvider

        provider = ExactExchangeCalendarProvider()
        calendar = xc.get_calendar("XNYS")
        sessions = calendar.sessions_in_range(
            pd.Timestamp(now.date()) - pd.Timedelta(days=14),
            pd.Timestamp(now.date()),
        )
        for session in reversed(sessions):
            candidate = session.date()
            try:
                provider.completed_session("US", candidate, now=now)
            except Exception:
                continue
            return candidate
    except (ImportError, KeyError, TypeError, ValueError):
        pass
    raise CandidateRuntimeError(US_COMPLETED_SESSION_REQUIRED)


def _validate_us_qfq_as_of(as_of_date: date, now: datetime) -> dict[str, Any]:
    """Guard yfinance auto-adjusted history to the latest completed XNYS T."""

    try:
        from trading.production_prerequisites import ExactExchangeCalendarProvider

        ExactExchangeCalendarProvider().completed_session("US", as_of_date, now=now)
    except Exception as exc:
        if "COMPLETED_SESSION_REQUIRED" in str(exc):
            raise CandidateRuntimeError(US_COMPLETED_SESSION_REQUIRED) from exc
        raise CandidateRuntimeError(US_HISTORICAL_QFQ_ASOF_UNVERIFIED) from exc
    latest = _latest_completed_us_session(now)
    if as_of_date != latest:
        raise CandidateRuntimeError(US_HISTORICAL_QFQ_ASOF_UNVERIFIED)
    return {
        "status": "SUCCESS",
        "qfq_method": "EXISTING_YFINANCE_AUTO_ADJUSTED_PATH",
        "as_of_mode": "LATEST_COMPLETED_SESSION_ONLY",
        "historical_replay_supported": False,
        "as_of_date": as_of_date.isoformat(),
        "latest_completed_session": latest.isoformat(),
    }


class ProductionCandidateRuntime:
    """Run one market's bounded Candidate screening and deep-history load."""

    SOURCE_CONTRACT = {
        "CN": {
            "seed": "BaoStock HS300 ∪ CSI500 + basic/industry metadata",
            "candidate_short_history": "existing yfinance raw batch",
            "strategy_deep_history": "existing yfinance QFQ path",
            "qfq": "yfinance auto_adjust=True; exact completed session T",
        },
        "US": {
            "seed": "official iShares IWB holdings",
            "candidate_short_history": "existing yfinance raw batch",
            "strategy_deep_history": "existing yfinance QFQ path",
            "qfq": "yfinance auto_adjust=True; latest completed XNYS T only",
        },
    }

    def __init__(
        self,
        *,
        seed_loaders: Mapping[str, SeedLoader] | None = None,
        short_history_loader: HistoryLoader | None = None,
        deep_history_loader: HistoryLoader | None = None,
        session_window_loader: SessionWindowLoader | None = None,
        enforce_us_latest_qfq_asof: bool = True,
    ) -> None:
        self.seed_loaders = {
            "CN": self._load_cn_seeds,
            "US": self._load_us_seeds,
            **{
                str(key).strip().upper(): value
                for key, value in (seed_loaders or {}).items()
            },
        }
        self.short_history_loader = short_history_loader or _default_short_history_loader
        self.deep_history_loader = deep_history_loader or _default_deep_qfq_history_loader
        self.session_window_loader = session_window_loader or _completed_session_window
        self.enforce_us_latest_qfq_asof = bool(enforce_us_latest_qfq_asof)

    @staticmethod
    def _load_cn_seeds(as_of_date: date) -> tuple[Any, ...]:
        return BaoStockCandidateSeedAdapter().load(as_of=as_of_date)

    @staticmethod
    def _load_us_seeds(as_of_date: date) -> tuple[date | None, tuple[Any, ...]]:
        del as_of_date
        return IwbOfficialHoldingsAdapter().load()

    def run(
        self,
        *,
        market: str,
        as_of_date: date,
        completed_session_identity: CompletedSessionIdentity,
        now: datetime | None = None,
        reuse_symbols: Iterable[str] = (),
        paper_active_symbols: Iterable[str] = (),
    ) -> CandidateMarketRuntimeResult:
        normalized_market = str(market).strip().upper()
        if normalized_market not in self.seed_loaders:
            raise ValueError("Candidate market must be CN or US")
        if (
            completed_session_identity.market.upper() != normalized_market
            or completed_session_identity.trade_date != as_of_date
        ):
            raise CandidateRuntimeError("CANDIDATE_SESSION_IDENTITY_MISMATCH")

        run_started = time.perf_counter()
        timings = _new_stage_timings()
        errors: list[str] = []
        qfq_contract = dict(self.SOURCE_CONTRACT[normalized_market])
        paper_symbols = tuple(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in paper_active_symbols
                if str(symbol).strip()
            )
        )
        paper_seeds = tuple(
            _paper_continuation_seed(normalized_market, symbol, ())
            for symbol in paper_symbols
        )

        seed_started = time.perf_counter()
        try:
            source_as_of, seeds = _normalise_seed_payload(
                self.seed_loaders[normalized_market](as_of_date)
            )
            if not seeds:
                raise CandidateRuntimeError("CANDIDATE_SEED_EMPTY")
            if any(
                str(getattr(seed, "market", "")).strip().upper()
                != normalized_market
                for seed in seeds
            ):
                raise CandidateRuntimeError("CANDIDATE_SEED_MARKET_MISMATCH")
            _record_stage(
                timings,
                "seed_metadata",
                started=seed_started,
                api_requests=4 if normalized_market == "CN" else 1,
                symbols=len(seeds),
                rows=len(seeds),
                usable_count=len(seeds),
                source=qfq_contract["seed"],
                source_as_of=source_as_of.isoformat() if source_as_of else None,
            )
        except Exception as exc:
            source_as_of = None
            seeds = ()
            error = f"SEED_METADATA_{type(exc).__name__}:{exc}"
            errors.append(error)
            _record_stage(
                timings,
                "seed_metadata",
                started=seed_started,
                failed_count=1,
                status="FAILED",
                error_code=error,
            )

        symbols = tuple(str(seed.symbol).strip().upper() for seed in seeds)
        paper_seeds = tuple(
            _paper_continuation_seed(normalized_market, symbol, seeds)
            for symbol in paper_symbols
        )
        short_started = time.perf_counter()
        try:
            short_sessions = self.session_window_loader(
                normalized_market, as_of_date, MIN_HISTORY_BARS
            )
            short_result = _normalise_history_result(
                self.short_history_loader(seeds, short_sessions[0], as_of_date)
            )
            errors.extend(short_result.errors)
            short_histories = short_result.histories
            short_usable = sum(
                len(short_histories.get(symbol, ())) >= MIN_HISTORY_BARS
                for symbol in symbols
            )
            _record_stage(
                timings,
                "candidate_short_history",
                started=short_started,
                api_requests=short_result.api_requests,
                symbols=len(seeds),
                rows=short_result.rows or sum(
                    len(values) for values in short_histories.values()
                ),
                usable_count=short_usable,
                failed_count=len(seeds) - short_usable,
                status="SUCCESS" if not short_result.errors else "PARTIAL_DATA_QUALITY",
                source="yfinance",
                history_bars=MIN_HISTORY_BARS,
                batch_chunk_size=YFINANCE_BATCH_CHUNK,
                batch_threads=YFINANCE_BATCH_THREADS,
            )
        except Exception as exc:
            error = f"CANDIDATE_SHORT_HISTORY_{type(exc).__name__}:{exc}"
            errors.append(error)
            short_histories = {}
            short_usable = 0
            _record_stage(
                timings,
                "candidate_short_history",
                started=short_started,
                symbols=len(seeds),
                failed_count=len(seeds),
                status="FAILED",
                error_code=error,
            )

        selector_started = time.perf_counter()
        try:
            universe = select_candidate_universe(
                seeds,
                short_histories,
                as_of_date,
                top_n_per_sector=TOP_N_PER_SECTOR,
                min_history_bars=MIN_HISTORY_BARS,
            )
            _record_stage(
                timings,
                "candidate_selector",
                started=selector_started,
                symbols=len(seeds),
                rows=sum(len(values) for values in short_histories.values()),
                usable_count=len(universe.included),
                failed_count=len(seeds) - len(universe.included),
                status="SUCCESS",
                included=len(universe.included),
                top_n_per_sector=TOP_N_PER_SECTOR,
            )
        except Exception as exc:
            error = f"CANDIDATE_SELECTOR_{type(exc).__name__}:{exc}"
            errors.append(error)
            universe = CandidateUniverse(as_of_date, TOP_N_PER_SECTOR, ())
            _record_stage(
                timings,
                "candidate_selector",
                started=selector_started,
                symbols=len(seeds),
                failed_count=len(seeds),
                status="FAILED",
                error_code=error,
            )

        seed_by_symbol = {
            str(seed.symbol).strip().upper(): seed for seed in seeds
        }
        reuse = {
            canonical_key(normalized_market, symbol)[1]
            for symbol in reuse_symbols
        }
        candidate_deep_targets = tuple(
            seed_by_symbol[record.symbol.upper()]
            for record in universe.included
            if canonical_key(normalized_market, record.symbol)[1] not in reuse
            and record.symbol.upper() in seed_by_symbol
        )
        deep_target_values: list[Any] = list(candidate_deep_targets)
        deep_target_symbols = {
            str(seed.symbol).strip().upper() for seed in deep_target_values
        }
        deep_target_values.extend(
            seed
            for seed in paper_seeds
            if str(seed.symbol).strip().upper() not in deep_target_symbols
        )
        deep_targets = tuple(deep_target_values)
        deep_started = time.perf_counter()
        deep_histories: dict[str, tuple[Quote, ...]] = {}
        deep_errors: dict[str, tuple[str, ...]] = {}
        qfq_gate: dict[str, Any] | None = None
        if normalized_market == "US" and deep_targets and self.enforce_us_latest_qfq_asof:
            try:
                qfq_gate = _validate_us_qfq_as_of(
                    as_of_date,
                    now or datetime.now().astimezone(),
                )
            except CandidateRuntimeError as exc:
                message = str(exc)
                for seed in deep_targets:
                    deep_errors[str(seed.symbol).upper()] = (message,)
                errors.append(message)
                _record_stage(
                    timings,
                    "deep_history",
                    started=deep_started,
                    symbols=len(deep_targets),
                    failed_count=len(deep_targets),
                    status="BLOCKED",
                    error_code=message,
                    qfq_as_of_gate="FAILED",
                )
            else:
                qfq_contract.update(qfq_gate)
        if deep_targets and not deep_errors:
            try:
                deep_result = _normalise_history_result(
                    self.deep_history_loader(
                        deep_targets,
                        self.session_window_loader(
                            normalized_market, as_of_date, STRATEGY_HISTORY_BARS
                        )[0],
                        as_of_date,
                    )
                )
                deep_histories.update(deep_result.histories)
                errors.extend(deep_result.errors)
                for seed in deep_targets:
                    symbol = str(seed.symbol).strip().upper()
                    if symbol not in deep_histories:
                        deep_errors[symbol] = (
                            "DEEP_HISTORY_UNAVAILABLE",
                        )
                    else:
                        quality = _deep_data_status(
                            deep_histories[symbol],
                            as_of_date=as_of_date,
                            expected_market=normalized_market,
                            expected_symbol=symbol,
                            expected_currency=getattr(seed, "currency", None),
                        )
                        if quality != DATA_OK:
                            deep_errors[symbol] = (
                                f"DEEP_HISTORY_{quality}",
                            )
                deep_status = (
                    "SUCCESS"
                    if not deep_result.errors and not deep_errors
                    else "PARTIAL_DATA_QUALITY"
                )
                _record_stage(
                    timings,
                    "deep_history",
                    started=deep_started,
                    api_requests=deep_result.api_requests,
                    symbols=len(deep_targets),
                    rows=deep_result.rows or sum(
                        len(values) for values in deep_histories.values()
                    ),
                    usable_count=sum(
                        _deep_data_status(
                            deep_histories.get(str(seed.symbol).upper(), ()),
                            as_of_date=as_of_date,
                            expected_market=normalized_market,
                            expected_symbol=str(seed.symbol),
                            expected_currency=getattr(seed, "currency", None),
                        )
                        == DATA_OK
                        for seed in deep_targets
                    ),
                    failed_count=len(deep_errors),
                    status=deep_status,
                    source="yfinance",
                    requested_bars=STRATEGY_HISTORY_BARS,
                    minimum_bars=MIN_HISTORY_BARS,
                    worker_count=YFINANCE_DEEP_HISTORY_WORKERS,
                    qfq_as_of_gate="SUCCESS" if normalized_market != "US" else "SUCCESS",
                )
            except Exception as exc:
                error = f"DEEP_HISTORY_{type(exc).__name__}:{exc}"
                errors.append(error)
                for seed in deep_targets:
                    deep_errors[str(seed.symbol).upper()] = (error,)
                _record_stage(
                    timings,
                    "deep_history",
                    started=deep_started,
                    symbols=len(deep_targets),
                    failed_count=len(deep_targets),
                    status="FAILED",
                    error_code=error,
                )
        elif not deep_targets and timings["deep_history"]["status"] == "NOT_RUN":
            _record_stage(
                timings,
                "deep_history",
                started=deep_started,
                symbols=0,
                usable_count=0,
                failed_count=0,
                status="NOT_REQUIRED",
                source="existing formal input reused",
            )

        deep_ready = sum(
            _deep_data_status(
                deep_histories.get(symbol, ()),
                as_of_date=as_of_date,
                expected_market=normalized_market,
                expected_symbol=symbol,
                expected_currency=_seed_currency(seeds, symbol),
            )
            == DATA_OK
            for symbol in (record.symbol for record in universe.included)
        )
        if not errors:
            status = "SUCCESS"
        elif universe.included:
            status = "PARTIAL_DATA_QUALITY"
        else:
            status = "FAILED"
        timings["total"] = {
            "elapsed_seconds": round(time.perf_counter() - run_started, 3),
            "api_requests": sum(
                int(values.get("api_requests", 0) or 0)
                for name, values in timings.items()
                if name != "total"
            ),
            "symbols": sum(
                int(values.get("symbols", 0) or 0)
                for name, values in timings.items()
                if name != "total"
            ),
            "rows": sum(
                int(values.get("rows", 0) or 0)
                for name, values in timings.items()
                if name != "total"
            ),
            "usable_count": deep_ready,
            "failed_count": len(deep_errors),
            "status": status,
        }
        return CandidateMarketRuntimeResult(
            normalized_market,
            as_of_date,
            source_as_of,
            tuple(seeds),
            universe,
            deep_histories,
            deep_errors,
            timings,
            tuple(dict.fromkeys(errors)),
            status,
            qfq_contract,
            tuple(str(seed.symbol).strip().upper() for seed in deep_targets),
            paper_symbols,
            paper_seeds,
        )


__all__ = [
    "CandidateMarketRuntimeResult",
    "CandidateRuntimeError",
    "HistoryLoadResult",
    "PRODUCTION_CANDIDATE_ACCOUNT_ROUTING_REQUIRED",
    "ProductionCandidateRuntime",
    "STRATEGY_HISTORY_BARS",
    "US_COMPLETED_SESSION_REQUIRED",
    "US_HISTORICAL_QFQ_ASOF_UNVERIFIED",
    "YFINANCE_BATCH_CHUNK",
    "YFINANCE_BATCH_THREADS",
    "YFINANCE_DEEP_HISTORY_WORKERS",
    "canonical_key",
]

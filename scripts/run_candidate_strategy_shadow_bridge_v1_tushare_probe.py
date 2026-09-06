"""Read-only bulk runtime and Candidate selector probe.

The runner never uses the old per-symbol history path. It first verifies the
multi-symbol ``ts_code`` contract with 20/50/80 symbols and, if that shape is
not usable, verifies the date-major ``trade_date`` contract. Only a verified
bulk shape may run the CN Candidate selector.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import replace
import json
from io import StringIO
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import Quote  # noqa: E402
from trading.candidate_universe import (  # noqa: E402
    AffordabilityTier,
    TOP_N_PER_SECTOR,
    select_candidate_universe,
)
from trading.candidate_universe_sources import BaoStockCandidateSeedAdapter  # noqa: E402
from trading.candidate_universe_sources import IwbOfficialHoldingsAdapter  # noqa: E402
from trading.daily_decision_chain import (  # noqa: E402
    DATA_BAD,
    DATA_OK,
    CompletedSessionIdentity,
    DailyDecisionChain,
    DailySymbolInput,
    InMemoryDecisionStateStore,
    PRODUCTION,
    STRATEGY_PROPOSAL,
)
from trading.tushare_gateway import (  # noqa: E402
    TushareGateway,
    TushareGatewayError,
    parse_tushare_daily_rows,
    tushare_result_records,
)


DEFAULT_AS_OF = date(2026, 9, 4)
HISTORY_BARS = 60
STRATEGY_HISTORY_BARS = 1000
MULTI_SYMBOL_PROBE_SIZES = (20, 50, 80)
FIXED_MULTI_SYMBOL_CHUNK = 80
STRATEGY_MULTI_SYMBOL_CHUNK = 5
YFINANCE_BATCH_CHUNK = 80
RUNTIME_BUDGET_SECONDS = 30 * 60
QFQ_VALIDATION_SYMBOLS = ("000725.SZ", "002156.SZ", "000333.SZ")
FORMAL_CN_QFQ_REFERENCE_SYMBOLS = ("000725.SZ", "002156.SZ", "512400.SH")
QFQ_RELATIVE_TOLERANCE = 0.002
MARKETS = ("CN", "US")
STAGE_NAMES = (
    "seed_metadata",
    "candidate_short_history_network",
    "candidate_selector",
    "deep_raw_history_network",
    "adj_factor_network",
    "qfq_construction",
    "daily_decision_chain",
    "report_construction",
    "total",
)


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
        for name in STAGE_NAMES
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
    elapsed_seconds: float | None = None,
    **extra: Any,
) -> None:
    timings[name] = {
        "elapsed_seconds": round(
            time.perf_counter() - started
            if elapsed_seconds is None
            else elapsed_seconds,
            3,
        ),
        "api_requests": int(api_requests),
        "symbols": int(symbols),
        "rows": int(rows),
        "usable_count": int(usable_count),
        "failed_count": int(failed_count),
        "status": status,
        **extra,
    }


def _stage_from_report(
    timings: dict[str, dict[str, Any]],
    name: str,
    report: Mapping[str, Any],
    *,
    started: float,
    symbols: int | None = None,
    api_requests: int | None = None,
    rows: int | None = None,
    usable_count: int | None = None,
    failed_count: int | None = None,
    status: str | None = None,
    **extra: Any,
) -> None:
    requested = int(report.get("symbols_requested", symbols or 0) or 0)
    usable = int(
        report.get(
            "symbols_usable",
            report.get("symbols_strategy_ready", usable_count or 0),
        )
        or 0
    )
    failed = int(
        failed_count
        if failed_count is not None
        else max(requested - usable, 0)
    )
    _record_stage(
        timings,
        name,
        started=started,
        api_requests=int(
            report.get("api_request_count", 0) or 0
        ) if api_requests is None else api_requests,
        symbols=requested,
        rows=int(report.get("rows", report.get("factor_rows", 0)) or 0)
        if rows is None
        else rows,
        usable_count=usable,
        failed_count=failed,
        status=status or str(report.get("status", "SUCCESS")),
        **extra,
    )


def _completed_market_sessions(
    calendar_name: str, as_of: date, bars: int
) -> tuple[date, ...]:
    try:
        import exchange_calendars as xc
        import pandas as pd

        calendar = xc.get_calendar(calendar_name)
        sessions = calendar.sessions_in_range(
            pd.Timestamp(as_of) - pd.Timedelta(days=max(180, bars * 2 + 30)),
            pd.Timestamp(as_of),
        )
    except Exception:
        raise RuntimeError("TUSHARE_SESSION_WINDOW_SETUP_FAILED") from None
    values = tuple(session.date() for session in sessions)
    if len(values) < bars:
        raise RuntimeError("COMPLETED_SESSION_WINDOW_INSUFFICIENT")
    return values[-bars:]


def _completed_cn_sessions(as_of: date, bars: int = HISTORY_BARS) -> tuple[date, ...]:
    return _completed_market_sessions("XSHG", as_of, bars)


def _completed_us_sessions(as_of: date, bars: int) -> tuple[date, ...]:
    return _completed_market_sessions("XNYS", as_of, bars)


def _normalize_symbols(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(value).strip().upper() for value in values if str(value).strip())
    )


def _safe_error(exc: BaseException) -> str:
    text = str(exc)
    return text if text.startswith("TUSHARE_") else "TUSHARE_BULK_REQUEST_FAILED"


def _bulk_report(
    *,
    mode: str,
    requested: tuple[str, ...],
    histories: Mapping[str, list[Any]],
    raw_rows: int,
    elapsed_seconds: float,
    api_request_count: int,
    errors: list[str],
) -> dict[str, Any]:
    returned = tuple(symbol for symbol in requested if histories.get(symbol))
    usable = tuple(
        symbol for symbol in requested if len(histories.get(symbol, ())) >= HISTORY_BARS
    )
    missing = tuple(symbol for symbol in requested if not histories.get(symbol))
    insufficient = tuple(
        symbol
        for symbol in requested
        if histories.get(symbol) and len(histories.get(symbol, ())) < HISTORY_BARS
    )
    all_dates = [quote.trade_date for quotes in histories.values() for quote in quotes]
    return {
        "mode": mode,
        "api_request_count": api_request_count,
        "symbols_requested": len(requested),
        "symbols_returned": len(returned),
        "symbols_usable": len(usable),
        "rows": raw_rows,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "missing_symbols": list(missing),
        "insufficient_history_symbols": list(insufficient),
        "latest_trade_date": max(all_dates).isoformat() if all_dates else None,
        "errors": errors,
        # A returned symbol with fewer than 60 bars is a Candidate history
        # quality result, not a bulk-contract failure. The selector must
        # classify it as HISTORY_INSUFFICIENT instead of aborting the run.
        "status": "SUCCESS" if not errors and returned else "FAILED_OR_INCOMPLETE",
    }


def _run_multi_symbol_probe(
    gateway: TushareGateway,
    symbols: Iterable[str],
    *,
    start_date: date,
    end_date: date,
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    requested = _normalize_symbols(symbols)
    started = time.perf_counter()
    errors: list[str] = []
    raw_rows = 0
    histories: dict[str, list[Any]] = {symbol: [] for symbol in requested}
    try:
        result = gateway.daily_multi_symbol(
            requested, start_date=start_date, end_date=end_date
        )
        records = tushare_result_records(result)
        raw_rows = len(records)
        histories = parse_tushare_daily_rows(
            records,
            requested,
            start_date=start_date,
            end_date=end_date,
        )
    except TushareGatewayError as exc:
        errors.append(_safe_error(exc))
    except Exception as exc:
        errors.append(_safe_error(exc))
    return (
        _bulk_report(
            mode="MULTI_SYMBOL_DAILY_BATCH",
            requested=requested,
            histories=histories,
            raw_rows=raw_rows,
            elapsed_seconds=time.perf_counter() - started,
            api_request_count=1,
            errors=errors,
        ),
        histories,
    )


def _run_date_major_batch(
    gateway: TushareGateway,
    symbols: Iterable[str],
    sessions: tuple[date, ...],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    requested = _normalize_symbols(symbols)
    started = time.perf_counter()
    histories: dict[str, list[Any]] = {symbol: [] for symbol in requested}
    raw_rows = 0
    errors: list[str] = []
    for session in sessions:
        try:
            result = gateway.daily_trade_date(session)
            records = tushare_result_records(result)
            raw_rows += len(records)
            day_histories = parse_tushare_daily_rows(
                records,
                requested,
                start_date=session,
                end_date=session,
            )
            for symbol, quotes in day_histories.items():
                histories[symbol].extend(quotes)
        except TushareGatewayError as exc:
            errors.append(f"{session.isoformat()}:{_safe_error(exc)}")
        except Exception as exc:
            errors.append(f"{session.isoformat()}:{_safe_error(exc)}")
    for symbol in histories:
        histories[symbol].sort(key=lambda quote: quote.trade_date)
    return (
        _bulk_report(
            mode="DATE_MAJOR_DAILY_BATCH",
            requested=requested,
            histories=histories,
            raw_rows=raw_rows,
            elapsed_seconds=time.perf_counter() - started,
            api_request_count=len(sessions),
            errors=errors,
        ),
        histories,
    )


def _run_fixed_multi_symbol_history(
    gateway: TushareGateway,
    symbols: tuple[str, ...],
    *,
    start_date: date,
    end_date: date,
    first_chunk_histories: Mapping[str, list[Any]],
    first_chunk_elapsed_seconds: float,
) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    histories: dict[str, list[Any]] = {
        symbol: list(first_chunk_histories.get(symbol, ()))
        for symbol in symbols[:FIXED_MULTI_SYMBOL_CHUNK]
    }
    requests = 1
    rows = sum(len(values) for values in histories.values())
    errors: list[str] = []
    started = time.perf_counter()
    for offset in range(FIXED_MULTI_SYMBOL_CHUNK, len(symbols), FIXED_MULTI_SYMBOL_CHUNK):
        chunk = symbols[offset : offset + FIXED_MULTI_SYMBOL_CHUNK]
        try:
            result = gateway.daily_multi_symbol(
                chunk, start_date=start_date, end_date=end_date
            )
            records = tushare_result_records(result)
            rows += len(records)
            parsed = parse_tushare_daily_rows(
                records, chunk, start_date=start_date, end_date=end_date
            )
            histories.update(parsed)
        except TushareGatewayError as exc:
            errors.append(_safe_error(exc))
        except Exception as exc:
            errors.append(_safe_error(exc))
        requests += 1
    report = _bulk_report(
        mode="MULTI_SYMBOL_DAILY_BATCH_FIXED_CHUNK_80",
        requested=symbols,
        histories=histories,
        raw_rows=rows,
        elapsed_seconds=time.perf_counter() - started + first_chunk_elapsed_seconds,
        api_request_count=requests,
        errors=errors,
    )
    return histories, report


def _strategy_history_report(
    *,
    mode: str,
    requested: tuple[str, ...],
    histories: Mapping[str, list[Any]],
    raw_rows: int,
    elapsed_seconds: float,
    api_request_count: int,
    errors: list[str],
    requested_bars: int,
    minimum_bars: int,
    as_of: date,
) -> dict[str, Any]:
    actual_bars = {
        symbol: len(histories.get(symbol, ())) for symbol in requested
    }
    future_symbols: list[str] = []
    duplicate_symbols: list[str] = []
    stale_symbols: list[str] = []
    insufficient_symbols: list[str] = []
    for symbol in requested:
        history = tuple(histories.get(symbol, ()))
        dates = [quote.trade_date for quote in history]
        if any(day > as_of for day in dates):
            future_symbols.append(symbol)
        if len(set(dates)) != len(dates):
            duplicate_symbols.append(symbol)
        if not dates or max(dates) != as_of:
            stale_symbols.append(symbol)
        if len(history) < minimum_bars:
            insufficient_symbols.append(symbol)

    invalid = sorted(
        set(future_symbols)
        | set(duplicate_symbols)
        | set(stale_symbols)
        | set(insufficient_symbols)
    )
    valid = [symbol for symbol in requested if symbol not in invalid]
    shorter_than_requested = sorted(
        symbol
        for symbol in valid
        if actual_bars[symbol] < requested_bars
    )
    distribution: dict[str, int] = {}
    for count in actual_bars.values():
        key = str(count)
        distribution[key] = distribution.get(key, 0) + 1
    return {
        "mode": mode,
        "api_request_count": api_request_count,
        "symbols_requested": len(requested),
        "symbols_strategy_ready": len(valid),
        "symbols_returned": sum(bool(histories.get(symbol)) for symbol in requested),
        "rows": raw_rows,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "requested_bars": requested_bars,
        "minimum_valid_bars": minimum_bars,
        "actual_bars_by_symbol": actual_bars,
        "bars_distribution": dict(sorted(distribution.items(), key=lambda item: int(item[0]))),
        "shorter_than_requested_symbols": shorter_than_requested,
        "future_bar_symbols": future_symbols,
        "duplicate_date_symbols": duplicate_symbols,
        "last_bar_not_exact_as_of_symbols": stale_symbols,
        "insufficient_history_symbols": insufficient_symbols,
        "invalid_symbols": invalid,
        "errors": errors,
        "status": "SUCCESS" if not errors and not invalid else "FAILED_OR_INCOMPLETE",
    }


def _run_tushare_strategy_history(
    gateway: TushareGateway,
    symbols: tuple[str, ...],
    *,
    start_date: date,
    end_date: date,
    deadline: float | None = None,
) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    """Fetch included CN candidates only, with the fixed deep-history chunk."""

    histories: dict[str, list[Any]] = {symbol: [] for symbol in symbols}
    errors: list[str] = []
    raw_rows = 0
    requests = 0
    started = time.perf_counter()
    for offset in range(0, len(symbols), STRATEGY_MULTI_SYMBOL_CHUNK):
        if deadline is not None and time.perf_counter() >= deadline:
            errors.append("RUNTIME_BUDGET_EXCEEDED")
            break
        chunk = symbols[offset : offset + STRATEGY_MULTI_SYMBOL_CHUNK]
        chunk_error: str | None = None
        for _attempt in range(2):
            try:
                result = gateway.daily_multi_symbol(
                    chunk, start_date=start_date, end_date=end_date
                )
                records = tushare_result_records(result)
                raw_rows += len(records)
                histories.update(
                    parse_tushare_daily_rows(
                        records, chunk, start_date=start_date, end_date=end_date
                    )
                )
                chunk_error = None
                requests += 1
                break
            except TushareGatewayError as exc:
                chunk_error = _safe_error(exc)
                requests += 1
            except Exception as exc:
                chunk_error = _safe_error(exc)
                requests += 1
        if chunk_error is not None:
            errors.append(chunk_error)
        if deadline is not None and time.perf_counter() >= deadline:
            errors.append("RUNTIME_BUDGET_EXCEEDED")
            break
    for symbol in histories:
        histories[symbol] = sorted(histories[symbol], key=lambda quote: quote.trade_date)
    return histories, _strategy_history_report(
        mode="MULTI_SYMBOL_DAILY_STRATEGY_HISTORY_FIXED_CHUNK_5",
        requested=symbols,
        histories=histories,
        raw_rows=raw_rows,
        elapsed_seconds=time.perf_counter() - started,
        api_request_count=requests,
        errors=errors,
        requested_bars=STRATEGY_HISTORY_BARS,
        minimum_bars=HISTORY_BARS,
        as_of=end_date,
    )


def _candidate_summary(
    seeds: tuple[Any, ...], histories: Mapping[str, list[Any]], as_of: date
) -> tuple[dict[str, Any], Any]:
    universe = select_candidate_universe(
        seeds,
        histories,
        as_of,
        top_n_per_sector=TOP_N_PER_SECTOR,
        min_history_bars=HISTORY_BARS,
    )
    reason_counts: dict[str, int] = {}
    for record in universe.records:
        reason = record.exclusion_reason or "INCLUDED"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    preferred = sum(
        record.affordability_tier is AffordabilityTier.CN_PREFERRED
        for record in universe.records
    )
    extended = sum(
        record.affordability_tier is AffordabilityTier.CN_EXTENDED_LOWER_PRIORITY
        for record in universe.records
    )
    included_per_sector: dict[str, int] = {}
    for record in universe.included:
        sector = str(record.sector or "")
        included_per_sector[sector] = included_per_sector.get(sector, 0) + 1
    usable = sum(len(histories.get(seed.symbol, ())) >= HISTORY_BARS for seed in seeds)
    summary = {
        "market": seeds[0].market if seeds else None,
        "seed_count": len(seeds),
        "seed": len(seeds),
        "history_usable": usable,
        "usable": usable,
        "affordability_preferred": preferred,
        "affordability_extended": extended,
        "affordability_excluded": reason_counts.get("CN_MINIMUM_NOTIONAL_OVER_20000", 0),
        "unsupported_board_excluded": reason_counts.get("UNSUPPORTED_BOARD_RULE", 0),
        "history_data_quality_excluded": sum(
            count
            for reason, count in reason_counts.items()
            if reason.startswith(("HISTORY_", "METADATA_"))
        ),
        "sector_count": len({seed.sector for seed in seeds if seed.sector}),
        "top_n_per_sector_excluded": reason_counts.get("SECTOR_TOP_N_EXCEEDED", 0),
        "final_included_count": len(universe.included),
        "included": len(universe.included),
        "included_per_sector": dict(sorted(included_per_sector.items())),
        "exclusion_reason_counts": dict(sorted(reason_counts.items())),
        "excluded_reasons": dict(sorted(
            (reason, count)
            for reason, count in reason_counts.items()
            if reason != "INCLUDED"
        )),
        "top_n_per_sector": TOP_N_PER_SECTOR,
        "strategy_engine_started": False,
    }
    return summary, universe


def _factor_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _factor_map(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[date, float]]:
    output: dict[str, dict[date, float]] = {}
    for row in records:
        symbol = str(row.get("ts_code") or "").strip().upper()
        trade_date = _factor_date(row.get("trade_date"))
        try:
            factor = float(row.get("adj_factor"))
        except (TypeError, ValueError):
            continue
        if symbol and trade_date is not None and factor > 0:
            output.setdefault(symbol, {})[trade_date] = factor
    return output


def _qfq_history_from_factors(
    raw_history: Iterable[Any],
    factors: Mapping[date, float],
    *,
    anchor_date: date,
) -> list[Any]:
    anchor_factor = factors.get(anchor_date)
    if anchor_factor is None:
        raise ValueError("TUSHARE_QFQ_EXACT_AS_OF_FACTOR_REQUIRED")
    output = []
    for quote in raw_history:
        factor = factors.get(quote.trade_date)
        if factor is None:
            raise ValueError("TUSHARE_QFQ_FACTOR_DATE_COVERAGE_REQUIRED")
        ratio = factor / anchor_factor
        output.append(
            replace(
                quote,
                source="TushareDailyAdjFactorQFQ",
                open=quote.open * ratio,
                high=quote.high * ratio,
                low=quote.low * ratio,
                close=quote.close * ratio,
                preclose=quote.preclose * ratio if quote.preclose is not None else None,
            )
        )
    return sorted(output, key=lambda quote: quote.trade_date)


def _relative_difference(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1e-12)


def _qfq_comparison(
    adjusted: Iterable[Any],
    existing: Iterable[Any],
    factors: Mapping[date, float],
) -> dict[str, Any]:
    left = {quote.trade_date: quote for quote in adjusted}
    right = {quote.trade_date: quote for quote in existing}
    common = sorted(set(left) & set(right))
    fields = ("open", "high", "low", "close")
    diffs = [
        _relative_difference(getattr(left[day], field), getattr(right[day], field))
        for day in common
        for field in fields
    ]
    boundaries = [
        day
        for previous, (day, value) in zip(sorted(factors)[:-1], sorted(factors.items())[1:])
        if factors[previous] != value
    ]
    change_examples = []
    for previous, (day, value) in zip(
        sorted(factors)[:-1], sorted(factors.items())[1:]
    ):
        before = factors[previous]
        if before == value:
            continue
        change_examples.append(
            {
                "before_date": previous.isoformat(),
                "after_date": day.isoformat(),
                "before_factor": before,
                "after_factor": value,
                "factor_direction": "UP" if value > before else "DOWN",
                "qfq_pre_change_ratio": before / factors.get(max(factors), before),
            }
        )
    boundary_days = [day.isoformat() for day in boundaries]
    return {
        "dates_tushare": len(left),
        "dates_existing_qfq": len(right),
        "dates_common": len(common),
        "dates_match": set(left) == set(right),
        "rows_compared": len(common),
        "max_relative_difference": round(max(diffs, default=0.0), 8),
        "mismatch_count": sum(value > QFQ_RELATIVE_TOLERANCE for value in diffs),
        "tolerance_relative": QFQ_RELATIVE_TOLERANCE,
        "corporate_action_boundary_dates": boundary_days,
        "corporate_action_boundary_checked": all(day in common for day in boundaries),
        "factor_change_count": len(change_examples),
        "factor_change_examples": change_examples[:5],
    }


def _watch_for_baostock(symbol: str) -> dict[str, str]:
    code, suffix = symbol.split(".", 1)
    return {
        "统一代码": symbol,
        "名称": symbol,
        "市场": "CN",
        "币种": "CNY",
        "BaoStock代码": f"{suffix.lower()}.{code}",
    }


def _validate_qfq_sample(
    gateway: TushareGateway,
    raw_histories: Mapping[str, list[Any]],
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    api_requests = 0
    network_rows = 0
    try:
        api_requests += 1
        gateway.pro_bar_qfq(QFQ_VALIDATION_SYMBOLS[0], start_date=start_date, end_date=end_date)
        pro_bar_status = {"status": "SUCCESS"}
    except TushareGatewayError as exc:
        pro_bar_status = {"status": "REJECTED", "error_code": _safe_error(exc)}

    factor_result: dict[str, Any] = {
        "status": "FAILED",
        "symbols_requested": len(QFQ_VALIDATION_SYMBOLS),
    }
    comparisons: list[dict[str, Any]] = []
    try:
        api_requests += 1
        raw_result = gateway.daily_multi_symbol(
            QFQ_VALIDATION_SYMBOLS,
            start_date=start_date,
            end_date=end_date,
        )
        raw_records = tushare_result_records(raw_result)
        network_rows += len(raw_records)
        validation_raw_histories = parse_tushare_daily_rows(
            raw_records,
            QFQ_VALIDATION_SYMBOLS,
            start_date=start_date,
            end_date=end_date,
        )
        api_requests += 1
        result = gateway.adj_factor_multi_symbol(
            QFQ_VALIDATION_SYMBOLS,
            start_date=start_date,
            end_date=end_date,
        )
        records = tushare_result_records(result)
        factors = _factor_map(records)
        factor_result.update(
            {
                "status": "SUCCESS",
                "api_request_count": 1,
                "rows": len(records),
                "symbols_returned": len(factors),
                "latest_trade_date": max(
                    (day for values in factors.values() for day in values),
                    default=None,
                ).isoformat()
                if factors
                else None,
            }
        )
        from providers import fetch_baostock

        for symbol in QFQ_VALIDATION_SYMBOLS:
            try:
                raw_history = validation_raw_histories.get(symbol, [])
                factor_history = factors.get(symbol, {})
                if not raw_history or not factor_history:
                    raise ValueError("TUSHARE_QFQ_SAMPLE_SYMBOL_DATA_REQUIRED")
                adjusted = _qfq_history_from_factors(
                    raw_history,
                    factor_history,
                    anchor_date=end_date,
                )
                existing = None
                last_error: BaseException | None = None
                for _attempt in range(2):
                    try:
                        api_requests += 1
                        with redirect_stdout(StringIO()):
                            existing = fetch_baostock(
                                _watch_for_baostock(symbol), "qfq", start_date, end_date
                            )
                        break
                    except Exception as exc:
                        last_error = exc
                if existing is None:
                    raise last_error or RuntimeError("BAOSTOCK_QFQ_EMPTY")
                comparison = _qfq_comparison(adjusted, existing, factor_history)
                comparison.update({"symbol": symbol, "status": "SUCCESS"})
                if (
                    not comparison["dates_match"]
                    or comparison["mismatch_count"]
                    or not comparison["corporate_action_boundary_checked"]
                ):
                    comparison["status"] = "FAILED"
                comparisons.append(comparison)
            except (KeyError, ValueError, TushareGatewayError) as exc:
                comparisons.append(
                    {
                        "symbol": symbol,
                        "status": "FAILED",
                        "error_code": f"QFQ_COMPARISON_FAILED_{type(exc).__name__}",
                    }
                )
            except Exception as exc:
                comparisons.append(
                    {
                        "symbol": symbol,
                        "status": "FAILED",
                        "error_code": f"QFQ_COMPARISON_FAILED_{type(exc).__name__}",
                    }
                )
    except TushareGatewayError:
        factor_result["error_code"] = "TUSHARE_QFQ_FACTOR_VALIDATION_FAILED"

    return {
        "selected_method": "B_DAILY_PLUS_ADJ_FACTOR",
        "pro_bar_option_a": pro_bar_status,
        "formal_cn_qfq_reference_symbols": list(FORMAL_CN_QFQ_REFERENCE_SYMBOLS),
        "formal_reference_note": "512400.SH is an ETF and returned no stock daily/adj_factor rows from this gateway; validation uses three CN equities with the existing BaoStock qfq path.",
        "factor_batch": factor_result,
        "api_request_count": api_requests,
        "rows": network_rows + int(factor_result.get("rows", 0) or 0),
        "comparisons": comparisons,
        "status": "SUCCESS"
        if factor_result["status"] == "SUCCESS"
        and len(comparisons) == len(QFQ_VALIDATION_SYMBOLS)
        and all(item["status"] == "SUCCESS" for item in comparisons)
        else "FAILED",
    }


def _run_qfq_bulk(
    gateway: TushareGateway,
    included_symbols: tuple[str, ...],
    raw_histories: Mapping[str, list[Any]],
    *,
    start_date: date,
    end_date: date,
    deadline: float | None = None,
) -> tuple[dict[str, list[Any]], dict[str, Any], dict[str, dict[date, float]]]:
    started = time.perf_counter()
    factor_by_symbol: dict[str, dict[date, float]] = {}
    rows = 0
    errors: list[str] = []
    requests = 0
    for offset in range(0, len(included_symbols), STRATEGY_MULTI_SYMBOL_CHUNK):
        if deadline is not None and time.perf_counter() >= deadline:
            errors.append("RUNTIME_BUDGET_EXCEEDED")
            break
        chunk = included_symbols[offset : offset + STRATEGY_MULTI_SYMBOL_CHUNK]
        chunk_error: str | None = None
        for _attempt in range(2):
            try:
                result = gateway.adj_factor_multi_symbol(
                    chunk, start_date=start_date, end_date=end_date
                )
                records = tushare_result_records(result)
                rows += len(records)
                factor_by_symbol.update(_factor_map(records))
                chunk_error = None
                requests += 1
                break
            except TushareGatewayError as exc:
                chunk_error = _safe_error(exc)
                requests += 1
            except Exception as exc:
                chunk_error = _safe_error(exc)
                requests += 1
        if chunk_error is not None:
            errors.append(chunk_error)
        if deadline is not None and time.perf_counter() >= deadline:
            errors.append("RUNTIME_BUDGET_EXCEEDED")
            break

    network_elapsed = time.perf_counter() - started
    construction_started = time.perf_counter()
    qfq_histories: dict[str, list[Any]] = {}
    invalid: list[str] = []
    for symbol in included_symbols:
        try:
            qfq_histories[symbol] = _qfq_history_from_factors(
                raw_histories[symbol],
                factor_by_symbol.get(symbol, {}),
                anchor_date=end_date,
            )
        except (KeyError, ValueError):
            invalid.append(symbol)
    construction_elapsed = time.perf_counter() - construction_started
    report = {
        "method": "B_DAILY_PLUS_ADJ_FACTOR",
        "api_request_count": requests,
        "symbols_requested": len(included_symbols),
        "symbols_with_qfq": len(qfq_histories),
        "factor_rows": rows,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "factor_network_elapsed_seconds": round(network_elapsed, 3),
        "construction_elapsed_seconds": round(construction_elapsed, 3),
        "chunk_size": STRATEGY_MULTI_SYMBOL_CHUNK,
        "missing_or_invalid_symbols": invalid,
        "errors": errors,
        "exact_as_of_anchor": not invalid,
        "status": "SUCCESS" if not errors and not invalid else "FAILED",
    }
    return qfq_histories, report, factor_by_symbol


def _validate_factor_change_sample(
    raw_histories: Mapping[str, list[Any]],
    factor_by_symbol: Mapping[str, Mapping[date, float]],
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Compare one real factor-change series with the formal BaoStock qfq path."""

    api_requests = 0

    candidates = sorted(
        symbol
        for symbol, factors in factor_by_symbol.items()
        if len(set(factors.values())) > 1 and raw_histories.get(symbol)
    )
    if not candidates:
        return {
            "status": "NO_FACTOR_CHANGE_SAMPLE",
            "symbols_scanned": len(factor_by_symbol),
            "sample_symbol": None,
            "comparison": None,
            "api_request_count": 0,
            "note": "No included CN equity had an observed adj_factor change in the 1000-bar range.",
        }

    symbol = candidates[0]
    factors = factor_by_symbol[symbol]
    changes = [
        (previous, day, factors[previous], factors[day])
        for previous, day in zip(sorted(factors)[:-1], sorted(factors)[1:])
        if factors[previous] != factors[day]
    ]
    from providers import fetch_baostock

    try:
        existing = None
        last_error: BaseException | None = None
        for _attempt in range(2):
            try:
                api_requests += 1
                with redirect_stdout(StringIO()):
                    existing = fetch_baostock(
                        _watch_for_baostock(symbol), "qfq", start_date, end_date
                    )
                break
            except Exception as exc:
                last_error = exc
        if existing is None:
            raise last_error or RuntimeError("BAOSTOCK_QFQ_EMPTY")
        adjusted = _qfq_history_from_factors(
            raw_histories[symbol], factors, anchor_date=end_date
        )
        comparison = _qfq_comparison(adjusted, existing, factors)
        comparison.update(
            {
                "symbol": symbol,
                "status": "SUCCESS",
                "factor_change_dates": [item[1].isoformat() for item in changes],
                "factor_change_directions": [
                    "UP" if item[3] > item[2] else "DOWN" for item in changes
                ],
                "factor_change_boundary_in_common": all(
                    item[1] in {quote.trade_date for quote in existing}
                    for item in changes
                ),
            }
        )
        if (
            not comparison["dates_match"]
            or comparison["mismatch_count"]
            or not comparison["corporate_action_boundary_checked"]
            or not comparison["factor_change_boundary_in_common"]
        ):
            comparison["status"] = "FAILED"
        return {
            "status": comparison["status"],
            "symbols_scanned": len(factor_by_symbol),
            "sample_symbol": symbol,
            "api_request_count": api_requests,
            "comparison": comparison,
        }
    except Exception as exc:
        return {
            "status": "FAILED",
            "symbols_scanned": len(factor_by_symbol),
            "sample_symbol": symbol,
            "api_request_count": api_requests,
            "comparison": {
                "symbol": symbol,
                "status": "FAILED",
                "error_code": f"QFQ_FACTOR_CHANGE_COMPARISON_FAILED_{type(exc).__name__}",
            },
        }


def _download_yfinance_symbol_frame(frame: Any, symbol: str) -> Any:
    """Select one symbol from yfinance's two supported MultiIndex layouts."""

    import pandas as pd

    if not isinstance(getattr(frame, "columns", None), pd.MultiIndex):
        return frame
    normalized = str(symbol).upper().replace(".", "-").replace("/", "-")
    for level in range(frame.columns.nlevels):
        labels = list(dict.fromkeys(frame.columns.get_level_values(level)))
        matching = next(
            (
                label
                for label in labels
                if str(label).strip().upper().replace(".", "-").replace("/", "-")
                == normalized
            ),
            None,
        )
        if matching is None:
            continue
        selected = frame.xs(matching, axis=1, level=level, drop_level=True)
        if hasattr(selected, "columns"):
            names = {str(name).strip().lower() for name in selected.columns}
            if {"open", "high", "low", "close"}.issubset(names):
                return selected
    return frame.iloc[:, 0:0]


def _yfinance_batch_quotes(
    frame: Any,
    symbol: str,
    *,
    start_date: date,
    end_date: date,
    auto_adjust: bool,
) -> list[Any]:
    import math

    selected = _download_yfinance_symbol_frame(frame, symbol)
    columns = {str(name).strip().lower(): name for name in selected.columns}
    required = {field: columns.get(field) for field in ("open", "high", "low", "close")}
    if any(value is None for value in required.values()):
        return []
    volume_column = columns.get("volume")
    quotes: list[Any] = []
    previous_close: float | None = None
    for index, row in selected.iterrows():
        try:
            parsed_date = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
            values = {field: float(row[column]) for field, column in required.items()}
            if not all(math.isfinite(value) for value in values.values()):
                continue
            volume = None
            if volume_column is not None and row[volume_column] == row[volume_column]:
                volume = float(row[volume_column])
            if parsed_date < start_date or parsed_date > end_date:
                continue
            quotes.append(
                Quote(
                    symbol=symbol,
                    name=symbol,
                    market="US",
                    trade_date=parsed_date,
                    source=(
                        "yfinance-batch-qfq" if auto_adjust else "yfinance-batch-raw"
                    ),
                    open=values["open"],
                    high=values["high"],
                    low=values["low"],
                    close=values["close"],
                    preclose=previous_close,
                    pct_change=(
                        (values["close"] / previous_close - 1.0) * 100.0
                        if previous_close not in (None, 0)
                        else None
                    ),
                    volume=volume,
                    amount=None,
                    turnover_rate=None,
                    currency="USD",
                )
            )
            previous_close = values["close"]
        except (TypeError, ValueError, OverflowError):
            continue
    return sorted(quotes, key=lambda quote: quote.trade_date)


def _run_yfinance_batch_history(
    symbols: tuple[str, ...],
    *,
    start_date: date,
    end_date: date,
    auto_adjust: bool,
    requested_bars: int,
    stage: str,
    deadline: float | None = None,
) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    """Fetch US history in fixed yfinance batches without per-symbol calls."""

    import yfinance as yf

    histories: dict[str, list[Any]] = {symbol: [] for symbol in symbols}
    errors: list[str] = []
    raw_rows = 0
    requests = 0
    started = time.perf_counter()
    for offset in range(0, len(symbols), YFINANCE_BATCH_CHUNK):
        if deadline is not None and time.perf_counter() >= deadline:
            errors.append(f"{stage}:RUNTIME_BUDGET_EXCEEDED")
            break
        chunk = symbols[offset : offset + YFINANCE_BATCH_CHUNK]
        try:
            frame = yf.download(
                tickers=list(chunk),
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=auto_adjust,
                actions=False,
                repair=False,
                group_by="ticker",
                threads=False,
                progress=False,
            )
            for symbol in chunk:
                quotes = _yfinance_batch_quotes(
                    frame,
                    symbol,
                    start_date=start_date,
                    end_date=end_date,
                    auto_adjust=auto_adjust,
                )
                histories[symbol] = quotes
                raw_rows += len(quotes)
        except Exception as exc:
            errors.append(f"{stage}:{type(exc).__name__}")
        requests += 1
        if deadline is not None and time.perf_counter() >= deadline:
            errors.append(f"{stage}:RUNTIME_BUDGET_EXCEEDED")
            break
    report = _strategy_history_report(
        mode=f"YFINANCE_BATCH_{stage}",
        requested=symbols,
        histories=histories,
        raw_rows=raw_rows,
        elapsed_seconds=time.perf_counter() - started,
        api_request_count=requests,
        errors=errors,
        requested_bars=requested_bars,
        minimum_bars=HISTORY_BARS,
        as_of=end_date,
    )
    # Candidate short history deliberately passes per-symbol quality gaps to
    # the existing selector, matching the CN bulk contract.  A completed
    # yfinance batch with no request-level error is therefore usable even when
    # some symbols will be excluded as HISTORY_INSUFFICIENT/HISTORY_STALE.
    if stage == "CANDIDATE_RAW_HISTORY" and not errors:
        report["status"] = "SUCCESS"
        report["batch_data_quality_exclusions_deferred_to_selector"] = True
    report["batch_chunk_size"] = YFINANCE_BATCH_CHUNK
    report["auto_adjust"] = auto_adjust
    return histories, report


def _run_daily_decision_shadow(
    qfq_histories: Mapping[str, list[Any]],
    as_of: date,
    *,
    market: str,
    requested_symbols: tuple[str, ...],
    history_ready_symbols: tuple[str, ...],
) -> dict[str, Any]:
    inputs = tuple(
        DailySymbolInput(
            symbol=symbol,
            market=market,
            as_of_date=as_of,
            qfq_history=tuple(history),
            data_quality_status=(
                DATA_OK if symbol in history_ready_symbols else DATA_BAD
            ),
            completed_session_identity=CompletedSessionIdentity(
                market=market,
                trade_date=as_of,
                identity=f"{market}_SHADOW_OBSERVED:{as_of.isoformat()}",
                session_dates=(as_of,),
            ),
        )
        for symbol in sorted(requested_symbols)
        for history in (qfq_histories.get(symbol, ()),)
    )
    started = time.perf_counter()
    store = InMemoryDecisionStateStore()
    chain = DailyDecisionChain(store=store)
    report = chain.evaluate(
        inputs,
        mode=PRODUCTION,
        allocation_budget=None,
        approved_event_identities=(),
    )
    final_status_counts: dict[str, int] = {}
    primary_action_counts: dict[str, int] = {}
    setup01_state_counts: dict[str, int] = {}
    setup02_state_counts: dict[str, int] = {}
    wave_scenario_counts: dict[str, int] = {}
    for result in report.results:
        for counts, value in (
            (final_status_counts, result.final_status),
            (primary_action_counts, result.primary_action),
            (setup01_state_counts, result.setup01_state),
            (setup02_state_counts, result.setup02_state),
            (wave_scenario_counts, result.primary_wave_scenario),
        ):
            counts[value] = counts.get(value, 0) + 1

    def symbols_where(predicate: Any) -> list[str]:
        return sorted(result.symbol for result in report.results if predicate(result))

    setup01_watch = symbols_where(lambda result: result.setup01_state == "WATCH")
    setup01_armed = symbols_where(lambda result: result.setup01_state == "ARMED")
    setup02_watch = symbols_where(lambda result: result.setup02_state == "WATCH")
    setup02_armed = symbols_where(lambda result: result.setup02_state == "ARMED")
    proposals = symbols_where(lambda result: result.final_status == STRATEGY_PROPOSAL)
    return {
        "status": "SUCCESS" if len(report.results) == len(inputs) else "FAILED",
        "symbols_requested": len(inputs),
        "evaluated": len(report.results),
        "failed": max(len(inputs) - len(report.results), 0),
        "results": len(report.results),
        "final_status_counts": dict(sorted(final_status_counts.items())),
        "primary_action_counts": dict(sorted(primary_action_counts.items())),
        "setup01_state_counts": dict(sorted(setup01_state_counts.items())),
        "setup02_state_counts": dict(sorted(setup02_state_counts.items())),
        "primary_wave_scenario_counts": dict(sorted(wave_scenario_counts.items())),
        "setup01_watch_symbols": setup01_watch,
        "setup01_armed_symbols": setup01_armed,
        "setup02_watch_symbols": setup02_watch,
        "setup02_armed_symbols": setup02_armed,
        "strategy_proposal_symbols": proposals,
        "explicit_state_symbols": {
            "SETUP_01 WATCH": setup01_watch,
            "SETUP_01 ARMED": setup01_armed,
            "SETUP_02 WATCH": setup02_watch,
            "SETUP_02 ARMED": setup02_armed,
            "STRATEGY_PROPOSAL": proposals,
        },
        "history_ready_symbols": len(history_ready_symbols),
        "history_blocked_symbols": sorted(
            set(requested_symbols) - set(history_ready_symbols)
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "in_memory_state_store": True,
        "persistent_state_write": False,
        "production_state_write": False,
        "sheets_write": False,
        "allocation": False,
        "broker_order": False,
    }


def _new_market_report(market: str, as_of: date) -> dict[str, Any]:
    return {
        "probe": "CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1",
        "market": market,
        "requested_as_of_date": as_of.isoformat(),
        "history_bars_requested": HISTORY_BARS,
        "strategy_history_bars_requested": STRATEGY_HISTORY_BARS,
        "stage_timings": _new_stage_timings(),
        "read_only": True,
        "production_state_write": False,
        "sheets_write": False,
        "allocation": False,
        "broker_order": False,
    }


def _market_error_code(prefix: str, exc: BaseException) -> str:
    if isinstance(exc, TushareGatewayError):
        return str(exc)
    return f"{prefix}_{type(exc).__name__}"


def _finish_market_report(
    report: dict[str, Any],
    run_started: float,
    *,
    status: str,
    marker: str,
    error_code: str | None = None,
) -> dict[str, Any]:
    construction_started = time.perf_counter()
    elapsed_before_finish = time.perf_counter() - run_started
    over_budget = elapsed_before_finish > RUNTIME_BUDGET_SECONDS
    if over_budget:
        status = f"READY_FOR_DECISION_{report['market']}_STRATEGY_RUNTIME"
        marker = status
        error_code = "RUNTIME_BUDGET_EXCEEDED"
        report["runtime_budget_seconds"] = RUNTIME_BUDGET_SECONDS
    report["status"] = status
    report["decision_marker"] = marker
    if error_code:
        report["error_code"] = error_code
    _record_stage(
        report["stage_timings"],
        "report_construction",
        started=construction_started,
        symbols=int(report.get("candidate", {}).get("seed_count", 0) or 0)
        if isinstance(report.get("candidate"), Mapping)
        else 0,
        rows=0,
        usable_count=int(
            report.get("strategy", {})
            .get("decision_chain", {})
            .get("evaluated", 0)
            or 0
        )
        if isinstance(report.get("strategy"), Mapping)
        else 0,
        failed_count=0,
        status="SUCCESS",
    )
    total_elapsed = time.perf_counter() - run_started
    _record_stage(
        report["stage_timings"],
        "total",
        started=run_started,
        elapsed_seconds=total_elapsed,
        api_requests=sum(
            int(item.get("api_requests", 0) or 0)
            for name, item in report["stage_timings"].items()
            if name != "total"
        ),
        symbols=sum(
            int(item.get("symbols", 0) or 0)
            for name, item in report["stage_timings"].items()
            if name != "total"
        ),
        rows=sum(
            int(item.get("rows", 0) or 0)
            for name, item in report["stage_timings"].items()
            if name != "total"
        ),
        usable_count=sum(
            int(item.get("usable_count", 0) or 0)
            for name, item in report["stage_timings"].items()
            if name != "total"
        ),
        failed_count=sum(
            int(item.get("failed_count", 0) or 0)
            for name, item in report["stage_timings"].items()
            if name != "total"
        ),
        status="SUCCESS" if not over_budget else "FAILED",
    )
    strategy = report.get("strategy", {})
    decision = strategy.get("decision_chain", {}) if isinstance(strategy, Mapping) else {}
    report["runtime"] = {
        "total_elapsed_seconds": round(total_elapsed, 3),
        "api_request_count": report["stage_timings"]["total"]["api_requests"],
        "symbols": report["stage_timings"]["total"]["symbols"],
        "rows": report["stage_timings"]["total"]["rows"],
        "symbols_evaluated": int(decision.get("evaluated", 0) or 0),
        "stage_timings": report["stage_timings"],
    }
    report["runtime_acceptance"] = (
        "ACCEPTED"
        if status == "CANDIDATE_SUCCESS" and not over_budget
        else "BLOCKED_RUNTIME_BUDGET"
        if over_budget
        else "NOT_ACCEPTED_MARKET_FAILED"
    )
    return report


def _finish_if_over_budget(
    report: dict[str, Any], run_started: float
) -> dict[str, Any] | None:
    if time.perf_counter() - run_started <= RUNTIME_BUDGET_SECONDS:
        return None
    return _finish_market_report(
        report,
        run_started,
        status=f"READY_FOR_DECISION_{report['market']}_STRATEGY_RUNTIME",
        marker=f"READY_FOR_DECISION_{report['market']}_STRATEGY_RUNTIME",
        error_code="RUNTIME_BUDGET_EXCEEDED",
    )


def _run_cn_market(*, as_of: date) -> dict[str, Any]:
    run_started = time.perf_counter()
    report = _new_market_report("CN", as_of)

    seed_started = time.perf_counter()
    try:
        gateway = TushareGateway()
        gateway.pro
        sessions = _completed_cn_sessions(as_of)
        effective_as_of = sessions[-1]
        start_date = sessions[0]
        with redirect_stdout(StringIO()):
            seeds = tuple(BaoStockCandidateSeedAdapter().load(as_of=effective_as_of))
    except Exception as exc:
        error_code = _market_error_code("CN_SEED_METADATA_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "seed_metadata",
            started=seed_started,
            symbols=0,
            failed_count=1,
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_SEED_METADATA",
            marker="READY_FOR_DECISION_CN_SEED_METADATA",
            error_code=error_code,
        )

    symbols = tuple(seed.symbol for seed in seeds)
    _record_stage(
        report["stage_timings"],
        "seed_metadata",
        started=seed_started,
        api_requests=4,
        symbols=len(seeds),
        rows=len(seeds),
        usable_count=len(seeds),
        status="SUCCESS",
        source="BaoStock_HS300_UNION_CSI500",
        effective_as_of=effective_as_of.isoformat(),
    )
    report.update(
        {
            "as_of_date": effective_as_of.isoformat(),
            "history_start_date": start_date.isoformat(),
            "seed_count": len(seeds),
        }
    )

    candidate_network_started = time.perf_counter()
    try:
        multi_probes: list[dict[str, Any]] = []
        probe_histories: dict[str, list[Any]] = {}
        for size in MULTI_SYMBOL_PROBE_SIZES:
            probe, histories = _run_multi_symbol_probe(
                gateway,
                symbols[:size],
                start_date=start_date,
                end_date=effective_as_of,
            )
            probe["probe_size"] = size
            multi_probes.append(probe)
            if size == FIXED_MULTI_SYMBOL_CHUNK:
                probe_histories = histories
        if multi_probes[-1]["status"] == "SUCCESS":
            bulk_mode = "MULTI_SYMBOL_DAILY_BATCH"
            histories, bulk_report = _run_fixed_multi_symbol_history(
                gateway,
                symbols,
                start_date=start_date,
                end_date=effective_as_of,
                first_chunk_histories=probe_histories,
                first_chunk_elapsed_seconds=multi_probes[-1]["elapsed_seconds"],
            )
        else:
            bulk_mode = "DATE_MAJOR_DAILY_BATCH"
            bulk_report, histories = _run_date_major_batch(gateway, symbols, sessions)
    except Exception as exc:
        error_code = _market_error_code("CN_CANDIDATE_HISTORY_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "candidate_short_history_network",
            started=candidate_network_started,
            symbols=len(seeds),
            failed_count=len(seeds),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_CANDIDATE_SHORT_HISTORY",
            marker="READY_FOR_DECISION_CN_CANDIDATE_SHORT_HISTORY",
            error_code=error_code,
        )

    report.update(
        {
            "multi_symbol_probes": multi_probes,
            "selected_bulk_mode": bulk_mode,
            "candidate_short_history": bulk_report,
        }
    )
    _stage_from_report(
        report["stage_timings"],
        "candidate_short_history_network",
        bulk_report,
        started=candidate_network_started,
        symbols=len(seeds),
        api_requests=sum(item["api_request_count"] for item in multi_probes)
        + int(bulk_report.get("api_request_count", 0) or 0),
        rows=int(bulk_report.get("rows", 0) or 0),
        usable_count=int(bulk_report.get("symbols_usable", 0) or 0),
        failed_count=max(
            len(seeds) - int(bulk_report.get("symbols_usable", 0) or 0), 0
        ),
        status=str(bulk_report.get("status", "FAILED")),
        probe_requests=sum(item["api_request_count"] for item in multi_probes),
    )
    if bulk_report["status"] != "SUCCESS":
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_CANDIDATE_SHORT_HISTORY",
            marker="READY_FOR_DECISION_CN_CANDIDATE_SHORT_HISTORY",
            error_code="CN_CANDIDATE_SHORT_HISTORY_INCOMPLETE",
        )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget

    selector_started = time.perf_counter()
    try:
        candidate_summary, candidate_universe = _candidate_summary(
            seeds, histories, effective_as_of
        )
    except Exception as exc:
        error_code = _market_error_code("CN_CANDIDATE_SELECTOR_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "candidate_selector",
            started=selector_started,
            symbols=len(seeds),
            rows=sum(len(values) for values in histories.values()),
            failed_count=len(seeds),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_CANDIDATE_SELECTOR",
            marker="READY_FOR_DECISION_CN_CANDIDATE_SELECTOR",
            error_code=error_code,
        )
    report["candidate"] = candidate_summary
    selector_usable = int(candidate_summary["history_usable"])
    selector_included = int(candidate_summary["final_included_count"])
    _record_stage(
        report["stage_timings"],
        "candidate_selector",
        started=selector_started,
        symbols=len(seeds),
        rows=sum(len(values) for values in histories.values()),
        usable_count=selector_included,
        failed_count=max(len(seeds) - selector_usable, 0),
        status="SUCCESS",
        included=selector_included,
        excluded=max(len(seeds) - selector_included, 0),
    )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget

    included_symbols = tuple(record.symbol for record in candidate_universe.included)
    if not included_symbols:
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_CANDIDATE_EMPTY",
            marker="READY_FOR_DECISION_CN_CANDIDATE_EMPTY",
            error_code="CN_CANDIDATE_EMPTY",
        )

    deep_started = time.perf_counter()
    try:
        strategy_sessions = _completed_cn_sessions(
            effective_as_of, bars=STRATEGY_HISTORY_BARS
        )
        strategy_histories, strategy_history_report = _run_tushare_strategy_history(
            gateway,
            included_symbols,
            start_date=strategy_sessions[0],
            end_date=effective_as_of,
            deadline=run_started + RUNTIME_BUDGET_SECONDS,
        )
    except Exception as exc:
        error_code = _market_error_code("CN_STRATEGY_HISTORY_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "deep_raw_history_network",
            started=deep_started,
            symbols=len(included_symbols),
            failed_count=len(included_symbols),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_STRATEGY_HISTORY",
            marker="READY_FOR_DECISION_CN_STRATEGY_HISTORY",
            error_code=error_code,
        )
    report.setdefault("strategy", {})["deep_raw_history"] = strategy_history_report
    _stage_from_report(
        report["stage_timings"],
        "deep_raw_history_network",
        strategy_history_report,
        started=deep_started,
        status=str(strategy_history_report.get("status", "FAILED")),
        history_mode="TUSHARE_DAILY_RAW",
    )
    if strategy_history_report["status"] != "SUCCESS":
        marker = (
            "READY_FOR_DECISION_CN_STRATEGY_RUNTIME"
            if "RUNTIME_BUDGET_EXCEEDED" in strategy_history_report.get("errors", [])
            else "READY_FOR_DECISION_CN_STRATEGY_HISTORY"
        )
        return _finish_market_report(
            report,
            run_started,
            status=marker,
            marker=marker,
            error_code=marker,
        )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget

    factor_started = time.perf_counter()
    try:
        qfq_validation = _validate_qfq_sample(
            gateway,
            histories,
            start_date=start_date,
            end_date=effective_as_of,
        )
        qfq_histories, qfq_report, factor_by_symbol = _run_qfq_bulk(
            gateway,
            included_symbols,
            strategy_histories,
            start_date=strategy_sessions[0],
            end_date=effective_as_of,
            deadline=run_started + RUNTIME_BUDGET_SECONDS,
        )
    except Exception as exc:
        error_code = _market_error_code("CN_ADJ_FACTOR_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "adj_factor_network",
            started=factor_started,
            symbols=len(included_symbols),
            failed_count=len(included_symbols),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_ADJ_FACTOR_RUNTIME",
            marker="READY_FOR_DECISION_CN_ADJ_FACTOR_RUNTIME",
            error_code=error_code,
        )
    report.setdefault("strategy", {}).update(
        {
            "qfq_validation": qfq_validation,
            "adj_factor": qfq_report,
        }
    )
    qfq_factor_batch = qfq_validation.get("factor_batch", {})
    qfq_api_requests = int(qfq_report.get("api_request_count", 0) or 0) + int(
        qfq_validation.get("api_request_count", 0) or 0
    )
    _record_stage(
        report["stage_timings"],
        "adj_factor_network",
        started=factor_started,
        elapsed_seconds=(
            time.perf_counter() - factor_started
            - float(qfq_report.get("construction_elapsed_seconds", 0.0) or 0.0)
        ),
        api_requests=qfq_api_requests,
        symbols=len(included_symbols),
        rows=int(qfq_report.get("factor_rows", 0) or 0)
        + int(qfq_factor_batch.get("rows", 0) or 0),
        usable_count=len(qfq_histories),
        failed_count=max(len(included_symbols) - len(qfq_histories), 0),
        status=(
            "SUCCESS"
            if qfq_validation.get("status") == "SUCCESS"
            and qfq_report.get("status") == "SUCCESS"
            else "FAILED"
        ),
        chunk_size=STRATEGY_MULTI_SYMBOL_CHUNK,
    )
    if qfq_validation["status"] != "SUCCESS" or qfq_report["status"] != "SUCCESS":
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_ADJ_FACTOR_RUNTIME",
            marker="READY_FOR_DECISION_CN_ADJ_FACTOR_RUNTIME",
            error_code="CN_ADJ_FACTOR_VALIDATION_FAILED",
        )

    construction_started = time.perf_counter()
    factor_change = _validate_factor_change_sample(
        strategy_histories,
        factor_by_symbol,
        start_date=strategy_sessions[0],
        end_date=effective_as_of,
    )
    report["strategy"]["factor_change_validation"] = factor_change
    _record_stage(
        report["stage_timings"],
        "qfq_construction",
        started=construction_started,
        elapsed_seconds=float(qfq_report.get("construction_elapsed_seconds", 0.0) or 0.0)
        + (time.perf_counter() - construction_started),
        api_requests=int(factor_change.get("api_request_count", 0) or 0),
        symbols=len(included_symbols),
        rows=sum(len(values) for values in qfq_histories.values()),
        usable_count=len(qfq_histories),
        failed_count=max(len(included_symbols) - len(qfq_histories), 0),
        status="SUCCESS" if factor_change.get("status") == "SUCCESS" else "FAILED",
        method="raw_price_times_adj_factor_over_exact_T_factor",
        exact_as_of_anchor=bool(qfq_report.get("exact_as_of_anchor")),
    )
    if factor_change["status"] != "SUCCESS":
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_QFQ_CORPORATE_ACTION_SEMANTICS",
            marker="READY_FOR_DECISION_CN_QFQ_CORPORATE_ACTION_SEMANTICS",
            error_code="CN_FACTOR_CHANGE_VALIDATION_FAILED",
        )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget

    decision_started = time.perf_counter()
    cn_strategy_ready = tuple(
        symbol for symbol in included_symbols if qfq_histories.get(symbol)
    )
    try:
        decision = _run_daily_decision_shadow(
            qfq_histories,
            effective_as_of,
            market="CN",
            requested_symbols=included_symbols,
            history_ready_symbols=cn_strategy_ready,
        )
    except Exception as exc:
        error_code = _market_error_code("CN_DAILY_DECISION_CHAIN_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "daily_decision_chain",
            started=decision_started,
            symbols=len(included_symbols),
            failed_count=len(included_symbols),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_CN_DAILY_DECISION_CHAIN",
            marker="READY_FOR_DECISION_CN_DAILY_DECISION_CHAIN",
            error_code=error_code,
        )
    report["strategy"]["decision_chain"] = decision
    _record_stage(
        report["stage_timings"],
        "daily_decision_chain",
        started=decision_started,
        symbols=len(included_symbols),
        rows=sum(len(values) for values in qfq_histories.values()),
        usable_count=decision["evaluated"],
        failed_count=decision["failed"],
        status=decision["status"],
    )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget
    return _finish_market_report(
        report,
        run_started,
        status="CANDIDATE_SUCCESS",
        marker="CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1_COMPLETE",
    )


def _run_us_market(*, as_of: date) -> dict[str, Any]:
    run_started = time.perf_counter()
    report = _new_market_report("US", as_of)

    seed_started = time.perf_counter()
    try:
        source_as_of, seeds = IwbOfficialHoldingsAdapter().load()
        candidate_sessions = _completed_us_sessions(as_of, HISTORY_BARS)
        effective_as_of = candidate_sessions[-1]
    except Exception as exc:
        error_code = _market_error_code("US_SEED_METADATA_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "seed_metadata",
            started=seed_started,
            symbols=0,
            failed_count=1,
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_US_SEED_METADATA",
            marker="READY_FOR_DECISION_US_SEED_METADATA",
            error_code=error_code,
        )
    _record_stage(
        report["stage_timings"],
        "seed_metadata",
        started=seed_started,
        api_requests=1,
        symbols=len(seeds),
        rows=len(seeds),
        usable_count=len(seeds),
        status="SUCCESS",
        source="iShares_IWB_OFFICIAL_HOLDINGS",
        source_as_of=source_as_of.isoformat() if source_as_of else None,
        effective_as_of=effective_as_of.isoformat(),
    )
    report.update(
        {
            "as_of_date": effective_as_of.isoformat(),
            "history_start_date": candidate_sessions[0].isoformat(),
            "seed_count": len(seeds),
        }
    )

    candidate_network_started = time.perf_counter()
    symbols = tuple(seed.symbol for seed in seeds)
    try:
        candidate_histories, candidate_history_report = _run_yfinance_batch_history(
            symbols,
            start_date=candidate_sessions[0],
            end_date=effective_as_of,
            auto_adjust=False,
            requested_bars=HISTORY_BARS,
            stage="CANDIDATE_RAW_HISTORY",
            deadline=run_started + RUNTIME_BUDGET_SECONDS,
        )
    except Exception as exc:
        error_code = _market_error_code("US_CANDIDATE_HISTORY_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "candidate_short_history_network",
            started=candidate_network_started,
            symbols=len(seeds),
            failed_count=len(seeds),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_US_CANDIDATE_SHORT_HISTORY",
            marker="READY_FOR_DECISION_US_CANDIDATE_SHORT_HISTORY",
            error_code=error_code,
        )
    report["candidate_short_history"] = candidate_history_report
    _stage_from_report(
        report["stage_timings"],
        "candidate_short_history_network",
        candidate_history_report,
        started=candidate_network_started,
        status=str(candidate_history_report.get("status", "FAILED")),
        history_mode="YFINANCE_RAW",
    )
    if candidate_history_report["status"] != "SUCCESS":
        marker = (
            "READY_FOR_DECISION_US_STRATEGY_RUNTIME"
            if any(
                "RUNTIME_BUDGET_EXCEEDED" in str(error)
                for error in candidate_history_report.get("errors", [])
            )
            else "READY_FOR_DECISION_US_CANDIDATE_SHORT_HISTORY"
        )
        return _finish_market_report(
            report,
            run_started,
            status=marker,
            marker=marker,
            error_code=marker,
        )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget

    selector_started = time.perf_counter()
    try:
        candidate_summary, candidate_universe = _candidate_summary(
            seeds, candidate_histories, effective_as_of
        )
    except Exception as exc:
        error_code = _market_error_code("US_CANDIDATE_SELECTOR_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "candidate_selector",
            started=selector_started,
            symbols=len(seeds),
            rows=sum(len(values) for values in candidate_histories.values()),
            failed_count=len(seeds),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_US_CANDIDATE_SELECTOR",
            marker="READY_FOR_DECISION_US_CANDIDATE_SELECTOR",
            error_code=error_code,
        )
    candidate_summary["source_as_of"] = source_as_of.isoformat() if source_as_of else None
    report["candidate"] = candidate_summary
    selector_usable = int(candidate_summary["history_usable"])
    selector_included = int(candidate_summary["final_included_count"])
    _record_stage(
        report["stage_timings"],
        "candidate_selector",
        started=selector_started,
        symbols=len(seeds),
        rows=sum(len(values) for values in candidate_histories.values()),
        usable_count=selector_included,
        failed_count=max(len(seeds) - selector_usable, 0),
        status="SUCCESS",
        included=selector_included,
        excluded=max(len(seeds) - selector_included, 0),
    )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget

    included_symbols = tuple(record.symbol for record in candidate_universe.included)
    if not included_symbols:
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_US_CANDIDATE_EMPTY",
            marker="READY_FOR_DECISION_US_CANDIDATE_EMPTY",
            error_code="US_CANDIDATE_EMPTY",
        )

    deep_started = time.perf_counter()
    try:
        strategy_sessions = _completed_us_sessions(
            effective_as_of, STRATEGY_HISTORY_BARS
        )
        strategy_histories, strategy_history_report = _run_yfinance_batch_history(
            included_symbols,
            start_date=strategy_sessions[0],
            end_date=strategy_sessions[-1],
            auto_adjust=True,
            requested_bars=STRATEGY_HISTORY_BARS,
            stage="STRATEGY_QFQ_HISTORY",
            deadline=run_started + RUNTIME_BUDGET_SECONDS,
        )
    except Exception as exc:
        error_code = _market_error_code("US_STRATEGY_HISTORY_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "deep_raw_history_network",
            started=deep_started,
            symbols=len(included_symbols),
            failed_count=len(included_symbols),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_US_STRATEGY_HISTORY",
            marker="READY_FOR_DECISION_US_STRATEGY_HISTORY",
            error_code=error_code,
        )
    report.setdefault("strategy", {})["deep_raw_history"] = strategy_history_report
    _stage_from_report(
        report["stage_timings"],
        "deep_raw_history_network",
        strategy_history_report,
        started=deep_started,
        status=str(strategy_history_report.get("status", "FAILED")),
        history_mode="YFINANCE_AUTO_ADJUSTED_QFQ",
    )
    if strategy_history_report["status"] != "SUCCESS":
        marker = (
            "READY_FOR_DECISION_US_STRATEGY_RUNTIME"
            if any(
                "RUNTIME_BUDGET_EXCEEDED" in str(error)
                for error in strategy_history_report.get("errors", [])
            )
            else "READY_FOR_DECISION_US_STRATEGY_HISTORY"
        )
        return _finish_market_report(
            report,
            run_started,
            status=marker,
            marker=marker,
            error_code=marker,
        )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget

    qfq_rows = sum(len(values) for values in strategy_histories.values())
    _record_stage(
        report["stage_timings"],
        "adj_factor_network",
        started=time.perf_counter(),
        elapsed_seconds=0.0,
        symbols=len(included_symbols),
        rows=0,
        usable_count=len(included_symbols),
        failed_count=0,
        status="NOT_APPLICABLE",
        method="YFINANCE_AUTO_ADJUSTED",
    )
    _record_stage(
        report["stage_timings"],
        "qfq_construction",
        started=time.perf_counter(),
        elapsed_seconds=0.0,
        symbols=len(included_symbols),
        rows=qfq_rows,
        usable_count=len(strategy_histories),
        failed_count=max(len(included_symbols) - len(strategy_histories), 0),
        status="NOT_APPLICABLE",
        method="YFINANCE_AUTO_ADJUSTED_QFQ",
    )
    decision_started = time.perf_counter()
    us_strategy_ready = tuple(
        symbol for symbol in included_symbols if strategy_histories.get(symbol)
    )
    try:
        decision = _run_daily_decision_shadow(
            strategy_histories,
            strategy_sessions[-1],
            market="US",
            requested_symbols=included_symbols,
            history_ready_symbols=us_strategy_ready,
        )
    except Exception as exc:
        error_code = _market_error_code("US_DAILY_DECISION_CHAIN_FAILED", exc)
        _record_stage(
            report["stage_timings"],
            "daily_decision_chain",
            started=decision_started,
            symbols=len(included_symbols),
            failed_count=len(included_symbols),
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status="READY_FOR_DECISION_US_DAILY_DECISION_CHAIN",
            marker="READY_FOR_DECISION_US_DAILY_DECISION_CHAIN",
            error_code=error_code,
        )
    report["strategy"].update(
        {
            "qfq": {
                "method": "YFINANCE_AUTO_ADJUSTED",
                "exact_as_of_anchor": True,
                "status": "SUCCESS",
            },
            "decision_chain": decision,
        }
    )
    _record_stage(
        report["stage_timings"],
        "daily_decision_chain",
        started=decision_started,
        symbols=len(included_symbols),
        rows=qfq_rows,
        usable_count=decision["evaluated"],
        failed_count=decision["failed"],
        status=decision["status"],
    )
    over_budget = _finish_if_over_budget(report, run_started)
    if over_budget is not None:
        return over_budget
    return _finish_market_report(
        report,
        run_started,
        status="CANDIDATE_SUCCESS",
        marker="CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1_COMPLETE",
    )


def run_market_probe(*, market: str, as_of: date = DEFAULT_AS_OF) -> dict[str, Any]:
    normalized = str(market).strip().upper()
    if normalized not in MARKETS:
        raise ValueError("market must be cn or us")
    run_started = time.perf_counter()
    try:
        if normalized == "CN":
            return _run_cn_market(as_of=as_of)
        return _run_us_market(as_of=as_of)
    except Exception as exc:
        report = _new_market_report(normalized, as_of)
        error_code = _market_error_code(
            f"{normalized}_MARKET_RUNTIME_FAILED", exc
        )
        _record_stage(
            report["stage_timings"],
            "report_construction",
            started=run_started,
            failed_count=1,
            status="FAILED",
            error_code=error_code,
        )
        return _finish_market_report(
            report,
            run_started,
            status=f"READY_FOR_DECISION_{normalized}_MARKET_RUNTIME",
            marker=f"READY_FOR_DECISION_{normalized}_MARKET_RUNTIME",
            error_code=error_code,
        )


def run_probe(
    *, as_of: date = DEFAULT_AS_OF, market: str = "all"
) -> dict[str, Any]:
    """Run one market independently, or run both as a convenience aggregate."""

    normalized = str(market).strip().upper()
    if normalized in MARKETS:
        return run_market_probe(market=normalized, as_of=as_of)
    if normalized != "ALL":
        raise ValueError("market must be cn, us, or all")

    started = time.perf_counter()
    markets = {
        name: run_market_probe(market=name, as_of=as_of) for name in MARKETS
    }
    successful = all(item.get("status") == "CANDIDATE_SUCCESS" for item in markets.values())
    return {
        "probe": "CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1",
        "market": "ALL",
        "requested_as_of_date": as_of.isoformat(),
        "status": "CANDIDATE_SUCCESS" if successful else "PARTIAL_MARKET_FAILURE",
        "decision_marker": (
            "CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1_COMPLETE"
            if successful
            else "MARKET_INDEPENDENT_RUNTIME_PARTIAL_FAILURE"
        ),
        "markets": markets,
        "candidate": {
            name: item.get("candidate") for name, item in markets.items()
        },
        "strategy": {
            name: item.get("strategy") for name, item in markets.items()
        },
        "stage_timings": {
            name: item.get("stage_timings") for name, item in markets.items()
        },
        "runtime": {
            "total_elapsed_seconds": round(time.perf_counter() - started, 3),
            "market_totals": {
                name: item.get("runtime", {}).get("total_elapsed_seconds")
                for name, item in markets.items()
            },
        },
        "runtime_acceptance": "NOT_AN_ACCEPTANCE_STANDARD",
        "all_is_convenience_only": True,
        "read_only": True,
        "production_state_write": False,
        "sheets_write": False,
        "allocation": False,
        "broker_order": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--market",
        choices=("cn", "us", "all"),
        default="all",
        help="independent market runtime; all is a development convenience aggregate",
    )
    parser.add_argument(
        "--date",
        "--as-of",
        dest="as_of",
        type=date.fromisoformat,
        default=DEFAULT_AS_OF,
        help="exact completed market date (legacy alias: --as-of)",
    )
    args = parser.parse_args()
    try:
        report = run_probe(as_of=args.as_of, market=args.market)
    except TushareGatewayError as exc:
        report = {
            "probe": "CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1",
            "market": args.market.upper(),
            "status": str(exc),
            "error_code": str(exc),
            "read_only": True,
            "production_state_write": False,
            "sheets_write": False,
            "allocation": False,
            "broker_order": False,
        }
    except Exception:
        report = {
            "probe": "CANDIDATE_STRATEGY_SHADOW_BRIDGE_V1",
            "market": args.market.upper(),
            "status": "CANDIDATE_STRATEGY_SHADOW_BRIDGE_SETUP_FAILED",
            "error_code": "CANDIDATE_STRATEGY_SHADOW_BRIDGE_SETUP_FAILED",
            "read_only": True,
            "production_state_write": False,
            "sheets_write": False,
            "allocation": False,
            "broker_order": False,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "CANDIDATE_SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())

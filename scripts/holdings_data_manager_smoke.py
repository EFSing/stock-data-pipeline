"""Read-only provider smoke for the holdings history coverage contract.

This utility intentionally bypasses Sheets and all strategy/research entry
points.  It uses the existing provider adapters and the same normalization,
latest-session, quote-QC, and raw/qfq coverage helpers as the lifecycle
manager.  Its output is observational evidence, not a frozen test fixture.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import latest_completed_market_session, ordinary_calendar_freshness_guard
from holdings_data_manager import (
    _calendar_year_before,
    _validate_fetched_quotes,
    history_coverage_report,
    normalize_holding,
)
from main import beijing_now
from providers import fetch_latest_with_retry, fetch_with_retry


BEIJING = ZoneInfo("Asia/Shanghai")


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _quote_summary(quotes) -> dict:
    dates = [item.trade_date for item in quotes]
    unique = set(dates)
    return {
        "first_trade_date": _date_text(min(unique) if unique else None),
        "last_trade_date": _date_text(max(unique) if unique else None),
        "bar_count": len(quotes),
        "duplicate_count": len(dates) - len(unique),
        "dates": unique,
    }


def run_smoke(symbol: str, market: str | None = None) -> dict:
    normalized = normalize_holding(symbol, market)
    watch = normalized.watch_row(enabled=False)
    now = beijing_now().astimezone(BEIJING)
    local_end = now.astimezone(ZoneInfo(normalized.timezone)).date()
    retry_count = 2
    retry_wait = 1.0

    latest = fetch_latest_with_retry(
        normalized.primary_source, watch, local_end, retry_count, retry_wait
    )
    latest = _validate_fetched_quotes(latest, watch, date.min, local_end)
    target = latest_completed_market_session(
        normalized.timezone, normalized.close_time, now, latest
    )
    if target is None:
        raise RuntimeError("无法从真实 provider 确定最近已完成交易日")
    guard = ordinary_calendar_freshness_guard(
        normalized.timezone, normalized.close_time, now
    )
    freshness_guard_ok = target >= guard

    start = _calendar_year_before(target)
    raw = fetch_with_retry(
        normalized.primary_source,
        watch,
        "raw",
        start,
        target,
        retry_count,
        retry_wait,
        target_trade_date=target,
    )
    adjusted = fetch_with_retry(
        normalized.historical_source,
        watch,
        "qfq",
        start,
        target,
        retry_count,
        retry_wait,
        target_trade_date=target,
    )
    raw = _validate_fetched_quotes(raw, watch, start, target)
    adjusted = _validate_fetched_quotes(adjusted, watch, start, target)
    raw_summary = _quote_summary(raw)
    adjusted_summary = _quote_summary(adjusted)
    report = history_coverage_report(
        [item.trade_date for item in raw],
        [item.trade_date for item in adjusted],
        start,
        target,
    )
    return {
        "symbol": normalized.symbol,
        "market": normalized.market,
        "primary_source": normalized.primary_source,
        "historical_source": normalized.historical_source,
        "requested_start": start.isoformat(),
        "target_trade_date": target.isoformat(),
        "ordinary_calendar_freshness_guard": guard.isoformat(),
        "freshness_guard_ok": freshness_guard_ok,
        "raw": {
            key: value for key, value in raw_summary.items() if key != "dates"
        },
        "qfq": {
            key: value for key, value in adjusted_summary.items()
            if key != "dates"
        },
        "raw_only_dates": [
            value.isoformat() for value in sorted(raw_summary["dates"] - adjusted_summary["dates"])
        ],
        "qfq_only_dates": [
            value.isoformat() for value in sorted(adjusted_summary["dates"] - raw_summary["dates"])
        ],
        "coverage_ok": report.ok,
        "coverage_reason": report.reason,
        "suspicious_gaps": [
            [left.isoformat(), right.isoformat()]
            for left, right in report.suspicious_gaps
        ],
        "quote_qc_ok": True,
        "coverage_qc_ok": report.ok,
        "lifecycle_ready": freshness_guard_ok and report.ok,
        "sheets_written": False,
        "strategy_or_research_called": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbol", nargs="?", default="512400.SH")
    parser.add_argument("--market")
    parser.add_argument("--include-us", action="store_true")
    args = parser.parse_args()
    symbols = [(args.symbol, args.market)]
    if args.include_us:
        symbols.append(("MU", "US"))
    results = []
    for symbol, market in symbols:
        try:
            results.append({"status": "OK", **run_smoke(symbol, market)})
        except Exception as exc:
            results.append({
                "status": "FAILED",
                "symbol": symbol,
                "market": market,
                "error": str(exc),
                "sheets_written": False,
                "strategy_or_research_called": False,
            })
    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(
        result["status"] == "OK"
        and result.get("coverage_ok")
        and result.get("coverage_qc_ok")
        for result in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

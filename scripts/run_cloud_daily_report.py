"""Run one market-scoped Cloud Daily Report with an observation-only ledger.

The script is intentionally a thin orchestrator.  Session identity, provider
fallback, latest validation, Candidate discovery, and the Daily Decision Chain
remain owned by the existing modules; this layer only supplies ephemeral
market evidence, persists opportunity observations, writes the two final
artifacts, and optionally notifies. Strategy/Paper/holdings remain read-only.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping

try:
    from scripts.run_production_daily_decision import run_production_daily_decision
except ModuleNotFoundError as exc:
    # ``python scripts/run_cloud_daily_report.py`` is the documented/manual
    # invocation used by the workflows, while tests and module callers import
    # it as ``scripts.run_cloud_daily_report``.  Keep both entrypoints valid.
    if exc.name != "scripts":
        raise
    from run_production_daily_decision import run_production_daily_decision
from sheets_client import SheetsClient
from trading.daily_dashboard import build_dashboard_projection, render_dashboard_html
from trading.daily_report_email import render_daily_report_email_html
from trading.ephemeral_market_data import (
    EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION,
    EphemeralMarketDataSnapshot,
    load_ephemeral_market_data,
)
from trading.notifications import github_run_url, send_bark, send_optional_email
from trading.operational_markers import (
    FINAL_SESSION_ALREADY_COMPLETED,
    claim_email_delivery_failure_alert,
    claim_ledger_error_alert,
    claim_report_notification,
    final_report_session_status,
)
from trading.production_candidate_runtime import ProductionCandidateRuntime
from trading.opportunity_ledger import RELEASE_DATE, SCHEMAS, birth_snapshots, persist_daily_opportunities
from trading.production_prerequisites import ExactExchangeCalendarProvider
from trading.risk import MIN_TARGET_UPSIDE_PCT
from trading.setup01_decision import SETUP01_MINIMUM_RR
from trading.setup02_decision import SETUP02_MINIMUM_RR


CLOUD_DAILY_REPORT_PROTOCOL_VERSION = "CLOUD-DAILY-REPORT-MOBILE-V1-2026-09-14"
DAILY_REPORT_DELIVERY_READINESS_VERSION = "DAILY_REPORT_DELIVERY_READINESS_V1"
FINAL_REPORT_ELIGIBLE = "FINAL_REPORT_ELIGIBLE"
DEGRADED_DIAGNOSTIC_ONLY = "DEGRADED_DIAGNOSTIC_ONLY"
UPSTREAM_NOT_READY = "UPSTREAM_NOT_READY"
DELIVERY_FAILED = "FAILED"
MARKET_LABELS = {"CN": "A股", "US": "美股"}
ARTIFACT_ALLOWLIST = ("daily-report.json", "daily-report.html")
# Operational-only Candidate readiness gates.  The 2026-10-06 US artifact
# had 306 stale Candidate errors over 717 data-qualified symbols (42.68%),
# while the recovered run had 0 stale errors over 1,021 qualified symbols and
# only two ordinary provider-symbol errors.  This boundary separates that
# observed broad-tail condition from isolated symbol failures; it never enters
# Candidate ranking or strategy calculations.
CANDIDATE_BROAD_STALE_MIN_COUNT = 3
CANDIDATE_BROAD_STALE_RATIO = 0.25
FINAL_DELIVERY_ELIGIBLE = "FINAL_DELIVERY_ELIGIBLE"
FINAL_DELIVERY_PENDING_LEDGER = "FINAL_DELIVERY_PENDING_LEDGER"
FINAL_DELIVERY_BLOCKED_LEDGER = "FINAL_DELIVERY_BLOCKED_LEDGER"
FINAL_DELIVERY_NOT_APPLICABLE_DIAGNOSTIC = "FINAL_DELIVERY_NOT_APPLICABLE_DIAGNOSTIC"
FINAL_DELIVERY_NOT_ELIGIBLE_REPORT_DATA = "FINAL_DELIVERY_NOT_ELIGIBLE_REPORT_DATA"
FINAL_DELIVERY_ALREADY_COMPLETED = "FINAL_DELIVERY_ALREADY_COMPLETED"
DELIVERY_SCOPE_NATURAL = "NATURAL"
DELIVERY_SCOPE_DIAGNOSTIC = "DIAGNOSTIC"
EMAIL_DELIVERY_FAILED = "EMAIL_DELIVERY_FAILED"
BARK_DELIVERY_FAILED = "BARK_DELIVERY_FAILED"
# The normal automatic path has a finite 25-minute recovery window: t=0, 5,
# 10, 15, 20, and 25 minutes.  A later schedule fallback remains useful when
# the close workflow itself is delayed, while this window covers the observed
# US provider lag without an unbounded runner wait.
DEFAULT_RETRY_NOT_READY_ATTEMPTS = 6
DEFAULT_RETRY_NOT_READY_DELAY_SECONDS = 300.0
MAX_RETRY_NOT_READY_ATTEMPTS = 8
MAX_RETRY_NOT_READY_DELAY_SECONDS = 900.0
PROSPECTIVE_FUNNEL_PROTOCOL_VERSION = "PROSPECTIVE_EXACT_T_FUNNEL_V1"


def bounded_readiness_attempt_offsets(
    attempts: int = DEFAULT_RETRY_NOT_READY_ATTEMPTS,
    delay_seconds: float = DEFAULT_RETRY_NOT_READY_DELAY_SECONDS,
) -> tuple[float, ...]:
    """Return the finite elapsed-second schedule used by the CLI retry loop."""

    count = min(max(int(attempts), 1), MAX_RETRY_NOT_READY_ATTEMPTS)
    delay = min(max(float(delay_seconds), 0.0), MAX_RETRY_NOT_READY_DELAY_SECONDS)
    return tuple(index * delay for index in range(count))


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _error_text(exc: BaseException | str) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ").strip()[:300] or type(exc).__name__


def resolve_cloud_trade_date(
    market: str,
    explicit_trade_date: date | None = None,
    *,
    now: datetime | None = None,
    calendar_provider: ExactExchangeCalendarProvider | None = None,
) -> date:
    """Resolve automatic report T from the latest real completed close.

    Explicit dates remain authoritative for diagnostics/manual runs.  Automatic
    runs use the shared exact exchange-calendar resolver, so a delayed trigger
    cannot select a new local civil date whose session has not completed.
    """

    if explicit_trade_date is not None:
        return explicit_trade_date
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("cloud report requires timezone-aware now")
    provider = calendar_provider or ExactExchangeCalendarProvider()
    return provider.latest_completed_session(
        str(market).strip().upper(), now=current
    ).trade_date


def _git_sha(environ: Mapping[str, str] | None = None) -> str | None:
    values = environ or os.environ
    configured = str(values.get("GITHUB_SHA") or values.get("CI_COMMIT_SHA") or "").strip()
    if configured:
        return configured
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _session_payload(identity: Any) -> dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "market": str(identity.market).upper(),
        "trade_date": _iso(identity.trade_date),
        "identity": str(identity.identity),
        "exact_exchange_calendar": bool(identity.exact_exchange_calendar),
        "next_session_date": _iso(identity.next_session_date),
    }


def _empty_result(as_of_date: date, status: str, errors: list[str]) -> dict[str, Any]:
    return {
        "market": None,
        "as_of_date": as_of_date.isoformat(),
        "preflight": {
            "T": as_of_date.isoformat(),
            "production readiness": status,
            "accounts": [],
            "errors": list(errors),
            "writes performed": False,
        },
        "read behavior": "READ_ONLY",
        "NO STATE WRITE": True,
        "NO Sheets mutation": True,
        "candidate strategy pool mutation": False,
        "broker orders": "NONE",
        "candidate_markets": {},
        "funnel": {},
        "candidate_runtime_errors": {},
        "reports": [],
    }


def _status_from_result(
    result: Mapping[str, Any],
    ephemeral: EphemeralMarketDataSnapshot,
) -> tuple[str, dict[str, Any]]:
    preflight = result.get("preflight") if isinstance(result.get("preflight"), Mapping) else {}
    report_values = result.get("reports") if isinstance(result.get("reports"), list) else []
    counts: dict[str, int] = {
        "DATA_OK": 0,
        "DATA_MISSING": 0,
        "DATA_STALE": 0,
        "DATA_INVALID": 0,
        "DATA_ADJUSTMENT_UNVERIFIED": 0,
        "PROVIDER_SYMBOL_ERROR": 0,
        "PROVIDER_GLOBAL_FAILURE": 0,
        "DATA_BAD": 0,
        "DATA_UNAVAILABLE": 0,
    }
    failed_symbols: set[str] = set()
    reported_symbols: set[str] = set()
    for entry in report_values:
        report = entry.get("报告") if isinstance(entry, Mapping) else {}
        for row in report.get("results", []) if isinstance(report, Mapping) else []:
            symbol = str(row.get("symbol") or row.get("统一代码") or "")
            if symbol:
                reported_symbols.add(symbol)
            status = str(row.get("data_status") or "").upper()
            if status in counts:
                counts[status] += 1
            if status and status != "DATA_OK":
                failed_symbols.add(symbol)
    for symbol, item in ephemeral.symbol_status.items():
        if symbol not in reported_symbols:
            status = str(item.get("status") or "").upper()
            if status in counts:
                counts[status] += 1
        if item.get("errors") or item.get("status") not in {None, "DATA_OK"}:
            failed_symbols.add(symbol)
    preflight_ready = str(preflight.get("production readiness") or "") == "READY"
    preflight_errors = tuple(str(value) for value in (preflight.get("errors") or ()) if value)
    candidate_errors = result.get("candidate_runtime_errors")
    candidate_quality_errors: list[str] = []
    candidate_component_status = "NOT_RUN"
    candidate_markets = result.get("candidate_markets")
    if isinstance(candidate_markets, Mapping):
        candidate = candidate_markets.get(ephemeral.market)
        if not isinstance(candidate, Mapping):
            candidate_component_status = "UNAVAILABLE"
            candidate_quality_errors.append(
                f"{ephemeral.market} Candidate status: NOT_REPORTED"
            )
        else:
            raw_candidate_status = str(candidate.get("candidate_status") or "").upper()
            candidate_status = str(candidate.get("status") or "").upper()
            if raw_candidate_status:
                candidate_component_status = raw_candidate_status
            elif candidate_status in {"FAILED", "PROVIDER_GLOBAL_FAILURE"}:
                candidate_component_status = "UNAVAILABLE"
            elif candidate_status == "PARTIAL_DATA_QUALITY":
                candidate_component_status = "PARTIAL"
            elif candidate_status == "NO_CANDIDATES":
                candidate_component_status = "NO_CANDIDATES"
            elif candidate_status == "SUCCESS":
                candidate_component_status = "SUCCESS"
            elif candidate_status == "NOT_RUN":
                candidate_component_status = "NOT_RUN"
            else:
                candidate_component_status = "UNAVAILABLE"
            if candidate_status not in {"", "SUCCESS", "NO_CANDIDATES", "NOT_RUN"}:
                candidate_quality_errors.append(
                    f"{ephemeral.market} Candidate status: {candidate_status}"
                )
            elif candidate_component_status in {"UNAVAILABLE", "PARTIAL"}:
                # Prefer the explicit component status when an older or
                # malformed payload claims SUCCESS for the Candidate stage.
                candidate_quality_errors.append(
                    f"{ephemeral.market} Candidate status: {candidate_component_status}"
                )
            elif candidate_status == "NOT_RUN" and report_values:
                candidate_quality_errors.append(
                    f"{ephemeral.market} Candidate status: NOT_RUN"
                )
            selection_outcome = str(
                candidate.get("candidate_selection_outcome") or ""
            ).upper()
            if not selection_outcome:
                included_count = candidate.get("candidate_included_count")
                try:
                    included_count = int(included_count or 0)
                except (TypeError, ValueError):
                    included_count = 0
                if candidate_status == "NOT_RUN" and not report_values:
                    selection_outcome = "NOT_RUN"
                elif candidate_status == "NO_CANDIDATES":
                    selection_outcome = "NO_CANDIDATES"
                elif included_count:
                    # Backward-compatible interpretation for an older
                    # artifact that predated the explicit outcome field.
                    selection_outcome = "CANDIDATES_INCLUDED"
                else:
                    selection_outcome = "NOT_REPORTED"
            if selection_outcome == "NOT_REPORTED":
                candidate_quality_errors.append(
                    f"{ephemeral.market} Candidate outcome: NOT_REPORTED"
                )
            if selection_outcome == "NOT_RUN" and report_values:
                candidate_quality_errors.append(
                    f"{ephemeral.market} Candidate outcome: NOT_RUN"
                )
            if selection_outcome == "DISCOVERY_FAILED":
                candidate_quality_errors.append(
                    f"{ephemeral.market} Candidate outcome: DISCOVERY_FAILED"
                )
            timings = candidate.get("stage_timings")
            if isinstance(timings, Mapping):
                for stage_name in ("candidate_short_history", "candidate_selector", "deep_history"):
                    stage = timings.get(stage_name)
                    stage_status = str(stage.get("status") or "").upper() if isinstance(stage, Mapping) else ""
                    if stage_status in {"FAILED", "PARTIAL_DATA_QUALITY", "BLOCKED"}:
                        candidate_quality_errors.append(
                            f"{ephemeral.market} Candidate {stage_name}: {stage_status}"
                        )
            candidate_quality_errors.extend(
                f"{ephemeral.market} Candidate: {value}"
                for value in (candidate.get("errors") or ())
                if value
            )
            deep_errors = candidate.get("deep_history_errors")
            if isinstance(deep_errors, Mapping):
                candidate_quality_errors.extend(
                    f"{ephemeral.market} Candidate deep history {symbol}: {value}"
                    for symbol, values in deep_errors.items()
                    for value in (values if isinstance(values, (list, tuple)) else (values,))
                    if value
                )
    elif result.get("reports"):
        candidate_component_status = "UNAVAILABLE"
        candidate_quality_errors.append(
            f"{ephemeral.market} Candidate status: NOT_REPORTED"
        )
    candidate_failed = bool(candidate_errors) or bool(candidate_quality_errors)
    attempted = len(ephemeral.required_symbols)
    data_ok = sum(
        1 for item in ephemeral.symbol_status.values() if item.get("status") == "DATA_OK"
    )
    symbol_failures = bool(failed_symbols) or data_ok < attempted
    provider_global_failure = any(
        bool(item.get("global_failure")) for item in ephemeral.provider_status.values()
    )
    # Candidate history loading is another canonical-provider boundary.  A
    # provider-wide auth/schema/outage error must remain one run-level failure,
    # not degrade into hundreds of candidate-quality symbol warnings.
    candidate_global_values = (
        list(candidate_errors.values())
        if isinstance(candidate_errors, Mapping)
        else []
    )
    candidate_global_values.extend(candidate_quality_errors)
    provider_global_failure = provider_global_failure or any(
        "PROVIDER_GLOBAL_FAILURE" in str(value).upper()
        for value in candidate_global_values
    )
    if isinstance(candidate_markets, Mapping):
        provider_global_failure = provider_global_failure or any(
            isinstance(candidate, Mapping)
            and bool(candidate.get("provider_global_failure"))
            for candidate in candidate_markets.values()
        )
    data_status = (
        "NO_USABLE_SYMBOLS"
        if attempted and data_ok == 0
        else "PARTIAL"
        if symbol_failures or bool(ephemeral.errors) or candidate_failed
        else "OK"
    )
    # A warning report may complete operationally without upgrading its quality.
    rows = [row for entry in report_values for row in entry.get("报告", {}).get("results", [])]
    exact_rows = [row for row in rows if row.get("market") == ephemeral.market
                  and row.get("as_of_date") == ephemeral.as_of_date.isoformat()
                  and row.get("data_status") == "DATA_OK"]
    if data_status == "NO_USABLE_SYMBOLS" and exact_rows:
        # A formal pool row is already exact-T usable evidence.  Candidate
        # discovery failure must not relabel that normal formal coverage as a
        # market-wide no-usable-symbols run.
        data_status = "PARTIAL"
    latest_symbols = {str(row.get("统一代码")) for row in ephemeral.latest_rows
                      if str(row.get("交易日期")) == ephemeral.as_of_date.isoformat()
                      and str(row.get("市场")) == ephemeral.market
                      and row.get("校验状态") in {"已验证", "单源可用", "DATA_OK"}}
    qfq_symbols = {str(row.get("统一代码")) for row in ephemeral.qfq_rows
                   if str(row.get("交易日期")) == ephemeral.as_of_date.isoformat()
                   and str(row.get("市场")) == ephemeral.market}
    core_failed = any("EVALUATION_FAILED" in str(reason) or
                      "QFQ_HISTORY_MUST_REACH_COMPLETED_SESSION_T" in str(reason)
                      for row in rows for reason in row.get("reasons", ()))
    core_failed = core_failed or any(
        "EVALUATION_FAILED" in str((row.get("position_management") or {}).get("status", ""))
        for row in rows)
    canonical_no_usable = data_status == "NO_USABLE_SYMBOLS" and any(
        item.get("status") in {
            "DATA_MISSING", "DATA_STALE", "DATA_INVALID",
            "DATA_ADJUSTMENT_UNVERIFIED", "PROVIDER_SYMBOL_ERROR",
            "PROVIDER_GLOBAL_FAILURE",
        }
        for item in ephemeral.symbol_status.values()
    )
    has_exact_market_data = bool(exact_rows or latest_symbols.intersection(qfq_symbols))
    operationally_complete = (
        bool(report_values)
        and not core_failed
        and (has_exact_market_data or canonical_no_usable)
    )
    if provider_global_failure:
        run_status = "PROVIDER_GLOBAL_FAILURE"
    elif not preflight_ready and not report_values:
        run_status = "FAILED"
    elif core_failed:
        run_status = "FAILED"
    elif data_status == "NO_USABLE_SYMBOLS":
        run_status = "COMPLETED_NO_USABLE_SYMBOLS"
    else:
        run_status = "COMPLETED"
    # Keep the historical status token as a display/API compatibility alias;
    # callers must use run_status and data_status for exit semantics.
    status = (
        "FAILED"
        if run_status == "FAILED"
        else "PROVIDER_GLOBAL_FAILURE"
        if run_status == "PROVIDER_GLOBAL_FAILURE"
        else "PARTIAL_DATA_QUALITY"
        if run_status == "COMPLETED_NO_USABLE_SYMBOLS"
        else "PARTIAL_DATA_QUALITY"
        if data_status != "OK"
        else "SUCCESS"
    )
    coverage_ratio = data_ok / attempted if attempted else 1.0
    candidate_operational: dict[str, Any] = {}
    if isinstance(candidate_markets, Mapping):
        candidate_value = candidate_markets.get(ephemeral.market)
        if isinstance(candidate_value, Mapping):
            candidate_operational = _candidate_operational_diagnostics(
                candidate_value, market=ephemeral.market,
            )
    quality = {
        "status": status,
        "run_status": run_status,
        "data_status": data_status,
        "attempted_universe": attempted,
        "data_ok_count": data_ok,
        "failed_count": max(attempted - data_ok, 0),
        "formal_exact_t_attempted_count": attempted,
        "formal_exact_t_usable_count": data_ok,
        "formal_exact_t_failed_count": max(attempted - data_ok, 0),
        "coverage_ratio": coverage_ratio,
        "coverage_pct": round(coverage_ratio * 100, 2),
        "formal_exact_t_coverage_ratio": coverage_ratio,
        "formal_exact_t_coverage_pct": round(coverage_ratio * 100, 2),
        "strategy_analyzed_count": len(exact_rows),
        "blocked_count": max(attempted - len(exact_rows), 0),
        "strategy_blocked_count": max(attempted - len(exact_rows), 0),
        "operationally_complete": operationally_complete,
        "counts": counts,
        "failed_symbols": sorted(symbol for symbol in failed_symbols if symbol),
        "failed_by_reason": {
            status_name: sorted(
                symbol
                for symbol, item in ephemeral.symbol_status.items()
                if item.get("status") == status_name
            )
            for status_name in sorted({
                str(item.get("status"))
                for item in ephemeral.symbol_status.values()
                if item.get("status") not in {None, "DATA_OK"}
            })
        },
        "ephemeral_errors": list(ephemeral.errors),
        "preflight_errors": list(preflight_errors),
        "candidate_runtime_errors": dict(candidate_errors) if isinstance(candidate_errors, Mapping) else {},
        "candidate_quality_errors": list(dict.fromkeys(candidate_quality_errors)),
        "preflight_ready": preflight_ready,
        "candidate_runtime_failed": candidate_failed,
        "candidate_status": candidate_component_status,
        "CANDIDATE_STATUS": candidate_component_status,
        "provider_global_failure": provider_global_failure,
        **candidate_operational,
    }
    return status, quality


def _integer_value(value: Any, default: int = 0) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _candidate_readiness_snapshot(
    result: Mapping[str, Any], quality: Mapping[str, Any], market: str,
) -> dict[str, Any]:
    candidate_markets = result.get("candidate_markets")
    candidate = (
        candidate_markets.get(market)
        if isinstance(candidate_markets, Mapping)
        else None
    )
    candidate = candidate if isinstance(candidate, Mapping) else {}
    candidate_status = str(
        quality.get("candidate_status")
        or candidate.get("candidate_status")
        or candidate.get("status")
        or "NOT_REPORTED"
    ).strip().upper()
    selection = str(candidate.get("candidate_selection_outcome") or "").strip().upper()
    included = _integer_value(candidate.get("candidate_included_count"))
    dynamic_analysis: int | None = None
    for entry in result.get("reports", ()) if isinstance(result.get("reports"), list) else ():
        if not isinstance(entry, Mapping) or str(entry.get("市场") or "").upper() != market:
            continue
        scope = (entry.get("universe") or {}).get("analysis_scope_counts")
        if isinstance(scope, Mapping):
            dynamic_analysis = _integer_value(scope.get("dynamic_candidate_strategy_analysis"))
            break
    if dynamic_analysis is None:
        dynamic_analysis = _integer_value(
            candidate.get("strategy_analysis_count"),
            _integer_value(candidate.get("deep_analysis_count")),
        )
    return {
        "candidate_status": candidate_status,
        "selection_outcome": selection,
        "included_count": included,
        "dynamic_strategy_analysis_count": dynamic_analysis,
        "candidate": candidate,
    }


def _candidate_operational_diagnostics(
    candidate: Mapping[str, Any], *, market: str,
) -> dict[str, Any]:
    """Classify Candidate provider symptoms without changing strategy inputs."""

    raw_errors: list[str] = [
        str(value) for value in (candidate.get("errors") or ()) if value
    ]
    deep_errors = candidate.get("deep_history_errors")
    if isinstance(deep_errors, Mapping):
        for symbol, values in deep_errors.items():
            values = values if isinstance(values, (list, tuple)) else (values,)
            raw_errors.extend(f"{symbol}:{value}" for value in values if value)

    def symbol_for(value: str) -> str | None:
        text = value.strip()
        prefix = f"{market} Candidate:"
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
        if text.startswith("Candidate:"):
            text = text[len("Candidate:"):].strip()
        symbol = text.split(":", 1)[0].strip()
        if not symbol or " " in symbol or symbol.upper() in {"STATUS", "CANDIDATE"}:
            return None
        return symbol.upper()

    stale_symbols: set[str] = set()
    provider_symbol_symbols: set[str] = set()
    stale_messages = 0
    provider_symbol_messages = 0
    for value in raw_errors:
        upper = value.upper()
        is_stale = (
            "YAHOO_CHART返回日期落后于目标交易日" in value
            or "DATA_STALE" in upper
            or "TARGET_SESSION_MISSING" in upper
            or ("TARGET SESSION" in upper and "STALE" in upper)
        )
        is_provider_symbol = (
            "PROVIDER_SYMBOL_ERROR" in upper
            or "YAHOO_CHART_SYMBOL_ERROR" in upper
        )
        symbol = symbol_for(value)
        if is_stale:
            stale_messages += 1
            if symbol:
                stale_symbols.add(symbol)
        elif is_provider_symbol:
            provider_symbol_messages += 1
            if symbol:
                provider_symbol_symbols.add(symbol)

    stale_count = len(stale_symbols) or stale_messages
    provider_symbol_count = len(provider_symbol_symbols) or provider_symbol_messages
    qualified = _integer_value(candidate.get("candidate_data_qualified_count"))
    included = _integer_value(candidate.get("candidate_included_count"))
    denominator = max(qualified, included)
    ratio = stale_count / denominator if denominator else 0.0
    exclusions = candidate.get("candidate_exclusion_reason_counts")
    normal_exclusions = 0
    if isinstance(exclusions, Mapping):
        for reason, value in exclusions.items():
            if str(reason).upper() != "INCLUDED":
                normal_exclusions += _integer_value(value)
    return {
        "candidate_exact_t_stale_count": stale_count,
        "candidate_exact_t_stale_ratio": round(ratio, 6),
        "candidate_exact_t_stale_base_count": denominator,
        "candidate_provider_symbol_error_count": provider_symbol_count,
        "candidate_normal_exclusion_count": normal_exclusions,
        "candidate_broad_stale": (
            stale_count >= CANDIDATE_BROAD_STALE_MIN_COUNT
            and ratio >= CANDIDATE_BROAD_STALE_RATIO
        ),
    }


def _delivery_readiness(
    *,
    market: str,
    status: str,
    session_identity: Any,
    result: Mapping[str, Any],
    data_quality: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate whether this run is a final report or diagnostic-only output.

    This is an operational delivery contract.  It consumes existing session,
    provider, Candidate, and strategy coverage facts and never evaluates a
    Wave, Setup, target, risk, or entry rule.
    """

    run_status = str(data_quality.get("run_status") or status).strip().upper()
    data_status = str(
        data_quality.get("data_status") or data_quality.get("status") or status
    ).strip().upper()
    provider_global_failure = bool(data_quality.get("provider_global_failure"))
    candidate_snapshot = _candidate_readiness_snapshot(result, data_quality, market)
    candidate_status = candidate_snapshot["candidate_status"]
    selection_outcome = candidate_snapshot["selection_outcome"]
    included_count = candidate_snapshot["included_count"]
    dynamic_analysis = candidate_snapshot["dynamic_strategy_analysis_count"]
    if "strategy_analyzed_count" in data_quality:
        strategy_analyzed = _integer_value(data_quality.get("strategy_analyzed_count"))
    else:
        strategy_analyzed = sum(
            1
            for entry in result.get("reports", ())
            if isinstance(entry, Mapping)
            for row in ((entry.get("报告") or {}).get("results") or ())
            if isinstance(row, Mapping) and str(row.get("data_status") or "").upper() == "DATA_OK"
        )
    operationally_complete = data_quality.get("operationally_complete")
    if operationally_complete is None:
        operationally_complete = bool(result.get("reports")) or run_status == "COMPLETED"
    candidate_errors = bool(
        data_quality.get("candidate_runtime_failed")
        or data_quality.get("candidate_quality_errors")
        or candidate_snapshot["candidate"].get("errors")
    )
    formal_attempted = _integer_value(
        data_quality.get(
            "formal_exact_t_attempted_count",
            data_quality.get("attempted_universe"),
        )
    )
    formal_usable = _integer_value(
        data_quality.get(
            "formal_exact_t_usable_count",
            data_quality.get("data_ok_count"),
        )
    )
    candidate_broad_stale = bool(data_quality.get("candidate_broad_stale"))

    def outcome(
        classification: str, reason: str, *, retryable: bool, notify: str,
    ) -> dict[str, Any]:
        return {
            "version": DAILY_REPORT_DELIVERY_READINESS_VERSION,
            "classification": classification,
            "final_report_eligible": classification == FINAL_REPORT_ELIGIBLE,
            "reason": reason,
            "retryable": retryable,
            "notification_mode": notify,
        }

    if status == "SKIPPED_NON_SESSION":
        return outcome(UPSTREAM_NOT_READY, "NON_SESSION", retryable=False, notify="NONE")
    if provider_global_failure or run_status == "PROVIDER_GLOBAL_FAILURE":
        return outcome(DELIVERY_FAILED, "PROVIDER_GLOBAL_FAILURE", retryable=False, notify="ALERT")
    if run_status == "FAILED" or status in {"FAILED", "SESSION_RESOLUTION_ERROR"}:
        return outcome(DELIVERY_FAILED, "REPORT_EXECUTION_FAILED", retryable=False, notify="ALERT")
    if session_identity is None:
        return outcome(UPSTREAM_NOT_READY, "SESSION_NOT_COMPLETED", retryable=True, notify="ALERT")
    if run_status == "COMPLETED_NO_USABLE_SYMBOLS" or data_status == "NO_USABLE_SYMBOLS":
        return outcome(UPSTREAM_NOT_READY, "NO_USABLE_SYMBOLS", retryable=True, notify="ALERT")
    # Dynamic Candidate analysis is not evidence that the formal universe was
    # ready.  A zero-coverage formal universe must remain retryable and can
    # never claim a complete final report.
    if formal_attempted > 0 and formal_usable == 0:
        return outcome(
            UPSTREAM_NOT_READY,
            "FORMAL_EXACT_T_NOT_READY",
            retryable=True,
            notify="ALERT",
        )

    if candidate_status in {"UNAVAILABLE", "NO_USABLE_SYMBOLS", "NOT_RUN", "NOT_REPORTED"}:
        if strategy_analyzed == 0:
            return outcome(
                UPSTREAM_NOT_READY,
                "CANDIDATE_UNAVAILABLE_NO_ANALYSIS",
                retryable=True,
                notify="ALERT",
            )
        return outcome(
            DEGRADED_DIAGNOSTIC_ONLY,
            "CANDIDATE_UNAVAILABLE_FORMAL_ONLY",
            retryable=True,
            notify="ALERT",
        )
    if candidate_status == "NO_CANDIDATES":
        if selection_outcome != "NO_CANDIDATES" or candidate_errors:
            return outcome(
                DEGRADED_DIAGNOSTIC_ONLY,
                "CANDIDATE_DISCOVERY_INCOMPLETE",
                retryable=True,
                notify="ALERT",
            )
        if not operationally_complete:
            return outcome(UPSTREAM_NOT_READY, "REPORT_COVERAGE_NOT_COMPLETE", retryable=True, notify="ALERT")
        return outcome(FINAL_REPORT_ELIGIBLE, "CANDIDATE_STAGE_COMPLETE_NO_CANDIDATES", retryable=False, notify="FINAL")
    if candidate_status not in {"SUCCESS", "PARTIAL"}:
        return outcome(
            DEGRADED_DIAGNOSTIC_ONLY,
            "CANDIDATE_STATUS_UNTRUSTED",
            retryable=True,
            notify="ALERT",
        )
    if candidate_status == "PARTIAL" and included_count == 0:
        return outcome(
            UPSTREAM_NOT_READY if strategy_analyzed == 0 else DEGRADED_DIAGNOSTIC_ONLY,
            "CANDIDATE_COVERAGE_INCOMPLETE",
            retryable=True,
            notify="ALERT",
        )
    if candidate_status == "PARTIAL" and included_count and dynamic_analysis == 0 and strategy_analyzed:
        return outcome(
            DEGRADED_DIAGNOSTIC_ONLY,
            "CANDIDATE_ANALYSIS_NOT_COVERED",
            retryable=True,
            notify="ALERT",
        )
    if candidate_broad_stale:
        return outcome(
            UPSTREAM_NOT_READY,
            "CANDIDATE_EXACT_T_BROADLY_STALE",
            retryable=True,
            notify="ALERT",
        )
    if not operationally_complete:
        return outcome(UPSTREAM_NOT_READY, "REPORT_COVERAGE_NOT_COMPLETE", retryable=True, notify="ALERT")
    if strategy_analyzed == 0:
        return outcome(UPSTREAM_NOT_READY, "NO_STRATEGY_ANALYSIS", retryable=True, notify="ALERT")
    return outcome(FINAL_REPORT_ELIGIBLE, "EXACT_SESSION_AND_ANALYSIS_COVERAGE", retryable=False, notify="FINAL")


def _has_report_signal(result: Mapping[str, Any]) -> bool:
    """Return whether the completed report contains a user-facing signal."""

    for entry in result.get("reports", ()) if isinstance(result.get("reports"), list) else ():
        report = entry.get("报告") if isinstance(entry, Mapping) else {}
        for row in report.get("results", ()) if isinstance(report, Mapping) else ():
            if not isinstance(row, Mapping):
                continue
            if str(row.get("primary_action") or "").upper() in {
                "ENTRY_ALLOWED", "STRATEGY_PROPOSAL"
            }:
                return True
            for decision in row.get("individual_decision_candidates") or ():
                if isinstance(decision, Mapping) and str(decision.get("action") or "").upper() in {
                    "ENTRY_ALLOWED", "STRATEGY_PROPOSAL"
                }:
                    return True
    return False


def _automatic_scheduler_delay(
    provider: ExactExchangeCalendarProvider,
    market: str,
    trade_date: date,
    now: datetime,
) -> bool:
    """Identify a delayed automatic run that crossed into a new session date."""

    try:
        local_date = provider.market_local_date(market, now=now)
        if local_date <= trade_date or not provider.is_session(market, local_date):
            return False
        return provider.latest_completed_session(market, now=now).trade_date == trade_date
    except Exception:
        return False


def _reliability_classification(
    *,
    status: str,
    result: Mapping[str, Any],
    automatic_scheduler_delay: bool = False,
    resolution_error: bool = False,
) -> str:
    if resolution_error:
        return "SESSION_RESOLUTION_ERROR"
    if status == "INCOMPLETE_SESSION":
        return "INCOMPLETE_SESSION"
    if status == "PARTIAL_DATA_QUALITY":
        candidate_values = (
            (result.get("candidate_markets") or {}).values()
            if isinstance(result.get("candidate_markets"), Mapping)
            else ()
        )
        if any(
            isinstance(candidate, Mapping)
            and str(candidate.get("candidate_status") or "").upper() == "UNAVAILABLE"
            for candidate in candidate_values
        ):
            return "CANDIDATE_COMPONENT_UNAVAILABLE"
        return "DATA_QUALITY_PARTIAL"
    if status in {"FAILED", "PROVIDER_GLOBAL_FAILURE"}:
        return "PROVIDER_FAILURE"
    if automatic_scheduler_delay:
        return "SCHEDULER_DELAY"
    if status in {"SUCCESS", "SKIPPED_NON_SESSION"} and not _has_report_signal(result):
        return "NO_SIGNAL"
    return "SUCCESS"


def _cloud_metadata(
    *,
    market: str,
    as_of_date: date,
    generated_at: datetime,
    status: str,
    session_identity: Any,
    ephemeral: Mapping[str, Any],
    data_quality: Mapping[str, Any],
    result: Mapping[str, Any],
    errors: list[str],
    reliability_classification: str | None = None,
    session_resolution: Mapping[str, Any] | None = None,
    legacy_recovery_identity: str | None = None,
    delivery_scope: str = DELIVERY_SCOPE_NATURAL,
) -> dict[str, Any]:
    candidate_markets = result.get("candidate_markets")
    seed_sources = {}
    candidate_as_of = {}
    candidate_seed_as_of = {}
    candidate_diagnostics = {}
    funnel_diagnostics = {}
    protocol_versions: dict[str, str] = {}
    if isinstance(candidate_markets, Mapping):
        candidate = candidate_markets.get(market)
        if isinstance(candidate, Mapping):
            qfq_contract = candidate.get("qfq_contract")
            qfq_contract = qfq_contract if isinstance(qfq_contract, Mapping) else {}
            seed_sources[market] = candidate.get("seed_source") or qfq_contract.get("seed")
            candidate_as_of[market] = candidate.get("as_of_date")
            candidate_seed_as_of[market] = candidate.get("seed_source_as_of")
            candidate_diagnostics[market] = {
                key: candidate.get(key)
                for key in (
                    "seed_count",
                    "candidate_data_qualified_count",
                    "candidate_included_count",
                    "deep_history_requested_count",
                    "deep_history_ready_count",
                    "deep_analysis_count",
                    "deep_analysis_attempted_count",
                    "strategy_analysis_count",
                    "deep_analysis_blocked_symbols",
                    "candidate_selection_outcome",
                    "candidate_status",
                    "universe_snapshot_status",
                    "candidate_exclusion_reason_counts",
                    "deep_history_errors",
                    "stage_timings",
                    "errors",
                    "status",
                )
                if key in candidate
            }
            for entry in result.get("reports", ()) if isinstance(result.get("reports"), list) else ():
                if not isinstance(entry, Mapping) or str(entry.get("市场") or "").upper() != market:
                    continue
                universe = entry.get("universe")
                if not isinstance(universe, Mapping):
                    continue
                scope = universe.get("analysis_scope_counts")
                if isinstance(scope, Mapping):
                    candidate_diagnostics[market]["analysis_scope_counts"] = dict(scope)
                for key in ("candidate_analysis_symbols", "candidate_strategy_analysis_symbols"):
                    if key in universe:
                        candidate_diagnostics[market][key] = list(universe.get(key) or ())
                break
    funnel_values = result.get("funnel")
    if isinstance(funnel_values, Mapping):
        funnel = funnel_values.get(market)
        if isinstance(funnel, Mapping):
            funnel_diagnostics[market] = dict(funnel)
    for entry in result.get("reports", ()) if isinstance(result.get("reports"), list) else ():
        report = entry.get("报告") if isinstance(entry, Mapping) else {}
        values = report.get("protocol_versions") if isinstance(report, Mapping) else {}
        if isinstance(values, Mapping):
            protocol_versions.update({str(key): str(value) for key, value in values.items()})
    metadata_errors = list(errors)
    for key in ("ephemeral_errors", "preflight_errors"):
        metadata_errors.extend(str(value) for value in (data_quality.get(key) or ()) if value)
    candidate_errors = data_quality.get("candidate_runtime_errors")
    if isinstance(candidate_errors, Mapping):
        metadata_errors.extend(str(value) for value in candidate_errors.values() if value)
    metadata_errors.extend(str(value) for value in (data_quality.get("candidate_quality_errors") or ()) if value)
    readiness = _delivery_readiness(
        market=market,
        status=status,
        session_identity=session_identity,
        result=result,
        data_quality=data_quality,
    )
    metadata = {
        "protocol_version": CLOUD_DAILY_REPORT_PROTOCOL_VERSION,
        "market": market,
        "market_label": MARKET_LABELS.get(market, market),
        "as_of_date": as_of_date.isoformat(),
        "git_sha": _git_sha(),
        "generated_at": generated_at.isoformat(),
        "status": status,
        "RUN_STATUS": data_quality.get("run_status", status),
        "DATA_STATUS": data_quality.get("data_status", data_quality.get("status", "UNKNOWN")),
        "CANDIDATE_STATUS": data_quality.get("candidate_status", "NOT_RUN"),
        "run_status": data_quality.get("run_status", status),
        "data_status": data_quality.get("data_status", data_quality.get("status", "UNKNOWN")),
        "candidate_status": data_quality.get("candidate_status", "NOT_RUN"),
        "reliability_classification": reliability_classification or status,
        "delivery_readiness_version": readiness["version"],
        "delivery_readiness": readiness["classification"],
        "final_report_eligible": readiness["final_report_eligible"],
        "delivery_readiness_reason": readiness["reason"],
        "delivery_readiness_retryable": readiness["retryable"],
        "delivery_notification_mode": readiness["notification_mode"],
        "report_data_readiness": readiness["classification"],
        "report_data_ready": readiness["final_report_eligible"],
        "final_delivery_eligibility": (
            FINAL_DELIVERY_PENDING_LEDGER
            if readiness["final_report_eligible"]
            else FINAL_DELIVERY_NOT_ELIGIBLE_REPORT_DATA
        ),
        "final_delivery_eligible": False,
        "report_email_eligible": bool(
            readiness["final_report_eligible"]
            and str(delivery_scope or DELIVERY_SCOPE_NATURAL).upper() == DELIVERY_SCOPE_NATURAL
        ),
        "opportunity_ledger_status": "NOT_RUN",
        "opportunity_ledger_alert_required": False,
        "delivery_scope": str(delivery_scope or DELIVERY_SCOPE_NATURAL).upper(),
        "session_identity": _session_payload(session_identity),
        "session_resolution": dict(session_resolution or {}),
        "calendar_gate": "EXACT_COMPLETED_SESSION" if session_identity is not None else status,
        "data_quality": dict(data_quality),
        "candidate_seed_source": seed_sources,
        "candidate_as_of": candidate_as_of,
        "candidate_seed_as_of": candidate_seed_as_of,
        "candidate_diagnostics": candidate_diagnostics,
        "funnel": funnel_diagnostics,
        "protocol_versions": protocol_versions,
        "input_fingerprint": ephemeral.get("input_fingerprint"),
        "ephemeral_market_data_protocol": ephemeral.get("protocol_version", EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION),
        "provider_status": ephemeral.get("provider_status", {}),
        "artifact_allowlist": list(ARTIFACT_ALLOWLIST),
        "raw_market_data_persisted": False,
        "qfq_persisted": False,
        "state_write": False,
        "sheet_mutation": False,
        "OPPORTUNITY_LEDGER_STATUS": "NOT_RUN",
        "broker_orders": "NONE",
        "errors": list(dict.fromkeys(metadata_errors)),
        "github_run_url": github_run_url(),
    }
    if legacy_recovery_identity:
        metadata["legacy_recovery_identity"] = str(legacy_recovery_identity).strip()
    return metadata


def _known_rejection_gates(decision: Mapping[str, Any] | None, setup: str) -> tuple[list[str], bool]:
    """Project T-known gates; identify when primary-gate order hid geometry."""
    if not isinstance(decision, Mapping):
        return [], False
    if decision.get("action") == "ENTRY_ALLOWED":
        return [], True
    gates: list[str] = []
    entry, upper = decision.get("planned_entry"), decision.get("entry_zone_high")
    targets = decision.get("targets") or []
    if entry is not None and upper is not None and entry > upper:
        gates.append("ABOVE_ENTRY_ZONE")
    if decision.get("gate_reason") == "NO_VALID_TARGET":
        gates.append("NO_VALID_TARGET")
    upside = decision.get("target_upside_pct")
    if upside is not None and upside < MIN_TARGET_UPSIDE_PCT:
        gates.append("TARGET_UPSIDE_BELOW_MINIMUM")
    ratios = (decision.get("rr") or {}).get("rr_ratios") or []
    rr_minimum = SETUP01_MINIMUM_RR if setup == "SETUP_01" else SETUP02_MINIMUM_RR
    if ratios and ratios[0] < rr_minimum:
        gates.append("RR_BELOW_MINIMUM")
    if decision.get("target_reasonableness_passed") is False:
        gates.append("TARGET_PROVENANCE_GEOMETRY")
    primary = str(decision.get("gate_reason") or "")
    if primary and primary != "ENTRY_ALLOWED" and primary not in gates:
        gates.append(primary)
    return sorted(set(gates)), bool(targets and ratios and entry is not None and upper is not None)


def build_prospective_observation(result: Mapping[str, Any], market: str, trade_date: date) -> dict[str, Any]:
    """Compact read-only projection of the already evaluated natural report."""
    target_t = trade_date.isoformat()
    candidate = (result.get("candidate_markets") or {}).get(market) or {}
    records: dict[str, dict[str, Any]] = {}
    variants: set[str] = set()
    formal: set[str] = set()
    dynamic: set[str] = set()
    for entry in sorted(result.get("reports") or [], key=lambda item: str(item.get("账户ID") or "")):
        if not isinstance(entry, Mapping) or entry.get("市场") != market:
            continue
        universe = entry.get("universe") or {}
        formal.update(str(value).upper() for value in universe.get("formal_strategy_pool") or [])
        dynamic.update(str(value).upper() for value in universe.get("dynamic_candidate_set") or [])
        for row in (entry.get("报告") or {}).get("results") or []:
            symbol = str(row.get("symbol") or "").upper()
            if symbol:
                prior = records.get(symbol)
                if prior is None:
                    records[symbol] = row
                elif any(prior.get(key) != row.get(key) for key in (
                    "as_of_date", "data_status", "weekly_state", "daily_state",
                    "setup01_state", "setup02_state", "new_confirmed_event_identities"
                )):
                    variants.add(symbol)
    candidate_records = {
        str(row.get("symbol") or "").upper(): row
        for row in candidate.get("candidate_records") or []
        if isinstance(row, Mapping) and row.get("included")
    }
    requested = set(candidate.get("deep_history_requested_symbols") or [])
    ready = set(candidate.get("deep_history_ready_symbols") or [])
    observations = []
    for symbol in sorted(formal | dynamic):
        row = records.get(symbol) or {}
        if symbol in variants:
            row = {"as_of_date": target_t, "data_status": "ACCOUNT_VARIANT_UNKNOWN"}
        is_formal, is_dynamic = symbol in formal, symbol in dynamic
        bucket = "OVERLAP" if is_formal and is_dynamic else "FORMAL_ONLY" if is_formal else "DYNAMIC_ONLY"
        candidate_row = candidate_records.get(symbol) or {}
        identities = set(row.get("new_confirmed_event_identities") or [])
        decisions = {
            str(item.get("event_identity")): item
            for item in row.get("individual_decision_candidates") or []
            if isinstance(item, Mapping) and item.get("event_identity")
        }
        for setup, state_key in (("SETUP_01", "setup01_state"), ("SETUP_02", "setup02_state")):
            event_identity = next((item for item in sorted(identities)
                                   if f"|{setup}|" in item or item.startswith(f"{setup}|")), None)
            decision = decisions.get(event_identity) if event_identity else None
            gates, complete = _known_rejection_gates(decision, setup)
            missing = []
            if not row:
                missing.append("MISSING_DAILY_RESULT")
            if symbol in variants:
                missing.append("CONFLICTING_ACCOUNT_OBSERVATIONS")
            elif row.get("as_of_date") != target_t:
                missing.append("ROW_NOT_EXACT_T")
            if event_identity and decision is None:
                missing.append("FIRST_EVENT_DECISION_UNAVAILABLE")
            elif event_identity and not complete and decision and decision.get("action") != "ENTRY_ALLOWED":
                missing.append("ALL_FAIL_GEOMETRY_NOT_EVALUATED")
            if row and row.get("data_status") != "DATA_OK":
                missing.append("DATA_NOT_OK")
            observations.append({
                "identity": f"{market}|{target_t}|{symbol}|{setup}",
                "market": market, "T": target_t, "symbol": symbol, "setup": setup,
                "formal_pool": is_formal, "dynamic_candidate": is_dynamic,
                "provenance_bucket": bucket,
                "stage_a_qualified": bool(candidate_row.get("included")) if is_dynamic else None,
                "stage_a_history_bars": candidate_row.get("history_bar_count") if is_dynamic else None,
                "stage_a_tail_date": candidate_row.get("latest_history_date") if is_dynamic else None,
                "stage_b": ("READY" if symbol in ready else "REQUESTED_NOT_READY" if symbol in requested
                            else "REUSED_FORMAL" if is_dynamic and is_formal else "UNKNOWN") if is_dynamic else "NOT_APPLICABLE",
                "data_status": row.get("data_status") if row else "MISSING_DAILY_RESULT",
                "exact_t_data": (row.get("as_of_date") == target_t and row.get("data_status") == "DATA_OK") if row else None,
                "data_reasons": row.get("reasons") if row else None,
                "weekly_state": row.get("weekly_state"), "daily_state": row.get("daily_state"),
                "setup_state": row.get(state_key),
                "first_confirmed": bool(event_identity), "event_identity": event_identity,
                "decision_action": decision.get("action") if decision else None,
                "primary_rejection": (decision.get("gate_reason") if decision and decision.get("action") != "ENTRY_ALLOWED" else None),
                "all_fail_known": gates, "all_fail_complete": complete if event_identity else None,
                "geometry": ({key: decision.get(key) for key in (
                    "planned_entry", "entry_zone_low", "entry_zone_high", "T1", "structural_invalidation",
                    "execution_stop", "target_upside_pct", "atr14")}
                    | {"t1_source": next((target.get("source") for target in decision.get("target_candidates") or []
                                           if target.get("price") == decision.get("T1")), None),
                       "t1_rr": next(iter((decision.get("rr") or {}).get("rr_ratios") or []), None)}
                    if decision else None),
                "missing_reasons": missing,
            })
    return {
        "protocol_version": PROSPECTIVE_FUNNEL_PROTOCOL_VERSION,
        "market": market, "T": target_t, "source_run_url": github_run_url(),
        "seed_source_as_of": candidate.get("seed_source_as_of"),
        "seed": candidate.get("seed_count"),
        "stage_a_qualified": candidate.get("candidate_data_qualified_count"),
        "included": candidate.get("candidate_included_count"),
        "stage_b_requested": candidate.get("deep_history_requested_count"),
        "stage_b_ready": candidate.get("deep_history_ready_count"),
        "formal_symbols": len(formal), "dynamic_symbols": len(dynamic),
        "formal_only_symbols": len(formal - dynamic), "dynamic_only_symbols": len(dynamic - formal),
        "overlap_symbols": len(formal & dynamic),
        "union_symbols": len(formal | dynamic),
        "observation_count": len(observations),
        "data_ok_symbols": sum(symbol not in variants and records.get(symbol, {}).get("data_status") == "DATA_OK"
                               for symbol in formal | dynamic),
        "data_blocked_symbols": sum(symbol not in variants and bool(records.get(symbol, {}).get("data_status")) and
                                    records[symbol]["data_status"] != "DATA_OK" for symbol in formal | dynamic),
        "account_variant_symbols": len(variants),
        "missing_daily_result_symbols": sum(symbol not in records for symbol in formal | dynamic),
        "first_event_count": sum(item["first_confirmed"] for item in observations),
        "decision_count": sum(item["first_confirmed"] and item["decision_action"] is not None for item in observations),
        "daily_state_counts": {
            setup: {state: sum(item["setup"] == setup and item["setup_state"] == state for item in observations)
                    for state in ("WATCH", "ARMED", "CONFIRMED")}
            for setup in ("SETUP_01", "SETUP_02")
        },
        "observations": observations,
    }


def _notification_text(payload: Mapping[str, Any]) -> tuple[str, str]:
    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or "").upper()
    label = MARKET_LABELS.get(market, market or "市场")
    status = str(cloud.get("status") or "FAILED")
    run_status = str(cloud.get("run_status") or cloud.get("RUN_STATUS") or status)
    data_status = str(cloud.get("data_status") or cloud.get("DATA_STATUS") or "UNKNOWN")
    candidate_status = str(
        cloud.get("candidate_status") or cloud.get("CANDIDATE_STATUS") or "NOT_RUN"
    )
    readiness = str(cloud.get("delivery_readiness") or "").strip().upper()
    readiness_reason = str(cloud.get("delivery_readiness_reason") or "").strip()
    projection = build_dashboard_projection(payload)
    summary = projection.get("summary", {})
    freshness = projection.get("freshness_funnel", {})
    plan_count = int(summary.get("strategy_proposal_count", 0) or 0) + int(
        summary.get("entry_allowed_count", 0) or 0
    )
    if readiness and readiness != FINAL_REPORT_ELIGIBLE:
        quality = cloud.get("data_quality") or {}
        failed = quality.get("failed_symbols") or []
        retryable = "是" if cloud.get("delivery_readiness_retryable") else "否"
        readiness_copy = {
            UPSTREAM_NOT_READY: "数据仍未准备完成",
            DEGRADED_DIAGNOSTIC_ONLY: "本次仅生成诊断信息",
            DELIVERY_FAILED: "日报运行异常",
        }
        reason_copy = {
            "SESSION_NOT_COMPLETED": "交易时段尚未完成",
            "NO_USABLE_SYMBOLS": "当前没有可用标的数据",
            "CANDIDATE_UNAVAILABLE_NO_ANALYSIS": "候选数据不可用且没有完成策略分析",
            "CANDIDATE_UNAVAILABLE_FORMAL_ONLY": "候选数据不可用，但已有正式标的完成分析",
            "CANDIDATE_COVERAGE_INCOMPLETE": "候选数据覆盖未完成",
            "CANDIDATE_EXACT_T_BROADLY_STALE": "候选数据大范围落后于报告日期",
            "FORMAL_EXACT_T_NOT_READY": "正式标的尚未覆盖报告日期",
            "REPORT_COVERAGE_NOT_COMPLETE": "日报分析覆盖未完成",
            "NO_STRATEGY_ANALYSIS": "尚未完成策略分析",
            "PROVIDER_GLOBAL_FAILURE": "行情数据服务出现全局异常",
            "REPORT_EXECUTION_FAILED": "日报运行出现异常",
        }
        title = (
            f"{label}日报等待数据"
            if readiness == UPSTREAM_NOT_READY
            else f"{label}日报仅诊断"
            if readiness == DEGRADED_DIAGNOSTIC_ONLY
            else f"{label}日报异常"
        )
        body = (
            f"市场：{label}\n"
            f"数据日期：{projection.get('as_of_date', '—')}\n"
            f"日报状态：{readiness_copy.get(readiness, '日报运行异常')}\n"
            f"原因：{reason_copy.get(readiness_reason, '暂时无法评估')}\n"
            f"策略分析：{quality.get('strategy_analyzed_count', '—')}；异常标的：{', '.join(failed[:20]) or '无'}\n"
            f"允许后续重试：{retryable}\n"
            "本次未形成可发送的正式交易日报。"
        )
        run_url = cloud.get("github_run_url")
        if run_url:
            body += f"\n查看本次运行：{run_url}"
        return title, body
    if run_status in {"COMPLETED", "COMPLETED_NO_USABLE_SYMBOLS"}:
        failed = ((cloud.get("data_quality") or {}).get("failed_symbols") or [])
        quality = cloud.get("data_quality") or {}
        attempted = quality.get("attempted_universe", "—")
        data_ok = quality.get("data_ok_count", "—")
        failed_count = quality.get("failed_count", "—")
        analyzed = quality.get("strategy_analyzed_count", "—")
        blocked = quality.get("blocked_count", "—")
        reasons = quality.get("failed_by_reason") or {}
        reason_text = "、".join(
            f"{len(values) if isinstance(values, (list, tuple, set)) else 1}项"
            for key, values in sorted(reasons.items())
            if key
        ) or "无"
        title = f"{label}日报完成" if run_status == "COMPLETED" else f"{label}日报完成但无可用标的"
        body = (
            f"市场：{label}\n"
            f"数据日期：{projection.get('as_of_date', '—')}\n"
            "日报状态：已完成\n"
            f"尝试标的：{attempted}；数据正常：{data_ok}；异常：{failed_count}\n"
            f"覆盖率：{(cloud.get('data_quality') or {}).get('coverage_pct', '—')}%\n"
            f"策略分析：{analyzed}；数据阻断：{blocked}\n"
            f"失败原因：{reason_text}\n"
            f"异常标的：{', '.join(failed[:20]) or '无'}\n"
            f"新确认：{summary.get('new_confirmed_count', 0)}\n"
            f"交易方案：{plan_count}\n"
            + (
                "候选发现组件本轮不可用；已有正式标的仍正常完成分析。"
                if candidate_status == "UNAVAILABLE"
                else "有效数据标的继续完成策略分析；异常标的仅本标的阻断。"
            )
        )
    elif status in {"SUCCESS", "SKIPPED_NON_SESSION"}:
        title = f"{label}日报完成"
        body = (
            f"市场：{label}\n"
            f"数据日期：{projection.get('as_of_date', '—')}\n"
            "数据状态：已完成\n"
            f"新确认：{summary.get('new_confirmed_count', 0)}\n"
            f"等待确认：{summary.get('armed_count', 0)}\n"
            f"交易方案：{plan_count}\n"
            f"策略跟踪持仓：{summary.get('position_count', 0)}\n"
            f"数据异常：{summary.get('data_blocked_count', 0)}\n"
            f"目标空间不足：{freshness.get('target_upside_below_minimum_count', 0) if isinstance(freshness, Mapping) else 0}"
        )
    else:
        failed = ((cloud.get("data_quality") or {}).get("failed_symbols") or [])
        title = f"{label}日报异常"
        body = (
            f"数据日期：{projection.get('as_of_date', '—')}\n"
            "状态：日报运行异常\n"
            f"异常标的：{', '.join(failed) or '无可用标的'}\n"
            "本日不生成新的交易信号。"
        )
    run_url = cloud.get("github_run_url")
    if str(cloud.get("OPPORTUNITY_LEDGER_STATUS") or "").upper() in {
        "FAILED", "MISSED_PROSPECTIVE_SESSION",
    } and readiness == FINAL_REPORT_ELIGIBLE:
        title += "（机会账本写入失败）"
        body += "\n日报已正常生成，可正常使用；机会观察账本写入失败，不影响本日报的行情和策略判断。"
    if run_url:
        body += f"\n查看本次运行：{run_url}"
    return title, body


def _ledger_alert_text(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Return the Bark-only message for a final report ledger failure."""

    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or payload.get("market") or "").upper()
    label = MARKET_LABELS.get(market, market or "市场")
    trade_date = str(cloud.get("as_of_date") or payload.get("as_of_date") or "—")
    error = str(cloud.get("opportunity_ledger_error") or "未提供").strip()
    title = f"{label}机会账本写入失败"
    body = (
        f"市场：{label}\n"
        f"数据日期：{trade_date}\n"
        "日报已正常生成，可正常使用；机会观察账本写入失败，不影响本日报的行情和策略判断。\n"
        f"简要错误：{error}"
    )
    run_url = cloud.get("github_run_url")
    if run_url:
        body += f"\n查看本次运行：{run_url}"
    return title, body


def _email_failure_alert_text(payload: Mapping[str, Any]) -> tuple[str, str]:
    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or payload.get("market") or "").upper()
    label = MARKET_LABELS.get(market, market or "市场")
    trade_date = str(cloud.get("as_of_date") or payload.get("as_of_date") or "—")
    notifications = cloud.get("notifications") if isinstance(cloud.get("notifications"), Mapping) else {}
    email_result = notifications.get("email") if isinstance(notifications.get("email"), Mapping) else {}
    error = str(email_result.get("error") or "未提供").strip()
    title = f"{label}日报已生成，但邮件发送失败"
    body = (
        f"市场：{label}\n"
        f"数据日期：{trade_date}\n"
        "今日正式日报已生成，但邮件发送失败；请查看日报文件。\n"
        f"简要错误：{error}"
    )
    run_url = cloud.get("github_run_url")
    if run_url:
        body += f"\n查看本次运行：{run_url}"
    return title, body


def _write_artifacts(
    payload: Mapping[str, Any],
    output_dir: str | Path,
    *,
    dashboard_html: str | None = None,
) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "daily-report.json"
    html_path = target / "daily-report.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    html_path.write_text(
        dashboard_html if dashboard_html is not None else render_dashboard_html(payload),
        encoding="utf-8",
    )
    return json_path, html_path


def _notification_attachment_filename(payload: Mapping[str, Any]) -> str:
    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or payload.get("market") or "").strip().upper()
    label = MARKET_LABELS.get(market, market or "市场")
    trade_date = str(cloud.get("as_of_date") or payload.get("as_of_date") or "unknown").strip()
    return f"{label}交易日报_{trade_date}.html"


def _finalize_delivery_eligibility(
    payload: dict[str, Any], opportunity_status: str,
) -> None:
    """Finalize independent report-email and ledger-alert eligibility."""

    cloud = payload.get("cloud_daily_report")
    if not isinstance(cloud, dict):
        return
    readiness = str(cloud.get("report_data_readiness") or cloud.get("delivery_readiness") or "").upper()
    scope = str(cloud.get("delivery_scope") or DELIVERY_SCOPE_NATURAL).upper()
    ledger_failed = opportunity_status in {"FAILED", "MISSED_PROSPECTIVE_SESSION"}
    if readiness != FINAL_REPORT_ELIGIBLE:
        eligibility = FINAL_DELIVERY_NOT_ELIGIBLE_REPORT_DATA
        reason = "REPORT_DATA_NOT_FINAL_READY"
    elif scope == DELIVERY_SCOPE_DIAGNOSTIC:
        eligibility = FINAL_DELIVERY_NOT_APPLICABLE_DIAGNOSTIC
        reason = "DIAGNOSTIC_SCOPE"
    else:
        eligibility = FINAL_DELIVERY_ELIGIBLE
        reason = "REPORT_DATA_READY_LEDGER_FAILED" if ledger_failed else "REPORT_DATA_AND_LEDGER_READY"
    cloud["final_delivery_eligibility"] = eligibility
    cloud["final_delivery_eligible"] = (
        eligibility == FINAL_DELIVERY_ELIGIBLE
        and scope == DELIVERY_SCOPE_NATURAL
    )
    cloud["report_email_eligible"] = (
        readiness == FINAL_REPORT_ELIGIBLE
        and scope == DELIVERY_SCOPE_NATURAL
    )
    cloud["opportunity_ledger_status"] = opportunity_status
    cloud["opportunity_ledger_alert_required"] = (
        ledger_failed
        and readiness == FINAL_REPORT_ELIGIBLE
        and scope == DELIVERY_SCOPE_NATURAL
    )
    cloud["final_delivery_reason"] = reason
    if readiness == FINAL_REPORT_ELIGIBLE and scope == DELIVERY_SCOPE_NATURAL:
        cloud["delivery_notification_mode"] = (
            "FINAL_WITH_LEDGER_ERROR" if ledger_failed else "FINAL"
        )
    elif scope == DELIVERY_SCOPE_DIAGNOSTIC:
        cloud["delivery_notification_mode"] = "NONE"
    else:
        cloud["delivery_notification_mode"] = "ALERT"


def _claim_with_store(claim_function, payload, marker_store):
    if marker_store is None:
        return claim_function(payload)
    return claim_function(payload, store=marker_store)


def _not_sent(status: str, *, configured: bool = False) -> dict[str, Any]:
    return {"status": status, "configured": configured}


def _notify(
    payload: dict[str, Any], *, dashboard_html: str,
    marker_store: Any | None = None,
) -> None:
    """Route one terminal payload according to the report/ledger contract."""

    cloud = payload.setdefault("cloud_daily_report", {})
    if not isinstance(cloud, dict):
        return
    try:
        readiness = str(
            cloud.get("report_data_readiness") or cloud.get("delivery_readiness") or ""
        ).strip().upper()
        scope = str(cloud.get("delivery_scope") or DELIVERY_SCOPE_NATURAL).strip().upper()
        if (
            scope == DELIVERY_SCOPE_DIAGNOSTIC
            or str(cloud.get("status") or "").strip().upper()
            in {"SKIPPED_NON_SESSION", "READ_ONLY_VALIDATION_REPLAY"}
            or str(cloud.get("delivery_readiness_reason") or "").strip().upper()
            == "NON_SESSION"
        ):
            cloud["notifications"] = {
                "routing": "NO_NOTIFICATION",
                "bark": _not_sent("NOT_SENT_NON_SESSION"),
                "email": _not_sent("NOT_SENT_NON_SESSION"),
            }
            return
        ledger_failed = str(
            cloud.get("OPPORTUNITY_LEDGER_STATUS") or cloud.get("opportunity_ledger_status") or ""
        ).strip().upper() in {"FAILED", "MISSED_PROSPECTIVE_SESSION"}

        if readiness in {"", FINAL_REPORT_ELIGIBLE}:
            report_claim = _claim_with_store(
                claim_report_notification, payload, marker_store,
            )
            cloud["notification_idempotency"] = report_claim
            final_status = str(report_claim.get("status") or "")
            can_send_email = final_status in {"CLAIMED", "NOT_CONFIGURED"}
            if final_status == "IDEMPOTENCY_UNAVAILABLE":
                can_send_email = False
            email = _not_sent(
                final_status or "NOT_SENT_FINAL_MARKER_NOT_CLAIMED",
                configured=bool(report_claim.get("configured")),
            )
            bark = _not_sent("NOT_SENT_FINAL_REPORT_EMAIL_ONLY")
            ledger_claim = None
            ledger_bark = _not_sent("NOT_SENT_LEDGER_ALERT_NOT_REQUIRED")
            if ledger_failed:
                ledger_claim = _claim_with_store(
                    claim_ledger_error_alert, payload, marker_store,
                )
                cloud["ledger_notification_idempotency"] = ledger_claim
                if ledger_claim.get("status") in {"CLAIMED", "NOT_CONFIGURED"}:
                    ledger_title, ledger_body = _ledger_alert_text(payload)
                    ledger_bark = send_bark(
                        os.environ.get("BARK_ENDPOINT", ""),
                        title=ledger_title,
                        body=ledger_body,
                        url=cloud.get("github_run_url"),
                    )
                    if ledger_bark.get("status") == "FAILED":
                        cloud["bark_delivery_status"] = BARK_DELIVERY_FAILED
            if can_send_email:
                title, body = _notification_text(payload)
                email = send_optional_email(
                    subject=title,
                    body=body,
                    html_body=render_daily_report_email_html(payload),
                    html_attachment=dashboard_html,
                    attachment_filename=_notification_attachment_filename(payload),
                )
                if email.get("status") == "FAILED":
                    # Make the terminal SMTP result available to the alert
                    # formatter before the final notification envelope is
                    # assembled below.
                    cloud["notifications"] = {"email": email}
                    cloud["email_delivery_status"] = EMAIL_DELIVERY_FAILED
                    failure_claim = _claim_with_store(
                        claim_email_delivery_failure_alert, payload, marker_store,
                    )
                    cloud["email_failure_notification_idempotency"] = failure_claim
                    if failure_claim.get("status") in {"CLAIMED", "NOT_CONFIGURED"}:
                        title, body = _email_failure_alert_text(payload)
                        failure_bark = send_bark(
                            os.environ.get("BARK_ENDPOINT", ""),
                            title=title,
                            body=body,
                            url=cloud.get("github_run_url"),
                        )
                        if failure_bark.get("status") == "FAILED":
                            cloud["bark_delivery_status"] = BARK_DELIVERY_FAILED
                        cloud["email_failure_bark"] = failure_bark
            elif final_status == "IDEMPOTENCY_UNAVAILABLE":
                cloud["email_delivery_status"] = "NOT_SENT_IDEMPOTENCY_UNAVAILABLE"
            cloud["notifications"] = {
                "routing": "FINAL_REPORT_WITH_LEDGER_ERROR" if ledger_failed else "FINAL_REPORT_ONLY",
                "kind": "FINAL_REPORT",
                "bark": ledger_bark if ledger_failed else bark,
                "email": email,
                "ledger_alert": {
                    "claim": ledger_claim,
                    "bark": ledger_bark,
                } if ledger_failed else None,
            }
            return

        alert_claim = _claim_with_store(claim_report_notification, payload, marker_store)
        cloud["notification_idempotency"] = alert_claim
        bark = _not_sent(
            "NOT_SENT_ERROR_MARKER_NOT_CLAIMED",
            configured=bool(alert_claim.get("configured")),
        )
        if alert_claim.get("status") in {"CLAIMED", "NOT_CONFIGURED"}:
            title, body = _notification_text(payload)
            bark = send_bark(
                os.environ.get("BARK_ENDPOINT", ""),
                title=title,
                body=body,
                url=cloud.get("github_run_url"),
            )
            if bark.get("status") == "FAILED":
                cloud["bark_delivery_status"] = BARK_DELIVERY_FAILED
        cloud["notifications"] = {
            "routing": "ERROR_ALERT_ONLY",
            "kind": "DEGRADED_ALERT",
            "bark": bark,
            "email": _not_sent("NOT_SENT_ERROR_BARK_ONLY"),
        }
    except Exception as exc:
        cloud["notifications"] = {
            "routing": "ERROR_ALERT_ONLY",
            "bark": {"status": "FAILED", "configured": bool(os.environ.get("BARK_ENDPOINT")), "error": _error_text(exc)},
            "email": _not_sent("NOT_RUN", configured=False),
        }


def _write_and_notify(
    payload: dict[str, Any], output_dir: str | Path, *, notify: bool,
    marker_store: Any | None = None,
) -> None:
    _, html_path = _write_artifacts(payload, output_dir)
    if not notify or (payload.get("cloud_daily_report") or {}).get("status") == FINAL_SESSION_ALREADY_COMPLETED:
        return
    dashboard_html = html_path.read_text(encoding="utf-8")
    _notify(payload, dashboard_html=dashboard_html, marker_store=marker_store)
    # Keep the final artifact byte-identical to the attachment even though the
    # JSON receives notification metadata after delivery.
    _write_artifacts(payload, output_dir, dashboard_html=dashboard_html)


def _finality_noop_payload(
    *, market: str, as_of_date: date, generated_at: datetime,
    output_dir: str | Path, finality: Mapping[str, Any],
    delivery_scope: str,
) -> dict[str, Any]:
    result = _empty_result(as_of_date, FINAL_SESSION_ALREADY_COMPLETED, [])
    result["market"] = market
    result["preflight"]["production readiness"] = FINAL_SESSION_ALREADY_COMPLETED
    result["finality_preflight"] = dict(finality)
    metadata = _cloud_metadata(
        market=market,
        as_of_date=as_of_date,
        generated_at=generated_at,
        status=FINAL_SESSION_ALREADY_COMPLETED,
        session_identity=None,
        ephemeral={
            "protocol_version": EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION,
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "input_fingerprint": None,
            "provider_status": {},
        },
        data_quality={
            "status": FINAL_SESSION_ALREADY_COMPLETED,
            "run_status": FINAL_SESSION_ALREADY_COMPLETED,
            "data_status": "NOT_RUN_FINAL_SESSION_ALREADY_COMPLETED",
            "failed_symbols": [],
            "ephemeral_errors": [],
        },
        result=result,
        errors=[],
        reliability_classification=FINAL_SESSION_ALREADY_COMPLETED,
        delivery_scope=delivery_scope,
    )
    metadata.update({
        "status": FINAL_SESSION_ALREADY_COMPLETED,
        "RUN_STATUS": FINAL_SESSION_ALREADY_COMPLETED,
        "run_status": FINAL_SESSION_ALREADY_COMPLETED,
        "DATA_STATUS": "NOT_RUN_FINAL_SESSION_ALREADY_COMPLETED",
        "data_status": "NOT_RUN_FINAL_SESSION_ALREADY_COMPLETED",
        "delivery_readiness": FINAL_SESSION_ALREADY_COMPLETED,
        "report_data_readiness": FINAL_SESSION_ALREADY_COMPLETED,
        "final_report_eligible": False,
        "delivery_readiness_reason": "FINAL_REPORT_ALREADY_COMPLETED",
        "delivery_readiness_retryable": False,
        "delivery_notification_mode": "NONE",
        "final_delivery_eligibility": FINAL_DELIVERY_ALREADY_COMPLETED,
        "final_delivery_eligible": False,
        "report_email_eligible": False,
        "opportunity_ledger_status": "NOT_RUN",
        "OPPORTUNITY_LEDGER_STATUS": "NOT_RUN",
        "opportunity_ledger_alert_required": False,
        "finality_preflight": dict(finality),
        "errors": [],
        "notifications": {
            "routing": "NO_NOTIFICATION",
            "bark": _not_sent(FINAL_SESSION_ALREADY_COMPLETED),
            "email": _not_sent(FINAL_SESSION_ALREADY_COMPLETED),
        },
    })
    payload = {
        **result,
        "market": market,
        "as_of_date": as_of_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "finality_preflight": dict(finality),
        "opportunity_tracking": {
            "status": FINAL_SESSION_ALREADY_COMPLETED,
            "error": None,
            "writes_performed": False,
        },
        "cloud_daily_report": metadata,
    }
    _write_artifacts(payload, output_dir)
    return payload


def _finality_preflight_failure_payload(
    *, market: str, as_of_date: date, generated_at: datetime,
    output_dir: str | Path, finality: Mapping[str, Any],
    delivery_scope: str,
) -> dict[str, Any]:
    error = f"FINALITY_PREFLIGHT_{finality.get('status', 'UNAVAILABLE')}"
    result = _empty_result(as_of_date, "FAILED", [error])
    result["market"] = market
    result["preflight"]["production readiness"] = "FAILED"
    result["finality_preflight"] = dict(finality)
    metadata = _cloud_metadata(
        market=market,
        as_of_date=as_of_date,
        generated_at=generated_at,
        status="FAILED",
        session_identity=None,
        ephemeral={"provider_status": {}, "input_fingerprint": None},
        data_quality={"status": "FAILED", "run_status": "FAILED", "failed_symbols": [], "ephemeral_errors": [error]},
        result=result,
        errors=[error],
        reliability_classification="FINALITY_PREFLIGHT_UNAVAILABLE",
        delivery_scope=delivery_scope,
    )
    metadata.update({
        "delivery_readiness": DELIVERY_FAILED,
        "report_data_readiness": DELIVERY_FAILED,
        "delivery_notification_mode": "NONE",
        "report_email_eligible": False,
        "finality_preflight": dict(finality),
    })
    payload = {
        **result,
        "market": market,
        "as_of_date": as_of_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "finality_preflight": dict(finality),
        "cloud_daily_report": metadata,
    }
    _write_artifacts(payload, output_dir)
    return payload


def run_cloud_daily_report(
    *,
    market: str,
    as_of_date: date,
    output_dir: str | Path,
    now: datetime | None = None,
    client: Any | None = None,
    calendar_provider: ExactExchangeCalendarProvider | None = None,
    notify: bool = True,
    automatic_resolution: bool = False,
    legacy_recovery_identity: str | None = None,
    delivery_scope: str = DELIVERY_SCOPE_NATURAL,
    marker_store: Any | None = None,
) -> dict[str, Any]:
    """Run and persist exactly one market/T report."""

    normalized_market = str(market).strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError(f"unsupported cloud market: {normalized_market}")
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("cloud report requires timezone-aware now")
    provider = calendar_provider or ExactExchangeCalendarProvider()
    scheduler_delay = False
    session_resolution: dict[str, Any] = {}

    normalized_scope = str(delivery_scope or DELIVERY_SCOPE_NATURAL).strip().upper()
    if (
        automatic_resolution
        and normalized_scope == DELIVERY_SCOPE_NATURAL
        and not str(legacy_recovery_identity or "").strip()
    ):
        marker_context = {
            "market": normalized_market,
            "as_of_date": as_of_date.isoformat(),
            "cloud_daily_report": {
                "market": normalized_market,
                "as_of_date": as_of_date.isoformat(),
                "protocol_version": CLOUD_DAILY_REPORT_PROTOCOL_VERSION,
                "delivery_scope": normalized_scope,
            },
        }
        finality = final_report_session_status(marker_context, store=marker_store)
        if finality.get("status") == FINAL_SESSION_ALREADY_COMPLETED:
            return _finality_noop_payload(
                market=normalized_market,
                as_of_date=as_of_date,
                generated_at=generated_at,
                output_dir=output_dir,
                finality=finality,
                delivery_scope=normalized_scope,
            )
        if finality.get("status") in {"IDEMPOTENCY_UNAVAILABLE", "FINAL_MARKER_INVALID"}:
            return _finality_preflight_failure_payload(
                market=normalized_market,
                as_of_date=as_of_date,
                generated_at=generated_at,
                output_dir=output_dir,
                finality=finality,
                delivery_scope=normalized_scope,
            )

    try:
        is_session = provider.is_session(normalized_market, as_of_date)
    except Exception as exc:
        error = _error_text(exc)
        result = _empty_result(as_of_date, "FAILED", [error])
        payload = {
            **result,
            "market": normalized_market,
            "as_of_date": as_of_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "cloud_daily_report": _cloud_metadata(
                market=normalized_market, as_of_date=as_of_date, generated_at=generated_at,
                status="FAILED", session_identity=None,
                ephemeral={"provider_status": {}, "input_fingerprint": None},
                data_quality={"status": "FAILED", "failed_symbols": [], "ephemeral_errors": [error]},
                result=result, errors=[error],
                reliability_classification="SESSION_RESOLUTION_ERROR",
                delivery_scope=normalized_scope,
            ),
        }
        _write_and_notify(payload, output_dir, notify=notify, marker_store=marker_store)
        return payload

    if not is_session:
        result = _empty_result(as_of_date, "SKIPPED_NON_SESSION", [])
        ephemeral_meta = {
            "protocol_version": EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION,
            "market": normalized_market,
            "as_of_date": as_of_date.isoformat(),
            "input_fingerprint": None,
            "provider_status": {},
        }
        quality = {"status": "SKIPPED_NON_SESSION", "counts": {}, "failed_symbols": [], "ephemeral_errors": []}
        payload = {
            **result,
            "market": normalized_market,
            "as_of_date": as_of_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "cloud_daily_report": _cloud_metadata(
                market=normalized_market, as_of_date=as_of_date, generated_at=generated_at,
                status="SKIPPED_NON_SESSION", session_identity=None,
                ephemeral=ephemeral_meta, data_quality=quality, result=result, errors=[],
                reliability_classification="SKIPPED_NON_SESSION",
                delivery_scope=normalized_scope,
            ),
        }
        _write_and_notify(payload, output_dir, notify=notify, marker_store=marker_store)
        return payload

    try:
        session_identity = provider.completed_session(normalized_market, as_of_date, now=generated_at)
        session_resolution = provider.completed_session_window(
            normalized_market, as_of_date, now=generated_at
        ).as_dict()
        scheduler_delay = automatic_resolution and _automatic_scheduler_delay(
            provider, normalized_market, as_of_date, generated_at
        )
    except Exception as exc:
        error = _error_text(exc)
        session_status = (
            "INCOMPLETE_SESSION"
            if error == "COMPLETED_SESSION_REQUIRED"
            else "FAILED"
        )
        result = _empty_result(as_of_date, session_status, [error])
        payload = {
            **result,
            "market": normalized_market,
            "as_of_date": as_of_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "cloud_daily_report": _cloud_metadata(
                market=normalized_market, as_of_date=as_of_date, generated_at=generated_at,
                status=session_status, session_identity=None,
                ephemeral={"provider_status": {}, "input_fingerprint": None},
                data_quality={"status": session_status, "failed_symbols": [], "ephemeral_errors": [error]},
                result=result, errors=[error],
                reliability_classification=_reliability_classification(
                    status=session_status,
                    result=result,
                    resolution_error=session_status == "FAILED",
                ),
                delivery_scope=normalized_scope,
            ),
        }
        _write_and_notify(payload, output_dir, notify=notify, marker_store=marker_store)
        return payload

    errors: list[str] = []
    report_status = "FAILED"
    observation_inputs: list = []
    opportunity_status = "NOT_ENABLED_FOR_DIAGNOSTIC"
    opportunity_error = None
    opportunity_write_attempted = False
    runtime = ProductionCandidateRuntime()
    sheets = None
    try:
        sheets = client if client is not None else SheetsClient()
        ephemeral = load_ephemeral_market_data(
            sheets, market=normalized_market, as_of_date=as_of_date, now=generated_at
        )
        result = run_production_daily_decision(
            sheets,
            as_of_date=as_of_date,
            preflight=False,
            write_state=False,
            now=generated_at,
            market=normalized_market,
            ephemeral_latest_rows=ephemeral.latest_rows,
            ephemeral_qfq_rows=ephemeral.qfq_rows,
            ephemeral_errors={
                f"{normalized_market}|{symbol}": "；".join(item.get("errors", ()))
                for symbol, item in ephemeral.symbol_status.items()
                if item.get("errors")
            },
            paper_active_symbols={normalized_market: ephemeral.active_paper_symbols},
            candidate_runtime=runtime,
            allow_no_runnable_account=True,
            observation_inputs=observation_inputs,
        )
        report_status, quality = _status_from_result(result, ephemeral)
        ephemeral_meta = ephemeral.to_dict()
    except Exception as exc:
        error = _error_text(exc)
        errors.append(error)
        result = _empty_result(as_of_date, "FAILED", [error])
        ephemeral_meta = {
            "protocol_version": EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION,
            "market": normalized_market,
            "as_of_date": as_of_date.isoformat(),
            "input_fingerprint": None,
            "provider_status": {},
            "errors": [error],
            "raw_market_data_persisted": False,
            "qfq_persisted": False,
        }
        quality = {"status": "FAILED", "counts": {}, "failed_symbols": [], "ephemeral_errors": [error]}

    payload = {
        **result,
        "market": normalized_market,
        "as_of_date": as_of_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "prospective_observation": build_prospective_observation(result, normalized_market, as_of_date),
        "cloud_daily_report": _cloud_metadata(
            market=normalized_market,
            as_of_date=as_of_date,
            generated_at=generated_at,
            status=report_status,
            session_identity=session_identity,
            ephemeral=ephemeral_meta,
            data_quality=quality,
            result=result,
            errors=errors,
            reliability_classification=_reliability_classification(
                status=report_status,
                result=result,
                automatic_scheduler_delay=scheduler_delay,
            ),
            session_resolution=session_resolution,
            legacy_recovery_identity=legacy_recovery_identity,
            delivery_scope=normalized_scope,
        ),
    }
    # A manual rerun of the current natural session uses the same ledger.
    # Historical dates are diagnostic-only; births must precede next open.
    # An upstream/degraded report is not a reliable Daily Decision and must
    # not create prospective birth/follow-up evidence.
    delivery_readiness = str(
        payload["cloud_daily_report"].get("delivery_readiness") or ""
    ).upper()
    eligible = (
        as_of_date > RELEASE_DATE
        and delivery_readiness == FINAL_REPORT_ELIGIBLE
    )
    if as_of_date > RELEASE_DATE and delivery_readiness != FINAL_REPORT_ELIGIBLE:
        opportunity_status = "NOT_ELIGIBLE_DELIVERY_READINESS"
    if eligible:
        try:
            window = provider.completed_session_window(normalized_market, as_of_date, now=generated_at)
            if generated_at >= window.next_session_open:
                opportunity_status = ("MISSED_PROSPECTIVE_SESSION" if automatic_resolution
                                      else "NOT_ENABLED_FOR_DIAGNOSTIC")
            else:
                if sheets is None:
                    raise RuntimeError("OPPORTUNITY_LEDGER_CLIENT_UNAVAILABLE")
                opportunity_write_attempted = True
                payload["opportunity_tracking"] = persist_daily_opportunities(
                    sheets, payload, observation_inputs, provider, runtime, generated_at,
                )
                opportunity_status = "SUCCESS"
        except Exception as exc:
            opportunity_status, opportunity_error = "FAILED", _error_text(exc)
    if "opportunity_tracking" not in payload:
        try:
            diagnostic_count = len(birth_snapshots(payload, observation_inputs))
        except Exception:
            diagnostic_count = None
        payload["opportunity_tracking"] = {
            "status": opportunity_status, "error": opportunity_error,
            "diagnostic_observation_count": diagnostic_count,
        }
    payload["cloud_daily_report"]["OPPORTUNITY_LEDGER_STATUS"] = opportunity_status
    payload["cloud_daily_report"]["opportunity_ledger_error"] = opportunity_error
    payload["cloud_daily_report"]["opportunity_ledger_sheet_write"] = opportunity_status == "SUCCESS"
    payload["cloud_daily_report"]["opportunity_ledger_write_attempted"] = opportunity_write_attempted
    payload["cloud_daily_report"]["sheet_mutation"] = (True if opportunity_status == "SUCCESS" else "UNKNOWN" if opportunity_write_attempted else False)
    payload["cloud_daily_report"]["sheet_mutation_scope"] = list(SCHEMAS) if opportunity_write_attempted else []
    payload["cloud_daily_report"]["opportunity_followup_ohlc_persistence"] = opportunity_write_attempted
    _finalize_delivery_eligibility(payload, opportunity_status)
    if opportunity_write_attempted:
        payload["NO Sheets mutation"] = False
        payload["read behavior"] = "READ_ONLY_STRATEGY_WITH_OPPORTUNITY_LEDGER"
    _write_and_notify(payload, output_dir, notify=notify, marker_store=marker_store)
    return payload


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market-scoped read-only Cloud Daily Report V1")
    parser.add_argument("--market", choices=("CN", "US"), required=True)
    parser.add_argument("--date", "--trade-date", dest="trade_date", type=_date, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--require-complete", action="store_true",
                        help="Exit nonzero for a delivered PARTIAL_DATA_QUALITY report")
    parser.add_argument(
        "--legacy-recovery-identity", default=None,
        help=(
            "Explicit one-time legacy V1 marker identity, for example "
            "US|2026-10-05|CLOUD-DAILY-REPORT-MOBILE-V1-2026-09-14"
        ),
    )
    parser.add_argument(
        "--retry-not-ready-attempts", type=int,
        default=DEFAULT_RETRY_NOT_READY_ATTEMPTS,
        help="Bounded attempts for retryable UPSTREAM_NOT_READY/diagnostic runs",
    )
    parser.add_argument(
        "--retry-not-ready-delay-seconds", type=float,
        default=DEFAULT_RETRY_NOT_READY_DELAY_SECONDS,
        help="Delay between bounded readiness attempts",
    )
    args = parser.parse_args(argv)
    generated_at = datetime.now(timezone.utc)
    calendar_provider = ExactExchangeCalendarProvider()
    try:
        trade_date = resolve_cloud_trade_date(
            args.market,
            args.trade_date,
            now=generated_at,
            calendar_provider=calendar_provider,
        )
    except Exception as exc:
        diagnostic_date = args.trade_date or generated_at.date()
        error = _error_text(exc)
        result = _empty_result(diagnostic_date, "SESSION_RESOLUTION_ERROR", [error])
        payload = {
            **result,
            "market": str(args.market).upper(),
            "as_of_date": diagnostic_date.isoformat(),
            "generated_at": generated_at.isoformat(),
            "cloud_daily_report": _cloud_metadata(
                market=str(args.market).upper(),
                as_of_date=diagnostic_date,
                generated_at=generated_at,
                status="SESSION_RESOLUTION_ERROR",
                session_identity=None,
                ephemeral={"provider_status": {}, "input_fingerprint": None},
                data_quality={
                    "status": "SESSION_RESOLUTION_ERROR",
                    "failed_symbols": [],
                    "ephemeral_errors": [error],
                },
                result=result,
                errors=[error],
                reliability_classification="SESSION_RESOLUTION_ERROR",
                delivery_scope=(
                    DELIVERY_SCOPE_DIAGNOSTIC if args.trade_date is not None else DELIVERY_SCOPE_NATURAL
                ),
            ),
        }
        _write_and_notify(payload, args.output, notify=not args.no_notify)
        print(json.dumps(payload["cloud_daily_report"], ensure_ascii=False, indent=2, default=str))
        return 1
    retry_offsets = bounded_readiness_attempt_offsets(
        args.retry_not_ready_attempts,
        args.retry_not_ready_delay_seconds,
    )
    payload = None
    for attempt, _elapsed_seconds in enumerate(retry_offsets):
        payload = run_cloud_daily_report(
            market=args.market,
            as_of_date=trade_date,
            output_dir=args.output,
            now=datetime.now(timezone.utc) if attempt else generated_at,
            calendar_provider=calendar_provider,
            # Bounded readiness attempts are internal computation only.  The
            # terminal payload is notified once after the loop below.
            notify=False,
            automatic_resolution=args.trade_date is None,
            legacy_recovery_identity=args.legacy_recovery_identity,
            delivery_scope=(
                DELIVERY_SCOPE_DIAGNOSTIC
                if args.trade_date is not None
                else DELIVERY_SCOPE_NATURAL
            ),
        )
        readiness = str(
            (payload.get("cloud_daily_report") or {}).get("delivery_readiness") or ""
        ).upper()
        retryable = bool(
            (payload.get("cloud_daily_report") or {}).get("delivery_readiness_retryable")
        )
        if (
            not retryable
            or readiness not in {UPSTREAM_NOT_READY, DEGRADED_DIAGNOSTIC_ONLY}
            or attempt + 1 >= len(retry_offsets)
        ):
            break
        delay = retry_offsets[attempt + 1] - retry_offsets[attempt]
        if delay:
            time.sleep(delay)
    assert payload is not None
    if payload.get("cloud_daily_report", {}).get("status") != FINAL_SESSION_ALREADY_COMPLETED:
        if not args.no_notify:
            dashboard_path = args.output / "daily-report.html"
            if dashboard_path.is_file():
                dashboard_html = dashboard_path.read_text(encoding="utf-8")
                _notify(payload, dashboard_html=dashboard_html)
                _write_artifacts(payload, args.output, dashboard_html=dashboard_html)
    print(json.dumps(payload.get("cloud_daily_report", {}), ensure_ascii=False, indent=2, default=str))
    metadata = payload.get("cloud_daily_report", {})
    if metadata.get("status") == FINAL_SESSION_ALREADY_COMPLETED:
        return 0
    if metadata.get("OPPORTUNITY_LEDGER_STATUS") in {"FAILED", "MISSED_PROSPECTIVE_SESSION"} or payload.get("opportunity_tracking", {}).get("provider_global_failure"):
        return 1
    status = str(metadata.get("status") or "FAILED")
    run_status = str(metadata.get("run_status") or metadata.get("RUN_STATUS") or status)
    data_status = str(metadata.get("data_status") or metadata.get("DATA_STATUS") or "UNKNOWN")
    delivery_readiness = str(metadata.get("delivery_readiness") or "").upper()
    if delivery_readiness in {UPSTREAM_NOT_READY, DEGRADED_DIAGNOSTIC_ONLY}:
        return 2
    if delivery_readiness == DELIVERY_FAILED:
        return 1
    if status in {"SUCCESS", "SKIPPED_NON_SESSION"} or run_status in {
        "COMPLETED", "COMPLETED_NO_USABLE_SYMBOLS"
    }:
        if args.require_complete and data_status != "OK" and run_status.startswith("COMPLETED"):
            return 2
        return 0
    partial_complete = (status == "PARTIAL_DATA_QUALITY"
                        and metadata.get("calendar_gate") == "EXACT_COMPLETED_SESSION"
                        and metadata.get("data_quality", {}).get("operationally_complete")
                        and all((args.output / name).is_file() for name in ARTIFACT_ALLOWLIST))
    if partial_complete:
        return 2 if args.require_complete else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

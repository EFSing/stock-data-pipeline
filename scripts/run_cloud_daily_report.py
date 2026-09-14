"""Run one market-scoped, read-only Cloud Daily Report.

The script is intentionally a thin orchestrator.  Session identity, provider
fallback, latest validation, Candidate discovery, and the Daily Decision Chain
remain owned by the existing modules; this layer only supplies ephemeral
market evidence, writes the two final artifacts, and optionally notifies.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
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
from trading.production_candidate_runtime import ProductionCandidateRuntime
from trading.production_prerequisites import ExactExchangeCalendarProvider


CLOUD_DAILY_REPORT_PROTOCOL_VERSION = "CLOUD-DAILY-REPORT-MOBILE-V1-2026-09-14"
MARKET_LABELS = {"CN": "A股", "US": "美股"}
ARTIFACT_ALLOWLIST = ("daily-report.json", "daily-report.html")


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _error_text(exc: BaseException | str) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ").strip()[:300] or type(exc).__name__


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
    counts = {"DATA_OK": 0, "DATA_BAD": 0, "DATA_STALE": 0, "DATA_UNAVAILABLE": 0}
    failed_symbols: set[str] = set()
    for entry in report_values:
        report = entry.get("报告") if isinstance(entry, Mapping) else {}
        for row in report.get("results", []) if isinstance(report, Mapping) else []:
            status = str(row.get("data_status") or "").upper()
            if status in counts:
                counts[status] += 1
            if status and status != "DATA_OK":
                failed_symbols.add(str(row.get("symbol") or ""))
    for symbol, item in ephemeral.symbol_status.items():
        if item.get("errors"):
            failed_symbols.add(symbol)
    preflight_ready = str(preflight.get("production readiness") or "") == "READY"
    preflight_errors = tuple(str(value) for value in (preflight.get("errors") or ()) if value)
    candidate_errors = result.get("candidate_runtime_errors")
    candidate_quality_errors: list[str] = []
    candidate_markets = result.get("candidate_markets")
    if isinstance(candidate_markets, Mapping):
        candidate = candidate_markets.get(ephemeral.market)
        if isinstance(candidate, Mapping):
            candidate_status = str(candidate.get("status") or "").upper()
            if candidate_status not in {"", "SUCCESS", "NOT_RUN"}:
                candidate_quality_errors.append(
                    f"{ephemeral.market} Candidate status: {candidate_status}"
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
    candidate_failed = bool(candidate_errors) or bool(candidate_quality_errors)
    has_data_issue = bool(ephemeral.errors) or bool(failed_symbols) or not preflight_ready or candidate_failed
    if not report_values and not preflight_ready:
        status = "FAILED"
    elif has_data_issue:
        status = "PARTIAL_DATA_QUALITY"
    else:
        status = "SUCCESS"
    quality = {
        "status": status,
        "counts": counts,
        "failed_symbols": sorted(symbol for symbol in failed_symbols if symbol),
        "ephemeral_errors": list(ephemeral.errors),
        "preflight_errors": list(preflight_errors),
        "candidate_runtime_errors": dict(candidate_errors) if isinstance(candidate_errors, Mapping) else {},
        "candidate_quality_errors": list(dict.fromkeys(candidate_quality_errors)),
        "preflight_ready": preflight_ready,
        "candidate_runtime_failed": candidate_failed,
    }
    return status, quality


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
) -> dict[str, Any]:
    candidate_markets = result.get("candidate_markets")
    seed_sources = {}
    candidate_as_of = {}
    candidate_seed_as_of = {}
    protocol_versions: dict[str, str] = {}
    if isinstance(candidate_markets, Mapping):
        candidate = candidate_markets.get(market)
        if isinstance(candidate, Mapping):
            qfq_contract = candidate.get("qfq_contract")
            qfq_contract = qfq_contract if isinstance(qfq_contract, Mapping) else {}
            seed_sources[market] = candidate.get("seed_source") or qfq_contract.get("seed")
            candidate_as_of[market] = candidate.get("as_of_date")
            candidate_seed_as_of[market] = candidate.get("seed_source_as_of")
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
    return {
        "protocol_version": CLOUD_DAILY_REPORT_PROTOCOL_VERSION,
        "market": market,
        "market_label": MARKET_LABELS.get(market, market),
        "as_of_date": as_of_date.isoformat(),
        "git_sha": _git_sha(),
        "generated_at": generated_at.isoformat(),
        "status": status,
        "session_identity": _session_payload(session_identity),
        "calendar_gate": "EXACT_COMPLETED_SESSION" if session_identity is not None else status,
        "data_quality": dict(data_quality),
        "candidate_seed_source": seed_sources,
        "candidate_as_of": candidate_as_of,
        "candidate_seed_as_of": candidate_seed_as_of,
        "protocol_versions": protocol_versions,
        "input_fingerprint": ephemeral.get("input_fingerprint"),
        "ephemeral_market_data_protocol": ephemeral.get("protocol_version", EPHEMERAL_MARKET_DATA_PROTOCOL_VERSION),
        "provider_status": ephemeral.get("provider_status", {}),
        "artifact_allowlist": list(ARTIFACT_ALLOWLIST),
        "raw_market_data_persisted": False,
        "qfq_persisted": False,
        "state_write": False,
        "sheet_mutation": False,
        "broker_orders": "NONE",
        "errors": list(dict.fromkeys(metadata_errors)),
        "github_run_url": github_run_url(),
    }


def _notification_text(payload: Mapping[str, Any]) -> tuple[str, str]:
    cloud = payload.get("cloud_daily_report") if isinstance(payload.get("cloud_daily_report"), Mapping) else {}
    market = str(cloud.get("market") or "").upper()
    label = MARKET_LABELS.get(market, market or "市场")
    status = str(cloud.get("status") or "FAILED")
    projection = build_dashboard_projection(payload)
    summary = projection.get("summary", {})
    plan_count = int(summary.get("strategy_proposal_count", 0) or 0) + int(
        summary.get("entry_allowed_count", 0) or 0
    )
    if status in {"SUCCESS", "SKIPPED_NON_SESSION"}:
        title = f"{label}日报完成"
        body = (
            f"市场：{label}\n"
            f"数据日期：{projection.get('as_of_date', '—')}\n"
            f"数据状态：{status}\n"
            f"新确认：{summary.get('new_confirmed_count', 0)}\n"
            f"接近确认：{summary.get('armed_count', 0)}\n"
            f"交易方案：{plan_count}\n"
            f"持仓：{summary.get('position_count', 0)}\n"
            f"数据异常：{summary.get('data_blocked_count', 0)}"
        )
    else:
        failed = ((cloud.get("data_quality") or {}).get("failed_symbols") or [])
        title = f"{label}日报异常"
        body = (
            f"数据日期：{projection.get('as_of_date', '—')}\n"
            f"状态：{status}\n"
            f"异常标的：{', '.join(failed) or '无可用标的'}\n"
            "本日不生成新的交易信号。"
        )
    run_url = cloud.get("github_run_url")
    if run_url:
        body += f"\n查看本次运行：{run_url}"
    return title, body


def _write_artifacts(payload: Mapping[str, Any], output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "daily-report.json"
    html_path = target / "daily-report.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    html_path.write_text(render_dashboard_html(payload), encoding="utf-8")
    return json_path, html_path


def _notify(payload: dict[str, Any]) -> None:
    cloud = payload.get("cloud_daily_report", {})
    try:
        title, body = _notification_text(payload)
        endpoint = os.environ.get("BARK_ENDPOINT", "")
        bark = send_bark(endpoint, title=title, body=body, url=cloud.get("github_run_url"))
        email = send_optional_email(
            subject=title,
            body=body,
            html_body=render_daily_report_email_html(payload),
        )
        cloud["notifications"] = {"bark": bark, "email": email}
    except Exception as exc:
        cloud["notifications"] = {
            "bark": {"status": "FAILED", "configured": bool(os.environ.get("BARK_ENDPOINT")), "error": _error_text(exc)},
            "email": {"status": "NOT_RUN", "configured": False},
        }


def run_cloud_daily_report(
    *,
    market: str,
    as_of_date: date,
    output_dir: str | Path,
    now: datetime | None = None,
    client: Any | None = None,
    calendar_provider: ExactExchangeCalendarProvider | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    """Run and persist exactly one market/T report."""

    normalized_market = str(market).strip().upper()
    if normalized_market not in {"CN", "US"}:
        raise ValueError(f"unsupported cloud market: {normalized_market}")
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("cloud report requires timezone-aware now")
    provider = calendar_provider or ExactExchangeCalendarProvider()

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
            ),
        }
        _write_artifacts(payload, output_dir)
        if notify:
            _notify(payload)
            _write_artifacts(payload, output_dir)
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
            ),
        }
        _write_artifacts(payload, output_dir)
        if notify:
            _notify(payload)
            _write_artifacts(payload, output_dir)
        return payload

    try:
        session_identity = provider.completed_session(normalized_market, as_of_date, now=generated_at)
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
            ),
        }
        _write_artifacts(payload, output_dir)
        if notify:
            _notify(payload)
            _write_artifacts(payload, output_dir)
        return payload

    errors: list[str] = []
    report_status = "FAILED"
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
            candidate_runtime=ProductionCandidateRuntime(),
            allow_no_runnable_account=True,
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
        ),
    }
    _write_artifacts(payload, output_dir)
    if notify:
        _notify(payload)
        _write_artifacts(payload, output_dir)
    return payload


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Market-scoped read-only Cloud Daily Report V1")
    parser.add_argument("--market", choices=("CN", "US"), required=True)
    parser.add_argument("--date", "--trade-date", dest="trade_date", type=_date, default=date.today())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args(argv)
    payload = run_cloud_daily_report(
        market=args.market,
        as_of_date=args.trade_date,
        output_dir=args.output,
        notify=not args.no_notify,
    )
    print(json.dumps(payload.get("cloud_daily_report", {}), ensure_ascii=False, indent=2, default=str))
    status = str(payload.get("cloud_daily_report", {}).get("status") or "FAILED")
    return 0 if status in {"SUCCESS", "SKIPPED_NON_SESSION"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

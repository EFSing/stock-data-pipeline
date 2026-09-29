#!/usr/bin/env python3
"""Trigger-only Ubuntu VPS watchdog for the market-close workflows.

The watchdog never imports this repository's market code and never touches the
VPS D1 store. It only checks GitHub Actions and dispatches the repository-owned
Daily Report/D1 reconciliation workflows with bounded retries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# The VPS timer is deliberately later than both the Daily Report and D1
# fallbacks. CN Daily Report primary -> VPS is about 155 minutes and US is
# about 125 minutes; a 90-minute window would incorrectly dispatch a second
# Daily Report after a successful primary run. The prior-session gap is much
# larger than four hours, so this remains bounded without confusing the prior
# market session with today's run.
LOOKBACK_SECONDS = 4 * 60 * 60
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
WORKFLOWS = {
    "CN": {
        "DAILY_REPORT": "cn-daily-report.yml",
        "D1_PROSPECTIVE": "setup01-d1-vps-natural-collector-cn.yml",
    },
    "US": {
        "DAILY_REPORT": "us-daily-report.yml",
        "D1_PROSPECTIVE": "setup01-d1-vps-natural-collector-us.yml",
    },
}


def _safe_error(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()[:240] or type(value).__name__


def _retry_delay(headers: Mapping[str, Any], attempt: int) -> float:
    try:
        retry_after = float(str(headers.get("Retry-After") or "0"))
    except (TypeError, ValueError):
        retry_after = 0
    return min(5.0, retry_after if retry_after > 0 else 0.5 * (2**attempt))


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    mode = stat.S_IMODE(config_path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("WATCHDOG_CONFIG_MUST_BE_PRIVATE_0600")
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("watchdog config must be a JSON object")
    token = str(value.get("github_token") or "").strip()
    repository = str(value.get("repository") or "").strip()
    parts = repository.split("/")
    if not token or len(parts) != 2 or not all(parts):
        raise ValueError("watchdog config requires github_token and repository owner/name")
    overrides = value.get("workflow_overrides", {})
    if not isinstance(overrides, Mapping):
        raise ValueError("watchdog config workflow_overrides must be an object")
    return {
        "github_token": token,
        "repository": repository,
        "ref": str(value.get("ref") or "main").strip() or "main",
        "api_url": str(value.get("api_url") or "https://api.github.com").rstrip("/"),
        "workflow_overrides": {
            str(market).upper(): {
                str(kind).upper(): str(workflow)
                for kind, workflow in values.items()
            }
            for market, values in overrides.items()
            if isinstance(values, Mapping)
        },
    }


def _request(
    config: Mapping[str, Any],
    method: str,
    path: str,
    *,
    body: Mapping[str, Any] | None = None,
    opener: Callable[..., Any] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    token = str(config["github_token"])
    url = f"{str(config['api_url']).rstrip('/')}{path}"
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    for attempt in range(3):
        request = Request(
            url,
            data=payload,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "stock-data-pipeline-market-close-watchdog",
                "Authorization": f"Bearer {token}",
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
            method=method,
        )
        try:
            with opener(request, timeout=20) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
                response_headers = dict(getattr(response, "headers", {}) or {})
            parsed = json.loads(raw.decode("utf-8")) if raw else None
            if 200 <= status < 300:
                return {"ok": True, "status": status, "body": parsed}
            result = {"ok": False, "status": status, "error": f"GITHUB_API_HTTP_{status}"}
            if status not in RETRYABLE_HTTP or attempt == 2:
                return result
            sleep(_retry_delay(response_headers, attempt))
        except HTTPError as exc:
            status = int(exc.code)
            if status not in RETRYABLE_HTTP or attempt == 2:
                return {"ok": False, "status": status, "error": f"GITHUB_API_HTTP_{status}"}
            sleep(_retry_delay(dict(exc.headers or {}), attempt))
        except (OSError, URLError, TimeoutError, ValueError) as exc:
            if attempt == 2:
                return {"ok": False, "status": 0, "error": _safe_error(exc)}
            sleep(0.5 * (2**attempt))
    return {"ok": False, "status": 0, "error": "GITHUB_API_UNAVAILABLE"}


def _recent_run(runs: Any, now: datetime) -> Mapping[str, Any] | None:
    cutoff = now.timestamp() - LOOKBACK_SECONDS
    candidates = []
    for run in runs if isinstance(runs, list) else ():
        if not isinstance(run, Mapping):
            continue
        try:
            created = datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
            if created.timestamp() >= cutoff:
                candidates.append((created, run))
        except (TypeError, ValueError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def reconcile_workflow(
    config: Mapping[str, Any],
    *,
    market: str,
    kind: str,
    now: datetime,
    opener: Callable[..., Any] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    normalized_market = str(market).strip().upper()
    normalized_kind = str(kind).strip().upper()
    workflow = WORKFLOWS.get(normalized_market, {}).get(normalized_kind)
    if not workflow:
        return {"status": "INVALID_ROUTE", "market": normalized_market, "kind": normalized_kind}
    owner, repository = str(config["repository"]).split("/", 1)
    configured_workflow = str(
        (config.get("workflow_overrides", {}).get(normalized_market, {}) or {}).get(normalized_kind)
        or workflow
    )
    encoded = configured_workflow.replace("/", "%2F")
    run_path = f"/repos/{owner}/{repository}/actions/workflows/{encoded}/runs?branch={config['ref']}&per_page=20"
    listing = _request(config, "GET", run_path, opener=opener, sleep=sleep)
    run = _recent_run((listing.get("body") or {}).get("workflow_runs"), now) if listing.get("ok") else None
    active_or_success = bool(run) and (
        str(run.get("status")) in {"queued", "in_progress", "waiting", "requested", "pending"}
        or (str(run.get("status")) == "completed" and str(run.get("conclusion")) == "success")
    )
    result = {
        "market": normalized_market,
        "kind": normalized_kind,
        "workflow": configured_workflow,
        "status_check_error": None if listing.get("ok") else listing.get("error"),
        "recent_run_id": run.get("id") if run else None,
        "recent_run_status": run.get("status") if run else None,
        "recent_run_conclusion": run.get("conclusion") if run else None,
    }
    if active_or_success:
        result["status"] = "NOOP_PRIMARY_ACTIVE_OR_SUCCESS"
        return result
    dispatch_path = f"/repos/{owner}/{repository}/actions/workflows/{encoded}/dispatches"
    dispatch = _request(
        config,
        "POST",
        dispatch_path,
        body={"ref": config["ref"], "inputs": {}},
        opener=opener,
        sleep=sleep,
    )
    result.update({
        "status": "DISPATCHED_RECONCILIATION" if dispatch.get("ok") else "DISPATCH_FAILED",
        "dispatch_http_status": dispatch.get("status"),
        "dispatch_error": dispatch.get("error"),
    })
    return result


def run_watchdog(
    config: Mapping[str, Any], *, market: str, now: datetime | None = None,
    opener: Callable[..., Any] = urlopen, sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("watchdog requires timezone-aware now")
    normalized = str(market).strip().upper()
    if normalized not in WORKFLOWS:
        raise ValueError("market must be CN or US")
    results = [
        reconcile_workflow(config, market=normalized, kind=kind, now=current, opener=opener, sleep=sleep)
        for kind in ("DAILY_REPORT", "D1_PROSPECTIVE")
    ]
    return {
        "watchdog": "market-close-watchdog",
        "trigger": "VPS_CRON_OR_USER_SYSTEMD_TIMER",
        "market": normalized,
        "generated_at": current.isoformat(),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger GitHub market-close workflows")
    parser.add_argument("--market", choices=("CN", "US"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_watchdog(load_config(args.config), market=args.market)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(item.get("status") != "DISPATCH_FAILED" for item in result["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

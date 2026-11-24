#!/usr/bin/env python3
"""Dispatch the repository's market-close workflows from Ubuntu systemd timers."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import stat
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPOSITORY = "EFSing/stock-data-pipeline"
REF = "main"
WORKFLOWS = {
    "cn-close": "asia-close.yml",
    "cn-report": "cn-daily-report.yml",
    "cn-d1": "setup01-d1-vps-natural-collector-cn.yml",
    "us-close": "us-close.yml",
    "us-report": "us-daily-report.yml",
    "us-d1": "setup01-d1-vps-natural-collector-us.yml",
}
LOOKBACK = timedelta(hours=4)
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "requested", "pending"}
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def _private_file(path: Path) -> Path:
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError(f"{path.name} must be a private file (0600)")
    return path


def load_config(path: Path) -> tuple[str, Path]:
    config = json.loads(_private_file(path).read_text(encoding="utf-8"))
    client_id = config.get("github_app_client_id") if isinstance(config, dict) else None
    key_file = config.get("github_app_private_key_file") if isinstance(config, dict) else None
    if not isinstance(client_id, str) or not client_id.strip() or not isinstance(key_file, str) or not key_file:
        raise ValueError("github_app_client_id and github_app_private_key_file are required")
    return client_id.strip(), _private_file(path.parent / key_file)


def _jwt(client_id: str, key: Path) -> str:
    def encode(data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    now = int(time.time())
    claims = {"iat": now - 60, "exp": now + 540, "iss": client_id}
    payload = b".".join((
        encode(b'{"alg":"RS256","typ":"JWT"}'),
        encode(json.dumps(claims, separators=(",", ":")).encode("utf-8")),
    ))
    try:
        signature = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(key)],
            input=payload, capture_output=True, timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("GITHUB_APP_JWT_SIGN_FAILED") from None
    return b".".join((payload, encode(signature))).decode("ascii")


def _request(
    method: str, path: str, token: str, body: dict[str, Any] | None = None, *,
    opener=urlopen, sleep=time.sleep,
) -> dict[str, Any]:
    request = Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "stock-data-pipeline-market-close-watchdog",
        },
        method=method,
    )
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    # Dispatch is not idempotent. Only retry a rejection (429), never a
    # response whose loss could have occurred after GitHub accepted the run.
    dispatch = path.endswith("/dispatches")
    for attempt in range(3):
        try:
            with opener(request, timeout=20) as response:
                raw = response.read()
            return json.loads(raw) if raw else {}
        except HTTPError as exc:
            if attempt == 2 or exc.code not in RETRYABLE_HTTP or (dispatch and exc.code != 429):
                raise RuntimeError(f"GITHUB_API_HTTP_{exc.code}") from None
        except (OSError, URLError):
            if dispatch or attempt == 2:
                raise RuntimeError("GITHUB_API_NETWORK_ERROR") from None
        sleep(0.5 * (2**attempt))
    raise RuntimeError("GITHUB_API_UNAVAILABLE")


def installation_token(client_id: str, key: Path, *, request=_request) -> tuple[str, str]:
    jwt = _jwt(client_id, key)
    installation = request("GET", f"/repos/{REPOSITORY}/installation", jwt)
    installation_id, slug = installation.get("id"), installation.get("app_slug")
    if not isinstance(installation_id, int) or not isinstance(slug, str) or not slug:
        raise RuntimeError("GITHUB_APP_INSTALLATION_INVALID")
    response = request(
        "POST", f"/app/installations/{installation_id}/access_tokens", jwt,
        {"repositories": [REPOSITORY.split("/")[1]], "permissions": {"actions": "write"}},
    )
    token = response.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("GITHUB_APP_INSTALLATION_TOKEN_MISSING")
    return token, f"{slug}[bot]"


def _workflow_path(workflow: str) -> str:
    return f"/repos/{REPOSITORY}/actions/workflows/{workflow}"


def dispatch_job(job: str, token: str, *, now: datetime | None = None, request=_request) -> dict[str, Any]:
    workflow = WORKFLOWS[job]
    path = _workflow_path(workflow)
    if not job.endswith("-close"):
        cutoff = (now or datetime.now(timezone.utc)) - LOOKBACK
        params = urlencode({"branch": REF, "created": f">={cutoff:%Y-%m-%dT%H:%M:%SZ}", "per_page": 100})
        runs = request("GET", f"{path}/runs?{params}", token)["workflow_runs"]
        for run in runs:
            active = run["status"] in ACTIVE_STATUSES
            # A completed report can still be waiting for data. Let the
            # report's own final marker decide whether a retry is needed.
            completed_d1 = job.endswith("-d1") and run["conclusion"] == "success"
            if active or completed_d1:
                return {"status": "NOOP_ACTIVE_OR_COMPLETE", "workflow": workflow, "run_id": run["id"]}
    inputs = {"mode": "latest"} if job.endswith("-close") else {}
    response = request("POST", f"{path}/dispatches", token, {"ref": REF, "inputs": inputs})
    return {"status": "DISPATCHED", "workflow": workflow, "run_id": response.get("workflow_run_id")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--job", choices=WORKFLOWS)
    action.add_argument("--check", action="store_true", help="Check App and workflow access without dispatching")
    args = parser.parse_args(argv)
    try:
        token, actor = installation_token(*load_config(args.config))
        if args.check:
            workflows = {
                workflow: _request("GET", _workflow_path(workflow), token)["state"]
                for workflow in WORKFLOWS.values()
            }
            ok = all(state == "active" for state in workflows.values())
            print(json.dumps({"status": "READY" if ok else "WORKFLOW_INACTIVE", "actor": actor, "workflows": workflows}))
            return 0 if ok else 1
        print(json.dumps({"actor": actor, **dispatch_job(args.job, token)}))
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        # Never include credentials, response bodies, or OpenSSL stderr.
        print(json.dumps({"status": "FAILED", "reason": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

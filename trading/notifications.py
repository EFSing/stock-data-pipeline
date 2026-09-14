"""Small, optional notification adapters for Cloud Daily Report V1."""
from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib
from typing import Any, Mapping
from urllib.request import Request, urlopen
import json


def _safe_error(exc: BaseException) -> str:
    return str(exc).replace("\r", " ").replace("\n", " ").strip()[:240] or type(exc).__name__


def github_run_url(environ: Mapping[str, str] | None = None) -> str | None:
    values = environ or os.environ
    server = str(values.get("GITHUB_SERVER_URL", "")).strip().rstrip("/")
    repository = str(values.get("GITHUB_REPOSITORY", "")).strip().strip("/")
    run_id = str(values.get("GITHUB_RUN_ID", "")).strip()
    if not server or not repository or not run_id:
        return None
    return f"{server}/{repository}/actions/runs/{run_id}"


def send_bark(
    endpoint: str | None,
    *,
    title: str,
    body: str,
    url: str | None = None,
    opener: Any = urlopen,
) -> dict[str, Any]:
    """Send one JSON Bark notification, without making it a report blocker."""

    target = str(endpoint or "").strip()
    if not target:
        return {"status": "NOT_CONFIGURED", "configured": False}
    payload: dict[str, Any] = {"title": title, "body": body}
    if url:
        payload["url"] = url
    request = Request(
        target,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with opener(request, timeout=20) as response:
            status_code = getattr(response, "status", None)
        return {"status": "SENT", "configured": True, "http_status": status_code}
    except Exception as exc:
        return {"status": "FAILED", "configured": True, "error": _safe_error(exc)}


def send_optional_email(
    *,
    subject: str,
    body: str,
    html_body: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Send SMTP only when explicitly configured; never raise to the runner."""

    values = environ or os.environ
    host = str(values.get("SMTP_HOST", "")).strip()
    sender = str(values.get("SMTP_FROM", "")).strip()
    recipients = tuple(
        item.strip()
        for item in str(values.get("SMTP_TO", "")).split(",")
        if item.strip()
    )
    if not host or not sender or not recipients:
        return {"status": "NOT_CONFIGURED", "configured": False}
    try:
        port = int(str(values.get("SMTP_PORT", "587")).strip() or "587")
        use_tls = str(values.get("SMTP_USE_TLS", "true")).strip().lower() not in {"0", "false", "no"}
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = ", ".join(recipients)
        message.set_content(body)
        message.add_alternative(html_body, subtype="html")
        with smtplib.SMTP(host, port, timeout=20) as server:
            if use_tls:
                server.starttls()
            username = str(values.get("SMTP_USERNAME", "")).strip()
            password = str(values.get("SMTP_PASSWORD", ""))
            if username:
                server.login(username, password)
            server.send_message(message)
        return {"status": "SENT", "configured": True}
    except Exception as exc:
        return {"status": "FAILED", "configured": True, "error": _safe_error(exc)}


__all__ = ["github_run_url", "send_bark", "send_optional_email"]

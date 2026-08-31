"""Strict protocol and result rendering for the holdings GitHub Issue bus.

This module contains transport validation only.  Holdings identity and lifecycle
semantics remain in :mod:`holdings_data_manager`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping


COMMAND_TITLE = "[HOLDINGS_COMMAND]"
COMMAND_VERSION = 1
RESULT_MARKER = "<!-- holdings-command-result:v1 -->"
REPOSITORY_FULL_NAME = "EFSing/stock-data-pipeline"
ALLOWED_ISSUE_ACTORS = frozenset({"EFSing"})
ALLOWED_OPERATIONS = frozenset({"ADD", "REENTER", "CLOSE", "SYNC"})
REQUIRED_COMMAND_FIELDS = frozenset(
    {"version", "operation", "symbol", "request_id", "dry_run"}
)
OPTIONAL_COMMAND_FIELDS = frozenset({"market"})
COMMAND_FIELDS = REQUIRED_COMMAND_FIELDS | OPTIONAL_COMMAND_FIELDS
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class CommandBusError(ValueError):
    """A fail-closed Issue event or command-schema error."""


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON object keys instead of silently taking the last one."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CommandBusError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def reject_nonstandard_json_constant(value: str) -> None:
    """Reject NaN/Infinity, which are not strict JSON values."""
    raise CommandBusError(f"non-standard JSON value: {value}")


def parse_json_object(raw: str, *, context: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise CommandBusError(f"{context} must be a non-empty JSON object")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_json_keys,
            parse_constant=reject_nonstandard_json_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, CommandBusError) as exc:
        raise CommandBusError(f"invalid {context} JSON") from exc
    if not isinstance(value, dict):
        raise CommandBusError(f"{context} must be a JSON object")
    return value


@dataclass(frozen=True)
class HoldingsCommand:
    version: int
    operation: str
    symbol: str
    market: str | None
    request_id: str
    dry_run: bool


def _require_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if type(value) is not str or not value:
        raise CommandBusError(f"{field} must be a non-empty string")
    if value != value.strip() or any(char.isspace() for char in value):
        raise CommandBusError(f"{field} contains whitespace/control characters")
    return value


def parse_command_body(body: str) -> HoldingsCommand:
    """Parse the exact v1 Issue body; no natural-language body is accepted."""
    payload = parse_json_object(body, context="command body")
    unknown = set(payload) - COMMAND_FIELDS
    missing = REQUIRED_COMMAND_FIELDS - set(payload)
    if unknown:
        raise CommandBusError("unknown command field")
    if missing:
        raise CommandBusError("missing required command field")

    version = payload["version"]
    if type(version) is not int or version != COMMAND_VERSION:
        raise CommandBusError("unsupported command version")

    operation = _require_string(payload, "operation")
    if operation not in ALLOWED_OPERATIONS:
        raise CommandBusError("operation is not allowed")

    symbol = _require_string(payload, "symbol")
    request_id = _require_string(payload, "request_id")
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise CommandBusError("request_id has an unsafe format")

    dry_run = payload["dry_run"]
    if type(dry_run) is not bool:
        raise CommandBusError("dry_run must be boolean")

    market: str | None = None
    if "market" in payload:
        market = _require_string(payload, "market")

    return HoldingsCommand(version, operation, symbol, market, request_id, dry_run)


def _login(value: Any, field: str) -> str:
    if not isinstance(value, Mapping):
        raise CommandBusError(f"{field} is missing")
    login = value.get("login")
    if type(login) is not str or not login:
        raise CommandBusError(f"{field} login is missing")
    return login


def parse_issue_event(event: Mapping[str, Any], *, actor: str | None) -> HoldingsCommand:
    """Validate the GitHub ``issues.opened`` envelope before reading its body."""
    if not isinstance(event, Mapping):
        raise CommandBusError("GitHub event must be an object")
    if event.get("action") != "opened":
        raise CommandBusError("only newly opened issues are accepted")

    repository = event.get("repository")
    if not isinstance(repository, Mapping) or repository.get("full_name") != REPOSITORY_FULL_NAME:
        raise CommandBusError("event repository is not the governed repository")

    issue = event.get("issue")
    if not isinstance(issue, Mapping):
        raise CommandBusError("issue payload is missing")
    if "pull_request" in issue:
        raise CommandBusError("pull requests are not command issues")
    number = issue.get("number")
    if type(number) is not int or number <= 0:
        raise CommandBusError("issue number is invalid")
    if issue.get("title") != COMMAND_TITLE:
        raise CommandBusError("issue title must be exactly [HOLDINGS_COMMAND]")

    sender_login = _login(event.get("sender"), "sender")
    issue_login = _login(issue.get("user"), "issue user")
    if type(actor) is not str or not actor:
        raise CommandBusError("workflow actor is missing")
    logins = (sender_login, issue_login, actor)
    allowed = {login.casefold() for login in ALLOWED_ISSUE_ACTORS}
    if any(login.casefold() not in allowed for login in logins):
        raise CommandBusError("issue sender/actor is not allowlisted")
    if len({login.casefold() for login in logins}) != 1:
        raise CommandBusError("issue sender/actor identity mismatch")

    return parse_command_body(issue.get("body"))


def safe_message(message: Any) -> str:
    """Keep result comments/logs bounded and free of secret-shaped payloads."""
    text = str(message)
    for env_name in ("GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON"):
        secret = os.environ.get(env_name, "")
        if secret:
            text = text.replace(secret, "<redacted-secret>")
    text = " ".join(text.split())
    text = re.sub(r"-----BEGIN [^-]+PRIVATE KEY-----.*?-----END [^-]+PRIVATE KEY-----", "<redacted-private-key>", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)(google_service_account_json|private_key|client_email|api[_ -]?key|access[_ -]?token)\s*[:=]\s*[^,; ]+", r"\1=<redacted>", text)
    text = text.replace("```", "''' ").replace("<!--", "< !--").replace("-->", "-- >")
    return text[:500] or "no message"


@dataclass(frozen=True)
class CommandResult:
    request_id: str | None
    operation: str | None
    normalized_symbol: str | None
    market: str | None
    status: str
    enabled: bool | None
    history_rows_written: int
    message: str
    dry_run: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": COMMAND_VERSION,
            "request_id": safe_message(self.request_id) if self.request_id is not None else None,
            "operation": safe_message(self.operation) if self.operation is not None else None,
            "normalized_symbol": safe_message(self.normalized_symbol) if self.normalized_symbol is not None else None,
            "market": safe_message(self.market) if self.market is not None else None,
            "status": safe_message(self.status),
            "enabled": self.enabled,
            "history_rows_written": int(self.history_rows_written),
            "message": safe_message(self.message),
            "dry_run": self.dry_run,
        }


def render_result_comment(result: CommandResult) -> str:
    """Render one stable machine-readable block plus a bounded human summary."""
    payload = json.dumps(
        result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    request_id = result.request_id or "unavailable"
    operation = result.operation or "unavailable"
    normalized_symbol = result.normalized_symbol or "unavailable"
    market = result.market or "unavailable"
    return (
        f"{RESULT_MARKER}\n"
        "```json\n"
        f"{payload}\n"
        "```\n\n"
        "Holdings command result\n\n"
        f"- request_id: `{safe_message(request_id)}`\n"
        f"- operation: `{safe_message(operation)}`\n"
        f"- normalized symbol: `{safe_message(normalized_symbol)}`\n"
        f"- market: `{safe_message(market)}`\n"
        f"- status: `{safe_message(result.status)}`\n"
        f"- enabled: `{result.enabled}`\n"
        f"- history_rows_written: `{int(result.history_rows_written)}`\n"
        f"- message: {safe_message(result.message)}\n"
    )

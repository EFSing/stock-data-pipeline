"""GitHub Issue event bridge for the existing HoldingsDataManager.

The bridge intentionally has no holdings business logic.  It validates the
Issue envelope and command schema, normalizes identity through the existing
manager module, and only delegates live execution to ``HoldingsDataManager``.
The workflow routes dry-run and live commands separately so Google credentials
are injected only into the validated live step.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from holdings_command_bus import (
    CommandBusError,
    CommandResult,
    HoldingsCommand,
    parse_issue_event,
    parse_json_object,
)


ROUTE_OUTPUT_KEY = "command_route"
LIVE_ROUTE = "live"
DRY_RUN_ROUTE = "dry_run"
INVALID_ROUTE = "invalid"
LIVE_CREDENTIAL_ENV = ("GOOGLE_SHEET_ID", "GOOGLE_SERVICE_ACCOUNT_JSON")


def _safe_runtime_message(message: Any) -> str:
    """Remove the exact runtime secret values before a result can be emitted."""
    text = str(message)
    for env_name in LIVE_CREDENTIAL_ENV:
        secret = os.environ.get(env_name, "")
        if secret:
            text = text.replace(secret, "<redacted-secret>")
    return text


def _failed(
    message: str,
    *,
    command: HoldingsCommand | None = None,
    normalized_symbol: str | None = None,
    market: str | None = None,
) -> CommandResult:
    return CommandResult(
        request_id=command.request_id if command else None,
        operation=command.operation if command else None,
        normalized_symbol=normalized_symbol,
        market=market if market is not None else (command.market if command else None),
        status="FAILED",
        enabled=None,
        history_rows_written=0,
        message=_safe_runtime_message(message),
        dry_run=command.dry_run if command else None,
    )


def route_event(event: Mapping[str, Any], *, actor: str | None) -> str:
    """Return a non-secret workflow route after authoritative event parsing."""
    try:
        command = parse_issue_event(event, actor=actor)
        # The route step may use identity normalization, but never constructs
        # the manager or a Sheets client.  Invalid identity therefore stays on
        # the no-secret fail-closed route.
        from holdings_data_manager import normalize_holding

        normalize_holding(command.symbol, command.market)
    except Exception:
        return INVALID_ROUTE
    return DRY_RUN_ROUTE if command.dry_run else LIVE_ROUTE


def execute_event(
    event: Mapping[str, Any],
    *,
    actor: str | None,
    live_writes_enabled: bool = False,
) -> CommandResult:
    """Execute one validated event, with live writes behind an explicit gate."""
    try:
        command = parse_issue_event(event, actor=actor)
    except CommandBusError as exc:
        return _failed(f"fail-closed command/event validation: {exc}")

    try:
        # This imports the existing identity normalization; it does not access
        # Sheets, providers, accounts, brokers, strategies, or research.
        from holdings_data_manager import normalize_holding

        normalized = normalize_holding(command.symbol, command.market)
    except Exception as exc:
        return _failed(
            f"fail-closed identity normalization: {exc}",
            command=command,
            market=command.market,
        )

    if command.dry_run:
        return CommandResult(
            request_id=command.request_id,
            operation=command.operation,
            normalized_symbol=normalized.symbol,
            market=normalized.market,
            status="DRY_RUN",
            enabled=None,
            history_rows_written=0,
            message="dry-run validated; no Google Sheets writes or holdings execution",
            dry_run=True,
        )

    if not live_writes_enabled:
        return CommandResult(
            request_id=command.request_id,
            operation=command.operation,
            normalized_symbol=normalized.symbol,
            market=normalized.market,
            status="FAILED",
            enabled=None,
            history_rows_written=0,
            message="fail-closed: live writes are disabled; submit dry_run=true",
            dry_run=False,
        )

    try:
        if any(not os.environ.get(name, "").strip() for name in LIVE_CREDENTIAL_ENV):
            return _failed(
                "fail-closed live credential gate: required Google credentials are missing",
                command=command,
                normalized_symbol=normalized.symbol,
                market=normalized.market,
            )

        # The only live business call is the existing manager contract.  It
        # owns provider, QC, history-key and Sheets lifecycle semantics.
        from holdings_data_manager import HoldingsDataManager

        execution = HoldingsDataManager().execute(
            command.operation, normalized.symbol, normalized.market
        )
        status = str(execution.status)
        return CommandResult(
            request_id=command.request_id,
            operation=execution.operation,
            normalized_symbol=execution.symbol,
            market=execution.market,
            status=status,
            enabled=None if status == "FAILED" else execution.enabled,
            history_rows_written=execution.history_rows_written,
            message=_safe_runtime_message(execution.message),
            dry_run=False,
        )
    except Exception as exc:
        return _failed(
            f"fail-closed HoldingsDataManager execution: {exc}",
            command=command,
            normalized_symbol=normalized.symbol,
            market=normalized.market,
        )


def _load_event(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    return parse_json_object(raw, context="GitHub event")


def _write_route(path: Path, route: str) -> None:
    path.write_text(f"{ROUTE_OUTPUT_KEY}={route}\n", encoding="utf-8")


def _write_outputs(result: CommandResult, result_path: Path, comment_path: Path) -> None:
    result_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    from holdings_command_bus import render_result_comment

    comment_path.write_text(render_result_comment(result), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--route-path")
    parser.add_argument("--result-path", default="holdings-command-result.json")
    parser.add_argument("--comment-path", default="holdings-command-result.md")
    args = parser.parse_args(argv)

    try:
        if not args.event_path:
            raise CommandBusError("GITHUB_EVENT_PATH is missing")
        event = _load_event(Path(args.event_path))
        if args.route_path:
            _write_route(
                Path(args.route_path),
                route_event(event, actor=os.environ.get("GITHUB_ACTOR")),
            )
            return 0
        result = execute_event(
            event,
            actor=os.environ.get("GITHUB_ACTOR"),
            live_writes_enabled=os.environ.get("HOLDINGS_COMMAND_BUS_LIVE_WRITES") == "enabled",
        )
    except Exception as exc:
        if args.route_path:
            _write_route(Path(args.route_path), INVALID_ROUTE)
            return 0
        result = _failed(f"fail-closed bridge error: {exc}")

    _write_outputs(result, Path(args.result_path), Path(args.comment_path))
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

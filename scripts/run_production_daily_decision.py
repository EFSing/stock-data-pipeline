"""Build and optionally run the account-isolated production Daily Chain.

``--preflight`` and the default ``--run`` path are strictly read-only.  The
``--write-state`` flag explicitly authorizes appending system-owned state rows
to the injected Sheets backend; neither mode writes strategy input worksheets
or calls a broker.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path
import sys
from typing import Iterable, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sheets_client import SheetsClient
from trading.daily_decision_chain import DailyDecisionChain
from trading.production_prerequisites import (
    ProductionInputAdapter,
    ProductionPrerequisiteError,
    SheetsDecisionStateStore,
)


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYY-MM-DD") from exc


def _allocation_budget(value: str) -> tuple[str, float]:
    account_id, separator, raw_budget = value.partition("=")
    account_id = account_id.strip()
    if not separator or not account_id or not raw_budget.strip():
        raise argparse.ArgumentTypeError(
            "allocation budget must use ACCOUNT_ID=AMOUNT"
        )
    try:
        budget = float(raw_budget)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("allocation budget must be numeric") from exc
    if not math.isfinite(budget) or budget <= 0:
        raise argparse.ArgumentTypeError("allocation budget must be positive and finite")
    return account_id, budget


def run_production_daily_decision(
    client,
    *,
    as_of_date: date,
    preflight: bool = True,
    write_state: bool = False,
    now: datetime | None = None,
    allocation_budgets: Mapping[str, float] | None = None,
    approved_event_identities: Iterable[str] | None = None,
):
    adapter = ProductionInputAdapter(client, as_of_date=as_of_date, now=now)
    snapshot = adapter.snapshot()
    if preflight:
        return snapshot.preflight
    if write_state and not snapshot.preflight.ready:
        raise ProductionPrerequisiteError("production preflight is not ready")
    if not snapshot.account_runs:
        raise ProductionPrerequisiteError("production preflight has no runnable account")
    budgets = {
        str(account_id).strip(): float(value)
        for account_id, value in (allocation_budgets or {}).items()
    }
    known_account_ids = tuple(item.account_id for item in snapshot.preflight.accounts)
    unknown_budget_accounts = tuple(sorted(set(budgets) - set(known_account_ids)))
    if unknown_budget_accounts:
        raise ProductionPrerequisiteError(
            "ALLOCATION_BUDGET_ACCOUNT_UNKNOWN:" + ",".join(unknown_budget_accounts)
        )
    approvals = tuple(approved_event_identities or ())
    reports = []
    for account_run in snapshot.account_runs:
        if write_state:
            store = SheetsDecisionStateStore(
                client,
                write_enabled=True,
                account_id=account_run.account.account_id,
                known_account_ids=known_account_ids,
            )
        else:
            store = account_run.state_store
            if store is None:
                raise ProductionPrerequisiteError("PRODUCTION_STATE_STORE_REQUIRED")
        report = DailyDecisionChain(store=store).evaluate(
            account_run.inputs,
            mode="PRODUCTION",
            allocation_budget=budgets.get(account_run.account.account_id),
            approved_event_identities=approvals,
            existing_positions=account_run.existing_positions,
            persist_state=write_state,
        )
        reports.append({
            "账户ID": account_run.account.account_id,
            "read behavior": "STATE_WRITE_AUTHORIZED" if write_state else "READ_ONLY",
            "NO STATE WRITE": not write_state,
            "NO Sheets mutation": not write_state,
            "broker orders": "NONE",
            "报告": report.to_dict(),
            "Markdown": report.to_markdown(),
        })
    return {
        "preflight": snapshot.preflight.to_dict(),
        "read behavior": "STATE_WRITE_AUTHORIZED" if write_state else "READ_ONLY",
        "NO STATE WRITE": not write_state,
        "NO Sheets mutation": not write_state,
        "broker orders": "NONE",
        "reports": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production prerequisites / account-isolated Daily Chain")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--preflight", action="store_true", help="只读验证，不写任何状态或 worksheet")
    actions.add_argument(
        "--run", action="store_true",
        help="运行 account-isolated Daily Chain；默认只读，只有 --write-state 才追加系统状态",
    )
    parser.add_argument("--date", "--trade-date", dest="trade_date", type=_date, default=date.today())
    parser.add_argument("--write-state", action="store_true", help="允许系统-owned 策略决策状态写入")
    parser.add_argument(
        "--approve-event", action="append", default=[],
        help="显式批准一个已发布 event identity；可重复传入，不接受 symbol shortcut",
    )
    parser.add_argument(
        "--allocation-budget", action="append", type=_allocation_budget, default=[],
        metavar="ACCOUNT_ID=AMOUNT",
        help="显式提供账户策略风险账本总预算；可重复传入，不读取 NAV 替代",
    )
    args = parser.parse_args(argv)
    if args.preflight and (args.write_state or args.approve_event or args.allocation_budget):
        parser.error("--preflight 不接受 state write、event approval 或 allocation budget")
    budgets = dict(args.allocation_budget)
    if len(budgets) != len(args.allocation_budget):
        parser.error("每个 ACCOUNT_ID 只能提供一次 allocation budget")
    client = SheetsClient()
    try:
        result = run_production_daily_decision(
            client,
            as_of_date=args.trade_date,
            preflight=args.preflight,
            write_state=args.write_state,
            allocation_budgets=budgets,
            approved_event_identities=args.approve_event,
        )
    except (TypeError, ValueError, ProductionPrerequisiteError) as exc:
        print(json.dumps({"production readiness": "NOT_READY", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    if args.preflight:
        print(result.to_markdown())
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ready else 2
    for item in result["reports"]:
        print(item["Markdown"])
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["preflight"]["production readiness"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

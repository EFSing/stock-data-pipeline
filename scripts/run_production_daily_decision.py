"""Build and optionally run the account-isolated production Daily Chain.

``--preflight`` is strictly read-only.  Stateful execution is deliberately
explicit because it can append system-owned state rows to the injected Sheets
backend; it never writes strategy input worksheets or calls a broker.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

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


def run_production_daily_decision(
    client,
    *,
    as_of_date: date,
    preflight: bool = True,
    write_state: bool = False,
):
    adapter = ProductionInputAdapter(client, as_of_date=as_of_date)
    snapshot = adapter.snapshot()
    if preflight:
        return snapshot.preflight
    if not snapshot.preflight.ready:
        raise ProductionPrerequisiteError("production preflight is not ready")
    if not write_state:
        raise ProductionPrerequisiteError("stateful run requires explicit write_state=True")
    reports = []
    for account_run in snapshot.account_runs:
        store = SheetsDecisionStateStore(
            client, write_enabled=True, account_id=account_run.account.account_id
        )
        report = DailyDecisionChain(store=store).evaluate(
            account_run.inputs,
            mode="PRODUCTION",
            reference_nav=account_run.reference_nav,
            existing_positions=account_run.existing_positions,
        )
        reports.append({
            "账户ID": account_run.account.account_id,
            "报告": report.to_dict(),
        })
    return tuple(reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production prerequisites / account-isolated Daily Chain")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--preflight", action="store_true", help="只读验证，不写任何状态或 worksheet")
    actions.add_argument("--run", action="store_true", help="运行 account-isolated Daily Chain")
    parser.add_argument("--date", "--trade-date", dest="trade_date", type=_date, default=date.today())
    parser.add_argument("--write-state", action="store_true", help="允许系统-owned 策略决策状态写入")
    args = parser.parse_args(argv)
    if args.preflight and args.write_state:
        parser.error("--preflight 不允许 --write-state")
    if args.run and not args.write_state:
        parser.error("--run 必须显式提供 --write-state")
    client = SheetsClient()
    try:
        result = run_production_daily_decision(
            client,
            as_of_date=args.trade_date,
            preflight=args.preflight,
            write_state=args.write_state,
        )
    except (TypeError, ValueError, ProductionPrerequisiteError) as exc:
        print(json.dumps({"production readiness": "NOT_READY", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    if args.preflight:
        print(result.to_markdown())
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ready else 2
    print(json.dumps(list(result), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

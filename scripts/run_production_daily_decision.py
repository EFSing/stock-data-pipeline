"""Build and optionally run the account-isolated production Daily Chain.

``--preflight`` and the default ``--run`` path are strictly read-only.  The
``--write-state`` flag explicitly authorizes appending system-owned state rows
to the injected Sheets backend; neither mode writes strategy input worksheets
or calls a broker.  On a real ``SheetsClient``, ``--run`` also performs the
bounded CN/US Candidate screening and merges the selected symbols into the
same day's in-memory Daily Chain input.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path
import sys
import time
from typing import Iterable, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sheets_client import SheetsClient
from trading.daily_decision_chain import DailyDecisionChain, STRATEGY_PROPOSAL
from trading.production_candidate_runtime import (
    CandidateMarketRuntimeResult,
    PRODUCTION_CANDIDATE_ACCOUNT_ROUTING_REQUIRED,
    ProductionCandidateRuntime,
)
from trading.production_prerequisites import (
    ProductionInputAdapter,
    ProductionPrerequisiteError,
    SheetsDecisionStateStore,
)


def _canonical_key(market: str, symbol: str) -> tuple[str, str]:
    normalized_market = str(market).strip().upper()
    normalized_symbol = str(symbol).strip().upper()
    if normalized_market == "CN":
        code, separator, suffix = normalized_symbol.partition(".")
        if code.isdigit() and len(code) == 6:
            if not separator:
                suffix = "SH" if code.startswith(("5", "6", "9")) else "SZ"
            elif suffix in {"SSE", "XSHG"}:
                suffix = "SH"
            elif suffix in {"SZSE", "XSHE"}:
                suffix = "SZ"
            if suffix in {"SH", "SZ"}:
                normalized_symbol = f"{code}.{suffix}"
    return normalized_market, normalized_symbol


def _action_value(decision) -> str | None:
    action = getattr(decision, "action", None)
    value = getattr(action, "value", action)
    return str(value) if value is not None else None


def _candidate_not_run_result(market: str, as_of_date: date) -> CandidateMarketRuntimeResult:
    from trading.candidate_universe import CandidateUniverse, TOP_N_PER_SECTOR

    return CandidateMarketRuntimeResult(
        market=market,
        as_of_date=as_of_date,
        seed_source_as_of=None,
        seeds=(),
        universe=CandidateUniverse(as_of_date, TOP_N_PER_SECTOR, ()),
        deep_histories={},
        deep_errors={},
        stage_timings={},
        errors=(),
        status="NOT_RUN",
        qfq_contract={},
    )


def _candidate_failure_result(
    market: str, as_of_date: date, error: BaseException
) -> CandidateMarketRuntimeResult:
    from trading.candidate_universe import CandidateUniverse, TOP_N_PER_SECTOR

    message = f"{type(error).__name__}:{error}"
    return CandidateMarketRuntimeResult(
        market=market,
        as_of_date=as_of_date,
        seed_source_as_of=None,
        seeds=(),
        universe=CandidateUniverse(as_of_date, TOP_N_PER_SECTOR, ()),
        deep_histories={},
        deep_errors={},
        stage_timings={
            "total": {
                "elapsed_seconds": 0.0,
                "api_requests": 0,
                "symbols": 0,
                "rows": 0,
                "usable_count": 0,
                "failed_count": 1,
                "status": "FAILED",
            }
        },
        errors=(message,),
        status="FAILED",
        qfq_contract={},
    )


def _merge_candidate_inputs(
    account_run,
    candidate_result: CandidateMarketRuntimeResult,
    session_identity,
) -> tuple[tuple, dict[str, object]]:
    """Union formal, active-position and dynamic Candidate inputs once."""

    values = {
        _canonical_key(item.market, item.symbol): item
        for item in account_run.inputs
    }
    formal_symbols = {
        str(symbol).strip().upper()
        for symbol in account_run.formal_strategy_pool
    }
    if not formal_symbols:
        formal_symbols = {
            item.symbol.upper()
            for item in account_run.inputs
            if item.open_position_state is None
        }
    position_symbols = {
        str(symbol).strip().upper()
        for symbol in account_run.active_strategy_positions
    }
    position_symbols.update(
        item.symbol.upper()
        for item in account_run.inputs
        if item.open_position_state is not None
    )
    dynamic_symbols = {
        str(symbol).strip().upper()
        for symbol in candidate_result.included_symbols
    }
    if session_identity is not None:
        for item in candidate_result.daily_inputs(session_identity):
            values.setdefault(_canonical_key(item.market, item.symbol), item)

    ordered = tuple(
        values[key]
        for key in sorted(values, key=lambda value: (value[0], value[1]))
    )
    formal_keys = {
        _canonical_key(account_run.account.market, symbol)
        for symbol in formal_symbols
    }
    position_keys = {
        _canonical_key(account_run.account.market, symbol)
        for symbol in position_symbols
    }
    dynamic_keys = {
        _canonical_key(account_run.account.market, symbol)
        for symbol in dynamic_symbols
    }
    provenance: dict[str, list[str]] = {}
    for item in ordered:
        symbol = item.symbol.upper()
        identity = _canonical_key(item.market, item.symbol)
        labels = provenance.setdefault(symbol, [])
        if identity in formal_keys:
            labels.append("FORMAL_STRATEGY_POOL")
        if identity in position_keys:
            labels.append("ACTIVE_STRATEGY_POSITION")
        if identity in dynamic_keys:
            labels.append("DYNAMIC_CANDIDATE")
    return ordered, {
        "formal_strategy_pool": sorted(formal_symbols),
        "active_strategy_positions": sorted(position_symbols),
        "dynamic_candidate_set": sorted(dynamic_symbols),
        "daily_analysis_universe": [item.symbol.upper() for item in ordered],
        "provenance": {
            symbol: labels for symbol, labels in sorted(provenance.items())
        },
    }


def _funnel(
    results,
    candidate_result: CandidateMarketRuntimeResult,
    deep_analysis_count: int,
) -> dict[str, int]:
    def is_watch(result) -> bool:
        return result.setup01_state == "WATCH" or result.setup02_state == "WATCH"

    def is_armed(result) -> bool:
        return result.setup01_state == "ARMED" or result.setup02_state == "ARMED"

    return {
        "seed": candidate_result.seed_count,
        "candidate_data_qualified": candidate_result.data_qualified_count,
        "candidate_included": len(candidate_result.included_records),
        "deep_analysis": deep_analysis_count,
        "WATCH": sum(is_watch(result) for result in results),
        "ARMED": sum(is_armed(result) for result in results),
        "new_CONFIRMED": sum(
            len(result.new_confirmed_event_identities) for result in results
        ),
        "STRATEGY_PROPOSAL": sum(
            result.final_status == STRATEGY_PROPOSAL for result in results
        ),
        "individual_ENTRY_ALLOWED": sum(
            _action_value(result.individual_decision) == "ENTRY_ALLOWED"
            for result in results
        ),
        "Portfolio_allowed": sum(
            result.final_status == "PORTFOLIO_ALLOWED" for result in results
        ),
        "NO_TRADE": sum(result.final_status == "NO_TRADE" for result in results),
        "DATA_BLOCKED": sum(
            result.final_status == "DATA_OR_PRODUCTION_PREREQUISITE_BLOCKED"
            for result in results
        ),
    }


def _production_markdown(
    report,
    candidate_report: Mapping[str, object],
    universe_report: Mapping[str, object],
    funnel: Mapping[str, int],
    strategy_elapsed_seconds: float,
) -> str:
    timings = candidate_report.get("stage_timings", {})
    timing_text = "；".join(
        f"{name}={values.get('elapsed_seconds', 0)}s"
        for name, values in timings.items()
        if name != "total" and isinstance(values, Mapping)
    )
    return "\n".join([
        report.to_markdown(),
        "## Candidate → Daily Chain",
        "",
        f"- Seed：{funnel['seed']}；Candidate 数据合格：{funnel['candidate_data_qualified']}；Candidate included：{funnel['candidate_included']}；进入深度策略分析：{funnel['deep_analysis']}",
        f"- WATCH：{funnel['WATCH']}；ARMED：{funnel['ARMED']}；新 CONFIRMED：{funnel['new_CONFIRMED']}；STRATEGY_PROPOSAL：{funnel['STRATEGY_PROPOSAL']}",
        f"- individual ENTRY_ALLOWED：{funnel['individual_ENTRY_ALLOWED']}；Portfolio allowed：{funnel['Portfolio_allowed']}；NO_TRADE：{funnel['NO_TRADE']}；DATA_BLOCKED：{funnel['DATA_BLOCKED']}",
        f"- 正式策略股票池：{len(universe_report.get('formal_strategy_pool', ())) }；已有策略持仓：{len(universe_report.get('active_strategy_positions', ())) }；动态 Candidate：{len(universe_report.get('dynamic_candidate_set', ())) }",
        f"- Candidate runtime：{candidate_report.get('status', 'UNKNOWN')}；阶段耗时：{timing_text or '—'}",
        f"- Strategy evaluation elapsed：{strategy_elapsed_seconds}s",
        "- Candidate 不写入策略股票池；broker orders：NONE；默认运行：READ_ONLY",
        "",
    ])


def _resolve_candidate_runtime(client, candidate_runtime):
    if candidate_runtime is not None:
        return candidate_runtime
    # Keep lightweight injected/fake clients used by callers and tests from
    # unexpectedly making network requests.  The real SheetsClient is the
    # production entrypoint and receives the bounded runtime by default.
    if isinstance(client, SheetsClient):
        return ProductionCandidateRuntime()
    return None


def _check_candidate_account_routing(accounts) -> None:
    by_market: dict[str, list[str]] = {}
    for value in accounts:
        account = getattr(value, "account", value)
        by_market.setdefault(account.market.upper(), []).append(
            account.account_id
        )
    ambiguous = {
        market: tuple(sorted(account_ids))
        for market, account_ids in by_market.items()
        if len(set(account_ids)) > 1
    }
    if ambiguous:
        detail = ";".join(
            f"{market}={','.join(account_ids)}"
            for market, account_ids in sorted(ambiguous.items())
        )
        raise ProductionPrerequisiteError(
            f"{PRODUCTION_CANDIDATE_ACCOUNT_ROUTING_REQUIRED}:{detail}"
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
    candidate_runtime=None,
):
    run_started = time.perf_counter()
    adapter = ProductionInputAdapter(client, as_of_date=as_of_date, now=now)
    snapshot = adapter.snapshot()
    if preflight:
        return snapshot.preflight
    candidate_runtime = _resolve_candidate_runtime(client, candidate_runtime)
    if candidate_runtime is not None:
        _check_candidate_account_routing(snapshot.preflight.accounts)
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
    candidate_results_by_market: dict[str, CandidateMarketRuntimeResult] = {}
    candidate_runtime_errors: dict[str, str] = {}
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
        market = account_run.account.market.upper()
        candidate_result = _candidate_not_run_result(market, as_of_date)
        if candidate_runtime is not None:
            candidate_result = candidate_results_by_market.get(market)
            if candidate_result is None:
                session_identity = next(
                    (
                        item.completed_session_identity
                        for item in account_run.inputs
                        if item.market.upper() == market
                    ),
                    None,
                )
                if session_identity is None:
                    candidate_result = _candidate_failure_result(
                        market,
                        as_of_date,
                        ProductionPrerequisiteError("CANDIDATE_SESSION_IDENTITY_REQUIRED"),
                    )
                else:
                    try:
                        candidate_result = candidate_runtime.run(
                            market=market,
                            as_of_date=as_of_date,
                            completed_session_identity=session_identity,
                            now=now,
                            reuse_symbols=(
                                item.symbol for item in account_run.inputs
                            ),
                        )
                    except Exception as exc:
                        candidate_runtime_errors[market] = str(exc)
                        candidate_result = _candidate_failure_result(
                            market, as_of_date, exc
                        )
                candidate_results_by_market[market] = candidate_result
        session_identity = next(
            (
                item.completed_session_identity
                for item in account_run.inputs
                if item.market.upper() == market
            ),
            None,
        )
        inputs, universe_report = _merge_candidate_inputs(
            account_run, candidate_result, session_identity
        )
        strategy_started = time.perf_counter()
        report = DailyDecisionChain(store=store).evaluate(
            inputs,
            mode="PRODUCTION",
            allocation_budget=budgets.get(account_run.account.account_id),
            approved_event_identities=approvals,
            existing_positions=account_run.existing_positions,
            persist_state=write_state,
        )
        strategy_elapsed_seconds = round(time.perf_counter() - strategy_started, 3)
        candidate_report = candidate_result.to_dict()
        candidate_report["deep_analysis_count"] = len(inputs)
        candidate_report["deep_analysis_symbols"] = [
            item.symbol.upper() for item in inputs
        ]
        candidate_report["reused_formal_or_position_count"] = sum(
            _canonical_key(market, symbol)
            in {
                _canonical_key(market, item.symbol)
                for item in account_run.inputs
            }
            for symbol in candidate_result.included_symbols
        )
        funnel = _funnel(report.results, candidate_result, len(inputs))
        markdown = _production_markdown(
            report,
            candidate_report,
            universe_report,
            funnel,
            strategy_elapsed_seconds,
        )
        reports.append({
            "账户ID": account_run.account.account_id,
            "市场": market,
            "read behavior": "STATE_WRITE_AUTHORIZED" if write_state else "READ_ONLY",
            "NO STATE WRITE": not write_state,
            "NO Sheets mutation": not write_state,
            "candidate strategy pool mutation": False,
            "broker orders": "NONE",
            "universe": universe_report,
            "Candidate": candidate_report,
            "Funnel": funnel,
            "runtime": {
                "strategy_evaluation_elapsed_seconds": strategy_elapsed_seconds,
            },
            "报告": report.to_dict(),
            "Markdown": markdown,
        })
    candidate_payload = {
        market: result.to_dict()
        for market, result in sorted(candidate_results_by_market.items())
    }
    funnel_payload = {
        item["市场"]: item["Funnel"] for item in reports
    }
    return {
        "preflight": snapshot.preflight.to_dict(),
        "read behavior": "STATE_WRITE_AUTHORIZED" if write_state else "READ_ONLY",
        "NO STATE WRITE": not write_state,
        "NO Sheets mutation": not write_state,
        "candidate strategy pool mutation": False,
        "broker orders": "NONE",
        "candidate_markets": candidate_payload,
        "funnel": funnel_payload,
        "candidate_runtime_errors": candidate_runtime_errors,
        "runtime": {
            "total_elapsed_seconds": round(time.perf_counter() - run_started, 3),
            "strategy_evaluation_elapsed_seconds": round(
                sum(
                    item["runtime"]["strategy_evaluation_elapsed_seconds"]
                    for item in reports
                ),
                3,
            ),
            "candidate_market_count": len(candidate_results_by_market),
            "candidate_market_timings": {
                market: dict(result.stage_timings.get("total", {}))
                for market, result in sorted(candidate_results_by_market.items())
            },
        },
        "reports": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production prerequisites / account-isolated Daily Chain")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--preflight", action="store_true", help="只读验证，不写任何状态或 worksheet")
    actions.add_argument(
        "--run", action="store_true",
        help="运行 Candidate→account-isolated Daily Chain；默认只读，只有 --write-state 才追加系统状态",
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
        readiness = (
            "READY_FOR_DECISION"
            if str(exc).startswith("READY_FOR_DECISION")
            else "NOT_READY"
        )
        print(json.dumps({"production readiness": readiness, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
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

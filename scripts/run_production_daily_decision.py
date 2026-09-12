"""Build and optionally run the account-isolated production Daily Chain.

``--preflight`` and the default ``--run`` path are strictly read-only.  The
``--write-state`` flag explicitly authorizes appending system-owned state rows
to the injected Sheets backend for formal strategy-pool inputs; Candidate-only
inputs remain read-only even when the flag is present.  Neither mode writes
strategy input worksheets or calls a broker.  On a real ``SheetsClient``,
``--run`` also performs the bounded CN/US Candidate screening and merges the
selected symbols into the same day's in-memory Daily Chain input.
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
from trading.daily_decision_chain import (
    DailyDecisionChain,
    DailyTradingDecisionReport,
    InMemoryDecisionStateStore,
    STRATEGY_PROPOSAL,
)
from trading.production_candidate_runtime import (
    CandidateMarketRuntimeResult,
    PRODUCTION_CANDIDATE_ACCOUNT_ROUTING_REQUIRED,
    ProductionCandidateRuntime,
    canonical_key,
)
from trading.production_prerequisites import (
    ProductionInputAdapter,
    ProductionPrerequisiteError,
    SheetsDecisionStateStore,
)


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
        canonical_key(item.market, item.symbol): item
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
            values.setdefault(canonical_key(item.market, item.symbol), item)

    ordered = tuple(
        values[key]
        for key in sorted(values, key=lambda value: (value[0], value[1]))
    )
    formal_keys = {
        canonical_key(account_run.account.market, symbol)
        for symbol in formal_symbols
    }
    position_keys = {
        canonical_key(account_run.account.market, symbol)
        for symbol in position_symbols
    }
    dynamic_keys = {
        canonical_key(account_run.account.market, symbol)
        for symbol in dynamic_symbols
    }
    provenance: dict[str, list[str]] = {}
    for item in ordered:
        symbol = item.symbol.upper()
        identity = canonical_key(item.market, item.symbol)
        labels = provenance.setdefault(symbol, [])
        if identity in formal_keys:
            labels.append("FORMAL_STRATEGY_POOL")
        if identity in position_keys:
            labels.append("ACTIVE_STRATEGY_POSITION")
        if identity in dynamic_keys:
            labels.append("DYNAMIC_CANDIDATE")
    provenance_metadata: dict[str, dict[str, object]] = {}
    dynamic_candidate_only: list[str] = []
    for symbol, labels in sorted(provenance.items()):
        is_formal = "FORMAL_STRATEGY_POOL" in labels
        is_position = "ACTIVE_STRATEGY_POSITION" in labels
        is_dynamic = "DYNAMIC_CANDIDATE" in labels
        candidate_only = is_dynamic and not is_formal and not is_position
        if candidate_only:
            dynamic_candidate_only.append(symbol)
        provenance_metadata[symbol] = {
            "source": "DYNAMIC_CANDIDATE" if candidate_only else "+".join(labels),
            "state_persistence_eligible": is_formal,
            "promotion_required": candidate_only,
            "persistence_policy": (
                "FORMAL_STRATEGY_LIFECYCLE"
                if is_formal
                else "READ_ONLY_DISCOVERY"
                if candidate_only
                else "READ_ONLY_POSITION_MANAGEMENT"
            ),
            "production_execution_eligible": is_formal,
        }
    return ordered, {
        "formal_strategy_pool": sorted(formal_symbols),
        "active_strategy_positions": sorted(position_symbols),
        "dynamic_candidate_set": sorted(dynamic_symbols),
        "dynamic_candidate_only": dynamic_candidate_only,
        "stateful_analysis_symbols": [
            item.symbol.upper()
            for item in ordered
            if canonical_key(item.market, item.symbol) in formal_keys
        ],
        "daily_analysis_universe": [item.symbol.upper() for item in ordered],
        "provenance": {
            symbol: labels for symbol, labels in sorted(provenance.items())
        },
        "provenance_metadata": provenance_metadata,
    }


def _split_persistence_inputs(
    account_run,
    inputs: tuple,
) -> tuple[tuple, tuple]:
    """Keep formal symbols stateful; inspect every other input read-only."""

    formal_keys = {
        canonical_key(account_run.account.market, symbol)
        for symbol in account_run.formal_strategy_pool
    }
    if not formal_keys:
        formal_keys = {
            canonical_key(item.market, item.symbol)
            for item in account_run.inputs
            if item.open_position_state is None
        }
    formal_inputs = tuple(
        item for item in inputs if canonical_key(item.market, item.symbol) in formal_keys
    )
    read_only_inputs = tuple(
        item for item in inputs if canonical_key(item.market, item.symbol) not in formal_keys
    )
    return formal_inputs, read_only_inputs


def _merge_reports(
    reports: Iterable[DailyTradingDecisionReport],
    *,
    as_of_date: date,
    generated_at: datetime,
) -> DailyTradingDecisionReport:
    """Combine disjoint group reports without re-evaluating any symbol."""

    group_reports = tuple(reports)
    if not group_reports:
        raise ValueError("Daily Decision Chain requires at least one input group")
    values = tuple(
        result
        for report in group_reports
        for result in report.results
    )
    identities = tuple((result.market.upper(), result.symbol.upper()) for result in values)
    if len(set(identities)) != len(identities):
        raise ValueError("Daily Decision Chain group inputs must be disjoint")
    return DailyTradingDecisionReport(
        as_of_date=as_of_date,
        results=tuple(sorted(values, key=lambda result: (result.market, result.symbol))),
        generated_at=generated_at,
        protocol_versions=dict(group_reports[0].protocol_versions),
    )


def _report_payload(report, universe_report: Mapping[str, object]) -> dict[str, object]:
    """Add per-symbol provenance without changing the frozen result model."""

    payload = report.to_dict()
    metadata = dict(universe_report.get("provenance_metadata", {}))
    payload["symbol_provenance"] = metadata
    for row in payload["results"]:
        row["provenance"] = metadata.get(row["symbol"], {})
    for rows in payload["sections"].values():
        for row in rows:
            row["provenance"] = metadata.get(row["symbol"], {})
    return payload


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


_PRIMARY_SETUP_BY_WAVE = {
    "WAVE_2_TO_3_CANDIDATE": "SETUP_01",
    "WAVE_3_CONTINUATION_CANDIDATE": "SETUP_02",
}
_CANDIDATE_REVIEW_PRIORITY = {"ARMED": 0, "WATCH": 1}


def _candidate_review_rows(
    report,
    universe_report: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    """Project the existing result into a compact candidate-only review list."""

    dynamic_candidate_only = {
        str(symbol).strip().upper()
        for symbol in universe_report.get("dynamic_candidate_only", ())
    }
    metadata_by_symbol = universe_report.get("provenance_metadata", {})
    results_by_symbol = {
        result.symbol.upper(): result
        for result in report.results
    }
    rows: list[dict[str, object]] = []
    for symbol in dynamic_candidate_only:
        metadata = metadata_by_symbol.get(symbol, {})
        if not isinstance(metadata, Mapping):
            continue
        # dynamic_candidate_only is the existing candidate-only identity; the
        # source check keeps this projection fail-closed if its metadata is
        # incomplete or accidentally mixed with another provenance.
        if (
            metadata.get("source") != "DYNAMIC_CANDIDATE"
            or metadata.get("promotion_required") is not True
            or metadata.get("state_persistence_eligible") is not False
            or metadata.get("production_execution_eligible") is not False
        ):
            continue
        result = results_by_symbol.get(symbol)
        if result is None:
            continue
        setup_type = _PRIMARY_SETUP_BY_WAVE.get(result.primary_wave_scenario)
        if setup_type is None:
            continue
        state_attribute = (
            "setup01_state" if setup_type == "SETUP_01" else "setup02_state"
        )
        setup_state = getattr(result, state_attribute, None)
        if setup_state not in _CANDIDATE_REVIEW_PRIORITY:
            continue
        waiting_reason = "；".join(
            str(value)
            for value in (*result.reasons, *result.blocking_prerequisites)
            if value
        ) or "—"
        rows.append({
            "ticker": result.symbol.upper(),
            "market": result.market.upper(),
            "provenance": metadata.get("source"),
            "primary_wave_scenario": result.primary_wave_scenario,
            "setup": setup_type,
            "setup_state": setup_state,
            "final_action": result.primary_action,
            "current_status": result.final_status,
            "promotion_required": metadata.get("promotion_required"),
            "state_persistence_eligible": metadata.get("state_persistence_eligible"),
            "production_execution_eligible": metadata.get(
                "production_execution_eligible"
            ),
            "waiting_reason": waiting_reason,
        })
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                _CANDIDATE_REVIEW_PRIORITY[row["setup_state"]],
                str(row["ticker"]),
            ),
        )
    )


def _markdown_cell(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value).replace("|", "\\|").replace("\n", " ")


def _candidate_review_markdown(
    report,
    universe_report: Mapping[str, object],
) -> str:
    rows = _candidate_review_rows(report, universe_report)
    lines = [
        "## Candidate Review",
        "",
        "- 仅展示 candidate-only 的 `DYNAMIC_CANDIDATE`；Primary Wave 只映射到对应的 SETUP。",
        "- 展示优先级：`ARMED` → `WATCH`；persistent `CONFIRMED`、正式策略池和已有持仓不进入本节。",
        "",
    ]
    headers = (
        "ticker",
        "market",
        "provenance",
        "primary Wave scenario",
        "Setup",
        "Setup state",
        "final action",
        "current status",
        "promotion_required",
        "state_persistence_eligible",
        "production_execution_eligible",
        "waiting reason",
    )
    for state in ("ARMED", "WATCH"):
        lines.extend([f"### {state}", ""])
        group = tuple(row for row in rows if row["setup_state"] == state)
        if not group:
            lines.extend(["无", ""])
            continue
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in group:
            lines.append(
                "| " + " | ".join(
                    _markdown_cell(row[field]) for field in (
                        "ticker",
                        "market",
                        "provenance",
                        "primary_wave_scenario",
                        "setup",
                        "setup_state",
                        "final_action",
                        "current_status",
                        "promotion_required",
                        "state_persistence_eligible",
                        "production_execution_eligible",
                        "waiting_reason",
                    )
                ) + " |"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


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
    report_markdown = report.to_markdown()
    candidate_review = _candidate_review_markdown(report, universe_report)
    first_detail_section = report_markdown.find("\n## ")
    if first_detail_section >= 0:
        report_markdown = (
            report_markdown[:first_detail_section].rstrip()
            + "\n\n"
            + candidate_review
            + report_markdown[first_detail_section:]
        )
    else:
        report_markdown = report_markdown.rstrip() + "\n\n" + candidate_review
    lines = [
        report_markdown,
        "## Candidate → Daily Chain",
        "",
        f"- Seed：{funnel['seed']}；Candidate 数据合格：{funnel['candidate_data_qualified']}；Candidate included：{funnel['candidate_included']}；进入深度策略分析：{funnel['deep_analysis']}",
        f"- WATCH：{funnel['WATCH']}；ARMED：{funnel['ARMED']}；新 CONFIRMED：{funnel['new_CONFIRMED']}；STRATEGY_PROPOSAL：{funnel['STRATEGY_PROPOSAL']}",
        f"- individual ENTRY_ALLOWED：{funnel['individual_ENTRY_ALLOWED']}；Portfolio allowed：{funnel['Portfolio_allowed']}；NO_TRADE：{funnel['NO_TRADE']}；DATA_BLOCKED：{funnel['DATA_BLOCKED']}",
        f"- 正式策略股票池：{len(universe_report.get('formal_strategy_pool', ())) }；已有策略持仓：{len(universe_report.get('active_strategy_positions', ())) }；动态 Candidate：{len(universe_report.get('dynamic_candidate_set', ())) }",
        f"- Candidate runtime：{candidate_report.get('status', 'UNKNOWN')}；阶段耗时：{timing_text or '—'}",
        f"- Strategy evaluation elapsed：{strategy_elapsed_seconds}s",
        "- Candidate 不写入策略股票池；broker orders：NONE；默认运行：READ_ONLY",
    ]
    for symbol in universe_report.get("dynamic_candidate_only", ()):
        metadata = universe_report.get("provenance_metadata", {}).get(symbol, {})
        result = next(
            (item for item in report.results if item.symbol.upper() == symbol),
            None,
        )
        line = (
            f"- Candidate-only {symbol}：source={metadata.get('source', 'DYNAMIC_CANDIDATE')}；"
            "state_persistence_eligible=false；promotion_required=true；"
            "policy=READ_ONLY_DISCOVERY；需要人工加入正式策略股票池后重新运行，"
            "才能进入正式交易生命周期。"
        )
        if result is not None and _action_value(result.individual_decision) == "ENTRY_ALLOWED":
            line += " technical ENTRY_ALLOWED 仍为 NOT_PRODUCTION_EXECUTION_ELIGIBLE_UNTIL_PROMOTED。"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


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


def _evaluate_persistence_groups(
    *,
    formal_inputs: tuple,
    read_only_inputs: tuple,
    state_store,
    existing_positions,
    allocation_budget: float | None,
    approved_event_identities: tuple[str, ...],
    write_state: bool,
    generated_at: datetime,
    as_of_date: date,
) -> DailyTradingDecisionReport:
    """Evaluate formal and discovery inputs once with separate write policy."""

    reports: list[DailyTradingDecisionReport] = []
    if formal_inputs:
        reports.append(
            DailyDecisionChain(store=state_store).evaluate(
                formal_inputs,
                mode="PRODUCTION",
                allocation_budget=allocation_budget,
                approved_event_identities=approved_event_identities,
                existing_positions=existing_positions,
                persist_state=write_state,
                generated_at=generated_at,
            )
        )
    if read_only_inputs:
        # Candidate-only and active-position-only inputs must not read an
        # accidental legacy Candidate event or pending record from the formal
        # production store.  This reuses the existing in-memory test/shadow
        # store only as an empty read-only state view; no second persistence
        # framework or production worksheet is introduced.
        reports.append(
            DailyDecisionChain(store=InMemoryDecisionStateStore()).evaluate(
                read_only_inputs,
                mode="PRODUCTION",
                allocation_budget=None,
                approved_event_identities=(),
                existing_positions=(),
                persist_state=False,
                generated_at=generated_at,
            )
        )
    return _merge_reports(reports, as_of_date=as_of_date, generated_at=generated_at)


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
        formal_inputs, read_only_inputs = _split_persistence_inputs(
            account_run, inputs
        )
        generated_at = datetime.now().astimezone()
        report = _evaluate_persistence_groups(
            formal_inputs=formal_inputs,
            read_only_inputs=read_only_inputs,
            state_store=store,
            existing_positions=account_run.existing_positions,
            allocation_budget=budgets.get(account_run.account.account_id),
            approved_event_identities=approvals,
            write_state=write_state,
            generated_at=generated_at,
            as_of_date=as_of_date,
        )
        strategy_elapsed_seconds = round(time.perf_counter() - strategy_started, 3)
        candidate_report = candidate_result.to_dict()
        candidate_report["deep_analysis_count"] = len(inputs)
        candidate_report["deep_analysis_symbols"] = [
            item.symbol.upper() for item in inputs
        ]
        candidate_report["reused_formal_or_position_count"] = sum(
            canonical_key(market, symbol)
            in {
                canonical_key(market, item.symbol)
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
            "报告": _report_payload(report, universe_report),
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
        help="运行 Candidate→account-isolated Daily Chain；默认只读，--write-state 只对正式策略池输入追加系统状态",
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

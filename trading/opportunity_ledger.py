"""Daily Opportunity Ledger V1: existing decisions and descriptive outcomes.

Direct Sheets reads/appends, no strategy evaluation or simulated execution.
The market workflows serialize schedule/manual/fallback writers. Immutable
births and follow-ups use existing event identities and exact session dates.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import json
import math
from statistics import mean, median
from typing import Any, Mapping

from market_data_contract import canonical_provider_for_market, validate_single_source_quotes
from trading.daily_dashboard import build_dashboard_projection
from trading.production_candidate_runtime import canonical_key


SESSION_SHEET = "日报历史"
OPPORTUNITY_SHEET = "机会观察账本"
FOLLOWUP_SHEET = "机会观察跟踪"
TRACKING_SESSIONS = 10
# Earliest possible natural sessions of this release. Historical diagnostics
# (including Sep 30) never create prospective rows, even on delayed deployment.
RELEASE_DATE = date(2026, 10, 4)
SESSION_HEADERS = (
    "market", "session_date", "seed", "data_qualified", "included", "deep_ready",
    "successful_analysis", "WATCH", "ARMED", "CONFIRMED", "new_CONFIRMED",
    "ENTRY_ALLOWED", "NO_TRADE_reasons_json", "RUN_STATUS", "DATA_STATUS",
    "CANDIDATE_STATUS", "payload_json",
)
OPPORTUNITY_HEADERS = (
    "opportunity_id", "market", "symbol", "setup", "event_identity", "T",
    "source_identity", "signal_close", "action", "primary_reject_reason",
    "entry_zone_low", "entry_zone_high", "probe_entry", "confirmation_entry",
    "structural_invalidation", "execution_stop", "T1", "T2", "T3",
    "t1_upside", "rr", "payload_json",
)
FOLLOWUP_HEADERS = (
    "opportunity_id", "as_of_date", "sessions_since_confirmation", "market", "symbol",
    "coverage_status", "open", "high", "low", "close", "close_return",
    "cumulative_max_favorable_move", "cumulative_max_adverse_move",
    "coverage_complete", "bar_order_status", "payload_json",
)
SCHEMAS = {
    SESSION_SHEET: SESSION_HEADERS,
    OPPORTUNITY_SHEET: OPPORTUNITY_HEADERS,
    FOLLOWUP_SHEET: FOLLOWUP_HEADERS,
}
LEVELS = ("T1", "T2", "T3", "execution_stop", "structural_invalidation")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None


def _row(payload: Mapping[str, Any], headers: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload.get(key) for key in headers if key != "payload_json"} | {
        "payload_json": _json(payload),
    }


def _read(client: Any, sheet: str) -> list[dict[str, Any]]:
    # Errors propagate: an unreadable durable ledger cannot be treated as empty.
    return [json.loads(row["payload_json"]) for row in client.records(sheet)]


def _append(client: Any, sheet: str, values: list[dict[str, Any]],
            existing: list[dict[str, Any]], keys: tuple[str, ...]) -> int:
    seen = {tuple(row[key] for key in keys) for row in existing}
    rows = []
    for value in values:
        key = tuple(value[field] for field in keys)
        if key not in seen:
            rows.append(_row(value, SCHEMAS[sheet]))
            existing.append(value)
            seen.add(key)
    if rows:
        client.append_rows(sheet, list(SCHEMAS[sheet]), rows)
    return len(rows)


def birth_snapshots(payload: Mapping[str, Any], inputs=()) -> list[dict[str, Any]]:
    """Copy each new event/Decision, including every rejected opportunity."""
    market, t = payload["market"], payload["as_of_date"]
    inputs_by_key = {canonical_key(item.market, item.symbol): item for item in inputs}
    births: dict[str, dict[str, Any]] = {}
    for entry in payload.get("reports") or ():
        if entry.get("市场") != market:
            continue
        universe = entry.get("universe") or {}
        formal = {canonical_key(market, symbol) for symbol in universe.get("formal_strategy_pool") or ()}
        candidate = {canonical_key(market, symbol) for symbol in universe.get("dynamic_candidate_set") or ()}
        for result in (entry.get("报告") or {}).get("results") or ():
            if result.get("as_of_date") != t:
                continue
            decisions = {value.get("event_identity"): value
                         for value in result.get("individual_decision_candidates") or ()}
            selected = result.get("individual_decision") or {}
            if selected.get("event_identity"):
                decisions.setdefault(selected["event_identity"], selected)
            for identity in result.get("new_confirmed_event_identities") or ():
                setup = next((name for name in ("SETUP_01", "SETUP_02")
                              if f"|{name}|" in identity), None)
                if setup is None:
                    continue
                decision = decisions.get(identity) or {}
                key = canonical_key(market, result["symbol"])
                item = inputs_by_key.get(key)
                signal_bar = next((bar for bar in item.quotes if bar.trade_date.isoformat() == t), None) if item else None
                signal_close = signal_bar.close if signal_bar is not None else result.get("signal_close")
                targets = decision.get("targets") or ()
                ratios = (decision.get("rr") or {}).get("rr_ratios") or ()
                action = decision.get("action")
                stable_decision = {name: decision.get(name) for name in (
                    "protocol_version", "event_identity", "action", "gate_reason", "gate_detail",
                    "atr14", "planned_entry", "confirmation_level", "entry_zone_low", "entry_zone_high",
                    "probe_entry", "confirmation_entry", "structural_invalidation", "execution_stop",
                    "wave1_origin", "wave_scenario_invalidation", "targets", "target_candidates",
                    "target_upside_pct", "rr",
                )} if decision else None
                birth = {
                    "opportunity_id": f"{market}|{identity}", "event_identity": identity,
                    "market": market, "symbol": result["symbol"], "setup": setup, "T": t,
                    "source_identity": "FORMAL" if key in formal else "CANDIDATE" if key in candidate else "OTHER_READ_ONLY",
                    "formal_pool": key in formal, "dynamic_candidate": key in candidate,
                    "signal_close": signal_close, "action": action,
                    "primary_reject_reason": decision.get("gate_reason") if action and action != "ENTRY_ALLOWED" else None,
                    "decision_status": "AVAILABLE" if decision else "DECISION_UNAVAILABLE",
                    **{name: decision.get(name) for name in (
                        "entry_zone_low", "entry_zone_high", "probe_entry", "confirmation_entry",
                        "planned_entry", "confirmation_level", "structural_invalidation", "execution_stop",
                    )},
                    **{name: decision.get(name, targets[index] if len(targets) > index else None)
                       for index, name in enumerate(("T1", "T2", "T3"))},
                    "t1_upside": decision.get("target_upside_pct"),
                    "rr": ratios[0] if ratios else None,
                    "wave_setup_context": {name: result.get(name) for name in (
                        "weekly_state", "daily_state", "primary_wave_scenario", "alternate_wave_scenario",
                        "setup01_state", "setup02_state", "opportunity_freshness",
                    )},
                    "decision": stable_decision,
                    "provenance": result.get("provenance"),
                    "market_data_provenance": _market_data_provenance(payload, result["symbol"]),
                    "signal_close_source": signal_bar.source if signal_bar else None,
                    "session_identity": (payload.get("cloud_daily_report") or {}).get("session_identity"),
                    "protocol_versions": result.get("protocol_versions"),
                    "git_sha": (payload.get("cloud_daily_report") or {}).get("git_sha"),
                    "created_at": payload.get("generated_at"),
                    "tracking_sessions": TRACKING_SESSIONS,
                }
                prior = births.get(identity)
                if prior and any(prior[name] != birth[name] for name in (
                    "market", "symbol", "T", "decision", "signal_close",
                )):
                    raise ValueError("CONFLICTING_ACCOUNT_OPPORTUNITY")
                births.setdefault(identity, birth)
    return list(births.values())


def _market_data_provenance(payload, symbol):
    cloud = payload.get("cloud_daily_report") or {}
    formal = (cloud.get("provider_status") or {}).get(symbol) or {}
    candidate = (payload.get("candidate_markets") or {}).get(payload["market"]) or {}
    return formal.get("qfq_provenance") or (candidate.get("source_provenance") or {}).get(symbol)


def session_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    market = payload["market"]
    candidate = (payload.get("candidate_markets") or {}).get(market) or {}
    funnel = (payload.get("funnel") or {}).get(market) or {}
    cloud = payload.get("cloud_daily_report") or {}
    results = [row for entry in payload.get("reports") or () if entry.get("市场") == market
               for row in (entry.get("报告") or {}).get("results") or ()]
    reasons = Counter()
    for row in results:
        for decision in row.get("individual_decision_candidates") or ():
            if decision.get("action") and decision["action"] != "ENTRY_ALLOWED":
                reasons[decision.get("gate_reason") or "UNKNOWN"] += 1
    return {
        "market": market, "session_date": payload["as_of_date"],
        "seed": candidate.get("seed_count"),
        "data_qualified": candidate.get("candidate_data_qualified_count"),
        "included": candidate.get("candidate_included_count"),
        "deep_ready": candidate.get("deep_history_ready_count"),
        "successful_analysis": build_dashboard_projection(payload)["summary"]["completed_analysis_count"],
        "WATCH": funnel.get("WATCH"), "ARMED": funnel.get("ARMED"),
        "CONFIRMED": sum(row.get("setup01_state") == "CONFIRMED" or row.get("setup02_state") == "CONFIRMED" for row in results),
        "new_CONFIRMED": funnel.get("new_CONFIRMED"),
        "ENTRY_ALLOWED": funnel.get("individual_ENTRY_ALLOWED"),
        "NO_TRADE": funnel.get("NO_TRADE"),
        "NO_TRADE_reasons_json": _json(dict(reasons)),
        "NO_TRADE_reasons": dict(reasons),
        "NO_TRADE_result_primary_reasons": dict(Counter(
            next(iter(row.get("reasons") or ()), "NO_REASON_REPORTED")
            for row in results if row.get("final_status") == "NO_TRADE"
        )),
        **{name: cloud.get(name) for name in ("RUN_STATUS", "DATA_STATUS", "CANDIDATE_STATUS")},
        "funnel": funnel, "git_sha": cloud.get("git_sha"),
    }


def observation_sessions(birth: Mapping[str, Any], as_of: date, calendar) -> tuple[date, ...]:
    sessions = []
    current = date.fromisoformat(birth["T"])
    for _ in range(birth["tracking_sessions"]):
        current = calendar.next_session(birth["market"], current)
        if current > as_of:
            break
        sessions.append(current)
    return tuple(sessions)


def active_symbols(births, follows, market: str) -> tuple[str, ...]:
    finished = {row["opportunity_id"] for row in follows
                if row["sessions_since_confirmation"] == TRACKING_SESSIONS}
    return tuple(sorted({birth["symbol"] for birth in births
                         if birth["market"] == market and birth["opportunity_id"] not in finished}))


def followup(birth, session: date, index: int, history, previous, *, provenance=None,
             unavailable_reason=None) -> dict[str, Any]:
    """Observe T+1 onward only. Frozen geometry; no execution/PnL/R outcome."""
    t = date.fromisoformat(birth["T"])
    if session <= t:
        raise ValueError("FOLLOWUP_REQUIRES_T_PLUS_ONE")
    previous = [row for row in previous if row["as_of_date"] < session.isoformat()]
    status = unavailable_reason
    errors = validate_single_source_quotes(
        history, expected_symbol=birth["symbol"], expected_market=birth["market"],
        target_trade_date=session, max_trade_date=session,
    )
    provider = canonical_provider_for_market(birth["market"])
    source_names = {provider, "YahooChart"} if birth["market"] == "US" else {provider}
    if not status and (not history or errors):
        status = "DATA_MISSING" if not history else "DATA_INVALID"
    if not status and any(bar.source not in source_names for bar in history):
        status = "DATA_PROVIDER_CONTRACT_MISMATCH"
    signal_close = _number(birth.get("signal_close"))
    original_bar = next((bar for bar in history if bar.trade_date == t), None)
    if not status and (not signal_close or original_bar is None):
        status = "DATA_SIGNAL_ANCHOR_UNAVAILABLE"
    if not status and not math.isclose(original_bar.close, signal_close, rel_tol=1e-8, abs_tol=1e-8):
        # Forward-adjusted prices may change basis after corporate actions.
        # Never compare a newly scaled bar with unscaled frozen T geometry.
        status = "DATA_ADJUSTMENT_BASIS_CHANGED"
    bar = history[-1] if not status else None
    prior = previous[-1] if previous else {}
    touches, first_hits = {}, dict(prior.get("first_touch_sessions") or {})
    for level in LEVELS:
        price = _number(birth.get(level))
        touch = (bar.high >= price if level.startswith("T") else bar.low <= price) if bar and price else None
        touches[level] = touch
        if touch and first_hits.get(level) is None:
            first_hits[level] = session.isoformat()
        first_hits.setdefault(level, None)
    ambiguous = any(touches[name] for name in ("execution_stop", "structural_invalidation")) and any(touches[name] for name in ("T1", "T2", "T3"))
    highs = [row["cumulative_max_favorable_move"] for row in previous if row.get("cumulative_max_favorable_move") is not None]
    lows = [row["cumulative_max_adverse_move"] for row in previous if row.get("cumulative_max_adverse_move") is not None]
    if bar:
        highs.append(bar.high / signal_close - 1)
        lows.append(bar.low / signal_close - 1)
    complete = bar is not None and len(previous) == index - 1 and all(row["coverage_status"] == "DATA_OK" for row in previous)
    return {
        "opportunity_id": birth["opportunity_id"], "market": birth["market"], "symbol": birth["symbol"],
        "as_of_date": session.isoformat(), "sessions_since_confirmation": index,
        "coverage_status": status or "DATA_OK", "coverage_complete": complete,
        **{name: getattr(bar, name) if bar else None for name in ("open", "high", "low", "close")},
        "close_return": bar.close / signal_close - 1 if bar else None,
        "cumulative_max_favorable_move": max(highs) if highs else None,
        "cumulative_max_adverse_move": min(lows) if lows else None,
        "touches": touches, "first_touch_sessions": first_hits,
        "bar_order_status": "SAME_BAR_ORDER_AMBIGUOUS" if ambiguous else "NO_SAME_BAR_CONFLICT" if bar else "UNAVAILABLE",
        "provenance": provenance,
    }


def tracking_projection(births, follows, market: str, t: str) -> dict[str, Any]:
    births = [birth for birth in births if birth["market"] == market and birth["T"] <= t]
    by_id = defaultdict(list)
    for row in follows:
        if row["market"] == market and row["as_of_date"] <= t:
            by_id[row["opportunity_id"]].append(row)
    today = [birth for birth in births if birth["T"] == t]
    matured = [birth for birth in births if any(row["sessions_since_confirmation"] == TRACKING_SESSIONS for row in by_id[birth["opportunity_id"]])]
    stats = []
    for reason in sorted({birth["primary_reject_reason"] or birth["action"] or "DECISION_UNAVAILABLE" for birth in matured}):
        group = [birth for birth in matured if (birth["primary_reject_reason"] or birth["action"] or "DECISION_UNAVAILABLE") == reason]
        final = [next(row for row in by_id[birth["opportunity_id"]] if row["sessions_since_confirmation"] == TRACKING_SESSIONS) for birth in group]
        usable = [row for row in final if row["coverage_complete"]]
        returns = [row["close_return"] for row in usable]
        stats.append({
            "original_reason": reason, "matured_count": len(group), "complete_count": len(usable),
            "coverage_gap_count": len(group) - len(usable), "sample_insufficient": len(usable) < 20,
            "mean_close_return": mean(returns) if returns else None,
            "median_close_return": median(returns) if returns else None,
            "mean_max_favorable_move": mean(row["cumulative_max_favorable_move"] for row in usable) if usable else None,
            "mean_max_adverse_move": mean(row["cumulative_max_adverse_move"] for row in usable) if usable else None,
            "T1_touched_count": sum(row["first_touch_sessions"]["T1"] is not None for row in usable),
            "stop_touched_count": sum(row["first_touch_sessions"]["execution_stop"] is not None for row in usable),
        })
    return {
        "new_observation_count": len(today),
        "today_original_reasons": dict(Counter(birth["primary_reject_reason"] or birth["action"] or "DECISION_UNAVAILABLE" for birth in today)),
        "active_tracking_count": len(births) - len(matured),
        "completed_today_count": sum(any(row["sessions_since_confirmation"] == TRACKING_SESSIONS and row["as_of_date"] == t for row in by_id[birth["opportunity_id"]]) for birth in matured),
        "matured_by_original_reason": stats,
        "sample_insufficient": not stats or any(row["sample_insufficient"] for row in stats),
        "description": "确认后10个真实交易日的价格观察；非成交、非PnL、非normalized R；缺口样本不进入收益统计。",
    }


def persist_daily_opportunities(client, payload, inputs, calendar, runtime, now) -> dict[str, Any]:
    """Append missing identities, then the session summary as completion marker."""
    for sheet, headers in SCHEMAS.items():
        client.ensure_worksheet(sheet, list(headers))
    births, follows = _read(client, OPPORTUNITY_SHEET), _read(client, FOLLOWUP_SHEET)
    new = birth_snapshots(payload, inputs)
    written = _append(client, OPPORTUNITY_SHEET, new, births, ("opportunity_id",))
    market, t = payload["market"], date.fromisoformat(payload["as_of_date"])
    active = set(active_symbols(births, [row for row in follows if row["as_of_date"] <= t.isoformat()], market)) & {
        birth["symbol"] for birth in births if birth["market"] == market and birth["T"] < t.isoformat()
    }
    reused = {item.symbol: tuple(item.quotes) for item in inputs
              if item.market == market and item.symbol in active and item.data_status == "DATA_OK"}
    histories = dict(reused)
    provenance = {symbol: _market_data_provenance(payload, symbol) for symbol in reused}
    load_error = None
    missing = active - set(reused)
    if missing:
        try:
            loaded = runtime.load_opportunity_continuation(market=market, symbols=missing, as_of_date=t, now=now)
            histories.update(loaded.histories)
            provenance.update(loaded.provenance)
            load_error = "PROVIDER_GLOBAL_FAILURE" if loaded.provider_global_failure else None
        except Exception:
            load_error = "DATA_CONTINUATION_UNAVAILABLE"
    pending = []
    for birth in births:
        if birth["market"] != market or birth["symbol"] not in active:
            continue
        previous = sorted((row for row in follows if row["opportunity_id"] == birth["opportunity_id"]), key=lambda row: row["as_of_date"])
        for index, session in enumerate(observation_sessions(birth, t, calendar), 1):
            if any(row["as_of_date"] == session.isoformat() for row in previous):
                continue
            # Missed daily executions remain explicit gaps; no retrospective
            # bar acquisition masquerades as an observation made that day.
            reason = "MISSED_OBSERVATION_SESSION" if session < t else (load_error if birth["symbol"] not in reused else None)
            value = followup(birth, session, index, histories.get(birth["symbol"], ()) if session == t else (),
                             previous, provenance=provenance.get(birth["symbol"]), unavailable_reason=reason)
            pending.append(value)
            previous.append(value)
    follow_written = _append(client, FOLLOWUP_SHEET, pending, follows, ("opportunity_id", "as_of_date"))
    summary_written = client.upsert_opportunity_summary(
        _row(session_summary(payload), SESSION_HEADERS), list(SESSION_HEADERS),
    )
    return tracking_projection(births, follows, market, t.isoformat()) | {
        "status": "SUCCESS", "birth_rows_written": written,
        "followup_rows_written": follow_written, "session_rows_written": summary_written,
        "coverage_gaps_today": sum(row["as_of_date"] == t.isoformat() and row["coverage_status"] != "DATA_OK" for row in follows if row["market"] == market),
        "provider_global_failure": load_error == "PROVIDER_GLOBAL_FAILURE",
    }

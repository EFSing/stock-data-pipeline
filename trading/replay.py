"""SETUP_03 historical replay diagnostics.

This module is intentionally read-only. It replays each historical trading day
as an as-of snapshot by passing only ``quotes[:i + 1]`` into the existing
Setup / Decision engines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from core import Quote
from trading.decision import DecisionDiagnostics
from trading.events import evaluate_setup03_event
from trading.models import Decision, DecisionAction, Setup, SetupState, validate_quote_series
from trading.setup import SetupDiagnostics
from trading.setup import detect_platform_breakout_history_with_diagnostics
from trading.swing import find_swings


REPLAY_SETUP_STATES = (
    SetupState.NONE,
    SetupState.WATCH,
    SetupState.ARMED,
    SetupState.CONFIRMED,
    SetupState.FAILED,
)


@dataclass(frozen=True)
class ReplayDay:
    symbol: str
    trade_date: date
    setup_state: SetupState
    confirmed_event: bool = False
    failed_event: bool = False
    decision_action: DecisionAction | None = None
    setup_diagnostics: SetupDiagnostics | None = None


@dataclass(frozen=True)
class ReplayEvent:
    symbol: str
    trade_date: date
    event_type: SetupState
    setup: Setup
    decision: Decision | None = None
    signal_date: date | None = None
    confirmed_date: date | None = None
    signal_close: float | None = None
    signal_atr: float | None = None
    decision_diagnostics: DecisionDiagnostics | None = None


@dataclass(frozen=True)
class SymbolReplayReport:
    symbol: str
    market: str
    days: tuple[ReplayDay, ...]
    events: tuple[ReplayEvent, ...] = ()
    state_day_counts: dict[SetupState, int] = field(default_factory=dict)
    state_dates: dict[SetupState, tuple[date, ...]] = field(default_factory=dict)
    confirmed_event_dates: tuple[date, ...] = ()
    failed_event_dates: tuple[date, ...] = ()
    decision_counts: dict[DecisionAction, int] = field(default_factory=dict)
    decision_dates: dict[DecisionAction, tuple[date, ...]] = field(default_factory=dict)

    def summary_row(self) -> dict:
        """Return a compact diagnostics row; no production Sheet schema implied."""
        row = {
            "统一代码": self.symbol,
            "市场": self.market,
            "回放交易日数": len(self.days),
        }
        for state in REPLAY_SETUP_STATES:
            row[f"{state.value}状态日数"] = self.state_day_counts.get(state, 0)
            row[f"{state.value}状态日期"] = _join_dates(self.state_dates.get(state, ()))
        row["CONFIRMED事件次数"] = len(self.confirmed_event_dates)
        row["CONFIRMED事件日期"] = _join_dates(self.confirmed_event_dates)
        row["FAILED事件次数"] = len(self.failed_event_dates)
        row["FAILED事件日期"] = _join_dates(self.failed_event_dates)
        for action in (DecisionAction.ENTRY_ALLOWED, DecisionAction.NO_TRADE):
            row[f"{action.value}事件次数"] = self.decision_counts.get(action, 0)
            row[f"{action.value}事件日期"] = _join_dates(
                self.decision_dates.get(action, ())
            )
        other_actions = [
            action
            for action in self.decision_counts
            if action not in (DecisionAction.ENTRY_ALLOWED, DecisionAction.NO_TRADE)
        ]
        row["Decision其他动作次数"] = sum(
            self.decision_counts[action] for action in other_actions
        )
        other_action_set = set(other_actions)
        row["Decision其他动作日期"] = _join_dates(
            day.trade_date
            for day in self.days
            if day.decision_action in other_action_set
        )
        return row


def replay_setup03_history(
    quotes: list[Quote],
    risk_capital: float,
    setup_parameters: dict | None = None,
    decision_parameters: dict | None = None,
    *,
    precompute_swings: bool = False,
) -> SymbolReplayReport:
    """Replay SETUP_03 state and confirmed-day decisions for one symbol.

    Each replay step calls the existing Trading Core with a prefix ending at the
    replay date. This is the as-of guardrail for Phase 5A.
    """
    validate_quote_series(quotes)
    setup_parameters = dict(setup_parameters or {})
    decision_parameters = dict(decision_parameters or {})
    precomputed_swings = None
    setup_history = None
    if precompute_swings:
        precomputed_swings = find_swings(
            quotes,
            lookback=int(setup_parameters.get("swing_lookback", 5)),
        )
        setup_history = detect_platform_breakout_history_with_diagnostics(
            quotes,
            **setup_parameters,
            swings=precomputed_swings,
        )
    state_dates: dict[SetupState, list[date]] = {
        state: [] for state in REPLAY_SETUP_STATES
    }
    confirmed_event_dates: list[date] = []
    failed_event_dates: list[date] = []
    decision_dates: dict[DecisionAction, list[date]] = {}
    days: list[ReplayDay] = []
    events: list[ReplayEvent] = []

    for index, quote in enumerate(quotes):
        as_of_quotes = quotes[: index + 1]
        evaluation_kwargs = {
            "setup_parameters": setup_parameters,
            "decision_parameters": decision_parameters,
        }
        if precompute_swings:
            evaluation_kwargs["setup_calculation"] = setup_history[index]
        evaluation = evaluate_setup03_event(
            as_of_quotes,
            risk_capital,
            **evaluation_kwargs,
        )
        setup = evaluation.setup
        state_dates[setup.state].append(quote.trade_date)

        confirmed_event = evaluation.event_type is SetupState.CONFIRMED
        failed_event = evaluation.event_type is SetupState.FAILED
        decision_action = (
            evaluation.decision.action if evaluation.decision is not None else None
        )
        if confirmed_event:
            confirmed_event_dates.append(quote.trade_date)
            assert evaluation.decision is not None
            decision_dates.setdefault(evaluation.decision.action, []).append(
                quote.trade_date
            )
        if failed_event:
            failed_event_dates.append(quote.trade_date)
        if evaluation.event_type is not None:
            events.append(
                ReplayEvent(
                    symbol=quotes[0].symbol,
                    trade_date=quote.trade_date,
                    event_type=evaluation.event_type,
                    setup=setup,
                    decision=evaluation.decision,
                    signal_date=evaluation.signal_date,
                    confirmed_date=evaluation.confirmed_date,
                    signal_close=evaluation.signal_close,
                    signal_atr=evaluation.signal_atr,
                    decision_diagnostics=evaluation.decision_diagnostics,
                )
            )

        days.append(
            ReplayDay(
                quotes[0].symbol,
                quote.trade_date,
                setup.state,
                confirmed_event,
                failed_event,
                decision_action,
                evaluation.setup_diagnostics,
            )
        )

    state_date_tuples = {
        state: tuple(dates) for state, dates in state_dates.items()
    }
    decision_date_tuples = {
        action: tuple(dates) for action, dates in decision_dates.items()
    }
    return SymbolReplayReport(
        symbol=quotes[0].symbol,
        market=quotes[0].market,
        days=tuple(days),
        events=tuple(events),
        state_day_counts={
            state: len(dates) for state, dates in state_date_tuples.items()
        },
        state_dates=state_date_tuples,
        confirmed_event_dates=tuple(confirmed_event_dates),
        failed_event_dates=tuple(failed_event_dates),
        decision_counts={
            action: len(dates) for action, dates in decision_date_tuples.items()
        },
        decision_dates=decision_date_tuples,
    )


def replay_setup03_symbols(
    symbol_quotes: dict[str, list[Quote]],
    risk_capital: float,
    setup_parameters: dict | None = None,
    decision_parameters: dict | None = None,
) -> dict[str, SymbolReplayReport]:
    return {
        symbol: replay_setup03_history(
            quotes, risk_capital, setup_parameters, decision_parameters
        )
        for symbol, quotes in symbol_quotes.items()
    }


def replay_summary_rows(
    reports: Iterable[SymbolReplayReport],
) -> list[dict]:
    return [report.summary_row() for report in reports]


def replay_event_rows(
    report: SymbolReplayReport,
    historical_source: str,
    parameter_version: str,
    parameter_snapshot: str,
) -> list[dict]:
    """Project the read-only terminal-event ledger into artifact fields."""
    rows: list[dict] = []
    for event in report.events:
        decision = event.decision
        entry = decision.entry_plan if decision is not None else None
        rr = decision.rr if decision is not None else None
        targets = decision.targets if decision is not None else ()
        ratios = rr.rr_ratios if rr is not None else ()
        rows.append(
            {
                "统一代码": event.symbol,
                "交易日期": event.trade_date,
                "事件类型": event.event_type.value,
                "signal_date": event.signal_date,
                "confirmed_date": event.confirmed_date,
                "signal_close": event.signal_close,
                "ATR": event.signal_atr,
                "Setup状态": event.setup.state.value,
                "detected_index": event.setup.detected_index,
                "state_entered_index": event.setup.state_entered_index,
                "confirmed_index": event.setup.confirmed_index,
                "突破价": event.setup.breakout_price,
                "结构失效价": event.setup.structural_invalidation,
                "Decision动作": decision.action.value if decision else None,
                "计划入场": entry.planned_entry if entry else None,
                "执行止损": decision.execution_stop if decision else None,
                "T1": targets[0] if targets else None,
                "T1_RR": ratios[0] if ratios else None,
                "T2": targets[1] if len(targets) > 1 else None,
                "T2_RR": ratios[1] if len(ratios) > 1 else None,
                "T3": targets[2] if len(targets) > 2 else None,
                "T3_RR": ratios[2] if len(ratios) > 2 else None,
                "历史数据源": historical_source,
                "参数版本": parameter_version,
                "参数快照": parameter_snapshot,
            }
        )
    return rows


def validate_replay_history(
    quotes: list[Quote],
    *,
    as_of_date: date,
    expected_latest_date: date | None,
    minimum_rows: int,
    max_calendar_gap_days: int,
    max_latest_lag_days: int,
) -> None:
    """Apply replay-only history quality gates without correcting source data."""
    if not quotes:
        raise ValueError("历史数据为空")
    dates = [quote.trade_date for quote in quotes]
    seen: set[date] = set()
    for trade_date in dates:
        if trade_date in seen:
            raise ValueError(f"历史数据存在重复日期：{trade_date.isoformat()}")
        seen.add(trade_date)
    for previous, current in zip(dates, dates[1:]):
        if current < previous:
            raise ValueError(
                "历史数据日期乱序："
                f"{previous.isoformat()}之后出现{current.isoformat()}"
            )
    validate_quote_series(quotes)

    if minimum_rows < 1:
        raise ValueError(f"minimum_rows必须>=1：{minimum_rows}")
    if len(quotes) < minimum_rows:
        raise ValueError(
            f"历史样本不足：实际{len(quotes)}，至少需要{minimum_rows}"
        )
    latest_date = dates[-1]
    if latest_date > as_of_date:
        raise ValueError(
            f"历史数据包含未来日期：{latest_date.isoformat()}>{as_of_date.isoformat()}"
        )
    if expected_latest_date is not None and latest_date != expected_latest_date:
        raise ValueError(
            f"历史数据最新日期{latest_date.isoformat()}与期望交易日"
            f"{expected_latest_date.isoformat()}不一致"
        )
    latest_lag = (as_of_date - latest_date).days
    if latest_lag > max_latest_lag_days:
        raise ValueError(
            f"历史数据最新日期滞后{latest_lag}天，超过{max_latest_lag_days}天"
        )
    for previous, current in zip(dates, dates[1:]):
        gap = (current - previous).days
        if gap > max_calendar_gap_days:
            raise ValueError(
                "历史数据存在异常缺口："
                f"{previous.isoformat()}至{current.isoformat()}相隔{gap}天，"
                f"超过{max_calendar_gap_days}天"
            )


def _join_dates(dates: Iterable[date]) -> str:
    return ",".join(day.isoformat() for day in dates)

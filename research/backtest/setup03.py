"""SETUP_03 T+1 execution research and parameter diagnostics.

The input event ledger is produced by ``trading.events`` through
``trading.replay``. This module deliberately has no terminal-event detector and
does not call Setup or Decision engines for an individual outcome.

Decision and execution chronology
---------------------------------
On signal day T, a CONFIRMED event first receives its production as-of Decision.
Only ``DecisionAction.ENTRY_ALLOWED`` becomes a candidate for T+1 execution. On
T+1, and only then, the open is classified as below breakout, executable inside
the entry zone, or above the entry zone. CONFIRMED therefore does not imply an
executed trade.

Research exit convention
------------------------
The production system does not yet define position management. For diagnostics
only, an executed trade observes at most 20 trading sessions from T+1. The first
touch of the execution stop or T1 closes the diagnostic trade. If both are
touched in one daily bar, stop is assumed first. If neither is touched after 20
sessions, the 20D close is marked to market. A shorter unresolved tail is
censored and excluded from R-based aggregate statistics.

Daily OHLC cannot establish the order of an exit-bar high and low. Excursions
therefore use full OHLC only for bars strictly before the exit bar. On a STOP
bar, the adverse endpoint is capped at the stop and the uncertain favorable
high is excluded. On a T1 bar, favorable excursion is capped at T1 and the bar
low is retained as the conservative possible pre-exit adverse path. Prices
beyond the first barrier are never treated as held-price excursion.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from enum import Enum
from itertools import product
from statistics import fmean
from typing import Iterable, Sequence

from core import Quote
from trading.decision import DecisionGateReason
from trading.models import DecisionAction, SetupState, validate_quote_series
from trading.replay import ReplayEvent, SymbolReplayReport, replay_setup03_history


FORWARD_HORIZON = 20
SENSITIVITY_SWING_LOOKBACKS = (3, 5, 7)
SENSITIVITY_PLATFORM_WINDOWS = (30, 40, 60)
SENSITIVITY_PLATFORM_TOLERANCES = (0.005, 0.01, 0.015, 0.02, 0.03, 0.05)
DECISION_GATE_REASONS = tuple(DecisionGateReason)


class ExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    SKIP_SIGNAL_NOT_ENTRY_ALLOWED = "SKIP_SIGNAL_NOT_ENTRY_ALLOWED"
    SKIP_NO_T_PLUS_1_BAR = "SKIP_NO_T_PLUS_1_BAR"
    SKIP_GAP_BELOW_BREAKOUT = "SKIP_GAP_BELOW_BREAKOUT"
    SKIP_GAP_ABOVE_ENTRY_ZONE = "SKIP_GAP_ABOVE_ENTRY_ZONE"


@dataclass(frozen=True)
class Setup03TradeOutcome:
    symbol: str
    market: str
    signal_date: date
    confirmed_date: date
    t_plus_1_date: date | None
    execution_status: ExecutionStatus
    t_plus_1_open: float | None
    actual_entry: float | None
    entry_zone_high: float | None
    stop: float | None
    targets: tuple[float, ...]
    return_5d: float | None = None
    return_10d: float | None = None
    return_20d: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    mfe_r: float | None = None
    mae_r: float | None = None
    first_exit_event: str | None = None
    first_exit_date: date | None = None
    final_r: float | None = None
    # Actual observed holding bars from T+1 through first exit (inclusive).
    # Without an exit this is the available forward-bar count, capped at 20.
    observation_days: int = 0
    horizon_complete: bool = False

    def to_row(self) -> dict:
        row = {
            "symbol": self.symbol,
            "market": self.market,
            "signal_date": self.signal_date,
            "confirmed_date": self.confirmed_date,
            "T+1_date": self.t_plus_1_date,
            "execution_status": self.execution_status.value,
            "T+1_open": self.t_plus_1_open,
            "actual_entry": self.actual_entry,
            "entry_zone_high": self.entry_zone_high,
            "stop": self.stop,
            "5D_return": self.return_5d,
            "10D_return": self.return_10d,
            "20D_return": self.return_20d,
            "MFE_pct": self.mfe_pct,
            "MAE_pct": self.mae_pct,
            "MFE_R": self.mfe_r,
            "MAE_R": self.mae_r,
            "first_exit_event": self.first_exit_event,
            "first_exit_date": self.first_exit_date,
            "final_R": self.final_r,
            "observation_days": self.observation_days,
            "horizon_complete": self.horizon_complete,
        }
        row.update(_target_columns(self.targets))
        return row


@dataclass(frozen=True)
class Setup03ResearchReport:
    symbol: str
    market: str
    confirmed_count: int
    outcomes: tuple[Setup03TradeOutcome, ...]

    @property
    def executed_count(self) -> int:
        return sum(
            outcome.execution_status is ExecutionStatus.EXECUTED
            for outcome in self.outcomes
        )


@dataclass(frozen=True)
class Setup03ParameterArtifacts:
    """Unranked Phase 5B metrics plus Phase 5C Decision gate projections."""

    sensitivity_rows: tuple[dict, ...]
    decision_gate_rows: tuple[dict, ...]
    decision_gate_summary_rows: tuple[dict, ...]


def research_trade_outcomes(
    replay_report: SymbolReplayReport,
    quotes: list[Quote],
) -> Setup03ResearchReport:
    """Consume the shared CONFIRMED event ledger and apply T+1 open rules."""
    validate_quote_series(quotes)
    confirmed_events = tuple(
        event
        for event in replay_report.events
        if event.event_type is SetupState.CONFIRMED
    )
    outcomes = tuple(
        _simulate_event(event, replay_report.market, quotes)
        for event in confirmed_events
    )
    return Setup03ResearchReport(
        replay_report.symbol,
        replay_report.market,
        len(confirmed_events),
        outcomes,
    )


def parameter_sensitivity_rows(
    symbol_quotes: dict[str, list[Quote]],
    risk_capital: float,
    production_setup_parameters: dict,
    decision_parameters: dict,
    swing_lookbacks: Sequence[int] = SENSITIVITY_SWING_LOOKBACKS,
    platform_windows: Sequence[int] = SENSITIVITY_PLATFORM_WINDOWS,
    platform_tolerances: Sequence[float] = SENSITIVITY_PLATFORM_TOLERANCES,
) -> list[dict]:
    """Run the declared research grid in stable order without ranking it."""
    return list(
        parameter_sensitivity_artifacts(
            symbol_quotes,
            risk_capital,
            production_setup_parameters,
            decision_parameters,
            swing_lookbacks,
            platform_windows,
            platform_tolerances,
        ).sensitivity_rows
    )


def parameter_sensitivity_artifacts(
    symbol_quotes: dict[str, list[Quote]],
    risk_capital: float,
    production_setup_parameters: dict,
    decision_parameters: dict,
    swing_lookbacks: Sequence[int] = SENSITIVITY_SWING_LOOKBACKS,
    platform_windows: Sequence[int] = SENSITIVITY_PLATFORM_WINDOWS,
    platform_tolerances: Sequence[float] = SENSITIVITY_PLATFORM_TOLERANCES,
) -> Setup03ParameterArtifacts:
    """Run each grid cell once and project both performance and gate diagnostics."""
    rows: list[dict] = []
    diagnostic_rows: list[dict] = []
    diagnostic_summary_rows: list[dict] = []
    input_bar_count = sum(len(quotes) for quotes in symbol_quotes.values())
    for swing_lookback, platform_window, tolerance in product(
        swing_lookbacks, platform_windows, platform_tolerances
    ):
        research_setup_parameters = dict(production_setup_parameters)
        research_setup_parameters.update(
            swing_lookback=swing_lookback,
            platform_window=platform_window,
            platform_tolerance_pct=tolerance,
        )
        report_pairs: list[tuple[SymbolReplayReport, Setup03ResearchReport]] = []
        for quotes in symbol_quotes.values():
            replay_report = replay_setup03_history(
                quotes,
                risk_capital,
                research_setup_parameters,
                decision_parameters,
            )
            research_report = research_trade_outcomes(replay_report, quotes)
            report_pairs.append((replay_report, research_report))

        outcomes = [
            outcome
            for _, research_report in report_pairs
            for outcome in research_report.outcomes
        ]
        executed = [
            outcome
            for outcome in outcomes
            if outcome.execution_status is ExecutionStatus.EXECUTED
        ]
        observed = [outcome for outcome in executed if outcome.final_r is not None]
        final_rs = [outcome.final_r for outcome in observed]
        mfe_rs = [outcome.mfe_r for outcome in observed if outcome.mfe_r is not None]
        mae_rs = [outcome.mae_r for outcome in observed if outcome.mae_r is not None]
        funnel_rows = [
            research_funnel_counts(replay_report, research_report)
            for replay_report, research_report in report_pairs
        ]
        funnel = {
            key: sum(row[key] for row in funnel_rows)
            for key in _FUNNEL_COUNT_FIELDS
        }
        cell_diagnostics = decision_gate_diagnostic_rows(
            (replay_report for replay_report, _ in report_pairs),
            swing_lookback,
            platform_window,
            tolerance,
        )
        diagnostic_rows.extend(cell_diagnostics)
        diagnostic_summary_rows.append(
            decision_gate_summary_row(
                cell_diagnostics,
                swing_lookback,
                platform_window,
                tolerance,
            )
        )
        rows.append(
            {
                "setup_swing_lookback": swing_lookback,
                "platform_window": platform_window,
                "platform_tolerance_pct": tolerance,
                "symbol_count": len(symbol_quotes),
                "input_bar_count": input_bar_count,
                "sample_size": len(observed),
                **funnel,
                "censored_count": len(executed) - len(observed),
                **_performance_metrics(final_rs, mfe_rs, mae_rs),
            }
        )
    return Setup03ParameterArtifacts(
        tuple(rows), tuple(diagnostic_rows), tuple(diagnostic_summary_rows)
    )


def decision_gate_diagnostic_rows(
    replay_reports: Iterable[SymbolReplayReport],
    setup_swing_lookback: int,
    platform_window: int,
    platform_tolerance_pct: float,
) -> list[dict]:
    """Project one conserved row per CONFIRMED event without recalculation."""
    rows: list[dict] = []
    for report in replay_reports:
        for event in report.events:
            if event.event_type is not SetupState.CONFIRMED:
                continue
            decision = event.decision
            diagnostics = event.decision_diagnostics
            action = decision.action if decision is not None else None
            if diagnostics is not None:
                reason = diagnostics.reason
            elif action is DecisionAction.ENTRY_ALLOWED:
                reason = DecisionGateReason.ENTRY_ALLOWED
            else:
                # Preserve an unexplained rejection instead of dropping it.
                reason = DecisionGateReason.OTHER_NO_TRADE
            if (reason is DecisionGateReason.ENTRY_ALLOWED) != (
                action is DecisionAction.ENTRY_ALLOWED
            ):
                raise ValueError("Decision action and gate reason are inconsistent")

            entry = decision.entry_plan if decision is not None else None
            targets = decision.targets if decision is not None else ()
            rr = decision.rr if decision is not None else None
            ratios = rr.rr_ratios if rr is not None else ()
            rows.append(
                {
                    "symbol": event.symbol,
                    "signal_date": event.signal_date,
                    "confirmed_date": event.confirmed_date,
                    "setup_swing_lookback": setup_swing_lookback,
                    "platform_window": platform_window,
                    "platform_tolerance_pct": platform_tolerance_pct,
                    "breakout_price": event.setup.breakout_price,
                    "structural_invalidation": event.setup.structural_invalidation,
                    "signal_close": event.signal_close,
                    "ATR": diagnostics.atr if diagnostics else event.signal_atr,
                    "decision_action": action.value if action else None,
                    "decision_gate_reason": reason.value,
                    "planned_entry": (
                        diagnostics.planned_entry
                        if diagnostics is not None
                        else (entry.planned_entry if entry else event.signal_close)
                    ),
                    "entry_zone_low": (
                        diagnostics.entry_zone_low
                        if diagnostics is not None
                        else (entry.entry_zone_low if entry else None)
                    ),
                    "entry_zone_high": (
                        diagnostics.entry_zone_high
                        if diagnostics is not None
                        else (entry.entry_zone_high if entry else None)
                    ),
                    "execution_stop": (
                        diagnostics.execution_stop
                        if diagnostics is not None
                        else (decision.execution_stop if decision else None)
                    ),
                    "T1": targets[0] if targets else None,
                    "T1_RR": ratios[0] if ratios else None,
                    "decision_index": (
                        diagnostics.decision_index if diagnostics else None
                    ),
                    "confirmed_index": event.setup.confirmed_index,
                }
            )
    return rows


def decision_gate_summary_row(
    diagnostic_rows: Sequence[dict],
    setup_swing_lookback: int,
    platform_window: int,
    platform_tolerance_pct: float,
) -> dict:
    """Aggregate a grid cell and enforce CONFIRMED reason conservation."""
    counts = Counter(row["decision_gate_reason"] for row in diagnostic_rows)
    confirmed = len(diagnostic_rows)
    known_values = {reason.value for reason in DECISION_GATE_REASONS}
    unknown = sum(count for value, count in counts.items() if value not in known_values)
    if unknown:
        raise ValueError("unknown Decision gate reason must be mapped to OTHER_NO_TRADE")
    row = {
        "setup_swing_lookback": setup_swing_lookback,
        "platform_window": platform_window,
        "platform_tolerance_pct": platform_tolerance_pct,
        "CONFIRMED": confirmed,
        "ENTRY_ALLOWED": counts[DecisionGateReason.ENTRY_ALLOWED.value],
    }
    for reason in DECISION_GATE_REASONS:
        count = counts[reason.value]
        row[f"{reason.value}_count"] = count
        row[f"{reason.value}_ratio"] = count / confirmed if confirmed else 0.0
    if confirmed != sum(row[f"{reason.value}_count"] for reason in DECISION_GATE_REASONS):
        raise ValueError("CONFIRMED count does not conserve across Decision reasons")
    return row


def _simulate_event(
    event: ReplayEvent,
    market: str,
    quotes: list[Quote],
) -> Setup03TradeOutcome:
    if event.signal_date is None or event.confirmed_date is None:
        raise ValueError("CONFIRMED event contract is missing signal/confirmed date")
    confirmed_index = event.setup.confirmed_index
    if confirmed_index is None or confirmed_index >= len(quotes):
        raise ValueError("CONFIRMED event contract has an invalid confirmed_index")
    if quotes[confirmed_index].trade_date != event.confirmed_date:
        raise ValueError("CONFIRMED event date does not match its as-of quote")

    decision = event.decision
    entry_plan = decision.entry_plan if decision is not None else None
    stop = decision.execution_stop if decision is not None else None
    targets = decision.targets if decision is not None else ()
    common = {
        "symbol": event.symbol,
        "market": market,
        "signal_date": event.signal_date,
        "confirmed_date": event.confirmed_date,
        "entry_zone_high": (
            entry_plan.entry_zone_high if entry_plan is not None else None
        ),
        "stop": stop,
        "targets": targets,
    }
    # T-day production Decision is the prerequisite gate. A rejected signal is
    # never allowed to fall through to T+1 availability or gap classification.
    if (
        decision is None
        or decision.action is not DecisionAction.ENTRY_ALLOWED
        or entry_plan is None
        or stop is None
        or not targets
    ):
        return Setup03TradeOutcome(
            **common,
            t_plus_1_date=None,
            execution_status=ExecutionStatus.SKIP_SIGNAL_NOT_ENTRY_ALLOWED,
            t_plus_1_open=None,
            actual_entry=None,
        )

    next_index = confirmed_index + 1
    if next_index >= len(quotes):
        return Setup03TradeOutcome(
            **common,
            t_plus_1_date=None,
            execution_status=ExecutionStatus.SKIP_NO_T_PLUS_1_BAR,
            t_plus_1_open=None,
            actual_entry=None,
        )

    next_quote = quotes[next_index]
    next_open = float(next_quote.open)
    next_common = {
        **common,
        "t_plus_1_date": next_quote.trade_date,
        "t_plus_1_open": next_open,
    }
    breakout_price = event.setup.breakout_price
    if breakout_price is None:
        raise ValueError("CONFIRMED event contract is missing breakout_price")
    if next_open < breakout_price:
        return Setup03TradeOutcome(
            **next_common,
            execution_status=ExecutionStatus.SKIP_GAP_BELOW_BREAKOUT,
            actual_entry=None,
        )
    if next_open > entry_plan.entry_zone_high:
        return Setup03TradeOutcome(
            **next_common,
            execution_status=ExecutionStatus.SKIP_GAP_ABOVE_ENTRY_ZONE,
            actual_entry=None,
        )

    path = quotes[next_index : next_index + FORWARD_HORIZON]
    return _executed_outcome(event, market, next_quote, next_open, path)


def _executed_outcome(
    event: ReplayEvent,
    market: str,
    execution_quote: Quote,
    actual_entry: float,
    path: list[Quote],
) -> Setup03TradeOutcome:
    assert event.signal_date is not None
    assert event.confirmed_date is not None
    assert event.decision is not None
    assert event.decision.entry_plan is not None
    assert event.decision.execution_stop is not None
    stop = event.decision.execution_stop
    targets = event.decision.targets
    risk_per_share = actual_entry - stop
    if risk_per_share <= 0:
        raise ValueError("T+1 actual_entry must be above the execution stop")

    forward_returns = {
        days: _forward_return(path, days, actual_entry) for days in (5, 10, 20)
    }
    first_exit_event = None
    first_exit_date = None
    final_r = None
    exit_index = None
    for index, quote in enumerate(path):
        if float(quote.low) <= stop:
            first_exit_event = "STOP"
            first_exit_date = quote.trade_date
            final_r = -1.0
            exit_index = index
            break
        if float(quote.high) >= targets[0]:
            first_exit_event = "T1"
            first_exit_date = quote.trade_date
            final_r = (targets[0] - actual_entry) / risk_per_share
            exit_index = index
            break

    horizon_complete = len(path) == FORWARD_HORIZON
    if final_r is None and horizon_complete:
        first_exit_event = "MARK_TO_MARKET_20D"
        first_exit_date = path[-1].trade_date
        final_r = (float(path[-1].close) - actual_entry) / risk_per_share
    elif final_r is None:
        first_exit_event = "CENSORED_END_OF_DATA"

    if exit_index is None:
        excursion_highs = [float(quote.high) for quote in path]
        excursion_lows = [float(quote.low) for quote in path]
        observation_days = len(path)
    else:
        # Full OHLC is safe only for bars strictly before the exit bar. The
        # exit-bar convention below does not invent an intraday ordering.
        pre_exit_path = path[:exit_index]
        excursion_highs = [float(quote.high) for quote in pre_exit_path]
        excursion_lows = [float(quote.low) for quote in pre_exit_path]
        exit_quote = path[exit_index]
        observation_days = exit_index + 1
        if first_exit_event == "STOP":
            # The stop is known to be reached; any lower price is necessarily
            # beyond that barrier. The uncertain same-bar high is excluded.
            excursion_lows.append(stop)
        else:
            assert first_exit_event == "T1"
            # T1 is the most favorable held price. The low stayed above stop,
            # but may have occurred before T1, so retain it as worst case.
            excursion_highs.append(targets[0])
            excursion_lows.append(float(exit_quote.low))
    max_high = max([actual_entry, *excursion_highs])
    min_low = min([actual_entry, *excursion_lows])
    favorable_move = max(max_high - actual_entry, 0.0)
    adverse_move = min(min_low - actual_entry, 0.0)
    return Setup03TradeOutcome(
        symbol=event.symbol,
        market=market,
        signal_date=event.signal_date,
        confirmed_date=event.confirmed_date,
        t_plus_1_date=execution_quote.trade_date,
        execution_status=ExecutionStatus.EXECUTED,
        t_plus_1_open=actual_entry,
        actual_entry=actual_entry,
        entry_zone_high=event.decision.entry_plan.entry_zone_high,
        stop=stop,
        targets=targets,
        return_5d=forward_returns[5],
        return_10d=forward_returns[10],
        return_20d=forward_returns[20],
        mfe_pct=favorable_move / actual_entry,
        mae_pct=adverse_move / actual_entry,
        mfe_r=favorable_move / risk_per_share,
        mae_r=adverse_move / risk_per_share,
        first_exit_event=first_exit_event,
        first_exit_date=first_exit_date,
        final_r=final_r,
        observation_days=observation_days,
        horizon_complete=horizon_complete,
    )


_FUNNEL_COUNT_FIELDS = (
    "confirmed_count",
    "entry_allowed_count",
    "signal_not_entry_allowed_count",
    "skip_no_t1_count",
    "skip_gap_below_breakout_count",
    "skip_gap_above_entry_zone_count",
    "executed_count",
    "other_execution_status_count",
)


def research_funnel_counts(
    replay_report: SymbolReplayReport,
    research_report: Setup03ResearchReport,
) -> dict[str, int]:
    """Return a conserved CONFIRMED -> Decision -> T+1 execution funnel."""
    confirmed_events = tuple(
        event
        for event in replay_report.events
        if event.event_type is SetupState.CONFIRMED
    )
    if research_report.confirmed_count != len(confirmed_events):
        raise ValueError("research report CONFIRMED count does not match replay events")
    if len(research_report.outcomes) != len(confirmed_events):
        raise ValueError("each CONFIRMED event must have exactly one research outcome")

    entry_allowed_count = sum(
        event.decision is not None
        and event.decision.action is DecisionAction.ENTRY_ALLOWED
        for event in confirmed_events
    )
    status_counts = Counter(
        outcome.execution_status for outcome in research_report.outcomes
    )
    mapped_statuses = {
        ExecutionStatus.EXECUTED,
        ExecutionStatus.SKIP_SIGNAL_NOT_ENTRY_ALLOWED,
        ExecutionStatus.SKIP_NO_T_PLUS_1_BAR,
        ExecutionStatus.SKIP_GAP_BELOW_BREAKOUT,
        ExecutionStatus.SKIP_GAP_ABOVE_ENTRY_ZONE,
    }
    other_execution_status_count = sum(
        count for status, count in status_counts.items() if status not in mapped_statuses
    )
    funnel = {
        "confirmed_count": len(confirmed_events),
        "entry_allowed_count": entry_allowed_count,
        "signal_not_entry_allowed_count": len(confirmed_events)
        - entry_allowed_count,
        "skip_no_t1_count": status_counts[ExecutionStatus.SKIP_NO_T_PLUS_1_BAR],
        "skip_gap_below_breakout_count": status_counts[
            ExecutionStatus.SKIP_GAP_BELOW_BREAKOUT
        ],
        "skip_gap_above_entry_zone_count": status_counts[
            ExecutionStatus.SKIP_GAP_ABOVE_ENTRY_ZONE
        ],
        "executed_count": status_counts[ExecutionStatus.EXECUTED],
        "other_execution_status_count": other_execution_status_count,
    }
    rejected_outcomes = status_counts[
        ExecutionStatus.SKIP_SIGNAL_NOT_ENTRY_ALLOWED
    ]
    if rejected_outcomes != funnel["signal_not_entry_allowed_count"]:
        raise ValueError("Decision gate and research execution statuses are inconsistent")
    t_plus_1_candidates = (
        funnel["skip_no_t1_count"]
        + funnel["skip_gap_below_breakout_count"]
        + funnel["skip_gap_above_entry_zone_count"]
        + funnel["executed_count"]
        + funnel["other_execution_status_count"]
    )
    if funnel["entry_allowed_count"] != t_plus_1_candidates:
        raise ValueError("ENTRY_ALLOWED count does not conserve across T+1 outcomes")
    if funnel["confirmed_count"] != (
        funnel["signal_not_entry_allowed_count"] + t_plus_1_candidates
    ):
        raise ValueError("CONFIRMED count does not conserve across the research funnel")
    return funnel


def _forward_return(path: list[Quote], days: int, entry: float) -> float | None:
    if len(path) < days:
        return None
    return float(path[days - 1].close) / entry - 1.0


def _performance_metrics(
    final_rs: list[float],
    mfe_rs: list[float],
    mae_rs: list[float],
) -> dict:
    wins = [value for value in final_rs if value > 0]
    losses = [value for value in final_rs if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    average_r = fmean(final_rs) if final_rs else None
    return {
        "win_rate": len(wins) / len(final_rs) if final_rs else None,
        "avg_R": average_r,
        "expectancy": average_r,
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else (math.inf if gross_profit > 0 else None)
        ),
        "MFE": fmean(mfe_rs) if mfe_rs else None,
        "MAE": fmean(mae_rs) if mae_rs else None,
    }


def _target_columns(targets: Sequence[float]) -> dict:
    return {
        "T1": targets[0] if len(targets) > 0 else None,
        "T2": targets[1] if len(targets) > 1 else None,
        "T3": targets[2] if len(targets) > 2 else None,
    }

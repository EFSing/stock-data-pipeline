"""Research-only management, cost and sizing engine for the SETUP_01 stage-2 study.

This module implements exactly the policy registered in
``research/protocols/setup01_early_entry_stage2_economic_validation_v1.json``.  It is an
adapter, not a production rule: it reuses frozen primitives (quote series, market
sessions, ATR, Wave/Swing identity and the production Decision geometry) and adds the
pre-registered research management policy, cost model and single-trade sizing.

Declared differences from ``trading/position_management.py`` are recorded in the protocol
and repeated in the study artifact: targets act as exits here, no MFE profit-protection
floor and no confirmed-higher-low stop raises are applied, and no Wave5/risk advisory is
computed.  No production module is imported for mutation and none is modified.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

from core import Quote


IDENTITY_A = "A_FULL_INCUMBENT"
IDENTITY_B = "B_FIRST_CONFIRMED_STRUCTURAL"
IDENTITY_C = "C_ARMED_CONSTRAINED_PKG_B"
IDENTITY_IDS = (IDENTITY_A, IDENTITY_B, IDENTITY_C)

SCENARIO_BASELINE = "BASELINE"
SCENARIO_STRESS = "STRESS"
SCENARIO_SPREAD_BP = {SCENARIO_BASELINE: 10.0, SCENARIO_STRESS: 25.0}
SCENARIO_IDS = (SCENARIO_BASELINE, SCENARIO_STRESS)

RISK_FRACTION = 0.005
STANDARDISED_RESEARCH_BUDGET = {"CN": 1_000_000.0, "US": 100_000.0}
LOT_SIZE = {"CN": 100, "US": 1}

CN_COMMISSION_BP_PER_SIDE = 2.5
CN_MINIMUM_COMMISSION = 5.0
CN_STAMP_DUTY_CUT_DATE = "2023-08-28"
CN_STAMP_DUTY_BP_BEFORE = 10.0
CN_STAMP_DUTY_BP_FROM = 5.0
CN_PRICE_LIMIT_PCT = 0.10
CN_LIMIT_PRICE_TOLERANCE = 0.005

US_SEC_FEE_BP_PER_SELL = 0.3
US_TAF_PER_SHARE_SELL = 0.000166
US_TAF_CAP = 8.30

EXIT_GAP_BELOW_STOP = "EXIT_GAP_BELOW_STOP"
EXIT_STOP_TRIGGERED = "EXIT_STOP_TRIGGERED"
EXIT_TARGET_T1_REACHED = "EXIT_TARGET_T1_REACHED"
EXIT_STRUCTURAL_INVALIDATION = "EXIT_STRUCTURAL_INVALIDATION"
EXIT_LIFECYCLE_TERMINATED = "EXIT_LIFECYCLE_TERMINATED"
EXIT_PRE_CONFIRMATION_TIMEOUT = "EXIT_PRE_CONFIRMATION_TIMEOUT"
CENSORED_AT_DATA_END = "CENSORED_AT_DATA_END"

FLAG_MODEL_ONLY_LIMIT_AT_ENTRY = "MODEL_ONLY_LIMIT_AT_ENTRY"
FLAG_MODEL_ONLY_LIMIT_DOWN_AT_EXIT = "MODEL_ONLY_LIMIT_DOWN_AT_EXIT"
FLAG_LIMIT_DATA_UNAVAILABLE = "LIMIT_DATA_UNAVAILABLE"
FLAG_ZERO_VOLUME_AT_ENTRY = "ZERO_VOLUME_AT_ENTRY"
FLAG_GAP_UP_THROUGH_TARGET_MODELED_AT_TARGET = "GAP_UP_THROUGH_TARGET_MODELED_AT_TARGET"
FLAG_NO_VALID_TARGET_AT_CONFIRMATION = "NO_VALID_TARGET_AT_CONFIRMATION"
FLAG_CONFIRMATION_DECISION_UNAVAILABLE = "CONFIRMATION_DECISION_UNAVAILABLE"
FLAG_STRUCTURAL_EXIT_AFTER_CONFIRMATION = "STRUCTURAL_EXIT_AFTER_CONFIRMATION"

SKIP_NO_NEXT_SESSION_BAR = "SKIP_NO_NEXT_SESSION_BAR"
SKIP_INVALID_OPEN = "SKIP_INVALID_OPEN"
SKIP_OPEN_AT_OR_BELOW_WAVE2_LOW = "SKIP_OPEN_AT_OR_BELOW_WAVE2_LOW"
SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP = "SKIP_OPEN_AT_OR_BELOW_EXECUTION_STOP"
SKIP_LIFECYCLE_TERMINATED_BEFORE_ENTRY = "SKIP_LIFECYCLE_TERMINATED_BEFORE_ENTRY"
SKIP_ZERO_VOLUME_AT_ENTRY = "SKIP_ZERO_VOLUME_AT_ENTRY"
NOT_EVALUABLE_NO_ATR = "NOT_EVALUABLE_NO_ATR"
NOT_EVALUABLE_NO_STOP_GEOMETRY = "NOT_EVALUABLE_NO_STOP_GEOMETRY"
NOT_EXECUTABLE_AT_RESEARCH_BUDGET = "NOT_EXECUTABLE_AT_RESEARCH_BUDGET"

TIMEOUT_SESSIONS = 20


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass(frozen=True)
class SizedTrade:
    quantity: float
    risk_capital: float
    notional: float
    lot_size: int


def size_position(
    market: str,
    entry: float,
    execution_stop: float,
) -> SizedTrade | None:
    """Standardised research sizing: 0.5% of a fixed research budget over 1R."""
    risk_per_share = float(entry) - float(execution_stop)
    if not math.isfinite(risk_per_share) or risk_per_share <= 0:
        return None
    budget = STANDARDISED_RESEARCH_BUDGET.get(market)
    lot = LOT_SIZE.get(market)
    if budget is None or lot is None:
        raise ValueError(f"unsupported market for sizing: {market}")
    risk_capital = budget * RISK_FRACTION
    quantity = math.floor(risk_capital / risk_per_share / lot) * lot
    if quantity <= 0:
        return None
    return SizedTrade(
        quantity=float(quantity),
        risk_capital=risk_capital,
        notional=float(quantity) * float(entry),
        lot_size=lot,
    )


def _commission_per_share(market: str, price: float, quantity: float) -> float:
    if market != "CN":
        return 0.0
    amount = float(price) * float(quantity)
    commission = max(amount * CN_COMMISSION_BP_PER_SIDE / 10_000.0, CN_MINIMUM_COMMISSION)
    return commission / float(quantity)


def buy_cost_per_share(
    market: str,
    price: float,
    quantity: float,
    scenario: str,
) -> float:
    spread_bp = SCENARIO_SPREAD_BP[scenario]
    return float(price) * spread_bp / 10_000.0 + _commission_per_share(
        market, price, quantity
    )


def sell_cost_per_share(
    market: str,
    price: float,
    quantity: float,
    trade_date: str,
    scenario: str,
) -> float:
    spread_bp = SCENARIO_SPREAD_BP[scenario]
    cost = float(price) * spread_bp / 10_000.0 + _commission_per_share(
        market, price, quantity
    )
    if market == "CN":
        stamp_bp = (
            CN_STAMP_DUTY_BP_FROM
            if str(trade_date) >= CN_STAMP_DUTY_CUT_DATE
            else CN_STAMP_DUTY_BP_BEFORE
        )
        cost += float(price) * stamp_bp / 10_000.0
    else:
        cost += float(price) * US_SEC_FEE_BP_PER_SELL / 10_000.0
        taf = min(float(quantity) * US_TAF_PER_SHARE_SELL, US_TAF_CAP)
        cost += taf / float(quantity)
    return cost


@dataclass(frozen=True)
class TradeGeometry:
    identity: str
    symbol: str
    market: str
    candidate_key: str
    signal_date: str
    entry_index: int
    entry_date: str
    entry_price: float
    execution_stop: float
    one_r: float
    structural_low: float
    initial_targets: tuple[float, ...]
    confirmation_index: int | None
    confirmation_targets: tuple[float, ...]
    lifecycle_termination_index: int | None
    manage_pre_confirmation: bool


@dataclass(frozen=True)
class TradeOutcome:
    geometry: TradeGeometry
    exit_index: int
    exit_date: str
    exit_price: float
    exit_reason: str
    sessions_held: int
    censored: bool
    flags: tuple[str, ...]
    target_exit_used: bool


def active_targets_for_session(
    geometry: TradeGeometry,
    index: int,
) -> tuple[float, ...]:
    """Return the target set that is causally active on one session."""
    if not geometry.manage_pre_confirmation:
        return geometry.initial_targets
    if geometry.confirmation_index is None:
        return ()
    if index <= geometry.confirmation_index:
        return ()
    return geometry.confirmation_targets


def simulate_trade(
    geometry: TradeGeometry,
    quotes: Sequence[Quote],
    *,
    target_exit_enabled: bool = True,
) -> TradeOutcome:
    """Replay one research position with the pre-registered exit policy."""
    flags: set[str] = set()
    pending_exit: str | None = None
    pre_confirmation_failure = geometry.lifecycle_termination_index
    if (
        geometry.manage_pre_confirmation
        and pre_confirmation_failure is not None
        and pre_confirmation_failure < geometry.entry_index
    ):
        flags.add("LIFECYCLE_TERMINATED_BEFORE_ENTRY")

    for index in range(geometry.entry_index, len(quotes)):
        quote = quotes[index]
        opening = _finite(quote.open)
        if pending_exit is not None:
            if opening is not None and opening > 0:
                return _outcome(
                    geometry,
                    index=index,
                    exit_date=quote.trade_date.isoformat(),
                    exit_price=opening,
                    reason=pending_exit,
                    flags=flags,
                    target_exit_used=target_exit_enabled
                    and pending_exit == EXIT_TARGET_T1_REACHED,
                )
            continue
        if opening is None or opening <= 0:
            continue
        if opening <= geometry.execution_stop:
            return _outcome(
                geometry,
                index=index,
                exit_date=quote.trade_date.isoformat(),
                exit_price=opening,
                reason=EXIT_GAP_BELOW_STOP,
                flags=flags,
                target_exit_used=False,
            )
        low = _finite(quote.low)
        if low is not None and low <= geometry.execution_stop:
            return _outcome(
                geometry,
                index=index,
                exit_date=quote.trade_date.isoformat(),
                exit_price=geometry.execution_stop,
                reason=EXIT_STOP_TRIGGERED,
                flags=flags,
                target_exit_used=False,
            )
        targets = active_targets_for_session(geometry, index)
        high = _finite(quote.high)
        if target_exit_enabled and targets and high is not None and high >= targets[0]:
            if opening > targets[0]:
                flags.add(FLAG_GAP_UP_THROUGH_TARGET_MODELED_AT_TARGET)
            return _outcome(
                geometry,
                index=index,
                exit_date=quote.trade_date.isoformat(),
                exit_price=targets[0],
                reason=EXIT_TARGET_T1_REACHED,
                flags=flags,
                target_exit_used=True,
            )
        close = _finite(quote.close)
        if close is not None and close <= geometry.structural_low:
            if geometry.confirmation_index is not None and index > geometry.confirmation_index:
                flags.add(FLAG_STRUCTURAL_EXIT_AFTER_CONFIRMATION)
            pending_exit = EXIT_STRUCTURAL_INVALIDATION
            continue
        if geometry.manage_pre_confirmation:
            confirmed_within_window = (
                geometry.confirmation_index is not None
                and geometry.confirmation_index
                <= geometry.entry_index + TIMEOUT_SESSIONS - 1
            )
            if (
                pre_confirmation_failure is not None
                and index >= pre_confirmation_failure
                and not confirmed_within_window
            ):
                pending_exit = EXIT_LIFECYCLE_TERMINATED
                continue
            if index == geometry.entry_index + TIMEOUT_SESSIONS - 1 and not confirmed_within_window:
                pending_exit = EXIT_PRE_CONFIRMATION_TIMEOUT
                continue
    return _outcome(
        geometry,
        index=len(quotes) - 1,
        exit_date=quotes[-1].trade_date.isoformat(),
        exit_price=float(quotes[-1].close),
        reason=CENSORED_AT_DATA_END,
        flags=flags,
        target_exit_used=False,
        censored=True,
    )


def _outcome(
    geometry: TradeGeometry,
    *,
    index: int,
    exit_date: str,
    exit_price: float,
    reason: str,
    flags: set[str],
    target_exit_used: bool,
    censored: bool = False,
) -> TradeOutcome:
    return TradeOutcome(
        geometry=geometry,
        exit_index=index,
        exit_date=exit_date,
        exit_price=float(exit_price),
        exit_reason=reason,
        sessions_held=len(range(geometry.entry_index, index + 1)),
        censored=censored,
        flags=tuple(sorted(flags)),
        target_exit_used=target_exit_used,
    )


def trade_economics(
    outcome: TradeOutcome,
    *,
    market: str,
    scenario: str,
    exit_date: str,
    sized: SizedTrade,
) -> dict[str, Any]:
    geometry = outcome.geometry
    buy_cost = buy_cost_per_share(
        market, geometry.entry_price, sized.quantity, scenario
    )
    sell_cost = sell_cost_per_share(
        market, outcome.exit_price, sized.quantity, exit_date, scenario
    )
    gross_pnl = outcome.exit_price - geometry.entry_price
    net_pnl = gross_pnl - buy_cost - sell_cost
    return {
        "scenario": scenario,
        "quantity": sized.quantity,
        "notional": sized.notional,
        "risk_capital": sized.risk_capital,
        "gross_pnl_per_share": gross_pnl,
        "buy_cost_per_share": buy_cost,
        "sell_cost_per_share": sell_cost,
        "total_cost_per_share": buy_cost + sell_cost,
        "net_pnl_per_share": net_pnl,
        "gross_r": gross_pnl / geometry.one_r,
        "net_r": net_pnl / geometry.one_r,
        "gross_return": gross_pnl / geometry.entry_price,
        "net_return": net_pnl / geometry.entry_price,
        "net_pnl_total": net_pnl * sized.quantity,
        "position_days": outcome.sessions_held,
        "capital_time": sized.notional * outcome.sessions_held,
    }


def cn_limit_price(preclose: float, *, up: bool) -> float:
    ratio = 1.0 + CN_PRICE_LIMIT_PCT if up else 1.0 - CN_PRICE_LIMIT_PCT
    return round(float(preclose) * ratio + 1e-9, 2)


def limit_flags(
    *,
    market: str,
    symbol: str,
    entry_open: float,
    entry_preclose: float | None,
    exit_price: float,
    exit_preclose: float | None,
    limit_data_available: bool,
) -> tuple[str, ...]:
    """Flag model-only limit fills; never claims a real fill."""
    if market != "CN":
        return ()
    if not limit_data_available:
        return (FLAG_LIMIT_DATA_UNAVAILABLE,)
    flags: list[str] = []
    if entry_preclose is not None:
        if abs(entry_open - cn_limit_price(entry_preclose, up=True)) <= CN_LIMIT_PRICE_TOLERANCE:
            flags.append(FLAG_MODEL_ONLY_LIMIT_AT_ENTRY)
    if exit_preclose is not None:
        if abs(exit_price - cn_limit_price(exit_preclose, up=False)) <= CN_LIMIT_PRICE_TOLERANCE:
            flags.append(FLAG_MODEL_ONLY_LIMIT_DOWN_AT_EXIT)
    return tuple(flags)


def load_cn_preclose_index(payload_path: Any) -> dict[str, float]:
    """Read the frozen raw BaoStock payload: date -> preclose for one symbol.

    The payload is a local frozen artifact and is never re-acquired.  A missing file
    returns an empty mapping so the caller can flag LIMIT_DATA_UNAVAILABLE instead of
    inventing limit data.
    """
    import json
    from pathlib import Path

    path = Path(payload_path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = list(payload.get("fields", ()))
    if "date" not in fields or "preclose" not in fields:
        return {}
    date_index = fields.index("date")
    preclose_index = fields.index("preclose")
    result: dict[str, float] = {}
    for row in payload.get("rows", ()):
        preclose = _finite(row[preclose_index])
        if preclose is not None and preclose > 0:
            result[str(row[date_index])] = preclose
    return result


def preclose_for_date(index: Mapping[str, float], trade_date: str) -> float | None:
    if not index:
        return None
    return index.get(trade_date)

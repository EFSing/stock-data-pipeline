"""Wave Scenario Engine v1（只读、因果、有限 taxonomy）。

本模块把现有 causal Swing、Market Structure 与 Fibonacci 组合成有限的
结构候选。它不是完整 Elliott Wave 自动数浪器，也不产生 Entry/Decision。

核心时间合同：

* 所有计算先截断到 ``as_of_date``；输入中更晚的 bars 永远不可见。
* 日线只使用该前缀中已经 CONFIRMED 的 Swing。
* 周线由市场真实 session date 聚合；当前 ISO 周默认视为未完成，直到
  后续评估时它已经成为历史周，因此不会把尚未完成的周线 close 带入母级别。
* 证据分数只是满足的显式结构规则数量，不是概率、收益分数或参数优化结果。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Iterable

from core import Quote
from trading.fibonacci import fibonacci_levels, fibonacci_regions
from trading.models import (
    PriceRegion,
    SwingKind,
    SwingPoint,
    SwingState,
    Trend,
    WaveLeg,
    WaveScenario,
    WaveScenarioEvaluation,
    WaveScenarioFamily,
    validate_quote_series,
)
from trading.structure import market_structure
from trading.swing import find_swings


WAVE_ENGINE_PROTOCOL_VERSION = "WAVE-SCENARIO-ENGINE-2026-08-30-v1"
WAVE_ENGINE_VERSION = "1.0.0"


def _week_key(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _aggregate_week(quotes: list[Quote]) -> Quote:
    first = quotes[0]
    last = quotes[-1]
    volumes = [quote.volume for quote in quotes if quote.volume is not None]
    return Quote(
        symbol=first.symbol,
        name=first.name,
        market=first.market,
        trade_date=last.trade_date,
        source=first.source,
        open=first.open,
        high=max(quote.high for quote in quotes),
        low=min(quote.low for quote in quotes),
        close=last.close,
        preclose=first.preclose,
        pct_change=None,
        volume=sum(volumes) if len(volumes) == len(quotes) else None,
        amount=None,
        turnover_rate=None,
        currency=first.currency,
    )


def aggregate_completed_weekly_quotes(
    quotes: list[Quote], as_of_date: date
) -> list[Quote]:
    """按 session date 聚合、并排除截至 t 尚未完成的当前 ISO 周。"""
    bounded = [quote for quote in quotes if quote.trade_date <= as_of_date]
    if not bounded:
        return []
    groups: dict[date, list[Quote]] = defaultdict(list)
    for quote in bounded:
        groups[_week_key(quote.trade_date)].append(quote)

    current_week = _week_key(as_of_date)
    return [
        _aggregate_week(groups[key])
        for key in sorted(groups)
        if key < current_week
    ]


def _confirmed_swings(swings: Iterable[SwingPoint], as_of_index: int) -> tuple[SwingPoint, ...]:
    return tuple(
        swing
        for swing in swings
        if swing.state is SwingState.CONFIRMED
        and swing.confirmed_index is not None
        and swing.confirmed_index <= as_of_index
    )


def _leg(start: SwingPoint, end: SwingPoint) -> WaveLeg:
    direction = "UP" if end.price > start.price else "DOWN"
    return WaveLeg(start=start, end=end, direction=direction)


def _fib_context(
    impulse_start: SwingPoint | None,
    impulse_end: SwingPoint | None,
) -> tuple[tuple[PriceRegion, ...], tuple[PriceRegion, ...]]:
    if impulse_start is None or impulse_end is None:
        return (), ()
    if impulse_start.kind is not SwingKind.LOW or impulse_end.kind is not SwingKind.HIGH:
        return (), ()
    levels = fibonacci_levels(impulse_end, impulse_start)
    return fibonacci_regions(levels)


def _scenario(
    family: WaveScenarioFamily,
    evidence: Iterable[str] = (),
    counter_evidence: Iterable[str] = (),
    confirmed_swings: Iterable[SwingPoint] = (),
    impulse: WaveLeg | None = None,
    retracement: WaveLeg | None = None,
    structural_invalidation: float | None = None,
    invalidation_reason: str = "没有足够结构证据定义失效条件",
    setup01: bool = False,
    setup02: bool = False,
) -> WaveScenario:
    retracement_regions, extension_regions = _fib_context(
        impulse.start if impulse is not None else None,
        impulse.end if impulse is not None else None,
    )
    evidence_tuple = tuple(evidence)
    return WaveScenario(
        family=family,
        evidence=evidence_tuple,
        counter_evidence=tuple(counter_evidence),
        evidence_score=len(evidence_tuple),
        confirmed_swings=tuple(confirmed_swings),
        candidate_impulse_leg=impulse,
        candidate_retracement_leg=retracement,
        fibonacci_retracement_regions=retracement_regions,
        fibonacci_extension_regions=extension_regions,
        structural_invalidation=structural_invalidation,
        scenario_invalidation_reason=invalidation_reason,
        setup01_context_eligible=setup01,
        setup02_context_eligible=setup02,
    )


def _latest_upward_three(swings: tuple[SwingPoint, ...]) -> tuple[SwingPoint, SwingPoint, SwingPoint] | None:
    for index in range(len(swings) - 3, -1, -1):
        first, second, third = swings[index : index + 3]
        if (
            first.kind is SwingKind.LOW
            and second.kind is SwingKind.HIGH
            and third.kind is SwingKind.LOW
        ):
            return first, second, third
    return None


def _latest_abc(
    swings: tuple[SwingPoint, ...],
) -> tuple[SwingPoint, SwingPoint, SwingPoint, SwingPoint, SwingPoint] | None:
    for index in range(len(swings) - 5, -1, -1):
        origin, peak, a_low, b_high, c_low = swings[index : index + 5]
        if (
            origin.kind is SwingKind.LOW
            and peak.kind is SwingKind.HIGH
            and a_low.kind is SwingKind.LOW
            and b_high.kind is SwingKind.HIGH
            and c_low.kind is SwingKind.LOW
        ):
            return origin, peak, a_low, b_high, c_low
    return None


def _upward_expansion(
    swings: tuple[SwingPoint, ...],
) -> tuple[SwingPoint, SwingPoint, SwingPoint, SwingPoint] | None:
    for index in range(len(swings) - 4, -1, -1):
        low0, high1, low2, high3 = swings[index : index + 4]
        if (
            low0.kind is SwingKind.LOW
            and high1.kind is SwingKind.HIGH
            and low2.kind is SwingKind.LOW
            and high3.kind is SwingKind.HIGH
            and high3.price > high1.price
            and low2.price > low0.price
        ):
            return low0, high1, low2, high3
    return None


def _downtrend_scenario(
    weekly_state: Trend,
    daily_state: Trend,
    daily_swings: tuple[SwingPoint, ...],
) -> WaveScenario:
    evidence = []
    counter = []
    if weekly_state is Trend.DOWNTREND:
        evidence.append("weekly structure is DOWNTREND")
    if daily_state is Trend.DOWNTREND:
        evidence.append("daily structure is DOWNTREND")
    if daily_state is Trend.UPTREND:
        counter.append("daily rebound is not allowed to overrule a conflicting parent trend")
    if not evidence:
        evidence.append("long-side structural context is not established")
    return _scenario(
        WaveScenarioFamily.DOWNTREND_OR_INVALID_FOR_LONG,
        evidence=evidence,
        counter_evidence=counter,
        confirmed_swings=daily_swings[-6:],
        invalidation_reason="long scenarios are structurally invalid while the parent or current trend is down",
    )


def _unknown_scenario(
    weekly_state: Trend,
    daily_state: Trend,
    daily_swings: tuple[SwingPoint, ...],
    reason: str,
    counter_evidence: Iterable[str] = (),
) -> WaveScenario:
    family = (
        WaveScenarioFamily.UPTREND_UNKNOWN_WAVE
        if weekly_state is Trend.UPTREND or daily_state is Trend.UPTREND
        else WaveScenarioFamily.NO_VALID_SCENARIO
    )
    return _scenario(
        family,
        evidence=(reason,),
        counter_evidence=counter_evidence,
        confirmed_swings=daily_swings[-6:],
        invalidation_reason="unknown/no-valid scenario has no structurally valid long invalidation",
    )


def evaluate_wave_scenario(
    quotes: list[Quote],
    as_of_date: date | None = None,
    daily_swing_lookback: int = 5,
    weekly_swing_lookback: int = 5,
) -> WaveScenarioEvaluation:
    """Evaluate a Wave Scenario using only bars available at ``as_of_date``.

    ``as_of_date`` defaults to the latest input date for live shadow use. For
    historical comparisons callers should pass it explicitly; this makes the
    future-bar append invariant observable and testable.
    """
    validate_quote_series(quotes)
    if daily_swing_lookback < 1 or weekly_swing_lookback < 1:
        raise ValueError("Wave Swing lookback 必须 >= 1")
    resolved_as_of = as_of_date or quotes[-1].trade_date
    bounded = [quote for quote in quotes if quote.trade_date <= resolved_as_of]
    if not bounded:
        raise ValueError("as_of_date 之前没有可用行情")

    daily_swings_all = find_swings(bounded, lookback=daily_swing_lookback)
    daily_swings = _confirmed_swings(daily_swings_all, len(bounded) - 1)
    daily_structure = market_structure(list(daily_swings))

    weekly_quotes = aggregate_completed_weekly_quotes(bounded, resolved_as_of)
    weekly_swings_all = (
        find_swings(weekly_quotes, lookback=weekly_swing_lookback)
        if weekly_quotes
        else []
    )
    weekly_swings = _confirmed_swings(
        weekly_swings_all, len(weekly_quotes) - 1
    ) if weekly_quotes else ()
    weekly_structure = market_structure(list(weekly_swings))

    abc = _latest_abc(daily_swings)
    expansion = _upward_expansion(daily_swings)
    upward_three = _latest_upward_three(daily_swings)
    w2_candidate: WaveScenario | None = None
    continuation_candidate: WaveScenario | None = None
    abc_candidate: WaveScenario | None = None

    if upward_three is not None:
        origin, peak, retracement_low = upward_three
        impulse = _leg(origin, peak)
        retracement = _leg(peak, retracement_low)
        base_evidence = [
            "confirmed LOW→HIGH→LOW sequence exists",
            "candidate impulse high is above its origin",
        ]
        if retracement_low.price > origin.price:
            base_evidence.append("retracement remains above impulse origin")
            if weekly_structure.trend is not Trend.DOWNTREND:
                base_evidence.append("weekly parent context does not explicitly conflict with long structure")
            if bounded[-1].close > peak.price:
                base_evidence.append("as-of close is above the impulse peak; Wave 3 is only a candidate")
            else:
                base_evidence.append("as-of close has not exceeded the impulse peak; Wave 2 remains WATCH-like")
            w2_candidate = _scenario(
                WaveScenarioFamily.WAVE_2_TO_3_CANDIDATE,
                evidence=base_evidence,
                counter_evidence=(
                    "Fibonacci regions are context only and do not decide the scenario",
                    "Wave 3 is not declared started solely by a Fib or indicator hit",
                ),
                confirmed_swings=upward_three,
                impulse=impulse,
                retracement=retracement,
                structural_invalidation=origin.price,
                invalidation_reason="a close at or below the impulse origin invalidates the Wave 2→3 candidate",
                setup01=True,
            )
        else:
            w2_candidate = _scenario(
                WaveScenarioFamily.UPTREND_UNKNOWN_WAVE,
                evidence=(
                    "confirmed upward impulse leg exists",
                    "retracement is present",
                ),
                counter_evidence=("retracement broke the impulse origin",),
                confirmed_swings=upward_three,
                impulse=impulse,
                retracement=retracement,
                structural_invalidation=origin.price,
                invalidation_reason="retracement broke the impulse origin; Wave 2→3 is invalid",
            )

    if expansion is not None and weekly_structure.trend is Trend.UPTREND:
        low0, high1, low2, high3 = expansion
        last_confirmed_low = daily_structure.lows[-1] if daily_structure.lows else low2
        holds_structure = bounded[-1].close > last_confirmed_low.price
        continuation_evidence = [
            "confirmed higher-high/higher-low expansion sequence exists",
            "daily market structure is UPTREND",
            "weekly parent structure is UPTREND",
        ]
        if holds_structure:
            continuation_evidence.append("as-of close remains above the latest confirmed higher-low")
        continuation_counter = [
            "single EMA, RSI, or Fibonacci hit cannot establish continuation",
        ]
        if bounded[-1].close <= high3.price:
            continuation_counter.append("as-of close has not broken the latest confirmed impulse high")
        continuation_candidate = _scenario(
            WaveScenarioFamily.WAVE_3_CONTINUATION_CANDIDATE,
            evidence=continuation_evidence,
            counter_evidence=continuation_counter,
            confirmed_swings=expansion,
            impulse=_leg(low0, high3),
            retracement=_leg(high1, low2),
            structural_invalidation=last_confirmed_low.price,
            invalidation_reason="a close at or below the latest confirmed higher-low invalidates continuation",
            setup02=holds_structure,
        )

    if abc is not None:
        origin, peak, a_low, b_high, c_low = abc
        if (
            b_high.price < peak.price
            and c_low.price < a_low.price
            and c_low.price > origin.price
        ):
            abc_candidate = _scenario(
                WaveScenarioFamily.ABC_CORRECTION_CANDIDATE,
                evidence=(
                    "confirmed impulse origin/peak followed by A low, lower B high, and lower C low",
                    "C remains above the impulse origin",
                    "lower B high is counter-evidence to an unconditional Wave 3 interpretation",
                ),
                counter_evidence=(
                    "a later confirmed break above the corrective B high would require re-evaluation",
                ),
                confirmed_swings=abc,
                impulse=_leg(origin, peak),
                retracement=_leg(peak, c_low),
                structural_invalidation=origin.price,
                invalidation_reason="a C low at or below the impulse origin invalidates this bounded ABC candidate",
            )

    down_context = (
        weekly_structure.trend is Trend.DOWNTREND
        or (
            daily_structure.trend is Trend.DOWNTREND
            and weekly_structure.trend is not Trend.UPTREND
            and abc_candidate is None
            and w2_candidate is None
        )
    )
    if down_context:
        primary = _downtrend_scenario(
            weekly_structure.trend,
            daily_structure.trend,
            daily_swings,
        )
        alternate = (
            w2_candidate
            or continuation_candidate
            or _unknown_scenario(
                weekly_structure.trend,
                daily_structure.trend,
                daily_swings,
                "daily/weekly rebound evidence is insufficient to override long-side invalid context",
            )
        )
    elif abc_candidate is not None:
        primary = abc_candidate
        alternate = (
            continuation_candidate
            or w2_candidate
            or _unknown_scenario(
                weekly_structure.trend,
                daily_structure.trend,
                daily_swings,
                "ABC is the only sufficiently explicit bounded structure",
            )
        )
    elif continuation_candidate is not None:
        primary = continuation_candidate
        alternate = (
            abc_candidate
            or w2_candidate
            or _unknown_scenario(
                weekly_structure.trend,
                daily_structure.trend,
                daily_swings,
                "continuation is structurally supported but no independent alternate is confirmed",
            )
        )
    elif w2_candidate is not None:
        primary = w2_candidate
        alternate = (
            abc_candidate
            or _unknown_scenario(
                weekly_structure.trend,
                daily_structure.trend,
                daily_swings,
                "the upward impulse/retracement is not sufficient to confirm a richer wave family",
            )
        )
    else:
        primary = _unknown_scenario(
            weekly_structure.trend,
            daily_structure.trend,
            daily_swings,
            "no finite Wave v1 pattern has enough confirmed structural evidence",
        )
        alternate = _scenario(
            WaveScenarioFamily.NO_VALID_SCENARIO,
            evidence=("no independent alternate scenario has enough confirmed evidence",),
            confirmed_swings=daily_swings[-6:],
        )

    return WaveScenarioEvaluation(
        protocol_version=WAVE_ENGINE_PROTOCOL_VERSION,
        as_of_date=resolved_as_of,
        as_of_close=bounded[-1].close,
        weekly_state=weekly_structure.trend,
        daily_state=daily_structure.trend,
        weekly_swings=weekly_swings,
        daily_swings=daily_swings,
        primary_scenario=primary,
        alternate_scenario=alternate,
    )


def _swing_dict(swing: SwingPoint) -> dict:
    return {
        "kind": swing.kind.value,
        "price": swing.price,
        "pivot_index": swing.pivot_index,
        "pivot_date": swing.pivot_date.isoformat(),
        "confirmed_index": swing.confirmed_index,
        "confirmed_date": swing.confirmed_date.isoformat() if swing.confirmed_date else None,
    }


def _leg_dict(leg: WaveLeg | None) -> dict | None:
    if leg is None:
        return None
    return {
        "direction": leg.direction,
        "start": _swing_dict(leg.start),
        "end": _swing_dict(leg.end),
    }


def _region_dict(region: PriceRegion) -> dict:
    return {"label": region.label, "lower": region.lower, "upper": region.upper}


def scenario_to_dict(scenario: WaveScenario) -> dict:
    """Return a stable JSON-ready shadow/report projection."""
    return {
        "family": scenario.family.value,
        "evidence": list(scenario.evidence),
        "counter_evidence": list(scenario.counter_evidence),
        "evidence_score": scenario.evidence_score,
        "confidence_score": scenario.confidence_score,
        "confirmed_swings": [_swing_dict(swing) for swing in scenario.confirmed_swings],
        "candidate_impulse_leg": _leg_dict(scenario.candidate_impulse_leg),
        "candidate_retracement_leg": _leg_dict(scenario.candidate_retracement_leg),
        "fibonacci_retracement_regions": [
            _region_dict(region) for region in scenario.fibonacci_retracement_regions
        ],
        "fibonacci_extension_regions": [
            _region_dict(region) for region in scenario.fibonacci_extension_regions
        ],
        "structural_invalidation": scenario.structural_invalidation,
        "scenario_invalidation_reason": scenario.scenario_invalidation_reason,
        "setup01_context_eligible": scenario.setup01_context_eligible,
        "setup02_context_eligible": scenario.setup02_context_eligible,
    }


def evaluation_to_dict(evaluation: WaveScenarioEvaluation) -> dict:
    return {
        "protocol_version": evaluation.protocol_version,
        "as_of_date": evaluation.as_of_date.isoformat(),
        "as_of_close": evaluation.as_of_close,
        "weekly_state": evaluation.weekly_state.value,
        "daily_state": evaluation.daily_state.value,
        "weekly_confirmed_swings": [_swing_dict(swing) for swing in evaluation.weekly_swings],
        "daily_confirmed_swings": [_swing_dict(swing) for swing in evaluation.daily_swings],
        "primary_scenario": scenario_to_dict(evaluation.primary_scenario),
        "alternate_scenario": scenario_to_dict(evaluation.alternate_scenario),
    }

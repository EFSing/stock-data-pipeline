"""Mechanical evidence aggregation for Phase 5J-v4 lifecycle attribution."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from statistics import median
import sys
import types
from typing import Any, Mapping, Sequence

from research.phase5j_v4_lifecycle_attribution import ROOT_CAUSES
from research.phase5j_v4_protocol import canonical_json
from trading.models import SetupState


def sha256_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def load_setup_module_from_source(source: str, module_name: str = "phase5j_v4_origin_main_setup") -> Any:
    module = types.ModuleType(module_name)
    sys.modules[module_name] = module
    exec(compile(source, f"<{module_name}>", "exec"), module.__dict__)
    return module


def origin_main_parity_for_symbol(
    quotes: list[Any],
    tolerance: float,
    trace_rows: Sequence[Mapping[str, Any]],
    baseline_setup_module: Any,
) -> dict[str, int]:
    swings = baseline_setup_module.find_swings(quotes, lookback=5)
    history = baseline_setup_module.detect_platform_breakout_history_with_diagnostics(
        quotes,
        swing_lookback=5,
        platform_window=40,
        platform_tolerance_pct=tolerance,
        arm_proximity_pct=0.0,
        swings=swings,
    )
    setup_mismatches = 0
    event_mismatches = 0
    event_count = 0
    fields = (
        "state", "breakout_price", "structural_invalidation", "detected_index",
        "state_entered_index", "confirmed_index",
    )
    for index, (row, calculation) in enumerate(zip(trace_rows, history)):
        setup = calculation.setup
        expected = {
            "state": setup.state.value,
            "breakout_price": setup.breakout_price,
            "structural_invalidation": setup.structural_invalidation,
            "detected_index": setup.detected_index,
            "state_entered_index": setup.state_entered_index,
            "confirmed_index": setup.confirmed_index,
        }
        actual = {field: row["setup_state"] if field == "state" else row[field] for field in fields}
        setup_mismatches += expected != actual
        terminal = None
        if setup.state is SetupState.CONFIRMED and setup.confirmed_index == index:
            terminal = "CONFIRMED"
        elif (
            setup.state is SetupState.FAILED
            and setup.state_entered_index == index
            and calculation.diagnostics.reason.value == "STRUCTURAL_INVALIDATION"
        ):
            terminal = "FAILED"
        event_count += terminal is not None
        event_mismatches += terminal != row["terminal_type"]
    if len(history) != len(trace_rows):
        setup_mismatches += abs(len(history) - len(trace_rows))
    return {
        "bar_comparisons": min(len(history), len(trace_rows)),
        "event_comparisons": event_count,
        "setup_mismatches": setup_mismatches,
        "event_mismatches": event_mismatches,
    }


def candidate_summaries(
    lifecycles: Sequence[Mapping[str, Any]],
    bars_by_market: Mapping[str, int],
    symbols_by_market: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for tolerance in (0.03, 0.04, 0.05):
        result[f"{tolerance:.1%}"] = {}
        selected_tolerance = [row for row in lifecycles if row["tolerance"] == tolerance]
        for market in ("CN", "US", "POOLED"):
            selected = [row for row in selected_tolerance if market == "POOLED" or row["market"] == market]
            symbols = [symbol for m, items in symbols_by_market.items() if market == "POOLED" or m == market for symbol in items]
            bars = sum(bars_by_market.values()) if market == "POOLED" else bars_by_market[market]
            confirmed = [row for row in selected if row["terminal_type"] == "CONFIRMED"]
            counts = Counter(row["symbol"] for row in confirmed)
            for symbol in symbols:
                counts.setdefault(symbol, 0)
            total = len(confirmed)
            result[f"{tolerance:.1%}"][market] = {
                "symbol_count": len(symbols),
                "bars": bars,
                "platform_count": len(selected),
                "platform_density_per_1000_bars": 1000.0 * len(selected) / bars,
                "confirmed_event_count": total,
                "event_density_per_1000_bars": 1000.0 * total / bars,
                "max_symbol_event_share": max(counts.values(), default=0) / total if total else None,
                "zero_event_symbol_count": sum(value == 0 for value in counts.values()),
                "sparse_1_to_2_event_symbol_count": sum(1 <= value <= 2 for value in counts.values()),
                "confirmed_event_identities": sorted((row["symbol"], row["terminal_date"]) for row in confirmed),
            }
    return result


def adjacent_exact_metrics(candidate: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for lower, upper in ((0.03, 0.04), (0.04, 0.05)):
        pair = f"{lower:.1%}→{upper:.1%}"
        result[pair] = {}
        for market in ("CN", "US", "POOLED"):
            old = set(map(tuple, candidate[f"{lower:.1%}"][market]["confirmed_event_identities"]))
            new = set(map(tuple, candidate[f"{upper:.1%}"][market]["confirmed_event_identities"]))
            retained = len(old & new)
            union = len(old | new)
            result[pair][market] = {
                "previous_event_count": len(old),
                "current_event_count": len(new),
                "retained_exact": retained,
                "added": len(new - old),
                "disappeared": len(old - new),
                "exact_date_jaccard": retained / union if union else None,
                "exact_retention": retained / len(old) if old else None,
            }
    return result


def root_cause_summary(episodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lower, upper in ((0.03, 0.04), (0.04, 0.05)):
        for market in ("CN", "US", "POOLED"):
            selected = [
                row for row in episodes
                if row["lower_tolerance"] == lower and row["upper_tolerance"] == upper
                and (market == "POOLED" or row["market"] == market)
            ]
            total = len(selected)
            for cause in ROOT_CAUSES:
                caused = [row for row in selected if row["primary_root_cause"] == cause]
                margin_fields = {
                    "lower_high": [row["distance_from_lower_frozen_tolerance_threshold"]["high"] for row in caused],
                    "lower_low": [row["distance_from_lower_frozen_tolerance_threshold"]["low"] for row in caused],
                    "upper_high": [row["distance_from_upper_frozen_tolerance_threshold"]["high"] for row in caused],
                    "upper_low": [row["distance_from_upper_frozen_tolerance_threshold"]["low"] for row in caused],
                }
                rows.append({
                    "market": market,
                    "lower_tolerance": lower,
                    "upper_tolerance": upper,
                    "root_cause": cause,
                    "count": len(caused),
                    "share": len(caused) / total if total else None,
                    "affected_symbols": len({row["symbol"] for row in caused}),
                    "affected_root_lifecycles": len({
                        (row["symbol"], row.get("lower_lifecycle_ordinal"), row.get("upper_lifecycle_ordinal"))
                        for row in caused
                    }),
                    "high_span_contribution": sum(cause_name == "HIGH_SPAN_THRESHOLD_CROSSING" for cause_name in (row["primary_root_cause"] for row in caused)),
                    "low_span_contribution": sum(cause_name == "LOW_SPAN_THRESHOLD_CROSSING" for cause_name in (row["primary_root_cause"] for row in caused)),
                    "both_span_contribution": sum(cause_name == "BOTH_SPAN_THRESHOLD_CROSSING" for cause_name in (row["primary_root_cause"] for row in caused)),
                    "threshold_margin_descriptive": {
                        field: _describe([value for value in values if value is not None])
                        for field, values in margin_fields.items()
                    },
                    "threshold_margin_use": "DESCRIPTION_ONLY_NOT_TOLERANCE_DESIGN",
                })
    return rows


def _describe(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0] if ordered else None,
        "median": median(ordered) if ordered else None,
        "max": ordered[-1] if ordered else None,
    }


def anchor_divergence_summary(lineage: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lower, upper in ((0.03, 0.04), (0.04, 0.05)):
        for market in ("CN", "US", "POOLED"):
            selected = [
                row for row in lineage
                if row.get("adjacent_lower_tolerance") == lower
                and row.get("adjacent_upper_tolerance") == upper
                and (market == "POOLED" or row["market"] == market)
            ]
            rows.append({
                "market": market,
                "lower_tolerance": lower,
                "upper_tolerance": upper,
                "detection_shift": _describe([row["detection_shift"] for row in selected if row.get("detection_shift") is not None]),
                "breakout_anchor_difference": _describe([row["breakout_anchor_difference"] for row in selected if row.get("breakout_anchor_difference") is not None]),
                "invalidation_anchor_difference": _describe([row["invalidation_anchor_difference"] for row in selected if row.get("invalidation_anchor_difference") is not None]),
                "terminal_shift": _describe([row["terminal_shift"] for row in selected if row.get("terminal_shift") is not None]),
            })
    return rows


def causal_consistency(root_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def dominant(market: str, lower: float, upper: float) -> str | None:
        selected = [
            row for row in root_rows
            if row["market"] == market and row["lower_tolerance"] == lower
            and row["upper_tolerance"] == upper and row["count"] > 0
        ]
        if not selected:
            return None
        selected.sort(key=lambda row: (-row["count"], row["root_cause"]))
        return selected[0]["root_cause"]

    pairs = {}
    for lower, upper in ((0.03, 0.04), (0.04, 0.05)):
        cn, us, pooled = dominant("CN", lower, upper), dominant("US", lower, upper), dominant("POOLED", lower, upper)
        pairs[f"{lower:.1%}→{upper:.1%}"] = {
            "CN_dominant_root": cn,
            "US_dominant_root": us,
            "POOLED_dominant_root": pooled,
            "CN_US_consistent": cn == us and cn is not None,
        }
    pooled_roots = [row["POOLED_dominant_root"] for row in pairs.values()]
    return {
        "by_adjacent_pair": pairs,
        "three_to_four_vs_four_to_five_consistent": len(set(pooled_roots)) == 1 and pooled_roots[0] is not None,
    }


def cascade_summary(
    propagation: Sequence[Mapping[str, Any]],
    lineage: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lower, upper in ((0.03, 0.04), (0.04, 0.05)):
        for market in ("CN", "US", "POOLED"):
            roots = [
                row for row in propagation
                if row["lower_tolerance"] == lower and row["upper_tolerance"] == upper
                and (market == "POOLED" or row["market"] == market)
            ]
            descendants = sum(row["downstream_divergent_lifecycle_count"] for row in roots)
            divergent_lifecycles = [
                row for row in lineage
                if row.get("adjacent_lower_tolerance") == lower
                and row.get("adjacent_upper_tolerance") == upper
                and (market == "POOLED" or row["market"] == market)
                and row["lineage_class"] != "SAME_ROOT_SAME_TERMINAL"
            ]
            rows.append({
                "market": market,
                "lower_tolerance": lower,
                "upper_tolerance": upper,
                "root_divergence_count": len(roots),
                "downstream_divergence_count": descendants,
                "downstream_root_ratio": descendants / len(roots) if roots else None,
                "max_depth": max((row["cascade_depth"] for row in roots), default=0),
                "descendants_share_of_all_divergent_lifecycles": descendants / len(divergent_lifecycles) if divergent_lifecycles else None,
                "propagation_class_counts": dict(sorted(Counter(row["propagation_class"] for row in roots).items())),
            })
    return rows


def aggregate_counterfactuals(
    counterfactual_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, float, float, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in counterfactual_rows:
        grouped[(row["market"], row["lower_tolerance"], row["upper_tolerance"], row["counterfactual"])].append(row)
        grouped[("POOLED", row["lower_tolerance"], row["upper_tolerance"], row["counterfactual"])].append(row)
    output: list[dict[str, Any]] = []
    numeric_fields = (
        "downstream_divergence_reduction", "anchor_divergence_reduction",
        "baseline_anchor_divergent_lineages", "terminal_divergence_remains_count",
        "added_or_disappeared_lifecycles_restored",
    )
    for (market, lower, upper, counterfactual), rows in sorted(grouped.items()):
        output.append({
            "market": market,
            "lower_tolerance": lower,
            "upper_tolerance": upper,
            "counterfactual": counterfactual,
            **{field: sum(int(row.get(field, 0) or 0) for row in rows) for field in numeric_fields},
            "terminal_divergence_remains": any(bool(row.get("terminal_divergence_remains")) for row in rows),
            "intervention_method": "FROZEN_CAUSAL_GRAPH_EDGE_INTERVENTION",
            "labels": ["RESEARCH_CAUSAL_DIAGNOSTIC_ONLY", "NOT_A_CANDIDATE_RULE"],
        })
    return output


def _direction(value: float) -> str:
    return "INCREASE" if value > 0 else "DECREASE" if value < 0 else "UNCHANGED"


def _find_historical_pair(adjacent: Mapping[str, Any], lower: float, upper: float) -> Mapping[str, Any]:
    prefix, suffix = f"{lower:.1%}", f"{upper:.1%}"
    matches = [value for key, value in adjacent.items() if key.startswith(prefix) and key.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"historical PR29 pair is unavailable or ambiguous: {prefix} to {suffix}")
    return matches[0]


def historical_symptom_concordance(
    current_candidate: Mapping[str, Any],
    current_adjacent: Mapping[str, Any],
    historical_capsule: Mapping[str, Any],
) -> list[dict[str, Any]]:
    historical = historical_capsule["structure_only_statistics"]
    by_tolerance = historical["by_tolerance"]
    adjacent = historical["adjacent_tolerance_stability"]
    rows: list[dict[str, Any]] = []
    for lower, upper in ((0.03, 0.04), (0.04, 0.05)):
        current_pair = current_adjacent[f"{lower:.1%}→{upper:.1%}"]
        old_pair = _find_historical_pair(adjacent, lower, upper)
        for market in ("CN", "US"):
            old_lower, old_upper = by_tolerance[f"{lower:.1%}"][market], by_tolerance[f"{upper:.1%}"][market]
            new_lower, new_upper = current_candidate[f"{lower:.1%}"][market], current_candidate[f"{upper:.1%}"][market]
            symptom_directions = {
                "event_count": (
                    _direction(old_upper["CONFIRMED_EVENTS"] - old_lower["CONFIRMED_EVENTS"]),
                    _direction(new_upper["confirmed_event_count"] - new_lower["confirmed_event_count"]),
                ),
                "event_density": (
                    _direction(old_upper["CONFIRMED_per_1000_bars"] - old_lower["CONFIRMED_per_1000_bars"]),
                    _direction(new_upper["event_density_per_1000_bars"] - new_lower["event_density_per_1000_bars"]),
                ),
                "platform_count": (
                    _direction(old_upper["platform_detected"] - old_lower["platform_detected"]),
                    _direction(new_upper["platform_count"] - new_lower["platform_count"]),
                ),
                "platform_density": (
                    _direction(old_upper["platform_per_1000_bars"] - old_lower["platform_per_1000_bars"]),
                    _direction(new_upper["platform_density_per_1000_bars"] - new_lower["platform_density_per_1000_bars"]),
                ),
                "symbol_concentration": (
                    _direction((old_upper["max_symbol_event_share"] or 0) - (old_lower["max_symbol_event_share"] or 0)),
                    _direction((new_upper["max_symbol_event_share"] or 0) - (new_lower["max_symbol_event_share"] or 0)),
                ),
                "sparse_event_symbols": (
                    _direction(old_upper["symbols_with_1_to_2_confirmed"] - old_lower["symbols_with_1_to_2_confirmed"]),
                    _direction(new_upper["sparse_1_to_2_event_symbol_count"] - new_lower["sparse_1_to_2_event_symbol_count"]),
                ),
            }
            agreements = {key: old == new for key, (old, new) in symptom_directions.items()}
            if not agreements:
                status = "INSUFFICIENT"
            elif all(agreements.values()):
                status = "CONCORDANT"
            elif any(agreements.values()):
                status = "PARTIALLY_CONCORDANT"
            else:
                status = "DISCORDANT"
            old_metrics = old_pair[market]
            rows.append({
                "market": market,
                "lower_tolerance": lower,
                "upper_tolerance": upper,
                "status": status,
                "causal_status": "NOT_CAUSAL_REPLICATION",
                "symptom_directions": symptom_directions,
                "direction_agreements": agreements,
                "historical_exact_date_jaccard": old_metrics["exact_date_jaccard"],
                "current_exact_date_jaccard": current_pair[market]["exact_date_jaccard"],
                "historical_exact_retained": old_metrics["retained"],
                "current_exact_retained": current_pair[market]["retained_exact"],
                "historical_exact_retention": old_metrics["retained"] / old_metrics["previous_event_count"] if old_metrics["previous_event_count"] else None,
                "current_exact_retention": current_pair[market]["exact_retention"],
            })
    return rows


def evidence_state_and_recommendation(
    root_rows: Sequence[Mapping[str, Any]],
    cascade_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    pooled = [row for row in root_rows if row["market"] == "POOLED" and row["count"] > 0]
    counts = Counter()
    for row in pooled:
        counts[row["root_cause"]] += row["count"]
    total_roots = sum(counts.values())
    ranking = [
        {"root_cause": cause, "count": count, "share": count / total_roots if total_roots else None}
        for cause, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    if not ranking:
        status = "INSUFFICIENT_CAUSAL_EVIDENCE"
        largest = None
    else:
        largest = ranking[0]["root_cause"]
        if len(ranking) == 1:
            cascade = sum(row["downstream_divergence_count"] for row in cascade_rows if row["market"] == "POOLED")
            roots = sum(row["root_divergence_count"] for row in cascade_rows if row["market"] == "POOLED")
            status = "ROOT_CAUSE_WITH_STRONG_CASCADE_AMPLIFICATION" if cascade > roots else "CLEAR_SINGLE_MECHANISM"
        else:
            status = "MIXED_CAUSAL_STRUCTURE"
    threshold_roots = {"HIGH_SPAN_THRESHOLD_CROSSING", "LOW_SPAN_THRESHOLD_CROSSING", "BOTH_SPAN_THRESHOLD_CROSSING"}
    cascade_present = any(row["downstream_divergence_count"] > 0 for row in cascade_rows if row["market"] == "POOLED")
    if largest in threshold_roots:
        recommendation = (
            "REDESIGN_PLATFORM_BOUNDARY_SEMANTICS_THEN_REDESIGN_TERMINAL_REARM_ORCHESTRATION"
            if cascade_present else "REDESIGN_PLATFORM_BOUNDARY_SEMANTICS"
        )
    elif largest in {"NEW_SWING_ELIGIBILITY_DIVERGENCE", "TERMINAL_STATE_DIVERGENCE"}:
        recommendation = "REDESIGN_TERMINAL_REARM_ORCHESTRATION"
    elif largest in {"STRUCTURE_INPUT_DIVERGENCE", "PLATFORM_FIRST_DETECTION_DIVERGENCE", "FROZEN_BREAKOUT_ANCHOR_DIVERGENCE", "FROZEN_INVALIDATION_ANCHOR_DIVERGENCE"}:
        recommendation = "REDESIGN_PLATFORM_IDENTITY"
    elif largest is None:
        recommendation = "PRESERVE_SETUP03_AND_REVISIT_VALIDATION_ASSUMPTIONS"
    else:
        recommendation = "STOP_SETUP03_DEVELOPMENT"
    return {
        "largest_root_cause": largest,
        "root_cause_ranking": ranking,
        "attribution_evidence_status": status,
        "attribution_evidence_rationale": {
            "rule": "logical root diversity and cascade presence; no post-result percentage threshold",
            "distinct_observed_root_causes": len(ranking),
            "pooled_root_count": sum(counts.values()),
            "cascade_present": cascade_present,
        },
        "next_research_recommendation": recommendation,
    }


def write_capsule(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    body = deepcopy(dict(payload))
    body["integrity"] = {
        "canonical_payload_sha256": None,
        "hash_scope": "canonical JSON with integrity.canonical_payload_sha256=null",
    }
    canonical_hash = f"sha256:{hashlib.sha256(canonical_json(body).encode('utf-8')).hexdigest()}"
    body["integrity"]["canonical_payload_sha256"] = canonical_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"canonical_payload_sha256": canonical_hash, "file_sha256": sha256_file(path)}


def render_chinese_report(payload: Mapping[str, Any], capsule_file_sha256: str) -> str:
    state = payload["decision_state"]
    lines = [
        "# Phase 5J-v4 SETUP_03 平台身份与生命周期分歧归因",
        "",
        "> 单一冻结数据集 causal diagnostic；不是 tolerance 搜索，不是生产规则，不是 Final OOS。",
        "",
        "## 冻结身份与边界",
        "",
        f"- protocol: `{payload['identity']['protocol_version']}` / `{payload['identity']['protocol_sha256']}`",
        f"- dataset: 40 symbols / 86,305 bars / `{payload['identity']['replay_aggregate_sha256']}`",
        f"- attribution capsule file SHA-256: `{capsule_file_sha256}`",
        f"- production parity: setup mismatches `{payload['parity']['setup_mismatches']}`，event mismatches `{payload['parity']['event_mismatches']}`",
        "- 禁止指标访问：returns/MFE/MAE/P&L/winrate/profit factor/expectancy 全部 false；Final OOS 未访问。",
        "",
        "## Root cause",
        "",
        f"- `LARGEST_ROOT_CAUSE`: `{state['largest_root_cause']}`",
        f"- `ATTRIBUTION_EVIDENCE_STATUS`: `{state['attribution_evidence_status']}`",
        f"- ranking: `{state['root_cause_ranking']}`",
        "",
        "### 相邻 pair 与市场一致性",
        "",
    ]
    for row in payload["root_cause_summary"]:
        if row["market"] == "POOLED" and row["count"]:
            lines.append(
                f"- {row['lower_tolerance']:.0%}→{row['upper_tolerance']:.0%} `{row['root_cause']}`: `{row['count']}` / `{row['share']:.2%}`"
            )
    consistency = payload["causal_consistency"]
    for pair, row in consistency["by_adjacent_pair"].items():
        lines.append(
            f"- {pair}: CN `{row['CN_dominant_root']}`，US `{row['US_dominant_root']}`，CN/US consistent=`{row['CN_US_consistent']}`"
        )
    lines.extend([
        f"- 3→4 vs 4→5 pooled dominant-root consistent: `{consistency['three_to_four_vs_four_to_five_consistent']}`",
        "",
        "## Cascade 与 counterfactual",
        "",
    ])
    for row in payload["cascade_summary"]:
        if row["market"] == "POOLED":
            lines.append(
                f"- {row['lower_tolerance']:.0%}→{row['upper_tolerance']:.0%}: roots `{row['root_divergence_count']}`, downstream `{row['downstream_divergence_count']}`, ratio `{row['downstream_root_ratio']}`，max depth `{row['max_depth']}`"
            )
    pooled_counterfactuals = [row for row in payload["counterfactual_summary"] if row["market"] == "POOLED"]
    for row in pooled_counterfactuals:
        if row["counterfactual"] == "A":
            result = f"downstream reduction `{row['downstream_divergence_reduction']}`"
        elif row["counterfactual"] == "B":
            result = f"anchor divergence reduction `{row['anchor_divergence_reduction']}`"
        elif row["counterfactual"] == "C":
            result = f"terminal divergence remains `{row['terminal_divergence_remains_count']}`"
        else:
            result = f"restored added/disappeared lifecycle `{row['added_or_disappeared_lifecycles_restored']}`"
        lines.append(f"- {row['lower_tolerance']:.0%}→{row['upper_tolerance']:.0%} counterfactual {row['counterfactual']}: {result}")
    lines.extend(["", "四个 counterfactual 均标记 `RESEARCH_CAUSAL_DIAGNOSTIC_ONLY` / `NOT_A_CANDIDATE_RULE`。", "", "## Historical symptom concordance", ""])
    for row in payload["historical_symptom_concordance"]:
        lines.append(f"- {row['market']} {row['lower_tolerance']:.0%}→{row['upper_tolerance']:.0%}: `{row['status']}` / `NOT_CAUSAL_REPLICATION`")
    lines.extend([
        "",
        "## Sol recommendation",
        "",
        f"`{state['next_research_recommendation']}`",
        "",
        "该建议只确定下一层研究方向，不实施策略修改。",
        "",
        "`PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION`",
        "",
    ])
    return "\n".join(lines)


__all__ = [
    "adjacent_exact_metrics", "aggregate_counterfactuals", "anchor_divergence_summary", "candidate_summaries",
    "cascade_summary", "evidence_state_and_recommendation", "historical_symptom_concordance",
    "causal_consistency",
    "load_setup_module_from_source", "origin_main_parity_for_symbol", "render_chinese_report",
    "root_cause_summary", "sha256_file", "write_capsule",
]

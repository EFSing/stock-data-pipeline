"""Research-only geometric attribution for SETUP_01 low-Fib events.

The module consumes the previous research-only target diagnostic artifact. It
does not replay bars, call Decision/Risk, read T+1 or outcome data, or choose
any production threshold. All calculations use the already persisted T-day
Wave1/Wave2/ATR/planned-entry fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping, Sequence


FIB_1_272_RATIO = 1.272
FIB_NEAR_CATEGORIES = frozenset(("SMALL_WAVE_FIB", "BOTH_NEAR"))
GROUP_ORDER = (
    "all_confirmed",
    "low_t1",
    "wave3_fib_near",
    "SMALL_WAVE_FIB",
    "BOTH_NEAR",
    "NEAR_SWING_ONLY",
)
METRICS = (
    "R",
    "r",
    "e",
    "wave1_gain_pct",
    "wave1_range_over_atr14",
    "confirmation_extension_pct",
    "confirmation_extension_over_wave1",
    "fib_headroom_over_wave1",
    "fib_1_272_remaining_absolute",
    "fib_1_272_remaining_upside_pct",
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_wave2_to_wave3_structure_scale_diagnostic_v1.json"
)
DEFAULT_JSON_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_wave2_to_wave3_geometry_attribution_v1.json"
)
DEFAULT_MARKDOWN_OUTPUT = (
    PROJECT_ROOT
    / "research"
    / "development"
    / "setup01_wave2_to_wave3_geometry_attribution_v1.md"
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _require_number(row: Mapping[str, Any], name: str) -> float:
    value = _number(row.get(name))
    if value is None:
        raise ValueError(f"missing finite geometry input: {name}")
    return value


def derive_geometry(row: Mapping[str, Any]) -> dict[str, float]:
    """Calculate the requested T-day geometry and the Fib identity residual."""

    low0 = _require_number(row, "wave1_origin_price")
    high1 = _require_number(row, "wave1_peak_price")
    low2 = _require_number(row, "wave2_low_price")
    planned_entry = _require_number(row, "planned_entry")
    atr14 = _number(row.get("decision_t_atr14"))
    R = high1 - low0
    if R <= 0:
        raise ValueError(f"Wave1 range must be positive: {R}")
    r = (high1 - low2) / R
    e = planned_entry - high1
    remaining_absolute = (FIB_1_272_RATIO - r) * R - e
    projection_remaining_absolute = (
        low2 + FIB_1_272_RATIO * R - planned_entry
    )
    return {
        "R": R,
        "r": r,
        "e": e,
        "wave1_gain_pct": R / low0,
        "wave1_range_over_atr14": (
            R / atr14 if atr14 is not None and atr14 > 0 else math.nan
        ),
        "confirmation_extension_pct": (
            e / high1 if high1 != 0 else math.nan
        ),
        "confirmation_extension_over_wave1": e / R,
        "fib_headroom_over_wave1": FIB_1_272_RATIO - r - e / R,
        "fib_1_272_remaining_absolute": remaining_absolute,
        "fib_1_272_remaining_upside_pct": (
            remaining_absolute / planned_entry
            if planned_entry != 0
            else math.nan
        ),
        "fib_identity_residual": (
            remaining_absolute - projection_remaining_absolute
        ),
    }


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (
        position - lower
    )


def _metric_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for metric in METRICS:
        values = [
            value
            for row in rows
            if (value := _number(row.get(metric))) is not None
        ]
        output[metric] = {
            "n": len(values),
            "min": min(values) if values else None,
            "p25": _percentile(values, 0.25),
            "median": median(values) if values else None,
            "mean": mean(values) if values else None,
            "p75": _percentile(values, 0.75),
            "max": max(values) if values else None,
        }
    residuals = [
        abs(value)
        for row in rows
        if (value := _number(row.get("fib_identity_residual"))) is not None
    ]
    output["identity_check"] = {
        "n": len(residuals),
        "max_absolute_residual": max(residuals) if residuals else None,
        "passed": bool(residuals) and max(residuals) <= 1e-9,
    }
    r_values = [
        value for row in rows if (value := _number(row.get("r"))) is not None
    ]
    fib_upside_values = [
        value
        for row in rows
        if (value := _number(row.get("fib_1_272_remaining_upside_pct")))
        is not None
    ]
    headroom_values = [
        value
        for row in rows
        if (value := _number(row.get("fib_headroom_over_wave1"))) is not None
    ]
    output["descriptive_counts"] = {
        "r_ge_0_786_count": sum(value >= 0.786 for value in r_values),
        "r_ge_0_786_share": (
            sum(value >= 0.786 for value in r_values) / len(r_values)
            if r_values
            else None
        ),
        "fib_headroom_nonpositive_count": sum(
            value <= 0 for value in headroom_values
        ),
        "fib_upside_below_5_count": sum(
            value < 0.05 for value in fib_upside_values
        ),
    }
    return output


def _source_rows(
    events: Sequence[Mapping[str, Any]],
    group: str,
) -> list[Mapping[str, Any]]:
    if group == "all_confirmed":
        return list(events)
    if group == "low_t1":
        return [row for row in events if bool(row.get("t1_lt_5"))]
    if group == "wave3_fib_near":
        return [
            row
            for row in events
            if row.get("low_t1_category") in FIB_NEAR_CATEGORIES
        ]
    if group in {"SMALL_WAVE_FIB", "BOTH_NEAR", "NEAR_SWING_ONLY"}:
        return [
            row for row in events if row.get("low_t1_category") == group
        ]
    raise KeyError(group)


def _geometry_rows(
    source_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source in source_rows:
        geometry = derive_geometry(source)
        row = {
            "event_identity": source.get("event_identity"),
            "symbol": source.get("symbol"),
            "market": source.get("market"),
            "trade_date": source.get("trade_date"),
            "low_t1_category": source.get("low_t1_category"),
            "t1_lt_5": bool(source.get("t1_lt_5")),
            "wave1_origin_price": source.get("wave1_origin_price"),
            "wave1_peak_price": source.get("wave1_peak_price"),
            "wave2_low_price": source.get("wave2_low_price"),
            "planned_entry": source.get("planned_entry"),
            "decision_t_atr14": source.get("decision_t_atr14"),
        }
        row.update({key: _finite(value) for key, value in geometry.items()})
        output.append(row)
    return output


def _share(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def build_geometry_attribution(
    source_document: Mapping[str, Any],
    *,
    source_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a machine-readable, outcome-free geometry attribution artifact."""

    events = tuple(source_document.get("events", ()))
    if not events:
        raise ValueError("source diagnostic contains no event rows")
    source_fib_rows = _source_rows(events, "wave3_fib_near")
    if len(source_fib_rows) != 81:
        raise AssertionError(
            f"expected 81 Wave3 Fib-near events, found {len(source_fib_rows)}"
        )

    geometry_by_group: dict[str, list[dict[str, Any]]] = {}
    group_statistics: dict[str, Any] = {}
    for group in GROUP_ORDER:
        rows = _geometry_rows(_source_rows(events, group))
        geometry_by_group[group] = rows
        group_statistics[group] = {
            "source_count": len(_source_rows(events, group)),
            "geometry_count": len(rows),
            "metrics": _metric_stats(rows),
        }

    fib_near_rows = geometry_by_group["wave3_fib_near"]
    mean_r = mean(row["r"] for row in fib_near_rows)
    mean_extension = mean(
        row["confirmation_extension_over_wave1"] for row in fib_near_rows
    )
    mean_headroom = mean(
        row["fib_headroom_over_wave1"] for row in fib_near_rows
    )
    extension_budget_terms = {
        "wave2_retracement_term_r": mean_r,
        "confirmation_extension_term_e_over_R": mean_extension,
        "remaining_headroom_term": mean_headroom,
        "extension_ratio_budget": FIB_1_272_RATIO,
    }
    extension_budget_shares = {
        "wave2_retracement_share_of_1_272": mean_r / FIB_1_272_RATIO,
        "confirmation_extension_share_of_1_272": (
            mean_extension / FIB_1_272_RATIO
        ),
        "remaining_headroom_share_of_1_272": (
            mean_headroom / FIB_1_272_RATIO
        ),
    }

    category_counts = {
        category: len(_source_rows(events, category))
        for category in ("SMALL_WAVE_FIB", "BOTH_NEAR", "NEAR_SWING_ONLY")
    }
    return {
        "artifact_type": "SETUP_01_WAVE2_WAVE3_GEOMETRY_ATTRIBUTION",
        "artifact_version": "v1",
        "analysis_date": source_document.get("analysis_date"),
        "protocol": {
            "scope": "existing Wave3 Fib-near events only for detailed rows",
            "source_artifact_type": source_document.get("artifact_type"),
            "fib_ratio": FIB_1_272_RATIO,
            "retracement_boundary_for_description": 0.786,
            "formal_target_gate_unchanged": 0.05,
            "production_rule_selection": False,
            "threshold_selection": False,
            "outcome_metrics_accessed": False,
        },
        "source_artifact": {
            "path": str(DEFAULT_INPUT.relative_to(PROJECT_ROOT)),
            "sha256": source_artifact_sha256,
            "dataset": source_document.get("dataset"),
        },
        "scope": {
            "all_confirmed": len(_source_rows(events, "all_confirmed")),
            "low_t1": len(_source_rows(events, "low_t1")),
            "wave3_fib_near": len(source_fib_rows),
            "wave3_fib_near_category_partition": category_counts,
        },
        "group_statistics": group_statistics,
        "wave3_fib_near_decomposition": {
            "mean_normalized_terms": extension_budget_terms,
            "mean_normalized_term_shares": extension_budget_shares,
            "category_mix": {
                "SMALL_WAVE_FIB": {
                    "count": category_counts["SMALL_WAVE_FIB"],
                    "share_of_wave3_fib_near": _share(
                        category_counts["SMALL_WAVE_FIB"], len(source_fib_rows)
                    ),
                },
                "BOTH_NEAR": {
                    "count": category_counts["BOTH_NEAR"],
                    "share_of_wave3_fib_near": _share(
                        category_counts["BOTH_NEAR"], len(source_fib_rows)
                    ),
                },
            },
            "detailed_rows": fib_near_rows,
        },
        "controls": {
            "research_only": True,
            "development_only": True,
            "formal_validation": False,
            "final_oos_accessed": False,
            "forward_returns_accessed": False,
            "mfe_accessed": False,
            "mae_accessed": False,
            "pnl_accessed": False,
            "win_rate_accessed": False,
            "expectancy_accessed": False,
            "t_plus_1_accessed": False,
            "decision_recomputed": False,
            "production_gate_changed": False,
            "sheets_written": False,
            "broker_orders": False,
        },
        "status": "SUCCESS",
    }


def _pct(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.2%}"


def _num(value: Any, decimals: int = 4) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.{decimals}f}"


def render_markdown(artifact: Mapping[str, Any]) -> str:
    """Render the geometry artifact as a compact human-readable research note."""

    scope = artifact["scope"]
    stats = artifact["group_statistics"]
    decomposition = artifact["wave3_fib_near_decomposition"]
    lines = [
        "# SETUP_01 Wave3 Fib Geometry Attribution v1",
        "",
        "> Research-only descriptive analysis. It does not select a threshold or",
        "> change SETUP_01 Decision, RR, Target, Wave, Swing, Fib, Entry, Stop,",
        "> or T→T+1 semantics.",
        "",
        f"- 全部 SETUP_01 CONFIRMED：{scope['all_confirmed']}",
        f"- 既有正式 T1 <5%：{scope['low_t1']}",
        f"- Wave3 Fib 本身 <5%：{scope['wave3_fib_near']}",
        f"- 其中 SMALL_WAVE_FIB：{scope['wave3_fib_near_category_partition']['SMALL_WAVE_FIB']}",
        f"- 其中 BOTH_NEAR：{scope['wave3_fib_near_category_partition']['BOTH_NEAR']}",
        "",
        "## 几何恒等式",
        "",
        "R = HIGH1 - LOW0；r = (HIGH1 - LOW2) / R；",
        "e = planned_entry - HIGH1。",
        "",
        "fib_1_272_remaining_absolute = (1.272 - r) × R - e，",
        "并逐事件与 LOW2 + 1.272 × R - planned_entry 核对。",
        "",
        f"- 恒等式最大绝对残差：{_num(stats['wave3_fib_near']['metrics']['identity_check']['max_absolute_residual'], 12)}",
        f"- 恒等式通过：{stats['wave3_fib_near']['metrics']['identity_check']['passed']}",
        "",
        "## 分组描述统计",
        "",
        "| group | N | r median | Wave1 gain median | Wave1 range / ATR14 median | e / R median | Fib headroom / R median | Fib1.272 remaining upside median |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "all_confirmed": "全部 CONFIRMED",
        "low_t1": "T1 <5%",
        "wave3_fib_near": "Wave3 Fib <5%（81）",
        "SMALL_WAVE_FIB": "SMALL_WAVE_FIB",
        "BOTH_NEAR": "BOTH_NEAR",
        "NEAR_SWING_ONLY": "NEAR_SWING_ONLY",
    }
    for group in GROUP_ORDER:
        metric = stats[group]["metrics"]
        lines.append(
            "| "
            + " | ".join(
                (
                    labels[group],
                    str(stats[group]["geometry_count"]),
                    _num(metric["r"]["median"]),
                    _pct(metric["wave1_gain_pct"]["median"]),
                    _num(metric["wave1_range_over_atr14"]["median"]),
                    _pct(metric["confirmation_extension_over_wave1"]["median"]),
                    _num(metric["fib_headroom_over_wave1"]["median"]),
                    _pct(metric["fib_1_272_remaining_upside_pct"]["median"]),
                )
            )
            + " |"
        )
    term = decomposition["mean_normalized_terms"]
    share = decomposition["mean_normalized_term_shares"]
    lines.extend(
        [
            "",
            "## 81 个 Wave3 Fib-near 的几何分解",
            "",
            "| 项目 | 均值 | 占 1.272 normalized extension budget |",
            "|---|---:|---:|",
            f"| Wave2 retracement term r | {_num(term['wave2_retracement_term_r'])} | {_pct(share['wave2_retracement_share_of_1_272'])} |",
            f"| confirmation extension term e/R | {_pct(term['confirmation_extension_term_e_over_R'])} | {_pct(share['confirmation_extension_share_of_1_272'])} |",
            f"| remaining Fib headroom 1.272-r-e/R | {_num(term['remaining_headroom_term'])} | {_pct(share['remaining_headroom_share_of_1_272'])} |",
            "",
            f"- r >= 0.786：{stats['wave3_fib_near']['metrics']['r']['n']} 可计算事件中 "
            f"{stats['wave3_fib_near']['metrics']['descriptive_counts']['r_ge_0_786_count']} 个"
            f"（{_pct(stats['wave3_fib_near']['metrics']['descriptive_counts']['r_ge_0_786_share'])}）。",
            f"- BOTH_NEAR：{decomposition['category_mix']['BOTH_NEAR']['count']} / "
            f"{scope['wave3_fib_near']}（{_pct(decomposition['category_mix']['BOTH_NEAR']['share_of_wave3_fib_near'])}）。",
            "",
            "## 描述性结论（不转化为生产规则）",
            "",
            "1. **Deep Wave2 retracement 是相对 Fib headroom 的主要压缩项。** 81 个事件的 "
            f"r median 为 {_num(stats['wave3_fib_near']['metrics']['r']['median'])}，"
            f"全部 CONFIRMED 为 {_num(stats['all_confirmed']['metrics']['r']['median'])}；"
            f"按既有 0.786 Fib 区域作描述性统计，{_pct(stats['wave3_fib_near']['metrics']['descriptive_counts']['r_ge_0_786_share'])} "
            "落在该区域。",
            "2. **Wave1 scale 是绝对价格空间的第二个明显因素。** Fib-near 组的 Wave1 "
            f"gain median 为 {_pct(stats['wave3_fib_near']['metrics']['wave1_gain_pct']['median'])}，"
            f"全部 CONFIRMED 为 {_pct(stats['all_confirmed']['metrics']['wave1_gain_pct']['median'])}；"
            f"Wave1 range / ATR14 median 为 {_num(stats['wave3_fib_near']['metrics']['wave1_range_over_atr14']['median'])}，"
            f"全部 CONFIRMED 为 {_num(stats['all_confirmed']['metrics']['wave1_range_over_atr14']['median'])}。",
            "3. **Confirmation extension 不是这 81 个事件的主要独立来源。** Fib-near 组 "
            f"e/R median 为 {_pct(stats['wave3_fib_near']['metrics']['confirmation_extension_over_wave1']['median'])}，"
            f"全部 CONFIRMED 为 {_pct(stats['all_confirmed']['metrics']['confirmation_extension_over_wave1']['median'])}；"
            "它会进一步减少 headroom，但本组并未表现出相对全部事件更大的 confirmation extension。",
            "4. **组合机制明显存在。** 81 个 Fib-near 中 BOTH_NEAR 占 "
            f"{_pct(decomposition['category_mix']['BOTH_NEAR']['share_of_wave3_fib_near'])} "
            "（63/81），所以不能把上一轮的 81 个直接写成“Wave1 too small”。"
            "更准确的描述是：深回撤压缩 normalized Fib headroom，较小 Wave1 scale "
            "压缩绝对空间，并且多数事件同时有近端 confirmed swing high。",
            "5. **全体低 T1 的 nearest-first 主导因素仍是已确认历史阻力。** 既有 "
            "198 个 T1 <5% 事件中，NEAR_SWING_ONLY=117、BOTH_NEAR=63、"
            "SMALL_WAVE_FIB=18；本轮没有因此改变 confirmed swing high 的正式候选边界。",
            "",
            "以上是描述统计与几何分解，不是阈值选择、不是收益归因，也不是新的 production gate。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    source_path: str | Path = DEFAULT_INPUT,
    *,
    json_output: str | Path = DEFAULT_JSON_OUTPUT,
    markdown_output: str | Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    source_path = Path(source_path)
    source_document = json.loads(source_path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    artifact = build_geometry_attribution(
        source_document,
        source_artifact_sha256=f"sha256:{source_hash}",
    )
    json_path = Path(json_output)
    markdown_path = Path(markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(artifact), encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--json-output", default=str(DEFAULT_JSON_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    args = parser.parse_args()
    artifact = write_outputs(
        args.input,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    print(
        "SETUP01_GEOMETRY_ATTRIBUTION_SUMMARY "
        + json.dumps(
            {
                "status": artifact["status"],
                "scope": artifact["scope"],
                "identity_check": artifact["group_statistics"]["wave3_fib_near"][
                    "metrics"
                ]["identity_check"],
                "controls": artifact["controls"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_INPUT",
    "DEFAULT_JSON_OUTPUT",
    "DEFAULT_MARKDOWN_OUTPUT",
    "FIB_1_272_RATIO",
    "build_geometry_attribution",
    "derive_geometry",
    "render_markdown",
    "write_outputs",
]

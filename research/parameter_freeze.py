"""Phase 5I SETUP_03 freeze inventory and pre-freeze audit.

This module consumes only the already-produced Phase 5G/5H artifact contracts.
It does not replay data, fetch history, inspect OOS, or calculate trading rules.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from research.platform_structure_calibration import PlatformStructureArtifacts
from research.platform_tolerance_sensitivity import PlatformToleranceArtifacts


SPEC_PATH = Path(__file__).with_name("setup03_frozen_spec.json")
INVENTORY_STATUSES = {
    "FIXED_EXISTING",
    "FROZEN_PHASE5I",
    "RETAINED_NOT_FROZEN",
    "DEPRECATED",
    "OUT_OF_SCOPE_NOT_SETUP03_PARAMETER",
    "UNRESOLVED",
}


@dataclass(frozen=True)
class ParameterFreezeArtifacts:
    inventory_rows: tuple[dict[str, Any], ...]
    audit_report: str
    specification: dict[str, Any]


def load_frozen_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    """Read and validate the versioned machine-readable freeze specification."""
    spec = json.loads(path.read_text(encoding="utf-8"))
    _validate_spec(spec)
    return spec


def critical_values_hash(spec: dict[str, Any]) -> str:
    """Hash the values that require an explicit freeze-version change to edit."""
    critical_inventory = [
        item
        for item in spec["parameter_inventory"]
        if item["status"] in {"FIXED_EXISTING", "FROZEN_PHASE5I"}
    ]
    payload = {
        "schema_version": spec["schema_version"],
        "freeze_version": spec["freeze_version"],
        "rule_version": spec["rule_version"],
        "freeze_decision": spec["freeze_decision"],
        "dataset": spec["dataset"],
        "evidence": spec["evidence"],
        "governance": spec["governance"],
        "critical_inventory": critical_inventory,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def phase5i_freeze_artifacts(
    phase5g: PlatformToleranceArtifacts,
    phase5h: PlatformStructureArtifacts,
    dataset_hash: str,
    *,
    spec_path: Path = SPEC_PATH,
) -> ParameterFreezeArtifacts:
    """Audit the frozen Phase 5G/5H evidence without adding research degrees."""
    spec = load_frozen_spec(spec_path)
    if dataset_hash != spec["dataset"]["aggregate_hash"]:
        raise ValueError("Phase 5I dataset hash does not match frozen specification")
    inventory = {item["id"]: item for item in spec["parameter_inventory"]}
    phase5g_tolerances = tuple(
        row["platform_tolerance_pct"] for row in phase5g.funnel_rows
    )
    expected_g = tuple(inventory["phase5g_platform_tolerance_sequence"]["value"])
    if phase5g_tolerances != expected_g:
        raise ValueError("Phase 5I Phase 5G evidence sequence mismatch")

    phase5h_all_rows = [row for row in phase5h.market_rows if row["市场"] == "ALL"]
    phase5h_tolerances = tuple(
        row["platform_tolerance_pct"] for row in phase5h_all_rows
    )
    expected_h = tuple(
        inventory["phase5h_primary_tolerance_sequence"]["value"]
        + inventory["phase5h_stress_boundary"]["value"]
    )
    if phase5h_tolerances != expected_h:
        raise ValueError("Phase 5I Phase 5H evidence sequence mismatch")

    rows = tuple(_inventory_row(item) for item in spec["parameter_inventory"])
    report = _render_audit_report(spec, phase5g, phase5h)
    return ParameterFreezeArtifacts(rows, report, spec)


def serialize_frozen_spec(spec: dict[str, Any]) -> str:
    """Return the stable artifact representation of the repository specification."""
    return json.dumps(spec, ensure_ascii=False, indent=2) + "\n"


def _validate_spec(spec: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "freeze_version",
        "rule_version",
        "frozen_at",
        "freeze_decision",
        "dataset",
        "evidence",
        "governance",
        "parameter_inventory",
        "integrity",
    }
    missing = required - set(spec)
    if missing:
        raise ValueError(f"freeze specification missing keys: {sorted(missing)}")
    inventory = spec["parameter_inventory"]
    ids = [item.get("id") for item in inventory]
    if len(ids) != len(set(ids)) or None in ids:
        raise ValueError("freeze specification parameter ids must be unique")
    for item in inventory:
        if item.get("status") not in INVENTORY_STATUSES:
            raise ValueError(f"invalid inventory status for {item['id']}")
        for key in ("classification", "semantics", "basis", "affects_setup03_signal"):
            if key not in item:
                raise ValueError(f"inventory item {item['id']} missing {key}")
        if item["status"] == "UNRESOLVED" and not item.get("missing_evidence"):
            raise ValueError(f"UNRESOLVED item {item['id']} must state missing evidence")
        if item["status"] in {"FIXED_EXISTING", "FROZEN_PHASE5I"} and "value" not in item:
            raise ValueError(f"frozen item {item['id']} must record its value")
    expected = spec["integrity"].get("critical_values_sha256")
    actual = critical_values_hash(spec)
    if expected != actual:
        raise ValueError(
            "freeze specification integrity mismatch; critical changes require an "
            "explicit freeze-version update"
        )


def _inventory_row(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("value", item.get("current_value"))
    return {
        "parameter_id": item["id"],
        "classification": item["classification"],
        "status": item["status"],
        "value_or_current_value": json.dumps(value, ensure_ascii=False, sort_keys=True),
        "semantics": item["semantics"],
        "basis": item["basis"],
        "missing_evidence": item.get("missing_evidence", ""),
        "affects_setup03_signal": item["affects_setup03_signal"],
    }


def _render_audit_report(
    spec: dict[str, Any],
    phase5g: PlatformToleranceArtifacts,
    phase5h: PlatformStructureArtifacts,
) -> str:
    inventory = spec["parameter_inventory"]
    frozen = [item for item in inventory if item["status"] == "FROZEN_PHASE5I"]
    existing = [item for item in inventory if item["status"] == "FIXED_EXISTING"]
    unresolved = [item for item in inventory if item["status"] == "UNRESOLVED"]

    primary = set(
        next(
            item["value"]
            for item in inventory
            if item["id"] == "phase5h_primary_tolerance_sequence"
        )
    )
    coverage_tolerance = min(primary)
    coverage_rows = [
        row
        for row in phase5h.market_rows
        if row["platform_tolerance_pct"] == coverage_tolerance
        and row["市场"] != "ALL"
    ]
    primary_stability = [
        row
        for row in phase5h.stability_rows
        if row["市场"] == "ALL" and row["当前tolerance"] in primary
    ]
    stress_stability = [
        row
        for row in phase5h.stability_rows
        if row["市场"] == "ALL" and row["当前tolerance"] not in primary
    ]
    primary_concentration = [
        row
        for row in phase5h.concentration_rows
        if row["范围"] == "ALL"
        and row["platform_tolerance_pct"] in primary
        and row["维度"] in {"market", "symbol"}
    ]
    max_concentration = max(
        (row for row in primary_concentration if row["最大份额"] is not None),
        key=lambda row: row["最大份额"],
        default=None,
    )

    g_rows = {row["platform_tolerance_pct"]: row for row in phase5g.funnel_rows}
    primary_jaccards = [row["CONFIRMED_Jaccard"] for row in primary_stability]
    primary_retentions = [row["retention"] for row in primary_stability]
    lines = [
        "# SETUP_03 Phase 5I 冻结前审计报告",
        "",
        "> 本报告只使用 Phase 5G／5H 已存在的结构证据；不新增指标、分层、stress test 或参数扫描，不读取 OOS。",
        "",
        "## 冻结结论",
        "",
        f"- Freeze decision：`{spec['freeze_decision']}`。当前证据不足以冻结任何 SETUP_03 可调信号参数。",
        f"- 本轮冻结 {len(frozen)} 项证据／治理协议；另有 {len(existing)} 项既有生产规则继续保持固定，但 Phase 5I 不修改它们。",
        f"- {len(unresolved)} 项信号研究自由度明确标记为 `UNRESOLVED`，不以继续样本内搜索解决。",
        f"- Frozen dataset：`{spec['dataset']['aggregate_hash']}`（{spec['dataset']['symbol_count']} 标的／{spec['dataset']['bar_count']} bars）。",
        "",
        "## 可以冻结的内容及依据",
        "",
    ]
    for item in frozen:
        lines.append(f"- `{item['id']}`：{item['basis']}")
    lines.extend(("", "## 仍为 UNRESOLVED", ""))
    for item in unresolved:
        lines.append(
            f"- `{item['id']}`：{item['basis']} 缺口：{item['missing_evidence']}"
        )

    lines.extend(("", "## Phase 5G／5H 已有证据复核", ""))
    for tolerance in (0.0, 0.03, 0.05, 0.075, 0.1):
        row = g_rows[tolerance]
        lines.append(
            f"- Phase 5G `{tolerance:.1%}`：平台 {row['平台识别数量']}，"
            f"CONFIRMED {row['CONFIRMED事件数']}，ENTRY_ALLOWED {row['ENTRY_ALLOWED']}，"
            f"EXECUTED {row['EXECUTED']}。"
        )
    if primary_jaccards:
        lines.append(
            f"- Phase 5H 主研究区相邻 CONFIRMED Jaccard："
            f"{min(primary_jaccards):.2%}～{max(primary_jaccards):.2%}；"
            f"retention：{min(primary_retentions):.2%}～{max(primary_retentions):.2%}。"
        )
    drift_rows = [row for row in primary_stability if row["日期匹配事件"]]
    if drift_rows:
        details = "、".join(
            f"{row['前一tolerance']:.1%}→{row['当前tolerance']:.1%} "
            f"median {row['日期漂移_median_days']:.1f}d"
            for row in drift_rows
        )
        lines.append(f"- 主研究区存在同标的确认日期漂移：{details}。")

    lines.extend(("", "## 市场／regime／样本依赖", ""))
    coverage = "、".join(f"{row['市场']}={row['bars']} bars" for row in coverage_rows)
    lines.append(f"- 实际市场覆盖：{coverage}；无 JP。样本规模和市场分布明显不均。")
    if max_concentration is not None:
        lines.append(
            f"- 主研究区已有集中度字段的最高观察值为 {max_concentration['最大份额']:.2%} "
            f"（{max_concentration['维度']}，{max_concentration['最大分组']}，"
            f"tolerance={max_concentration['platform_tolerance_pct']:.1%}）；"
            "事件样本仍少，只能描述，不能支持 market-specific freeze。"
        )
    lines.append(
        "- Phase 5G／5H 没有定义 regime 分层，因此不存在可用于冻结 regime-specific 规则的允许证据。"
    )

    lines.extend(("", "## Stress boundary 脆弱性", ""))
    for row in stress_stability:
        drift = (
            "无可匹配日期漂移"
            if row["日期漂移_median_days"] is None
            else f"日期漂移 median={row['日期漂移_median_days']:.1f}d"
        )
        lines.append(
            f"- `{row['前一tolerance']:.1%}→{row['当前tolerance']:.1%}`："
            f"Jaccard={row['CONFIRMED_Jaccard']:.2%}，retention={row['retention']:.2%}，"
            f"新增={row['新增事件']}，消失={row['消失事件']}，{drift}。"
        )
    lines.extend(
        (
            "",
            "## 是否足以进入正式 parameter freeze",
            "",
            "不足。Phase 5G 证明零容差是退化的精确相等语义，但不能据此选择替代值；"
            "Phase 5H 显示主研究区仅部分稳定，仍有事件日期漂移，stress boundary 更脆弱，"
            "且 universe 小、市场不均、无 JP、没有 regime 证据。正确结论是保留策略参数为 `UNRESOLVED`，"
            "冻结证据身份和禁止继续调参的治理边界，而不是继续微调或提前查看 OOS。",
            "",
            "Phase 5I 后不得在 OOS 前继续调参；任何正式冻结或 OOS 设计都需要独立授权和显式版本变更。",
            "",
        )
    )
    return "\n".join(lines)

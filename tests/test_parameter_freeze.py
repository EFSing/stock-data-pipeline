import ast
import copy
import json
from pathlib import Path
import unittest

from research.frozen_validation import PHASE5E_DATASET_HASH
from research.parameter_freeze import (
    SPEC_PATH,
    _validate_spec,
    critical_values_hash,
    load_frozen_spec,
    phase5i_freeze_artifacts,
    serialize_frozen_spec,
)
from research.platform_structure_calibration import (
    CALIBRATION_TOLERANCES,
    PRIMARY_TOLERANCES,
    VOLATILITY_WINDOW,
    PlatformStructureArtifacts,
)
from research.platform_tolerance_sensitivity import (
    PLATFORM_TOLERANCES,
    PlatformToleranceArtifacts,
)
from scripts.run_setup03_replay import main as replay_main


EXPECTED_FREEZE_VERSION = "SETUP_03-FREEZE-2026-08-26-v1"
EXPECTED_CRITICAL_HASH = (
    "sha256:447b20182f54b8c994042227bbfbaf94c50b2a9b4ade7332058a014915390a15"
)


def phase5g_artifacts():
    rows = tuple(
        {
            "platform_tolerance_pct": tolerance,
            "平台识别数量": index,
            "CONFIRMED事件数": index,
            "ENTRY_ALLOWED": 0,
            "EXECUTED": 0,
        }
        for index, tolerance in enumerate(PLATFORM_TOLERANCES)
    )
    return PlatformToleranceArtifacts(rows, (), (), (), (), ())


def phase5h_artifacts():
    market_rows = []
    for index, tolerance in enumerate(CALIBRATION_TOLERANCES):
        market_rows.extend(
            (
                {
                    "platform_tolerance_pct": tolerance,
                    "市场": "ALL",
                    "bars": 6032,
                },
                {
                    "platform_tolerance_pct": tolerance,
                    "市场": "US",
                    "bars": 3099,
                },
                {
                    "platform_tolerance_pct": tolerance,
                    "市场": "CN",
                    "bars": 1450,
                },
                {
                    "platform_tolerance_pct": tolerance,
                    "市场": "SE",
                    "bars": 749,
                },
                {
                    "platform_tolerance_pct": tolerance,
                    "市场": "HK",
                    "bars": 734,
                },
            )
        )
    stability = tuple(
        {
            "前一tolerance": previous,
            "当前tolerance": current,
            "市场": "ALL",
            "CONFIRMED_Jaccard": 0.8 if current <= 0.055 else 0.5,
            "retention": 1.0 if current <= 0.055 else 0.7,
            "新增事件": 1,
            "消失事件": 0,
            "日期匹配事件": 0,
            "日期漂移_median_days": None,
        }
        for previous, current in zip(CALIBRATION_TOLERANCES, CALIBRATION_TOLERANCES[1:])
    )
    concentration = tuple(
        {
            "platform_tolerance_pct": tolerance,
            "范围": "ALL",
            "维度": dimension,
            "最大份额": 0.5,
            "最大分组": "US" if dimension == "market" else "TEST",
        }
        for tolerance in PRIMARY_TOLERANCES
        for dimension in ("market", "symbol")
    )
    return PlatformStructureArtifacts(tuple(market_rows), stability, (), concentration)


class ParameterFreezeTests(unittest.TestCase):
    def test_spec_is_stable_machine_readable_and_complete(self):
        spec = load_frozen_spec()
        self.assertEqual(spec["freeze_version"], EXPECTED_FREEZE_VERSION)
        self.assertEqual(critical_values_hash(spec), EXPECTED_CRITICAL_HASH)
        self.assertEqual(
            spec["integrity"]["critical_values_sha256"], EXPECTED_CRITICAL_HASH
        )
        self.assertEqual(spec["freeze_decision"], "NOT_READY_FOR_FORMAL_PARAMETER_FREEZE")
        statuses = {item["status"] for item in spec["parameter_inventory"]}
        self.assertEqual(
            statuses,
            {
                "FIXED_EXISTING",
                "FROZEN_PHASE5I",
                "RETAINED_NOT_FROZEN",
                "DEPRECATED",
                "OUT_OF_SCOPE_NOT_SETUP03_PARAMETER",
                "UNRESOLVED",
            },
        )
        self.assertTrue(spec["governance"]["parameter_changes_before_oos_forbidden"])
        self.assertFalse(spec["governance"]["oos_started"])

    def test_spec_matches_actual_frozen_research_contracts(self):
        spec = load_frozen_spec()
        inventory = {item["id"]: item for item in spec["parameter_inventory"]}
        self.assertEqual(
            tuple(inventory["phase5g_platform_tolerance_sequence"]["value"]),
            PLATFORM_TOLERANCES,
        )
        self.assertEqual(
            frozenset(inventory["phase5h_primary_tolerance_sequence"]["value"]),
            PRIMARY_TOLERANCES,
        )
        self.assertEqual(
            tuple(
                inventory["phase5h_primary_tolerance_sequence"]["value"]
                + inventory["phase5h_stress_boundary"]["value"]
            ),
            CALIBRATION_TOLERANCES,
        )
        self.assertEqual(
            inventory["phase5h_realized_volatility_window"]["value"],
            VOLATILITY_WINDOW,
        )
        self.assertEqual(spec["dataset"]["aggregate_hash"], PHASE5E_DATASET_HASH)

    def test_critical_change_fails_without_explicit_version_update(self):
        spec = load_frozen_spec()
        changed = copy.deepcopy(spec)
        item = next(
            row for row in changed["parameter_inventory"]
            if row["id"] == "phase5h_realized_volatility_window"
        )
        item["value"] = 21
        with self.assertRaisesRegex(ValueError, "explicit freeze-version update"):
            _validate_spec(changed)

    def test_audit_consumes_only_existing_phase5g_phase5h_artifacts(self):
        artifacts = phase5i_freeze_artifacts(
            phase5g_artifacts(), phase5h_artifacts(), PHASE5E_DATASET_HASH
        )
        self.assertIn("当前证据不足以冻结任何 SETUP_03 可调信号参数", artifacts.audit_report)
        self.assertIn("`platform_tolerance_pct`", artifacts.audit_report)
        self.assertIn("无 JP", artifacts.audit_report)
        self.assertIn("不得在 OOS 前继续调参", artifacts.audit_report)
        self.assertEqual(
            json.loads(serialize_frozen_spec(artifacts.specification)),
            artifacts.specification,
        )

    def test_phase5i_rejects_live_or_incomplete_evidence_entry(self):
        with self.assertRaisesRegex(ValueError, "live history is forbidden"):
            replay_main(["--phase5i"])

    def test_phase5i_module_has_no_production_sheets_execution_or_oos_io(self):
        source = Path("research/parameter_freeze.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(
            imported_roots.isdisjoint(
                {"main", "providers", "sheets_client", "trading", "core"}
            )
        )
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "phase5i_freeze_artifacts"
        )
        called_names = {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        self.assertTrue(called_names.isdisjoint({"open", "read_text", "read_bytes"}))
        workflow = Path(".github/workflows/setup03-replay.yml").read_text()
        self.assertIn("--phase5e --phase5f --phase5g --phase5h --phase5i", workflow)


if __name__ == "__main__":
    unittest.main()

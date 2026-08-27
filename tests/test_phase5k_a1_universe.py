import ast
import copy
import json
from pathlib import Path
import random
import shutil
from tempfile import TemporaryDirectory
import unittest

from research.phase5k_a1_universe import (
    AGGREGATE_DIAGNOSTIC_INSTRUMENTS,
    CN_COHORTS,
    CN_MAIN_ACTIVE,
    CN_REGISTERED_INACTIVE,
    MANIFEST_PATH,
    MANIFEST_STATUS,
    MANIFEST_VERSION,
    PINNED_MANIFEST_SHA256_BY_VERSION,
    RESERVE_TARGETS,
    SNAPSHOT_DIR,
    CN_PRIMARY_QUOTAS,
    US_PRIMARY_QUOTAS,
    US_COHORTS,
    build_manifest,
    cn_board_status,
    filter_cn_cohort_items,
    load_manifest,
    load_selection_spec,
    load_snapshot_bundle,
    manifest_integrity_hash,
    rebuild_frozen_manifest,
    selection_spec_integrity_hash,
)
from research.structural_validation_protocol_v2 import (
    EXPECTED_PROTOCOL_VERSION,
    PINNED_PROTOCOL_SHA256_BY_VERSION,
    load_protocol,
)


def _synthetic_cohorts():
    cn = {}
    for cohort_index, cohort in enumerate(CN_COHORTS, start=1):
        rows = []
        for number in range(1, 41):
            rows.append({
                "market": "CN",
                "cohort": cohort,
                "canonical_symbol": f"CN{cohort_index:02d}{number:03d}",
                "canonical_identity": f"CN|{cohort_index}|{number}",
                "source_ticker": f"{cohort_index:02d}{number:04d}",
                "source_name": f"CN {cohort} {number}",
                "board_status": CN_MAIN_ACTIVE[number % 2],
            })
        cn[cohort] = rows
    us = {}
    for cohort_index, cohort in enumerate(US_COHORTS, start=1):
        us[cohort] = [{
            "market": "US",
            "cohort": cohort,
            "canonical_symbol": f"U{cohort_index}{number:03d}",
            "canonical_identity": f"US|U{cohort_index}{number:03d}",
            "source_name": f"US {cohort} {number}",
            "source_sector": "Synthetic",
            "source_asset_class": "Equity",
        } for number in range(1, 41)]
    return cn, us


class Phase5KA1UniverseTests(unittest.TestCase):
    def test_parent_v2_is_exactly_pinned_and_not_executed(self):
        protocol = load_protocol()
        self.assertEqual(protocol["protocol_version"], EXPECTED_PROTOCOL_VERSION)
        self.assertEqual(
            protocol["integrity"]["protocol_sha256"],
            PINNED_PROTOCOL_SHA256_BY_VERSION[EXPECTED_PROTOCOL_VERSION],
        )
        self.assertFalse(protocol["scope"]["phase5k_validation_ohlcv_accessed"])
        self.assertFalse(protocol["scope"]["setup03_output_accessed"])

    def test_selection_spec_is_machine_readable_and_pinned(self):
        spec = load_selection_spec()
        self.assertEqual(spec["selection_spec_version"], "SETUP_03-CN-US-UNIVERSE-SELECTION-2026-08-27-v1")
        self.assertEqual(spec["integrity"]["selection_spec_sha256"], selection_spec_integrity_hash(spec))
        self.assertEqual(spec["ranking"]["algorithm"], "SHA-256")
        self.assertTrue(spec["ranking"]["selection_inputs_are_non_signal_only"])

    def test_three_cn_official_snapshots_are_http_200_code_zero(self):
        provenance = json.loads((SNAPSHOT_DIR / "snapshot_provenance.json").read_text(encoding="utf-8"))
        records = {record["cohort"]: record for record in provenance["source_snapshots"] if record["source_id"].startswith("HITHINK_")}
        self.assertEqual(set(records), set(CN_COHORTS))
        for cohort in CN_COHORTS:
            record = records[cohort]
            self.assertEqual(record["http_status"], 200)
            self.assertEqual(record["api_success_state"], "HTTP_200_API_CODE_0")
            self.assertIsNotNone(record["api_data_timestamp"])
            raw = (Path(record["raw_snapshot_path"]).resolve()).read_bytes()
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["code"], 0)
            self.assertEqual(len(payload["data"]["item"]), record["constituent_count"])
            self.assertTrue(record["raw_snapshot_sha256"].startswith("sha256:"))

    def test_cn_main_board_filter_excludes_star_and_chinext_as_registered_inactive(self):
        items = [
            {"thscode": "600000.SH", "ticker": "600000", "name": "SSE main"},
            {"thscode": "000001.SZ", "ticker": "000001", "name": "SZSE main"},
            {"thscode": "688001.SH", "ticker": "688001", "name": "STAR"},
            {"thscode": "300001.SZ", "ticker": "300001", "name": "ChiNext"},
        ]
        eligible, diagnostics = filter_cn_cohort_items("CSI300", items)
        self.assertEqual({row["canonical_symbol"] for row in eligible}, {"600000.SH", "000001.SZ"})
        self.assertEqual(set(diagnostics["registered_inactive_statuses_preserved"]), set(CN_REGISTERED_INACTIVE))
        self.assertEqual(diagnostics["excluded_by_board_status"], {
            "CN_CHINEXT_REGISTERED_INACTIVE": 1,
            "CN_STAR_REGISTERED_INACTIVE": 1,
        })
        self.assertEqual(cn_board_status("688001.SH"), "CN_STAR_REGISTERED_INACTIVE")
        self.assertEqual(cn_board_status("300001.SZ"), "CN_CHINEXT_REGISTERED_INACTIVE")

    def test_frozen_manifest_has_exact_quota_split_and_aggregate_diagnostics(self):
        manifest = load_manifest()
        self.assertEqual(manifest["manifest_version"], MANIFEST_VERSION)
        self.assertEqual(manifest["status"], MANIFEST_STATUS)
        self.assertEqual(manifest["counts"], {
            "CN": {"PRIMARY": 40, "RESERVE": 20},
            "US": {"PRIMARY": 40, "RESERVE": 20},
            "total": {"PRIMARY": 80, "RESERVE": 40},
        })
        self.assertEqual(
            manifest["aggregate_diagnostic_instruments"]["instruments"],
            list(AGGREGATE_DIAGNOSTIC_INSTRUMENTS),
        )
        self.assertEqual(
            manifest["aggregate_diagnostic_instruments"]["role"],
            "AGGREGATE_DIAGNOSTIC_ONLY",
        )
        self.assertTrue(all(
            row["canonical_symbol"] not in AGGREGATE_DIAGNOSTIC_INSTRUMENTS
            for row in manifest["symbols"]
        ))
        for market, quotas in (("CN", CN_PRIMARY_QUOTAS), ("US", US_PRIMARY_QUOTAS)):
            for cohort, quota in quotas.items():
                self.assertEqual(
                    sum(row["market"] == market and row["source_cohort"] == cohort and row["intended_role"] == "PRIMARY" for row in manifest["symbols"]),
                    quota,
                )
        for row in manifest["symbols"]:
            if row["market"] == "CN":
                self.assertIn(row["board_status"], CN_MAIN_ACTIVE)

    def test_cn_and_us_duplicate_attribution_uses_first_declared_cohort(self):
        cn, us = _synthetic_cohorts()
        baseline = build_manifest(cn, us, generated_at="2026-08-27T00:00:00+08:00")
        selected_cn = next(row for row in baseline["symbols"] if row["market"] == "CN" and row["source_cohort"] == "CSI300")
        duplicate_cn = dict(next(row for row in cn["CSI300"] if row["canonical_symbol"] == selected_cn["canonical_symbol"]))
        duplicate_cn["cohort"] = "CSI500"
        cn["CSI500"].append(duplicate_cn)
        selected_us = next(row for row in baseline["symbols"] if row["market"] == "US" and row["source_cohort"] == "SP500")
        duplicate_us = dict(next(row for row in us["SP500"] if row["canonical_symbol"] == selected_us["canonical_symbol"]))
        duplicate_us["cohort"] = "NASDAQ100"
        us["NASDAQ100"].append(duplicate_us)
        manifest = build_manifest(cn, us, generated_at="2026-08-27T00:00:00+08:00")
        for market, duplicate in (("CN", selected_cn), ("US", selected_us)):
            rows = [row for row in manifest["symbols"] if row["market"] == market and row["canonical_symbol"] == duplicate["canonical_symbol"]]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["source_cohort"], "CSI300" if market == "CN" else "SP500")

    def test_manifest_is_invariant_to_input_order(self):
        cn, us = _synthetic_cohorts()
        first = build_manifest(cn, us, generated_at="2026-08-27T00:00:00+08:00")
        shuffled_cn = {key: list(value) for key, value in cn.items()}
        shuffled_us = {key: list(value) for key, value in us.items()}
        rng = random.Random(20260827)
        for rows in list(shuffled_cn.values()) + list(shuffled_us.values()):
            rng.shuffle(rows)
        second = build_manifest(shuffled_cn, shuffled_us, generated_at="2026-08-27T00:00:00+08:00")
        self.assertEqual(first, second)

    def test_frozen_snapshot_exactly_reproduces_frozen_manifest(self):
        self.assertEqual(load_manifest(), rebuild_frozen_manifest())

    def test_frozen_duplicates_are_attributed_to_first_declared_cohort(self):
        _, cn, us = load_snapshot_bundle()
        manifest = load_manifest()
        for market, cohorts in (("CN", CN_COHORTS), ("US", US_COHORTS)):
            rows_by_symbol = {}
            source_rows = cn if market == "CN" else us
            for cohort in cohorts:
                for row in source_rows[cohort]:
                    rows_by_symbol.setdefault(row["canonical_symbol"], []).append(cohort)
            duplicate_symbols = [symbol for symbol, memberships in rows_by_symbol.items() if len(memberships) > 1]
            if market == "US":
                self.assertTrue(duplicate_symbols, "US source snapshots unexpectedly have no overlap")
            for row in [item for item in manifest["symbols"] if item["market"] == market]:
                memberships = rows_by_symbol[row["canonical_symbol"]]
                self.assertEqual(row["source_cohort"], memberships[0])

    def test_source_snapshot_hash_change_is_detected(self):
        with TemporaryDirectory() as directory:
            copied = Path(directory) / "bundle"
            shutil.copytree(SNAPSHOT_DIR, copied)
            provenance = json.loads((copied / "snapshot_provenance.json").read_text(encoding="utf-8"))
            raw_name = Path(provenance["source_snapshots"][0]["raw_snapshot_path"]).name
            raw_path = copied / raw_name
            raw_path.write_bytes(raw_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(RuntimeError, "source snapshot hash changed"):
                load_snapshot_bundle(copied)

    def test_manifest_version_pin_rejects_content_change_after_internal_rehash(self):
        manifest = load_manifest()
        changed = copy.deepcopy(manifest)
        changed["symbols"][0]["source_name"] = "changed without a version bump"
        changed["integrity"]["manifest_sha256"] = manifest_integrity_hash(changed)
        self.assertNotEqual(
            changed["integrity"]["manifest_sha256"],
            PINNED_MANIFEST_SHA256_BY_VERSION[MANIFEST_VERSION],
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "same-version-drift.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bound to a different canonical hash"):
                load_manifest(path)

    def test_source_has_no_historical_ohlcv_or_setup03_evaluator_dependency(self):
        source_path = Path("research/phase5k_a1_universe.py")
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(imported_roots.isdisjoint({"main", "providers", "core", "trading"}))
        self.assertNotIn("/api/dump/", source)
        self.assertNotIn("fetch_historical", source)
        self.assertNotIn("evaluate_setup03", source)
        self.assertNotIn("replay_setup03_history", source)
        self.assertNotIn("Google Sheets", source)

    def test_frozen_controls_prove_no_ohlcv_and_no_evaluator_call(self):
        controls = load_manifest()["phase5k_controls"]
        self.assertFalse(controls["historical_ohlcv_fetched"])
        self.assertFalse(controls["validation_ohlcv_fetched"])
        self.assertFalse(controls["setup03_evaluator_called"])
        self.assertFalse(controls["setup03_output_accessed"])
        self.assertFalse(controls["final_oos_accessed"])


if __name__ == "__main__":
    unittest.main()

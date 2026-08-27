import ast
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.phase5k_a1_universe import load_manifest
from research.phase5k_b0_dataset_contract import (
    ALLOWED_REPLACEMENT_REASONS,
    CANONICAL_BAR_FIELDS,
    CONTRACT_PATH,
    CONTRACT_STATUS,
    CONTRACT_VERSION,
    DATE_END,
    DATE_START,
    EXPECTED_MANIFEST_SHA256,
    EXPECTED_MANIFEST_VERSION,
    EXPECTED_PROTOCOL_SHA256,
    EXPECTED_PROTOCOL_VERSION,
    PINNED_CONTRACT_SHA256,
    ContractViolation,
    contract_integrity_hash,
    deduplicate_bars,
    evaluable_bars_after_warmup,
    evaluate_coverage,
    load_contract,
    normalize_bars,
    reserve_rows_for_failures,
    required_warmup_bars,
    validate_bars,
)


def _bar(**changes):
    row = {
        "market": "CN",
        "canonical_symbol": "000001.SZ",
        "date": "2017-01-03",
        "open": 100.0,
        "high": 110.0,
        "low": 90.0,
        "close": 105.0,
        "volume": 1000.0,
        "source_provider": "HITHINK_A_SHARE_HISTORICAL_FORWARD_ADJUSTED",
        "adjustment_mode": "forward",
    }
    row.update(changes)
    return row


class Phase5KB0DatasetContractTests(unittest.TestCase):
    def test_contract_and_both_parent_identities_are_exactly_pinned(self):
        contract = load_contract()
        self.assertEqual(contract["contract_version"], CONTRACT_VERSION)
        self.assertEqual(contract["status"], CONTRACT_STATUS)
        self.assertEqual(contract["integrity"]["contract_sha256"], PINNED_CONTRACT_SHA256)
        self.assertEqual(contract_integrity_hash(contract), PINNED_CONTRACT_SHA256)
        self.assertEqual(contract["parent_protocol"]["version"], EXPECTED_PROTOCOL_VERSION)
        self.assertEqual(contract["parent_protocol"]["sha256"], EXPECTED_PROTOCOL_SHA256)
        self.assertEqual(contract["parent_a1_manifest"]["version"], EXPECTED_MANIFEST_VERSION)
        self.assertEqual(contract["parent_a1_manifest"]["sha256"], EXPECTED_MANIFEST_SHA256)

    def test_exact_date_provider_schema_and_b1_status_are_registered(self):
        contract = load_contract()
        self.assertEqual(
            contract["date_window"],
            {
                "start_date": DATE_START.isoformat(),
                "end_date": DATE_END.isoformat(),
                "inclusive": True,
                "date_semantics": "security_local_exchange_trading_date",
                "freeze_reason": contract["date_window"]["freeze_reason"],
                "post_freeze_window_change": "forbidden_even_if_confirmed_count_is_low",
            },
        )
        cn = contract["providers"]["CN"]
        self.assertEqual(cn["provider_id"], "HITHINK_A_SHARE_HISTORICAL_FORWARD_ADJUSTED")
        self.assertEqual(cn["endpoint_path"], "/api/a-share/prices/historical")
        self.assertEqual(cn["api_key_env"], "HITHINK_FINANCE_API_KEY")
        self.assertEqual(cn["request_contract"]["interval"], "1d")
        self.assertEqual(cn["request_contract"]["adjust"], "forward")
        us = contract["providers"]["US"]
        self.assertEqual(us["provider_id"], "IBKR_TWS_API_ADJUSTED_LAST")
        self.assertEqual(
            {
                key: us["request_contract"][key]
                for key in ("security_type", "bar_size", "what_to_show", "use_rth", "end_cutoff", "keep_up_to_date")
            },
            {
                "security_type": "STK",
                "bar_size": "1 day",
                "what_to_show": "ADJUSTED_LAST",
                "use_rth": 1,
                "end_cutoff": "2026-08-26",
                "keep_up_to_date": False,
            },
        )
        self.assertEqual(contract["canonical_bar_schema"]["fields"], list(CANONICAL_BAR_FIELDS))
        self.assertFalse(contract["canonical_bar_schema"]["forward_fill_allowed"])
        self.assertFalse(contract["canonical_bar_schema"]["interpolation_allowed"])
        self.assertFalse(contract["canonical_bar_schema"]["synthetic_bars_allowed"])
        self.assertEqual(
            contract["b1_manifest_schema"]["success_status"],
            "DEVELOPMENT_VALIDATION_DATASET_FROZEN_NOT_EVALUATED",
        )
        self.assertTrue(contract["b1_manifest_schema"]["must_not_be_generated_in_b0"])

    def test_same_version_tamper_fails_even_after_internal_rehash(self):
        contract = load_contract()
        changed = copy.deepcopy(contract)
        changed["coverage_rules"]["minimum_valid_daily_bars_per_market"] = 6001
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ContractViolation, "integrity mismatch"):
                load_contract(path)
            changed["integrity"]["contract_sha256"] = contract_integrity_hash(changed)
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ContractViolation, "bound to a different canonical hash"):
                load_contract(path)

    def test_normalization_preserves_missing_dates_without_filling(self):
        rows = normalize_bars(
            [
                _bar(date="2017-01-01"),
                _bar(date="2017-01-03"),
            ]
        )
        self.assertEqual([row["date"] for row in rows], ["2017-01-01", "2017-01-03"])
        self.assertEqual(len(rows), 2)

    def test_invalid_ohlc_and_post_end_date_fail_closed(self):
        with self.assertRaisesRegex(ContractViolation, "INVALID_OHLC_FAIL_CLOSED"):
            normalize_bars([_bar(open=120.0, high=110.0)])
        with self.assertRaisesRegex(ContractViolation, "INVALID_OHLC_FAIL_CLOSED"):
            normalize_bars([_bar(close=float("nan"))])
        with self.assertRaisesRegex(ContractViolation, "ADJUSTMENT_SEMANTICS_FAIL_CLOSED"):
            normalize_bars([_bar(adjustment_mode="unadjusted")])
        with self.assertRaisesRegex(ContractViolation, "outside the frozen"):
            normalize_bars([_bar(date="2026-08-27")])

    def test_exact_duplicates_are_deduped_but_conflicting_duplicates_fail(self):
        self.assertEqual(len(deduplicate_bars([_bar(), _bar(source_metadata="ignored")])), 1)
        with self.assertRaisesRegex(ContractViolation, "DATA_CONFLICT_FAIL_CLOSED"):
            deduplicate_bars([_bar(), _bar(open=101.0)])
        with self.assertRaisesRegex(ContractViolation, "duplicate symbol/date"):
            validate_bars([_bar(), _bar()])

    def test_reserve_activation_uses_frozen_rank_and_rejects_signal_reasons(self):
        manifest = load_manifest()
        primary = [
            row for row in manifest["symbols"]
            if row["market"] == "CN" and row["intended_role"] == "PRIMARY"
        ]
        failures = {
            primary[3]["canonical_symbol"]: ALLOWED_REPLACEMENT_REASONS[0],
            primary[8]["canonical_symbol"]: ALLOWED_REPLACEMENT_REASONS[1],
        }
        replacements = reserve_rows_for_failures(manifest, "CN", failures)
        self.assertEqual([row["manifest_rank"] for row in replacements], [41, 42])
        with self.assertRaisesRegex(ContractViolation, "objective and allowed"):
            reserve_rows_for_failures(manifest, "CN", {primary[0]["canonical_symbol"]: "CONFIRMED_COUNT"})
        with self.assertRaisesRegex(ContractViolation, "FINAL_DATASET_ROSTER_LOCKED"):
            reserve_rows_for_failures(
                manifest,
                "CN",
                {primary[0]["canonical_symbol"]: ALLOWED_REPLACEMENT_REASONS[0]},
                setup03_evaluation_started=True,
            )
        too_many = {
            row["canonical_symbol"]: ALLOWED_REPLACEMENT_REASONS[0]
            for row in primary[:21]
        }
        with self.assertRaisesRegex(ContractViolation, "TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW"):
            reserve_rows_for_failures(manifest, "CN", too_many)

    def test_coverage_is_independent_and_target_shortfall_is_not_lowered(self):
        passing = evaluate_coverage(
            {
                "CN": {"final_roster_count": 40, "valid_symbols": 8, "valid_daily_bars": 6000},
                "US": {"final_roster_count": 40, "valid_symbols": 32, "valid_daily_bars": 6000},
            }
        )
        self.assertEqual(passing["status"], "COVERAGE_OK")
        blocked_cn = evaluate_coverage(
            {
                "CN": {"final_roster_count": 40, "valid_symbols": 7, "valid_daily_bars": 6000},
                "US": {"final_roster_count": 40, "valid_symbols": 33, "valid_daily_bars": 7000},
            }
        )
        self.assertEqual(blocked_cn["status"], "INSUFFICIENT_COVERAGE")
        shortfall = evaluate_coverage(
            {
                "CN": {"final_roster_count": 39, "valid_symbols": 39, "valid_daily_bars": 7000},
                "US": {"final_roster_count": 40, "valid_symbols": 40, "valid_daily_bars": 7000},
            }
        )
        self.assertEqual(shortfall["status"], "TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW")
        self.assertFalse(shortfall["eligible"])

    def test_warmup_prefix_is_excluded_and_insufficient_history_fails(self):
        self.assertEqual(required_warmup_bars(), 40)
        self.assertEqual(evaluable_bars_after_warmup(list(range(41))), [40])
        with self.assertRaisesRegex(ContractViolation, "INSUFFICIENT_FOR_REQUIRED_WARMUP"):
            evaluable_bars_after_warmup(list(range(40)))

    def test_b0_module_has_no_formal_data_or_trading_io_dependency(self):
        source_path = Path("research/phase5k_b0_dataset_contract.py")
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(imported_roots.isdisjoint({"main", "providers", "sheets_client", "core", "trading"}))
        self.assertNotIn("urllib", source)
        self.assertNotIn("requests", source)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertTrue(called.isdisjoint({"fetch_historical", "evaluate_setup03", "replay_setup03_history"}))
        self.assertEqual(CONTRACT_PATH.name, "phase5k_b0_dataset_acquisition_contract.json")


if __name__ == "__main__":
    unittest.main()

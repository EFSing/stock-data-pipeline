import ast
import copy
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.phase5k_a1_universe import load_manifest
from research.phase5k_b0_dataset_contract import (
    ALLOWED_REPLACEMENT_REASONS,
    CANONICAL_BAR_FIELDS,
    CN_CONVERSION_TIMEZONE,
    CN_WIRE_END_MS,
    CN_WIRE_START_MS,
    CONTRACT_PATH,
    CONTRACT_STATUS,
    CONTRACT_VERSION,
    DATE_END,
    DATE_START,
    DATASET_READINESS_STATUS,
    EXPECTED_MANIFEST_SHA256,
    EXPECTED_MANIFEST_VERSION,
    EXPECTED_PROTOCOL_SHA256,
    EXPECTED_PROTOCOL_VERSION,
    FINAL_ROSTER_VALIDITY_MISMATCH_STATUS,
    HISTORICAL_CONTRACT_V1_SHA256,
    HISTORICAL_CONTRACT_V1_VERSION,
    IBKR_CALENDAR_CHUNKS,
    IBKR_DURATION_STR,
    PINNED_CONTRACT_SHA256,
    TARGET_ROSTER_SHORTFALL_STATUS,
    US_CONVERSION_TIMEZONE,
    VALID_ACCEPTED_STATUS,
    ContractViolation,
    build_cn_wire_request,
    build_final_roster,
    build_ibkr_contract_wire,
    build_ibkr_req_historical_data_wire,
    build_ibkr_wire_request,
    contract_integrity_hash,
    deduplicate_bars,
    evaluable_bars_after_warmup,
    evaluate_coverage,
    filter_cn_response_rows,
    filter_ibkr_chunk_rows,
    load_historical_contract_v1,
    load_contract,
    local_datetime_to_unix_ms,
    merge_ibkr_chunk_bars,
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


def _us_bar(**changes):
    row = _bar(
        market="US",
        canonical_symbol="AAPL",
        source_provider="IBKR_TWS_API_ADJUSTED_LAST",
        adjustment_mode="ADJUSTED_LAST",
    )
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

    def test_v1_remains_immutable_historical_audit_evidence(self):
        historical = load_historical_contract_v1()
        self.assertEqual(historical["contract_version"], HISTORICAL_CONTRACT_V1_VERSION)
        self.assertEqual(historical["integrity"]["contract_sha256"], HISTORICAL_CONTRACT_V1_SHA256)
        self.assertEqual(contract_integrity_hash(historical), HISTORICAL_CONTRACT_V1_SHA256)
        changed = copy.deepcopy(historical)
        changed["coverage_rules"]["minimum_valid_daily_bars_per_market"] = 6001
        with TemporaryDirectory() as directory:
            path = Path(directory) / "historical-v1-tampered.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ContractViolation, "canonical hash changed"):
                load_historical_contract_v1(path)
            changed["integrity"]["contract_sha256"] = contract_integrity_hash(changed)
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ContractViolation, "stored hash changed"):
                load_historical_contract_v1(path)

    def test_exact_date_provider_schema_and_b1_status_are_registered(self):
        contract = load_contract()
        self.assertEqual(contract["date_window"]["start_date"], DATE_START.isoformat())
        self.assertEqual(contract["date_window"]["end_date"], DATE_END.isoformat())
        self.assertTrue(contract["date_window"]["inclusive"])
        self.assertEqual(contract["date_window"]["wire_boundary_conversion"]["timezone"], CN_CONVERSION_TIMEZONE)
        self.assertEqual(contract["date_window"]["wire_boundary_conversion"]["start_unix_ms"], CN_WIRE_START_MS)
        self.assertEqual(contract["date_window"]["wire_boundary_conversion"]["end_unix_ms"], CN_WIRE_END_MS)
        cn = contract["providers"]["CN"]
        self.assertEqual(cn["provider_id"], "HITHINK_A_SHARE_HISTORICAL_FORWARD_ADJUSTED")
        self.assertEqual(cn["endpoint_path"], "/api/a-share/prices/historical")
        self.assertEqual(cn["api_key_env"], "HITHINK_FINANCE_API_KEY")
        self.assertEqual(
            cn["request_contract"]["wire_parameters"],
            ["thscode", "interval", "start", "end", "adjust"],
        )
        self.assertEqual(cn["request_contract"]["conversion_timezone"], CN_CONVERSION_TIMEZONE)
        self.assertFalse(cn["formal_fallback_allowed"])
        self.assertIn("automatic provider fallback", contract["forbidden_metrics_and_actions"])
        us = contract["providers"]["US"]
        self.assertEqual(us["provider_id"], "IBKR_TWS_API_ADJUSTED_LAST")
        self.assertEqual(
            us["request_contract"]["wire_parameters"],
            ["endDateTime", "durationStr", "barSizeSetting", "whatToShow", "useRTH", "formatDate", "keepUpToDate", "chartOptions"],
        )
        self.assertEqual(us["request_contract"]["durationStr"], IBKR_DURATION_STR)
        self.assertEqual(us["request_contract"]["barSizeSetting"], "1 day")
        self.assertEqual(us["request_contract"]["whatToShow"], "ADJUSTED_LAST")
        self.assertEqual(us["request_contract"]["useRTH"], 1)
        self.assertEqual(us["request_contract"]["formatDate"], 1)
        self.assertFalse(us["request_contract"]["keepUpToDate"])
        self.assertEqual(us["request_contract"]["chartOptions"], [])
        self.assertEqual(us["request_contract"]["timezone"], US_CONVERSION_TIMEZONE)
        self.assertFalse(us["formal_fallback_allowed"])
        self.assertEqual(contract["canonical_bar_schema"]["fields"], list(CANONICAL_BAR_FIELDS))
        self.assertFalse(contract["canonical_bar_schema"]["forward_fill_allowed"])
        self.assertFalse(contract["canonical_bar_schema"]["interpolation_allowed"])
        self.assertFalse(contract["canonical_bar_schema"]["synthetic_bars_allowed"])
        self.assertEqual(
            contract["b1_manifest_schema"]["success_status"],
            "DEVELOPMENT_VALIDATION_DATASET_FROZEN_NOT_EVALUATED",
        )
        self.assertTrue(contract["b1_manifest_schema"]["must_not_be_generated_in_b0"])
        self.assertEqual(
            contract["b1_manifest_schema"]["must_bind_active_contract_version"],
            CONTRACT_VERSION,
        )

    def test_cn_wire_contract_uses_exact_unix_ms_and_local_date_filter(self):
        self.assertEqual(
            local_datetime_to_unix_ms(datetime(2017, 1, 1), CN_CONVERSION_TIMEZONE),
            1483200000000,
        )
        self.assertEqual(
            local_datetime_to_unix_ms(datetime(2026, 8, 26, 23, 59, 59, 999000), CN_CONVERSION_TIMEZONE),
            1787759999999,
        )
        self.assertEqual(
            build_cn_wire_request("000001.SZ"),
            {
                "thscode": "000001.SZ",
                "interval": "1d",
                "start": 1483200000000,
                "end": 1787759999999,
                "adjust": "forward",
            },
        )
        rows = filter_cn_response_rows(
            [{"date": "2016-12-31"}, {"date": "2017-01-01"}, {"date": "2026-08-26"}, {"date": "2026-08-27"}]
        )
        self.assertEqual([row["date"] for row in rows], ["2017-01-01", "2026-08-26"])

    def test_ibkr_wire_contract_and_request_are_exactly_frozen(self):
        chunk = IBKR_CALENDAR_CHUNKS[0]
        self.assertEqual(
            build_ibkr_contract_wire("AAPL", 265598, "NASDAQ", "USD"),
            {
                "symbol": "AAPL",
                "conId": 265598,
                "secType": "STK",
                "exchange": "SMART",
                "primaryExchange": "NASDAQ",
                "currency": "USD",
            },
        )
        self.assertEqual(
            build_ibkr_req_historical_data_wire(chunk),
            {
                "endDateTime": "20171231 23:59:59 US/Eastern",
                "durationStr": "1 Y",
                "barSizeSetting": "1 day",
                "whatToShow": "ADJUSTED_LAST",
                "useRTH": 1,
                "formatDate": 1,
                "keepUpToDate": False,
                "chartOptions": [],
            },
        )
        self.assertEqual(
            build_ibkr_wire_request("AAPL", 265598, "NASDAQ", "USD", chunk),
            {
                "contract": build_ibkr_contract_wire("AAPL", 265598, "NASDAQ", "USD"),
                "reqHistoricalData": build_ibkr_req_historical_data_wire(chunk),
            },
        )

    def test_ibkr_calendar_chunks_have_deterministic_conversion_and_strict_filter(self):
        self.assertEqual(len(IBKR_CALENDAR_CHUNKS), 10)
        self.assertEqual(
            build_ibkr_req_historical_data_wire(IBKR_CALENDAR_CHUNKS[-1])["endDateTime"],
            "20260826 23:59:59 US/Eastern",
        )
        rows = filter_ibkr_chunk_rows(
            [_us_bar(date="2017-01-01"), _us_bar(date="2017-12-31"), _us_bar(date="2018-01-01")],
            IBKR_CALENDAR_CHUNKS[0],
        )
        self.assertEqual([row["date"] for row in rows], ["2017-01-01", "2017-12-31"])
        self.assertEqual(
            len(merge_ibkr_chunk_bars({"2017": [_us_bar(), _us_bar(source_metadata="ignored")]})),
            1,
        )
        with self.assertRaisesRegex(ContractViolation, "DATA_CONFLICT_FAIL_CLOSED"):
            merge_ibkr_chunk_bars({"2017": [_us_bar(), _us_bar(close=106.0)]})

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

    def test_active_v2_version_and_stored_hash_tamper_fail(self):
        contract = load_contract()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tampered-v2.json"
            changed_version = copy.deepcopy(contract)
            changed_version["contract_version"] += "-tampered"
            path.write_text(json.dumps(changed_version), encoding="utf-8")
            with self.assertRaisesRegex(ContractViolation, "contract version changed"):
                load_contract(path)

            changed_hash = copy.deepcopy(contract)
            changed_hash["integrity"]["contract_sha256"] = "sha256:tampered"
            path.write_text(json.dumps(changed_hash), encoding="utf-8")
            with self.assertRaisesRegex(ContractViolation, "integrity mismatch"):
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

    def test_hard_minimum_does_not_override_40_valid_symbol_readiness(self):
        mismatch = evaluate_coverage(
            {
                "CN": {"final_roster_count": 40, "valid_symbols": 8, "valid_daily_bars": 6000},
                "US": {"final_roster_count": 40, "valid_symbols": 32, "valid_daily_bars": 6000},
            }
        )
        self.assertEqual(mismatch["status"], FINAL_ROSTER_VALIDITY_MISMATCH_STATUS)
        self.assertTrue(mismatch["hard_minimum_eligible"])
        self.assertFalse(mismatch["dataset_readiness_eligible"])
        self.assertFalse(mismatch["eligible"])
        blocked_cn = evaluate_coverage(
            {
                "CN": {"final_roster_count": 8, "valid_symbols": 8, "valid_daily_bars": 6000},
                "US": {"final_roster_count": 32, "valid_symbols": 32, "valid_daily_bars": 7000},
            }
        )
        self.assertEqual(blocked_cn["status"], TARGET_ROSTER_SHORTFALL_STATUS)
        self.assertTrue(blocked_cn["hard_minimum_eligible"])
        self.assertFalse(blocked_cn["dataset_readiness_eligible"])
        ready = evaluate_coverage(
            {
                "CN": {"final_roster_count": 40, "valid_symbols": 40, "valid_daily_bars": 6000},
                "US": {"final_roster_count": 40, "valid_symbols": 40, "valid_daily_bars": 6000},
            }
        )
        self.assertEqual(ready["status"], "COVERAGE_OK")
        self.assertEqual(ready["dataset_readiness_status"], DATASET_READINESS_STATUS)
        self.assertTrue(ready["hard_minimum_eligible"])
        self.assertTrue(ready["dataset_readiness_eligible"])
        self.assertTrue(ready["eligible"])
        shortfall = evaluate_coverage(
            {
                "CN": {"final_roster_count": 39, "valid_symbols": 39, "valid_daily_bars": 7000},
                "US": {"final_roster_count": 40, "valid_symbols": 40, "valid_daily_bars": 7000},
            }
        )
        self.assertEqual(shortfall["status"], "TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW")
        self.assertFalse(shortfall["eligible"])

    def test_final_roster_uses_only_validated_accepted_symbols_and_ranked_reserves(self):
        manifest = load_manifest()
        rows = [row for row in manifest["symbols"] if row["market"] == "CN"]
        primary = sorted((row for row in rows if row["intended_role"] == "PRIMARY"), key=lambda row: row["manifest_rank"])
        reserves = sorted((row for row in rows if row["intended_role"] == "RESERVE"), key=lambda row: row["manifest_rank"])
        statuses = {row["canonical_symbol"]: VALID_ACCEPTED_STATUS for row in rows}
        statuses[primary[0]["canonical_symbol"]] = ALLOWED_REPLACEMENT_REASONS[0]
        statuses[primary[1]["canonical_symbol"]] = ALLOWED_REPLACEMENT_REASONS[1]
        statuses[reserves[0]["canonical_symbol"]] = ALLOWED_REPLACEMENT_REASONS[2]
        final = build_final_roster(manifest, "CN", statuses)
        self.assertEqual(len(final), 40)
        self.assertEqual([row["manifest_rank"] for row in final[:2]], [42, 43])
        self.assertTrue(all(statuses[row["canonical_symbol"]] == VALID_ACCEPTED_STATUS for row in final))
        exhausted = dict(statuses)
        for row in reserves:
            exhausted[row["canonical_symbol"]] = ALLOWED_REPLACEMENT_REASONS[0]
        with self.assertRaisesRegex(ContractViolation, TARGET_ROSTER_SHORTFALL_STATUS):
            build_final_roster(manifest, "CN", exhausted)

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
        self.assertEqual(CONTRACT_PATH.name, "phase5k_b0_dataset_acquisition_contract_v2.json")


if __name__ == "__main__":
    unittest.main()

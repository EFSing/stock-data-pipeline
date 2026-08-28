import ast
import copy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import research.phase5k_b1a_ibkr_readiness as readiness_module
from scripts import run_phase5k_b1a_ibkr_readiness as readiness_runner
from research.phase5k_b1a_ibkr_readiness import (
    API_PROVENANCE_FILE_ENV,
    API_PYTHON_PATH_ENV,
    accept_frozen_manifest,
    B0_SHA256,
    B0_VERSION,
    CAPTURE_MODE,
    CURRENCY,
    EXCHANGE,
    FROZEN_STATUS,
    FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS,
    FORMAT_DATE,
    HEAD_READY_STATUS,
    HEAD_UNAVAILABLE_STATUS,
    IDENTITY_AMBIGUOUS_STATUS,
    IDENTITY_NOT_RESOLVABLE_STATUS,
    IDENTITY_UNIQUE_STATUS,
    HOST_VERSION_EVIDENCE_FILE_ENV,
    MANIFEST_VERSION,
    PROVIDER_NOT_READY_STATUS,
    REQ_CONTRACT_DETAILS,
    REQ_HEAD_TIMESTAMP,
    ReadinessError,
    SEC_TYPE,
    VERSION_NOT_PROVEN_STATUS,
    WHAT_TO_SHOW,
    ConnectionConfig,
    build_contract_request,
    build_head_timestamp_request,
    build_readiness_manifest,
    load_us_candidates,
    manifest_integrity_hash,
    normalize_ibkr_symbol,
    resolve_identity_candidates,
    run_readiness,
    sha256_json,
    VALIDATE_EXISTING_MODE,
    validate_manifest,
    write_manifest,
    _official_package_source_sha256,
    _load_official_ibapi,
    _validate_api_provenance,
    _validate_host_version_evidence,
)
from research.phase5k_a1_universe import load_manifest
from research.phase5k_b0_dataset_contract import load_contract


def _details(symbol="AAPL", con_id=265598, primary="NASDAQ", currency="USD"):
    return SimpleNamespace(
        contract=SimpleNamespace(
            symbol=symbol,
            conId=con_id,
            secType="STK",
            exchange="SMART",
            primaryExchange=primary,
            currency=currency,
            localSymbol=symbol,
            tradingClass=symbol.replace(" ", ""),
        ),
        validExchanges="SMART,AMEX,NYSE,NASDAQ",
        longName="Apple Inc.",
        underConId=0,
    )


def _metadata(**extra):
    metadata = {
        "application": "TWS",
        "api_client_version": "test-fixture",
        "api_version": "test-fixture",
        "api_provenance": {
            "provider": "Interactive Brokers",
            "source_class": "IBKR_OFFICIAL_TWS_API_DISTRIBUTION",
            "package_name": "ibapi",
            "package_version": "test-fixture",
            "package_source_sha256": "sha256:" + "a" * 64,
            "source_reference": "https://www.interactivebrokers.com/",
            "recorded_at": "2026-08-28T00:00:00+00:00",
        },
        "server_version": 178,
        "tws_version": "10.49",
        "tws_version_source": "IBKR_TWS_ABOUT_DIALOG",
        "tws_version_evidence_sha256": "sha256:" + "b" * 64,
        "tws_version_provenance": {
            "application": "TWS",
            "version": "10.49",
            "source_class": "IBKR_TWS_ABOUT_DIALOG",
            "source_reference": "local non-sensitive TWS About evidence",
            "recorded_at": "2026-08-28T00:00:00+00:00",
            "evidence_file_sha256": "sha256:" + "b" * 64,
        },
        "host_role": "localhost",
        "connection_timestamp": "2026-08-28T00:00:00+00:00",
    }
    metadata.update(extra)
    return metadata


class _FakeSession:
    def __init__(self, details_by_symbol, probe_by_symbol, metadata=None):
        self.details_by_symbol = details_by_symbol
        self.probe_by_symbol = probe_by_symbol
        self.metadata = metadata or _metadata()
        self.probe_requests = []

    def preflight_metadata(self):
        return self.metadata

    def resolve_contract(self, canonical_symbol, ibkr_symbol):
        response = self.details_by_symbol.get(canonical_symbol, {"details": [], "errors": []})
        if "terminal" not in response:
            response = {**response, "terminal": True}
        return response

    def probe_head_timestamp(self, identity):
        self.probe_requests.append(build_head_timestamp_request(identity))
        response = self.probe_by_symbol.get(identity["ibkr_symbol"], {
            "request_timestamp": "2026-08-28T00:00:00+00:00",
            "success": True,
            "head_timestamp": "20170103 09:30:00",
        })
        if "terminal" not in response:
            response = {**response, "terminal": True}
        return response


class _ContractTimeoutSession(_FakeSession):
    def resolve_contract(self, canonical_symbol, ibkr_symbol):
        return {
            "details": [_details(symbol=canonical_symbol)],
            "errors": [],
            "terminal": False,
            "transport_error": {
                "status": "REQUEST_TIMEOUT",
                "message": "fixture contract-details timeout",
            },
        }


class Phase5KB1AReadinessTests(unittest.TestCase):
    def _complete_capture(self):
        rows = load_us_candidates(load_manifest())
        details_by_symbol = {
            row["canonical_symbol"]: {
                "details": [_details(symbol=row["canonical_symbol"], con_id=600000 + row["manifest_rank"])]
            }
            for row in rows
        }
        return run_readiness(_FakeSession(details_by_symbol, {}))

    def test_exact_parent_pins_and_sixty_input_rows(self):
        b0 = load_contract()
        a1 = load_manifest()
        self.assertEqual(b0["contract_version"], B0_VERSION)
        self.assertEqual(b0["integrity"]["contract_sha256"], B0_SHA256)
        self.assertEqual(a1["manifest_version"], "SETUP_03-CN-US-OFFICIAL-UNIVERSE-MANIFEST-2026-08-27-v2")
        self.assertEqual(a1["integrity"]["manifest_sha256"], "sha256:ded740ef98d9dbba6051d2cd47d54066ac7485785a9e6ea116f7e64076868433")
        rows = load_us_candidates(a1)
        self.assertEqual(len(rows), 60)
        self.assertEqual(sum(row["intended_role"] == "PRIMARY" for row in rows), 40)
        self.assertEqual(sum(row["intended_role"] == "RESERVE" for row in rows), 20)

    def test_connection_config_reads_only_required_env_and_safe_role(self):
        temp_root = Path(tempfile.gettempdir())
        config = ConnectionConfig.from_env({
            "IBKR_HOST": "127.0.0.1",
            "IBKR_PORT": "7497",
            "IBKR_CLIENT_ID": "41",
            "IBKR_APPLICATION": "TWS",
            API_PYTHON_PATH_ENV: str(temp_root / "TWS API" / "source" / "pythonclient"),
            API_PROVENANCE_FILE_ENV: str(temp_root / "evidence" / "ibkr-api-provenance.json"),
            HOST_VERSION_EVIDENCE_FILE_ENV: str(temp_root / "evidence" / "tws-version.json"),
            "IBKR_USERNAME": "must-not-be-read-by-config",
        })
        self.assertEqual(config.host_role, "localhost")
        self.assertEqual(config.port, 7497)
        self.assertEqual(config.client_id, 41)
        self.assertEqual(config.api_python_path.name, "pythonclient")
        with self.assertRaisesRegex(ReadinessError, "IBKR_TWS_API_PYTHON_PATH") as context:
            ConnectionConfig.from_env({
                "IBKR_HOST": "127.0.0.1",
                "IBKR_PORT": "7497",
                "IBKR_CLIENT_ID": "41",
                "IBKR_APPLICATION": "TWS",
            })
        self.assertEqual(context.exception.status, PROVIDER_NOT_READY_STATUS)
        with self.assertRaisesRegex(Exception, "missing required"):
            ConnectionConfig.from_env({"IBKR_APPLICATION": "TWS"})

    def test_symbol_normalization_is_mechanical_and_no_alias_table(self):
        self.assertEqual(normalize_ibkr_symbol(" brk.b "), "BRK B")
        self.assertEqual(normalize_ibkr_symbol("AAPL"), "AAPL")
        with self.assertRaises(ValueError):
            normalize_ibkr_symbol("AAPL/US")

    def test_exact_identity_and_head_timestamp_contracts(self):
        self.assertEqual(build_contract_request("BRK.B"), {
            "method": REQ_CONTRACT_DETAILS,
            "contract": {"symbol": "BRK B", "secType": SEC_TYPE, "exchange": EXCHANGE, "currency": CURRENCY},
        })
        request = build_head_timestamp_request({
            "ibkr_symbol": "AAPL", "conId": 265598, "secType": SEC_TYPE,
            "exchange": EXCHANGE, "primaryExchange": "NASDAQ", "currency": CURRENCY,
        })
        self.assertEqual(request["method"], REQ_HEAD_TIMESTAMP)
        self.assertEqual(request["whatToShow"], WHAT_TO_SHOW)
        self.assertEqual(request["useRTH"], 1)
        self.assertEqual(request["formatDate"], FORMAT_DATE)
        self.assertEqual(request["contract"]["conId"], 265598)
        self.assertNotIn("reqHistoricalData", request)

    def test_identity_selection_fail_closes_for_unique_ambiguous_and_unresolved(self):
        unique = resolve_identity_candidates("AAPL", [_details()])
        self.assertEqual(unique["status"], IDENTITY_UNIQUE_STATUS)
        self.assertEqual(unique["identity"]["conId"], 265598)
        ambiguous = resolve_identity_candidates("AAPL", [_details(), _details(con_id=999999)])
        self.assertEqual(ambiguous["status"], IDENTITY_AMBIGUOUS_STATUS)
        self.assertIsNone(ambiguous["identity"])
        unresolved = resolve_identity_candidates("AAPL", [_details(currency="EUR")])
        self.assertEqual(unresolved["status"], IDENTITY_NOT_RESOLVABLE_STATUS)
        self.assertIsNone(unresolved["identity"])

    def test_all_sixty_are_attempted_and_no_manual_contract_choice(self):
        rows = load_us_candidates(load_manifest())
        details_by_symbol = {
            row["canonical_symbol"]: {"details": [_details(symbol=row["canonical_symbol"], con_id=100000 + row["manifest_rank"])]}
            for row in rows
        }
        fake = _FakeSession(details_by_symbol, {})
        manifest = run_readiness(fake)
        self.assertEqual(len(manifest["candidates"]), 60)
        self.assertEqual(manifest["readiness_summary"]["primary_40"]["unique_resolved"], 40)
        self.assertEqual(manifest["readiness_summary"]["reserve_20"]["unique_resolved"], 20)
        self.assertEqual(manifest["status"], FROZEN_STATUS)
        self.assertEqual(manifest["freeze_artifact_status"], FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)
        self.assertEqual(len(fake.probe_requests), 60)
        self.assertTrue(all(request["method"] == REQ_HEAD_TIMESTAMP for request in fake.probe_requests))
        self.assertTrue(all(request["contract"]["secType"] == "STK" for request in fake.probe_requests))
        self.assertTrue(all(request["contract"]["exchange"] == "SMART" for request in fake.probe_requests))
        self.assertTrue(all(request["whatToShow"] == "ADJUSTED_LAST" for request in fake.probe_requests))
        self.assertTrue(all(request["useRTH"] == 1 for request in fake.probe_requests))
        self.assertTrue(all(request["formatDate"] == 1 for request in fake.probe_requests))
        self.assertTrue(all("reqHistoricalData" not in request for request in fake.probe_requests))

    def test_readiness_errors_do_not_replace_primary_or_use_signal_fields(self):
        rows = load_us_candidates(load_manifest())
        first = rows[0]["canonical_symbol"]
        details_by_symbol = {
            row["canonical_symbol"]: {"details": [_details(symbol=row["canonical_symbol"], con_id=200000 + row["manifest_rank"])]}
            for row in rows
        }
        details_by_symbol[first] = {"details": [_details(symbol=first), _details(symbol=first, con_id=777777)]}
        fake = _FakeSession(details_by_symbol, {})
        manifest = run_readiness(fake)
        self.assertEqual(manifest["status"], FROZEN_STATUS)
        self.assertEqual(manifest["readiness_summary"]["total_candidate_pool"], 59)
        self.assertTrue(manifest["readiness_summary"]["provider_capture_complete"])
        self.assertEqual(manifest["candidates"][0]["readiness_status"], IDENTITY_AMBIGUOUS_STATUS)
        validate_manifest(
            manifest,
            expected_hash_by_version={MANIFEST_VERSION: manifest_integrity_hash(manifest)},
        )
        serialized = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn("confirmed_count", serialized.lower())
        self.assertNotIn("forward_return", serialized.lower())
        self.assertNotIn("mfe", serialized.lower())
        self.assertNotIn("mae", serialized.lower())

    def test_head_timestamp_permission_and_unavailable_are_objective(self):
        rows = load_us_candidates(load_manifest())
        details_by_symbol = {
            row["canonical_symbol"]: {"details": [_details(symbol=row["canonical_symbol"], con_id=300000 + row["manifest_rank"])]}
            for row in rows
        }
        permission_symbol = rows[0]["canonical_symbol"]
        unavailable_symbol = rows[1]["canonical_symbol"]
        fake = _FakeSession(details_by_symbol, {
            permission_symbol: {"success": False, "head_timestamp": None, "error_code": 354, "error_message": "not subscribed"},
            unavailable_symbol: {"success": False, "head_timestamp": None, "error_code": 321, "error_message": "service unavailable"},
        })
        manifest = run_readiness(fake)
        self.assertEqual(manifest["candidates"][0]["readiness_status"], "NO_IBKR_PERMISSION")
        self.assertEqual(manifest["candidates"][1]["readiness_status"], HEAD_UNAVAILABLE_STATUS)

    def test_secret_and_account_identifiers_are_not_serialized(self):
        rows = load_us_candidates(load_manifest())
        details_by_symbol = {row["canonical_symbol"]: {"details": [], "errors": [
            {"code": 354, "message": "account=DU1234567 password=do-not-record"},
        ]} for row in rows}
        fake = _FakeSession(details_by_symbol, {}, metadata=_metadata(
            account_id="DU1234567", password="do-not-record",
        ))
        manifest = run_readiness(fake)
        serialized = json.dumps(manifest, ensure_ascii=False)
        self.assertNotIn("DU1234567", serialized)
        self.assertNotIn("do-not-record", serialized)
        self.assertIn("<account-redacted>", serialized)
        self.assertNotIn("account_id", serialized)

    def test_missing_version_metadata_fails_closed(self):
        rows = load_us_candidates(load_manifest())
        details_by_symbol = {row["canonical_symbol"]: {"details": []} for row in rows}
        fake = _FakeSession(details_by_symbol, {}, metadata={
            "application": "TWS", "api_version": "test-fixture", "server_version": 178,
            "host_role": "localhost", "connection_timestamp": "2026-08-28T00:00:00+00:00",
        })
        with self.assertRaises(ReadinessError) as context:
            run_readiness(fake)
        self.assertEqual(context.exception.status, VERSION_NOT_PROVEN_STATUS)

    def test_official_api_and_host_version_provenance_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "ibapi"
            package.mkdir()
            (package / "__init__.py").write_text("# official fixture\n", encoding="utf-8")
            source_hash = _official_package_source_sha256(package)
            provenance = _validate_api_provenance({
                "provider": "Interactive Brokers",
                "source_class": "IBKR_OFFICIAL_TWS_API_DISTRIBUTION",
                "package_name": "ibapi",
                "package_version": "10.49-fixture",
                "package_source_sha256": source_hash,
                "source_reference": "https://interactivebrokers.github.io/tws-api/",
                "recorded_at": "2026-08-28T00:00:00+00:00",
            }, python_root=root, package_root=package)
            self.assertEqual(provenance["package_name"], "ibapi")
            with self.assertRaises(ReadinessError):
                _validate_api_provenance(
                    {**provenance, "source_class": "PYPI"},
                    python_root=root,
                    package_root=package,
                )
            host = _validate_host_version_evidence({
                "application": "TWS",
                "version": "10.49.1",
                "source_class": "IBKR_TWS_ABOUT_DIALOG",
                "source_reference": "local non-sensitive TWS About evidence",
                "recorded_at": "2026-08-28T00:00:00+00:00",
            }, expected_application="TWS")
            self.assertEqual(host["source_class"], "IBKR_TWS_ABOUT_DIALOG")

    def test_official_loader_uses_declared_distribution_without_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "ibapi"
            package.mkdir()
            (package / "__init__.py").write_text("__version__ = '10.49-fixture'\n", encoding="utf-8")
            (package / "client.py").write_text("class EClient:\n    pass\n", encoding="utf-8")
            (package / "contract.py").write_text("class Contract:\n    pass\n", encoding="utf-8")
            (package / "wrapper.py").write_text("class EWrapper:\n    pass\n", encoding="utf-8")
            source_hash = _official_package_source_sha256(package)
            provenance_path = root / "api-provenance.json"
            provenance_path.write_text(json.dumps({
                "provider": "Interactive Brokers",
                "source_class": "IBKR_OFFICIAL_TWS_API_DISTRIBUTION",
                "package_name": "ibapi",
                "package_version": "10.49-fixture",
                "package_source_sha256": source_hash,
                "source_reference": "https://interactivebrokers.github.io/tws-api/",
                "recorded_at": "2026-08-28T00:00:00+00:00",
            }), encoding="utf-8")
            config = ConnectionConfig(
                host="127.0.0.1",
                port=7497,
                client_id=41,
                application="TWS",
                api_python_path=root,
                api_provenance_file=provenance_path,
                host_version_evidence_file=root / "unused-host-evidence.json",
            )
            try:
                client_class, contract_class, wrapper_class, provenance = _load_official_ibapi(config)
                self.assertEqual(client_class.__module__, "ibapi.client")
                self.assertEqual(contract_class.__module__, "ibapi.contract")
                self.assertEqual(wrapper_class.__module__, "ibapi.wrapper")
                self.assertEqual(provenance["package_version"], "10.49-fixture")
            finally:
                for module_name in ("ibapi.wrapper", "ibapi.contract", "ibapi.client", "ibapi"):
                    sys.modules.pop(module_name, None)
                while str(root) in sys.path:
                    sys.path.remove(str(root))

    def test_current_error_callback_includes_error_time(self):
        source = Path("research/phase5k_b1a_ibkr_readiness.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        error_methods = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "error"
        ]
        self.assertEqual(len(error_methods), 1)
        names = [arg.arg for arg in error_methods[0].args.args]
        self.assertEqual(names[:4], ["self", "reqId", "errorTime", "errorCode"])
        self.assertIn("errorString", names)

    def test_manifest_hash_requires_external_version_pin_and_same_version_rehash_fails(self):
        rows = load_us_candidates(load_manifest())
        records = []
        for row in rows:
            snapshot = {"fixture": row["canonical_symbol"]}
            record = {
                "market": "US", "canonical_symbol": row["canonical_symbol"], "canonical_identity": row["canonical_identity"],
                "source_cohort": row["source_cohort"], "intended_role": row["intended_role"], "manifest_rank": row["manifest_rank"],
                "ibkr_symbol": row["canonical_symbol"], "identity_request_timestamp": "2026-08-28T00:00:00+00:00",
                "identity_status": IDENTITY_UNIQUE_STATUS, "contract_identity": {
                    "ibkr_symbol": row["canonical_symbol"], "conId": 400000 + row["manifest_rank"], "secType": "STK",
                    "exchange": "SMART", "primaryExchange": "NASDAQ", "currency": "USD", "localSymbol": row["canonical_symbol"],
                    "tradingClass": row["canonical_symbol"], "validExchanges": "SMART,NASDAQ", "longName": "fixture",
                },
                "selected_contract_details_snapshot": {"snapshot": snapshot, "snapshot_sha256": sha256_json(snapshot)},
                "selected_contract_details_snapshot_sha256": sha256_json(snapshot), "all_contract_details_snapshots": [], "identity_errors": [],
                "adjusted_last_probe": {"success": True, "head_timestamp": "20170103 09:30:00"},
                "readiness_status": HEAD_READY_STATUS,
            }
            records.append(record)
        manifest = build_readiness_manifest(
            b0=load_contract(), a1=load_manifest(),
            connection=_metadata(),
            records=records, generated_at="2026-08-28T00:00:00+00:00",
        )
        self.assertEqual(manifest["integrity"]["manifest_sha256"], manifest_integrity_hash(manifest))
        with self.assertRaises(ReadinessError) as context:
            accept_frozen_manifest(manifest)
        self.assertEqual(context.exception.status, FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)
        pinned = {MANIFEST_VERSION: manifest_integrity_hash(manifest)}
        validate_manifest(manifest, expected_hash_by_version=pinned)
        changed = copy.deepcopy(manifest)
        changed["candidates"][0]["contract_identity"]["conId"] += 1
        changed["integrity"]["manifest_sha256"] = manifest_integrity_hash(changed)
        with self.assertRaisesRegex(ValueError, "different canonical hash"):
            validate_manifest(changed, expected_hash_by_version=pinned)

    def test_capture_mode_writes_candidate_but_never_reports_frozen_success(self):
        rows = load_us_candidates(load_manifest())
        details_by_symbol = {
            row["canonical_symbol"]: {
                "details": [_details(symbol=row["canonical_symbol"], con_id=700000 + row["manifest_rank"])]
            }
            for row in rows
        }
        fake = _FakeSession(details_by_symbol, {})

        class _SessionContext:
            def __enter__(self):
                return fake

            def __exit__(self, exc_type, exc_value, traceback):
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "candidate.json"
            output = StringIO()
            with patch.object(readiness_runner.ConnectionConfig, "from_env", return_value=object()), \
                patch.object(readiness_runner, "OfficialIbapiSession", return_value=_SessionContext()), \
                redirect_stdout(output):
                result = readiness_runner.main(["--mode", CAPTURE_MODE, "--output", str(path)])

            self.assertEqual(result, 2)
            self.assertEqual(output.getvalue().strip(), FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], FROZEN_STATUS)
            self.assertEqual(saved["freeze_artifact_status"], FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)

    def test_validate_existing_accepts_saved_capture_after_correct_pin_without_live_requests(self):
        manifest = self._complete_capture()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "saved-capture.json"
            write_manifest(path, manifest)
            before = path.read_bytes()
            with patch.object(
                readiness_module,
                "PINNED_MANIFEST_SHA256_BY_VERSION",
                {MANIFEST_VERSION: manifest_integrity_hash(manifest)},
            ), patch.object(
                readiness_runner.ConnectionConfig,
                "from_env",
                side_effect=AssertionError("validate-existing must not read live connection configuration"),
            ), patch.object(
                readiness_runner,
                "OfficialIbapiSession",
                side_effect=AssertionError("validate-existing must not create a live session"),
            ):
                output = StringIO()
                with redirect_stdout(output):
                    result = readiness_runner.main([
                        "--mode", VALIDATE_EXISTING_MODE, "--output", str(path),
                    ])

            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue().strip(), FROZEN_STATUS)
            self.assertEqual(path.read_bytes(), before)

    def test_validate_existing_tamper_fails_even_after_self_rehash(self):
        manifest = self._complete_capture()
        pinned = manifest_integrity_hash(manifest)
        changed = copy.deepcopy(manifest)
        changed["candidates"][0]["contract_identity"]["conId"] += 1
        changed["integrity"]["manifest_sha256"] = manifest_integrity_hash(changed)
        self.assertNotEqual(changed["integrity"]["manifest_sha256"], pinned)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tampered-capture.json"
            write_manifest(path, changed)
            output = StringIO()
            with patch.object(
                readiness_module,
                "PINNED_MANIFEST_SHA256_BY_VERSION",
                {MANIFEST_VERSION: pinned},
            ), redirect_stdout(output):
                result = readiness_runner.main([
                    "--mode", VALIDATE_EXISTING_MODE, "--output", str(path),
                ])

            self.assertEqual(result, 2)
            self.assertEqual(output.getvalue().strip(), FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)

    def test_validate_existing_missing_pin_fails_closed_without_live_requests(self):
        manifest = self._complete_capture()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "un-pinned-capture.json"
            write_manifest(path, manifest)
            output = StringIO()
            with patch.object(readiness_runner.ConnectionConfig, "from_env", side_effect=AssertionError()), \
                patch.object(readiness_runner, "OfficialIbapiSession", side_effect=AssertionError()), \
                redirect_stdout(output):
                result = readiness_runner.main([
                    "--mode", VALIDATE_EXISTING_MODE, "--output", str(path),
                ])

            self.assertEqual(result, 2)
            self.assertEqual(output.getvalue().strip(), FREEZE_ARTIFACT_NOT_ACQUIRED_STATUS)

    def test_contract_details_timeout_is_provider_blocker_not_symbol_failure(self):
        fake = _ContractTimeoutSession({}, {})
        with self.assertRaises(ReadinessError) as context:
            run_readiness(fake)
        self.assertEqual(context.exception.status, PROVIDER_NOT_READY_STATUS)
        self.assertIn(REQ_CONTRACT_DETAILS, str(context.exception))
        self.assertEqual(fake.probe_requests, [])

    def test_head_timestamp_timeout_is_provider_blocker_not_candidate_failure(self):
        rows = load_us_candidates(load_manifest())
        details_by_symbol = {
            row["canonical_symbol"]: {
                "details": [_details(symbol=row["canonical_symbol"], con_id=500000 + row["manifest_rank"])]
            }
            for row in rows
        }
        first = rows[0]["canonical_symbol"]
        fake = _FakeSession(details_by_symbol, {
            first: {
                "success": False,
                "head_timestamp": None,
                "terminal": False,
                "transport_error": {
                    "status": "REQUEST_TIMEOUT",
                    "message": "fixture head-timestamp timeout",
                },
            },
        })
        with self.assertRaises(ReadinessError) as context:
            run_readiness(fake)
        self.assertEqual(context.exception.status, PROVIDER_NOT_READY_STATUS)
        self.assertIn(REQ_HEAD_TIMESTAMP, str(context.exception))
        self.assertEqual(len(fake.probe_requests), 1)

    def test_static_source_has_no_historical_request_call_or_forbidden_dependencies(self):
        source = Path("research/phase5k_b1a_ibkr_readiness.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotEqual(node.func.attr, "reqHistoricalData")
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        self.assertTrue(imported_roots.isdisjoint({"main", "providers", "core", "trading", "sheets_client"}))
        self.assertNotIn("importlib.metadata", source)
        self.assertNotIn("ib_insync", source)
        self.assertNotIn("ib_async", source)
        self.assertNotIn("twsVersion", source)
        self.assertNotIn("twsVersionString", source)
        self.assertNotIn("ibapi>=", Path("requirements.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

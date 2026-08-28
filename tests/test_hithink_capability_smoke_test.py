import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.hithink_cn_capability_smoke_test import (
    API_KEY_ENV,
    BASE_URL,
    _response_summary,
    endpoint_specs,
    run_smoke_test,
    sha256_bytes,
)


class HiThinkCapabilitySmokeTests(unittest.TestCase):
    def test_endpoint_specs_are_bounded_read_only_probes(self):
        specs = endpoint_specs()
        self.assertEqual(len(specs), 7)
        self.assertEqual(specs[0]["capability"], "a_share_ticker_list")
        self.assertIn("limit=1", specs[0]["endpoint"])
        self.assertEqual(
            [row["capability"] for row in specs[1:4]],
            ["index_constituents", "index_constituents", "index_constituents"],
        )
        self.assertTrue(all(row["endpoint"].startswith(BASE_URL) for row in specs))
        self.assertIn("download-url", specs[4]["endpoint"])

    def test_response_summary_exposes_fields_without_raw_values(self):
        raw = json.dumps({
            "code": 0,
            "message": "ok",
            "request_id": "redacted-in-test",
            "data": {
                "timestamp": 1780000000000,
                "item": [{"thscode": "600519.SH", "ticker": "600519"}],
            },
        }).encode("utf-8")
        summary = _response_summary(200, raw, None)
        self.assertEqual(summary["api_code"], 0)
        self.assertEqual(summary["data_fields"], ["item", "timestamp"])
        self.assertEqual(summary["item_fields"], ["thscode", "ticker"])
        self.assertEqual(summary["source_data_timestamp_field"], "data.timestamp")
        self.assertNotIn("600519.SH", summary)

    def test_smoke_report_is_safe_when_key_is_absent(self):
        def fake_probe(endpoint, api_key):
            return 200, b'{"code":0,"message":"ok","request_id":"test","data":{}}', None

        with patch.dict(os.environ, {API_KEY_ENV: ""}, clear=False), TemporaryDirectory() as directory:
            result = run_smoke_test(Path(directory), probe=fake_probe)
            report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
            self.assertFalse(report["api_key_configured"])
            self.assertTrue(report["raw_response_sha256_supported"])
            self.assertFalse(report["scope"]["formal_phase5k_dataset_built"])
            self.assertFalse(report["scope"]["phase5k_validation_ohlcv_accessed"])
            self.assertFalse(report["scope"]["setup03_output_accessed"])
            self.assertFalse(report["scope"]["final_oos_accessed"])
            self.assertEqual(len(report["results"]), 7)
            for row in report["results"]:
                self.assertTrue(row["raw_response_sha256"].startswith("sha256:"))
                self.assertTrue(Path(row["raw_response_path"]).exists())
                self.assertNotIn("api_key", row)

    def test_configured_key_changes_only_auth_header_input_and_never_report_content(self):
        seen_keys = []

        def fake_probe(endpoint, api_key):
            seen_keys.append(api_key)
            return 401, b'{"code":2001,"message":"unauthorized","data":{}}', None

        with patch.dict(os.environ, {API_KEY_ENV: "test-secret"}, clear=False), TemporaryDirectory() as directory:
            result = run_smoke_test(Path(directory), probe=fake_probe)
            report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
            self.assertTrue(report["api_key_configured"])
            self.assertEqual(seen_keys, ["test-secret"] * 7)
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("test-secret", serialized)
            self.assertIn("api_key_configured", serialized)

    def test_hash_is_stable(self):
        self.assertEqual(sha256_bytes(b"probe"), sha256_bytes(b"probe"))


if __name__ == "__main__":
    unittest.main()

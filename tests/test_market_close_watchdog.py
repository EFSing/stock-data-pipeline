from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

_WATCHDOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "infra" / "vps" / "market-close-watchdog" / "market_close_watchdog.py"
)
_SPEC = importlib.util.spec_from_file_location("market_close_watchdog_test_module", _WATCHDOG_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
load_config = _MODULE.load_config
reconcile_workflow = _MODULE.reconcile_workflow
run_watchdog = _MODULE.run_watchdog


class _Response:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}

    def read(self):
        return b"" if self.payload is None else json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _config():
    return {
        "github_token": "fixture-token-not-printed",
        "repository": "EFSing/stock-data-pipeline",
        "ref": "main",
        "api_url": "https://api.github.com",
        "workflow_overrides": {
            "CN": {
                "DAILY_REPORT": "cn-daily-report.yml",
                "D1_PROSPECTIVE": "setup01-d1-vps-natural-collector-cn.yml",
            },
            "US": {
                "DAILY_REPORT": "us-daily-report.yml",
                "D1_PROSPECTIVE": "setup01-d1-vps-natural-collector-us.yml",
            },
        },
    }


class WatchdogTests(unittest.TestCase):
    NOW = datetime(2026, 9, 29, 10, 5, tzinfo=timezone.utc)

    def test_recent_success_is_noop(self):
        calls = []

        def opener(request, timeout=0):
            calls.append(request.full_url)
            return _Response({"workflow_runs": [{
                "id": 1,
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-09-29T09:50:00Z",
            }]})

        result = reconcile_workflow(
            _config(), market="CN", kind="D1_PROSPECTIVE", now=self.NOW,
            opener=opener, sleep=lambda _: None,
        )
        self.assertEqual(result["status"], "NOOP_PRIMARY_ACTIVE_OR_SUCCESS")
        self.assertEqual(len(calls), 1)

    def test_later_vps_check_keeps_older_daily_success_inside_bounded_window(self):
        calls = []

        def opener(request, timeout=0):
            calls.append(request.full_url)
            return _Response({"workflow_runs": [{
                "id": 11,
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-09-29T08:00:00Z",
            }]})

        result = reconcile_workflow(
            _config(), market="CN", kind="DAILY_REPORT", now=self.NOW,
            opener=opener, sleep=lambda _: None,
        )
        self.assertEqual(result["status"], "NOOP_PRIMARY_ACTIVE_OR_SUCCESS")
        self.assertEqual(len(calls), 1)

    def test_missing_run_dispatches_market_specific_workflow(self):
        calls = []

        def opener(request, timeout=0):
            calls.append(request)
            if len(calls) == 1:
                return _Response({"workflow_runs": []})
            return _Response(status=204)

        result = reconcile_workflow(
            _config(), market="US", kind="DAILY_REPORT", now=self.NOW,
            opener=opener, sleep=lambda _: None,
        )
        self.assertEqual(result["status"], "DISPATCHED_RECONCILIATION")
        self.assertIn("us-daily-report.yml", calls[1].full_url)
        self.assertEqual(json.loads(calls[1].data.decode("utf-8"))["ref"], "main")

    def test_429_is_bounded_before_success(self):
        calls = []
        sleeps = []

        def opener(request, timeout=0):
            calls.append(request)
            if len(calls) == 1:
                return _Response({"message": "rate limit"}, status=429, headers={"Retry-After": "0"})
            return _Response({"workflow_runs": [{
                "id": 2,
                "status": "in_progress",
                "created_at": "2026-09-29T10:00:00Z",
            }]})

        result = reconcile_workflow(
            _config(), market="CN", kind="DAILY_REPORT", now=self.NOW,
            opener=opener, sleep=sleeps.append,
        )
        self.assertEqual(result["status"], "NOOP_PRIMARY_ACTIVE_OR_SUCCESS")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(sleeps), 1)

    def test_run_watchdog_reconciles_daily_and_d1_independently(self):
        calls = []

        def opener(request, timeout=0):
            calls.append(request.full_url)
            if request.method == "GET":
                return _Response({"workflow_runs": []})
            return _Response(status=204)

        result = run_watchdog(
            _config(), market="US", now=self.NOW, opener=opener, sleep=lambda _: None,
        )
        self.assertEqual([item["status"] for item in result["results"]], [
            "DISPATCHED_RECONCILIATION", "DISPATCHED_RECONCILIATION",
        ])
        self.assertTrue(any("us-daily-report.yml" in item for item in calls))
        self.assertTrue(any("setup01-d1-vps-natural-collector-us.yml" in item for item in calls))

    def test_config_must_be_private(self):
        if os.name == "nt":
            self.skipTest("POSIX file mode enforcement is validated on the Ubuntu VPS")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "watchdog.json"
            path.write_text(json.dumps(_config()), encoding="utf-8")
            path.chmod(0o644)
            if os.name != "nt":
                with self.assertRaisesRegex(ValueError, "0600"):
                    load_config(path)
            path.chmod(0o600)
            self.assertEqual(load_config(path)["repository"], "EFSing/stock-data-pipeline")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
VPS = ROOT / "infra" / "vps" / "market-close-watchdog"
SPEC = importlib.util.spec_from_file_location("market_close_watchdog", VPS / "market_close_watchdog.py")
scheduler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(scheduler)


class WatchdogTests(unittest.TestCase):
    NOW = datetime(2026, 11, 24, 10, 5, tzinfo=timezone.utc)

    def test_app_installation_token_is_minted_for_this_repository_only(self):
        request = Mock(side_effect=[
            {"id": 456, "app_slug": "fixture-scheduler"},
            {"token": "fixture-installation-token"},
        ])
        with patch.object(scheduler, "_jwt", return_value="fixture-jwt"):
            token, actor = scheduler.installation_token("fixture-client", Path("fixture.pem"), request=request)

        self.assertEqual(token, "fixture-installation-token")
        self.assertEqual(actor, "fixture-scheduler[bot]")
        request.assert_any_call("GET", "/repos/EFSing/stock-data-pipeline/installation", "fixture-jwt")
        request.assert_called_with(
            "POST", "/app/installations/456/access_tokens", "fixture-jwt",
            {"repositories": ["stock-data-pipeline"], "permissions": {"actions": "write"}},
        )

    def test_close_dispatch_uses_latest_and_main_for_both_markets(self):
        for job, workflow in [("cn-close", "asia-close.yml"), ("us-close", "us-close.yml")]:
            with self.subTest(job=job):
                request = Mock(return_value={})
                result = scheduler.dispatch_job(job, "fixture-token", request=request)
                self.assertEqual(result["status"], "DISPATCHED")
                request.assert_called_once_with(
                    "POST", f"/repos/EFSing/stock-data-pipeline/actions/workflows/{workflow}/dispatches",
                    "fixture-token", {"ref": "main", "inputs": {"mode": "latest"}},
                )

    def test_active_report_suppresses_a_duplicate(self):
        request = Mock(return_value={"workflow_runs": [{"id": 12, "status": "in_progress", "conclusion": None}]})
        result = scheduler.dispatch_job("cn-report", "fixture-token", now=self.NOW, request=request)
        self.assertEqual(result["status"], "NOOP_ACTIVE_OR_COMPLETE")
        self.assertEqual(result["run_id"], 12)
        self.assertEqual(request.call_count, 1)
        query = parse_qs(urlsplit(request.call_args.args[1]).query)
        self.assertEqual(query["branch"], ["main"])
        self.assertEqual(query["created"], [">=2026-11-24T06:05:00Z"])

    def test_report_fallback_still_runs_after_a_potentially_partial_success(self):
        request = Mock(side_effect=[
            {"workflow_runs": [{"id": 12, "status": "completed", "conclusion": "success"}]},
            {},
        ])
        result = scheduler.dispatch_job("us-report", "fixture-token", now=self.NOW, request=request)
        self.assertEqual(result["status"], "DISPATCHED")
        request.assert_called_with(
            "POST", "/repos/EFSing/stock-data-pipeline/actions/workflows/us-daily-report.yml/dispatches",
            "fixture-token", {"ref": "main", "inputs": {}},
        )

    def test_only_failed_or_missing_d1_dispatches_at_the_next_slot(self):
        for runs, expected in [
            ([{"id": 12, "status": "completed", "conclusion": "success"}], "NOOP_ACTIVE_OR_COMPLETE"),
            ([{"id": 13, "status": "completed", "conclusion": "failure"}], "DISPATCHED"),
            ([], "DISPATCHED"),
        ]:
            with self.subTest(runs=runs):
                request = Mock(side_effect=[{"workflow_runs": runs}, {}])
                result = scheduler.dispatch_job("cn-d1", "fixture-token", now=self.NOW, request=request)
                self.assertEqual(result["status"], expected)

    def test_rate_limit_retries_but_network_failure_does_not_repeat_dispatch(self):
        path = "/repos/example/example/actions/workflows/example.yml/dispatches"
        throttled = HTTPError(f"https://api.github.com{path}", 429, "rate limited", {}, None)
        opener = Mock(side_effect=[throttled, URLError("fixture-network-error")])
        sleep = Mock()
        with self.assertRaisesRegex(RuntimeError, "GITHUB_API_NETWORK_ERROR"):
            scheduler._request("POST", path, "fixture-token", opener=opener, sleep=sleep)
        self.assertEqual(opener.call_count, 2)
        sleep.assert_called_once()

    @unittest.skipIf(os.name == "nt", "POSIX file modes are enforced on Ubuntu")
    def test_config_and_key_must_be_private(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scheduler.json"
            key_path = path.with_name("scheduler.pem")
            path.write_text(json.dumps({
                "github_app_client_id": "fixture-client",
                "github_app_private_key_file": key_path.name,
            }), encoding="utf-8")
            key_path.touch()
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "scheduler.json must be a private file"):
                scheduler.load_config(path)
            path.chmod(0o600)
            key_path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "scheduler.pem must be a private file"):
                scheduler.load_config(path)
            key_path.chmod(0o600)
            self.assertEqual(scheduler.load_config(path), ("fixture-client", key_path))

    def test_vps_owns_all_six_schedules(self):
        schedules = {
            "cn-close": ("17:30",),
            "cn-report": ("17:45", "18:00", "18:30", "20:05"),
            "cn-d1": ("18:40", "18:55", "20:05"),
            "us-close": ("08:30",),
            "us-report": ("09:15", "09:30", "10:00", "11:05"),
            "us-d1": ("09:40", "09:55", "11:05"),
        }
        self.assertEqual(set(scheduler.WORKFLOWS), set(schedules))
        for job, slots in schedules.items():
            with self.subTest(job=job):
                timer = (VPS / "systemd" / f"market-close-schedule@{job}.timer").read_text(encoding="utf-8")
                days = "Mon..Fri" if job.startswith("cn-") else "Tue..Sat"
                self.assertEqual(
                    [line for line in timer.splitlines() if line.startswith("OnCalendar=")],
                    [f"OnCalendar={days} *-*-* {slot}:00 Asia/Shanghai" for slot in slots],
                )
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            self.assertNotIn("\n  schedule:", workflow.read_text(encoding="utf-8"), workflow.name)
        self.assertIn("crons = []", (ROOT / "infra/cloudflare/market-close-watchdog/wrangler.toml").read_text())


if __name__ == "__main__":
    unittest.main()

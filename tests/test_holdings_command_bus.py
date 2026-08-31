import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from holdings_command_bus import (
    COMMAND_TITLE,
    CommandBusError,
    parse_command_body,
    parse_issue_event,
    render_result_comment,
)
from scripts.holdings_command_bridge import execute_event, main
from holdings_data_manager import OperationResult


ROOT = Path(__file__).resolve().parents[1]


def command_body(**overrides):
    payload = {
        "version": 1,
        "operation": "ADD",
        "symbol": "MU",
        "request_id": "chatgpt-20260831-0001",
        "dry_run": True,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def issue_event(body, *, repository="EFSing/stock-data-pipeline", title=COMMAND_TITLE,
                action="opened", sender="EFSing", issue_user="EFSing", number=17,
                pull_request=False):
    issue = {
        "number": number,
        "title": title,
        "body": body,
        "user": {"login": issue_user},
    }
    if pull_request:
        issue["pull_request"] = {"url": "https://example.invalid/pull"}
    return {
        "action": action,
        "repository": {"full_name": repository},
        "sender": {"login": sender},
        "issue": issue,
    }


class HoldingsCommandSchemaTests(unittest.TestCase):
    def test_valid_v1_command_and_optional_market(self):
        command = parse_command_body(command_body(market="US"))
        self.assertEqual(command.operation, "ADD")
        self.assertEqual(command.symbol, "MU")
        self.assertEqual(command.market, "US")
        self.assertTrue(command.dry_run)

    def test_strict_schema_rejects_unknown_missing_and_wrong_types(self):
        cases = (
            command_body(extra="reject"),
            command_body().replace('"request_id":', '"missing_request_id":', 1),
            command_body(operation="DELETE"),
            command_body(operation="add"),
            command_body(symbol=["MU"]),
            command_body(symbol="MU INTC"),
            command_body(dry_run="true"),
            "```json\n" + command_body() + "\n```",
        )
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaises(CommandBusError):
                    parse_command_body(body)

    def test_duplicate_json_key_and_nonstandard_json_fail_closed(self):
        with self.assertRaises(CommandBusError):
            parse_command_body('{"version":1,"version":1,"operation":"ADD",'
                               '"symbol":"MU","request_id":"r1","dry_run":true}')
        with self.assertRaises(CommandBusError):
            parse_command_body('{"version":1,"operation":"ADD","symbol":"MU",'
                               '"request_id":"r1","dry_run":NaN}')

    def test_issue_envelope_guards_repository_title_actor_action_and_pr(self):
        cases = (
            issue_event(command_body(), repository="attacker/fork"),
            issue_event(command_body(), title="[HOLDINGS_COMMAND] ADD MU"),
            issue_event(command_body(), action="edited"),
            issue_event(command_body(), sender="attacker"),
            issue_event(command_body(), issue_user="attacker"),
            issue_event(command_body(), pull_request=True),
        )
        for event in cases:
            with self.subTest(event=event):
                with self.assertRaises(CommandBusError):
                    parse_issue_event(event, actor="EFSing")

        with self.assertRaises(CommandBusError):
            parse_issue_event(issue_event(command_body()), actor="attacker")


class HoldingsCommandBridgeTests(unittest.TestCase):
    def test_dry_run_runs_event_schema_and_identity_without_sheets_or_manager(self):
        event = issue_event(command_body(market="US"))
        with patch("sheets_client.SheetsClient") as sheets_class, \
                patch("holdings_data_manager.HoldingsDataManager") as manager_class:
            result = execute_event(event, actor="EFSing", live_writes_enabled=False)

        self.assertEqual(result.status, "DRY_RUN")
        self.assertEqual(result.request_id, "chatgpt-20260831-0001")
        self.assertEqual(result.operation, "ADD")
        self.assertEqual(result.normalized_symbol, "MU")
        self.assertEqual(result.market, "US")
        self.assertIsNone(result.enabled)
        self.assertEqual(result.history_rows_written, 0)
        sheets_class.assert_not_called()
        manager_class.assert_not_called()

    def test_invalid_identity_and_live_write_request_fail_closed_without_manager(self):
        event = issue_event(command_body(symbol="512400", market="US", dry_run=False))
        with patch("holdings_data_manager.HoldingsDataManager") as manager_class:
            result = execute_event(event, actor="EFSing", live_writes_enabled=True)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("identity normalization", result.message)
        manager_class.assert_not_called()

        valid_live_event = issue_event(command_body(dry_run=False))
        with patch("holdings_data_manager.HoldingsDataManager") as manager_class:
            result = execute_event(valid_live_event, actor="EFSing", live_writes_enabled=False)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("live writes are disabled", result.message)
        manager_class.assert_not_called()

    def test_live_path_delegates_only_to_existing_manager_contract(self):
        event = issue_event(command_body(operation="SYNC", market="US", dry_run=False))
        manager = Mock()
        manager.execute.return_value = OperationResult(
            "SYNC", "MU", "US", "SUCCESS", True, 0, "SYNC成功"
        )
        with patch("holdings_data_manager.HoldingsDataManager", return_value=manager) as manager_class:
            result = execute_event(event, actor="EFSing", live_writes_enabled=True)
        manager_class.assert_called_once_with()
        manager.execute.assert_called_once_with("SYNC", "MU", "US")
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.normalized_symbol, "MU")

    def test_cli_writes_only_bounded_receipt_and_comment(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            event_path = directory / "event.json"
            result_path = directory / "result.json"
            comment_path = directory / "comment.md"
            event_path.write_text(json.dumps(issue_event(command_body())), encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_ACTOR": "EFSing", "HOLDINGS_COMMAND_BUS_LIVE_WRITES": "disabled"}, clear=False):
                self.assertEqual(main([
                    "--event-path", str(event_path),
                    "--result-path", str(result_path),
                    "--comment-path", str(comment_path),
                ]), 0)
            result = json.loads(result_path.read_text(encoding="utf-8"))
            comment = comment_path.read_text(encoding="utf-8")
            self.assertEqual(result["status"], "DRY_RUN")
            self.assertEqual(result["normalized_symbol"], "MU")
            self.assertIn("holdings-command-result:v1", comment)
            self.assertNotIn("GOOGLE_SERVICE_ACCOUNT_JSON", comment)
            self.assertNotIn("private_key", comment.lower())

    def test_result_comment_has_machine_and_human_sections_without_account_fields(self):
        event = issue_event(command_body())
        result = execute_event(event, actor="EFSing")
        comment = render_result_comment(result)
        self.assertIn("```json", comment)
        self.assertIn("normalized symbol: `MU`", comment)
        for forbidden in ("account", "cost", "NAV", "P&L", "broker"):
            self.assertNotIn(forbidden.lower(), comment.lower())


class HoldingsCommandWorkflowTests(unittest.TestCase):
    def test_workflow_is_issue_opened_only_with_minimal_permissions(self):
        source = (ROOT / ".github" / "workflows" / "holdings-command.yml").read_text(encoding="utf-8")
        self.assertIn("on:\n  issues:\n    types: [opened]", source)
        self.assertNotIn("workflow_dispatch:", source)
        self.assertNotIn("pull_request:", source)
        self.assertNotIn("schedule:", source)
        self.assertNotIn("push:", source)
        self.assertIn("contents: read", source)
        self.assertIn("issues: write", source)
        self.assertIn("EFSing/stock-data-pipeline", source)
        self.assertIn('HOLDINGS_COMMAND_BUS_LIVE_WRITES: disabled', source)
        self.assertIn('"$GITHUB_EVENT_PATH"', source)
        self.assertNotIn("github.event.issue.body", source)
        self.assertIn("createComment", source)
        self.assertIn("state: 'closed'", source)


if __name__ == "__main__":
    unittest.main()

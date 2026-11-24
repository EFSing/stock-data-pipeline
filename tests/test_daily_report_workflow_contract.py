from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _workflow_run_eligible(
    *, event_name: str, conclusion: str = "", head_branch: str = "", upstream_event: str = "",
    actor: str = "", scheduler_bot: str = "",
) -> bool:
    """Executable model of the workflow_run gate kept in both YAML workflows."""
    if event_name != "workflow_run":
        return True
    return (
        conclusion == "success"
        and head_branch == "main"
        and upstream_event == "workflow_dispatch"
        and bool(scheduler_bot)
        and actor == scheduler_bot
    )


class DailyReportWorkflowContractTests(unittest.TestCase):
    def test_only_successful_main_app_close_is_eligible(self):
        scheduler = "fixture-scheduler[bot]"
        eligible = {
            "event_name": "workflow_run", "conclusion": "success", "head_branch": "main",
            "upstream_event": "workflow_dispatch", "actor": scheduler, "scheduler_bot": scheduler,
        }
        self.assertTrue(_workflow_run_eligible(**eligible))
        for override in (
            {"actor": "manual-user"}, {"scheduler_bot": ""}, {"conclusion": "failure"},
            {"head_branch": "other"}, {"upstream_event": "schedule"},
        ):
            with self.subTest(override=override):
                self.assertFalse(_workflow_run_eligible(**(eligible | override)))

    def test_cn_and_us_workflows_encode_the_same_gate_and_bounded_recovery(self):
        for filename in ("cn-daily-report.yml", "us-daily-report.yml"):
            with self.subTest(filename=filename):
                source = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
                self.assertIn("github.event.workflow_run.conclusion == 'success'", source)
                self.assertIn("github.event.workflow_run.head_branch == 'main'", source)
                self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'", source)
                self.assertIn("vars.VPS_SCHEDULER_BOT != ''", source)
                self.assertIn("github.event.workflow_run.actor.login == vars.VPS_SCHEDULER_BOT", source)
                self.assertIn("--retry-not-ready-attempts 6 --retry-not-ready-delay-seconds 300", source)

    def test_manual_daily_report_dispatch_remains_allowed(self):
        self.assertTrue(_workflow_run_eligible(event_name="workflow_dispatch"))


if __name__ == "__main__":
    unittest.main()

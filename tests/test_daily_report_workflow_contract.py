from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _workflow_run_eligible(
    *, event_name: str, conclusion: str = "", head_branch: str = "", upstream_event: str = "",
) -> bool:
    """Executable model of the workflow_run gate kept in both YAML workflows."""

    if event_name != "workflow_run":
        return True
    return (
        conclusion == "success"
        and head_branch == "main"
        and upstream_event == "schedule"
    )


class DailyReportWorkflowContractTests(unittest.TestCase):
    def test_only_scheduled_successful_main_close_is_eligible(self):
        self.assertTrue(_workflow_run_eligible(
            event_name="workflow_run",
            conclusion="success",
            head_branch="main",
            upstream_event="schedule",
        ))
        self.assertFalse(_workflow_run_eligible(
            event_name="workflow_run",
            conclusion="success",
            head_branch="main",
            upstream_event="workflow_dispatch",
        ))
        self.assertFalse(_workflow_run_eligible(
            event_name="workflow_run",
            conclusion="failure",
            head_branch="main",
            upstream_event="schedule",
        ))

    def test_cn_and_us_workflows_encode_the_same_gate_and_bounded_recovery(self):
        for filename, schedules in (
            (
                ".github/workflows/cn-daily-report.yml",
                ('- cron: "0 10 * * 1-5"', '- cron: "30 10 * * 1-5"'),
            ),
            (
                ".github/workflows/us-daily-report.yml",
                ('- cron: "30 1 * * 2-6"', '- cron: "0 2 * * 2-6"'),
            ),
        ):
            with self.subTest(filename=filename):
                text = (ROOT / filename).read_text(encoding="utf-8")
                self.assertIn("github.event.workflow_run.conclusion == 'success'", text)
                self.assertIn("github.event.workflow_run.head_branch == 'main'", text)
                self.assertIn("github.event.workflow_run.event == 'schedule'", text)
                for schedule in schedules:
                    self.assertIn(schedule, text)
                self.assertIn(
                    "--retry-not-ready-attempts 6 --retry-not-ready-delay-seconds 300",
                    text,
                )

    def test_manual_daily_report_dispatch_remains_allowed(self):
        self.assertTrue(_workflow_run_eligible(event_name="workflow_dispatch"))


if __name__ == "__main__":
    unittest.main()

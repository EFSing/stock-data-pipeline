from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from trading.daily_report_email import render_daily_report_email_html
from trading.notifications import send_optional_email


FIXTURE = Path(__file__).with_name("fixtures") / "daily_dashboard_v1.json"


class _FakeSMTP:
    last_message = None

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def starttls(self):
        return None

    def login(self, username, password):
        return None

    def send_message(self, message):
        type(self).last_message = message


def _cloud_payload(market: str = "US", status: str = "SUCCESS") -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cloud_daily_report"] = {
        "market": market,
        "market_label": "A股" if market == "CN" else "美股",
        "status": status,
        "data_quality": {
            "counts": {"DATA_OK": 3},
            "failed_symbols": [],
        },
        "github_run_url": "https://github.com/EFSing/stock-data-pipeline/actions/runs/1",
    }
    return payload


class DailyReportEmailTests(unittest.TestCase):
    def test_email_html_is_static_single_column_and_hides_internal_tokens(self):
        rendered = render_daily_report_email_html(_cloud_payload())
        lower = rendered.lower()

        for forbidden in (
            "<script",
            "<select",
            'type="search"',
            "<details",
            "<style",
            "position:sticky",
            "display:flex",
            "display:grid",
        ):
            self.assertNotIn(forbidden, lower)
        for forbidden in ("setup_01", "setup_02", "armed", "confirmed", "event_identity", "provenance"):
            self.assertNotIn(forbidden, lower)

        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1">', rendered)
        self.assertIn('<table role="presentation"', rendered)
        self.assertIn("市场：美股", rendered)
        self.assertIn("数据状态</strong>：数据正常", rendered)
        self.assertIn("新确认数量</strong>：1", rendered)
        self.assertIn("接近确认数量</strong>：0", rendered)
        self.assertIn("交易方案数量</strong>：2", rendered)
        self.assertIn("持仓数量</strong>：0", rendered)
        self.assertIn("数据异常数量</strong>：0", rendered)
        self.assertIn("示例云计算", rendered)
        self.assertNotIn("示例制造", rendered)

    def test_no_decision_plan_never_fabricates_price_fields(self):
        payload = _cloud_payload("CN")
        payload["reports"] = [payload["reports"][0]]
        report = payload["reports"][0]
        report["报告"]["results"] = [report["报告"]["results"][1]]
        report["universe"]["candidate_metadata"] = {
            "600002.SH": {"name": "示例观察", "sector": "专用设备"}
        }
        payload["candidate_markets"] = {
            "CN": {
                "status": "SUCCESS",
                "candidate_included_count": 1,
                "candidate_included_symbols": ["600002.SH"],
            }
        }

        rendered = render_daily_report_email_html(payload)

        self.assertIn("是否已有交易计划：</span>否", rendered)
        for forbidden in ("Entry", "Stop", "Targets", "RR", "入场（", "止损（", "目标（", "风险收益比（"):
            self.assertNotIn(forbidden, rendered)

    def test_real_decision_plan_displays_only_real_price_fields(self):
        payload = _cloud_payload("US")
        payload["reports"] = [payload["reports"][1]]
        payload["reports"][0]["报告"]["results"] = [payload["reports"][0]["报告"]["results"][1]]
        payload["candidate_markets"] = {
            "US": {
                "status": "SUCCESS",
                "candidate_included_count": 1,
                "candidate_included_symbols": ["BBB"],
            }
        }

        rendered = render_daily_report_email_html(payload)

        self.assertIn("是否已有交易计划：</span>是", rendered)
        self.assertIn("入场（Entry）：200", rendered)
        self.assertIn("止损（Stop）：190", rendered)
        self.assertIn("目标（Targets）：T1：220；T2：230；T3：240", rendered)
        self.assertIn("风险收益比（RR）：2.00 / 3.00 / 4.00", rendered)

    def test_priority_order_is_data_position_plan_confirmation_then_armed(self):
        rendered = render_daily_report_email_html(_cloud_payload())

        self.assertLess(rendered.index("已形成交易计划"), rendered.index("今日新确认"))
        self.assertNotIn("示例科技", rendered)
        self.assertNotIn("示例软件", rendered)
        self.assertNotIn("示例制造", rendered)

    def test_more_than_twenty_rows_reports_unexpanded_remainder(self):
        payload = _cloud_payload("CN")
        source_report = payload["reports"][0]
        template = source_report["报告"]["results"][1]
        metadata = {}
        results = []
        for index in range(25):
            symbol = f"TEST{index:02d}"
            row = deepcopy(template)
            row["symbol"] = symbol
            results.append(row)
            metadata[symbol] = {"name": f"测试标的{index:02d}", "sector": "测试"}
        source_report["报告"]["results"] = results
        source_report["universe"]["candidate_metadata"] = metadata
        source_report["Candidate"] = {
            "candidate_included_count": 25,
            "candidate_included_symbols": list(metadata),
        }
        payload["candidate_markets"] = {
            "CN": {
                "status": "SUCCESS",
                "candidate_included_count": 25,
                "candidate_included_symbols": list(metadata),
            }
        }

        rendered = render_daily_report_email_html(payload)

        self.assertIn("测试标的00", rendered)
        self.assertIn("测试标的19", rendered)
        self.assertNotIn("测试标的20", rendered)
        self.assertIn("其余 5 只观察标的未展开", rendered)

    def test_report_level_failure_is_visible_without_raw_diagnostics(self):
        payload = _cloud_payload("CN", "FAILED")
        payload["reports"] = []
        payload["cloud_daily_report"]["data_quality"] = {
            "counts": {},
            "failed_symbols": [],
            "preflight_errors": ["INTERNAL_DIAGNOSTIC_SHOULD_NOT_BE_MAILED"],
        }

        rendered = render_daily_report_email_html(payload)

        self.assertIn("数据异常", rendered)
        self.assertIn("数据异常数量</strong>：1", rendered)
        self.assertNotIn("INTERNAL_DIAGNOSTIC_SHOULD_NOT_BE_MAILED", rendered)
        self.assertNotIn("event_identity", rendered)

    def test_smtp_message_keeps_plain_text_fallback_and_html_alternative(self):
        with patch("trading.notifications.smtplib.SMTP", _FakeSMTP):
            result = send_optional_email(
                subject="A股日报完成",
                body="纯文本摘要",
                html_body="<html><body>静态摘要</body></html>",
                environ={
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_FROM": "sender@example.test",
                    "SMTP_TO": "receiver@example.test",
                    "SMTP_USE_TLS": "true",
                    "SMTP_USERNAME": "sender@example.test",
                    "SMTP_PASSWORD": "not-a-real-secret",
                },
            )

        self.assertEqual(result["status"], "SENT")
        message = _FakeSMTP.last_message
        self.assertIsNotNone(message)
        self.assertEqual(
            [part.get_content_type() for part in message.iter_parts()],
            ["text/plain", "text/html"],
        )
        self.assertIn("纯文本摘要", message.get_body(preferencelist=("plain",)).get_content())
        self.assertIn("静态摘要", message.get_body(preferencelist=("html",)).get_content())


if __name__ == "__main__":
    unittest.main()

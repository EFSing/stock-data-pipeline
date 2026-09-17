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


class _FailingSMTP(_FakeSMTP):
    def send_message(self, message):
        raise RuntimeError("simulated SMTP failure")


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


def _decision_result(symbol: str, market: str, decision: dict) -> dict:
    return {
        "symbol": symbol,
        "market": market,
        "as_of_date": "2026-09-03",
        "data_status": "DATA_OK",
        "primary_wave_scenario": "WAVE_2_TO_3_CANDIDATE",
        "alternate_wave_scenario": "UNKNOWN",
        "setup01_state": "CONFIRMED",
        "setup02_state": "NONE",
        "primary_action": decision["action"],
        "event_was_new": False,
        "individual_decision": decision,
        "portfolio_result": None,
        "position_management": None,
        "reasons": [],
        "blocking_prerequisites": [],
        "final_status": "NO_TRADE",
    }


def _no_trade_payload(symbol: str, decision: dict, name: str) -> dict:
    payload = _cloud_payload("CN")
    report = payload["reports"][0]
    report["报告"]["results"] = [_decision_result(symbol, "CN", decision)]
    report["universe"]["provenance"] = {symbol: ["FORMAL_STRATEGY_POOL"]}
    report["universe"]["provenance_metadata"] = {
        symbol: {
            "source": "FORMAL_STRATEGY_POOL",
            "state_persistence_eligible": True,
            "promotion_required": False,
            "production_execution_eligible": True,
        }
    }
    report["universe"]["symbol_metadata"] = {
        symbol: {"name": name, "sector": "示例行业"}
    }
    report["Candidate"] = {
        "candidate_included_count": 1,
        "candidate_included_symbols": [symbol],
    }
    payload["candidate_markets"] = {
        "CN": {
            "status": "SUCCESS",
            "candidate_included_count": 1,
            "candidate_included_symbols": [symbol],
        }
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
        self.assertIn("等待确认数量</strong>：0", rendered)
        self.assertIn("交易方案数量</strong>：2", rendered)
        self.assertIn("策略跟踪持仓数量</strong>：0", rendered)
        self.assertNotIn("接近确认数量", rendered)
        self.assertNotIn("<strong>持仓数量</strong>", rendered)
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

    def test_formal_position_email_uses_strategy_tracked_position_label(self):
        rendered = render_daily_report_email_html(_cloud_payload("CN"))

        self.assertIn(
            '<h2 style="margin:0;color:#172033;font-size:18px;line-height:1.35;">策略跟踪持仓（1）</h2>',
            rendered,
        )

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

    def test_real_plan_displays_upside_band_without_changing_plan_semantics(self):
        payload = _cloud_payload("US")
        payload["reports"] = [payload["reports"][1]]
        result = payload["reports"][0]["报告"]["results"][1]
        result["individual_decision"].update({
            "target_upside_pct": 0.064,
            "target_upside_band": "LOW_UPSIDE",
            "minimum_target_upside_pct": 0.05,
        })
        payload["candidate_markets"] = {
            "US": {
                "status": "SUCCESS",
                "candidate_included_count": 1,
                "candidate_included_symbols": ["BBB"],
            }
        }

        rendered = render_daily_report_email_html(payload)

        self.assertIn("目标上涨空间：6.40%", rendered)
        self.assertIn("空间评价：偏小，但达到最低交易门槛", rendered)

    def test_600941_target_upside_rejection_preserves_rr_calculation_basis(self):
        rendered = render_daily_report_email_html(
            _no_trade_payload(
                "600941.SH",
                {
                    "action": "NO_TRADE",
                    "gate_reason": "TARGET_UPSIDE_BELOW_MINIMUM",
                    "planned_entry": 98.16,
                    "execution_stop": 94.31,
                    "targets": [98.6825],
                    "target_upside_pct": (98.6825 - 98.16) / 98.16,
                    "target_upside_band": "BELOW_MINIMUM",
                    "minimum_target_upside_pct": 0.05,
                    "rr": {"rr_ratios": [0.14], "quality": "NO_TRADE"},
                },
                "中国移动",
            )
        )

        self.assertIn("今日不交易（1）", rendered)
        self.assertIn("今日结论：</span>不交易", rendered)
        self.assertIn("目标上涨空间不足", rendered)
        self.assertIn("参考价格：98.16", rendered)
        self.assertIn("第一目标候选：98.6825", rendered)
        self.assertIn("目标上涨空间：0.53%", rendered)
        self.assertIn("系统最低要求：5.00%", rendered)
        self.assertIn("对应 RR：0.14R", rendered)
        self.assertIn("最低 RR 要求：2.00R", rendered)
        self.assertIn("这些是本次 Decision gate 的计算依据，不是买入/止盈建议。", rendered)
        self.assertIn("是否已有交易计划：</span>否", rendered)
        self.assertNotIn("交易计划（来自真实 Decision）", rendered)
        self.assertNotIn("入场（Entry）", rendered)

    def test_new_confirmation_no_trade_email_surfaces_rejection_summary_first(self):
        payload = _cloud_payload("US")
        report = payload["reports"][1]
        result = deepcopy(report["报告"]["results"][1])
        result["symbol"] = "SPCX"
        result["event_was_new"] = True
        result["primary_action"] = "NO_TRADE"
        result["final_status"] = "NO_TRADE"
        result["individual_decision"] = {
            "action": "NO_TRADE",
            "gate_reason": "RR_BELOW_MINIMUM",
            "target_upside_pct": 0.1426,
            "entry_zone_upper_distance_pct": -0.01,
            "rr": {"rr_ratios": [0.88], "quality": "NO_TRADE"},
        }
        report["报告"]["results"] = [result]

        rendered = render_daily_report_email_html(payload)

        for fragment in (
            "确认成功",
            "仍在入场区",
            "T1空间 14.26%",
            "R/R 0.88 &lt; 2",
            "→ 不交易",
        ):
            self.assertIn(fragment, rendered)

    def test_no_trade_email_separates_near_resistance_from_wave3_structure_target(self):
        rendered = render_daily_report_email_html(
            _no_trade_payload(
                "NEAR_SWING_ONLY",
                {
                    "action": "NO_TRADE",
                    "gate_reason": "TARGET_UPSIDE_BELOW_MINIMUM",
                    "planned_entry": 100.0,
                    "execution_stop": 95.0,
                    "targets": [101.0, 120.0, 130.0],
                    "target_upside_pct": 0.01,
                    "target_upside_band": "BELOW_MINIMUM",
                    "minimum_target_upside_pct": 0.05,
                    "rr": {"rr_ratios": [0.2], "quality": "NO_TRADE"},
                    "target_projection": {
                        "current_effective_t1": 101.0,
                        "effective_t1_source": "CONFIRMED_SWING_HIGH",
                        "nearest_overhead_confirmed_swing_high": {"price": 101.0},
                        "overhead_resistance_upside_pct": 0.01,
                        "nearest_wave3_fib_extension": {
                            "price": 120.0,
                            "ratio": 1.272,
                            "upside_pct": 0.20,
                        },
                        "nearest_wave3_fib_extension_ratio": 1.272,
                        "wave3_fib_upside_pct": 0.20,
                        "wave3_fib_extensions": [
                            {"ratio": 1.272, "price": 120.0, "upside_pct": 0.20},
                            {"ratio": 1.618, "price": 130.0, "upside_pct": 0.30},
                        ],
                    },
                },
                "近端阻力示例",
            )
        )

        self.assertIn("当前正式 T1（保持 gate/RR）", rendered)
        self.assertIn("保守第一障碍（最近已确认历史阻力）", rendered)
        self.assertIn("Wave3 结构目标（最近 Fib 投射）", rendered)
        self.assertIn("系统不是认为 Wave3 只有 1.00% 空间", rendered)
        self.assertIn("按现有保守规则不交易", rendered)

    def test_above_entry_zone_rejected_decision_explains_no_chasing(self):
        rendered = render_daily_report_email_html(
            _no_trade_payload(
                "600803.SH",
                {
                    "action": "NO_TRADE",
                    "gate_reason": "ABOVE_ENTRY_ZONE",
                    "planned_entry": 18.78,
                    "entry_zone_low": 18.09,
                    "entry_zone_high": 18.36,
                    "execution_stop": 17.5,
                    "targets": [20.0],
                    "rr": {"rr_ratios": [1.0], "quality": "NO_TRADE"},
                },
                "新奥股份",
            )
        )

        self.assertIn("今日结论：</span>不追高", rendered)
        self.assertIn("允许入场区：18.09～18.36", rendered)
        self.assertIn("当前价格：18.78", rendered)
        self.assertIn("原因：已经高于允许入场区上沿", rendered)
        self.assertIn("是否已有交易计划：</span>否", rendered)
        self.assertNotIn("交易计划（来自真实 Decision）", rendered)
        self.assertNotIn("目标（Targets）", rendered)

    def test_summary_plan_count_excludes_rejected_decisions(self):
        payload = _cloud_payload("US")
        report = payload["reports"][1]
        report["报告"]["results"].append(
            _decision_result(
                "REJECTED",
                "US",
                {
                    "action": "NO_TRADE",
                    "gate_reason": "RR_BELOW_MINIMUM",
                    "planned_entry": 100.0,
                    "execution_stop": 90.0,
                    "targets": [101.0],
                    "rr": {"rr_ratios": [0.1], "quality": "NO_TRADE"},
                },
            )
        )

        rendered = render_daily_report_email_html(payload)

        self.assertIn("交易方案数量</strong>：2", rendered)
        self.assertIn("今日不交易（1）", rendered)
        self.assertNotIn("交易方案数量</strong>：3", rendered)

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

    def test_smtp_message_includes_full_utf8_dashboard_html_attachment(self):
        dashboard_html = "<!doctype html><html><body>完整 Dashboard 中文</body></html>\n"
        filename = "美股交易日报_2026-09-03.html"
        with patch("trading.notifications.smtplib.SMTP", _FakeSMTP):
            result = send_optional_email(
                subject="美股日报完成",
                body="纯文本摘要",
                html_body="<html><body>静态摘要</body></html>",
                html_attachment=dashboard_html,
                attachment_filename=filename,
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
        self.assertEqual(result["attachment"]["status"], "SENT")
        message = _FakeSMTP.last_message
        attachments = list(message.iter_attachments())
        self.assertEqual(len(attachments), 1)
        attachment = attachments[0]
        self.assertEqual(attachment.get_content_type(), "text/html")
        self.assertEqual(attachment.get_content_charset(), "utf-8")
        self.assertEqual(attachment.get_filename(), filename)
        self.assertEqual(
            attachment.get_payload(decode=True).decode("utf-8"),
            dashboard_html,
        )
        self.assertIn("纯文本摘要", message.get_body(preferencelist=("plain",)).get_content())
        self.assertIn("静态摘要", message.get_body(preferencelist=("html",)).get_content())

    def test_smtp_attachment_failure_is_reported_as_non_core_failed_metadata(self):
        with patch("trading.notifications.smtplib.SMTP", _FailingSMTP):
            result = send_optional_email(
                subject="日报完成",
                body="纯文本摘要",
                html_body="<html><body>静态摘要</body></html>",
                html_attachment="<!doctype html><html></html>\n",
                attachment_filename="A股交易日报_2026-09-03.html",
                environ={
                    "SMTP_HOST": "smtp.example.test",
                    "SMTP_PORT": "587",
                    "SMTP_FROM": "sender@example.test",
                    "SMTP_TO": "receiver@example.test",
                },
            )

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["attachment"]["status"], "FAILED")
        self.assertEqual(result["attachment"]["filename"], "A股交易日报_2026-09-03.html")


if __name__ == "__main__":
    unittest.main()

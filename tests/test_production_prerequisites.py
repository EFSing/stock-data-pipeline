from datetime import date, datetime, timezone
import json
import unittest

from core import Quote
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DailyDecisionResult,
    DailyPortfolioResult,
    DailyPositionManagementResult,
    InMemoryDecisionStateStore,
    PendingT1Decision,
    SettlementRecord,
    T1ExecutionPhase,
)
from trading.models import DecisionAction, RiskReward, SetupState, Trend
from trading.portfolio_risk import (
    OpenPortfolioPosition,
    PortfolioCandidate,
    PortfolioRiskEngine,
)
from trading.production_prerequisites import (
    DATA_BAD,
    DATA_OK,
    DATA_STALE,
    DATA_UNAVAILABLE,
    DECISION_STATE_HEADERS,
    ExactExchangeCalendarProvider,
    ProductionInputAdapter,
    ProductionPrerequisiteError,
    PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH,
    SheetsDecisionStateStore,
    STRATEGY_ACCOUNT_HEADERS,
    STRATEGY_POSITION_HEADERS,
    STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS,
    build_production_snapshot,
    encode_payload,
    parse_strategy_accounts,
)
from trading.setup01_decision import (
    Setup01Decision,
    Setup01Execution,
    Setup01TargetCandidate,
    Setup01TargetProvenance,
)


T_DAY = date(2026, 9, 3)


class FakeSheetsClient:
    def __init__(self, rows, headers=None):
        self.rows = {name: list(values) for name, values in rows.items()}
        self.header_rows = headers or {
            name: tuple(values[0].keys()) if values else ()
            for name, values in self.rows.items()
        }
        self.writes = []

    def records(self, sheet_name):
        return [dict(row) for row in self.rows.get(sheet_name, [])]

    def headers(self, sheet_name):
        return list(self.header_rows.get(sheet_name, ()))

    def append_rows(self, sheet_name, headers, rows):
        self.writes.append((sheet_name, list(headers), list(rows)))
        self.rows.setdefault(sheet_name, []).extend(dict(row) for row in rows)


def _latest(symbol, market, currency, *, trade_date=T_DAY, validation="已验证", closed="TRUE"):
    return {
        "统一代码": symbol, "名称": symbol, "市场": market, "交易日期": trade_date.isoformat(),
        "正式收盘": closed, "校验状态": validation, "数据源": "synthetic",
        "开盘": "100", "最高": "105", "最低": "95", "收盘": "102",
        "昨收": "101", "成交量": "1000", "币种": currency,
    }


def _history(symbol, market, currency, *, trade_date=T_DAY):
    return {
        "统一代码": symbol, "名称": symbol, "市场": market, "交易日期": trade_date.isoformat(),
        "复权方式": "前复权", "数据源": "synthetic", "开盘": "100", "最高": "105",
        "最低": "95", "收盘": "102", "昨收": "101", "成交量": "1000", "币种": currency,
    }


def _rows(*, same_symbol=False, missing_group=False, position=False, cn_currency="CNY"):
    accounts = [
        {"账户ID": "CN-1", "启用": "TRUE", "市场": "CN", "币种": cn_currency, "参考净值": "100000", "净值日期": T_DAY.isoformat(), "备注": ""},
        {"账户ID": "US-1", "启用": "TRUE", "市场": "US", "币种": "USD", "参考净值": "200000", "净值日期": T_DAY.isoformat(), "备注": ""},
    ]
    universe = [
        {"启用": "TRUE", "账户ID": "CN-1", "市场": "CN", "统一代码": "600000", "名称": "CN", "备注": ""},
        {"启用": "TRUE", "账户ID": "US-1", "市场": "US", "统一代码": "AAPL", "名称": "US", "备注": ""},
    ]
    if same_symbol:
        universe[1]["统一代码"] = "600000"
        universe[1]["市场"] = "CN"
        universe[1]["账户ID"] = "US-1"
    groups = [] if missing_group else [
        {"市场": "CN", "统一代码": "600000", "风险组": "BANK", "备注": ""},
        {"市场": "US", "统一代码": "AAPL", "风险组": "TECH", "备注": ""},
    ]
    latest = [_latest("600000", "CN", "CNY")]
    history = [_history("600000", "CN", "CNY")]
    if not same_symbol:
        latest.append(_latest("AAPL", "US", "USD"))
        history.append(_history("AAPL", "US", "USD"))
    positions = []
    if position:
        positions.append({
            "启用": "TRUE", "账户ID": "US-1", "市场": "US", "统一代码": "AAPL",
            "数量": "10", "实际入场价": "100", "当前保护止损": "90",
            "入场日期": "2026-08-01", "来源事件ID": "origin-aapl",
            "更新时间": "2026-09-03T08:00:00+08:00", "备注": "",
        })
    rows = {
        "策略账户": accounts, "策略股票池": universe, "策略风险分组": groups,
        "策略持仓": positions, "最新行情": latest, "历史行情_前复权": history,
        "策略决策状态": [],
    }
    headers = {
        "策略账户": STRATEGY_ACCOUNT_HEADERS,
        "策略股票池": ("启用", "账户ID", "市场", "统一代码", "名称", "备注"),
        "策略风险分组": ("市场", "统一代码", "风险组", "备注"),
        "策略持仓": STRATEGY_POSITION_HEADERS,
        "最新行情": tuple(latest[0].keys()), "历史行情_前复权": tuple(history[0].keys()),
        "策略决策状态": DECISION_STATE_HEADERS,
    }
    return FakeSheetsClient(rows, headers)


def _result(symbol="AAPL"):
    return DailyDecisionResult(
        symbol=symbol, market="US", as_of_date=T_DAY, data_status=DATA_OK,
        weekly_state=Trend.UNKNOWN.value, daily_state=Trend.UNKNOWN.value,
        primary_wave_scenario="NO_VALID_SCENARIO", alternate_wave_scenario="NO_VALID_SCENARIO",
        setup01_state=SetupState.NONE.value, setup02_state=SetupState.NONE.value,
        setup01_event_identity=None, setup02_event_identity=None,
        new_confirmed_event_identity=None, new_confirmed_event_identities=(), event_was_new=False,
        individual_decision=None, individual_decision_candidates=(), portfolio_result=None,
        position_management=None, wave5_context="NOT_APPLICABLE", primary_action=DecisionAction.NO_TRADE.value,
        execution_phase=None, execution_outcome=None, reasons=(), blocking_prerequisites=(),
        protocol_versions={"daily_chain": "test"},
        generated_at=datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc), final_status="NO_TRADE",
    )


class ProductionPrerequisiteTests(unittest.TestCase):
    def test_calendar_provider_skips_weekend_and_exchange_holiday(self):
        provider = ExactExchangeCalendarProvider()
        with self.assertRaisesRegex(ValueError, "CALENDAR_REQUIRED"):
            provider.completed_session("US", date(2026, 7, 5))
        identity = provider.completed_session("US", date(2026, 7, 2))
        self.assertEqual(identity.next_session_date, date(2026, 7, 6))
        self.assertTrue(identity.exact_exchange_calendar)
        self.assertEqual(identity.identity, "exchange_calendars:XNYS:2026-07-02")

    def test_accounts_require_same_day_nav_and_known_currency(self):
        with self.assertRaisesRegex(ValueError, "PORTFOLIO_NAV_REQUIRED"):
            parse_strategy_accounts([{
                "账户ID": "A", "启用": "TRUE", "市场": "US", "币种": "USD",
                "参考净值": "", "净值日期": T_DAY.isoformat(), "备注": "",
            }], as_of_date=T_DAY)
        with self.assertRaisesRegex(ValueError, "PRODUCTION_NAV_DATE_REQUIRED"):
            parse_strategy_accounts([{
                "账户ID": "A", "启用": "TRUE", "市场": "US", "币种": "USD",
                "参考净值": "100", "净值日期": "2026-09-02", "备注": "",
            }], as_of_date=T_DAY)
        client = _rows(cn_currency="USD")
        report = build_production_snapshot(client, as_of_date=T_DAY).preflight
        self.assertTrue(any(PRODUCTION_RISK_BOOK_MARKET_CURRENCY_MISMATCH in item for item in report.errors))

    def test_accounts_are_isolated_and_duplicate_symbol_is_fail_closed(self):
        client = _rows()
        snapshot = build_production_snapshot(client, as_of_date=T_DAY)
        self.assertTrue(snapshot.preflight.ready)
        runs = {item.account.account_id: item for item in snapshot.account_runs}
        self.assertEqual(len(runs["CN-1"].inputs), 1)
        self.assertEqual(len(runs["US-1"].inputs), 1)
        self.assertEqual(runs["CN-1"].reference_nav, 100000.0)
        self.assertEqual(runs["US-1"].reference_nav, 200000.0)
        duplicate = build_production_snapshot(_rows(same_symbol=True), as_of_date=T_DAY).preflight
        self.assertTrue(any(STRATEGY_SYMBOL_MULTIPLE_ACCOUNTS in item for item in duplicate.errors))

    def test_data_quality_mapping_is_conservative(self):
        client = _rows()
        client.rows["最新行情"][0]["交易日期"] = "2026-09-02"
        client.rows["历史行情_前复权"][0]["交易日期"] = "2026-09-02"
        snapshot = build_production_snapshot(client, as_of_date=T_DAY)
        summary = next(item for item in snapshot.preflight.accounts if item.account_id == "CN-1")
        self.assertEqual(summary.data_bad_stale_unavailable_count, 1)
        self.assertEqual(summary.data_ok_count, 0)
        self.assertIn(DATA_STALE, " ".join(summary.errors))

        client = _rows()
        client.rows["最新行情"][0]["校验状态"] = "待复核"
        summary = next(item for item in build_production_snapshot(client, as_of_date=T_DAY).preflight.accounts if item.account_id == "CN-1")
        self.assertIn(DATA_BAD, " ".join(summary.errors))

        client = _rows()
        client.rows["历史行情_前复权"] = [item for item in client.rows["历史行情_前复权"] if item["统一代码"] != "600000"]
        summary = next(item for item in build_production_snapshot(client, as_of_date=T_DAY).preflight.accounts if item.account_id == "CN-1")
        self.assertIn(DATA_UNAVAILABLE, " ".join(summary.errors))

    def test_missing_group_and_position_origin_are_reported(self):
        client = _rows(missing_group=True, position=True)
        snapshot = build_production_snapshot(client, as_of_date=T_DAY)
        cn = next(item for item in snapshot.preflight.accounts if item.account_id == "CN-1")
        us = next(item for item in snapshot.preflight.accounts if item.account_id == "US-1")
        self.assertEqual(cn.missing_risk_groups, ("600000",))
        self.assertEqual(us.missing_position_origins, ("AAPL",))
        self.assertFalse(snapshot.preflight.ready)

    def test_manual_position_uses_actual_entry_for_risk(self):
        client = _rows(position=True)
        snapshot = build_production_snapshot(client, as_of_date=T_DAY)
        us = next(item for item in snapshot.account_runs if item.account.account_id == "US-1")
        self.assertEqual(len(us.existing_positions), 1)
        position = us.existing_positions[0]
        self.assertEqual(position.actual_entry, 100.0)
        self.assertEqual(position.current_price, 102.0)
        self.assertEqual(position.remaining_loss_risk(us.reference_nav), 10 * 10 / 200000)

    def test_preflight_is_read_only(self):
        client = _rows()
        report = ProductionInputAdapter(client, as_of_date=T_DAY).preflight()
        self.assertFalse(report.writes_performed)
        self.assertEqual(client.writes, [])
        self.assertTrue(report.to_dict()["NO STATE WRITE"])
        self.assertTrue(report.to_dict()["NO Sheets mutation"])

    def test_persistent_state_reloads_published_and_origin_exactly_once(self):
        client = _rows()
        store = SheetsDecisionStateStore(client, write_enabled=True, account_id="US-1")
        result = _result()
        store.record_published_event("event-1", result)
        self.assertEqual(len(client.writes), 1)
        restarted = SheetsDecisionStateStore(client, write_enabled=True, account_id="US-1")
        self.assertEqual(restarted.get_published_event("event-1"), result)
        with self.assertRaises(ValueError):
            restarted.record_published_event("event-1", result)

        origin = _origin()
        restarted.save_position_origin(origin)
        reloaded = SheetsDecisionStateStore(client, write_enabled=False, account_id="US-1")
        self.assertEqual(reloaded.get_position_origin(origin.source_event_identity), origin)

    def test_pending_and_settlement_reload_once(self):
        from tests.test_daily_decision_chain import _fixture
        _, _, event, _ = _fixture(t1=True)
        provenance = Setup01TargetProvenance("SYNTHETIC", pivot_date=T_DAY, confirmed_date=T_DAY)
        candidate = Setup01TargetCandidate(130.0, "SYNTHETIC", "test", (provenance,))
        decision = Setup01Decision(
            "SETUP-01-DECISION-RISK-TEST", event.event_identity, event.symbol, event.market,
            T_DAY, SetupState.CONFIRMED, True, DecisionAction.ENTRY_ALLOWED,
            "ENTRY_ALLOWED", "test", 1.0, 90.0, 100.0, 100.0, 100.0, 105.0,
            95.0, 95.0, 90.0, (candidate,), (130.0,), False, None,
            RiskReward(100.0, 90.0, 10.0, (130.0,), (3.0,), "NORMAL"), None, None,
        )
        portfolio_candidate = PortfolioCandidate(event.event_identity, "SETUP_01", event.symbol, "US", T_DAY, 100, 90, 2.5, "NORMAL")
        reservation = PortfolioRiskEngine(mode="DEVELOPMENT_EXPOSED").reserve([portfolio_candidate]).approved[0]
        pending = PendingT1Decision(event, decision, reservation, date(2026, 9, 4))
        client = _rows()
        store = SheetsDecisionStateStore(client, write_enabled=True)
        store.save_pending(pending)
        restarted = SheetsDecisionStateStore(client, write_enabled=True)
        self.assertEqual(restarted.pending_for_symbol(event.symbol)[0], pending)
        execution = Setup01Execution(
            event.event_identity, event.symbol, "US", T_DAY, date(2026, 9, 4), 100.0,
            True, "EXECUTED", 100.0,
        )
        settlement = PortfolioRiskEngine(mode="DEVELOPMENT_EXPOSED").settle(
            reservation, outcome="EXECUTED", execution_date=date(2026, 9, 4), actual_entry=100.0
        )
        restarted.settle_pending(event.event_identity, SettlementRecord(pending, execution, settlement, None))
        reloaded = SheetsDecisionStateStore(client, write_enabled=False)
        self.assertIsNotNone(reloaded.get_settlement(event.event_identity))
        self.assertEqual(reloaded.pending_for_symbol(event.symbol), ())

    def test_corrupt_and_duplicate_state_fail_closed(self):
        base = _rows()
        base.rows["策略决策状态"] = [{
            "记录类型": "PUBLISHED_EVENT", "主键": "same", "账户ID": "", "市场": "US",
            "统一代码": "AAPL", "交易日期": T_DAY.isoformat(), "状态": "PUBLISHED",
            "PayloadJSON": "{bad", "更新时间": "now",
        }]
        with self.assertRaises(ProductionPrerequisiteError):
            SheetsDecisionStateStore(base)
        base.rows["策略决策状态"][0]["PayloadJSON"] = encode_payload(_result())
        base.rows["策略决策状态"].append(dict(base.rows["策略决策状态"][0]))
        with self.assertRaises(ProductionPrerequisiteError):
            SheetsDecisionStateStore(base)

    def test_inmemory_origin_accessor_is_additive(self):
        store = InMemoryDecisionStateStore()
        origin = _origin()
        store.save_position_origin(origin)
        self.assertEqual(store.get_position_origin(origin.source_event_identity), origin)


def _origin():
    from trading.position_management import PositionAnchor, PositionOrigin, PositionTarget
    anchor = PositionAnchor("LOW0", "LOW", 90.0, 0, date(2026, 8, 1), 0, date(2026, 8, 1))
    return PositionOrigin(
        "SETUP_01", "origin-aapl", "AAPL", "US", date(2026, 8, 1), 100.0, 90.0, 95.0,
        (PositionTarget(130.0, "SYNTHETIC", ("test",)),), (anchor,), 10.0,
    )


if __name__ == "__main__":
    unittest.main()

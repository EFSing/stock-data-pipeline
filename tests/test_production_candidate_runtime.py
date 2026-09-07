from datetime import date, timedelta
import unittest

from core import Quote
from scripts.run_production_daily_decision import run_production_daily_decision
from tests.test_production_prerequisites import AFTER_CLOSE, T_DAY, _latest, _rows
from trading.candidate_universe import SeedSecurity
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DATA_UNAVAILABLE,
)
from trading.production_candidate_runtime import (
    HistoryLoadResult,
    ProductionCandidateRuntime,
)


def _seed(market: str, symbol: str, *, price: float = 100.0, sector: str = "TECH"):
    return SeedSecurity(
        market=market,
        symbol=symbol,
        name=symbol,
        sector=sector,
        asset_class="Equity",
        exchange="SH" if market == "CN" else "NYSE",
        currency="CNY" if market == "CN" else "USD",
        source="synthetic",
        source_as_of=T_DAY,
        reference_price=price,
        metadata_status="OK",
    )


def _history(symbol: str, market: str, currency: str, *, bars: int = 60):
    start = T_DAY - timedelta(days=bars - 1)
    return tuple(
        Quote(
            symbol=symbol,
            name=symbol,
            market=market,
            trade_date=start + timedelta(days=index),
            source="synthetic",
            open=100.0 + index * 0.1,
            high=101.0 + index * 0.1,
            low=99.0 + index * 0.1,
            close=100.5 + index * 0.1,
            preclose=100.4 + index * 0.1 if index else None,
            pct_change=0.1,
            volume=10000.0,
            amount=1_000_000.0,
            turnover_rate=None,
            currency=currency,
        )
        for index in range(bars)
    )


def _identity(market: str) -> CompletedSessionIdentity:
    return CompletedSessionIdentity(
        market=market,
        trade_date=T_DAY,
        identity=f"synthetic:{market}:{T_DAY.isoformat()}",
        exact_exchange_calendar=True,
        next_session_date=T_DAY + timedelta(days=1),
        session_dates=(T_DAY, T_DAY + timedelta(days=1)),
    )


class ProductionCandidateRuntimeTests(unittest.TestCase):
    def test_stage_b_requests_only_included_candidates(self):
        seeds = (
            _seed("CN", "600001.SH", sector="BANK"),
            _seed("CN", "600002.SH", sector="BANK"),
            _seed("CN", "600003.SH", sector="BANK"),
        )
        histories = {
            seed.symbol: _history(seed.symbol, "CN", "CNY")
            for seed in seeds
        }
        # The third symbol is short-history and therefore excluded before the
        # deep loader is called.
        histories["600003.SH"] = histories["600003.SH"][:10]
        deep_calls = []

        def short_loader(values, start, end):
            return HistoryLoadResult(
                {seed.symbol: histories[seed.symbol] for seed in values},
                api_requests=1,
            )

        def deep_loader(values, start, end):
            deep_calls.append(tuple(seed.symbol for seed in values))
            return HistoryLoadResult(
                {seed.symbol: histories[seed.symbol] for seed in values},
                api_requests=1,
            )

        runtime = ProductionCandidateRuntime(
            seed_loaders={"CN": lambda as_of: seeds},
            short_history_loader=short_loader,
            deep_history_loader=deep_loader,
            session_window_loader=lambda market, end, bars: (
                end - timedelta(days=bars - 1),
                end,
            ),
            enforce_us_latest_qfq_asof=False,
        )
        result = runtime.run(
            market="CN",
            as_of_date=T_DAY,
            completed_session_identity=_identity("CN"),
            reuse_symbols=(),
        )

        self.assertEqual(result.seed_count, 3)
        self.assertEqual(result.data_qualified_count, 2)
        self.assertEqual(result.included_symbols, ("600001.SH", "600002.SH"))
        self.assertEqual(deep_calls, [("600001.SH", "600002.SH")])
        self.assertEqual(result.to_dict()["deep_history_requested_count"], 2)

    def test_missing_deep_history_projects_data_blocked_input(self):
        seed = _seed("US", "MSFT")
        history = _history(seed.symbol, "US", "USD")

        def loader(values, start, end):
            return HistoryLoadResult({})

        runtime = ProductionCandidateRuntime(
            seed_loaders={"US": lambda as_of: (T_DAY, (seed,))},
            short_history_loader=lambda values, start, end: HistoryLoadResult(
                {seed.symbol: history}
            ),
            deep_history_loader=loader,
            session_window_loader=lambda market, end, bars: (end, end),
            enforce_us_latest_qfq_asof=False,
        )
        result = runtime.run(
            market="US",
            as_of_date=T_DAY,
            completed_session_identity=_identity("US"),
        )
        projected = result.daily_inputs(_identity("US"))

        self.assertEqual(result.included_symbols, ("MSFT",))
        self.assertEqual(projected[0].data_quality_status, DATA_UNAVAILABLE)
        self.assertEqual(projected[0].qfq_history, ())
        self.assertIn("DEEP_HISTORY_UNAVAILABLE", result.to_dict()["deep_history_errors"]["MSFT"])

    def test_production_runner_unions_formal_and_dynamic_inputs_without_writes(self):
        client = _rows()
        cn_seeds = (
            _seed("CN", "600000.SH", sector="BANK"),
            _seed("CN", "600001.SH", sector="BANK"),
        )
        us_seed = _seed("US", "AAPL", sector="TECH")
        seed_by_market = {"CN": cn_seeds, "US": (us_seed,)}

        def seed_loader(market):
            return lambda as_of: seed_by_market[market]

        def short_loader(values, start, end):
            return HistoryLoadResult({
                seed.symbol: _history(seed.symbol, seed.market, seed.currency)
                for seed in values
            })

        def deep_loader(values, start, end):
            return HistoryLoadResult({
                seed.symbol: _history(seed.symbol, seed.market, seed.currency)
                for seed in values
            })

        runtime = ProductionCandidateRuntime(
            seed_loaders={"CN": seed_loader("CN"), "US": seed_loader("US")},
            short_history_loader=short_loader,
            deep_history_loader=deep_loader,
            session_window_loader=lambda market, end, bars: (end, end),
            enforce_us_latest_qfq_asof=False,
        )
        result = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            now=AFTER_CLOSE,
            candidate_runtime=runtime,
        )

        by_account = {item["账户ID"]: item for item in result["reports"]}
        self.assertEqual(
            by_account["CN-1"]["universe"]["daily_analysis_universe"],
            ["600000", "600001.SH"],
        )
        self.assertEqual(
            by_account["US-1"]["universe"]["daily_analysis_universe"],
            ["AAPL"],
        )
        self.assertIn(
            "DYNAMIC_CANDIDATE",
            by_account["US-1"]["universe"]["provenance"]["AAPL"],
        )
        self.assertIn(
            "DYNAMIC_CANDIDATE",
            by_account["CN-1"]["universe"]["provenance"]["600000"],
        )
        self.assertEqual(
            by_account["CN-1"]["Candidate"]["deep_history_requested_symbols"],
            ["600001.SH"],
        )
        self.assertTrue(by_account["CN-1"]["Candidate"]["read_only"])
        self.assertEqual(client.writes, [])
        self.assertNotIn("策略股票池", [write[0] for write in client.writes])

    def test_multiple_enabled_accounts_same_market_requires_routing_decision(self):
        client = _rows()
        client.rows["策略账户"].append({
            "账户ID": "CN-2", "启用": "TRUE", "市场": "CN", "币种": "CNY",
            "参考净值": "100000", "净值日期": T_DAY.isoformat(), "备注": "",
        })
        client.rows["策略股票池"].append({
            "启用": "TRUE", "账户ID": "CN-2", "市场": "CN",
            "统一代码": "600001", "名称": "CN2", "备注": "",
        })
        runtime = ProductionCandidateRuntime(
            seed_loaders={"CN": lambda as_of: (_seed("CN", "600001.SH"),)},
            short_history_loader=lambda values, start, end: HistoryLoadResult({}),
            deep_history_loader=lambda values, start, end: HistoryLoadResult({}),
            session_window_loader=lambda market, end, bars: (end, end),
            enforce_us_latest_qfq_asof=False,
        )

        with self.assertRaisesRegex(
            ValueError, "READY_FOR_DECISION_CANDIDATE_ACCOUNT_ROUTING"
        ):
            run_production_daily_decision(
                client,
                as_of_date=T_DAY,
                preflight=False,
                now=AFTER_CLOSE,
                candidate_runtime=runtime,
            )

    def test_active_position_outside_formal_pool_is_still_in_chain(self):
        client = _rows()
        client.rows["策略持仓"] = [{
            "启用": "TRUE", "账户ID": "US-1", "市场": "US", "统一代码": "MSFT",
            "数量": "10", "实际入场价": "100", "当前保护止损": "90",
            "入场日期": "2026-08-01", "来源事件ID": "missing-origin",
            "更新时间": AFTER_CLOSE.isoformat(), "备注": "",
        }]
        client.rows["最新行情"].append(_latest("MSFT", "US", "USD"))
        client.rows["历史行情_前复权"].append(_history_row("MSFT"))

        result = run_production_daily_decision(
            client,
            as_of_date=T_DAY,
            preflight=False,
            now=AFTER_CLOSE,
        )
        us_report = next(item for item in result["reports"] if item["账户ID"] == "US-1")
        self.assertIn("MSFT", us_report["universe"]["daily_analysis_universe"])
        msft = next(row for row in us_report["报告"]["results"] if row["symbol"] == "MSFT")
        self.assertIsNotNone(msft["position_management"])
        self.assertIn("POSITION_ORIGIN_REQUIRED", str(msft["position_management"]))


def _history_row(symbol: str) -> dict:
    return {
        "统一代码": symbol, "名称": symbol, "市场": "US", "交易日期": T_DAY.isoformat(),
        "复权方式": "前复权", "数据源": "synthetic", "开盘": "100", "最高": "105",
        "最低": "95", "收盘": "102", "昨收": "101", "成交量": "1000", "币种": "USD",
    }


if __name__ == "__main__":
    unittest.main()

from datetime import date, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from core import Quote
from scripts.run_production_daily_decision import run_production_daily_decision
from tests.test_production_prerequisites import (
    AFTER_CLOSE,
    T_DAY,
    _decision_for_state,
    _latest,
    _rows,
)
from trading.candidate_universe import SeedSecurity
from trading.daily_decision_chain import (
    CompletedSessionIdentity,
    DATA_UNAVAILABLE,
    DailyChainEvaluators,
    DailyDecisionChain as RealDailyDecisionChain,
    STRATEGY_PROPOSAL,
)
from trading.models import Setup01Evaluation, SetupState, Trend
from trading.setup01_replay import Setup01ReplayDay, Setup01ReplayEvent, Setup01ReplayReport
from trading.production_candidate_runtime import (
    HistoryLoadResult,
    ProductionCandidateRuntime,
    YFINANCE_BATCH_THREADS,
    YFINANCE_DEEP_HISTORY_WORKERS,
    _default_deep_qfq_history_loader,
    _default_short_history_loader,
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


def _candidate_event_identity(symbol: str) -> str:
    return f"{symbol}|SETUP_01|{T_DAY.isoformat()}|CONFIRMED|lifecycle=1"


def _stub_chain_factory(confirmed_symbols: set[str]):
    wave = SimpleNamespace(
        weekly_state=Trend.UPTREND,
        daily_state=Trend.UPTREND,
        primary_scenario=SimpleNamespace(family="WAVE_2_TO_3_CANDIDATE"),
        alternate_scenario=SimpleNamespace(family="ABC_CORRECTION_CANDIDATE"),
    )

    def setup01(history, **_kwargs):
        symbol = history[0].symbol.upper()
        confirmed = symbol in confirmed_symbols
        current = Setup01Evaluation(
            setup_type="SETUP_01",
            protocol_version="SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1",
            state=SetupState.CONFIRMED if confirmed else SetupState.NONE,
            as_of_date=T_DAY,
            wave1_origin=None,
            wave1_peak=None,
            wave2_low=None,
            fib_retracement_ratio=None,
            fib_retracement_region=None,
            confirmation_level=None,
            structural_invalidation=None,
            wave_scenario_invalidation=None,
            wave1_origin_confirmed_date=None,
            wave1_peak_confirmed_date=None,
            wave2_low_confirmed_date=None,
            state_entered_index=0,
            state_entered_date=T_DAY,
            confirmed_index=0 if confirmed else None,
            confirmed_date=T_DAY if confirmed else None,
            failed_index=None,
            failed_date=None,
            primary_wave_scenario="WAVE_2_TO_3_CANDIDATE",
            alternate_wave_scenario="ABC_CORRECTION_CANDIDATE",
            reason="synthetic",
            terminal_event_type=SetupState.CONFIRMED if confirmed else None,
            terminal_event_date=T_DAY if confirmed else None,
            is_new_confirmed_event_as_of=confirmed,
            is_live_preconfirmation_candidate=False,
            lifecycle_index=1,
        )
        if not confirmed:
            return Setup01ReplayReport(
                symbol=symbol,
                market="US",
                days=(Setup01ReplayDay(symbol, T_DAY, current),),
                events=(),
            )
        event = Setup01ReplayEvent(
            event_identity=_candidate_event_identity(symbol),
            symbol=symbol,
            market="US",
            trade_date=T_DAY,
            event_type=SetupState.CONFIRMED,
            setup01=current,
        )
        return Setup01ReplayReport(
            symbol=symbol,
            market="US",
            days=(Setup01ReplayDay(symbol, T_DAY, current),),
            events=(event,),
        )

    def setup02(_history, **_kwargs):
        return SimpleNamespace(current=SimpleNamespace(state=SetupState.NONE), events=())

    def factory(*, store):
        return RealDailyDecisionChain(
            store=store,
            evaluators=DailyChainEvaluators(
                wave=lambda *_args, **_kwargs: wave,
                setup01=setup01,
                setup02=setup02,
            ),
        )

    return factory


def _runtime_for(seed):
    histories = {seed.symbol: _history(seed.symbol, seed.market, seed.currency)}
    return ProductionCandidateRuntime(
        seed_loaders={
            "CN": lambda _as_of: (),
            "US": lambda _as_of: (T_DAY, (seed,)),
        },
        short_history_loader=lambda values, _start, _end: HistoryLoadResult(
            {item.symbol: histories[item.symbol] for item in values}
        ),
        deep_history_loader=lambda values, _start, _end: HistoryLoadResult(
            {item.symbol: histories[item.symbol] for item in values}
        ),
        session_window_loader=lambda _market, end, _bars: (end, end),
        enforce_us_latest_qfq_asof=False,
    )


def _state_rows(client, symbol: str | None = None):
    rows = [
        row
        for sheet_name, _headers, written in client.writes
        if sheet_name == "策略决策状态"
        for row in written
    ]
    if symbol is None:
        return rows
    return [row for row in rows if row.get("统一代码") == symbol]


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
    def test_short_history_loader_uses_bounded_threads_and_preserves_fixture_quotes(self):
        start = T_DAY - timedelta(days=1)
        seeds = (_seed("US", "AAA"), _seed("US", "BBB"))
        frame = pd.DataFrame(
            {
                ("AAA", "Open"): [10.0, 11.0],
                ("AAA", "High"): [11.0, 12.0],
                ("AAA", "Low"): [9.0, 10.0],
                ("AAA", "Close"): [10.5, 11.5],
                ("AAA", "Volume"): [100.0, 110.0],
                ("BBB", "Open"): [20.0, 21.0],
                ("BBB", "High"): [21.0, 22.0],
                ("BBB", "Low"): [19.0, 20.0],
                ("BBB", "Close"): [20.5, 21.5],
                ("BBB", "Volume"): [200.0, 210.0],
            },
            index=pd.to_datetime([start, T_DAY]),
        )
        frame.columns = pd.MultiIndex.from_tuples(
            frame.columns, names=["Ticker", "Price"]
        )
        calls = []

        def download(**kwargs):
            calls.append(kwargs)
            return frame

        with patch.dict("sys.modules", {"yfinance": SimpleNamespace(download=download)}):
            result = _default_short_history_loader(seeds, start, T_DAY)

        self.assertEqual(calls[0]["threads"], YFINANCE_BATCH_THREADS)
        self.assertEqual(calls[0]["start"], start.isoformat())
        self.assertEqual(calls[0]["end"], (T_DAY + timedelta(days=1)).isoformat())
        self.assertEqual(calls[0]["auto_adjust"], False)
        self.assertEqual(calls[0]["actions"], False)
        self.assertEqual(calls[0]["repair"], False)
        self.assertEqual(calls[0]["group_by"], "ticker")
        self.assertEqual(result.api_requests, 1)
        self.assertEqual(result.rows, 4)
        self.assertEqual(
            tuple(result.histories),
            ("AAA", "BBB"),
        )
        self.assertEqual(
            [(item.trade_date, item.close, item.volume) for item in result.histories["AAA"]],
            [(start, 10.5, 100.0), (T_DAY, 11.5, 110.0)],
        )
        self.assertEqual(
            [(item.trade_date, item.close, item.volume) for item in result.histories["BBB"]],
            [(start, 20.5, 200.0), (T_DAY, 21.5, 210.0)],
        )

    def test_deep_loader_bounded_pool_preserves_provider_contract_and_order(self):
        seeds = (
            _seed("US", "AAA"),
            _seed("US", "BBB"),
            _seed("US", "CCC"),
        )
        calls = []

        def fetch(source, watch, adjust, start, end, retry_count, retry_wait_seconds, target_trade_date):
            calls.append(
                {
                    "source": source,
                    "symbol": watch["统一代码"],
                    "adjust": adjust,
                    "start": start,
                    "end": end,
                    "retry_count": retry_count,
                    "retry_wait_seconds": retry_wait_seconds,
                    "target_trade_date": target_trade_date,
                }
            )
            if watch["统一代码"] == "BBB":
                raise RuntimeError("synthetic provider failure")
            return _history(watch["统一代码"], "US", "USD")

        with patch("providers.fetch_with_retry", side_effect=fetch):
            result = _default_deep_qfq_history_loader(
                seeds,
                T_DAY - timedelta(days=999),
                T_DAY,
            )

        self.assertEqual(YFINANCE_DEEP_HISTORY_WORKERS, 4)
        self.assertEqual(result.api_requests, 3)
        self.assertEqual(result.rows, 120)
        self.assertEqual(tuple(result.histories), ("AAA", "CCC"))
        self.assertEqual(result.errors, ("BBB:RuntimeError",))
        self.assertEqual(
            {call["symbol"] for call in calls},
            {"AAA", "BBB", "CCC"},
        )
        self.assertTrue(
            all(
                call["source"] == "yfinance"
                and call["adjust"] == "qfq"
                and call["retry_count"] == 1
                and call["retry_wait_seconds"] == 0.0
                and call["target_trade_date"] == T_DAY
                for call in calls
            )
        )

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

    def test_candidate_only_write_state_is_discovery_only(self):
        client = _rows()
        seed = _seed("US", "DYN")
        runtime = _runtime_for(seed)
        event_identity = _candidate_event_identity("DYN")

        with (
            patch(
                "scripts.run_production_daily_decision.DailyDecisionChain",
                side_effect=_stub_chain_factory({"DYN"}),
            ),
            patch(
                "trading.daily_decision_chain.evaluate_setup01_decision",
                side_effect=lambda event, _history, **_kwargs: _decision_for_state(event),
            ),
        ):
            result = run_production_daily_decision(
                client,
                as_of_date=T_DAY,
                preflight=False,
                write_state=True,
                approved_event_identities=(event_identity,),
                allocation_budgets={"US-1": 100000.0},
                now=AFTER_CLOSE,
                candidate_runtime=runtime,
            )

        us_report = next(item for item in result["reports"] if item["账户ID"] == "US-1")
        dyn = next(row for row in us_report["报告"]["results"] if row["symbol"] == "DYN")
        metadata = us_report["universe"]["provenance_metadata"]["DYN"]
        self.assertEqual(dyn["final_status"], STRATEGY_PROPOSAL)
        self.assertIsNone(dyn["portfolio_result"])
        self.assertEqual(metadata["source"], "DYNAMIC_CANDIDATE")
        self.assertFalse(metadata["state_persistence_eligible"])
        self.assertTrue(metadata["promotion_required"])
        self.assertEqual(metadata["persistence_policy"], "READ_ONLY_DISCOVERY")
        self.assertEqual(_state_rows(client, "DYN"), [])
        self.assertIn("promotion_required=true", us_report["Markdown"])
        self.assertIn("NOT_PRODUCTION_EXECUTION_ELIGIBLE_UNTIL_PROMOTED", us_report["Markdown"])

    def test_candidate_only_approval_and_budget_do_not_allocate_or_write(self):
        client = _rows()
        seed = _seed("US", "DYN")
        runtime = _runtime_for(seed)

        with (
            patch(
                "scripts.run_production_daily_decision.DailyDecisionChain",
                side_effect=_stub_chain_factory({"DYN"}),
            ),
            patch(
                "trading.daily_decision_chain.evaluate_setup01_decision",
                side_effect=lambda event, _history, **_kwargs: _decision_for_state(event),
            ),
        ):
            result = run_production_daily_decision(
                client,
                as_of_date=T_DAY,
                preflight=False,
                approved_event_identities=(_candidate_event_identity("DYN"),),
                allocation_budgets={"US-1": 100000.0},
                now=AFTER_CLOSE,
                candidate_runtime=runtime,
            )

        us_report = next(item for item in result["reports"] if item["账户ID"] == "US-1")
        dyn = next(row for row in us_report["报告"]["results"] if row["symbol"] == "DYN")
        self.assertEqual(dyn["final_status"], STRATEGY_PROPOSAL)
        self.assertIsNone(dyn["portfolio_result"])
        self.assertEqual(client.writes, [])

    def test_formal_candidate_member_keeps_formal_state_lifecycle(self):
        client = _rows()
        seed = _seed("US", "AAPL")
        runtime = _runtime_for(seed)
        event_identity = _candidate_event_identity("AAPL")

        with (
            patch(
                "scripts.run_production_daily_decision.DailyDecisionChain",
                side_effect=_stub_chain_factory({"AAPL"}),
            ),
            patch(
                "trading.daily_decision_chain.evaluate_setup01_decision",
                side_effect=lambda event, _history, **_kwargs: _decision_for_state(event),
            ),
        ):
            first = run_production_daily_decision(
                client,
                as_of_date=T_DAY,
                preflight=False,
                write_state=True,
                now=AFTER_CLOSE,
                candidate_runtime=runtime,
            )
            second = run_production_daily_decision(
                client,
                as_of_date=T_DAY,
                preflight=False,
                write_state=True,
                approved_event_identities=(event_identity,),
                allocation_budgets={"US-1": 100000.0},
                now=AFTER_CLOSE,
                candidate_runtime=runtime,
            )

        us_report = next(item for item in second["reports"] if item["账户ID"] == "US-1")
        aapl = next(row for row in us_report["报告"]["results"] if row["symbol"] == "AAPL")
        metadata = us_report["universe"]["provenance_metadata"]["AAPL"]
        self.assertEqual(first["reports"][1]["报告"]["results"][0]["final_status"], STRATEGY_PROPOSAL)
        self.assertEqual(aapl["final_status"], "PORTFOLIO_ALLOWED")
        self.assertTrue(aapl["provenance"]["production_execution_eligible"])
        self.assertTrue(metadata["state_persistence_eligible"])
        self.assertFalse(metadata["promotion_required"])
        self.assertTrue(_state_rows(client, "AAPL"))
        self.assertTrue(
            any(row["记录类型"] == "PENDING_T1" for row in _state_rows(client, "AAPL"))
        )

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

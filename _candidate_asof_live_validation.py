"""Temporary public-provider Actions probe; never reads real Sheets/holdings."""
import contextlib
import io
import json
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import scripts.run_cloud_daily_report as report
from market_data_contract import canonical_provider_for_market
from providers import fetch_hithink_with_provenance, _hithink_json
from tests.test_production_prerequisites import _rows
from trading.candidate_universe_sources import (
    CandidateSeedDataError, HITHINK_CN_INDEXES,
    HITHINK_INDEX_CONSTITUENT_ENDPOINT, HithinkCandidateSeedAdapter,
    IwbOfficialHoldingsAdapter, parse_hithink_index_constituents,
)

market = os.environ['VALIDATION_MARKET']
as_of = date.fromisoformat(os.environ.get('REPORT_DATE') or '2026-09-30')
out = Path(os.environ['RUNNER_TEMP']) / 'cloud-daily-report' / market
summary = {'market': market, 'report_as_of_date': str(as_of),
           'real_holdings_read': False, 'notifications': False,
           'production_state_write': False, 'formal_d1_write': False}
if market == 'CN':
    indexes = []
    for name, code in HITHINK_CN_INDEXES:
        source_day, timestamp, seeds = parse_hithink_index_constituents(
            _hithink_json(HITHINK_INDEX_CONSTITUENT_ENDPOINT, {'thscode': code}),
            index_name=name, index_code=code)
        indexes.append({'index_code': code, 'snapshot_date': str(source_day), 'rows': len(seeds)})
    summary['index_snapshots'] = indexes
    try:
        seeds = HithinkCandidateSeedAdapter().load(as_of=as_of)
        assert all(seed.source_as_of <= as_of for seed in seeds)
        summary['seed_status'] = 'AVAILABLE'
    except CandidateSeedDataError as exc:
        assert 'AFTER_AS_OF' in str(exc)
        summary['seed_status'] = 'UNAVAILABLE_FAIL_CLOSED'
        summary['seed_diagnostic'] = str(exc)
    etf = fetch_hithink_with_provenance(
        {'统一代码': '512400.SH', '名称': 'public ETF', '市场': 'CN', '币种': 'CNY'},
        'qfq', as_of - timedelta(days=2000), as_of)
    assert len(etf.quotes) >= 60 and etf.quotes[-1].trade_date == as_of
    assert all(quote.trade_date <= as_of for quote in etf.quotes)
    summary['public_etf'] = {'symbol': '512400.SH', 'rows': len(etf.quotes),
        'first_date': str(etf.quotes[0].trade_date), 'last_date': str(etf.quotes[-1].trade_date),
        'api_requests': etf.api_requests, 'provenance': etf.provenance}
    symbols = ('000725.SZ', '512400.SH')
else:
    source_day, seeds = IwbOfficialHoldingsAdapter().load(as_of=as_of)
    assert source_day <= as_of and all(seed.source_as_of <= as_of for seed in seeds)
    summary['seed_status'] = 'AVAILABLE'
    summary['membership_snapshot'] = {'snapshot_date': str(source_day), 'rows': len(seeds)}
    try:
        IwbOfficialHoldingsAdapter().load(as_of=source_day - timedelta(days=1))
    except CandidateSeedDataError as exc:
        assert 'AFTER_AS_OF' in str(exc)
        summary['historical_fail_closed'] = str(exc)
    else:
        raise AssertionError('future IWB membership was accepted')
    symbols = ('AAPL', 'MSFT', 'PUBLIC-ASOF-NOT-A-SYMBOL')

client = _rows()
account = market + '-1'
client.rows['策略账户'] = [{**row, '净值日期': str(as_of)} for row in client.rows['策略账户'] if row['市场'] == market]
client.rows['策略股票池'] = [{'启用': 'TRUE', '账户ID': account, '市场': market,
    '统一代码': symbol, '名称': symbol, '备注': 'PUBLIC_VALIDATION_FIXTURE'} for symbol in symbols]
client.rows['策略风险分组'] = [{'市场': market, '统一代码': symbol, '风险组': 'PUBLIC_FIXTURE', '备注': ''} for symbol in symbols]
client.rows['策略持仓'] = []
client.rows['策略模拟账本'] = []
client.rows['策略决策状态'] = []
client.rows['最新行情'] = []
client.rows['历史行情_前复权'] = []
vendor = canonical_provider_for_market(market)
client.rows['自选清单'] = [{'启用': 'TRUE', '市场': market, '统一代码': symbol, '名称': symbol,
    '币种': 'CNY' if market == 'CN' else 'USD', '主数据源': vendor, '历史数据源': vendor,
    '校验数据源': '', '时区': 'Asia/Shanghai' if market == 'CN' else 'America/New_York',
    '收盘时间': '15:00' if market == 'CN' else '16:00',
    **({'HITHINK代码': symbol} if market == 'CN' else {'yfinance代码': symbol})} for symbol in symbols]
client.header_rows['自选清单'] = tuple(client.rows['自选清单'][0])
client.config = lambda: {'history_days': '1000', 'retry_count': '1', 'retry_wait_seconds': '0'}
with patch.object(report, 'SheetsClient', return_value=client), contextlib.redirect_stdout(io.StringIO()):
    exit_code = report.main(['--market', market, '--date', str(as_of), '--output', str(out), '--no-notify'])
payload = json.loads((out / 'daily-report.json').read_text(encoding='utf-8'))
metadata = payload['cloud_daily_report']
summary['report'] = {key: metadata.get(key) for key in ('status', 'RUN_STATUS', 'DATA_STATUS', 'CANDIDATE_STATUS')}
summary['exit_code'] = exit_code
assert exit_code == 0, metadata
assert (out / 'daily-report.html').is_file()
assert not client.writes
assert metadata['DATA_STATUS'] == 'PARTIAL'
with patch.object(report, 'run_cloud_daily_report', return_value=payload), contextlib.redirect_stdout(io.StringIO()):
    strict_exit = report.main(['--market', market, '--date', str(as_of), '--output', str(out), '--no-notify', '--require-complete'])
assert strict_exit == 2
summary['strict_exit_code'] = strict_exit
print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
(out / 'validation-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

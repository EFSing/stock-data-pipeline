"""Fixed Development-only confirmed retest timing research; no production writes."""
from __future__ import annotations
from collections import Counter
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.development import system_signal_scarcity_audit_v1 as audit
from research.development_holdout_dataset import load_frozen_holdout, FROZEN_INPUT_PATH
from research.market_sessions import build_market_session_dates
from trading.models import DecisionAction
from trading.setup01 import _candidate_from_wave as candidate01
from trading.setup02 import _candidate_from_wave as candidate02
from trading.setup01_decision import execute_setup01_t1_open
from trading.setup02_decision import execute_setup02_t1_open
from trading.risk import MIN_TARGET_UPSIDE_PCT, target_upside_pct, risk_reward

VERSION = 'POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1'
STATUS = 'READY_FOR_DECISION_POST_CONFIRMATION_RETEST_ARCHITECTURE'
STEM = 'post_confirmation_retest_entry_causal_research_v1'
PROTOCOL = ROOT / 'research/protocols' / (STEM + '.json')
OUTPUT = ROOT / 'research/development' / STEM


def identity_hash(value):
    return 'sha256:' + hashlib.sha256(audit._canonical_json(value).encode('utf-8')).hexdigest()


def context_key(setup_type, wave, index):
    candidate = (candidate01 if setup_type == audit.SETUP01 else candidate02)(wave, index)
    return candidate.key if candidate is not None else None


def price_plan(record, price):
    """Reprice only entry; canonical target sources/stop/zone remain frozen."""
    geometry = record.geometry
    if not geometry.calculable or not geometry.targets:
        return None, 'NO_VALID_FROZEN_GEOMETRY_OR_TARGET'
    if price <= geometry.structural_invalidation:
        return None, 'STRUCTURAL_INVALIDATION'
    if price < geometry.entry_zone_low or price > geometry.entry_zone_high:
        return None, 'OUTSIDE_FROZEN_ENTRY_ZONE'
    if target_upside_pct(geometry.targets[0], price) < MIN_TARGET_UPSIDE_PCT:
        return None, 'RETEST_TARGET_UPSIDE_BELOW_MINIMUM'
    if risk_reward(price, geometry.execution_stop, geometry.targets).rr_ratios[0] < 2:
        return None, 'RETEST_RR_BELOW_MINIMUM'
    plan = audit._rebuild_plan(replace(geometry, planned_entry=price), geometry.target_candidates)
    return (plan, None) if plan is not None else (None, 'TARGET_REASONABLENESS_FAILED')


def execute_plan(record, plan, plan_date, quotes, sessions):
    # The production executor reads OPEN only, including exact next-session proof.
    decision = replace(record.decision, action=DecisionAction.ENTRY_ALLOWED,
                       trade_date=plan_date, planned_entry=plan.planned_entry,
                       entry_zone_low=plan.entry_zone_low, entry_zone_high=plan.entry_zone_high,
                       structural_invalidation=plan.structural_invalidation,
                       execution_stop=plan.execution_stop, targets=plan.targets,
                       target_candidates=plan.target_candidates, rr=plan.rr,
                       target_upside_pct=plan.target_upside_pct)
    executor = execute_setup01_t1_open if record.setup_type == audit.SETUP01 else execute_setup02_t1_open
    return executor(decision, quotes, market_session_dates=sessions)


def evaluate_event(record, quotes, sessions, snapshots, wave_at):
    """One original confirmed lifecycle -> at most one A and one residual B fact."""
    dates = tuple(sessions[record.decision.market])
    ordinal = {day: index for index, day in enumerate(dates)}
    by_date = {quote.trade_date: (index, quote) for index, quote in enumerate(quotes)}
    confirmation = record.decision.trade_date
    result = {'A_plan': False, 'A_executable': False, 'A_reason': None,
              'B_plan': False, 'B_executable': False, 'B_reason': None,
              'A_latency': None, 'B_latency': None, 'B_retested': False}
    if record.execution is not None and record.execution.outcome == 'EXECUTED':
        result.update(A_reason='INCUMBENT_EXECUTED', B_reason='INCUMBENT_EXECUTED')
        return result
    geometry = record.geometry
    if not geometry.calculable or not geometry.targets or confirmation not in by_date:
        result.update(A_reason='NO_VALID_FROZEN_GEOMETRY_OR_TARGET', B_reason='NO_VALID_FROZEN_GEOMETRY_OR_TARGET')
        return result
    index, quote = by_date[confirmation]
    # T HIGH is known at confirmation close. T+1 HIGH/LOW are never used for A.
    if quote.high >= geometry.targets[0]:
        result.update(A_reason='T1_EXHAUSTED_AT_CONFIRMATION', B_reason='T1_EXHAUSTED_AT_CONFIRMATION')
        return result
    original_key = context_key(record.setup_type, wave_at(index), index)
    if original_key is None:
        result.update(A_reason='CONTEXT_UNPROVEN', B_reason='CONTEXT_UNPROVEN')
        return result
    result['A_plan'] = True  # retained confirmed pending fact, not T-day ENTRY_ALLOWED
    opening = audit._exact_next_open(record.decision, quotes, sessions)
    if opening is None:
        result.update(A_reason='SKIP_NO_T1_BAR', B_reason='DATA_OR_SESSION_CONTRACT_UNPROVEN')
        return result
    if opening <= geometry.structural_invalidation:
        result.update(A_reason='SKIP_BELOW_INVALIDATION', B_reason='STRUCTURAL_INVALIDATION_AT_T1_OPEN')
        return result
    if opening >= geometry.targets[0]:
        result.update(A_reason='T1_EXHAUSTED_AT_T1_OPEN', B_reason='T1_EXHAUSTED_BEFORE_RETEST')
        return result
    plan, reason = price_plan(record, opening)
    if plan is not None:
        execution = execute_plan(record, plan, confirmation, quotes, sessions)
        result['A_executable'] = execution.outcome == 'EXECUTED'
        result['A_reason'] = execution.outcome
        if result['A_executable']:
            result.update(A_latency=1, B_reason='A_EXECUTED_NO_B_SEARCH')
            return result
    else:
        result['A_reason'] = reason
    lifecycle = audit._snapshot_for_event(record).lifecycle_index
    expected_start = ordinal[confirmation] + 1
    for session_index in range(expected_start, len(dates)):
        day = dates[session_index]
        if day not in by_date:
            result['B_reason'] = 'DATA_OR_SESSION_CONTRACT_UNPROVEN'
            return result
        index, bar = by_date[day]
        snapshot = snapshots[index]
        # Existing structure fails on CLOSE; no invented intraday invalidation rule.
        if bar.close <= geometry.structural_invalidation:
            result['B_reason'] = 'STRUCTURAL_INVALIDATION'
            return result
        if snapshot.lifecycle_index != lifecycle or context_key(record.setup_type, wave_at(index), index) != original_key:
            result['B_reason'] = 'CONTEXT_REPLACED_OR_LIFECYCLE_ENDED'
            return result
        if bar.high >= geometry.targets[0]:
            result['B_reason'] = 'T1_EXHAUSTED_BEFORE_RETEST'
            return result
        if not geometry.entry_zone_low <= bar.close <= geometry.entry_zone_high:
            continue
        result.update(B_retested=True, B_latency=session_index - ordinal[confirmation])
        plan, reason = price_plan(record, float(bar.close))
        if plan is None:
            result['B_reason'] = reason
            return result  # first retest only; never cherry-pick a later close
        result['B_plan'] = True
        execution = execute_plan(record, plan, day, quotes, sessions)
        result['B_executable'] = execution.outcome == 'EXECUTED'
        result['B_reason'] = execution.outcome
        return result
    result['B_reason'] = 'NEVER_RETESTED_RIGHT_CENSORED_DATASET_END'
    return result


def summarize(rows):
    return {'confirmed': len(rows),
            'incumbent_entry_allowed': sum(row['incumbent_allowed'] for row in rows),
            'incumbent_exact_t1_executed': sum(row['incumbent_executed'] for row in rows),
            'above_entry_zone_cohort': sum(row['above'] for row in rows),
            'A_recovered_pending_plan': sum(row['A_plan'] and not row['incumbent_allowed'] for row in rows),
            'A_pending_plan_total': sum(row['A_plan'] for row in rows),
            'A_executable': sum(row['A_executable'] for row in rows),
            'B_retested_close': sum(row['B_retested'] for row in rows),
            'B_recovered_plan': sum(row['B_plan'] and not row['incumbent_allowed'] for row in rows),
            'B_plan_total': sum(row['B_plan'] for row in rows),
            'B_executable': sum(row['B_executable'] for row in rows),
            'incremental_executable_union': sum(row['A_executable'] or row['B_executable'] for row in rows),
            'A_terminal_reasons': dict(sorted(Counter(row['A_reason'] for row in rows).items())),
            'B_terminal_reasons': dict(sorted(Counter(row['B_reason'] for row in rows).items())),
            'A_executable_latency_sessions': audit._distribution(row['A_latency'] for row in rows),
            'B_retest_latency_sessions': audit._distribution(row['B_latency'] for row in rows),
            'B_executable_retest_latency_sessions': audit._distribution(row['B_latency'] for row in rows if row['B_executable']),
            'B_latency_session_counts': dict(sorted(Counter(str(row['B_latency']) for row in rows if row['B_latency'] is not None).items()))}


def grouped(rows, key, values):
    return {value: summarize([row for row in rows if row[key] == value]) for value in values}


def run_research(output=OUTPUT):
    protocol = json.loads(PROTOCOL.read_text(encoding='utf-8'))
    body = json.loads(json.dumps(protocol));body['integrity']['protocol_sha256'] = None
    assert identity_hash(body) == protocol['integrity']['protocol_sha256']
    manifest, quotes_by_symbol, wrapper = load_frozen_holdout(
        manifest_path=ROOT/'research/development_holdout/dataset_manifest.json',
        replay_input_path=FROZEN_INPUT_PATH,
        replay_manifest_path=ROOT/'research/development_holdout/replay_manifest.json')
    assert manifest['integrity']['manifest_sha256'] == protocol['dataset']['manifest_sha256']
    assert wrapper.aggregate_hash == protocol['dataset']['replay_input_aggregate_sha256']
    sessions = build_market_session_dates(quotes_by_symbol)
    halves = audit._half_map(quotes_by_symbol)
    reports01, reports02, events01, events02 = audit._build_structural_replays(quotes_by_symbol)
    _, records01 = audit._build_decision_records(audit.SETUP01, events01, quotes_by_symbol, halves)
    _, records02 = audit._build_decision_records(audit.SETUP02, events02, quotes_by_symbol, halves)
    records = records01 + records02
    all_lifecycles = (audit._build_lifecycles(audit.SETUP01, reports01, halves)
                      + audit._build_lifecycles(audit.SETUP02, reports02, halves))
    assert len(all_lifecycles) == 2050
    parent = json.loads((ROOT/'research/development/system_signal_scarcity_audit_v1.json').read_text(encoding='utf-8'))
    parent_body = json.loads(json.dumps(parent));parent_body['integrity']['canonical_payload_sha256'] = None
    assert identity_hash(parent_body) == protocol['parent_audit']['canonical_payload_sha256']
    assert parent['decision']['classification'] == 'MIXED_ARCHITECTURE_SIGNAL_STARVATION'
    before = audit._decision_snapshot_digest(records)
    waves = {symbol: audit._CausalWaveAccessor(quotes) for symbol, quotes in quotes_by_symbol.items()}
    rows = []
    for record in records:
        symbol = record.decision.symbol
        report = (reports01 if record.setup_type == audit.SETUP01 else reports02)[symbol]
        snapshots = tuple(day.setup01 if record.setup_type == audit.SETUP01 else day.setup02 for day in report.days)
        row = evaluate_event(record, quotes_by_symbol[symbol], sessions, snapshots, waves[symbol].at)
        row.update(identity=record.decision.event_identity, setup=record.setup_type, symbol=symbol,
                   lifecycle=(record.setup_type, symbol, audit._snapshot_for_event(record).lifecycle_index),
                   market=record.decision.market, half=halves[record.decision.market][record.decision.trade_date],
                   above=record.first_fail == 'ABOVE_ENTRY_ZONE',
                   incumbent_allowed=record.decision.action == DecisionAction.ENTRY_ALLOWED,
                   incumbent_executed=record.execution is not None and record.execution.outcome == 'EXECUTED')
        rows.append(row)
    ids = [row['identity'] for row in rows]
    lifecycles = [row['lifecycle'] for row in rows]
    incumbent = {row['identity'] for row in rows if row['incumbent_executed']}
    added_a = {row['identity'] for row in rows if row['A_executable']}
    added_b = {row['identity'] for row in rows if row['B_executable']}
    assert len(ids) == len(set(ids)) == len(set(lifecycles)) == 999
    assert not incumbent & (added_a | added_b) and not added_a & added_b
    assert before == audit._decision_snapshot_digest(records)
    assert sum(row['above'] for row in rows) == 595
    counts = summarize(rows)
    assert counts['incumbent_entry_allowed'] == 8 and counts['incumbent_exact_t1_executed'] == 4
    concentration = grouped(rows, 'symbol', sorted(quotes_by_symbol))
    ranked = sorted(concentration, key=lambda symbol: (-concentration[symbol]['incremental_executable_union'],symbol))
    top = ranked[0]
    payload = {'protocol_version': VERSION, 'status': STATUS,
               'source': {'dataset_version': manifest['dataset_version'], 'manifest_sha256':manifest['integrity']['manifest_sha256'],
                          'replay_input_aggregate_sha256':wrapper.aggregate_hash,
                          'protocol_sha256':protocol['integrity']['protocol_sha256'],
                          'source_event_snapshot_sha256':before},
               'parent_audit_classification':'MIXED_ARCHITECTURE_SIGNAL_STARVATION',
               'all_confirmed':counts,
               'above_entry_zone':summarize([row for row in rows if row['above']]),
               'by_setup':grouped(rows,'setup',(audit.SETUP01,audit.SETUP02)),
               'by_market':grouped(rows,'market',('CN','US')),
               'by_time_half':grouped(rows,'half',('EARLY','LATE')),
               'above_by_setup':grouped([row for row in rows if row['above']],'setup',(audit.SETUP01,audit.SETUP02)),
               'above_by_market':grouped([row for row in rows if row['above']],'market',('CN','US')),
               'above_by_time_half':grouped([row for row in rows if row['above']],'half',('EARLY','LATE')),
               'symbol_concentration':concentration,
               'top_incremental_symbol':top,
               'excluding_top_symbol':summarize([row for row in rows if row['symbol'] != top]),
               'conservation': {'candidate_lifecycles':len(all_lifecycles), 'nonconfirmed_lifecycles':len(all_lifecycles)-len(set(lifecycles)), 'unique_confirmed_events':len(set(ids)), 'unique_confirmed_lifecycles':len(set(lifecycles)),
                                'incumbent_executed':len(incumbent),'added_A':len(added_a),'added_B':len(added_b),
                                'A_B_overlap':len(added_a & added_b),'incumbent_increment_overlap':len(incumbent & (added_a | added_b)),
                                'executed_union':len(incumbent | added_a | added_b),
                                'not_executed':len(rows)-len(incumbent | added_a | added_b),
                                'A_terminal_count':sum(counts['A_terminal_reasons'].values()),
                                'B_terminal_count':sum(counts['B_terminal_reasons'].values()),'source_events_unchanged':True},
               'controls': {'development_only':True,'production_semantics_changed':False,'final_oos_accessed':False,
                            'parameter_search':False,'waiting_window':None,'threshold_sweep':False,'post_entry_outcomes_used':False,
                            'real_holdings_accessed':False,'provider_accessed':False,'sheets_writes':0,'state_writes':0,
                            'paper_writes':0,'broker_orders':0,'raw_bars_persisted':False,'event_dump_persisted':False},
               'integrity': {'canonical_payload_sha256':None,'hash_scope':'canonical JSON with integrity.canonical_payload_sha256=null'}}
    payload['integrity']['canonical_payload_sha256'] = identity_hash(payload)
    Path(str(output)+'.json').write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    write_markdown(payload,Path(str(output)+'.md'))
    return payload


def write_markdown(p,path):
    c=p['all_confirmed'];above=p['above_entry_zone']
    lines=['# Post-confirmation Retest Entry Causal Research V1','',
           '`DEVELOPMENT_ONLY / NOT_PRODUCTION_AUTHORIZED`','',
           'Parent audit remains `MIXED_ARCHITECTURE_SIGNAL_STARVATION`. This fixed study tests decoupling confirmed facts from immediate entry; it does not prove Entry Zone wrong.','',
           '## Finding','',
           'Absolute recovery is small: A adds '+str(c['A_executable'])+' executable events; B forms '+str(c['B_plan_total'])+' plans ('+str(c['B_recovered_plan'])+' from previously non-ENTRY_ALLOWED facts) and adds '+str(c['B_executable'])+' executions. The '+str(above['confirmed'])+' ABOVE_ENTRY_ZONE cohort contributes '+str(above['B_recovered_plan'])+' B plans and '+str(above['B_executable'])+' executions ('+format(100*above['B_executable']/above['confirmed'],'.3f')+'%).',
           'SETUP_01 adds '+str(p['by_setup']['SETUP_01']['B_executable'])+'; SETUP_02 adds '+str(p['by_setup']['SETUP_02']['B_executable'])+'. CN/US add '+str(p['by_market']['CN']['B_executable'])+'/'+str(p['by_market']['US']['B_executable'])+'; EARLY/LATE add '+str(p['by_time_half']['EARLY']['B_executable'])+'/'+str(p['by_time_half']['LATE']['B_executable'])+'. This is no broad or time-stable restoration of the missing cohort, and no production authorization.',
           '', '## Fixed policies / timing','',
           'A retains a frozen confirmed pending fact, checks only exact T+1 OPEN and reuses the incumbent executor. A pending plan is not incumbent ENTRY_ALLOWED; recovered plans exclude existing ENTRY_ALLOWED.',
           'B searches only after A did not execute. First close inside the frozen zone must pass frozen T1 5%, 2R and existing target reasonableness; execute only its exact next-session OPEN. A failed first retest ends the observation, with no second attempt.',
           'All confirmation-day targets/provenance, ATR14 zone, confirmation level, structural invalidation and stop remain frozen. Existing candidate eligibility/key and lifecycle replacement terminate waiting causally; structure invalidation is CLOSE <= frozen invalidation. Known HIGH >= frozen T1 exhausts it; the confirmation-day HIGH is already known at T close. Same-close terminators precede a retest conservatively. No waiting window or outcome/parameter optimization.','',
           '## Aggregate','',
           '| Cohort | Confirmed | Incumbent allowed | Incumbent executed | A recovered pending plans | A executable | B plan total | B recovered plans | B executable |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for label,row in [('ALL',c),('ABOVE_ENTRY_ZONE',above)]+list(p['by_setup'].items())+list(p['by_market'].items())+list(p['by_time_half'].items()):
        lines.append('| '+label+' | '+' | '.join(str(row[k]) for k in ('confirmed','incumbent_entry_allowed','incumbent_exact_t1_executed','A_recovered_pending_plan','A_executable','B_plan_total','B_recovered_plan','B_executable'))+' |')
    for name,row in [('ALL',c),('ABOVE_ENTRY_ZONE',above)]:
        lines += ['', '## '+name+' terminal reasons','', '```json',json.dumps({k:row[k] for k in ('A_terminal_reasons','B_terminal_reasons','B_retest_latency_sessions','B_executable_retest_latency_sessions')},ensure_ascii=False,indent=2),'```']
    lines += ['', '## Concentration / conservation','',
              'Incremental symbol counts: '+', '.join('`'+symbol+'`='+str(row['incremental_executable_union']) for symbol,row in p['symbol_concentration'].items() if row['incremental_executable_union'])+'.',
              'Top incremental symbol (lexicographic tie-break): `'+p['top_incremental_symbol']+'`; excluding it retains '+str(p['excluding_top_symbol']['incremental_executable_union'])+' incremental executable events.',
              '```json',json.dumps(p['conservation'],indent=2),'```','',
              'Full setup/market/time-half/symbol and ABOVE_ENTRY_ZONE strata are retained in JSON. NEVER_RETESTED at dataset end is right-censored, not proof of permanent failure. Executable counts are descriptive opportunities, not broker fills, returns or evidence of profitability.',
              '', '## Decision boundary','',
              'Whether recovery is large or small, stop here. User must decide whether confirmed → wait-for-retest architecture should enter a separate production design / fresh-validation task. No production change, extra policy, waiting-window search, ATR sweep, confirmation relaxation, target replacement or Final OOS access is authorized.','',
              '`'+STATUS+'`','']
    path.write_text('\n'.join(lines),encoding='utf-8')


if __name__ == '__main__':
    p=run_research();print(json.dumps({'status':p['status'],'counts':p['all_confirmed'],'hash':p['integrity']['canonical_payload_sha256']},ensure_ascii=False))

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from research.development import post_confirmation_retest_entry_causal_research_v1 as retest
from research.development import system_signal_scarcity_audit_v1 as audit
from trading.models import DecisionAction
from trading.setup01_decision import Setup01TargetCandidate, Setup01Decision
from trading.risk import risk_reward, target_upside_pct


def fixture(setup=audit.SETUP01):
    day=date(2026,1,2)
    candidate=Setup01TargetCandidate(175.,'WAVE3_FIB_EXTENSION','controlled')
    g=audit.GeometrySnapshot(setup,True,'ABOVE_ENTRY_ZONE',20.,115.,100.,110.,90.,85.,100.,
                             (candidate,),(175.,),risk_reward(115.,85.,(175.,)),
                             target_upside_pct(175.,115.),False,(90.,100.,95.),day)
    # Same immutable Decision shape consumed by the actual OPEN executors.
    d=Setup01Decision(protocol_version='test',event_identity='test-confirmed',symbol='TEST',market='US',
        trade_date=day,event_type=NS(value='CONFIRMED'),decision_calculable=True,
        action=DecisionAction.NO_TRADE,gate_reason='ABOVE_ENTRY_ZONE',gate_detail='controlled',
        atr14=20.,wave1_origin=90.,confirmation_level=100.,planned_entry=115.,
        entry_zone_low=100.,entry_zone_high=110.,structural_invalidation=90.,wave_scenario_invalidation=90.,
        execution_stop=85.,target_candidates=(candidate,),targets=(175.,),
        target_reasonableness_checked=True,target_reasonableness_passed=True,
        rr=g.rr,position_size=None,position_size_required_input=None)
    snapshot=NS(lifecycle_index=1)
    event=NS(setup01=snapshot,setup02=snapshot)
    r=audit.DecisionRecord(setup,event,d,None,g,'ABOVE_ENTRY_ZONE',('ABOVE_ENTRY_ZONE',))
    quotes=[NS(symbol='TEST',market='US',trade_date=day+timedelta(days=i),
               open=opening,close=close,high=high) for i,(opening,close,high) in enumerate(
               [(115.,115.,116.),(115.,105.,116.),(105.,106.,108.),(104.,105.,108.)])]
    sessions={'US':tuple(q.trade_date for q in quotes)}
    return r,quotes,sessions,[snapshot]*len(quotes)


class ConfirmedRetestTests(unittest.TestCase):
    def evaluate(self,r,q,s,snap,keys=None):
        with patch.object(retest,'context_key',side_effect=(lambda setup,wave,index: (keys or {}).get(index,(1,2)))):
            return retest.evaluate_event(r,q,s,snap,lambda index:index)

    def test_a_executes_only_exact_open_for_both_setups_without_future_intraday(self):
        for setup in (audit.SETUP01,audit.SETUP02):
            with self.subTest(setup=setup):
                r,q,s,snap=fixture(setup);q[1].open=105.;q[1].high=200.;q[1].close=70.
                row=self.evaluate(r,q,s,snap)
                self.assertTrue(row['A_executable']);self.assertFalse(row['B_executable'])
                self.assertEqual(row['B_reason'],'A_EXECUTED_NO_B_SEARCH')

    def test_b_first_close_creates_plan_then_uses_its_exact_next_open(self):
        r,q,s,snap=fixture();row=self.evaluate(r,q,s,snap)
        self.assertFalse(row['A_executable']);self.assertTrue(row['B_plan']);self.assertTrue(row['B_executable'])
        self.assertEqual(row['B_latency'],1)
        q[2].open=111.;row=self.evaluate(r,q,s,snap)
        self.assertTrue(row['B_plan']);self.assertFalse(row['B_executable'])
        self.assertEqual(row['B_reason'],'SKIP_GAP_ABOVE_ENTRY_ZONE')

    def test_missing_exact_session_never_falls_forward(self):
        r,q,s,snap=fixture();q[1].close=115.;q=q[:2]+q[3:];snap=snap[:len(q)]
        row=self.evaluate(r,q,s,snap)
        self.assertEqual(row['B_reason'],'DATA_OR_SESSION_CONTRACT_UNPROVEN')
        r,q,s,snap=fixture();q=q[:1]+q[2:];snap=snap[:len(q)]
        self.assertEqual(self.evaluate(r,q,s,snap)['A_reason'],'SKIP_NO_T1_BAR')

    def test_termination_precedes_same_close_retest(self):
        for cause in ('structure','context','lifecycle','target'):
            with self.subTest(cause=cause):
                r,q,s,snap=fixture();keys={}
                if cause=='structure':q[1].close=90.
                if cause=='context':keys[1]=None
                if cause=='lifecycle':snap[1]=NS(lifecycle_index=2)
                if cause=='target':q[1].high=175.
                row=self.evaluate(r,q,s,snap,keys)
                self.assertFalse(row['B_plan']);self.assertFalse(row['B_executable'])
                self.assertIn(row['B_reason'],('STRUCTURAL_INVALIDATION','CONTEXT_REPLACED_OR_LIFECYCLE_ENDED','T1_EXHAUSTED_BEFORE_RETEST'))

    def test_first_retest_economic_failure_does_not_search_later_close(self):
        for target,close,reason in ((114.,109.,'RETEST_TARGET_UPSIDE_BELOW_MINIMUM'),
                                   (130.,105.,'RETEST_RR_BELOW_MINIMUM')):
            r,q,s,snap=fixture();q[0].high=112.;q[0].close=111.
            q[1].open=113.;q[1].high=113.5;q[1].close=close
            candidate=replace(r.geometry.target_candidates[0],price=target)
            r=replace(r,geometry=replace(r.geometry,targets=(target,),target_candidates=(candidate,)))
            row=self.evaluate(r,q,s,snap)
            self.assertEqual(row['B_reason'],reason);self.assertFalse(row['B_plan'])

    def test_next_open_upside_and_rr_remain_hard_gates(self):
        r,q,s,snap=fixture();plan,_=retest.price_plan(r,105.)
        for opening,targets,expected in ((111.,(175.,),'SKIP_GAP_ABOVE_ENTRY_ZONE'),
             (105.,(109.,),'SKIP_TARGET_UPSIDE_BELOW_MINIMUM'),(105.,(115.,),'SKIP_RR_BELOW_MINIMUM_AT_OPEN')):
            q[2].open=opening;changed=replace(plan,targets=targets)
            outcome=retest.execute_plan(r,changed,q[1].trade_date,q,s)
            self.assertEqual(outcome.outcome,expected);self.assertIsNone(outcome.actual_entry)

    def test_never_retested_is_censored_and_future_append_after_terminal_is_invariant(self):
        r,q,s,snap=fixture();q[1].high=175.
        first=self.evaluate(r,q,s,snap)
        q[-1].close=100.;q[-1].high=200.
        self.assertEqual(first,self.evaluate(r,q,s,snap))
        r,q,s,snap=fixture()
        for quote in q[1:]:quote.close=115.;quote.high=116.
        self.assertEqual(self.evaluate(r,q,s,snap)['B_reason'],'NEVER_RETESTED_RIGHT_CENSORED_DATASET_END')

    def test_checked_in_protocol_artifact_hash_controls_and_conservation(self):
        protocol=json.loads(retest.PROTOCOL.read_text(encoding='utf-8'));body=deepcopy(protocol)
        recorded=body['integrity']['protocol_sha256'];body['integrity']['protocol_sha256']=None
        self.assertEqual(recorded,retest.identity_hash(body))
        artifact=json.loads(Path(str(retest.OUTPUT)+'.json').read_text(encoding='utf-8'));body=deepcopy(artifact)
        recorded=body['integrity']['canonical_payload_sha256'];body['integrity']['canonical_payload_sha256']=None
        self.assertEqual(recorded,retest.identity_hash(body))
        c=artifact['conservation'];self.assertEqual(c['unique_confirmed_events'],999)
        self.assertEqual(c['executed_union']+c['not_executed'],999)
        self.assertEqual(c['A_B_overlap'],0);self.assertEqual(c['incumbent_increment_overlap'],0)
        self.assertEqual(artifact['parent_audit_classification'],'MIXED_ARCHITECTURE_SIGNAL_STARVATION')
        self.assertEqual(artifact['status'],retest.STATUS)
        for key in ('final_oos_accessed','parameter_search','production_semantics_changed','real_holdings_accessed','post_entry_outcomes_used'):
            self.assertFalse(artifact['controls'][key])
        for section in ('by_setup','by_market','by_time_half'):
            self.assertEqual(sum(row['confirmed'] for row in artifact[section].values()),999)


if __name__=='__main__':unittest.main()

<!-- DEVELOPMENT_ONLY; NO_FINAL_OOS; NO_PRODUCTION_RULE_CHANGE -->
# CN executable-opportunity scarcity: descriptive audit

Status: `READY_FOR_DECISION` for any **new** research. This audit does not authorize a trading rule change, Paper run, state write, or new dataset. It uses the user-supplied 2026-09-22/23 natural-run summaries and the already approved frozen Development artifacts: `research/development/system_signal_scarcity_audit_v1.{json,md}`, `research/development/post_confirmation_retest_entry_causal_research_v1.md`, and `research/development/pre_confirmation_early_entry_causal_research_v1.md`. The recent daily-report artifact JSON was not available in this workspace; the reported summaries are not a substitute for per-symbol records. No replay or Final OOS access was performed.

## Populations and funnel

The recent numbers are **daily stock/state counts**. WATCH and ARMED are contemporaneous observations, not successive subsets of that day's newly CONFIRMED events. `DATA_OK=516` is completed analysis coverage, not an identified Seed or Included count. Formal pool versus dynamic Candidate counts and identities were not supplied, so those stages remain unknown.

| CN live date | Seed | Included | DATA_OK | WATCH | ARMED | first CONFIRMED | formal plan | ENTRY_ALLOWED | T+1 EXECUTED for new events |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-22 | unknown | unknown | 516 | 42 | 25 | 1 | 0 | 0 | 0 possible |
| 2026-09-23 | unknown | unknown | 516 | 50 | 20 | 1 | 0 | 0 | 0 possible |

The 9/22 new confirmation's first Decision rejection was T1 gross upside below 5%; the 9/23 new confirmation's first rejection was T1 R/R below 2R. The provided summaries do not show the other gate diagnostics for either event, so overlap cannot be assigned for these two live events. `WATCH` means a structure worth observing; `ARMED` means close to its confirmation condition; first `CONFIRMED` is a new structural fact; only its as-of Decision can yield `ENTRY_ALLOWED`. The earlier stages cannot be promoted from presentation state to execution status. With no T-day plan, there is no corresponding T+1 execution attempt. Other pre-existing plans, if any, are outside these summaries.

The frozen Development audit is a **different 40-symbol, 2017–2026 sample**, without live Candidate selection or the current formal pool. It must not be interpreted as recent market frequency. Its units are causal setup lifecycles and first-entry events, not daily stock counts:

| frozen Development scope | symbol-sessions | setup lifecycles | lifecycles with WATCH | lifecycles with ARMED | first CONFIRMED / Decision | ENTRY_ALLOWED | exact T+1 EXECUTED |
|---|---:|---:|---:|---:|---:|---:|---:|
| CN SETUP_01 | 41,274 CN total | 670 | 329 | 236 | 299 | 0 | 0 |
| CN SETUP_02 | same CN sessions | 197 | 136 | 100 | 77 | 0 | 0 |
| CN total | 41,274 | 867 | 465 setup-lifecycle occurrences | 336 setup-lifecycle occurrences | 376 | 0 | 0 |
| US comparison | 45,031 | 1,183 | not added here | not added here | 623 | 8 | 4 |

WATCH/ARMED lifecycle occurrences are not a conserved linear funnel: 185 CN SETUP_01 and 33 SETUP_02 confirmations occurred without a previously counted ARMED lifecycle in this audit, and a lifecycle can occupy a state for multiple symbol-sessions. The conserved comparisons are 867 candidate lifecycles → 376 first confirmations → 376 Decisions → 0 `ENTRY_ALLOWED` for CN; all-market 2,050 → 999 → 8 → 4. The 516 live `DATA_OK` stocks cannot be aligned to the 20 frozen CN symbols.

## Attribution without double counting

CN Development first Decision rejection, one primary reason per 376 new confirmations:

| reason | SETUP_01 | SETUP_02 | CN total | fraction of CN confirmations |
|---|---:|---:|---:|---:|
| confirmation close above Entry Zone | 188 | 44 | 232 | 61.7% |
| T1 upside below 5% | 86 | 20 | 106 | 28.2% |
| T1 R/R below 2R | 25 | 8 | 33 | 8.8% |
| stale confirmation geometry | 0 | 4 | 4 | 1.1% |
| no valid T1 | 0 | 1 | 1 | 0.3% |

The rows sum to 376. They are **first failures**, not independent causal effects. Across both markets, the all-fail diagnostics found RR below minimum on 942 of 999 confirmations, target upside below minimum on 745, and above Entry Zone on 595. The intersections include RR ∩ target upside = 745 and above zone ∩ RR = 565. Thus adding these raw counts would greatly overstate distinct lost opportunities. All-market one-gate counterfactuals recovered 0 `ENTRY_ALLOWED` from removing only the 5% gate, 100 from removing only 2R, 14 from excluding confirmed-swing-high T1 provenance, and 6 from removing only Entry Zone. These are prohibited as production changes and are not performance evidence; they show where geometry overlaps. CN-specific all-fail overlaps and one-gate recovery were not published in the compact report, so no CN-specific increment is inferred.

The upstream 491 CN lifecycles that did not confirm are separate from the 376 Decision rejections. Development first-fail lifecycle reasons include structural invalidation, Wave/context replacement, daily/weekly state, and unconfirmed tails; the compact artifact does not supply a CN-specific mutually exclusive breakdown. The existing pre-confirmation causal study found 2,254 Wave2 anchor contexts across markets, 745 later confirmed, 947 failed, and 562 never confirmed. Earlier milestones gained headroom on matched later-confirmed cases but admitted many failed or never-confirmed contexts. This supports the interpretation that confirmation timing sacrifices price space **and** protects against false positives; it does not prove an earlier executable rule.

At T+1, the all-market Development sample had 8 plans and 4 executions; the other four were rejected at exact next-session OPEN (two below confirmation, one gap above Entry Zone, one insufficient R/R). CN had zero plans, so its historical T+1 execution friction cannot be estimated from this sample. The live 9/22 and 9/23 blockers were Decision economics, with no evidence of CN data blockage in the 516 `DATA_OK` rows; Candidate inclusion and formal-vs-dynamic quality remain unmeasured. Two daily observations are inadequate to attribute a market regime effect.

## Existing research boundaries

- `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1` is **closed** in `docs/DECISION_LOG.md`: 999 confirmed facts yielded only five additional executable retests, all in the EARLY half and only one CN. Do not rename and restart the same waiting policy without new independent evidence.
- `PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH_V1` is already registered and completed as Development-only. Its early policies gained 0.170–0.337 Wave1-R of paired median headroom, but many early cohorts failed or never confirmed. The report explicitly says execution/cost research is not yet cleared and no production policy is authorized.
- `ARMED_OPPORTUNITY_PROJECTION_V1` is a read-only explanatory estimate, never a plan; at confirmation the actual Decision recomputes zone and T1. `SETUP_01` already displays the nearest confirmed resistance and a separate farther Wave3 projection; the latter cannot replace T1 just to pass a gate.

## Distinct next research choices (maximum three)

**1. Fresh independent validation of an earlier structure.** Hypothesis: a pre-confirmation structural milestone can retain meaningful T1 space with acceptably bounded false positives across CN time periods and symbols. Candidate signal can only use already confirmed Swing/Wave anchors and that day's close/high; earliest execution is exact next-session OPEN, never same-bar or later substitution. Invalidation is the existing causal structural level, with a separately predeclared execution stop and unchanged 0.5% allocation-budget risk limit if the study ever reaches execution. Baseline: first-CONFIRMED incumbent on identical full anchor-context cohort, including eventual failures and censored contexts. Falsify if incremental headroom is absent out of sample, failure/adverse-excursion rate is materially worse, or benefit is concentrated by symbol/time. Needs a new independent, predeclared CN validation cohort and full false-positive/censoring accounting **before** cost or production testing. If advanced, model exact OPEN, A-share lot/board constraints, price limits, suspensions, fees, spread, and slippage. This is continuation of an existing hypothesis, not permission to search new milestones on the same Development set.

**2. T1/stop geometry provenance diagnosis.** Hypothesis: the nearest confirmed resistance and frozen structural stop sometimes encode the same narrow distance constraint twice, so current T1 R/R is economically unachievable even when the Wave3 projection is valid. The diagnostic signal is the first CONFIRMED T close; earliest possible trade remains exact T+1 OPEN. Invalidation, current T1, target-before-RR, 5%, and 2R remain fixed for the baseline. Compare predeclared causal obstacle/target provenance strata and stop-distance decomposition to the unchanged Decision; no farther T2/T3 substitution or retrofitted stop. Falsify if low R/R persists in independent CN data, the apparent overlap is explained by genuine near resistance, or any alternative geometry loses downside protection after realistic costs. Needs event-level T-known target candidates, confirmed swings, ATR, zone, structural stop, exact OPEN and market execution constraints; new target construction would require a separate frozen protocol and user authorization.

**3. Prospective universe and market-state attribution.** Hypothesis: formal-pool composition versus dynamic Candidate composition, and as-of weekly/daily market state, explain why broad DATA_OK coverage yields few confirmations. Signal is each completed T report's already-known Seed/Included/provenance and state; no trade is generated. The earliest *possible* execution for any later independent confirmed Decision is T+1 OPEN under unchanged invalidation/risk gates. Baseline: identical daily funnel measured separately by formal pool and dynamic Candidate, with fixed market-state strata and no outcome-based universe substitution. Falsify if the deficit is similar across strata or disappears when data-quality/missing-identity gaps are resolved. Needs several prospective exact-T CN reports with per-symbol provenance and first-fail fields, plus execution-cost/lot/limit/suspension assumptions before any strategy proposal. The present two daily summaries lack Seed/Included and provenance, so this is currently an observation plan, not a tested improvement.

## Decision requested

Choose **one** of: (A) authorize a new independent CN cohort and frozen protocol for existing early-entry hypothesis; (B) authorize a frozen, read-only geometry/provenance study without target or stop rule changes; or (C) continue collecting prospective exact-T funnel/provenance reports before selecting a structural hypothesis. For A or B, define the permitted development dataset and cost/market-execution assumptions before research starts. None authorizes Final OOS, threshold changes, Paper, or production writes.

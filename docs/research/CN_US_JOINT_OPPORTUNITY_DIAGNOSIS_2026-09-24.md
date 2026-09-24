<!-- READ_ONLY_ATTRIBUTION; DEVELOPMENT_EVIDENCE_SEPARATE_FROM_LIVE; NO_NEW_VALIDATION -->
# CN/US executable opportunity diagnosis and validation decision draft

Status: `READY_FOR_DECISION` for any new independent research. This document uses the existing frozen Development reports, the 2026-09-22/23 natural-run summaries already recorded in PR #102 and the US incident report in PR #101. It does not run a new replay, use Final OOS, change trading rules, or treat a data repair as evidence of edge.

## Evidence layers and units

1. **Recent production observation** describes the current market, current universe and exact-session coverage. The available CN summaries are two daily aggregate snapshots. The available US 9/23 incident summary has Candidate seed and data-quality counts, but no per-symbol strategy funnel or raw report JSON in this workspace. These summaries do not support a formal-pool versus dynamic-Candidate strategy comparison.
2. **Frozen Development** is the fixed 40-symbol (20 CN, 20 US), 2017–2026 Phase 5J-v3 holdout: 86,305 symbol-sessions (41,274 CN; 45,031 US). `system_signal_scarcity_audit_v1` replays SETUP_01/02 using first causal terminal events. This is neither today's market nor a sample of today's formal pool or live dynamic Candidate selection.
3. **New independent validation** has not been authorized, frozen or run. All choices below are protocol proposals, not findings.

`Seed → Included → DATA_OK` is a universe/data chain. `WATCH` and `ARMED` are states observed on a day or over a lifecycle; neither is a same-day linear predecessor of a first `CONFIRMED` event. The conserved event chain is first `CONFIRMED → Decision → ENTRY_ALLOWED → exact T+1 attempt → EXECUTED`. Count unique `(market, symbol, setup, first-confirmation date, lifecycle)` events once. A symbol in the formal pool and dynamic discovery must retain both provenance flags and one event identity, with mutually exclusive reporting buckets for formal-only, dynamic-only and overlap. Dynamic-only remains read-only discovery and cannot be counted as a formal production proposal.

## Recent production diagnostic view

| Market / T / source | Seed | Included | DATA_OK | WATCH | ARMED | first CONFIRMED | Decision / first rejection | ENTRY_ALLOWED | T+1 EXECUTED |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| CN 2026-09-22, reported aggregate | unknown | unknown | 516 | 42 | 25 | 1 | 1; T1 upside <5% | 0 | 0 possible from this event |
| CN 2026-09-23, reported aggregate | unknown | unknown | 516 | 50 | 20 | 1 | 1; T1 R/R <2R | 0 | 0 possible from this event |
| US 2026-09-23, dynamic Candidate data stage | 1,023 | unknown; 1 usable Stage A history | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| US 2026-09-23, formal writer / report | formal count unknown | not applicable | BABA/RKLB QFQ T-1; formal QFQ 0 updated | unknown | unknown | unknown | unknown | unknown | unknown |

CN daily summaries do not carry formal versus dynamic identities, setup splits or per-event geometry. US Candidate had 1,022 `HISTORY_INSUFFICIENT` exclusions in the saved incident summary; the exact causal share of the 60-session window defect is unproven. The US writer's four latest rows were pending and the formal QFQ update was zero. These data failures invalidate a recent US strategy-frequency estimate; they do **not** erase the independent frozen Development scarcity evidence. The recent CN Decision blockers are observed, but two days cannot establish a stable market effect. For every missing formal/dynamic/date/setup cell above, report `unknown`, not zero.

For the next natural reports, preserve one row per `(market, T, provenance bucket, setup)` with distinct `Seed`, `Included`, `DATA_OK`, daily `WATCH`, daily `ARMED`, first `CONFIRMED`, Decision, `ENTRY_ALLOWED`, exact T+1 attempt and `EXECUTED`. Attach event identity, actual confirmation close, Entry Zone bounds, nearest valid T1 and provenance, structural invalidation, execution stop, gross T1 upside, T-day R/R, primary rejection and all-fail set. The current compact reports do not contain enough event-level facts to fill those fields retrospectively. No dynamic-only record is promoted to the formal pool by this observation.

## Frozen Development funnel: CN and US together

These rows count setup lifecycles; WATCH/ARMED are numbers of lifecycles ever visiting those states and are not additive across rows. Symbol-sessions are market denominators, repeated for each setup only for context.

| Market / setup | Symbol-sessions | Lifecycles | ever WATCH | ever ARMED | first CONFIRMED = Decisions | ENTRY_ALLOWED | exact T+1 EXECUTED |
|---|---:|---:|---:|---:|---:|---:|---:|
| CN / SETUP_01 | 41,274 | 670 | 329 | 236 | 299 | 0 | 0 |
| CN / SETUP_02 | same CN sessions | 197 | 136 | 100 | 77 | 0 | 0 |
| CN / both setups | 41,274 | 867 | 465 setup occurrences | 336 setup occurrences | 376 | 0 | 0 |
| US / SETUP_01 | 45,031 | 833 | 351 | 330 | 446 | 5 | 4 |
| US / SETUP_02 | same US sessions | 350 | 188 | 196 | 177 | 3 | 0 |
| US / both setups | 45,031 | 1,183 | 539 setup occurrences | 526 setup occurrences | 623 | 8 | 4 |

The US WATCH/ARMED cells are derived from the frozen JSON's market/setup lifecycle counts; they are lifecycle occurrences, not distinct stock-days. The 376/0 and 623/8 figures come from `system_signal_scarcity_audit_v1`'s frozen first-confirmation Decision population, not from 2026 production reports. Its four US `EXECUTED` outcomes mean only that the mechanical exact-next-session OPEN passed the existing executor: five US SETUP_01 plans produced four executions; three US SETUP_02 plans produced none. Of the other four US attempts, two opened below confirmation, one gapped above Entry Zone and one failed open-time R/R. No broker fills, costs, P&L or return distribution were measured by this audit.

## Confirmation geometry, first failure and overlapping conditions

At T close, the incumbent uses the actual confirmation price against the frozen Entry Zone, selects the nearest *valid* causal T1 before testing gross upside >=5%, and uses the execution stop for R/R >=2R while preserving structural invalidation separately. The geometry diagnosis must display `confirmation close`, `zone low/high`, `T1 price/source`, `structural invalidation`, `execution stop`, `T1 minus price`, `stop distance` and `T1 reward / execution risk` on the same as-of event. The compact audit does not publish these per-event price tuples; it supports only the aggregate attribution below. Reconstructing per-event tuples from the already frozen input would be a separate read-only computation under an approved scope, not evidence already obtained.

| First failed gate on first CONFIRMED Decision | CN SETUP_01 | CN SETUP_02 | CN total | US SETUP_01 | US SETUP_02 | US total |
|---|---:|---:|---:|---:|---:|---:|
| Above Entry Zone | 188 | 44 | 232 | 276 | 87 | 363 |
| T1 upside <5% | 86 | 20 | 106 | 112 | 59 | 171 |
| T1 R/R <2R | 25 | 8 | 33 | 53 | 14 | 67 |
| Stale confirmation geometry | 0 | 4 | 4 | 0 | 10 | 10 |
| No valid T1 | 0 | 1 | 1 | 0 | 4 | 4 |
| `ENTRY_ALLOWED` | 0 | 0 | 0 | 5 | 3 | 8 |

First-fail rows are mutually exclusive within a Decision, summing to 376 CN and 623 US. The *all-fail* set is different: across 991 rejected Decisions, R/R fails in 942, upside in 745, and above-zone in 595. Upside ∩ R/R is 745; above-zone ∩ R/R is 565; above-zone ∩ upside is 468. Thus a first-fail label is not a single-cause removal estimate, and these overlapping counts must not be added. The published compact overlap matrix is aggregate CN+US, not market-specific; no CN/US overlap split is claimed. Single-gate counterfactuals recover +0 plans when only 5% is removed, +100 when only 2R is removed (CN 33, US 67), +14 when confirmed-swing-high T1 provenance alone is excluded (CN 7, US 7), and +6 when Entry Zone alone is removed (CN 0, US 6). These are diagnostic perturbations, not candidate production rules or return estimates.

Earlier SETUP_01 geometry work found 198 of 745 first confirmations with formal T1 upside <5%; 117 were near confirmed-swing resistance only, 63 had both near resistance and near Wave3 Fib, and 18 had a small-wave near Fib alone. It also found that deep retracement and smaller Wave1 scale compress Fib headroom; confirmation extension was not the main independent factor in the 81 Fib-near events. This is a SETUP_01 Development subgroup, not a CN/US split or proof that a farther Fib target can replace the current nearest T1. Stop-distance and open-time gap decomposition still need event-level paired evidence.

## Shared and distinct scarcity mechanisms

Both markets lose many potential contexts before confirmation and nearly all confirmed events at Decision. The frozen first failures are dominated by confirmation price beyond Entry Zone, nearest T1 upside and T1 R/R, with strong overlap; a single gate change is not a validated cure. CN has no frozen `ENTRY_ALLOWED` or T+1 attempts, so its execution friction and return distribution cannot be estimated here. US has eight plans but only four mechanical open-time executions, showing a further execution-stage loss. Recent US exact-T and Stage A coverage failures add a current operational bottleneck; recent CN summaries with 516 DATA_OK and two economic Decision rejections suggest a different immediate bottleneck. Formal-pool versus dynamic-Candidate opportunity rates and current market-state effects remain unknown in both markets because identity-level live records were unavailable.

The existing pre-confirmation study used a common 2,254 Wave2-context cohort (1,008 CN; 1,246 US). Only 745 later confirmed; 947 failed and 562 never confirmed. Earlier fixed milestones improved median paired headroom by 0.170–0.337 Wave1-R among later-confirmed matches, while admitting substantial failed and never-confirmed populations. That paired subset cannot establish net executable opportunity or profitability. The confirmed→wait-for-retest study is closed: five additional mechanical executions, CN 1 / US 4, all in its EARLY half, without broad or time-stable recovery. Do not rerun that waiting policy on the same Development set. SETUP_03 structural Development is stopped without formal validation or a production tolerance; SETUP_04 is unimplemented. Neither can be assumed to add formal opportunity.

## Unified independent validation proposal for user decision

**Common population and causal clock.** Freeze a new CN and US universe and disjoint date span before reading signals or outcomes, with explicit formal versus dynamic provenance and market-state strata. Use every eligible Wave2 anchor context as the shared denominator for incumbent first-confirmation and the already defined early milestones; retain failures, never-confirmed and right-censored contexts. For the geometry-only branch, use every first-confirmed SETUP_01/02 event in the same frozen population, with its causal T-close price, Zone, nearest valid T1, structural invalidation, execution stop, and all-fail set. Count a setup lifecycle once and report market/setup/provenance/date strata without selecting symbols from results. Prevent context leakage across development/validation time and symbols as predeclared.

**Comparators.** A: unchanged first-CONFIRMED close, unchanged 5%, 2R and exact T+1 OPEN. B: one already registered pre-confirmation milestone, selected *before* independent data access, with its own predeclared causal stop and risk treatment; compare on the same full anchor cohort, not just eventual winners. C: unchanged A plus read-only target/stop/zone provenance and distance decomposition, with no target substitution or threshold selection. If B is not selected, compare A and C descriptively only. The study should predeclare whether CN and US share one policy or require separate decisions; do not infer market-specific parameters from this Development sample.

**Execution and outcome contract.** T signals use data <= T; entries can use only exact T+1 OPEN, with missing session/open reported as a failure rather than shifted to T+2. Include no-signal, failed, never-confirmed, censored, price-limit/suspension and gap cases. Predeclare CN board/lot/limit and US share/notional feasibility, spread, commissions, taxes where applicable, slippage and FX treatment. Preserve the current 0.5% individual-risk and portfolio-risk semantics for incumbent assessment; any alternative stop or position-sizing rule needs explicit approval and a new frozen protocol. Report gross and net executable count per 1,000 common contexts and per market-session, confirmation-to-plan and plan-to-open attrition, realized R distribution, expectancy with uncertainty, win/loss, max drawdown and concentration by market/setup/provenance/time, including skipped and unconfirmed cohorts. Prevent same-bar high/low path assumptions from manufacturing fills or exits. Predeclare minimum coverage, economic success/failure bounds, multiple-comparison handling and stop conditions before the independent sample is opened.

**Decision required.** Choose (1) observation-only prospective exact-T provenance capture across both markets; (2) freeze a new CN/US independent validation protocol and sample for one existing early milestone versus incumbent; or (3) freeze a read-only CN/US geometry/provenance protocol first. For (2) or (3), approve the permissible independent sample, timeframe, universe, data provider/QC and cost/market-execution assumptions. No branch here authorizes Final OOS, Paper, trading, production state/Sheet writes, a retest restart, or a change to formal Wave/Setup/Entry/Target/Risk/T→T+1 rules.

## Source map

- `research/development/system_signal_scarcity_audit_v1.{json,md}`: frozen denominators, funnel, first-fail, all-fail overlap, one-gate counterfactual and exact-open outcomes.
- `research/development/pre_confirmation_early_entry_causal_research_v1.md`: common anchor cohort, matched headroom and failed/never-confirmed early contexts.
- `research/development/post_confirmation_retest_entry_causal_research_v1.md`: closed retest result.
- `research/development/setup01_wave2_to_wave3_geometry_attribution_v1.md`: SETUP_01 T1/Fib subgroup geometry.
- PR #101 `docs/US_DATA_QUALITY_2026-09-23.md`: recent US operational incident and acceptance boundary.
- PR #102 `docs/research/CN_OPPORTUNITY_SCARCITY_2026-09-23.md`: recent CN summaries and CN-only read-only attribution.

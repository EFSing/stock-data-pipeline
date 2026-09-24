# SETUP_01 earlier-entry independent validation V1 — first stage

> Independent-sample research only. No production entry rule, confirmation, target, stop, RR, state, Sheets, or broker behavior is changed. No execution cost, net return, win rate or Final OOS is touched.

- Protocol: `SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1`
- Status: `FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`
- Sample: `SETUP01-EARLY-ENTRY-INDEPENDENT-VALIDATION-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-09-24-v1`
- Symbols / bars: `40` / `88075`
- Experimental group / comparator: `ARMED_HALF_RECOVERY` / `INCUMBENT_CONFIRMED_CLOSE`
- Setup scope: SETUP_01 (Wave 2 -> Wave 3) Wave2 anchor contexts only

## Sample provenance and independence

- Universe manifest: `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b` / symbol list `sha256:a00cdd73e6976546df43ea92a6e5e48f64124af974ff20c7812ee6c350399e58`
- Replay aggregate: `sha256:2500398be662fa2bd894aa4e3d538e9f3c6a04f0a291ece8ff85dfb5164aa4e7`
- Payload re-acquisition check vs the 2026-08-29 clean-holdout acquisition: `PAYLOAD_DIFFERS_FROM_FROZEN_CLEAN_HOLDOUT` (22/40 identical adjusted series, identical session coverage and bar counts for all 40 symbols)
- The frozen roster proves empty intersections with the A1 formal 120, the earlier development universe v1 and the Development holdout used by the pre-confirmation research, so no symbol and no lifecycle identity is shared with the exposed Development data.
- The calendar window matches the frozen Development window: independence is by symbol and lifecycle only, and market-regime overlap remains a disclosed limitation.

## Cohort and coverage

| item | count |
|---|---:|
| anchor contexts | 2291 |
| later CONFIRMED | 790 |
| FAILED | 942 |
| never CONFIRMED | 559 |
| screened out by the current system | 551 |
| timeout/unresolved at data end | 8 |
| invalid Wave2 geometry retained/screened | 14 |
| CN / US symbols accepted | 20 / 20 |

## Common-denominator comparison

| market | anchor contexts | early signaled | early executable | later CONFIRMED | FAILED | never CONFIRMED | invalidation share | confirmed share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CN | 1081 | 462 | 461 | 153 | 139 | 170 | 0.204 | 0.332 |
| US | 1210 | 525 | 525 | 176 | 151 | 198 | 0.234 | 0.335 |

## Paired price space versus the incumbent

Positive gain means the earlier entry obtained a lower exact next-session OPEN than the incumbent on the same lifecycle, normalized by Wave1 `R`.

An earlier trigger is structurally expected to pay a lower price, so this table is not by itself evidence of edge; the discriminating evidence is the failure, non-confirmation and censoring side below.

| market | paired | paired later CONFIRMED | positive share | median gain/R | sign-test p |
|---|---:|---:|---:|---:|---:|
| CN | 153 | 153 | 0.980 | 0.275 | 2.05e-40 |
| US | 175 | 175 | 0.960 | 0.238 | 3.85e-41 |

## Adverse excursion and censoring

| market | adverse median/R | adverse P90/R | censored executable paths |
|---|---:|---:|---:|
| CN | 0.227 | 0.661 | 169 |
| US | 0.215 | 0.667 | 198 |

## Descriptive strata (experimental group)

All stratum rows stay on the same anchor-context denominator; strata are descriptive and carry no separate decision gate.

| stratum | anchor contexts | early signaled | executable | later CONFIRMED | FAILED | never CONFIRMED |
|---|---:|---:|---:|---:|---:|---:|
| time:FIRST_HALF | 1136 | 496 | 496 | 182 | 135 | 179 |
| time:SECOND_HALF | 1155 | 491 | 490 | 147 | 155 | 189 |
| depth:NORMAL_OR_SHALLOW | 1047 | 465 | 465 | 150 | 136 | 179 |
| depth:DEEP | 579 | 247 | 246 | 79 | 77 | 91 |
| depth:VERY_DEEP | 651 | 275 | 275 | 100 | 77 | 98 |

Count-leading symbol by early signal count: `NXPI` (40 signals); the JSON retains the same strata for the incumbent comparator.

## Hurdle reach and adverse cost (both groups)

| policy | H1+0.272R reached | H1+0.618R reached | censored paths | adverse magnitude median/R | adverse magnitude P90/R |
|---|---:|---:|---:|---:|---:|
| ARMED_HALF_RECOVERY | 449 (0.455) | 313 (0.317) | 367 | 0.219 | 0.665 |
| INCUMBENT_CONFIRMED_CLOSE | 712 (0.902) | 608 (0.771) | 200 | 0.972 | 1.904 |

## Pre-registered decision

Overall: **FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION**

| market | classification | failed floors | failed gates |
|---|---|---|---|
| CN | FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION | — | — |
| US | FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION | — | — |

- Supports applying for a stage-2 execution-cost / net-return study: `true`
- Production authorization: `false`

Both markets met the pre-registered space, invalidation and confirmation gates; this supports applying for a separate execution-cost/net-return stage and authorizes no production policy. CN: FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION (cohort 1081, executable early signals 461, paired later-CONFIRMED 153, median paired gain 0.275 R, sign-test p 2.05e-40, invalidation share 0.204, confirmed share 0.332; failed floors none; failed gates none); US: FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION (cohort 1210, executable early signals 525, paired later-CONFIRMED 175, median paired gain 0.238 R, sign-test p 3.85e-41, invalidation share 0.234, confirmed share 0.335; failed floors none; failed gates none).

## Boundaries

- Independent sample by symbol and lifecycle; the calendar window matches the frozen Development window, so market-regime overlap is a disclosed limitation and not a controlled factor.
- Coercion-free controls: no same-bar fill, no later-bar substitution, no symbol replacement, no provider switch after the roster freeze, no parameter or milestone search.
- Not in scope: execution cost, net return, win rate, expectancy, portfolio allocation, new Stop/Target/Entry/5%/2R/position rules, Paper, production state, Sheets, broker and Final OOS.

Status: `FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`

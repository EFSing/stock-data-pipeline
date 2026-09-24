# SETUP_01 earlier-entry independent validation V1 — first stage

> Independent-sample research only. No production entry rule, confirmation, target, stop, RR, state, Sheets, or broker behavior is changed. No execution cost, net return, win rate or Final OOS is touched.

- Protocol: `SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1`
- Status: `FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`
- Sample: `SETUP01-EARLY-ENTRY-INDEPENDENT-VALIDATION-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-09-24-v1`
- Symbols / bars: `40` / `88075`
- Experimental group / comparator: `ARMED_HALF_RECOVERY` / `INCUMBENT_CONFIRMED_CLOSE`

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

| market | paired | paired later CONFIRMED | positive share | median gain/R | sign-test p |
|---|---:|---:|---:|---:|---:|
| CN | 153 | 153 | 0.980 | 0.275 | 0.0000 |
| US | 175 | 175 | 0.960 | 0.238 | 0.0000 |

## Adverse excursion and censoring

| market | adverse median/R | adverse P90/R | censored executable paths |
|---|---:|---:|---:|
| CN | 0.227 | 0.661 | 169 |
| US | 0.215 | 0.667 | 198 |

## Pre-registered decision

Overall: **FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION**

| market | classification | failed floors | failed gates |
|---|---|---|---|
| CN | FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION | — | — |
| US | FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION | — | — |

- Supports applying for a stage-2 execution-cost / net-return study: `true`
- Production authorization: `false`

Both markets met the pre-registered space, invalidation and confirmation gates; this supports applying for a separate execution-cost/net-return stage and authorizes no production policy. CN: FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION (cohort 1081, executable early signals 461, paired later-CONFIRMED 153, median paired gain 0.275 R, sign-test p 0.0000, invalidation share 0.204, confirmed share 0.332; failed floors none; failed gates none); US: FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION (cohort 1210, executable early signals 525, paired later-CONFIRMED 175, median paired gain 0.238 R, sign-test p 0.0000, invalidation share 0.234, confirmed share 0.335; failed floors none; failed gates none).

## Boundaries

- Independent sample by symbol and lifecycle; the calendar window matches the frozen Development window, so market-regime overlap is a disclosed limitation and not a controlled factor.
- Coercion-free controls: no same-bar fill, no later-bar substitution, no symbol replacement, no provider switch after the roster freeze, no parameter or milestone search.
- Not in scope: execution cost, net return, win rate, expectancy, portfolio allocation, new Stop/Target/Entry/5%/2R/position rules, Paper, production state, Sheets, broker and Final OOS.

Status: `FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`

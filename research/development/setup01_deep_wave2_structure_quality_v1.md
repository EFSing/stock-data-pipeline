# SETUP_01 Deep Wave2 Structure Quality V1

> Development research only. This report does not propose or implement a Wave2 depth gate or an early-entry rule.

## Research question and fixed protocol

This study asks whether a deep Wave2 mainly indicates weaker Wave2→Wave3 structure, or whether the existing breakout confirmation / planned-entry geometry consumes most of the projected Wave3 space.

- Protocol: `SETUP-01-DEEP-WAVE2-STRUCTURE-QUALITY-2026-09-16-v1`; scope: `745` existing SETUP_01 CONFIRMED events.
- Frozen session identity: `FROZEN_DATASET_MARKET_SESSION_SET`; bands are fixed at `r ≤ 0.618`, `0.618 < r ≤ 0.786`, and `r > 0.786`.
- Primary structure outcome starts strictly after T. Target high and structural/scenario invalidation close use the existing contracts. Same future-bar target/invalidation is ambiguous; execution stop-first is not reused.
- The 81-event Fib-near sample is the exact PR #86 category binding `SMALL_WAVE_FIB + BOTH_NEAR`, not a result-selected reclassification.

## Frozen binding and controls

- Rebuilt confirmed events: **745**; PR #86 bound count: **745**.
- PR #86 category conservation: `NEAR_SWING_ONLY=117`, `SMALL_WAVE_FIB=18`, `BOTH_NEAR=63`; Fib-near = **81**.
- Fib identity max residual: `1.137e-13`; passed = `True`.
- Final OOS: not accessed. Parameter search: false. Threshold sweep: false. Production Decision/parameters: unchanged. State/Sheets writes and broker orders: 0.

## Pure geometry decomposition

`pre_confirmation_consumption` is the fraction of the projected Wave3 length consumed by the retracement before re-breaking Wave1 high. `post_confirmation_headroom_over_R` is the remaining normalized space after the T-day planned-entry extension.

| depth band | N | r P25 / median / P75 | Wave1 gain median | Wave1 / ATR14 median | pre-consumption 1.272 median | pre-consumption 1.618 median | post-headroom 1.272 median | post-headroom 1.618 median | Fib1.272 upside <5% | Fib1.618 upside <5% |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NORMAL_OR_SHALLOW | 345 | 0.366 / 0.455 / 0.533 | 20.8% | 5.199 | 35.8% | 28.1% | 0.631R | 0.977R | 96 (27.8%) | 56 (16.2%) |
| DEEP | 183 | 0.656 / 0.698 / 0.742 | 14.0% | 3.671 | 54.9% | 43.2% | 0.371R | 0.717R | 114 (62.3%) | 60 (32.8%) |
| VERY_DEEP | 217 | 0.836 / 0.893 / 0.939 | 11.3% | 3.081 | 70.2% | 55.2% | 0.170R | 0.516R | 183 (84.3%) | 122 (56.2%) |

## Structural continuation by fixed depth band

| depth band | N | 1.272 before structural invalidation | structural invalidation first | ambiguous | censored | Fib1.618 before invalidation | median sessions to 1.272 | median sessions to invalidation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NORMAL_OR_SHALLOW | 345 | 225 (65.2%) | 117 (33.9%) | 0 | 3 | 196 (56.8%) | 25.0 | 57.0 |
| DEEP | 183 | 147 (80.3%) | 36 (19.7%) | 0 | 0 | 132 (72.1%) | 3.5 | 56.5 |
| VERY_DEEP | 217 | 195 (89.9%) | 20 (9.2%) | 0 | 2 | 169 (77.9%) | 1.0 | 52.0 |

Scenario invalidation is tracked separately. Under the existing close-based contract, Wave1 origin is below Wave2 low, so a distinct scenario-before-structural ordering is not expected; same-date relations remain visible in the JSON.

## Structure quality × entry geometry

The binary structure dimension is `FIB1272_BEFORE_STRUCTURAL_INVALIDATION` versus `STRUCTURAL_INVALIDATION_BEFORE_FIB1272`; ambiguous/censored rows remain outside the binary cells and are reported separately.

| depth band | success + headroom ≥5% | success + headroom <5% | failure + headroom ≥5% | failure + headroom <5% | unresolved |
|---|---:|---:|---:|---:|---:|
| NORMAL_OR_SHALLOW | 139 | 86 | 108 | 9 | 3 |
| DEEP | 44 | 103 | 25 | 11 | 0 |
| VERY_DEEP | 25 | 170 | 9 | 11 | 2 |

### Fixed 81-event Fib-near sample

- N = **81**; category mix: `{'BOTH_NEAR': 63, 'SMALL_WAVE_FIB': 18}`; VERY_DEEP = **55**.
- Strictly after T: **64** reached Fib1.272 before structural invalidation (79.0%); headroom <5% = **81**, headroom ≥5% = **0**.
- Strict outcomes: `{'FIB1272_BEFORE_STRUCTURAL_INVALIDATION': {'count': 64, 'rate': 0.7901234567901234}, 'STRUCTURAL_INVALIDATION_BEFORE_FIB1272': {'count': 16, 'rate': 0.19753086419753085}, 'SAME_BAR_AMBIGUOUS': {'count': 0, 'rate': 0.0}, 'CENSORED_INSUFFICIENT_PATH': {'count': 1, 'rate': 0.012345679012345678}}`. T-bar target crossings are not credited to this post-T continuation count.

## Existing production Decision funnel

These are the existing production Decision and exact T+1 OPEN classifications, grouped by the research-only depth bands. They are secondary context and are not used to relabel structural outcomes.

| depth band | CONFIRMED | ABOVE_ENTRY_ZONE | TARGET_UPSIDE_BELOW_MINIMUM | RR_BELOW_MINIMUM | ENTRY_ALLOWED | T+1 EXECUTED | already excluded by T-day gates |
|---|---:|---:|---:|---:|---:|---:|---:|
| NORMAL_OR_SHALLOW | 345 | 222 | 75 | 43 | 5 | 4 | 340 (98.6%) |
| DEEP | 183 | 109 | 51 | 23 | 0 | 0 | 183 (100.0%) |
| VERY_DEEP | 217 | 133 | 72 | 12 | 0 | 0 | 217 (100.0%) |

VERY_DEEP has `0` ENTRY_ALLOWED and `0` EXECUTED rows in this development funnel; a new depth gate would therefore have no incremental effect on this sample after the existing gates.

## Robustness

### CN / US

| market | depth band | N | structural success rate | Fib1.618 before invalidation rate |
|---|---|---:|---:|---:|
| CN | NORMAL_OR_SHALLOW | 130 | 62.3% | 54.6% |
| CN | DEEP | 76 | 76.3% | 72.4% |
| CN | VERY_DEEP | 93 | 89.2% | 73.1% |
| US | NORMAL_OR_SHALLOW | 215 | 67.0% | 58.1% |
| US | DEEP | 107 | 83.2% | 72.0% |
| US | VERY_DEEP | 124 | 90.3% | 81.5% |

### Development time halves

Split definition: Within each market, frozen market-session ordinal midpoint; aggregate by half after the split. Cutoffs: `{'CN': '2021-10-29', 'US': '2021-10-26'}`.

| half | depth band | N | structural success rate |
|---|---|---:|---:|
| FIRST_HALF | NORMAL_OR_SHALLOW | 200 | 67.5% |
| FIRST_HALF | DEEP | 94 | 79.8% |
| FIRST_HALF | VERY_DEEP | 112 | 92.9% |
| SECOND_HALF | NORMAL_OR_SHALLOW | 145 | 62.1% |
| SECOND_HALF | DEEP | 89 | 80.9% |
| SECOND_HALF | VERY_DEEP | 105 | 86.7% |

### Symbol concentration

| depth band | symbol count | top-5 event share | max symbol share | HHI | success rate excluding top symbol |
|---|---:|---:|---:|---:|---:|
| NORMAL_OR_SHALLOW | 39 | 22.6% | 4.6% | 0.0316 | 65.3% |
| DEEP | 39 | 26.8% | 6.6% | 0.0334 | 80.1% |
| VERY_DEEP | 39 | 22.1% | 5.5% | 0.0309 | 89.3% |

## Secondary executed-performance context

This section is not the primary test, is not a random control, and is not evidence for selecting a depth rule. Executed samples are especially small.

| depth band | executed | closed | open/censored | gross expectancy R | win rate | profit factor | stop-out |
|---|---:|---:|---:|---:|---:|---:|---:|
| NORMAL_OR_SHALLOW | 4 | 4 | 0 | -0.865 | 25.0% | 0.006 | 2 (50.0%) |
| DEEP | 0 | 0 | 0 | — | — | — | 0 (—) |
| VERY_DEEP | 0 | 0 | 0 | — | — | — | 0 (—) |

## Evidence judgment

**EARLY_ENTRY_RESEARCH_CANDIDATE**

Strict post-T structural continuation is not worse in DEEP/VERY_DEEP than in NORMAL_OR_SHALLOW (65.2% vs 80.3% / 89.9%). In the fixed 81-event Fib-near sample, 64/81 still reached Fib1.272 before structural invalidation, including 55 VERY_DEEP events, while headroom was below 5% by construction. This supports prioritizing a separate early-entry causal study over deleting deep Wave2 contexts. At the same time, existing T-day gates already exclude all 217 VERY_DEEP events from ENTRY_ALLOWED in this development funnel, so a new depth gate would be redundant here; no production change is authorized by this result.

This is a research prioritization signal only. It does not change Wave2 eligibility, confirmation, Entry Zone, Stop, Target, R/R, production Decision, or execution. Any early-entry work would require a separate causal research protocol; the current study does not create an early-entry rule.

## Controls

- Final OOS access: `false`
- Parameter search: `false`; threshold sweep: `false`
- Production strategy / Decision modified: `false`
- Production/state/Sheets writes: `0`; broker orders: `0`
- PR #82 mixed in: `false`

Status: `READY_FOR_DECISION`.

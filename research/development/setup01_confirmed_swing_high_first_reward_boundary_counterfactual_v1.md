# SETUP_01 CONFIRMED_SWING_HIGH first-reward boundary counterfactual V1

Decision classification: **INSUFFICIENT_EVIDENCE**

The fixed NEAR_SWING_ONLY run produced 6 executed P1 research rows: 5 cleared the overhead Swing High before a stop and 1 cleared it before terminal without a stop, 1 reached the research Fib T1, and 5 stopped out. The executed sample is small, the positive gross R is concentrated in one symbol, and CN/US and time-half results diverge. That is not stable evidence either to retain the Swing High as a protective hard boundary or to remove it as a universally removable boundary; no conditioning variable or distance threshold is searched in this run.

## Scope and controls

- Policy comparison: `P0_CURRENT` vs `P1_FIB_FORMAL_T1_RESEARCH_ONLY`.
- Frozen dataset: `SETUP_03-DEVELOPMENT-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1`; 40 symbols / 86305 bars.
- Sample conservation: NEAR_SWING_ONLY=117, BOTH_NEAR=63, SMALL_WAVE_FIB=18.
- On the fixed 117-event sample, P0 has 0 ENTRY_ALLOWED rows and 117 target-upside rejections.
- All P1 performance is GROSS, without a transaction-cost model.
- Final OOS, provider access, production/state/Sheets/broker writes, parameter search, and threshold sweep: none.

## P0 baseline

```json
{
  "confirmed_events": 745,
  "decision_rows": 745,
  "decision_calculable": 745,
  "entry_allowed": 5,
  "no_trade": 740,
  "t1_execution_attempts": 5,
  "executed": 4,
  "decision_gate_reason_counts": {
    "ABOVE_ENTRY_ZONE": 464,
    "ENTRY_ALLOWED": 5,
    "RR_BELOW_MINIMUM": 78,
    "TARGET_UPSIDE_BELOW_MINIMUM": 198
  },
  "execution_outcome_counts": {
    "EXECUTED": 4,
    "SKIP_GAP_BELOW_CONFIRMATION": 1
  },
  "ignored_non_confirmed_event_count": 659,
  "duplicate_event_count": 0,
  "prior_geometry_parity": {
    "event_count": 745,
    "gate_action_target_parity": true,
    "mismatch_count": 0,
    "mismatches": []
  },
  "p0_output_unchanged_after_p1_derivation": true
}
```

## P1 research funnel

```json
{
  "stages": {
    "fixed_sample": 117,
    "fib_t1_available": 117,
    "fib_t1_upside_ge_5": 117,
    "rr_ge_2": 11,
    "entry_allowed_research": 11,
    "exact_t_plus_1_open_eligible": 11,
    "executed_research": 6
  },
  "stage_exclusion_reasons": {
    "executed_research": {
      "SKIP_GAP_ABOVE_ENTRY_ZONE": 2,
      "SKIP_GAP_BELOW_CONFIRMATION": 2,
      "SKIP_RR_BELOW_MINIMUM_AT_OPEN": 1
    },
    "rr_ge_2": {
      "RR_BELOW_MINIMUM": 106
    }
  },
  "research_entry_execution_outcome_counts": {
    "EXECUTED": 6,
    "SKIP_GAP_ABOVE_ENTRY_ZONE": 2,
    "SKIP_GAP_BELOW_CONFIRMATION": 2,
    "SKIP_RR_BELOW_MINIMUM_AT_OPEN": 1
  },
  "terminal_outcome_distribution": {
    "CLOSED_EXIT_STOP_TRIGGERED": 5,
    "CLOSED_STRUCTURAL_EXIT_PENDING": 1
  }
}
```

## P1 obstacle behavior

```json
{
  "executed_with_overhead_obstacle": 6,
  "gap_above_obstacle_at_entry_count": 0,
  "gap_above_obstacle_at_entry_rate": 0.0,
  "non_gap_obstacle_path_denominator": 6,
  "obstacle_clear_before_stop_count": 5,
  "obstacle_clear_before_stop_rate_non_gap": 0.8333333333333334,
  "obstacle_clear_before_terminal_without_stop_count": 1,
  "obstacle_clear_before_terminal_without_stop_rate_non_gap": 0.16666666666666666,
  "obstacle_clear_before_stop_or_terminal_count": 6,
  "obstacle_clear_before_stop_or_terminal_rate_non_gap": 1.0,
  "stop_before_obstacle_clear_count": 0,
  "stop_before_obstacle_clear_rate_non_gap": 0.0,
  "ambiguous_count_non_gap": 0,
  "ambiguous_rate_non_gap": 0.0,
  "same_bar_stop_first_conservative_count": 0,
  "same_bar_stop_first_contract": "PositionReplay excludes exit-day high when stop exits first",
  "path_status_counts": {
    "CLEARED_BEFORE_STOP": 5,
    "CLEARED_BEFORE_TERMINAL_WITHOUT_STOP": 1
  }
}
```

## P1 Fib target and gross outcome

```json
{
  "fib_outcome": {
    "executed_with_research_fib_t1": 6,
    "fib_t1_hit_before_stop_count": 1,
    "fib_t1_hit_before_stop_rate": 0.16666666666666666,
    "stop_before_fib_t1_count": 4,
    "stop_before_fib_t1_rate": 0.6666666666666666,
    "ambiguous_count": 0,
    "path_status_counts": {
      "FIB_HIT_BEFORE_STOP": 1,
      "FIB_NOT_REACHED_BEFORE_TERMINAL": 1,
      "STOP_BEFORE_FIB_HIT": 4
    },
    "same_bar_stop_first_contract": "PositionReplay excludes exit-day high when stop exits first"
  },
  "gross_performance": {
    "executed": 6,
    "closed": 6,
    "open_censored": 0,
    "wins": 1,
    "losses": 5,
    "flats": 0,
    "gross_total_R": -0.30047014057029653,
    "gross_positive_R": 3.2126185744392792,
    "gross_negative_R": -3.5130887150095758,
    "gross_expectancy_R": -0.05007835676171609,
    "median_realized_gross_R": -0.670300691996299,
    "gross_win_rate": 0.16666666666666666,
    "gross_profit_factor": 0.9144712345900785,
    "stop_out_count": 5,
    "stop_out_rate": 0.8333333333333334,
    "average_holding_sessions": 24.833333333333332,
    "terminal_outcome_distribution": {
      "CLOSED_EXIT_STOP_TRIGGERED": 5,
      "CLOSED_STRUCTURAL_EXIT_PENDING": 1
    },
    "metrics_are_gross_no_transaction_costs": true,
    "open_censored_excluded_from_closed_performance": true
  }
}
```

## Robustness

```json
{
  "market": {
    "CN": {
      "executed": 4,
      "closed": 4,
      "open_censored": 0,
      "wins": 1,
      "losses": 3,
      "flats": 0,
      "gross_total_R": 0.7599731874986485,
      "gross_positive_R": 3.2126185744392792,
      "gross_negative_R": -2.4526453869406306,
      "gross_expectancy_R": 0.18999329687466213,
      "median_realized_gross_R": -0.7263226934703153,
      "gross_win_rate": 0.25,
      "gross_profit_factor": 1.309858568036458,
      "stop_out_count": 3,
      "stop_out_rate": 0.75,
      "average_holding_sessions": 15.5,
      "terminal_outcome_distribution": {
        "CLOSED_EXIT_STOP_TRIGGERED": 3,
        "CLOSED_STRUCTURAL_EXIT_PENDING": 1
      },
      "metrics_are_gross_no_transaction_costs": true,
      "open_censored_excluded_from_closed_performance": true
    },
    "US": {
      "executed": 2,
      "closed": 2,
      "open_censored": 0,
      "wins": 0,
      "losses": 2,
      "flats": 0,
      "gross_total_R": -1.0604433280689451,
      "gross_positive_R": 0,
      "gross_negative_R": -1.0604433280689451,
      "gross_expectancy_R": -0.5302216640344726,
      "median_realized_gross_R": -0.5302216640344726,
      "gross_win_rate": 0.0,
      "gross_profit_factor": 0.0,
      "stop_out_count": 2,
      "stop_out_rate": 1.0,
      "average_holding_sessions": 43.5,
      "terminal_outcome_distribution": {
        "CLOSED_EXIT_STOP_TRIGGERED": 2
      },
      "metrics_are_gross_no_transaction_costs": true,
      "open_censored_excluded_from_closed_performance": true
    }
  },
  "development_time_half": {
    "first_half": {
      "executed": 2,
      "closed": 2,
      "open_censored": 0,
      "wins": 1,
      "losses": 1,
      "flats": 0,
      "gross_total_R": 2.7140372269934896,
      "gross_positive_R": 3.2126185744392792,
      "gross_negative_R": -0.49858134744578964,
      "gross_expectancy_R": 1.3570186134967448,
      "median_realized_gross_R": 1.3570186134967448,
      "gross_win_rate": 0.5,
      "gross_profit_factor": 6.4435193793297385,
      "stop_out_count": 2,
      "stop_out_rate": 1.0,
      "average_holding_sessions": 20.5,
      "terminal_outcome_distribution": {
        "CLOSED_EXIT_STOP_TRIGGERED": 2
      },
      "metrics_are_gross_no_transaction_costs": true,
      "open_censored_excluded_from_closed_performance": true
    },
    "second_half": {
      "executed": 4,
      "closed": 4,
      "open_censored": 0,
      "wins": 0,
      "losses": 4,
      "flats": 0,
      "gross_total_R": -3.014507367563786,
      "gross_positive_R": 0,
      "gross_negative_R": -3.014507367563786,
      "gross_expectancy_R": -0.7536268418909465,
      "median_realized_gross_R": -0.8980420380208247,
      "gross_win_rate": 0.0,
      "gross_profit_factor": 0.0,
      "stop_out_count": 3,
      "stop_out_rate": 0.75,
      "average_holding_sessions": 27.0,
      "terminal_outcome_distribution": {
        "CLOSED_EXIT_STOP_TRIGGERED": 3,
        "CLOSED_STRUCTURAL_EXIT_PENDING": 1
      },
      "metrics_are_gross_no_transaction_costs": true,
      "open_censored_excluded_from_closed_performance": true
    }
  },
  "symbol_concentration": {
    "closed_symbol_count": 6,
    "gross_total_net_R": -0.30047014057029653,
    "gross_total_absolute_net_R": 6.725707289448854,
    "gross_total_positive_R": 3.2126185744392792,
    "top_5_by_absolute_net_R": [
      {
        "symbol": "603919.SH",
        "value_R": 3.2126185744392792,
        "share_of_total_net_R": -10.69197281414281,
        "share_of_total_absolute_net_R": 0.47766256189578254,
        "share_of_total_positive_R": 1.0
      },
      {
        "symbol": "601888.SH",
        "value_R": -1.0,
        "share_of_total_net_R": 3.3281177227859846,
        "share_of_total_absolute_net_R": 0.1486832472725625,
        "share_of_total_positive_R": -0.3112725575193865
      },
      {
        "symbol": "001696.SZ",
        "value_R": -0.9540640394948411,
        "share_of_total_net_R": 3.1752374385155684,
        "share_of_total_absolute_net_R": 0.14185333949807127,
        "share_of_total_positive_R": -0.29697395361083617
      },
      {
        "symbol": "QLYS",
        "value_R": -0.8420200365468083,
        "share_of_total_net_R": 2.8023418065723353,
        "share_of_total_absolute_net_R": 0.1251942733023412,
        "share_of_total_positive_R": -0.2620977302584923
      },
      {
        "symbol": "002768.SZ",
        "value_R": -0.49858134744578964,
        "share_of_total_net_R": 1.6593374186848493,
        "share_of_total_absolute_net_R": 0.07413069376776973,
        "share_of_total_positive_R": -0.15519469115091278
      }
    ],
    "top_5_by_positive_gross_R": [
      {
        "symbol": "603919.SH",
        "positive_gross_R": 3.2126185744392792,
        "share_of_total_positive_R": 1.0
      }
    ],
    "top_symbol_by_positive_gross_R": "603919.SH",
    "top_symbol_positive_contribution_share": 1.0,
    "single_symbol_is_only_positive_contributor": true,
    "positive_contributor_symbols": [
      "603919.SH"
    ],
    "concentration_is_descriptive_no_threshold_selected": true
  }
}
```

## Current formal SETUP_01 context

```json
{
  "definition": "same frozen Development holdout current formal P0 SETUP_01 EXECUTED cohort; descriptive context, not a random control group",
  "gross_performance": {
    "executed": 4,
    "closed": 4,
    "open_censored": 0,
    "wins": 1,
    "losses": 3,
    "flats": 0,
    "gross_total_R": -3.4618153319905227,
    "gross_positive_R": 0.019805804235028722,
    "gross_negative_R": -3.4816211362255514,
    "gross_expectancy_R": -0.8654538329976307,
    "median_realized_gross_R": -0.8454501838640092,
    "gross_win_rate": 0.25,
    "gross_profit_factor": 0.005688673023309,
    "stop_out_count": 2,
    "stop_out_rate": 0.5,
    "average_holding_sessions": 15.0,
    "terminal_outcome_distribution": {
      "CLOSED_EXIT_GAP_BELOW_STOP": 2,
      "CLOSED_STRUCTURAL_EXIT_PENDING": 2
    },
    "metrics_are_gross_no_transaction_costs": true,
    "open_censored_excluded_from_closed_performance": true
  },
  "executed_details": [
    {
      "event_identity": "STX|SETUP_01|2018-04-16|CONFIRMED|lifecycle=8",
      "symbol": "STX",
      "market": "US",
      "T_date": "2018-04-16",
      "entry_date": "2018-04-17",
      "actual_entry": 45.179065005110296,
      "formal_t1": 55.36819535146739,
      "terminal_outcome": "CLOSED_EXIT_GAP_BELOW_STOP",
      "realized_gross_R": -1.5140482404485962,
      "holding_sessions": 11,
      "exit_date": "2018-05-01",
      "exit_reason": "EXIT_GAP_BELOW_STOP",
      "exit_price": 38.09070999313224
    },
    {
      "event_identity": "QLYS|SETUP_01|2020-05-20|CONFIRMED|lifecycle=20",
      "symbol": "QLYS",
      "market": "US",
      "T_date": "2020-05-20",
      "entry_date": "2020-05-21",
      "actual_entry": 111.36000061035156,
      "formal_t1": 158.6854384460449,
      "terminal_outcome": "CLOSED_STRUCTURAL_EXIT_PENDING",
      "realized_gross_R": -0.17685212727942223,
      "holding_sessions": 13,
      "exit_date": "2020-06-09",
      "exit_reason": "STRUCTURAL_EXIT_PENDING",
      "exit_price": 108.6500015258789
    },
    {
      "event_identity": "LRCX|SETUP_01|2021-02-04|CONFIRMED|lifecycle=22",
      "symbol": "LRCX",
      "market": "US",
      "T_date": "2021-02-04",
      "entry_date": "2021-02-05",
      "actual_entry": 49.57181420386763,
      "formal_t1": 66.13659111657323,
      "terminal_outcome": "CLOSED_STRUCTURAL_EXIT_PENDING",
      "realized_gross_R": 0.019805804235028722,
      "holding_sessions": 22,
      "exit_date": "2021-03-09",
      "exit_reason": "STRUCTURAL_EXIT_PENDING",
      "exit_price": 49.70223929794733
    },
    {
      "event_identity": "META|SETUP_01|2024-04-05|CONFIRMED|lifecycle=43",
      "symbol": "META",
      "market": "US",
      "T_date": "2024-04-05",
      "entry_date": "2024-04-08",
      "actual_entry": 525.229391434242,
      "formal_t1": 704.5131985665921,
      "terminal_outcome": "CLOSED_EXIT_GAP_BELOW_STOP",
      "realized_gross_R": -1.7907207684975333,
      "holding_sessions": 14,
      "exit_date": "2024-04-25",
      "exit_reason": "EXIT_GAP_BELOW_STOP",
      "exit_price": 418.1748277483047
    }
  ]
}
```

## Executed P1 detail

```json
[
  {
    "event_identity": "002768.SZ|SETUP_01|2017-09-20|CONFIRMED|lifecycle=5",
    "symbol": "002768.SZ",
    "market": "CN",
    "T_date": "2017-09-20",
    "T_plus_1_entry_date": "2017-09-21",
    "actual_entry": 15.88373764,
    "execution_stop": 14.969750746595867,
    "original_overhead_confirmed_swing_high_price": 16.63974377,
    "original_overhead_confirmed_swing_high_provenance": [
      {
        "source": "CONFIRMED_SWING_HIGH",
        "pivot_date": "2017-03-08",
        "confirmed_date": "2017-03-28",
        "extension_ratio": null
      }
    ],
    "overhead_distance": 0.7560061299999994,
    "overhead_distance_pct_from_actual_entry": 0.0475962362974411,
    "research_fib_t1_price": 19.65060124096,
    "research_fib_t1_ratio": 1.272,
    "research_fib_t1_provenance": [
      {
        "source": "WAVE3_FIB_EXTENSION",
        "pivot_date": null,
        "confirmed_date": null,
        "extension_ratio": 1.272
      }
    ],
    "fib_t1_distance": 3.7668636009600007,
    "fib_t1_distance_pct_from_actual_entry": 0.237152217339193,
    "t_plus_1_open_already_gapped_above_swing_high": false,
    "swing_high_cleared_after_entry_before_stop": true,
    "stop_reached_before_swing_high_cleared": false,
    "fib_t1_reached_before_stop": false,
    "obstacle_path": {
      "status": "CLEARED_BEFORE_STOP",
      "gap_above_at_entry": false,
      "cleared_after_entry_before_stop": true,
      "cleared_before_terminal_without_stop": false,
      "stop_before_obstacle_clear": false,
      "obstacle_clear_date": "2017-09-25",
      "stop_date": "2017-11-03",
      "same_bar_stop_first_applied": false
    },
    "fib_path": {
      "status": "STOP_BEFORE_FIB_HIT",
      "fib_t1_hit_before_stop": false,
      "stop_before_fib_t1": true,
      "fib_hit_date": null,
      "stop_date": "2017-11-03",
      "same_bar_stop_first_applied": false
    },
    "terminal_outcome": "CLOSED_EXIT_STOP_TRIGGERED",
    "realized_gross_R": -0.49858134744578964,
    "holding_sessions": 27,
    "exit_date": "2017-11-03",
    "exit_reason": "EXIT_STOP_TRIGGERED",
    "exit_price": 15.428040823138776,
    "development_time_half": "first_half"
  },
  {
    "event_identity": "603919.SH|SETUP_01|2020-05-13|CONFIRMED|lifecycle=18",
    "symbol": "603919.SH",
    "market": "CN",
    "T_date": "2020-05-13",
    "T_plus_1_entry_date": "2020-05-14",
    "actual_entry": 10.3182947,
    "execution_stop": 9.40070742460455,
    "original_overhead_confirmed_swing_high_price": 10.37369494,
    "original_overhead_confirmed_swing_high_provenance": [
      {
        "source": "CONFIRMED_SWING_HIGH",
        "pivot_date": "2020-02-11",
        "confirmed_date": "2020-03-03",
        "extension_ratio": null
      }
    ],
    "overhead_distance": 0.05540024000000088,
    "overhead_distance_pct_from_actual_entry": 0.005369127516778609,
    "research_fib_t1_price": 12.226832968,
    "research_fib_t1_ratio": 1.272,
    "research_fib_t1_provenance": [
      {
        "source": "WAVE3_FIB_EXTENSION",
        "pivot_date": null,
        "confirmed_date": null,
        "extension_ratio": 1.272
      }
    ],
    "fib_t1_distance": 1.908538268000001,
    "fib_t1_distance_pct_from_actual_entry": 0.18496644295302023,
    "t_plus_1_open_already_gapped_above_swing_high": false,
    "swing_high_cleared_after_entry_before_stop": true,
    "stop_reached_before_swing_high_cleared": false,
    "fib_t1_reached_before_stop": true,
    "obstacle_path": {
      "status": "CLEARED_BEFORE_STOP",
      "gap_above_at_entry": false,
      "cleared_after_entry_before_stop": true,
      "cleared_before_terminal_without_stop": false,
      "stop_before_obstacle_clear": false,
      "obstacle_clear_date": "2020-05-14",
      "stop_date": "2020-06-02",
      "same_bar_stop_first_applied": false
    },
    "fib_path": {
      "status": "FIB_HIT_BEFORE_STOP",
      "fib_t1_hit_before_stop": true,
      "stop_before_fib_t1": false,
      "fib_hit_date": "2020-05-28",
      "stop_date": "2020-06-02",
      "same_bar_stop_first_applied": false
    },
    "terminal_outcome": "CLOSED_EXIT_STOP_TRIGGERED",
    "realized_gross_R": 3.2126185744392792,
    "holding_sessions": 14,
    "exit_date": "2020-06-02",
    "exit_reason": "EXIT_STOP_TRIGGERED",
    "exit_price": 13.266152624604551,
    "development_time_half": "first_half"
  },
  {
    "event_identity": "601888.SH|SETUP_01|2023-01-05|CONFIRMED|lifecycle=34",
    "symbol": "601888.SH",
    "market": "CN",
    "T_date": "2023-01-05",
    "T_plus_1_entry_date": "2023-01-06",
    "actual_entry": 212.55797731,
    "execution_stop": 196.57830910205934,
    "original_overhead_confirmed_swing_high_price": 213.43370902,
    "original_overhead_confirmed_swing_high_provenance": [
      {
        "source": "CONFIRMED_SWING_HIGH",
        "pivot_date": "2022-07-28",
        "confirmed_date": "2022-08-15",
        "extension_ratio": null
      }
    ],
    "overhead_distance": 0.8757317099999966,
    "overhead_distance_pct_from_actual_entry": 0.00411996633145792,
    "research_fib_t1_price": 262.08815751944,
    "research_fib_t1_ratio": 1.272,
    "research_fib_t1_provenance": [
      {
        "source": "WAVE3_FIB_EXTENSION",
        "pivot_date": null,
        "confirmed_date": null,
        "extension_ratio": 1.272
      }
    ],
    "fib_t1_distance": 49.530180209440005,
    "fib_t1_distance_pct_from_actual_entry": 0.23301962521596598,
    "t_plus_1_open_already_gapped_above_swing_high": false,
    "swing_high_cleared_after_entry_before_stop": true,
    "stop_reached_before_swing_high_cleared": false,
    "fib_t1_reached_before_stop": false,
    "obstacle_path": {
      "status": "CLEARED_BEFORE_STOP",
      "gap_above_at_entry": false,
      "cleared_after_entry_before_stop": true,
      "cleared_before_terminal_without_stop": false,
      "stop_before_obstacle_clear": false,
      "obstacle_clear_date": "2023-01-09",
      "stop_date": "2023-02-03",
      "same_bar_stop_first_applied": false
    },
    "fib_path": {
      "status": "STOP_BEFORE_FIB_HIT",
      "fib_t1_hit_before_stop": false,
      "stop_before_fib_t1": true,
      "fib_hit_date": null,
      "stop_date": "2023-02-03",
      "same_bar_stop_first_applied": false
    },
    "terminal_outcome": "CLOSED_EXIT_STOP_TRIGGERED",
    "realized_gross_R": -1.0,
    "holding_sessions": 16,
    "exit_date": "2023-02-03",
    "exit_reason": "EXIT_STOP_TRIGGERED",
    "exit_price": 196.57830910205934,
    "development_time_half": "second_half"
  },
  {
    "event_identity": "001696.SZ|SETUP_01|2023-03-06|CONFIRMED|lifecycle=20",
    "symbol": "001696.SZ",
    "market": "CN",
    "T_date": "2023-03-06",
    "T_plus_1_entry_date": "2023-03-07",
    "actual_entry": 6.7763491,
    "execution_stop": 6.328787089145791,
    "original_overhead_confirmed_swing_high_price": 6.80419711,
    "original_overhead_confirmed_swing_high_provenance": [
      {
        "source": "CONFIRMED_SWING_HIGH",
        "pivot_date": "2022-07-18",
        "confirmed_date": "2022-08-15",
        "extension_ratio": null
      }
    ],
    "overhead_distance": 0.02784800999999959,
    "overhead_distance_pct_from_actual_entry": 0.00410958904109583,
    "research_fib_t1_price": 8.093522842319999,
    "research_fib_t1_ratio": 1.272,
    "research_fib_t1_provenance": [
      {
        "source": "WAVE3_FIB_EXTENSION",
        "pivot_date": null,
        "confirmed_date": null,
        "extension_ratio": 1.272
      }
    ],
    "fib_t1_distance": 1.3171737423199987,
    "fib_t1_distance_pct_from_actual_entry": 0.19437808219178063,
    "t_plus_1_open_already_gapped_above_swing_high": false,
    "swing_high_cleared_after_entry_before_stop": null,
    "stop_reached_before_swing_high_cleared": false,
    "fib_t1_reached_before_stop": false,
    "obstacle_path": {
      "status": "CLEARED_BEFORE_TERMINAL_WITHOUT_STOP",
      "gap_above_at_entry": false,
      "cleared_after_entry_before_stop": null,
      "cleared_before_terminal_without_stop": true,
      "stop_before_obstacle_clear": false,
      "obstacle_clear_date": "2023-03-07",
      "stop_date": null,
      "same_bar_stop_first_applied": false
    },
    "fib_path": {
      "status": "FIB_NOT_REACHED_BEFORE_TERMINAL",
      "fib_t1_hit_before_stop": false,
      "stop_before_fib_t1": false,
      "fib_hit_date": null,
      "stop_date": null,
      "same_bar_stop_first_applied": false
    },
    "terminal_outcome": "CLOSED_STRUCTURAL_EXIT_PENDING",
    "realized_gross_R": -0.9540640394948411,
    "holding_sessions": 5,
    "exit_date": "2023-03-13",
    "exit_reason": "STRUCTURAL_EXIT_PENDING",
    "exit_price": 6.34934628,
    "development_time_half": "second_half"
  },
  {
    "event_identity": "LRCX|SETUP_01|2023-06-30|CONFIRMED|lifecycle=31",
    "symbol": "LRCX",
    "market": "US",
    "T_date": "2023-06-30",
    "T_plus_1_entry_date": "2023-07-03",
    "actual_entry": 62.58102934525486,
    "execution_stop": 56.810337612332326,
    "original_overhead_confirmed_swing_high_price": 62.60416104478932,
    "original_overhead_confirmed_swing_high_provenance": [
      {
        "source": "CONFIRMED_SWING_HIGH",
        "pivot_date": "2021-08-02",
        "confirmed_date": "2021-08-27",
        "extension_ratio": null
      }
    ],
    "overhead_distance": 0.023131699534459926,
    "overhead_distance_pct_from_actual_entry": 0.00036962798113856626,
    "research_fib_t1_price": 76.31292762316197,
    "research_fib_t1_ratio": 1.272,
    "research_fib_t1_provenance": [
      {
        "source": "WAVE3_FIB_EXTENSION",
        "pivot_date": null,
        "confirmed_date": null,
        "extension_ratio": 1.272
      }
    ],
    "fib_t1_distance": 13.731898277907106,
    "fib_t1_distance_pct_from_actual_entry": 0.21942589346284558,
    "t_plus_1_open_already_gapped_above_swing_high": false,
    "swing_high_cleared_after_entry_before_stop": true,
    "stop_reached_before_swing_high_cleared": false,
    "fib_t1_reached_before_stop": false,
    "obstacle_path": {
      "status": "CLEARED_BEFORE_STOP",
      "gap_above_at_entry": false,
      "cleared_after_entry_before_stop": true,
      "cleared_before_terminal_without_stop": false,
      "stop_before_obstacle_clear": false,
      "obstacle_clear_date": "2023-07-03",
      "stop_date": "2023-09-15",
      "same_bar_stop_first_applied": false
    },
    "fib_path": {
      "status": "STOP_BEFORE_FIB_HIT",
      "fib_t1_hit_before_stop": false,
      "stop_before_fib_t1": true,
      "fib_hit_date": null,
      "stop_date": "2023-09-15",
      "same_bar_stop_first_applied": false
    },
    "terminal_outcome": "CLOSED_EXIT_STOP_TRIGGERED",
    "realized_gross_R": -0.21842329152213671,
    "holding_sessions": 53,
    "exit_date": "2023-09-15",
    "exit_reason": "EXIT_STOP_TRIGGERED",
    "exit_price": 61.32057586259034,
    "development_time_half": "second_half"
  },
  {
    "event_identity": "QLYS|SETUP_01|2025-06-11|CONFIRMED|lifecycle=44",
    "symbol": "QLYS",
    "market": "US",
    "T_date": "2025-06-11",
    "T_plus_1_entry_date": "2025-06-12",
    "actual_entry": 140.00999450683594,
    "execution_stop": 132.1064639043556,
    "original_overhead_confirmed_swing_high_price": 140.63999938964844,
    "original_overhead_confirmed_swing_high_provenance": [
      {
        "source": "CONFIRMED_SWING_HIGH",
        "pivot_date": "2021-11-09",
        "confirmed_date": "2021-12-10",
        "extension_ratio": null
      }
    ],
    "overhead_distance": 0.6300048828125,
    "overhead_distance_pct_from_actual_entry": 0.004499713645669347,
    "research_fib_t1_price": 166.9227958984375,
    "research_fib_t1_ratio": 1.272,
    "research_fib_t1_provenance": [
      {
        "source": "WAVE3_FIB_EXTENSION",
        "pivot_date": null,
        "confirmed_date": null,
        "extension_ratio": 1.272
      }
    ],
    "fib_t1_distance": 26.912801391601562,
    "fib_t1_distance_pct_from_actual_entry": 0.19222057315549393,
    "t_plus_1_open_already_gapped_above_swing_high": false,
    "swing_high_cleared_after_entry_before_stop": true,
    "stop_reached_before_swing_high_cleared": false,
    "fib_t1_reached_before_stop": false,
    "obstacle_path": {
      "status": "CLEARED_BEFORE_STOP",
      "gap_above_at_entry": false,
      "cleared_after_entry_before_stop": true,
      "cleared_before_terminal_without_stop": false,
      "stop_before_obstacle_clear": false,
      "obstacle_clear_date": "2025-06-12",
      "stop_date": "2025-07-31",
      "same_bar_stop_first_applied": false
    },
    "fib_path": {
      "status": "STOP_BEFORE_FIB_HIT",
      "fib_t1_hit_before_stop": false,
      "stop_before_fib_t1": true,
      "fib_hit_date": null,
      "stop_date": "2025-07-31",
      "same_bar_stop_first_applied": false
    },
    "terminal_outcome": "CLOSED_EXIT_STOP_TRIGGERED",
    "realized_gross_R": -0.8420200365468083,
    "holding_sessions": 34,
    "exit_date": "2025-07-31",
    "exit_reason": "EXIT_STOP_TRIGGERED",
    "exit_price": 133.35506338008662,
    "development_time_half": "second_half"
  }
]
```

## Governance conclusion

This is a research result only. It does not change production Decision semantics, target candidates, entry, stop, Wave, Swing, confirmation, or Paper/production lifecycle behavior.

Status: `READY_FOR_DECISION`.

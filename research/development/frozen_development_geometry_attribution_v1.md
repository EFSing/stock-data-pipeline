# Frozen Development T-day geometry attribution

Protocol: `FROZEN_DEVELOPMENT_T1_ZONE_STOP_GEOMETRY_V1`. Common denominator: **999** first CONFIRMED Decisions. No T+1 outcome was read.

| Market / Setup | N | Entry allowed | Above zone | T1 upside <5% | T1 RR <2R | Complete geometry |
|---|---:|---:|---:|---:|---:|---:|
| CN/SETUP_01 | 299 | 0 | 188 | 86 | 25 | 294 |
| CN/SETUP_02 | 77 | 0 | 44 | 20 | 8 | 70 |
| US/SETUP_01 | 446 | 5 | 276 | 112 | 53 | 435 |
| US/SETUP_02 | 177 | 3 | 87 | 59 | 14 | 157 |

## Paired geometry on the common 999-event denominator

Calculable complete tuples: 956/999. Median gross T1 space: 1.6054%; median execution-risk distance: 14.1703%; median T1/R: 0.121. Medians use available fields; missing events remain in the 999 denominator.

Unknown fields: `{"atr14": 14, "entry_zone_high": 14, "execution_stop": 14, "t1": 43, "t1_rr": 43}`.

## Overlapping rejection conditions

Above zone and RR below minimum: 565; upside below 5% and RR below 2R: 745. These intersections are events counted in both conditions, not additional rejected plans.

The existing aggregate audit's `FORMAL_T1_CONFIRMED_SWING_HIGH` is a T1-source attribute, not a rejection; event rows retain it in `all_fail` only for exact audit reconciliation and expose actual `all_rejections` separately. Primary counts and all-market flags reconcile with the frozen scarcity audit. JSON contains all 999 T-day event rows plus market, Setup and T1-source summaries. Unknown fields remain null. Neither targets nor stops were changed.

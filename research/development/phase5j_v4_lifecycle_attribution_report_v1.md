# Phase 5J-v4 SETUP_03 平台身份与生命周期分歧归因

> 单一冻结数据集 causal diagnostic；不是 tolerance 搜索，不是生产规则，不是 Final OOS。

## 冻结身份与边界

- protocol: `SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1` / `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`
- dataset: 40 symbols / 86,305 bars / `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`
- attribution capsule file SHA-256: `sha256:33fea52774618474a7e343db17f92a2f5d0b2160fda8530f1a11daa0f41b3762`
- production parity: setup mismatches `0`，event mismatches `0`
- 禁止指标访问：returns/MFE/MAE/P&L/winrate/profit factor/expectancy 全部 false；Final OOS 未访问。

## Root cause

- `LARGEST_ROOT_CAUSE`: `LOW_SPAN_THRESHOLD_CROSSING`
- `ATTRIBUTION_EVIDENCE_STATUS`: `MIXED_CAUSAL_STRUCTURE`
- ranking: `[{'root_cause': 'LOW_SPAN_THRESHOLD_CROSSING', 'count': 88, 'share': 0.4971751412429379}, {'root_cause': 'HIGH_SPAN_THRESHOLD_CROSSING', 'count': 69, 'share': 0.3898305084745763}, {'root_cause': 'BOTH_SPAN_THRESHOLD_CROSSING', 'count': 20, 'share': 0.11299435028248588}]`

### 相邻 pair 与市场一致性

- 3%→4% `HIGH_SPAN_THRESHOLD_CROSSING`: `28` / `31.11%`
- 3%→4% `LOW_SPAN_THRESHOLD_CROSSING`: `53` / `58.89%`
- 3%→4% `BOTH_SPAN_THRESHOLD_CROSSING`: `9` / `10.00%`
- 4%→5% `HIGH_SPAN_THRESHOLD_CROSSING`: `41` / `47.13%`
- 4%→5% `LOW_SPAN_THRESHOLD_CROSSING`: `35` / `40.23%`
- 4%→5% `BOTH_SPAN_THRESHOLD_CROSSING`: `11` / `12.64%`
- 3.0%→4.0%: CN `LOW_SPAN_THRESHOLD_CROSSING`，US `LOW_SPAN_THRESHOLD_CROSSING`，CN/US consistent=`True`
- 4.0%→5.0%: CN `HIGH_SPAN_THRESHOLD_CROSSING`，US `LOW_SPAN_THRESHOLD_CROSSING`，CN/US consistent=`False`
- 3→4 vs 4→5 pooled dominant-root consistent: `False`

## Cascade 与 counterfactual

- 3%→4%: roots `90`, downstream `76`, ratio `0.8444444444444444`，max depth `4`
- 4%→5%: roots `87`, downstream `69`, ratio `0.7931034482758621`，max depth `4`
- 3%→4% counterfactual A: downstream reduction `76`
- 3%→4% counterfactual B: anchor divergence reduction `0`
- 3%→4% counterfactual C: terminal divergence remains `0`
- 3%→4% counterfactual D: restored added/disappeared lifecycle `76`
- 4%→5% counterfactual A: downstream reduction `69`
- 4%→5% counterfactual B: anchor divergence reduction `0`
- 4%→5% counterfactual C: terminal divergence remains `0`
- 4%→5% counterfactual D: restored added/disappeared lifecycle `69`

四个 counterfactual 均标记 `RESEARCH_CAUSAL_DIAGNOSTIC_ONLY` / `NOT_A_CANDIDATE_RULE`。

## Historical symptom concordance

- CN 3%→4%: `PARTIALLY_CONCORDANT` / `NOT_CAUSAL_REPLICATION`
- US 3%→4%: `CONCORDANT` / `NOT_CAUSAL_REPLICATION`
- CN 4%→5%: `PARTIALLY_CONCORDANT` / `NOT_CAUSAL_REPLICATION`
- US 4%→5%: `PARTIALLY_CONCORDANT` / `NOT_CAUSAL_REPLICATION`

## Sol recommendation

`REDESIGN_PLATFORM_BOUNDARY_SEMANTICS_THEN_REDESIGN_TERMINAL_REARM_ORCHESTRATION`

该建议只确定下一层研究方向，不实施策略修改。

`PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION`

# Phase 5J-v4 SETUP_03 生命周期分歧归因协议

本协议在任何真实 holdout attribution 结果产生前冻结。机器可读单一事实来源是 `setup03_phase5j_v4_lifecycle_attribution_protocol.json`，版本 `SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1`，canonical SHA-256 为 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`。

研究只在第二套 frozen development holdout（40 symbols / 86,305 bars / replay `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`）上解释 3%→4% 与 4%→5% 的 platform/event lifecycle divergence。早期 40 / 84,284 数据集 exact bytes 不可恢复，只能把 tracked PR #29 capsule/report 用作 `HISTORICAL_STRUCTURE_SYMPTOM_EVIDENCE`，明确标记 `NOT_CAUSAL_REPLICATION`；不 refetch v1，也不建立第三套 development dataset。

实现必须复用 production SETUP_03 状态机，只增加 read-only trace。每个相邻 tolerance pair 从同 symbol 的 `FIRST_DIVERGENCE_BAR` 开始，按已冻结的 ordered root-cause taxonomy 给出唯一 primary cause；root 与 downstream cascade 分开，descendants 不重复计作 root。research-only lifecycle identity、lineage 与四个单机制 counterfactual 不能反向修改 Phase 5J-v3 matching/qualification，也不能进入 production path。

禁止访问 Final OOS、A1 formal 120 OHLCV、forward returns、MFE、MAE、P&L、winrate、profit factor、expectancy；禁止 tolerance search、新候选和任何 production/market/regime/volatility rule 修改。任何 parity mismatch 都先作为 correctness bug 修复，不得改研究规则绕过。

完成后只能形成 attribution evidence、Sol redesign recommendation 和新 PR；不得 merge。最终 stop state 为 `PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION`。

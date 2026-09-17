# HANDOFF — 当前开发现场

Git/GitHub 是动态工程事实源；恢复时实时查询 main、PR HEAD、CI 和 mergeability。

## Current Task

当前分支：`hotfix/us-cloud-daily-report-freshness-v1`，独立 PR #90，已合并最新 main。

## Current State

- 本次任务：先修正并验证 PR #91 的治理分类冲突，squash merge；随后在 PR #90 原分支落实 usable exact-session partial report 的 exit 0 运维语义，验证并 squash merge；再从最新 main 开展 `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1`。
- PR #91 已 squash merge 且最终 CI 三项成功；PR #90 仍 OPEN；PR #82 完全独立，不 merge/rebase/mix。
- `PROJECT_GOVERNANCE_STATE_CONFLICT` 的原因已客观核实并修正：确定性 code/artifact 总体分类是 `MIXED_ARCHITECTURE_SIGNAL_STARVATION`。`ABOVE_ENTRY_ZONE=595/999` 是最大 post-confirmation first-fail，不能替代总体分类。

## Completed / Validation

- #90 已落实：PARTIAL_DATA_QUALITY 在 exact target-session usable data、核心计算完成和两个 final artifact 存在时 exit 0；status、单源标记、actual provenance 与所有策略/data gates 不变。
- #90 focused provider/report 79 tests；full 777 tests，3 skipped，OK；py_compile 与 git diff --check 通过。

- PR #91 production code、研究算法、阈值和 artifact 未改。
- Focused 14 tests；full 767 tests，3 skipped，OK；artifact self-hash tests 通过。
- frozen Development loader 已核验 40 symbols、86,305 bars 和固定 manifest/replay identities；完整重放的所有内容与已提交 artifact 一致，初次 hash 差异仅为 protocol CRLF/LF file bytes，已以 Git LF bytes 完成复核，canonical artifact SHA 完全匹配。

- #90 只读 US manual smoke 已完成：exact XNYS 2026-09-16，report PARTIAL_DATA_QUALITY，workflow success/exit 0，220 DATA_OK、2 DATA_UNAVAILABLE；两个 final artifacts 及 transport digest 核验通过。actual primary Tencent、verifier Sina；两条 QFQ provider 不可用仍 blocked，没有以 T-1 替代 T，没有 state/Sheets/Paper/broker/raw writes。

## Blocker

无研究实现 blocker；继续用户已授权的 #90 修改与研究。

## Next Action

核对 #90 final-head CI 后 squash merge；继续独立 retest 研究，最终停在 `READY_FOR_DECISION_POST_CONFIRMATION_RETEST_ARCHITECTURE`。

## Constraints / Pitfalls

- 总体规则以 `docs/TRADING_SYSTEM_SPEC.md` 为准；5%、2R、confirmation、Entry Zone、Swing/Wave/Target/Stop、T→T+1 不变。
- retest 研究只允许固定 A/B policies，Development-only、strict as-of、冻结确认日 geometry；无等待期限/参数搜索、Final OOS、production code 修改。
- 不写 Sheets/state/Paper、不读取真实 holdings、不下 broker order；generic shadow 不注入 holdings secrets。
- #90 stale/no exact session、核心异常、final artifact 失败继续 non-zero；partial status/provenance 不能伪装 SUCCESS；notification contract 不变。
- 本机默认 ignored manifest 路径不存在时使用 Git-tracked `research/development_holdout/dataset_manifest.json` 与 `replay_manifest.json`；不重新抓取冻结数据。

`HANDOFF_CURRENT_AND_CONSISTENT`

总体主线：Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
四类 Setup：SETUP_01、SETUP_02、SETUP_03、SETUP_04；SETUP_03 只是四类 Setup 之一的子策略。

`CROSS_DEVICE_HANDOFF_READY`

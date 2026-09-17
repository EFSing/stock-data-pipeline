# HANDOFF — 当前开发现场

Git/GitHub 是动态工程事实源；恢复时实时查询 main、PR HEAD、CI 和 mergeability。

## Current Task / State

- 本次任务：先修正并验证 PR #91 的治理分类冲突，squash merge；随后在 PR #90 原分支落实 usable exact-session partial report 的 exit 0 运维语义，验证并 squash merge；再从最新 main 开展 `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1`。
- PR #91 仍 OPEN，正在按本次用户授权完成验证与合并；PR #90 仍 OPEN；PR #82 完全独立，不 merge/rebase/mix。
- `PROJECT_GOVERNANCE_STATE_CONFLICT` 的原因已客观核实并修正：确定性 code/artifact 总体分类是 `MIXED_ARCHITECTURE_SIGNAL_STARVATION`。`ABOVE_ENTRY_ZONE=595/999` 是最大 post-confirmation first-fail，不能替代总体分类。

## Completed / Validation

- PR #91 production code、研究算法、阈值和 artifact 未改。
- Focused 14 tests；full 767 tests，3 skipped，OK；artifact self-hash tests 通过。
- frozen Development loader 已核验 40 symbols、86,305 bars 和固定 manifest/replay identities；完整重放的所有内容与已提交 artifact 一致，初次 hash 差异仅为 protocol CRLF/LF file bytes，正在以 Git LF bytes 完成确定性复核。

## Next Action

完成 #91 deterministic/hash 与 CI 核对后 squash merge，同步 main；继续 #90 和独立 retest 研究，最终停在 `READY_FOR_DECISION_POST_CONFIRMATION_RETEST_ARCHITECTURE`。

## Constraints / Pitfalls

- 总体规则以 `docs/TRADING_SYSTEM_SPEC.md` 为准；5%、2R、confirmation、Entry Zone、Swing/Wave/Target/Stop、T→T+1 不变。
- retest 研究只允许固定 A/B policies，Development-only、strict as-of、冻结确认日 geometry；无等待期限/参数搜索、Final OOS、production code 修改。
- 不写 Sheets/state/Paper、不读取真实 holdings、不下 broker order；generic shadow 不注入 holdings secrets。
- #90 stale/no exact session、核心异常、final artifact 失败继续 non-zero；partial status/provenance 不能伪装 SUCCESS；notification contract 不变。
- 本机默认 ignored manifest 路径不存在时使用 Git-tracked `research/development_holdout/dataset_manifest.json` 与 `replay_manifest.json`；不重新抓取冻结数据。

`HANDOFF_CURRENT_AND_CONSISTENT`

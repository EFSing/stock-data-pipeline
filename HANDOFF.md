# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI、mergeability 的实时事实源；不依赖本机目录、聊天或 session memory。

## Current Task

`POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1` 已完成固定 Development-only A/B 研究。
正式节点：`READY_FOR_DECISION_POST_CONFIRMATION_RETEST_ARCHITECTURE`。
本轮所有已授权实现与验证已完成；只等待用户决定是否进入独立 production design / fresh validation。

## Current State

- 当前分支：`codex/post-confirmation-retest-entry-causal-research-v1`，从包含 #90/#91 squash merge 的最新 main 创建；独立 research PR #92 已创建，保持 OPEN、不自动 merge。
- PR #91 分类冲突已核实、修正并验证后 squash merge；确定性 artifact 总体分类仍为 `MIXED_ARCHITECTURE_SIGNAL_STARVATION`。`ABOVE_ENTRY_ZONE=595/999` 是最大 post-confirmation first-fail，不是总体唯一原因。
- PR #90 已落实用户明确的 partial-report operational exit 语义，经 full/focused tests、CI 与只读 US manual smoke 后 squash merge；main 交接已同步。
- PR #82 完全独立，保持 OPEN；本次没有 merge/rebase/mix。其 HEAD、CI 与冲突状态实时从 GitHub 查询。
- 长期总体交易规则以 `docs/TRADING_SYSTEM_SPEC.md` 为唯一正式事实源。

## Completed

- 先提交固定 A/B protocol，再执行冻结 Development replay；SETUP_01/02、CN/US、EARLY/LATE、ABOVE_ENTRY_ZONE 子集和 symbol concentration 分别报告。
- incumbent：999 CONFIRMED、8 ENTRY_ALLOWED、4 exact T+1 executed。
- A：620 个 previously non-ENTRY_ALLOWED confirmed pending facts，新增 executable 0；其中 ABOVE_ENTRY_ZONE pending 352。
- B：8 个 plan（7 个 previously non-ENTRY_ALLOWED，另 1 个 incumbent T+1 skip 后 retest plan），新增 executable 5；SETUP_01/02 为 4/1，CN/US 为 1/4，EARLY/LATE 为 5/0。
- ABOVE_ENTRY_ZONE 595 个事件：B 78 个 first-close retests，7 个 plans，4 个 executable（0.672%）；其 first-retest economic failures、T1 exhaustion、context replacement、structural invalidation、next-open gap 与 right censoring 全部守恒记录。
- 新增执行来自 5 个 symbol，每个 1 次；剔除按 count/lexicographic tie-break 的 top symbol 后仍为 4。执行 retest latency 为 3–17 sessions，中位数 6；不选择等待窗口。
- 2,050 candidate lifecycles = 999 confirmed + 1,051 non-confirmed；confirmed 的 incumbent/A/B executed sets 去重无重叠，executed union 9 + non-executed 990 = 999；A/B terminal reasons 各守恒 999。
- JSON/Markdown 是 compact aggregate，无 raw bars/event dump；production code 和 strategy semantics 未改。

## Validation

- Retest focused 8 tests；full `python -m unittest discover -s tests -v`：785 tests、3 skipped、OK；py_compile 通过。
- 两次 full frozen replay JSON bytes 与 canonical self-hash 相同，Markdown deterministic；固定 protocol、parent audit self-hash、dataset manifest/replay aggregate pins 通过。
- `git diff --check` 与现有 governance checks 通过；PR ready 前从 GitHub 实时核对 final HEAD CI 与 mergeability。
- #91 focused 14/full 767，artifact full parity 与 self-hash 通过；#90 focused 79/full 777 和三项 PR CI 通过。
- #90 一次只读 US smoke：exact XNYS 2026-09-16，PARTIAL_DATA_QUALITY 保留、workflow exit 0；220 DATA_OK、2 DATA_UNAVAILABLE，actual primary Tencent/verifier Sina；两条 unavailable QFQ 继续 blocked，未用 T-1 替代 T；final JSON/HTML 与 transport digest 核验通过，无 state/Sheets/Paper/raw writes 或 broker action。可复核 workflow 链接见 #90 PR 描述。

## Blocker

无实现安全 blocker，`PROJECT_GOVERNANCE_STATE_CONFLICT` 已解除。
恢复数量很小且全部新增执行属于 EARLY half，不支持声称 broad/time-stable signal restoration，不证明 Entry Zone 错误，不构成生产授权。

## Next Action

用户决定：是否仍授权 confirmed → wait-for-retest 架构进入独立 production design / fresh validation，或据小样本结果保持当前 production semantics。
不自动实现生产变化，不继续搜索 ATR、confirmation、entry、等待天数或更多 policies。

## Constraints

- 主线：Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
- 四类 Setup：SETUP_01、SETUP_02、SETUP_03、SETUP_04；SETUP_03 只是四类 Setup 之一的子策略。
- confirmation、ATR14 Entry Zone、Swing/Wave/Fib、Target-before-RR、Stop、5%、2R、T→T+1 均不变；确认日 geometry/targets/provenance 冻结。
- A 只用 exact T+1 OPEN；B 只用 first legal retest close 形成 plan，真正执行取其 exact next-session OPEN；首次 retest 失败不挑选后续更有利 close。
- waiting lifetime 由既有 context eligibility/key/lifecycle、close-based structural invalidation、known T1 exhaustion 与数据契约终止，不引入固定等待窗口。
- Development-only，无 Final OOS/parameter search/threshold sweep/provider fetch/真实 holdings；不写 Sheets/state/Paper，不下 broker order，不使用 post-entry outcomes。
- REAL_HOLDINGS_SHADOW 仍为 OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY，不是研究 blocker。

## Pitfalls

- HIGH >= frozen T1 只用于当时已知的 pre-entry exhaustion；A 不能读取 T+1 HIGH/LOW/CLOSE。confirmation-day HIGH 已在 T close 知晓。
- same-close structural/context/target terminator 优先于 close retest；不假设有利 intraday 顺序。dataset-end never-retested 为 right-censored。
- Development session identity 为既有 FROZEN_DATASET_MARKET_SESSION_SET，不声称 exchange calendar proof；缺 exact symbol/session bar 不得顺延。
- 冻结 bytes 按 docs/FROZEN_ARTIFACT_REGISTRY.json / FROZEN_ARTIFACT_POLICY.md 的持久身份恢复；使用 Git-tracked research/development_holdout manifests 和现有 loader 验证 hashes/counts，不重新抓取替代 frozen input。
- #90 PARTIAL_DATA_QUALITY 的 exit 0 只表示 usable exact-session data + core completed + final artifacts；status/provenance 不变，stale/no exact/core exception/artifact failure 继续 non-zero，notification contract 不变。

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

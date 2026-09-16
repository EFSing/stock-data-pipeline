# HANDOFF — 当前开发现场恢复文件

> 本文件只承载当前开发现场；Git/GitHub 是 branch、HEAD、PR、commit、diff、CI
> 的实时事实源。另一台电脑不需要复用本机目录名称或本地缓存。

## 1. Current Task（当前任务）

- 当前任务：PR #89 的 `PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH_V1` 已完成
  squash merge 与 post-merge governance closeout；其后独立的
  `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1` 已在固定 Development holdout 上完成，并创建
  独立 PR #91。审计分类为 `STRUCTURAL_GATE_COLLISION_OBSERVED`，只表示
  研究证据：`CONFIRMED → ABOVE_ENTRY_ZONE` 在 999 个确认事件中发生 595 次；不产生
  production authorization。
  PR #88 的 Deep Wave2 corrective conclusion 也已 squash merge 到 `main`。
- 长期总体交易框架的唯一正式事实源：`docs/TRADING_SYSTEM_SPEC.md`。
- 正式状态：`READY_FOR_DECISION`；PR #86、PR #87、PR #88、PR #89 已合并到 `main`，
  PR #91 保持 OPEN 等待用户决策；本轮没有修改 production strategy。
- 本轮在固定 Development frozen holdout 上完成 PR #88 的预注册三档 Wave2 depth
  corrective research、PR #89 的完整 pre-confirmation causal research，以及
  `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1`；这些研究均为 Development-only，未访问 Final OOS。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支：`main`。
- PR #84、PR #85、PR #87、PR #88 均已 squash merge 到 `main`；`origin/main` 的当前 SHA、main CI
  以及其他动态状态必须从 Git/GitHub 实时查询，不在本文件固定保存。
- 当前分支：`research/system-signal-scarcity-audit-v1`；它从包含 PR #89 squash
  merge 的最新 `main` 创建。PR #89 不改变 production semantics。
- PR #84、PR #85、PR #87、PR #88、PR #89 已合并；其 branch HEAD、base、merge commit 和 CI checks
  等动态状态
  仍须从 Git/GitHub 实时查询。
- Signal Scarcity Audit 为独立 PR #91；其 branch HEAD、base、mergeability 与 CI checks
  仍须从 Git/GitHub 实时查询，且本轮不自动合并。
- PR #82（Node 24 maintenance）保持独立；本轮没有 merge、rebase 或把 maintenance
  改动混入策略 PR，相关动态状态由用户单独从 Git/GitHub 实时查询。

## 3. Completed（已完成）

- 已保留上一轮未提交的
  `research/development/setup01_wave2_to_wave3_structure_scale_diagnostic_v1.json`，
  并在本分支一并纳入；没有 reset、覆盖或丢弃该研究成果。
- `trading/setup01_decision.py` 新增只读 `target_projection`：当前正式 T1/source、
  最近已确认历史阻力及空间、最近/后续 Wave3 Fib extension、ratio 与空间均来自
  既有 candidate/provenance；Decision evaluator、5% gate、2R、nearest-first 和
  T→T+1 未改。
- Daily JSON/Markdown、Dashboard 与 email-safe HTML 已统一展示“正式 T1 / 保守第一
  障碍 / Wave3 结构目标”，包括 NO_TRADE 场景；展示层没有复制 target geometry。
- 新增
  `research/development/setup01_wave2_to_wave3_geometry_attribution_v1.json/.md`；
  81 个 Fib-near 的 identity 最大残差约 `5.2e-14`，BOTH_NEAR 为 `63/81`，归因
  结论仅为描述统计，不形成新 gate。
- 新增 `research/development/setup01_swing_boundary_counterfactual_v1.py` 与 compact
  JSON/Markdown report；固定 `117 → 117 → 117 → 11 → 11 → 6` P1 funnel。6 条
  executed research row 中 5/6 在 stop 前、另 1/6 在无 stop 的结构性终止前清过最近
  confirmed Swing High；1/6 到达 Fib T1，5/6 stop；结果分类为
  `INSUFFICIENT_EVIDENCE`，未转成生产规则；confirmed Swing High hard boundary
  保持现状，不能将该结论解释为 hard boundary 已被证明正确。
- 新增 `research/development/setup01_deep_wave2_structure_quality_v1.py` 与 compact
  JSON/Markdown report；从 frozen artifact/replay 重建 `745` 个 CONFIRMED，固定
  depth bands 为 `345 / 183 / 217`。严格 T 后 Fib1.272 continuation 为
  `225/345`、`147/183`、`195/217`；PR #86 Fib-near `81` 中 `64` 先到 Fib1.272，
  其中 `55` 个为 VERY_DEEP。后续 corrective analysis 增加了与 `r` 无关的
  normalized post-T excursion 与固定 `H1+0.272R / H1+0.618R` hurdles；H1
  max-HIGH median 为 `1.516R / 2.185R / 2.110R`，两项 hurdle success 分别为
  `87.2% / 88.0% / 91.7%` 与 `73.0% / 79.8% / 80.2%`。修正结论为：在已经
  `CONFIRMED` 的条件下没有看到 deep Wave2 continuation 更弱；这不证明
  pre-confirmation early entry 有效，只支持把它作为下一项包含未确认候选的独立
  因果研究假设，不是 early-entry 或 depth gate 的生产授权。
- 注册 `research/protocols/pre_confirmation_early_entry_causal_research_v1.json`，并
  新增对应 research module、focused tests 与 compact JSON/Markdown artifact。
  Cohort 从 primary/alternate strict as-of Wave2 anchor contexts 重建：`2,254`
  contexts，`745` later-CONFIRMED、`947` FAILED、`562` never-CONFIRMED，其中
  `551` 被 current system later-screened、`11` timeout/unresolved；另保留 `12`
  invalid Wave2 geometry contexts。固定 incumbent + 四个 pre-confirmation policies
  均只用 signal-time data，T+1 只取 exact next frozen-session OPEN。
- PR #89 的正式结论为：`close > H1` 确实消耗部分 entry headroom，但同时提供强
  failure filtering；四个简单 early milestones 不足以替代 confirmation，不支持
  production early entry、execution/cost research，或在同一 Development dataset 上
  无约束搜索更多 early filters。production strategy 完全不变。
- 已注册并完成 `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1`：固定 Phase 5J-v3 holdout 的
  `86,305` symbol-sessions 产生 `2,050` candidate lifecycles、`999` confirmed、
  `8` `ENTRY_ALLOWED` 与 `4` exact T+1 executions。aggregate lifecycle funnel 为
  `WATCH 1,004 → ARMED 862 → CONFIRMED 999`（其中 `ARMED → CONFIRMED` 为
  `442/862 = 51.28%`，`420` 个 ARMED lifecycle 未确认；另有 `557` 个 confirmed
  event 没有经历可观测 ARMED 状态）。Decision first-fail 主要为
  `ABOVE_ENTRY_ZONE 595/999`、`TARGET_UPSIDE_BELOW_MINIMUM 277/999`、
  `RR_BELOW_MINIMUM 100/999`；最高 gate pair 的 Jaccard 为 `0.79087`。5% gate
  first-fail 为 `277/999`，但在保持其他 gate 不变的一门反事实中新增
  `ENTRY_ALLOWED=0`；这不是建议移除 5% gate。RR 反事实分解为 stop distance
  `7`、first-target distance `26`、both `14`、insufficient evidence `895`。
  最终 research classification 为 `STRUCTURAL_GATE_COLLISION_OBSERVED`，不改变任何
  production rule。formal pool 与 live Dynamic Candidate 未进入冻结样本，比较状态为
  `INSUFFICIENT_EVIDENCE_FOR_FORMAL_VS_LIVE_CANDIDATE`。
- `ARMED` Dashboard 合同审计：结构 evaluator 已因果暴露 trigger 与 structural
  invalidation，但 DailyDecisionResult 没有透传当前 close/距离/预期 Entry Zone 等
  snapshot。最小后续设计是 `daily_decision_chain` 的只读 context projection，renderer
  只展示；本 PR 不混入 UI 改版。
- 已生成并提交 compact JSON/Markdown artifact；最近 production daily reports
  不足以推断短窗口，状态明确为 `INSUFFICIENT_RECENT_LIVE_SAMPLE`。

## 4. Validation（验证结果）

- focused：`tests.test_system_signal_scarcity_audit` → `14 tests passed`；PR #89
  pre-confirmation causal research tests → `9 tests passed`；#88 deep Wave2 research
  tests 在合并前为 `8 tests passed`。
- full：`python -m unittest discover -s tests -v` → `767 tests passed, OK`；现有
  generic operational shadow checks 继续通过。
- `python -m py_compile` 覆盖 audit research module/test；audit artifact 已重复
  重放并得到相同 canonical SHA，且通过 compactness/self-hash、fixed dataset pin、
  causal as-of、first-fail conservation、all-fail overlap、one-gate-only、exact
  T+1 OPEN、CN/US/time-half/concentration 与 no-outcome controls 核对；protocol/
  artifact JSON syntax 与 `git diff --check` 均通过。
- PR #88、PR #89 均已 squash merge；PR #91 为独立 research PR，等待 CI 与用户
  决策。本轮没有访问 Final OOS、没有参数搜索/threshold sweep、没有真实 holdings
  读取、Sheets 写入、state write 或 broker order；PR #82 保持独立。

## 5. Blocker（当前 Blockers / 决策节点）

- 当前没有实现安全 blocker，也没有 `PROJECT_GOVERNANCE_STATE_CONFLICT`；研究节点为
  `READY_FOR_DECISION`，且 `HANDOFF_CURRENT_AND_CONSISTENT`。
- PR #88 的结论必须限定为 `conditional_on_having_reached_CONFIRMED`：共同 normalized
  excursion 与两项固定 hurdle 没有显示 DEEP/VERY_DEEP continuation 更弱；它不证明
  deep Wave2 更优，不证明 pre-confirmation early entry 有效，不批准 depth gate 或
  production early entry。
- 现有 T-day gates 已排除全部 `DEEP`（183/183）与 `VERY_DEEP`（217/217）进入
  `ENTRY_ALLOWED`，因此新增 depth gate 在本总体上可能高度冗余；当前不实现任何
  depth gate 或 early-entry rule。
- 当前 full causal cohort 已包含 primary/alternate Wave2 contexts、later
  CONFIRMED、FAILED/structural invalidation、never-CONFIRMED、current-system
  screened-out 与 timeout/unresolved rows；没有 survivorship-only cohort。
- 四个 fixed early policy 都在 matched later-CONFIRMED 子集产生更多 normalized
  headroom（约 `+0.170R` 至 `+0.337R` 中位数），但 signaled rows 的
  FAILED/never-CONFIRMED 比例约 `59.9%`–`76.4%`；当前证据不支持进入
  execution/cost research，不支持任何 production entry/confirmation/Stop/Target/RR
  变化。该判断不使用 P&L 或 Final OOS。
- Early Entry 研究已完成，但只支持用户决定是否继续独立 fresh-validation research；
  不支持 execution/cost research，也不产生 production authorization。
- Signal Scarcity Audit 已达到 `READY_FOR_DECISION`：在冻结样本中确认 close 与现有
  Entry Zone upper 的结构性冲突可重复观察（`595/999`），故分类为
  `STRUCTURAL_GATE_COLLISION_OBSERVED`。这只是 Development descriptive research；
  不能据此放宽 confirmation、Entry Zone、5%、RR、Swing 或 Target，也不支持 P&L、
  未来频率或 Final OOS 结论。PR #91 保持 OPEN，不自动合并。
- PR #82（Node 24 maintenance）保持完全独立；交易成本、SETUP_03 formal validation、
  SETUP_04、Final OOS、真实 holdings、broker、state/Sheets mutation 均未启动。

## 6. Next Action（下一步）

1. 从 Git/GitHub 实时核对 PR #91 的最终 head、base、mergeability 与 CI；保持审计
   PR OPEN，等待用户决定下一项研究或架构方向。
2. 任何后续任务前仍须 fetch/pull 并实时核对 Git/GitHub 状态；不得把 PR #82
   maintenance 混入本研究线。

## 7. Constraints（关键约束）

- 总体主线仍是 `Weekly State → Daily State → Swing → Wave Scenario → Fibonacci
  → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management
  → Exit`；四类 Setup 仍为 `SETUP_01`、`SETUP_02`、`SETUP_03`、`SETUP_04`，不把
  SETUP_03 解释为总体策略；SETUP_03 只是四类 Setup 之一的子策略。
- `signal(t)` 只使用 `data <= t`；不使用未来 Swing/ZigZag、future bars、事后最低
  点、MFE/MAE、Final OOS 或 outcome 来优化确认/入场。
- Target-before-RR；T1 是第一 formal target；不以更远 T2/T3 绕过 5% 或 2R。
- T→T+1；T 日只形成 plan；T+1 只读取 exact next-session OPEN；
  `actual_entry != None ⇔ outcome == EXECUTED`。
- CN/US runtime 独立；Candidate-only 不写 state/paper promotion/portfolio/broker；
  generic shadow 不读真实持仓与账户 secrets。
- Paper tracking 只在显式 `--paper-track` 下写独立 ledger；旧 Paper ledger
  forward-only，不历史回填。

## 8. Pitfalls（已知坑）

- 自动日报不能恢复使用裸 `date.today()`；必须保留 exchange-local-date → exact
  session gate 的顺序，节假日/非 session 不得重发上一交易日。
- Dashboard 完整 HTML 只从最终 `daily-report.html` 产物进入附件；正文继续使用
  email-safe 摘要 renderer，不要在邮件层复制第二套 Dashboard renderer。
- Notification 是非核心 delivery；SMTP/Bark 失败不得改写报告状态，但 SMTP 附件
  失败必须保留 `attachment.status=FAILED` metadata。
- 不要因本地目录不同、缺少 service-account env 或没有真实 holdings 就扩大本轮范围；
  GitHub remote 与 PR 是跨设备权威恢复点。
- 不要读取 Final OOS；不要把 PR #82 rebase/merge 到本策略 branch。

## 9. Cross-device resume（跨设备恢复）

`CROSS_DEVICE_HANDOFF_READY`

- authoritative repo: `EFSing/stock-data-pipeline`
- active branch: `research/system-signal-scarcity-audit-v1`
- current PR: PR #91 是独立的 Signal Scarcity Audit research PR，保持 OPEN 等待用户
  决策；PR #89、PR #88、PR #87、PR #86 已 squash merge；PR #82 保持独立。
- working tree expected: clean after the governance commit/push；本轮无 credentials、
  Final OOS 或真实 holdings-derived 数据
- 动态 branch、HEAD、`origin/main`、PR、CI checks 与 merge 状态
  必须在恢复现场时从 Git/GitHub 实时查询；本文件不固定保存这些 SHA、CI run 或
  mergeability 信息。
- first action on another computer:

```bash
git fetch --all --prune
git switch research/system-signal-scarcity-audit-v1
git pull --ff-only origin research/system-signal-scarcity-audit-v1
gh pr view 91 --repo EFSing/stock-data-pipeline
```

公司电脑本地路径可不同；不依赖 `D:\`、本机绝对路径、stash、未上传 artifact、
临时 worktree 或 Codex session memory。下一项任务开始前再从 Git/GitHub 核对动态事实。

---

状态标记：

`READY_FOR_DECISION`

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

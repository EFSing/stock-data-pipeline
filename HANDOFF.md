# HANDOFF — 当前开发现场恢复文件

> 本文件只承载当前开发现场；Git/GitHub 是 branch、HEAD、PR、commit、diff、CI
> 的实时事实源。另一台电脑不需要复用本机目录名称或本地缓存。

## 1. Current Task（当前任务）

- 当前任务：`SETUP_01_DEEP_WAVE2_STRUCTURE_QUALITY_V1`；已完成固定 Phase 5J-v3
  Development frozen holdout 研究，当前独立 research branch 等待 review，未自动
  merge。
- 长期总体交易框架的唯一正式事实源：`docs/TRADING_SYSTEM_SPEC.md`。
- 正式状态：`READY_FOR_DECISION`；PR #86、PR #87 均已合并到 `main`，本轮没有修改
  production strategy。
- 本轮只在固定 Development frozen holdout 上按预注册三档 Wave2 depth 做
  Development research；结构结果只评价 T 之后的路径，未访问 Final OOS。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支：`main`。
- PR #84、PR #85、PR #87 均已 squash merge 到 `main`；`origin/main` 的当前 SHA、main CI
  以及其他动态状态必须从 Git/GitHub 实时查询，不在本文件固定保存。
- 当前分支：`codex/setup01-deep-wave2-structure-quality-v1`；从 PR #87 收口后的
  最新 `main` 建立，PR #88 已创建并等待 review，未自动 merge。
- PR #84、PR #85 已合并；其 branch HEAD、base、merge commit 和 CI checks 等动态状态
  仍须从 Git/GitHub 实时查询。
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
  其中 `55` 个为 VERY_DEEP。结论为 `EARLY_ENTRY_RESEARCH_CANDIDATE`，仅表示应
  优先考虑一项独立因果研究，不是 early-entry 或 depth gate 的生产授权。

## 4. Validation（验证结果）

- focused：deep Wave2 research tests → `4 tests passed`。
- full：`python -m unittest discover -s tests -v` → `740 tests passed, 3 skipped, OK`；
  现有 generic operational shadow checks 继续通过。
- `python -m py_compile` 覆盖本轮 research module；research artifact 重新生成并核对
  frozen hash binding、745 confirmed、117/63/18 category conservation、81 Fib-near、
  Fib identity、三档 depth exhaustive/mutually-exclusive、signal(T) as-of、严格
  T 后 outcome path、现有 Decision parity 与 compact event-detail hash；
  `git diff --check` 通过。
- 本轮没有访问 Final OOS、没有参数搜索/threshold sweep、没有真实 holdings 读取、
  Sheets 写入、state write 或 broker order；PR #82 保持独立。

## 5. Blocker（当前 Blockers / 决策节点）

- 当前没有实现安全 blocker，也没有 `PROJECT_GOVERNANCE_STATE_CONFLICT`；研究节点为
  `READY_FOR_DECISION`。
- 本轮结论为 `EARLY_ENTRY_RESEARCH_CANDIDATE`：DEEP/VERY_DEEP 的结构继续性不低于
  NORMAL_OR_SHALLOW，且固定 81 个 Fib-near 事件中 64 个仍在 T 后先达到 Fib1.272；
  但这一结论只授权记录为下一项独立 Development causal research 候选，不改变
  confirmation、Entry Zone、Stop、Target、RR 或 production Decision。
- 现有 T-day gates 已排除全部 `DEEP`（183/183）与 `VERY_DEEP`（217/217）进入
  `ENTRY_ALLOWED`，因此新增 depth gate 在本总体上可能高度冗余；当前不实现任何
  depth gate 或 early-entry rule。
- PR #82（Node 24 maintenance）保持完全独立；交易成本、正式
  `EARLY_WAVE3_ENTRY_RESEARCH`、SETUP_03 formal validation、SETUP_04、Final OOS
  与 broker execution 仍未启动。

## 6. Next Action（下一步）

1. Review the deep Wave2 structure-quality report and decide whether to approve a separate
   early-entry causal research task。
2. Do not merge this research PR or change production strategy automatically；this branch
   does not implement a depth gate or early-entry rule。
3. 任何后续任务前仍须 fetch/pull 并实时核对 Git/GitHub 状态。

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
- active branch: `codex/setup01-deep-wave2-structure-quality-v1`
- current PR: PR #88 已开放 review、未自动 merge；PR #86、PR #87 已 squash merge；
  PR #82 保持独立
- working tree expected: clean after the research commit/push；本轮无 credentials、Final
  OOS 或真实 holdings-derived 数据
- 动态 branch、HEAD、`origin/main`、PR、CI checks 与 merge 状态
  必须在恢复现场时从 Git/GitHub 实时查询；本文件不固定保存这些 SHA、CI run 或
  mergeability 信息。
- first action on another computer:

```bash
git fetch --all --prune
git switch main
git pull --ff-only origin main
```

公司电脑本地路径可不同；不依赖 `D:\`、本机绝对路径、stash、未上传 artifact、
临时 worktree 或 Codex session memory。下一项任务开始前再从 Git/GitHub 核对动态事实。

---

状态标记：

`READY_FOR_DECISION`

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

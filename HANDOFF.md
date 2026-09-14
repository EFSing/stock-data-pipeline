# HANDOFF — 当前开发现场恢复文件

> 本文件只承载当前开发现场；Git/GitHub 是 branch、HEAD、PR、commit、diff、CI
> 的实时事实源。另一台电脑不需要复用本机目录名称或本地缓存。

## 1. Current Task（当前任务）

- 当前任务：`TARGET_UPSIDE_GATE_V1` + `OPPORTUNITY_FRESHNESS_DIAGNOSTICS_V1`
  已实现并提交到 PR #84。PR #84 不在本轮合并，等待用户 review/merge 决策。
- 正式状态：`TARGET_UPSIDE_FRESHNESS_V1_PR_READY`。
- `UPSIZE GATE` 是正式交易资格语义；`FRESHNESS DIAGNOSTICS` 只读观察，不能
  改变 `ENTRY_ALLOWED`、`NO_TRADE`、排序、仓位、组合分配、批准或 Candidate 晋级。
- 已完成 PR #83 `EMAIL_DAILY_REPORT_V1` 的用户验收与 squash merge；合并 commit
  为 `c5d64b990077cacb8e3c6fc9952e398cdc57899a`。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支：`main`。
- `origin/main`（合并 PR #83 后）为
  `c5d64b990077cacb8e3c6fc9952e398cdc57899a`；该 main CI 已成功。
- 当前分支：`feat/target-upside-freshness-v1`。
- 当前 feature implementation remote HEAD（PR #84 已验证的 exact head）：
  `6d782a58e457a03878d62201113e5326013e0e7f`。
- PR #84：<https://github.com/EFSing/stock-data-pipeline/pull/84>
  当前为 OPEN、MERGEABLE；其 base 是合并 #83 后的 `main`。
- PR #82（Node 24 maintenance）仍是独立 OPEN PR；本轮没有 merge、rebase 或把
  maintenance 改动混入策略 PR。其 base 尚未随 #83 更新，后续由用户单独处理。

## 3. Completed（已完成）

- `trading/risk.py` 现在是 T1 gross upside 的唯一事实源：
  `MIN_TARGET_UPSIDE_PCT=0.05`、`target_upside_pct()`、`target_upside_band()`。
- SETUP_01/02 在既有 data → structure → entry-zone precedence 之后、R/R gate
  同层加入 T1 gate：
  `target_upside_pct < 0.05` → `NO_TRADE / TARGET_UPSIDE_BELOW_MINIMUM`。
  T1 仍为 nearest-first 的第一正式目标；没有切换 T2/T3，没有修改 Target、Fib、
  Wave、structural invalidation、stop、R/R 或 ranking。RR 对象在双重失败时仍保留。
- exact T+1 OPEN 复用冻结 T1，使用 actual OPEN 计算
  `remaining_target_upside_pct`；低于 5% → `SKIP_TARGET_UPSIDE_BELOW_MINIMUM`。
  structural invalidation、below-confirmation、above-entry-zone、missing exact
  session 的旧 precedence 保持不变；T+1 仍只读 OPEN。
- `5% <= upside < 8%` 为 `LOW_UPSIDE`，`>=8%` 为 `PREFERRED_UPSIDE`，仅作
  presentation/research band。
- Daily Decision JSON/Markdown 记录 `target_upside_pct`、band、最低要求、
  `entry_zone_upper_distance_pct`、`confirmation_extension_pct`、T+1 gap 和剩余
  T1 空间，并提供 primary-reason、无重叠的 `freshness_funnel`。
- Candidate-only 走相同 technical gate，但继续保持
  `READ_ONLY_DISCOVERY`、`state_persistence_eligible=false`、
  `promotion_required=true`、`production_execution_eligible=false`、production
  writes=0。
- Paper lifecycle 复用既有 evaluator/executor/PositionOrigin/replay；新诊断通过
  既有 append-only ledger 的 `payload_json` 保留，不回溯或改写旧 Paper 事件。
- Browser Dashboard 与 email-safe HTML 增加“机会新鲜度”和绝对空间人话；
  `TARGET_UPSIDE_BELOW_MINIMUM` 显示目标空间不足、参考价格、T1、实际百分比、
  5% 最低要求和可用 RR 计算依据。600941 regression 覆盖
  `98.16 → 98.6825 ≈ 0.53%`、`NO_TRADE`、目标空间不足与 `RR≈0.14R`。
- SETUP_01/02 focused、T+1、Daily Chain、Candidate/Paper、Dashboard、Email、
  Cloud、generic operational shadow 和 full unittest 均已通过；development
  funnel 也已运行且未访问 Final OOS。

## 4. Validation（验证结果）

- 本地：`python -m unittest discover -s tests -v` → `722 tests ... OK`。
- GitHub PR #84 exact implementation head `6d782a5…`：CI Test Gate、SETUP_01
  generic shadow、SETUP_02 generic shadow、Daily Decision Chain generic shadow、
  Paper lifecycle generic shadow、Portfolio Risk generic shadow 共 6 项成功。
- development funnel：SETUP_01 `745` confirmed，`198` 个 primary
  `TARGET_UPSIDE_BELOW_MINIMUM`；SETUP_02 `213` confirmed，`91` 个同类 gate；
  两个 funnel conservation 与 `final_oos_accessed=false` 通过。
- `git diff --check` 通过；临时 funnel 输出目录已清理。没有新增凭证、真实持仓
  读取、Sheets state write、broker order 或 production schedule。

## 5. Blocker（当前 Blockers / 决策节点）

- 当前没有实现安全 blocker，也没有 `PROJECT_GOVERNANCE_STATE_CONFLICT`。
- PR #84 的剩余节点是用户 review/merge 决策；本轮按请求不自动合并正式策略语义。
- 交易成本模型（commission/slippage/stamp duty/net RR/net upside）、
  `EARLY_WAVE3_ENTRY_RESEARCH`、SETUP_03 formal validation、SETUP_04、Final OOS
  与 broker execution 仍未启动。

## 6. Next Action（下一步）

1. 用户在 GitHub review PR #84，确认 5% T1 gate 与 freshness 只读边界后决定是否
   squash merge。
2. 若合并，另一台电脑先 fetch/pull，再核对新的 `origin/main` 和 merge CI；不要把
   PR #82 Node 24 maintenance 与本策略 PR 混合处理。
3. 若继续做早期入场或交易成本研究，另建独立 decision/protocol；不得在本 PR 内
   根据 freshness funnel 自动调参。

## 7. Constraints（关键约束）

- 总体主线仍是 `Weekly State → Daily State → Swing → Wave Scenario → Fibonacci
  → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management
  → Exit`；四类 Setup 仍为 `SETUP_01`、`SETUP_02`、`SETUP_03`、`SETUP_04`，不把
  SETUP_03 解释为总体策略。
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

- 不要把 `LOW_UPSIDE` / `PREFERRED_UPSIDE` 当 eligibility gate；8% 不是交易门槛。
- 不要在 Dashboard/Email 重新计算另一套 Target、Stop、RR 或信号；只投影 Decision
  已给出的字段。
- 不要把 Daily Chain 的 freshness funnel 与正式交易状态机混为一谈；funnel 的
  分类优先使用 primary terminal/gate reason，重叠失败只计一次。
- 不要因本地目录不同、缺少 service-account env 或没有真实 holdings 就停工；GitHub
  remote 与 PR 是跨设备权威恢复点。
- 不要读取 Final OOS；不要把 PR #82 rebase/merge 到本策略 branch。

## 9. Cross-device resume（跨设备恢复）

`CROSS_DEVICE_HANDOFF_READY`

- authoritative repo: `EFSing/stock-data-pipeline`
- base: `origin/main @ c5d64b990077cacb8e3c6fc9952e398cdc57899a`
- active branch: `feat/target-upside-freshness-v1`
- remote head: `6d782a58e457a03878d62201113e5326013e0e7f`（PR #84 已验证的 feature
  implementation tip；最终 handoff-only docs closeout 后仍以 GitHub live HEAD 为准）
- PR: `#84` — <https://github.com/EFSing/stock-data-pipeline/pull/84>
- working tree expected: `clean`
- first action on another computer:

```bash
git fetch --all --prune
git checkout feat/target-upside-freshness-v1
git pull --ff-only origin feat/target-upside-freshness-v1
```

公司电脑本地路径可不同；不依赖 `D:\`、本机绝对路径、stash、未上传 artifact、
临时 worktree 或 Codex session memory。检查 PR #84 后再决定是否合并。

---

状态标记：

`TARGET_UPSIDE_FRESHNESS_V1_PR_READY`

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

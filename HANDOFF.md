# HANDOFF — 当前开发现场恢复文件

> 本文件只承载当前开发现场；Git/GitHub 是 branch、HEAD、PR、commit、diff、CI
> 的实时事实源。另一台电脑不需要复用本机目录名称或本地缓存。

## 1. Current Task（当前任务）

- 当前任务：`US_CLOUD_DAILY_REPORT_DATA_FRESHNESS_HOTFIX_V1`。这是与
  `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1` 完全独立的 operational hotfix，使用独立
  worktree/branch；当前工作区、PR #82 和另一研究分支均不在本任务范围内。
- 长期总体交易框架的唯一正式事实源：`docs/TRADING_SYSTEM_SPEC.md`。
- 已完成 provider / ephemeral latest fallback 修复与 focused/full regression；生产
  strategy、Wave、Swing、Setup、Entry、Target、Risk、Paper、Sheets 与 broker 语义均未改。
- 当前待用户决定：`PARTIAL_DATA_QUALITY` 在报告 artifact 已成功形成后是否应映射为
  workflow execution success；本 branch 暂不改变既有 CLI exit semantics。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支：`main`。
- PR #84、PR #85、PR #87、PR #88 均已 squash merge 到 `main`；`origin/main` 的当前 SHA、main CI
  以及其他动态状态必须从 Git/GitHub 实时查询，不在本文件固定保存。
- 当前分支：`hotfix/us-cloud-daily-report-freshness-v1`，从当时最新 `origin/main`
  创建；PR #89 已在 base main，且不改变 production semantics。
- PR #84、PR #85、PR #87、PR #88、PR #89 已合并；其 branch HEAD、base、merge commit 和 CI checks
  等动态状态
  仍须从 Git/GitHub 实时查询。
- PR #82（Node 24 maintenance）保持独立；本轮没有 merge、rebase 或把 maintenance
  改动混入策略 PR，相关动态状态由用户单独从 Git/GitHub 实时查询。
- 本 hotfix 尚未自动 merge；独立 PR 创建后仍须等待用户决定，不触碰 PR #82。

## 3. Completed（已完成）

- 已基于 2026-09-16 US Daily Report 的只读 GitHub Actions 日志确认现场：BABA/RKLB
  latest configured paths 均返回 OK，但 actual source collision 使状态为 `单源可用`；
  qfq yfinance 返回 T-1，报告与 Bark/email/artifact 成功后 CLI 仍返回 1。
- `providers.py` 已让 exact-target qfq 在完整但 stale 的 yfinance payload 后尝试现有
  Yahoo Chart fallback；`trading/ephemeral_market_data.py` 已让 verifier 按 actual source
  排除同源候选，并保留 configured/actual/fallback diagnostics。
- 新增回归覆盖 T-1/T、T-1/T-1、Tencent→Sina、独立 fallback 失败、正常双源、partial
  artifact/report 与既有 CLI exit contract；未改变 production strategy 或任何写入边界。
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

## 4. Validation（验证结果）

- focused provider + Cloud Daily Report：`77 tests passed`。
- full：`python -m unittest discover -s tests -v` → `761 tests passed, 3 skipped, OK`；
  generic operational shadow checks 继续通过。
- `python -m py_compile providers.py latest_snapshot.py trading/ephemeral_market_data.py
  scripts/run_cloud_daily_report.py tests/test_validation.py tests/test_cloud_daily_report.py`
  与 `git diff --check` 均通过。
- 本轮仅使用 synthetic/provider stubs 与 GitHub read-only log；没有真实 holdings、Final
  OOS、Sheets/state/cache/artifact raw-data 写入或 broker order。PR #82、PR #88、PR #89
  与 Signal Scarcity Audit 的 branch/history 保持独立。

## 5. Blocker（当前 Blockers / 决策节点）

- 当前没有 provider 实现 blocker，也没有 `PROJECT_GOVERNANCE_STATE_CONFLICT`。
- `READY_FOR_DECISION_REPORT_EXIT_SEMANTICS`：当前 CLI 仍只将 `SUCCESS` 与
  `SKIPPED_NON_SESSION` 映射为 exit 0；报告已生成但数据质量为
  `PARTIAL_DATA_QUALITY` 时仍 exit 1。是否把“执行成功”和“数据质量警告”分离为
  workflow success，需要用户/运维明确决定，本 branch 未擅自修改。
- `validate_quotes` 的双源标准保持严格：同一 actual source 仍是 `单源可用`；若下一
  独立 source 不可用，日报继续保留 `PARTIAL_DATA_QUALITY`，不伪造成 `SUCCESS`。
- PR #88 / PR #89 的 Development-only 研究结论与 `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1`
  的独立状态不属于本 hotfix scope；PR #82 保持完全独立。

## 6. Next Action（下一步）

1. 等待用户决定 `READY_FOR_DECISION_REPORT_EXIT_SEMANTICS`：PARTIAL report 是否应成为
   workflow execution success；在决定前保持当前 CLI exit 1。
2. 等待独立 PR #90 的 CI/review 与用户决定；不要自动 merge。
3. 后续任务前仍须 fetch/pull 并实时核对 Git/GitHub 状态，不要触碰 PR #82、PR #89 或
   `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1`。

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
- Cloud verifier 的独立性按返回 Quote 的 actual source 判断，不能按 configured source
  名称判断；primary fallback 与 verifier fallback 必须保留可解释的 source notes。
- 不要因本地目录不同、缺少 service-account env 或没有真实 holdings 就扩大本轮范围；
  GitHub remote 与 PR 是跨设备权威恢复点。
- 不要读取 Final OOS；不要把 PR #82 rebase/merge 到本策略 branch。

## 9. Cross-device resume（跨设备恢复）

`CROSS_DEVICE_HANDOFF_READY`

- authoritative repo: `EFSing/stock-data-pipeline`
- active branch: `hotfix/us-cloud-daily-report-freshness-v1`
- current PR: 独立 Cloud Daily Report hotfix PR #90 已创建，未 merge；PR #82、PR #89 与
  `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1` 保持独立。
- working tree expected: clean after the governance commit/push；本轮无 credentials、Final
  OOS 或真实 holdings-derived 数据。
- 动态 branch、HEAD、`origin/main`、PR、CI checks 与 merge 状态
  必须在恢复现场时从 Git/GitHub 实时查询；本文件不固定保存这些 SHA、CI run 或
  mergeability 信息。
- first action on another computer:

```bash
git fetch --all --prune
git worktree list
git status --short --branch
```

公司电脑本地路径可不同；不依赖 `D:\`、本机绝对路径、stash、未上传 artifact、
临时 worktree 或 Codex session memory。下一项任务开始前再从 Git/GitHub 核对动态事实；
如需继续本 hotfix，使用 `hotfix/us-cloud-daily-report-freshness-v1` 的隔离 worktree。

---

状态标记：

`READY_FOR_DECISION_REPORT_EXIT_SEMANTICS`

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

`PR_READY_FOR_USER_DECISION`

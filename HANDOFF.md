# HANDOFF — 当前开发现场恢复文件

> 本文件只承载当前开发现场；Git/GitHub 是 branch、HEAD、PR、commit、diff、CI
> 的实时事实源。另一台电脑不需要复用本机目录名称或本地缓存。

## 1. Current Task（当前任务）

- 当前任务：`SETUP_01_TARGET_PROJECTION_AND_GEOMETRY_ATTRIBUTION`；分开展示
  Wave3 structure target 与 overhead confirmed swing high，并完成 81 个
  Wave3 Fib-near event 的纯几何描述归因，不修改正式交易语义。
- 长期总体交易框架的唯一正式事实源：`docs/TRADING_SYSTEM_SPEC.md`。
- 正式状态：`PR_OPEN_AWAITING_CHECKS_AND_REVIEW`。
- 本轮只消费现有 Decision/target provenance 与上一轮 research-only artifact；几何
  归因没有重放生产结果、没有读取 Final OOS、forward return、MFE/MAE、P&L 或其他
  outcome 信息。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支：`main`。
- PR #84、PR #85 均已 squash merge 到 `main`；`origin/main` 的当前 SHA、main CI
  以及其他动态状态必须从 Git/GitHub 实时查询，不在本文件固定保存。
- 当前分支：`codex/setup01-target-geometry-diagnostic`；本轮独立 PR #86 已创建并保持
  open，base=`main`，未自动 merge；GitHub checks 仍在运行。
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

## 4. Validation（验证结果）

- focused：SETUP_01 Decision、geometry attribution、Dashboard、email、Daily Chain
  共 `90 tests passed`。
- full：`python -m unittest discover -s tests -v` → `732 tests passed, 3 skipped, OK`；
  现有 generic operational shadow checks 继续通过。
- `python -m py_compile` 覆盖本轮代码、研究模块与新增测试；research artifact 重新
  生成并核对 745/198/81 与分组守恒；`git diff --check` 通过。
- 本轮只做 T 日既有字段几何分解；没有 T+1、Final OOS、forward/outcome 指标、
  真实 holdings 读取、Sheets 写入或 broker order。

## 5. Blocker（当前 Blockers / 决策节点）

- 当前没有实现安全 blocker，也没有 `PROJECT_GOVERNANCE_STATE_CONFLICT`。
- PR #86 等待 GitHub checks 与用户 review/decision；本轮没有提出或实施新的 Wave1 最低涨幅/ATR、
  Wave2 最大回撤、确认时点或其他 production threshold。
- 下一步真正需要用户决定：是否继续让所有 confirmed swing high 参与正式 first-
  reward boundary；以及是否对深 Wave2 / 确认时点 / Wave1 尺度做独立策略研究。
- PR #82（Node 24 maintenance）保持完全独立；交易成本、`EARLY_WAVE3_ENTRY_RESEARCH`、
  SETUP_03 formal validation、SETUP_04、Final OOS 与 broker execution 仍未启动。

## 6. Next Action（下一步）

1. 等待并核对 PR #86 的 GitHub checks；不自动 merge。
2. 等待用户决定 first-reward boundary 与后续策略研究方向；本轮不把描述统计转成规则。
3. 从 `main` 开始任何后续任务前仍须 fetch/pull 并实时核对 Git/GitHub 状态。

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
- active branch: `codex/setup01-target-geometry-diagnostic`
- current PR: #86，base=`main`，状态 OPEN、未自动 merge；PR #82 保持独立
- working tree: 本轮代码、测试、docs 与 research-only artifacts 待提交；无 credentials、
  Final OOS 或真实 holdings-derived 数据
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

`PR_OPEN_AWAITING_CHECKS_AND_REVIEW`

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

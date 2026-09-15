# HANDOFF — 当前开发现场恢复文件

> 本文件只承载当前开发现场；Git/GitHub 是 branch、HEAD、PR、commit、diff、CI
> 的实时事实源。另一台电脑不需要复用本机目录名称或本地缓存。

## 1. Current Task（当前任务）

- 当前任务：`CLOUD_DAILY_REPORT_DELIVERY_V1` 已实现并提交到 PR #85；PR #84 已按用户
  批准 squash merge。本轮不处理 PR #82。
- 长期总体交易框架的唯一正式事实源：`docs/TRADING_SYSTEM_SPEC.md`。
- 正式状态：`CLOUD_DAILY_REPORT_DELIVERY_V1_PR_READY`。
- 本轮只修复 Cloud Daily Report delivery/runtime：自动 T 日按目标交易所本地日期
  推导并继续通过 ExactExchangeCalendarProvider gate；SMTP 保留摘要并增加完整
  Dashboard HTML 附件。没有改变交易策略或生产写入语义。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支：`main`。
- PR #84 已 squash merge 到 `main`；`origin/main` 的当前 SHA、main CI 以及其他
  动态状态必须从 Git/GitHub 实时查询，不在本文件固定保存。
- 当前分支：`fix/cloud-daily-report-delivery-v1`。
- PR #85：<https://github.com/EFSing/stock-data-pipeline/pull/85>；当前语义状态为
  OPEN，已达到 review/merge 门禁；其 branch HEAD、base、mergeability 和 CI checks
  必须从 Git/GitHub 实时查询。
- PR #82（Node 24 maintenance）保持独立；本轮没有 merge、rebase 或把 maintenance
  改动混入策略 PR，相关动态状态由用户单独从 Git/GitHub 实时查询。

## 3. Completed（已完成）

- 自动调度未传日期时，`scripts/run_cloud_daily_report.py` 通过
  `ExactExchangeCalendarProvider` 将 timezone-aware 当前时刻转换为 XSHG/XNYS
  本地 civil date，再复用既有 `is_session` / `completed_session` gate；显式
  `--date/--trade-date` 保持原样。跨 UTC 午夜、CN/US 收盘后、节假日/非 session
  的 fail-closed 语义均有 deterministic regression 覆盖，不回退到旧 session。
- SMTP 保留纯文本摘要和 mobile-friendly email-safe HTML body，并从最终
  `daily-report.html` 产物增加 UTF-8 `text/html` 完整 Dashboard 附件；CN/US 使用
  人类可读文件名。附件与最终 artifact 使用同一渲染文本，附件失败在 notification
  metadata 中明确为 `FAILED`，仍保持非核心 blocker 语义。
- artifact allowlist 仍只有 `daily-report.json` 与 `daily-report.html`；没有新增 raw
  行情、QFQ、Sheets、凭证或其他内部文件输出。
- PR #84 合并后的 main 已作为本分支基线；没有混入 PR #82 或策略、broker、state
  write 相关改动。

## 4. Validation（验证结果）

- 本地 focused：Cloud Daily Report / calendar / notifications / email 共 `47` tests
  passed。
- 本地 full：`python -m unittest discover -s tests -v` → `727 tests passed,
  3 skipped, OK`；`git diff --check` 通过。
- PR #85 相关 CI、generic operational shadow checks 已成功；docs-only HANDOFF
  closeout 后须从 GitHub 实时确认最新 checks。
- US workflow_dispatch SMTP smoke 使用明确完成日 `2026-09-14` 成功：报告
  `SUCCESS`，email `SENT`，附件 `SENT`，文件名为
  `美股交易日报_2026-09-14.html`，Content-Type 为 `text/html; charset=utf-8`。
  该运行 metadata 同时确认 artifact allowlist、`state_write=false`、
  `broker_orders=NONE`；workflow artifact 页面显示生成了一个 `us-daily-report`
  artifact。

## 5. Blocker（当前 Blockers / 决策节点）

- 当前没有实现安全 blocker，也没有 `PROJECT_GOVERNANCE_STATE_CONFLICT`。
- PR #85 的剩余节点是用户 review/merge 决策；本轮按请求不自动合并。
- 交易成本模型（commission/slippage/stamp duty/net RR/net upside）、
  `EARLY_WAVE3_ENTRY_RESEARCH`、SETUP_03 formal validation、SETUP_04、Final OOS
  与 broker execution 仍未启动。

## 6. Next Action（下一步）

1. 用户在 GitHub review 并手动决定是否 squash merge PR #85；不要自动 merge。
2. 合并后另一台电脑先 fetch/pull，再核对新的 `origin/main` 和 merge CI；不要把
   PR #82 Node 24 maintenance 与本 delivery PR 混合处理。
3. 若继续做策略、早期入场或交易成本研究，另建独立 task/decision/protocol；不得
   在本 PR 内扩大范围。

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
- active branch: `fix/cloud-daily-report-delivery-v1`
- PR: `#85` — <https://github.com/EFSing/stock-data-pipeline/pull/85>
- working tree expected: `clean`
- 动态 branch、HEAD、`origin/main`、PR open/mergeability、CI checks 与 merge 状态
  必须在恢复现场时从 Git/GitHub 实时查询；本文件不固定保存这些 SHA、CI run 或
  mergeability 信息。
- first action on another computer:

```bash
git fetch --all --prune
git checkout fix/cloud-daily-report-delivery-v1
git pull --ff-only origin fix/cloud-daily-report-delivery-v1
```

公司电脑本地路径可不同；不依赖 `D:\`、本机绝对路径、stash、未上传 artifact、
临时 worktree 或 Codex session memory。检查 PR #85 后再决定是否合并。

---

状态标记：

`CLOUD_DAILY_REPORT_DELIVERY_V1_PR_READY`

`PR_FULLY_READY`

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

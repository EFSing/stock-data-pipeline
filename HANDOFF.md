# HANDOFF — 当前开发现场恢复文件

> 定位：让另一台电脑 / 新 Codex 会话 clone/pull 后，只读本文件 +
> `docs/CURRENT_STATUS.md` 就能继续当前开发。
> 本文件不是历史流水账：历史由 Git / PR / commit 保存；branch、HEAD、PR、CI、
> merge 状态以 GitHub 实时事实为准。治理规则与文件职责见 `AGENTS.md`。

## 1. Current Task（当前任务）

- 当前唯一任务：**Production Daily Decision Chain V1（Human-in-the-loop）**。
  在现有 frozen Wave / SETUP_01 / SETUP_02 Decision/Risk / Portfolio Risk /
  Position Management 之上，完成正式 `策略股票池` 驱动的每日只读决策输出；用户保留
  最终交易决定。
- 只做 `SETUP_01` / `SETUP_02`，不重开 `SETUP_03`、不做 `SETUP_03 formal
  validation`、不开发 `SETUP_04`、不接 Candidate Universe、不接 broker/order，
  不自动批准交易；默认 read-only，state write 必须继续显式 `--write-state`。
- 治理体系瘦身 v1 已完成：PR #73 已合并；此前关于 PR #73 `OPEN / 等待 merge`
  的现场描述已经过期。动态 branch / PR / CI 状态以 GitHub 实时事实为准。
- 本轮实现分支：`codex/production-daily-decision-chain-v1`；PR #74 已创建并为
  OPEN；只保留这一 feature PR，不自动 merge。PR final tip / checks 以 GitHub
  实时状态为准。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支 `main`。
- 本任务开始时真实仓库状态：本地 `main` = `origin/main`、working tree clean、
  GitHub 无 open PR、无未提交业务代码；最后核对日期 `2026-09-06`。
  本轮已从该基线创建 feature branch 并打开 PR #74；此后一律以 Git / GitHub
  实时结果为准，不信任本文件中的历史描述。
- 治理文件职责现为（详见 `AGENTS.md`）：
  - Git/GitHub = 动态工程事实源；
  - `HANDOFF.md` = 当前开发现场恢复；
  - `docs/CURRENT_STATUS.md` = 系统能力地图；
  - `docs/DECISION_LOG.md` = 长期有效决策及理由。
- `HANDOFF_CURRENT_AND_CONSISTENT` 表示：本文件能恢复现场、CURRENT_STATUS 与
  系统能力无实质矛盾、长期 Decision 无已知冲突、无会让下一设备错误继续的重大
  状态错误。它不要求本文件保存实时 main SHA / CI run ID，也不要求 docs-only
  commit 后重新完整验证。
- 当前不存在 `PROJECT_GOVERNANCE_STATE_CONFLICT`。实时 PR 状态以 GitHub 上的
  PR #74 与 `git fetch origin` 结果为准。

## 3. Completed（已完成事项 — 当前任务上下文）

- 完成治理问题审计：原 HANDOFF（约 106KB）与 CURRENT_STATUS 保存了大量历史
  Engineering Event / 运行证据 / CI run ID / commit SHA，造成文档维护与 reconcile
  成本高；`tests/test_governance.py` 仍把旧模型（固定 12 节 HANDOFF、文档内嵌
  frozen SHA）锁死。
- 已重写 `HANDOFF.md`、`docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`：
  - 删除历史事件流水账、PR 过程、测试计数、CI run ID、硬编码 commit SHA；
  - CURRENT_STATUS 改为能力地图（行情、Candidate、Wave/Swing、SETUP_01/02/03/04、
    Daily Decision Chain、Portfolio Risk、Production wiring、Broker）；
  - DECISION_LOG 只保留长期策略 / 架构 / 研究边界决策；机器可读 frozen 文件
    继续由 `research/` 下 JSON 与 registry 承载身份，不在 governance 文档复制。
- 已最小同步 `AGENTS.md`：定义各治理文件职责、`HANDOFF_CURRENT_AND_CONSISTENT`
  与 `PROJECT_GOVERNANCE_STATE_CONFLICT` 的新语义，并写入 docs-only 轻量验证规则。
- 已同步 `tests/test_governance.py` 到新模型；未新增 validator / registry /
  protocol / CI workflow / 测试框架。
- 近期已完成且已合并的能力里程碑（背景，非流水账）：生产 QFQ 刷新、策略预算与
  NAV 解耦、bounded Candidate Universe、Candidate/Strategy shadow bridge、
  一次性 Tushare CN 基准归档；详见 `docs/CURRENT_STATUS.md` 能力地图与 Git
  历史。
- 本轮已核对正式五表契约、CN/US 账户隔离、exact exchange-calendar proof、QFQ
  数据质量门与现有 frozen Daily Chain/Portfolio Risk/Position Management 边界。
- 已完成最小 production glue：正式 `策略股票池` → latest/QFQ → account-isolated
  Daily Chain；默认 `--run` 只读输出 JSON/Markdown，`--write-state` 是唯一显式
  状态写入开关；`--approve-event` 与 `--allocation-budget` 保持人工在环。
- 已覆盖 read-only 不写状态、stale QFQ 逐标的 fail-closed、显式 state write、无
  broker order 与 CN/US 隔离回归；未接 Candidate、SETUP_03/04 或自动调度。
- 已按 bounded smoke 结论记录 HiThink Financial API（同花顺金融数据服务）仍是
  未完成验证的未来辅助源，本 V1 不依赖、不接入，也不把它描述成已验证的 iFinD
  替代品。

## 4. Blocker（当前 Blockers / 决策节点）

- PR #73 已合并，不再是 blocker；本轮实现、文档、本地验证与 PR checks 已完成。
  PR #74 等待用户 review / merge，不自动 merge。
- 只有当现有 frozen semantics 无法推导、而实现会改变正式业务语义时，才停在
  `READY_FOR_DECISION` 请求用户选择；普通代码接线、测试和文档处理不构成 blocker。

## 5. Next Action（下一步动作）

1. 用户 review / merge PR #74；不自动 merge。
2. 若 PR 继续修改，重新核对本地分支、GitHub checks 与
   `HANDOFF_CURRENT_AND_CONSISTENT`；若合并，按 `AGENTS.md` 规则以新的明确授权
   任务为准。

## 6. Important Unfinished / Deferred（重要未完成事项）

- Production 策略链：Daily Decision Chain / Portfolio Risk / SETUP_01/02 语义已
  frozen，人工触发的 account-isolated 只读 `--run` 已可用；自动 daily schedule、
  自动 state write 与 broker 仍未启用。`--run --write-state` 必须显式授权。
- SETUP_03：formal validation 未执行，无 production tolerance；继续需新的明确
  研究决策 + 新 protocol/version。
- Candidate Universe 尚未接入 production strategy chain。
- HiThink Financial API 只有 bounded transport smoke，财务字段、复权公式/as-of
  与长历史覆盖仍未验证；继续保持未接入状态。
- （治理层）GitHub CI 的 `ci.yml` 仍对所有 PR/main push 跑完整 unittest；本次未
  改 workflow（不新增 validator / CI）。若未来要彻底消除 docs-only push 的完整 CI
  成本，需单独决策是否给 `ci.yml` 加 paths-ignore。

## 7. Constraints（当前必须遵守的关键约束）

- 策略身份：总体主线是 `Weekly State → Daily State → Swing → Wave Scenario →
  Fibonacci → Setup → Entry/Decision → Invalidation/Target → Risk/Position
  Management → Exit`。第一版四类 Setup：`SETUP_01`（Wave 2 → Wave 3）、
  `SETUP_02`（Wave 3 Continuation）、`SETUP_03`（Platform Breakout）、
  `SETUP_04`（Extreme Fear Reversal）；`SETUP_03` 只是其中一个子策略。改变总体
  路线需用户批准并写入 DECISION_LOG。
- 研究 / 生产安全：`signal(t)` 只用 `data <= t`；禁止未来 Swing / ZigZag 回填、
  look-ahead、OOS 泄漏、人为制造 Target/RR、按结果删交易或调参。
- T→T+1、Target-before-RR、Wave 主／备情景、CN/US runtime 独立、
  `allocation_budget` 总预算语义与 Portfolio Risk 公式均为 frozen，不随意改。
- 生产写入边界：无券商 / order；策略 state write 需显式授权；Google Sheets 凭证
  只经 Secrets / 本机环境变量注入，不写入仓库或文档。
- 真实持仓 shadow 属 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时
  `NOT_RUN_USER_PRIVACY`；缺少真实持仓不是 SETUP_01 等核心开发的默认 blocker。
- docs-only 更新只做轻量检查（`git diff --check`、Markdown/JSON 语法、必要 grep），
  不得触发完整 unittest / runtime shadow，也不得因此循环更新 docs。

## 8. Pitfalls（已知坑 / 容易重复犯的错误）

- 把 HANDOFF/CURRENT_STATUS 当历史档案：旧文件曾积累 106KB+ 事件流水与 CI run
  ID。以后只写“当前现场”与“能力状态”；历史查 Git。
- 把治理一致性建立在硬编码 SHA / CI run ID 上：docs commit 会改变 HEAD，造成
  无限 reconcile。动态事实一律实时查 GitHub。
- 本地 `origin/main` 过期后仍当作基线：关键决策前 `git fetch origin`，并以
  `gh pr list/view` 对账；无法对账且会改变下一步时才标记
  `PROJECT_GOVERNANCE_STATE_CONFLICT`。
- 把 docs-only 提交当成需要重跑全套验证的实质修改：docs-only 只需轻量检查；
  `tests/test_governance.py` 是现有轻量 governance 回归，不代表要重跑 runtime
  shadow。
- 误删长期决策：DECISION_LOG 清理只删 PR/merge/CI/验证过程；T→T+1、
  allocation_budget、Portfolio Risk 公式、SETUP_03 冻结边界等长期语义必须保留。

## 9. Quick Reference（速查）

- `AGENTS.md`：唯一入口与治理规则（含文件职责、docs-only 验证、两个 marker 定义）。
- `docs/CURRENT_STATUS.md`：能力地图。
- `docs/DECISION_LOG.md`：长期决策。
- `docs/TRADING_SYSTEM_SPEC.md`：总体策略唯一正式事实源。
- `docs/ARCHITECTURE.md`：真实代码架构；`docs/FROZEN_ARTIFACT_REGISTRY.json`：
  非 Git frozen artifact 的机器可读登记。

---

状态标记：

`PR_FULLY_READY`

`HANDOFF_CURRENT_AND_CONSISTENT`

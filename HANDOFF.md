# HANDOFF — 当前开发现场恢复文件

> 定位：让另一台电脑 / 新 Codex 会话 clone/pull 后，只读本文件 +
> `docs/CURRENT_STATUS.md` 就能继续当前开发。
> 本文件不是历史流水账：历史由 Git / PR / commit 保存；branch、HEAD、PR、CI、
> merge 状态以 GitHub 实时事实为准。治理规则与文件职责见 `AGENTS.md`。

## 1. Current Task（当前任务）

- 当前唯一任务：**治理体系最小瘦身（governance slim v1）**，只改治理文档与
  governance 约束，不触碰行情 / Candidate / Wave / Fibonacci / Setup / Decision /
  Portfolio Risk / 生产写入 / broker 等业务代码或交易语义。
- 目标：把 `HANDOFF.md` 收敛为现场恢复文件、`docs/CURRENT_STATUS.md` 收敛为能力
  地图、`docs/DECISION_LOG.md` 收敛为长期决策；明确 docs-only 不触发完整验证。
- 工作分支：`codex/governance-slim-v1`。当前状态：
  `PR_FULLY_READY`（等待用户 review / merge，不自动 merge）。
- 本任务完成并合并前，不启动任何新的工程 / 研究 / production 任务。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支 `main`。
- 本任务开始时真实仓库状态：本地 `main` = `origin/main`、working tree clean、
  GitHub 无 open PR、无未提交业务代码；最后核对日期 `2026-09-06`。
  此后一律以 `git fetch origin` + `gh pr list` 的实时结果为准，不信任本文件中的
  历史描述。
- 治理文件职责现为（详见 `AGENTS.md`）：
  - Git/GitHub = 动态工程事实源；
  - `HANDOFF.md` = 当前开发现场恢复；
  - `docs/CURRENT_STATUS.md` = 系统能力地图；
  - `docs/DECISION_LOG.md` = 长期有效决策及理由。
- `HANDOFF_CURRENT_AND_CONSISTENT` 表示：本文件能恢复现场、CURRENT_STATUS 与
  系统能力无实质矛盾、长期 Decision 无已知冲突、无会让下一设备错误继续的重大
  状态错误。它不要求本文件保存实时 main SHA / CI run ID，也不要求 docs-only
  commit 后重新完整验证。
- 当前不存在 `PROJECT_GOVERNANCE_STATE_CONFLICT`。

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
  一次性 Tushare CN 基准归档；此后没有新的工程任务启动。详见
  `docs/CURRENT_STATUS.md` 能力地图与 Git 历史。

## 4. Blocker（当前 Blockers / 决策节点）

- 无工程 / 研究 blocker。唯一等待项：用户 review 并合并本治理 PR
  （`codex/governance-slim-v1`）。
- 合并后建议：删除本地与远端该分支（可选）；然后以 `docs/CURRENT_STATUS.md` 的
  能力状态决定下一个明确授权的任务。不要在没有用户授权时自行启动下一阶段。

## 5. Next Action（下一步动作）

1. 新会话开始：按 `AGENTS.md` 顺序读取本文件、CURRENT_STATUS、DECISION_LOG，
   再 `git fetch origin` + `gh pr list` / `gh pr view` 核对实时 PR 状态。
2. 若本治理 PR 尚未合并：review diff（应只有治理文档、AGENTS.md 与
   `tests/test_governance.py`），确认无业务代码 / 交易语义变化后 squash merge。
3. 若已合并：`git fetch origin && git switch main && git pull`，随后选择下一个
   明确授权的开发 / 研究任务。

## 6. Important Unfinished / Deferred（重要未完成事项）

- Production 策略链：Daily Decision Chain / Portfolio Risk / SETUP_01/02 语义已
  frozen，但每日自动 production 决策链仍未启用；`--run --write-state` 必须显式
  授权。Strategy state 写入未启用；broker 未连接。
- SETUP_03：formal validation 未执行，无 production tolerance；继续需新的明确
  研究决策 + 新 protocol/version。
- Candidate Universe 尚未接入 production strategy chain。
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

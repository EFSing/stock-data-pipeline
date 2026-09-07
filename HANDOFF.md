# HANDOFF — 当前开发现场恢复文件

> 定位：让另一台电脑 / 新 Codex 会话 clone/pull 后，只读本文件 +
> `docs/CURRENT_STATUS.md` 就能继续当前开发。
> 本文件不是历史流水账：历史由 Git / PR / commit 保存；branch、HEAD、PR、CI、
> merge 状态以 GitHub 实时事实为准。治理规则与文件职责见 `AGENTS.md`。

## 1. Current Task（当前任务）

- 本轮唯一任务：**修正 Candidate Universe 接入 Production Daily Decision Chain
  V1 的生命周期边界**；当前在 feature branch 上完成实现、回归与文档收尾。
- 基线 `main` 已包含 Production Daily Decision Chain V1；本轮新增 Candidate
  runtime 仍保持人工触发、account-isolated、默认只读。
- 本轮已将现有 frozen Wave / SETUP_01 / SETUP_02 Decision/Risk / Portfolio Risk /
  Position Management 接入正式 `策略股票池` 驱动的每日只读决策输出；用户保留最终
  交易决定。
- 只做 `SETUP_01` / `SETUP_02`，不重开 `SETUP_03`、不做 `SETUP_03 formal
  validation`、不开发 `SETUP_04`、不接 scheduler/HiThink/broker/order，不自动
  批准交易；默认 read-only，state write 必须继续显式 `--write-state`。
- Dynamic Candidate 正式确定为 discovery-only：Candidate-only 只进入当日只读分析
  与报告，不进入 state write、published event、T→T+1 pending/settlement、Portfolio
  allocation 或 production execution；必须人工加入正式 `策略股票池` 并补齐现有
  production prerequisites 后重新运行。Candidate overlap 正式池时按正式池生命周期，
  正式池之外的已有持仓仍只做 Position Management。
- 治理体系瘦身 v1 已完成：PR #73 已合并；此前关于 PR #73 `OPEN / 等待 merge`
  的现场描述已经过期。动态 branch / PR / CI 状态以 GitHub 实时事实为准。
- PR #74 已 squash merge；本轮 Candidate 接入的 PR #75 已创建并保持未合并，
  feature branch / PR / HEAD / CI 动态状态仍以 Git / GitHub 实时事实为准。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支 `main`。
- PR #74 已 squash merge 到 `main`；本轮 Candidate 接入工作现场位于
  `codex/candidate-daily-chain-v1` / PR #75，PR 保持未合并；branch、PR、HEAD、
  working tree 与 GitHub 状态仍须以实时结果为准，不信任本文件中的历史描述。
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
  PR #75 与 `git fetch origin` 结果为准。

## 3. Completed（已完成事项 — 当前任务上下文）

- Production Daily Decision Chain V1 已完成 PR #74 squash merge，并正式进入
  `main`；本轮 merge closeout 已完成。
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
- 已完成最小 production glue：正式 `策略股票池` + active `策略持仓` + 当日动态
  Candidate Set → 同一个 account-isolated Daily Chain；正式池、持仓与 Candidate
  以共享 market-aware identity 去重，并保留报告 provenance；正式池与非正式输入
  分成 stateful/read-only persistence groups 后合并报告。
- 已修正生命周期漏洞：Candidate-only 永远使用 `READ_ONLY_DISCOVERY`，不受
  `--approve-event`、`--allocation-budget` 或 `--write-state` 绕过；只有人工 promotion
  到正式 `策略股票池` 后才可进入正式策略生命周期。
- Candidate Stage A 使用 60-bar yfinance batch selector，Stage B 只请求 included
  Candidate 的既有 yfinance QFQ 深历史；Candidate 不写 `策略股票池`。默认 `--run`
  只读输出 JSON/Markdown；`--write-state` 仍是唯一显式状态写入开关，但只对正式
  `策略股票池` 输入生效；`--approve-event` 与 `--allocation-budget` 保持人工在环，
  且不能替代 Candidate promotion。
- 已覆盖 read-only 不写状态、Candidate 两阶段/去重/失败闭环、持仓独立管理、无
  broker order 与 CN/US 隔离回归；未触碰 SETUP_03/04 或自动调度。
- 已按 bounded smoke 结论记录 HiThink Financial API（同花顺金融数据服务）仍是
  未完成验证的未来辅助源，本 V1 不依赖、不接入，也不把它描述成已验证的 iFinD
  替代品。

## 4. Blocker（当前 Blockers / 决策节点）

- PR #73 与 PR #74 均已合并；本轮 PR #75 的实现、文档与本地回归已完成，当前本地
  提交尚未因 GitHub 命令行认证缺失推送，PR #75 保持未合并等待远端 head/CI 刷新与
  review；最新远端 branch/CI 结论必须以 GitHub 实时状态为准。
- 当前没有已知的业务语义 blocker。若同一 market 存在多个 enabled strategy
  accounts，Candidate runtime 必须停在 `READY_FOR_DECISION`，不猜账户归属。
- 只有当现有 frozen semantics 无法推导、而实现会改变正式业务语义时，才停在
  `READY_FOR_DECISION` 请求用户选择；普通代码接线、测试和文档处理不构成 blocker。

## 5. Next Action（下一步动作）

1. 在 GitHub 已认证的命令行环境推送当前本地 PR #75 分支，并确认新 head 的 CI
   checks；不自动 merge。
2. CI 通过后由用户 review / merge PR #75；若继续修改，重新核对本地分支、GitHub
   checks 与 `HANDOFF_CURRENT_AND_CONSISTENT`。
3. 本轮结束后不启动 scheduler、HiThink、SETUP_03/04 或 broker 开发。

## 6. Important Unfinished / Deferred（重要未完成事项）

- Production Daily Decision Chain V1 已正式进入 `main`：人工触发、account-isolated、
  默认只读 production `--run` 已可用；state write 仍只允许显式 `--write-state`；
  人工批准仍通过明确 event identity；`allocation_budget` 仍由人工显式提供。
  无 broker、无自动下单、无自动 daily schedule。
- SETUP_03：formal validation 未重开（仍未执行），无 production tolerance；继续需新的明确
  研究决策 + 新 protocol/version。
- SETUP_04：未实现。
- Candidate Universe 已接入人工触发的 production strategy chain；Candidate-only
  需要人工 promotion 才能进入正式生命周期；真实 private smoke 仍需在凭证与隐私
  安全允许时执行。
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

`READY_FOR_DECISION`

`HANDOFF_CURRENT_AND_CONSISTENT`

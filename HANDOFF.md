# HANDOFF — 当前开发现场恢复文件

> 定位：让另一台电脑 / 新 Codex 会话 clone/pull 后，只读本文件 +
> `docs/CURRENT_STATUS.md` 就能继续当前开发。
> 本文件不是历史流水账：历史由 Git / PR / commit 保存；branch、HEAD、PR、CI、
> merge 状态以 GitHub 实时事实为准。治理规则与文件职责见 `AGENTS.md`。

## 1. Current Task（当前任务）

- 当前任务：PR #81 的 Cloud Daily Report V1 + Mobile Dashboard V2 已完成 CN/US
  live smoke 验收并完成正式 cutover；旧 asia/us workflow 的 schedule 已移除，原有
  workflow_dispatch、latest/full 手工维护能力、Google Sheets credentials contract
  与 legacy 手工逻辑均保留。正在完成 PR #81 的 exact-head CI、merge 与 main closeout；
  本轮运行始终 read-only，不写 production state、paper ledger、策略输入或 broker。
- 当前工作分支：`feat/cloud-daily-report-mobile-v1`；PR #81 已创建，等待 review 与
  用户决定；PR 未 merge。branch / HEAD / CI / merge 状态以 Git / GitHub 实时事实为准。
- 本轮新增两个独立的 CN/US Cloud workflow、精确交易日 gate、内存 latest/QFQ
  边界、`daily-report.json` / `daily-report.html` 白名单产物、可选 Bark/SMTP 通知，
  并将 Dashboard 调整为移动优先的人类语言展示。
- PR #79 的信息架构/视觉密度整改与 presentation-only 状态措辞已完成：默认“今日重点”、
  紧凑股票行、sticky 阶段导航、前端搜索、按需详情与观察中/全部诊断视图均已接入；
  Dashboard 不改变内部 JSON contract、交易语义或写入边界。
- PR #80 的 Paper correctness 与展示整改已完成：计划风险 `planned_risk_per_share`
  与成交后 `PositionOrigin.initial_risk_per_share` 分开；当前 R、最终 R、收益率均沿用
  实际成交风险；默认 Paper 卡片回答买入理由、是否成交、当前状态与下一步，原始审计字段
  收进折叠技术区；generic shadow HTML 覆盖 PENDING_T1、OPEN、CLOSED、SKIPPED。
- 已完成最小 presentation-only metadata propagation：CN/US CandidateRecord 的
  `name` / `sector` / `rank` / inclusion-exclusion reason 进入现有 universe report，
  Candidate Review 保留轻量筛选审计；缺失值展示
  `—`，不改变 Candidate-only 过滤、Primary Wave→Setup 映射或 `ARMED > WATCH > ticker`
  排序。
- PR #78 已由用户侧 squash merge；Candidate metadata 的 `name` / `sector` 已进入
  `main`。该 presentation-only 改动未改变 Candidate selector、Wave、Setup、
  Decision/Risk、persistence、promotion、Portfolio Risk、scheduler、broker 或 execution
  semantics。
- 基线 `main` 已包含 Production Daily Decision Chain V1；本轮新增 Candidate
  runtime 仍保持人工触发、account-isolated、默认只读。
- 本轮已将现有 frozen Wave / SETUP_01 / SETUP_02 Decision/Risk / Portfolio Risk /
  Position Management 接入正式 `策略股票池` 驱动的每日只读决策输出；用户保留最终
  交易决定。
- 只复用既有 `SETUP_01` / `SETUP_02` 语义，未重开 `SETUP_03`、未做 `SETUP_03
  formal validation`、未开发 `SETUP_04`，不接 HiThink/broker/order，不自动批准
  交易；Cloud workflow 仍是 read-only，state write 必须继续显式 `--write-state`。
- Dynamic Candidate 正式确定为 discovery-only：Candidate-only 只进入当日只读分析
  与报告，不进入 state write、published event、T→T+1 pending/settlement、Portfolio
  allocation 或 production execution；必须人工加入正式 `策略股票池` 并补齐现有
  production prerequisites 后重新运行。Candidate overlap 正式池时按正式池生命周期，
  正式池之外的已有持仓仍只做 Position Management。
- 治理体系瘦身 v1 已完成：PR #73 已合并；此前关于 PR #73 `OPEN / 等待 merge`
  的现场描述已经过期。动态 branch / PR / CI 状态以 GitHub 实时事实为准。
- PR #74 与 PR #75 均已 squash merge；Candidate Universe 已正式进入
  production Daily Chain。动态 branch / PR / HEAD / CI 状态仍以 Git / GitHub
  实时事实为准。
- 本轮真实 smoke 通过已连接 Google Drive 的只读 Sheet snapshot 适配到现有
  `run_production_daily_decision`；本地 service-account env 未被写入或持久化，
  适配器只暴露 `records`/`headers`，未提供任何写 API。

## 2. Current State（当前正式状态）

- 项目：`EFSing/stock-data-pipeline`；默认分支 `main`。
- PR #74、PR #75 与 PR #76 已 squash merge 到 `main`；本轮工作位于独立 feature
  branch，尚未进入 `main`。branch、PR、HEAD、working tree 与 GitHub CI 动态状态
  仍须以实时结果为准，不信任本文件中的历史描述。
- 治理文件职责现为（详见 `AGENTS.md`）：
  - Git/GitHub = 动态工程事实源；
  - `HANDOFF.md` = 当前开发现场恢复；
  - `docs/CURRENT_STATUS.md` = 系统能力地图；
  - `docs/DECISION_LOG.md` = 长期有效决策及理由。
- `HANDOFF_CURRENT_AND_CONSISTENT` 表示：本文件能恢复现场、CURRENT_STATUS 与
  系统能力无实质矛盾、长期 Decision 无已知冲突、无会让下一设备错误继续的重大
  状态错误。它不要求本文件保存实时 main SHA / CI run ID，也不要求 docs-only
  commit 后重新完整验证。
- 当前不存在 `PROJECT_GOVERNANCE_STATE_CONFLICT`；实时 PR 状态以 GitHub 与
  `git fetch origin` 结果为准。

## 3. Completed（已完成事项 — 当前任务上下文）

- Cloud Daily Report V1 + Mobile Dashboard V2 已实现：CN/US 独立 workflow、精确
  `XSHG` / `XNYS` completed-session gate、目标市场内存 latest/QFQ 边界、既有
  Candidate→Daily Chain 只读复用、`daily-report.json` / `daily-report.html` final
  artifact 白名单、可选 Bark/SMTP 通知和移动优先人类语言 Dashboard 已接线。
- PR #81 已通过 CN/US 独立 GitHub workflow live smoke：分别使用 exact completed
  `XSHG` / `XNYS` session，Candidate Stage A/B、formal pool、active positions、
  provider/data-quality 与 final artifact allowlist 均通过；production state、paper
  ledger、broker orders、raw/QFQ persistence 均为零。
- `scripts/run_production_daily_decision.py --market CN|US` 已加入市场隔离能力；省略
  `--market` 保留旧全市场手工行为。Cloud runner 显式不写 state、Paper ledger、策略
  输入或 broker，并在 provider/数据不完整时输出 fail-closed 诊断。
- 新增 Cloud/mobile 回归测试并完成完整 unittest 验证；未改变 Wave、Setup、Decision、
  Risk、Position Management、T→T+1 或 Candidate promotion semantics。

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
- 已完成 `PRODUCTION_CANDIDATE_REVIEW_REPORT_V1` 与当前 metadata 增量：Candidate Review
  仅投影既有 `DailyDecisionResult`、Candidate metadata 与 provenance，不新增评分、排序
  模型、reason taxonomy 或第二套事件/状态判断；Candidate-only 仍为 `READ_ONLY_DISCOVERY`。
- 已完成 `DAILY_TRADING_DASHBOARD_V1`：`trading/daily_dashboard.py` 提供纯标准库的
  presentation projection/standalone HTML，默认“今日重点”只显示需要处理的既有阶段，
  股票以 compact row 展示，完整诊断按“查看详情”展开；runner 可选输出 `latest.html`
  与日期版本，saved JSON 可由 `scripts/render_daily_dashboard.py` 渲染；WATCH/ARMED
  不伪造入场价，Decision/Risk/Position Management 只展示现有字段。
## 4. Blocker（当前 Blockers / 决策节点）

- 当前交接节点：`CLOUD_DAILY_REPORT_LIVE_SMOKE_PASSED`。GitHub workflow 已实际使用
  既有 `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` 完成 CN/US smoke；本地
  service-account env 缺失不构成 blocker，也不记录或索取 secret 值。正式 cutover
  已完成，当前只剩 PR #81 的 exact-head CI、squash merge 与 main closeout。

- 本轮 GitHub smoke 的 CN/US artifact 与 summary 均证明 read-only、market isolation、
  exact-session 与 zero-write 边界；若后续要直接在本机运行 CLI，仍需注入既有两个
  环境变量，但这不是本次 live acceptance 的配置节点。
- 本次验收中的 US `BABA` / `RKLB` QFQ freshness blocker 已按既有 contract 清除；
  CN/XSHG 与 US/XNYS 的 exact completed T 均为当前动态 T，CN/US formal preflight
  均 `READY`，fail-closed gate 未被放宽。
- 本次 CN/US Candidate deep errors=0、Daily Chain `DATA_BLOCKED=0`；Candidate-only
  仍保持 discovery-only，不进入 state write、published event、allocation 或
  production execution。
- 当前无业务语义 blocker；PR #79 / #80 merge closeout、main CI 与 Paper generic
  shadow 均已完成。`FIRST_LIVE_PAPER_TRACK_2026-09-11` 已完成：已连接工作簿已
  创建当前 schema 的 `策略模拟账本`，写入 2 条 `PAPER_COVERAGE`（CN/US），
  `PAPER_PLAN_CREATED=0`，无成交/跳过/结束事件；CN/US coverage 起点与最新处理
  session 均为 `2026-09-11`，状态 `CONTINUOUS`，下一 exact session 为
  `2026-09-14`。
  Paper V1 仍保持独立账本、显式 `--paper-track`、前瞻 exact-session 与 fail-closed
  数据边界，不改变生产 state、portfolio risk、broker 或 order。
- CN/US standalone HTML 实体文件已生成并在 Codex 文件预览中打开；viewport、responsive
  media query、`overflow-x`、无 `<table>`、默认可见人类语言与无伪造 plan 值的 DOM/CSS
  审计通过。当前 CUA Chrome 工具策略禁止打开本地 `file://`，因此 exact 390px/430px
  浏览器 scrollWidth 未在该工具中直接测量；未启动本地 server、Pages 或 hosting，
  这不是生产/交易语义 blocker。若同一 market 存在多个 enabled strategy
  accounts，Candidate runtime 必须停在 `READY_FOR_DECISION`，不猜账户归属。
- 只有当现有 frozen semantics 无法推导、而实现会改变正式业务语义时，才停在
  `READY_FOR_DECISION` 请求用户选择；普通代码接线、测试和文档处理不构成 blocker。

## 5. Next Action（下一步动作）

1. 核对 PR #81 exact-head CI 与 mergeability，squash merge 后 fetch/pull `main` 并
  核对 merge commit、main CI 与两个新 scheduled workflow。
2. 确认旧 `asia-close.yml` / `us-close.yml` 仅保留 workflow_dispatch 手工应急入口，
  且 latest/full 与 credentials contract 未改变。
3. Candidate-only 仍需人工 promotion 到正式 `策略股票池` 才能进入正式生命周期；
   本轮不启动 broker、自动批准、paper write、SETUP_03/04 或新策略语义。

## 6. Important Unfinished / Deferred（重要未完成事项）

- Production Daily Decision Chain V1 已正式进入 `main`：人工触发、account-isolated、
  默认只读 production `--run` 已可用；state write 仍只允许显式 `--write-state`；
  人工批准仍通过明确 event identity；`allocation_budget` 仍由人工显式提供。
  Cloud Daily Report workflow 已完成 CN/US Secrets/live acceptance；正式 cutover 已
  移除旧 scheduled writer，同时保留旧 workflow_dispatch 手工入口。
- SETUP_03：formal validation 未重开（仍未执行），无 production tolerance；继续需新的明确
  研究决策 + 新 protocol/version。
- SETUP_04：未实现。
- Candidate Universe 已接入人工触发的 production strategy chain；Candidate-only
  需要人工 promotion 才能进入正式生命周期；本次真实日常验收已确认 CN/US
  Candidate 与 Daily Chain 均可只读运行；当前报告另有紧凑 Candidate Review 摘要，
  且不改变 formal QFQ refresh、strategy pool、broker 或 scheduler 能力。
- Paper Trade Lifecycle V1 已在独立 `策略模拟账本` 中实现：仅显式 `--paper-track` 写入，
  只接受新的 exact-session `SETUP_01`/`SETUP_02` `CONFIRMED` + individual
  `ENTRY_ALLOWED`；事件按 `event_identity + lifecycle_event_type` 幂等追加，并复用既有
  Decision / T+1 executor / `PositionOrigin` / replay。支持 pending/open/closed/skipped、
  CN/US coverage、Candidate-only active continuation、normalized R/return statistics 与
  Paper Dashboard；不做历史回填、真实 holdings、portfolio P&L、broker 或生产 state 写入。
- Generic operational shadow 已覆盖 formal closed 与 dynamic-candidate skipped 路径，并
  生成 synthetic JSON/HTML artifact；真实账户与凭证继续不进入 generic shadow。
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
- Paper 写入边界：`策略模拟账本` 与 production sheets/state 独立；普通 `--run` 只读，
  只有显式 `--paper-track` 才能 append；Paper auto-approval 仅表示 technical paper
  tracking，不提升为 production approval、allocation 或 candidate promotion。
- Paper 数据边界：必须使用 completed exchange-calendar T、exact T+1、`DATA_OK` QFQ，
  缺失/跨市场账户路由/不连续覆盖时 fail-closed；active paper symbols 在 candidate
  dropout 后仍需继续进入 QFQ refresh。
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
- 本地推荐开发路径（仅本机便利，不构成生产 contract）：
  `D:\Dev\stock-data-pipeline`。

---

状态标记：

`CLOUD_DAILY_REPORT_LIVE_SMOKE_PASSED`

`HANDOFF_CURRENT_AND_CONSISTENT`

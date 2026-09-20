# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI、mergeability 的实时事实源；不依赖本机目录、聊天或 session memory。

## Current Task

`HOLDINGS_MARKET_DATA_PR97_MERGE_CLOSEOUT` 已在 `main` 完成文档 closeout。PR #97 的
合并、schedule/CI 核验已完成；当前只等待首次真实 Sheet-backed writer 运行，以完成只读
生产验收。未执行生产写入、历史补抓、Paper、broker 或策略状态操作。

## Current State

- 当前恢复基线：`main`；PR #94 已 squash merge。合并决策时的 live PR head / exact-head CI 由 GitHub 实时核验；transient PR head is not a governance invariant。基线 main 已包含 PR #93 的 ARMED projection。
- PR #97 已由 GitHub squash merge，实际 merge commit 为 `cdae0de44bb5e5c47cb090f0d145d6ba2cec238e`；合并后 main CI run `35515316806` 对该 SHA 结论为 `success`。
- docs-only closeout PR #98 已无冲突 squash merge，main merge commit 为 `6022825d1c3ba2737ab97337997c8dc0b6b899ae`；合并后 main CI run `35516127719` 对该 SHA 结论为 `success`。
- PR #97 恢复 `asia-close` 工作日 `30 9 * * 1-5` UTC（北京时间 17:30，CN/HK/JP）与 `us-close` 工作日 `30 22 * * 1-5` UTC（US/SE）；schedule 强制 `latest`，成功后分别刷新正式 CN/US exact-T QFQ，`full` 仍仅手动。
- PR #96（Cloud dashboard card）与 PR #82（Actions Node 24）保持独立，本任务不混入、不 rebase、不合并它们。PR #96 仍 OPEN，因 #97 改变 main 基线当前为 conflicting；PR #82 仍 OPEN。
- PR #92 已按正式负研究结论 squash merge；Post-confirmation Retest hypothesis 已关闭，不进入 production design / fresh validation。
- PR #91 分类冲突已核实、修正并验证后 squash merge；确定性 artifact 总体分类仍为 `MIXED_ARCHITECTURE_SIGNAL_STARVATION`。`ABOVE_ENTRY_ZONE=595/999` 是最大 post-confirmation first-fail，不是总体唯一原因。
- PR #90 已落实用户明确的 partial-report operational exit 语义，经 full/focused tests、CI 与只读 US manual smoke 后 squash merge；main 交接已同步。
- 长期总体交易规则以 `docs/TRADING_SYSTEM_SPEC.md` 为唯一正式事实源。

本次核实到：Cloud cutover 移除了 `asia-close` / `us-close` schedule，但旧 Sheet 仍是
现有自动化监控的行情输入；PR #97 恢复的是 Sheet-backed writer，不是把 Cloud 报告接回旧
Sheet。Cloud CN/US 日报继续使用 exchange-calendar exact-session 与 provider 的进程内
latest/QFQ，保持独立 read-only 路径。合并前 HANDOFF 的 OPEN 状态及 DECISION_LOG 的过期
更新时间页眉已在本 closeout 修正，当前不存在未解决的 `PROJECT_GOVERNANCE_STATE_CONFLICT`。

## Completed

- `DailyDecisionResult.armed_opportunity` 复用当前 causal SETUP_01/02 ARMED snapshot 与 as-of T history，暴露 close、confirmation、距离、structural invalidation、ATR14 和现有正式 Entry Zone 公式结果。
- 缺 confirmation / invalidation / ATR 等字段时 fail closed；projection 明确 `is_trade_signal=false`，不创建 Decision/event/plan/Paper/state write。
- Dashboard 新增“机会观察”详情与 compact 距确认信息；交易方案优先，ARMED 仅按距确认百分比绝对值作展示排序。
- Dashboard/email 将 Entry Zone 标为“预计入场区（按当前 ATR，仅供观察）”；共享 guidance 明确当前不是买入信号、未来以确认日 Decision 为准、超过正式入场区不追价且不等待后续回踩补入，结构失效则放弃。
- email 复用同一 projection，保持移动端有限重点项；renderer 不重算策略公式。已 CONFIRMED NO_TRADE 的原拒绝原因路径保持不变。
- 本任务已将 ARMED 的所有用户入口改为“等待确认”；确认日已计算且最终 NO_TRADE 时，Dashboard/email 首层复用既有 gate、Entry Zone 状态、T1 空间与 T1 R/R 字段；策略持仓标为“策略跟踪持仓”，Paper ledger 标为“模拟持仓”。
- Decision/RR payload 未携带可直接消费的 minimum RR；因此 Dashboard/email 只格式化实际 R/R，并以既有 `gate_reason=RR_BELOW_MINIMUM` 展示“R/R不足”，不在 presentation 层复制正式阈值。
- 本次能力仍是 presentation/read-only only；production trading semantics unchanged，Post-confirmation Retest hypothesis remains closed，不进入 persistent/retest lifecycle。
- Post-confirmation Retest 正式结论已同步到 CURRENT_STATUS / DECISION_LOG：逻辑可行但恢复极少且全在 EARLY，不证明 broad/time-stable improvement，不改任何现有交易语义。
- `asia-close` 恢复工作日 `30 9 UTC`（北京时间 17:30），覆盖 CN/HK/JP；`us-close` 恢复
  `30 22 UTC`，覆盖 US/SE；schedule 强制 `latest`，随后仅执行正式 CN/US QFQ companion，
  `full` 仍只可手动选择。两个 workflow 各自使用不取消 concurrency。
- latest 完全失败时 `最新行情` 保留旧值仅作审计并标为 `数据不可用`；正式 QFQ 只接受 exact
  date、正式收盘、已验证的 latest row，生产读取仍要求 exact-T QFQ 尾行。

## Production Acceptance

- 状态：`PRODUCTION_ACCEPTANCE_PENDING`。PR #97 合并后只读核对未发现任何 `main` 上新的
  `asia-close` 或 `us-close` 运行；合并发生在周日，下一次 schedule 尚未到达。
- 因尚无合并后的真实 writer 运行，本次不能确认真实 Sheet 的最新交易日、正式 CN/US QFQ
  尾日或自动化监控的数据新鲜度；本机也未配置 `GOOGLE_SHEET_ID` / Google service
  account，未访问或写入真实 Sheet。不能把旧的 workflow 成功、代码检查或 Cloud 日报 smoke
  当作 Sheet 恢复验收。
- 停更/失败窗口的可核实基线：main 上最近一次成功的 Asia writer 为 2026-09-11，US
  writer 为 2026-09-08；US 随后的 2026-09-09 至 2026-09-12 scheduled runs 失败，随后
  旧 schedule 被移除直到 PR #97 恢复。由此，`最新行情` / `校验记录` / `运行日志` 与正式
  CN/US QFQ 不能假定已覆盖停更期间；依赖 exact session、已验证 latest 与 exact-T QFQ
  的监控会保持 stale / DATA_* fail-closed，而不是安全地用旧日期替代。
- 未执行历史补抓。Cloud Daily Report 的独立 provider/内存运行不修复 Sheet 历史缺口，也
  不改变上述监控影响；待首次合并后 Asia/US scheduled run 完成后，再进行只读 Sheet、QFQ
  尾日与监控 freshness 验收。

## Validation

- 本任务已通过行情校验、latest failure-marker、production prerequisite、QFQ refresh、治理
  与调度 focused tests；覆盖 schedule、并发串行、日期/状态 gate、QFQ exact-T、全量失败不写
  与重复刷新不重复目标日期。完整 `python -m unittest discover -s tests -v` 为 801 passed、3 skipped；
  `py_compile`、`git diff --check` 与 PR exact-head CI 均通过。
- 远端 main/PR/CI/Actions 状态只以 GitHub 实时结果为准；本任务不执行真实 Sheets 访问、生产
  补写、Paper、broker 或策略状态写入。

## Blocker

无实现安全 blocker，`PROJECT_GOVERNANCE_STATE_CONFLICT` 不存在。当前唯一未完成节点是
`PRODUCTION_ACCEPTANCE_PENDING`：等待真实 schedule 运行后做只读 Sheet/QFQ/监控验收；是否
补齐历史缺口仍需单独决策。本任务不访问真实 holdings，不做生产补写，不运行 Paper/broker/
Final OOS。

## Next Action

等待 PR #97 合并后的首次 `asia-close` / `us-close` scheduled run；完成后只读核验 Sheet 最新交易日、正式
CN/US QFQ exact-T 尾日、latest gate 与自动化监控 freshness。不得手动触发生产写入、历史补抓，
也不得把 Cloud 日报当作 Sheet 恢复替代，或自动启动新的 strategy threshold research、
persistent state、Protocol、Paper/broker lifecycle。

## Constraints

- 主线：Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
- 四类 Setup：SETUP_01、SETUP_02、SETUP_03、SETUP_04；SETUP_03 只是四类 Setup 之一的子策略。
- confirmation、ATR14 Entry Zone、Swing/Wave/Fib、Target-before-RR、Stop、5%、2R、T→T+1 均不变；确认日 geometry/targets/provenance 冻结。
- ARMED projection 只读、causal/as-of；展示排序不属于策略 ranking/promotion/gate。
- renderer 不计算 confirmation + ATR multiplier 等交易公式；缺字段不猜测。
- 无 Final OOS/parameter search/provider fetch/真实 holdings；不写 Sheets/state/Paper，不下 broker order。
- 本任务修改的是 workflow / Sheet-backed data quality boundary，不改变 Wave、Setup、Decision、Risk、Position Management、T→T+1 或 broker 权限。
- REAL_HOLDINGS_SHADOW 仍为 OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY，不是研究 blocker。

## Pitfalls

- 同一 symbol/T 若 SETUP_01 与 SETUP_02 同时 ARMED，projection 以 `MULTIPLE_ARMED_SETUPS` fail closed，不在展示层做 setup 仲裁。
- ARMED 排序使用 projection 已给出的 `distance_to_confirmation_pct` 绝对值；缺失值排在同阶段末尾，不影响其他阶段优先级。
- 预计 Entry Zone 是按当前 ARMED as-of ATR14 与现有正式 multiplier 形成的 read-only estimate，仅供观察；未来正式确认以确认日 Decision 为准，不是当前 plan、买入信号或未来成交承诺。若确认时超过正式入场区则不追价、不等待后续回踩补入；结构失效则放弃。
- fixture 中尚未带新 projection 的旧 ARMED row 必须显示数据不足，不得由 renderer 从旧字段补算。
- Cloud `cn-daily-report` / `us-daily-report` 只取配置并在进程内存获取 target-market latest/QFQ；不得改成读取旧 `最新行情` / `历史行情_前复权`。
- Sheet latest row 只有 exact T + `正式收盘=True` + `校验状态=已验证` 才可供生产策略 reader 使用；`数据不可用`、`待复核` 或 QFQ 尾日落后均必须 DATA_* fail closed。

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

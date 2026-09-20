# CURRENT_STATUS.md — 系统当前能力地图

> 职责：回答“系统目前已经具备什么能力，哪些仍在研究／未接入生产”，让新设备或新
> Codex 会话在读完本文件后快速建立整个系统的能力画面。
> 本文件不保存历史 PR 过程、blocker 演变、测试数量、CI run ID、commit SHA 或
> Engineering Event 流水账；动态工程事实以 Git / GitHub 实时状态为准。
> 最后实质更新：2026-09-20（恢复 Sheet-backed holdings market-data schedules；
> Cloud Daily Report 保持独立 read-only 内存边界）。

## 项目身份

- 长期总体交易框架的唯一正式事实源是 `docs/TRADING_SYSTEM_SPEC.md`，主线为：
  `Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup →
  Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。
- 项目版本基线：`V0.2`（行情抓取、双源校验、Sheets 写入已完成；决策与
  production 链仍在分阶段推进）。
- 本项目不是单一 Platform Breakout 系统。第一版四类 Setup：
  `SETUP_01` = Wave 2 → Wave 3；`SETUP_02` = Wave 3 Continuation；
  `SETUP_03` = Platform Breakout；`SETUP_04` = Extreme Fear Reversal。
  `SETUP_03` 只是其中一个子策略，其开发深度或研究阶段不改变总体路线；
  Wave Scenario Engine、`SETUP_01`、`SETUP_02` 仍是总体核心路线。
- 跨设备恢复现场、治理文件职责与 docs-only 验证规则见 `AGENTS.md` 与根目录
  `HANDOFF.md`。

## 能力清单

### 行情与数据质量（已生产运行）

- 定时行情流水线：`asia-close`（CN/HK/JP）与 `us-close`（US/SE）两个 GitHub
  Actions workflow 按市场收盘时间调度，运行 `main.py --mode latest`；Asia 为工作日
  09:30 UTC（北京时间 17:30），US 为工作日 22:30 UTC。
- `latest` 模式只抓取短窗口最新行情、执行 source-date evidence、双源校验与
  ordinary-calendar freshness guard，写入 `最新行情`、`校验记录`、`运行日志`；
  不抓取多年历史／qfq，不运行策略路径，`history_rows_written=0`。
- 定时 latest 成功后，`scripts/refresh_production_qfq.py` 只为启用正式 CN/US
  策略股票刷新 exact latest date 的前复权历史；HK/JP/SE 不被猜测扩展为 QFQ 范围，
  `full` 仍只可由 workflow_dispatch 手动触发。
- `PRODUCTION_ACCEPTANCE_PENDING`：上述 Sheet-backed schedule wiring 已恢复，但截至当前
  closeout 尚无恢复后的 `main` Asia/US writer run；真实 Sheet 最新交易日、正式 CN/US QFQ
  尾日与自动化监控 freshness 尚未验收，也不包含历史补抓。
- 行情完全失败会在 `最新行情` 保留最后值但写入当前 `抓取时间`、`校验状态=数据不可用`
  和显式禁止复用旧行情的备注，并使 scheduled job 非零退出；pending/single-source
  仍显式为非 `已验证`。下游 production reader 要求 exact T、`正式收盘=True`、
  `校验状态=已验证` 及 QFQ exact-T 尾行，缺一即 DATA_* fail closed。
- 数据源回退链稳定：主源 yfinance（含无 cookie Yahoo Chart 回退）、BaoStock
  （CN）、Tencent / Sina 快照回退；AKShare 已从生产依赖移除，仅保留遗留别名路由。
- 收盘语义固定：`交易日期` = 市场真实 session date，`抓取时间` = 北京时间，
  两者不可互换；未来日期 fail closed；未完成 session / 非正式收盘不得标记已验证。
- 前复权（qfq）只允许 yfinance / BaoStock；生产 QFQ 刷新由
  `scripts/refresh_production_qfq.py` 在 scheduled latest 成功后执行，失败 fail
  closed。Cloud exact-T qfq fetch 会在完整但 stale 的 yfinance payload 后继续尝试
  现有 Yahoo Chart fallback；Yahoo Chart 也未到 T 时仍 fail closed，不接受 T-1 替代 T。
- 数据质量核心（`core.py`）提供 Quote / ValidationResult、双源容差校验、freshness
  guard、session-date 推导、OHLCV sanity；只依赖标准库，供所有上层复用。

### 持仓数据生命周期与 holdings 操作（已生产运行）

- `latest_snapshot.py` 是 scheduled latest 与持仓生命周期共享的 evaluator /
  row-projection 单一事实源，禁止维护第二套 latest pipeline。
- `skills/holdings-data-manager`（薄 contract）+ `holdings_data_manager.py`：
  单一标的 `ADD` / `REENTER` / `CLOSE` / `SYNC`，自然语言只解析为唯一操作；
  以最近已完成 market session 为界补 raw/qfq 缺口；enable-last、幂等重试、
  `CLOSE` 不删除历史；覆盖/QC 只依赖 observed session dates。
- GitHub Issue command bus（`[HOLDINGS_COMMAND]`，严格 JSON v1）已启用 live
  route：job-level repository/actor/sender/Issue-user guard、非取消并发组、live
  step 才注入既有 Google Secrets；已记录首条真实 `ADD 512400`（CN，
  `history_rows_written=480`）成功。该路径只操作行情覆盖与 watchlist 身份，
  不进入策略 / 决策 / 研究语义。

### Candidate Universe（已接入 Production Daily Decision Chain V1）

- `trading/candidate_universe_sources.py` + `candidate_universe.py`：
  CN seed = `HS300 ∪ CSI500`（BaoStock basic/industry）；US seed = iShares
  Russell 1000（IWB）official holdings。
- 输出 affordability tier（CN `<=10,000` preferred / `<=20,000` retained；
  US 一股 `>1,000 USD` 排除）、20D/60D traded-notional 流动性 proxy、
  history/data-quality gate、sector-aware `TOP_N_PER_SECTOR=20` 与
  included/excluded 审计行。
- Candidate selector 仍不产生 `ENTRY_ALLOWED`、`STRATEGY_PROPOSAL` 或买入信号；
  `scripts/run_production_daily_decision.py --run` 在真实 `SheetsClient` 上按 CN/US
  独立运行两阶段输入：Stage A 用固定 yfinance batch 获取至少 60 bars 并调用现有
  selector，Stage B 只对 included Candidate（已存在正式池/持仓输入的标的复用已有
  QFQ）加载深历史并交给同一套 Strategy/Daily 分析。
- 动态集合只存在于当日内存和 JSON/Markdown 报告中，按 market-aware identity 与
  正式 `策略股票池`、`策略持仓` 去重；报告保留
  `FORMAL_STRATEGY_POOL` / `ACTIVE_STRATEGY_POSITION` / `DYNAMIC_CANDIDATE`
  provenance。正式池输入组成 stateful group；Candidate-only 强制为
  `READ_ONLY_DISCOVERY`，`state_persistence_eligible=false`、
  `promotion_required=true`，不产生 state/pending/settlement/Portfolio allocation
  或 production execution。Candidate overlap 正式池时按正式池生命周期处理。

### 策略核心计算层（Wave / Swing / Structure / Fibonacci）

- Swing：causal confirmed / provisional pivot 状态机，禁止事后 ZigZag 回填；
  历史决策只能使用 `confirmed_index <= t` 的 Swing。
- Weekly / Daily：Wave Scenario Engine v1 内部以严格 as-of 聚合 weekly parent
  与 daily context，不把未完成 ISO 周计入母级状态；未来 bar 追加不改写历史结果。
- Wave Scenario Engine v1：有限 primary/alternate 情景（`WAVE_2_TO_3_CANDIDATE`、
  `WAVE_3_CONTINUATION_CANDIDATE`、`ABC_CORRECTION_CANDIDATE`、
  `UPTREND_UNKNOWN_WAVE`、`DOWNTREND_OR_INVALID_FOR_LONG`、`NO_VALID_SCENARIO`），
  带证据 / 反证、结构失效与 SETUP_01/02 context eligibility；
  `scripts/run_wave_shadow.py` 提供只读 holdings shadow。
- Fibonacci：`trading/fibonacci.py` 是纯几何 single source；引擎只将其转为描述性
  候选区域，不作为独立信号。

### SETUP_01（Wave 2 → Wave 3）

- 独立 structural evaluator + strict as-of replay（`trading/setup01*.py`）：
  `NONE → WATCH → ARMED → CONFIRMED/FAILED`；只接受 primary
  `WAVE_2_TO_3_CANDIDATE`，确认需日线 close 严格高于 Wave 1 peak；
  结构性失效与 trade-structure 失效分开。
- Decision/Risk revision v2 已实现并合并：first-entry `CONFIRMED` exactly-once、
  T close 只形成 plan、最早 T+1 session `OPEN` 执行、Target-before-RR、
  `actual_entry != None ⇔ outcome == EXECUTED`。
- 新增正式 T1 gross upside gate：`trading.risk.MIN_TARGET_UPSIDE_PCT=0.05`。
  T1 相对 T 日 canonical `planned_entry` 低于 5% 时为
  `NO_TRADE / TARGET_UPSIDE_BELOW_MINIMUM`；T1 仍是第一正式目标，T2/T3、
  Target、Fib、Wave、Stop、R/R、排序与仓位均不改。`LOW_UPSIDE`（5%–8%）和
  `PREFERRED_UPSIDE`（>=8%）只作诊断 band；exact T+1 OPEN 重新检查剩余 T1
  upside，低于 5% 时为 `SKIP_TARGET_UPSIDE_BELOW_MINIMUM`，原结构与
  entry-zone reason precedence 保持不变。
- Decision/日报保留 `target_upside_pct`、band、最低要求、entry-zone 上沿距离、
  confirmation extension，以及 exact T+1 gap/remaining-upside 诊断；这些
  freshness fields 不改变 action/final status。
- SETUP_01 Decision 的只读 `target_projection` 将当前正式 T1 及其 source、最近已确认
  Swing High 阻力及上涨空间、最近与后续 Wave3 Fib extension、ratio 与上涨空间
  一并暴露给 JSON/Markdown/Dashboard/email；它只消费既有 target candidate/provenance，
  不生成第二套 target、gate 或 R/R。
- `research/development/setup01_wave2_to_wave3_geometry_attribution_v1.json/.md` 是
  development-only 的纯几何描述归因输出；不读取 outcome、Final OOS、T+1 或真实持仓，
  不接入生产 gate。
- `research/development/setup01_confirmed_swing_high_first_reward_boundary_counterfactual_v1.json/.md`
  与其可复现 research module 已完成固定 `NEAR_SWING_ONLY` 的 P0/P1 counterfactual，
  正式结论为 `INSUFFICIENT_EVIDENCE`：证据不足以批准修改 confirmed Swing High
  hard boundary，当前 production rule 保持不变；这不表示现有 hard boundary 已被
  证明正确，也不授权移除或修改任何 production target/gate/Decision 语义。
- `research/development/setup01_deep_wave2_structure_quality_v1.py` 与对应 compact
  JSON/Markdown report 已进入 `main`，完成固定 Phase 5J-v3 Development 研究及
  corrective geometry-controlled analysis：从 frozen replay 重建 `745` 个 CONFIRMED，
  预注册 depth bands 为 `NORMAL_OR_SHALLOW / DEEP / VERY_DEEP`，计数为
  `345 / 183 / 217`。原始 Fib1.272 hit-rate 为 `65.2% / 80.3% / 89.9%`，受
  `Fib1.272 - H1 = (1.272 - r) * R` 的机械几何关系影响，不能单独解释为 deep
  Wave2 structural quality 更好。控制共同 normalized geometry 后，post-T max
  HIGH − H1 median 为 `1.516R / 2.185R / 2.110R`，`H1+0.272R` hurdle success
  为 `87.2% / 88.0% / 91.7%`，`H1+0.618R` 为 `73.0% / 79.8% / 80.2%`；在
  已达到 `CONFIRMED` 的条件下，没有观察到 DEEP/VERY_DEEP continuation 更弱。
  该结果不证明 deep Wave2 更优、不证明 early entry 有效、不批准 depth gate 或
  production early entry。现有 funnel 中 DEEP `183/183`、VERY_DEEP `217/217`
  均未进入 `ENTRY_ALLOWED`，因此新增 depth gate 高度冗余；Early Entry 仅进入
  独立 PRE-CONFIRMATION causal research，不改变任何 production Decision 语义。
- `research/protocols/pre_confirmation_early_entry_causal_research_v1.json` 与对应
  `research/development/pre_confirmation_early_entry_causal_research_v1.py/.json/.md`
  已完成 `PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH_V1`：从 primary/alternate
  strict as-of Wave2 context 重建 `2,254` 个 causal anchor contexts，含 `745`
  later-CONFIRMED、`947` FAILED、`562` never-CONFIRMED（其中 `551` 被当前系统
  later-screened、`11` timeout/unresolved），固定比较 incumbent 与四个
  pre-confirmation milestones。早入场在 matched later-CONFIRMED 子集保留更多
  normalized headroom，但同时引入大量最终未确认/失败候选；研究结论为
  `READY_FOR_DECISION`，仅支持用户决定是否继续独立研究，不支持 execution/cost
  研究或任何 production authorization。
- 上述 `PRE_CONFIRMATION_EARLY_ENTRY_CAUSAL_RESEARCH_V1` 已 squash merge；正式研究
  含义保持为：`close > H1` 消耗部分 entry headroom，但也提供强 failure filtering；
  固定 early milestones 不足以替代 confirmation，不支持 production early entry、
  execution/cost research，或在同一 Development dataset 上继续无约束搜索。该研究
  不改变任何 production Strategy / Wave / Swing / Entry / Target / RR 语义。
- 有 generic synthetic operational shadow 与 development-only replay evidence；
  尚未接入生产自动执行（生产日历集成是已登记前置条件）。

### SETUP_02（Wave 3 Continuation）

- 独立 structural evaluator + replay（`trading/setup02*.py`）：只接受 primary
  `WAVE_3_CONTINUATION_CANDIDATE` + `setup02_context_eligible=true`，要求因果
  `LOW0→HIGH1→LOW2→HIGH3`、`HIGH3>HIGH1`、`LOW2>LOW0`、weekly/daily UPTREND；
  recovery 与确认阈值固定，终态事件仅首次进入发出一次。
- Decision/Risk revision v3 已实现并合并：target 几何固定为
  `LOW2 + (HIGH1−LOW0) × EXTENSION_RATIO`（source=`WAVE3_FIB_EXTENSION`），
  filter `target > planned_entry` 后按升序 T1/T2/T3 再做 R/R；
  旧 `structural_invalidation → HIGH3` 投影因数学上与最小 R/R 不兼容已被废弃。
- 当前 Decision/Risk revision 同时执行共享 5% T1 gate；nearest T1 即使空间或
  R/R 不足，也不会跳到更远的 T2/T3。T+1 使用 exact OPEN 重新计算剩余空间，
  原有结构与 entry-zone reason precedence 保持不变。
- 有 generic synthetic operational shadow 与 development replay；尚未接入生产
  自动执行。

### SETUP_03（Platform Breakout）

- 现状一句话：**研究主线已停止在
  `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`，formal validation 未执行，未选择任何
  production tolerance；legacy 手动 full 路径仍保留**。
- Legacy / 研究路径：`main.py --mode full`（仅 workflow_dispatch 手动选择）保留
  SETUP_03 replay/Decision 与 `交易决策` Sheet 事件发布；`trading.events` 统一
  终态事件语义，仅发布首次 `CONFIRMED`。
- 正式研究：参数冻结审计结论为 `NOT_READY_FOR_FORMAL_PARAMETER_FREEZE`；
  Phase 5J 结构验证 protocol（v1/v2/v3/v4/v5 相关 machine-readable JSON）已注册
  并冻结，正式 production tolerance 候选仅 `3.0% / 4.0% / 5.0%`，
  `lookback=5`、`window=40` 只作为 incumbent constants；
  qualification matrix 已冻结但未执行 formal validation；第二套
  development holdout 与 lifecycle attribution 均为 `RESEARCH_ONLY`，
  `qualified_candidates=[]`。
- ATR-normalized boundary 实现保留为 `RESEARCH_ONLY` /
  `NOT_PRODUCTION_AUTHORIZED` / `FAILED_STRUCTURAL_CANDIDATE_FAMILY`，不进任何
  production 入口。
- Formal validation dataset 获取 contract（Phase 5K-B0 v2）已冻结但未获取；
  Final OOS 未建立、未读取。Frozen artifact 恢复治理见
  `docs/FROZEN_ARTIFACT_POLICY.md` 与 `docs/FROZEN_ARTIFACT_REGISTRY.json`。

### SETUP_04（Extreme Fear Reversal）

- 未实现。

### Daily Decision Chain（已实现，人工触发只读生产报告）

- `trading/daily_decision_chain.py` 是只读 prospective orchestration：将 frozen
  Wave、SETUP_01/02 Decision/Risk、Portfolio Risk、Position Management、Wave5
  组合为单账户日决策链，可发 T 日 prospective Decision，但不下 broker order，
  也不把机械 T+1 ledger 观察当成真实成交。
- 生产运行要求正式 `策略股票池` universe、显式 `allocation_budget`（不读取 NAV
  替代）、risk-group metadata、authoritative position origin、exact
  exchange-calendar session 与持久
  `DecisionStateStore`；缺失时 fail closed。`scripts/run_production_daily_decision.py`
  提供 `--preflight` 与默认只读 `--run`；`--run` 会将 Candidate→Daily 的动态输入
  并入去重后的当日分析 universe，但把正式池与非正式池输入分成 stateful/read-only
  两组后合并展示结果。只有正式池输入在显式 `--write-state` 下才追加 system-owned
  `策略决策状态`；`--approve-event`、`--allocation-budget ACCOUNT_ID=AMOUNT` 对
  Candidate-only 不会绕过晋级边界。
- Daily JSON/Markdown 另含 causal、non-overlapping `freshness_funnel`：按当日
  new CONFIRMED 的 primary reason 统计 `ABOVE_ENTRY_ZONE`、目标空间不足、RR
  不足、其他 NO_TRADE、仍可交易，并统计可见 T+1 gap/空间衰减 skip；不使用事后
  最低点或 future bars。
- `ARMED_OPPORTUNITY_PROJECTION_V1` 已随 PR #93 squash merge 进入 main；它在
  `daily_decision_chain` 内对当前 ARMED SETUP_01/02 暴露只读 causal context：当前 close、
  confirmation level、距确认绝对值/百分比、structural invalidation、ATR14 与按现有正式
  multiplier 得到的预期 Entry Zone。该 Entry Zone 是按当前 ARMED as-of ATR 的 read-only
  estimate，仅供观察；正式确认时以确认日 Decision 重新计算为准，确认时超过正式区则不追价、
  不等待后续回踩补入，结构失效则放弃。缺字段时 fail closed 并给出原因；它不产生
  Decision、event、plan、Paper/state write、ranking 或交易 gate，production trading semantics
  unchanged。
 - `trading/daily_dashboard.py` 是 presentation-only 投影与 standalone HTML renderer；
   它只消费现有 Production Daily Decision result/JSON，不计算新信号、不改变内部
   enum/protocol/交易语义。首页默认是“今日重点”，只展示 ENTRY_ALLOWED、
   STRATEGY_PROPOSAL、今日新 CONFIRMED、ARMED、POSITION_MANAGEMENT 与
   DATA_BLOCKED；WATCH、NO_TRADE、FAILED 仍保留在数据中，分别通过阶段导航或
   “全部/诊断”按需查看。股票默认以 compact row 展示，完整 Wave / Setup / Decision /
   Risk / Position Management / 原始诊断在“查看详情”展开；页面支持 sticky 阶段导航、
   ticker/公司名称前端搜索与既有 CN/US、Setup、行业筛选。`scripts/render_daily_dashboard.py`
   可将已保存 JSON 写为 `reports/daily_dashboard/latest.html` 及日期版本；runner 通过
   显式 `--dashboard-output DIR` 选择性生成相同输出。
 - 前瞻模拟交易跟踪 V1 已接入显式 `--paper-track` 路径：只对新 `CONFIRMED` 且已有
   individual `ENTRY_ALLOWED` 的 SETUP_01/02 事件创建 Paper plan，使用独立、append-only
   `策略模拟账本`；正式池与 Candidate-only 均保留原 provenance，Candidate 仍不晋级、不
   写策略状态、不进入 Portfolio Risk 或 production execution。普通 `--run` 继续只读。
 - Paper lifecycle 严格复用现有 Decision evaluator、exact T+1 executor、`PositionOrigin`
   与 `replay_position`；计划、T+1 执行/跳过、真实 Position Management exit、coverage 与
   normalized R/return 统计均不复制交易公式。active Paper symbols 会续载同一 QFQ provider，
   Candidate dropout 不会让既有 Paper plan 消失；缺失 exact completed session 时 fail closed。
 - Paper workspace 已采用面向人的生命周期卡片：默认回答“为什么买／为什么关注、是否
   真正模拟成交、现在怎么样、下一步／为什么卖”，计划风险与成交后实际 1R 分开显示，
   当前 R 与最终 R 均来自成交后的 `PositionOrigin`；原始 identity、policy、provenance、
   PositionOrigin 与完整数值只在折叠的技术审计区显示。绩效页将胜率、R、收益率与样本
   不足明确区分，Coverage 缺口以用户可读警告呈现。
- Paper plan/trade 通过现有 `payload_json` 继续保留 T1 upside、band、entry-zone
  distance、confirmation extension、T+1 gap 与 remaining upside；不回溯或改写
  旧 Paper ledger 事件，也不改变 Candidate-only 的 `READ_ONLY_DISCOVERY` 边界。
- 启用持仓即使不在正式股票池或 Candidate 中也会继续进入 Position Management；
  多个 enabled account 共享同一 market 且没有现成 routing 规则时 fail closed 为
  `READY_FOR_DECISION_CANDIDATE_ACCOUNT_ROUTING`。

### Cloud Daily Report V1 / Mobile Dashboard V2（live acceptance 已通过，正式 cutover）

- 运维 exit 与 report quality 分离：`PARTIAL_DATA_QUALITY` 只有 exact target-session usable data 存在、核心日报计算完成且 final JSON/HTML 已形成时 exit 0，状态仍保持 partial。单源仍明确为“单源可用”并保留 actual provider provenance；stale/no exact-session、核心计算异常、artifact 失败继续 non-zero；通知 contract 不变。
- `scripts/run_cloud_daily_report.py` 提供一个严格 `CN` 或 `US` 的日报入口；新增的
  `.github/workflows/cn-daily-report.yml` 与 `us-daily-report.yml` 分别在 09:30 UTC
  和 22:30 UTC 运行，并使用既有 `exchange_calendars` 的 `XSHG` / `XNYS` 精确
  completed-session gate。周末或交易所休市返回 `SKIPPED_NON_SESSION`，不使用上一
  交易日替代；未收盘、provider 失败、latest/QFQ 不完整或校验失败均 fail closed，
  仍生成异常报告并通知。自动调度的 T 由 timezone-aware 当前时刻转换到目标交易所
  本地日期后再进入同一 exact-session gate，跨 UTC 午夜不会误取 runner 日期，节假日仍
  当天安全跳过；显式 `--date/--trade-date` 继续严格使用指定日期。
- `trading/ephemeral_market_data.py` 只抓取目标市场正式策略池、启用持仓和已有 Paper
  continuation 所需的 provider rows；latest/QFQ 复用既有 provider fallback、
  `latest_snapshot.py` 投影和 exact-T 校验，数据只在本次进程内存中存在，也不读取旧的
  `最新行情`、`历史行情_前复权`；不写入缓存、artifact 原始数据或日志。latest verifier
  会按第一路返回的实际 source 排除同源候选，确定性尝试下一独立 Tencent/Sina/yfinance
  fallback，并在 provider metadata 中同时保留 configured source、actual source 与
  fallback notes；同一实际 source 永不计作双源。Sheets 继续只承担配置、策略池、风险组、
  持仓、决策状态和 Paper ledger 等既有事实源。
- 每次市场/T 只保留 `daily-report.json` 与 `daily-report.html` 两个 final artifact，
  JSON 元数据包含市场/T、git SHA、session identity、data quality、Candidate seed/as-of、
  CandidateRecord 的轻量筛选审计、provider status、input fingerprint、协议版本和状态写入
  边界，不包含 raw/QFQ bars。
  Bark 使用 `BARK_ENDPOINT`，SMTP 是可选标准库通知，并发送 text/plain fallback、
  独立的静态 email-safe HTML 正文，以及复用最终 `daily-report.html` 的 UTF-8 完整
  Dashboard HTML 附件（`A股交易日报_YYYY-MM-DD.html` / `美股交易日报_YYYY-MM-DD.html`）；
  邮件只有既有 `ENTRY_ALLOWED` /
  `STRATEGY_PROPOSAL` Decision 才展示为交易方案，`NO_TRADE` 只展示人话拒绝原因与
  Decision gate 计算依据；通知失败不改变日报核心结果，SMTP 附件失败在通知 metadata
  中明确为 `FAILED`。standalone `daily-report.html` 仍是完整 Browser Dashboard artifact
  的唯一渲染产物，邮件正文不嵌入完整 Dashboard。
- Dashboard 仍是 presentation-only，但默认移动优先（390/430 宽度、单列卡片、无默认
  宽表、可点击区域至少 44px），首页优先展示数据异常、策略跟踪持仓、交易方案、新确认和等待
  确认；用户区使用中文交易含义，Wave/Setup/Decision 原始字段只在折叠的开发者区。
- Dashboard / email 复用上述 ARMED projection 展示“机会观察”，明确标记“观察中，
  不是买入信号”；交易方案保持优先，ARMED 仅按距确认百分比绝对值作展示排序，
  renderer 不计算 ATR/Entry Zone 等策略公式；Entry Zone 标为“预计入场区（按当前 ATR，仅供
  观察）”，并明确未来以确认日 Decision 为准、超过正式区不追价且不等待回踩补入。邮件只
  展示有限重点项，完整列表保留在 Dashboard；已 CONFIRMED 的 NO_TRADE 继续显示原 Decision
  拒绝原因；确认日已计算但最终不交易时，首层摘要直接展示确认成功、入场区状态、可用的 T1 空间与
  T1 R/R 拒绝依据。策略跟踪持仓与模拟持仓分别标注，不将模拟账本计数写成当前真实持仓。该能力为
  presentation/read-only only，不改变 production trading semantics。
- CN/US live smoke 已通过，且 Cloud report 的 production state、paper ledger、broker order
  与 raw/QFQ persistence 均为零；final artifact allowlist 已通过。`asia-close` / `us-close`
  是独立的 Sheet-backed scheduled writer，按 CN/HK/JP 与 US/SE 维护旧行情中台；Cloud
  Daily Report 仍只读配置、在内存取行情，不读写 `最新行情` / `历史行情_前复权`，不与该 writer
  争用策略状态。Bark/SMTP 仍为可选通知，当前 `NOT_CONFIGURED`。
- Cloud 的 live smoke/acceptance 不等于 Sheet-backed writer 的真实恢复验收；当前仅能确认
  schedule 代码已恢复，尚无合并后真实 writer run，因此 Sheet latest、正式 CN/US QFQ 尾日
  与监控 freshness 仍为 `PRODUCTION_ACCEPTANCE_PENDING`。
- 下一阶段优先观察真实 prospective Cloud Daily Reports / Paper 数据的正常 production
  runs；这些 observational acceptance 不自动启动新的 strategy threshold research，也不
  打开已关闭的 post-confirmation retest lifecycle。
 - Browser Dashboard 与 email-safe HTML 在人类可读详情中展示“机会新鲜度”；目标
   空间不足明确写成“目标上涨空间不足”，并同时显示参考价格、T1、实际百分比、5%
   最低要求及可用的 RR 诊断。SETUP_01 target projection 额外把“保守第一障碍
   （最近已确认历史阻力）”与“Wave3 结构目标（最近 Fib 投射）”分开显示；邮件与
   Dashboard 均不重新计算交易几何。

### Portfolio Risk（已实现并合并，未自动生产运行）

- `PORTFOLIO-RISK-2026-09-02-v1`：独立、conservative、fail-closed 的 downstream
  capacity gate，只消费 individual `ENTRY_ALLOWED`。
- 冻结常量：`BASE_RISK_FRACTION=0.005`、`MAX_TOTAL_OPEN_RISK_FRACTION=0.02`、
  `MAX_RISK_PER_GROUP_FRACTION=0.01`；risk group 只来自可靠 metadata，不猜 NAV、
  不做相关性推断、不缩放 stop。
- 风险语义修正为 remaining capital-loss risk：
  `max(actual_entry − active_protective_stop, 0) × quantity / reference_nav`；
  `current_price` 不参与 capacity；stop-raise / exit 释放 capacity；
  gap/slippage tail risk 明确不在框架内。
- `allocation_budget` 是用户授权给该账户整个策略风险账本的总预算，不是 NAV /
  账户资产 / P&L；预算不等于 approval，approval 只按已发布 proposal 的 event
  identity 匹配。
- 有 generic synthetic operational shadow 与 frozen development replay；
  account-isolated production run 未自动启用。

### Position Management / Exit / Wave5（已实现并合并）

- `trading/position_management.py` 只消费 SETUP_01/02 的 `EXECUTED` rows；origin
  geometry、actual entry、initial stop、targets、Wave anchors、one-R 不可变。
- 提供 current R/MFE/MAE、MFE drawdown、confirmed-higher-low trailing、monotonic
  2R/1R MFE floor、next-session mechanical stop/structural exit、target reach、
  Wave4/Wave5 context 与 advisory actions；Wave5 不能强制全退或新建 entry。
- Exit 语义在 `trading/events` / position replay 中与 Portfolio Risk 分开；
  不计算 win rate / aggregate P&L / expectancy / Sharpe，不读取 Final OOS。

### Production wiring（部分运行）

- Google Sheets V1 五个正式契约已落地：`策略账户`、`策略股票池`、`策略风险分组`、
  `策略持仓`、系统-owned `策略决策状态`；`自选清单` 仍只是行情覆盖事实源。
  `策略股票池` 才是 formal strategy universe。
- `SheetsDecisionStateStore` 是 V1 persistent store（typed canonical JSON、
  account-scoped、append-only compound protocol、默认 read-only）；production
  adapter 支持 account-isolated risk books（CN=CNY/XSHG、US=USD/XNYS）与 exact
  session proof（`exchange_calendars`）。
- 已具备严格只读 `--preflight` 与默认只读的人工 `--run` 报告；正式 daily
  chain 的 stateful `--run` 需要显式 `--write-state`，且当前没有自动 workflow
  调用。显式 `--paper-track` 只追加 `策略模拟账本` 的 Paper lifecycle rows，不写
  `策略决策状态`、`策略股票池`、`策略持仓`，也不触发 Portfolio allocation、broker order
  或 scheduled execution；holdings 行情路径（上表）是已运行的例外。

- 现有 `HiThink Financial API（同花顺金融数据服务）` 仅完成有界 CN transport
  smoke：ticker/index constituents、market-dump signing、corporate-action
  adjustment events、calendar；尚未证明财务报表字段契约、复权公式/as-of
  语义或长历史覆盖。因此本 V1 不依赖、不接入 HiThink；后续可在单独验证后
  作为 CN fundamentals/metadata 或 Candidate 辅助源，不能把它描述成已验证的
  iFinD 替代品。当前生产链仍使用正式 `策略股票池` 与现有已验证的 QFQ 数据边界。

### Broker execution

- 未连接券商；无 order submission、IBKR、自动下单路径。任何“机械回放成交”不得
  声称是 broker execution。

## 研究中的能力 / 明确未接入生产

- `POST_CONFIRMATION_RETEST_ENTRY_CAUSAL_RESEARCH_V1` 已关闭并保留为正式负研究结论：
  confirmed→wait-for-retest 在逻辑上成立，但固定 Development-only A/B replay 只恢复极少量
  executable，且全部集中 EARLY，不证明 broad/time-stable improvement，不进入 production
  design，也不单独 fresh validation。confirmation、Entry Zone、ATR multiplier、5%、2R、
  Swing、Wave、Target、Stop 与 T→T+1 均不变；除非未来出现新的独立证据，不重复启动
  同类 retest 参数研究。父审计分类仍为 `MIXED_ARCHITECTURE_SIGNAL_STARVATION`。

- Candidate Universe：已接入人工触发的 production Daily Decision Chain V1；动态
  Candidate-only 仍是 discovery-only，进入正式生命周期必须人工加入
  `策略股票池` 并重新满足 production prerequisites；没有自动调度、自动批准、自动
  state write 或 broker execution。仅在显式 `--paper-track` 下，Candidate-only 的新
  `CONFIRMED + ENTRY_ALLOWED` 才会进入独立 Paper ledger；这不改变其 discovery-only
  production 身份。
- `SYSTEM_SIGNAL_SCARCITY_AUDIT_V1`：已注册并完成固定 Phase 5J-v3 Development
  holdout 的 SETUP_01/SETUP_02 causal replay，覆盖 symbol-session、candidate
  lifecycle、CONFIRMED、Decision、exact T+1 OPEN、first-fail、all-fail overlap、
  one-gate ablation、CN/US/time-half frequency、concentration 与 architecture
  classification。结果为 `86,305` symbol-sessions、`2,050` candidate lifecycles、
  `1,004 WATCH`、`862 ARMED`、`999 CONFIRMED`、`8 ENTRY_ALLOWED`、`4` exact
  T+1 executions；`ARMED → CONFIRMED` 为 `442/862 = 51.28%`，另有 `420` 个
  ARMED lifecycle 未确认。Decision first-fail 为 `ABOVE_ENTRY_ZONE 595/999`、
  `TARGET_UPSIDE_BELOW_MINIMUM 277/999`、`RR_BELOW_MINIMUM 100/999`，最终分类
  `MIXED_ARCHITECTURE_SIGNAL_STARVATION`。该结论只支持后续研究决策，不改变
  confirmation、Entry Zone、5%、RR、Swing、Target 或任何 production semantics。
  固定 5% gate 的一门移除反事实新增 `ENTRY_ALLOWED=0`；RR 分解报告 stop distance、
  first-target distance、both 与 insufficient-evidence 四类。formal pool 与 live
  Dynamic Candidate 未进入冻结样本，比较状态为
  `INSUFFICIENT_EVIDENCE_FOR_FORMAL_VS_LIVE_CANDIDATE`。Dashboard 审计发现 ARMED
  causal snapshot 没有由 DailyDecisionResult 透传到 renderer；最小修复位置是
  `daily_decision_chain` 的只读 context projection，不在本轮改 UI。最近 production
  daily-report 样本不足时明确标记为 `INSUFFICIENT_RECENT_LIVE_SAMPLE`。对应 protocol、
  research module 与 compact JSON/Markdown artifact 均为 Development-only，未接入生产。
- SETUP_03：structural development stopped；formal validation 未执行；无 production
  tolerance 选择；Phase 5K-B0 dataset 未获取；Final OOS 未建立。
- SETUP_04：未实现。
- Daily Decision Chain / Portfolio Risk / Position Management：策略语义已实现并
  frozen，支持 Candidate + 正式池 + 持仓的 account-isolated 人工触发只读生产报告；
  仍未作为自动调度任务运行。Paper tracking 是独立、显式触发的 prospective ledger
  与 replay projection，不是生产状态或 broker execution。
- 真实账户持仓 shadow 属 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时
  status=`NOT_RUN_USER_PRIVACY`；缺少真实持仓不是 SETUP_01 等核心开发 blocker。

## 长期不变量（任何开发不得违反）

- `signal(t)` 只用 `data <= t`；禁止未来 Swing / ZigZag 回填、look-ahead、OOS
  泄漏、按结果改样本或人为制造 Target / R/R。
- T→T+1 execution semantics；Target-before-RR；Wave 主／备情景；
  CN / US runtime 独立。
- 凭证只经 GitHub / Codespaces Secrets 或本机环境变量注入；真实持仓与
  holdings-derived 数据不进 GitHub Actions；不自动连接券商下单。
- 策略公式与 risk 常数的 Single Source of Truth 在 `trading/` 代码与 protocol
  文件中；生产展示层与研究层不得复制交易逻辑。

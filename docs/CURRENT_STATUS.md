# CURRENT_STATUS.md — 系统当前能力地图

> 职责：回答“系统目前已经具备什么能力，哪些仍在研究／未接入生产”，让新设备或新
> Codex 会话在读完本文件后快速建立整个系统的能力画面。
> 本文件不保存历史 PR 过程、blocker 演变、测试数量、CI run ID、commit SHA 或
> Engineering Event 流水账；动态工程事实以 Git / GitHub 实时状态为准。

> 最后实质更新：2026-10-05（CN A-share provider-forward QFQ 合同迁移与 US Candidate lifecycle structural fixes 已合并到 main、独立 Candidate 源日期修复、Wave 非正摆幅 Fib-context 边界
> 修复与 formal reader DATA_OK 接入已合并到 main；真实只读 CN 回补已 COMPLETED，核心
> 异常解除，数据质量仍 PARTIAL。日报优先展示重点、折叠原始审计、区分覆盖与成功分析；
> 公式和门槛不变。Daily Opportunity Ledger V1 已合并并接入 production Cloud path，
> merge 后首个自然 CN Daily Report 与 ledger natural acceptance pending；Daily Report
> human-opportunity presentation 已在 PR #135（OPEN / PR-ready / proposed）实现于共享
> renderer；该能力尚未进入 main，只有 PR merge 后才成为正式当前能力。单源 provider、
> D1 V2 activation 与 natural production / D1 evidence 边界不变）。

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

- 生产 CN/US 行情合同已收敛为 `SINGLE_SOURCE_MARKET_DATA_V1`：CN 唯一 price
  provider 为 `HITHINK_FINANCIAL_API`，US 唯一 implementation 为 `YAHOO_CHART`。
  provider retry 只重试同一 provider，不切换 vendor；Tencent/Sina/BaoStock/yfinance
  仅保留 legacy/research/universe metadata 职责，不进入 CN/US production decision path。
- 单源合同由 `market_data_contract.py` 统一验证 exact-T、严格递增且无重复日期、未来
  bar、OHLC sanity、非负 volume、schema 与 required history。CN asset type 由明确 metadata
  或 HITHINK 同源 metadata directory 的 exact symbol match 决定：生产股票 qfq 使用同一
  HITHINK provider 的 `/api/a-share/prices/historical?adjust=forward`，记录
  `CN_HITHINK_PROVIDER_FORWARD_ADJUSTED_V2` / `CN_HITHINK_PROVIDER_FORWARD_QFQ_CONTRACT_V2`；
  旧 raw `adjust=none` + corporate actions 的 `CN_FORWARD_ADJUSTMENT_ENGINE_V1` 保持
  immutable，供 D1 V2/旧 evidence。fund/ETF 使用同一 HITHINK fund
  historical endpoint，并记录 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1` provider-adjusted
  provenance；无法证明的 adjustment contract 标为 `DATA_ADJUSTMENT_UNVERIFIED`，不回退
  其他 vendor。
- symbol-level `DATA_MISSING`、`DATA_STALE`、`DATA_INVALID`、
  `DATA_ADJUSTMENT_UNVERIFIED`、`PROVIDER_SYMBOL_ERROR` 只阻断自身并映射为
  `DATA_UNAVAILABLE_FOR_DECISION`，不生成 `NO_SIGNAL`，其余正式池/持仓/Candidate 继续。
  `PROVIDER_GLOBAL_FAILURE` 仅用于 provider-wide auth/schema/outage 等 system-level
  failure；coverage 只作诊断，不作数量 hard gate。完整合同见
  `docs/PRODUCTION_SINGLE_SOURCE_MARKET_DATA_V1.md`。

- 定时行情流水线：`asia-close`（CN/HK/JP）与 `us-close`（US/SE）两个 GitHub
  Actions workflow 按市场收盘时间调度，运行 `main.py --mode latest`；Asia 为工作日
  09:30 UTC（北京时间 17:30），US 为周二至周六 00:30 UTC（北京时间 08:30）。
- `latest` 模式只抓取短窗口最新行情、执行 source-date evidence 与单源合同校验，
  对 CN/US 不再执行双源校验；
  ordinary-calendar freshness guard，写入 `最新行情`、`校验记录`、`运行日志`；
  不抓取多年历史／qfq，不运行策略路径，`history_rows_written=0`。
- 定时 latest 成功后，`scripts/refresh_production_qfq.py` 只为启用正式 CN/US
  策略股票刷新 exact latest date 的前复权历史；HK/JP/SE 不被猜测扩展为 QFQ 范围，
  `full` 仍只可由 workflow_dispatch 手动触发。
- `SINGLE_SOURCE_MARKET_DATA_V1` 与 CN A-share provider-forward migration 已
  `MERGED_TO_MAIN`；真实 HITHINK CN 与 `YAHOO_CHART` US provider acceptance 已按
  exact-T、OHLCV、chronology、stale、adjustment provenance、same-provider retry 与
  reproducibility 完成。provider-forward route 合并到 main 后尚无自然 CN Daily Report，
  状态为 `WAITING_FOR_FIRST_POST_MERGE_CN_NATURAL_ACCEPTANCE`；不能把尚未发生的自然日报写成
  已经验收，也不能把 provider acceptance 写成 D1 formal evidence。
- 单 symbol 行情失败会在 `最新行情` 保留最后值但写入当前 `抓取时间`、`校验状态=数据不可用`
  和显式禁止复用旧行情的备注，同时隔离该 symbol；只有 provider-wide failure、
  session/calendar 或 orchestrator failure 才使 scheduled job 非零退出。下游
  production reader 要求 exact T、`正式收盘=True`、合格校验状态与 QFQ exact-T 尾行，
  缺一即 DATA_* fail closed；单源 DATA_OK 标签接入的实现/部署状态见 Production wiring。
- legacy provider registry 仍为旧市场/研究 fixture 提供兼容性；CN/US production
  不再使用 yfinance→其他 vendor、BaoStock/Tencent/Sina cross-check 或 qfq fallback。
- 收盘语义固定：`交易日期` = 市场真实 session date，`抓取时间` = 北京时间，
  两者不可互换；未来日期 fail closed；未完成 session / 非正式收盘不得标记已验证。
- 前复权（qfq）生产 CN/US 由各自 canonical provider 完成；生产 QFQ 刷新由
  `scripts/refresh_production_qfq.py` 在 scheduled latest 后执行，单 symbol 失败隔离，
  provider-wide failure 才 fail closed。Cloud exact-T qfq 只接受 canonical provider
  的 exact T，不接受 T-1 替代 T。
- US exact-T QFQ 由 direct Yahoo Chart implementation 使用有限同源重试，落后 T 时
  fail closed，不接受 T-1；CN 同样只重试 HITHINK。`SheetsClient` 在单次进程内复用
  worksheet 对象和 records 快照，并只对读取型 Sheets 429 做有限退避，不自动重试写入；
  日报、Candidate Stage B 与正式 QFQ writer 的 exact-T QFQ 仍不接受 T-1。QFQ 历史替换
  仍先保留非目标行，且单源结果通过合同后才写入。
- 数据质量核心（`core.py`）提供 Quote / ValidationResult、legacy 双源容差校验、freshness
  guard、session-date 推导、OHLCV sanity；`market_data_contract.py` 提供 CN/US 单源
  合同校验，供所有 production 上层复用。

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
  CN seed = HITHINK official `000300.SH`（HS300）∪ `000905.SH`（CSI500）constituents；
  US seed = iShares Russell 1000（IWB）official holdings。CN seed 保留 index membership、
  current snapshot timestamp 与 endpoint/index provenance；BaoStock 仅保留
  legacy/research adapter，不进入 production Candidate runtime。
- CN/US membership snapshot 与逐条 seed metadata 必须有可验证日期，且
  `snapshot_date <= report_as_of_date`；runtime 在 Candidate price fetch 前校验 envelope 与
  每条 seed，US IWB adapter 接收 report date，selector 拒绝未来 metadata。该日期保护已
  进入 main；以下 source-date 修正与 US 历史下载也已合并到 main。
- HITHINK 官方成分股仍是 current-only，REST/CLI 未提供历史日期 selector。`timestamp` 是
  data-ready time；新 adapter 保留原始 ISO/epoch 值，将非交易日响应按既有 XSHG calendar
  归属前一真实 session，交易日仍用当天日期，不为早期报告回退。此解释依据用户确认的
  非交易日数据归属，不是 approximation 或历史端点；真正晚于报告日的 source session
  仍 `UNAVAILABLE`，诊断保留 source/report date 与 `NO_ELIGIBLE_SNAPSHOT`。
- US 新 adapter 在指定 report date 时从 iShares 官方 IWB 历史下载传 `asOfDate=YYYYMMDD`，
  response `Fund Holdings as of` 是日期事实源；保留日期查询 URL/provenance，并兼容官方
  historical CSV 日期/数字格式。不把 request date 赋给响应；缺日期或未来 snapshot fail
  closed。未指定日期的直接下载仍为 current-only。当前 production 无 persistent
  snapshot cache；所有新加载或 cache-backed loader 的输入均须重验日期。US live seed
  仅为 IWB Russell 1000，Yahoo 只供价格；S&P500/QQQ/SOX frozen research snapshots 独立。
- US IWB Equity rows retain generic lifecycle metadata and source provenance. Explicit
  unlisted/no-market exchange metadata, including the official
  `NO MARKET (E.G. UNLISTED)` value, is excluded as
  `LIFECYCLE_UNLISTED_OR_NO_MARKET`; blank/missing Exchange is not treated as explicit
  lifecycle metadata. A canonical `-WI` identity is excluded as
  `LIFECYCLE_WHEN_ISSUED` without mapping it to the regular common-stock ticker. Ordinary
  Equity, including newly listed Equity, remains on the existing history gate; insufficient
  history remains `HISTORY_INSUFFICIENT`. These are Candidate data/identity exclusions only
  and do not change provider routing, strategy filters, or trading rules.
- Candidate data-quality structural fixes are complete. HOLX/VYLR-WI lifecycle outcomes are
  explicit and auditable; JMKE `HISTORY_INSUFFICIENT`, 601059/601198 stale/unavailable are
  legitimate fail-closed data states, not reasons to alter Candidate rules. Remaining work is
  natural production acceptance only; no additional provider, threshold, or data-architecture
  change is authorized by this state.
- 输出 affordability tier（CN `<=10,000` preferred / `<=20,000` retained；
  US 一股 `>1,000 USD` 排除）、20D/60D traded-notional 流动性 proxy、
  history/data-quality gate、确定性 global rank 与 included/excluded 审计行；production
  不依赖 sector metadata，也不使用 `TOP_N_PER_SECTOR` 限额。
- Candidate component failure 与 formal data quality 分离：formal rows 仍可形成
  `RUN_STATUS=COMPLETED`、`DATA_STATUS=PARTIAL`，同时明确
  `CANDIDATE_STATUS=UNAVAILABLE`；不得把 Candidate failure 渲染为 `NO_SIGNAL`。若整个
  attempted universe snapshot 无法形成，则 D1 V2 不得 formal commit；已知 universe 下的
  symbol-level partial 仍保留逐标的 provenance。
- Candidate selector 仍不产生 `ENTRY_ALLOWED`、`STRATEGY_PROPOSAL` 或买入信号；
  `scripts/run_production_daily_decision.py --run` 在真实 `SheetsClient` 上按 CN/US
  独立运行两阶段输入：Stage A 使用 canonical HITHINK（CN）或 direct Yahoo Chart（US）
  请求 70 个 completed sessions，
  保留至少 60 bars 与 exact-T 尾日门槛，并调用现有
  selector，Stage B 只对 included Candidate（已存在正式池/持仓输入的标的复用已有
  QFQ）加载深历史并交给同一套 Strategy/Daily 分析。Stage A 对空或无可用历史批次做
  有界重试（含 stale 尾部）；仍无可用 Stage-A 行或至少 20 个 seed 时可用覆盖低于
  50%，标记 discovery coverage incomplete，不把它伪装成
  规则筛选后的 `NO_CANDIDATES`。结果显式暴露 Seed、数据合格、included、Stage B
  requested/ready、策略分析尝试/完成/阻断及筛选原因。
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
- 独立修复在 Wave 的已判无效 impulse 边界避免请求非正摆幅的描述性 Fib 区域；
  invalid scenario / Setup eligibility 保持既有语义，canonical Fibonacci 正摆幅合同、
  公式、ratio 与策略阈值不变。该边界修复已进入 main。

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
- `ARMED_OPPORTUNITY_PROJECTION_V1` 已随 PR #93 squash merge 进入 main；当前
  `daily_decision_chain` 对 causal `WATCH` / `ARMED` SETUP_01/02 暴露只读 context：当前
  close、confirmation level、距确认绝对值/百分比、structural invalidation、ATR14 与按现有
  正式 multiplier 得到的预期 Entry Zone。SETUP_01 的已确认 Wave1 Origin / Peak / Wave2
  Low 也会原样带入 projection，并调用 canonical Fibonacci extension helper 暴露 1.272 / 1.618 /
  2.0 / 2.618 预估目标及相对当前价空间；anchor 缺失、非 causal 或顺序非法时显式数据缺口，
  不倒推价格。该 projection 仍仅供观察；正式确认时以确认日 Decision 重新计算为准，确认时
  超过正式区则不追价、不等待后续回踩补入，结构失效则放弃。它不产生 Decision、event、plan、
  Paper/state write、ranking 或交易 gate，production trading semantics unchanged。
 - `trading/daily_dashboard.py` 是 presentation-only 投影与 standalone HTML renderer；
  它只消费现有 Production Daily Decision result/JSON，不计算新信号、不改变内部
  enum/protocol/交易语义。共享 CN/US renderer 现以“人工机会判断”优先，展开后先展示
  当前/Decision 参考价、确认价、入场区、结构风险、T1/阻力与 Wave3 target/upside；
  PR #135 的 proposed projection 还会将 SETUP_02 已生成的 `target_candidates` / provenance
  转为与 SETUP_01 相同的目标卡片；若 `ABOVE_ENTRY_ZONE` 等 gate 在 candidate 生成前提前终止，
  但 continuation anchors 已足够，则只读人工层可展示 canonical Wave3 结构空间，并明确不等同正式 T1。
  随后保留“确认后的交易判断”和机会新鲜度，结构与判断依据、开发者原始数据默认折叠。
  未展开 card 也展示紧凑的当前价、确认距离、结构风险和主要 Wave3 空间；所有用户侧价格/百分比
  使用 compact formatting，缺失字段显示可解释原因而非裸 `—`。独立展示修复默认优先显示今日重点，将确认与等待确认放在
  异常之前；“全部/诊断”仍可访问全部结果，静态 HTML 在没有 JavaScript 时也保留完整
  逐标的内容。原始质量/覆盖/前瞻审计默认折叠，报告覆盖数与成功分析数分开；评估失败
  不冒充普通 NO_TRADE。该共享展示修复属于 PR #135 proposed implementation，待 PR 合并后才进入
  main 正式能力地图。股票以 compact row 展示，完整
  当日状态、当前浪型、Setup、已满足/未满足条件、Decision/Risk/Position Management /
  原始诊断在“查看详情”展开；页面支持 sticky 阶段导航、
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

- 运维交付与分析质量分离：scheduled CN/US workflow 使用 partial-symbol-tolerant 语义，
  `RUN_STATUS=COMPLETED` + `DATA_STATUS=PARTIAL` 时 Actions 保持 success；manual
  `workflow_dispatch` 默认同 scheduled 一致，仅显式 `require_complete=true`
  才传 `--require-complete` 做 strict audit（exit 2），partial 质量标签仍保留。单源保留 provider
  provenance；stale/no exact-session、provider-wide failure、核心计算异常、artifact
  失败继续 non-zero；`COMPLETED_NO_USABLE_SYMBOLS` 先生成完整诊断再由 strict audit
  决定是否 non-zero。
- `scripts/run_cloud_daily_report.py` 提供一个严格 `CN` 或 `US` 的日报入口；新增的
  `.github/workflows/cn-daily-report.yml` 与 `us-daily-report.yml` 保留既有 primary
  schedules，并通过共享 `ExactExchangeCalendarProvider.latest_completed_session()` 选择
  最近一个真实收盘已过去的 `XSHG` / `XNYS` session。跨北京时间午夜、周末、节假日、US
  DST/EST 和 schedule 延迟都不会把 runner 当前 civil date 当成未完成 T；显式
  `--date/--trade-date` 继续严格使用指定日期并进入 exact-session gate。日报 metadata
  额外区分 `SCHEDULER_DELAY`、`SESSION_RESOLUTION_ERROR`、`INCOMPLETE_SESSION`、
  `DATA_QUALITY_PARTIAL`、`PROVIDER_FAILURE`、`NO_SIGNAL` 与 `SUCCESS`，其中 `NO_SIGNAL`
  不是 failure。
- `trading/ephemeral_market_data.py` 只抓取目标市场正式策略池、启用持仓和已有 Paper
  continuation 所需的 provider rows；CN/US latest/QFQ 只使用 canonical provider、
  `latest_snapshot.py` 投影和 exact-T 单源合同校验，数据只在本次进程内存中存在，也不
  读取旧的 `最新行情`、`历史行情_前复权`；不写入缓存、artifact 原始数据或日志。provider
  metadata 保留 canonical identity、合同状态与 adjustment provenance。Sheets 继续只
  承担配置、策略池、风险组、持仓、决策状态和 Paper ledger 等既有事实源。
- 每次市场/T 只保留 `daily-report.json` 与 `daily-report.html` 两个 final artifact，
  JSON 元数据包含市场/T、git SHA、session identity、data quality、Candidate seed/as-of、
  CandidateRecord 的轻量筛选审计、Candidate 漏斗汇总、provider status、input fingerprint、
  协议版本和状态写入边界，不包含 raw/QFQ bars。首页和 email 使用同一 presentation
  diagnostics projection：数据失效时列出异常标的及原因；无交易信号时列出 Seed、数据合格、
  included、深度分析、正式策略池/动态 Candidate/实际日报结果、DATA_OK/NO_TRADE、
  Stage A/B 状态和可获得的 Candidate 过滤原因。Candidate 发现失败、有效零候选、
  候选已生成但深度阻断、以及结果未报告保持不同诊断结论。
  Bark 使用 `BARK_ENDPOINT`，SMTP 是可选标准库通知，并发送 text/plain fallback、
  独立的静态 email-safe HTML 正文，以及复用最终 `daily-report.html` 的 UTF-8 完整
  Dashboard HTML 附件（`A股交易日报_YYYY-MM-DD.html` / `美股交易日报_YYYY-MM-DD.html`）；
  邮件只有既有 `ENTRY_ALLOWED` /
  `STRATEGY_PROPOSAL` Decision 才展示为交易方案，`NO_TRADE` 只展示人话拒绝原因与
  Decision gate 计算依据；通知失败不改变日报核心结果，SMTP 附件失败在通知 metadata
  中明确为 `FAILED`。standalone `daily-report.html` 仍是完整 Browser Dashboard artifact
  的唯一渲染产物，邮件正文不嵌入完整 Dashboard。
- Dashboard 仍是 presentation-only，但默认移动优先（390/430 宽度、单列卡片、无默认
  宽表、可点击区域至少 44px），首页完整保留所有实际分析结果，同时将数据异常、策略跟踪
  持仓、交易方案、新确认和等待确认排在前面；用户区使用中文交易含义，Wave/Setup/Decision
  原始字段只在折叠的开发者区。邮件正文仍可只展示重点摘要，但明确完整 HTML 覆盖数和候选
  异常，HTML 附件保留完整结果。
- Dashboard / email 复用既有只读 context 展示“机会观察”，明确标记“观察中，不是买入信号”；
  Dashboard 的 CN/US 共享 renderer 以人工机会层优先：确认前显示当前价、确认距离、预计入场区、
  结构风险和 causal Wave3 预估；已 CONFIRMED 则显示正式 T1/阻力、Wave3 target/upside 与
  “确认后的交易判断”。交易规则、目标选择、5% gate、R/R、Entry Zone 与 Decision 原值均保留，
  renderer 不重算 ATR/Entry Zone/Target 公式；Entry Zone 标为“预计入场区（按当前 ATR，仅供观察）”，
  并明确未来以确认日 Decision 为准、超过正式区不追价且不等待回踩补入。WATCH 缺少合法锚点时显示
  具体缺口而不伪造数字；已 CONFIRMED 的 NO_TRADE 继续显示原 Decision 拒绝原因与正式字段。邮件只
  展示有限重点项，完整列表保留在 Dashboard。该能力为 presentation/read-only only，不改变
  production trading semantics。
- Cloud report 的 production state、paper ledger、broker order 与完整 raw/QFQ series persistence
  仍为零，final artifact allowlist 不变；独立Opportunity Ledger接线后只新增session/birth/
  follow-up观察记录（含单session OHLC），不写行情历史表。`asia-close` / `us-close` 是独立的 Sheet-backed
  scheduled writer；Cloud Daily Report 仍只读配置、在内存取行情，不读写 `最新行情` /
  `历史行情_前复权`，也不改变 writer 的事实源边界。Bark/SMTP 仍为可选通知；配置 D1
  VPS credentials 后，通知会先在独立 `system/operational/daily-report-notifications/`
  namespace create-only claim，同一 market/session/protocol 的 fallback 返回
  `NOOP_REPORT_ALREADY_SENT`，不混入 formal D1 session graph。
- 自然运行与只读诊断已证实 US provider 尾部可暂时落后 exact T，且相邻任务读取 Sheets
  曾遇到 429。CN 9/23 writer 已完成正式 QFQ 3/3，但 US 同日 latest 待复核、正式 QFQ
  更新 0；Candidate 大规模历史不足和绿色日报掩盖部分质量亦已形成独立修复 PR。
  合并后仍需自然 schedule 只读验收 US exact-T、Candidate 覆盖、writer、日报状态与通知；
  代码测试或 Cloud 日报送达不能替代该验收，状态保持 `PRODUCTION_ACCEPTANCE_PENDING`。
- 当前处于生产观察：CN/US workflow 公开 fixture + 真实 provider 验证已完成，后续自然
  日报继续核对 Candidate seed / included / deep-ready 数量、individual ENTRY_ALLOWED、
  DATA_BLOCKED 与 JSON/HTML 完整性；自然运行验收仍待完成。仅记录问题，遇真实生产
  blocker 或需要用户决策时停止；这些 observational acceptance 不启动新的开发 Phase 或
  strategy threshold research，也不
  打开已关闭的 post-confirmation retest lifecycle。
- 独立 Candidate / Wave 边界修复的真实只读 CN 回补已完成，零摆幅核心异常解除，
  RUN_STATUS=COMPLETED，JSON/HTML 完整；不可评估的输入仍显式保留，DATA_STATUS 与
  CANDIDATE_STATUS 仍 PARTIAL。不能把运维成功写成全标的数据完整或自然生产/D1 验收；
  修复已进入 main，后续自然运行观察继续独立。既有核心异常 fail-closed 合同继续有效。
 - Browser Dashboard 与 email-safe HTML 在人类可读详情中展示“机会新鲜度”；目标
   空间不足明确写成“目标上涨空间不足”，并同时显示参考价格、T1、实际百分比、5%
   最低要求及可用的 RR 诊断。SETUP_01 target projection 额外把“保守第一障碍
   （最近已确认历史阻力）”与“Wave3 结构目标（最近 Fib 投射）”分开显示；邮件与
   Dashboard 均不重新计算交易几何。

### Daily Opportunity Ledger V1（已合并并接入 production Cloud path，natural acceptance pending）

- Cloud 日报 production path 已接入“日报历史”和 SETUP_01/02 new CONFIRMED 的观察账本；
  尚未产生正式 prospective 生产记录，natural acceptance pending；

  ENTRY_ALLOWED 与所有 NO_TRADE 都纳入，birth只复制原Decision和T日signal close，
  缺字段为null，不重算策略。三张独立tab已用既有Cloud凭证创建并核验写权限。
- 每个机会从T+1起按XSHG/XNYS真实session跟踪10个completed sessions，复用现有
  canonical QFQ continuation；Candidate dropout后仍加载，Opportunity/Paper身份独立。
  描述性记录OHLC、相对signal close的变化、未来区间高低变化、原目标/失效触及。
  不伪造成交、PnL或normalized R；same-bar stop/target为顺序不明。
- summary按market/session行级upsert；birth按market+existing event identity、follow-up
  按opportunity_id/date幂等。DATA_*、漏运行和复权基准改变保留gap，缺口不伪造收益；
  有gap的成熟样本不进入收益统计。日报“机会跟踪”只显示新增、拒绝原因、仍跟踪、
  当日完成10-session数量与按原reason分组的描述统计；样本不足不评价参数。
- 历史显式--date只诊断，release前session不进入正式账本；自然close→next-open窗口
  才创建birth。2026-09-30 fixture的5个拒绝new CONFIRMED得到5/5 observation投影，
  未写成真实prospective生产记录。真实自然启用/T+1/成熟样本仍待未来session。
- ledger失败独立输出OPPORTUNITY_LEDGER_STATUS=FAILED，尽量保留JSON/HTML并使
  workflow可见失败。策略/Paper/持仓/broker、33条Candidate unavailable与D1不变。

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

- `HITHINK_FINANCIAL_API` 已接入并完成真实 acceptance 的 `SINGLE_SOURCE_MARKET_DATA_V1`
  CN price path：生产 `a-share` qfq 使用 provider `adjust=forward`，记录
  `CN_HITHINK_PROVIDER_FORWARD_ADJUSTED_V2` 与完整 request/as-of provenance；旧
  `CN_FORWARD_ADJUSTMENT_ENGINE_V1` 不删除、不改写。`fund-etf` 继续使用同一 vendor 的
  fund historical endpoint，并保留 `HITHINK_FUND_ETF_FORWARD_ADJUSTED_V1` provenance。ETF 历史单次最多五自然年；已合并
  修复对长请求分段连续取数，保留原请求区间，避免默认 2000 日 QFQ 请求的 1003，不换源或
  截断请求。公开 provider 验证已成功，但实际返回历史覆盖仍由 provider 与既有门槛决定。
  财务报表字段仍不属于当前
  minimum market-data contract，也不作为 Wave/Fib/PA 依赖；任何未验证 adjustment contract
  都 fail closed 为 `DATA_ADJUSTMENT_UNVERIFIED`，不换 vendor。

- formal reader 修复已接入既有单源 `校验状态=DATA_OK` 并合并到 main；旧 `已验证`
  标签保持兼容，`DATA_OK` 路径额外执行 canonical provider 与 exact-T 单源合同。新路径复用
  `market_data_contract.validate_single_source_quotes` 校验 latest/QFQ 的 exact-T、无未来
  bar、OHLCV、日期质量与 schema，并核对市场 canonical provider；US 兼容现有 direct
  Chart 行 source 名称 `YahooChart`，不接入 yfinance/未知来源。旧 `已验证` 行兼容性保持，
  闭市、币种和 QFQ 前置条件不降低。公开 provider / 合成配置验证通过不代表真实正式池
  自然验收；Candidate unavailable 个体不纳入该修复范围，不把数据阻断解释为无信号。

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
  `INSUFFICIENT_EVIDENCE_FOR_FORMAL_VS_LIVE_CANDIDATE`。PR #135 当前实现已由
  `daily_decision_chain` 的只读 context projection 透传 ARMED/WATCH causal snapshot、
  SETUP_01 anchors 与 canonical Wave3 presentation projection；历史保存且未包含新字段的
  JSON 会显示明确 data gap，等待下一次自然日报生成新 projection。最近 production daily-report
  样本不足时明确标记为 `INSUFFICIENT_RECENT_LIVE_SAMPLE`。对应 protocol、
  research module 与 compact JSON/Markdown artifact 均为 Development-only，未接入生产。
- CN/US 只读诊断实现已在 main：prospective exact-T 漏斗只在自然日报 final JSON/HTML
  追加 `PROSPECTIVE_EXACT_T_FUNNEL_V1` 紧凑事件证据，不新增 artifact、存储路径或
  production 写入；`FROZEN_DEVELOPMENT_T1_ZONE_STOP_GEOMETRY_V1` 在既有冻结 Development
  的 999 个首次确认事件上重建 T-known T1/Entry Zone/执行止损几何（Development-only，
  不读 T+1）。两者都不改变正式策略、生产状态或既有审计结论；历史聚合日志仍不能转
  换成逐股机会率。
- `SETUP01_EARLY_ENTRY_INDEPENDENT_VALIDATION_V1`（独立样本第一阶段，research-only，
  已随 PR #107 squash merge 进入 main）：唯一实验组是既有正式 SETUP_01
  ARMED 里程碑（`SETUP01_RECOVERY_RATIO=0.5`）作为入场触发，对照组为首次
  `close > H1` CONFIRMED 入场；样本为已冻结 clean-holdout roster（20 CN + 20 US，
  2017-01-01..2026-08-26），其 manifest 证明与 A1 formal 120、development universe v1
  及 Development holdout 的 symbol-level 交集为空。共同分母 2,291 个 Wave2 anchor
  contexts（CN 1,081 / US 1,210，含 942 FAILED、559 never-CONFIRMED、551 screened-out、
  8 timeout）；328 个 paired later-CONFIRMED 上 median headroom 改善 +0.265R，CN/US
  结构失效率 20.4% / 23.4%、确认率 33.2% / 33.5%，均满足预注册 floors 与 gates。
  结论 `FIRST_STAGE_SUPPORTED_FOR_SECOND_STAGE_APPLICATION`：只支持申请第二阶段执行
  成本／净收益研究，不授权任何 production rule、Entry、Stop、Target、5%、2R、仓位或
  allocation 变更。较早入场结构上必然取得更低入场价（非 edge 证明），且约 2/3 触发
  最终未确认；成本、净收益、胜率、期望与 Final OOS 均不在本阶段范围内。
- `SETUP01_EARLY_ENTRY_SECOND_STAGE_DECISION_V1`（第二阶段执行可行性决策节点，
  research-only，已随 PR #109 squash merge 进入 main）：在同一冻结 cohort 上重建 2,291 个 anchor
  contexts 与 987 个 ARMED 信号（986 个有可执行 exact next-session OPEN），审计实验组
  的可交易定义是否已由冻结规则唯一确定。结论：入场准入、确认前执行止损／风险基准、
  确认前目标与 5%/2R 口径、确认前终止与长期未确认处理、确认后 PM/Exit 衔接、成本与
  可交易性输入均**未被唯一确定**，因此状态为 `READY_FOR_DECISION`，未注册、未冻结任何
  第二阶段协议，也未计算成本、净收益、胜率或期望。已由冻结规则唯一确定的部分：ARMED
  触发、`data <= t` 信息集与 exact T+1 OPEN、结构失效（close <= 已确认 Wave 2 low /
  Wave 1 origin）、完整共同分母。交付登记三个互斥候选 package：A 仅结构止损、
  B 结构低点 − 0.5×ATR14（信号日）执行止损、C 现行确认纪律前移至信号日（含
  trigger band、5% 与 2R）。几何事实：A 准入 984/986、B 986/986、C 0/986（831/986 先被
  5% 目标上行门槛阻断）；每笔 1R 距离中位数 A 5.7% / B 7.1%（占 entry），0.5% 风险下
  名义金额中位数 A 8.8% / B 7.0%（占 allocation_budget）。未选择任何 package。
- `SETUP01_EARLY_ENTRY_STAGE2_ECONOMIC_VALIDATION_V1` 位于保持 OPEN 的独立 PR #110，
  未合并：用户选择的受约束 `PKG_B_ATR_EXECUTION_STOP` 在同一已暴露样本上得到
  `INSUFFICIENT_EVIDENCE`；实验组净 R 在 CN/US 均为负，完整现行 Decision 成交过少，
  且删失敏感性会改变比较排序。该结果不授权生产变更，也不允许改参重跑；PR 状态和 CI
  以 GitHub 实时事实为准。
- `SETUP01_POST_BREAKOUT_DUAL_PATH_ENTRY_RESEARCH_V1_DRAFT`（research-only）已形成
  可预注册但不可执行的架构草案：以既有首次 `close > H1` event 为 overlay 出生点，
  因果路由 `BREAKOUT_CONTINUATION` 与 `BREAKOUT_RETEST`，明确 running-leg Fib 与 confirmed
  Swing 的信息边界、两类信号 K、next-session buy-stop、路径止损、target/exit、CN/US
  执行差异、5%/2R 两种研究角色、已暴露样本与新独立验证漏斗。状态为
  `ARCHITECTURE_FROZEN_AWAITING_D2_DATA_AND_COST_FREEZE`。用户已在新样本结果访问前选择
  `PRICE_ACTION_ONLY`、`ONE_PER_PATH_UNTIL_FILL`（20-session 总窗口不重置）、
  `SIGNAL_SUPPORT_ATR_STOP`、primary `X1_MECHANICAL_T1_EXIT`、primary
  `G1_SIGNAL_FIRST_DIAGNOSTIC_GATES` 与 `D2_NEW_SYMBOL_DISJOINT_HISTORICAL`；X2 与 G0
  分别只作预注册 sensitivity / nested attribution。冻结前确认 B 日可直接成为路径 A
  信号 K（最早 B+1 执行，且消耗同一 A 路径机会），路径 B 仍须等待 B 后真实回踩；目标
  按 `price > entry_trigger` nearest-first 冻结，`entry_ceiling` 不得预过滤较近 T1。上述
  修正在 D2 roster、行情、信号和收益均未创建或访问时记录，并由独立 architecture
  freeze record 绑定协议 hash。D2 数据可行性审计结论为
  `BLOCKED_EXISTING_FREE_STACK_NO_COMPLIANT_POINT_IN_TIME_SOURCE`：US 缺历史 membership/
  退市 master，CN 仍缺逐日 board/ST/涨跌停/lot、完整 identity lifecycle 与已证明公司行动
  合同。D2 roster、provider、成本来源和 snapshot/hash 尚未冻结，因此仍不可执行；未
  建立 roster、抓取 D2 bars、生成信号或运行经济回放，
  未改变生产 SETUP/Risk/Paper/Sheet/broker 或 Final OOS。
- `SETUP01_POST_BREAKOUT_D1_PROSPECTIVE_V1` 已作为独立协议修订冻结，明确以 D1 前瞻
  时间隔离替代受 point-in-time 数据源阻塞的 D2；D2 审计与 architecture freeze 保留，
  双路径 signal/opportunity/stop/target/exit/gate 选择均未重选。已实现 research-only
  causal Path A/B observer、next-session OHLC 模型、CN T+1、同日歧义、右删失、五组件
  hash-bound session snapshot、content-addressed immutable reference store、跨日幂等、
  missing/hash/protocol 检测、clean-directory recovery 与独立中文报告/CLI。
- D1 durable backend 已由用户正式决定改为用户自有 Ubuntu VPS
  （`SETUP01_D1_VPS_SSH_DURABLE_STORAGE` / `VPS_D1_DURABLE_BACKEND_V1`）。GitHub Actions
  继续做全部计算；VPS 只做 immutable storage、activation/pointer 存储、SHA 校验、
  verify/recovery/export/migrate 与磁盘健康，不主动抓行情、不运行 pipeline、不读取
  holdings/account/Paper/production Sheet/broker/Final OOS。实现包括单一
  stdlib-only、repository-owned remote helper（SSH 非交互、流式、低内存）、
  `objects/`、`sessions/CN/`、`sessions/US/`、`system/activation|validation/`、
  `manifests/` 目录合同、create-only（`O_CREAT|O_EXCL`）+ fsync + 落盘重算 SHA-256 +
  read-back、`IDEMPOTENT_REPLAY`/冲突/partial transfer/missing/corrupt fail closed、
  pointer/object 与 component/event hash 交叉校验、host key pin
  （`StrictHostKeyChecking=yes` + 冻结 fingerprint，禁止 `no`）、专用非 root 账户、
  root-owned helper、私有 key 只经 Secret 注入临时文件、磁盘 free-space 安全/危险阈值
  （危险阈值触发 `D1_STORAGE_LOW_SPACE_FAIL_CLOSED`，绝不自动删除 evidence）、root
  manifest、VPS → 空目录 verified export/recovery 与旧 VPS → export → 新 VPS import →
  full verify 迁移路径，以及 storage-validation / activation / per-market market-close
  reconciliation workflows；另有专用 manual `SETUP01 D1 VPS Read-Only Verify` workflow，
  只调用 `vps-verify --full-objects`，不注入行情、持仓、broker 或 Cloudflare 凭证，raw
  receipt 只留 runner 临时目录，artifact 与 Job Summary 仅保留 sanitized summary。合同
  细节见 `docs/research/SETUP01_D1_VPS_DURABLE_STORAGE.md`。
  VPS 已完成一次性初始化（专用非 root 账户 + root-owned helper + 冻结 storage root 与
  目录合同），运行期凭证只存在于 GitHub Secrets；真实 VPS synthetic storage validation
  已 `VERIFIED`（create-only、落盘重算 SHA-256、read-back、幂等重放、同 identity 不同
  bytes fail-closed、空目录恢复、CN/US 正式 graph 为空），并通过同一 SSH/helper 路径在
  真实磁盘上重跑确认。10 GB system disk 已投入使用：collector 每次都报告 total/used/free/
  store bytes/object·session count，危险阈值 fail closed 且不自动删除任何 evidence。
- `scripts/run_market_close_reconcile.py` 是 CN/US D1 primary、Cloudflare fallback 与 VPS
  watchdog 的共同执行边界：解析最近 exact completed session，检查 VPS session pointer，
  只在 `session close <= now < next exchange session open` 内运行 natural collector；已提交
  返回 `NOOP_ALREADY_COMMITTED`，缺失但过了 next-open 返回 `MISSED_PROSPECTIVE_SESSION`
  且绝不历史 backfill。Daily Report 与 D1 reconciliation 仍是两个独立业务 workflow。
- GitHub native CN/US schedules 是 primary；Cloudflare Worker Cron 是第一 fallback，独立
  Ubuntu VPS user-level watchdog 是第二 fallback。两者只 dispatch repository-owned Daily
  Report/D1 reconciliation workflow，不抓行情、不运行策略、不读取 holdings/Paper/broker、
  不写 `/srv/d1-research`，不复制交易逻辑。Cloudflare Worker 已部署并完成 CN/US 受保护
  smoke；VPS main 版本已部署，非 root runtime user credential 为 `0600`，CN/US timers
  已 `enable/active` 并完成 trigger-only smoke。
- 独立公开 source/observer contract 已接入既有 Candidate runtime：保存当日 universe、raw
  Stage-A payload/hash、QFQ exact-T causal prefix/hash、精确 session identity、既有 causal
  Swing/Fibonacci 与双路径 observer 的 signal/touch/no-signal、trigger/ceiling、stop、
  nearest-first T1/T2/T3、G1/G0/5%/2R、`ECONOMIC_ATTRACTIVENESS`、next-session model
  execution/skip、open follow-up set 和中文报告；不从普通 Cloud 日报摘要推导正式 D1 证据，
  不读取 holdings、Paper、production Sheet/state 或 broker。natural collector 与生产日报
  独立，D1 failure 不改变生产日报结果。
- 数据合同迁移已新增 `SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2`：保存 attempted/usable/
  missing/invalid universe、per-symbol source status、provider identity、adjustment engine
  version、session identity、index membership/current snapshot metadata 与 per-symbol
  provenance；symbol-level partiality 不再被写成 `NO_SIGNAL`。V1 legacy activation
  继续位于 `system/activation/{CN,US}.json`，V2 使用 append-only
  `system/activation_epochs/{CN,US}/SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2.json`，按
  source-contract version 精确绑定，无 `current`/`latest` fallback。natural collector 在
  durable verify、formal session count 与 activation version 通过前 fail closed：V1 返回
  `D1_SOURCE_MIGRATION_PENDING`，formal evidence 已存在则返回
  `D1_SOURCE_MIGRATION_AFTER_FORMAL_EVIDENCE`。
- `SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2` 的 CN raw/QFQ basis 保持旧
  `CN_RAW_CORPORATE_ACTIONS_QFQ_CONTRACT_V1` immutable；新的
  `SETUP01_D1_CN_PROVIDER_FORWARD_QFQ_CONTRACT_V1` 已 code-ready，activation epoch
  只允许写入 `system/activation_epochs/CN/SETUP01_D1_CN_PROVIDER_FORWARD_QFQ_CONTRACT_V1.json`，
  当前不创建真实 activation、不运行 natural collector、不回填。
- 不可变 per-market activation record 仍绑定冻结 protocol SHA、VPS backend/version、
  storage identity hash、code SHA、冻结 signal/stop/exit/gate package、source contract、
  cost scenario、observer version、首个 eligible exchange session 与固定 12 个月边界。
  V1 legacy activation 继续保留，V2 使用 append-only epoch；当前状态为
  `D1_V2_ACTIVATION_COMPLETE`。CN record 为
  `321179a6beed10f8786a1cc27e43676085b04b344483426d708c74246304a067`，timestamp 为
  `2026-09-30T03:46:23+00:00`，`code_sha=0633e80a81302d0da8d5592c404bf80275a3c8cf`，
  `storage_identity_sha256=43815f2754928dc7be5e58e409a6d0c61493040fbe9f56f6050a93e374675116`，
  canonical path 为 `system/activation_epochs/CN/SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2.json`。
  US record 为 `bb3409ddb1059a34e18375495b5bf976dab31b289b92f7a77ccbb21966bc1f51`，timestamp
  为 `2026-09-30T07:02:56+00:00`，同一 `code_sha` 与 storage identity，canonical path 为
  `system/activation_epochs/US/SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2.json`；其
  `source_contract_version=SETUP01_D1_SINGLE_SOURCE_CONTRACT_V2`、
  `observer_version=SETUP01_POST_BREAKOUT_DUAL_PATH_OBSERVER_V1`、
  `protocol_version=SETUP01_POST_BREAKOUT_D1_PROSPECTIVE_V1`、
  `protocol_sha256=ee55ec82959be510a8d9a2d84a99143de3638e550f88527536dad9fd5546d0e0`，
  backend 为 `SETUP01_D1_VPS_SSH_DURABLE_STORAGE / VPS_D1_DURABLE_BACKEND_V1`，first eligible
  session 为 `2026-09-30`，last eligible 为 `2027-09-29`，end boundary 为 `2027-09-30`，
  final cutoff 为 `2027-09-30T04:00:00+08:00`。US record 状态为
  `D1_ACTIVATION_READY_FOR_FIRST_ELIGIBLE_SESSION`，未允许 formal entry、paper write 或
  production state write。不得用人工日期或旧日报补 session。
- VPS helper 曾为已知旧版本，且不会扫描 `system/activation_epochs/`；branch-only maintenance
  只原子更新 `/srv/d1-research/system/d1_vps_store_helper.py` 到授权 main helper bytes，
  read-back SHA 与 mode 一致、无 `.part`/backup residue。最终 main read-only verify 为
  `VERIFIED`，backend/storage identity 正确，CN/US formal session 为 `0/0`，V1 hash 为
  `01d339d52732966d50a33245321b1dc873a7f200f801e887e166d290ea83cb81` /
  `a1a97dabfa01adeaab964c4ebecc6f686497c1ac1fafa5c399a937d8fb35f85e`，CN/US V2 均 present，
  unreferenced object 与 errors 均为 `0`，`continuation_ready=true`。自然 eligible session
  之前不得运行 backfill 或 formal collector。
- 同一 market activation identity 下只允许一个 approved durable backend：activation record
  绑定 backend identity/version 与 storage identity hash，因此保留的 GCS/Drive adapter 无法
  在 VPS activation 生效期间写 formal D1 evidence（运行期 fail closed），不构成 split-brain。
  GCS adapter 保留为未来可选迁移 backend；其 workflows 已标记
  `[DISABLED]`/non-production，也不需要 GCS Secrets 或 Google Billing。
- VPS 为月租实例：到期日不等于 D1 结束日，deletion/reinstall 属外部 durability risk；系统
  不把它描述为永久存储，也不代用户续费或修改云主机账户。
- Google Drive 路线仅作为历史失败证据保留：主线上的 service-account `files.get` 对配置
  folder ID 返回 404，未创建 validation object，未发生正式写入/迁移；不扩大 Drive OAuth
  scope，Drive synthetic adapter 仅保留为历史测试资产。未访问历史经济样本、Final OOS、
  真实持仓，未启用 Paper、production Sheet/state 或 broker 写入。
- 普通股票绝对收益偏好已作为独立研究/产品诊断登记：`SIGNAL_VALID`、`RISK_VALID`、
  `TARGET_GEOMETRY`、`ECONOMIC_ATTRACTIVENESS`、`RESEARCH_ADMISSION` 分开报告；日常中文研究
  报告记录最近合法 T1 gross headroom、后续结构目标不确定性、止损距离/1R/RR/成本，并仅在
  合法最终结果存在时报告 net return/net R/持有期/资金占用。当前未设新的绝对收益硬阈值，
  未改变 primary economic evaluation、T1 全退或正式研究准入。
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

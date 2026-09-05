# ARCHITECTURE.md — 系统真实架构

本文件描述**真实代码**，不是理想架构。任何重构后必须同步更新本文件。

## 数据流

```text
Weekly bounded seed refresh (read-only, no Sheet write)
        ↓
trading/candidate_universe_sources.py
        → BaoStock HS300 ∪ CSI500 + basic/industry metadata (CN)
        → official iShares IWB latest-holdings.csv (US)
        ↓
trading/candidate_universe.py
        → security/sector normalization
        → documented board-rule affordability gate
        → 20D/60D traded-notional proxy and history/data-quality gate
        → sector-aware TOP_N_PER_SECTOR selection
        ↓
lightweight candidate rows / fixture (no production state, no Sheets)
        ↓
existing Data Quality → Weekly / Daily → Swing → Wave → Fibonacci → Setup chain

GitHub Actions scheduler (cron)
        ↓
main.py  (CLI 入口: --group asia|us|all, --mode latest|full, --fixture)
        ↓
SheetsClient.config() / records("自选清单")          ← Google Sheets
        ↓
对每个自选标的 (启用=True 且市场∈目标组):
    fetch_latest_with_retry(主数据源)                [providers: latest mode]
    fetch_latest_with_retry(校验数据源)              [providers: latest mode]
        → yfinance → YahooChart 回退
        → BaoStock (仅 A股)
        → Tencent / Sina 快照回退 (CN/HK/US)
        ↓
    evaluate_latest_snapshot()                      [latest_snapshot: shared contract]
        → latest_completed_market_session / ordinary freshness guard
        → validate_quotes / quote_sanity_issue / fresher_quote
        → project_latest_row / project_validation_row
    SheetsClient.upsert_latest("最新行情")
    SheetsClient.append_rows("校验记录")
    SheetsClient.append_rows("运行日志")

    # --mode full only:
    select_history_series(...)                      [main]
    fetch_with_retry(历史数据源, "qfq")             [providers]
        → 仅 yfinance / BaoStock；不使用快照源
    confirmed close + qfq末日一致                    [main gate]
        → evaluate_setup03_event()                   [trading.events]
            → detect_platform_breakout_with_diagnostics() [trading.setup]
            → 仅最新bar首次CONFIRMED且未发布时
               decide_platform_breakout()            [trading.decision]
        ↓
        → upsert_history(未复权/前复权) + upsert_decisions

    # repository-local holdings-data-manager Skill:
    上层自然语言请求
        → skills/holdings-data-manager/SKILL.md  [thin contract only]
        → holdings_data_manager.py               [one normalized symbol]
        → shared latest-snapshot evaluator      [completed date + validation]
        → existing fetch_with_retry()           [raw + qfq missing intervals]
        → observed provider session-date coverage/QC
        → SheetsClient.upsert_history()         [idempotent date key]
        → SheetsClient.upsert_latest()          [latest snapshot]
        → SheetsClient.append_rows()            [校验记录]
        → SheetsClient.upsert_watchlist()       [enable last]
        → existing 运行日志 append-only audit

    The holdings manager never calls the full pipeline and never enters
    SETUP/Wave/Fibonacci/Decision/Risk/Position/Exit or research paths.

    # manual/local read-only Wave shadow (not a GitHub Actions gate):
    scripts/run_wave_shadow.py
        → read enabled 自选清单 + explicit qfq history source
        → trading.wave.evaluate_wave_scenario()
        → JSON/CSV artifact + GitHub Step Summary
        (no Sheet write, no Decision, no production entry)
```

`trading/candidate_universe_sources.py` and `trading/candidate_universe.py` form the
bounded V1 candidate layer.  The source adapters are read-only and do not reuse the
production watchlist as a universe, do not create a security master, and do not write
Google Sheets, broker state, orders, or strategy state.  `CandidateRecord` exposes
inclusion/exclusion reason, sector, rank, affordability tier, documented minimum quantity,
20D/60D liquidity proxy and history freshness.  It intentionally has no Strategy action
field and cannot produce `ENTRY_ALLOWED`.

### Execution modes

`--mode latest` 是亚洲/欧美 scheduled workflow 的生产路径：只读取自选清单，使用短窗口 latest quote provider，分别执行 source-date evidence、ordinary-calendar freshness guard、双源校验和最新行情写入，并追加校验记录/运行日志。source date 早于 ordinary-calendar guard 时仍可显示该行情，但必须 `待复核/PARTIAL_DATA_QUALITY`；该 guard 不声明交易所开市且不推断节假日。该模式不读取 `交易决策`，不抓取 qfq 或多年历史，不运行 SETUP_03，且 `history_rows_written=0`。

`--mode full` 保留需要历史数据的手动路径，继续执行未复权历史、qfq、SETUP_03 和 Decision。它不由 daily schedule 调用；workflow_dispatch 可显式选择该模式。

`holdings-data-manager` 是上层 ChatGPT/Codex Skill 使用的单标的路径：它只执行确定性的 `ADD`、`REENTER`、`CLOSE`、`SYNC`，不调用 `main.run()` 或把完整 `full` pipeline 当作新增股票接口。ADD/REENTER 以同一 completed trade date 完成 latest snapshot、raw/qfq history QC、latest upsert、validation append 和 enable-last；已启用重复 ADD 先 reconciliation，完整历史不重抓。provider、日期/OHLCV 质量门控与 Sheet 写入仍复用现有模块。

`main.run(mode="latest")` 与 holdings manager 共享 `latest_snapshot.py` 的
evaluator 和 row projection。共享 contract 保持 source-date evidence、普通日历
freshness guard、future/sanity、`validate_quotes`/`fresher_quote`、single-source
和 pending 状态语义一致；manager 额外用 identity expectation 和 publishable
gate 防止将 future/stale/invalid identity 作为 lifecycle snapshot 发布。

历史 coverage 只使用 provider/已有历史的 observed session dates；不以 weekday 推断交易所开市，不伪造休市日 bar。raw/qfq 日期集必须一致、无重复，并满足一年窗口的末日、边界、最小 180 bar 和最长 14 日 observed-session gap contract。`REENTER`/`SYNC` 只请求尾部或异常中段 gap；完整历史不会因 US/CN 节假日重复抓取。`scripts/holdings_data_manager_smoke.py` 提供不写 Sheet 的真实 provider read-only smoke。

## 目录结构（扁平，未使用 src/ 包布局）

```text
.
├── .github/workflows/
│   ├── asia-close.yml        # 亚洲收盘任务 (CN/HK/JP)
│   ├── us-close.yml          # 欧美收盘任务 (US/SE)
│   └── setup03-replay.yml    # SETUP_03 手动只读历史回放
├── .devcontainer/
│   └── devcontainer.json     # GitHub Codespaces / VS Code Dev Container
├── AGENTS.md                 # AI 开发人员项目规则
├── docs/                     # 项目共享上下文（本文件所在）
├── core.py                   # 数据模型与校验逻辑（无外部依赖）
├── main.py                   # CLI 入口与流水线编排
├── holdings_data_manager.py  # 单标的持仓生命周期编排（ADD/REENTER/CLOSE/SYNC）
├── latest_snapshot.py        # scheduled latest 与 holdings 共用 evaluator/projection
├── providers.py              # 行情数据源适配器与回退链
├── sheets_client.py          # Google Sheets 客户端与表头定义
├── skills/
│   └── holdings-data-manager/
│       └── SKILL.md           # 上层 Skill 薄 contract，不承载业务实现
├── scripts/
│   ├── run_setup03_replay.py # 读取真实配置并输出 SETUP_03 回放/研究 artifact
│   └── holdings_data_manager_smoke.py # provider-only raw/qfq coverage smoke
├── research/
│   ├── replay_input.py      # canonical input hash / manifest / frozen replay
│   ├── frozen_validation.py # Phase 5E 固定数据集描述性验证
│   ├── confirmation_diagnostics.py # Phase 5F 确认前守恒漏斗/near-miss
│   ├── platform_tolerance_sensitivity.py # Phase 5G 单参数平台容差敏感性
│   ├── platform_structure_calibration.py # Phase 5H 市场分层平台结构校准
│   ├── parameter_freeze.py # Phase 5I 冻结规范读取、完整性校验与冻结前审计
│   ├── setup03_frozen_spec.json # Phase 5I 机器可读参数 inventory / frozen spec
│   ├── structural_validation_protocol.py # Phase 5J 结构验证协议读取/完整性校验/静态审计
│   ├── setup03_structural_validation_protocol.json # Phase 5J 机器可读结构验证协议
│   ├── structural_validation_protocol_v2.py # Phase 5J-v2 CN/US scope revision loader
│   ├── setup03_structural_validation_protocol_v2.json # Phase 5J-v2 CN/US scope contract
│   ├── phase5k_b0_dataset_contract.py # Phase 5K-B0 获取契约/标准化/QC/覆盖纯校验
│   ├── phase5k_b0_dataset_acquisition_contract.json # B0 v1 historical audit evidence (immutable)
│   ├── phase5k_b0_dataset_acquisition_contract_v2.json # B0 active acquisition contract
│   ├── phase5j_v4_protocol.py # Phase 5J-v4 protocol version/hash gate
│   ├── phase5j_v4_lifecycle_attribution.py # read-only lifecycle trace/root/lineage/counterfactual classifier
│   ├── phase5j_v4_evidence.py # mechanical parity, aggregation, hashes and report
│   └── backtest/
│       └── setup03.py       # T+1 执行回测与参数敏感性（只读）
├── trading/                  # Trading Core 与只读诊断
│   ├── models.py             # 数据模型 + 输入校验
│   ├── indicators.py         # Wilder ATR / RSI、EMA
│   ├── swing.py              # causal pivot 状态机
│   ├── structure.py          # Market Structure
│   ├── fibonacci.py          # Fibonacci levels
│   ├── risk.py               # R/R + Position Size
│   ├── setup.py              # SETUP_03 Platform Breakout
│   ├── decision.py           # SETUP_03 Decision Engine + 同源只读 gate diagnostics
│   ├── events.py             # 生产/回放共享的终态事件语义与幂等键
│   ├── replay.py             # SETUP_03 Historical Replay & Diagnostics（只读）
│   ├── wave.py               # Wave Scenario Engine v1（只读、严格 as-of）
  │   ├── setup01.py            # SETUP_01 Wave 2 → Wave 3 v1 evaluator
  │   ├── setup01_replay.py     # SETUP_01 strict as-of structural replay
  │   └── setup01_decision.py   # SETUP_01 independent Decision/Risk v1
  ├── docs/WAVE_SCENARIO_ENGINE_V1.md # Wave Engine v1 protocol
  ├── docs/SETUP_01_WAVE2_TO_WAVE3_V1.md # SETUP_01 v1 protocol
  ├── docs/SETUP_01_DECISION_RISK_V1.md # SETUP_01 Decision/Risk v1 protocol
  ├── scripts/run_wave_shadow.py # private/local holdings structural shadow capability
  ├── scripts/run_setup01_structural_replay.py # development-only SETUP_01 replay
  ├── scripts/run_setup01_decision_funnel.py # development-only Decision/T+1 funnel
  ├── scripts/run_setup01_decision_shadow.py # optional private Decision shadow capability
  ├── scripts/run_setup01_generic_operational_shadow.py # synthetic-only operational gate
├── README.md
├── requirements.txt
├── .gitignore
└── tests/test_validation.py  # unittest 测试
```

## 模块职责

### core.py

- `Quote` / `ValidationResult` 数据类
- `validate_quotes()`：双源校验（日期、收盘价、成交量容差）
- `relative_diff()`、`latest_quote()`
- `fresher_quote()`：优先保留 quote sanity 正常者，再比较交易日期；同日主源字段异常而校验源正常时采用校验源
- `market_close_confirmed()`、`expected_latest_trade_date()`：收盘时间与时区判断；后者的无 observation 形式保留兼容用途
- `ordinary_calendar_freshness_guard()`：按本地 weekday、收盘 buffer 返回 ordinary-calendar freshness 下限；不使用交易所节假日 calendar
- `latest_completed_market_session()`：只从有效 source quote date 推导 source-evidence 结果，收盘前排除当日、未来日期 fail closed；latest 必须另与 ordinary-calendar guard 比较
- `quote_sanity_issue()`：OHLCV 字段一致性检查
- 依赖：仅标准库

### providers.py

- `PROVIDERS` 注册表：`BaoStock`、`Tencent`、`Sina`、`yfinance`
- `fetch_with_retry()`：按回退链抓取并重试，支持 `target_trade_date` 过期判断
- `fetch_latest_with_retry()`：独立的短窗口 latest quote 路径；scheduled latest 不调用 full-history fetch
- `_configured_source_candidates()`：数据源回退链 + AKShare 遗留别名路由
- `fetch_yfinance()`：yfinance，失败回退 `_fetch_yahoo_chart()`（无 cookie 的 chart 端点）
- `fetch_tencent()` / `fetch_sina()`：实时快照解析（含美股常规交易时段字段处理）
- `fetch_baostock()`：A股历史（仅 CN）
- 依赖：标准库；baostock / pandas / yfinance 均按需惰性导入

### sheets_client.py

- `SheetsClient`：gspread 封装，凭证来自环境变量 `GOOGLE_SHEET_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON`
- `records()` / `config()` / `upsert_latest()` / `upsert_history()` / `upsert_decisions()` / `upsert_watchlist()` / `append_rows()`
- `_clean()`：datetime → Google Sheets 数值（北京时间序列号）
- 各表表头常量：`LATEST_HEADERS` / `HISTORY_HEADERS` / `DECISION_HEADERS` / `VALIDATION_HEADERS` / `LOG_HEADERS`
- 依赖：标准库；gspread / google-auth 惰性导入

### holdings_data_manager.py / skills/holdings-data-manager/SKILL.md

- `normalize_holding()`：把 symbol、market、provider mapping 规范化；市场或身份不明确时 fail closed。
- `parse_natural_language()`：只识别唯一的 `ADD` / `REENTER` / `CLOSE` / `SYNC` 意图和单一标的。
- `HoldingsDataManager.execute()` / `execute_text()`：逐标的执行历史覆盖、启用/停用和审计；复用现有 provider、`core` 质量逻辑和 Sheets schema。
- 新身份以最近已完成市场交易日为上限补过去一个自然年 raw/qfq；既有身份只请求缺口；CLOSE 永不删除历史。
- coverage/QC 只依赖 observed session dates：raw/qfq 日期集一致、无重复、至少 180 bar、起点边界最多 7 天、末日到达目标、最长 observed-session gap 不超过 14 天；不把 weekday 当交易日。
- 已启用身份 ADD 幂等；已停用身份 ADD 自动按 REENTER 补缺口并恢复启用；节假日不生成 bar；read-only smoke 不连接 Sheets。
- `SKILL.md` 只定义上层调用 contract、允许/禁止动作和示例，不实现行情、Sheet 或生命周期业务。
- 依赖：`core`、`main.quote_row`、`providers`、`sheets_client`；不依赖 `main.run()`，不触发任何策略/研究路径。

### main.py

- CLI：`--group`（asia/us/all）、`--mode`（latest/full）、`--fixture`
- `run(group, mode)`：按 execution mode 编排；latest 不读取/写入历史和 Decision 表
- `wanted_markets_for_group()`：任务组 → 市场集合
- `as_ratio()` / `as_bool()`：解析 Google Sheets 配置
- `quote_row()` / `decision_row()`：纯展示映射，不重算 Trading Core 逻辑
- `evaluate_set03_decision()`：正式收盘 + qfq 末日一致双门控后，仅发布当前最后一根 K 线首次进入 CONFIRMED 的事件
- 启动时读取 `交易决策` 已有事件键；同一标的/交易日/Setup 已存在时不重新计算 Decision，持续 CONFIRMED 状态日也不生成新行
- 单标的 Setup/Decision 异常仅写入运行日志，不中断其他标的与行情表写入
- `trading_parameters()`：从 `参数设置` 读取全部 Setup/Decision 参数，缺失时 fail fast
- 依赖：core；providers / sheets_client 惰性导入

### trading/events.py

- `terminal_event_type()`：统一判定 CONFIRMED/FAILED 是否在当前最后一根 K 线首次进入终态
- `evaluate_setup03_event()`：生产与回放共用；复用现有 Setup / Decision Engine，仅为新 CONFIRMED 事件计算 Decision；已发布事件键命中时不重算
- CONFIRMED 事件同一 as-of 上下文携带 `signal_date` / `confirmed_date` / `signal_close` / ATR，供 Phase 5A artifact 与 Phase 5B 共用
- CONFIRMED Decision 使用同一次 production calculation 取得不改变 `Decision` 的 `DecisionDiagnostics`，并随事件 contract 传给 Replay/Research
- 不复制 Swing / Setup / Decision 公式
- 同一次 production Setup 计算携带只读 `SetupDiagnostics`；兼容入口仍只暴露原 `Setup`，不改变发布与交易行为
- Phase 5J-v4 instrumentation 在同一状态机循环中额外记录 as-of confirmed swing identity、new-swing eligibility、gate pass 与 `last_terminal_index`；这些字段只进入 research trace，逐 bar 对 `origin/main` 的 `Setup` 与 CONFIRMED/FAILED 输出 parity 必须为 0 mismatch

### trading/replay.py

- `replay_setup03_history()`：对单标的历史序列逐日回放 SETUP_03，传入 Trading Core 的输入严格为 `quotes[:i+1]`
- `replay_setup03_symbols()` / `replay_summary_rows()`：输出每标的 NONE/WATCH/ARMED/CONFIRMED/FAILED 状态日数与日期、CONFIRMED/FAILED 事件次数与日期，并统计 CONFIRMED 事件日上的 Decision 动作
- `ReplayEvent` / `replay_event_rows()`：只读终态事件流水及关键 Setup/Decision 字段
- `validate_replay_history()`：空序列、重复/乱序日期、样本不足、最新日期和异常日历缺口门控
- 只读诊断层；不写入 `交易决策` 表，不复制 Swing / Setup / Decision 交易逻辑，不修改生产参数

### trading/wave.py / scripts/run_wave_shadow.py

- `trading.wave.evaluate_wave_scenario()` 先按 `as_of_date` 截断输入，复用
  causal confirmed Swing、Weekly→Daily Market Structure 与现有 Fibonacci
  levels，输出有限 primary/alternate scenario、证据、反证、结构失效和
  `SETUP_01`/`SETUP_02` context eligibility；不输出 Entry/Decision。
- Weekly 当前 ISO 周不进入母级别状态；未来 bar append 在固定 as-of 下不
  改写历史结果。`evidence_score` 是规则计数，不是收益/概率评分。
- `WAVE_2_TO_3_CANDIDATE` 明确要求 `peak.price > origin.price`；as-of close
  触及或跌破 impulse origin 时输出失效/UNKNOWN，`SETUP_01` context 为 false。
  ABC candidate 同样要求真实向上 impulse，且 current close 不得跌破其 origin。
- `run_wave_shadow.py` 只读启用持仓与 qfq 历史，输出 JSON/CSV artifact 和
  summary，不写 Google Sheets、历史行情或交易决策；报告记录
  `history_last_date`、`latest_completed_session`、`freshness_status`。qfq
  history 未达到最新完成 session 或 ordinary-calendar freshness 下限时
  `DATA_STALE` 并 fail closed，不评估 stale scenario。

### trading/setup01.py / trading/setup01_replay.py

- `SETUP_01` 独立消费 `trading.wave.evaluate_wave_scenario()` 的 primary
  `WAVE_2_TO_3_CANDIDATE`；不修改 SETUP_03 的 `Setup`、Decision 或事件路径。
- v1 只实现 `NONE/WATCH/ARMED/CONFIRMED/FAILED`。ARMED 的固定因果恢复条件为
  `close >= wave2_low + 0.5 * (wave1_peak - wave2_low)` 且尚未严格突破
  `wave1_peak`；CONFIRMED 只接受 `close > wave1_peak`。
- `wave1_origin` 是 wave-scenario invalidation，confirmed `wave2_low` 是
  SETUP_01 trade-structure invalidation；两者分别输出，均不是 execution stop。
- 所有 Wave1/Wave2 Swing 必须已经 confirmed，weekly DOWNTREND 或 primary
  `ABC_CORRECTION_CANDIDATE` 阻断 SETUP_01。Fibonacci 只复用 canonical
  retracement levels/regions 作为 diagnostics，不是 hard gate。
- SETUP_01 projection 明确区分持续存在的历史 terminal lifecycle 与当前日期
  的新事件：`terminal_event_type`、`terminal_event_date`、
  `is_new_confirmed_event_as_of`、`is_new_failed_event_as_of` 及
  `is_live_preconfirmation_candidate`。其中前两者保留 terminal 事实，两个
  `is_new_*` 仅在 terminal date 等于 as-of date 时为真，live candidate 只对
  `WATCH`/`ARMED` 为真；这些字段不改变 lifecycle/event identity/count。
- `replay_setup01_history()` 对每个历史日严格使用可见前缀，只产生
  `CONFIRMED`/`FAILED` first-entry event identity；不访问 returns/outcomes/OOS，
  不产生 `ENTRY_ALLOWED`。

### trading/setup01_decision.py / scripts/run_setup01_decision_funnel.py

- Decision/Risk v1 只接收 T 日首次 `CONFIRMED` event；persistent terminal
  `CONFIRMED` 不会重新决策，同一 event identity 最多产生一个 Decision。
- T close 只形成 plan，最早执行为精确 T+1 session 的 `OPEN`；不执行同 bar，
  不读取 T+1 high/low/close。Entry、固定 Entry Zone、execution stop、
  structural invalidation 与 Wave Scenario invalidation 语义均与 protocol 一致。
- Target 先于 R/R 生成，只复用 T-known confirmed highs 与
  `trading.fibonacci.EXTENSION_RATIOS`；`actual_entry` 仅表示真实成交，严格满足
  `actual_entry != None iff outcome == EXECUTED`，观察价格使用 `t1_open`。
- Funnel 是 `DEVELOPMENT_EXPOSED`、只读、无 outcome/OOS 的聚合器，按 total/CN/US
  /symbol 输出 `CONFIRMED → Decision → ENTRY_ALLOWED/NO_TRADE(reason) → T+1` 守恒。

### scripts/run_setup01_generic_operational_shadow.py

- generic operational shadow 只读取 `GENERIC.*` controlled public synthetic
  fixture，不读取 `自选清单`、真实 holdings、Google credentials 或任何账户
  secrets。它覆盖 Decision/Risk、exact-once、T→T+1 OPEN、terminal semantics、
  fail-closed 与 JSON/CSV reporting，是当前产品/工程 gate。

### scripts/run_setup01_decision_shadow.py

- 这是未来可选的 private operational capability，classification 为
  `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，当前状态为
  `NOT_RUN_USER_PRIVACY`。本轮不调用它、不读取真实 holdings、不向 GitHub
  Actions 输出 holdings-derived data。

### scripts/run_setup01_structural_replay.py

- 只读取已冻结的 `DEVELOPMENT_ONLY` replay input，输出 SETUP_01 lifecycle、
  event、market、current-candidate 与 block-reason artifacts；不重新抓取、
  不写 Sheets/Decision/生产配置，也不读取收益或 Final OOS。

### research/backtest/setup03.py

- `research_trade_outcomes()`：只消费 `SymbolReplayReport.events` 中由 `trading/events.py` 产生的 CONFIRMED event contract；不重建事件、Setup 或 Decision
- T 日按 as-of 数据先生成生产 Decision，只有 `ENTRY_ALLOWED` 才进入 T+1 候选；T+1 Open 再执行 below-breakout / entry-zone / above-zone 三分支，`actual_entry` 从不使用 T 日 close
- `parameter_sensitivity_rows()`：通过 `replay_setup03_history()` 运行固定 54 组研究参数，不排名、不回写 `参数设置`、不修改生产参数；artifact 的 `setup_swing_lookback` 只表示 Setup lookback，Decision lookback 保持生产参数原值
- 一级漏斗直接使用 `ReplayEvent.decision` 与 outcome `execution_status`，显式输出 CONFIRMED → ENTRY_ALLOWED / rejected → T+1 各 skip / EXECUTED，并强制校验计数守恒
- 绩效是 research-only 20D 首障碍诊断：stop/T1 同日保守按 stop；20D 未触发则期末盯市；不足 20D 且未触发的样本标记 censored，不进入 R 聚合统计
- excursion 只完整使用退出 bar 之前的 OHLC；STOP bar 的 MAE 截止 stop、忽略无法确定先后的有利 high，T1 bar 的 MFE 截止 T1、保守保留可能在 T1 前发生且高于 stop 的 low；`observation_days` 是从 T+1 起到首次退出（含退出 bar）的实际观察交易日数，未退出时才等于 available forward bars
- `parameter_sensitivity_artifacts()` 对固定 54 组每格只运行一次 Replay，同时投影 Phase 5B sensitivity 与 Phase 5C gate 明细/汇总；Research 不重算 ATR / Entry Zone / Target / R/R
- gate 汇总覆盖 `ATR_UNAVAILABLE` / `BELOW_STRUCTURAL_INVALIDATION` / `BELOW_BREAKOUT` / `ABOVE_ENTRY_ZONE` / `NO_VALID_TARGET` / `RR_BELOW_MINIMUM` / `FUTURE_OR_INVALID_CONFIRMATION_CONTEXT` / `OTHER_NO_TRADE` / `ENTRY_ALLOWED`，每组强制计数守恒

### research/replay_input.py

- `canonical_bar()`：对真正进入 replay 的完整 `Quote` 字段做 `setup03-replay-input-v1` canonical projection；日期使用 ISO，所有浮点数使用精确 `float.hex()`，拒绝 NaN/Infinity
- `build_input_manifest()`：输入先通过 Trading Core 严格序列校验；逐 symbol 对 canonical bar stream 计算完整 SHA-256，再按 symbol 排序计算 dataset aggregate hash
- manifest 同时记录每个 symbol 的 bar count、起止日期、input hash，以及总 symbol/bar count 与 aggregate hash；JSON 用于机器比较，CSV 用于人工审阅
- `compare_input_manifests()`：稳定区分 `IDENTICAL` / `BAR_COUNT_CHANGED` / `DATE_RANGE_CHANGED` / `CONTENT_CHANGED_WITH_SAME_BAR_COUNT` / `SYMBOL_ADDED` / `SYMBOL_REMOVED`
- `write_frozen_input()` / `read_frozen_input()`：以固定 mtime/filename 的 gzip JSONL 保存 canonical Quote；读取时重算 manifest 并与嵌入值完全比对，内容损坏或漂移立即失败

### research/frozen_validation.py

- Phase 5E 基线固定为 Phase 5D 已验证的 workflow run `32826696259`，dataset aggregate hash 为 `sha256:2b8203468ee22c46bce446ae0aed695fab73c36ae6feab045b19c889f2c54703`；同时锁定该次生产参数版本 `sha256:abe4d3026892`，任一漂移均 fail fast
- 只投影生产参数下的 `SymbolReplayReport` / `ReplayEvent` / `Setup03ResearchReport`，输出 CONFIRMED → ENTRY_ALLOWED → EXECUTED、Decision reason、标的/市场/年份/季度分布与集中度；不运行 Phase 5B 的 54 组敏感性网格
- 信号后路径以 CONFIRMED 日 `signal_close` 为锚，观察后续第 5/10/20 个交易日 close，以及相同期内 high/low 的描述性 MFE/MAE；它不是模拟成交、生产持仓管理或参数优化
- 中文 Markdown/CSV 明确标记“描述性诊断（非参数优化）”；零 CONFIRMED/EXECUTED 时收益、MFE/MAE 与 Edge 均为不可评估，不放宽任何规则

### research/confirmation_diagnostics.py

- 只消费 `ReplayDay.setup_diagnostics`，不重算 Swing、Market Structure、平台边界或突破条件
- 每个 bar 以 production 短路顺序唯一归入 terminal reason，强制 `total bars = 所有 terminal reason 之和`；多条件同时失败只记入不求和的 auxiliary diagnostics
- 输出平台搜索逐 gate 进入/淘汰/通过数、状态转移分布、逐 bar 操作数和 near-miss 分位数；仅描述冻结 Phase 5E 数据集

### research/platform_tolerance_sensitivity.py

- 仅在 Phase 5E frozen dataset 上按固定顺序回放 `0%、0.5%、1%、1.5%、2%、3%、5%、7.5%、10%`；除 `platform_tolerance_pct` 外全部使用同一 production 参数快照
- 每档直接调用 `replay_setup03_history()`，消费同源 Setup/Decision diagnostics、CONFIRMED event 与 T+1 execution contract；research 层不复制 Swing、Structure、Decision、RR、Entry/Stop/Target/Execution 公式
- 输出平台识别、WATCH/ARMED/CONFIRMED/ENTRY_ALLOWED/EXECUTED 完整漏斗、confirmation/decision reason 守恒、标的/市场/年份分布、5/10/20D 描述性 forward return/MFE/MAE 及 high/low span 与集中度稳定性
- 固定原始 tolerance 顺序，不排名、不打分、不计算最佳参数、不写回生产配置；`0` 的精确相等语义只作为配置默认值审计，与策略参数选择明确分离

### research/parameter_freeze.py / setup03_frozen_spec.json

- Phase 5I 的 JSON 规范是冻结 inventory、证据身份、治理边界和 `UNRESOLVED` 缺口的单一事实来源；每项明确分类为既有固定、本轮冻结、保留不冻结、废弃、非 SETUP_03 参数或未解决
- 关键固定值有 canonical SHA-256 完整性合同；同一 freeze version 下修改 dataset、证据序列、固定规则或治理声明会失败，必须显式升级 freeze version 与合同测试
- 只消费已经生成的 Phase 5G／5H artifact contract，不调用 Replay/Trading Core、不读取 live history 或 OOS；验证 Phase 5G／5H 固定序列与 frozen dataset hash 后输出参数清单、机器规范和中文冻结前审计报告
- 当前正式参数冻结结论为 `NOT_READY_FOR_FORMAL_PARAMETER_FREEZE`：证据／治理协议已冻结，既有 production 规则保持固定；`platform_tolerance_pct`、lookback/window/proximity 及 market/regime/波动率 production 定义均保留为 `UNRESOLVED`

### research/structural_validation_protocol.py / setup03_structural_validation_protocol.json

- Phase 5J 只注册未来 SETUP_03 structural validation protocol，最终状态固定为 `VALIDATION_PROTOCOL_REGISTERED_NOT_EXECUTED`；模块只读取 JSON、验证完整性并对现有 `trading/setup.py` / `trading/events.py` 做 AST 静态依赖审计，不调用 Replay、Trading Core、行情源或 Sheets
- Phase 5J-v4 只在 hash-pinned second development holdout 上调用 production SETUP_03 history，逐 bar定位真实 `FIRST_DIVERGENCE_BAR`；research 层只分类 root、propagation、lineage 与 frozen-seam counterfactual，不复制 swing/structure/platform 公式，不访问 outcome 或 Final OOS，不修改 v3 matching/qualification
- protocol 记录父级 Phase 5I 的实际 `research/setup03_frozen_spec.json` identity：`freeze_version=SETUP_03-FREEZE-2026-08-26-v1`、`freeze_decision=NOT_READY_FOR_FORMAL_PARAMETER_FREEZE` 及 `critical_values_sha256=sha256:447b20182f54b8c994042227bbfbaf94c50b2a9b4ade7332058a014915390a15`；canonical SHA-256 先验证 JSON 内容与 stored hash 一致，再由不可变的 `protocol_version -> expected hash` contract 验证唯一版本绑定，因此即使同步重算 hash，同一 version 的内容漂移也会失败；真正修改协议必须显式升级 version 并更新 version/hash contract
- 正式 production tolerance 仅允许 `3.0%、4.0%、5.0%`；`2.5%、5.5%、7.5%、10.0%` 仅为诊断/压力边界，`3.5%、4.5%` 等任何未列入正式集合的值不得成为 production candidate。`setup_swing_lookback=5` 与 `platform_window=40` 保留为 v1 incumbent design constants，不声明最优；market-specific、regime-specific、volatility-normalized production rule 均在 v1 禁用
- 未来 development-validation dataset 预注册 CN/HK/US/JP/SE，每市场至少 8 个标的、合计至少 40 个标的、每市场目标至少约 6000 个有效日 K bars；标的必须在看到 SETUP_03 输出前按非信号元数据确定，symbol manifest 必须在 Phase 5K 获取行情前冻结并哈希，任何依据信号替换/增删标的均禁止，覆盖不足返回 `INSUFFICIENT_COVERAGE`。该集不是最终 OOS
- Phase 5K 结构门槛固定为每市场每候选至少 8 个 CONFIRMED、相邻候选 Jaccard ≥60%、retention ≥80%、匹配日期漂移 median ≤5/P90 ≤15 个交易日、市场事件集中度 ≤35%、标的事件集中度 ≤25%、相邻候选每千 bar CONFIRMED 发生率增幅 ≤50%；其中 market/symbol concentration 对 3%/4%/5% 每个 candidate 独立计算，denominator 分别是该 candidate 在全部五个市场/全部 validation symbols 的 CONFIRMED，绝不合并候选事件；样本不足与门槛失败分别使用预注册状态，不得根据结果调整门槛。Phase 5J-v2 qualification 的 drift 仅使用同一市场 `sorted(union(all valid local trading dates))` 的 ordinal distance，calendar-day drift 只保留为 descriptive field
- 正式选择规则为 lexicographic conservative，并使用预注册 qualification matrix：3% 必须通过自身 candidate-level thresholds 加 3%→4% 全部 adjacent-pair thresholds；4% 必须通过自身 candidate-level thresholds 加 3%→4% 与 4%→5% 两侧 thresholds；5% 必须通过自身 candidate-level thresholds 加 4%→5% thresholds。按 3%→4%→5% 顺序选择首个 qualified candidate；全部不满足为 `VALIDATION_FAIL_NOT_READY_FOR_FORMAL_FREEZE`，主要因样本不足为 `INSUFFICIENT_VALIDATION_EVIDENCE`。禁止使用 forward return、MFE、MAE、win rate、P&L 或任何收益指标，不生成 market/regime-specific production 参数
- `arm_proximity_pct=0` 只做静态代码依赖审计：它影响 WATCH/ARMED proximity 状态转移、ARMED/WATCH diagnostics 及参数传递，但严格 `close_t > breakout_price`、`close_t < structural_invalidation` 和 `trading.events` 的 CONFIRMED terminal event predicate 不依赖它；因此 v1 保持关闭，不改变正式 terminal semantics

### research/structural_validation_protocol_v2.py / setup03_structural_validation_protocol_v2.json

- Phase 5J-v2 是独立的 scope revision，保留 v1 文件和 v1 hash 不变；它只注册 CN/US validation scope，不执行 validation、Replay、SETUP_03、OOS 或正式参数选择
- CN 只启用 SSE Main Board / SZSE Main Board common A shares；`CN_STAR_REGISTERED_INACTIVE` 与 `CN_CHINEXT_REGISTERED_INACTIVE` 保留为注册入口但禁止进入 Phase 5K、OHLCV 和 qualification，激活必须升级 protocol version
- CN 使用 CSI300/500/1000（primary quota 12/14/14），US 使用 S&P500/Nasdaq-100/SOX/IGV（primary quota 12/10/8/10）；两市场各为 40 primary / 20 reserve，跨 universe/cohort 重复按预注册 canonical identity 规则只计一次，选择不能依赖 SETUP_03 输出或收益指标
- QQQ、SOX index、IGV ETF 仅为 aggregate diagnostics，不计入 equity sample minimum、不参与 qualification、不决定 tolerance；5J-v2 移除五市场 market concentration gate，并要求 CN 与 US 各自独立满足全部剩余结构门槛，禁止市场间补偿
- 3%/4%/5%、lookback=5、window=40、arm proximity=0、Jaccard/retention/drift/rate、symbol concentration、qualification matrix 与收益指标禁用规则保持锁定；不重新搜索 thresholds 或 tolerance

### research/phase5k_b0_dataset_contract.py / phase5k_b0_dataset_acquisition_contract_v2.json

- Phase 5K-B0 active contract v2 只冻结未来 development-validation 日 K 数据集的 acquisition contract，状态为 `DATASET_ACQUISITION_CONTRACT_FROZEN_NOT_ACQUIRED`；v1 文件保留为 historical audit evidence，active loader 绑定 v2 canonical SHA-256 `sha256:0fdfef827d48ef6deec8e58c1de1e0e470d3adb6567a1e74d25c44d8a3137588`，并校验 Phase 5J-v2 protocol `sha256:d7b216…451aa0` 与 A1 v2 manifest `sha256:ded740…68433`，不调用行情源或 SETUP_03
- 日期窗口固定为 security-local trading date `2017-01-01` 至 `2026-08-26`（inclusive）。CN `/api/a-share/prices/historical` 的 exact wire query 固定为 `thscode=<canonical symbol>`、`interval=1d`、`start=1483200000000`、`end=1787759999999`、`adjust=forward`；边界由 `Asia/Shanghai` local wall-clock 转 integer Unix ms，返回后仍严格按 security-local date inclusive filter
- US IBKR Contract wire fields 固定为 resolved/frozen `conId`、`secType=STK`、`exchange=SMART`、resolved/frozen `primaryExchange` 与 `currency`；`reqHistoricalData` 固定 `barSizeSetting=1 day`、`whatToShow=ADJUSTED_LAST`、`useRTH=1`、`formatDate=1`、`keepUpToDate=false`、`chartOptions=[]`，每个预注册 calendar-year chunk 固定 `endDateTime=<chunk end> 23:59:59 US/Eastern` 与 `durationStr=1 Y`，随后严格 local-date filter；overlap 仅允许 exact deterministic dedupe，冲突 fail closed。API/TWS version fields、identity source 与 timezone semantics 必须在 B1 首次历史请求前冻结
- CN/US 均禁止 provider fallback 或混用 adjusted/unadjusted semantics；canonical schema 固定为 `market/canonical_symbol/date/open/high/low/close/volume/source_provider/adjustment_mode`；raw response 与 request/provenance metadata 分开保存。OHLC、日期、volume、重复值及 `DATA_CONFLICT_FAIL_CLOSED` 均由纯校验函数 fail closed，绝不 forward-fill、interpolate、补 synthetic bar 或跨市场补行
- reserve 只能在 SETUP_03 evaluation 前因机器可读客观 provider/QC/warmup failure 激活，并严格遵循 A1 `manifest_rank`；reserve 也必须通过同一 validation，final roster 只包含 `VALID_ACCEPTED` symbols。`final_roster_count == valid_symbols` 是 fail-closed invariant；CN/US 各自目标为 40 valid accepted symbols，未达到时为 `TARGET_ROSTER_SHORTFALL_REQUIRES_REVIEW`
- Phase 5J-v2 的 8 symbols/market、40 symbols total、6000 bars/market hard minimum 与 40-valid-symbol-per-market dataset-readiness target 分开计算；hard minimum 通过不得覆盖 readiness gate。B1 manifest schema 预注册 per-symbol raw/normalized hash、QC、bar count/date range、replacement audit、market totals 与 aggregate hash，并必须绑定 active B0 v2；B1 成功状态为 `DEVELOPMENT_VALIDATION_DATASET_FROZEN_NOT_EVALUATED`，B0 不生成该状态

### research/development_dataset.py / scripts/run_development_strategy_stability.py

- PR #29 的 development-only dataset v2 使用固定 CN/US development universe；CN 统一走 `BAOSTOCK_DEVELOPMENT_QFQ`（`query_history_k_data_plus`、`frequency=d`、`adjustflag=2`），US 走 `YFINANCE_DEVELOPMENT_HISTORICAL`（`auto_adjust=True`、`repair=False`），两者均固定 local-date window `2017-01-01` 至 `2026-08-26` inclusive；该 provider split 不改变 production provider fallback chain，也不进入 formal Phase 5K-B1
- immutable v1 OHLC failure audit 只读 v1 adjusted artifact，并以同日 yfinance `auto_adjust=False/actions=True/repair=False` raw bar 做对照；所有 violation 保存 machine-readable JSON/CSV。`OHLC_ORDERING_NUMERICAL_COMPARISON-IEEE754-ULP-2026-08-28-v1` 只作为 QC comparison（最大 8 ULP），不 clip/round/fill/mutate source prices；material violation 仍 fail closed
- v2 manifest 固定 raw request/provenance、normalized/raw hash、QC、缺失日期不推断、无 provider fallback/history splice/synthetic bar。BaoStock 已存在且 OHLC 有效、四价相等、activity fields 全空的 suspension row 只规范 `volume=0`，不创建 row/date
- `run_development_strategy_stability.py` 先完成 v1 diagnostic，再生成 v2 dataset、结构 evidence 与 `precompute_swings=False/True` 全量 parity；parity 覆盖 40 symbols × 7 tolerances、每根 bar 的 Setup/diagnostics/event/Decision，任何 mismatch 必须保持 baseline semantics

### research/market_sessions.py / research/development_decision_capsule.py

- `build_market_session_dates()` 从冻结 v2 replay input 的全部有效 local `Quote.trade_date` 按市场取 union 并排序；`trading_day_distance()` 要求 matched old/new event date 都在对应 market session set 中，再返回 ordinal index absolute difference，不读取 live calendar/provider，也不使用单一 symbol bar count
- Development T+1 identity 正式登记为 `DEVELOPMENT_SESSION_IDENTITY = FROZEN_DATASET_MARKET_SESSION_SET`；它防止 symbol-level missing bar fall-forward 到 T+2，但不能证明整个 frozen market universe 缺失时仍识别出真实 session。生产 execution 前必须完成 `PRODUCTION_EXCHANGE_CALENDAR_INTEGRATION_REQUIRED_BEFORE_PRODUCTION_EXECUTION`；本轮不接第三方 calendar、不改变 development funnel。
- v3 decision capsule 保留 v2 capsule identity，输出完整 candidate × market × frozen-threshold matrix、`qualified_candidates`、唯一 frozen lexicographic result、failure breakdown、trading-day drift buckets 与 extreme Top 20；3%/4%/5% qualification 仍独立要求 CN 与 US 均通过，执行结果不写入 production config

### scripts/hithink_cn_capability_smoke_test.py / docs/HITHINK_CN_API_CAPABILITY_SMOKE_TEST.md

- 仅对 HiThink Financial API 做 bounded GET capability/provenance smoke test；API Key 只从 `HITHINK_FINANCE_API_KEY` 环境变量读取，不写日志/代码/报告
- market-dump 只探测签名端点，不跟随下载 URL；不会生成 Phase 5K manifest、validation OHLCV、SETUP_03 output 或 OOS
- 保存 exact raw response 并计算 SHA-256；成功能力必须同时满足 HTTP 200 与 response `code=0`，`code=2003` 只能记录为未授权/无权限，不能当作数据能力已证明

### scripts/run_setup03_replay.py

- 由 `.github/workflows/setup03-replay.yml` 手动触发
- 复用 `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` secrets 读取 `自选清单` 与 `参数设置`
- 使用生产参数原值和 `自选清单.历史数据源` 抓取最近 3 年前复权历史，并保留数据源原始顺序供质量门控检查
- 输出 summary / skipped / replay events / trade outcomes / parameter sensitivity，并新增 `setup03_decision_gate_diagnostics.csv` 与 `setup03_decision_gate_summary.csv` 两类只读 artifact；事件明细与研究结果含生产参数哈希版本，零事件运行仍可复现；不写任何生产 Sheet
- Phase 5D 额外输出 JSON/CSV input manifest、deterministic `setup03_replay_input.jsonl.gz` 与 manifest comparison CSV；`--frozen-input` 跳过 live history fetch，精确还原 Quote 后复用同一 Replay/Decision/Research 链
- `research/phase5k_a1_universe.py` 只读取已 pin 的 Phase 5J-v2 与 A1 selection spec，保存 CN/US 当前 universe 原始快照并生成 `MANIFEST_FROZEN_NOT_FETCHED`；不导入行情、Replay、Trading Core、Decision、SETUP_03 或 Sheets
- `research/snapshots/phase5k_a1_cn_us_2026-08-27-v1/` 与 `research/phase5k_a1_universe_manifest.json` 保持不可变历史审计证据；active v2 使用 `research/snapshots/phase5k_a1_cn_us_2026-08-27-v2/` 与 `research/phase5k_a1_universe_manifest_v2.json`。S&P500 优先尝试 S&P DJI 完整机器可读表，无法满足完整性合同则使用明确标记的 `S&P500_UNIVERSE_PROXY_IVV_OFFICIAL_HOLDINGS`；IVV 是 official ETF issuer holdings proxy，不得称为 official S&P500 constituents，并必须记录 raw hash/count/as-of/retrieval/limitation。两版均只包含 40 CN PRIMARY + 20 CN RESERVE、40 US PRIMARY + 20 US RESERVE；QQQ、SOX index、IGV ETF 仅记录为 aggregate diagnostics
- `--phase5e` 必须与 `--frozen-input` 同时使用，并且只接受上述固定 dataset/参数版本；使用 frozen manifest 自带的完整 symbol universe，不读取 live historical data，也不运行参数网格
- `--phase5f` 必须同时启用 `--phase5e`，输出逐 bar terminal reason、完整确认前漏斗、辅助多重失败、near-miss 分布与中文报告
- `--phase5i` 必须同时启用 frozen input、Phase 5E、Phase 5G 与 Phase 5H；它只审计已有 artifact 并输出 frozen specification，不新增 replay 网格、指标、市场/regime 分层或 stress test
- Phase 5J 不新增 workflow flag，也不接入 `scripts/run_setup03_replay.py`；其 protocol loader/static audit 不执行 validation，不抓取 live/new historical data，不访问最终 OOS，不修改 production SETUP_03、Trading Core、Decision、execution 或 Google Sheets
- 输出 calculable/enabled 覆盖率；enabled=0 或 calculable=0 时先落诊断 artifact 再令 workflow 失败

## Google Sheets 各表（真实存在）

| Sheet | 用途 | 读取/写入 |
|---|---|---|
| `自选清单` | 标的代码与数据源映射 | 读（启用、市场、主/校验数据源、时区、收盘时间、代码字段） |
| `最新行情` | 每标的最近一条未复权日线 | 写（upsert，键=统一代码） |
| `历史行情_未复权` | 最新价格、成交量、缺口分析 | 写（upsert，键=市场+统一代码+交易日期） |
| `历史行情_前复权` | 均线、波浪、斐波那契分析 | 写（upsert，键=市场+统一代码+交易日期） |
| `交易决策` | SETUP_03 CONFIRMED Decision 事件流水 | 写（仅新 CONFIRMED 事件；upsert 键=统一代码+交易日期+Setup类型） |
| `校验记录` | 两源逐次比对结果 | 追加 |
| `运行日志` | 任务时间、状态、错误 | 追加 |
| `参数设置` | 容差、历史长度、Setup/Decision 显式参数 | 读 |

`latest` 模式只写 `最新行情`、`校验记录`、`运行日志`；`历史行情_*` 与 `交易决策` 只属于 `full` 模式。运行 stdout 和 GitHub Step Summary 输出 `symbols_requested`、freshness/validation 分布、拒绝的 stale/future sources、失败标的及 `history_rows_written`；数据不完整时为 `PARTIAL_DATA_QUALITY`。

持仓生命周期路径沿用 `自选清单.启用` 的现有语义，并可按单标的写入 `历史行情_未复权`、`历史行情_前复权` 与既有 `运行日志`。它不会新增 Sheet 列、registry 或第二套身份事实源；CLOSE 只停用当前持仓视图，不物理删除历史数据。

`参数设置` 必须显式提供以下 Trading Core 参数；值保持当前规则基线，不在 Phase 4 调参：

`setup_swing_lookback=5`、`setup_platform_window=40`、`setup_platform_tolerance_pct=0`、`setup_arm_proximity_pct=0`、`decision_swing_lookback=5`、`decision_atr_period=14`、`decision_atr_buffer=0.5`、`decision_max_chase_atr=0.5`、`decision_risk_capital=<显式风险资本>`。

### 自选清单 现有列映射（Known Issue）

`自选清单` 实际范围为 `A:O`（15 列），当前代码**只消费以下 12 列**；未消费列含义未核实，**禁止猜测**：

| 列（表头） | 消费位置 |
|---|---|
| 启用 | main.py `as_bool(watch.get("启用"))` |
| 市场 | main.py `watch.get("市场")` |
| 主数据源 | main.py / providers.py |
| 校验数据源 | main.py / providers.py |
| 历史数据源 | main.py qfq 历史与 Decision；仅允许 yfinance / BaoStock |
| 时区 | main.py `watch["时区"]` |
| 收盘时间 | main.py `watch["收盘时间"]` |
| 统一代码 | providers.py 符号转换基准 |
| 名称 | providers.py `Quote.name` |
| 币种 | providers.py `Quote.currency` |
| BaoStock代码 | providers.py `fetch_baostock` |
| yfinance代码 | providers.py `fetch_yfinance` |
| AKShare代码 | providers.py（仅遗留符号回退，不触发网络请求） |

> `历史数据源` 是新增的显式列，不得复用或猜测 A:O 中未核实列的含义。`交易决策` worksheet 与固定表头需在生产启用前预先创建。代码中仍无 `总览` 表读写逻辑。

## GitHub Actions

- `asia-close.yml`：`cron "30 10 * * 1-5"`（UTC）= 北京 18:30；schedule 强制运行 `python main.py --group asia --mode latest`，workflow_dispatch 可选 full
- `us-close.yml`：`cron "30 22 * * 1-5"`（UTC）；schedule 强制运行 `python main.py --group us --mode latest`，workflow_dispatch 可选 full
- `setup03-replay.yml`：仅 `workflow_dispatch`；默认抓取 live qfq 后输出 Phase 5A~5D 只读 artifact；可传 `frozen_input_run_id` 下载此前同名 artifact，使用其 canonical frozen input 重放并自动输出 manifest comparison；固定 run `32826696259` 额外启用 Phase 5E 生产参数描述性报告，绝不抓取 live history；失败时仍上传诊断文件
- `wave-shadow.yml`：已移除；不通过 GitHub Actions 读取或输出真实持仓派生信息。`scripts/run_wave_shadow.py` 仅保留 private/local capability，本轮不调用
- `setup01-generic-operational-shadow.yml`：PR/手动运行 synthetic-only generic operational shadow，不需要 Secrets，不读取账户 holdings
- 固定 run `32826696259` 还启用 Phase 5F~5I 只读诊断；Phase 5H 仅以 production Replay/Setup diagnostics 聚合市场分层、相邻 tolerance 稳定性及严格 as-of ATR/20 日实现波动率标准化；Phase 5I 只消费 Phase 5G／5H 现有 artifact 合同并冻结证据边界，不读取 OOS、不新增搜索，也不选择 production 参数。
- `ci.yml`：PR / main push / 手动触发跑 unittest
- 环境：ubuntu-latest，Python 3.11
- Secrets：`GOOGLE_SHEET_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON`
- 当前 CI 安装依赖后运行 `python -m unittest discover -s tests -v`

## 配置文件

- `requirements.txt`：baostock、gspread、google-auth、pandas、yfinance（+ tzdata 供 Windows 本地开发）
- `.gitignore`：`__pycache__/`、`.pytest_cache/`、`.venv/`、`.env`、`service-account*.json`、`artifacts/`
- 无 pyproject.toml / setup.py

## 数据源

| 市场 | 主源 | 校验源 | 快照回退 |
|---|---|---|---|
| A股 (CN) | yfinance | Tencent | Tencent / Sina |
| 港股 (HK) | yfinance | Tencent / Sina | Tencent / Sina |
| 美股 (US) | yfinance | Tencent / Sina | Tencent / Sina |
| 日股 (JP) | yfinance | 无 | 无 |
| 瑞典股 (SE) | yfinance | 无 | 无 |

## 模块依赖

```text
main.py ──→ core.py
main.py ──→ providers.py   (惰性)
main.py ──→ sheets_client.py (惰性)
providers.py ──→ core.py
tests/test_validation.py ──→ core / main / providers / sheets_client
```

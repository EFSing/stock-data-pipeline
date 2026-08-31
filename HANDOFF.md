# CURRENT OPERATIONAL HANDOFF SNAPSHOT

> 本文件是下一台设备 / 下一次开发会话的可执行交接快照，不是完整历史流水账。新会话第一步读取本文件，然后读取 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`，再核对真实 Git / PR / CI / artifact 状态。

## PROJECT STRATEGY IDENTITY

- 本项目不是单一 Platform Breakout 系统；长期总体策略的唯一正式事实源是 `docs/TRADING_SYSTEM_SPEC.md`。
- 总体主线：`Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。
- 第一版四类 Setup：`SETUP_01`（Wave 2 → Wave 3）、`SETUP_02`（Wave 3 Continuation）、`SETUP_03`（Platform Breakout）、`SETUP_04`（Extreme Fear Reversal）。
- `SETUP_03` 当前只是正在研究的一个子策略；当前开发深度、commit 数量或 Phase 数量不改变总体策略或优先级。Wave Scenario Engine、`SETUP_01`、`SETUP_02` 仍是总体核心路线。
- 任何总体路线变化都必须先取得用户明确批准，并记录在 `docs/DECISION_LOG.md`；本快照不复制完整策略规范，避免双事实源。

## 1. Current Objective

- **当前 Phase / task:** `HOLDINGS_DATA_MANAGER_SKILL`。
- **具体目标:** 为上层 ChatGPT/Codex 提供 repository-local `holdings-data-manager` Skill；将自然语言稳定映射为 `ADD`、`REENTER`、`CLOSE`、`SYNC`，只管理持仓数据生命周期，不进入交易策略或账户动作。
- **当前实现:** Skill contract 在 `skills/holdings-data-manager/SKILL.md`，业务实现为 `holdings_data_manager.py`；source/tests substantive commit 为 `2dd1ed0`，基于真实最新 `main@3a6d417ede3594c05003ea18ce65bd4562eff294`。
- **操作边界:** 新身份完成 symbol/market/provider normalization，raw/qfq 均覆盖最近已完成市场交易日前一个自然年后才启用；REENTER 只补缺口；CLOSE 只停用 `自选清单.启用`，永久保留历史、校验、映射和身份；重复操作幂等。
- **明确禁止事项:** 不新增第二套 registry/Sheet 事实源，不猜 ticker/market/provider，不伪造或插值行情，不把完整 `full` pipeline 作为单标的入口；不读取账户数量、成本、NAV、盈亏，不访问券商，不修改 SETUP_01/02/03/04、Wave、Fibonacci、Decision/Risk、Position Management、Exit 或研究协议。
- **停止条件:** push 独立 PR，完成 full unittest、focused tests、compileall、`git diff --check` 和新 PR exact-head CI；治理同步并确认 `HANDOFF_CURRENT_AND_CONSISTENT` 后停在 `HOLDINGS_DATA_MANAGER_SKILL_READY_FOR_SOL_REVIEW`，不自动 merge。

## 2. Current Repository State

- **repository:** `EFSing/stock-data-pipeline`
- **default/main branch:** `main`
- **main/base SHA:** GitHub remote `main@3a6d417ede3594c05003ea18ce65bd4562eff294`；main push CI `33316793033` success，Asia/US latest runs `33320878809` / `33320860435` success。
- **working branch:** `codex/holdings-data-manager`，基于上述真实最新 main。
- **implementation source head:** `2dd1ed0` (`feat: add holdings data manager skill`)；新 PR tip、exact-head CI 和 mergeability 待 push 后实时核验。
- **PR:** #38 `OPEN`，当前治理同步前 live tip 为 `8f48921a15cfbd0b45c11d28c705a865c5db9d92`；此前 #35/#36 仅为历史策略上下文，本任务不修改其内容。
- **latest exact-head checks:** PR #38 tip `8f48921…` 的 CI `33354460712` success、mergeable=true；本次 docs-only 对账 push 后必须核对新 exact SHA/CI。
- **working tree expected state:** 治理文档同步后工作区保持 clean；ignored `artifacts/` 保持 ignored；development replay 与 shadow artifact 仅作审计核验，不进入生产 Sheet。
- **current project/phase status:** `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` 保持不变；持仓数据管理当前状态为 `HOLDINGS_DATA_MANAGER_LOCAL_VALIDATION_PENDING_PR`。SETUP_02、Final OOS、Phase 5K-B1、IBKR 与任何 outcome 研究仍未执行。

## 3. Completed Work

- Holdings manager implementation: deterministic symbol/market/source normalization; natural-language parsing for single-symbol `ADD`/`REENTER`/`CLOSE`/`SYNC`; raw/qfq latest-completed-session one-year initialization and gap-only sync; fail-closed provider/QC/duplicate-date gates; idempotent `自选清单` update; CLOSE history preservation; Beijing-time append-only audit.
- Repository-local Skill specification and capability documentation are tracked. `SheetsClient.upsert_watchlist()` updates only known headers and preserves unverified `自选清单` columns; no schema/registry change.
- Holdings regression suite covers first ADD, repeated ADD, CLOSE/repeated CLOSE, REENTER gap/full coverage, SYNC state preservation, ambiguity, provider/qfq failure, duplicate dates, natural-language examples, and unknown Sheet columns. Existing scheduled latest tests remain green.

- PR #35 已从最新 main squash merge 为 `2d48d90bdc3a48ef96b2a802d5c8c448de5ba6b6`，main CI `33298510168` success；PR #31 已关闭并记录 `superseded by #34`。
- Wave Scenario Engine v1 已实现：严格 `data <= as_of_date`、完整周边界、weekly parent → daily context、confirmed Swing、现有 Fibonacci regions、primary/alternate、证据/反证/规则计分、结构失效、context eligibility 与 fail-closed UNKNOWN/NO_VALID families。
- Wave Engine v1 测试覆盖 canonical/synthetic 场景、future append invariance、不完整当前周、weekly/daily state、confirmed/provisional、Fib region、primary/alternate coexistence 与 read-only shadow；focused `tests.test_wave` 为 `12/12` 通过。
- PR #36 previous review head `ca9ec6e93518e7e47c13f8f41a7f5751c9fd24d0` 的 exact-head CI `33300273163` 与只读 shadow `33300273180` success；当前 substantive head 为 `eed768bec92365615b05b0a8314cf555e44b22ac`，必须重新完成相同检查。previous shadow 对真实 10 个启用持仓生成 JSON/CSV artifact，未写 Sheets、历史、Decision 或交易字段。
- Final shadow summary：`symbols_requested=10`、`evaluated=9`、`errors=1`、`unknown_primary=5`、`unknown_primary_ratio=0.5`；primary counts 为 `DOWNTREND_OR_INVALID_FOR_LONG=3`、`WAVE_2_TO_3_CANDIDATE=1`、`UPTREND_UNKNOWN_WAVE=4`、`ABC_CORRECTION_CANDIDATE=1`、`NO_VALID_SCENARIO=1`；状态 `PARTIAL_DATA_QUALITY`。MU 的 `历史数据源` 为空，按 fail-closed 记录错误。
- SETUP_01 v1 已完成：独立 immutable model/evaluator、固定 `NONE/WATCH/ARMED/CONFIRMED/FAILED` lifecycle、primary-only Wave Engine context、ABC/downtrend counter-scenario blocks、两类独立 invalidation、canonical Fib diagnostics、strict prefix replay 与 deterministic CONFIRMED/FAILED event identity。Wave 2 low 额外要求低于 Wave 1 peak，避免非 retracement 误判。
- Development structural replay 已完成：40/40 symbols、86,305 days、0 errors、1,404 events（745 CONFIRMED / 659 FAILED）；CN event distribution 299/313，US 446/346；唯一未终结 development candidate 为 STX/US ARMED。
- Real holdings shadow 已完成：10 requested / 8 evaluated / 2 errors；SETUP_01 states FAILED=5、WATCH=1、CONFIRMED=2；000725.SZ/CN 为当前 WATCH candidate；SIVE.SE freshness stale、MU empty historical source 均 fail-closed。
- Correctness closeout shadow summary：`symbols_requested=10`、`evaluated=8`、`errors=2`；8 个成功行的 qfq `history_last_date` 均与 `latest_completed_session` 对齐，5 个 US 标的均到 `2026-08-28`；SIVE.SE 因 `2026-08-27 < 2026-08-28` 为 `DATA_STALE`，MU 因空 `历史数据源` fail-closed；`returns_accessed=false`、`oos_accessed=false`、`sheets_written=false`。
- Phase 5J-v3 protocol、independent universe、holdout dataset、structure-only replay/parity 与 qualification 已完成并由 PR #30 合并；exact identities 见第 7 节和 `docs/CURRENT_STATUS.md`。
- loader 已修复 dataset → replay wrapper 的 provisional-hash cross-binding 顺序问题；现有 frozen identities 与研究结果不变，tracked wrapper integrity 为 `sha256:6746fa0914ef20916ec9006492f2043ed9d35fc65b74995e1cab903837890148`。
- 本地 recovery bundle 已生成：`artifacts/frozen_backups/SETUP_03_DEVELOPMENT_HOLDOUT_2026-08-29_v1_FROZEN_BACKUP.zip`，3,086,881 bytes，ZIP SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；bundle 含 5 个文件，成员 hash 见 registry/recovery manifest。
- 外部 ChatGPT 审计已将 exact ZIP bytes 上传 Google Drive `交易系统/Frozen Artifacts/stock-data-pipeline/2026-08-29-v1/`，file ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS`；独立重新读取后的 recovered ZIP SHA-256 与上传前完全一致。该 session 不重复访问 Google Drive。
- 本次治理初始化与本轮 cloud recovery correction：新增/更新治理文件与 governance test；不改变业务逻辑和 frozen artifact bytes。治理修正 commit 的 SHA 以 Git/PR 最终核对为准。
- Phase 5J-v4 exact Sol specification 已落为 machine-readable protocol、中文说明、hash-pinned loader 与 protocol regression tests；canonical protocol SHA-256 为 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`。本独立 freeze task 未运行真实 holdout attribution。
- Phase 5J-v4 在 40 symbols / 86,305 bars 上生成 258,915 trace rows、1,031 lifecycles、177 real first-divergence episodes；对 `origin/main@142b7345…` 完成 120 cells / 258,915 Setup bar comparisons / 1,028 terminal-event comparisons，Setup/event mismatches 均为 0。capsule file SHA-256 `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`，deterministic trace SHA-256 `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`；tracked provenance hashes 使用 Git-normalized LF bytes，跨 Windows/Linux 稳定。
- v5 clean holdout acquisition：冻结 universe 的 40/40 symbols 均 `VALID_ACCEPTED`，CN 42,355 + US 45,720 = 88,075 bars；dataset manifest `sha256:9940f0e496e3c5ead4216d33d28bd23b023801007bf46d63051237bd7b8a1b29`，normalized aggregate `sha256:a98cbbb0065b29f77d237dd43365746a41d08462f1ec2bbc112030e0231ce038`，replay aggregate `sha256:37c269ca1044fcb611650a83e670b12b41353ddcf9b912514222c9218ca70a76`；provider/QC exceptions=0，未使用 formal B1/IBKR。
- v5 ATR structure-only qualification：4 candidates 的 124-row matrix 中 candidate-level gates 全部通过，但 adjacent/lifecycle gates 使 `qualified_candidates=[]`、`selected_candidate_atr=null`；parity 为 280 cells / 616,525 bars / 3,253 terminal-event comparisons / 0 mismatches，deterministic repeat `PASS`。capsule canonical payload `sha256:5c799f5f9b2d2655c0dd1ff4fd773af32e3e05d805175d696791c80fe767a42b`，最终状态 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`。
- `trading/setup.py` 的 `ATR_NORMALIZED_BOUNDARY_MODE` 保留用于研究复现，并明确标记为 `RESEARCH_ONLY` / `NOT_PRODUCTION_AUTHORIZED` / `FAILED_STRUCTURAL_CANDIDATE_FAMILY`；`main.py`、Sheets 参数解析、workflow 与 Decision 入口均不选择该 mode，percentage production default 与既有交易行为不变。
- PR #33 已完成远端 squash merge，merge commit 为 `b27f6c9052fe44bcec3d7ea4c3a05ac2efcb6d11`，main exact-head CI `33264260330` success；未启动 Wave Engine。
- PR #31 全部 diff 已审计：旧治理文件基于 `main@142b7345a5640b1e87932e41f3dc9311172bf54c`，不直接移植；本分支只重新实现 latest/full 隔离、source-date freshness、ordinary-calendar guard、future-date rejection 和时区归一化。
- 已完成生产根因链审计：`main.run()` 构造 latest row 时的 `交易日期` 只允许来自 `chosen.trade_date`，`抓取时间` 只来自北京时间 `fetched_at`；真实 Sheet 元数据与 `自选清单`/`最新行情` 已只读核对，目标表为「持仓股股票行情数据中台」。
- 已完成最终验证：全量 unittest `343/343`、focused validation/latest `64/64`、compile、`git diff --check` 与 PR #34 exact-head CI `33265845873` 均成功；实现 head 为 `a9a7a06d546412d4de390029baaa5ff4d44ee263`。
- 最终 production smoke：Asia `33265877563` 与 US `33265875055` 均为 workflow_dispatch/latest、成功，summary 分别为 `3/3 verified` 与 `6 verified + 1 single-source current/pending`，两者 `history_rows_written=0`、`decision_rows_written=0`。真实 Sheet 中 10/10 启用持仓交易日期均为 `2026-08-28`，SIVE 的 Friday 行来自 bounded Yahoo Chart；日期列为 DATE、运行时间列为北京时间 DATE_TIME。
- 最终状态：`PRODUCTION_HOLDINGS_DATE_BUG_FIXED_AND_LIVE_VERIFIED`；SIVE 保留单源待复核，未伪造双源验证。`HANDOFF_CURRENT_AND_CONSISTENT`。

## 4. Pending Work

### Required Next

1. [x] 从真实最新 `main@3a6d417ede3594c05003ea18ce65bd4562eff294` 建立 `codex/holdings-data-manager`。
2. [x] 完成 `holdings_data_manager.py`、repository-local Skill specification、Sheet watchlist upsert、focused regression tests 及架构/README 说明。
3. [x] 固化 substantive source commit `2dd1ed0`；`ADD`/`REENTER`/`CLOSE`/`SYNC`、raw/qfq 缺口、幂等与 fail-closed contract 已实现。
4. [x] 完成治理同步草稿：CURRENT_STATUS、DECISION_LOG 和本 HANDOFF 指向当前 holdings task；此前 Wave/SETUP01 状态保留为不变历史上下文。
5. [ ] 跑最终 full unittest、focused tests、compileall、`git diff --check`，并验证 Skill validator；官方 validator 当前受 bundled Python 缺少 `yaml` 模块影响。
6. [ ] push 分支、创建独立 PR，实时核对 base/tip、PR state/mergeability 和 exact-head CI；不自动 merge。
7. [ ] exact-head CI 成功且治理快照再次对账后，将状态置为 `HOLDINGS_DATA_MANAGER_SKILL_READY_FOR_SOL_REVIEW`。

### Deferred

- SETUP_01 Decision/Risk/production integration 与独立 SETUP_02 实现，须先经 Sol review 确认 v1 结构语义与实际 shadow 数据质量。
- 如需继续 SETUP_03，等待新的明确研究决策并注册新 protocol/version；当前结果不授权任何 threshold 或 production 选择。
- Final OOS、formal Phase 5K-B1、IBKR readiness 和任何 production parameter/strategy change。

### Prohibited For Now

- 自动 merge 本任务 PR；此前 Wave/SETUP01 shadow 不得被当作本任务的交易动作或授权。
- 直接 merge/rebase 旧 PR，或重新打开 SETUP_03 structural development。
- 读取账户数量、成本、NAV、盈亏或访问真实券商账户；不进入任何 outcome/OOS/策略研究路径。
- 修改 SETUP_01/02/03/04、Wave、Fibonacci、Decision/Risk、Position Management、Exit、Trading Core 既有交易行为或 Google Sheets schema。
- `CLOSE` 物理删除历史行情、校验记录、数据源映射或证券身份；任何 provider/history/QC 失败时错误启用标的。

## 5. Key Decisions And Rationale

### Decision

- 以 `HANDOFF.md` 管当前快照、`CURRENT_STATUS.md` 管正式状态、`DECISION_LOG.md` 管长期理由；artifact 的可恢复性单独由 policy + registry 管理。
- 重要 bytes 未进 Git 时，只有 `LOCAL_PRESENT`、`HASH_VERIFIED`、`PERSISTENT_BACKUP_PRESENT`、`RECOVERY_VERIFIED` 全部满足，才允许 `FULLY_RECOVERABLE`。
- Phase 5J-v3 当前结果保持 development-only / structure-only；没有新的授权前，不将其解释为生产参数决定。
- 持仓数据管理采用薄 Skill + 可测试 Python 编排；沿用 `自选清单.启用` 和现有历史/provider/QC/schema，不新增 registry；CLOSE 永久禁止删除历史，失败时 fail closed。

### Why

这样能把“下一步怎么接手”“正式状态是什么”“为什么这么决定”和“frozen bytes 怎么恢复”分开；旧聊天、本地目录或临时 CI artifact 都不能单独承担 correctness-critical provenance。

### Rejected Alternatives

- 仅复制完整 Git history 或继续依赖聊天记录：不能提供当前 exact PR/CI/artifact 对账。
- 把 ignored 大文件重新生成一份“相同逻辑”的文件：不能证明 exact bytes，违反 frozen identity。
- 仅记录 local ZIP：不能证明跨设备持久化和独立恢复。

### Revisit Condition

只有出现客观的新 Git/PR/CI/artifact evidence、approved storage policy 变化或明确授权扩大 research/production scope，才允许重审；identity 变化必须新建版本并保留旧版本。

## 6. Important Files Changed

| path | purpose | semantic impact / nature |
|---|---|---|
| `HANDOFF.md` | 当前操作交接快照 | governance；下一次会话的第一入口 |
| `AGENTS.md` | 新会话启动、冲突和更新 gate | governance；不改变交易规则 |
| `README.md` | 公开发现入口，链接治理文件 | documentation / governance |
| `holdings_data_manager.py` | 单标的身份规范化、ADD/REENTER/CLOSE/SYNC、历史缺口与审计编排 | 新持仓数据能力；不进入策略/账户路径 |
| `skills/holdings-data-manager/SKILL.md` | 上层自然语言 Skill specification、contract、示例与禁止动作 | 薄编排入口；不承载业务实现 |
| `docs/HOLDINGS_DATA_MANAGER.md` | 持仓生命周期、历史分离、schema 与 fail-closed 说明 | capability documentation |
| `tests/test_holdings_data_manager.py` | 持仓生命周期、自然语言、provider/QC、日期幂等和 unknown column regression | 新能力回归 |
| `sheets_client.py` | 增加保留未知列的单行 `自选清单` upsert | additive Sheet adapter；无 schema 变化 |
| `docs/CURRENT_STATUS.md` | 正式状态、PR/CI 对账和下一步 | governance/status；修正已核实的 stale PR labels |
| `docs/DECISION_LOG.md` | 记录本次治理设计的长期理由 | governance / decision history |
| `docs/FROZEN_ARTIFACT_POLICY.md` | artifact 恢复与状态规则 | governance / protocol |
| `docs/FROZEN_ARTIFACT_REGISTRY.json` | 当前重要 artifact 的机器可读 identity/status | governance / registry |
| `research/protocols/setup03_phase5j_v4_lifecycle_attribution_protocol.json` | Phase 5J-v4 machine-readable frozen protocol | research protocol；真实 attribution 前冻结 |
| `research/protocols/setup03_phase5j_v4_lifecycle_attribution_protocol.md` | Phase 5J-v4 中文协议说明 | research protocol documentation |
| `research/phase5j_v4_protocol.py` | version/hash/invariant loader | research-only integrity gate |
| `tests/test_phase5j_v4_protocol.py` | protocol immutability regression | research protocol tests |
| `trading/setup.py` | additive read-only lifecycle operands | production Setup/event outputs unchanged by exact-main parity |
| `research/phase5j_v4_lifecycle_attribution.py` | trace, FIRST_DIVERGENCE_BAR, root/propagation/lineage/counterfactual | research-only |
| `research/phase5j_v4_evidence.py` | mechanical aggregation, parity, concordance, hashes/report | research-only |
| `scripts/run_phase5j_v4_lifecycle_attribution.py` | frozen end-to-end runner | no provider/outcome/OOS path |
| `research/development/phase5j_v4_*` | capsule/report/per-symbol/root/cascade/counterfactual/concordance artifacts | tracked development-only evidence |
| `research/atr_boundary_protocol.py` / `research/protocols/setup03_atr_boundary_structural_qualification_protocol.json` | v5 ATR boundary protocol/hash gate | research-only frozen contract |
| `research/atr_boundary_universe.py` / `research/atr_boundary_universe_manifest.json` | metadata-only final clean roster | selection before OHLCV; result-independent |
| `research/atr_boundary_dataset.py` / `research/atr_boundary_clean_holdout/*` | new clean-holdout acquisition and tracked manifests | BaoStock/yfinance development data identity |
| `research/atr_boundary_qualification.py` / `research/atr_boundary_qualification/*` | structure-only candidate/adjacent/lifecycle matrix, parity and repeat | no Decision/outcome/OOS path |
| `scripts/acquire_atr_boundary_holdout.py` / `scripts/run_atr_boundary_qualification.py` | bounded acquisition and qualification runners | explicit stop-state output |
| `core.py` / `providers.py` / `main.py` | production latest quote date, source freshness and execution-mode isolation | P0 hotfix; trade behavior unchanged |
| `.github/workflows/asia-close.yml` / `.github/workflows/us-close.yml` | scheduled latest-only and manual full mode routing | production workflow boundary |
| `tests/test_validation.py` / `tests/test_decision_sheet.py` / `tests/test_governance.py` | market-local date, source mismatch, future-date and latest-only regression | regression coverage |
| `trading/models.py` / `trading/fibonacci.py` / `trading/wave.py` | Wave Scenario Engine v1 models, Fibonacci regions and strict causal evaluator | additive read-only structural context |
| `scripts/run_wave_shadow.py` / `.github/workflows/wave-shadow.yml` | real-holdings JSON/CSV shadow and manual PR workflow | no Sheets/Decision/ENTRY/outcome writes |
| `tests/test_wave.py` / `docs/WAVE_SCENARIO_ENGINE_V1.md` | Wave Engine regression contract and protocol documentation | v1 semantics / governance |
| `trading/setup01.py` / `trading/setup01_replay.py` | SETUP_01 immutable lifecycle evaluator, strict prefix replay and terminal event identity | separate SETUP_01 structural layer; no SETUP_03 behavior change |
| `docs/SETUP_01_WAVE2_TO_WAVE3_V1.md` | SETUP_01 v1 protocol, lifecycle, invalidation, Fib and as-of contract | protocol / governance |
| `scripts/run_setup01_structural_replay.py` / `research/development/setup01_wave2_to_wave3_v1_structural_diagnostic.*` | development-only structure replay and compact Sol evidence | no outcomes/OOS/Decision/Sheets |
| `tests/test_setup01.py` | synthetic lifecycle, invalidation, ABC/downtrend, confirmed/provisional and future invariance regression | SETUP_01 correctness |

## 7. Frozen Identities And Invariants

- Wave Engine protocol: `WAVE-SCENARIO-ENGINE-2026-08-30-v1`；fixed as-of uses only `data <= as_of_date`，weekly aggregation excludes Monday–Thursday incomplete ISO week，and daily continuation requires current daily `UPTREND`。
- SETUP_01 protocol: `SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1`；eligible primary context is confirmed LOW→HIGH→LOW with `peak > origin`, `wave2_low > origin`, `wave2_low < peak`, weekly parent not DOWNTREND, and `setup01_context_eligible=true`。
- SETUP_01 lifecycle invariant: `NONE/WATCH/ARMED/CONFIRMED/FAILED`; ARMED uses fixed causal 0.5 recovery, CONFIRMED requires close strictly above Wave 1 peak, and origin versus confirmed Wave 2 low remain separate invalidations. No ACTIVE/COMPLETED state, no Fib hard gate, no production ENTRY/Decision.
- Development evidence: 40 symbols / 86,305 days / 1,404 events (745 CONFIRMED / 659 FAILED) / 0 errors; real shadow run `33300273180`: 10 enabled / 8 evaluated / 2 fail-closed errors, no returns/OOS/Sheets writes。

- Phase 5J-v3 event-matching protocol: `SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1`, canonical SHA-256 `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`。
- Phase 5J-v4 lifecycle-attribution protocol: `SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1`, canonical SHA-256 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`；state `LIFECYCLE_ATTRIBUTION_PROTOCOL_FROZEN_NOT_EXECUTED`。
- Phase 5J-v4 attribution capsule: file SHA-256 `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`，canonical payload `sha256:a2e9a48cac483bca6aae9aeec4d5405634118632e7c34170aef863f24991e797`；ignored derived trace SHA-256 `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`。
- Holdout universe: `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-2026-08-29-v2`, manifest SHA-256 `sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65`；symbol-list SHA-256 `sha256:dc81b5b8c96408b0d18a161f946aeaf5ad616060d82cd6b6f8497a5b26bef036`。
- Dataset: `SETUP_03-DEVELOPMENT-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1`，canonical manifest SHA-256 `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`，normalized aggregate `sha256:b08832bdad7c2a857d7b60fc7b56a75d09594ee648008ab852bde4a8a56405b1`，replay aggregate `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`。
- Dataset coverage: CN 20 / 41,274 bars；US 20 / 45,031 bars；total 40 symbols / 86,305 bars；provider split is `BAOSTOCK_DEVELOPMENT_QFQ` / `YFINANCE_DEVELOPMENT_HISTORICAL`。
- Backup container: 3,086,881 bytes, SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；Google Drive persistent backup and independent cloud reread are externally verified, current status `FULLY_RECOVERABLE`。
- Recovery manifest records source artifact commit `3a2c6699559074161b56281dd16084264f7dc717` as a historical local-ref-only provenance pin；this is not the current remote `main` SHA and must not be silently rewritten.
- Invariants: no provider fallback/history splice/date fill/synthetic bar/OHLC mutation/result-driven symbol replacement；no future data; `signal(t)` only uses `data <= t`；frozen protocol, manifests, roster, hashes and exact replay bytes cannot be silently changed。
- v5 ATR protocol: `SETUP_03-ATR-BOUNDARY-STRUCTURAL-QUALIFICATION-2026-08-29-v1`, SHA-256 `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4`；clean universe `SETUP_03-ATR-BOUNDARY-CLEAN-HOLDOUT-CN-US-2026-08-29-v1`, manifest SHA-256 `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b`。
- v5 dataset: 40 symbols / 88,075 bars；manifest SHA-256 `sha256:9940f0e496e3c5ead4216d33d28bd23b023801007bf46d63051237bd7b8a1b29`，normalized aggregate `sha256:a98cbbb0065b29f77d237dd43365746a41d08462f1ec2bbc112030e0231ce038`，replay aggregate `sha256:37c269ca1044fcb611650a83e670b12b41353ddcf9b912514222c9218ca70a76`。
- v5 qualification: candidates `1.0/1.5/2.0/2.5` all candidate-level PASS；adjacent/lifecycle gates leave `qualified_candidates=[]`，selected candidate `null`，parity/repro PASS；final status `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`。Capsule canonical payload `sha256:5c799f5f9b2d2655c0dd1ff4fd773af32e3e05d805175d696791c80fe767a42b`。
- Production date invariants: `交易日期 = chosen quote 的市场真实 session trade_date`；`运行时间 = 北京时间 fetched_at`。US 交易日期保持 US local session date，不因北京时间跨日加一天；A股交易日期保持 A股市场日期；两者不得互相替代。

## 8. Known Issues / Blockers

| category | status / impact | workaround | blocks continuation? |
|---|---|---|---|
| artifact/data availability | second-holdout bundle is `FULLY_RECOVERABLE`; Google Drive object ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS` and recovered ZIP SHA-256 are recorded from external audit | do not repeat cloud network verification; use registry identity and existing loader evidence | No |
| environment / verification | 持仓 manager substantive source `2dd1ed0` 已在最新 main 上本地验证；当前尚未 push/创建 PR，Skill validator 因 bundled Python 缺少 `yaml` 模块未能运行 | 完成 compile/diff checks 后 push，实时核对新 PR tip、exact-head CI 与 mergeability；docs-only commit 不记录自身 SHA | No |
| research/design blocker | v5 预注册 ATR family 已完成；candidate-level 全通过但 adjacent/lifecycle qualification 未通过，结果为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` | 不选择 threshold，不改 terminal/rearm；后续需新的明确研究决策和新 protocol/version | Yes for any further SETUP_03 research or production/strategy change |
| protocol persistence | v5 protocol 已冻结，SHA `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4`；clean universe manifest SHA `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b` | 先提交/push freeze checkpoint，再获取 OHLCV；任何 identity 变化新建版本 | No after freeze commit |
| Sol / user decision node | SETUP_03 仍为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`；Wave/SETUP01 为历史上下文；本任务只等待 holdings manager Sol review | 新 PR exact-head CI 与治理对账成功后停止在 `HOLDINGS_DATA_MANAGER_SKILL_READY_FOR_SOL_REVIEW`；不自动 merge，不进入策略/账户动作 | No for this task |
| shadow data quality | 10 个启用持仓中 8 个完成评估；SIVE.SE qfq `2026-08-27` 相对 freshness 下限 `2026-08-28` 为 `DATA_STALE`，MU 的 `历史数据源` 为空，均 fail-closed，整体 `PARTIAL_DATA_QUALITY` | 补齐明确历史源后另行运行 shadow；禁止默认猜测 provider 或写入 Sheets | Yes for claiming full 10/10 evaluation |
| project coordination | 旧 PR #31 已关闭并注明 `superseded by #34`；PR #35/#36 属于历史 strategy work；本任务分支独立 | 不 merge/rebase 旧 PR；仅创建本任务独立 PR，等待 Sol review | No, if kept separate |
| environment | 初始检查时存在的 `.hotfix-worktree/` 在 post-commit 检查时已不再存在；未执行删除命令 | 若重新出现，保持隔离并排除 governance commit | No |

## 9. Lessons / Pitfalls — DO NOT REPEAT

### Pitfall 1

**What happened:** 文档中的 PR 状态曾落后于真实 GitHub 状态，例如已合并 PR 仍写成待审阅/待合并。

**Root cause:** 只依赖旧文档，没有在交接时按 exact head 查询远端 PR。

**Consequence:** 新会话可能重复工作或错误判断 base/stacked branch。

**Permanent prevention rule:** 每次独立任务结束和新会话开始都核对远端 PR number/state/head SHA/merge SHA，并在 HANDOFF 中记录。

### Pitfall 2

**What happened:** 本地 `origin/main` 仍为旧 SHA，而 GitHub `main` 已推进。

**Root cause:** remote-tracking ref 没有刷新，且旧 ref 看起来像有效基线。

**Consequence:** 本地 merge-base、diff 和 PR 预判可能错误。

**Permanent prevention rule:** 关键决策前必须 `git fetch origin main`，并将本地 ref 与 GitHub API/PR base SHA 对账；无法对账时标记 `PROJECT_GOVERNANCE_STATE_CONFLICT`。

### Pitfall 3

**What happened:** frozen replay wrapper 曾绑定 provisional dataset SHA，而不是包含 replay aggregate 的 final dataset SHA。

**Root cause:** 生成顺序为 wrapper 先于 final dataset manifest。

**Consequence:** provenance cross-binding 错误，虽未改变 bars，但破坏了恢复身份的可信度。

**Permanent prevention rule:** 固定顺序为 normalized data → replay input/aggregate → final dataset manifest → replay wrapper；loader 必须 fail closed 验证所有 cross-bindings。

### Pitfall 4

**What happened:** correctness-critical payload 只存在 ignored `artifacts/` 或短期 CI artifact。

**Root cause:** Git 中只保留 manifest/report，未登记持久化备份与恢复证据。

**Consequence:** 新电脑无法按 hash 恢复 exact input，不能声称 fully recoverable。

**Permanent prevention rule:** 每个重要 artifact 必须进入 registry；未满足 local/hash/persistent/recovery 四项时，状态明确不是 `FULLY_RECOVERABLE`，禁止用近似重生成替代。

### Pitfall 5

**What happened:** branch 名称暗示 Phase 5J-v4，而治理快照曾只证明 v3 holdout 与 backup staging；本轮用户已明确确认 v4 frozen task 可继续。

**Root cause:** branch naming 曾被误当作正式 objective/protocol；本轮必须以用户确认和仓库可核对的 protocol/evidence 共同落地。

**Consequence:** 可能在 backup prerequisite 未完成或 scope 未核实前启动未授权研究。

**Permanent prevention rule:** branch name 只能作为线索；正式任务必须由 HANDOFF/CURRENT_STATUS、用户本轮授权、protocol、PR/commit 和客观 artifact evidence 共同确认。

## 10. Next Action

1. [x] 从真实最新 `main@3a6d417ede3594c05003ea18ce65bd4562eff294` 建立 `codex/holdings-data-manager`。
2. [x] substantive source commit `2dd1ed0` 已实现，并通过 focused `13/13` 与 full `384/384` unittest。
3. [x] `HANDOFF`、`CURRENT_STATUS`、`DECISION_LOG`、`ARCHITECTURE`、README 与 Skill specification 已同步本任务边界。
4. [x] targeted compileall、`git diff --check` 与手工 Skill frontmatter 检查通过；官方 validator 因 bundled Python 缺少 `yaml` 模块未运行。
5. [x] push 分支、创建独立 PR #38；首轮 tip `8f48921…` 的 exact-head CI `33354460712` success，PR OPEN/mergeable=true。
6. [ ] docs-only 对账 push 后核对 PR #38 final tip/exact-head CI；确认一致后停在 `HOLDINGS_DATA_MANAGER_SKILL_READY_FOR_SOL_REVIEW`，不自动 merge。

## 11. Handoff Checklist

- [x] Current Objective 已更新
- [x] main / branch / PR / CI 已更新
- [x] Completed Work 已更新
- [x] Pending Work 已更新
- [x] 新的重要 decision + rationale 已记录
- [x] Important Files Changed 已更新
- [x] Frozen identities / invariants 与真实状态一致
- [x] Known Issues / Blockers 已更新
- [x] 新的高价值踩坑已记录
- [x] Next Action 可直接执行
- [x] 与其他治理文件不存在冲突
- [x] HANDOFF 没有陈旧状态

## 12. Last Verified

- `last_updated_at`: `2026-08-31T11:39:28+08:00`（治理 snapshot；docs-only update 后 PR final tip/CI 需实时复核）
- `verified_main_sha`: `3a6d417ede3594c05003ea18ce65bd4562eff294`
- `verified_branch_head`: `2dd1ed0`（branch=`codex/holdings-data-manager`；latest substantive source head）
- `latest_test_result`: focused holdings `13/13`、full unittest `384/384` passed；targeted compileall 与 `git diff --check` passed；manual Skill frontmatter check passed；official validator blocked by missing bundled `yaml` module
- `latest_ci_run`: PR #38 pre-final-docs tip `8f48921…` exact-head CI `33354460712` success；docs-only update后 final tip/CI须实时复核
- `latest_pr`: #38 `OPEN`，base=`3a6d417…`，mergeable=true；不自动 merge
- `updated_by_task`: `repository-local holdings-data-manager Skill and deterministic holdings lifecycle operations`

`HANDOFF_CURRENT_AND_CONSISTENT`

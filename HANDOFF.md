# CURRENT OPERATIONAL HANDOFF SNAPSHOT

> 本文件是下一台设备 / 下一次开发会话的可执行交接快照，不是完整历史流水账。新会话第一步读取本文件，然后读取 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`，再核对真实 Git / PR / CI / artifact 状态。

## PROJECT STRATEGY IDENTITY

- 本项目不是单一 Platform Breakout 系统；长期总体策略的唯一正式事实源是 `docs/TRADING_SYSTEM_SPEC.md`。
- 总体主线：`Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`。
- 第一版四类 Setup：`SETUP_01`（Wave 2 → Wave 3）、`SETUP_02`（Wave 3 Continuation）、`SETUP_03`（Platform Breakout）、`SETUP_04`（Extreme Fear Reversal）。
- `SETUP_03` 当前只是正在研究的一个子策略；当前开发深度、commit 数量或 Phase 数量不改变总体策略或优先级。Wave Scenario Engine、`SETUP_01`、`SETUP_02` 仍是总体核心路线。
- 任何总体路线变化都必须先取得用户明确批准，并记录在 `docs/DECISION_LOG.md`；本快照不复制完整策略规范，避免双事实源。

## 1. Current Objective

- **当前 Phase / task:** `SETUP01_GENERIC_OPERATIONAL_SHADOW_READY_FOR_SOL_REVIEW`。
- **具体目标:** PR #36 correctness/governance closeout 已完成并 squash merge；从新 main 独立实现的 SETUP_01 Decision/Risk v1、DEVELOPMENT_EXPOSED historical funnel 与 synthetic-only generic operational shadow 已完成，停在 Sol 审阅节点。
- **PR #35 closeout:** 已按 `APPROVE_WAVE_SCENARIO_ENGINE_V1` squash merge；真实 merge commit `2d48d90bdc3a48ef96b2a802d5c8c448de5ba6b6`，main exact-head CI `33298510168` success；旧 PR #31 已关闭并注明 `superseded by #34`。
- **当前实现:** PR #36 已按授权 squash merge，真实 merge commit 为 `3a6d417ede3594c05003ea18ce65bd4562eff294`，main exact-head CI `33316793033` success。PR #37 `codex/setup01-decision-risk-v1` 的 latest substantive source head 为 `5d242fb`，实现独立的 `SETUP-01-DECISION-RISK-2026-08-30-v1` 与 synthetic-only generic operational shadow；PR final tip/CI 状态由 GitHub 实时核验。SETUP_01 structural protocol 仍为 `SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1`，structural lifecycle/event counts 未改写。
- **Decision/Risk evidence:** DEVELOPMENT_EXPOSED funnel 使用既有 745 个首个 `CONFIRMED` event，745 条 Decision；`ABOVE_ENTRY_ZONE=464`、`RR_BELOW_MINIMUM=276`、`ENTRY_ALLOWED=5`；5 次 T+1 OPEN feasibility 中 `EXECUTED=4`、`SKIP_GAP_BELOW_CONFIRMATION=1`。risk capital 保持显式输入；本次 funnel 未猜 NAV/position size。
- **Generic operational shadow:** `CONTROLLED_PUBLIC_SYNTHETIC_HOLDINGS_FIXTURE` 已通过：7 supplied events / 6 unique identities / 3 Decision rows / 2 T+1 attempts / 1 EXECUTED / 1 `SKIP_GAP_BELOW_CONFIRMATION`；exact-once、terminal semantics、T→T+1、fail-closed、reporting pipeline 全部通过。
- **Real holdings shadow classification:** `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`；当前状态 `NOT_RUN_USER_PRIVACY`。本任务不读取真实持仓、不依赖账户 holdings secrets、不向 GitHub Actions 输出任何持仓派生信息；它不是当前 SETUP_01 research/development gate 的 blocker。
- **明确禁止事项:** 不启动 SETUP_02，不重新打开 SETUP_03，不自动 merge新的 Decision/Risk PR，不读取 returns/MFE/MAE/P&L/Final OOS，不猜 NAV/position size，不写任何 production Sheet；PR #37 仅供 Sol review。
- **停止条件:** 已达到 `SETUP01_GENERIC_OPERATIONAL_SHADOW_READY_FOR_SOL_REVIEW`。PR #37 保持 OPEN，不自动 merge；Sol review 前不启动 SETUP_02、不重新打开 SETUP_03、不读取任何 outcome/OOS。

## 2. Current Repository State

- **repository:** `EFSing/stock-data-pipeline`
- **default/main branch:** `main`
- **main/base SHA:** GitHub remote `main@3a6d417ede3594c05003ea18ce65bd4562eff294`；该 SHA 是 PR #36 的 squash merge commit，main push CI `33316793033` success。
- **working branch:** `codex/setup01-decision-risk-v1`（PR #37，保持 OPEN 供 Sol review）。
- **implementation source head:** PR #37 latest substantive head `5d242fb`，基于 main `3a6d417...`；governance docs 不保存包含自身的最终 docs-only SHA，PR final tip/exact-head CI/mergeability 以 GitHub 实时证据为准。
- **previous reviewed head:** `b3da9e87a25b3a56c341a6096c021666150a19d5`，exact-head CI `33268711570` success，shadow `33268711569` success。
- **PR:** #36 已关闭并 squash merge，merge commit `3a6d417...`；旧 PR #31 已关闭并注明 `superseded by #34`；PR #37 base=`main@3a6d417...`，head=`04cf4c4...`，保持 OPEN，未自动 merge。
- **latest exact-head checks:** PR #37 previous source head CI `33318129206` success；generic shadow source head `5d242fb` 的 CI/mergeability 由 GitHub 实时核验；当前没有任何 GitHub Actions workflow 读取或输出真实持仓派生信息。
- **working tree expected state:** 治理文档同步后工作区保持 clean；ignored `artifacts/` 保持 ignored；development replay 与 shadow artifact 仅作审计核验，不进入生产 Sheet。
- **current project/phase status:** `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` 保持不变；当前状态为 `SETUP01_GENERIC_OPERATIONAL_SHADOW_READY_FOR_SOL_REVIEW`。SETUP_02、Final OOS、Phase 5K-B1、IBKR 与任何 outcome 研究仍未执行。

## 3. Completed Work

- PR #35 已从最新 main squash merge 为 `2d48d90bdc3a48ef96b2a802d5c8c448de5ba6b6`，main CI `33298510168` success；PR #31 已关闭并记录 `superseded by #34`。
- Wave Scenario Engine v1 已实现：严格 `data <= as_of_date`、完整周边界、weekly parent → daily context、confirmed Swing、现有 Fibonacci regions、primary/alternate、证据/反证/规则计分、结构失效、context eligibility 与 fail-closed UNKNOWN/NO_VALID families。
- Wave Engine v1 测试覆盖 canonical/synthetic 场景、future append invariance、不完整当前周、weekly/daily state、confirmed/provisional、Fib region、primary/alternate coexistence 与 read-only shadow；focused `tests.test_wave` 为 `12/12` 通过。
- PR #36 correctness/governance closeout 已完成并 squash merge 为 `3a6d417ede3594c05003ea18ce65bd4562eff294`；main exact-head CI `33316793033` success。PR #37 的 Decision/Risk v1、funnel、generic operational shadow 与 tests 已提交；PR #37 previous CI `33318129206` success，latest generic-shadow tip 的 exact-head CI 待实时核验，未向 GitHub Actions 暴露真实持仓。
- Historical Wave shadow evidence remains archived for audit only; it is not a current Decision/Risk gate and is not re-run or re-read in this task.
- SETUP_01 v1 已完成：独立 immutable model/evaluator、固定 `NONE/WATCH/ARMED/CONFIRMED/FAILED` lifecycle、primary-only Wave Engine context、ABC/downtrend counter-scenario blocks、两类独立 invalidation、canonical Fib diagnostics、strict prefix replay 与 deterministic CONFIRMED/FAILED event identity。Wave 2 low 额外要求低于 Wave 1 peak，避免非 retracement 误判。
- Development structural replay 已完成：40/40 symbols、86,305 days、0 errors、1,404 events（745 CONFIRMED / 659 FAILED）；CN event distribution 299/313，US 446/346；唯一未终结 development candidate 为 STX/US ARMED。
- Generic operational shadow 已完成且仅使用 `GENERIC.*` controlled fixture；真实持仓 shadow 仅登记为 `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY`，不作为当前 progression blocker。
- Correctness closeout shadow remains historical evidence only; this task does not re-read real holdings or emit holdings-derived output to GitHub Actions. Its private validation category is `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY`。
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

1. [x] 核对并 squash merge PR #35，确认 merge commit `2d48d90bdc3a48ef96b2a802d5c8c448de5ba6b6` 与 main CI `33298510168` success。
2. [x] 关闭旧 PR #31 并记录 `superseded by #34`，不直接移植其旧-base diff。
3. [x] 从最新 main 建立 `codex/setup01-wave2-to-wave3-v1`，实现 Wave Scenario Engine v1 与 read-only shadow runner/workflow。
4. [x] 增加 causal/as-of、state、Fib、scenario coexistence、未来追加不变性及 shadow read-only 测试。
5. [x] 对真实 10 个启用持仓重新运行 correctness-closeout shadow；8 个完成评估，SIVE.SE freshness stale、MU 历史源为空，均 fail-closed，artifact 状态为 `PARTIAL_DATA_QUALITY`。
6. [x] SETUP_01 v1 protocol/lifecycle/evaluator/replay、future invariance、counter-scenario tests 与 structure-only diagnostic 已完成。
7. [x] Historical PR #36 shadow `33300273180` 已作为旧 head evidence 保留；新 terminal projection 在 PR #37 关联的 run `33318129223` 上重新核验。
8. [x] PR #36 final tip exact-head CI/shadow、PR state/mergeability 已实时核验；按授权 squash merge 为 `3a6d417...`，main CI `33316793033` success。
9. [x] 从新 main 建立 `codex/setup01-decision-risk-v1`，实现独立 Decision/Risk v1、DEVELOPMENT_EXPOSED funnel、structural holdings shadow 与 regression；PR #37 保持 OPEN，不自动 merge。

### Deferred

- SETUP_01 Decision/Risk/production integration 与独立 SETUP_02 实现，须先经 Sol review 确认 v1 结构语义与实际 shadow 数据质量。
- 如需继续 SETUP_03，等待新的明确研究决策并注册新 protocol/version；当前结果不授权任何 threshold 或 production 选择。
- Final OOS、formal Phase 5K-B1、IBKR readiness 和任何 production parameter/strategy change。

### Prohibited For Now

- 自动 merge新的 Decision/Risk PR；把 Wave Engine/SETUP_01 shadow 场景当作交易信号或 `ENTRY_ALLOWED`。
- 直接 merge/rebase PR #31，或重新打开 SETUP_03 structural development。
- 读取 returns、forward returns、MFE、MAE、P&L、winrate、expectancy、Final OOS、Phase 5K-B1 或 IBKR formal OHLCV。
- 改变 percentage production default、SETUP_03/Trading Core/Decision 既有交易行为或 Google Sheets schema。
- shadow runner 不得写 Google Sheets、历史行情、交易决策、生产配置或任何交易字段。

## 5. Key Decisions And Rationale

### Decision

- 以 `HANDOFF.md` 管当前快照、`CURRENT_STATUS.md` 管正式状态、`DECISION_LOG.md` 管长期理由；artifact 的可恢复性单独由 policy + registry 管理。
- 重要 bytes 未进 Git 时，只有 `LOCAL_PRESENT`、`HASH_VERIFIED`、`PERSISTENT_BACKUP_PRESENT`、`RECOVERY_VERIFIED` 全部满足，才允许 `FULLY_RECOVERABLE`。
- Phase 5J-v3 当前结果保持 development-only / structure-only；没有新的授权前，不将其解释为生产参数决定。

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
| `scripts/run_wave_shadow.py` | private/local holdings structural shadow capability | optional private validation only; no GitHub Actions path |
| `tests/test_wave.py` / `docs/WAVE_SCENARIO_ENGINE_V1.md` | Wave Engine regression contract and protocol documentation | v1 semantics / governance |
| `trading/setup01.py` / `trading/setup01_replay.py` | SETUP_01 immutable lifecycle evaluator, strict prefix replay and terminal event identity | separate SETUP_01 structural layer; no SETUP_03 behavior change |
| `trading/setup01_decision.py` / `trading/fibonacci.py` | independent SETUP_01 Decision/Risk v1, generic canonical extension projection, T+1 OPEN feasibility | Decision/Risk only; no SETUP_03 reuse or outcome path |
| `research/setup01_decision_funnel.py` / `scripts/run_setup01_decision_funnel.py` | DEVELOPMENT_EXPOSED confirmed-event → Decision → T+1 funnel | development-only, no returns/OOS |
| `scripts/run_setup01_generic_operational_shadow.py` / `tests/test_setup01_generic_operational_shadow.py` | synthetic-only generic operational shadow | no real holdings, no account secrets, no outcome path |
| `scripts/run_setup01_decision_shadow.py` | private real holdings Decision shadow capability | optional production-validation scope only; not run and no GitHub Actions workflow |
| `tests/test_setup01_decision.py` / `docs/SETUP_01_DECISION_RISK_V1.md` | exactly-once, causal T+1, target-first/RR, shadow regression and protocol | v1 review contract |
| `docs/SETUP_01_WAVE2_TO_WAVE3_V1.md` | SETUP_01 v1 protocol, lifecycle, invalidation, Fib and as-of contract | protocol / governance |
| `scripts/run_setup01_structural_replay.py` / `research/development/setup01_wave2_to_wave3_v1_structural_diagnostic.*` | development-only structure replay and compact Sol evidence | no outcomes/OOS/Decision/Sheets |
| `tests/test_setup01.py` | synthetic lifecycle, invalidation, ABC/downtrend, confirmed/provisional and future invariance regression | SETUP_01 correctness |

## 7. Frozen Identities And Invariants

- Wave Engine protocol: `WAVE-SCENARIO-ENGINE-2026-08-30-v1`；fixed as-of uses only `data <= as_of_date`，weekly aggregation excludes Monday–Thursday incomplete ISO week，and daily continuation requires current daily `UPTREND`。
- SETUP_01 protocol: `SETUP-01-WAVE2-TO-WAVE3-2026-08-30-v1`；eligible primary context is confirmed LOW→HIGH→LOW with `peak > origin`, `wave2_low > origin`, `wave2_low < peak`, weekly parent not DOWNTREND, and `setup01_context_eligible=true`。
- SETUP_01 lifecycle invariant: `NONE/WATCH/ARMED/CONFIRMED/FAILED`; ARMED uses fixed causal 0.5 recovery, CONFIRMED requires close strictly above Wave 1 peak, and origin versus confirmed Wave 2 low remain separate invalidations. No ACTIVE/COMPLETED state, no Fib hard gate, no production ENTRY/Decision.
- Development evidence: 40 symbols / 86,305 days / 1,404 events (745 CONFIRMED / 659 FAILED) / 0 errors; Decision funnel uses 745 first-entry CONFIRMED events and yields 5 ENTRY_ALLOWED / 4 EXECUTED / 1 T+1 skip, no returns/OOS。
- SETUP_01 Decision/Risk protocol: T close plan only; earliest T+1 OPEN; confirmation=Wave1 peak; entry zone `[peak, peak+0.5*ATR14(T)]`; execution stop=`Wave2 low-0.5*ATR14(T)`; structural invalidations remain Wave2 low and Wave1 origin; canonical existing extension ratios only; RR<2 NO_TRADE。
- Generic operational shadow `5d242fb`: 7 supplied synthetic events / 6 unique identities / 3 Decision rows / 2 T+1 attempts / 1 executed / 1 gap-below-confirmation skip；all five operational checks pass. Real holdings shadow is `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY`; no holdings-derived output was sent to GitHub Actions.

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
| environment / verification | PR #36 已 squash merge为 `3a6d417...`；PR #37 latest substantive source head `5d242fb`，previous CI `33318129206` success；PR final tip/mergeability 以 GitHub 实时核验 | 新 Decision/Risk PR 不自动 merge；generic shadow 不需要 Secrets；真实持仓不通过 GitHub Actions；docs-only commit 不记录自身 SHA | No |
| research/design blocker | v5 预注册 ATR family 已完成；candidate-level 全通过但 adjacent/lifecycle qualification 未通过，结果为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` | 不选择 threshold，不改 terminal/rearm；后续需新的明确研究决策和新 protocol/version | Yes for any further SETUP_03 research or production/strategy change |
| protocol persistence | v5 protocol 已冻结，SHA `sha256:86595d25226b0c9280492df8f91bb5a9fd92c2dd753dfa6114986c71ec6145b4`；clean universe manifest SHA `sha256:bee3b399a50393fb793862408935d2f5397f93e1c2209ced91183e6ee9517f9b` | 先提交/push freeze checkpoint，再获取 OHLCV；任何 identity 变化新建版本 | No after freeze commit |
| Sol / user decision node | SETUP_03 仍为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT`；PR #37 为 OPEN review PR | review Decision/Risk v1 protocol、745-event funnel 与 generic operational shadow；不启动 SETUP_02、不重开 SETUP_03、不自动 merge新的 Decision/Risk PR | P1 for merge/production decisions; not a generic gate blocker |
| real holdings shadow | `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`; current status `NOT_RUN_USER_PRIVACY` | 不读取真实持仓，不依赖 holdings secrets；只有未来明确 production milestone 要求真实持仓集成时，才在该 milestone 内重新定义 scope-local blocker | No |
| generic operational shadow | `GENERIC_OPERATIONAL_SHADOW` success；synthetic-only fixture，exact-once/T→T+1/terminal/fail-closed/reporting checks all pass | 作为当前产品/工程 gate；继续只使用 controlled fixture 与 DEVELOPMENT_EXPOSED data | No |
| research/design blocker | v5 预注册 ATR family 已完成；candidate-level 全通过但 adjacent/lifecycle qualification 未通过，结果为 `STOP_SETUP_03_STRUCTURAL_DEVELOPMENT` | 不选择 threshold，不改 terminal/rearm；后续需新的明确研究决策和新 protocol/version | P1 only for SETUP_03 continuation |
| project coordination | 旧 PR #31 已关闭并注明 `superseded by #34`；PR #36 已独立 squash merge；PR #37 为当前 review PR | do not merge/rebase #31；PR #37 只等待 Sol review，不自动 merge | No, if kept separate |
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

1. [x] PR #35 已 squash merge 为 `2d48d90bdc3a48ef96b2a802d5c8c448de5ba6b6`，main CI `33298510168` success；PR #31 已关闭并记录 `superseded by #34`。
2. [x] SETUP_01 Wave 2 → Wave 3 v1 已在 `codex/setup01-wave2-to-wave3-v1` 实现并通过 focused/full tests。
3. [x] 已记录 previous reviewed head `b3da9e87a25b3a56c341a6096c021666150a19d5`、CI `33268711570`、shadow `33268711569` 及 review correctness findings。
4. [x] PR #36 previous head `ca9ec6e93518e7e47c13f8f41a7f5751c9fd24d0` 的 exact-head CI `33300273163`、real holdings shadow `33300273180` success；该 evidence 不覆盖当前 substantive head。
5. [x] SETUP_01 development replay：40/40 symbols、86,305 days、1,404 events、0 errors；previous real shadow：10 requested / 8 evaluated / 2 fail-closed errors。
6. [x] PR #36 source head `eed768...` 已增加 terminal-vs-new-event projection、shadow 字段与回归，并已 squash merge为 `3a6d417...`。
7. [x] PR #36 final tip exact-head CI/shadow、PR state/mergeability 已实时核验；PR #36 已 squash merge为 `3a6d417...`，main CI `33316793033` success。
8. [x] 从新 main 实现独立 SETUP_01 Decision/Risk v1、历史 decision/execution funnel 与 synthetic-only generic operational shadow；PR #37 previous CI `33318129206` success；不自动 merge PR #37。
9. [x] governance self-reference rule、terminal-vs-new-event projection、event identity exactly-once、T→T+1、target-first/RR、read-only shadow regression 已落地并通过测试。

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

- `last_updated_at`: `2026-08-30T23:00:00+08:00`（治理快照；PR final tip/mergeability 仍以 GitHub 实时核验）
- `verified_main_sha`: `3a6d417ede3594c05003ea18ce65bd4562eff294`
- `verified_branch_head`: `5d242fb`（branch=`codex/setup01-decision-risk-v1`；latest substantive generic-shadow source head；docs-only updates 不要求记录自身 SHA）
- `latest_test_result`: full unittest `381/381` passed；focused SETUP_01/Wave/generic `38/38` passed；compile `3538` Python files passed；synthetic shadow success；`git diff --check` passed
- `latest_ci_run`: PR #37 exact-head CI `33318129206` success；PR #37 current final tip/mergeability 需在 governance docs commit后实时复核
- `generic_operational_shadow`: synthetic-only `5d242fb` success；7 supplied / 6 unique / 3 decisions / 2 T+1 attempts / 1 executed / 1 skip；no real holdings or account secrets
- `setup01_decision_funnel`: 745 CONFIRMED / 745 Decision rows / 5 ENTRY_ALLOWED / 5 T+1 attempts / 4 EXECUTED / 1 SKIP_GAP_BELOW_CONFIRMATION；CN 299, US 446；decision gates ABOVE_ENTRY_ZONE=464, RR_BELOW_MINIMUM=276, ENTRY_ALLOWED=5
- `setup01_structural_replay`: 40/40 symbols / 86,305 days / 1,404 lifecycle events / 745 CONFIRMED / 659 FAILED / 0 errors；real holdings shadow is not run in this task for privacy
- `real_holdings_shadow`: `OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY`; no GitHub Actions holdings-derived output
- `updated_by_task`: `PR #36 closeout, SETUP_01 Decision/Risk v1, and generic operational shadow governance reclassification`

`HANDOFF_CURRENT_AND_CONSISTENT`

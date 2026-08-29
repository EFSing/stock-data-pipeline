# CURRENT OPERATIONAL HANDOFF SNAPSHOT

> 本文件是下一台设备 / 下一次开发会话的可执行交接快照，不是完整历史流水账。新会话第一步读取本文件，然后读取 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`，再核对真实 Git / PR / CI / artifact 状态。

## 1. Current Objective

- **当前 Phase / task:** `Phase 5J-v4 — SINGLE_FROZEN_DATASET_CAUSAL_ATTRIBUTION_WITH_HISTORICAL_SYMPTOM_CONCORDANCE`，继续使用已冻结的第二套 development holdout。其 persistent backup/recovery prerequisite 已由外部审计完成并登记。
- **具体目标:** Phase 5J-v4 protocol 已先独立冻结，exact second holdout attribution、counterfactual diagnostics、historical symptom concordance、deterministic artifacts、完整验证与 PR 已完成；当前停在 Sol structure decision node，不把 development evidence 解释为 production decision。
- **为什么现在做:** correctness-critical raw/normalized/replay payload 虽位于被 Git 忽略的 `artifacts/`，但 exact ZIP 已上传 Google Drive，并由外部审计独立重新读取且 SHA-256 一致，跨设备恢复 gate 已满足。
- **Scope:** 仅使用现有 frozen protocol、second-holdout bundle、tracked provenance 与既有 research contracts；更新 v4 research evidence、registry/status/handoff/decision records，并为最终 review 准备 PR。
- **明确禁止事项:** 不访问 provider；不重新获取或重生成 bars；不修改 frozen manifests、protocol、symbol roster、既有 capsule 或既有 canonical hashes；不访问 Final OOS；不读取 returns/MFE/MAE/P&L/winrate/expectancy；不修改 production、Trading Core、Decision、execution 或 Google Sheets；不把近似重生成文件当作原 frozen artifact。
- **完成条件:** Phase 5J-v4 frozen workflow 产生可审计的 machine-readable/report evidence，保留 causal/as-of/identity/invariant checks，测试与静态检查通过，治理记录与实际 Git/PR/CI/artifact 状态一致，并创建 PR（不 merge）。
- **停止条件:** instrumentation 无法在不改变 production semantics 下完成；exact frozen holdout 出现真实性问题；新的真实 governance blocker；attribution 已形成 Sol 结构决策；或 PR fully ready。普通代码、测试、diagnostic、artifact/hash 问题自行修复。

## 2. Current Repository State

- **repository:** `EFSing/stock-data-pipeline`
- **default/main branch:** `main`
- **main/base SHA:** GitHub remote `main@142b7345a5640b1e87932e41f3dc9311172bf54c`；本地 `origin/main` 已通过 `git fetch origin main` 刷新到同一 SHA。
- **working branch:** `research/phase5j-v4-lifecycle-attribution`（已推送 origin）
- **current HEAD:** `THIS_COMMIT`（protocol freeze `4be4545bc2ddf54c3e970a162160c9fe3e464d4d`；implementation/evidence `573745b12ba39f28de738791ac7d91e737372481`；cross-platform provenance correction `a71640291eb993a2d3f8c06dcccc71909bdc51d5`；以 `git rev-parse HEAD` 解析最终治理 tip）。
- **PR:** #32 `Phase 5J-v4: lifecycle causal attribution` is `OPEN`, base `main`, not merged: `https://github.com/EFSing/stock-data-pipeline/pull/32`。Predecessor PR #30 was merged with merge commit `142b7345a5640b1e87932e41f3dc9311172bf54c`.
- **latest exact-head CI:** run `33259097880` covered `a71640291eb993a2d3f8c06dcccc71909bdc51d5` and succeeded after correcting tracked provenance hashes to Git-normalized LF bytes。This HANDOFF-only reconciliation commit must receive its own exact-head CI after push; verify it from PR #32 rather than inferring from the predecessor run.
- **latest remote main CI:** run `33232320454`, head `142b7345a5640b1e87932e41f3dc9311172bf54c`, `success`。
- **另一个并行项目 PR:** #31 `hotfix/production-market-data-stability` is `OPEN`, head `79ad70cc71171a10f232e02e752f795849bf706d`，exact-head CI run `33248943280` success；它不属于当前 checkout。
- **working tree expected state:** tracked files 应只包含本任务的 governance changes；ignored `artifacts/` 保持 ignored；初始检查时观察到的未追踪 `.hotfix-worktree/` 在 post-commit 检查时已不再存在，本任务未执行删除且未纳入 commit；若并行 worktree 重新出现，必须保持隔离。
- **current project/phase status:** Phase 5J-v4 mechanical status 为 `PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION`。largest root 为 `LOW_SPAN_THRESHOLD_CROSSING`，但 high/low/both 三类 root 均存在，故 `ATTRIBUTION_EVIDENCE_STATUS=MIXED_CAUSAL_STRUCTURE`；建议只到 `REDESIGN_PLATFORM_BOUNDARY_SEMANTICS` then `REDESIGN_TERMINAL_REARM_ORCHESTRATION`，不实施策略修改。formal validation、Final OOS、Phase 5K-B1 仍未执行。

## 3. Completed Work

- Phase 5J-v3 protocol、independent universe、holdout dataset、structure-only replay/parity 与 qualification 已完成并由 PR #30 合并；exact identities 见第 7 节和 `docs/CURRENT_STATUS.md`。
- loader 已修复 dataset → replay wrapper 的 provisional-hash cross-binding 顺序问题；现有 frozen identities 与研究结果不变，tracked wrapper integrity 为 `sha256:6746fa0914ef20916ec9006492f2043ed9d35fc65b74995e1cab903837890148`。
- 本地 recovery bundle 已生成：`artifacts/frozen_backups/SETUP_03_DEVELOPMENT_HOLDOUT_2026-08-29_v1_FROZEN_BACKUP.zip`，3,086,881 bytes，ZIP SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；bundle 含 5 个文件，成员 hash 见 registry/recovery manifest。
- 外部 ChatGPT 审计已将 exact ZIP bytes 上传 Google Drive `交易系统/Frozen Artifacts/stock-data-pipeline/2026-08-29-v1/`，file ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS`；独立重新读取后的 recovered ZIP SHA-256 与上传前完全一致。该 session 不重复访问 Google Drive。
- 本次治理初始化与本轮 cloud recovery correction：新增/更新治理文件与 governance test；不改变业务逻辑和 frozen artifact bytes。治理修正 commit 使用 `THIS_COMMIT`，实际 SHA 以 Git 为准。
- Phase 5J-v4 exact Sol specification 已落为 machine-readable protocol、中文说明、hash-pinned loader 与 protocol regression tests；canonical protocol SHA-256 为 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`。本独立 freeze task 未运行真实 holdout attribution。
- Phase 5J-v4 在 40 symbols / 86,305 bars 上生成 258,915 trace rows、1,031 lifecycles、177 real first-divergence episodes；对 `origin/main@142b7345…` 完成 120 cells / 258,915 Setup bar comparisons / 1,028 terminal-event comparisons，Setup/event mismatches 均为 0。capsule file SHA-256 `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`，deterministic trace SHA-256 `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`；tracked provenance hashes 使用 Git-normalized LF bytes，跨 Windows/Linux 稳定。

## 4. Pending Work

### Required Next

1. 从 PR #32 核对最终 HANDOFF reconciliation tip 的 exact-head CI；成功后不再修改本分支。
2. 停止在 Sol decision node，等待明确结构设计决定；PR 保持 OPEN 且不 merge。

### Deferred

- Sol 对 `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION` 的决定。
- Formal Phase 5K-B1、Final OOS、IBKR readiness 和任何 production parameter/strategy change。

### Prohibited For Now

- provider/data fetch、symbol replacement、dataset regeneration、frozen identity rewrite。
- SETUP_03 / Trading Core / Decision / execution / production Sheets changes。
- Final OOS、formal validation、returns/MFE/MAE/P&L/outcome access。
- 根据收益或信号结果选择/替换标的、参数或 backup 内容。

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

## 7. Frozen Identities And Invariants

- Phase 5J-v3 event-matching protocol: `SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1`, canonical SHA-256 `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`。
- Phase 5J-v4 lifecycle-attribution protocol: `SETUP_03-PHASE5J-V4-LIFECYCLE-ATTRIBUTION-2026-08-29-v1`, canonical SHA-256 `sha256:babece4e00837fd5b47fca6746255982bc362544d4072c5dc7a1b8d17f837cbe`；state `LIFECYCLE_ATTRIBUTION_PROTOCOL_FROZEN_NOT_EXECUTED`。
- Phase 5J-v4 attribution capsule: file SHA-256 `sha256:a779960f1267331788d69c5f087dd7ec8896a90989679d750eb491154e53501f`，canonical payload `sha256:a2e9a48cac483bca6aae9aeec4d5405634118632e7c34170aef863f24991e797`；ignored derived trace SHA-256 `sha256:f27a1fd15b0aa0468140f319b70ef725ace7c0581b3654748e694b3cd44e18b4`。
- Holdout universe: `SETUP_03-DEVELOPMENT-HOLDOUT-CN-US-2026-08-29-v2`, manifest SHA-256 `sha256:aca071eea6e93b8beecf7c2925a86f006e242a031fe32b5f2e33423037d00a65`；symbol-list SHA-256 `sha256:dc81b5b8c96408b0d18a161f946aeaf5ad616060d82cd6b6f8497a5b26bef036`。
- Dataset: `SETUP_03-DEVELOPMENT-HOLDOUT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-29-v1`，canonical manifest SHA-256 `sha256:44f4dcb62eb42829ed643c7aca199334509d55c4e9cb9d059413fc0669d3216f`，normalized aggregate `sha256:b08832bdad7c2a857d7b60fc7b56a75d09594ee648008ab852bde4a8a56405b1`，replay aggregate `sha256:cb4c68eb080ac02d6cf022476abf5b88d6bb0af480b8ce583baca8c6119381e2`。
- Dataset coverage: CN 20 / 41,274 bars；US 20 / 45,031 bars；total 40 symbols / 86,305 bars；provider split is `BAOSTOCK_DEVELOPMENT_QFQ` / `YFINANCE_DEVELOPMENT_HISTORICAL`。
- Backup container: 3,086,881 bytes, SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；Google Drive persistent backup and independent cloud reread are externally verified, current status `FULLY_RECOVERABLE`。
- Recovery manifest records source artifact commit `3a2c6699559074161b56281dd16084264f7dc717` as a historical local-ref-only provenance pin；this is not the current remote `main` SHA and must not be silently rewritten.
- Invariants: no provider fallback/history splice/date fill/synthetic bar/OHLC mutation/result-driven symbol replacement；no future data; `signal(t)` only uses `data <= t`；frozen protocol, manifests, roster, hashes and exact replay bytes cannot be silently changed。

## 8. Known Issues / Blockers

| category | status / impact | workaround | blocks continuation? |
|---|---|---|---|
| artifact/data availability | second-holdout bundle is `FULLY_RECOVERABLE`; Google Drive object ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS` and recovered ZIP SHA-256 are recorded from external audit | do not repeat cloud network verification; use registry identity and existing loader evidence | No |
| environment / verification | PR #32 run `33259097880` 已覆盖 `a71640291e…` 并成功；最终 HANDOFF reconciliation tip 仍须在 push 后核对自己的 exact-head CI | 从 PR #32 读取匹配最终 `headRefOid` 的 run；不得用 predecessor run 替代 | Blocks final PR readiness until exact-head success |
| research/design blocker | `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION` | wait for explicit Sol decision; preserve current evidence | Yes for parameter/strategy changes; descriptive v4 attribution remains bounded by the frozen contract |
| protocol persistence | Earlier v4 design had not been persisted; this was `PHASE5J_V4_PROTOCOL_NOT_YET_PERSISTED`, `NOT_AN_ARTIFACT_LOSS_EVENT` | exact Sol specification is now version/hash frozen; attribution may begin only after the freeze commit | No after freeze commit |
| Sol decision node | `PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION`; mixed boundary roots plus terminal-index cascade | create PR, verify exact-head CI, then stop without implementing redesign | Yes after PR readiness |
| project coordination | PR #31 is an independent OPEN hotfix；当前研究 PR 为 #32 | do not mix worktrees or infer PR #32 status from PR #31 | No, if kept separate |
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

1. `git status --short --branch`，若并行 `.hotfix-worktree/` 重新出现则保持隔离，确认没有未授权删除/覆盖。
2. `git fetch origin main`，确认 GitHub `main@142b7345…` 与本地 ref，并重算 current branch/base 关系。
3. 运行完整验证并提交 Phase 5J-v4 implementation/evidence/governance commit。
4. push `research/phase5j-v4-lifecycle-attribution`，创建新 PR，不 merge。
5. 等待 exact-head CI success；随后报告 `PHASE_5J_V4_CAUSAL_ATTRIBUTION_READY_FOR_SOL_DECISION` 并停止，不启动 redesign、Final OOS 或 Phase 5K-B1。

## 11. Handoff Checklist

- [x] Current Objective 已更新
- [x] main / branch / HEAD / PR / CI 已更新
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

- `last_updated_at`: `2026-08-29T20:54:56+08:00`
- `verified_main_sha`: `142b7345a5640b1e87932e41f3dc9311172bf54c`
- `verified_branch_head`: `THIS_COMMIT`（以 `git rev-parse HEAD` 解析最终 reconciliation commit；治理前 working HEAD 为 `5891a2df62e2d3e4623b93b1c4f368e53b4d47ba`）
- `latest_test_result`: Phase 5J-v4 focused `24/24`、full unittest `312/312`、compileall、protocol/registry/capsule JSON、artifact hash manifest、deterministic repeat 与 `git diff --check` passed
- `latest_ci_run`: `33232320454` on remote main success；current local tip has no exact-head CI
- `updated_by_task`: `research: attribute Phase 5J-v4 lifecycle divergence`

`HANDOFF_CURRENT_AND_CONSISTENT`

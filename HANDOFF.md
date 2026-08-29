# CURRENT OPERATIONAL HANDOFF SNAPSHOT

> 本文件是下一台设备 / 下一次开发会话的可执行交接快照，不是完整历史流水账。新会话第一步读取本文件，然后读取 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`，再核对真实 Git / PR / CI / artifact 状态。

## 1. Current Objective

- **当前 Phase / task:** `Phase 5J-v4 — SINGLE_FROZEN_DATASET_CAUSAL_ATTRIBUTION_WITH_HISTORICAL_SYMPTOM_CONCORDANCE`，继续使用已冻结的第二套 development holdout。其 persistent backup/recovery prerequisite 已由外部审计完成并登记。
- **具体目标:** 读取并核对 Phase 5J-v4 的冻结 protocol、现有实现与测试，在 exact hash-pinned second holdout 上完成既定 descriptive/causal attribution 与 historical symptom concordance evidence；不把 development evidence 解释为 production decision。当前因仓库内未找到 v4 protocol/source/tests，执行尚未开始。
- **为什么现在做:** correctness-critical raw/normalized/replay payload 虽位于被 Git 忽略的 `artifacts/`，但 exact ZIP 已上传 Google Drive，并由外部审计独立重新读取且 SHA-256 一致，跨设备恢复 gate 已满足。
- **Scope:** 仅使用现有 frozen protocol、second-holdout bundle、tracked provenance 与既有 research contracts；更新 v4 research evidence、registry/status/handoff/decision records，并为最终 review 准备 PR。
- **明确禁止事项:** 不访问 provider；不重新获取或重生成 bars；不修改 frozen manifests、protocol、symbol roster、既有 capsule 或既有 canonical hashes；不访问 Final OOS；不读取 returns/MFE/MAE/P&L/winrate/expectancy；不修改 production、Trading Core、Decision、execution 或 Google Sheets；不把近似重生成文件当作原 frozen artifact。
- **完成条件:** Phase 5J-v4 frozen workflow 产生可审计的 machine-readable/report evidence，保留 causal/as-of/identity/invariant checks，测试与静态检查通过，治理记录与实际 Git/PR/CI/artifact 状态一致，并创建 PR（不 merge）。
- **停止条件:** 发现 v4 protocol/implementation/evidence 缺失或冲突；任何 hash、binding、count、chronology 或 causal check 失败；遇到需要改变 frozen input、provider/data access、production rule、Final OOS 或重大研究解释的决策；或真实 Git/PR/CI 状态无法核对。

## 2. Current Repository State

- **repository:** `EFSing/stock-data-pipeline`
- **default/main branch:** `main`
- **main/base SHA:** GitHub remote `main@142b7345a5640b1e87932e41f3dc9311172bf54c`；本地 `origin/main` 已通过 `git fetch origin main` 刷新到同一 SHA。
- **working branch:** `research/phase5j-v4-lifecycle-attribution`（仅本地）
- **current HEAD:** `THIS_COMMIT`（治理 commits 已重放到刷新后的 `origin/main`；cloud-recovery correction 的当前重放 commit 为 `92a33940133485d9cd04228b2488cd3c40bb75b1`；以 `git rev-parse HEAD` 解析最终 tip）。
- **PR:** `NONE` for current branch. Predecessor PR #30 was merged with merge commit `142b7345a5640b1e87932e41f3dc9311172bf54c`.
- **latest exact-head CI:** `NONE` for current local tip `92a33940133485d9cd04228b2488cd3c40bb75b1` because the branch has not been pushed; predecessor run `33193832124` covered old head `5891a2df62e2d3e4623b93b1c4f368e53b4d47ba` and was `success`。
- **latest remote main CI:** run `33195350848`, head `142b7345a5640b1e87932e41f3dc9311172bf54c`, `success`。
- **另一个并行项目 PR:** #31 `hotfix/production-market-data-stability` is `OPEN`, head `bb006ae5ca61e76192c751e9bd818584fc42f051`, exact-head CI run `33248386042` success；它不属于当前 checkout。
- **working tree expected state:** tracked files 应只包含本任务的 governance changes；ignored `artifacts/` 保持 ignored；初始检查时观察到的未追踪 `.hotfix-worktree/` 在 post-commit 检查时已不再存在，本任务未执行删除且未纳入 commit；若并行 worktree 重新出现，必须保持隔离。
- **current project/phase status:** V0.2 production pipeline 已运行；Phase 5J-v3 holdout 已合并但结构资格结果需要 Sol 决策；second-holdout backup 已由外部审计验证为 `FULLY_RECOVERABLE`；用户已授权继续 Phase 5J-v4，但仓库中未找到其 frozen protocol/source/tests，当前执行被 `PHASE5J_V4_PROTOCOL_NOT_PRESENT` 阻塞；formal validation、Final OOS、Phase 5K-B1 仍未执行。

## 3. Completed Work

- Phase 5J-v3 protocol、independent universe、holdout dataset、structure-only replay/parity 与 qualification 已完成并由 PR #30 合并；exact identities 见第 7 节和 `docs/CURRENT_STATUS.md`。
- loader 已修复 dataset → replay wrapper 的 provisional-hash cross-binding 顺序问题；现有 frozen identities 与研究结果不变，tracked wrapper integrity 为 `sha256:6746fa0914ef20916ec9006492f2043ed9d35fc65b74995e1cab903837890148`。
- 本地 recovery bundle 已生成：`artifacts/frozen_backups/SETUP_03_DEVELOPMENT_HOLDOUT_2026-08-29_v1_FROZEN_BACKUP.zip`，3,086,881 bytes，ZIP SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；bundle 含 5 个文件，成员 hash 见 registry/recovery manifest。
- 外部 ChatGPT 审计已将 exact ZIP bytes 上传 Google Drive `交易系统/Frozen Artifacts/stock-data-pipeline/2026-08-29-v1/`，file ID `119X2DoBlA_vqSzt62GfTi3ZDiCktVBvS`；独立重新读取后的 recovered ZIP SHA-256 与上传前完全一致。该 session 不重复访问 Google Drive。
- 本次治理初始化与本轮 cloud recovery correction：新增/更新治理文件与 governance test；不改变业务逻辑和 frozen artifact bytes。治理修正 commit 使用 `THIS_COMMIT`，实际 SHA 以 Git 为准。

## 4. Pending Work

### Required Next

1. 读取并核对 Phase 5J-v4 protocol、现有 research implementation 与 tests，确认 scope、输入、输出与禁止的 outcome access。
2. 使用 registry 中已验证的 exact second-holdout identity，运行既定 Phase 5J-v4 causal attribution / historical symptom concordance workflow；不得重新抓取或重生成输入。
3. 保存 machine-readable evidence/report、运行 loader/cross-binding/chronology/causal checks 与完整测试，检查是否触发 Sol/研究决策 blocker。
4. 更新 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`、`HANDOFF.md` 与必要 registry provenance，再核对真实 Git/PR/CI/artifact。
5. 完成 PR-ready 检查后创建 PR；不 merge，不扩大到 Final OOS、provider、production 或 Phase 5K-B1。

### Deferred

- Phase 5J-v4 lifecycle attribution：用户已确认正式任务名为 `SINGLE_FROZEN_DATASET_CAUSAL_ATTRIBUTION_WITH_HISTORICAL_SYMPTOM_CONCORDANCE`，但当前 checkout、所有 refs、reflog/unreachable commits、已有 artifacts 和原始任务附件均未找到对应 protocol/source/tests；未自行补造规则。
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

## 7. Frozen Identities And Invariants

- Phase 5J-v3 event-matching protocol: `SETUP_03-PHASE5J-V3-EVENT-MATCHING-2026-08-28-v1`, canonical SHA-256 `sha256:84c85e3abe24745022dd8040330e92e9d97736a05b249972a2203d4a9a4fe816`。
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
| environment / verification | local `origin/main` 已刷新为 GitHub remote main `142b734…`；current branch 已重放到该基线，但 current tip 尚无 exact-head CI | push 后等待匹配 `headSha` 的 CI；在此之前不声称 current PR-ready | Blocks PR readiness, not blocker documentation |
| research/design blocker | `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION` | wait for explicit Sol decision; preserve current evidence | Yes for parameter/strategy changes; descriptive v4 attribution remains bounded by the frozen contract |
| unresolved ambiguity | `PHASE5J_V4_PROTOCOL_NOT_PRESENT`; only the phase name is available, with no repository-verifiable protocol/source/tests | provide or restore the exact frozen v4 protocol/implementation/test location or commit; do not invent causal/symptom rules | Yes, blocks v4 execution and PR readiness |
| project coordination | PR #31 is an independent OPEN hotfix; current branch has PR `NONE` | do not mix worktrees or infer current branch status from PR #31 | No, if kept separate |
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
3. 定位并读取 `SINGLE_FROZEN_DATASET_CAUSAL_ATTRIBUTION_WITH_HISTORICAL_SYMPTOM_CONCORDANCE` 的 exact frozen protocol、source 和 tests；当前仓库核对未找到，不能自行设计替代物，也不重复访问 Google Drive。
4. 只有 protocol/source/tests 可核对后，才使用 registry 中的 exact second-holdout identity 执行 v4，并保持 as-of、causal、frozen-input、descriptive-only 与 outcome-access 边界。
5. protocol blocker 解除且 v4 evidence 完成后，再更新治理与研究 evidence、核对 PR/CI/artifact，创建 PR 后停止，不 merge。

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

- `last_updated_at`: `2026-08-29T19:30:00+08:00`
- `verified_main_sha`: `142b7345a5640b1e87932e41f3dc9311172bf54c`
- `verified_branch_head`: `THIS_COMMIT`（以 `git rev-parse HEAD` 解析最终 reconciliation commit；治理前 working HEAD 为 `5891a2df62e2d3e4623b93b1c4f368e53b4d47ba`）
- `latest_test_result`: governance、full unittest、compileall、registry JSON、hash 与 `git diff --check` 已在 cloud-recovery correction 后通过；本次 protocol blocker 记录后的文档变更待做最终验证
- `latest_ci_run`: `33195350848` on remote main success；current checkout exact-head `33193832124` success
- `updated_by_task`: `docs: record Phase 5J-v4 protocol blocker`

`HANDOFF_CURRENT_AND_CONSISTENT`

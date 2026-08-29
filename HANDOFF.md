# CURRENT OPERATIONAL HANDOFF SNAPSHOT

> 本文件是下一台设备 / 下一次开发会话的可执行交接快照，不是完整历史流水账。新会话第一步读取本文件，然后读取 `docs/CURRENT_STATUS.md`、`docs/DECISION_LOG.md`，再核对真实 Git / PR / CI / artifact 状态。

## 1. Current Objective

- **当前 Phase / task:** `FROZEN_ARTIFACT_BACKUP_STAGING`，针对 Phase 5J-v3 第二套 development holdout 的 persistent backup 与 recovery verification。当前 checkout 分支名称为 `research/phase5j-v4-lifecycle-attribution`，但 Phase 5J-v4 尚未运行，正式 objective / protocol 为 `UNKNOWN / NEEDS_VERIFICATION`。
- **具体目标:** 把已完成本地 hash 验证的 frozen holdout backup 上传到已批准的 persistent storage；记录不可变 URI / object ID、bytes 与 SHA-256；在全新目录恢复并重新运行现有 loader/cross-binding 校验。
- **为什么现在做:** correctness-critical raw/normalized/replay payload 位于被 Git 忽略的 `artifacts/`，tracked manifests 只能证明身份，不能单独恢复 exact replay input。当前 ZIP 只有本地 staging，跨设备仍不可恢复。
- **Scope:** 仅处理现有 frozen holdout bundle 的持久化、完整性和恢复证据；更新 registry、CURRENT_STATUS、HANDOFF 与必要的决策记录。
- **明确禁止事项:** 不访问 provider；不重新获取或重生成 bars；不修改 frozen manifests、protocol、symbol roster 或既有 capsule；不运行 SETUP_03、Phase 5J-v4、Final OOS 或 Phase 5K-B1；不读取 returns/MFE/MAE/P&L/winrate/expectancy；不修改 production、Trading Core、Decision、execution 或 Google Sheets；不把近似重生成文件当作原 frozen artifact。
- **完成条件:** approved persistent storage 中存在该 ZIP；下载/恢复后的 bytes、成员 hashes、loader cross-bindings、symbol count `40` 和 bar count `86,305` 全部匹配；registry 状态更新为 `LOCAL_PRESENT + HASH_VERIFIED + PERSISTENT_BACKUP_PRESENT + RECOVERY_VERIFIED`，再决定是否可标记 `FULLY_RECOVERABLE`。
- **停止条件:** 没有明确的 approved storage destination / credential；任何 hash、member、binding、count 或 recovery 校验失败；发现治理文档与客观 Git/PR/CI/artifact 证据冲突；或需要开始 Phase 5J-v4、SETUP_03、OOS、provider/data access 时，停止并报告，不自行扩大授权。

## 2. Current Repository State

- **repository:** `EFSing/stock-data-pipeline`
- **default/main branch:** `main`
- **main/base SHA:** GitHub remote `main@142b7345a5640b1e87932e41f3dc9311172bf54c`；本地 `origin/main@3a2c6699559074161b56281dd16084264f7dc717` 过旧，必须先 `git fetch origin main`。
- **working branch:** `research/phase5j-v4-lifecycle-attribution`（仅本地）
- **current HEAD:** `5891a2df62e2d3e4623b93b1c4f368e53b4d47ba`；治理初始化提交完成后以 `git rev-parse HEAD` 为准。
- **PR:** `NONE` for current branch. Predecessor PR #30 was merged with merge commit `142b7345a5640b1e87932e41f3dc9311172bf54c`.
- **latest exact-head CI:** run `33193832124`, workflow `CI Test Gate`, head `5891a2df62e2d3e4623b93b1c4f368e53b4d47ba`, `success`。
- **latest remote main CI:** run `33195350848`, head `142b7345a5640b1e87932e41f3dc9311172bf54c`, `success`。
- **另一个并行项目 PR:** #31 `hotfix/production-market-data-stability` is `OPEN`, head `bb006ae5ca61e76192c751e9bd818584fc42f051`, exact-head CI run `33248386042` success；它不属于当前 checkout。
- **working tree expected state:** 治理提交后 tracked files 应只包含本任务的 governance changes；ignored `artifacts/` 保持 ignored；未追踪 `.hotfix-worktree/` 是并行 hotfix worktree，本任务必须保留且不得纳入 commit。
- **current project/phase status:** V0.2 production pipeline 已运行；Phase 5J-v3 holdout 已合并但结构资格结果需要 Sol 决策；当前 backup staged 但未持久化；Phase 5J-v4、formal validation、Final OOS、Phase 5K-B1 均未执行。

## 3. Completed Work

- Phase 5J-v3 protocol、independent universe、holdout dataset、structure-only replay/parity 与 qualification 已完成并由 PR #30 合并；exact identities 见第 7 节和 `docs/CURRENT_STATUS.md`。
- loader 已修复 dataset → replay wrapper 的 provisional-hash cross-binding 顺序问题；现有 frozen identities 与研究结果不变，tracked wrapper integrity 为 `sha256:6746fa0914ef20916ec9006492f2043ed9d35fc65b74995e1cab903837890148`。
- 本地 recovery bundle 已生成：`artifacts/frozen_backups/SETUP_03_DEVELOPMENT_HOLDOUT_2026-08-29_v1_FROZEN_BACKUP.zip`，3,086,881 bytes，ZIP SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；bundle 含 5 个文件，成员 hash 见 registry/recovery manifest。
- 本次治理初始化：新增 `HANDOFF.md`、artifact policy/registry，更新 `AGENTS.md`、`README.md`、`docs/CURRENT_STATUS.md` 与 `docs/DECISION_LOG.md`；不改变业务逻辑和 frozen artifact bytes。治理 commit 为本文件所在的 `THIS_COMMIT`，实际 SHA 以 Git 为准。

## 4. Pending Work

### Required Next

1. 先确认 approved persistent storage destination、object identity 和访问方式；没有明确目标时保持 blocker。
2. 上传 ZIP，并保存 detached SHA-256 / size / upload timestamp / immutable object identity。
3. 在全新目录恢复 ZIP，独立计算 archive/member hashes，运行既有 holdout loader 验证 cross-binding、40 symbols、86,305 bars，并记录 recovery evidence。
4. 更新 `docs/FROZEN_ARTIFACT_REGISTRY.json`、`docs/CURRENT_STATUS.md`、`HANDOFF.md`，再重新核对 Git/PR/CI。

### Deferred

- Phase 5J-v4 lifecycle attribution：当前仅由 branch name 暗示，正式 protocol/objective 未核实。
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
- Backup container: 3,086,881 bytes, SHA-256 `sha256:4f7de4a64bd6b020cd1b93a8bcc392db8d19b69a3b430b85b14b8e548e13f599`；current status is staged local only, not persistent/recovery verified。
- Recovery manifest records source artifact commit `3a2c6699559074161b56281dd16084264f7dc717` as a historical local-ref-only provenance pin；this is not the current remote `main` SHA and must not be silently rewritten.
- Invariants: no provider fallback/history splice/date fill/synthetic bar/OHLC mutation/result-driven symbol replacement；no future data; `signal(t)` only uses `data <= t`；frozen protocol, manifests, roster, hashes and exact replay bytes cannot be silently changed。

## 8. Known Issues / Blockers

| category | status / impact | workaround | blocks continuation? |
|---|---|---|---|
| artifact/data availability | `FROZEN_ARTIFACT_BACKUP_STAGED_CLOUD_UPLOAD_REQUIRED`; raw/normalized/replay payload is ignored local data | upload to approved persistent storage, then independently restore and verify | Yes, blocks Phase 5J-v4 continuation |
| environment / verification | local `origin/main` is stale at `3a2c669…`; GitHub remote main is `142b734…` | `git fetch origin main`, then re-check exact ref and merge-base | Blocks trustworthy base/PR comparison, not documentation-only work |
| research/design blocker | `SETUP_03_STRUCTURAL_STABILITY_FAILURE_REQUIRES_SOL_DECISION` | wait for explicit Sol decision; preserve current evidence | Yes for parameter/strategy changes |
| project coordination | PR #31 is an independent OPEN hotfix; current branch has PR `NONE` | do not mix worktrees or infer current branch status from PR #31 | No, if kept separate |
| environment | untracked `.hotfix-worktree/` exists in this checkout | preserve and exclude from governance commit | No |

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

**What happened:** branch 名称暗示 Phase 5J-v4，但当前 evidence 只证明 v3 holdout 与 backup staging，v4 尚未运行。

**Root cause:** branch naming 被误当作正式 objective/protocol。

**Consequence:** 可能在 prerequisite backup 或 Sol decision 前启动未授权研究。

**Permanent prevention rule:** branch name 只能作为线索；正式任务必须由 HANDOFF/CURRENT_STATUS、protocol、PR/commit 和客观 artifact evidence 共同确认。

## 10. Next Action

1. `git status --short --branch`，保留 `.hotfix-worktree/`，确认没有未授权删除/覆盖。
2. `git fetch origin main`，确认 GitHub `main@142b7345…` 与本地 ref，并重算 current branch/base 关系。
3. 确认 approved persistent storage；若没有明确目的地或凭证，停止并保持 `FROZEN_ARTIFACT_BACKUP_STAGED_CLOUD_UPLOAD_REQUIRED`。
4. 上传 ZIP，记录不可变对象身份、bytes、SHA-256；在 clean directory 恢复并运行既有 loader/cross-binding/count checks。
5. 更新 registry、CURRENT_STATUS、HANDOFF 并重新核对 PR/CI；只有完成上述 prerequisite 且取得明确授权后，才讨论 Phase 5J-v4，否则停在 blocker/Sol decision。

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

- `last_updated_at`: `2026-08-29T19:05:21+08:00`
- `verified_main_sha`: `142b7345a5640b1e87932e41f3dc9311172bf54c`
- `verified_branch_head`: `THIS_COMMIT`（以 `git rev-parse HEAD` 解析本文件所在治理提交；初始化前 working HEAD 为 `5891a2df62e2d3e4623b93b1c4f368e53b4d47ba`）
- `latest_test_result`: governance test `4/4` passed；full `python -m unittest discover -s tests -v` `288/288` passed；registry JSON valid；`git diff --check` passed
- `latest_ci_run`: `33195350848` on remote main success；current checkout exact-head `33193832124` success
- `updated_by_task`: `chore: establish project handoff governance`

`HANDOFF_CURRENT_AND_CONSISTENT`

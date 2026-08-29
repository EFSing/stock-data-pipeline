# FROZEN_ARTIFACT_POLICY.md — frozen / important artifact recovery governance

## Purpose

本项目会产生 replay input、raw/normalized bars、manifest、benchmark witness、validation evidence 和其他可能影响 correctness 的文件。Git 只保存其中一部分；凡是没有进入 Git 的重要 bytes，必须能够在新设备上按 hash 恢复，不能依赖某台电脑、临时 CI artifact 或聊天记录。

机器可读登记表为 [`FROZEN_ARTIFACT_REGISTRY.json`](FROZEN_ARTIFACT_REGISTRY.json)。本文件定义状态、登记字段、恢复流程和禁止事项。

## Required status gates

每个 correctness-critical artifact 或 bundle 都必须分别记录以下四项，不得用一个模糊的“已备份”替代：

- `LOCAL_PRESENT`: 当前 checkout 中存在目标 bytes。
- `HASH_VERIFIED`: 按登记算法重新计算，bytes / members / canonical identity 与 registry 一致。
- `PERSISTENT_BACKUP_PRESENT`: approved persistent storage 中存在可定位的 immutable object，且记录 URI / object ID、size、hash 和 retention 信息。
- `RECOVERY_VERIFIED`: 从 persistent object 在全新目录恢复后，再次验证 bytes、members、manifests、cross-bindings 和必要的 loader/count checks。

只有四项全部为 `true`，bundle 才能标记 `FULLY_RECOVERABLE`。`LOCAL_PRESENT` 或 Git-tracked manifest 不等于 persistent backup；ZIP 在本地生成也不等于 recovery verified。

## Registry contract

每项登记至少包含：

- stable `artifact_id`、`artifact_type`、purpose、lifecycle/status 和 `development_only` / `formal_validation` / `final_oos` labels；
- repository-relative tracked paths、local payload paths、bundle path（如有）；
- exact file/member SHA-256、byte counts、canonical manifest/dataset/replay/universe identities；
- producer commit/ref 和 provider/source identity；
- 四项 recovery gates、persistent location/identity、last verification time、verification method；
- immutable invariants、prohibited mutations、dependencies and recovery notes。

Hash 语义必须区分：

1. canonical content hash（由 artifact protocol 定义）；
2. exact file bytes SHA-256；
3. aggregate/replay identity；
4. transport container/member hash。

不得把一种 hash 冒充另一种 hash。自包含 recovery manifest 不得把自己未经定义的循环 hash 当作已验证；可采用 detached hash 或由 archive/member verification 证明。

## Lifecycle procedure

1. 生成或收到重要 artifact 后，先以 opaque bytes 保存，再计算 exact hash；同时登记 source commit、protocol/config/version、provider/API identity 和 schema。
2. 写入 registry 前运行现有 loader/QC/cross-binding checks；失败则保留诊断并标记 `UNRESOLVED`，不修补 bytes 以“通过”。
3. 创建 persistent backup 时保留 immutable object identity、bytes、SHA-256、上传时间和 retention/ownership 信息；禁止只记录本机路径。
4. 在与原目录分离的新目录恢复；重新计算 archive/member hashes，并执行 artifact-specific loader、schema、manifest binding、数量和版本检查。
5. 只有恢复成功后才更新 registry 的 `RECOVERY_VERIFIED` 与 `FULLY_RECOVERABLE`；同步更新 `HANDOFF.md`、`CURRENT_STATUS.md`，必要时追加 `DECISION_LOG.md`。
6. artifact bytes、source、protocol、roster 或 semantics 变化时，保留旧登记并创建新 version/hash；禁止覆盖旧 frozen identity。

## Cross-device handoff rule

新设备首先读取 `HANDOFF.md` 和 registry，再按 registry 的 persistent identity 恢复。若对象不存在、下载不完整、hash 不匹配、loader 不能验证或恢复方法没有独立证据，状态必须保持 `LOCAL_ONLY` / `STAGED_LOCAL_ONLY` / `PARTIAL_UNVERIFIED` 之一，并停止依赖该 artifact 的工作。

## Prohibited

- 用同一逻辑重新抓取或重新生成的“差不多”文件替代 frozen bytes。
- 以 manifest、report、Git commit 或短期 CI retention 单独声称原始 payload 可恢复。
- 在看到 signal、return、MFE/MAE、P&L 或参数结果后改 roster、provider、日期、数据清洗或 artifact 内容。
- 为方便跨设备而静默压缩、重编码、排序、标准化或修改 opaque payload；如格式转换是协议的一部分，必须生成新 version 并保存原 bytes。
- 把 API key、token、service account 或其他凭证写入 registry、handoff、report、代码或配置。

## Current registry boundary

本次初始化优先登记当前 Phase 5J-v3 holdout 及其 active backup staging，因为它是下一步工作的 correctness-critical prerequisite。历史 `artifacts/phase5e_*`、`phase5f-*`、`phase5g-*`、`phase5h-*`、`phase5i-*` 等 ignored directories 未被声明为 fully recoverable；在未来需要复用它们前，必须先单独登记并完成本 policy 的四项 gate。

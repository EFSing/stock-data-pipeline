# SETUP_01 D1 VPS Durable Storage Contract

状态：`D1_READY_NOT_ACTIVE`（CN/US 均未 activation；正式 session 数 = 0）

backend identity：`SETUP01_D1_VPS_SSH_DURABLE_STORAGE`

backend version：`VPS_D1_DURABLE_BACKEND_V1`

remote helper：`D1_VPS_STORE_HELPER_V1`，`research/d1_vps_store_helper.py`

该文件只描述 durable storage、SSH 安全与迁移合同。D1 研究协议、signal/stop/target/exit/gate
语义仍以 `SETUP01_D1_PROSPECTIVE_PROTOCOL_V1.md` 与冻结 protocol JSON 为唯一事实源。

## 角色边界

```text
Market/Public Data
        ↓
GitHub Actions（全部计算：Candidate / source contract / Path A-B observer）
        ↓
canonical D1 session evidence
        ↓
SSH encrypted transport
        ↓
Ubuntu VPS（immutable store）
```

VPS 不主动抓行情、不运行完整 stock-data-pipeline，也不读取 holdings、account、Paper、
production Sheet/state、broker 或 Final OOS。它只负责 immutable object storage、activation
record、session pointer、SHA 校验、verify/recovery/export/migrate 与磁盘健康。GitHub Actions
继续做全部计算；D1 storage failure 不能改变生产日报路径。

## Remote directory contract

```text
/srv/d1-research/
    objects/<sha256>.json                     # content-addressed formal session object
    sessions/CN/YYYY-MM-DD.json               # 唯一 session pointer
    sessions/US/YYYY-MM-DD.json
    system/activation/CN.json                 # 不可变 per-market activation record
    system/activation/US.json
    system/validation/*.json                  # synthetic，不是 D1 evidence
    system/d1_vps_store_helper.py             # repository-owned helper（root:root 0644）
    system/tmp/*.part                         # 传输中临时文件，从不成为 evidence
    manifests/store-manifest-v1.json          # derived index，可重建，不是 evidence
```

`D1_VPS_STORAGE_ROOT` 默认 `/srv/d1-research`，必须是绝对 POSIX 路径并把 realpath 冻结为
storage identity 的一部分：

```text
storage_identity_sha256 = SHA256(canonical_json({
  schema_version: "setup01-d1-vps-storage-identity-v1",
  backend_identity, backend_version, storage_root }))
```

storage identity 绑定的是磁盘位置而不是网络端点：更换主机但保持同一 frozen storage root 的
迁移仍是同一个 store；改变 storage root 则 activation record 不再授权该 store 写入，必须
由用户单独决定，不得静默继续。IP / port / user 属于 SSH transport，由 host key pin 与
GitHub Secrets 冻结。

正式 object 与 pointer 只在 `objects/`、`sessions/`、`system/activation/` 内创建；同一
identity 不允许 update，也没有 delete API。`manifests/` 是唯一允许替换的 prefix，因为它只
保存可重建的 derived index（`evidence_role: DERIVED_INDEX_NOT_FORMAL_SESSION_EVIDENCE`）。

## 一次性服务器初始化

`scripts/setup01_d1_vps_bootstrap.sh` 由用户在 VPS 上以 root 执行一次：

```bash
sudo D1_VPS_PUBLIC_KEY="ssh-ed25519 AAAA... d1-github-actions" \
     bash scripts/setup01_d1_vps_bootstrap.sh
```

它创建专用非 root 账户（默认 `d1store`，无 sudo）、冻结目录布局、安装 root-owned helper，
并打印 host key fingerprint 与 storage identity。它不改动 nginx、数据库、容器、代理或其他
用户服务，脚本本身幂等。helper 只由该账户读取；运行期账户对该目录以外没有额外权限。

## SSH / security contract

运行期身份与 GitHub Secrets / Variables：

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `D1_VPS_HOST` | Secret | 冻结的 hostname / IP |
| `D1_VPS_PORT` | Variable | SSH port（默认 22） |
| `D1_VPS_USER` | Variable | 专用非 root 账户（默认 `d1store`） |
| `D1_VPS_STORAGE_ROOT` | Variable | 冻结的 storage root（默认 `/srv/d1-research`） |
| `D1_VPS_SSH_PRIVATE_KEY` | Secret | 只 writable-by-owner 的临时文件，从不写入 repo/artifact/log/receipt |
| `D1_VPS_KNOWN_HOSTS` | Secret | 冻结的 host key entry |
| `D1_VPS_HOST_KEY_FINGERPRINT` | Secret | 冻结的 `SHA256:...` fingerprint |
| `D1_VPS_MIN_FREE_BYTES` | Variable | 低空间安全阈值（默认 1 GiB） |
| `D1_VPS_DANGER_FREE_BYTES` | Variable | 危险阈值，达到即 fail closed（默认 256 MiB） |

固定要求：

- 只使用 public key authentication；禁止 root 登录、禁止 password/agent 回退
  （`BatchMode=yes`、`PasswordAuthentication=no`、`PreferredAuthentications=publickey`、
  `IdentitiesOnly=yes`）；
- `StrictHostKeyChecking=yes` + 冻结的 `UserKnownHostsFile` + `UpdateHostKeys=no`；
  `StrictHostKeyChecking=no` 在任何路径都不允许出现；
- 每次连接前在本地重新校验 known_hosts entry 与冻结 fingerprint 一致，缺失或不匹配即
  fail closed，不建立连接；
- helper 强制路径 containment：拒绝绝对路径、`..`、反斜杠、`system/tmp/` 与逃逸出
  storage root 的 symlink parent。

## 写入与 read-back 合同

每次 formal 写入必须完成：

1. Actions 端计算 canonical bytes 的 SHA-256；
2. SSH 上传并流式写入 `system/tmp/<uuid>.part`，flush + fsync；
3. 校验收到的字节数与 SHA-256；不匹配或传输中断 → 删除临时文件并 fail closed；
4. 用 `link` 原子 create-only 落到最终路径；已存在时比较 bytes：一致 →
   `IDEMPOTENT_REPLAY`，不一致 → `D1_CREATE_ONLY_CONFLICT`；
5. fsync 目标目录；
6. helper 对落盘文件重算 SHA-256 并返回结构化 receipt；
7. pointer 写入后用 pointer 读回整段 session object，校验 object bytes hash、
   pointer/object cross-bind、component/event hash；
8. 只有以上全部通过，session 才可标记 `COMMITTED`。

receipt 至少包含 backend identity/version、object identity、SHA-256、market、session、
remote path identity、commit status、protocol version；不包含 private key、token 或任何
环境变量。SSH exit 0 本身不构成 durable commit 证据。

## 磁盘空间策略

10 GB system disk 先投入使用，activation 不以“12 个月一定够用”为前置条件。每次 collector
前都会读取并报告 total / used / free / store bytes / object count / session count；helper 在
free < danger 阈值时拒绝任何新写入（`D1_STORAGE_LOW_SPACE_FAIL_CLOSED`），free < 安全阈值时
标记 `D1_STORAGE_LOW_SPACE` 但继续。系统绝不自动删除旧 session、content object、activation
或为腾空间改写 evidence；容量不足时由用户决定迁移到更大 VPS 或导出到本地。

## 验证、导出与迁移

```bash
python scripts/run_setup01_d1_collector.py vps-identity
python scripts/run_setup01_d1_collector.py vps-status
python scripts/run_setup01_d1_collector.py vps-verify [--full-objects]
python scripts/run_setup01_d1_collector.py vps-export --target EMPTY_DIRECTORY
python scripts/run_setup01_d1_collector.py vps-recover --target EMPTY_DIRECTORY
python scripts/run_setup01_d1_collector.py vps-migrate --from EXPORTED_DIRECTORY
```

- `vps-verify` 校验 pointer、object 存在性与大小、CN/US session graph、activation record 与
  duplicate/orphan 状态；`--full-objects` 额外对每个 object 重算 SHA-256（不下载字节）。
- `vps-export` 把全部 session、activation record 和 root manifest 写入空目录，并在本地
  重新逐项验证；`vps-recover` 只做 session graph 的 clean-directory 恢复。
- `vps-migrate` 把已验证 export 导入空的（新）store 并做 full verify；旧 VPS → local verified
  export → 新 VPS import → full verify 是官方迁移路径，不依赖旧 VPS 路径之外的隐藏状态。
- root manifest 记录 backend version、activation identities、session counts、referenced
  object hashes 与 `manifest_sha256`；它不能替代正式 session evidence。

## 生命周期风险

VPS 为月租实例，到期日不等于 D1 结束日；用户需要持续续费或在停服前导出/迁移。VPS
deletion/reinstall 属于外部 durability risk，系统不得把它描述为永久存储，也不会代用户购买
续费或修改云主机账户。

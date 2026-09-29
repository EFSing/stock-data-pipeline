# SETUP_01 D1 前瞻时间隔离协议 V1

状态：`D1_ACTIVATION_READY`（CN/US activation record 已建立；正式 session 数 = 0，
首个自然完整 session 通过前不得报告 `D1_COLLECTION_ACTIVE`）

协议身份：`SETUP01_POST_BREAKOUT_D1_PROSPECTIVE_V1`

冻结记录：`SETUP01_POST_BREAKOUT_D1_PROSPECTIVE_FREEZE_V1`

协议 SHA-256：`ee55ec82959be510a8d9a2d84a99143de3638e550f88527536dad9fd5546d0e0`

## 决策与不变边界

D2 因现有免费数据栈不能提供合规的 point-in-time 历史成员、证券生命周期及逐日
CN board/ST/lot/涨跌停信息而暂停。用户批准改用 `D1_PROSPECTIVE_TIME_ISOLATED`。
这是独立的数据协议修订，不覆盖或改写 D2 审计、架构冻结记录，也不把两者称为同一
协议。不得购买数据、建立幸存者历史名单，或在已暴露历史样本上运行新的经济验证。

双路径机制原样保留：`PRICE_ACTION_ONLY`、`ONE_PER_PATH_UNTIL_FILL`、20 个 completed
sessions、`SIGNAL_SUPPORT_ATR_STOP`、X1 primary、X2 preregistered sensitivity、G1
primary、G0 nested attribution。B 日可成为 Path A 信号，Path B 必须等待 B 后真实回踩；
target 只保留 `price > entry_trigger` 的因果候选并 nearest-first 冻结，entry ceiling 不得
过滤较近 T1，实际入场达到或超过 T1 时直接跳过。

## CN / US 独立窗口

每个市场只有在五项 activation gate 全部满足后才写入 `activation_timestamp`。起点是
市场开盘严格晚于 activation timestamp 的首个完整 exchange session；内部身份保留市场
当地 session date，展示时间统一为北京时间。窗口使用半开区间：

```text
[start_session_local_date, start_session_local_date + 12 calendar months)
```

最后一个合格 session 是 end boundary 之前的最后一个 exchange session。窗口不得因表现、
样本量或数据质量延长；样本不足输出 `INSUFFICIENT_EVIDENCE`。CN/US 单独激活、单独计数，
一侧不能替另一侧补证据。当前两侧 activation/start/end 都为 pending；当前安装的 XSHG
calendar 只覆盖到 2026 年末，因此 CN 的未来精确最后 session/北京时间 cutoff 要在日历
可用后解析；XNYS 已覆盖相同未来区间。无论 calendar horizon 如何，冻结的 12 个月日期
边界不变。

启用前历史 K 线、旧日报和事后补抓均不得计为 D1。迟到或缺失写为 `LATE_SOURCE`、
`DATA_MISSING`；diagnostic backfill 的 `prospective_eligible=false`。

## 每日不可变记录与生命周期

`research/setup01_dual_path_observer.py` 复用 causal Swing、Wilder ATR 与 Fibonacci extension
SSOT，生成 H1 birth、Path A/B candidate/touch/signal、next-session model execution、CN T+1、
保守同日 stop-first、退出和右删失事件。所有事件都固定
`formal_entry_allowed=false`、`real_fill_evidence=false`；daily OHLC 只形成模型结果。

`research/setup01_d1_prospective.py` 将以下五个 component 分别 hash，再生成整个 session
event hash：

1. 当日 universe 成员、来源日期、取得时间及可交易属性；
2. raw source identity/payload reference；
3. 标准化 prefix、调整口径、session 与完整性；
4. 正式 Decision 快照和独立 research observation；
5. 中文只读研究报告。

正式幂等键是 `market + session_date + event_id`。reference store 使用 content-addressed
immutable object 加每市场/日期唯一 commit；相同 bytes 重跑为 `IDEMPOTENT_REPLAY`，相同
身份不同 bytes fail closed。verify 检测缺失 session、hash/protocol/component mismatch；
recover 必须复制到空目录并重新逐项验证。退出当日 universe 但生命周期未结束的 symbol
属于 follow-up set，不能因今日名单变化丢弃。

CLI：

```text
python scripts/run_setup01_d1_collector.py collect --input INPUT.json --store STORE --report-output research.md
python scripts/run_setup01_d1_collector.py verify --store STORE
python scripts/run_setup01_d1_collector.py recover --store STORE --target EMPTY_DIRECTORY
python scripts/run_setup01_d1_collector.py vps-identity
python scripts/run_setup01_d1_collector.py vps-status
python scripts/run_setup01_d1_collector.py vps-validate-storage --expected-storage-identity-sha256 SHA256_OF_STORAGE_IDENTITY
python scripts/run_setup01_d1_collector.py vps-create-activation --market CN --activation-timestamp ISO8601 --code-sha MAIN_CODE_SHA
python scripts/run_setup01_d1_natural_collector.py --backend vps --market CN --output receipt.json --report-output research.md
python scripts/run_setup01_d1_collector.py vps-verify
python scripts/run_setup01_d1_collector.py vps-export --target EMPTY_DIRECTORY
python scripts/run_setup01_d1_collector.py vps-recover --target EMPTY_DIRECTORY
python scripts/run_setup01_d1_collector.py vps-migrate --from EXPORTED_DIRECTORY
```

本地文件 store 只用于实现、fixture 与恢复合同验证，不等于获批的 12 个月 durable backend。
`vps-create-activation` 和 natural collector 不接受历史日期补抓；每个市场只能在 storage/source
gate 完成后独立激活，natural collector 只解析当前自然 exchange session。首次完整自然 session
验证通过前，市场保持 `D1_READY_NOT_ACTIVE`；验证通过后才可进入 `D1_COLLECTION_ACTIVE`。
保留的 `gcs-*` / `drive-*` 命令属于被禁用的历史 adapter：正式 D1 backend 是 VPS，误用它们
写 formal evidence 会在运行期 fail closed。

## 成本与执行证据

10bp/side baseline、25bp/side stress 是固定研究滑点/点差情景，不是账户费率或真实报价。
CN 佣金 2.5bp/side 与每单最低 5 CNY 是研究假设；财政部、税务总局公告确认自
2023-08-28 起证券交易印花税减半，协议在激活日记录适用的公开规则。US Section 31 必须
按事件时点官方 advisory 记录；SEC 的 FY2026 advisory 自 2026-04-04 起为 $20.60/million。
FINRA TAF 亦按退出时点的正式 rate 记录，不能沿用过期常量。真实账户费率缺失时继续明确
标记 assumption。

证据：

- CN 印花税：https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm
- SEC FY2026 Section 31：https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2
- FINRA TAF rule filing：https://www.finra.org/sites/default/files/2024-11/sr-finra-2024-019.pdf

CN 每日快照必须保留 board/ST/lot/price-limit/suspension 事实，买入日不得卖出；队列不能
由 OHLC 证明。US halt、spread 与滑点没有报价证据时只能写模型假设。buy-stop 与同日
stop/target 顺序不明要单列 ambiguity，不能标记为真实成交。

## 持久化与 source/activation 验收边界

现有仓库只有 30 天 GitHub Actions artifact；它不满足 12 个月、跨设备恢复和不可变对象
要求。D1 正式 durable backend 是用户自有 Ubuntu VPS 上的
`SETUP01_D1_VPS_SSH_DURABLE_STORAGE` / `VPS_D1_DURABLE_BACKEND_V1`。Drive 与 GCS 路线
仅保留历史实现/测试资产：Drive service-account `files.get` 对配置 folder ID 返回 HTTP 404；
GCS adapter 已实现并合并，但在创建 bucket、activation 或任何 formal D1 evidence 之前被停止。
两者都不是当前 formal backend，误用会在运行期 fail closed；不得扩大 Drive OAuth scope，
也不需要 GCS Secrets 或 Google Billing。

VPS durable backend 的固定合同见
`docs/research/SETUP01_D1_VPS_DURABLE_STORAGE.md`，其要点为：

- GitHub Actions 继续负责全部计算；VPS 只做 immutable storage、activation/pointer 存储、
  SHA 校验、verify/recovery/export 与磁盘健康，不主动抓行情、不运行 pipeline、不读取
  holdings/account/Paper/production Sheet/broker/Final OOS；
- 通过 SSH 公钥运行单一 repository-owned、stdlib-only remote helper，不使用 nginx、数据库、
Docker、Redis、S3 gateway、FTP 或常驻 Web API；create-only 写入（`O_CREAT|O_EXCL`）+
  fsync + 落盘后重算 SHA-256 + read-back；同一 bytes 只能返回 `IDEMPOTENT_REPLAY`，同一
  identity 的不同 bytes、partial/interrupted transfer、missing/corrupt object 一律 fail closed；
- 目录固定为 `objects/`、`sessions/CN/`、`sessions/US/`、`system/activation/`、
  `system/validation/`、`manifests/`；formal evidence 没有 update 或 delete 路径，
  `manifests/` 只保存可重建的 derived index；
- GitHub Actions 必须校验 host key 与冻结 fingerprint，禁止 `StrictHostKeyChecking=no`；
  private key 只经 Secret 注入临时文件，不写入 repo、artifact、log 或 receipt；
- synthetic validation object 的 classification 固定为
  `SYNTHETIC_VALIDATION_OBJECT_NOT_D1_EVIDENCE`，不得计入 formal event；任何 formal session
  都必须绑定不可变 per-market activation record，且 activation 之后不得回填。

### Source / observer contract

正式 natural collector 不读取 holdings-aware Cloud Daily Report，不从普通日报摘要反推证据，
而是独立调用公开 Candidate runtime。每个完整 session 必须保存并 hash-bound：当日 universe
snapshot；raw source identity 与 Stage-A payload/reference；前复权 QFQ exact-T causal prefix；
精确 market/session identity；LOW0、H1、Wave2 Low；causal Swing/Fibonacci；Path A/B observer
input/output；signal、touch、explicit no-signal；entry trigger/ceiling、stop、nearest-first
T1/T2/T3；G1/G0 与 5%/2R diagnostics；`ECONOMIC_ATTRACTIVENESS`；next-session model
execution/skip；open follow-up set；中文只读报告。缺任一 source/QFQ/observer 组件、出现未来行、
session identity 不精确或出现 holdings/account/broker 字段时，snapshot 为 incomplete，不能
formal commit。所有 output 仍固定为 research-only，不代表 formal entry、real fill、Paper、
production Sheet/state 或 broker action；D1 storage failure 不能改变生产日报路径。

真实 write/read-back/clean recovery、完整 source/observer 与不可变 activation record 均已
完成，因此 CN/US 已进入 `D1_ACTIVATION_READY`；每个市场只有在各自首个自然完整 session 通过
source/universe/observer/report/hash/pointer/read-back 验收后才进入 `D1_COLLECTION_ACTIVE`。

## 普通股票绝对收益空间诊断

用户明确拒绝把只能获得 0.x%、1.x%、2.x% 的普通股票机会视为有意义目标，但尚未批准新的
绝对收益硬阈值或退出政策。D1 不改变冻结门槛，仅新增互相独立的只读诊断维度：
`SIGNAL_VALID`、`RISK_VALID`、`TARGET_GEOMETRY`、`ECONOMIC_ATTRACTIVENESS`、
`RESEARCH_ADMISSION`。报告必须先列最近合法 T1 的 gross headroom，再列当时结构可说明的
更远目标及不确定性；不得用 T2/T3 或 Fibonacci 投射绕过 T1。止损距离、1R、R/R 与成本假设
单列，gross 不得称为 net。只有退出与成本证据完整、结果在冻结协议下合法时，才报告 final
net return%、net R、持有期与资金占用。收益区间先完整保留为诊断，不按结果选阈值。

# SETUP_01 D1 前瞻时间隔离协议 V1

状态：`D1_READY_NOT_ACTIVE`

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
```

本地文件 store 只用于实现、fixture 与恢复合同验证，不等于获批的 12 个月 durable backend。

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

## 持久化审计与唯一 blocker

现有仓库只有 30 天 GitHub Actions artifact；它不满足 12 个月、跨设备恢复和不可变对象
要求。现有 Google service account/Drive API 面向生产 Sheet，当前授权明确禁止新增生产
Sheet/state 写入，仓库也没有获批的独立研究 folder/object identity。因此未配置 workflow、
未写外部数据，正式事件数为 0。

可选方案：

1. **独立 Google Drive 文件夹（建议）**：用户创建仅存 public research objects 的专用
   folder，将既有 service account 只授予该 folder，并新增 `D1_RESEARCH_DRIVE_FOLDER_ID`
   secret。通常在既有 Workspace/Drive 配额内无新增服务费；具体配额/费用由用户账户决定。
   需要实现并验证 create-if-absent、read-back hash、独立 restore 后才能激活。
2. **独立对象存储 bucket**：新建带 object versioning/retention 的 GCS/S3 bucket 和最小
   写入凭证。会新增云资源、权限与按存储/请求/出口流量计费；需用户指定 provider、region、
   retention 与预算后再实现。

在用户选择并授权 durable backend 前，CN/US 均保持 `D1_READY_NOT_ACTIVE`。

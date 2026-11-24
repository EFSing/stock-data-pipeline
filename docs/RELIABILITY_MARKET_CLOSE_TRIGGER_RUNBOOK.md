# CN/US market-close trigger reliability runbook

状态：`AT_LEAST_ONCE_TRIGGER` + `EXACTLY_ONCE_PER_MARKET_SESSION` +
`RECONCILE_MISSING_SESSION`

本 runbook 只描述调度、session identity、D1 reconciliation 和通知运维。它不改变
`docs/TRADING_SYSTEM_SPEC.md`、Wave/Swing/Fibonacci、Setup、Entry、Stop、Target、
5%/2R、Risk、Paper 或 broker 语义。

## 固定语义

```text
Trigger:
AT_LEAST_ONCE

Session resolution:
LATEST_ELIGIBLE_COMPLETED_EXCHANGE_SESSION

Formal D1 storage:
EXACTLY_ONCE_PER_MARKET_SESSION

Duplicate handling:
IDEMPOTENT / NOOP

Missing formal session recovery:
RECONCILE_BEFORE_NEXT_SESSION_OPEN

After prospective deadline:
MISSED_PROSPECTIVE_SESSION
NO_BACKFILL
```

正式 identity 始终是 `market + session_date`。重复触发不创建第二个 D1 event。
D1 入口统一进入 `scripts/run_market_close_reconcile.py`。VPS 只检查、触发 GitHub Actions，
行情、日报和研究计算均由各自的 Actions workflow 执行。

## Shared completed-session resolver

`ExactExchangeCalendarProvider.latest_completed_session()` 使用
`exchange_calendars` 的 `XSHG` / `XNYS` session open/close，选择截至实际运行时刻最后一个
真实 close 已过去的 exchange session。它不再执行
`market_local_date(now) -> 当天 T`。

因此：

| 情况 | CN 目标 T |
|---|---|
| 9/29 17:30 北京 | 9/29 |
| 9/29 22:00 北京 | 9/29 |
| 9/30 01:46 北京、9/30 尚未开盘 | 9/29 |
| 9/30 下一 session 已开盘 | 仍解析 9/29，但 D1 采集窗口已关闭，不能补证据 |
| 周末/节假日 | 最近一个真实完成的 session |

US 使用真实 `XNYS` close，因此 EDT/EST 自动切换；周末、Observed Holiday 和长假不以
“减一天”推导。Daily Report 的自动入口与 D1 collector 共用这一 resolver。手动
`--date/--trade-date` 仍是显式诊断输入，仍需 exact completed-session gate。

## D1 reconciliation

主入口和两条 fallback 都调用同一个 market-specific workflow：

| Market | GitHub workflow file | VPS primary |
|---|---|---|
| CN | `.github/workflows/setup01-d1-vps-natural-collector-cn.yml` | 18:40 BJT (Mon–Fri) |
| US | `.github/workflows/setup01-d1-vps-natural-collector-us.yml` | 09:40 BJT (Tue–Sat) |

workflow 名称保留历史文件路径，但 job 已执行 reconciliation CLI。CLI：

1. 解析最新真实 completed session；
2. 先 read-back `sessions/{market}/{session_date}.json`；已有则返回
   `NOOP_ALREADY_COMMITTED`；并发重复在 durable store 层返回 `IDEMPOTENT_REPLAY`；
3. 检查 immutable activation window；activation 前不补采；
4. 检查 `session close <= now < next exchange session open`；缺失且在窗口内才运行
   natural collector；
5. 下一 session 已开始则返回 `MISSED_PROSPECTIVE_SESSION`，不做历史 backfill；
6. collector commit 后再次 load/read-back，hash/session identity 不匹配则
   `READBACK_FAILED`；
7. receipt 与中文 research report 作为非权威 Actions artifact 输出；若运行在 GitHub
   Actions，CLI 同时把同一结构化诊断写入 `GITHUB_STEP_SUMMARY`。`MISSED_PROSPECTIVE_SESSION`
   返回非零状态，因而在 Actions 页面形成可见失败通知，但不阻塞下一自然 session 的正常
   schedule。

Daily Report 与 D1 仍故障隔离：任一 D1/VPS 失败不改变普通 Daily Report，普通日报失败也
不删除或修改 D1 durable evidence。

## Daily Report reliability

`cloud_daily_report.reliability_classification` 额外区分：

- `SCHEDULER_DELAY`：自动触发跨入新的 exchange-local session date，但 T 仍使用最近真实完成 session；
- `SESSION_RESOLUTION_ERROR`：calendar/session identity 无法安全解析；
- `INCOMPLETE_SESSION`：显式目标日期尚未完成；
- `DATA_QUALITY_PARTIAL`：exact T 有结果但 provider/candidate/data quality 不完整；
- `PROVIDER_FAILURE`：运行期 provider/读取/计算异常；
- `NO_SIGNAL`：报告成功完成，但没有用户可见交易信号；这不是 failure；
- `SUCCESS`：报告成功且存在信号或正常完成。

`status=PARTIAL_DATA_QUALITY` 仍保留，不降低 scheduled `--require-complete` 的质量门槛。

当 Daily Report workflow 具备 D1 VPS connection secrets 时，通知先在独立的
`system/operational/daily-report-notifications/` namespace create-only claim，key 为
`market + session_date + report_protocol_version`。已 claim 的 fallback 返回
`NOOP_REPORT_ALREADY_SENT`；marker 失败时不发送普通 Bark/SMTP，避免重复骚扰，并在
report metadata 记录 `IDEMPOTENCY_UNAVAILABLE`。该 marker 绝不进入 `objects/` 或
`sessions/`，也不构成 D1 evidence。

## VPS 调度与 GitHub App

六个 GitHub Actions workflow 的时间触发统一由 Ubuntu VPS 的 user-level systemd timers
负责。App 按次生成短期 installation token，权限范围为本仓库的 Actions 读写。日报的主触发
仍为收盘更新成功后的 `workflow_run`，仅接受 `main` 上由配置的 App bot 发起的更新。
定时日报补跑照常执行 readiness 和终态去重。D1 补跑照常执行 prospective session gate。

时刻表、只读预检、验收与部署步骤见 [VPS 调度运维](../infra/vps/market-close-watchdog/README.md)。
部署切换时在 Cloudflare 控制台停用旧 Cron，并停用 VPS 上的两条旧 watchdog timer。
若 VPS 故障覆盖某次调度，恢复后由余下的本交易日时段尝试协调。VPS 没有独立的外部
定时后备，系统启动后也不自动补发错过的全部时段。

## Activation / code SHA audit

现有 activation record 的 `code_sha` 是创建时的不可变 provenance 字段；当前
`VpsD1Store` 会校验它是合法 Git SHA，并把 activation record hash 绑定到 snapshot source
contract，但不会把运行中的 `GITHUB_SHA` 当作每次 commit 的硬门槛。此次变更只改
operational session resolution、reconciliation 和 trigger delivery，未改变 frozen
protocol、source/observer bytes、signal/stop/target/exit/gate 或 prospective activation
timestamp；因此保留现有 CN/US activation，不重新选择首个 session，也不创建新的 activation
epoch。receipt 明确记录 reconciliation protocol version，避免把 operational hardening
描述为新的研究语义。

如果未来修改 frozen research/source contract，必须先创建新的明确 protocol/freeze 与
activation 记录；不得静默覆盖既有 activation 或把历史/日报 backfill 成 prospective evidence。

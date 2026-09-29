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
所有入口进入 `scripts/run_market_close_reconcile.py`；Cloudflare 和 VPS 只检查/触发
GitHub Actions，不复制 market-data 或研究业务逻辑。

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

| Market | GitHub workflow file | Primary schedule |
|---|---|---|
| CN | `.github/workflows/setup01-d1-vps-natural-collector-cn.yml` | `40 10 * * 1-5` UTC = 18:40 BJT |
| US | `.github/workflows/setup01-d1-vps-natural-collector-us.yml` | `40 1 * * 2-6` UTC = 09:40 BJT |

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

## Cloudflare Worker fallback

源码在 `infra/cloudflare/market-close-watchdog/`。Free-plan Worker 只调用 GitHub Actions
API：最近 90 分钟存在 queued/in-progress/success run 时 `NOOP_PRIMARY_ACTIVE_OR_SUCCESS`；
没有运行、失败或 API 状态不确定时 dispatch 同一 workflow。429/5xx/network error 最多
三次 bounded retry；token 不打印。

| UTC cron | Market | fallback |
|---|---|---|
| `45 9 * * 1-5` | CN | Daily Report |
| `55 10 * * 1-5` | CN | D1 prospective |
| `15 1 * * 2-6` | US | Daily Report |
| `55 1 * * 2-6` | US | D1 prospective |

部署时只需要创建一个 Free Worker 并设置 secret `GITHUB_TOKEN`。Fine-grained token
必须只允许 `EFSing/stock-data-pipeline` 一个 repository、`Actions: Read and write`；
不授予 Contents write、Administration 或其他仓库。Cloudflare 不需要 paid Workers、KV、
R2、Durable Objects 或任何购买/升级操作。详细步骤见该目录 README。

## Ubuntu VPS watchdog fallback

源码在 `infra/vps/market-close-watchdog/`。user-level systemd timers 约在：

- CN：周一至周五 20:05–20:15 BJT；
- US：周二至周六 11:05–11:15 BJT。

watchdog 同时检查 Daily Report 与 D1 workflow，仍只调用 GitHub Actions API；不连接行情、
VPS D1 store、holdings、Paper、Sheet 或 broker。GitHub API 使用 bounded retry，不无限循环。
由于 VPS 检查晚于日报 primary/fallback，watchdog 对最近 workflow run 使用四小时有界查询窗；
该窗口覆盖两条业务链的延迟，不会把前一交易日的成功 run 当作当前 run。

token 放在 VPS 用户自己的 `0600` 配置文件，不进入 repo、D1 evidence 或日志。建议与
Cloudflare 使用两个独立 fine-grained token，以隔离 credential failure domain；若确实共享，
必须接受两条 fallback 共享 credential failure domain，并记录同一个 expiry。轮换时先建同
权限新 token、更新对应 secret/config、验证后撤销旧 token。

最少部署命令和不使用 Docker/nginx/database/root 的约束见
`infra/vps/market-close-watchdog/README.md`。

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

## 外部节点

本 PR 不需要用户把任何 credential 发到聊天。真正部署时用户只需在各自控制面完成：

1. Cloudflare Free Worker + `GITHUB_TOKEN` secret；
2. GitHub fine-grained token 精确限制到本仓库 Actions read/write；
3. VPS 0600 watchdog config + user systemd timers。

没有新增付费服务或自动购买动作。

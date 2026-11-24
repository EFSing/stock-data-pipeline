# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`VPS_GITHUB_APP_SCHEDULER_LIVE_AWAITING_NATURAL_ACCEPTANCE`。迁移 PR 已合并到 main。
现有 Ubuntu VPS 的六个 systemd user timers 已启用，专用 App 私钥由 VPS 非 root 调度账户
以 `0600` 保管。每个定时进程按次签发短期 installation token，再触发 GitHub Actions。
GitHub 原生 Cron 已从 main 移除，Cloudflare 已清空该 Worker 的 Cron，VPS 的两条
旧 PAT timer 已停用。App 的只读预检和由 App bot 发起的 CI 均已通过。

下一步只读核对首次自然 CN/US 收盘更新、日报接跑和 D1 补跑。时刻表、部署及验收见
[VPS 调度运维](infra/vps/market-close-watchdog/README.md)。首次自然链路尚待验收。
运行期不依赖本地 Windows 电脑、PAT 或 Cloudflare Cron。

## 日报后续验收


`DAILY_REPORT_WAVE3_SECTOR_SUMMARY_MERGED_WAITING_NATURAL_ACCEPTANCE`。三浪板块分布已随独立
PR 合并到 main，接入 A 股／美股日报、邮件正文和 JSON。统计当日三浪结构确认与等待确认，按
市场和股票代码去重。A 股补充国证行业快照，美股复用当期 IWB 行业。缺分类保留为行业未知。

下一步是只读核对合并后的自然日报，确认分类覆盖和展示效果。在定时切换后继续验收现有交付路径。

## 独立的日报运维验收

`DAILY_REPORT_VPS_MARKER_ABSENCE_FIX_MERGED_WAITING_NATURAL_ACCEPTANCE`。
PR #138 已合并，但其首次 CN/US natural acceptance 已失败；原“无 code blocker、等待
natural acceptance”的现场描述与生产证据冲突。本轮已核对远端 main、PR #138 与 Actions，
最小修复已按用户授权通过 PR #139 squash merge 进入 main，PR 为 MERGED/CLOSED，
merge 后 main CI 已通过；本地 main 已同步。修复后的真实 CN/US natural acceptance 仍待
下一次自然运行，本次 merge closeout 未触发日报、Email/Bark、历史补跑或 formal collector。
PR/HEAD/mergeability/exact-head CI 一律实时查询 GitHub，不在这里镜像。

## Production Evidence / Root Cause

- CN 主触发 [run 37959437802](https://github.com/EFSing/stock-data-pipeline/actions/runs/37959437802)
  与 fallback [run 37961419265](https://github.com/EFSing/stock-data-pipeline/actions/runs/37961419265)、
  [run 37964063137](https://github.com/EFSing/stock-data-pipeline/actions/runs/37964063137)，以及 US
  主触发 [run 38030159960](https://github.com/EFSing/stock-data-pipeline/actions/runs/38030159960)
  均在 provider/Candidate/strategy/Ledger 前失败。CN 日志为 2026-10-09 UTC（北京时间
  2026-10-10 凌晨），US 日志为 2026-10-10 UTC/北京时间。
- `finality_preflight.status=IDEMPOTENCY_UNAVAILABLE`；错误为
  `D1_REMOTE_OBJECT_MISSING (helper exit 6)`。这是真实首次自然验收失败，不是 pending。
- 根因是 production adapter exception mismatch：`VpsD1Store.read_bytes()` 抛
  `VpsObjectMissing`，而 PR #138 的 `_read_v2_final_marker()` 只将
  `FileNotFoundError/KeyError` 视为 absent；旧 `_MarkerStore` 的 KeyError fixture 未覆盖
  真实 adapter 合同。缺 marker 是首次日报的正常状态，不是 storage unavailable。

## Current State / Completed / Validation

- 仅在 operational-marker 读取边界增加 `VpsObjectMissing` 的精确类型识别；V2 absent
  继续查 legacy，无 legacy 时返回 `NO_FINAL_REPORT_MARKER`，允许首次自然日报继续。
  合法 V2 final marker 保持 terminal NOOP；非 missing SSH/helper、identity、hash、read/scan
  错误仍为 `IDEMPOTENCY_UNAVAILABLE`；非法 final payload 仍为 `FINAL_MARKER_INVALID`。
- 测试复用真实 `VpsD1Store + repository-owned helper` 和本地临时目录，无 VPS credentials、
  真实持仓、生产 Sheet、broker 或通知。CN/US natural automatic fixture 已证明 absent 后
  到达行情加载/策略调用；read failure 不到达这些调用；已有 final marker 无下游工作。
- `_legacy_v1_markers()` 没有同类 missing-exception bug：不存在的 prefix scan 返回空列表；
  scan 已列出的 immutable marker 随后 read missing 仍 fail closed，不把证据丢失当正常 absent。
  没有修改 legacy scan/read 的错误处理或 storage/helper。
- focused tests、完整 unittest、compileall、workflow contracts、六个既有 generic operational
  shadows 与 `git diff --check` 已通过；PR #139 合并前 exact-head checks 与 merge 后 main
  CI 均已成功。docs-only closeout 仅执行既有轻量治理检查与 diff check，不因文档提交
  重跑完整测试/shadow；synthetic 验证不等于修复后的 natural acceptance。
- notification routing、Ledger failure 独立维度、bounded retry 静默和 session terminality 的
  长期设计不变；`docs/DECISION_LOG.md` 的 2026-10-09 决策无需改写。

## Blocker / Separate Follow-ups / Remaining Risks

- D1 独立 blocker 已只读核实：[run 38019348189](https://github.com/EFSing/stock-data-pipeline/actions/runs/38019348189)
  返回 `D1_SOURCE_MIGRATION_AFTER_FORMAL_EVIDENCE:{"CN":0,"US":1}`。本修复不放松保护，
  不创建 activation、不迁移/回填 evidence、不运行 formal collector。
- 既有 VPS helper `_iter_store_files()` 未枚举 `system/operational/`；因此 generic legacy
  fixture 的有效 V1 marker 识别不证明真实 VPS legacy 枚举覆盖。该扫描范围问题与本次
  absent exception mismatch 不同，单独记录，不在本 PR 重构/扩展 storage。
- 修复后自然 CN/US 报告、通知与 Opportunity Ledger 验收仍需合并后真实自然运行；历史
  replay、手动发送、synthetic shadow 均不得冒充。CN 原 residual/formal coverage、Yahoo
  exact-T forensic、Ledger 三表自然结果仍以新自然 artifact 为准，不宣称已通过。
- 新 D1 provider-forward activation 仍需独立授权；601059/601198、JMKE 等合法 fail-closed
  数据/历史不足状态不因本修复改变。

## Next Action

下次真实 CN/US natural Daily Report 由 VPS App 触发的收盘更新成功后接跑，或由 VPS
补跑。只读核对 run、交付和幂等结果，不以 replay 或 synthetic 结果代替自然验收。

自然验收必须确认：

- 首次 session 的 finality preflight 正常 absent / `NO_FINAL_REPORT_MARKER`，不再因缺 marker
  返回 `IDEMPOTENCY_UNAVAILABLE`。
- 实际进入 provider、Candidate、strategy 与 Opportunity Ledger，并按真实结果报告各自状态。
- 合法 final marker 后的重复自然触发为 terminal `NOOP_FINAL_SESSION_ALREADY_COMPLETED`，
  无下游重复工作。
- 非 missing storage/read/corruption 继续 fail-closed，不以成功自然日报推断这些边界已被
  自然触发验证；按实际故障证据与已通过的回归合同分别记录。
- 跨真实 run 核对 Email/Bark/marker 没有重复发送/claim；未形成真实 delivery evidence 时
  不宣称通知自然验收成功。

## Constraints / Pitfalls

- 总体交易主线与四类 Setup 以 `docs/TRADING_SYSTEM_SPEC.md` 为唯一事实源：
  Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup →
  Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
  SETUP_01=Wave 2→Wave 3，SETUP_02=Wave 3 Continuation，SETUP_03=Platform Breakout，
  SETUP_04=Extreme Fear Reversal；SETUP_03 只是四类 Setup 之一的子策略，其开发深度不
  改变总体优先级，Wave Scenario Engine、SETUP_01、SETUP_02 仍是总体核心路线。
- 不改变 Candidate ranking、provider contract、Wave/Setup/Entry/Target/Risk、Opportunity
  Ledger、Paper、broker 或 D1 formal evidence 语义；不访问真实持仓。
- 保持 `data <= t`、T→T+1、Target-before-RR、CN/US 独立和 exact-T；不制造目标/RR。
- Cloud observation writer 继续使用既有 per-market workflow concurrency；不绕过它写 Ledger。
- 凭证只经 Secret/本机环境变量注入，不输出到账本、repo、普通 CI 或 artifact。

`HANDOFF_CURRENT_AND_CONSISTENT`

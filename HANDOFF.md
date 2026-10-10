# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI 的实时事实源；本文件只记录继续工作所需的语义状态。

## Current Task

`DAILY_REPORT_VPS_MARKER_ABSENCE_FIX_IMPLEMENTED_AWAITING_MERGE_DECISION`。
PR #138 已合并，但其首次 CN/US natural acceptance 已失败；原“无 code blocker、等待
natural acceptance”的现场描述与生产证据冲突。本轮已核对远端 main、PR #138 与 Actions，
并在最新 main 上建立独立分支 `codex/fix-daily-report-vps-marker-absence` 做最小修复。
修复 PR 保持 OPEN、未合并；main 的 production regression 在合并前仍存在。
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
  shadows 与 `git diff --check` 已通过。远端 CI 与相关 shadow readiness 看修复 PR 的实时
  exact-head checks；synthetic 验证不等于修复后的 natural acceptance。
- notification routing、Ledger failure 独立维度、bounded retry 静默和 session terminality 的
  长期设计不变；`docs/DECISION_LOG.md` 的 2026-10-09 决策无需改写。

## Blocker / Separate Follow-ups / Remaining Risks

- D1 独立 blocker 已只读核实：[run 38019348189](https://github.com/EFSing/stock-data-pipeline/actions/runs/38019348189)
  返回 `D1_SOURCE_MIGRATION_AFTER_FORMAL_EVIDENCE:{"CN":0,"US":1}`。本修复不放松保护，
  不创建 activation、不迁移/回填 evidence、不运行 formal collector。
- scheduler 独立问题：Asia nominal 北京时间 17:30，最近三次
  [10-09](https://github.com/EFSing/stock-data-pipeline/actions/runs/37959269205)、
  [10-08](https://github.com/EFSing/stock-data-pipeline/actions/runs/37811655542)、
  [10-07](https://github.com/EFSing/stock-data-pipeline/actions/runs/37654963376) created/start
  延迟约 418/438/439 分钟；US nominal 北京时间 08:30，最近三次
  [10-10](https://github.com/EFSing/stock-data-pipeline/actions/runs/38030097686)、
  [10-09](https://github.com/EFSing/stock-data-pipeline/actions/runs/37893695255)、
  [10-08](https://github.com/EFSing/stock-data-pipeline/actions/runs/37737676192) 延迟约
  342/358/357 分钟。只读记录，cron 与 trigger/concurrency 不变。
- 既有 VPS helper `_iter_store_files()` 未枚举 `system/operational/`；因此 generic legacy
  fixture 的有效 V1 marker 识别不证明真实 VPS legacy 枚举覆盖。该扫描范围问题与本次
  absent exception mismatch 不同，单独记录，不在本 PR 重构/扩展 storage。
- 修复后自然 CN/US 报告、通知与 Opportunity Ledger 验收仍需合并后真实自然运行；历史
  replay、手动发送、synthetic shadow 均不得冒充。CN 原 residual/formal coverage、Yahoo
  exact-T forensic、Ledger 三表自然结果仍以新自然 artifact 为准，不宣称已通过。
- 新 D1 provider-forward activation 仍需独立授权；601059/601198、JMKE 等合法 fail-closed
  数据/历史不足状态不因本修复改变。

## Next Action

唯一下一步决策：审阅并决定是否合并这个最小修复 PR。保持 OPEN，不自动 merge；获准
合并后等待真实自然日报验证恢复，不手动发送 Email/Bark，不历史补跑冒充验收。

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

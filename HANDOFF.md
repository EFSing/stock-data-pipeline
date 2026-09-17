# HANDOFF — 当前开发现场恢复文件

Git/GitHub 是 branch、HEAD、PR、CI、mergeability 的实时事实源；不依赖本机目录、聊天或 session memory。

## Current Task

`DAILY_REPORT_DENSE_DECISION_CARD_V1` 正在独立分支
`fix/daily-report-dense-decision-card-v1` 上，PR #96 OPEN、未合并；范围仅为 CN / US Cloud Daily Report
完整 HTML 主报告的共享高密度 Decision / ARMED / WATCH 展示；不改变策略计算、Gate、
Candidate 生命周期、Paper/state/Sheets/broker 或任何 production trading semantics。

## Current State

- 当前恢复基线：`main`；PR #94 已 squash merge。合并决策时的 live PR head / exact-head CI 由 GitHub 实时核验；transient PR head is not a governance invariant。基线 main 已包含 PR #93 的 ARMED projection。
- 当前开发 branch：`fix/daily-report-dense-decision-card-v1`，从 live `main` 独立创建；PR #96 为本任务唯一 PR，未与其他 PR 混合。
- PR #92 已按正式负研究结论 squash merge；Post-confirmation Retest hypothesis 已关闭，不进入 production design / fresh validation。
- PR #91 分类冲突已核实、修正并验证后 squash merge；确定性 artifact 总体分类仍为 `MIXED_ARCHITECTURE_SIGNAL_STARVATION`。`ABOVE_ENTRY_ZONE=595/999` 是最大 post-confirmation first-fail，不是总体唯一原因。
- PR #90 已落实用户明确的 partial-report operational exit 语义，经 full/focused tests、CI 与只读 US manual smoke 后 squash merge；main 交接已同步。
- PR #82 完全独立，保持 OPEN；本次没有 merge/rebase/mix。其 HEAD、CI 与冲突状态实时从 GitHub 查询。
- 长期总体交易规则以 `docs/TRADING_SYSTEM_SPEC.md` 为唯一正式事实源。

## Completed

- `DailyDecisionResult.armed_opportunity` 复用当前 causal SETUP_01/02 ARMED snapshot 与 as-of T history，暴露 close、confirmation、距离、structural invalidation、ATR14 和现有正式 Entry Zone 公式结果。
- 缺 confirmation / invalidation / ATR 等字段时 fail closed；projection 明确 `is_trade_signal=false`，不创建 Decision/event/plan/Paper/state write。
- Dashboard 新增“机会观察”详情与 compact 距确认信息；交易方案优先，ARMED 仅按距确认百分比绝对值作展示排序。
- Dashboard/email 将 Entry Zone 标为“预计入场区（按当前 ATR，仅供观察）”；共享 guidance 明确当前不是买入信号、未来以确认日 Decision 为准、超过正式入场区不追价且不等待后续回踩补入，结构失效则放弃。
- email 复用同一 projection，保持移动端有限重点项；renderer 不重算策略公式。已 CONFIRMED NO_TRADE 的原拒绝原因路径保持不变。
- 本任务已将 ARMED 的所有用户入口改为“等待确认”；确认日已计算且最终 NO_TRADE 时，Dashboard/email 首层复用既有 gate、Entry Zone 状态、T1 空间与 T1 R/R 字段；策略持仓标为“策略跟踪持仓”，Paper ledger 标为“模拟持仓”。
- 本任务已将 Dashboard 主卡片统一为 `DAILY_REPORT_DENSE_DECISION_CARD_V1`：CN/US 共用同一固定顺序的四行摘要与 Decision 计算依据；前置 Gate、`NO_VALID_TARGET`、数据缺失分别显示，不在 renderer 中补算 Target / ATR / Entry Zone / Stop / R/R。大段波浪、机会新鲜度和开发者审计信息压缩到 secondary / collapsed detail。
- ARMED 首层只复用现有 `armed_opportunity`（Setup、收盘价、确认价、距离、ATR14、观察区、结构失效）并明确“不是买入信号”；WATCH 不生成伪造 Decision 字段。CN/US synthetic HTML 已完成桌面与 390px 手机宽度人工检查。
- Decision/RR payload 未携带可直接消费的 minimum RR；因此 Dashboard/email 只格式化实际 R/R，并以既有 `gate_reason=RR_BELOW_MINIMUM` 展示“R/R不足”，不在 presentation 层复制正式阈值。
- 本次能力仍是 presentation/read-only only；production trading semantics unchanged，Post-confirmation Retest hypothesis remains closed，不进入 persistent/retest lifecycle。
- Post-confirmation Retest 正式结论已同步到 CURRENT_STATUS / DECISION_LOG：逻辑可行但恢复极少且全在 EARLY，不证明 broad/time-stable improvement，不改任何现有交易语义。

## Validation

- 本任务 Dashboard / email / Cloud Daily Report focused：66 tests，OK。
- 本任务 full `python -m unittest discover -s tests -v`：799 tests，OK。
- 本任务 `python -m py_compile` 与 `git diff --check` 通过；CN/US synthetic HTML smoke 已覆盖 ABOVE_ENTRY_ZONE、RR_BELOW_MINIMUM、NO_VALID_TARGET、ARMED、WATCH、字段顺序与缺失语义，并完成桌面/390px 手机宽度检查。
- PR #94 合并前 4/4 GitHub checks 已通过且无冲突，随后已 squash merge；合并后的 main 状态与 CI 以 GitHub 实时状态为准。
- PR #93 final HEAD 4/4 checks passed、无冲突并已 squash merge，merge 后 main push CI green。
- #91 focused 14/full 767，artifact full parity 与 self-hash 通过；#90 focused 79/full 777 和三项 PR CI 通过。
- #90 一次只读 US smoke：exact XNYS 2026-09-16，PARTIAL_DATA_QUALITY 保留、workflow exit 0；220 DATA_OK、2 DATA_UNAVAILABLE，actual primary Tencent/verifier Sina；两条 unavailable QFQ 继续 blocked，未用 T-1 替代 T；final JSON/HTML 与 transport digest 核验通过，无 state/Sheets/Paper/raw writes 或 broker action。可复核 workflow 链接见 #90 PR 描述。

## Blocker

无实现安全 blocker，`PROJECT_GOVERNANCE_STATE_CONFLICT` 不存在。
如无可安全复用的现有 Cloud Daily Report 输入，只使用 synthetic/现有 fixture 做只读 UI smoke，不访问 Sheets/state/Paper/broker/Final OOS。

## Next Action

完成 PR #96 当前 HEAD 的 exact-head CI 核对后，停在 `READY_FOR_DAILY_HTML_PRODUCT_ACCEPTANCE`，等待产品验收；不自动 merge。

## Constraints

- 主线：Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit。
- 四类 Setup：SETUP_01、SETUP_02、SETUP_03、SETUP_04；SETUP_03 只是四类 Setup 之一的子策略。
- confirmation、ATR14 Entry Zone、Swing/Wave/Fib、Target-before-RR、Stop、5%、2R、T→T+1 均不变；确认日 geometry/targets/provenance 冻结。
- ARMED projection 只读、causal/as-of；展示排序不属于策略 ranking/promotion/gate。
- renderer 不计算 confirmation + ATR multiplier 等交易公式；缺字段不猜测。
- 无 Final OOS/parameter search/provider fetch/真实 holdings；不写 Sheets/state/Paper，不下 broker order。
- REAL_HOLDINGS_SHADOW 仍为 OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION / NOT_RUN_USER_PRIVACY，不是研究 blocker。

## Pitfalls

- 同一 symbol/T 若 SETUP_01 与 SETUP_02 同时 ARMED，projection 以 `MULTIPLE_ARMED_SETUPS` fail closed，不在展示层做 setup 仲裁。
- ARMED 排序使用 projection 已给出的 `distance_to_confirmation_pct` 绝对值；缺失值排在同阶段末尾，不影响其他阶段优先级。
- 预计 Entry Zone 是按当前 ARMED as-of ATR14 与现有正式 multiplier 形成的 read-only estimate，仅供观察；未来正式确认以确认日 Decision 为准，不是当前 plan、买入信号或未来成交承诺。若确认时超过正式入场区则不追价、不等待后续回踩补入；结构失效则放弃。
- fixture 中尚未带新 projection 的旧 ARMED row 必须显示数据不足，不得由 renderer 从旧字段补算。

`HANDOFF_CURRENT_AND_CONSISTENT`

`CROSS_DEVICE_HANDOFF_READY`

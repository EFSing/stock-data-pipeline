# SETUP_02 — Wave 3 Continuation Structural v1

状态：`SETUP_02_STRUCTURAL_V1_READY_FOR_SOL_REVIEW`

本文件冻结 SETUP_02 的结构性 evaluator、strict-prefix replay 和
`DEVELOPMENT_EXPOSED` 证据边界。它不是 Decision/Risk、Entry、Exit、持仓、
production 或 outcome protocol。

## 1. Scope and source of truth

- protocol version：`SETUP-02-WAVE3-CONTINUATION-2026-09-01-v1`
- setup type：`SETUP_02`
- Wave Engine protocol：`WAVE-SCENARIO-ENGINE-2026-08-30-v1`
- implementation：`trading/setup02.py`
- replay：`trading/setup02_replay.py`
- development runner：`scripts/run_setup02_structural_replay.py`
- regression：`tests/test_setup02.py`

SETUP_02 只读取现有 Wave Scenario Engine 的结果。Wave Engine、Swing、
Fibonacci、SETUP_01、Decision/Risk 和 production path 不由本任务改写。

## 2. Candidate eligibility

唯一允许进入 SETUP_02 的场景是：

1. `primary_wave_scenario == WAVE_3_CONTINUATION_CANDIDATE`；
2. `setup02_context_eligible == true`；
3. primary context 为因果、已确认的 `LOW0 → HIGH1 → LOW2 → HIGH3`；
4. `HIGH3 > HIGH1` 且 `LOW2 > LOW0`；
5. daily 和 weekly state 都是 `UPTREND`；
6. 所有参与 Swing 的 `confirmed_index` 不晚于当前 `as_of` bar；
7. `continuation_high` 固定为 `HIGH3`；
8. `structural_invalidation` 必须直接使用 Wave Engine 的现有最新确认
   higher-low / structural invalidation，不在 SETUP_02 内重新定义。

Alternate scenario 只作诊断展示，不能把 primary 非 continuation 场景升级为
候选。候选 identity 由四个确认 pivot 的因果 index 组成；普通 context refresh
不产生伪造的 FAILED。

## 3. Lifecycle

状态集合严格为：`NONE`、`WATCH`、`ARMED`、`CONFIRMED`、`FAILED`。

设：

```text
invalidation = Wave Engine structural_invalidation
recovery = invalidation + 0.5 * (HIGH3 - invalidation)
```

### Pre-confirmation states

- `NONE`：没有可用 primary candidate。
- `WATCH`：候选仍有效，收盘价高于 invalidation，但低于 recovery。
- `ARMED`：收盘价大于等于 recovery 且小于等于 `HIGH3`。
- `CONFIRMED`：首次 daily close 严格大于 `HIGH3`。
- 收盘价等于 `HIGH3` 不确认，仍可为 `ARMED`。
- `ARMED` 后回落到 recovery 以下但仍高于 invalidation 时，回到 `WATCH`。

允许的正常路径为 `NONE → WATCH ↔ ARMED → CONFIRMED`。候选在
`WATCH/ARMED` 期间可因 structural invalidation、weekly/daily structure loss、
primary ABC、primary downtrend/invalid 或 primary eligibility loss 进入
`FAILED`。

### Terminal rules

- `CONFIRMED` 和 `FAILED` 是 terminal；历史 terminal state 在后续普通刷新中保持。
- `CONFIRMED` / `FAILED` 事件只在首次进入对应 terminal state 时发出一次。
- 在 confirmation 之前，收盘价小于等于 invalidation 即 `FAILED`。
- weekly parent loss 和 daily structure loss 必须 fail closed。
- primary ABC、primary downtrend/invalid、primary loses eligibility 必须 fail closed。
- 没有新的候选且不存在活跃 lifecycle 时为 `NONE`；已有活跃 lifecycle 时，
  context 暂时缺失按对应失败原因 fail closed，不重复发 terminal event。
- 新的 candidate identity 开始新的 lifecycle；旧 terminal identity 不重开。

## 4. Causality and invariance

每个 `as_of` 日只将该日以前的 quote prefix 传给 Wave Engine；不得读取未来
confirmed Swing、未来收盘、未来周线或未来 candidate。`signal(t)` 只使用
`data <= t`。对同一历史前缀追加未来 bars 不得改变此前任何 evaluation、state
或 terminal event。

SETUP_02 不做 provider fallback、history splice、日期填充、synthetic bar、
OHLC 修改或结果驱动的 symbol replacement。

## 5. Fibonacci diagnostics

仅使用项目现有 canonical Fibonacci levels/regions 作为描述性字段，不作为
candidate、lifecycle、confirmation 或 failure 的硬门槛。SETUP_02 使用
现有 canonical helper 计算 `HIGH1 → LOW0` 的诊断 retracement ratio/region；
不新增 ratio、不调参、不把 Fib 改造成交易规则。

## 6. Event identity

event type 只有 `CONFIRMED` 和 `FAILED`，namespace 固定为 `SETUP_02`。replay
identity 的形式为：

```text
<symbol>|SETUP_02|<trade_date>|<event_type>|lifecycle=<lifecycle_index>
```

同一 symbol、日期、event type 和 lifecycle index 只能有一个 event。事件 payload
只包含结构字段、Wave context、Fib diagnostics、reason 和 lifecycle provenance；
不包含 Entry、Exit、Decision/Risk、持仓或 outcome。

## 7. DEVELOPMENT_EXPOSED replay

runner：

```powershell
python -m scripts.run_setup02_structural_replay
```

默认读取冻结的 local development manifest：

```text
dataset_version = SETUP_03-DEVELOPMENT-DATASET-CN-BAOSTOCK-US-YFINANCE-2026-08-28-v2
symbols = 40 (CN 20 / US 20)
bars = 84,284 (CN 40,873 / US 43,411)
manifest_sha256 = 93368588ced692c7a0360cd6914c46caa9726f3e20abb0381d99729afbd5e216
replay_aggregate_sha256 = 9271560e6662b910b02d8eb6a76ddb3476e5b724466bb102443064e8c9d7fe18
```

输出仅允许包含：

- symbols/days 和 CN/US coverage；
- `NONE/WATCH/ARMED/CONFIRMED/FAILED` state-day counts；
- first-entry confirmed/failed event counts；
- per-symbol state/event distribution；
- primary/alternate Wave scenario distribution；
- current candidates；
- failure/block reasons；
- canonical Fib diagnostic regions；
- deterministic identity duplicate/mismatch audit。

明确禁止输出或计算 forward returns、win rate、MFE、MAE、P&L、expectancy、
OOS、交易成本、Entry/Exit、Decision/Risk、生产日历、Sheets 或账户数据。
证据标签固定为 `DEVELOPMENT_ONLY`、`NOT_FORMAL_VALIDATION`、
`NOT_FINAL_OOS`。

## 8. Regression minimum

回归必须覆盖：

- canonical continuation candidate and primary-only selection；
- `NONE → WATCH → ARMED → WATCH → CONFIRMED`；
- close equals `HIGH3` does not confirm；
- close strictly above `HIGH3` confirms once；
- invalidation / weekly / daily / ABC / downtrend / eligibility failures；
- context refresh without duplicate failure；
- new candidate identity after terminal；
- alternate continuation cannot override primary；
- strict-prefix and future-append invariance；
- confirmed Swing causality；
- deterministic identity and structural-only event rows。

## 9. Review stop

本协议的交付停止点是 `SETUP_02_STRUCTURAL_V1_READY_FOR_SOL_REVIEW`。
Sol review 未批准前，不得实现 SETUP_02 Decision/Risk、Entry、Exit、production
integration 或 outcome research。

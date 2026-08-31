---
name: holdings-data-manager
description: Manage the current holdings universe and its raw/qfq daily-history lifecycle from deterministic ADD, REENTER, CLOSE, and SYNC intents. Use for requests such as adding a ticker, buying it back, closing it, or filling its history; do not use for orders, account positions, NAV, P&L, or strategy decisions.
---

# 持仓股数据管理

本 Skill 只负责把自然语言持仓数据请求编排为确定性的生命周期操作。业务实现位于仓库根目录的 `holdings_data_manager.py`，Skill 文件不得自行抓行情、解析 Google Sheets、删除历史或推断账户信息。

## 调用 contract

优先调用：

```python
from holdings_data_manager import HoldingsDataManager

result = HoldingsDataManager().execute_text(user_request)
```

若上层已完成意图解析，调用 `execute(operation, symbol, market=None)`，其中 `operation` 只能是 `ADD`、`REENTER`、`CLOSE`、`SYNC`。`market` 只有在用户明确提供或由规范化代码格式唯一确定时才可传入；不能猜测市场、ticker、provider 或公司身份。

返回值至少包含 `operation`、规范化 `symbol`、`market`、`status`（`SUCCESS` / `IDEMPOTENT` / `FAILED`）、`enabled`、`history_rows_written` 和 `message`。失败必须保持 `enabled` 不被错误打开，并在可确定身份时写入 `运行日志` 的 append-only 审计记录。

## 自然语言意图

- “添加 MU”“我买了 512400” → `ADD`
- “重新买回 INTC”“重新入场 INTC” → `REENTER`
- “NOK 已清仓”“卖出 NOK” → `CLOSE`
- “同步 MU”“补齐 MU 历史” → `SYNC`

多个标的、多个操作、无法确定市场或身份时必须 `FAILED` / fail closed，请用户补充明确输入。

## 生命周期语义

- `ADD`：新身份先完成 symbol/market/source normalization，再确保未复权与前复权历史覆盖最近已完成市场交易日前的过去一个自然年；两套历史和质量检查成功后才设 `自选清单.启用=True`。已启用身份重复 ADD 为幂等，不重抓历史；已存在但停用的身份自动采用 REENTER 的补缺口后恢复语义，用户不需要记忆内部操作名。
- `REENTER`：只接受已有身份；检查历史覆盖，仅抓取缺失的边界/区间；完整覆盖时不重抓一年；完成后恢复 `启用=True`。历史或 provider 失败时保持停用。
- `CLOSE`：只把当前身份从 `启用=True` 改为 `False`。绝不删除 `历史行情_未复权`、`历史行情_前复权`、校验记录、数据源映射或证券身份；重复 CLOSE 为幂等。
- `SYNC`：补齐目标身份的 raw/qfq 历史缺口，不改变当前启用状态；它不是 ADD，也不会触发 SETUP、Decision 或任何交易动作。

### History coverage / session contract

目标窗口是最近已完成市场交易日向前一个自然年。coverage 只使用 provider 实际返回的 session dates 和已有历史，不把 weekday 当交易所日历，也不为休市日插值 bar。raw 与 qfq 必须拥有完全一致的 session-date 集合；两者任一为空、日期重复/越界、未到达目标末日、起点距目标超过 7 个自然日、少于 180 个有效日线 bar，或相邻 observed session 相差超过 14 个自然日，均 `FAILED`。这是一组确定性的稀疏/截断/异常中段 gap 门控；正常节假日形成的短闭市区间不会被当作缺口。

REENTER/SYNC 只对 observed dates 推导边界和异常中段区间。尾部缺口请求增量区间，中段异常 gap 请求中间区间；provider 返回空、仍不完整或 raw/qfq 集合不一致时 fail closed。完整一年历史不会因圣诞节、感恩节、春节、国庆等休市日重复抓取。

所有操作复用既有 `providers.fetch_with_retry` / `fetch_latest_with_retry`、`core` 的日期/行情质量检查、`SheetsClient.upsert_history` 和 `自选清单.启用` 语义。不要调用整个 `main.py --mode full` 作为单标的操作。

## 禁止动作

- 不读取或推断账户数量、成本、NAV、盈亏，不下单，不访问真实券商账户。
- 不删除历史行情，不因 CLOSE 清空历史，也不创建第二套 holdings registry 或重复 Sheet 事实源。
- 不触发 SETUP_01/02/03/04、Wave、Fibonacci、Decision、Risk、Position Management、Exit、研究回放或 outcome 逻辑。
- 不填充、插值、伪造、重复写入历史日期；任何身份歧义、provider/history failure、重复日期或质量失败都必须 fail closed。

只读 provider smoke 位于 `scripts/holdings_data_manager_smoke.py`，默认检查 `512400.SH` 的 raw/qfq 一年窗口；它不连接 Sheets、不写生产数据、不触发 full/SETUP/Wave/Decision/research，也不读取账户信息。

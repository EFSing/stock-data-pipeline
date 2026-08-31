# Holdings Data Manager

`holdings_data_manager.py` 是持仓数据生命周期的薄编排层。它只处理单一规范化标的，复用现有行情 provider、`core` 质量门控、Google Sheets 表头和 `upsert_history` 写入；不会调用完整 `main.py --mode full`，也不会进入 SETUP、Decision、Risk 或研究路径。

## 状态与事实源

当前持仓集合仍由 `自选清单.启用` 表达，证券身份和数据源映射仍由同一行表达。`历史行情_未复权`、`历史行情_前复权`、`校验记录` 与 `运行日志` 是独立的历史/审计事实；CLOSE 只停用当前视图，不物理删除任何历史数据。历史 upsert 身份键为 `市场+统一代码+交易日期`，不会因不同市场使用相同代码而互相覆盖。未知的 `自选清单` 列保持原样，不被解释或覆盖。

`运行日志` 复用既有表头承载 append-only 生命周期审计：北京时间 `运行时间`、市场、规范化统一代码、动作/结果（写入 `消息`）和历史写入行数。没有新增 Sheet 列或 registry。

## 操作 contract

| 操作 | 已有身份 | 历史行为 | 启用语义 |
|---|---|---|---|
| `ADD` | 已启用时幂等；已停用时自动采用 REENTER 语义 | 新身份初始化一年；已停用身份只补缺口 | 双历史成功后设为启用 |
| `REENTER` | 必须已存在 | 只补 raw/qfq 缺口；完整覆盖不重抓一年 | 双历史成功后恢复启用 |
| `CLOSE` | 不存在/已停用幂等 | 不访问、不删除历史 | 仅设为停用 |
| `SYNC` | 必须已存在 | 只补缺口 | 保持原状态 |

目标窗口从最近已完成市场交易日向前回溯一个自然年；raw/qfq 均须达到该窗口边界。规范化失败、市场冲突、未知数据源、重复日期、越界/异常 OHLC、latest/history provider 失败或覆盖不足均不得错误启用标的。

## Coverage 与 exchange session

`history_coverage_report()` 是确定性的 coverage/QC contract：它只看 provider 与已有历史的 observed session dates，从不把周一至周五当作交易所日历。raw/qfq 必须拥有相同且无重复的日期集；每套历史必须在目标末日结束、起点最多落后 7 个自然日、至少有 180 个有效日线 bar，并且相邻 observed session 的自然日间隔不得超过 14 天。首尾两根、中间大段缺失、provider 截断最近 N 日、raw/qfq 日期集不一致都会 fail closed；正常节假日导致的短闭市区间合法，不生成休市日 bar。

`REENTER`/`SYNC` 通过 observed session dates 计算边界和中段 gap：仅抓尾部缺口或异常中段区间，完整一年不因 US/CN 节假日重复请求。补齐后的 raw/qfq 仍需整体 coverage/QC 通过，之后 `ADD` 首次或停用身份自动恢复才会写 `自选清单.启用=True`。只读验证可运行 `scripts/holdings_data_manager_smoke.py`；该脚本不写 Sheet、不进入任何策略/研究路径。

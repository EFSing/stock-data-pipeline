# 股票行情数据中台自动更新程序

该项目在各市场收盘后抓取免费公开行情，将结果写入固定的 Google Sheet，并对最新日线执行双源校验。

## 默认数据源

| 市场 | 主数据源 | 校验数据源 |
|---|---|---|
| A股 | yfinance | BaoStock |
| 港股 | yfinance | 腾讯／新浪 |
| 美股 | yfinance | 腾讯／新浪 |
| 日股 | yfinance | 暂无免费稳定校验源 |
| 瑞典股 | yfinance | 暂无免费稳定校验源 |

A股、港股或美股的历史来源重试失败，或者虽然成功返回但最新日期落后于收盘后的目标交易日时，程序会将该来源判定为失效，并使用腾讯与新浪实时行情接口补充最新未复权快照。两者不提供历史日线及前复权序列，因此只作为正式收盘校验或当日收盘应急源。美股解析只读取常规交易时段收盘字段，不会把盘前或盘后价格当成正式收盘。若主源与校验源最终落到同一个快照接口，程序会标记为“单源可用”，不会误判为双源验证成功。

AKShare已从生产依赖和数据源注册表中移除。为保证旧版Google Sheet配置平稳迁移，程序仍识别配置文本`AKShare`，但只会将其改路由至yfinance、腾讯或新浪，不会导入或调用AKShare。

只有两个独立来源在同一最新已完成交易日、且收盘价差异及成交量差异均在容差内，并且最新有效 source date 不早于 ordinary-calendar freshness guard，才会在“最新行情”中标记为“已验证”和“正式收盘”。如果来源交易日不同，程序按有效交易日期优先采用更新来源，但保持“待复核”，并明确记录“最新交易日仅单源可用”；不会把它升级为已验证数据。ordinary-calendar guard 只用于 freshness proof：收盘前使用最近前一 weekday，收盘后使用当天，周末使用最近 Friday，不推断交易所节假日。双源共同停在 guard 之前时行情可保留显示，但必须待复核；未来日期仍 fail closed。

## 执行模式

定时亚洲/欧美 workflow 使用 `latest` 模式：只抓取短窗口最新行情、执行 source-date freshness/双源校验、更新 `最新行情`，并写入必要的 `校验记录` 与 `运行日志`。它不会抓取多年历史或 qfq，不运行 SETUP_03/Decision，不写历史行情表；运行摘要必须显示 `history_rows_written=0`。

需要历史行情、qfq 或策略展示时，手动使用 `full` 模式：

```bash
python main.py --group all --mode full
```

需要查看启用持仓的波浪结构上下文时，手动运行只读 shadow workflow：

```bash
python -m scripts.run_wave_shadow --group all
```

Wave shadow 使用 `WAVE-SCENARIO-ENGINE-2026-08-30-v1`，输出 weekly/daily
state、主/备选情景、confirmed Swing、Fib 候选区间、结构失效位以及
`SETUP_01`/`SETUP_02` context。它只读 Google Sheets 和 qfq 历史，生成
JSON/CSV artifact，不写 Sheet、交易决策、ENTRY 或生产配置。

`workflow_dispatch` 默认是 `latest`，仅手动选择 `full`；daily schedule 始终强制 `latest`。

## 持仓数据生命周期 Skill

上层 ChatGPT/Codex Skill 的规范位于 [`skills/holdings-data-manager/SKILL.md`](skills/holdings-data-manager/SKILL.md)，业务实现位于 [`holdings_data_manager.py`](holdings_data_manager.py)。它只处理单一标的的 `ADD`、`REENTER`、`CLOSE`、`SYNC`：

- “添加 MU”“我买了 512400” → 规范化身份，首次补最近已完成交易日向前一个自然年 raw/qfq 历史，成功后启用；
- “重新买回 INTC” → 只补现有历史缺口，完整覆盖时不重抓一年；
- “NOK 已清仓” → 仅停用 `自选清单.启用`，永久保留历史和数据源映射；
- 歧义、provider/history 失败、重复日期或质量不满足时 fail closed，不猜 ticker/provider，不触发完整 `full` pipeline 或任何策略路径。

历史 coverage 只使用 provider 观测到的 session dates：raw/qfq 日期集必须一致、无重复、覆盖目标末日、至少 180 个有效日线 bar，且不能出现超过 14 个自然日的异常中段 gap；不把 weekday 当交易所日历，也不为节假日补 bar。已停用身份收到 `ADD` 时自动按 REENTER 语义补缺口并恢复启用。

该路径复用现有 provider、日期/OHLCV 质量门控、Google Sheets schema 和幂等历史写入；不读取账户数量、成本、NAV、盈亏，也不访问真实券商账户。详见 [`docs/HOLDINGS_DATA_MANAGER.md`](docs/HOLDINGS_DATA_MANAGER.md)。

可用 `python scripts/holdings_data_manager_smoke.py` 对默认 `512400.SH` 做真实 provider raw/qfq 一年只读 smoke；脚本不写 Google Sheets，也不触发 SETUP/Wave/Decision/research。

## Google Sheet结构

- `自选清单`：标的代码及数据源映射。
- `最新行情`：每个标的最新一条未复权日线。
- `历史行情_未复权`：用于最新价格、成交量及缺口分析。
- `历史行情_前复权`：用于均线、波浪和斐波那契分析。
- `校验记录`：两个来源逐次比对结果。
- `运行日志`：任务时间、状态及错误信息。
- `参数设置`：价格和成交量容差、历史长度等参数。

## 一次性部署

1. 在 Google Cloud 创建服务账号，并启用 Google Sheets API 与 Google Drive API。
2. 将目标 Google Sheet 共享给服务账号邮箱，权限设为“编辑者”。
3. 将本压缩包解压后的内容放在 GitHub 仓库根目录，保留`.github/workflows`目录。
4. 在仓库的 `Settings → Secrets and variables → Actions` 中增加：
   - `GOOGLE_SHEET_ID`：Google Sheet网址中`/d/`与下一个`/`之间的ID。
   - `GOOGLE_SERVICE_ACCOUNT_JSON`：服务账号JSON密钥的完整内容。
5. 在`Actions`页面手动运行一次`亚洲市场收盘更新`和`欧美市场收盘更新`。

此后任务会在工作日自动运行：

- A股／港股／日股：`10:30 UTC`，即北京时间`18:30`。
- 美股／瑞典股：`22:30 UTC`；兼容夏令时和冬令时，均晚于常规交易时段收盘。

节假日仍可能触发任务，但数据交易日期不会前进；程序会保留最近已完成交易日，并记录运行日志。

## 本地运行

```bash
python -m pip install -r requirements.txt
export GOOGLE_SHEET_ID="你的表格ID"
export GOOGLE_SERVICE_ACCOUNT_JSON='服务账号JSON内容'
python main.py --group all --mode latest
```

只测试校验逻辑而不访问网络或Google Sheet：

```bash
python main.py --fixture
python -m unittest discover -s tests -v
```

## 使用边界

这些数据源均为免费公开数据，可能因上游网站改版、限流或节假日更新时间变化而暂时失败。程序的处理原则是：宁可标记“待复核”，也不把未确认数据当作最新正式收盘。

## 多设备 / 多会话开发交接

新电脑、新 clone 或新 Codex 会话开始时，按顺序读取：

1. `HANDOFF.md`：当前可执行交接快照；
2. `docs/CURRENT_STATUS.md`：正式项目状态；
3. `docs/DECISION_LOG.md`：长期决策及理由；
4. 当前任务相关的 architecture / protocol / governance 文件。

随后必须核对真实 Git、远端 PR、CI、artifact 和 hash。文档与客观状态冲突时，标记 `PROJECT_GOVERNANCE_STATE_CONFLICT` 并停止猜测。重要但未进入 Git 的 replay input、raw/normalized data 或其他 artifact，遵循 [`docs/FROZEN_ARTIFACT_POLICY.md`](docs/FROZEN_ARTIFACT_POLICY.md)，并以 [`docs/FROZEN_ARTIFACT_REGISTRY.json`](docs/FROZEN_ARTIFACT_REGISTRY.json) 为机器可读登记表。

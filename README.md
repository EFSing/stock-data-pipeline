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

只有交易日期一致、收盘价差异及成交量差异均在容差内的数据，才会在“最新行情”中标记为“已验证”和“正式收盘”。单一来源可用时只标记为“单源可用”，不会升级为已验证数据。

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
python main.py --group all
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

# 股票行情数据中台自动更新程序

该项目在各市场收盘后抓取免费公开行情，将结果写入固定的 Google Sheet，并对最新日线执行双源校验。

## 默认数据源

| 市场 | 主数据源 | 校验数据源 |
|---|---|---|
| A股 | AKShare | BaoStock |
| 港股 | AKShare | yfinance |
| 美股 | yfinance | AKShare |

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
   - `GOOGLE_SERVICE_ACCOUNT_JSON`：服务账号JSON密钥的完整内容。

目标表格 ID 已写入工作流，无需再单独配置。若以后更换表格，只需修改两个工作流中的 `GOOGLE_SHEET_ID`。
5. 在`Actions`页面手动运行一次`亚洲市场收盘更新`和`美股收盘更新`。

此后任务会在工作日自动运行：

- A股／港股：`08:45 UTC`，即北京时间`16:45`。
- 美股：`22:30 UTC`，兼容夏令时和冬令时，均晚于常规交易时段收盘。

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

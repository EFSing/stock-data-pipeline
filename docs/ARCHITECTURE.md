# ARCHITECTURE.md — 系统真实架构

本文件描述**真实代码**，不是理想架构。任何重构后必须同步更新本文件。

## 数据流

```text
GitHub Actions scheduler (cron)
        ↓
main.py  (CLI 入口: --group asia|us|all, --fixture)
        ↓
SheetsClient.config() / records("自选清单")          ← Google Sheets
        ↓
对每个自选标的 (启用=True 且市场∈目标组):
    expected_latest_trade_date()                    [core]
    fetch_with_retry(主数据源)                       [providers]
    fetch_with_retry(校验数据源)                     [providers]
        → yfinance → YahooChart 回退
        → BaoStock (仅 A股)
        → Tencent / Sina 快照回退 (CN/HK/US)
        ↓
    validate_quotes(primary, verifier)              [core]
    quote_sanity_issue(chosen)                      [core]
    fresher_quote(primary, verifier)                [core]
    select_history_series(...)                      [main]
    fetch_with_retry(历史数据源, "qfq")             [providers]
        → 仅 yfinance / BaoStock；不使用快照源
    confirmed close + qfq末日一致                    [main gate]
        → evaluate_setup03_event()                   [trading.events]
            → detect_platform_breakout()             [trading.setup]
            → 仅最新bar首次CONFIRMED且未发布时
               decide_platform_breakout()            [trading.decision]
        ↓
    SheetsClient.upsert_latest("最新行情")
    SheetsClient.upsert_history("历史行情_未复权")
    SheetsClient.upsert_history("历史行情_前复权")
    SheetsClient.upsert_decisions("交易决策")
    SheetsClient.append_rows("校验记录")
    SheetsClient.append_rows("运行日志")
```

## 目录结构（扁平，未使用 src/ 包布局）

```text
.
├── .github/workflows/
│   ├── asia-close.yml        # 亚洲收盘任务 (CN/HK/JP)
│   ├── us-close.yml          # 欧美收盘任务 (US/SE)
│   └── setup03-replay.yml    # SETUP_03 手动只读历史回放
├── .devcontainer/
│   └── devcontainer.json     # GitHub Codespaces / VS Code Dev Container
├── AGENTS.md                 # AI 开发人员项目规则
├── docs/                     # 项目共享上下文（本文件所在）
├── core.py                   # 数据模型与校验逻辑（无外部依赖）
├── main.py                   # CLI 入口与流水线编排
├── providers.py              # 行情数据源适配器与回退链
├── sheets_client.py          # Google Sheets 客户端与表头定义
├── scripts/
│   └── run_setup03_replay.py # 读取真实配置并输出 SETUP_03 回放 artifact
├── trading/                  # Trading Core 与只读诊断
│   ├── models.py             # 数据模型 + 输入校验
│   ├── indicators.py         # Wilder ATR / RSI、EMA
│   ├── swing.py              # causal pivot 状态机
│   ├── structure.py          # Market Structure
│   ├── fibonacci.py          # Fibonacci levels
│   ├── risk.py               # R/R + Position Size
│   ├── setup.py              # SETUP_03 Platform Breakout
│   ├── decision.py           # SETUP_03 Decision Engine
│   ├── events.py             # 生产/回放共享的终态事件语义与幂等键
│   └── replay.py             # SETUP_03 Historical Replay & Diagnostics（只读）
├── README.md
├── requirements.txt
├── .gitignore
└── tests/test_validation.py  # unittest 测试
```

## 模块职责

### core.py

- `Quote` / `ValidationResult` 数据类
- `validate_quotes()`：双源校验（日期、收盘价、成交量容差）
- `relative_diff()`、`fresher_quote()`、`latest_quote()`
- `market_close_confirmed()`、`expected_latest_trade_date()`：收盘时间与时区判断
- `quote_sanity_issue()`：OHLCV 字段一致性检查
- 依赖：仅标准库

### providers.py

- `PROVIDERS` 注册表：`BaoStock`、`Tencent`、`Sina`、`yfinance`
- `fetch_with_retry()`：按回退链抓取并重试，支持 `target_trade_date` 过期判断
- `_configured_source_candidates()`：数据源回退链 + AKShare 遗留别名路由
- `fetch_yfinance()`：yfinance，失败回退 `_fetch_yahoo_chart()`（无 cookie 的 chart 端点）
- `fetch_tencent()` / `fetch_sina()`：实时快照解析（含美股常规交易时段字段处理）
- `fetch_baostock()`：A股历史（仅 CN）
- 依赖：标准库；baostock / pandas / yfinance 均按需惰性导入

### sheets_client.py

- `SheetsClient`：gspread 封装，凭证来自环境变量 `GOOGLE_SHEET_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON`
- `records()` / `config()` / `upsert_latest()` / `upsert_history()` / `upsert_decisions()` / `append_rows()`
- `_clean()`：datetime → Google Sheets 数值（北京时间序列号）
- 各表表头常量：`LATEST_HEADERS` / `HISTORY_HEADERS` / `DECISION_HEADERS` / `VALIDATION_HEADERS` / `LOG_HEADERS`
- 依赖：标准库；gspread / google-auth 惰性导入

### main.py

- CLI：`--group`（asia/us/all）、`--fixture`
- `run(group)`：编排整个流水线
- `wanted_markets_for_group()`：任务组 → 市场集合
- `as_ratio()` / `as_bool()`：解析 Google Sheets 配置
- `quote_row()` / `decision_row()`：纯展示映射，不重算 Trading Core 逻辑
- `evaluate_set03_decision()`：正式收盘 + qfq 末日一致双门控后，仅发布当前最后一根 K 线首次进入 CONFIRMED 的事件
- 启动时读取 `交易决策` 已有事件键；同一标的/交易日/Setup 已存在时不重新计算 Decision，持续 CONFIRMED 状态日也不生成新行
- 单标的 Setup/Decision 异常仅写入运行日志，不中断其他标的与行情表写入
- `trading_parameters()`：从 `参数设置` 读取全部 Setup/Decision 参数，缺失时 fail fast
- 依赖：core；providers / sheets_client 惰性导入

### trading/events.py

- `terminal_event_type()`：统一判定 CONFIRMED/FAILED 是否在当前最后一根 K 线首次进入终态
- `evaluate_setup03_event()`：生产与回放共用；复用现有 Setup / Decision Engine，仅为新 CONFIRMED 事件计算 Decision；已发布事件键命中时不重算
- 不复制 Swing / Setup / Decision 公式

### trading/replay.py

- `replay_setup03_history()`：对单标的历史序列逐日回放 SETUP_03，传入 Trading Core 的输入严格为 `quotes[:i+1]`
- `replay_setup03_symbols()` / `replay_summary_rows()`：输出每标的 NONE/WATCH/ARMED/CONFIRMED/FAILED 状态日数与日期、CONFIRMED/FAILED 事件次数与日期，并统计 CONFIRMED 事件日上的 Decision 动作
- `ReplayEvent` / `replay_event_rows()`：只读终态事件流水及关键 Setup/Decision 字段
- `validate_replay_history()`：空序列、重复/乱序日期、样本不足、最新日期和异常日历缺口门控
- 只读诊断层；不写入 `交易决策` 表，不复制 Swing / Setup / Decision 交易逻辑，不修改生产参数

### scripts/run_setup03_replay.py

- 由 `.github/workflows/setup03-replay.yml` 手动触发
- 复用 `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` secrets 读取 `自选清单` 与 `参数设置`
- 使用生产参数原值和 `自选清单.历史数据源` 抓取最近 3 年前复权历史，并保留数据源原始顺序供质量门控检查
- 输出 summary / skipped / `setup03_replay_events.csv` 三类只读 CSV artifact；事件明细与 summary 均含参数哈希版本及完整参数快照，零事件运行仍可复现；不写任何生产 Sheet
- 输出 calculable/enabled 覆盖率；enabled=0 或 calculable=0 时先落诊断 artifact 再令 workflow 失败

## Google Sheets 各表（真实存在）

| Sheet | 用途 | 读取/写入 |
|---|---|---|
| `自选清单` | 标的代码与数据源映射 | 读（启用、市场、主/校验数据源、时区、收盘时间、代码字段） |
| `最新行情` | 每标的最近一条未复权日线 | 写（upsert，键=统一代码） |
| `历史行情_未复权` | 最新价格、成交量、缺口分析 | 写（upsert，键=统一代码+交易日期） |
| `历史行情_前复权` | 均线、波浪、斐波那契分析 | 写（upsert） |
| `交易决策` | SETUP_03 CONFIRMED Decision 事件流水 | 写（仅新 CONFIRMED 事件；upsert 键=统一代码+交易日期+Setup类型） |
| `校验记录` | 两源逐次比对结果 | 追加 |
| `运行日志` | 任务时间、状态、错误 | 追加 |
| `参数设置` | 容差、历史长度、Setup/Decision 显式参数 | 读 |

`参数设置` 必须显式提供以下 Trading Core 参数；值保持当前规则基线，不在 Phase 4 调参：

`setup_swing_lookback=5`、`setup_platform_window=40`、`setup_platform_tolerance_pct=0`、`setup_arm_proximity_pct=0`、`decision_swing_lookback=5`、`decision_atr_period=14`、`decision_atr_buffer=0.5`、`decision_max_chase_atr=0.5`、`decision_risk_capital=<显式风险资本>`。

### 自选清单 现有列映射（Known Issue）

`自选清单` 实际范围为 `A:O`（15 列），当前代码**只消费以下 12 列**；未消费列含义未核实，**禁止猜测**：

| 列（表头） | 消费位置 |
|---|---|
| 启用 | main.py `as_bool(watch.get("启用"))` |
| 市场 | main.py `watch.get("市场")` |
| 主数据源 | main.py / providers.py |
| 校验数据源 | main.py / providers.py |
| 历史数据源 | main.py qfq 历史与 Decision；仅允许 yfinance / BaoStock |
| 时区 | main.py `watch["时区"]` |
| 收盘时间 | main.py `watch["收盘时间"]` |
| 统一代码 | providers.py 符号转换基准 |
| 名称 | providers.py `Quote.name` |
| 币种 | providers.py `Quote.currency` |
| BaoStock代码 | providers.py `fetch_baostock` |
| yfinance代码 | providers.py `fetch_yfinance` |
| AKShare代码 | providers.py（仅遗留符号回退，不触发网络请求） |

> `历史数据源` 是新增的显式列，不得复用或猜测 A:O 中未核实列的含义。`交易决策` worksheet 与固定表头需在生产启用前预先创建。代码中仍无 `总览` 表读写逻辑。

## GitHub Actions

- `asia-close.yml`：`cron "30 10 * * 1-5"`（UTC）= 北京 18:30，运行 `python main.py --group asia`
- `us-close.yml`：`cron "30 22 * * 1-5"`（UTC），运行 `python main.py --group us`
- `setup03-replay.yml`：仅 `workflow_dispatch`，运行 `python scripts/run_setup03_replay.py`，输出只读 CSV artifact；失败时仍上传诊断文件
- `ci.yml`：PR / main push / 手动触发跑 unittest
- 环境：ubuntu-latest，Python 3.11
- Secrets：`GOOGLE_SHEET_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON`
- 当前 CI 安装依赖后运行 `python -m unittest discover -s tests -v`

## 配置文件

- `requirements.txt`：baostock、gspread、google-auth、pandas、yfinance（+ tzdata 供 Windows 本地开发）
- `.gitignore`：`__pycache__/`、`.pytest_cache/`、`.venv/`、`.env`、`service-account*.json`
- 无 pyproject.toml / setup.py

## 数据源

| 市场 | 主源 | 校验源 | 快照回退 |
|---|---|---|---|
| A股 (CN) | yfinance | BaoStock | Tencent / Sina |
| 港股 (HK) | yfinance | Tencent / Sina | Tencent / Sina |
| 美股 (US) | yfinance | Tencent / Sina | Tencent / Sina |
| 日股 (JP) | yfinance | 无 | 无 |
| 瑞典股 (SE) | yfinance | 无 | 无 |

## 模块依赖

```text
main.py ──→ core.py
main.py ──→ providers.py   (惰性)
main.py ──→ sheets_client.py (惰性)
providers.py ──→ core.py
tests/test_validation.py ──→ core / main / providers / sheets_client
```

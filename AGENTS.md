# AGENTS.md — AI 开发人员项目规则

> 本文件是所有 AI 开发工具（DeepSeek、Codex、ChatGPT 等）协作开发本项目的统一规则与唯一入口。
> **GitHub 仓库是本项目唯一可信事实来源，聊天记录不是项目记忆。** 不要在每次对话中重新设计整个系统。

## 项目总体策略身份与层级

本项目不是单一 Platform Breakout 系统。长期总体交易框架的唯一正式事实源是 `docs/TRADING_SYSTEM_SPEC.md`，总体主线为：

`Weekly State → Daily State → Swing → Wave Scenario → Fibonacci → Setup → Entry / Decision → Invalidation / Target → Risk / Position Management → Exit`

第一版四类 Setup：

- `SETUP_01` = Wave 2 → Wave 3
- `SETUP_02` = Wave 3 Continuation
- `SETUP_03` = Platform Breakout
- `SETUP_04` = Extreme Fear Reversal

`SETUP_03` 只是四类 Setup 之一。任一 Setup 当前开发深度、commit 数量或 Phase 数量，不得被解释为项目总体策略或优先级已经改变。Wave Scenario Engine、`SETUP_01`、`SETUP_02` 属于总体核心路线。除非用户明确批准，并记录在 `docs/DECISION_LOG.md`，否则不得擅自改变总体路线。本文件不复制完整 `TRADING_SYSTEM_SPEC`，避免双事实源。

## 新会话启动与交接治理（必须遵守）

每个新电脑、新 clone 或新 Codex 会话，在实现、研究、数据访问或修改前必须按以下顺序执行：

1. 读取根目录 `HANDOFF.md`，了解当前唯一主任务、边界和可直接执行的下一步。
2. 读取 `docs/CURRENT_STATUS.md`，了解正式项目状态。
3. 读取 `docs/DECISION_LOG.md`，了解仍然有效的历史决策与理由。
4. 读取与当前任务直接相关的 governance / protocol / architecture 文件。
5. 核对真实 Git、远端 PR、CI、artifact 和 hash 状态；不得以聊天记录或旧的本地 remote-tracking ref 代替远端事实。

如果治理文件与客观 Git / PR / CI / artifact 证据冲突，状态必须标记为
`PROJECT_GOVERNANCE_STATE_CONFLICT`，停止继续实现，先用客观证据完成核对；不得自行猜测哪个状态正确。

治理文件记录 latest substantive implementation/source head，以及与之对应
的业务状态、protocol、决策和 next action；不得要求它们保存“包含它自身的
最终 commit SHA”，因为这是不可满足的自引用条件。当前 PR final tip、
exact-head CI、mergeability 与 merge commit 必须在需要时从 GitHub 实时核验。
docs-only governance commit 不要求文件记录其自身 SHA。`HANDOFF_CURRENT_AND_CONSISTENT`
表示业务状态、protocol、source head、决策和 next action 与真实 repo 一致；
PR final tip/CI 由实时 GitHub verification 提供。不得为了更新文件自己的
SHA 制造无限 docs-only commit。

真实持仓 shadow 必须与 generic operational shadow 分离：
`GENERIC_OPERATIONAL_SHADOW` 使用 synthetic / controlled public fixture，是
默认产品/工程 gate；`REAL_HOLDINGS_SHADOW` 的 classification 固定为
`OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 status 为
`NOT_RUN_USER_PRIVACY`。缺少真实持仓不得写成 SETUP_01
research/development 的默认 blocker。未经明确 production milestone scope
授权，不得读取真实持仓，也不得将任何 holdings-derived 数据输出到
GitHub Actions；不得把账户 holdings secrets 注入 generic shadow 或普通 CI。

每完成一个具有独立意义的逻辑任务，或准备报告 `TASK_COMPLETE`、`PHASE_COMPLETE`、`PR_FULLY_READY`、`READY_FOR_REVIEW`、`READY_FOR_DECISION` 前，必须更新 `HANDOFF.md`，并确认其状态为 `HANDOFF_CURRENT_AND_CONSISTENT`。

## 每次修改代码之前（必须按顺序）

1. 阅读本文件 `AGENTS.md`
2. 阅读 `docs/CURRENT_STATUS.md`（了解项目当前进展）
3. 根据任务阅读相关设计文档（`docs/ARCHITECTURE.md`、`docs/TRADING_SYSTEM_SPEC.md`、`docs/DECISION_LOG.md`）
4. 全仓库搜索是否已有相同或相近职责的实现（模块/函数/数据模型）；优先复用、扩展或抽象现有实现，不得为方便在新模块中复制已有业务逻辑，公共计算逻辑必须保持 Single Source of Truth
5. 阅读相关源代码
6. 阅读相关测试（`tests/`）

## 任何修改禁止

- 引入未来函数（look-ahead bias）：`signal(t)` 只能使用 `data <= t`
- 使用未来 Swing
- 使用未来 ZigZag 节点产生过去信号
- 擅自改变交易系统核心规则（见 `docs/TRADING_SYSTEM_SPEC.md`）
- 在代码中保存 API Key / Token / 凭证（一律使用 GitHub Secrets / Codespaces Secrets / 环境变量）
- 在 `devcontainer.json` 中使用 `${localEnv:...}` 映射或硬编码任何凭证
- 自动连接券商下单
- 无理由重写已经稳定工作的行情模块（`core.py` / `providers.py` / `sheets_client.py`）
- 为提高回测结果人为删除失败交易
- 为达到目标 R/R 人为制造目标价

## 修改完成必须

1. 运行测试：`python -m unittest discover -s tests -v`
2. 增加必要测试
3. 更新 `docs/CURRENT_STATUS.md`
4. 重要设计变化写入 `docs/DECISION_LOG.md`
5. 给出修改文件列表
6. 给出测试结果
7. 给出剩余风险

## 项目技术约定（以当前真实代码为准）

- 测试框架为 `unittest`（尚未迁移 pytest）；新测试沿用 `unittest` 风格，迁移 pytest 需单独 PR。
- 依赖清单在 `requirements.txt`（无 pyproject.toml）；新增运行时依赖需同步更新该文件。
- 生产运行环境为 GitHub Actions（ubuntu-latest，Python 3.11）；本地 Windows 开发需安装 `tzdata`。
- Google Sheets 凭证通过环境变量 `GOOGLE_SHEET_ID`、`GOOGLE_SERVICE_ACCOUNT_JSON` 注入，禁止写入仓库。
- 凭证注入通道固定为：GitHub Actions → Actions Secrets；Codespaces → Codespaces Secrets；本地开发 → 本机环境变量。**不通过 `devcontainer.json` 的 `remoteEnv`/`localEnv` 映射传入**，也不写入任何文档或配置文件的明文。
- 数据源回退链与双源校验是稳定逻辑，修改前必须先读 `providers.py` 与 `tests/test_validation.py`。
- 项目为扁平模块结构（根目录 `core.py` / `main.py` / `providers.py` / `sheets_client.py`），未使用 `src/` 包布局；不要仅为迎合目录规范而大规模重构。

## Git 工作流

- 不直接在 `main` 分支长期开发大型功能。
- 每个独立功能使用独立分支与 PR：如 `feat/swing-engine`、`feat/setup-engine`、`fix/data-quality`。
- PR 必须说明：`What Changed`、`Why`、`Tests`、`Risks`。

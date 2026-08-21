# AGENTS.md — AI 开发人员项目规则

> 本文件是所有 AI 开发工具（DeepSeek、Codex、ChatGPT 等）协作开发本项目的统一规则与唯一入口。
> **GitHub 仓库是本项目唯一可信事实来源，聊天记录不是项目记忆。** 不要在每次对话中重新设计整个系统。

## 每次修改代码之前（必须按顺序）

1. 阅读本文件 `AGENTS.md`
2. 阅读 `docs/CURRENT_STATUS.md`（了解项目当前进展）
3. 根据任务阅读相关设计文档（`docs/ARCHITECTURE.md`、`docs/TRADING_SYSTEM_SPEC.md`、`docs/DECISION_LOG.md`）
4. 阅读相关源代码
5. 阅读相关测试（`tests/`）

## 任何修改禁止

- 引入未来函数（look-ahead bias）：`signal(t)` 只能使用 `data <= t`
- 使用未来 Swing
- 使用未来 ZigZag 节点产生过去信号
- 擅自改变交易系统核心规则（见 `docs/TRADING_SYSTEM_SPEC.md`）
- 在代码中保存 API Key / Token / 凭证（一律使用 GitHub Secrets / Codespaces Secrets / 环境变量）
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
- 数据源回退链与双源校验是稳定逻辑，修改前必须先读 `providers.py` 与 `tests/test_validation.py`。
- 项目为扁平模块结构（根目录 `core.py` / `main.py` / `providers.py` / `sheets_client.py`），未使用 `src/` 包布局；不要仅为迎合目录规范而大规模重构。

## Git 工作流

- 不直接在 `main` 分支长期开发大型功能。
- 每个独立功能使用独立分支与 PR：如 `feat/swing-engine`、`feat/setup-engine`、`fix/data-quality`。
- PR 必须说明：`What Changed`、`Why`、`Tests`、`Risks`。

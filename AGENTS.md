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

Git / GitHub 负责动态工程事实：branch、HEAD、PR、commit、diff、CI 的唯一实时
事实源是仓库本身，不是治理文档。治理文档不长期镜像 main SHA、PR final tip、
CI run ID、mergeability 等易变信息；需要时一律从 GitHub 实时核对，不得以聊天
记录或旧的本地 remote-tracking ref 代替远端事实。

`HANDOFF_CURRENT_AND_CONSISTENT` 只表示：当前 HANDOFF 能正确恢复当前开发现场；
`docs/CURRENT_STATUS.md` 与当前系统能力没有实质矛盾；长期 Decision 与当前实现
没有已知冲突；不存在会让下一台设备错误继续开发的重大状态错误。它不要求文档
保存实时 main SHA、exact-head CI run、docs-only commit 后重新完整验证，也不要求
历史 Event 记录逐项相互一致。

`PROJECT_GOVERNANCE_STATE_CONFLICT` 只用于可能真正影响正确开发的问题，例如：
HANDOFF 说 PR 未合并但实际已合并且会改变下一步；CURRENT_STATUS 能力状态与代码
明显不一致；DECISION_LOG frozen semantics 与当前实现冲突；当前 branch 有重要
未提交工作且新设备可能覆盖；或治理指示会造成生产／研究语义错误。docs-only
commit 改变 HEAD、CI run ID 过期、测试计数变化、merge 后旧 SHA 尚未同步、历史
Event 未同步最新动态事实等自然过期信息，不得单独升级为治理冲突。若确属真实
冲突，先用客观 Git/GitHub 证据完成核对，再标记冲突并停止猜测。

真实持仓 shadow 必须与 generic operational shadow 分离：
`GENERIC_OPERATIONAL_SHADOW` 使用 synthetic / controlled public fixture，是
默认产品/工程 gate；`REAL_HOLDINGS_SHADOW` 的 classification 固定为
`OPTIONAL_PRIVATE_OPERATIONAL_VALIDATION`，未运行时 status 为
`NOT_RUN_USER_PRIVACY`。缺少真实持仓不得写成 SETUP_01
research/development 的默认 blocker。未经明确 production milestone scope
授权，不得读取真实持仓，也不得将任何 holdings-derived 数据输出到
GitHub Actions；不得把账户 holdings secrets 注入 generic shadow 或普通 CI。

每完成一个具有独立意义的逻辑任务，或准备报告 `TASK_COMPLETE`、`PHASE_COMPLETE`、`PR_FULLY_READY`、`READY_FOR_REVIEW`、`READY_FOR_DECISION` 前，必须更新 `HANDOFF.md`，并确认其状态为 `HANDOFF_CURRENT_AND_CONSISTENT`。

## 治理文档职责与验证成本（必须遵守）

各治理文件的职责固定为：

- **Git / GitHub**：动态工程事实源。治理文档只允许在 HANDOFF 中作 branch / PR
  状态的语义描述，不得硬编码 SHA 或 CI run ID 来证明治理一致性。
- **`HANDOFF.md`**：当前开发现场恢复文件。只保留新设备 / 新 Codex 会话继续工作
  真正需要的信息（当前任务、正式状态、branch / PR 语义状态、已完成、blocker、
  下一步、未完成事项、关键约束、已知坑）。历史由 Git / PR / commit 保存，不保存
  旧 Engineering Event / Historical Event 流水账，不另建 archive。
- **`docs/CURRENT_STATUS.md`**：整个系统当前能力地图，回答“已具备什么能力、
  哪些仍在研究／未接入生产”。不保存历史 PR 过程、blocker 演变、测试数量、
  CI run ID、commit SHA 或 Engineering Event 流水账。
- **`docs/DECISION_LOG.md`**：只保留长期有效、未来开发不能随意推翻的重要决策及
  理由（策略架构、T→T+1、Target-before-RR、Wave 主／备情景、Candidate 边界、
  CN / US runtime 独立、allocation_budget / Portfolio Risk 语义、look-ahead /
  OOS / production safety 等）。普通 bugfix、PR review correction、测试数量变化、
  小型 provider 细节、临时 runtime 调试结论不作为长期 Decision。

三个文件职责不重复；修改时若发现同一信息被复制到多个文件，只保留其职责所在
位置的事实源。

**验证规则（禁止 docs-only 触发高成本验证）：**

代码／研究产生实质变化时：

```text
实质修改 → 根据风险执行对应测试 / shadow → 验证通过
→ 一次性同步治理文档 → 仅执行轻量 docs closeout 检查 → 结束
```

禁止形成“代码验证 → 更新 docs → docs commit 改 HEAD → 因 HEAD 改变重新完整验证
→ 再更新 docs → 再 reconcile”的循环。

docs-only governance 更新原则上不得触发完整 unittest、完整 runtime shadow 或其他
高成本验证。docs-only 默认验证最多包括当前已有且无需新增工具的轻量检查，例如：
`git diff --check`、现有 Markdown / JSON 语法检查、必要的 grep / consistency
check。不得为了 governance 新增 validator、registry、state machine、protocol、
CI workflow 或测试框架。

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

1. 实质代码／研究修改运行 `python -m unittest discover -s tests -v`；docs-only
   修改按上文“验证规则”执行轻量检查，不重跑完整测试。
2. 实质代码／研究修改按需增加必要测试；docs-only 修改不得为此新增测试框架。
3. 系统能力发生实质变化时更新 `docs/CURRENT_STATUS.md`；普通 docs-only 同步视
   需要更新，不把历史 PR 过程写入该文件。
4. 重要长期设计变化写入 `docs/DECISION_LOG.md`；普通 bugfix、review correction、
   测试数量变化等不写。
5. 给出修改文件列表。
6. 给出验证结果（实质修改给出测试结果；docs-only 给出轻量检查结果）。
7. 给出剩余风险。

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

## Engineering Simplicity / Complexity Budget

- 默认选择“最小正确实现”，而不是“最大防御实现”。优先小改动、复用现有代码和局部修复；能改 20 行解决的问题，不得无理由重构 200 行。
- 不得为假设性的、低概率且可恢复的问题提前引入新模块、抽象层、状态机、协议、registry、shadow、gate、兼容层或恢复框架。新增复杂度必须对应当前真实需求或高代价风险。
- 新建抽象、模块或架构层之前，必须先证明现有结构无法以更简单方式正确实现；证明不了则不得新增。
- 强 fail-closed / 高强度防御仅优先用于不可逆写入、安全、资金/交易、数据污染、look-ahead、OOS 泄漏、研究结论污染等高代价场景。普通可恢复维护问题应采用简单错误处理。
- 治理强度必须与变更风险匹配。普通 bugfix、格式、映射、字段、轻量功能不得自动升级为新 Phase、Protocol、Decision、Shadow 或大规模治理流程。
- 测试只优先覆盖用户可见行为、关键不变量和真实高价值回归；禁止为了提高测试数量而测试大量内部实现细节。测试数量不是目标。
- 避免 scope creep。完成当前明确需求后停止；发现邻近问题时，除非它直接阻塞正确性，否则记录而不是顺手扩大任务。
- 当“更稳健”与“明显增加维护复杂度”冲突时，优先选择足够稳健且更简单、可理解、可维护的方案。

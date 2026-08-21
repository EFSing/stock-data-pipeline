"""Trading Core Phase 1 — 技术特征 / Swing / Market Structure / Fibonacci / R&R / Position Size。

本包为纯计算层：输入 `list[core.Quote]`（已按 `trade_date` 严格升序），
不依赖 `main` / `providers` / `sheets_client`，不发起网络或写入 Google Sheets。

核心不变式（见 AGENTS.md 与 TRADING_SYSTEM_SPEC.md）：
- `signal(t)` 只能使用 `data <= t`，禁止未来函数。
- Swing 区分 `PROVISIONAL` / `CONFIRMED`；历史决策只能用 `confirmed_index <= t` 的 Swing。
"""

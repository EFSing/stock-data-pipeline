# Holdings command bus v1

This is the controlled execution boundary from an approved ChatGPT/Codex
request to the existing `HoldingsDataManager`. It is a GitHub Issue event bus,
not an MCP integration and not a second holdings implementation.

## Flow

```text
ChatGPT/Codex
    -> one GitHub Issue with exact title and strict JSON body
    -> issues.opened workflow in EFSing/stock-data-pipeline
    -> event + sender/actor + schema guards
    -> existing identity normalization
    -> dry-run receipt, or (future reviewed enablement) HoldingsDataManager.execute
    -> machine-readable + human-readable comment
    -> result label and issue close
```

The checked-in workflow has `HOLDINGS_COMMAND_BUS_LIVE_WRITES=disabled`.
The dry-run job receives no Google credentials: it has no Google secret
mappings and does not pass credentials by another channel. `dry_run=false`
still fails closed before a `SheetsClient` or `HoldingsDataManager` can be
constructed. Enabling live writes is a separate, reviewed change that must
design and review secret injection before it can pass credentials to the
existing `SheetsClient` path.

Invariant: `DRY_RUN_COMMAND_BUS_HAS_NO_GOOGLE_SECRETS`.

The workflow job also fails closed before Python starts unless the event is
from this governed repository, is a non-PR issue, and has `EFSing` as the
workflow actor, event sender, and Issue user. Python retains the authoritative
second validation of the same allowlist and event envelope.

Future live enablement prerequisite:
`LIVE_WRITE_CONCURRENCY_SERIALIZATION_REQUIRED_BEFORE_ENABLEMENT`. Multiple
live command jobs must not modify the same holdings state out of order; this
PR does not implement live concurrency or enable writes.

## Command body

The title must be exactly `[HOLDINGS_COMMAND]`. The body must be one JSON
object with no Markdown fence, prose, duplicate keys, unknown keys, or trailing
command data:

```json
{
  "version": 1,
  "operation": "ADD",
  "symbol": "MU",
  "market": "US",
  "request_id": "chatgpt-20260831-0001",
  "dry_run": true
}
```

Required fields are `version`, `operation`, `symbol`, `request_id`, and
`dry_run`. `market` is optional. `operation` is exactly one of `ADD`,
`REENTER`, `CLOSE`, and `SYNC`; one command contains one symbol string only.
`request_id` is bounded to ASCII letters, digits, `.`, `_`, and `-` for safe
receipts. `dry_run` is explicit and boolean. The event guard additionally
requires `issues.opened`, the exact repository, the exact title, a non-PR
issue, and the allowlisted repository owner `EFSing` as matching issue user,
sender, and workflow actor.

## Receipt and safety

The workflow writes a comment containing the `holdings-command-result:v1`
marker, canonical JSON, and a bounded human summary. It reports only the
request ID, operation, normalized symbol, market, status, enabled state,
history rows written, and message. It never reports account count, cost, NAV,
P&L, or broker information. The Issue body is read only from
`GITHUB_EVENT_PATH`; it is never interpolated into shell, Python source, or a
command argument. The result relay reads only the bridge-produced receipt.

All schema, identity, provider, QC, and lifecycle failures return a
fail-closed `FAILED` receipt. The Python bridge does not reproduce history,
normalization, QC, or Sheets logic. A future live path calls only
`HoldingsDataManager().execute(operation, symbol, market)`.

Transport reruns do not create a second business truth source. Existing manager
semantics remain authoritative: history upsert identity is
`市场+统一代码+交易日期`, ADD is idempotent for an enabled identity, CLOSE only
changes `自选清单.启用` and never deletes history, REENTER/SYNC fetch only
observed-session gaps, and Sheets upsert is key-idempotent. The manager
regressions plus command-bus fixture tests cover these boundaries.

## Dry-run verification

Run the focused fixture suite locally:

```bash
python -m unittest tests.test_holdings_command_bus -v
```

It supplies a checked-in-style `issues.opened` payload, verifies strict schema
and sender/actor guards, runs event parsing through identity normalization,
asserts no `SheetsClient` or manager construction in dry-run, and checks the
exact receipt/comment shape. The full repository suite remains the required
CI gate. No real ADD/CLOSE is run at this review node.

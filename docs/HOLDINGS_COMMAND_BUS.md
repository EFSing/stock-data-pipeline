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
    -> dry-run receipt, or (strictly authorized live route) HoldingsDataManager.execute
    -> machine-readable + human-readable comment
    -> result label and issue close
```

The checked-in workflow routes through a no-secret validation step first.
`dry_run=true` and invalid routes execute with
`HOLDINGS_COMMAND_BUS_LIVE_WRITES=disabled` and receive no Google credentials,
preserving the invariant below. Only a strictly validated `dry_run=false`
route enters the live step, where the existing GitHub Actions Secrets are
passed as environment variables to the bridge. The bridge still defaults to
fail closed, requires both credential values before manager construction, and
delegates the live operation only to the existing `SheetsClient` path owned by
`HoldingsDataManager`.

The live route is enabled for an explicit, unambiguous user-requested holdings
data mutation such as ADD/买入/新增, REENTER/重新买回, or CLOSE/清仓. Questions,
assumptions, demonstrations, or ambiguous identity/market/operation requests
must not use live write and remain dry-run or fail closed. The command schema
and version remain v1.

Invariant: `DRY_RUN_COMMAND_BUS_HAS_NO_GOOGLE_SECRETS`.

The workflow uses a non-canceling concurrency group for command jobs so live
operations do not run concurrently against the same holdings state. This is
transport serialization only; it is not a new holdings registry or database.

The workflow job also fails closed before Python starts unless the event is
from this governed repository, is a non-PR issue, and has `EFSing` as the
workflow actor, event sender, and Issue user. Python retains the authoritative
second validation of the same allowlist and event envelope.

The implementation remains bounded to the existing v1 command schema and
allowlist. No request ledger or transport database is added; reruns continue
to rely on the existing manager's idempotent history/watchlist semantics.

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
normalization, QC, or Sheets logic. The live path calls only
`HoldingsDataManager().execute(operation, normalized_symbol, market)`; a
manager `FAILED` result is relayed as `FAILED` and never claims an enabled
state.

Transport reruns do not create a second business truth source. Existing manager
semantics remain authoritative: history upsert identity is
`市场+统一代码+交易日期`; ADD/REENTER complete latest snapshot, matching-date
raw/qfq history QC, latest upsert, validation append, and enable-last in one
operation. An enabled repeated ADD is idempotent only after reconciliation;
complete history is not refetched while missing/stale latest or validation is
repaired. CLOSE only changes `自选清单.启用` and never deletes history,
REENTER/SYNC fetch only observed-session gaps, and Sheets upsert is key-idempotent.
The manager regressions plus command-bus fixture tests cover these boundaries.

## Dry-run verification

Run the focused fixture suite locally:

```bash
python -m unittest tests.test_holdings_command_bus -v
```

It supplies a checked-in-style `issues.opened` payload, verifies strict schema
and sender/actor guards, runs event parsing through identity normalization,
asserts no `SheetsClient` or manager construction in dry-run, covers live ADD,
fail-closed actor/schema gates, manager `FAILED`, rerun/idempotency, workflow
Secret routing and output redaction, and checks the exact receipt/comment
shape. Focused and full-suite counts are recorded by the current task handoff;
local regression tests never execute a real ADD/CLOSE/REENTER/SYNC.

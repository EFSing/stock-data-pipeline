# Cloudflare market-close watchdog

This is the first independent trigger fallback for the CN/US GitHub Actions
paths. It is intentionally a trigger-only Worker: it does not call a market
provider, the VPS, Google Sheets, a broker, or any holdings API. GitHub Actions
remains responsible for exact exchange-session resolution, prospective D1
deadline enforcement, and idempotent storage.

The Worker checks the recent run state for the market's Daily Report or D1
reconciliation workflow. A recent queued/in-progress/success run is a
`NOOP_PRIMARY_ACTIVE_OR_SUCCESS`; a missing/failed/uncertain status causes one
bounded `workflow_dispatch` of the same workflow. GitHub API 429/5xx/network
errors use three bounded attempts; the token is never included in diagnostics.

Cron expressions are UTC:

| UTC cron | Market | Fallback |
|---|---|---|
| `45 9 * * 1-5` | CN | Daily Report |
| `55 10 * * 1-5` | CN | D1 prospective |
| `15 1 * * 2-6` | US | Daily Report |
| `55 1 * * 2-6` | US | D1 prospective |

## One-time account setup

1. In Cloudflare Workers create a Free-plan Worker from this directory. Do not
   enable paid Workers, Durable Objects, KV, R2, or any other paid service.
2. Set the Worker secret `GITHUB_TOKEN` to a repository-scoped fine-grained
   token for `EFSing/stock-data-pipeline` only. Required repository permission:
   `Actions: Read and write`; do not grant Contents write, Administration, or
   access to any other repository. Set an expiry and record it in the user's
   password manager; do not put it in Git or chat.
3. Set a separate random Worker secret named `WATCHDOG_SMOKE_TOKEN`. It only
   protects the optional manual `POST` smoke endpoint; do not reuse the GitHub
   token. Scheduled Cron events do not require this secret.
4. Keep the tracked `GITHUB_REPOSITORY` and `GITHUB_REF` values unless the
   repository is intentionally renamed.
5. Deploy with the normal Cloudflare Wrangler flow from this directory. The
   Worker deployer must authenticate in the Cloudflare account; no Cloudflare
   credential belongs in this repository.

From this directory, the minimal deployment commands are:

```sh
npx wrangler@latest secret put GITHUB_TOKEN --config wrangler.toml
npx wrangler@latest secret put WATCHDOG_SMOKE_TOKEN --config wrangler.toml
npx wrangler@latest deploy --config wrangler.toml
```

Each `secret put` prompt is entered locally and must not be pasted into Git or
chat. The second secret can be generated locally with `openssl rand -hex 32`.

The fallback is safe before deployment credentials exist: the source and tests
can be reviewed and run without a token. A missing token produces
`EXTERNAL_TOKEN_MISSING` and does not dispatch anything.

For a controlled live smoke test after deployment, send a `POST` request with
the separate smoke token to the deployed Worker URL, for example:

```sh
curl --fail-with-body -X POST \
  "https://<worker-subdomain>.workers.dev/?market=CN&kind=D1_PROSPECTIVE" \
  -H "Authorization: Bearer $WATCHDOG_SMOKE_TOKEN"
```

The expected result is either `DISPATCHED_RECONCILIATION` (then verify the
corresponding `workflow_dispatch` run in GitHub Actions) or
`NOOP_PRIMARY_ACTIVE_OR_SUCCESS`. The Worker still performs no market or D1
work itself.

## Rotation / recovery

Create a replacement fine-grained token with the same exact repository and
Actions permission, update only the Worker secret, verify one controlled
`POST` request or the next scheduled diagnostic, then revoke the old token.
If the GitHub API is unavailable, the VPS watchdog remains the independent
fallback; neither fallback runs market computation itself.

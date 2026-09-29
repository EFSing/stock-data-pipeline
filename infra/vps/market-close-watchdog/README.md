# Ubuntu VPS market-close watchdog

This is the second independent trigger fallback. It does not run Python market
logic, read the VPS D1 store, access holdings, or call a broker. It only checks
the recent GitHub Actions run state and dispatches the existing CN/US Daily
Report and D1 reconciliation workflows. The GitHub workflow remains the sole
business executor and owns all exact exchange-session/prospective semantics.

The watchdog uses three bounded attempts for GitHub API 429/5xx/network
failures. It never prints the token. It checks a bounded four-hour window: this
covers the later VPS check of both Daily Report and D1 primary/fallback paths
without treating the prior market session as today's run. A recent
queued/in-progress/success run is `NOOP_PRIMARY_ACTIVE_OR_SUCCESS`; missing,
failed, or uncertain status causes a single idempotent workflow dispatch.

The checked-in systemd units run as the normal user at approximately 20:05 BJT
Monday-Friday (CN) and 11:05 BJT Tuesday-Saturday (US), with at most a ten
minute randomized delay. Both are before the next exchange session opens. If a
VPS is down and `Persistent=true` causes a late run, the repository
reconciliation layer still refuses prospective backfill after the next session
opens and records `MISSED_PROSPECTIVE_SESSION`.

## One-time VPS setup

The following commands are examples to execute on the user's Ubuntu VPS after
copying this repository to `$HOME/stock-data-pipeline` (or adjusting the two
checked-in service `ExecStart` paths to the chosen non-root path). They do not
require Docker, nginx, a database, or root access.

```sh
install -d -m 700 "$HOME/.config/stock-data-pipeline"
install -m 600 infra/vps/market-close-watchdog/config.example.json \
  "$HOME/.config/stock-data-pipeline/market-close-watchdog.json"
```

Edit that private JSON file locally on the VPS. Use a separate fine-grained
GitHub token from the Cloudflare Worker when possible. The exact token scope is
repository `EFSing/stock-data-pipeline` only, `Actions: Read and write`, with
no Contents write, Administration, or other repository access. Record the
expiry date privately and rotate before expiry. Never commit the real file or
paste the token into chat.

Install the two user units and enable them without sudo:

```sh
mkdir -p "$HOME/.config/systemd/user"
cp infra/vps/market-close-watchdog/systemd/market-close-watchdog-*.service \
   infra/vps/market-close-watchdog/systemd/market-close-watchdog-*.timer \
   "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now market-close-watchdog-cn.timer market-close-watchdog-us.timer
systemctl --user list-timers 'market-close-watchdog-*'
```

If the VPS user is not logged in continuously, enable user lingering through
the VPS administrator's normal account policy; do not grant the watchdog root
privileges solely for this task. A one-shot manual smoke uses a dummy token
only against a controlled GitHub account and must not log the Authorization
header.

The monthly VPS fee and any GitHub token cost are external account matters.
This watchdog does not create Cloudflare paid resources or purchase anything.

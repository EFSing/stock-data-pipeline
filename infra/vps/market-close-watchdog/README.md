# Ubuntu VPS market-close scheduler

The six user-level systemd timers dispatch the existing GitHub Actions workflows
on `main`. GitHub Actions still performs market-data updates, Daily Report
generation and D1 reconciliation. The scheduler contacts only the GitHub API.

| Job | Beijing time | Days |
|---|---|---|
| Asia close update | 17:30 | Mon–Fri |
| CN Daily Report fallback | 17:45, 18:00, 18:30, 20:05 | Mon–Fri |
| CN D1 reconciliation | 18:40, 18:55, 20:05 | Mon–Fri |
| US close update | 08:30 | Tue–Sat |
| US Daily Report fallback | 09:15, 09:30, 10:00, 11:05 | Tue–Sat |
| US D1 reconciliation | 09:40, 09:55, 11:05 | Tue–Sat |

The successful App-triggered close on `main` also starts the corresponding
Daily Report. Fallbacks skip active reports and let a later workflow check the
report's durable final marker if a completed run could have been partial. D1
skips recent active or successful runs and applies the existing prospective
deadline in Actions. systemd does not replay missed timer slots after a reboot.

## Provision or restore

1. Use a private GitHub App installed only on this repository with repository
   `Actions: Read and write` and the required read-only Metadata permission.
   Disable webhooks. Set the repository Actions variable `VPS_SCHEDULER_BOT`
   to the App's login including `[bot]`.
2. Provision Ubuntu's Python 3.10+ and OpenSSL. Use a dedicated non-root account
   with user lingering enabled. Place the repository at
   `$HOME/stock-data-pipeline`.
3. Put the App private key in `$HOME/.config/stock-data-pipeline/`. Use directory
   mode `0700` and file mode `0600` for the JSON configuration and PEM. Copy
   `config.example.json` to `market-close-scheduler.json` there, enter the App's
   Client ID and set the key filename. Each timer run requests its own
   repository-scoped installation token in memory.

Run the following as the service account from the repository root:

```sh
python3 infra/vps/market-close-watchdog/market_close_watchdog.py \
  --config "$HOME/.config/stock-data-pipeline/market-close-scheduler.json" --check

install -d "$HOME/.config/systemd/user"
install -m 644 infra/vps/market-close-watchdog/systemd/market-close-schedule@* \
  "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
```

The check verifies the App identity and access to all six workflows without
dispatching them. Compare the printed bot login with `VPS_SCHEDULER_BOT`, and
verify the App can dispatch the repository's CI workflow before switching
production timers. Schedule the cutover between market windows. After the
workflow changes reach `main`, enable the new timers and retire the old ones:

```sh
systemctl --user enable --now market-close-schedule@{cn,us}-{close,report,d1}.timer
systemctl --user list-timers --all 'market-close-schedule@*'
systemctl --user disable --now market-close-watchdog-{cn,us}.timer
journalctl --user -u 'market-close-schedule@*' --since today
```

Remove the four Cron triggers from the deployed Cloudflare Worker. A repository
merge alone does not change the deployed Worker. Check the next natural CN/US
runs before revoking any credentials previously used by the retired triggers.
Keep the private key outside the checkout. To rotate it, provision the new PEM,
run `--check`, and then revoke the prior key in GitHub.

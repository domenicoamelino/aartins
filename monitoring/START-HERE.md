# Run history + Telegram — install on the UM870

This is an add-on to your configured ingestion package. Do not reinstall or reconfigure ingestion. This package does not include your passwords or API keys.

## 1. Extract and install

Extract `meeting-monitor-complete.zip` on the UM870 to `~/meeting-monitor` (the folder containing install.sh).

If you cloned SMARTINI’s instead, use `cd ~/smartinis/monitoring` and skip the ZIP extraction. Run the same checks and installer from that directory.

```bash
cd ~/meeting-monitor
bash -n install.sh
bash -n activate.sh
bash -n rollback.sh
bash install.sh
```

This runs the offline tests and copies new files to `~/ai-platform/ingestion-monitor`. Existing services are not changed yet.

## 2. Choose the private page password

```bash
python3 ~/ai-platform/ingestion-monitor/run_monitor.py configure
```

- Accept the detected Tailscale HTTPS address ending in `:8443`. If no address is detected, enter `https://YOUR-UM870-TAILSCALE-HOST.ts.net:8443` using your actual server hostname.
- Choose a new dashboard password, at least 12 characters. Input is hidden. This is separate from your Open WebUI password.

## 3. Set up Telegram locally

In Telegram:

1. Open the official **@BotFather** account, send `/newbot`, and follow its naming prompts.
2. Open your new bot's chat and send `/start`.
3. Keep the bot token from BotFather private. Do not paste it into this Codex chat.

On the UM870:

```bash
python3 ~/ai-platform/ingestion-monitor/run_monitor.py configure-telegram
python3 ~/ai-platform/ingestion-monitor/run_monitor.py test-telegram
```

Setup asks for the bot token with hidden input and lets you select your private Telegram chat. The test command sends one test message, even on weekends. Normal run reports are Monday–Friday only.

## 4. Activate the page and monitored ingestion

Wait until your current ingestion run is finished, then:

```bash
bash ~/ai-platform/ingestion-monitor/activate.sh
python3 ~/ai-platform/ingestion-monitor/private_web.py enable
```

Activation backs up the relevant settings, adds a small override to the existing ingestion service, and starts the dashboard. Your existing nightly timer schedule is retained. The private-web command adds ONLY a separate Tailscale Serve listener on port 8443. It refuses to replace an existing listener on that port. It does not use Funnel or change your Open WebUI listener on 443.

Open the printed HTTPS address on your computer or phone while connected to Tailscale, then sign in with the dashboard password.

## 5. Run the live check

```bash
systemctl --user start meeting-ingestion.service
python3 ~/ai-platform/ingestion-monitor/run_monitor.py status
```

The run should appear on the page. On a weekday, a service run also sends a Telegram summary, including when nothing new was indexed. If the worker is busy, expect Deferred instead of a false success. On weekends the run is still recorded, but the normal Telegram report is skipped.

For a manual monitored run WITHOUT a routine notification:

```bash
python3 ~/ai-platform/ingestion-monitor/run_monitor.py run
```

Your existing direct `ingest_meetings.py sync --apply` command still works but bypasses this run-history wrapper. Use the monitored command or the existing systemd service when you want a run recorded.

See README.md for recovery, notification delivery limitations, backups, password changes and rollback. No service on the UM870 has been changed by this chat; these commands perform installation there.

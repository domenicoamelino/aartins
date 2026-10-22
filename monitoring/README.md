# Private ingestion history and weekday Telegram reports

This package extends the existing meeting ingestion 1.0.0/1.0.1 installation targeting Open WebUI 0.12.3. It leaves the ingestion script, config.json, api-key.txt, state.json, meeting worker, proxy and existing timer schedule in place. Read START-HERE.md for installation.

## What runs where

Everything runs on your UM870. The dashboard listens on `127.0.0.1:8788` only, with no LAN/public bind. Tailscale Serve terminates HTTPS on a separate port, `8443`, and proxies to loopback. Your existing Open WebUI/meeting listener on 443 is not replaced. Tailscale must be connected on your phone; tailnet permissions must allow access to port 8443. A separate dashboard password protects run details, including from other tailnet users who can reach the node.

No Sites cloud hosting, public Funnel endpoint, AI model calls or additional vector database is introduced. Telegram receives only run status, timestamps, duration, counts, error count and your private dashboard URL. It does not receive meeting titles, transcripts, finding text, detailed errors, API keys or dashboard passwords.

The page uses no third-party scripts/fonts. It is read-only: you cannot trigger ingestion or edit configuration from it. It refreshes every 30 seconds while visible, shows a stale-data notice when refresh fails, and can filter problematic runs. The latest 200 runs are displayed; history remains in the local SQLite database without an automatic deletion policy. A warning appears when the timer is active but its most recent recorded service run started more than 30 hours ago. A newly installed monitor with no service history is not falsely reported overdue.

## Installation and service integration

The installer runs the included offline tests and creates `~/ai-platform/ingestion-monitor`, refusing to overwrite an existing directory. Initial dashboard setup creates `monitor.json` and `history.sqlite3`. Telegram setup is separate and may be done later; the page works without it.

Activation expects your existing user units from the ingestion README. It verifies the ingestion module version/interface and dashboard configuration, refuses activation during an active ingestion service run, and saves a timestamped backup under `~/ai-platform/backups/meeting-monitor-*`. The backup includes the previous effective service text, timer activity state, dashboard config and Telegram credential if configured. Keep that backup private.

The existing timer is paused briefly during activation, then restored to its previous active/inactive state. The timer file and its schedule are never replaced. A service drop-in at `~/.config/systemd/user/meeting-ingestion.service.d/monitor.conf` replaces only ExecStart and adds ExecStopPost. It calls the existing ingestion code through its verified Python interface under the same ingestion lock. The wrapper runs an apply sync with the existing configuration and writes the normal last-run.json, while recording the current result directly. It never mistakes an old successful last-run.json for the outcome of a new failed run.

The dashboard user unit is enabled as `meeting-monitor.service`. Your previous linger setup permits it to run after logout/reboot. If not already enabled and you want unattended user services, use `sudo loginctl enable-linger "$USER"`. The monitor does not silently change linger settings.

Use these commands to check the deployment:

```bash
systemctl --user --no-pager status meeting-monitor.service
systemctl --user cat meeting-ingestion.service
systemctl --user list-timers --all meeting-ingestion.timer
curl --fail --max-time 5 http://127.0.0.1:8788/health
```

The health endpoint reveals only `ok: true`; all run data requires sign-in. If the dashboard port is occupied or service validation fails, activation removes its newly added override/unit and restores the timer's prior active state. It does not alter the underlying ingestion unit. Read the error rather than retrying installation over an existing directory.

## Private Tailscale exposure

Run `python3 ~/ai-platform/ingestion-monitor/private_web.py enable` after activation. It checks that the configured hostname matches this node's Tailscale DNS name, reads current Serve state and saves it under `serve-backups/`. It refuses an existing 8443 configuration unless it is exactly this monitor's dedicated HTTPS listener. It never executes `tailscale serve reset` or enables Funnel.

If Tailscale asks you to enable HTTPS, complete its normal setup yourself, then rerun the enable command. If any command is interrupted, inspect `sudo tailscale serve status` before retrying. The enable command is idempotent when it can verify its own listener. The script uses the current Tailscale Serve CLI syntax and schema; if your version reports a different schema, it stops instead of assuming the setup succeeded.

To remove only the dedicated web listener:

```bash
python3 ~/ai-platform/ingestion-monitor/private_web.py disable
```

Disable refuses removal if port 8443 no longer matches this monitor. Do not restore an old whole-Serve snapshot over your current configuration: that could replace unrelated routes added since the snapshot. The snapshot is for inspection/recovery; normal rollback removes only the monitor listener.

## Run results

Each monitored run has its own ID, trigger, start/end times, duration, counts, error details, exit code and separate Telegram delivery state. The wrapper records Running before reading ingestion credentials or connecting to Open WebUI.

| State | Meaning |
|---|---|
| Running | Monitored ingestion is executing; latest progress text is available on the page. |
| Completed | Current sync returned without errors or deferral. Zero new files is a valid completed run. |
| Deferred | Existing ingestion reported the worker busy, or another ingestion owns the shared lock. Not a successful import. |
| Failed | Configuration, connection, source, indexing or another run error prevented completion. |
| Interrupted | The wrapper was stopped or a previous Running record had no final result. Remote processing may still finish; normal ingestion recovery still applies. |

The service retains the existing exit 75 handling for a cooperative deferral. Deferred runs wait for your next manual run or next scheduled night; no repeated daytime indexing is added. The background dashboard and monitoring records do not make ingestion faster or reserve the GPU. Existing worker-idle checks remain as before.

History begins after this add-on is activated. Old journal logs and last-run.json are not imported as if they had precise per-run records. Original direct ingestion commands and rollback commands are not automatically monitored. Use `run_monitor.py run` for a manual indexed run, or the existing `meeting-ingestion.service` for a service run.

## Telegram behavior

Create a dedicated bot with the official @BotFather account, send /start to the bot, then run configure-telegram locally. Setup verifies bot identity, reads private chats without acknowledging/consuming the updates, and asks you to select your own chat. A dedicated bot avoids conflicting with another integration's webhook/polling. No inbound bot command server or webhook is installed; this is outbound reporting only.

The token is saved in `telegram-token.txt`, with mode 600, separate from monitor.json. Browser/API responses never include the bot token, chat ID, password salt/hash or Open WebUI API key. The login password is stored as a salted PBKDF2 hash. Browser sessions expire after eight hours and disappear on dashboard restart. Sessions use HttpOnly/SameSite cookies and Secure cookies on the configured HTTPS origin.

**Routine reports are sent after each service run that finishes Monday–Friday in Europe/Amsterdam**, including failures, deferrals and successful runs with no new files. Weekend runs remain in history but skip Telegram. Starting the service manually also counts as a service run and can produce an additional weekday report. A direct `run_monitor.py run` defaults to a manual run and does not send the routine notification. There is no arbitrary daily deduplication that would hide a later failure on the same day.

`test-telegram` is an explicit connectivity test and sends a message regardless of the weekday:

```bash
python3 ~/ai-platform/ingestion-monitor/run_monitor.py test-telegram
```

The page distinguishes Telegram configuration from delivery: Configured means credentials are present, not that the most recent message was delivered. Expand each run to inspect notification status.

| Notification state | Meaning |
|---|---|
| sent | Telegram accepted the message and returned its ID; this does not prove you read it or the phone displayed a push. |
| skipped-weekend | Normal report intentionally skipped on Saturday/Sunday. |
| skipped-manual | Run invoked in manual mode, without a routine report. |
| not-configured | No Telegram destination/token is configured yet. |
| sending | Notification request is in progress. |
| uncertain | A request failed or was interrupted; acceptance cannot be assumed or ruled out. No automatic resend is made. |
| failed | Notification setup could not be read. The ingestion result remains separate. |

Notification failures do not turn completed ingestion into failed ingestion. Keys, credential-bearing URLs and provider response bodies are not logged. A timeout might follow a successful Telegram acceptance, so automatic retries could produce duplicate notifications. After checking your Telegram chat, you can explicitly retry a specific unsent/uncertain run on a weekday:

```bash
python3 ~/ai-platform/ingestion-monitor/run_monitor.py retry-notification RUN-ID
```

This command respects weekday policy and does not resend a run already marked sent. For an uncertain run, a manual retry can create a duplicate if Telegram accepted the original request. There is no automatic periodic retry timer or chat notification on every dashboard refresh.

## Status, logs and password changes

```bash
python3 ~/ai-platform/ingestion-monitor/run_monitor.py status
journalctl --user -u meeting-ingestion.service -n 80 --no-pager
journalctl --user -u meeting-monitor.service -n 40 --no-pager
```

To change/recover the page password locally without resetting run history or Telegram:

```bash
python3 ~/ai-platform/ingestion-monitor/run_monitor.py set-password
```

The command asks for a new hidden password and invalidates existing browser sessions. Do not run configure again or delete monitor.json just to change a password. To update Telegram, rerun configure-telegram with your dedicated bot token and chat; no existing ingestion key is affected.

## Interruptions, reboot and missed runs

The wrapper handles normal cancellation/termination by recording Interrupted. ExecStopPost reconciles a run killed before its final write. Dashboard startup also reconciles abandoned Running entries, only after obtaining the wrapper lock, so it does not mark an active wrapper interrupted. An interrupted notification is marked uncertain and not automatically resent.

A machine that is off cannot send its own Telegram message or serve its page. A service that never starts due to a missing unit/executable cannot record its own start. The page provides last-run timestamps, timer state and a basic overdue warning once service history exists, but independent guaranteed missed-run alerts require an external heartbeat monitor. No such external monitor is installed by this package. The existing timer's Persistent=false behavior remains unchanged, so a missed overnight run is not silently caught up during daytime.

## Backups and rollback

Keep your existing off-device backup process. This package's activation backup, ingestion snapshots and local history are local recovery aids, not off-device backup.

Monitor recovery needs `monitor.json`, `telegram-token.txt` if configured, and a consistent backup of history.sqlite3. You can take a consistent SQLite snapshot with:

```bash
python3 - <<'PY'
from contextlib import closing
import datetime
from pathlib import Path
import sqlite3
root = Path.home() / 'ai-platform/ingestion-monitor'
dest = root / ('history-backup-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
with closing(sqlite3.connect(root / 'history.sqlite3')) as src:
    with closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)
dest.chmod(0o600)
print(dest)
PY
```

To remove this add-on's runtime integration while retaining the previous ingestion setup:

```bash
bash ~/ai-platform/ingestion-monitor/rollback.sh
```

Rollback refuses while an ingestion service run is active. It verifies its own drop-in, removes only its dedicated Tailscale listener, disables the dashboard, removes the ingestion ExecStart override and reloads user services. The existing timer returns to its previous active state; its schedule is retained. The original ingestion service, its API key/state, all meeting archives and history/configuration files remain. The dashboard unit is left disabled for recovery. If the listener/drop-in was changed by another administrator, rollback stops for review rather than deleting unknown configuration.

## Verification performed

See VALIDATION.txt. Offline tests use temporary databases and fake APIs; no real Telegram messages or live UM870 changes were made during development. A local browser sign-in/render check used synthetic run data, not your real meetings. Linux unit/Tailscale activation must be verified during installation on the UM870.

References: [Telegram bot setup](https://core.telegram.org/bots/tutorial), [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage), [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve).

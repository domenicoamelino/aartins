# Server operations runbook

These commands match the accepted deployment, not a hypothetical new folder layout. Run on the MINISFORUM. Secrets and meeting archives stay outside Git.

## Known paths and services

| Item | Current deployment |
|---|---|
| Worker source and settings | `~/ai-platform/transcription/meeting-worker-2.3/` |
| Python environment | `~/ai-platform/transcription/.venv/` |
| Original CLI reporter | `~/ai-platform/transcription/meeting_report.py` (separate copy) |
| Worker service | `minisforum-meetings` |
| Proxy configuration | `~/ai-platform/meeting-proxy/nginx.conf` |
| Proxy Docker container | `minisforum-meeting-proxy` |
| Open WebUI container | `open-webui`, host networking |
| Existing Open WebUI Compose project | `~/ai-platform/open-webui/` (inspect actual filenames) |
| Archives and job SQLite | `~/ai-platform/meetings/` |
| Ollama | `http://127.0.0.1:11434` |

## Before rebooting

Wait for the queue to finish if possible. A reboot interrupts active work; the worker will requeue and repeat that job from audio. Check specific job statuses or inspect the queue without exposing tokens:

```bash
~/ai-platform/transcription/.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path
p = Path.home() / 'ai-platform/meetings/jobs.sqlite3'
with sqlite3.connect('file:' + str(p) + '?mode=ro', uri=True) as c:
    for row in c.execute("SELECT id,state,detail FROM jobs WHERE state NOT IN ('completed','failed')"):
        print(row)
PY
sudo reboot
```

SSH disconnects during reboot. Reconnect using your usual Tailscale/SSH address, then:

```bash
systemctl is-active minisforum-meetings
sudo docker ps --format 'table {{.Names}}	{{.Status}}'
sudo tailscale serve status
curl --fail http://127.0.0.1:8765/health
curl --fail http://127.0.0.1:8088/meeting-proxy-health
curl --fail http://127.0.0.1:8088/api/version
curl --fail http://127.0.0.1:11434/api/tags
```

Expected: worker active/alive, both containers running, proxy ready, WebUI version, installed Ollama models. Tailscale should still proxy `/` to `http://127.0.0.1:8088`; its `--bg` configuration persists. The worker was enabled at installation and the proxy uses `unless-stopped`. Open WebUI's existing restart policy is part of its own deployment; verify it rather than assuming:

```bash
sudo docker inspect open-webui --format '{{.HostConfig.RestartPolicy.Name}}'
sudo docker inspect minisforum-meeting-proxy --format '{{.HostConfig.RestartPolicy.Name}}'
systemctl is-enabled minisforum-meetings
```

## Targeted restart and logs

```bash
# Wait for active work to finish first.
sudo systemctl restart minisforum-meetings
journalctl -u minisforum-meetings -n 80 --no-pager
journalctl -u minisforum-meetings -f
```

Ctrl+C exits the log viewer, not the service. To start an existing stopped container:

```bash
sudo docker start open-webui minisforum-meeting-proxy
```

Do not recreate Open WebUI or pull a new image merely to restart it. Preserve its volumes, accounts and installed Function/Valve settings. For Ollama inspect `systemctl status ollama --no-pager`; restart it only while no model jobs are active. Proxy diagnostics: `sudo docker logs --tail 60 minisforum-meeting-proxy`. Avoid sharing logs containing card URLs or meeting text.

## Failed report writing

The reporter intentionally fails rather than publishing unsupported decisions/citations. Audio, transcript and checked findings remain. For an existing failed job:

```bash
cd ~/ai-platform/transcription/meeting-worker-2.3
set -a
. ./worker.env
set +a
~/ai-platform/transcription/.venv/bin/python recover_meeting_job.py YOUR_JOB_ID
```

Run once for that job, while other processing is idle; keep the SSH session connected. This helper reuses saved source and compatible extraction/writing caches and marks the original job completed only after publishing a successful report. It does not repeat Whisper. If it fails, the original failed state remains available. It is intended for failures after transcript/analysis archives exist, not broken uploads or Whisper failures. For those, diagnose and submit again after fixing the cause.

Then, for a WebUI-owned job, use `status JOB_ID` with the same WebUI account. Recovery does not create a new WebUI owner. Do not resubmit the audio merely to retrieve a completed report.

## Tailscale route rollback

If the new proxy breaks browser access, restore the original direct WebUI route:

```bash
sudo tailscale serve --bg http://127.0.0.1:8080
```

This restores ordinary WebUI access but bypasses the meeting upload card route. After the proxy works, restore `sudo tailscale serve --bg http://127.0.0.1:8088`. Neither command deletes meetings.

## Backup and restore

Back up the source repository separately from private state. For a coherent meeting archive/SQLite snapshot, wait for jobs/uploads to finish, stop the worker and copy the entire meeting tree. Do this in a maintenance window; new requests cannot be accepted while it is stopped.

```bash
mkdir -p ~/ai-platform/backups
chmod 700 ~/ai-platform/backups
sudo systemctl stop minisforum-meetings
backup_name="meetings-$(date +%Y%m%d-%H%M%S).tar.gz"
(umask 077; tar -czf "$HOME/ai-platform/backups/$backup_name" -C "$HOME/ai-platform" meetings)
sudo systemctl start minisforum-meetings
```

If the archive command fails, restart the service and resolve storage problems; do not treat the failed file as a backup. Copy successful backups to a separate protected device/location and verify they can be listed/extracted in a scratch directory. A second file on the same disk does not protect against disk failure.

Privately back up `worker.env`, the service unit, proxy configuration, actual pinned image references, existing Open WebUI Compose settings and its data volume using a consistent stopped-volume snapshot. The WebUI volume holds accounts, Functions, Valve secrets and chats. Locate mounts with `sudo docker inspect open-webui --format '{{json .Mounts}}'`; do not guess a volume name. Keep backups encrypted/access-controlled and out of Git.

Restore into a separate directory first and verify contents. Stop the relevant services before restoring databases; retain the current data as a rollback copy. Restore service user ownership and private permissions, then start and run the health checks. Exact Open WebUI volume restore commands depend on the real mount configuration and are deliberately not guessed here.

## Common symptoms

| Symptom | Check/action |
|---|---|
| `../.venv/bin/python` missing | New SSH session is in home: use the documented directory and absolute Python path |
| `Load worker.env` | Source settings with `set -a` / `. ./worker.env` / `set +a` |
| WebUI package metadata missing | Use `curl http://127.0.0.1:8080/api/version`; source-based container installs may lack package metadata |
| Chat waiting interrupted | Reconnect using same account and `status JOB_ID`; backend may still run |
| Decision lacks confirmed support | Ensure reporter 2.2.4 is deployed and service restarted when idle; recover failed writer |
| Full transcript appears in chat | Replace the installed Pipe with 0.1.1; old messages do not change retroactively |
| Long wait | Check job detail and logs, CPU/RAM/model activity; do not infer failure from elapsed time alone |
| Disk fills | Stop accepting uploads, back up, inspect archives; no automatic retention/deletion is implemented |

## MVP 3.1 additions (22 October)

Retain the paths above. Knowledge is exported into each completed processed folder.
Ingestion uses `~/ai-platform/ingestion`; optional monitoring uses
`~/ai-platform/ingestion-monitor`. Neither lives in the audio-worker directory.

```bash
systemctl --user status meeting-ingestion.timer --no-pager
systemctl --user list-timers meeting-ingestion.timer --all
journalctl --user -u meeting-ingestion.service -n 60 --no-pager
systemctl --user status meeting-monitor.service --no-pager
python3 ~/ai-platform/ingestion-monitor/run_monitor.py status
```

The last two commands require installed monitoring. The existing timer is 03:00
Europe/Amsterdam; weekends still index, routine Telegram summaries skip weekends.
See [stabilization](MVP31-STABILIZATION.md) and preserve private configuration,
keys, state, snapshots, SQLite history and source archives in backups.

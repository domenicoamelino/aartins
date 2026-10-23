# MINISFORUM move: wind down, transport, resume

This runbook preserves the existing deployment. Do not update Python, packages,
models, Docker images or service paths while moving. Commands run on MINISFORUM
as um870-server unless explicitly marked Windows. Use Bash, not Ruby.

## A. Before shutdown today

1. Finish uploads/review generation and close browser upload cards. Export your
   existing Open WebUI Function from its editor as a private backup. Git source
   does not contain the Function database, valves or credentials.
2. Check jobs/review work with the supplied move_checkpoint.py helper. Copy that file to
   ~/ai-platform/move_checkpoint.py first; it is an operations helper, not a service:

```bash
~/ai-platform/transcription/.venv/bin/python "$HOME/ai-platform/move_checkpoint.py"
```

   Exit 2 means active work: wait; do not power off yet. Old waiting_upload
   records are reported but do not prevent shutdown. They may expire; create a
   fresh card tomorrow. A separate candidate-generation terminal is not tracked
   in the job queue: let that command finish too.
3. Create a private checkpoint location and record whether the timer was enabled:

```bash
checkpoint="$HOME/ai-platform/move-checkpoints/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$checkpoint"
chmod 700 "$checkpoint"
systemctl --user is-enabled meeting-ingestion.timer > "$checkpoint/timer-enabled.txt" || true
printf 'Checkpoint directory: %s
' "$checkpoint"
```

4. Pause scheduled ingestion across the move. This deliberately disables only
   the timer, not the ingestion service or stored data. Do not kill a running
   ingestion: wait for the service to become inactive before the next step.

```bash
systemctl --user disable --now meeting-ingestion.timer
systemctl --user status meeting-ingestion.service --no-pager
```

   Inactive after successful oneshot completion is normal. If active/activating,
   wait; check journalctl --user -u meeting-ingestion.service -n 50 --no-pager.
   If failed, preserve the logs/state and investigate after the move; do not reset
   state.json or ingestion.lock to hide an error.
5. Stop the idle worker, then save SQLite snapshots and source fingerprints.
   Run the check script from step 2 with --snapshot "$checkpoint". It performs
   online SQLite backup, not an unsafe standalone copy of WAL database files.
   SQLite snapshots can contain private identifiers and upload capabilities;
   keep this checkpoint private and outside Git.

```bash
sudo systemctl stop minisforum-meetings.service
~/ai-platform/transcription/.venv/bin/python "$HOME/ai-platform/move_checkpoint.py"   --snapshot "$checkpoint"
```

6. Stop the existing web containers cleanly. They will be explicitly started
   tomorrow, because a manual stop may prevent an unless-stopped auto-start.

```bash
sudo docker stop minisforum-meeting-proxy open-webui
```

7. Make/preserve a PRIVATE backup before transport. The checkpoint alone does not
   back up recordings, Open WebUI volumes, model caches or credentials. At minimum
   copy ~/ai-platform and the existing Open WebUI volume/bind data to a trusted
   separate disk using your established backup method, with containers stopped.
   To identify Open WebUI storage without exposing environment variables:

```bash
sudo docker inspect open-webui --format '{{range .Mounts}}{{println .Type .Name .Source "->" .Destination}}{{end}}'
```

   Preserve the mount backing /app/backend/data (or the deployment's actual data
   directory). Do not delete/recreate volumes. Keep private backups outside Git.
   Models and virtual environments can be re-created, but are best left untouched
   on the PC so tomorrow does not require downloads/reinstallation.
8. Shut down normally:

```bash
sudo poweroff
```

   SSH disconnect is expected. Wait until the PC has fully powered off before
   removing power, networking and peripherals. The checkpoint and Git commit do
   not make it safe to unplug a running PC.

## B. At home in NL tomorrow

1. Reconnect Ethernet/network, peripherals and power, then boot. If SSH is not
   reachable, use the local screen to establish the home network first. A new
   LAN address is normal; the existing Tailscale name/IP is usually the stable
   route. Do not reset Tailscale or recreate the proxy to fix a LAN IP change.
2. Log in and start existing infrastructure/services and containers:

```bash
sudo systemctl start docker ollama tailscaled
sudo docker start open-webui minisforum-meeting-proxy
sudo systemctl start minisforum-meetings.service
```

3. Verify health. Startup refusal may be transient; the worker check retries.

```bash
sudo systemctl --no-pager show minisforum-meetings.service   --property=ExecStart --property=WorkingDirectory --property=ActiveEnterTimestamp
curl --fail --retry 10 --retry-connrefused --retry-delay 2 http://127.0.0.1:8765/health
sudo docker ps --format 'table {{.Names}}	{{.Status}}'
curl --fail http://127.0.0.1:8088/meeting-proxy-health
curl --fail http://127.0.0.1:8088/api/version
curl --fail http://127.0.0.1:11434/api/tags
sudo tailscale serve status
systemctl --user status meeting-ingestion.timer --no-pager
```

   Worker must return ok=true and worker_alive=true; both containers must run.
   The timer should still be disabled/inactive until deliberately restored.
   Open the same HTTPS Open WebUI URL and verify login, existing chats, meetings,
   speaker corrections and Knowledge collection. No new account/collection is
   required. Check the existing monitoring dashboard if used:

```bash
systemctl --user start meeting-monitor.service
systemctl --user status meeting-monitor.service --no-pager
```

4. Run move_checkpoint.py again and compare source fingerprints and job/review
   counts with the saved checkpoint. Retrieve an existing draft with review JOB_ID.
   No model reinstallation, fresh audio upload or source deployment is needed.
5. Resume the closure checklist in MVP-CLOSURE.md. Keep nightly ingestion paused
   until the manual approval/indexing test is ready. To inspect the plan:

```bash
cd "$HOME/ai-platform/ingestion"
~/ai-platform/transcription/.venv/bin/python ingest_meetings.py sync
```

   This omits --apply and must remain a read-only plan. For the controlled live
   test, after approving the intended exact revision:

```bash
systemctl --user start meeting-ingestion.service
journalctl --user -u meeting-ingestion.service -n 80 --no-pager
```

6. Restore the nightly timer deliberately. If it was enabled before the move
   (see timer-enabled.txt) and the manual run is accepted:

```bash
systemctl --user enable --now meeting-ingestion.timer
systemctl --user list-timers --all meeting-ingestion.timer --no-pager
loginctl show-user "$USER" -p Linger
```

   Check the next run/time zone. The repository timer is 03:00 Europe/Amsterdam,
   Persistent=false: a missed run is not automatically caught up. Inspect the
   installed timer if behavior differs. User timers need a running user manager;
   if Linger=no, keep a login session or explicitly arrange lingering later.
   If the timer was originally disabled, do not enable it just because of the move.

## Recovery if something is unavailable

Worker: sudo journalctl -u minisforum-meetings.service -n 80 --no-pager.
Web: sudo docker logs --tail 50 open-webui, then minisforum-meeting-proxy.
Network: tailscale status and nmcli device status (from the local screen if needed).
Do not share worker.env, tokens, monitor.json or raw environment dumps.
Keep services/data in place and fix the specific failed health check; do not
rerun old deployment bundles, wipe job databases or pull newer container images.

## Source versus runtime paths

| Repository | Existing MINISFORUM location |
|---|---|
| Root meeting_*.py, upload.html, Pipe source | ~/ai-platform/transcription/meeting-worker-2.3/ |
| diarization-benchmark/diarize_meeting.py | ~/ai-platform/diarization-benchmark/diarize_meeting.py |
| ingestion/ingest_meetings.py | ~/ai-platform/ingestion/ingest_meetings.py |
| monitoring/ | ~/ai-platform/ingestion-monitor/ |

This mapping documents the current deployment; moving the PC does not require
copying or relocating those application files. The temporary move_checkpoint.py
helper may be removed after the restart checks.

# Operations for the reference installation

These commands assume [INSTALL.md](INSTALL.md): checkout `~/aartins`, service `aartins`, proxy container `aartins-proxy`, private data `~/aartins-data`. Original MINISFORUM users have different names/paths; use [PoC operations](POC-OPERATIONS.md) instead.

## Restart and reboot

Wait for active jobs/uploads to finish before restarting. Restart recovery requeues interrupted jobs from archived audio, rather than continuing at the exact segment/chunk.

```bash
sudo systemctl restart aartins
curl --retry 5 --retry-connrefused --retry-delay 1 --fail http://127.0.0.1:8765/health
journalctl -u aartins -n 60 --no-pager
```

After a server reboot, reconnect using your normal address and check:

```bash
systemctl is-active aartins
sudo docker ps --format 'table {{.Names}}	{{.Status}}'
curl --fail http://127.0.0.1:8765/health
curl --fail http://127.0.0.1:8088/meeting-proxy-health
curl --fail http://127.0.0.1:8088/api/version
curl --fail http://127.0.0.1:11434/api/tags
```

The worker is enabled by the install guide and proxy uses `unless-stopped`. WebUI and Ollama startup behavior belongs to their prerequisite installation. Inspect those services/policies rather than recreating containers or pulling updated images. If using Tailscale, check `sudo tailscale serve status`; otherwise inspect your HTTPS entry point.

## Recover a failed writer

```bash
cd ~/aartins
set -a
. ./worker.env
set +a
"$HOME/aartins/.venv/bin/python" recover_meeting_job.py YOUR_JOB_ID
```

Run once while other processing is idle, keeping SSH connected. It requires a failed job with transcript/analysis files and reuses checked results without repeating transcription. The original job becomes completed only after publication. For an interrupted chat use `status JOB_ID`; do not resubmit merely to retrieve a result. Failed uploads/ASR require separate diagnosis and a new submission after the cause is fixed.

## Backup

Wait for processing/uploads to finish, stop the worker and take a coherent backup of the entire private data directory, including SQLite sidecars. For the generic path:

```bash
mkdir -p ~/aartins-backups
chmod 700 ~/aartins-backups
sudo systemctl stop aartins
recap_backup="recap-$(date +%Y%m%d-%H%M%S).tar.gz"
(umask 077; tar -czf "$HOME/aartins-backups/$recap_backup" -C "$HOME" aartins-data)
sudo systemctl start aartins
```

If backup fails, restart the service and fix the problem; do not trust an incomplete file. Copy verified backups to separate protected storage. Also privately back up worker.env, service/proxy settings, image references and the WebUI data volume (accounts/chats/functions/Valves). Locate its real mounts rather than guessing names. Git holds source, not runtime data or secrets.

Test restores into a separate scratch directory. Stop services before restoring live databases, preserve the current data as rollback, restore private permissions/ownership and verify all health endpoints. Exact WebUI restore steps depend on its prerequisite deployment.

## Typical issues

- Missing Python path: use the absolute venv path and correct checkout directory.
- Missing API key: load worker.env in each new CLI session; never paste it in chat.
- Upload card absent: check Pipe enabled, PUBLIC_ORIGIN, user settings, Rich UI compatibility and HTTPS route.
- Worker unreachable: verify host-vs-bridge networking; loopback is namespace-specific.
- Source validation rejects report: retain files, inspect model audit, recover rather than disabling checks.
- Disk growth: no automatic retention is implemented; plan protected backups and deliberate cleanup.

When troubleshooting, don't share raw request/response logs, capability URLs or meeting text publicly. Use redacted synthetic reproductions.

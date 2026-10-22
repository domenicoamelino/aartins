# Meeting ingestion — complete package for Open WebUI 0.12.3

This tool imports generated meeting knowledge into your existing Open WebUI Knowledge collection. It uses the existing embedding configuration (BGE-M3 in your setup). It does not call the Qwen chat models, change thinking/query-generation settings, or install another vector database. New/changed files still require embedding work, so first ingestion can take time.

Your original meeting folders, audio, queue, Whisper, report generator and proxy are left untouched. No existing application source file needs replacement.

## Naming

Each meeting keeps `knowledge.md` in its own local `processed-*` folder. New remote uploads receive a distinct name:

```text
2026-10-22__planning-meeting__JOB-ID__CONTENT-HASH.md
```

The date/title come from `meeting_metadata.json`. The job ID is taken from the meeting folder's final 32-character ID, or a deterministic folder hash for legacy names. A 12-character content-hash suffix identifies the version. Repeated runs with unchanged content skip uploading and embedding it. The name is a citation/file label, not a separate knowledge collection: every meeting goes into your selected Meeting Archive.

The existing manual test upload named `knowledge.md` can be adopted if its complete UTF-8 text exactly matches one local meeting (line endings/BOM are normalized). It is reused without another upload or re-embedding. Its original remote name is deliberately retained. Future new uploads have the distinct names above. Renamed/manual copies that aren't exact matches are not automatically deleted or replaced.

## 1. Install on the UM870

Download `meeting-ingestion-complete.zip` and extract it to a NEW staging folder, for example `~/meeting-ingestion`. The ZIP contains the entire `meeting-ingestion` folder; use the folder containing `install.sh`.

For the consolidated SMARTINI’s checkout, use `cd ~/smartinis/ingestion` instead. The remaining installer/configuration steps are the same. Do not reinstall an already configured importer.

```bash
cd ~/meeting-ingestion
bash -n install.sh
bash install.sh
```

The installer runs the offline tests and copies the tool to `~/ai-platform/ingestion`. It refuses to overwrite an existing ingestion directory. It does not stop or restart any existing service. Nightly scheduling is not enabled by installation. Python 3.10+ and the standard library are sufficient; no packages need downloading.

## 2. Get an Open WebUI API key

Use an Open WebUI account with write access to Meeting Archive. An API key acts with that account's permissions.

- If API keys are disabled: open **Admin Panel > Settings > Authentication**, enable API Keys, and Save. Non-admin accounts also need the API Keys feature permission.
- In your **personal Settings > Account**, find API keys/Secrets and expand Show. Reuse an existing key if one already exists. Creating a replacement key invalidates the previous one and can break another integration using it.
- Do not paste this key into chat. The setup command below asks for it with hidden terminal input and stores it only on the UM870 in a mode-600 file.
- If endpoint restrictions are already enabled, the allowed routes must cover `/api/version`, `/api/v1/knowledge`, and `/api/v1/files` and their subpaths. Do not remove restrictions indiscriminately.

Official guide: https://docs.openwebui.com/features/authentication-access/api-keys/

## 3. Configure once

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py configure
```

The command asks for:

1. Open WebUI base URL. Default: `http://127.0.0.1:8080`, read from the UM870 itself, matching the upstream shown in your proxy logs. If that is not reachable, enter the normal HTTPS Tailscale base URL you use in the browser, without `/api` or a chat path. HTTP is accepted only for loopback addresses. No TLS validation is disabled.
2. Your API key, with hidden input.
3. A numbered selection of writable knowledge collections. Choose your existing **Meeting Archive**; no collection is created or wiped.
4. Meetings root. Default: `~/ai-platform/meetings`.

Configuration verifies Open WebUI is version `0.12.3`. It deliberately refuses other versions until API compatibility is checked. It never imports Open WebUI internals or writes its database directly.

Local files created:

- `config.json`: server origin, collection ID, source path and timeouts, without the API key.
- `api-key.txt`: credential; owner-only access on Linux.
- `state.json`: file IDs, content hashes, pending operations and previous-version history.
- `state.json.bak`: previous saved state.
- `snapshots/`: exact normalized Markdown versions used during ingestion.
- `last-run.json`: last sync summary, including errors or deferrals. A dry run updates this local summary, but never uploads, embeds, removes or changes remote files.

Keep state and snapshots with your backups. Do not share the credential file. If configuration fails before completion, it may have created the private directory/lock file only. If a later interruption leaves only `api-key.txt`, keep its backup, remove that incomplete key file yourself, then rerun configure.

## 4. Preview the first ingestion

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py sync
```

Default mode is a remote read-only dry run. It lists candidate operations:

- `WOULD ADOPT`: reuse an exact manual upload already attached to Meeting Archive.
- `WOULD UPLOAD`: add a new meeting.
- `WOULD REPLACE`: upload a new version before detaching the previous managed version.
- `WOULD RESUME`: finish an interrupted operation using its saved file ID.
- `UNCHANGED`: verified file is already attached with the same text.

Only direct, non-symlink `processed-*` folders containing `knowledge.md` and a `job.json` with `state: completed` are included. Metadata is optional for legacy meetings, but an invalid supplied date fails rather than being guessed. A missing metadata date becomes `date-unknown` in the filename. Failed/in-progress jobs and folders without knowledge files are skipped. To explicitly include old knowledge files without job.json, add `--include-legacy` to both the dry run and the apply command; it does not override a job.json marked unfinished.

If multiple identical manual copies are found, the tool stops for that meeting and leaves them in place. Review those copies in Open WebUI and remove only the redundant collection entries you identify, then rerun. Your existing knowledge.md may remain the generic name because it was adopted rather than uploaded by this tool.

## 5. Apply one meeting, then verify

When no upload or recap is running:

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py sync --apply --limit 1
python3 ~/ai-platform/ingestion/ingest_meetings.py status
```

The tool checks your worker's SQLite queue read-only before each changed meeting. A recent waiting-upload session, upload, queued job, Whisper job or report-analysis job defers the run (exit 75) without starting that meeting's ingestion. Stale waiting-upload sessions older than 30 minutes do not block it. This is a cooperative check, not a shared scheduler: a newly submitted recap or chat can still start during an individual file's ingestion. Avoid triggering a large import while using chat. The tool has no reliable knowledge of interactive Qwen activity and does not pretend to pause for it.

Uploads are processed serially. The script waits for document processing, adds the file to the selected collection, and confirms membership. A successful upload alone is not counted as successful ingestion. On replacement, the new file is attached before the previous managed file is detached. The old uploaded file resource is retained for rollback; there is a short interval with both versions attached during replacement. No remote global file is deleted.

In Open WebUI, open Meeting Archive and verify the file is present. In a new chat attach `#Meeting Archive`, ask the same evidence-based question you already tested, and check both accuracy and response time. Keep **thinking Off** and **retrieval-query generation Off**. Those settings are separate from indexing and are not modified by this package.

Then repeat the dry run:

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py sync
```

The imported meeting should say `UNCHANGED`. This is the important no-duplicate check. After that, ingest the remaining completed meetings with:

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py sync --apply
```

This last command is your on-demand **Index new meetings** operation. It scans the folder; you do not have to download/rename/upload files manually. It does not generate missing knowledge.md files: use the existing MVP 3.1 backfill separately if needed.

## Failures and recovery

- Stop the command with Ctrl+C if needed. The OS lock releases; do not delete a lock file while another instance is running. Remote processing may continue after a client disconnect or timeout.
- `status` reports pending file IDs. After checking that server processing is not still running, rerun `sync --apply` to resume. An interrupted upload with a lost response is recovered by its deterministic filename plus exact content check among the account's stored uploads; it is not blindly re-uploaded.
- If a file has status failed, inspect Open WebUI's file-processing logs. Remove that failed uploaded resource in Open WebUI, correct the underlying cause and rerun. The tool recognizes a saved pending ID that now returns 404 and can upload again. Do not delete a healthy file just because polling timed out.
- If the source changes while an upload is pending, ingestion stops for that meeting. Keep a copy of the new knowledge.md outside its folder, restore the exact pending version from `snapshots/<pending-sha256>.md` into knowledge.md, and run sync --apply to finish the pending version. Then restore the new knowledge.md and sync again. Never hand-edit file IDs or discard state to force a retry.
- If an attach call times out, the script checks membership before declaring failure. If the new file is still not attached, it retains the pending ID and exits; it does not launch a second attach loop automatically. Check the server before retrying.
- A failed old-version detach may leave both versions searchable. The pending state is retained so a later run can finish the detach without another upload. Do not run accuracy tests until the replacement is confirmed complete.
- 401/403: check the key, account/collection access and API endpoint restrictions. Server response bodies, document text and keys are not printed by the client.
- 400 during collection attachment: check Open WebUI logs for embedding, duplicate-content or processing errors. Existing committed content is retained. If a manual copy was renamed or modified so exact adoption fails, reconcile that entry deliberately; the tool does not delete arbitrary manual uploads.
- Changing the embedding model or resetting the vector database requires Open WebUI reindexing. This script's unchanged checks verify membership and original file bytes; they cannot prove that a corrupted/missing vector index is healthy.
- A changed metadata JSON alone does not regenerate knowledge.md. Regenerate the knowledge export first, then sync the resulting changed content.
- Remote files are not pruned when a local source disappears. Deletions require deliberate review; a temporarily unavailable disk must not erase your knowledge collection.

## Rollback one managed meeting

First disable nightly scheduling if enabled. Use the exact processed folder name shown by status:

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py rollback --meeting 'processed-YOUR-EXACT-FOLDER'
python3 ~/ai-platform/ingestion/ingest_meetings.py rollback --meeting 'processed-YOUR-EXACT-FOLDER' --apply
```

Default rollback is a dry run. If a previous version exists, apply reattaches it before detaching the current version. Without a previous version, an initial tool-created upload is detached. An initially adopted manual upload is retained and simply forgotten from local management. All uploaded file resources and local meeting files are retained. If a retained previous file was deleted externally, rollback refuses to detach the current one.

Rollback changes indexed versions, not source Markdown. If you sync again while the local file still contains the newer text, that newer version will be ingested again. Pause scheduling until the local source and desired indexed version agree. Back up the full ingestion directory before manual repair; state.json.bak is only the most recent saved state, not a substitute for a complete backup.

## Optional nightly run — only after the manual smoke test passes

The supplied user timer runs at **03:00 Europe/Amsterdam**. It is not enabled automatically. Persistent=false deliberately prevents a missed overnight run from catching up during daytime. There are no periodic chat notifications; check status or the journal as needed.

```bash
mkdir -p ~/.config/systemd/user
cp ~/ai-platform/ingestion/meeting-ingestion.service ~/.config/systemd/user/
cp ~/ai-platform/ingestion/meeting-ingestion.timer ~/.config/systemd/user/
systemd-analyze --user verify ~/.config/systemd/user/meeting-ingestion.service ~/.config/systemd/user/meeting-ingestion.timer
systemctl --user daemon-reload
systemctl --user enable --now meeting-ingestion.timer
systemctl --user list-timers meeting-ingestion.timer
```

For the user timer to run after logout/reboot without an interactive login, enable lingering for your account:

```bash
sudo loginctl enable-linger "$USER"
```

This is optional and affects user-service lifetime; it is not required for manual ingestion. The service uses low CPU/I/O priority and defers when the meeting queue is busy. Those priorities are not a GPU reservation or a guarantee that indexing cannot slow simultaneous chat. A deferred run is skipped until your next manual run or next night; it does not repeatedly retry during daytime.

To manually trigger the installed systemd service instead of the Python command:

```bash
systemctl --user start meeting-ingestion.service
```

Do not run both at the same time; the ingestion lock prevents overlap.

Inspect status/logs:

```bash
python3 ~/ai-platform/ingestion/ingest_meetings.py status
journalctl --user -u meeting-ingestion.service -n 60 --no-pager
```

Disable nightly execution:

```bash
systemctl --user disable --now meeting-ingestion.timer
```

This does not stop an ingestion already running. Stop that separate service deliberately if required: `systemctl --user stop meeting-ingestion.service`. Remote processing may finish afterward; resume from saved state on the next manual run.

## Evidence links and backups

Open WebUI supplies document citations to its indexed files. The existing relative `transcript.md#S...` and `findings.json` links inside knowledge.md still refer to the original meeting archive. This package does not publish a transcript web server or make those relative links accessible from the Open WebUI browser. Use the meeting ID/file name to locate the original archive and verify the quoted segment there. Full transcript hosting/link resolution is separate work.

Back up your original meeting archives, Open WebUI persistent data (including its vector store) and the ingestion directory using your existing backup process. Source snapshots/state are local recovery copies; they are not off-device disaster recovery. Do not copy a live database directory as if it were necessarily a consistent backup; use your established stopped-service/database backup process. Installation itself does not create or change a backup schedule.

## Validation and compatibility

Run the included offline tests any time:

```bash
cd ~/meeting-ingestion
python3 -m unittest -v test_ingestion
```

See VALIDATION.txt for checks performed before delivery. No live UM870 deployment or real Open WebUI ingestion has been performed by this chat. The first --limit 1 run is the live compatibility and permissions test. Once it passes, enable nightly scheduling if desired.

API reference checked against 0.12.3:

- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/routers/files.py
- https://github.com/open-webui/open-webui/blob/v0.12.3/backend/open_webui/routers/knowledge.py
- https://docs.openwebui.com/reference/api-endpoints/

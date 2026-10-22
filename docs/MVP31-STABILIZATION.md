# MVP 3.1 stabilization and release adoption

This revision consolidates the accepted audio-to-recap workflow, metadata/knowledge
export, incremental indexing and optional monitoring. It is a source baseline;
checking it out does not change an installed service. Preserve the working system
while finishing live acceptance. See [implementation record](IMPLEMENTATION-RECORD.md).

The project display name is now **SMARTINI’s**. New-install examples use the
`smartinis` slug; existing service/path names must not be renamed during source
adoption. See [brand and compatibility notes](BRANDING.md).

## What is preserved

Authenticated Pipe sessions, scoped upload capabilities, ownership checks, durable
SQLite queue, serialized Whisper/Ollama work, recap-only responses, evidence archives,
configurable languages and resumable reports remain. The merged worker extends the
portable SMARTINI’s source; it does not replace it with the older fixed-language PoC.
Recovery now exports knowledge before marking a recovered job completed.

## Repository layout

| Path | Responsibility |
|---|---|
| Root Python/HTML and tests/ | Audio upload, processing, reports and deterministic knowledge |
| ingestion/ | Incremental WebUI importer, tests and optional nightly user units |
| monitoring/ | Read-only private history page, notification wrapper, tests and rollback |
| docs/ | Public setup, architecture, usage and stabilization documentation |
| tools/check_all.py | Run independent offline suites in separate processes |

Private server handbook, secrets, recordings, caches, ingestion snapshots and
history databases are not part of the public source release. Original PoC and
portable baseline remain inspectable through Git tags. The GitHub upload had lost
hidden ignore/line-ending files; this revision restores and extends them.

## Existing working server: adoption sequence

Do not create a second worker or replace WebUI containers. First record the deployed
source hashes, Python/dependency versions, Ollama version/model IDs, WebUI image
digest/version, embedding configuration, unit files and active Tailscale routes.
Store that inventory privately. Avoid package/model/image upgrades during source
adoption; an exact full machine lock has not been collected from the server.

1. Clone source into a separate checkout. Review the diff against the live files.
2. Finish uploads, queued audio, ingestion and recovery work. Take source/config
   backups and a consistent SQLite backup while idle. The existing runbooks explain
   application-specific backups; copying a live WAL database alone is insufficient.
3. Run `python3 tools/check_all.py`. On Linux check `bash -n` for scripts you will
   execute. Keep installed dependency versions unchanged for this adoption.
4. In a deliberate maintenance window, stop only the existing worker service and
   copy the reviewed `meeting_worker.py`, `meeting_report.py`, `meeting_knowledge.py`,
   `upload.html`, `recover_meeting_job.py` and CLI helper if used to its existing
   source directory. Preserve its environment, secrets, job database and proxy.
5. Restart the same service. The portable worker adds nullable language columns
   when absent. Do not downgrade/restore the database just to roll source back.
6. Only if adopting the portable language UI, update the Pipe separately and preserve
   its existing admin Valves. Old open cards must be reopened. External clients must
   now supply `X-Meeting-Metadata` as documented in configuration.
7. Test a short non-sensitive recording: metadata required, recap-only response,
   archive outputs, knowledge evidence and a supported language selection.
8. Keep existing ingestion configuration/key/state/timer. Do not rerun its new-install
   installer. Compare versions before copying a maintenance update. Ingestion 1.0.1
   supports WebUI 0.12.3; update `ingest_meetings.py` only after saving its old copy.
9. Install optional monitoring through its [START-HERE](../monitoring/START-HERE.md).
   It preserves the timer, adds an override and uses a separate private HTTPS port.

No universal copy/deploy script is supplied for unknown live versions. The earlier
MVP upgrade used hashes specific to one collected source snapshot; it is not a
general reusable installer and is intentionally not reused here.

## Acceptance and rollback

Keep a record of the commit actually deployed and the test results. Verify a new
recording, a monitored manual/service ingestion, a repeated no-change run, a
collection-backed answer with a meaningful citation, phone dashboard access and a
Telegram test. Then let the existing nightly timer discover a further meeting
without manually triggering it. Verify the following morning; source tests cannot
establish that a scheduled machine run occurred.

If a backend smoke test fails, stop the worker while idle and restore its backed-up
source set, retaining the live database and all outputs. Review any new schema
columns before a downgrade; they are additive and should not be erased by restoring
an old job snapshot. Restore Pipe code separately if changed. For monitoring use
its `rollback.sh`; for indexing use its documented state/version rollback. Do not
reset Tailscale Serve or delete whole collections as a rollback shortcut.

## Freeze scope

Finish acceptance and backups before new features. Keep lecture-specific profiles,
speaker identification, coding-assistant MVP, full dependency/container locking,
multi-user source hosting and retention automation outside this release. Failed
or deferred ingestion is a recorded outcome, not successful indexing. A powered-off
machine cannot send its own failure alert; external uptime monitoring is separate.

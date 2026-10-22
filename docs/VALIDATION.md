# Validation — MVP 3.1 consolidation, 22 October 2026

The consolidated source passed **102 offline tests** under Python 3.12.14 on
Windows: 49 worker/reporter/Pipe/metadata/CLI/recovery tests, 27 importer tests and
26 monitoring/Telegram tests. Run them with `python tools/check_all.py`.

Coverage includes authenticated ownership and upload-session reuse, language
propagation and legacy schema migration, metadata validation, deterministic
knowledge/evidence warnings, report failure/resume, CLI metadata encoding, recovery
completion ordering, incremental imports and uncertain HTTP recovery, queue locks,
private dashboard authentication/CSRF/session handling, weekday summaries and
uncertain notification delivery. External model/ASR/Telegram calls are mocked;
HTTP integration fixtures use temporary local services and synthetic data.

The merged worker preserves SMARTINI’s language selection while adding MVP 3.1;
the original reporter and Pipe are unchanged by this consolidation. Documentation
links, Python compilation and upload/dashboard JavaScript syntax are included in
the release checks. Git archives exclude environments, caches and runtime data.

Earlier local browser validation covered the monitor login/dashboard using sample
data. The metadata upload page had syntax/simulated submission checks in its earlier
package. This consolidation did not repeat a physical phone/browser/model test.
Bash/systemd/Tailscale activation was not executed on Windows; use the supplied
Linux syntax/unit checks before installation.

The user confirmed real recap and metadata/knowledge outputs, and useful retrieval
answers in the existing deployment. Ingestion configuration and scheduling were
reported complete. The newest unattended nightly discovery, optional monitor
installation, real Telegram delivery and fresh portable language UI deployment
were not confirmed before this revision. Source updates do not establish deployment.

Not established: full OS/dependency/container lock, clean-machine provisioning,
every model/language, a restored off-device backup, hosted transcript evidence
links, or an external outage detector. See [release acceptance](MVP31-STABILIZATION.md).

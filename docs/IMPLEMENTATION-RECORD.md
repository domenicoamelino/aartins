# Implementation record — 22 October 2026

Curated technical record of “Build meeting report CLI” and “Update meeting upload
and RAG files”. This is not a raw chat dump; no recordings, meeting excerpts,
credentials, real run IDs or personal network hostname are included.

| Increment | Outcome and evidence |
|---|---|
| MVP 1 | User-operated local Ollama and Open WebUI on AMD MINISFORUM |
| MVP 2.2 | Evidence-linked readable reports, bounded context, source checks and recovery |
| MVP 2.3–2.4 | User-validated durable queue, mobile upload card and recap-only WebUI response |
| Portable SMARTINI’s | MIT source, generic install and language selection; original PoC retained |
| MVP 3.1 metadata/export | Required title/date, optional participants; user confirmed real recap and output files |
| Native WebUI retrieval | User confirmed useful meeting answers after importing knowledge |
| Incremental ingestion | Unique filenames, fingerprints, manual-upload adoption, safe replacement and nightly timer; user completed setup |
| Monitoring extension | Private password-protected history and weekday Telegram code delivered; live delivery not yet confirmed |
| Scheduled acceptance | User loaded another recording and planned to check the following morning; result not yet reported |

## Decisions retained

- Export structured findings without another model call. Preserve uncertainty and
  source evidence; metadata is user-supplied, not inferred from a filename.
- Keep `knowledge.md` locally per meeting. Unique remote filenames distinguish
  meetings/versions; content fingerprints avoid redundant indexing.
- Use WebUI's existing Knowledge/embedding/vector system and permissions. Do not
  introduce a second search service or write its internal database directly.
- Use plain chat plus a selected Knowledge collection for questions; the upload
  Pipe generates recaps, not retrieval answers. Thinking and search-query rewriting
  are independently configurable overheads.
- Defer ingestion while audio jobs are busy, serialize operations, retain old remote
  versions for rollback and store configuration/state outside source control.
- Record all monitored runs, skip routine weekend Telegram messages, and keep
  notification failure separate from indexing outcome. Avoid automatic retries
  when Telegram delivery is uncertain.
- Keep the existing working deployment separate from the maintained checkout.

## Observations and limits

The user reported a short direct answer in 10.51 seconds with 54 generated tokens
and zero thinking characters. Longer WebUI waits prompted investigation; after
thinking and retrieval-query generation settings were adjusted, the user reported
the result was useful and fast. This does not establish a universal latency target
or prove that every prior delay had the same cause.

The observed WebUI version was 0.12.3. The user listed qwen3.5:9b and qwen3.5:4b;
the 9b model was shown using GPU with 4096 context. These are reference environment
observations, not requirements for all deployments. See [tested PoC](TESTED-POC.md).

## Stabilization priority

The intended MVP feature set is present. Complete live nightly/notification checks,
capture the deployed inventory, record the deployed commit and test backup recovery
before expanding scope. See [release adoption](MVP31-STABILIZATION.md) and
[validation](VALIDATION.md). An exact reproducible OS/dependency/container build is
not claimed by this source consolidation.

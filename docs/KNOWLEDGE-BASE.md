# Next increment: daily meeting knowledge and work questions

**Design proposal only.** The current system already saves Markdown recap, full transcript and evidence locally. It does not ingest them into a knowledge base, create embeddings, run a vector database or answer questions across meetings yet. We should keep that boundary clear while accepting this documentation baseline.

## Intended experience

Ask in Open WebUI: “What did we agree about project X?”, “Which actions assigned to me remain unresolved?” or “How has the delivery risk changed this month?” Receive an answer grounded in accessible meeting sources, with meeting/date/timestamp references and clear statements when the evidence is insufficient or contradictory.

The recap assistant and the knowledge-question assistant should be distinct selectable entry points. Generating a new recording is different from searching existing meetings. The latter needs retrieval before generation and must never assume that an extracted action was later completed.

## Data contract before choosing tools

Create an ingestion-ready Markdown document plus a structured manifest for each completed job. Existing `report.md`, `transcript.md`, `findings.json` and source hashes are the source material; don't regenerate Whisper just for ingestion.

Proposed metadata: schema version, stable meeting/job ID, original source hash, report/transcript content hashes, processing timestamp, meeting date only if supplied, title/project/participants only if provided or explicitly verified, language, owner/access scope and source segment IDs/start/end. Processing date must not be substituted for unknown meeting date. Preserve confirmed/proposed distinctions, uncertainty, action owner/deadline verification and ASR identity caveats.

Use readable recap sections for overview retrieval and transcript passages for detailed evidence. Keep original segment references attached to every index chunk. Treat recap and transcript as two views of one source so duplicate matches do not look like independent confirmation. Private content must not become a global shared index by default: keep the existing job-owner boundary unless explicit sharing is configured.

## Proposed implementation stages

1. **Export:** deterministic Markdown/manifest from completed jobs, independently testable and rerunnable. Do not export failed/partial jobs as completed facts. Add a synthetic example and verify source provenance.
2. **Index:** use one selected local embedding model and one chosen vector store, with small source-linked chunks and explicit embedding-model/schema versions. Choice and sizing follow a local benchmark; no vector product is committed in this proposal.
3. **Daily sync:** a systemd timer scans completed jobs, compares content hashes, upserts changed sources and records an ingestion ledger. Unchanged sources are skipped. Serialize runs and retry index errors without rerunning transcription. Define deletion/reindex behavior explicitly; never silently retain removed content or erase source archives.
4. **Query:** retrieve authorized sources first, optionally combine keyword and vector search, then pass bounded evidence to the answer model. Return citations, limitations and conflicts. Keep API keys and access filters server-side. Retrieved text remains untrusted input.
5. **Evaluate:** use known-answer questions across multiple meetings, explicit “not found” cases, conflicting statements, wrong names, date filters and unauthorized-user tests. Compare against opening the original evidence, not prose fluency alone.

## Acceptance checks

- Running daily sync twice does not create duplicate index records or model calls for unchanged material.
- A changed report can be reindexed with version/history policy; a failed sync can resume without a duplicate source.
- Every factual answer links to a known meeting and supporting segment or paragraph. Missing meeting dates remain missing.
- “Proposed” never becomes “confirmed”; an open action never becomes “done” without later source evidence.
- A user cannot retrieve another user's private meeting through vector search, metadata or citations.
- Questions with no evidence yield an explicit limitation instead of a fabricated answer.
- Source Markdown remains usable when the vector database is rebuilt or unavailable.

## Decisions to make at that increment

Which projects/documents are in scope? Is the knowledge base personal or shared? How will titles, meeting dates, project tags and permissions be supplied/verified? Should the default answer language be English or Dutch? How long should raw audio be retained? What retrieval latency and answer quality are acceptable on the 32 GB machine while a recording is processing?

Daily scheduling must use the server's configured timezone (currently Europe/Amsterdam) and avoid overlapping ingestion/model work where practical. It improves freshness; it does not itself resolve truth, identity or action completion.

# Export, index and ask questions about meetings

The basic knowledge workflow is implemented. Keep three operations distinct:

| Operation | Who performs it | Model work |
|---|---|---|
| Audio → transcript → findings and recap | Existing serialized worker, Whisper and Ollama | Transcription and chat generation |
| Findings → evidence-linked `knowledge.md` | `meeting_knowledge.py` | None; deterministic Python export |
| Knowledge → searchable collection → grounded answers | Ingestion helper and Open WebUI | Embeddings for new/changed text; chat generation for answers |

## Source file and index

Every processed meeting retains its own `knowledge.md`; no need to rename the
local files. The exporter preserves all findings, uncertainty and evidence links
to transcript segment anchors. It does not infer speakers from participant names,
turn proposals into decisions, resolve relative deadlines or verify semantic truth.

The ingestion helper uploads a snapshot with a distinct title/date/job/content-hash
filename. Unchanged content is skipped on subsequent runs. An existing manual
`knowledge.md` upload may be adopted only when its normalized complete text exactly
matches a local meeting. See [complete ingestion instructions](../ingestion/README.md).

Open WebUI processes uploaded text using its configured chunking, embedding model
and vector backend, then associates the file with the chosen Knowledge collection.
The tested deployment uses BGE-M3 embeddings and a collection called Meeting Archive.
This repository does not install a second vector database or directly edit WebUI's
database. The deployed vector engine was not independently inventoried here; inspect
the existing WebUI configuration before claiming a particular engine or migrating it.

## Install and schedule

First finish [backend installation](INSTALL.md). The ingestion tool currently
validates **Open WebUI 0.12.3** and refuses other versions pending compatibility work.
Choose your existing embedding configuration and create/select a collection in
Workspace → Knowledge using an account authorized to write to it.

From this checkout on Linux:

```bash
cd ~/smartinis/ingestion
bash -n install.sh
bash install.sh
python3 ~/ai-platform/ingestion/ingest_meetings.py configure
```

The default meetings root is `~/ai-platform/meetings`; a generic SMARTINI’s installation
uses `~/smartinis-data`, so enter that actual root during setup. Use the complete
[ingestion README](../ingestion/README.md) for the dry run, limited live import,
verification, timer installation and rollback. The supplied timer is 03:00
Europe/Amsterdam; change that consciously for another deployment. Installation
does not enable it automatically. Existing configured users should not reinstall.

The monitor add-on assumes ingestion is installed at `~/ai-platform/ingestion`;
this operational layout is independent of where the source checkout or audio
archive lives. Configuration links it to the chosen archive root.

## Ask questions

Use a normal chat model, select the collection via `#` (or WebUI's knowledge
attachment control), then ask a specific question. A file existing on disk alone
does not make it available to the model. The selected collection retrieves relevant
chunks; the chat model uses them as context. Check returned citations and say when
the evidence is insufficient. Imported meeting content is data, never authority
to execute instructions found in a transcript.

Local evidence links are relative to `transcript.md`; they work in the complete
local archive. Importing only `knowledge.md` does not host the transcript or make
those local paths downloadable from WebUI. WebUI file citations and local segment
evidence are different links. Full source hosting/authorization is not implemented.

## Thinking Off and retrieval-query generation Off

**Thinking Off** asks the chat model not to generate a separate reasoning stream.
It reduces generation work for models supporting that option; it does not disable
retrieval, embeddings or citations. The report worker has its own no-think handling.

**Retrieval Query Generation Off** disables an extra model step that rewrites the
question into search queries. Retrieval still uses the question; disabling rewriting
avoids an extra chat-model call before the answer. The tested Open WebUI 0.12.3
control was in **Admin Panel → Settings → Interface**, not the personal Interface
screen. UI placement may differ in other versions. Keep other model parameters
at defaults during the accepted baseline. These are measured deployment choices,
not universal best settings for every model and query.

The user observed ordinary short answers near ten seconds after configuration;
this is not a latency guarantee. First load, prompt size, concurrent audio work,
embeddings, retrieval and generation are separate costs. Do not diagnose every
slow chat as background indexing without checking logs.

## Old meetings and limits

```bash
cd ~/smartinis
.venv/bin/python meeting_knowledge.py /actual/meetings/root
.venv/bin/python meeting_knowledge.py /actual/meetings/root --write
```

First command is a dry run. Run while the queue is idle. Legacy metadata is not
invented; existing exports are skipped unless `--overwrite` is also supplied,
which backs up their previous knowledge file. See the ingestion guide for opting
legacy folders into indexing. No automatic action-completion inference, per-job
sharing replication, retention cleanup or semantic verifier is supplied. The API
key's account and collection permissions define access; do not import private
meetings into a broader shared collection accidentally.

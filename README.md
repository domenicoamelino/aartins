# SMARTINI’s

![SMARTINI’s logo](assets/brand/smartinis-logo.png)

**S**mart **M**emo **A**rtificial **R**ecording **T**ranscription **I**nitiative **N**otes **I**ntelligence **s**oftware

*Turn recordings into notes. Turn notes into knowledge.*

SMARTINI’s combines local audio transcription, readable summaries and searchable
meeting memory. The martini-glass logo blends a voice waveform with connected
memory nodes: a playful name for a practical local intelligence workflow.

Formerly AARTINS. The current GitHub address remains
[domenicoamelino/aartins](https://github.com/domenicoamelino/aartins); the display
rename does not rename the hosted repository or existing server services.
See [brand and compatibility notes](docs/BRANDING.md).

Record a lecture or meeting, upload the audio through Open WebUI, and generate a transcript and readable summary on your own hardware. SMARTINI’s is an MIT-licensed reference implementation you can reuse and adapt.

A reference implementation that connects **Open WebUI to a Python backend** for local audio transcription and readable meeting summaries. Upload a recording inside chat, follow processing status and receive the recap. Original audio, timestamped transcripts and Markdown reports remain on the server.

The project implements the integration and reporting workflow. It is **not an Ollama installer, an Open WebUI distribution or an AMD-specific inference engine**. You bring a running Open WebUI installation and a local Ollama model; the guides link to their official setup documentation.

## Features

- In-chat audio upload and operation-specific progress.
- Durable SQLite jobs, serialized transcription/reporting and saved audit files.
- faster-whisper transcription: automatic language detection or a selected language, with optional mixed-language detection.
- **Language choices in Open WebUI:** spoken language, mixed-language mode and recap language are per-user settings captured for each new request.
- Bounded evidence extraction and prose writing for long recordings with a default 4096-token model context.
- Readable recap with topics, supported decisions, actions, open questions/risks and cautious observations about communication.
- Source IDs/timestamps, grounded owner/deadline handling and resumable writing failures.
- Recap-only chat output; complete transcript and evidence remain in the archive.
- Required meeting title/date, optional participants and validated metadata archives.
- Deterministic evidence-linked `knowledge.md` export without extra model calls.
- Incremental ingestion into an existing Open WebUI Knowledge collection, with an optional nightly timer.
- Optional private run-history dashboard and weekday Telegram run summaries.

## What you need

A Linux host with Python, Docker if using the reference proxy, an existing Open WebUI instance supporting Pipe Functions/Rich UI, and Ollama serving a local model with chat and JSON-schema output support. No particular PC brand or GPU vendor is required by the application. This reference deployment uses Linux Docker **host networking** and loopback upstreams; bridge/remote layouts require deliberate URL/network changes.

Start with [prerequisites and hardware guidance](docs/PREREQUISITES.md), then follow the [build and integration guide](docs/INSTALL.md).

## Architecture

```text
Browser / phone
  → your HTTPS endpoint → reference proxy
       ├─ Open WebUI → SMARTINI’s Pipe
       └─ upload/progress card → Python worker
                                  ├─ SQLite queue and local archive
                                  ├─ faster-whisper → timestamped transcript
                                  └─ report writer → local Ollama model
  ← readable recap in Open WebUI
```

The Pipe polls jobs; the durable worker owns processing. Closing a chat after upload acceptance does not cancel the job, but you may need `status JOB_ID` to retrieve its result. The workflow uploads an existing file; it does not implement live microphone recording or transcription of ordinary WebUI attachments.

## Documentation

| Purpose | Guide |
|---|---|
| Hardware, Ollama model and Open WebUI prerequisites | [Prerequisites](docs/PREREQUISITES.md) |
| Build this integration from source | [Installation](docs/INSTALL.md) |
| Choose languages and use the chat workflow | [User tutorial](docs/TUTORIAL.md) |
| Services, restarts, backup and recovery | [Operations](docs/OPERATIONS.md) |
| Component responsibilities and data flow | [Architecture](docs/ARCHITECTURE.md) |
| Environment variables and code changes | [Configuration](docs/CONFIGURATION.md) |
| Maintain Git source and deploy changes | [Repository workflow](docs/ADOPT-REPOSITORY.md) |
| AMD MINISFORUM reference environment | [Tested PoC](docs/TESTED-POC.md) |
| Tests, limits and evidence of validation | [Development](docs/DEVELOPMENT.md), [validation](docs/VALIDATION.md) |
| Export, index and ask questions across meetings | [Knowledge workflow](docs/KNOWLEDGE-BASE.md) |
| Optional run history and Telegram | [Monitoring setup](monitoring/START-HERE.md) |
| Stabilize an existing installation | [MVP 3.1 release and adoption](docs/MVP31-STABILIZATION.md) |
| This conversation distilled into project decisions | [Implementation record](docs/IMPLEMENTATION-RECORD.md) |

## Model choice

The reporting engine uses Ollama's local chat API rather than a Qwen-specific SDK. `REPORT_MODEL` selects the installed model. `qwen3.5:9b` is the tested example and fallback default, not a mandatory model or guarantee that every alternative meets the same quality/latency targets. A replacement must handle the supplied JSON schema, requested languages and 4096-token context. Whisper's multilingual model handles recognition independently of the recap model.

## Language settings

The Pipe exposes `AUDIO_LANGUAGE`, `MIXED_LANGUAGES` and `RECAP_LANGUAGE` through Open WebUI User Valves. Defaults are **auto-detect, mixed-language mode off, English recap**; no Dutch/English pair is hardcoded. English is a selectable output default, not a restriction. The current UI offers 16 languages plus automatic speech detection; support/quality depends on the chosen models. Administrative labels and report section headings remain English.

New requests store these settings with their jobs. Changing your preferences later does not alter a running/completed job. Enable mixed-language mode for recordings that switch languages; this asks Whisper to detect changes rather than restricting it to a chosen pair.

## Open-source reuse

Licensed under [MIT](LICENSE). You can use, modify and redistribute this project subject to the license notice. Open WebUI, Ollama, faster-whisper and model weights retain their own licenses; they are prerequisites, not bundled under this license. See [contributing](CONTRIBUTING.md) and [project scope](docs/ABOUT.md).

## Source and validation

A dedicated lecture/study-note profile is planned; the current generator uses the meeting recap structure. Recordings of lectures can be transcribed, but no flashcards, exam-preparation tools or cross-lecture question answering are implemented.

The repository contains the full runnable Python/HTML source, proxy/service templates, synthetic example and offline tests. It retains the original working source in Git history under tag `poc-baseline`; new portable code is committed separately. Runtime secrets, recordings and generated meeting archives are excluded.

Run from the repository root:

```bash
python tools/check_all.py
```

The original PoC was user-tested end to end on an AMD MINISFORUM with 32 GB RAM. The merged portable worker/language settings have offline coverage but still need fresh installation and browser verification. Metadata/export and retrieval were user-validated on the existing PoC; automatic nightly discovery and monitoring delivery still await live acceptance. Do not infer that every language, model, GPU or Linux distribution has been benchmarked.

Initial model downloads require network access; inference uses the local services. Archives are not backups. There is no verified diarization, speaker identity, automatic action-completion tracking or an independently supplied vector database. Optional ingestion uses Open WebUI's existing embedding/vector backend; the tested API version is 0.12.3. Evidence validation is not proof that every model interpretation is correct.

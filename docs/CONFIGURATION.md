> The examples below retain original PoC paths. New installs use `~/smartinis` and service `smartinis`; follow [INSTALL.md](INSTALL.md). Per-user languages now override worker fallbacks for new WebUI requests.

## Language API and UI

The session API accepts `audio_language` (auto or selected code), `mixed_languages` (JSON boolean) and `report_language` (selected language name). They are validated and saved at creation; repeated idempotency keys retain original settings. Open WebUI maps User Valves AUDIO_LANGUAGE, MIXED_LANGUAGES and RECAP_LANGUAGE to these fields. Missing API settings default to auto, false and REPORT_LANGUAGE/English. Legacy database rows with NULL settings preserve prior multilingual behavior. See [tutorial](TUTORIAL.md) for the selection list and examples.

# Configuration and hands-on changes

## Two configurations, two deployment locations

The worker reads `worker.env` at process startup. The Pipe reads Function Valves in Open WebUI. A source edit in Git does not automatically update either running component. `upload.html` is read from the worker's directory for new cards. Nginx loads its mounted configuration when started/reloaded.

| Worker variable | Default / validated initial value | Purpose |
|---|---|---|
| `MEETING_API_KEY` | Required random secret, 32+ characters | Authenticates Pipe and CLI requests |
| `MEETING_ROOT` | `~/ai-platform/meetings` | Queue and archives; leave unchanged unless migrating data |
| `MEETING_BIND` | `127.0.0.1` | Keep loopback for host-network deployment |
| `MEETING_PORT` | `8765` | Worker port |
| `MEETING_MAX_BYTES` | `536870912` | Maximum upload bytes |
| `WHISPER_MODEL` | `large-v3` | faster-whisper model name/path |
| `WHISPER_THREADS` | `8` | CPU threads |
| `REPORT_MODEL` | `qwen3.5:9b` | Ollama model |
| `REPORT_LANGUAGE` | `English` | Recap language, independently of spoken languages |
| `REPORT_TIMEOUT` | Worker `1200` seconds | Per-request Ollama time limit, not total job duration |
| `REPORT_OLLAMA_URL` | `http://127.0.0.1:11434` | Local model endpoint |

Environment-file values should be simple `KEY=value` lines without spaces for the documented shell sourcing. The service uses systemd's EnvironmentFile parser; avoid putting arbitrary shell expressions in the file.

| Pipe Valve | Value |
|---|---|
| `WORKER_URL` | `http://127.0.0.1:8765` |
| `WORKER_API_KEY` | Same private key as the worker |
| `PUBLIC_ORIGIN` | Your existing Tailscale HTTPS origin, no trailing path |
| `POLL_SECONDS` | `3` |
| `WAIT_SECONDS` | `21600` (6 hours; wait limit, not job cancellation) |

The portable source leaves PUBLIC_ORIGIN empty. Your deployed function already has the correct saved value. Do not paste `worker.env` or the key into a shared chat/repository. If rotating the key, change both worker settings and admin Valves, restart the worker when idle, and reload CLI environment settings.

## Change the recap language

Edit the private worker file with `nano ~/ai-platform/transcription/meeting-worker-2.3/worker.env`. Set `REPORT_LANGUAGE=Dutch` or `English`, save, and restart the worker when idle. Test a short recording. This changes the fallback for CLI/API requests without an explicit language; WebUI users choose their own recap language in User Valves. Spoken-language/mixed settings are independent.

## Compare a different reporting model

Choose an Ollama model that supports local chat and the JSON-schema output used here; the reporter requests no-thinking mode where supported. No model-specific SDK is required. Install the candidate using `ollama pull MODEL_TAG`, check `ollama list`, set `REPORT_MODEL=MODEL_TAG`, restart when idle and compare the same short transcript. Record quality, run time, RAM, quantization and model digest. Larger weights can exceed practical RAM on a 32 GB integrated-GPU system; no alternative model is declared superior without a local comparison.

For a reporter-only test, avoid retranscription:

```bash
cd ~/ai-platform/transcription/meeting-worker-2.3
~/ai-platform/transcription/.venv/bin/python meeting_report.py /absolute/path/to/transcript.json --model MODEL_TAG --language English
```

This creates a separate report archive. A cache from a different model/language cannot be reused as if it were the same run. To roll back, restore `REPORT_MODEL=qwen3.5:9b` and restart when idle.

## Change the writing style

`NARRATIVE_SYSTEM` in `meeting_report.py` controls the connected prose pass; `SYSTEM` controls evidence extraction. Change writing instructions first when improving repetition/tone. Keep the rules for supported citations, proposed versus confirmed decisions and unknown owners/deadlines. Update `NARRATIVE_STYLE` when the writing policy changes so old narrative caches cannot silently stand in for the new prompt. Extraction-cache invalidation needs deliberate attention if evidence prompts/schema change; do not reuse older extraction results for a prompt comparison.

Run tests, install the updated reporter into the worker folder, restart when idle and test a short meeting. Existing reports remain unchanged. The source-references appendix stays in archived Markdown. The Pipe's completed-job branch strips it and returns recap only; don't append `job['transcript']` there.

## Change transcription speed/settings

`meeting_worker.py` constructs Whisper CPU/int8, per-job language selection and multilingual flag, VAD enabled and beam size 5. Model/thread choices come from the environment; beam size and compute device are code changes. Compare a candidate on identical audio in your selected languages, focusing on names, negation and language switches as well as time. Keep the known working environment/PyAV versions. Do not reinstall dependencies just to change a model.

## Change upload size or ports

Upload size appears in three places: `MEETING_MAX_BYTES`, `upload.html` and Nginx `client_max_body_size`. Keep them consistent. A worker-port change also needs Pipe WORKER_URL and Nginx upload upstream changes. A proxy-port change needs Tailscale Serve. Keep all upstream worker/model listeners on loopback. Validate proxy config with `nginx -t` inside the existing container before reload. Capture working files first and keep an immediate rollback copy.

## Meeting metadata and knowledge (MVP 3.1)

Raw-audio uploads now require `X-Meeting-Metadata`, containing percent-encoded
UTF-8 JSON: `meeting_title` (1–150 characters), `meeting_date` (valid YYYY-MM-DD),
and optional `participants` (up to 20 names, 1–100 characters each). The server
validates before consuming the upload session. See `meeting_knowledge.validate_metadata`.
The supplied card/CLI encode it; arbitrary clients need updating.

Metadata is stored in `meeting_metadata.json` and `audio_source.json`. Existing
hash/bytes/filename/received-at provenance remains. Newly generated report metadata
uses supplied title/date; legacy jobs without metadata stay explicitly unavailable.
No extra model calls are made by the exporter. Knowledge includes every finding's
kind, topic, text, evidence, owner, deadline, interpretation and verification warnings.

Ingestion configuration/API keys and monitor configuration/Telegram credentials
are separate private files outside the checkout. See [knowledge](KNOWLEDGE-BASE.md)
and [monitoring](../monitoring/README.md); neither setting belongs in Pipe Valves.

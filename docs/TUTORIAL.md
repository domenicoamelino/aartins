# Use the integration and choose languages

## Choose settings inside Open WebUI

Select **AARTINS**, then open its per-user Function settings (**User Valves**). Depending on WebUI version, these are under the function/user settings control or the selected model's settings. Admin **Valves** hold connectivity/secrets; **User Valves** hold the following language preferences. See the [official Valves documentation](https://docs.openwebui.com/features/extensibility/plugin/development/valves/) if the controls are not visible in your version.

| Setting | Meaning | Default |
|---|---|---|
| AUDIO_LANGUAGE | Spoken language code, or auto-detect | `auto` |
| MIXED_LANGUAGES | Ask a multilingual Whisper model to detect changes across segments | Off |
| RECAP_LANGUAGE | Requested language of the summary prose | English |

The UI offers `en` English, `nl` Dutch, `it` Italian, `de` German, `fr` French, `es` Spanish, `pt` Portuguese, `zh` Chinese, `ja` Japanese, `ko` Korean, `ar` Arabic, `hi` Hindi, `ru` Russian, `uk` Ukrainian, `pl` Polish and `tr` Turkish, plus `auto` for speech. This is an initial explicit selection list, not a claim that only these languages exist in Whisper. Expanding it requires updating both the backend allowlists and the Pipe schema.

Examples:

- Italian meeting, English recap: `it`, mixed off, English.
- Dutch/English meeting, Dutch recap: `auto`, mixed on, Dutch.
- Unknown single language, French recap: `auto`, mixed off, French.

Mixed mode is not a selected language-pair filter. With mixed mode on, an explicit audio language is an initial hint; later segments can be detected as other languages. With mixed mode off, auto detects the initial language and normally uses it for the recording. Use a multilingual Whisper model for automatic/mixed or non-English recordings; an English-only `.en` model is unsuitable. Model language coverage/quality varies. Output section headings, progress labels and metadata remain English; RECAP_LANGUAGE controls generated prose, not complete interface localization.

Preferences apply to each **new** generated request and are saved with its job. Changing preferences does not reinterpret existing recordings, running jobs or retrieved reports. This repository's new language UI is offline-tested and still needs a browser check against your installed WebUI version.

## Upload and retrieve

1. Sign into your existing HTTPS Open WebUI address from a computer or phone.
2. Configure language preferences, select **AARTINS** and start a saved chat, not a temporary one.
3. Send `Generate a meeting recap`.
4. Choose a recording in the embedded upload card and press **Upload & generate recap**.
5. Stay connected until upload acceptance. Once queued, the durable worker continues if the browser disconnects.
6. Read operation-specific progress. A high transcription percentage does not mean the report is nearly finished.
7. Read the recap in chat; full transcript/evidence remain archived.

Use the card, not the normal paperclip/microphone, which may invoke WebUI's independent processing path. Existing audio files are supported; in-browser recording is not implemented. On iPhone, export a Voice Memos recording to Files first if necessary.

To reconnect or retrieve an existing result, use the same model and account:

```text
status YOUR_32_CHARACTER_JOB_ID
```

This does not resubmit audio. Stop generating/closing chat does not cancel an accepted job; automatic delivery to an interrupted response is not guaranteed. Another WebUI account cannot retrieve the job. CLI jobs belong to `local-cli` and are checked through the CLI.

## CLI alternative

For the generic installation:

```bash
cd ~/aartins
set -a
. ./worker.env
set +a
"$HOME/aartins/.venv/bin/python" submit_meeting.py /absolute/path/to/recording.m4a
"$HOME/aartins/.venv/bin/python" submit_meeting.py --status YOUR_JOB_ID
```

CLI submissions currently use auto speech detection, mixed mode off and the worker's REPORT_LANGUAGE fallback. User Valves apply to the WebUI Pipe, not the CLI. Completed status prints the archive path. For custom programmatic language settings use the authenticated session API fields documented in the configuration guide.

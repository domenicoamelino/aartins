# Contributing to SMARTINI’s

Improvements to setup, local model compatibility, language support, report quality and reliability are welcome. Read the [architecture](docs/ARCHITECTURE.md) and [development notes](docs/DEVELOPMENT.md) first.

1. Describe the problem or proposed improvement in an issue for substantial changes.
2. Work on a branch and use synthetic audio/text examples in committed tests.
3. Run `python -m unittest discover -s tests -v` from the root.
4. Update relevant instructions when configuration or behavior changes.
5. Submit a pull request describing the change, checks performed and any live-runtime limitations.

Do not include recordings, actual meeting/lecture transcripts, API keys, capability URLs, worker.env, databases or unredacted logs. For a bug report include versions, hardware, job stage and a redacted error. Model output must retain grounding and uncertainty safeguards; do not fix validation failures by silently promoting proposals to confirmed decisions.

Contributions are made under this repository's MIT license. Changes to upstream software or model dependencies must respect their own licenses. Offline tests do not replace real language/model/browser checks; state exactly what you tested.

# About SMARTINI’s

**SMARTINI’s — Local AI Audio Transcription, Notes & Summaries** is a reusable open-source integration of Open WebUI, a Python backend, faster-whisper and an Ollama-hosted local language model.

The aim is to help people reproduce and adapt a workflow that transcribes recordings and turns them into readable summaries on their own hardware. It is a GitHub project, not a subscription service or a commercial product.

## Motivation

The project's author recorded university lectures and spent considerable time transcribing them manually. That experience motivates the broader goal: reduce the manual effort needed to turn recorded speech into useful notes. The first implemented and tested workflow produces meeting recaps. A dedicated lecture profile is a possible next contribution, not an existing feature.

## Scope

- Provide original source, build instructions, configuration and operational notes.
- Keep local model choice, languages and Markdown output configurable.
- Document one tested AMD MINISFORUM environment without requiring that hardware.
- Preserve source evidence and uncertainty rather than treating fluent output as proof of correctness.
- Welcome reusable improvements through ordinary GitHub issues and pull requests.

## What is outside the current implementation

No hosted account service, payment system, live microphone recorder, flashcard/quiz generator, lecture-specific report profile or standalone vector database is supplied. Optional incremental ingestion makes the exported knowledge available through an existing Open WebUI Knowledge collection and its retrieval system.

## Naming and reuse

Use `smartinis` as the filesystem/package slug and display name **SMARTINI’s**. The expanded name is Smart Memo Artificial Recording Transcription Initiative Notes Intelligence software. See [branding](BRANDING.md) for the logo and compatibility policy. The [MIT license](../LICENSE) covers this repository's original source and documentation. Dependencies and model weights retain their own licenses.

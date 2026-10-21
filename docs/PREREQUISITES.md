# Prerequisites and hardware

This repository starts where platform provisioning ends. Install and validate the following independently, then build the integration in [INSTALL.md](INSTALL.md). Existing working installations should not be replaced merely to follow this example.

## Platform software

| Prerequisite | Setup/reference | Check |
|---|---|---|
| Linux with systemd, Python 3.10+ and venv/pip | Your distribution documentation; Python 3.11 is a conservative new-environment choice | `python3 --version` |
| Docker Engine (for reference proxy and optional WebUI container) | [Docker Engine install](https://docs.docker.com/engine/install/) | `docker version` |
| Open WebUI with admin access, Pipe Functions and Rich UI embeds | [Official quick start](https://docs.openwebui.com/getting-started/quick-start/) | Open UI; `curl http://127.0.0.1:8080/api/version` in the reference layout |
| Local Ollama service | [Linux setup](https://docs.ollama.com/linux), [quick start](https://docs.ollama.com/quickstart) | `curl http://127.0.0.1:11434/api/tags` |
| HTTPS access for a phone | Your existing reverse proxy/TLS service; optional [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) | Open the HTTPS UI from the phone |

The provided networking example assumes WebUI listens on host loopback port 8080, the worker on 8765, and the proxy on 8088. A Linux Docker-host-network WebUI container can call the worker at `127.0.0.1`. In a bridge container that address points at the container itself: adapt the network explicitly instead of copying these upstreams unchanged. The worker remains a Linux host process; native Windows/macOS workers are not supported by this systemd/fcntl deployment.

The tested WebUI version was 0.12.3. Use a known image version/digest, preserve its data volume and verify installed `httpx` and `pydantic` before importing the Pipe. Future WebUI versions may change embedding/settings presentation.

## Local model setup example

After following Ollama's official installation guide, choose a **local** model supporting chat, JSON-schema structured output and the languages you need. The tested example is [Qwen 3.5 9B in the Ollama library](https://ollama.com/library/qwen3.5:9b):

```bash
ollama pull qwen3.5:9b
ollama run qwen3.5:9b
```

Send a short prompt, then exit the interactive session with `/bye`. Confirm it appears in `ollama list`. Set `REPORT_MODEL` to the exact installed tag when configuring this project. The reporter discovers thinking controls where available and requests no-thinking mode; other models may behave differently. See [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

Do not substitute a cloud-only model when local processing is required. Models should be evaluated with a short recording before long jobs. Quantization, context size and model architecture affect memory and output quality; parameter count alone is insufficient.

## Hardware planning

These are project planning estimates, **not certified minimums or universal Ollama requirements**. The actual requirement depends on chosen ASR/LLM weights, quantization, context, GPU offload, other services and recording size.

| Profile | Practical starting point | Expectation |
|---|---|---|
| Small-model experiment | 16 GB RAM, modern 64-bit multicore CPU, SSD | Try smaller Whisper/LLM models first; not validated here with large-v3 plus the tested 9B model |
| Reference-sized setup | 32 GB RAM, modern multicore CPU, SSD; compatible GPU optional | Matches the validated memory capacity; still expect substantial processing time |
| Larger local models/concurrent workloads | More RAM/VRAM according to actual selected models | Benchmark before buying; this worker itself still serializes meeting jobs |

Reserve approximately 30 GB of free space as an initial planning allowance for application/model caches, then add room for OS/container images and retained recordings, transcripts and backups. Large or multiple models can exceed that allowance. Measure actual downloads and archive growth rather than treating it as a hard bound. No automatic retention/deletion is implemented.

A GPU is not required by the Python workflow: Whisper currently uses CPU/int8, while Ollama can use whatever acceleration its installation supports. The AMD PoC used Vulkan for Ollama, not ROCm Whisper acceleration. See [Ollama GPU documentation](https://docs.ollama.com/gpu) for actual supported hardware; do not assume every AMD/NVIDIA device is supported. Integrated graphics share system RAM, so 32 GB system RAM is not 32 GB of independent GPU memory.

## ASR dependency

The backend uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper), pinned here to `1.2.1`. Its dependencies include the audio/runtime stack. Follow the installation guide in a fresh virtual environment; do not upgrade an existing known working environment accidentally. This repo pins the direct package but does not yet provide a fully tested cross-platform transitive lock.

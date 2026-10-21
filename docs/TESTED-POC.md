# Tested proof-of-concept environment

This is evidence from one implementation, not required hardware or a vendor recommendation.

| Component | PoC |
|---|---|
| Computer | MINISFORUM UM870 / EliteMini family, AMD integrated graphics |
| System RAM | 32 GB, shared with integrated GPU |
| OS | Ubuntu on the server |
| Open WebUI | 0.12.3, Docker Compose, host networking |
| Ollama acceleration | Vulkan worked in the earlier GPU test; do not assume ROCm support for this device |
| Report model | `qwen3.5:9b`, 4096 reporting context |
| Recognition | faster-whisper 1.2.1, large-v3, CPU/int8, eight threads |
| Remote browser access | Tailscale Serve HTTPS → loopback Nginx 8088 → WebUI/worker |
| Speech evaluated | Dutch/English switching |

The user validated complete CLI reporting, background jobs, status retrieval, archive output, writing-failure recovery and recap-only Open WebUI output. One approximately 16-minute recording took approximately 16 minutes for transcription and another 16 minutes for reporting. This is a single observed run, not a benchmark of other hardware/models or a promise of linear scaling.

The portable revision adds a generic source installation guide and per-user language selection. Its language plumbing/migration has automated tests, but no fresh-machine installation, multilingual quality benchmark or live user-settings browser test has been performed here. Previously validated reporter 2.2.4/Pipe 0.1.1 are retained under Git tag `poc-baseline`.

The PoC's operational paths/service names are retained in [POC-OPERATIONS.md](POC-OPERATIONS.md) for the original owner. New users should follow the generic installation guide and operations runbook. No actual hostname, private key, recording or meeting transcript is needed to reproduce the source repository.

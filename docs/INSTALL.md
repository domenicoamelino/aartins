# Build and connect the integration

This is a Linux reference recipe for **existing** Open WebUI and Ollama services, both reachable on the host. Complete [prerequisites](PREREQUISITES.md) first. Nothing here installs/updates either prerequisite. Back up an existing deployment before changing routes.

## 1. Obtain the source

Clone the GitHub repository that hosts this source, or unpack the source ZIP. Example (replace YOUR_GITHUB_USER with the publisher’s account):

```bash
git clone https://github.com/domenicoamelino/aartins.git ~/smartinis
```

For an unpublished/offline copy, use the supplied Git bundle. Put it at `~/smartinis` for the commands below. If using the supplied history bundle:

```bash
git clone /path/to/smartinis.bundle ~/smartinis
cd ~/smartinis
```

Check that Open WebUI is on loopback 8080 and Ollama on 11434; ports 8765/8088 must be unused:

```bash
curl --fail http://127.0.0.1:8080/api/version
curl --fail http://127.0.0.1:11434/api/tags
ss -ltn 'sport = :8765 or sport = :8088'
```

## 2. Create the backend environment

```bash
cd ~/smartinis
python3 -m venv .venv
"$HOME/smartinis/.venv/bin/python" -m pip install -r requirements-asr.txt
"$HOME/smartinis/.venv/bin/python" -c 'import faster_whisper, av; print("ASR imports OK")'
"$HOME/smartinis/.venv/bin/python" -m unittest discover -s tests -v
```

Use a Python version compatible with the resolved wheels; the source supports Python 3.10+. If your distribution lacks venv/pip, install those through its package manager first. The first model load downloads Whisper weights unless already cached. Pinning faster-whisper does not pin every dependency; after a successful real run save `pip freeze` and Python version privately for reproducibility.

Create a private environment file without overwriting an existing one:

```bash
"$HOME/smartinis/.venv/bin/python" - <<'PY'
from pathlib import Path
import secrets
p = Path('worker.env')
with p.open('x') as f:
    p.chmod(0o600)
    f.write('MEETING_API_KEY=' + secrets.token_hex(32) + '\n')
    f.write('MEETING_ROOT=' + str(Path.home() / 'smartinis-data') + '\n')
    f.write('MEETING_BIND=127.0.0.1\nMEETING_PORT=8765\n')
    f.write('WHISPER_MODEL=large-v3\nWHISPER_THREADS=8\n')
    f.write('REPORT_MODEL=qwen3.5:9b\nREPORT_LANGUAGE=English\nREPORT_TIMEOUT=1200\n')
print('Private settings created')
PY
```

Edit model/thread settings for your machine. `REPORT_MODEL` must match a locally installed tag. Source archives are outside the checkout. New UI requests override the fallback report language with the user's selected recap language.

## 3. Install the durable worker service

```bash
cd ~/smartinis
cat > /tmp/smartinis.service <<EOF
[Unit]
Description=SMARTINI’s worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$HOME/smartinis
EnvironmentFile=$HOME/smartinis/worker.env
Environment=PYTHONUNBUFFERED=1
ExecStart=$HOME/smartinis/.venv/bin/python $HOME/smartinis/meeting_worker.py
Restart=on-failure
RestartSec=5
UMask=0077
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF
sudo install -m 644 /tmp/smartinis.service /etc/systemd/system/smartinis.service
sudo systemctl daemon-reload
sudo systemctl enable --now smartinis
curl --retry 5 --retry-connrefused --retry-delay 1 --fail http://127.0.0.1:8765/health
```

Expected: `{"ok": true, "worker_alive": true}`. On failure inspect `journalctl -u smartinis -n 60 --no-pager`. The service uses the server's timezone; choose its configured timezone deliberately for processing-date folders.

## 4. Add the reference proxy

This does not recreate WebUI. The proxy listens only on host loopback 8088 and routes `/meeting-ui/` to the worker, other requests to WebUI 8080. The supplied config assumes a public HTTPS entry point; local HTTP checks below test reachability only.

```bash
cd ~/smartinis
sudo docker pull nginx:stable-alpine
RECAP_PROXY_IMAGE="$(sudo docker image inspect nginx:stable-alpine --format '{{index .RepoDigests 0}}')"
sudo docker run --rm --network host   --mount "type=bind,src=$PWD/deploy/nginx.conf,dst=/etc/nginx/conf.d/default.conf,readonly"   "$RECAP_PROXY_IMAGE" nginx -t
```

Only after the config test passes:

```bash
sudo docker run -d --name smartinis-proxy --restart unless-stopped --network host   --mount "type=bind,src=$PWD/deploy/nginx.conf,dst=/etc/nginx/conf.d/default.conf,readonly"   "$RECAP_PROXY_IMAGE"
curl --fail http://127.0.0.1:8088/meeting-proxy-health
curl --fail http://127.0.0.1:8088/api/version
```

Expect `meeting proxy ready` and your WebUI version. Configure your existing HTTPS entry point to forward to 127.0.0.1:8088. Optional Tailscale example, when replacing an existing root Serve route:

```bash
sudo tailscale serve status
sudo tailscale serve --bg http://127.0.0.1:8088
```

Record the previous route before switching; restore it if tests fail. Other TLS proxies are valid alternatives, but must forward uploads, WebSockets and long-running responses. Check the public `/meeting-proxy-health` and normal login page from the phone before importing the Function. Do not expose worker 8765 or Ollama 11434 directly to the public internet.

## 5. Install the Open WebUI Pipe

As an administrator, go to **Admin Panel → Functions**, create a function, paste all of `openwebui_meeting_pipe.py`, save and enable it. It appears as **SMARTINI’s** in the model selector. Function code executes on the WebUI server; import the reviewed repository source, not an unknown snippet.

Configure admin **Valves**:

| Setting | Reference value |
|---|---|
| WORKER_URL | `http://127.0.0.1:8765` for host-network/host-process WebUI |
| WORKER_API_KEY | Value from private `worker.env` |
| PUBLIC_ORIGIN | Your browser's HTTPS origin, e.g. `https://your-server.example`, without path |
| POLL_SECONDS / WAIT_SECONDS | Keep defaults for first test |

To display the key locally: `sed -n 's/^MEETING_API_KEY=//p' ~/smartinis/worker.env`. Copy it directly into admin Valves; don't post it in chat or commit it. Verify WebUI can reach worker health from its own runtime. If container name is `open-webui`, use:

```bash
sudo docker exec open-webui python -c 'import httpx,pydantic,urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8765/health").read().decode())'
```

## 6. Select languages and validate

Choose the function's **User Valves** in Open WebUI and set recording language, mixed-language mode and recap language. The exact settings entry point varies by WebUI version; see [user tutorial](TUTORIAL.md). Start a saved chat using SMARTINI’s, send `Generate a meeting recap`, then upload a short recording via the card. Confirm progress, recap-only chat output and archived transcript/report before trying a long recording.

## Existing PoC users upgrading language settings

Keep your original paths/service names; do not follow steps 1–4 to create a second running worker. Back up the job database and current source while idle. Deploy `meeting_worker.py`, `meeting_report.py`, `meeting_knowledge.py`, `upload.html` and `recover_meeting_job.py` together, then restart your existing service. The worker adds nullable language columns to the existing SQLite table; it does not replace jobs or owner IDs. Old jobs preserve their legacy multilingual behavior. Deploy Pipe 0.2.0 in WebUI, retain admin Valves and configure User Valves. New jobs snapshot selected settings; old cached reports are unchanged. See [PoC operations](POC-OPERATIONS.md) for its specific paths and [MVP 3.1 stabilization](MVP31-STABILIZATION.md) before upgrading a working installation. New upload clients must supply the metadata header; update the CLI helper too if you use it.

#!/usr/bin/env python3
"""Submit audio to the local worker, or inspect a previously submitted job."""
import argparse
import http.client
import json
import os
from pathlib import Path
import uuid
from urllib.parse import quote


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("audio", nargs="?", type=Path)
    p.add_argument("--status", metavar="JOB_ID")
    a = p.parse_args()
    key = os.environ.get("MEETING_API_KEY", "")
    if len(key) < 32:
        p.error("Load worker.env into this terminal first (see guide)")
    headers = {"Authorization": "Bearer " + key, "X-Owner-Id": "local-cli"}

    def request(method, path, body=None, extra=None):
        c = http.client.HTTPConnection("127.0.0.1", 8765, timeout=600)
        try:
            c.request(method, path, body=body, headers={**headers, **(extra or {})})
            r = c.getresponse()
            data = json.loads(r.read())
            if r.status >= 400:
                raise RuntimeError(f"HTTP {r.status}: {data.get('error', data)}")
            return data
        finally:
            c.close()

    try:
        if a.status:
            if a.audio or len(a.status) != 32 or any(ch not in "0123456789abcdef" for ch in a.status):
                p.error("Use --status with a 32-character job ID and no audio path")
            result = request("GET", "/v1/sessions/" + a.status)
            for field in ("id", "state", "detail", "percent", "error", "archive"):
                if result.get(field) is not None:
                    print(f"{field}: {result[field]}")
            return
        if not a.audio or not a.audio.is_file():
            p.error("Provide an existing audio file, or --status JOB_ID")
        result = request("POST", "/v1/sessions", json.dumps({"owner": "local-cli", "request_key": uuid.uuid4().hex}), {"Content-Type": "application/json"})
        print("Job ID:", result["id"], flush=True)
        print("Uploading recording to the local worker...", flush=True)
        with a.audio.open("rb") as f:
            result = request("POST", "/meeting-ui/upload/" + result["upload_token"], f,
                             {"Content-Length": str(a.audio.stat().st_size), "X-Filename": quote(a.audio.name), "Content-Type": "application/octet-stream"})
        print("State:", result["state"])
        print("Upload accepted. You can close this terminal; processing continues.")
    except (OSError, RuntimeError, ValueError) as e:
        p.exit(1, f"ERROR: {e}\n")


if __name__ == "__main__":
    main()

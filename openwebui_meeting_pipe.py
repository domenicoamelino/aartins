"""
title: AARTINS
author: Local AI project
version: 0.2.0
description: Upload meeting audio inside chat, run durable local jobs, return cited Markdown.
"""
import asyncio
import html
import re
import time
from urllib.parse import urlsplit
from typing import Literal

import httpx
from pydantic import BaseModel, Field


class Pipe:
    class UserValves(BaseModel):
        AUDIO_LANGUAGE: Literal["auto", "en", "nl", "it", "de", "fr", "es", "pt", "zh", "ja", "ko", "ar", "hi", "ru", "uk", "pl", "tr"] = Field(
            default="auto", description="Spoken language code; auto detects it. With mixed-language mode, this is an initial language hint.")
        MIXED_LANGUAGES: bool = Field(default=False, description="Detect language changes across segments; requires a multilingual Whisper model. No fixed language pair.")
        RECAP_LANGUAGE: Literal["English", "Dutch", "Italian", "German", "French", "Spanish", "Portuguese", "Chinese", "Japanese", "Korean", "Arabic", "Hindi", "Russian", "Ukrainian", "Polish", "Turkish"] = Field(
            default="English", description="Language requested for the recap; independent of the recording language.")

    class Valves(BaseModel):
        WORKER_URL: str = Field(default="http://127.0.0.1:8765")
        WORKER_API_KEY: str = Field(default="", json_schema_extra={"input": {"type": "password"}})
        PUBLIC_ORIGIN: str = Field(default="", description="The browser's Open WebUI origin, e.g. http://192.168.1.10:8088; no trailing path")
        POLL_SECONDS: int = Field(default=3, ge=2, le=30)
        WAIT_SECONDS: int = Field(default=21600, ge=60, le=86400)

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __user__: dict = None, __event_emitter__=None,
                   __chat_id__: str = None, __message_id__: str = None, __task__: str = None):
        if __task__:
            return "Meeting recap"
        if not __user__ or not __user__.get("id"):
            return "Sign in to Open WebUI before starting a meeting job."
        origin = self.valves.PUBLIC_ORIGIN.rstrip("/")
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            return "Admin setup required: set PUBLIC_ORIGIN to the Open WebUI browser address with no path."
        if not self.valves.WORKER_API_KEY:
            return "Admin setup required: configure WORKER_API_KEY in the Function valves."
        owner = str(__user__["id"])
        preferences = __user__.get("valves") or self.UserValves()
        def preference(name, default):
            return preferences.get(name, default) if isinstance(preferences, dict) else getattr(preferences, name, default)
        headers = {"Authorization": "Bearer " + self.valves.WORKER_API_KEY, "X-Owner-Id": owner}
        async def event(kind, data):
            if __event_emitter__:
                try:
                    await __event_emitter__({"type": kind, "data": data})
                except Exception:
                    pass  # UI connection loss must not cancel the durable worker job.
        async def status(text, done=False):
            await event("status", {"description": text, "done": done, "hidden": False})
        def last_user():
            for msg in reversed(body.get("messages", [])):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        return " ".join(x.get("text", "") for x in content if isinstance(x, dict))
                    return str(content)
            return ""
        match = re.fullmatch(r"\s*status\s+([a-f0-9]{32})\s*", last_user(), re.I)
        jid = match[1].lower() if match else None
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            try:
                if not jid:
                    if not __chat_id__ or not __message_id__:
                        return "Start a saved Open WebUI chat so the upload has a stable request ID."
                    r = await client.post(self.valves.WORKER_URL.rstrip("/") + "/v1/sessions", headers=headers,
                                          json={"owner": owner, "request_key": str(__chat_id__) + ":" + str(__message_id__),
                                                "audio_language": preference("AUDIO_LANGUAGE", "auto"),
                                                "mixed_languages": preference("MIXED_LANGUAGES", False),
                                                "report_language": preference("RECAP_LANGUAGE", "English")})
                    r.raise_for_status()
                    session = r.json()
                    jid = session["id"]
                    url = origin + "/meeting-ui/view/" + session["upload_token"]
                    await event("embeds", {"embeds": [url], "replace": True})
                    await status(f"Choose your audio in the upload card. Audio: {preference('AUDIO_LANGUAGE', 'auto')}; mixed languages: {preference('MIXED_LANGUAGES', False)}; recap: {preference('RECAP_LANGUAGE', 'English')}. Job: {jid}")
                started, last = time.monotonic(), None
                while time.monotonic() - started < self.valves.WAIT_SECONDS:
                    r = await client.get(self.valves.WORKER_URL.rstrip("/") + "/v1/sessions/" + jid, headers=headers)
                    if r.status_code == 404:
                        await status("Job unavailable for this account", True)
                        return "Job not found or belongs to another account."
                    r.raise_for_status()
                    job = r.json()
                    if job["state"] == "completed":
                        await status("Complete — report archived on the server", True)
                        # Chat receives the readable recap; evidence stays in the archive.
                        text = re.sub(
                            r"<details>\s*<summary>Source references and review notes</summary>.*?</details>",
                            "", job["report"], flags=re.S)
                        text = re.sub(r"\s*\[↗\]\(#note-\d+\)", "", text)
                        text = re.sub(r"\[([^\]]+)\]\(transcript\.md(?:#[^)]+)?\)", r"\1", text)
                        return text.strip()
                    if job["state"] == "failed":
                        await status("Processing failed; recording retained", True)
                        return "Meeting processing failed. Source and partial results remain on the server.\n\n" + html.escape(job.get("error") or "Inspect the worker log.") + "\n\nJob: `" + jid + "`"
                    signature = (job["state"], job["detail"], job["percent"])
                    if signature != last:
                        percent = f" ({job['percent']:.0f}% of this stage)" if job.get("percent") is not None else ""
                        await status(job["detail"] + percent + f" Â· Job: {jid}")
                        last = signature
                    if job["state"] == "waiting_upload" and time.time() - job["created"] > 1800:
                        await status("Upload window expired", True)
                        return "No file was uploaded within 30 minutes. Send a new request to get a new upload card."
                    await asyncio.sleep(self.valves.POLL_SECONDS)
                await status("Server job remains available; chat waiting limit reached", True)
                return f"The job remains on the server. Send `status {jid}` to check progress or retrieve the report."
            except asyncio.CancelledError:
                # Phone disconnect / Stop generating affects this waiter, not the job.
                raise
            except Exception as e:
                await status("Connection to worker interrupted", True)
                recovery = f" Send `status {jid}` to reconnect." if jid else " Start a new request after checking the worker."
                return "Could not reach the meeting worker. Any already queued job continues on the server." + recovery + "\n\n" + html.escape(str(e)[:500])

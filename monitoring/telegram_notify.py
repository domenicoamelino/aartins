"""Small Telegram notifier. No model calls or third-party dependencies."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo


class NotificationError(RuntimeError):
    """A deliberately sanitized notification error."""


_TOKEN = re.compile(r"[0-9]+:[A-Za-z0-9_-]{20,}\Z")
_METHODS = {"getMe", "getUpdates", "sendMessage"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(token, method, payload=None, timeout=15):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        raise NotificationError("Invalid Telegram bot token.")
    if method not in _METHODS:
        raise NotificationError("Unsupported Telegram operation.")
    try:
        data = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/{method}", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise NotificationError("Telegram response exceeded the size limit.")
        result = json.loads(raw)
    except NotificationError:
        raise
    except urllib.error.HTTPError:
        raise NotificationError("Telegram rejected the request.") from None
    except Exception:
        raise NotificationError("Telegram connection or response failed.") from None
    if not isinstance(result, dict) or result.get("ok") is not True or "result" not in result:
        raise NotificationError("Telegram did not accept the operation.")
    return result["result"]


def read_token(path):
    path = Path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise NotificationError("Telegram token must be a regular file.")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600:
            raise NotificationError("Telegram token file must have permissions 600.")
        token = path.read_text(encoding="utf-8").strip()
    except NotificationError:
        raise
    except Exception:
        raise NotificationError("Could not read Telegram token file.") from None
    if not _TOKEN.fullmatch(token):
        raise NotificationError("Invalid Telegram bot token.")
    return token


def _datetime(value):
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed


def eligible(trigger, finished_iso, timezone="Europe/Amsterdam"):
    if trigger != "service":
        return False
    try:
        return _datetime(finished_iso).astimezone(ZoneInfo(timezone)).weekday() < 5
    except (ValueError, TypeError, KeyError):
        return False


def _local(value):
    try:
        return _datetime(value).astimezone(ZoneInfo("Europe/Amsterdam")).strftime("%Y-%m-%d %H:%M %Z")
    except (ValueError, TypeError):
        return "unavailable"


def _count(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def format_message(run, dashboard_url):
    status = run.get("status", "failed")
    if status not in {"running", "completed", "failed", "deferred", "interrupted"}:
        status = "failed"
    duration = run.get("duration_seconds", 0)
    errors = run.get("errors") or []
    error_count = len(errors) if isinstance(errors, (list, dict)) else _count(errors)
    return "\n".join([
        f"SMARTINI’s meeting ingestion: {status}",
        f"Started: {_local(run.get('started'))}",
        f"Finished: {_local(run.get('finished'))}",
        f"Duration: {_count(duration)} seconds",
        " | ".join(f"{name}: {_count(run[name]) if run.get(name) is not None else 'unavailable'}"
                   for name in ("uploaded", "adopted", "unchanged", "skipped")),
        f"Errors: {error_count}",
        str(dashboard_url),
    ])


def send_report(token, chat_id, run, dashboard_url):
    result = api(token, "sendMessage", {
        "chat_id": chat_id,
        "text": format_message(run, dashboard_url),
        "disable_web_page_preview": True,
    })
    if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
        raise NotificationError("Telegram returned no delivery identifier.")
    return result["message_id"]


def discover_chats(token):
    updates = api(token, "getUpdates", {
        "timeout": 0, "limit": 100, "allowed_updates": ["message"]})
    if not isinstance(updates, list):
        raise NotificationError("Telegram returned an invalid chat list.")
    chats = {}
    for update in updates:
        if not isinstance(update, dict):
            continue
        message = update.get("message") or {}
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        if not isinstance(chat, dict):
            continue
        if chat.get("type") != "private" or not isinstance(chat.get("id"), int):
            continue
        label = " ".join(str(chat.get(key) or "") for key in ("first_name", "last_name")).strip()
        if not label:
            label = str(chat.get("username") or "Private chat")
        chats[chat["id"]] = {"id": chat["id"], "label": label}
    return list(chats.values())

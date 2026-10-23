"""Reuse the existing monitor bot with explicit owner -> chat binding. No model calls."""
import importlib.util
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import meeting_review as review


def deliver_next(root):
    home = Path(os.environ.get('MEETING_MONITOR_HOME', str(Path.home()/'ai-platform/ingestion-monitor'))).expanduser()
    binding = home/'meeting-notifications.json'
    if not binding.exists():
        return False
    try:
        config = json.loads(binding.read_text(encoding='utf-8'))
        owners = config.get('owner_chats', {})
        if config.get('enabled') is not True or not isinstance(owners, dict):
            return False
        spec = importlib.util.spec_from_file_location('existing_telegram_notifier', home/'telegram_notify.py')
        telegram = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(telegram)
        token = telegram.read_token(home/'telegram-token.txt')
    except Exception:
        return False  # Unconfigured/temporarily unavailable; no meeting job is affected.
    with review.connection(root) as c:
        c.execute('BEGIN IMMEDIATE')
        row = next((r for r in c.execute("SELECT * FROM notices WHERE status='pending' ORDER BY updated") if r['owner'] in owners), None)
        if row is None:
            return False
        row = dict(row)
        chat = owners[row['owner']]
        if type(chat) is not int and (not isinstance(chat, str) or not chat.lstrip('-').isdigit()):
            return False
        c.execute("UPDATE notices SET status='sending',updated=? WHERE key=?", (time.time(), row['key']))
    text = "SMARTINI’s: " + row['text'] + '\nJob: ' + row['id'] + '\nIn Open WebUI send: review ' + row['id']
    origin = config.get('openwebui_url', '')
    parsed = urlsplit(origin) if isinstance(origin, str) else None
    if parsed and parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
        text += '\n' + origin.rstrip('/')
    try:
        telegram.api(token, 'sendMessage', {'chat_id': chat, 'text': text, 'disable_web_page_preview': True})
        status = 'sent'
    except Exception:
        # A lost response may follow accepted delivery. Do not auto-resend ambiguously.
        status = 'uncertain'
    with review.connection(root) as c:
        c.execute('UPDATE notices SET status=?,updated=? WHERE key=?', (status, time.time(), row['key']))
    return True


def loop(root, stop):
    while not stop.wait(5):
        try:
            deliver_next(root)
        except Exception:
            pass

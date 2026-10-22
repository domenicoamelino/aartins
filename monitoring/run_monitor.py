#!/usr/bin/env python3
"""Local ingestion run history, private dashboard and weekday Telegram reports."""
import argparse
import base64
from contextlib import closing, contextmanager
import datetime as dt
import getpass
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid
from zoneinfo import ZoneInfo

import telegram_notify as telegram

HOME = Path.home() / 'ai-platform/ingestion-monitor'
INGESTION_HOME = Path.home() / 'ai-platform/ingestion'
TIMEZONE = 'Europe/Amsterdam'
COUNTS = ('uploaded', 'adopted', 'unchanged', 'skipped', 'planned')


class MonitorError(Exception):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp-' + secrets.token_hex(6))
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR, 0o600), 'r+b')
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                if path.stat().st_size == 0:
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise MonitorError('A monitored ingestion run is already active') from None
        yield
    finally:
        handle.close()


class History:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / 'history.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, started TEXT NOT NULL, finished TEXT,
                status TEXT NOT NULL, trigger TEXT NOT NULL, exit_code INTEGER,
                details TEXT NOT NULL, notification_status TEXT NOT NULL,
                notification_error TEXT, notification_message_id TEXT,
                notification_updated TEXT)''')
        if os.name != 'nt':
            self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def start(self, trigger):
        rid = uuid.uuid4().hex
        details = {key: None for key in COUNTS}
        details.update(errors=[], duration_seconds=None, activity='Starting ingestion')
        with self.connect() as db:
            db.execute('INSERT INTO runs (id,started,status,trigger,details,notification_status) VALUES (?,?,?,?,?,?)',
                       (rid, now(), 'running', trigger, json.dumps(details), 'pending'))
        return rid

    def get(self, rid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
        return self.unpack(row) if row else None

    @staticmethod
    def unpack(row):
        result = dict(row)
        details = json.loads(result.pop('details'))
        return {**result, **details}

    def runs(self, limit=200):
        with self.connect() as db:
            return [self.unpack(row) for row in db.execute('SELECT * FROM runs ORDER BY started DESC,rowid DESC LIMIT ?', (limit,))]

    def count(self):
        with self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]

    def activity(self, rid, message):
        with self.connect() as db:
            row = db.execute('SELECT details FROM runs WHERE id=?', (rid,)).fetchone()
            data = json.loads(row['details'])
            data['activity'] = str(message)[:600]
            db.execute('UPDATE runs SET details=? WHERE id=?', (json.dumps(data), rid))

    def finish(self, rid, status, code, report=None, error=None, elapsed=None):
        report = report or {}
        errors = []
        for item in report.get('errors', []):
            errors.append(str(item.get('error', 'Ingestion error'))[:1000] if isinstance(item, dict) else str(item)[:1000])
        if error:
            errors.append(error)
        details = {key: report.get(key) for key in COUNTS}
        details.update(errors=errors, duration_seconds=elapsed, activity='Finished')
        with self.connect() as db:
            db.execute('UPDATE runs SET finished=?,status=?,exit_code=?,details=? WHERE id=?',
                       (now(), status, code, json.dumps(details), rid))

    def notification(self, rid, status, error=None, message_id=None):
        with self.connect() as db:
            db.execute('UPDATE runs SET notification_status=?,notification_error=?,notification_message_id=?,notification_updated=? WHERE id=?',
                       (status, error, str(message_id) if message_id is not None else None, now(), rid))

    def stale(self):
        # Caller must own monitor.lock: a previous running row cannot belong to a live wrapper.
        stale_ids = []
        with self.connect() as db:
            for row in db.execute("SELECT id FROM runs WHERE status='running'").fetchall():
                stale_ids.append(row['id'])
        for rid in stale_ids:
            self.finish(rid, 'interrupted', 130, error='Previous monitored run ended without a final result; completion was not assumed.')
        return stale_ids


def load_config(home):
    config = read_json(Path(home) / 'monitor.json')
    origin = config.get('public_origin', '')
    parsed = urlsplit(origin)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise MonitorError('Invalid dashboard origin')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
        raise MonitorError('Dashboard requires HTTPS; local HTTP is allowed only for local testing')
    if not re.fullmatch(r'[0-9a-f]{64}', config.get('password_hash', '')) or not re.fullmatch(r'[0-9a-f]{32}', config.get('password_salt', '')):
        raise MonitorError('Dashboard password configuration is incomplete')
    # Keep the complete configuration and all secrets out of the public API.
    return config


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()


def ingestion_module(path):
    path = Path(path)
    spec = importlib.util.spec_from_file_location('existing_meeting_ingestion', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = ('locked', 'load_config', 'State', 'Client', 'load_key', 'sync', 'save_json', 'IngestionError')
    if module.VERSION not in ('1.0.0', '1.0.1') or any(not hasattr(module, name) for name in required):
        raise MonitorError('Expected the existing meeting ingestion 1.0.0 or 1.0.1 interface')
    return module


def notify(history, rid, config, home, allow_retry=False):
    run = history.get(rid)
    if not run or run['status'] == 'running':
        raise MonitorError('A completed run is required for notification')
    if run['notification_status'] == 'sent' or (run['notification_status'] in ('sending', 'uncertain') and not allow_retry):
        return  # Do not blindly repeat an accepted or ambiguous delivery.
    if not telegram.eligible(run['trigger'], run['finished'], TIMEZONE):
        history.notification(rid, 'skipped-weekend' if run['trigger'] == 'service' else 'skipped-manual')
        return
    if not config.get('telegram_chat_id') or not (Path(home) / 'telegram-token.txt').is_file():
        history.notification(rid, 'not-configured')
        return
    if run['notification_status'] == 'failed' and not allow_retry:
        return
    # Manual retries still respect weekdays at actual delivery time.
    if dt.datetime.now(ZoneInfo(TIMEZONE)).weekday() >= 5:
        history.notification(rid, 'skipped-weekend')
        return
    history.notification(rid, 'sending')
    try:
        token = telegram.read_token(Path(home) / 'telegram-token.txt')
        mid = telegram.send_report(token, config['telegram_chat_id'], run, config['public_origin'])
        history.notification(rid, 'sent', message_id=mid)
    except telegram.NotificationError as exc:
        # A timeout can mean Telegram accepted the message but its response was lost.
        # No automatic resend: avoid duplicate daily notifications.
        history.notification(rid, 'uncertain', str(exc))


def run_ingestion(home, trigger='manual', ingestion_home=INGESTION_HOME):
    history = History(home)
    with exclusive(Path(home) / 'monitor.lock'):
        history.stale()
        rid = history.start(trigger)
        started = time.monotonic()
        report, status, code, error, module = None, 'failed', 1, None, None
        try:
            config = load_config(home)
            module = ingestion_module(Path(ingestion_home) / 'ingest_meetings.py')
            previous_emit = module.emit
            def progress(message):
                previous_emit(message)
                history.activity(rid, message)
            module.emit = progress
            with module.locked(Path(ingestion_home) / 'ingestion.lock'):
                ic = module.load_config(Path(ingestion_home) / 'config.json')
                state = module.State(Path(ingestion_home) / 'state.json', ic)
                client = module.Client(ic['base_url'], module.load_key(Path(ingestion_home) / 'api-key.txt'), ic.get('request_timeout_seconds', 120))
                report = module.sync(client, ic, state, apply=True)
                module.save_json(Path(ingestion_home) / 'last-run.json', report)
                if report['errors']:
                    status, code = 'failed', 1
                elif report['deferred']:
                    status, code = 'deferred', 75
                else:
                    status, code = 'completed', 0
        except KeyboardInterrupt:
            status, code, error = 'interrupted', 130, 'Run interrupted; remote processing may still finish. Resume ingestion from saved state.'
        except Exception as exc:
            # Never echo arbitrary exception text, which might contain credential URLs.
            status, code, error = 'failed', 1, f'Ingestion could not finish ({type(exc).__name__}); inspect local configuration and service logs.'
            if isinstance(exc, MonitorError) or (module is not None and isinstance(exc, module.IngestionError)):
                error = str(exc)[:1500]
                if 'Another ingestion operation is running' in error:
                    status, code = 'deferred', 75
            print('MONITOR ' + error, flush=True)
        finally:
            history.finish(rid, status, code, report, error, round(time.monotonic() - started, 2))
        print(f'MONITOR run={rid} status={status} exit={code}', flush=True)
        try:
            notify(history, rid, load_config(home), home)
        except Exception:
            history.notification(rid, 'failed', 'Notification setup could not be read; ingestion result is retained.')
        return code


def schedule_info():
    try:
        result = subprocess.run(['systemctl', '--user', 'show', 'meeting-ingestion.timer',
                                 '-p', 'ActiveState', '-p', 'NextElapseUSecRealtime'],
                                capture_output=True, text=True, timeout=3,
                                env={**os.environ, 'TZ': TIMEZONE})
        if result.returncode:
            raise ValueError()
        props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        raw = props.get('NextElapseUSecRealtime', '')
        match = re.search(r'(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(\S+)', raw)
        value = None
        if match and match[3] in ('CET', 'CEST', 'UTC', 'GMT'):
            zone = dt.timezone.utc if match[3] in ('UTC', 'GMT') else ZoneInfo(TIMEZONE)
            value = dt.datetime.fromisoformat(match[1] + 'T' + match[2]).replace(tzinfo=zone).isoformat()
        return {'enabled': props.get('ActiveState') == 'active', 'next_run': value, 'timezone': TIMEZONE}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'enabled': None, 'next_run': None, 'timezone': TIMEZONE}


def configure(home):
    home = Path(home)
    if (home / 'monitor.json').exists():
        raise MonitorError('Dashboard configuration already exists; it was not overwritten')
    home.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        home.chmod(0o700)
    dns = ''
    try:
        output = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=5, check=True)
        dns = json.loads(output.stdout).get('Self', {}).get('DNSName', '').rstrip('.')
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    default = f'https://{dns}:8443' if dns else ''
    origin = input(f'Dashboard HTTPS origin [{default}]: ').strip() or default
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.ts.net') or parsed.port != 8443 or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise MonitorError('Use https://YOUR-TAILSCALE-HOST.ts.net:8443 without a path')
    password = getpass.getpass('Choose a dashboard password (at least 12 characters; hidden): ')
    if len(password) < 12 or password != getpass.getpass('Repeat dashboard password: '):
        raise MonitorError('Passwords must match and contain at least 12 characters')
    salt = secrets.token_hex(16)
    atomic(home / 'monitor.json', {'public_origin': origin.rstrip('/'), 'password_salt': salt,
                                  'password_hash': password_hash(password, salt), 'telegram_chat_id': None,
                                  'web_port': 8788, 'timezone': TIMEZONE})
    History(home)
    print('Dashboard configured. Telegram setup is a separate command; no message was sent.', flush=True)


def configure_telegram(home):
    config = load_config(home)
    print('Create a dedicated bot with @BotFather. Open that bot in Telegram and send /start first.', flush=True)
    token = getpass.getpass('Telegram bot token (hidden): ').strip()
    print('Checking bot identity (15-second network timeout)...', flush=True)
    me = telegram.api(token, 'getMe')
    print('Bot: @' + me.get('username', '(unnamed)'), flush=True)
    chats = telegram.discover_chats(token)
    if not chats:
        raise MonitorError('No private chat found. Send /start to this bot in Telegram, then run setup again.')
    for index, chat in enumerate(chats, 1):
        print(f'{index}. {chat["label"]} | chat ID {chat["id"]}')
    selection = input('Your private chat number: ').strip()
    if not selection.isdigit() or not 1 <= int(selection) <= len(chats):
        raise MonitorError('Choose a listed chat number')
    path = Path(home) / 'telegram-token.txt'
    # Do not write the token in monitor.json or expose it to the browser.
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(token + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    if os.name != 'nt':
        path.chmod(0o600)
    config['telegram_chat_id'] = chats[int(selection) - 1]['id']
    atomic(Path(home) / 'monitor.json', config)
    print('Telegram configured. Use test-telegram to send one explicit test message.', flush=True)


def set_password(home):
    config = load_config(home)
    password = getpass.getpass('New dashboard password (at least 12 characters; hidden): ')
    if len(password) < 12 or password != getpass.getpass('Repeat new password: '):
        raise MonitorError('Passwords must match and contain at least 12 characters')
    config['password_salt'] = secrets.token_hex(16)
    config['password_hash'] = password_hash(password, config['password_salt'])
    atomic(Path(home) / 'monitor.json', config)
    print('Dashboard password updated. Existing browser sessions are invalidated.', flush=True)


LOGIN = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SMARTINI’s · Run history</title><style>body{font:16px system-ui;background:#0b1220;color:#e9f0f7;display:grid;place-items:center;min-height:100vh;margin:0}main{width:min(360px,84vw);padding:32px;border:1px solid #283549;border-radius:18px;background:#131e30}small,p{color:#a4b3c7;line-height:1.6}h1{font-size:25px}label{display:block;margin-top:25px}input,button{box-sizing:border-box;width:100%;padding:13px;margin-top:10px;border-radius:9px;font:inherit}input{border:1px solid #53647d;background:#0b1220;color:#fff}button{background:#91ebc4;color:#10291f;border:0;font-weight:650;cursor:pointer}:focus-visible{outline:3px solid #fff;outline-offset:3px}.error{color:#ffbab7}</style><main><small>PRIVATE · SMARTINI’s</small><h1>Meeting run history</h1><p>Sign in to view ingestion results and weekday notification status.</p>__ERROR__<form method="post" action="/login"><label for="password">Dashboard password</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus><button>Sign in</button></form></main></html>'''


class MonitorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, home):
        self.home = Path(home)
        self.history = History(home)
        self.sessions = {}
        self.failures = []
        self.mutex = threading.Lock()
        self.schedule_cache = (0, {})
        super().__init__(address, WebHandler)


class WebHandler(BaseHTTPRequestHandler):
    server_version = 'SMARTINIsRunHistory/1.0'

    def log_message(self, *_):
        pass  # Never log passwords, cookies or request paths containing secrets.

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def respond(self, status, data, content_type='application/json', headers=None):
        blob = json.dumps(data).encode() if content_type == 'application/json' else data.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(blob)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        if content_type == 'text/html':
            scripts = re.findall(r'<script>([\s\S]*?)</script>', data)
            styles = re.findall(r'<style>([\s\S]*?)</style>', data)
            def hashes(items):
                return ' '.join("'sha256-" + base64.b64encode(hashlib.sha256(v.encode()).digest()).decode() + "'" for v in items) or "'none'"
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src " + hashes(scripts) +
                             '; style-src ' + hashes(styles) + "; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(blob)

    def context(self):
        config = load_config(self.server.home)
        expected = urlsplit(config['public_origin'])
        allowed = {expected.netloc, f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in allowed:
            self.respond(421, {'error': 'Unexpected host'})
            return None
        return config

    def authenticated(self, config):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            token = cookie['run_session'].value
        except (KeyError, ValueError):
            return False
        with self.server.mutex:
            current = time.time()
            self.server.sessions = {k: v for k, v in self.server.sessions.items() if v[0] > current}
            session = self.server.sessions.get(token)
            return bool(session and session[1] == config['password_hash'])

    def do_GET(self):
        try:
            config = self.context()
            if config is None:
                return
            path = urlsplit(self.path).path
            if path == '/health':
                return self.respond(200, {'ok': True})
            if path == '/login':
                return self.respond(200, LOGIN.replace('__ERROR__', ''), 'text/html')
            if not self.authenticated(config):
                if path.startswith('/api/'):
                    return self.respond(401, {'error': 'Sign in required'})
                return self.respond(303, '', 'text/plain', {'Location': '/login'})
            if path == '/':
                return self.respond(200, (Path(__file__).parent / 'dashboard.html').read_text(encoding='utf-8'), 'text/html')
            if path == '/api/runs':
                runs = self.server.history.runs()
                with self.server.mutex:
                    cached_at, schedule = self.server.schedule_cache
                if time.monotonic() - cached_at > 15:
                    schedule = schedule_info()
                    with self.server.mutex:
                        self.server.schedule_cache = (time.monotonic(), schedule)
                last_service = next((r['started'] for r in runs if r['trigger'] == 'service'), None)
                overdue = bool(schedule.get('enabled') and last_service and
                               dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last_service) > dt.timedelta(hours=30))
                return self.respond(200, {'runs': runs, 'summary': {'latest_status': runs[0]['status'] if runs else None,
                                          'last_finished': next((r['finished'] for r in runs if r['finished']), None),
                                          'total_runs': self.server.history.count()},
                                          'schedule': schedule, 'telegram': {'configured': bool(config.get('telegram_chat_id') and (self.server.home / 'telegram-token.txt').is_file())},
                                          'service_health': {'overdue': overdue, 'last_service_started': last_service},
                                          'server_time': now()})
            self.respond(404, {'error': 'Not found'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.respond(503, {'error': 'Dashboard data unavailable; check local monitor configuration and service logs'})

    def do_POST(self):
        try:
            config = self.context()
            if config is None:
                return
            if self.headers.get('Origin') != config['public_origin']:
                return self.respond(403, {'error': 'Unexpected origin'})
            path = urlsplit(self.path).path
            if path == '/logout':
                try:
                    cookie = SimpleCookie(self.headers.get('Cookie', ''))
                    with self.server.mutex:
                        self.server.sessions.pop(cookie['run_session'].value, None)
                except (KeyError, ValueError):
                    pass
                return self.respond(200, {'ok': True}, headers={'Set-Cookie': 'run_session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict'})
            if path != '/login':
                return self.respond(404, {'error': 'Not found'})
            with self.server.mutex:
                self.server.failures = [t for t in self.server.failures if time.time() - t < 300]
                limited = len(self.server.failures) >= 10
            if limited:
                return self.respond(429, {'error': 'Too many attempts; wait five minutes'})
            if self.headers.get('Transfer-Encoding'):
                return self.respond(400, {'error': 'Unsupported request framing'})
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                return self.respond(400, {'error': 'Invalid login request'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                return self.respond(400, {'error': 'Invalid login content type'})
            data = parse_qs(self.rfile.read(length).decode('utf-8'))
            password = data.get('password', [''])[0]
            candidate = password_hash(password, config['password_salt'])
            if not hmac.compare_digest(candidate, config['password_hash']):
                with self.server.mutex:
                    self.server.failures.append(time.time())
                return self.respond(401, LOGIN.replace('__ERROR__', '<p class="error">Password not recognized.</p>'), 'text/html')
            token = secrets.token_urlsafe(32)
            with self.server.mutex:
                self.server.sessions[token] = (time.time() + 8 * 3600, config['password_hash'])
            secure = '; Secure' if urlsplit(config['public_origin']).scheme == 'https' else ''
            self.respond(303, '', 'text/plain', {'Location': '/', 'Set-Cookie': f'run_session={token}; Path=/; Max-Age=28800; HttpOnly; SameSite=Strict{secure}'})
        except (ValueError, UnicodeError):
            self.respond(400, {'error': 'Invalid request'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.respond(503, {'error': 'Dashboard login unavailable'})


def service_stopped(home):
    history = History(home)
    try:
        with exclusive(Path(home) / 'monitor.lock'):
            interrupted = history.stale()
            for rid in interrupted:
                try:
                    notify(history, rid, load_config(home), home)
                except Exception:
                    history.notification(rid, 'failed', 'Notification setup unavailable after interruption')
            for row in history.runs(1000):
                if row['notification_status'] == 'sending':
                    history.notification(row['id'], 'uncertain', 'Delivery was interrupted; Telegram may have accepted the message. No automatic resend was made.')
    except MonitorError:
        return  # A live run owns the lock; do not mark it interrupted.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=HOME)
    parser.add_argument('--ingestion-home', type=Path, default=INGESTION_HOME)
    commands = parser.add_subparsers(dest='command', required=True)
    for cmd in ('configure', 'configure-telegram', 'test-telegram', 'serve', 'status', 'service-stopped', 'check', 'set-password'):
        commands.add_parser(cmd)
    run = commands.add_parser('run')
    run.add_argument('--trigger', choices=('manual', 'service'), default='manual')
    retry = commands.add_parser('retry-notification')
    retry.add_argument('run_id')
    args = parser.parse_args()
    os.umask(0o077)
    home = args.home.expanduser().resolve()
    try:
        if args.command == 'configure':
            configure(home)
        elif args.command == 'check':
            load_config(home)
            mod = ingestion_module(args.ingestion_home / 'ingest_meetings.py')
            print('Dashboard configuration and ingestion ' + mod.VERSION + ' interface verified.')
        elif args.command == 'configure-telegram':
            configure_telegram(home)
        elif args.command == 'set-password':
            set_password(home)
        elif args.command == 'test-telegram':
            config = load_config(home)
            token = telegram.read_token(home / 'telegram-token.txt')
            telegram.api(token, 'sendMessage', {'chat_id': config['telegram_chat_id'],
                         'text': 'SMARTINI’s test notification: Telegram delivery is working.\nRun history: ' + config['public_origin'],
                         'disable_web_page_preview': True})
            print('Test message accepted by Telegram.', flush=True)
        elif args.command == 'run':
            if hasattr(signal, 'SIGTERM'):
                signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
            return run_ingestion(home, args.trigger, args.ingestion_home)
        elif args.command == 'service-stopped':
            service_stopped(home)
        elif args.command == 'retry-notification':
            history = History(home)
            with exclusive(home / 'monitor.lock'):
                notify(history, args.run_id, load_config(home), home, allow_retry=True)
            print(json.dumps(history.get(args.run_id), indent=2))
        elif args.command == 'status':
            print(json.dumps({'schedule': schedule_info(), 'runs': History(home).runs(20)}, indent=2))
        elif args.command == 'serve':
            config = load_config(home)
            # Recover abandoned running rows only when no wrapper currently owns the monitor lock.
            service_stopped(home)
            server = MonitorServer(('127.0.0.1', int(config.get('web_port', 8788))), home)
            print(f'Dashboard listening on loopback port {server.server_port}; private origin {config["public_origin"]}', flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
        return 0
    except KeyboardInterrupt:
        print('Cancelled.', flush=True)
        return 130
    except (MonitorError, telegram.NotificationError) as exc:
        print('ERROR: ' + str(exc), flush=True)
        return 1
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}; check local configuration. No credential details were logged.', flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())

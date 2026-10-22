from contextlib import contextmanager
import datetime as dt
from http.cookies import SimpleCookie
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

import run_monitor as m
import private_web as web


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def config(home, origin='https://server.example.ts.net:8443'):
    salt = 'a' * 32
    data = {'public_origin': origin, 'password_salt': salt,
            'password_hash': m.password_hash('test-password-123', salt),
            'telegram_chat_id': 123, 'web_port': 8788}
    m.atomic(Path(home) / 'monitor.json', data)
    (Path(home) / 'telegram-token.txt').write_text('123456:' + 'A' * 30, encoding='utf-8')
    (Path(home) / 'telegram-token.txt').chmod(0o600)
    return data


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.config = config(self.home)
        self.history = m.History(self.home)

    def completed(self, trigger='service'):
        rid = self.history.start(trigger)
        self.history.finish(rid, 'completed', 0, {'uploaded': 2, 'unchanged': 3}, elapsed=10)
        return rid

    def test_history_persist_counts_errors_and_order(self):
        first = self.completed()
        second = self.history.start('manual')
        self.history.finish(second, 'failed', 1, {'errors': [{'error': 'Failure'}]})
        fresh = m.History(self.home)
        self.assertEqual(fresh.runs()[0]['id'], second)
        self.assertEqual(fresh.get(first)['uploaded'], 2)
        self.assertEqual(fresh.get(second)['errors'], ['Failure'])
        self.assertEqual(fresh.count(), 2)

    def test_stale_run_not_falsely_completed(self):
        rid = self.history.start('service')
        with patch.object(m, 'notify'):
            m.service_stopped(self.home)
        self.assertEqual(self.history.get(rid)['status'], 'interrupted')

    def test_live_run_not_marked_stale(self):
        rid = self.history.start('service')
        with m.exclusive(self.home / 'monitor.lock'):
            m.service_stopped(self.home)
        self.assertEqual(self.history.get(rid)['status'], 'running')

    def test_sending_after_crash_is_uncertain(self):
        rid = self.completed()
        self.history.notification(rid, 'sending')
        m.service_stopped(self.home)
        self.assertEqual(self.history.get(rid)['notification_status'], 'uncertain')

    def test_weekday_notification_sent_once(self):
        rid = self.completed()
        with patch.object(m.telegram, 'eligible', return_value=True), patch.object(m.telegram, 'send_report', return_value=77) as send:
            m.notify(self.history, rid, self.config, self.home)
            m.notify(self.history, rid, self.config, self.home)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.history.get(rid)['notification_status'], 'sent')

    def test_weekend_and_manual_skip(self):
        rid = self.completed()
        with patch.object(m.telegram, 'eligible', return_value=False), patch.object(m.telegram, 'send_report') as send:
            m.notify(self.history, rid, self.config, self.home)
        self.assertEqual(self.history.get(rid)['notification_status'], 'skipped-weekend')
        send.assert_not_called()
        other = self.completed('manual')
        with patch.object(m.telegram, 'send_report') as send:
            m.notify(self.history, other, self.config, self.home)
        self.assertEqual(self.history.get(other)['notification_status'], 'skipped-manual')
        send.assert_not_called()

    def test_failed_telegram_does_not_change_ingestion_result(self):
        rid = self.completed()
        with patch.object(m.telegram, 'eligible', return_value=True), patch.object(m.telegram, 'send_report', side_effect=m.telegram.NotificationError('Connection failed')):
            m.notify(self.history, rid, self.config, self.home)
        run = self.history.get(rid)
        self.assertEqual(run['status'], 'completed')
        self.assertEqual(run['notification_status'], 'uncertain')
        with patch.object(m.telegram, 'send_report') as send:
            m.notify(self.history, rid, self.config, self.home)
        send.assert_not_called()

    def fake_module(self, report):
        @contextmanager
        def lock(_):
            yield
        return types.SimpleNamespace(locked=lock, load_config=lambda _: {'base_url': 'http://127.0.0.1', 'request_timeout_seconds': 1},
                                     State=lambda *_: object(), Client=lambda *_: object(), load_key=lambda _: 'fake-key',
                                     sync=lambda *a, **kw: report, save_json=lambda *a: None, emit=lambda _: None,
                                     IngestionError=RuntimeError)

    def test_wrapper_records_current_result_and_no_chat_calls(self):
        report = {'uploaded': 1, 'adopted': 0, 'unchanged': 2, 'skipped': 0, 'planned': 1, 'errors': [], 'deferred': False}
        with patch.object(m, 'ingestion_module', return_value=self.fake_module(report)), patch.object(m, 'notify'):
            code = m.run_ingestion(self.home)
        self.assertEqual(code, 0)
        self.assertEqual(self.history.runs()[0]['uploaded'], 1)
        self.assertEqual(self.history.runs()[0]['status'], 'completed')

    def test_wrapper_deferral_and_failure(self):
        for report, expected, code in (({'errors': [], 'deferred': True}, 'deferred', 75),
                                       ({'errors': [{'error': 'No access'}], 'deferred': False}, 'failed', 1)):
            with patch.object(m, 'ingestion_module', return_value=self.fake_module(report)), patch.object(m, 'notify'):
                self.assertEqual(m.run_ingestion(self.home), code)
            self.assertEqual(self.history.runs()[0]['status'], expected)

    def test_setup_failure_does_not_reuse_last_run_success(self):
        m.atomic(self.home / 'last-run.json', {'uploaded': 999, 'errors': []})
        with patch.object(m, 'ingestion_module', side_effect=RuntimeError('SECRET-CREDENTIAL-URL')), patch.object(m, 'notify'):
            self.assertEqual(m.run_ingestion(self.home), 1)
        run = self.history.runs()[0]
        self.assertEqual(run['status'], 'failed')
        self.assertIsNone(run['uploaded'])
        self.assertNotIn('SECRET', str(run))

    def test_wrapper_interrupted(self):
        fake = self.fake_module({})
        fake.sync = lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt())
        with patch.object(m, 'ingestion_module', return_value=fake), patch.object(m, 'notify'):
            self.assertEqual(m.run_ingestion(self.home), 130)
        self.assertEqual(self.history.runs()[0]['status'], 'interrupted')

    def test_tailnet_listener_collision_and_ownership(self):
        state = {'TCP': {'443': {'HTTPS': True}}, 'Web': {'host.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8080'}}}}}
        self.assertFalse(web.mentions_port(state))
        self.assertFalse(web.own_listener(state, 'host.ts.net'))
        state['TCP']['8443'] = {'HTTPS': True}
        state['Web']['host.ts.net:8443'] = {'Handlers': {'/': {'Proxy': web.TARGET}}}
        self.assertTrue(web.own_listener(state, 'host.ts.net'))
        state['AllowFunnel'] = {'host.ts.net:8443': True}
        self.assertFalse(web.own_listener(state, 'host.ts.net'))

    def test_schedule_parses_amsterdam_time(self):
        result = types.SimpleNamespace(returncode=0, stdout='ActiveState=active\nNextElapseUSecRealtime=Fri 2026-10-23 03:00:00 CEST\n')
        with patch.object(m.subprocess, 'run', return_value=result):
            schedule = m.schedule_info()
        self.assertTrue(schedule['enabled'])
        self.assertEqual(schedule['next_run'], '2026-10-23T03:00:00+02:00')


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.server = m.MonitorServer(('127.0.0.1', 0), self.home)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.config = config(self.home, self.origin)
        self.server.schedule_cache = (m.time.monotonic(), {'enabled': False, 'next_run': None, 'timezone': m.TIMEZONE})
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, data=None, cookie=None, origin=None, headers=None):
        hdr = dict(headers or {})
        if cookie:
            hdr['Cookie'] = cookie
        if origin:
            hdr['Origin'] = origin
        if data is not None:
            hdr['Content-Type'] = 'application/x-www-form-urlencoded'
            data = urlencode(data).encode()
        req = Request(self.origin + path, data=data, headers=hdr)
        try:
            response = self.opener.open(req)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, dict(response.headers), response.read().decode()

    def login(self):
        code, headers, _ = self.request('/login', {'password': 'test-password-123'}, origin=self.origin)
        self.assertEqual(code, 303)
        return headers['Set-Cookie'].split(';')[0]

    def test_unauthenticated_has_no_history(self):
        rid = self.server.history.start('manual')
        self.assertEqual(self.request('/')[0], 303)
        code, _, body = self.request('/api/runs')
        self.assertEqual(code, 401)
        self.assertNotIn(rid, body)
        self.assertEqual(self.request('/monitor.json')[0], 303)

    def test_login_cookie_and_api_does_not_leak_secrets(self):
        cookie = self.login()
        code, _, body = self.request('/api/runs', cookie=cookie)
        self.assertEqual(code, 200)
        self.assertNotIn(self.config['password_hash'], body)
        self.assertNotIn('A' * 30, body)
        self.assertNotIn('telegram_chat_id', body)
        code, headers, page = self.request('/', cookie=cookie)
        self.assertEqual(code, 200)
        self.assertIn('sha256-', headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertIn('Meeting ingestion', page)

    def test_csrf_host_and_wrong_password(self):
        self.assertEqual(self.request('/login', {'password': 'test-password-123'}, origin='https://evil.example')[0], 403)
        self.assertEqual(self.request('/health', headers={'Host': 'evil.example'})[0], 421)
        self.assertEqual(self.request('/login', {'password': 'wrong'}, origin=self.origin)[0], 401)

    def test_logout_and_password_rotation_invalidate_session(self):
        cookie = self.login()
        self.assertEqual(self.request('/logout', {}, cookie=cookie, origin=self.origin)[0], 200)
        self.assertEqual(self.request('/api/runs', cookie=cookie)[0], 401)
        cookie = self.login()
        self.config['password_hash'] = m.password_hash('a-different-password', self.config['password_salt'])
        m.atomic(self.home / 'monitor.json', self.config)
        self.assertEqual(self.request('/api/runs', cookie=cookie)[0], 401)

    def test_rate_limit(self):
        self.server.failures = [m.time.time()] * 10
        self.assertEqual(self.request('/login', {'password': 'wrong'}, origin=self.origin)[0], 429)

    def test_secure_cookie_for_tailnet_origin(self):
        self.config['public_origin'] = 'https://server.example.ts.net:8443'
        m.atomic(self.home / 'monitor.json', self.config)
        code, headers, _ = self.request('/login', {'password': 'test-password-123'}, origin=self.config['public_origin'])
        self.assertEqual(code, 303)
        self.assertIn('; Secure', headers['Set-Cookie'])
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])


if __name__ == '__main__':
    unittest.main()

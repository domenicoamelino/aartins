import copy
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import ingest_meetings as m


class FakeClient:
    def __init__(self):
        self.storage = {}
        self.members = set()
        self.uploads = 0
        self.writes = []
        self.fail_wait = False
        self.fail_add = False
        self.fail_remove = False
        self.fail_upload_response = False

    def version(self):
        pass

    def request(self, method, path, obj=None):
        if path == '/api/v1/knowledge/kb':
            return {'id': 'kb', 'name': 'Meeting Archive', 'write_access': True}
        if path == '/api/v1/files/?content=false':
            return [{'id': k, 'filename': v['filename']} for k, v in self.storage.items()]
        if path.startswith('/api/v1/files/'):
            key = path.rsplit('/', 1)[1]
            if key not in self.storage:
                raise m.APIError(404, path)
            return {'id': key}
        raise AssertionError((method, path, obj))

    def files(self, kb):
        return [{'id': k, 'filename': self.storage[k]['filename']} for k in self.members]

    def raw_file(self, fid):
        return self.storage[fid]['raw']

    def stored_files(self, filename):
        return [{'id': k, 'filename': v['filename']} for k, v in self.storage.items() if v['filename'] == filename]

    def upload(self, doc):
        self.uploads += 1
        fid = 'file' + str(self.uploads)
        self.storage[fid] = {'filename': doc['filename'], 'raw': doc['raw']}
        self.writes.append(('upload', fid))
        if self.fail_upload_response:
            raise m.IngestionError('Lost upload response')
        return fid

    def wait(self, *args):
        if self.fail_wait:
            raise m.IngestionError('Processing timeout')

    def add(self, kb, fid):
        self.writes.append(('add', fid))
        if self.fail_add:
            raise m.IngestionError('Attach failed')
        self.members.add(fid)

    def remove(self, kb, fid):
        self.writes.append(('remove', fid))
        if self.fail_remove:
            raise m.IngestionError('Detach failed')
        self.members.discard(fid)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / 'meetings'
        self.root.mkdir()
        self.folder = self.root / ('processed-2026-10-22_test_' + 'a' * 32)
        self.folder.mkdir()
        m.save_json(self.folder / 'job.json', {'state': 'completed'})
        m.save_json(self.folder / 'meeting_metadata.json', {'meeting_title': 'Café plan', 'meeting_date': '2026-10-22'})
        self.content = '# Knowledge\nMeeting ID: ' + self.folder.name + '\nAction: Review plan.\n'
        (self.folder / 'knowledge.md').write_text(self.content, encoding='utf-8')
        self.config = {'base_url': 'http://127.0.0.1:8080', 'collection_id': 'kb', 'meetings_root': str(self.root.resolve())}
        self.client = FakeClient()
        self.state = m.State(self.home / 'state.json', self.config)
        self.prints = patch.object(m, 'emit')
        self.prints.start()
        self.addCleanup(self.prints.stop)

    def run_sync(self, apply=True, **kwargs):
        return m.sync(self.client, self.config, self.state, apply=apply, busy=lambda _: False, **kwargs)

    def modify(self):
        (self.folder / 'knowledge.md').write_text(self.content + 'Deadline: tomorrow.\n', encoding='utf-8')

    def test_dry_run_has_no_remote_or_state_writes(self):
        before = copy.deepcopy(self.state.data)
        result = self.run_sync(False)
        self.assertEqual(result['planned'], 1)
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.state.data, before)
        self.assertFalse(self.state.path.exists())

    def test_initial_sync_then_unchanged_skips_embedding(self):
        self.run_sync()
        result = self.run_sync()
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(result['unchanged'], 1)
        self.assertEqual(self.client.members, {'file1'})

    def test_adopt_exact_manual_upload_without_uploading(self):
        self.client.storage['manual'] = {'filename': 'knowledge.md', 'raw': self.content.replace('\n', '\r\n').encode()}
        self.client.members.add('manual')
        result = self.run_sync()
        self.assertEqual(result['adopted'], 1)
        self.assertEqual(self.client.uploads, 0)
        self.assertEqual(self.state.data['meetings'][self.folder.name]['committed']['file_id'], 'manual')

    def test_two_existing_exact_copies_are_not_deleted(self):
        for fid in ('manual1', 'manual2'):
            self.client.storage[fid] = {'filename': 'knowledge.md', 'raw': self.content.encode()}
            self.client.members.add(fid)
        self.assertTrue(self.run_sync()['errors'])
        self.assertEqual(len(self.client.members), 2)
        self.assertEqual(self.client.writes, [])

    def test_replace_attaches_new_before_detaching_old_and_retains_upload(self):
        self.run_sync()
        self.modify()
        self.run_sync()
        self.assertEqual(self.client.members, {'file2'})
        self.assertIn('file1', self.client.storage)
        self.assertLess(self.client.writes.index(('add', 'file2')), self.client.writes.index(('remove', 'file1')))
        self.assertEqual(len(self.state.data['meetings'][self.folder.name]['history']), 1)

    def test_timeout_resumes_same_upload(self):
        self.client.fail_wait = True
        self.assertTrue(self.run_sync()['errors'])
        self.client.fail_wait = False
        self.run_sync()
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(self.client.members, {'file1'})

    def test_lost_upload_response_recovers_by_name_and_content(self):
        self.client.fail_upload_response = True
        self.assertTrue(self.run_sync()['errors'])
        self.client.fail_upload_response = False
        self.run_sync()
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(self.client.members, {'file1'})

    def test_attach_failure_preserves_old_index(self):
        self.run_sync()
        self.modify()
        self.client.fail_add = True
        self.assertTrue(self.run_sync()['errors'])
        self.assertEqual(self.client.members, {'file1'})
        self.client.fail_add = False
        self.run_sync()
        self.assertEqual(self.client.members, {'file2'})
        self.assertEqual(self.client.uploads, 2)

    def test_lost_attach_response_verified_by_membership(self):
        original = self.client.add
        def lost_response(kb, fid):
            original(kb, fid)
            raise m.IngestionError('Response lost after successful attach')
        self.client.add = lost_response
        self.assertFalse(self.run_sync()['errors'])
        self.assertEqual(self.client.members, {'file1'})

    def test_detach_failure_recovers_without_another_upload(self):
        self.run_sync()
        self.modify()
        self.client.fail_remove = True
        self.assertTrue(self.run_sync()['errors'])
        self.assertEqual(self.client.members, {'file1', 'file2'})
        self.client.fail_remove = False
        self.run_sync()
        self.assertEqual(self.client.members, {'file2'})
        self.assertEqual(self.client.uploads, 2)

    def test_changed_source_during_pending_is_blocked(self):
        self.client.fail_wait = True
        self.run_sync()
        self.modify()
        self.client.fail_wait = False
        self.assertTrue(self.run_sync()['errors'])
        self.assertEqual(self.client.uploads, 1)

    def test_remote_removal_reuses_stored_upload(self):
        self.run_sync()
        self.client.members.clear()
        self.run_sync()
        self.assertEqual(self.client.uploads, 1)
        self.assertEqual(self.client.members, {'file1'})

    def test_external_deletion_of_pending_file_can_retry(self):
        self.client.fail_wait = True
        self.run_sync()
        self.client.storage.clear()
        self.client.fail_wait = False
        self.run_sync()
        self.assertEqual(self.client.uploads, 2)
        self.assertEqual(self.client.members, {'file2'})

    def test_busy_worker_defers_without_writes(self):
        result = m.sync(self.client, self.config, self.state, apply=True, busy=lambda _: True)
        self.assertTrue(result['deferred'])
        self.assertEqual(self.client.writes, [])

    def test_unfinished_meeting_skipped(self):
        m.save_json(self.folder / 'job.json', {'state': 'analyzing'})
        self.assertEqual(self.run_sync()['skipped'], 1)
        self.assertEqual(self.client.uploads, 0)

    def test_legacy_requires_opt_in_and_date_not_guessed(self):
        (self.folder / 'job.json').unlink()
        (self.folder / 'meeting_metadata.json').unlink()
        self.assertIsNone(m.document(self.folder, self.root))
        doc = m.document(self.folder, self.root, True)
        self.assertTrue(doc['filename'].startswith('date-unknown__'))

    def test_distinct_meetings_with_same_title_and_date_have_distinct_names(self):
        other = self.root / 'processed-2026-10-22_other'
        other.mkdir()
        for name in ('job.json', 'meeting_metadata.json', 'knowledge.md'):
            (other / name).write_bytes((self.folder / name).read_bytes())
        self.assertNotEqual(m.document(other, self.root)['filename'], m.document(self.folder, self.root)['filename'])

    def test_source_files_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        self.run_sync()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.folder.iterdir()})

    def test_state_destination_mismatch_refused(self):
        self.run_sync()
        with self.assertRaises(m.IngestionError):
            m.State(self.state.path, {**self.config, 'collection_id': 'different'})

    def test_rollback_restore_old_version(self):
        self.run_sync()
        self.modify()
        self.run_sync()
        with patch.object(m, 'worker_busy', return_value=False):
            m.rollback(self.client, self.config, self.state, self.folder.name, True)
        self.assertEqual(self.client.members, {'file1'})
        self.assertIn('file2', self.client.storage)

    def test_rollback_adopted_initial_preserves_manual_upload(self):
        self.client.storage['manual'] = {'filename': 'knowledge.md', 'raw': self.content.encode()}
        self.client.members.add('manual')
        self.run_sync()
        with patch.object(m, 'worker_busy', return_value=False):
            m.rollback(self.client, self.config, self.state, self.folder.name, True)
        self.assertEqual(self.client.members, {'manual'})
        self.assertNotIn(self.folder.name, self.state.data['meetings'])

    def test_rollback_dry_run_does_not_write(self):
        self.run_sync()
        before = copy.deepcopy(self.state.data)
        writes = list(self.client.writes)
        m.rollback(self.client, self.config, self.state, self.folder.name)
        self.assertEqual(self.state.data, before)
        self.assertEqual(self.client.writes, writes)

    def test_database_busy_check(self):
        import sqlite3
        with closing(sqlite3.connect(self.root / 'jobs.sqlite3')) as db:
            with db:
                db.execute('CREATE TABLE jobs (state TEXT, created REAL)')
                db.execute("INSERT INTO jobs VALUES ('analyzing', 0)")
        self.assertTrue(m.worker_busy(self.root))

    def test_lock_conflict(self):
        with m.locked(self.home / 'test.lock'):
            with self.assertRaises(m.IngestionError):
                with m.locked(self.home / 'test.lock'):
                    pass


class HTTPTests(unittest.TestCase):
    def test_full_sync_over_http_then_no_duplicate_upload(self):
        from email import policy
        from email.parser import BytesParser
        from urllib.parse import urlsplit
        files, members, uploads = {}, set(), []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, obj, raw=False):
                if self.headers.get('Authorization') != 'Bearer local-test-key':
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(obj if raw else json.dumps(obj).encode())

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == '/api/version':
                    self.reply({'version': '0.12.3'})
                elif path == '/api/v1/knowledge/kb':
                    self.reply({'id': 'kb', 'name': 'Archive', 'write_access': True})
                elif path == '/api/v1/knowledge/kb/files':
                    rows = [{'id': fid, 'filename': files[fid]['filename']} for fid in members]
                    self.reply({'items': rows, 'total': len(rows)})
                elif path == '/api/v1/files/search':
                    self.reply([{'id': fid, 'filename': item['filename']} for fid, item in files.items()])
                elif path.endswith('/process/status'):
                    self.reply({'status': 'completed'})
                elif path.endswith('/content'):
                    self.reply(files[path.split('/')[4]]['raw'], True)
                else:
                    raise AssertionError(path)

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                path = urlsplit(self.path).path
                if path == '/api/v1/files/':
                    mime = b'MIME-Version: 1.0\r\nContent-Type: ' + self.headers['Content-Type'].encode() + b'\r\n\r\n' + body
                    part = next(BytesParser(policy=policy.default).parsebytes(mime).iter_parts())
                    fid = 'u' + str(len(files) + 1)
                    files[fid] = {'filename': part.get_filename(), 'raw': part.get_payload(decode=True)}
                    uploads.append(fid)
                    self.reply({'id': fid})
                elif path == '/api/v1/knowledge/kb/file/add':
                    members.add(json.loads(body)['file_id'])
                    self.reply({'id': 'kb'})
                else:
                    raise AssertionError(path)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'meetings'
                folder = root / 'processed-test'
                folder.mkdir(parents=True)
                m.save_json(folder / 'job.json', {'state': 'completed'})
                (folder / 'knowledge.md').write_text('# Meeting\nTopic: test\n', encoding='utf-8')
                base = f'http://127.0.0.1:{server.server_port}'
                config = {'base_url': base, 'collection_id': 'kb', 'meetings_root': str(root)}
                client = m.Client(base, 'local-test-key')
                state = m.State(Path(tmp) / 'state.json', config)
                with patch.object(m, 'emit'):
                    result = m.sync(client, config, state, True, busy=lambda _: False)
                    again = m.sync(client, config, state, True, busy=lambda _: False)
                self.assertFalse(result['errors'])
                self.assertEqual(again['unchanged'], 1)
                self.assertEqual(len(uploads), 1)
                self.assertEqual(members, {'u1'})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_multipart_poll_pagination_and_auth(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                received.append(('GET', self.path, self.headers.get('Authorization')))
                if self.path.startswith('/api/v1/knowledge/?page='):
                    page = int(self.path.split('page=')[1])
                    out = {'items': [{'id': str(page)}], 'total': 2}
                elif self.path.endswith('/process/status'):
                    out = {'status': 'completed'}
                elif self.path == '/api/version':
                    out = {'version': '0.12.3'}
                elif self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/must-not-follow')
                    self.end_headers()
                    return
                else:
                    out = {}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(out).encode())

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                received.append(('POST', self.path, self.headers.get('Authorization'), self.headers.get('Content-Type'), body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"id":"uploaded"}')

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = m.Client(f'http://127.0.0.1:{server.server_port}', 'test-secret')
            client.version()
            self.assertEqual(len(client.collections()), 2)
            fid = client.upload({'filename': 'test.md', 'raw': 'Café\n'.encode()})
            self.assertEqual(fid, 'uploaded')
            client.wait(fid, 1)
            upload = next(row for row in received if row[0] == 'POST')
            self.assertEqual(upload[1], '/api/v1/files/?process=true&process_in_background=true')
            self.assertEqual(upload[2], 'Bearer test-secret')
            self.assertIn('multipart/form-data', upload[3])
            self.assertIn(b'filename="test.md"', upload[4])
            self.assertIn('Café\n'.encode(), upload[4])
            client.add('kb', fid)
            client.remove('kb', fid)
            self.assertTrue(any('delete_file=false' in row[1] for row in received))
            with self.assertRaises(m.APIError):
                client.request('GET', '/redirect')
            self.assertFalse(any(row[1] == '/must-not-follow' for row in received))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_unencrypted_nonlocal_url_refused(self):
        for url in ('http://example.com', 'https://user:secret@example.com', 'https://example.com/api'):
            with self.assertRaises(m.IngestionError):
                m.Client(url, 'secret')


if __name__ == '__main__':
    unittest.main()

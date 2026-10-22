"""Metadata-aware CLI and recovery boundaries; no real services or model calls."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote

import recover_meeting_job as recovery
import submit_meeting as cli


class ClientTests(unittest.TestCase):
    def test_cli_encodes_metadata_and_streams_original_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'sample.m4a'
            audio.write_bytes(b'synthetic-audio')
            calls = []

            class Connection:
                def __init__(self, *args, **kwargs):
                    pass

                def request(self, method, path, body=None, headers=None):
                    calls.append((path, body.read() if hasattr(body, 'read') else body, headers))

                def getresponse(self):
                    class Response:
                        status = 200

                        def read(self):
                            return json.dumps({'id': 'a' * 32, 'upload_token': 'test-token',
                                               'state': 'queued'}).encode()
                    return Response()

                def close(self):
                    pass

            with patch.object(cli.http.client, 'HTTPConnection', Connection), \
                 patch.dict(cli.os.environ, {'MEETING_API_KEY': 'x' * 40}), \
                 patch('sys.argv', ['submit', str(audio), '--title', 'Café planning',
                                    '--meeting-date', '2026-10-22', '--participant', 'Alex']), \
                 contextlib.redirect_stdout(io.StringIO()):
                cli.main()
            self.assertEqual(calls[1][1], b'synthetic-audio')
            metadata = json.loads(unquote(calls[1][2]['X-Meeting-Metadata']))
            self.assertEqual(metadata, {'meeting_title': 'Café planning',
                                       'meeting_date': '2026-10-22', 'participants': ['Alex']})

    def test_cli_rejects_missing_metadata_before_any_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'sample.m4a'
            audio.write_bytes(b'test')
            with patch.object(cli.http.client, 'HTTPConnection') as connection, \
                 patch.dict(cli.os.environ, {'MEETING_API_KEY': 'x' * 40}), \
                 patch('sys.argv', ['submit', str(audio)]), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cli.main()
                connection.assert_not_called()


class RecoveryTests(unittest.TestCase):
    def recover(self, export_error=None):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            archive = folder / 'analysis' / 'attempt'
            archive.mkdir(parents=True)
            (archive / 'manifest.json').write_text(json.dumps({
                'model': 'test', 'language': 'English', 'context': 4096,
                'output_tokens': 500}), encoding='utf-8')
            for name in ('report.md', 'transcript.md', 'source.json', 'findings.json'):
                (archive / name).write_text('synthetic', encoding='utf-8')
            job = {'id': 'a' * 32, 'state': 'failed', 'folder': str(folder)}
            events = []

            def export(path):
                self.assertEqual(path, folder)
                self.assertTrue((path / 'findings.json').is_file())
                events.append('export')
                if export_error:
                    raise export_error

            with patch.object(recovery.w, 'get_job', return_value=job), \
                 patch.object(recovery.w.report, 'run', return_value=archive), \
                 patch.object(recovery.w.knowledge, 'export', side_effect=export), \
                 patch.object(recovery.w, 'update', side_effect=lambda *a, **k: events.append(k['state'])), \
                 patch('sys.argv', ['recover', job['id']]), \
                 contextlib.redirect_stdout(io.StringIO()):
                if export_error:
                    with self.assertRaises(ValueError):
                        recovery.main()
                else:
                    recovery.main()
            return events

    def test_recovery_exports_before_completion(self):
        self.assertEqual(self.recover(), ['export', 'completed'])

    def test_export_failure_leaves_recovered_job_failed(self):
        self.assertEqual(self.recover(ValueError('bad evidence')), ['export'])

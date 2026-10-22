import json
from pathlib import Path
import tempfile
import unittest

import meeting_knowledge as k
from test_worker import Tests


class MetadataHTTP(Tests):
    def test_missing_invalid_metadata_does_not_consume_session(self):
        s = self.session()
        path = '/meeting-ui/upload/' + s['upload_token']
        headers = {'X-Filename': 'test.m4a'}
        for value in (None, '%7Bbad', '%5B%5D', '%7B%7D', 'x' * 6001):
            if value is not None:
                headers['X-Meeting-Metadata'] = value
            code, _ = self.request(path, b'audio', headers)
            self.assertEqual(code, 400)
            import meeting_worker as w
            self.assertEqual(w.get_job(s['id'])['state'], 'waiting_upload')
        self.assertEqual(self.upload(s)[0], 202)

    def test_invalid_capability_and_preflight(self):
        self.assertEqual(self.request('/meeting-ui/upload/unknown', b'audio')[0], 404)
        import urllib.request
        req = urllib.request.Request(self.base + '/meeting-ui/upload/token', method='OPTIONS')
        with urllib.request.urlopen(req) as response:
            self.assertIn('X-Meeting-Metadata', response.headers['Access-Control-Allow-Headers'])


class KnowledgeTests(unittest.TestCase):
    def test_metadata_validation(self):
        valid = {'meeting_title': '  Café planning  ', 'meeting_date': '2024-02-29', 'participants': [' A ', 'A']}
        self.assertEqual(k.validate_metadata(valid)['participants'], ['A'])
        for patch in ({'meeting_title': ''}, {'meeting_title': 'x\ny'}, {'meeting_date': '2026-02-29'},
                      {'meeting_date': '20261022'}, {'participants': 'Alice'}, {'participants': ['']},
                      {'participants': ['x'] * 21}, {'meeting_title': 'x' * 151}):
            with self.assertRaises(ValueError):
                k.validate_metadata({**valid, **patch})

    def test_deterministic_links_warnings_and_escaping(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'transcript.md').write_text('<a id="S000001"></a>\n**S000001 [00:00–00:01]** We may try tomorrow.\n', encoding='utf-8')
            findings = [{'kind': 'proposed', 'topic': '<script>alert(1)</script>', 'text': 'May try',
                         'owner': None, 'deadline': 'tomorrow', 'interpretation': 'Tentative',
                         'verification_warnings': ['Uncertain'],
                         'evidence': [{'id': 'S000001', 'quote': 'We may try tomorrow.'},
                                      {'id': 'S000099', 'quote': 'Missing'},
                                      {'id': 'S000001', 'quote': 'Invented'}]}]
            raw = json.dumps(findings)
            (folder / 'findings.json').write_text(raw)
            rendered = k.render(folder)
            self.assertEqual(rendered, k.render(folder))
            self.assertIn('(transcript.md#S000001)', rendered)
            self.assertNotIn('(transcript.md#S000099)', rendered)
            self.assertIn('Quote does not match', rendered)
            self.assertIn('Metadata unavailable', rendered)
            self.assertIn('deadline: tomorrow', rendered)
            self.assertNotIn('<script>', rendered)
            k.export(folder)
            self.assertEqual((folder / 'findings.json').read_text(), raw)
            self.assertTrue((folder / 'knowledge.md').is_file())


def load_tests(loader, tests, pattern):
    # Reuse the HTTP fixture without re-running its inherited regression cases.
    suite = unittest.TestSuite([loader.loadTestsFromTestCase(KnowledgeTests)])
    for name in ('test_missing_invalid_metadata_does_not_consume_session',
                 'test_invalid_capability_and_preflight'):
        suite.addTest(MetadataHTTP(name))
    return suite


if __name__ == '__main__':
    unittest.main()

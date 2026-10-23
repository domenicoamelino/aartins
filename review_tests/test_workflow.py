"""Offline integration checks; never touches the production archive or APIs."""
import http.client
import itertools
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.parse import quote

import os
import sys
import copy
import os
import time
import contextlib
import runpy

# Locate one complete application tree, independent of the current directory.
# Works inside ~/ai-platform/ingestion and inside the extracted update package.
_override = os.environ.get('MEETING_TEST_PLATFORM_ROOT')
_candidates = ([Path(_override).expanduser()] if _override else
               [candidate for parent in Path(__file__).resolve().parents
                for candidate in (parent, parent / 'ai-platform')])
PLATFORM = next((candidate.resolve() for candidate in _candidates
                 if all((candidate / relative).is_file() for relative in (
                     'transcription/meeting-worker-2.3/meeting_worker.py',
                     'transcription/meeting-worker-2.3/meeting_knowledge.py',
                     'transcription/meeting-worker-2.3/meeting_report.py',
                     'ingestion/ingest_meetings.py'))), None)
if PLATFORM is None and (Path(__file__).resolve().parents[1]/'meeting_worker.py').is_file():
    PLATFORM = Path(__file__).resolve().parents[1]
if PLATFORM is None:
    raise SystemExit(
        'Cannot find the ai-platform modules. Keep this test in ai-platform/ingestion, '
        'with worker files in ai-platform/transcription/meeting-worker-2.3, '
        'or set MEETING_TEST_PLATFORM_ROOT to the ai-platform directory.')
sys.path[:0] = [str(PLATFORM), str(PLATFORM / 'transcription/meeting-worker-2.3'),
                str(PLATFORM / 'ingestion')]
print('Testing modules from:', PLATFORM, flush=True)

import meeting_worker as worker
import meeting_speakers as speakers
import meeting_review as review
import meeting_knowledge as knowledge
import meeting_report as report
import ingest_meetings as ingestion

BASE = {'meeting_title': 'Language test', 'meeting_date': '2026-10-23', 'participants': ['Ada']}

RESULT = {'schema': 'meeting-diarization/2.5.2', 'status': 'completed', 'model': 'test-model',
          'turns': [{'start': 0, 'end': 2, 'speaker': 'SPEAKER_00'}],
          'exclusive_turns': [{'start': 0, 'end': 2, 'speaker': 'SPEAKER_00'}]}


class SpeakerTests(unittest.TestCase):
    def test_production_runner_contract(self):
        calls = []
        class Wave:
            shape = (1, 32000)
            def mean(self, **kw): return self
        class Pipeline:
            @classmethod
            def from_pretrained(cls, model, token):
                self.assertEqual(token, False)
                self.assertEqual(os.environ['HF_HUB_OFFLINE'], '1')
                return cls()
            def to(self, device):
                self_device = device
                if self_device != 'cpu': raise AssertionError('Expected CPU')
            def __call__(self, audio, **kw):
                calls.append(kw)
                turn = types.SimpleNamespace(start=0, end=2)
                return types.SimpleNamespace(speaker_diarization=[(turn, 'SPEAKER_00')],
                                             exclusive_speaker_diarization=[(turn, 'SPEAKER_00')])
        torch = types.SimpleNamespace(set_num_threads=lambda _: None, set_num_interop_threads=lambda _: None,
                                      manual_seed=lambda _: None, device=lambda x: x, inference_mode=contextlib.nullcontext)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'result.json'
            helper = PLATFORM/'diarization-benchmark/diarize_meeting.py'
            modules = {'torch': torch, 'torchaudio': types.SimpleNamespace(load=lambda _: (Wave(), 16000)),
                       'pyannote': types.ModuleType('pyannote'), 'pyannote.audio': types.SimpleNamespace(Pipeline=Pipeline),
                       'resource': types.SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _: types.SimpleNamespace(ru_maxrss=1024))}
            old_umask = os.umask(0o077)
            try:
                with patch.dict('sys.modules', modules), patch.dict(os.environ, {}), \
                     patch('sys.argv', [str(helper), '--audio', 'fake.wav', '--output', str(output), '--speakers', '2']), \
                     patch('importlib.metadata.version', return_value='test'):
                    runpy.run_path(str(helper), run_name='__main__')
            finally:
                os.umask(old_umask)
            result = speakers.validate_result(json.loads(output.read_text(encoding='utf-8')), 2)
            self.assertEqual(result['requested_speaker_count'], 2)
            self.assertEqual(calls, [{'num_speakers': 2}])

    def test_metadata_and_alignment(self):
        self.assertEqual(speakers.options({}), {'diarization_enabled': False, 'speaker_count': None})
        for count in (None, 1, 2, 20):
            self.assertEqual(speakers.options({'diarization_enabled': True, 'speaker_count': count})['speaker_count'], count)
        for value in ('yes', 1, None):
            with self.assertRaises(ValueError):
                knowledge.validate_metadata(dict(BASE, diarization_enabled=value))
        for value in (True, 0, 21, 2.5, '2'):
            with self.assertRaises(ValueError):
                knowledge.validate_metadata(dict(BASE, diarization_enabled=True, speaker_count=value))
        with self.assertRaises(ValueError):
            speakers.options({'speaker_count': 2})
        segment = {'start': 0, 'end': 2, 'text': 'Original text.'}
        for turns, expected in (
            (RESULT['turns'], 'assigned'),
            ([], 'uncertain'),
            ([{'start': 0, 'end': 1, 'speaker': 'SPEAKER_00'}, {'start': 1, 'end': 2, 'speaker': 'SPEAKER_01'}], 'mixed'),
            ([{'start': 0, 'end': 2, 'speaker': 'SPEAKER_00'}, {'start': 0.5, 'end': 1, 'speaker': 'SPEAKER_01'}], 'overlap'),
        ):
            aligned = speakers.align([segment], turns)[0]
            self.assertEqual(aligned['speaker_status'], expected)
            self.assertEqual({k: aligned[k] for k in segment}, segment)
            self.assertEqual(set(segment), {'start', 'end', 'text'})
            if expected != 'assigned':
                self.assertIsNone(aligned['speaker'])
        self.assertEqual(speakers.align([dict(segment, end=0)], [])[0]['speaker_status'], 'uncertain')

    def test_results_validation(self):
        speakers.validate_result(copy.deepcopy(RESULT), 2)
        for key, value in (('start', -1), ('end', 4), ('end', float('nan')), ('speaker', 'Ada')):
            data = copy.deepcopy(RESULT)
            data['turns'][0][key] = value
            with self.assertRaises(ValueError):
                speakers.validate_result(data, 2)

    def test_child_success_timeout_and_shutdown(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            runner = folder / 'fake.py'
            runner.write_text('''import argparse,json,os,time
p=argparse.ArgumentParser()
p.add_argument('--audio'); p.add_argument('--output'); p.add_argument('--threads'); p.add_argument('--speakers')
a=p.parse_args()
assert 'MEETING_API_KEY' not in os.environ
assert os.environ['HF_HUB_OFFLINE']=='1'
assert a.speakers=='2'
''' + 'json.dump(' + repr(RESULT) + ",open(a.output,'w'))\n", encoding='utf-8')
            env = {'DIARIZATION_PYTHON': sys.executable, 'DIARIZATION_SCRIPT': str(runner),
                   'MEETING_API_KEY': 'test-secret', 'DIARIZATION_TIMEOUT_SECONDS': '5'}
            with patch.dict(os.environ, env):
                data = speakers.run(folder/'audio.wav', folder, {'diarization_enabled': True, 'speaker_count': 2}, 2, threading.Event(), lambda _: None)
                self.assertEqual(data['turns'], RESULT['turns'])
                runner.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
                with patch.dict(os.environ, {'DIARIZATION_TIMEOUT_SECONDS': '1'}), self.assertRaises(TimeoutError):
                    speakers.run(folder/'audio.wav', folder, {'diarization_enabled': True}, 2, threading.Event(), lambda _: None)
                stop = threading.Event()
                stop.set()
                with self.assertRaises(speakers.Interrupted):
                    speakers.run(folder/'audio.wav', folder, {'diarization_enabled': True}, 2, stop, lambda _: None)
            self.assertEqual(list(folder.glob('diarization-pending-*')), [])

    def test_worker_report_knowledge_and_fallback(self):
        class Model:
            def __init__(self, *a, **kw): pass
            def transcribe(self, *a, **kw):
                return iter([types.SimpleNamespace(start=0, end=2, text='Let us meet tomorrow.')]), types.SimpleNamespace(duration=2, language='en')
        class Ollama:
            def __init__(self, args, archive):
                self.args = args
                self.archive, self.cache, self.counter = archive, {}, 0
                self.think, self.validation_failures = False, 0
            def discover(self): pass
            def generate(self, prompt, label, system, schema=None, request_meta=None):
                self.counter += 1
                if label == 'Meaning verification':
                    return {'supported': True}
                if label == 'Report writing':
                    item = request_meta['items'][0]
                    voice = next((e.get('speaker') for e in item.get('speaker_context', []) if e.get('speaker')), None)
                    text = ('The estimated voice ' + voice + ' proposed a meeting.') if voice else 'A meeting was proposed.'
                    return {'paragraphs': [{'section': 'discussion', 'text': text, 'facts': [item['ref']]}]}
                return {'facts': [{'kind': 'proposed', 'topic': 'Meeting', 'text': 'A meeting was proposed.',
                                   'evidence': [1], 'owner': None, 'deadline': None, 'interpretation': None}]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'DB', root/'jobs.sqlite3'), \
                 patch.dict('sys.modules', {'faster_whisper': types.SimpleNamespace(WhisperModel=Model)}), \
                 patch.object(report, 'Ollama', Ollama):
                worker.init()
                for mode in ('success', 'failed', 'timeout', 'empty', 'off', 'legacy', 'interrupted'):
                    session = worker.create_session('test-speakers', mode)
                    folder = root / ('processed-test_' + session['id'])
                    folder.mkdir()
                    (folder/'audio.wav').write_bytes(b'fixture')
                    metadata = dict(BASE, expected_languages=['en'], diarization_enabled=True, speaker_count=None)
                    if mode == 'off': metadata['diarization_enabled'] = False
                    if mode == 'legacy':
                        metadata.pop('diarization_enabled')
                        metadata.pop('speaker_count')
                    report.save(folder/'meeting_metadata.json', metadata)
                    worker.update(session['id'], state='queued', filename='test.wav', folder=str(folder))
                    effect = {'failed': RuntimeError('fixture'), 'timeout': TimeoutError('fixture'),
                              'interrupted': speakers.Interrupted('fixture')}.get(mode)
                    result = copy.deepcopy(RESULT)
                    if mode == 'empty': result.update(turns=[], exclusive_turns=[])
                    with patch.object(speakers, 'run', side_effect=effect, return_value=result) as run:
                        worker.process(worker.get_job(session['id']))
                    if mode == 'interrupted':
                        self.assertEqual(worker.get_job(session['id'])['state'], 'queued')
                        self.assertFalse((folder/'report.md').exists())
                        continue
                    self.assertEqual(worker.get_job(session['id'])['state'], 'completed')
                    transcript = json.loads((folder/'transcript.json').read_text(encoding='utf-8'))
                    knowledge_md = (folder/'knowledge.md').read_text(encoding='utf-8')
                    recap = (folder/'report.md').read_text(encoding='utf-8')
                    if mode == 'success':
                        self.assertEqual(transcript['segments'][0]['speaker'], 'SPEAKER_00')
                        self.assertIn('SPEAKER_00', recap.replace('\\_', '_'))
                        self.assertIn('SPEAKER_00', knowledge_md.replace('\\_', '_'))
                        self.assertIn('SPEAKER_00', (folder/'transcript.md').read_text(encoding='utf-8'))
                        raw = json.loads((folder/'transcript.raw.json').read_text(encoding='utf-8'))
                        self.assertNotIn('speaker', raw['segments'][0])
                    elif mode in ('failed', 'timeout', 'empty'):
                        self.assertEqual(transcript['diarization']['status'], 'failed')
                        self.assertIn('unavailable', recap)
                        self.assertIn('original transcript', knowledge_md)
                        self.assertIn('unavailable', worker.get_job(session['id'])['detail'])
                        self.assertNotIn('speaker', transcript['segments'][0])
                    else:
                        run.assert_not_called()
                        self.assertFalse((folder/'diarization.json').exists())
                    self.assertIsNone(ingestion.document(folder, root))
                    current = review.view(root, session['id'], 'test-speakers')
                    review.act(root, session['id'], 'test-speakers', {'action':'approve','revision':current['revision']})
                    self.assertIsNotNone(ingestion.document(folder, root))

    def test_unsupported_narrative_speaker_rejected(self):
        with self.assertRaises(report.ReportError):
            report.check_narrative({'paragraphs': [{'section': 'discussion', 'text': 'SPEAKER_99 agreed.', 'facts': [1]}]},
                                   {1}, {1: {'kind': 'topic', 'speaker_context': [{'speaker': 'SPEAKER_00'}]}})


class Tests(unittest.TestCase):
    def test_validation(self):
        for count in (1, 2, 3):
            for codes in itertools.combinations(('en', 'nl', 'it'), count):
                metadata = knowledge.validate_metadata(dict(BASE, expected_languages=list(codes)), require_languages=True)
                options = knowledge.transcription_options(metadata)
                self.assertEqual(options, {'language': codes[0] if count == 1 else None, 'multilingual': count != 1})
        for value in (None, [], 'en', ['fr'], ['en', 'en'], ['en', 'nl', 'it', 'en'], [1], [{}]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                knowledge.validate_metadata(dict(BASE, expected_languages=value), require_languages=True)
        with self.assertRaises(ValueError):
            knowledge.validate_metadata(BASE, require_languages=True)
        self.assertEqual(knowledge.validate_metadata(BASE), dict(BASE, diarization_enabled=False, speaker_count=None, transcription_vocabulary=''))
        self.assertEqual(knowledge.transcription_options({}), {'language': None, 'multilingual': True})

    def test_upload_processing_and_ingestion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(worker, 'ROOT', root), patch.object(worker, 'DB', root / 'jobs.sqlite3'):
                worker.init()
                server = worker.ThreadingHTTPServer(('127.0.0.1', 0), worker.Handler)
                server.worker_thread = threading.current_thread()
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    for codes in ([ 'en' ], ['nl'], ['it'], ['en', 'nl'], ['en', 'it'], ['nl', 'it'], ['en', 'nl', 'it'], None):
                        session = worker.create_session('test', str(codes))
                        conn = http.client.HTTPConnection(*server.server_address, timeout=10)
                        route = '/meeting-ui/upload/' + session['upload_token']
                        def upload(metadata):
                            conn.request('POST', route, b'test audio', {'X-Filename': 'test.wav', 'X-Meeting-Metadata': quote(json.dumps(metadata))})
                            response = conn.getresponse()
                            response.read()
                            return response.status
                        for invalid in (dict(BASE), dict(BASE, expected_languages=[]), dict(BASE, expected_languages=['xx'])):
                            self.assertEqual(upload(invalid), 400)
                            self.assertEqual(worker.get_job(session['id'])['state'], 'waiting_upload')
                        for invalid in (dict(BASE, expected_languages=['en'], diarization_enabled='yes'),
                                        dict(BASE, expected_languages=['en'], diarization_enabled=True, speaker_count=0),
                                        dict(BASE, expected_languages=['en'], diarization_enabled=False, speaker_count=2)):
                            self.assertEqual(upload(invalid), 400)
                            self.assertEqual(worker.get_job(session['id'])['state'], 'waiting_upload')
                        metadata = dict(BASE, expected_languages=codes or ['en'])
                        self.assertEqual(upload(metadata), 202)
                        self.assertEqual(upload(metadata), 409)
                        conn.close()
                        job = worker.get_job(session['id'])
                        folder = Path(job['folder'])
                        if codes is None:
                            # Existing queued job with MVP3 metadata but no language selection.
                            report.save(folder / 'meeting_metadata.json', BASE)
                            with worker.connect() as c:
                                c.execute('UPDATE jobs SET audio_language=NULL,mixed_languages=NULL WHERE id=?', (job['id'],))
                            job = worker.get_job(job['id'])
                        calls = []
                        class Model:
                            def __init__(self, *a, **kw): pass
                            def transcribe(self, audio, **kw):
                                calls.append(kw)
                                return iter([types.SimpleNamespace(start=0, end=2, text='Hello, goedemorgen, buongiorno.')]), types.SimpleNamespace(duration=2, language='en')
                        original_run = report.run
                        def run(args):
                            args.validate_only = True
                            archive = original_run(args)
                            report.save(archive / 'findings.json', [])
                            report.atomic(archive / 'report.md', '# Offline report fixture\n')
                            return archive
                        with patch.dict('sys.modules', {'faster_whisper': types.SimpleNamespace(WhisperModel=Model)}), patch.object(report, 'run', side_effect=run):
                            worker.process(job)
                        self.assertEqual(worker.get_job(job['id'])['state'], 'completed')
                        expected = knowledge.transcription_options({'expected_languages': codes} if codes else {})
                        self.assertEqual(calls[0], dict(task='transcribe', vad_filter=True, beam_size=5, word_timestamps=True, hotwords=None, **expected))
                        source = json.loads((folder / 'audio_source.json').read_text(encoding='utf-8'))
                        self.assertEqual(source['expected_languages'], codes or ['en'])
                        transcript = json.loads((folder / 'transcript.json').read_text(encoding='utf-8'))
                        self.assertEqual(transcript['expected_languages'], codes)
                        self.assertIn('buongiorno', (folder / 'transcript.md').read_text(encoding='utf-8'))
                        self.assertIn('Expected audio languages', (folder / 'knowledge.md').read_text(encoding='utf-8'))
                        self.assertIsNone(ingestion.document(folder, root))
                        current = review.view(root, job['id'], job['owner'])
                        review.act(root, job['id'], job['owner'], {'action':'approve', 'revision':current['revision']})
                        doc = ingestion.document(folder, root)
                        self.assertIn(b'Reviewed meeting recap', doc['raw'])
                        self.assertIsNotNone(doc)
                        worker.update(job['id'], state='analyzing')
                        self.assertIsNone(ingestion.document(folder, root))
                        worker.update(job['id'], state='completed')
                    # Completely legacy archive without meeting metadata remains exportable.
                    (folder / 'meeting_metadata.json').unlink()
                    self.assertIn('Metadata unavailable', knowledge.render(folder))
                    self.assertFalse(ingestion.worker_busy(root))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()




if __name__ == '__main__':
    unittest.main(verbosity=2)


"""Offline worker tests: HTTP + SQLite + real reporter; ASR and Ollama are mocked."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import meeting_worker as w


class ModelServer(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            out = {"thinking": {"values": [False, True]}}
        else:
            data = json.loads(body["messages"][1]["content"].split("DATA:\n")[1])
            if "paragraphs" in body["format"].get("properties", {}):
                out = {"message": {"content": json.dumps({"paragraphs": [{"section": "discussion", "text": "The group discussed the plan together.", "facts": [data[0]["ref"]]}]})}, "done": True, "done_reason": "stop", "prompt_eval_count": 1500}
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(out).encode() + b"\n")
                return
            ev = data[0]["ref"]
            out = {"message": {"content": json.dumps({"facts": [{"kind": "topic", "topic": "Planning", "text": "The plan was discussed.",
                "evidence": [ev], "owner": None, "deadline": None, "interpretation": None}]})}, "done": True, "done_reason": "stop", "prompt_eval_count": 1500}
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(out).encode() + b"\n")


class FakeWhisper:
    calls = []
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, *args, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["task"] == "transcribe"
        return iter([types.SimpleNamespace(start=0, end=5, text="We bespreken het plan in English and Dutch.")]), types.SimpleNamespace(duration=6, language="nl")


class Tests(unittest.TestCase):
    def setUp(self):
        FakeWhisper.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(w, "ROOT", self.root), patch.object(w, "DB", self.root / "jobs.sqlite3"), patch.object(w, "API_KEY", "x" * 40)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        w.init()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), w.Handler)
        self.server.worker_thread = threading.current_thread()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, data=None, headers=None):
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    def session(self):
        code, obj = self.request("/v1/sessions", json.dumps({"owner": "alice", "request_key": "chat:message"}).encode(), {"Authorization": "Bearer " + "x" * 40})
        self.assertEqual(code, 200)
        return obj

    def upload(self, s):
        return self.request("/meeting-ui/upload/" + s["upload_token"], b"mock audio bytes", {"X-Filename": "test.m4a", "Content-Type": "application/octet-stream"})

    def test_auth_ownership_and_idempotency(self):
        s = self.session()
        self.assertEqual(self.session()["id"], s["id"])
        self.assertEqual(self.request("/v1/sessions/" + s["id"])[0], 401)
        headers = {"Authorization": "Bearer " + "x" * 40, "X-Owner-Id": "bob"}
        self.assertEqual(self.request("/v1/sessions/" + s["id"], headers=headers)[0], 404)

    def test_upload_atomic_and_single_use(self):
        s = self.session()
        self.assertEqual(self.upload(s)[0], 202)
        self.assertEqual(self.upload(s)[0], 409)
        job = w.get_job(s["id"])
        self.assertEqual(job["state"], "queued")
        self.assertEqual((Path(job["folder"]) / "audio.m4a").read_bytes(), b"mock audio bytes")
        self.assertIsNone(json.loads((Path(job["folder"]) / "audio_source.json").read_text())["meeting_date"])

    def test_restart_recovery(self):
        s = self.session()
        self.upload(s)
        w.update(s["id"], state="analyzing")
        w.recover()
        self.assertEqual(w.get_job(s["id"])["state"], "queued")

    def test_upload_to_completed_archive_mock_models(self):
        s = self.session()
        self.complete_job(s)
        self.assertIsNone(FakeWhisper.calls[-1]["language"])
        self.assertFalse(FakeWhisper.calls[-1]["multilingual"])

    def test_selected_languages_reach_asr_and_report(self):
        s = w.create_session("alice", "italian", "it", True, "French")
        self.complete_job(s)
        self.assertEqual(FakeWhisper.calls[-1]["language"], "it")
        self.assertTrue(FakeWhisper.calls[-1]["multilingual"])
        folder = Path(w.get_job(s['id'])['folder'])
        meta = json.loads(next((folder / 'analysis').glob('*/manifest.json')).read_text())
        self.assertEqual(meta['language'], 'French')
        w.recover()
        self.assertEqual(w.get_job(s['id'])['report_language'], 'French')

    def test_language_validation_and_idempotency(self):
        s = w.create_session("alice", "same", "de", True, "Italian")
        repeated = w.create_session("alice", "same", "nl", False, "Dutch")
        self.assertEqual(s['id'], repeated['id'])
        self.assertEqual(repeated['audio_language'], 'de')
        self.assertEqual(repeated['report_language'], 'Italian')
        for options in ({'audio_language': 'invented'}, {'mixed_languages': 'false'}, {'report_language': 'Ignore instructions'}):
            body = {'owner': 'alice', 'request_key': 'invalid', **options}
            self.assertEqual(self.request('/v1/sessions', json.dumps(body).encode(), {'Authorization': 'Bearer ' + 'x' * 40})[0], 400)

    def test_legacy_schema_migrates_without_losing_jobs(self):
        with w.connect() as c:
            c.execute('DROP TABLE jobs')
            c.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, token TEXT UNIQUE, owner TEXT, request_key TEXT, created REAL, updated REAL, state TEXT, detail TEXT, percent REAL, filename TEXT, folder TEXT, error TEXT, UNIQUE(owner,request_key))')
            c.execute("INSERT INTO jobs(id,owner,request_key,state) VALUES ('old','alice','old','completed')")
        w.init()
        self.assertEqual(w.get_job('old')['state'], 'completed')
        self.assertIsNone(w.get_job('old')['mixed_languages'])
        self.assertIsNone(w.get_job('old')['audio_language'])
        w.init()  # Migration is idempotent.

    def complete_job(self, s):
        self.upload(s)
        model = ThreadingHTTPServer(("127.0.0.1", 0), ModelServer)
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=FakeWhisper)}), patch.dict(w.os.environ, {"REPORT_OLLAMA_URL": f"http://127.0.0.1:{model.server_port}"}), contextlib.redirect_stderr(io.StringIO()):
                w.process(w.get_job(s["id"]))
        finally:
            model.shutdown()
            model.server_close()
            thread.join()
        job = w.get_job(s["id"])
        self.assertEqual(job["state"], "completed", job["error"])
        folder = Path(job["folder"])
        self.assertIn("Source references and review notes", (folder / "report.md").read_text(encoding="utf-8"))
        self.assertIn("S000001", (folder / "transcript.md").read_text(encoding="utf-8"))
        code, result = self.request("/v1/sessions/" + s["id"], headers={"Authorization": "Bearer " + "x" * 40, "X-Owner-Id": "alice"})
        self.assertEqual(code, 200)
        self.assertIn("report", result)
        self.assertNotIn("report", self.request("/meeting-ui/status/" + s["upload_token"])[1])


if __name__ == "__main__":
    unittest.main()

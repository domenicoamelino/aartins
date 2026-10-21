"""Offline Pipe control-flow tests; stub httpx/pydantic, not a WebUI runtime test."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class BaseModel:
    pass


class Response:
    def __init__(self, obj, status=200):
        self.obj, self.status_code = obj, status

    def json(self):
        return self.obj

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Client:
    posts = []
    gets = []
    code = 200
    jid = "a" * 32

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return Response({"id": self.jid, "upload_token": "test-capability"})

    async def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return Response({"state": "completed", "report": "# Meeting\nRecap text. [↗](#note-1)\n[00:00](transcript.md#S000001)\n<details>\n<summary>Source references and review notes</summary>\nPrivate evidence.\n</details>",
                         "transcript": '## Full transcript\n<a id="S000001"></a>Evidence.', "archive": "/meetings/test"}, self.code)


class Tests(unittest.TestCase):
    def setUp(self):
        Client.posts, Client.gets, Client.code = [], [], 200
        spec = importlib.util.spec_from_file_location("tested_pipe", Path(__file__).resolve().parent.parent / "openwebui_meeting_pipe.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"httpx": types.SimpleNamespace(AsyncClient=Client),
                                     "pydantic": types.SimpleNamespace(BaseModel=BaseModel, Field=lambda default=None, **kwargs: default)}):
            spec.loader.exec_module(module)
        self.pipe = module.Pipe()
        self.pipe.valves.WORKER_API_KEY = "x" * 40
        self.pipe.valves.PUBLIC_ORIGIN = "http://mini:8088"
        self.events = []

    async def emit(self, obj):
        self.events.append(obj)

    def call(self, text, valves=None):
        return asyncio.run(self.pipe.pipe({"messages": [{"role": "user", "content": text}]},
            __user__={"id": "alice", "valves": valves}, __event_emitter__=self.emit, __chat_id__="chat", __message_id__="message"))

    def test_upload_card_and_final_markdown(self):
        result = self.call("Generate a meeting recap")
        self.assertEqual(Client.posts[0][1]["json"]["owner"], "alice")
        self.assertEqual(Client.posts[0][1]["json"]["audio_language"], "auto")
        self.assertFalse(Client.posts[0][1]["json"]["mixed_languages"])
        self.assertEqual(Client.gets[0][1]["headers"]["X-Owner-Id"], "alice")
        self.assertTrue(any(e["type"] == "embeds" and e["data"]["replace"] for e in self.events))
        self.assertIn("# Meeting", result)
        self.assertNotIn("<details>", result)
        self.assertNotIn("Full transcript", result)
        self.assertNotIn("Private evidence", result)
        self.assertNotIn("#note-", result)
        self.assertNotIn("Archived locally", result)
        self.assertIn("Recap text.", result)
        self.assertNotIn("transcript.md#", result)
        self.assertTrue(self.events[-1]["data"]["done"])

    def test_status_reuses_job(self):
        self.assertIn("# Meeting", self.call("status " + Client.jid))
        self.assertEqual(Client.posts, [])
        self.assertFalse(any(e["type"] == "embeds" for e in self.events))

    def test_unknown_job(self):
        Client.code = 404
        self.assertIn("Job not found", self.call("status " + Client.jid))
        self.assertEqual(Client.posts, [])

    def test_user_language_settings_sent_as_dict_or_object(self):
        settings = {"AUDIO_LANGUAGE": "it", "MIXED_LANGUAGES": True, "RECAP_LANGUAGE": "French"}
        for prefs in (settings, types.SimpleNamespace(**settings)):
            self.call('Generate', prefs)
            payload = Client.posts[-1][1]['json']
            self.assertEqual(payload['audio_language'], 'it')
            self.assertTrue(payload['mixed_languages'])
            self.assertEqual(payload['report_language'], 'French')


if __name__ == "__main__":
    unittest.main()

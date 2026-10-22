import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import telegram_notify as t

TOKEN = "123456:" + "A" * 30


class TelegramTests(unittest.TestCase):
    def test_weekdays_in_local_timezone(self):
        self.assertTrue(t.eligible("service", "2026-10-23T10:00:00Z"))
        self.assertFalse(t.eligible("service", "2026-10-23T23:30:00Z"))
        self.assertTrue(t.eligible("service", "2026-10-25T23:30:00Z"))
        self.assertFalse(t.eligible("manual", "2026-10-23T10:00:00Z"))
        self.assertFalse(t.eligible("service", "invalid"))
        self.assertFalse(t.eligible("service", "2026-10-23T10:00:00"))

    def test_private_chats_only_without_consuming_updates(self):
        updates = [
            {"message": {"chat": {"id": 4, "type": "private", "first_name": "Alex"}}},
            {"message": {"chat": {"id": 4, "type": "private", "first_name": "Alex"}}},
            {"message": {"chat": {"id": -9, "type": "group", "title": "Team"}}},
            {"channel_post": {"chat": {"id": 5, "type": "private"}}},
        ]
        with patch.object(t, "api", return_value=updates) as call:
            self.assertEqual(t.discover_chats(TOKEN), [{"id": 4, "label": "Alex"}])
            self.assertNotIn("offset", call.call_args.args[2])
            self.assertEqual(call.call_args.args[2]["timeout"], 0)

    def test_plain_delivery_and_privacy(self):
        run = {"status": "completed", "started": "2026-10-23T01:00:00Z",
               "finished": "2026-10-23T01:01:00Z", "duration_seconds": 60,
               "uploaded": 2, "unchanged": 4,
               "errors": ["SECRET APIKEY filename-private.md"],
               "filename": "private.md"}
        with patch.object(t, "api", return_value={"message_id": 22}) as call:
            self.assertEqual(t.send_report(TOKEN, 4, run, "http://100.1.2.3:8088"), 22)
            payload = call.call_args.args[2]
            self.assertNotIn("parse_mode", payload)
            self.assertTrue(payload["disable_web_page_preview"])
            self.assertNotIn("SECRET", payload["text"])
            self.assertNotIn("private.md", payload["text"])
            self.assertIn("Errors: 1", payload["text"])
            self.assertIn("03:00 CEST", payload["text"])

    def test_api_json_and_no_proxies_redirects(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true,"result":{"id":1}}'
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(t.urllib.request, "build_opener", return_value=opener) as build:
            self.assertEqual(t.api(TOKEN, "getMe"), {"id": 1})
            handlers = build.call_args.args
            self.assertEqual(handlers[0].proxies, {})
            self.assertIsInstance(handlers[1], t._NoRedirect)
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, f"https://api.telegram.org/bot{TOKEN}/getMe")
            self.assertIsNone(handlers[1].redirect_request(None, None, 302, "", {}, "http://evil"))

    def test_errors_never_expose_token_or_response(self):
        opener = MagicMock()
        for exc in (urllib.error.HTTPError(f"https://secret/{TOKEN}", 401, TOKEN, {}, None),
                    urllib.error.URLError(TOKEN), ValueError(TOKEN)):
            opener.open.side_effect = exc
            with patch.object(t.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(t.NotificationError) as caught:
                    t.api(TOKEN, "getMe")
                self.assertNotIn(TOKEN, str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"ok": False, "description": TOKEN}).encode()
        opener.open.side_effect = None
        opener.open.return_value = response
        with patch.object(t.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(t.NotificationError) as caught:
                t.api(TOKEN, "getMe")
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_invalid_token_and_method_no_network(self):
        with patch.object(t.urllib.request, "build_opener") as build:
            for token, method in (("bad", "getMe"), (TOKEN, "deleteWebhook")):
                with self.assertRaises(t.NotificationError):
                    t.api(token, method)
            build.assert_not_called()

    def test_token_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text(TOKEN + "\n")
            os.chmod(path, 0o600)
            self.assertEqual(t.read_token(path), TOKEN)
            if os.name != "nt":
                os.chmod(path, 0o644)
                with self.assertRaises(t.NotificationError):
                    t.read_token(path)


if __name__ == "__main__":
    unittest.main()

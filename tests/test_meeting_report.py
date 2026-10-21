"""Offline regression tests: no installed Ollama or third-party packages needed."""
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest

import meeting_report as m


class FakeOllama(BaseHTTPRequestHandler):
    requests = []
    reject_think = False
    bad_quote = False
    truncate = False
    invalid_kind = False
    invalid_kind_once = False
    fail_after = None
    bad_narrative = False

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"thinking":{"values":[true,false]}}')
            return
        type(self).requests.append(body)
        if self.reject_think and "think" in body:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"think is unsupported"}')
            return
        prompt = body["messages"][1]["content"]
        items = json.loads(prompt.split("DATA:\n", 1)[1])
        if "paragraphs" in body["format"].get("properties", {}):
            refs = [999] if self.bad_narrative else [x["ref"] for x in items]
            output = json.dumps({"paragraphs": [{"section": "discussion", "text": "The group discussed the current planning. Some questions remained open.", "facts": refs}]})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"message": {"content": output}, "done": True, "done_reason": "stop", "prompt_eval_count": 1600}).encode() + b"\n")
            return
        summary = "Summarize these" in prompt
        evidence = [items[0]["evidence"][0]["ref"]] if summary else [items[0]["ref"]]
        if self.bad_quote:
            evidence = [999999]
        fact = {"kind": "summary" if summary else "topic", "topic": "Planning", "text": "Planning was discussed.", "evidence": evidence,
                "owner": None, "deadline": None, "interpretation": None}
        if self.invalid_kind or self.invalid_kind_once or (self.fail_after is not None and len(self.requests) > self.fail_after):
            fact["kind"] = "topic|confirmed|proposed|action"
            type(self).invalid_kind_once = False
        output = json.dumps({"facts": [fact]})
        self.send_response(200)
        self.end_headers()
        for packet in [{"message": {"content": output[:20]}}, {"message": {"content": output[20:]}, "done": True,
                        "done_reason": "length" if self.truncate else "stop", "prompt_eval_count": 1600}]:
            self.wfile.write(json.dumps(packet).encode() + b"\n")


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        FakeOllama.requests = []
        FakeOllama.reject_think = False
        FakeOllama.bad_quote = False
        FakeOllama.truncate = False
        FakeOllama.invalid_kind = False
        FakeOllama.invalid_kind_once = False
        FakeOllama.fail_after = None
        FakeOllama.bad_narrative = False

    def args(self, rows):
        path = self.root / "input.json"
        path.write_text(json.dumps({"segments": rows}), encoding="utf-8")
        return m.parser().parse_args([str(path), "--archive-root", str(self.root / "meetings"), "--url", f"http://127.0.0.1:{self.server.server_port}", "--report-style", "detailed"])

    def make_legacy(self, folder):
        for request_path in folder.glob("request_[0-9]*.json"):
            meta_path = request_path.with_name(request_path.name.replace("request_", "request_meta_", 1))
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["format"] = "json"
            request["messages"][1]["content"] = "Legacy request\nDATA:\n" + m.wire(meta["items"])
            m.save(request_path, request)
            answer_path = request_path.with_name(request_path.name.replace("request_", "response_", 1))
            if answer_path.exists():
                answer = json.loads(answer_path.read_text(encoding="utf-8"))
                try:
                    _, catalog = m.request_data(meta["items"], meta["summary"])
                    answer["content"] = m.wire(m.resolve_output(json.loads(answer["content"]), catalog, meta["summary"]))
                    m.save(answer_path, answer)
                except m.ReportError:
                    pass
            meta_path.unlink()

    def test_long_bilingual_end_to_end_and_budget(self):
        rows = [{"start": i * 30, "end": i * 30 + 29, "text": f"Planning {i}: We bespreken het voorstel. We should review this plan together."} for i in range(180)]
        args = self.args(rows)
        with contextlib.redirect_stderr(io.StringIO()):
            archive = m.run(args)
        manifest = json.loads((archive / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertIsNone(manifest["meeting_date"])
        self.assertGreater(manifest["summary_levels"], 0)
        self.assertEqual(manifest["source_sha256"], hashlib.sha256((archive / "source.original.json").read_bytes()).hexdigest())
        self.assertIn("S000180", (archive / "transcript.md").read_text())
        self.assertIn("## Action items", (archive / "report.md").read_text(encoding="utf-8"))
        for req in FakeOllama.requests:
            total = sum(len(x["content"].encode()) for x in req["messages"])
            self.assertLessEqual(total + req["options"]["num_predict"] + 384, 4096)
            self.assertIs(req["think"], False)

    def test_bad_quotes_fail_without_final_report(self):
        FakeOllama.bad_quote = True
        args = self.args([{"start": 0, "end": 2, "text": "We bespreken het plan."}])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(m.ReportError):
            m.run(args)
        archive = next((self.root / "meetings").iterdir())
        self.assertFalse((archive / "report.md").exists())
        self.assertEqual(json.loads((archive / "manifest.json").read_text())["status"], "failed")
        self.assertTrue((archive / "source.original.json").exists())

    def test_thinking_fallback(self):
        FakeOllama.reject_think = True
        args = self.args([{"start": 0, "end": 2, "text": "Review the plan."}])
        with contextlib.redirect_stderr(io.StringIO()):
            archive = m.run(args)
        self.assertEqual(json.loads((archive / "manifest.json").read_text())["thinking_control"], "model_default")
        self.assertNotIn("think", FakeOllama.requests[-1])

    def test_truncation_fails(self):
        FakeOllama.truncate = True
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(m.ReportError):
            m.run(self.args([{"start": 0, "end": 2, "text": "Review the plan."}]))

    def test_invalid_times(self):
        for value in [True, float("nan"), -1, "0"]:
            args = self.args([{"start": value, "end": 2, "text": "hello"}])
            with self.assertRaises(m.ReportError):
                m.load_source(args.transcript)

    def test_exact_owner_grounding(self):
        source = {"S000001": {"text": "Alex: I will send it tomorrow."}}
        fact = {"kind": "action", "topic": "Send", "text": "Send it", "evidence": [{"id": "S000001", "quote": "I will send it tomorrow."}], "owner": "Alex", "deadline": "tomorrow", "interpretation": None}
        with self.assertRaises(m.ReportError):
            m.validate({"facts": [fact]}, source, {"S000001": [source["S000001"]["text"]]})
        fact["owner"] = None
        self.assertEqual(m.validate({"facts": [fact]}, source, {"S000001": [source["S000001"]["text"]]})[0]["deadline"], "tomorrow")

    def test_oversized_segment_no_text_loss(self):
        text = "één café hello \"data\"\n" * 2000
        units = m.units_for([{"id": "S000001", "text": text}], 600)
        self.assertEqual("".join(x["text"] for x in units), text)
        self.assertTrue(all(len(m.wire([x]).encode()) <= 600 for x in units))

    def test_nonlocal_endpoint_rejected(self):
        args = self.args([{"start": 0, "end": 2, "text": "hello"}])
        args.url = "http://example.com:11434"
        with self.assertRaises(m.ReportError):
            m.run(args)

    def test_request_schema_enforces_actual_categories_and_ids(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the plan."}])
        with contextlib.redirect_stderr(io.StringIO()):
            m.run(args)
        schema = FakeOllama.requests[0]["format"]
        self.assertIsInstance(schema, dict)
        fact = schema["properties"]["facts"]["items"]
        self.assertEqual(fact["properties"]["kind"]["enum"], list(m.KINDS[:-1]))
        self.assertEqual(schema["properties"]["facts"]["maxItems"], 3)
        self.assertEqual(fact["properties"]["evidence"]["items"], {"type": "integer", "enum": [1]})
        self.assertEqual(m.response_schema(["S000001"], True)["properties"]["facts"]["items"]["properties"]["kind"]["enum"], ["summary"])

    def test_invalid_kind_corrected_once_without_splitting(self):
        FakeOllama.invalid_kind_once = True
        args = self.args([{"start": i, "end": i + 1, "text": "Review the plan."} for i in range(4)])
        with contextlib.redirect_stderr(io.StringIO()):
            archive = m.run(args)
        self.assertEqual(len(FakeOllama.requests), 2)
        first, second = [x["messages"][1]["content"] for x in FakeOllama.requests]
        self.assertEqual(first.split("DATA:\n")[1], second.split("DATA:\n")[1])
        self.assertIn("Previous output rejected", second)
        self.assertEqual(json.loads((archive / "manifest.json").read_text())["status"], "complete")

    def test_persistent_invalid_kind_does_not_cascade_splits(self):
        FakeOllama.invalid_kind = True
        args = self.args([{"start": i, "end": i + 1, "text": "Review the plan."} for i in range(4)])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(m.ReportError, "corrective retry"):
            m.run(args)
        self.assertEqual(len(FakeOllama.requests), 2)

    def test_resume_reuses_cache_without_model_generation(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the plan."}])
        with contextlib.redirect_stderr(io.StringIO()):
            first = m.run(args)
            FakeOllama.requests = []
            args.resume = first
            second = m.run(args)
        self.assertNotEqual(first, second)
        self.assertEqual(FakeOllama.requests, [])
        self.assertTrue((first / "report.md").exists())
        self.assertTrue((second / "report.md").exists())

    def test_resume_legacy_audit_files_without_cache(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the plan."}])
        with contextlib.redirect_stderr(io.StringIO()):
            first = m.run(args)
            (first / "cache.json").unlink()
            self.make_legacy(first)
            meta = json.loads((first / "manifest.json").read_text())
            meta["version"] = "2.2.0"
            m.save(first / "manifest.json", meta)
            FakeOllama.requests = []
            args.resume = first
            second = m.run(args)
        self.assertEqual(FakeOllama.requests, [])
        self.assertEqual(json.loads((second / "manifest.json").read_text())["imported_cache_entries"], 1)

    def test_resume_rejects_changed_source(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the plan."}])
        with contextlib.redirect_stderr(io.StringIO()):
            first = m.run(args)
        args.transcript.write_text('{"segments":[{"start":0,"end":2,"text":"Different source"}]}', encoding="utf-8")
        args.resume = first
        with self.assertRaisesRegex(m.ReportError, "different source"):
            m.run(args)

    def test_validation_failure_budget(self):
        FakeOllama.invalid_kind = True
        args = self.args([{"start": 0, "end": 2, "text": "Review the plan."}])
        args.max_validation_failures = 1
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaisesRegex(m.ReportError, "Stopped after 1"):
            m.run(args)
        self.assertEqual(len(FakeOllama.requests), 1)

    def test_resume_partial_failed_legacy_run(self):
        args = self.args([{"start": i * 10, "end": i * 10 + 8,
                          "text": f"Planning item {i}: We bespreken het voorstel en we review the plan together."} for i in range(30)])
        FakeOllama.fail_after = 1
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(m.ReportError):
            m.run(args)
        first = next((self.root / "meetings").iterdir())
        (first / "cache.json").unlink()  # Reproduce the original version's audit-only recovery.
        self.make_legacy(first)
        FakeOllama.fail_after = None
        FakeOllama.requests = []
        args.resume = first
        with contextlib.redirect_stderr(io.StringIO()):
            second = m.run(args)
        meta = json.loads((second / "manifest.json").read_text())
        self.assertEqual(meta["status"], "complete")
        self.assertEqual(meta["imported_cache_entries"], 1)
        first_new_items = json.loads(FakeOllama.requests[0]["messages"][1]["content"].split("DATA:\n")[1])
        self.assertNotEqual(first_new_items[0]["id"], "S000001")
        self.assertFalse((first / "report.md").exists())

    def test_reference_resolution_uses_original_source_verbatim(self):
        items = [{"id": "S000011", "text": "For this synthetic example, Sam will review the sample document with Taylor today."}]
        _, catalog = m.request_data(items)
        raw = {"facts": [{"kind": "action", "topic": "Introduction", "text": "Jordan will meet a colleague tomorrow.",
                          "evidence": [1], "owner": "Jordan", "deadline": "tomorrow", "interpretation": None}]}
        result = m.resolve_output(raw, catalog)["facts"][0]
        self.assertEqual(result["evidence"], [{"id": "S000011", "quote": items[0]["text"]}])
        self.assertIsNone(result["owner"])
        self.assertNotIn("Jordan", result["text"])
        self.assertIsNone(result["deadline"])
        self.assertNotIn("tomorrow", result["text"])
        self.assertIn("owner_unverified", result["verification_warnings"])

    def test_reference_resolution_rejects_unknown_or_boolean_ids(self):
        for ref in (999, True, "1", {"id": "S000011", "quote": "invented"}):
            with self.assertRaises(m.ReportError):
                m.resolve_output({"facts": [{"evidence": [ref]}]}, {1: {"id": "S000011", "quote": "Original words."}})

    def test_optional_interpretation_does_not_abort_core_report(self):
        catalog = {1: {"id": "S000001", "quote": "Could you explain the planning?"}}
        raw = {"kind": "behavior", "topic": "Clarification", "text": "A participant asks for clarification.",
               "evidence": [1], "owner": None, "deadline": None, "interpretation": "This may indicate a need for shared understanding."}
        result = m.resolve_output({"facts": [raw]}, catalog)["facts"][0]
        self.assertTrue(result["interpretation"].startswith("Possible interpretation:"))
        raw["kind"] = "topic"
        result = m.resolve_output({"facts": [raw]}, catalog)["facts"][0]
        self.assertIsNone(result["interpretation"])
        self.assertIn("interpretation_omitted", result["verification_warnings"])

    def test_owner_case_whitespace_and_word_boundaries(self):
        evidence = [{"id": "S000001", "quote": "Alex will send it next   week; planning continues."}]
        self.assertEqual(m.grounded_field("alex", evidence), "Alex")
        self.assertEqual(m.grounded_field("next week", evidence), "next   week")
        self.assertIsNone(m.grounded_field("Ann", evidence))

    def test_preview_never_publishes_complete_report_and_can_resume(self):
        args = self.args([{"start": i * 10, "end": i * 10 + 8, "text": "We bespreken het voorstel and review this plan together."} for i in range(40)])
        args.preview_chunks = 1
        with contextlib.redirect_stderr(io.StringIO()):
            first = m.run(args)
        self.assertFalse((first / "report.md").exists())
        self.assertIn("PARTIAL PREVIEW", (first / "preview_report.md").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((first / "manifest.json").read_text())["status"], "preview_complete")
        args.resume, args.preview_chunks = first, 0
        with contextlib.redirect_stderr(io.StringIO()):
            second = m.run(args)
        self.assertTrue((second / "report.md").exists())

    def test_diagnostic_pairs_wrong_quote_with_actual_source(self):
        from inspect_meeting_run import diagnose
        args = self.args([{"start": 0, "end": 2, "text": "That was the question."},
                          {"start": 2, "end": 4, "text": "The action we agreed on is an introduction."}])
        with contextlib.redirect_stderr(io.StringIO()):
            archive = m.run(args)
        self.make_legacy(archive)
        response_path = archive / "response_0001.json"
        answer = json.loads(response_path.read_text(encoding="utf-8"))
        bad = json.loads(answer["content"])
        bad["facts"][0]["evidence"] = [{"id": "S000001", "quote": "The action we agreed on is an introduction."}]
        answer["content"] = m.wire(bad)
        m.save(response_path, answer)
        output = diagnose(archive)
        self.assertIn("QUOTE MISMATCH", output)
        self.assertIn("Exact quote found in: S000002", output)

    def test_readable_report_has_prose_and_expandable_evidence(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the planning together."}])
        args.report_style = "readable"
        with contextlib.redirect_stderr(io.StringIO()):
            archive = m.run(args)
        report = (archive / "report.md").read_text(encoding="utf-8")
        body, appendix = report.split("<details>", 1)
        self.assertIn("The group discussed the current planning.", body)
        self.assertNotIn("Evidence (", body)
        self.assertNotIn("No supported findings", body)
        self.assertNotIn("- ", body)
        self.assertIn("Review the planning together.", appendix)
        self.assertIn("transcript.md#S000001", appendix)
        self.assertTrue((archive / "narrative.json").exists())

    def test_preview_also_runs_readable_writing(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the planning together."}])
        args.report_style, args.preview_chunks = "readable", 1
        with contextlib.redirect_stderr(io.StringIO()):
            archive = m.run(args)
        self.assertTrue((archive / "preview_report.md").exists())
        self.assertFalse((archive / "report.md").exists())
        self.assertTrue(any("paragraphs" in r["format"]["properties"] for r in FakeOllama.requests))

    def test_unknown_narrative_refs_rejected(self):
        with self.assertRaises(m.ReportError):
            m.check_narrative({"paragraphs": [{"section": "discussion", "text": "Claim.", "facts": [999]}]}, {1})

    def test_failed_writer_preserves_checked_extraction_for_resume(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the planning together."}])
        args.report_style = "readable"
        FakeOllama.bad_narrative = True
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(m.ReportError):
            m.run(args)
        first = next((self.root / "meetings").iterdir())
        self.assertTrue((first / "findings.json").exists())
        self.assertTrue((first / "cache.json").exists())
        self.assertFalse((first / "report.md").exists())
        FakeOllama.bad_narrative, FakeOllama.requests = False, []
        args.resume = first
        with contextlib.redirect_stderr(io.StringIO()):
            second = m.run(args)
        self.assertTrue((second / "report.md").exists())
        self.assertTrue(all("paragraphs" in r["format"]["properties"] for r in FakeOllama.requests))

    def test_readable_resume_reuses_both_stages(self):
        args = self.args([{"start": 0, "end": 2, "text": "Review the planning together."}])
        args.report_style = "readable"
        with contextlib.redirect_stderr(io.StringIO()):
            first = m.run(args)
            FakeOllama.requests = []
            args.resume = first
            second = m.run(args)
        self.assertTrue((second / "report.md").exists())
        self.assertEqual(FakeOllama.requests, [])

    def test_contradictory_action_metadata_is_not_fuzzy_deleted(self):
        base = {"kind": "action", "text": "Send the plan.", "owner": "Alex", "deadline": "Monday", "evidence": [{"id": "S000001", "quote": "Alex will send the plan on Monday."}], "interpretation": None}
        rows = m.narrative_items([base, dict(base), dict(base, deadline="Tuesday"), dict(base, owner="Sam")])
        self.assertEqual(len(rows), 3)

    def test_readable_long_transcript_keeps_requests_in_context(self):
        args = self.args([{"start": i * 30, "end": i * 30 + 29,
                          "text": f"Planning {i}: We bespreken het voorstel and review the plan together."} for i in range(180)])
        args.report_style = "readable"
        with contextlib.redirect_stderr(io.StringIO()):
            archive = m.run(args)
        self.assertEqual(json.loads((archive / "manifest.json").read_text())["status"], "complete")
        self.assertTrue(any("paragraphs" in r["format"]["properties"] for r in FakeOllama.requests))
        for req in FakeOllama.requests:
            total = sum(len(x["content"].encode()) for x in req["messages"])
            self.assertLessEqual(total + req["options"]["num_predict"] + 384, 4096)

    def test_writer_cannot_promote_proposal_to_confirmed_decision(self):
        with self.assertRaises(m.ReportError):
            m.check_narrative({"paragraphs": [{"section": "decisions", "text": "Agreed.", "facts": [1]}]}, {1}, {1: {"kind": "proposed"}})
        sections = m.narrative_schema([1], {"proposed"})["properties"]["paragraphs"]["items"]["properties"]["section"]["enum"]
        self.assertNotIn("decisions", sections)


if __name__ == "__main__":
    unittest.main()

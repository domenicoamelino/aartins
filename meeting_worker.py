#!/usr/bin/env python3
"""Durable single-worker audio -> local meeting report service. Python 3.10+."""
import datetime as dt
from contextlib import contextmanager
import gc
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sqlite3
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid

import meeting_report as report
import meeting_knowledge as knowledge
import meeting_speakers as speakers
import meeting_review as review
import meeting_revision as revisions
import meeting_notifications as notifications

ROOT = Path(os.environ.get("MEETING_ROOT", str(Path.home() / "ai-platform/meetings"))).expanduser()
DB = ROOT / "jobs.sqlite3"
API_KEY = os.environ.get("MEETING_API_KEY", "")
MAX_BYTES = int(os.environ.get("MEETING_MAX_BYTES", 512 * 1024 * 1024))
STOP = threading.Event()
UPDATE_LOCK = threading.RLock()
EXTENSIONS = {".m4a", ".mp3", ".wav", ".mpeg", ".mpga", ".mp4", ".ogg", ".webm", ".flac", ".aac"}


@contextmanager
def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()


def init():
    ROOT.mkdir(parents=True, exist_ok=True)
    review.init(ROOT)
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, token TEXT UNIQUE, owner TEXT, request_key TEXT,
            created REAL, updated REAL, state TEXT, detail TEXT, percent REAL,
            filename TEXT, folder TEXT, error TEXT, UNIQUE(owner, request_key))""")
        columns = {row[1] for row in c.execute("PRAGMA table_info(jobs)")}
        for name, definition in (("audio_language", "TEXT"), ("mixed_languages", "INTEGER"), ("report_language", "TEXT")):
            if name not in columns:
                c.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")


def recover():
    review.recover(ROOT)
    with connect() as c:
        c.execute("UPDATE jobs SET state='queued',detail='Restarted; queued for a fresh processing attempt',updated=? WHERE state IN ('transcribing','analyzing')", (time.time(),))
        c.execute("UPDATE jobs SET state='waiting_upload',detail='Upload interrupted; choose the file again',updated=? WHERE state='uploading'", (time.time(),))


def get_job(jid):
    with connect() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    return dict(row) if row else None


def update(jid, **values):
    with UPDATE_LOCK:
        values["updated"] = time.time()
        with connect() as c:
            c.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?", [*values.values(), jid])
        job = get_job(jid)
        if job and job["folder"]:
            report.save(Path(job["folder"]) / "job.json", public(job))


def public(job):
    return {k: job[k] for k in ("id", "created", "updated", "state", "detail", "percent", "filename", "error")}


def create_session(owner, request_key, audio_language="auto", mixed_languages=False, report_language=None):
    language_codes = {"auto", "en", "nl", "it", "de", "fr", "es", "pt", "zh", "ja", "ko", "ar", "hi", "ru", "uk", "pl", "tr"}
    report_language = report_language or os.environ.get('REPORT_LANGUAGE', 'English')
    if not isinstance(audio_language, str) or audio_language not in language_codes or type(mixed_languages) is not bool or not isinstance(report_language, str) or report_language not in report.REPORT_LANGUAGES:
        raise ValueError('Invalid language preference')
    now = time.time()
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO jobs (id,token,owner,request_key,created,updated,state,detail,audio_language,mixed_languages,report_language) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (uuid.uuid4().hex, secrets.token_urlsafe(32), owner, request_key, now, now, "waiting_upload", "Choose a meeting recording", audio_language, int(mixed_languages), report_language))
        row = dict(c.execute("SELECT * FROM jobs WHERE owner=? AND request_key=?", (owner, request_key)).fetchone())
    return {**public(row), "upload_token": row["token"]}


def process(job):
    jid = job["id"]
    folder = Path(job["folder"])
    audio = folder / ("audio" + Path(job["filename"]).suffix.lower())
    old_log = report.log
    try:
        update(jid, state="transcribing", detail="Loading multilingual Whisper model", percent=None, error=None)
        metadata_path = folder / "meeting_metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        options = knowledge.transcription_options(metadata)
        if 'expected_languages' not in metadata and job.get('audio_language'):
            options = {'language': None if job['audio_language']=='auto' else job['audio_language'],
                       'multilingual': True if job.get('mixed_languages') is None else bool(job['mixed_languages'])}
        from faster_whisper import WhisperModel
        model = WhisperModel(os.environ.get("WHISPER_MODEL", "large-v3"), device="cpu", compute_type="int8",
                             cpu_threads=int(os.environ.get("WHISPER_THREADS", "8")), num_workers=1)
        update(jid, detail=("Transcribing in " + knowledge.LANGUAGES[options["language"]]
                            if options["language"] else "Detecting languages throughout audio; language switching enabled"))
        stream, info = model.transcribe(str(audio), task="transcribe", **options,
                                        vad_filter=True, beam_size=5, word_timestamps=True, hotwords=metadata.get('transcription_vocabulary') or None)
        segments = []
        for segment in stream:
            row = {"start": float(segment.start), "end": float(segment.end), "text": segment.text}
            if getattr(segment, 'words', None):
                row['words'] = [{'start': float(word.start), 'end': float(word.end), 'word': word.word,
                                 'probability': float(word.probability)} for word in segment.words]
            segments.append(row)
            percent = min(99.0, 100 * segment.end / info.duration) if info.duration else None
            update(jid, detail=f"Transcribing {report.stamp(segment.end)} of {report.stamp(info.duration)}", percent=percent)
            if len(segments) % 20 == 0:
                report.save(folder / "transcript.partial.json", {"segments": segments, "complete": False})
        transcript = {"source_file": job["filename"], "model": os.environ.get("WHISPER_MODEL", "large-v3"),
                      "multilingual": options["multilingual"], "language": options["language"],
                      "expected_languages": metadata.get("expected_languages"),
                      "initial_language": info.language, "audio_duration_seconds": info.duration,
                      "segments": segments}
        report.save(folder / "transcript.json", transcript)
        del model, stream
        gc.collect()
        speaker_warning = None
        # Keep the existing transcribing state: queue recovery and ingestion busy checks already know it.
        if speakers.options(metadata)['diarization_enabled']:
            report.save(folder / "transcript.raw.json", transcript)
            update(jid, detail="Identifying different speakers on CPU; recap will follow", percent=None)
            try:
                result = speakers.run(audio, folder, metadata, info.duration, STOP,
                                      lambda message: update(jid, detail=message, percent=None))
                aligned = speakers.align_words(segments, result['turns'], result['exclusive_turns'])
                if not result['turns']:
                    raise ValueError('No speaker turns found')
                result['alignment_summary'] = {
                    'word_timed_source_segments': sum(bool(row.get('words')) for row in segments),
                    'word_aligned_turns': sum(row.get('alignment')=='word-timestamps' for row in aligned),
                    'segment_fallback_turns': sum(row.get('alignment')=='segment-fallback' for row in aligned),
                    'assigned_words_by_voice': {label: sum(len(row.get('words',[])) for row in aligned if row.get('speaker')==label)
                                                for label in sorted({row['speaker'] for row in aligned if row.get('speaker')})}}
                report.save(folder / "diarization.json", result)
                transcript['segments'] = aligned
                transcript['diarization'] = {'status': 'completed', 'anonymous_labels': True,
                                             'model': result.get('model'), 'alignment': 'word-timestamps-with-overlap-flags'}
            except speakers.Interrupted:
                # Restart recovery requeues this job. Never mark shutdown as success.
                raise
            except Exception as exc:
                speaker_warning = "Speaker separation unavailable; recap uses the original transcript"
                old_log(f"Job {jid}: diarization fallback ({type(exc).__name__}): {exc}")
                report.save(folder / "diarization.json", {'schema': 'meeting-diarization/2.5.2',
                            'status': 'failed', 'reason_type': type(exc).__name__, 'fallback': 'original_transcript'})
                transcript['diarization'] = {'status': 'failed', 'fallback': 'original_transcript'}
            report.save(folder / "transcript.json", transcript)
        update(jid, state="analyzing", detail="Preparing evidence-linked analysis", percent=None)
        def progress(message):
            old_log(message)
            match = re.search(r"Extracting chunk (\d+)/(\d+)", message)
            if match:
                update(jid, detail=message, percent=100 * (int(match[1]) - 1) / int(match[2]))
            else:
                update(jid, detail=message, percent=None)
        report.log = progress
        args = report.parser().parse_args([str(folder / "transcript.json"), "--archive-root", str(folder / "analysis"),
                                           "--model", os.environ.get("REPORT_MODEL", "qwen3.5:9b"),
                                           "--language", job.get("report_language") or os.environ.get("REPORT_LANGUAGE", "English"),
                                           "--timeout", os.environ.get("REPORT_TIMEOUT", "1200"),
                                           "--url", os.environ.get("REPORT_OLLAMA_URL", "http://127.0.0.1:11434")])
        if metadata.get('meeting_title'):
            args.title = metadata['meeting_title']
        if metadata.get('meeting_date'):
            args.meeting_date = dt.date.fromisoformat(metadata['meeting_date'])
        archive = report.run(args)
        for name in ("report.md", "transcript.md", "source.json", "findings.json"):
            # Publish copies atomically; all model audit files remain in analysis/.
            report.atomic(folder / name, (archive / name).read_text(encoding="utf-8"))
        knowledge.export(folder)
        update(jid, state="completed", detail=("Draft ready for review; not approved for knowledge ingestion" + (". " + speaker_warning if speaker_warning else "")), percent=100)
        review.ensure(ROOT, get_job(jid))
        review.notice(ROOT, 'completed:'+jid, job['owner'], jid, 'Meeting draft ready for review')
    except speakers.Interrupted:
        update(jid, state="queued", detail="Interrupted during speaker separation; queued for restart", percent=None)
    except Exception as e:
        old_log(f"Job {jid} failed: {e}")
        update(jid, state="failed", detail="Processing failed; source and partial results retained", percent=None, error=str(e)[:1500])
        review.notice(ROOT, 'failed:'+jid, job['owner'], jid, 'Meeting processing failed; source retained')
    finally:
        report.log = old_log


def worker():
    while not STOP.wait(1):
        with connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE jobs SET state='transcribing',updated=? WHERE id=?", (time.time(), row["id"]))
        if row:
            process(dict(row))
        else:
            review.process_next(ROOT, revisions.generate)


class Handler(BaseHTTPRequestHandler):
    server_version = "MeetingWorker/3.1"

    def log_message(self, *_):
        pass  # Never log capability tokens from browser URLs.

    def setup(self):
        super().setup()
        self.connection.settimeout(600)

    def send(self, status, data, content_type="application/json"):
        blob = (json.dumps(data, ensure_ascii=False).encode() if content_type == "application/json" else data.encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        if self.path.startswith("/meeting-ui/"):
            # The iframe has an opaque origin. Its scoped bearer capability grants access.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename, X-Meeting-Metadata")
        self.end_headers()
        self.wfile.write(blob)

    def do_OPTIONS(self):
        if self.path.startswith("/meeting-ui/"):
            self.send(200, {})
        else:
            self.send(404, {"error": "Not found"})

    def auth(self):
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, "Bearer " + API_KEY)

    def capability(self, token):
        with connect() as c:
            row = c.execute("SELECT * FROM jobs WHERE token=?", (token,)).fetchone()
        if not row or time.time() - row["created"] > 86400:
            return None
        return dict(row)

    def length(self, limit):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length")
        if not 0 < n <= limit:
            raise ValueError(f"Body must be between 1 and {limit} bytes")
        return n

    def do_GET(self):
        try:
            self.route_get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except review.Conflict as e:
            self.send(409, {"error": str(e)})
        except Exception as e:
            self.send(500, {"error": str(e)[:500]})

    def route_get(self):
        parts = urlsplit(self.path).path.strip("/").split("/")
        if parts == ["health"]:
            return self.send(200, {"ok": True, "worker_alive": self.server.worker_thread.is_alive()})
        if len(parts) == 4 and parts[:2] == ["v1", "sessions"] and parts[3] == 'review':
            job = self.review_job(parts[2])
            if job is None:
                return
            review.ensure(ROOT, job)
            return self.send(200, review.view(ROOT, job['id'], job['owner']))
        if len(parts) == 3 and parts[:2] == ["v1", "sessions"]:
            if not self.auth():
                return self.send(401, {"error": "Unauthorized"})
            job = get_job(parts[2])
            if not job or job["owner"] != self.headers.get("X-Owner-Id"):
                return self.send(404, {"error": "Not found"})
            result = public(job)
            if job["state"] == "completed":
                folder = Path(job["folder"])
                result.update(report=(folder / "report.md").read_text(encoding="utf-8"),
                              transcript=(folder / "transcript.md").read_text(encoding="utf-8"), archive=str(folder))
                review.ensure(ROOT, job)
                result.update(review.view(ROOT, job['id'], job['owner']))
            return self.send(200, result)
        if len(parts) == 3 and parts[0] == "meeting-ui" and parts[1] in ("view", "status"):
            job = self.capability(parts[2])
            if not job:
                return self.send(404, {"error": "Upload session missing or expired; start a new request"})
            if parts[1] == "view":
                template = (Path(__file__).parent / "upload.html").read_text(encoding="utf-8")
                return self.send(200, template.replace("__TOKEN__", job["token"]), "text/html")
            return self.send(200, public(job))
        self.send(404, {"error": "Not found"})

    def review_job(self, jid):
        if not self.auth():
            self.send(401, {'error': 'Unauthorized'})
            return None
        job = get_job(jid)
        if not job or job['owner'] != self.headers.get('X-Owner-Id'):
            self.send(404, {'error': 'Not found'})
            return None
        return job

    def do_POST(self):
        try:
            self.route_post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except review.Conflict as e:
            self.send(409, {"error": str(e)})
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:
            self.send(500, {"error": str(e)[:500]})

    def route_post(self):
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ['v1', 'sessions'] and parts[3] == 'review':
            job = self.review_job(parts[2])
            if job is None:
                return
            review.ensure(ROOT, job)
            obj = json.loads(self.rfile.read(self.length(256000)))
            return self.send(200, review.act(ROOT, job['id'], job['owner'], obj))
        if parts == ["v1", "sessions"]:
            if not self.auth():
                return self.send(401, {"error": "Unauthorized"})
            obj = json.loads(self.rfile.read(self.length(8192)))
            owner = obj.get("owner", "")
            key = obj.get("request_key", "")
            if not isinstance(owner, str) or not owner or not isinstance(key, str) or not key or len(owner) > 200 or len(key) > 300:
                raise ValueError("owner and request_key required")
            return self.send(200, create_session(owner, key, obj.get('audio_language', 'auto'),
                                                obj.get('mixed_languages', False), obj.get('report_language')))
        if len(parts) == 3 and parts[:2] == ["meeting-ui", "upload"]:
            job = self.capability(parts[2])
            if not job:
                return self.send(404, {"error": "Session expired"})
            if time.time() - job["created"] > 1800:
                return self.send(410, {"error": "Choose a new upload session (upload window is 30 minutes)"})
            filename = Path(unquote(self.headers.get("X-Filename", "audio.m4a")).replace("\\", "/")).name[:180]
            if Path(filename).suffix.lower() not in EXTENSIONS:
                raise ValueError("Unsupported audio filename extension")
            raw_metadata = self.headers.get("X-Meeting-Metadata", "")
            if not raw_metadata or len(raw_metadata) > 6000:
                raise ValueError("Meeting title and date are required (metadata header <=6000 characters)")
            metadata = knowledge.validate_metadata(json.loads(unquote(raw_metadata)), require_languages=True)
            size = self.length(MAX_BYTES)
            with connect() as c:
                cur = c.execute("UPDATE jobs SET state='uploading',detail='Receiving recording',updated=? WHERE id=? AND state='waiting_upload'", (time.time(), job["id"]))
                if cur.rowcount != 1:
                    return self.send(409, {"error": "This session already has an upload or job"})
            slug = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")[:50] or "meeting"
            folder = ROOT / ("processed-" + dt.date.today().isoformat() + "_" + slug + "_" + job["id"])
            folder.mkdir(mode=0o700, exist_ok=True)
            partial = folder / "audio.part"
            try:
                digest = hashlib.sha256()
                remaining = size
                with partial.open("wb") as f:
                    while remaining:
                        block = self.rfile.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError("Upload interrupted")
                        remaining -= len(block)
                        digest.update(block)
                        f.write(block)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(partial, folder / ("audio" + Path(filename).suffix.lower()))
                report.save(folder / "audio_source.json", {"filename": filename, "sha256": digest.hexdigest(), "bytes": size,
                                                           "received_at": dt.datetime.now().astimezone().isoformat(), **metadata})
                report.save(folder / "meeting_metadata.json", metadata)
                update(job["id"], state="queued", detail="Queued for the MINISFORUM worker", filename=filename, folder=str(folder), percent=None)
            except Exception:
                update(job["id"], state="waiting_upload", detail="Upload interrupted; choose the file again")
                raise
            return self.send(202, public(get_job(job["id"])))
        self.send(404, {"error": "Not found"})


def main():
    if len(API_KEY) < 32:
        raise SystemExit("Set MEETING_API_KEY to a random secret of at least 32 characters")
    os.umask(0o077)
    init()
    # One service instance only; prevents duplicate model workers on the same DB.
    import fcntl
    lock = (ROOT / "worker.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another meeting worker already owns this archive")
    recover()
    server = ThreadingHTTPServer((os.environ.get("MEETING_BIND", "127.0.0.1"), int(os.environ.get("MEETING_PORT", "8765"))), Handler)
    server.daemon_threads = True
    server.worker_thread = threading.Thread(target=worker, daemon=True)
    server.worker_thread.start()
    threading.Thread(target=notifications.loop, args=(ROOT, STOP), daemon=True).start()
    def stop(*_):
        STOP.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        print(f"Meeting worker on {server.server_address}; archive {ROOT}", flush=True)
        server.serve_forever()
    finally:
        STOP.set()
        server.server_close()
        # A shutdown interrupts any in-flight model work. Restart requeues that job.


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only move readiness; optional private source/SQLite snapshot. No service changes."""
import argparse
from collections import Counter
from contextlib import closing
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

ACTIVE = {'uploading', 'queued', 'transcribing', 'analyzing'}
WORKER_FILES = ('upload.html', 'meeting_worker.py', 'meeting_report.py', 'meeting_knowledge.py',
                'meeting_speakers.py', 'meeting_review.py', 'meeting_revision.py',
                'meeting_notifications.py', 'configure_meeting_notifications.py', 'openwebui_meeting_pipe.py')

def inspect(root):
    db = root/'meetings/jobs.sqlite3'
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True)) as c:
        jobs = c.execute('SELECT id,state FROM jobs').fetchall()
    result = {'checked_at': dt.datetime.now().astimezone().isoformat(timespec='seconds'),
              'platform': str(root), 'job_counts': dict(Counter(state for _,state in jobs)),
              'active_jobs': [{'id':jid,'state':state} for jid,state in jobs if state in ACTIVE],
              'review_task_counts': {}, 'notice_counts': {}, 'review_meetings': None,
              'active_review_tasks': 0, 'source_sha256': {}}
    review_db=root/'meetings/reviews.sqlite3'
    if review_db.exists():
        with closing(sqlite3.connect(review_db.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            result['review_task_counts']=dict(c.execute('SELECT status,COUNT(*) FROM tasks GROUP BY status'))
            result['review_meetings']=c.execute('SELECT COUNT(*) FROM meetings').fetchone()[0]
            result['notice_counts']=dict(c.execute('SELECT status,COUNT(*) FROM notices GROUP BY status'))
        result['active_review_tasks']=sum(result['review_task_counts'].get(status,0) for status in ('queued','running'))
    for name in WORKER_FILES:
        file=root/'transcription/meeting-worker-2.3'/name
        if file.is_file():
            result['source_sha256'][str(file.relative_to(root))]=hashlib.sha256(file.read_bytes()).hexdigest()
    for relative in ('ingestion/ingest_meetings.py','diarization-benchmark/diarize_meeting.py'):
        file=root/relative
        if file.is_file():
            result['source_sha256'][relative]=hashlib.sha256(file.read_bytes()).hexdigest()
    result['idle']=not result['active_jobs'] and not result['active_review_tasks']
    return result

def snapshot(root, dest, result):
    if not result['idle']:
        raise RuntimeError('Active work: snapshot refused; wait for completion')
    dest=dest.expanduser().resolve()
    if (dest/'checkpoint.json').exists():
        raise RuntimeError('Checkpoint exists; choose a new destination')
    os.umask(0o077)
    dest.mkdir(parents=True,exist_ok=True)
    dest.chmod(0o700)
    for name in ('jobs.sqlite3','reviews.sqlite3'):
        source=root/'meetings'/name
        target=dest/name
        if target.exists():
            raise RuntimeError('Refusing to overwrite existing SQLite snapshot: '+str(target))
        if source.exists():
            with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as src:
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
            target.chmod(0o600)
    for relative in result['source_sha256']:
        target=dest/'source'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/relative,target)
    for relative in ('ingestion/state.json','ingestion/last-run.json'):
        source=root/relative
        if source.exists():
            target=dest/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
            target.chmod(0o600)
    (dest/'checkpoint.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Private source/database checkpoint saved:',dest)
    print('Recordings, credentials and Open WebUI volumes are NOT backed up by this helper.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.home()/'ai-platform')
    p.add_argument('--snapshot',type=Path)
    args=p.parse_args()
    root=args.root.expanduser().resolve()
    result=inspect(root)
    print(json.dumps(result,indent=2))
    if not result['idle']:
        print('WAIT: processing/review work is active. Old waiting_upload sessions do not block this check.')
        return 2
    print('Tracked queues are idle. Check separate candidate terminals and ingestion service before shutdown.')
    if args.snapshot:
        snapshot(root,args.snapshot,result)
    return 0

if __name__=='__main__':
    raise SystemExit(main())

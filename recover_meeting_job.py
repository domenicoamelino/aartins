#!/usr/bin/env python3
"""Recover a failed writing job using its existing transcript and checked caches."""
import argparse
import json
import os
from pathlib import Path
import meeting_worker as w


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('job_id')
    args = p.parse_args()
    job = w.get_job(args.job_id)
    if not job or job['state'] != 'failed' or not job['folder']:
        p.error('Job must exist and be in failed state')
    folder = Path(job['folder'])
    candidates = list((folder / 'analysis').glob('*/manifest.json'))
    if not candidates:
        p.error('No analysis archive found; no changes made')
    previous = max(candidates, key=lambda x: x.stat().st_mtime).parent
    meta = json.loads((previous / 'manifest.json').read_text())
    command = [str(folder / 'transcript.json'), '--resume', str(previous),
               '--archive-root', str(folder / 'analysis'), '--model', meta['model'],
               '--language', meta['language'], '--context', str(meta['context']),
               '--output-tokens', str(meta['output_tokens']),
               '--timeout', os.environ.get('REPORT_TIMEOUT', '1200'),
               '--url', os.environ.get('REPORT_OLLAMA_URL', 'http://127.0.0.1:11434')]
    if meta.get('title'):
        command += ['--title', meta['title']]
    if meta.get('meeting_date'):
        command += ['--meeting-date', meta['meeting_date']]
    print('Resuming checked analysis from:', previous, flush=True)
    # Leave state failed until a complete report is safely published. The worker
    # only claims queued jobs, so it cannot claim this recovery concurrently.
    archive = w.report.run(w.report.parser().parse_args(command))
    for name in ('report.md', 'transcript.md', 'source.json', 'findings.json'):
        w.report.atomic(folder / name, (archive / name).read_text(encoding='utf-8'))
    w.update(job['id'], state='completed', detail='Report recovered and full transcript saved', percent=100, error=None)
    print('Recovered report:', folder / 'report.md')


if __name__ == '__main__':
    main()

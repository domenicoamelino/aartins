"""Optional offline diarization subprocess and conservative segment alignment.

Standard library only: imported by the existing transcription environment.
"""
import copy
from bisect import bisect_left, bisect_right
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid


LABEL = re.compile(r'SPEAKER_\d{2,4}\Z')


class Interrupted(RuntimeError):
    pass


def options(metadata):
    enabled = metadata.get('diarization_enabled', False)
    count = metadata.get('speaker_count')
    if type(enabled) is not bool:
        raise ValueError('Identify different speakers must be true or false')
    if count is not None and (type(count) is not int or not 1 <= count <= 20):
        raise ValueError('Known speaker count must be an integer from 1 to 20, or blank')
    if count is not None and not enabled:
        raise ValueError('Enable speaker identification before supplying a speaker count')
    return {'diarization_enabled': enabled, 'speaker_count': count}


def validate_result(data, duration):
    if not isinstance(data, dict) or data.get('schema') != 'meeting-diarization/2.5.2':
        raise ValueError('Invalid diarization schema')
    if data.get('status') != 'completed':
        raise ValueError('Incomplete diarization result')
    for key in ('turns', 'exclusive_turns'):
        rows = data.get(key)
        if not isinstance(rows, list) or len(rows) > 200000:
            raise ValueError('Invalid diarization turns')
        previous = -1.0
        previous_end = -1.0
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Invalid speaker turn')
            start, end, label = row.get('start'), row.get('end'), row.get('speaker')
            if (any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end))
                    or not 0 <= start < end <= duration + 1 or start < previous
                    or not isinstance(label, str) or not LABEL.fullmatch(label)):
                raise ValueError('Invalid speaker label or timestamps')
            if key == 'exclusive_turns' and start < previous_end - 0.001:
                raise ValueError('Exclusive turns overlap')
            previous, previous_end = start, end
    return data


def _union(intervals):
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def align(segments, turns):
    """Preserve text/times; label only segments dominated by one voice.

    Coverage is a time-overlap heuristic, never a model confidence score.
    """
    output = copy.deepcopy(segments)
    ordered = sorted(turns, key=lambda turn: turn['start'])
    starts = [turn['start'] for turn in ordered]
    ends = []
    maximum = 0.0
    for turn in ordered:
        maximum = max(maximum, turn['end'])
        ends.append(maximum)
    for segment in output:
        start, end = segment['start'], segment['end']
        width = end - start
        by_speaker = {}
        # Restrict scanning to turns that can intersect this ASR segment.
        for turn in ordered[bisect_right(ends, start):bisect_left(starts, end)]:
            a, b = max(start, turn['start']), min(end, turn['end'])
            if a < b:
                by_speaker.setdefault(turn['speaker'], []).append((a, b))
        by_speaker = {label: _union(intervals) for label, intervals in by_speaker.items()}
        coverage = {label: sum(b - a for a, b in intervals) / width
                    for label, intervals in by_speaker.items()} if width > 0 else {}
        ranked = sorted(coverage, key=lambda label: (-coverage[label], label))
        overlapping = False
        for index, label in enumerate(ranked):
            for other in ranked[index + 1:]:
                simultaneous = sum(max(0, min(b, d) - max(a, c))
                                   for a, b in by_speaker[label] for c, d in by_speaker[other])
                if simultaneous > 0.05:
                    overlapping = True
        if overlapping:
            speaker, status = None, 'overlap'
        elif ranked and coverage[ranked[0]] >= 0.8 and (len(ranked) == 1 or coverage[ranked[1]] <= 0.1):
            speaker, status = ranked[0], 'assigned'
        else:
            speaker, status = None, 'mixed' if len(ranked) > 1 else 'uncertain'
        segment.update(speaker=speaker, speaker_status=status,
                       speaker_candidates=ranked,
                       speaker_coverage={label: round(value, 4) for label, value in coverage.items()})
    return output


def _stop_child(process):
    if process.poll() is not None:
        return
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()


def align_words(segments, turns, exclusive_turns):
    """Split only on actual ASR words. Preserve raw text and source provenance.

    Exclusive diarization selects a probable voice; raw overlap remains visible,
    rather than disqualifying a whole multi-second ASR segment.
    """
    output = []
    ordered = sorted(exclusive_turns, key=lambda row: row['start'])
    starts = [row['start'] for row in ordered]
    for source_index, source in enumerate(segments, 1):
        words = source.get('words') or []
        if not words or ''.join(word['word'] for word in words).strip() != source['text'].strip():
            fallback = align([source], turns)[0]
            fallback.update(source_asr_segment=f'A{source_index:06d}', alignment='segment-fallback')
            output.append(fallback)
            continue
        group = None
        for index, word in enumerate(words):
            start, end = word['start'], word['end']
            width = end-start
            coverage = {}
            left = max(0, bisect_right(starts, start)-1)
            right = bisect_left(starts, end)
            for turn in ordered[left:right]:
                overlap = max(0, min(end, turn['end'])-max(start, turn['start']))
                if overlap:
                    coverage[turn['speaker']] = coverage.get(turn['speaker'], 0)+overlap
            ranked = sorted(coverage, key=lambda label: (-coverage[label], label))
            label = ranked[0] if ranked and width > 0 and coverage[ranked[0]]/width >= 0.6 and (
                len(ranked)==1 or (coverage[ranked[0]]-coverage[ranked[1]])/width >= 0.2) else None
            raw_candidates = {turn['speaker'] for turn in turns if turn['start']<end and turn['end']>start}
            overlap_estimate = len(raw_candidates)>1
            status = ('estimated_overlap' if overlap_estimate else 'assigned') if label else 'uncertain'
            uncertain = bool(word.get('probability', 1) < 0.5)
            if group is None or group['speaker']!=label or group['speaker_status']!=status or end-group['start']>15:
                group = {'start': start, 'end': end, 'text': '', 'words': [], 'speaker': label,
                         'speaker_status': status, 'asr_uncertain': False,
                         'source_asr_segment': f'A{source_index:06d}', 'alignment': 'word-timestamps'}
                output.append(group)
            group['end'] = end
            group['text'] += word['word']
            group['words'].append(copy.deepcopy(word))
            group['asr_uncertain'] = group['asr_uncertain'] or uncertain
    return output


def run(audio, folder, metadata, duration, stop, progress):
    """Return completed results or raise; caller handles fallback publication."""
    opts = options(metadata)
    base = Path.home() / 'ai-platform/diarization-benchmark'
    python = Path(os.environ.get('DIARIZATION_PYTHON', str(base / '.venv/bin/python'))).expanduser()
    script = Path(os.environ.get('DIARIZATION_SCRIPT', str(base / 'diarize_meeting.py'))).expanduser()
    if not python.is_file() or not script.is_file():
        raise RuntimeError('Diarization environment or runner is missing')
    threads = int(os.environ.get('DIARIZATION_THREADS', '4'))
    timeout = int(os.environ.get('DIARIZATION_TIMEOUT_SECONDS', '14400'))
    if not 1 <= threads <= 16 or not 1 <= timeout <= 86400:
        raise ValueError('Invalid diarization threads or timeout')
    folder = Path(folder)
    pending = folder / ('diarization-pending-' + uuid.uuid4().hex + '.json')
    command = [str(python), str(script), '--audio', str(audio), '--output', str(pending), '--threads', str(threads)]
    if opts['speaker_count'] is not None:
        command += ['--speakers', str(opts['speaker_count'])]
    env = os.environ.copy()
    # Do not forward API credentials or a user-defined module path to the child.
    for key in list(env):
        if key.endswith(('_TOKEN', '_API_KEY')) or key in ('PYTHONPATH', 'PYTHONHOME'):
            env.pop(key)
    env.update(HF_HOME=str(base / 'hf-cache'), HF_HUB_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', PYANNOTE_METRICS_ENABLED='0',
               OMP_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads), OPENBLAS_NUM_THREADS=str(threads))
    started = time.monotonic()
    process = None
    try:
        with (folder / 'diarization.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                                       start_new_session=(os.name == 'posix'))
            while process.poll() is None:
                if stop.wait(1):
                    raise Interrupted('Worker shutdown requested')
                elapsed = time.monotonic() - started
                if elapsed > timeout:
                    raise TimeoutError('Diarization exceeded its time limit')
                progress(f'Identifying speakers on CPU; {int(elapsed)} seconds elapsed')
            if process.returncode != 0:
                raise RuntimeError('Diarization runner failed; see diarization.log')
        if stop.is_set():
            raise Interrupted('Worker shutdown requested')
        if not pending.is_file() or pending.stat().st_size > 32 * 1024 * 1024:
            raise ValueError('Diarization result missing or too large')
        data = validate_result(json.loads(pending.read_text(encoding='utf-8')), duration)
        data['elapsed_worker_seconds'] = time.monotonic() - started
        return data
    finally:
        if process is not None:
            _stop_child(process)
        pending.unlink(missing_ok=True)
        pending.with_suffix('.tmp').unlink(missing_ok=True)

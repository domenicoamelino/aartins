#!/usr/bin/env python3
"""Offline CPU helper, run only by the separate diarization virtual environment."""
import argparse
from importlib.metadata import version
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--speakers', type=int)
    args = parser.parse_args()
    if not 1 <= args.threads <= 16 or (args.speakers is not None and not 1 <= args.speakers <= 20):
        parser.error('Invalid thread or speaker count')
    os.umask(0o077)
    os.environ['HF_HOME'] = str(Path.home() / 'ai-platform/diarization-benchmark/hf-cache')
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['PYANNOTE_METRICS_ENABLED'] = '0'
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ[name] = str(args.threads)
    import resource
    import torch
    import torchaudio
    from pyannote.audio import Pipeline
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    started = time.perf_counter()
    model = 'pyannote/speaker-diarization-community-1'
    pipeline = Pipeline.from_pretrained(model, token=False)
    pipeline.to(torch.device('cpu'))
    loaded = time.perf_counter()
    waveform, rate = torchaudio.load(str(args.audio))
    waveform = waveform.mean(dim=0, keepdim=True)
    if rate != 16000:
        waveform = torchaudio.functional.resample(waveform, rate, 16000)
    duration = waveform.shape[1] / 16000
    decoded = time.perf_counter()
    kwargs = {} if args.speakers is None else {'num_speakers': args.speakers}
    with torch.inference_mode():
        result = pipeline({'waveform': waveform, 'sample_rate': 16000}, **kwargs)
    inferred = time.perf_counter()
    def rows(annotation):
        return sorted([{'start': float(turn.start), 'end': float(turn.end), 'speaker': str(speaker)}
                       for turn, speaker in annotation], key=lambda row: (row['start'], row['end'], row['speaker']))
    revision = Path(os.environ['HF_HOME']) / 'hub/models--pyannote--speaker-diarization-community-1/refs/main'
    payload = {'schema': 'meeting-diarization/2.5.2', 'status': 'completed', 'model': model,
               'model_revision': revision.read_text().strip() if revision.exists() else None,
               'audio_seconds': duration, 'threads': args.threads, 'requested_speaker_count': args.speakers,
               'model_load_seconds': loaded - started, 'decode_seconds': decoded - loaded,
               'inference_seconds': inferred - decoded,
               'peak_process_memory_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
               'versions': {name: version(name) for name in ('pyannote.audio', 'torch', 'torchaudio', 'torchcodec')},
               'turns': rows(result.speaker_diarization),
               'exclusive_turns': rows(result.exclusive_speaker_diarization)}
    temporary = args.output.with_suffix('.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

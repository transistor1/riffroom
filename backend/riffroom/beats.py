"""Small, deterministic CPU beat tracker. Only a 100 Hz envelope stays in memory.

This is a practice aid, not a downbeat or meter detector. Sparse attacks, syncopation
and compound meter can produce half/double tempo estimates.
"""

import json
import math
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

VERSION = 1
ANALYZER_REVISION = 2


def validate_timeline(value):
    """Reject stale, malformed or non-finite cache data before exposing it."""
    if not isinstance(value, dict) or value.get("version") != VERSION:
        raise ValueError("Unsupported beat timeline")
    for key in ("bpm", "confidence"):
        if type(value.get(key)) not in (int, float) or not math.isfinite(value[key]):
            raise ValueError("Invalid beat metadata")
    beats = value.get("beats")
    if not isinstance(beats, list) or len(beats) > 10000:
        raise ValueError("Invalid beats")
    previous = -1.0
    for beat in beats:
        if type(beat) not in (int, float) or not math.isfinite(beat) or beat < 0 or beat <= previous:
            raise ValueError("Beats must be finite and increasing")
        previous = beat
    if not 0 <= value["confidence"] <= 1 or not 0 <= value["bpm"] <= 200:
        raise ValueError("Invalid beat metadata")
    if beats and (len(beats) < 2 or value["bpm"] < 55):
        raise ValueError("Invalid beat tempo")
    return value


def analyze_beats(path: Path):
    empty = {"version": VERSION, "bpm": 0.0, "confidence": 0.0, "beats": []}
    energies = []
    with sf.SoundFile(path) as audio:
        hop = max(1, round(audio.samplerate / 100))
        fps = audio.samplerate / hop
        duration = len(audio) / audio.samplerate
        # Stereo energy avoids cancellation of opposite-phase channels.
        for block in audio.blocks(blocksize=hop * 1000, dtype="float32", always_2d=True):
            block = block[:len(block) // hop * hop]
            if len(block):
                energies.extend(np.sqrt(np.mean(block.reshape(-1, hop, audio.channels) ** 2,
                                                axis=(1, 2))).tolist())
    energy = np.asarray(energies)
    if len(energy) < fps * 2 or np.max(energy, initial=0) < 1e-4:
        return empty
    # Positive energy change suppresses sustained notes; local normalization gives
    # quiet passages a vote without amplifying digital silence.
    onset = np.maximum(0, np.diff(energy, prepend=0))
    floor = max(1e-5, float(np.max(onset)) * 0.02)
    onset[onset < floor] = 0
    onset = np.sqrt(onset)
    norm = float(np.dot(onset, onset))
    if norm < 1e-8 or np.count_nonzero(onset) < 4:
        return empty
    lags = np.arange(math.ceil(60 * fps / 200), math.floor(60 * fps / 55) + 1)
    # Smooth over timing jitter without spreading attacks in the final timeline.
    smooth = np.convolve(onset, [0.25, 0.5, 1, 0.5, 0.25], mode="same")
    scores = np.array([np.dot(smooth[:-lag], smooth[lag:]) for lag in lags])
    best = int(np.argmax(scores))
    period = float(lags[best])
    # Seed phase from the opening beats; later tempo drift must not shift the
    # initial grid away from the opening attacks.
    phase_scores = [smooth[p:round(8 * period):round(period)].sum() for p in range(round(period))]
    phase = float(np.argmax(phase_scores))
    # A fast grid may follow eighth notes. Require both a competitive slower
    # correlation and consistent alternating strength before choosing half tempo.
    if 60 * fps / period > 110 and 60 * fps / (2 * period) >= 55:
        slower = np.flatnonzero(abs(lags - 2 * period) <= 2)
        slow_best = int(slower[np.argmax(scores[slower])])
        radius = max(2, round(period * 0.18))
        grid = [float(np.max(onset[max(0, p - radius):min(len(onset), p + radius + 1)]))
                for p in range(round(phase), len(onset), round(period))]
        pairs = np.asarray(grid[:len(grid) // 2 * 2]).reshape(-1, 2)
        if len(pairs) >= 4:
            means = pairs.mean(axis=0)
            strong = int(np.argmax(means))
            weak = 1 - strong
            if (scores[slow_best] >= 0.8 * scores[best]
                    and means[strong] > 1.25 * means[weak]
                    and np.mean(pairs[:, strong] > 1.15 * pairs[:, weak]) >= 0.7):
                phase += strong * period
                period = float(lags[slow_best])
    beats = []
    strengths = []
    predicted = phase
    while predicted < len(onset):
        radius = max(2, round(period * 0.22))
        lo, hi = max(0, round(predicted) - radius), min(len(onset), round(predicted) + radius + 1)
        indices = np.arange(lo, hi)
        weighted = onset[lo:hi] * (1 - 0.4 * np.abs(indices - predicted) / radius)
        peak = int(indices[np.argmax(weighted)])
        found = onset[peak] > 0
        aligned = float(peak) if found else predicted
        if beats:
            interval = aligned - beats[-1]
            if found and 0.65 * period < interval < 1.35 * period:
                period = float(np.clip(0.75 * period + 0.25 * interval, fps * 60 / 200, fps * 60 / 55))
        if found or beats:
            beats.append(aligned)
            strengths.append(found)
        predicted = aligned + period
    if len(beats) < 4:
        return empty
    confidence = float(np.mean(strengths))
    if confidence < 0.25:
        return empty
    return {"version": VERSION, "bpm": round(60 * fps / float(np.median(np.diff(beats))), 2),
            "confidence": round(confidence, 3),
            "beats": [round(b / fps, 4) for b in beats if b / fps < duration]}


def cached_beats(folder: Path):
    """Called in a worker thread; publish the cache with an atomic rename."""
    path = folder / "beats.json"
    try:
        cached = validate_timeline(json.loads(path.read_text()))
        if cached.get("analyzer_revision") == ANALYZER_REVISION:
            return cached
    except (OSError, ValueError, TypeError):
        pass
    timeline = validate_timeline(analyze_beats(folder / "original.wav"))
    timeline["analyzer_revision"] = ANALYZER_REVISION
    temporary = folder / f"beats-{uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps(timeline, allow_nan=False))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return timeline

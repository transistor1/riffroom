"""Decode once to sample-aligned stereo PCM; keep model and browser I/O simple."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

MAX_SECONDS = 20 * 60


def decode(source: Path, output: Path) -> float:
    if not shutil.which("ffmpeg"):
        raise ValueError("FFmpeg is missing. Install it with: brew install ffmpeg")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        raise ValueError("This file could not be read as audio. Try WAV, MP3, FLAC or M4A.") from None
    if not 0 < duration <= MAX_SECONDS:
        raise ValueError("Please use a track shorter than 20 minutes.")
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-t",
            str(MAX_SECONDS + 1),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise ValueError("FFmpeg couldn't decode this file. Try exporting it as WAV or FLAC.")
    info = sf.info(output)
    if info.duration > MAX_SECONDS:
        raise ValueError("Please use a track shorter than 20 minutes.")
    return info.duration


def waveform(path: Path, bins: int = 600) -> list[float]:
    info = sf.info(path)
    block = max(1, int(np.ceil(info.frames / bins)))
    values = []
    for samples in sf.blocks(path, blocksize=block, dtype="float32", always_2d=True):
        values.append(float(np.max(np.abs(samples))))
    peak = max(values, default=1) or 1
    return [round(x / peak, 4) for x in values]


def validate_stems(paths: dict[str, Path], original: Path):
    expected = sf.info(original)
    for name, path in paths.items():
        actual = sf.info(path)
        if (
            actual.frames != expected.frames
            or actual.samplerate != expected.samplerate
            or actual.channels != 2
        ):
            raise ValueError(f"The {name} stem isn't aligned with the source. No results were saved.")


def write_float_stem(output: Path, stem_path: str, samples):
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 2 and samples.shape[0] == 2 and samples.shape[1] > 2:
        samples = samples.T
    if not np.isfinite(samples).all():
        raise ValueError("The model produced invalid audio samples. Try another model.")
    # Float WAV preserves model amplitude, even above 0 dBFS; the player limits
    # the final mix instead of independently changing the stems' relative levels.
    sf.write(output / Path(stem_path).name, samples, 44100, subtype="FLOAT")

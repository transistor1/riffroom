"""Generate an original synthetic plucked-string/drum fixture, no music download."""

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=8)
parser.add_argument("--output", type=Path, default=Path("data/smoke/practice-check.wav"))
args = parser.parse_args()
sr = 44100
t = np.arange(int(sr * args.seconds)) / sr
rng = np.random.default_rng(42)
audio = np.zeros((len(t), 2))
for beat in np.arange(0, args.seconds, 0.5):
    u = np.maximum(0, t - beat)
    envelope = np.exp(-u * 5) * (t >= beat)
    note = 110 * 2 ** ([0, 3, 5, 7][int(beat * 2) % 4] / 12)
    guitar = sum(np.sin(2 * np.pi * note * h * u) / h**1.8 for h in range(1, 7)) * envelope * 0.15
    kick = np.sin(2 * np.pi * (55 * u + 4 * (1 - np.exp(-u * 30)))) * np.exp(-u * 20) * (t >= beat) * 0.12
    hat = rng.normal(0, 0.025, len(t)) * np.exp(-u * 75) * (t >= beat)
    audio[:, 0] += guitar + kick + hat
    audio[:, 1] += guitar * 0.85 + kick + hat * 0.8
args.output.parent.mkdir(parents=True, exist_ok=True)
sf.write(args.output, audio, sr, subtype="FLOAT")
print(args.output)

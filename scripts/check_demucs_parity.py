"""Compare cached MLX Demucs output with the original PyTorch implementation.

Run locally on Apple Silicon, e.g.:
.env/bin/python scripts/check_demucs_parity.py data/diagnostics/demucs/reference.wav
No files are uploaded. Input must be stereo 44.1 kHz WAV, as stored by Riffroom.
"""

import argparse
import json
import os
import random
from pathlib import Path

import numpy as np
import soundfile as sf

parser = argparse.ArgumentParser()
parser.add_argument("audio", type=Path)
parser.add_argument("--model", choices=["demucs-6", "demucs-ft"], default="demucs-6")
parser.add_argument("--seconds", type=float, default=8)
parser.add_argument("--output", type=Path, default=Path("data/diagnostics/demucs-parity"))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
cache = root / "data/models"
os.environ["TORCH_HOME"] = str(cache / "torch")
os.environ["XDG_CACHE_HOME"] = str(cache / "cache")

import torch  # noqa: E402
from demucs.apply import apply_model  # noqa: E402
from mlx_audio_separator.demucs_mlx.secure_demucs import get_restricted_demucs_model  # noqa: E402
from riffroom.models import MODELS  # noqa: E402
from riffroom.worker import run  # noqa: E402

samples, rate = sf.read(args.audio, frames=int(args.seconds * 44100), dtype="float32", always_2d=True)
if rate != 44100 or samples.shape[1] != 2:
    raise SystemExit("Use a stereo 44.1 kHz WAV input.")
args.output.mkdir(parents=True, exist_ok=True)
source = args.output / "input.wav"
sf.write(source, samples, rate, subtype="FLOAT")
run(source.resolve(), (args.output / "mlx").resolve(), cache, args.model)
profile = MODELS[args.model]
model = get_restricted_demucs_model(Path(profile.filename).stem)
wave = torch.from_numpy(samples.T.copy())
reference = wave.mean(0)
mean, std = reference.mean(), reference.std()
if std < 1e-8:
    raise SystemExit("Use a non-silent comparison clip.")
torch.set_num_threads(4)
torch.manual_seed(42)
random.seed(42)
with torch.inference_mode():
    output = (
        apply_model(
            model,
            ((wave - mean) / std)[None],
            device="cpu",
            shifts=1,
            split=True,
            overlap=0.25,
            progress=True,
        )[0]
        * std
        + mean
    )
report = {}
for name, tensor in zip(model.sources, output):
    expected = tensor.T.numpy()
    sf.write(args.output / f"torch-{name}.wav", expected, rate, subtype="FLOAT")
    actual, _ = sf.read(args.output / "mlx" / f"{name}.wav", dtype="float32")
    relative_error = float(np.linalg.norm(actual - expected) / max(np.linalg.norm(expected), 1e-8))
    report[name] = {"relative_l2_error": relative_error}
(args.output / "report.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if any(stem["relative_l2_error"] > 0.005 for stem in report.values()):
    raise SystemExit("FAIL: MLX differs from reference by more than 0.5%. Inspect outputs before publishing.")
print("PASS: every stem is within 0.5% relative L2 error of original Demucs.")

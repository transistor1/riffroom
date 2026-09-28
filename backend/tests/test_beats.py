import numpy as np
import pytest
import soundfile as sf
from riffroom.beats import analyze_beats, validate_timeline


def clicks(path, positions, duration=25):
    samples = np.zeros((int(duration * 44100), 2), dtype=np.float32)
    pulse = np.exp(-np.arange(441) / 65) * 0.8
    for position in positions:
        start = round(position * 44100)
        samples[start:start + len(pulse)] = pulse[:, None]
    sf.write(path, samples, 44100)


def test_regular_clicks(tmp_path):
    path = tmp_path / "original.wav"
    expected = np.arange(0.2, 24.8, 0.5)
    clicks(path, expected)
    timeline = analyze_beats(path)
    assert 117 < timeline["bpm"] < 123
    assert timeline["confidence"] > 0.8
    assert abs(len(timeline["beats"]) - len(expected)) <= 1
    assert np.max(np.min(abs(np.array(timeline["beats"])[:, None] - expected), axis=1)) < 0.03


def test_drift_is_locally_aligned(tmp_path):
    path = tmp_path / "original.wav"
    expected = np.r_[0.2, 0.2 + np.cumsum(np.linspace(0.52, 0.46, 48))]
    clicks(path, expected)
    timeline = analyze_beats(path)
    assert 110 < timeline["bpm"] < 135
    beats = np.array(timeline["beats"])
    assert abs(len(beats) - len(expected)) <= 2
    assert np.mean(np.min(abs(beats[:, None] - expected), axis=1) < 0.03) > 0.95
    assert np.std(np.diff(beats)) > 0.01


@pytest.mark.parametrize("amplitude", [0, 1e-6])
def test_silence(tmp_path, amplitude):
    path = tmp_path / "original.wav"
    sf.write(path, np.full((44100 * 3, 2), amplitude, dtype=np.float32), 44100)
    assert analyze_beats(path) == {"version": 1, "bpm": 0.0, "confidence": 0.0, "beats": []}


@pytest.mark.parametrize("beats", [[0.5, 0.4], [float("nan"), 1], [-1, 0], [0, float("inf")]])
def test_invalid_cache(beats):
    with pytest.raises(ValueError):
        validate_timeline({"version": 1, "bpm": 120, "confidence": 0.8, "beats": beats})

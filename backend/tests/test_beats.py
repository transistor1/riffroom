import numpy as np
import pytest
import soundfile as sf
from riffroom.beats import ANALYZER_REVISION, analyze_beats, cached_beats, validate_timeline


def clicks(path, positions, duration=25, amplitudes=None):
    samples = np.zeros((int(duration * 44100), 2), dtype=np.float32)
    pulse = np.exp(-np.arange(441) / 65) * 0.8
    for i, position in enumerate(positions):
        start = round(position * 44100)
        samples[start:start + len(pulse)] = pulse[:, None] * (1 if amplitudes is None else amplitudes[i])
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


@pytest.mark.parametrize("strong_parity", [0, 1])
def test_slow_beats_with_weaker_eighth_notes(tmp_path, strong_parity):
    path = tmp_path / "original.wav"
    positions = np.arange(0.2, 24.8, 60 / 130)
    amplitudes = np.where(np.arange(len(positions)) % 2 == strong_parity, 1.0, 0.4)
    clicks(path, positions, amplitudes=amplitudes)
    timeline = analyze_beats(path)
    assert 63 < timeline["bpm"] < 67
    expected = positions[strong_parity::2]
    beats = np.asarray(timeline["beats"])
    assert abs(len(beats) - len(expected)) <= 1
    assert np.max(np.min(abs(beats[:, None] - expected), axis=1)) < 0.03


def test_even_fast_pulse_is_not_halved(tmp_path):
    path = tmp_path / "original.wav"
    clicks(path, np.arange(0.2, 24.8, 60 / 130))
    assert 127 < analyze_beats(path)["bpm"] < 133


def test_old_analysis_cache_is_recomputed(tmp_path):
    (tmp_path / "beats.json").write_text(
        '{"version": 1, "bpm": 130, "confidence": 1, "beats": [0.2, 0.66]}'
    )
    clicks(tmp_path / "original.wav", np.arange(0.2, 24.8, 0.5))
    timeline = cached_beats(tmp_path)
    assert timeline["bpm"] == 120
    assert timeline["analyzer_revision"] == ANALYZER_REVISION
    assert cached_beats(tmp_path) == timeline


@pytest.mark.parametrize("amplitude", [0, 1e-6])
def test_silence(tmp_path, amplitude):
    path = tmp_path / "original.wav"
    sf.write(path, np.full((44100 * 3, 2), amplitude, dtype=np.float32), 44100)
    assert analyze_beats(path) == {"version": 1, "bpm": 0.0, "confidence": 0.0, "beats": []}


@pytest.mark.parametrize("beats", [[0.5, 0.4], [float("nan"), 1], [-1, 0], [0, float("inf")]])
def test_invalid_cache(beats):
    with pytest.raises(ValueError):
        validate_timeline({"version": 1, "bpm": 120, "confidence": 0.8, "beats": beats})

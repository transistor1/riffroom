import json
import shutil
from dataclasses import replace

import numpy as np
import pytest
import soundfile as sf
from riffroom import worker
from riffroom.models import CURATED_MODELS


def write_source(path, *, frames=8):
    samples = np.linspace(-0.5, 0.5, frames * 2, dtype=np.float32).reshape(frames, 2)
    sf.write(path, samples, 44100, subtype="FLOAT")


def test_worker_dispatches_paths_and_writes_unchanged_manifest(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.wav"
    output = tmp_path / "output"
    cache = tmp_path / "cache"
    write_source(source)
    profile = replace(
        CURATED_MODELS["demucs-6"],
        id="test-model",
        provider="test-provider",
        stems=("guitar",),
    )
    received = {}

    class FakeProvider:
        def separate(
            self,
            received_profile,
            received_source,
            received_output,
            received_cache,
            *,
            on_model_loaded,
        ):
            received.update(
                profile=received_profile,
                source=received_source,
                output=received_output,
                cache=received_cache,
                directories_exist=received_output.is_dir() and received_cache.is_dir(),
            )
            on_model_loaded()
            stem = received_output / "guitar.wav"
            shutil.copyfile(received_source, stem)
            return {"guitar": stem, "unused": received_output / "unused.wav"}

    monkeypatch.setattr(worker, "MODELS", {profile.id: profile})
    monkeypatch.setattr(worker, "waveform", lambda path: [0.25, 1.0])

    worker.run(source, output, cache, profile.id, {profile.provider: FakeProvider()})

    assert received == {
        "profile": profile,
        "source": source,
        "output": output,
        "cache": cache,
        "directories_exist": True,
    }
    assert json.loads((output / "stems.json").read_text()) == [
        {"name": "guitar", "file": "guitar.wav", "peaks": [0.25, 1.0]}
    ]
    messages = [
        json.loads(line.removeprefix("RIFFROOM:"))["message"] for line in capsys.readouterr().out.splitlines()
    ]
    assert messages == [
        "Loading model · first use downloads and converts the weights",
        "Separating instruments · this can take several minutes",
        "Preparing waveforms and playback",
        "Ready to practice",
    ]


def test_worker_still_validates_provider_stems_before_manifest(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    output = tmp_path / "output"
    cache = tmp_path / "cache"
    write_source(source, frames=8)
    profile = replace(
        CURATED_MODELS["demucs-6"],
        id="test-model",
        provider="test-provider",
        stems=("guitar",),
    )

    class MisalignedProvider:
        def separate(self, profile, source, output, cache, *, on_model_loaded):
            on_model_loaded()
            stem = output / "guitar.wav"
            write_source(stem, frames=4)
            return {"guitar": stem}

    monkeypatch.setattr(worker, "MODELS", {profile.id: profile})

    with pytest.raises(ValueError, match="isn't aligned with the source"):
        worker.run(source, output, cache, profile.id, {profile.provider: MisalignedProvider()})

    assert not (output / "stems.json").exists()


def test_worker_rejects_a_missing_expected_stem(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    write_source(source)
    profile = replace(
        CURATED_MODELS["demucs-6"],
        id="test-model",
        provider="test-provider",
        stems=("guitar",),
    )

    class MissingStemProvider:
        def separate(self, profile, source, output, cache, *, on_model_loaded):
            on_model_loaded()
            return {}

    monkeypatch.setattr(worker, "MODELS", {profile.id: profile})

    with pytest.raises(ValueError, match="expected guitar stem"):
        worker.run(
            source,
            tmp_path / "output",
            tmp_path / "cache",
            profile.id,
            {profile.provider: MissingStemProvider()},
        )

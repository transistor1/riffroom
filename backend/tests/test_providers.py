import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from riffroom.models import CURATED_MODELS
from riffroom.providers import get_provider
from riffroom.providers.mlx import MlxAudioSeparatorProvider


def test_trusted_mlx_provider_resolves():
    provider = get_provider("mlx-audio-separator")

    assert isinstance(provider, MlxAudioSeparatorProvider)


def test_unknown_provider_fails_closed():
    with pytest.raises(ValueError, match="^Unknown separation provider: untrusted-runtime$"):
        get_provider("untrusted-runtime")


def test_mlx_provider_preserves_runtime_configuration(tmp_path, monkeypatch):
    output = tmp_path / "output"
    cache = tmp_path / "cache"
    output.mkdir()
    cache.mkdir()
    source = tmp_path / "source.wav"
    source.touch()
    profile = replace(CURATED_MODELS["demucs-6"], stems=("guitar",))
    calls = []
    captured = {}

    class FakeSeparator:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.model_instance = SimpleNamespace()
            calls.append("constructed")

        def load_model(self, filename):
            captured["filename"] = filename
            calls.append("loaded")

        def separate(self, source_path, *, custom_output_names):
            captured["source"] = source_path
            captured["names"] = custom_output_names
            self.model_instance.write_audio("GUITAR.wav", "samples")
            (output / "GUITAR.wav").touch()
            calls.append("separated")

    configured = []
    writes = []
    monkeypatch.setattr("riffroom.providers.mlx.LocalSeparator", FakeSeparator)
    monkeypatch.setattr("riffroom.providers.mlx.configure_demucs_cache", configured.append)
    monkeypatch.setattr(
        "riffroom.providers.mlx.write_float_stem",
        lambda output_path, stem_path, samples: writes.append((output_path, stem_path, samples)),
    )

    paths = MlxAudioSeparatorProvider().separate(
        profile,
        source,
        output,
        cache,
        on_model_loaded=lambda: calls.append("notified"),
    )

    assert configured == [cache]
    assert captured["kwargs"] == {
        "log_level": logging.INFO,
        "model_file_dir": str(cache),
        "output_dir": str(output),
        "output_format": "WAV",
        "normalization_threshold": 1.0,
        "amplification_threshold": 0.0,
        "save_converted_safetensors": True,
        "demucs_params": {
            "segment_size": "Default",
            "shifts": 1,
            "overlap": 0.25,
            "segments_enabled": True,
            "batch_size": 1,
            "seed": 42,
        },
        "mdxc_params": {
            "segment_size": 256,
            "override_model_segment_size": False,
            "batch_size": 1,
            "overlap": 2,
            "pitch_shift": 0,
        },
    }
    assert captured["filename"] == profile.filename
    assert captured["source"] == str(source)
    assert captured["names"] == {"guitar": "guitar"}
    assert writes == [(output, "GUITAR.wav", "samples")]
    assert calls == ["constructed", "loaded", "notified", "separated"]
    assert paths == {"guitar": output / "guitar.wav"}
    assert (output / "guitar.wav").is_file()

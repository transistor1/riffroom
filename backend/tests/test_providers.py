import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from riffroom.models import CURATED_MODELS
from riffroom.providers import get_provider, is_provider_available
from riffroom.providers.audio_separator import AudioSeparatorCliProvider
from riffroom.providers.mlx import MlxAudioSeparatorProvider


def test_trusted_mlx_provider_resolves():
    provider = get_provider("mlx-audio-separator")

    assert isinstance(provider, MlxAudioSeparatorProvider)
    assert is_provider_available("mlx-audio-separator") is True


def test_trusted_audio_separator_provider_resolves():
    provider = get_provider("audio-separator")

    assert isinstance(provider, AudioSeparatorCliProvider)


def test_unknown_provider_fails_closed():
    with pytest.raises(ValueError, match="^Unknown separation provider: untrusted-runtime$"):
        get_provider("untrusted-runtime")

    with pytest.raises(ValueError, match="^Unknown separation provider: untrusted-runtime$"):
        is_provider_available("untrusted-runtime")


def test_audio_separator_configured_executable_wins_over_path(tmp_path):
    executable = tmp_path / "managed-audio-separator"
    executable.touch(mode=0o755)
    calls = []

    def unexpected_resolver(name):
        raise AssertionError(f"PATH resolver should not be called for {name}")

    provider = AudioSeparatorCliProvider(
        environ={"RIFFROOM_AUDIO_SEPARATOR_BIN": str(executable)},
        executable_resolver=unexpected_resolver,
        runner=lambda argv, **kwargs: calls.append(argv) or SimpleNamespace(returncode=0),
    )

    assert provider.is_available() is True
    provider.separate(
        CURATED_MODELS["demucs-6"],
        tmp_path / "source.wav",
        tmp_path,
        tmp_path / "cache",
        on_model_loaded=lambda: None,
    )
    assert calls[0][0] == str(executable)


def test_audio_separator_discovers_default_executable_from_path():
    looked_up = []
    provider = AudioSeparatorCliProvider(
        environ={},
        executable_resolver=lambda name: looked_up.append(name) or "/managed/audio-separator",
    )

    assert provider.is_available() is True
    assert looked_up == ["audio-separator"]


def test_audio_separator_unavailable_runtime_fails_clearly(tmp_path):
    notified = []
    provider = AudioSeparatorCliProvider(environ={}, executable_resolver=lambda name: None)

    assert provider.is_available() is False
    with pytest.raises(
        RuntimeError,
        match="portable audio-separator runtime is not installed/configured",
    ):
        provider.separate(
            CURATED_MODELS["demucs-6"],
            tmp_path / "source.wav",
            tmp_path / "output",
            tmp_path / "cache",
            on_model_loaded=lambda: notified.append(True),
        )
    assert notified == []


def test_audio_separator_cli_contract_and_normalized_outputs(tmp_path):
    source = tmp_path / "source.wav"
    output = tmp_path / "output"
    cache = tmp_path / "cache"
    source.touch()
    output.mkdir()
    cache.mkdir()
    profile = replace(CURATED_MODELS["demucs-6"], stems=("guitar", "other"))
    calls = []
    captured = {}

    def fake_runner(argv, **kwargs):
        calls.append("runner")
        captured.update(argv=argv, kwargs=kwargs)
        (output / "GUITAR.wav").touch()
        (output / "other.wav").touch()
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    provider = AudioSeparatorCliProvider(
        environ={},
        executable_resolver=lambda name: "/managed/audio-separator",
        runner=fake_runner,
    )
    paths = provider.separate(
        profile,
        source,
        output,
        cache,
        on_model_loaded=lambda: calls.append("notified"),
    )

    assert calls == ["notified", "runner"]
    assert captured["kwargs"] == {"check": False, "shell": False}
    argv = captured["argv"]
    assert argv[:2] == ["/managed/audio-separator", str(source)]
    assert argv[argv.index("--model_filename") + 1] == profile.filename
    assert argv[argv.index("--output_dir") + 1] == str(output)
    assert argv[argv.index("--model_file_dir") + 1] == str(cache)
    assert argv[argv.index("--output_format") + 1] == "WAV"
    assert argv[argv.index("--normalization_threshold") + 1] == "1.0"
    assert argv[argv.index("--amplification_threshold") + 1] == "0.0"
    assert "--use_soundfile" in argv
    assert json.loads(argv[argv.index("--custom_output_names") + 1]) == {
        "guitar": "guitar",
        "other": "other",
    }
    assert paths == {"guitar": output / "guitar.wav", "other": output / "other.wav"}
    assert (output / "guitar.wav").is_file()


def test_audio_separator_nonzero_exit_has_bounded_actionable_error(tmp_path):
    provider = AudioSeparatorCliProvider(
        environ={},
        executable_resolver=lambda name: "/managed/audio-separator",
        runner=lambda argv, **kwargs: SimpleNamespace(
            returncode=17,
            stderr="diagnostic " * 1_000,
            stdout=None,
        ),
    )

    with pytest.raises(RuntimeError) as raised:
        provider.separate(
            CURATED_MODELS["demucs-6"],
            tmp_path / "source.wav",
            tmp_path / "output",
            tmp_path / "cache",
            on_model_loaded=lambda: None,
        )

    message = str(raised.value)
    assert "exit code 17" in message
    assert "worker log" in message
    assert len(message) < 650


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

import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest
from riffroom.models import CURATED_MODELS
from riffroom.providers import get_provider, is_provider_available
from riffroom.providers.audio_separator import AudioSeparatorCliProvider
from riffroom.providers.base import (
    MAX_STEM_NAME,
    completed_stem_paths,
    custom_output_names,
    normalized_stem_paths,
    restricted_output_path,
)
from riffroom.providers.mlx import MlxAudioSeparatorProvider, MlxRuntimeUnavailableError


def test_trusted_mlx_provider_resolves():
    provider = get_provider("mlx-audio-separator")

    assert isinstance(provider, MlxAudioSeparatorProvider)
    assert is_provider_available("mlx-audio-separator") is provider.is_available()


def test_trusted_audio_separator_provider_resolves():
    provider = get_provider("audio-separator")

    assert isinstance(provider, AudioSeparatorCliProvider)


def test_mlx_provider_unavailable_runtime_fails_clearly(tmp_path, monkeypatch):
    notified = []

    def unavailable_runtime():
        raise MlxRuntimeUnavailableError("optional MLX runtime unavailable")

    monkeypatch.setattr("riffroom.providers.mlx._load_runtime", unavailable_runtime)
    provider = MlxAudioSeparatorProvider()

    assert provider.is_available() is False
    with pytest.raises(MlxRuntimeUnavailableError, match="optional MLX runtime unavailable"):
        provider.separate(
            CURATED_MODELS["demucs-6"],
            CURATED_MODELS["demucs-6"].variants[0],
            tmp_path / "source.wav",
            tmp_path / "output",
            tmp_path / "cache",
            on_model_loaded=lambda: notified.append(True),
        )
    assert notified == []


def test_unknown_provider_fails_closed():
    with pytest.raises(ValueError, match="^Unknown separation provider: untrusted-runtime$"):
        get_provider("untrusted-runtime")

    with pytest.raises(ValueError, match="^Unknown separation provider: untrusted-runtime$"):
        is_provider_available("untrusted-runtime")


def test_audio_separator_configured_executable_wins_over_path(tmp_path):
    executable = tmp_path / "managed-audio-separator"
    executable.touch(mode=0o755)
    for name in CURATED_MODELS["demucs-6"].stems:
        (tmp_path / f"{name}.wav").touch()
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
        CURATED_MODELS["demucs-6"].variants[1],
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
            CURATED_MODELS["demucs-6"].variants[1],
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
        profile.variants[1],
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
    # audio-separator 0.47.0's Python API uses the *_threshold names, but its
    # CLI exposes the shorter option names. Passing the API names exits 2
    # during argument parsing before the model can load.
    assert argv[argv.index("--normalization") + 1] == "1.0"
    assert argv[argv.index("--amplification") + 1] == "0.0"
    assert "--normalization_threshold" not in argv
    assert "--amplification_threshold" not in argv
    assert "--use_soundfile" in argv
    # audio-separator 0.47.0 has no CUDA CLI flag. Its Separator selects CUDA
    # from torch.cuda.is_available() and otherwise keeps this same command on CPU.
    assert "--device" not in argv
    assert "--use_cuda" not in argv
    assert json.loads(argv[argv.index("--custom_output_names") + 1]) == {
        "guitar": "guitar",
        "other": "other",
    }
    assert paths == {"guitar": output / "guitar.wav", "other": output / "other.wav"}
    assert (output / "guitar.wav").is_file()


@pytest.mark.parametrize(
    "upstream_filename",
    [
        "OTHER.wav",
        "original_(other)_vocals_mel_band_roformer.wav",
        "OrIgInAl_(OtHeR)_VoCaLs_MeL_BaNd_RoFoRmEr.WAV",
    ],
)
def test_audio_separator_uses_kimberley_other_alias_for_logical_instrumental(tmp_path, upstream_filename):
    source = tmp_path / "original.wav"
    output = tmp_path / "output"
    cache = tmp_path / "cache"
    source.touch()
    output.mkdir()
    cache.mkdir()
    profile = CURATED_MODELS["roformer-vocals"]
    variant = profile.variants[1]
    captured = {}

    def fake_runner(argv, **kwargs):
        captured["names"] = json.loads(argv[argv.index("--custom_output_names") + 1])
        (output / "vocals.wav").touch()
        # Some upstream versions ignore the custom logical output name.
        (output / upstream_filename).touch()
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    provider = AudioSeparatorCliProvider(
        environ={},
        executable_resolver=lambda name: "/managed/audio-separator",
        runner=fake_runner,
    )
    paths = provider.separate(
        profile,
        variant,
        source,
        output,
        cache,
        on_model_loaded=lambda: None,
    )

    assert captured["names"] == {"other": "instrumental", "vocals": "vocals"}
    assert paths == {
        "vocals": output / "vocals.wav",
        "instrumental": output / "instrumental.wav",
    }
    assert (output / "instrumental.wav").is_file()


@pytest.mark.parametrize(
    "upstream_filename",
    ["other.wav", "original_(other)_vocals_mel_band_roformer.wav"],
)
def test_mlx_normalizes_kimberley_alias_and_requests_logical_names(tmp_path, monkeypatch, upstream_filename):
    output = tmp_path / "output"
    output.mkdir()
    profile = CURATED_MODELS["roformer-vocals"]
    captured = {}

    class FakeSeparator:
        def __init__(self, **kwargs):
            self.model_instance = SimpleNamespace()

        def load_model(self, filename):
            assert filename == profile.filename

        def separate(self, source, *, custom_output_names):
            captured.update(custom_output_names)
            (output / "vocals.wav").write_bytes(b"vocals")
            (output / upstream_filename).write_bytes(b"backing")

    monkeypatch.setattr("riffroom.providers.mlx._load_runtime", lambda: SimpleNamespace(
        LocalSeparator=FakeSeparator, configure_demucs_cache=lambda _: None
    ))
    paths = MlxAudioSeparatorProvider().separate(
        profile, profile.variants[0], tmp_path / "original.wav", output, tmp_path / "cache",
        on_model_loaded=lambda: None,
    )
    assert captured == {"vocals": "vocals", "other": "instrumental"}
    assert paths == {name: output / f"{name}.wav" for name in profile.stems}
    assert paths["instrumental"].read_bytes() == b"backing"


def test_audio_separator_nonzero_exit_has_bounded_actionable_error(tmp_path):
    (tmp_path / "output").mkdir()
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
            CURATED_MODELS["demucs-6"].variants[1],
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
    runtime = SimpleNamespace(
        LocalSeparator=FakeSeparator,
        configure_demucs_cache=configured.append,
    )
    monkeypatch.setattr("riffroom.providers.mlx._load_runtime", lambda: runtime)
    monkeypatch.setattr(
        "riffroom.providers.mlx.write_float_stem",
        lambda output_path, stem_path, samples: writes.append((output_path, stem_path, samples)),
    )

    paths = MlxAudioSeparatorProvider().separate(
        profile,
        profile.variants[0],
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


def test_normalizer_matches_whole_trusted_tokens_with_overlapping_names(tmp_path):
    stems = ("guitar", "electric-guitar", "no vocals", "vocals", "other")
    filenames = (
        "a_(vocals)_song_(guitar)_arbitrary_model.wav",
        "a_(vocals)_song_(ELECTRIC-GUITAR)_arbitrary_model.WAV",
        "No Vocals.WAV",
        "vocals.wav",
        "a_(vocals)_song_(other)_arbitrary_model.wav",
    )
    for name, filename in zip(stems, filenames, strict=True):
        (tmp_path / filename).write_text(name)
    unrelated = tmp_path / "electric_guitar_vocals_arbitrary_model.wav"
    unrelated.write_text("unrelated")

    paths = normalized_stem_paths(
        stems, tmp_path, source=tmp_path / "a_(vocals)_song.wav", model_filename="arbitrary_model.ckpt"
    )

    assert paths == {name: tmp_path / f"{name}.wav" for name in stems}
    assert {name: path.read_text() for name, path in paths.items()} == {name: name for name in stems}
    assert unrelated.read_text() == "unrelated"


def test_normalizer_prefers_exact_logical_names_and_preserves_other_files(tmp_path):
    filenames = (
        "vocals.wav", "instrumental.wav", "other.wav",
        "original_(other)_model.wav", "original_(instrumental)_model.wav", "notes.txt",
    )
    for filename in filenames:
        (tmp_path / filename).write_text(filename)

    paths = normalized_stem_paths(
        ("vocals", "instrumental"), tmp_path, output_aliases=(("other", "instrumental"),),
        source=tmp_path / "original.wav", model_filename="model.ckpt",
    )

    assert paths["instrumental"].read_text() == "instrumental.wav"
    assert {path.name: path.read_text() for path in tmp_path.iterdir()} == {
        filename: filename for filename in filenames
    }


@pytest.mark.parametrize(
    "filenames",
    [
        ("other.wav", "original_(other)_model.wav"),
        ("INSTRUMENTAL.WAV", "original_(instrumental)_model.wav"),
        ("original_(other)_model.wav", "original_(instrumental)_model.wav"),
    ],
)
def test_normalizer_rejects_multiple_candidates_before_any_rename(tmp_path, filenames):
    for filename in ("VOCALS.WAV", *filenames):
        (tmp_path / filename).write_text(filename)

    with pytest.raises(ValueError, match="ambiguous 'instrumental'") as raised:
        normalized_stem_paths(
            ("vocals", "instrumental"), tmp_path, output_aliases=(("other", "instrumental"),),
            source=tmp_path / "original.wav", model_filename="model.ckpt",
        )

    assert "Expected stems: vocals, instrumental" in str(raised.value)
    assert "Observed files:" in str(raised.value)
    for filename in ("VOCALS.WAV", *filenames):
        assert filename in str(raised.value)
        assert (tmp_path / filename).read_text() == filename


@pytest.mark.parametrize(
    "filename",
    [
        "original_other_model.wav",
        "original_(some other)_model.wav",
        "original_(other vocals)_model.wav",
        "original_((other))_model.wav",
        "original_(other)_wrong_model.wav",
        "wrong_source_(other)_model.wav",
        "original_(other)_model_extra.wav",
        "original_(other)_model.wav.bak",
        "original_(other)_model.mp3",
        "original_(instrumental remix)_model.wav",
        "instrumental_model.wav",
    ],
)
def test_normalizer_does_not_guess_from_arbitrary_words_or_wrong_context(tmp_path, filename):
    (tmp_path / "VOCALS.wav").touch()
    (tmp_path / filename).write_text("unrelated")

    with pytest.raises(ValueError, match="missing 'instrumental'") as raised:
        normalized_stem_paths(
            ("vocals", "instrumental"), tmp_path, output_aliases=(("other", "instrumental"),),
            source=tmp_path / "original.wav", model_filename="model.ckpt",
        )

    assert filename in str(raised.value)
    assert (tmp_path / filename).read_text() == "unrelated"
    assert {path.name for path in tmp_path.iterdir()} == {"VOCALS.wav", filename}


def test_normalizer_requires_trusted_alias_and_decorated_context(tmp_path):
    candidate = tmp_path / "original_(other)_model.wav"
    candidate.touch()
    with pytest.raises(ValueError, match="missing 'instrumental'"):
        normalized_stem_paths(
            ("instrumental",), tmp_path, source=tmp_path / "original.wav", model_filename="model.ckpt"
        )
    with pytest.raises(ValueError, match="missing 'instrumental'"):
        normalized_stem_paths(("instrumental",), tmp_path, output_aliases=(("other", "instrumental"),))
    assert candidate.is_file()


@pytest.mark.parametrize(
    ("stems", "aliases"),
    [
        (("../outside",), ()),
        (("/outside",), ()),
        (("nested\\outside",), ()),
        (("vocals", "VOCALS"), ()),
        (("vocals", "other"), (("other", "vocals"),)),
        (("vocals",), (("../outside", "vocals"),)),
        (("vocals",), (("other", "missing"),)),
        (("vocals",), (("other", "vocals"), ("OTHER", "vocals"))),
        (("vocals", "other"), (("backing", "vocals"), ("backing", "other"))),
    ],
)
def test_normalizer_rejects_unsafe_or_overlapping_metadata(tmp_path, stems, aliases):
    with pytest.raises(ValueError, match="trusted output"):
        normalized_stem_paths(stems, tmp_path, output_aliases=aliases)
    assert list(tmp_path.iterdir()) == []


def test_custom_output_names_supports_multiple_trusted_aliases_for_one_stem():
    assert custom_output_names(
        ("vocals", "instrumental"), output_aliases=(("other", "instrumental"), ("backing", "instrumental"))
    ) == {"vocals": "vocals", "other": "instrumental", "backing": "instrumental"}


@pytest.mark.parametrize("filename", ["instrumental.wav", "other.wav", "original_(other)_model.wav"])
@pytest.mark.parametrize("broken", [False, True])
def test_normalizer_rejects_symlinks_even_with_a_valid_fallback(tmp_path, filename, broken):
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside.wav"
    if not broken:
        outside.write_text("do not touch")
    (output / filename).symlink_to(outside)
    (output / "original_(instrumental)_model.wav").write_text("fallback")

    with pytest.raises(ValueError, match="symlinks are forbidden"):
        normalized_stem_paths(
            ("instrumental",), output, output_aliases=(("other", "instrumental"),),
            source=tmp_path / "original.wav", model_filename="model.ckpt",
        )

    assert (output / filename).is_symlink()
    assert outside.exists() is not broken
    if not broken:
        assert outside.read_text() == "do not touch"


def test_normalizer_rejects_hardlinked_duplicate_stems(tmp_path):
    (tmp_path / "vocals.wav").write_text("same audio")
    (tmp_path / "instrumental.wav").hardlink_to(tmp_path / "vocals.wav")
    with pytest.raises(ValueError, match="duplicate stems refer to the same file"):
        normalized_stem_paths(("vocals", "instrumental"), tmp_path)
    assert {path.name for path in tmp_path.iterdir()} == {"vocals.wav", "instrumental.wav"}


def test_normalizer_rejects_directory_as_stem_and_ignores_nested_files(tmp_path):
    nested = tmp_path / "vocals.wav"
    nested.mkdir()
    (nested / "instrumental.wav").write_text("nested")
    with pytest.raises(ValueError, match="not a regular file"):
        normalized_stem_paths(("vocals",), tmp_path)
    with pytest.raises(ValueError, match="missing 'instrumental'"):
        normalized_stem_paths(("instrumental",), tmp_path)
    assert (nested / "instrumental.wav").read_text() == "nested"


def test_normalizer_rejects_missing_or_symlink_output_folder(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="Observed files: \\(none\\)"):
        normalized_stem_paths(("vocals",), missing)
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "VOCALS.wav").write_text("untouched")
    link = tmp_path / "link"
    link.symlink_to(folder, target_is_directory=True)
    with pytest.raises(ValueError, match="output must be a directory, not a symlink"):
        normalized_stem_paths(("vocals",), link)
    assert (folder / "VOCALS.wav").read_text() == "untouched"


@pytest.mark.parametrize("filename", ["../outside.wav", "/outside.wav", "nested/vocals.wav", "..\\outside.wav"])
def test_mlx_output_write_rejects_paths_outside_output(tmp_path, filename):
    with pytest.raises(ValueError, match="Unsafe separation output path"):
        restricted_output_path(tmp_path, filename)
    assert list(tmp_path.iterdir()) == []


def test_mlx_output_write_allows_basename_or_path_in_output_and_rejects_links(tmp_path):
    assert restricted_output_path(tmp_path, "vocals.wav") == tmp_path / "vocals.wav"
    assert restricted_output_path(tmp_path, str(tmp_path / "vocals.wav")) == tmp_path / "vocals.wav"
    (tmp_path / "other.wav").symlink_to(tmp_path / "vocals.wav")
    with pytest.raises(ValueError, match="Unsafe separation output file"):
        restricted_output_path(tmp_path, "other.wav")
    (tmp_path / "vocals.wav").write_text("audio")
    (tmp_path / "backing.wav").hardlink_to(tmp_path / "vocals.wav")
    with pytest.raises(ValueError, match="Unsafe separation output file"):
        restricted_output_path(tmp_path, "backing.wav")


@pytest.mark.parametrize("provider_id", ["mlx-audio-separator", "audio-separator"])
def test_providers_reject_symlink_output_directory_before_inference(tmp_path, monkeypatch, provider_id):
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "output"
    output.symlink_to(outside, target_is_directory=True)
    profile = CURATED_MODELS["roformer-vocals"]

    def unexpected_runtime(*args, **kwargs):
        raise AssertionError("runtime must not write through a symlink output folder")

    if provider_id == "mlx-audio-separator":
        monkeypatch.setattr("riffroom.providers.mlx._load_runtime", lambda: SimpleNamespace(
            LocalSeparator=unexpected_runtime, configure_demucs_cache=unexpected_runtime
        ))
        provider = MlxAudioSeparatorProvider()
        variant = profile.variants[0]
    else:
        provider = AudioSeparatorCliProvider(
            environ={}, executable_resolver=lambda _: "/managed/audio-separator", runner=unexpected_runtime
        )
        variant = profile.variants[1]

    with pytest.raises(ValueError, match="output must be a directory, not a symlink"):
        provider.separate(
            profile, variant, tmp_path / "original.wav", output, tmp_path / "cache",
            on_model_loaded=unexpected_runtime,
        )
    assert list(outside.iterdir()) == []


def test_fallback_sanitizes_and_uniquifies_filenames_without_overwriting(tmp_path):
    filenames = ["odd (part).wav", "odd #part.wav", "odd_part.wav", "instrumental!.wav",
                 "é.wav", "x" * 120 + ".wav", "X" * 119 + "y.wav"]
    for filename in filenames:
        (tmp_path / filename).write_text(filename)
    paths = completed_stem_paths(("vocals", "instrumental"), tmp_path)
    assert len(paths) == len(filenames)
    assert len({name.casefold() for name in paths}) == len(filenames)
    assert "instrumental" not in paths  # Sanitization cannot assert a trusted identity.
    assert {path.read_text() for path in paths.values()} == set(filenames)
    assert all(len(name) <= MAX_STEM_NAME and path.name == f"{name}.wav" for name, path in paths.items())
    assert paths.output_warning["actual_files"] == sorted(filenames)


@pytest.mark.parametrize("exception", [ValueError("broken metadata"), OSError("rename failed"),
                                       RuntimeError("unexpected error")])
def test_fallback_does_not_hide_non_naming_errors(tmp_path, monkeypatch, exception):
    for name in ("vocals", "instrumental"):
        (tmp_path / f"{name}.wav").touch()

    def broken(*args, **kwargs):
        raise exception

    monkeypatch.setattr("riffroom.providers.base.normalized_stem_paths", broken)
    with pytest.raises(type(exception), match=str(exception)):
        completed_stem_paths(("vocals", "instrumental"), tmp_path)

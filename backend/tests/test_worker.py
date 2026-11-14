import json
import shutil
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from riffroom import worker
from riffroom.models import CURATED_MODELS, ExecutionVariant
from riffroom.providers.audio_separator import AudioSeparatorCliProvider
from riffroom.providers.base import MAX_OUTPUT_STEMS, OUTPUT_WARNING_MESSAGE, StemPaths
from riffroom.providers.mlx import MlxAudioSeparatorProvider


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
        variants=(ExecutionVariant("test-provider", "test.bin", ("macos-arm64",), True),),
        stems=("guitar",),
    )
    received = {}

    class FakeProvider:
        def separate(
            self,
            received_profile,
            received_variant,
            received_source,
            received_output,
            received_cache,
            *,
            on_model_loaded,
        ):
            received.update(
                profile=received_profile,
                variant=received_variant,
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

    worker.run(source, output, cache, profile.id, "test-provider", {"test-provider": FakeProvider()})

    assert received == {
        "profile": profile,
        "variant": profile.variants[0],
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
        variants=(ExecutionVariant("test-provider", "test.bin", ("macos-arm64",), True),),
        stems=("guitar",),
    )

    class MisalignedProvider:
        def separate(self, profile, variant, source, output, cache, *, on_model_loaded):
            on_model_loaded()
            stem = output / "guitar.wav"
            write_source(stem, frames=4)
            return {"guitar": stem}

    monkeypatch.setattr(worker, "MODELS", {profile.id: profile})

    with pytest.raises(ValueError, match="isn't aligned with the source"):
        worker.run(
            source,
            output,
            cache,
            profile.id,
            "test-provider",
            {"test-provider": MisalignedProvider()},
        )

    assert not (output / "stems.json").exists()


def test_worker_rejects_a_missing_expected_stem(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    write_source(source)
    profile = replace(
        CURATED_MODELS["demucs-6"],
        id="test-model",
        variants=(ExecutionVariant("test-provider", "test.bin", ("macos-arm64",), True),),
        stems=("guitar",),
    )

    class MissingStemProvider:
        def separate(self, profile, variant, source, output, cache, *, on_model_loaded):
            on_model_loaded()
            return {}

    monkeypatch.setattr(worker, "MODELS", {profile.id: profile})

    with pytest.raises(ValueError, match="expected guitar stem"):
        worker.run(
            source,
            tmp_path / "output",
            tmp_path / "cache",
            profile.id,
            "test-provider",
            {"test-provider": MissingStemProvider()},
        )


def test_worker_does_not_fall_back_after_selected_provider_fails(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    write_source(source)
    profile = replace(
        CURATED_MODELS["demucs-6"],
        id="test-model",
        variants=(
            ExecutionVariant("preferred", "preferred.bin", ("macos-arm64",), True),
            ExecutionVariant("fallback", "fallback.bin", ("macos-arm64",), True),
        ),
    )
    calls = []

    class FailingProvider:
        def separate(self, profile, variant, source, output, cache, *, on_model_loaded):
            calls.append(variant.provider_id)
            raise RuntimeError("selected provider failed")

    class FallbackProvider:
        def separate(self, profile, variant, source, output, cache, *, on_model_loaded):
            calls.append(variant.provider_id)
            return {}

    monkeypatch.setattr(worker, "MODELS", {profile.id: profile})

    with pytest.raises(RuntimeError, match="selected provider failed"):
        worker.run(
            source,
            tmp_path / "output",
            tmp_path / "cache",
            profile.id,
            "preferred",
            {"preferred": FailingProvider(), "fallback": FallbackProvider()},
        )

    assert calls == ["preferred"]


@pytest.mark.parametrize("provider_id", ["mlx-audio-separator", "audio-separator"])
def test_worker_validates_real_decorated_kimberley_output_and_writes_manifest(tmp_path, monkeypatch, provider_id):
    source = tmp_path / "original.wav"
    output = tmp_path / "output"
    write_source(source)
    profile = CURATED_MODELS["roformer-vocals"]
    decorated = "original_(other)_vocals_mel_band_roformer.wav"

    if provider_id == "mlx-audio-separator":
        class FakeSeparator:
            def __init__(self, **kwargs):
                self.model_instance = SimpleNamespace()

            def load_model(self, filename):
                assert filename == profile.filename

            def separate(self, source_path, *, custom_output_names):
                assert custom_output_names == {"vocals": "vocals", "other": "instrumental"}
                samples, _ = sf.read(source_path, dtype="float32")
                self.model_instance.write_audio(str(output / "vocals.wav"), samples)
                self.model_instance.write_audio(str(output / decorated), samples)

        monkeypatch.setattr("riffroom.providers.mlx._load_runtime", lambda: SimpleNamespace(
            LocalSeparator=FakeSeparator, configure_demucs_cache=lambda _: None
        ))
        provider = MlxAudioSeparatorProvider()
    else:
        def runner(argv, **kwargs):
            shutil.copyfile(source, output / "vocals.wav")
            shutil.copyfile(source, output / decorated)
            return SimpleNamespace(returncode=0)

        provider = AudioSeparatorCliProvider(
            environ={}, executable_resolver=lambda _: "/managed/audio-separator", runner=runner
        )

    worker.run(source, output, tmp_path / "cache", profile.id, provider_id, {provider_id: provider})

    manifest = json.loads((output / "stems.json").read_text())
    assert [(stem["name"], stem["file"]) for stem in manifest] == [
        ("vocals", "vocals.wav"), ("instrumental", "instrumental.wav")
    ]
    assert all(stem["peaks"] for stem in manifest)
    assert {path.name for path in output.iterdir()} == {"vocals.wav", "instrumental.wav", "stems.json"}
    expected = sf.info(source)
    for name in profile.stems:
        actual = sf.info(output / f"{name}.wav")
        assert (actual.frames, actual.samplerate, actual.channels) == (
            expected.frames, expected.samplerate, expected.channels
        )


def test_worker_keeps_ambiguous_portable_outputs_without_guessing(tmp_path):
    source = tmp_path / "original.wav"
    output = tmp_path / "output"
    write_source(source)
    profile = CURATED_MODELS["roformer-vocals"]
    filenames = ("VOCALS.WAV", "other.wav", "original_(other)_vocals_mel_band_roformer.wav")

    def runner(argv, **kwargs):
        for filename in filenames:
            shutil.copyfile(source, output / filename)
        return SimpleNamespace(returncode=0)

    provider = AudioSeparatorCliProvider(
        environ={}, executable_resolver=lambda _: "/managed/audio-separator", runner=runner
    )
    worker.run(
        source, output, tmp_path / "cache", profile.id, "audio-separator", {"audio-separator": provider}
    )
    manifest = json.loads((output / "stems.json").read_text())
    assert {stem["name"] for stem in manifest["stems"]} == {"vocals", "other", "other_2"}
    assert manifest["output_warning"]["actual_files"] == sorted(filenames)
    assert {path.name for path in output.iterdir()} == {"vocals.wav", "other.wav", "other_2.wav", "stems.json"}


def successful_runtime(monkeypatch, provider_id, generate, *, fail=False):
    """Both real provider adapters see the same filesystem output / runtime outcome."""
    if provider_id == "mlx-audio-separator":
        class FakeSeparator:
            def __init__(self, **kwargs):
                self.model_instance = SimpleNamespace()

            def load_model(self, filename):
                pass

            def separate(self, source, **kwargs):
                generate()
                if fail:
                    raise RuntimeError("inference crashed")

        monkeypatch.setattr("riffroom.providers.mlx._load_runtime", lambda: SimpleNamespace(
            LocalSeparator=FakeSeparator, configure_demucs_cache=lambda _: None,
        ))
        return MlxAudioSeparatorProvider()

    def runner(*args, **kwargs):
        generate()
        return SimpleNamespace(returncode=9 if fail else 0)

    return AudioSeparatorCliProvider(
        environ={}, executable_resolver=lambda _: "/managed/audio-separator", runner=runner,
    )


@pytest.mark.parametrize("provider_id", ["mlx-audio-separator", "audio-separator"])
@pytest.mark.parametrize("filenames,labels", [
    (("vocals.wav", "hiccup.wav"), {"vocals", "hiccup"}),
    (("vocals.wav", "instrumental.wav", "hiccup.wav"), {"vocals", "instrumental", "hiccup"}),
    (("VOCALS.WAV", "other.wav", "hiccup.wav"), {"vocals", "instrumental", "hiccup"}),
    (("other.wav", "original_(other)_vocals_mel_band_roformer.wav"), {"other", "other_2"}),
    (("odd #1.wav", "odd (2).WAV"), {"odd_1", "odd_2"}),
    (("original_(hiccup)_vocals_mel_band_roformer.wav",), {"hiccup"}),
    (("wrong_(hiccup)_vocals_mel_band_roformer.wav",), {"wrong_hiccup_vocals_mel_band_roformer"}),
])
def test_worker_fallback_keeps_all_actual_wavs_and_warning(tmp_path, monkeypatch, provider_id, filenames, labels):
    source, output = tmp_path / "original.wav", tmp_path / "output"
    write_source(source)

    def generate():
        for filename in filenames:
            shutil.copyfile(source, output / filename)
        (output / "job.log").write_text("diagnostics")
        (output / "notes.json").write_text("{}")

    provider = successful_runtime(monkeypatch, provider_id, generate)
    worker.run(source, output, tmp_path / "cache", "roformer-vocals", provider_id, {provider_id: provider})
    manifest = json.loads((output / "stems.json").read_text())
    assert {stem["name"] for stem in manifest["stems"]} == labels
    assert all(stem["file"] == stem["name"] + ".wav" for stem in manifest["stems"])
    assert all(stem["peaks"] for stem in manifest["stems"])
    assert manifest["output_warning"] == {
        "code": "unexpected_model_outputs",
        "message": OUTPUT_WARNING_MESSAGE,
        "expected_stems": ["vocals", "instrumental"],
        "actual_files": sorted(filenames),
    }
    for stem in manifest["stems"]:
        assert (output / stem["file"]).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("provider_id", ["mlx-audio-separator", "audio-separator"])
@pytest.mark.parametrize("problem", [
    "no_wav", "malformed", "misaligned", "nonfinite", "symlink", "hardlink", "directory",
    "collision", "unsafe_name", "crash", "sample_rate", "channels", "empty", "fake_wav", "too_many",
])
def test_worker_fallback_still_fails_without_manifest(tmp_path, monkeypatch, provider_id, problem):
    source, output = tmp_path / "original.wav", tmp_path / "output"
    write_source(source)

    def generate():
        if problem == "no_wav":
            (output / "notes.json").write_text("{}")
            return
        shutil.copyfile(source, output / "vocals.wav")
        path = output / "hiccup.wav"
        if problem == "malformed":
            path.write_text("not audio")
        elif problem == "misaligned":
            write_source(path, frames=4)
        elif problem in {"sample_rate", "channels", "empty", "fake_wav"}:
            sf.write(path, np.zeros((0 if problem == "empty" else 8, 1 if problem == "channels" else 2)),
                     48000 if problem == "sample_rate" else 44100,
                     format="FLAC" if problem == "fake_wav" else "WAV")
        elif problem == "too_many":
            for index in range(MAX_OUTPUT_STEMS):
                shutil.copyfile(source, output / f"output_{index}.wav")
        elif problem == "nonfinite":
            sf.write(path, np.full((8, 2), np.nan), 44100, subtype="FLOAT")
        elif problem == "symlink":
            path.symlink_to(source)
        elif problem == "hardlink":
            path.hardlink_to(source)
        elif problem == "directory":
            path.mkdir()
        elif problem == "collision":
            shutil.copyfile(source, output / "ss.wav")
            # Some macOS filesystems consider these names identical. In that
            # environment, a two-file casefold collision cannot be created.
            if (output / "ß.wav").exists() and (output / "ß.wav").samefile(output / "ss.wav"):
                pytest.skip("Filesystem does not distinguish ss.wav from ß.wav")
            shutil.copyfile(source, output / "ß.wav")
        elif problem == "unsafe_name":
            shutil.copyfile(source, output / "bad\\name.wav")
        else:
            shutil.copyfile(source, path)

    provider = successful_runtime(monkeypatch, provider_id, generate, fail=problem == "crash")
    with pytest.raises((ValueError, RuntimeError)):
        worker.run(source, output, tmp_path / "cache", "roformer-vocals", provider_id, {provider_id: provider})
    assert not (output / "stems.json").exists()
    assert sf.info(source).frames == 8


def test_worker_fallback_handles_mismatched_declared_stems(tmp_path, monkeypatch):
    source, output = tmp_path / "original.wav", tmp_path / "output"
    write_source(source)
    original = CURATED_MODELS["roformer-vocals"]
    profile = replace(original, stems=("guitar", "drums", "bass"), variants=tuple(
        replace(variant, output_aliases=()) for variant in original.variants
    ))
    monkeypatch.setattr(worker, "MODELS", {profile.id: profile})

    def generate():
        for name in ("vocals", "hiccup"):
            shutil.copyfile(source, output / f"{name}.wav")

    provider_id = "audio-separator"
    provider = successful_runtime(monkeypatch, provider_id, generate)
    worker.run(source, output, tmp_path / "cache", profile.id, provider_id, {provider_id: provider})
    manifest = json.loads((output / "stems.json").read_text())
    assert manifest["output_warning"]["expected_stems"] == ["guitar", "drums", "bass"]
    assert {stem["name"] for stem in manifest["stems"]} == {"vocals", "hiccup"}


@pytest.mark.parametrize("filename", ["stale.wav", "stems.json"])
def test_worker_refuses_reused_run_directory_without_reading_or_modifying_it(tmp_path, filename):
    output = tmp_path / "output"
    output.mkdir()
    stale = output / filename
    stale.write_text("untouched previous output")
    with pytest.raises(ValueError, match="fresh run output directory"):
        worker.run(tmp_path / "original.wav", output, tmp_path / "cache",
                   "roformer-vocals", "audio-separator", {})
    assert stale.read_text() == "untouched previous output"


@pytest.mark.parametrize("stage", ["construct", "load", "waveform"])
def test_model_creation_and_postprocessing_errors_never_produce_manifest(tmp_path, monkeypatch, stage):
    source, output = tmp_path / "original.wav", tmp_path / "output"
    write_source(source)

    class Separator:
        def __init__(self, **kwargs):
            if stage == "construct":
                raise RuntimeError("construction failed")
            self.model_instance = SimpleNamespace()

        def load_model(self, filename):
            if stage == "load":
                # Even a failed load which leaves plausible outputs is an error.
                shutil.copyfile(source, output / "hiccup.wav")
                raise RuntimeError("load failed")

        def separate(self, *args, **kwargs):
            shutil.copyfile(source, output / "hiccup.wav")

    def broken_waveform(path):
        raise RuntimeError("waveform failed")

    monkeypatch.setattr("riffroom.providers.mlx._load_runtime", lambda: SimpleNamespace(
        LocalSeparator=Separator, configure_demucs_cache=lambda _: None,
    ))
    monkeypatch.setattr(worker, "waveform", broken_waveform)
    provider_id = "mlx-audio-separator"
    with pytest.raises(RuntimeError, match="failed"):
        worker.run(source, output, tmp_path / "cache", "roformer-vocals", provider_id,
                   {provider_id: MlxAudioSeparatorProvider()})
    assert not (output / "stems.json").exists()


@pytest.mark.parametrize("problem", ["outside", "symlink", "hardlink", "duplicate", "omitted", "label"])
def test_worker_independently_rejects_unsafe_warning_mapping(tmp_path, monkeypatch, problem):
    source, output = tmp_path / "original.wav", tmp_path / "output"
    write_source(source)

    class UncheckedProvider:
        def separate(self, profile, variant, source, output, cache, **kwargs):
            path = output / "hiccup.wav"
            if problem == "outside":
                path = tmp_path / "outside.wav"
                shutil.copyfile(source, path)
            elif problem == "symlink":
                path.symlink_to(source)
            elif problem == "hardlink":
                path.hardlink_to(source)
            else:
                shutil.copyfile(source, path)
            paths = {"../hiccup" if problem == "label" else "hiccup": path}
            if problem == "duplicate":
                paths["another"] = path
            if problem == "omitted":
                shutil.copyfile(source, output / "omitted.wav")
            return StemPaths(paths, {"code": "unexpected_model_outputs", "message": OUTPUT_WARNING_MESSAGE,
                                     "expected_stems": list(profile.stems), "actual_files": [path.name]})

    def forbidden(*args):
        pytest.fail("Unsafe paths must fail before reading audio")

    monkeypatch.setattr(worker, "validate_stems", forbidden)
    provider_id = "audio-separator"
    with pytest.raises(ValueError):
        worker.run(source, output, tmp_path / "cache", "roformer-vocals", provider_id,
                   {provider_id: UncheckedProvider()})
    assert not (output / "stems.json").exists()

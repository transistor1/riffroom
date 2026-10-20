"""Trust boundaries and routing for the lead/rhythm checkpoint."""

import asyncio
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from riffroom.jobs import Jobs
from riffroom.models import CURATED_MODELS, catalog, resolve_model_variant
from riffroom.providers import listra92
from riffroom.providers.audio_separator import AudioSeparatorCliProvider
from riffroom.store import Store


def test_listra_catalog_uses_existing_portable_runtime(tmp_path):
    profile = CURATED_MODELS[listra92.MODEL_ID]
    assert profile.stems == ("lead", "rhythm")
    assert profile.terms_status == "unverified"
    assert profile.cache_files == (listra92.CHECKPOINT, listra92.CONFIG)
    for platform in ("macos-arm64", "windows-x86_64"):
        assert resolve_model_variant(profile, lambda _: False, platform_key=platform) is None
        row = next(row for row in catalog(
            tmp_path, platform_key=platform, provider_availability={"audio-separator": True}
        ) if row["id"] == profile.id)
        assert row["provider"] == "audio-separator"
        assert row["compatibility"]["compatible"]
        assert row["compatibility"]["experimental"] == (platform == "windows-x86_64")
    assert resolve_model_variant(profile, lambda _: True, platform_key="linux-x86_64") is None


def test_provider_uses_selected_runtime_python_and_logical_outputs(tmp_path):
    executable = tmp_path / "audio-separator"
    python = tmp_path / "python"
    python.touch(mode=0o755)
    captured = []

    def runner(argv, **kwargs):
        captured.append((argv, kwargs))
        (tmp_path / "Lead.wav").touch()
        (tmp_path / "Rhythm.wav").touch()
        return SimpleNamespace(returncode=0)

    provider = AudioSeparatorCliProvider(
        environ={}, executable_resolver=lambda _: str(executable), runner=runner
    )
    profile = CURATED_MODELS[listra92.MODEL_ID]
    paths = provider.separate(
        profile, profile.variants[0], tmp_path / "guitar.wav", tmp_path, tmp_path / "cache",
        on_model_loaded=lambda: None,
    )
    argv, kwargs = captured[0]
    assert argv == [str(python), "-I", str(Path(listra92.__file__)),
                    str(tmp_path / "guitar.wav"), str(tmp_path), str(tmp_path / "cache")]
    assert kwargs == {"check": False, "shell": False}
    assert list(paths) == ["lead", "rhythm"]
    assert all(path.is_file() for path in paths.values())


def test_missing_runtime_python_fails_without_falling_back(tmp_path):
    with pytest.raises(RuntimeError, match="requires Python beside"):
        AudioSeparatorCliProvider._runtime_python(str(tmp_path / "audio-separator"))


def test_mask_expansion_is_scoped_and_restored_even_on_error():
    def estimator(**kwargs):
        return kwargs

    module = SimpleNamespace(MaskEstimator=estimator)
    with pytest.raises(RuntimeError, match="load failed"):
        with listra92.mask_expansion_compatibility(module):
            assert module.MaskEstimator(dim=384) == {"dim": 384, "mlp_expansion_factor": 2}
            raise RuntimeError("load failed")
    assert module.MaskEstimator is estimator


def test_artifact_download_is_pinned_verified_and_rechecks_cache(tmp_path, monkeypatch):
    payload = b"trusted bytes"
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(listra92, "ARTIFACTS", (("model.ckpt", "upstream.ckpt", digest),))
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return io.BytesIO(payload)

    monkeypatch.setattr(listra92.urllib.request, "urlopen", fetch)
    listra92.prepare_artifacts(tmp_path)
    listra92.prepare_artifacts(tmp_path)
    assert calls == [listra92.SOURCE + "upstream.ckpt"]
    (tmp_path / "model.ckpt").write_bytes(b"corrupt")
    listra92.prepare_artifacts(tmp_path)
    assert len(calls) == 2
    assert (tmp_path / "model.ckpt").read_bytes() == payload


def test_bad_download_never_publishes_and_cleans_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(listra92, "ARTIFACTS", (("model.ckpt", "upstream.ckpt", "bad"),))
    monkeypatch.setattr(listra92.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"bad"))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        listra92.prepare_artifacts(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_existing_partial_is_not_removed(tmp_path):
    partial = tmp_path / (listra92.CHECKPOINT + ".part")
    partial.write_bytes(b"another worker")
    with pytest.raises(RuntimeError, match="already in progress or interrupted"):
        listra92.prepare_artifacts(tmp_path)
    assert partial.read_bytes() == b"another worker"


def test_symlink_artifact_is_rejected(tmp_path):
    (tmp_path / listra92.CHECKPOINT).symlink_to(tmp_path / "unrelated")
    with pytest.raises(ValueError, match="Refusing symlink"):
        listra92.prepare_artifacts(tmp_path)


def test_listra_child_job_replaces_only_parent_guitar(tmp_path, monkeypatch):
    calls = []

    class EmptyOutput:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    async def spawn(*argv, **kwargs):
        calls.append(argv)
        output = Path(argv[4])
        (output / "stems.json").write_text(json.dumps([
            {"name": name, "file": name + ".wav", "peaks": []} for name in ("lead", "rhythm")
        ]))

        async def wait():
            return 0

        return SimpleNamespace(stdout=EmptyOutput(), wait=wait)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    async def run():
        store = Store(tmp_path / "tracks")
        tid, root_id = uuid4().hex, uuid4().hex
        folder = store.directory(tid) / "runs" / root_id
        folder.mkdir(parents=True)
        (folder / "guitar.wav").touch()
        store.put({
            "id": tid, "status": "ready", "created_at": "now", "active_run": root_id,
            "next_take_number": 2, "runs": [{
                "id": root_id, "model_id": "demucs-6", "take_number": 1,
                "stems": [{"name": "guitar", "file": "guitar.wav"},
                          {"name": "drums", "file": "drums.wav"}],
            }],
        })
        provider = SimpleNamespace(is_available=lambda: True)
        jobs = Jobs(store, tmp_path / "cache", provider_registry={"audio-separator": provider})
        source = {"type": "stem", "run_id": root_id, "stem_name": "guitar"}
        jobs.start(tid, listra92.MODEL_ID, source)
        await jobs.tasks[tid]
        track = store.get(tid)
        parent, child = track["runs"]
        assert track["status"] == "ready"
        assert track["active_run"] == root_id
        assert track["next_take_number"] == 2
        assert parent["active_children"] == {"guitar": child["id"]}
        assert child["source"] == source
        assert child["model_id"] == listra92.MODEL_ID
        assert child["provider_id"] == "audio-separator"
        assert [stem["name"] for stem in child["stems"]] == ["lead", "rhythm"]
        assert Path(calls[0][3]) == folder / "guitar.wav"
        assert calls[0][-2:] == (listra92.MODEL_ID, "audio-separator")

    asyncio.run(run())

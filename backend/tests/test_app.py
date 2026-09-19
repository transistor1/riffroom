import io
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from riffroom.app import create_app
from riffroom.audio import validate_stems
from riffroom.models import (
    COMMUNITY_MODELS,
    CURATED_MODELS,
    MODELS,
    community_model_id,
    community_profiles_from_metadata,
    current_platform_key,
    filter_models,
)


@pytest.fixture
def application(tmp_path, monkeypatch):
    app = create_app(tmp_path, tmp_path / "no-frontend")
    started = []
    monkeypatch.setattr(app.state.jobs, "start", lambda tid, model: started.append((tid, model)))
    app.state.started = started
    with TestClient(app) as client:
        yield app, client


def wav_bytes(seconds=0.1):
    stream = io.BytesIO()
    samples = np.sin(np.arange(int(48000 * seconds)) * 2 * np.pi * 440 / 48000) * 0.1
    sf.write(stream, samples, 48000, format="WAV")
    return stream.getvalue()


def upload(client):
    response = client.post("/api/tracks", files={"file": ("../guitar.wav", wav_bytes(), "audio/wav")})
    assert response.status_code == 201, response.text
    return response.json()


def test_model_catalog_exposes_provider_terms_and_compatibility(application):
    _, client = application

    response = client.get("/api/models")

    assert response.status_code == 200
    models = response.json()
    assert [model["id"] for model in models[:4]] == [
        "demucs-6",
        "roformer-6",
        "guitar-focus",
        "demucs-ft",
    ]
    assert len(models) > 4
    assert {model["provider"] for model in models} == {"mlx-audio-separator"}
    assert {"Demucs", "RoFormer", "MDXC"} <= {model["architecture"] for model in models}
    assert {model["terms_status"] for model in models} == {
        "open",
        "non-commercial",
        "unverified",
    }
    for model in models:
        assert model["supported_platforms"] == ["macos-arm64"]
        platform_key = current_platform_key()
        expected_compatibility = platform_key in model["supported_platforms"]
        assert model["compatibility"]["platform_key"] == platform_key
        assert model["compatibility"]["platform_name"]
        assert model["compatibility"]["compatible"] is expected_compatibility
        assert model["compatibility"]["label"].startswith(
            "Compatible" if expected_compatibility else "Unavailable"
        )
        assert model["prepared"] is False
        assert model["cache_bytes"] == 0
        assert model["cache_label"] == "Downloads on first use"
    for model in models[:4]:
        assert model["curated"] is True
        assert model["catalog_group"] == "curated"
        assert model["catalog_origin"] == "Riffroom curated catalog"
        assert model["cache_cleanup_supported"] is True
    for model in models[4:]:
        assert model["curated"] is False
        assert model["catalog_group"] == "community"
        assert model["terms_status"] == "unverified"
        assert "Checkpoint terms unverified" in model["license"]
        assert model["catalog_origin"].startswith("mlx-audio-separator 0.1.7 bundled")


def test_curated_profiles_are_unchanged_and_community_order_is_deterministic(application):
    _, client = application

    models = client.get("/api/models").json()

    assert [(item["id"], item["filename"], item["stems"]) for item in models[:4]] == [
        ("demucs-6", "htdemucs_6s.yaml", list(CURATED_MODELS["demucs-6"].stems)),
        ("roformer-6", "BS-Roformer-SW.ckpt", list(CURATED_MODELS["roformer-6"].stems)),
        ("guitar-focus", "becruily_guitar.ckpt", list(CURATED_MODELS["guitar-focus"].stems)),
        ("demucs-ft", "htdemucs_ft.yaml", list(CURATED_MODELS["demucs-ft"].stems)),
    ]
    community_order = [(item["name"].casefold(), item["filename"].casefold()) for item in models[4:]]
    assert community_order == sorted(community_order)
    assert [model.id for model in filter_models()] == [item["id"] for item in models]
    assert all(model.catalog_group == "community" for model in filter_models(catalog_group="community"))
    mdxc = filter_models(catalog_group="community", architecture="MDXC", query="drum")
    assert len(mdxc) == 1
    assert mdxc[0].filename == "MDX23C-DrumSep-aufr33-jarredou.ckpt"


def test_community_ids_and_explicit_stem_boundary_are_safe_and_deterministic():
    registry = {
        "roformer_download_list": {
            "Explicit stems": {"safe.ckpt": "safe.yaml"},
            "Missing stems": {"unknown.ckpt": "unknown.yaml"},
            "Unsafe URL": {"https://example.test/model.ckpt": "unsafe.yaml"},
            "Unsafe path": {"../escape.ckpt": "escape.yaml"},
            "Unsafe Windows path": {"..\\escape.ckpt": "escape.yaml"},
            "Executable": {"plugin.py": "plugin.yaml"},
            "Unsafe stem": {"unsafe-stem.ckpt": "unsafe-stem.yaml"},
        }
    }
    scores = {
        "safe.ckpt": {"stems": ["vocals", "other"]},
        "unknown.ckpt": {"model_name": "No output metadata"},
        "https://example.test/model.ckpt": {"stems": ["vocals", "other"]},
        "../escape.ckpt": {"stems": ["vocals", "other"]},
        "..\\escape.ckpt": {"stems": ["vocals", "other"]},
        "plugin.py": {"stems": ["vocals", "other"]},
        "unsafe-stem.ckpt": {"stems": ["../vocals", "other"]},
    }

    first = community_profiles_from_metadata(registry, scores)
    second = community_profiles_from_metadata(registry, scores)

    assert first == second
    assert len(first) == 1
    assert first[0].filename == "safe.ckpt"
    assert first[0].stems == ("vocals", "other")
    assert first[0].id == community_model_id("safe.ckpt")
    assert first[0].id != first[0].filename
    assert all(model.stems for model in COMMUNITY_MODELS.values())
    assert "UVR-BVE-4B_SN-44100-2.pth" not in {model.filename for model in COMMUNITY_MODELS.values()}


def test_only_trusted_community_ids_can_start_separation(application):
    app, client = application
    track = upload(client)
    community = next(iter(COMMUNITY_MODELS.values()))

    response = client.post(
        f"/api/tracks/{track['id']}/separate", json={"model_id": community.id}
    )
    assert response.status_code == 202
    assert app.state.started[-1] == (track["id"], community.id)

    response = client.post(
        f"/api/tracks/{track['id']}/separate", json={"model_id": community.filename}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown separation model."}


def test_local_separator_rejects_an_untrusted_filename_before_runtime_lookup():
    from riffroom.separator import LocalSeparator

    separator = object.__new__(LocalSeparator)
    with pytest.raises(ValueError, match="trusted catalog"):
        separator.load_model("../arbitrary.py")


def write_model_assets(root, model_id, byte=b"prepared"):
    paths = []
    for filename in MODELS[model_id].cache_files:
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(byte)
        paths.append(path)
    return paths


def test_model_cache_state_and_safe_idempotent_cleanup(application):
    app, client = application
    cache = app.state.jobs.cache
    target_assets = write_model_assets(cache, "demucs-6", b"target")
    other_assets = write_model_assets(cache, "guitar-focus", b"other")
    partial = target_assets[0].with_name(target_assets[0].name + ".part")
    partial.write_bytes(b"partial")
    shared_registry = cache / "download_checks.json"
    shared_torch = cache / "torch" / "hub" / "checkpoints" / "5c90dfd2-34c22ccb.th"
    shared_registry.write_bytes(b"shared")
    shared_torch.parent.mkdir(parents=True)
    shared_torch.write_bytes(b"shared torch cache")

    models = {model["id"]: model for model in client.get("/api/models").json()}
    assert models["demucs-6"]["prepared"] is True
    assert models["demucs-6"]["cache_bytes"] == sum(
        path.stat().st_size for path in [*target_assets, partial]
    )
    assert models["demucs-6"]["cache_label"] == "Prepared"
    assert models["guitar-focus"]["prepared"] is True

    track = upload(client)
    run_id = uuid4().hex
    add_runs(app, track["id"], [run_id], active_run=run_id)
    original = app.state.store.directory(track["id"]) / "original.wav"
    stem = app.state.store.directory(track["id"]) / "runs" / run_id / "guitar.wav"
    original_bytes, stem_bytes = original.read_bytes(), stem.read_bytes()
    app.state.store.update(
        track["id"], status="queued", pending_model="demucs-6"
    )

    response = client.delete("/api/models/demucs-6/cache")
    assert response.status_code == 409
    assert "active separation" in response.json()["detail"]
    assert all(path.is_file() for path in target_assets)

    app.state.store.update(track["id"], status="ready", pending_model=None)
    assert client.delete("/api/models/demucs-6/cache").status_code == 204
    assert client.delete("/api/models/demucs-6/cache").status_code == 204

    assert not any(path.exists() for path in [*target_assets, partial])
    assert all(path.is_file() for path in other_assets)
    assert shared_registry.read_bytes() == b"shared"
    assert shared_torch.read_bytes() == b"shared torch cache"
    assert original.read_bytes() == original_bytes
    assert stem.read_bytes() == stem_bytes
    models = {model["id"]: model for model in client.get("/api/models").json()}
    assert models["demucs-6"]["prepared"] is False
    assert models["demucs-6"]["cache_bytes"] == 0
    assert models["guitar-focus"]["prepared"] is True


@pytest.mark.parametrize("status", ["queued", "processing"])
def test_model_cache_cleanup_rejects_each_active_status(application, status):
    app, client = application
    assets = write_model_assets(app.state.jobs.cache, "roformer-6")
    track = upload(client)
    app.state.store.update(track["id"], status=status, pending_model="roformer-6")

    response = client.delete("/api/models/roformer-6/cache")

    assert response.status_code == 409
    assert all(path.is_file() for path in assets)


def test_model_cache_does_not_follow_directory_symlink(application, tmp_path):
    app, client = application
    cache = app.state.jobs.cache
    outside = tmp_path / "outside"
    outside.mkdir()
    external_files = []
    for filename in MODELS["demucs-6"].cache_files:
        path = cache / filename
        if path.parent.name == "demucs-mlx":
            external = outside / path.name
            external.write_bytes(b"outside")
            external_files.append(external)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"inside")
    (cache / "demucs-mlx").symlink_to(outside, target_is_directory=True)

    model = next(item for item in client.get("/api/models").json() if item["id"] == "demucs-6")
    assert model["prepared"] is False
    assert model["cache_bytes"] == 2 * len(b"inside")
    assert client.delete("/api/models/demucs-6/cache").status_code == 204

    assert all(path.read_bytes() == b"outside" for path in external_files)
    assert (cache / "demucs-mlx").is_symlink()


def test_delete_unknown_model_cache_returns_404(application):
    _, client = application

    response = client.delete("/api/models/not-curated/cache")

    assert response.status_code == 404
    assert response.json() == {"detail": "Separation model not found."}


def test_shared_community_config_cannot_be_removed(application):
    app, client = application
    model = next(model for model in COMMUNITY_MODELS.values() if not model.cache_cleanup_supported)
    assets = write_model_assets(app.state.jobs.cache, model.id)

    response = client.delete(f"/api/models/{model.id}/cache")

    assert response.status_code == 409
    assert "shared model config" in response.json()["detail"]
    assert all(path.is_file() for path in assets)


def add_runs(app, track_id, run_ids, active_run=None):
    runs = []
    for run_id in run_ids:
        folder = app.state.store.directory(track_id) / "runs" / run_id
        folder.mkdir(parents=True)
        (folder / "guitar.wav").write_bytes(wav_bytes())
        runs.append(
            {
                "id": run_id,
                "model_id": "demucs-6",
                "stems": [{"name": "guitar", "file": "guitar.wav"}],
            }
        )
    app.state.store.update(track_id, status="ready", runs=runs, active_run=active_run)
    return runs


def test_import_decode_and_persist(application):
    app, client = application
    track = upload(client)
    assert track["title"] == "guitar"
    assert track["duration"] == pytest.approx(0.1)
    assert app.state.started == [(track["id"], "demucs-6")]
    assert client.get("/api/tracks").json()[0] == track
    path = app.state.store.directory(track["id"]) / "original.wav"
    info = sf.info(path)
    assert (info.samplerate, info.channels, info.frames) == (44100, 2, 4410)
    assert (
        client.get(f"/api/tracks/{track['id']}/original", headers={"Range": "bytes=0-99"}).status_code == 206
    )
    assert len(track["peaks"]) <= 600
    assert not (path.parent / "upload").exists()


def test_bad_audio_and_unknown_model_leave_no_projects(application):
    app, client = application
    response = client.post("/api/tracks", files={"file": ("bad.mp3", b"not audio")})
    assert response.status_code == 400
    assert client.get("/api/tracks").json() == []
    assert list(app.state.store.root.iterdir()) == []
    response = client.post("/api/tracks", data={"model_id": "evil"}, files={"file": ("a.wav", wav_bytes())})
    assert response.status_code == 400


def test_audio_access_only_to_published_stems(application):
    app, client = application
    track = upload(client)
    tid, run_id = track["id"], uuid4().hex
    folder = app.state.store.directory(tid) / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "guitar.wav").write_bytes(wav_bytes())
    app.state.store.update(tid, runs=[{"id": run_id, "stems": [{"file": "guitar.wav"}]}])
    assert client.get(f"/api/tracks/{tid}/audio/{run_id}/guitar.wav").status_code == 200
    assert client.get(f"/api/tracks/{tid}/audio/{run_id}/job.log").status_code == 404
    assert client.get(f"/api/tracks/{tid}/audio/unknown/guitar.wav").status_code == 404
    assert client.get("/api/tracks/not-a-valid-id").status_code == 404


def test_model_switch_delete_and_cross_origin(application):
    app, client = application
    track = upload(client)
    tid = track["id"]
    assert client.post(f"/api/tracks/{tid}/separate", json={"model_id": "roformer-6"}).status_code == 202
    assert app.state.started[-1] == (tid, "roformer-6")
    response = client.delete(f"/api/tracks/{tid}", headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403
    assert client.delete(f"/api/tracks/{tid}").status_code == 204
    assert not app.state.store.directory(tid).exists()
    assert client.get(f"/api/tracks/{tid}").status_code == 404


def test_delete_run_preserves_track_and_falls_back_to_newest_run(application):
    app, client = application
    track = upload(client)
    tid = track["id"]
    run_ids = [uuid4().hex for _ in range(3)]
    add_runs(app, tid, run_ids, active_run=run_ids[1])
    original = app.state.store.directory(tid) / "original.wav"
    original_bytes = original.read_bytes()

    response = client.delete(f"/api/tracks/{tid}/runs/{run_ids[1]}")

    assert response.status_code == 204
    updated = client.get(f"/api/tracks/{tid}").json()
    assert [run["id"] for run in updated["runs"]] == [run_ids[0], run_ids[2]]
    assert updated["active_run"] == run_ids[2]
    runs_folder = app.state.store.directory(tid) / "runs"
    assert not (runs_folder / run_ids[1]).exists()
    assert (runs_folder / run_ids[0] / "guitar.wav").is_file()
    assert (runs_folder / run_ids[2] / "guitar.wav").is_file()
    assert original.read_bytes() == original_bytes


def test_delete_last_run_clears_active_run(application):
    app, client = application
    track = upload(client)
    tid, run_id = track["id"], uuid4().hex
    add_runs(app, tid, [run_id], active_run=run_id)

    assert client.delete(f"/api/tracks/{tid}/runs/{run_id}").status_code == 204

    updated = client.get(f"/api/tracks/{tid}").json()
    assert updated["runs"] == []
    assert updated["active_run"] is None
    assert (app.state.store.directory(tid) / "original.wav").is_file()


def test_delete_unknown_run_returns_clear_404(application):
    app, client = application
    track = upload(client)
    run_id = uuid4().hex
    add_runs(app, track["id"], [run_id], active_run=run_id)

    response = client.delete(f"/api/tracks/{track['id']}/runs/{uuid4().hex}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Separation result not found."}
    assert app.state.store.get(track["id"])["runs"][0]["id"] == run_id


@pytest.mark.parametrize("status", ["queued", "processing"])
def test_delete_run_rejects_active_separation(application, status):
    app, client = application
    track = upload(client)
    tid, run_id = track["id"], uuid4().hex
    add_runs(app, tid, [run_id], active_run=run_id)
    app.state.store.update(tid, status=status)

    response = client.delete(f"/api/tracks/{tid}/runs/{run_id}")

    assert response.status_code == 409
    assert "finish" in response.json()["detail"]
    assert app.state.store.get(tid)["runs"][0]["id"] == run_id
    assert (app.state.store.directory(tid) / "runs" / run_id).is_dir()


def test_alignment_rejects_wrong_length(tmp_path):
    source, stem = tmp_path / "source.wav", tmp_path / "stem.wav"
    sf.write(source, np.zeros((500, 2)), 44100)
    sf.write(stem, np.zeros((499, 2)), 44100)
    with pytest.raises(ValueError, match="aligned"):
        validate_stems({"guitar": stem}, source)


def test_restart_marks_interrupted_job(tmp_path):
    app = create_app(tmp_path, tmp_path / "none")
    tid = uuid4().hex
    app.state.store.put({"id": tid, "status": "processing", "created_at": "now"})
    with TestClient(app) as client:
        recovered = client.get(f"/api/tracks/{tid}").json()
        assert recovered["status"] == "error"
        assert "retry" in recovered["error"]


def test_float_writer_preserves_relative_levels_and_overrange(tmp_path):
    from riffroom.audio import write_float_stem

    signal = np.array([[1.25, -0.5], [0.1, -0.2], [0, 0]], dtype=np.float32)
    write_float_stem(tmp_path, "guitar.wav", signal)
    actual, sr = sf.read(tmp_path / "guitar.wav", dtype="float32")
    np.testing.assert_array_equal(actual, signal)
    assert sr == 44100
    assert sf.info(tmp_path / "guitar.wav").subtype == "FLOAT"
    with pytest.raises(ValueError, match="invalid audio"):
        write_float_stem(tmp_path, "bad.wav", np.array([[np.nan, 0]]))

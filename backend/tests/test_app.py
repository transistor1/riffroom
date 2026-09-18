import io
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from riffroom.app import create_app
from riffroom.audio import validate_stems


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

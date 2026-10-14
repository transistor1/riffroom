import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from riffroom.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("fixture,status", [
    ("easy_lover_approved_groove.json", "applied"),
    ("reelin_original_grid.json", "no_confident_repair"),
    ("comfortably_numb_duplicate_grid.json", "applied"),
])
def test_read_only_correction_from_stored_analysis(tmp_path, fixture, status):
    baseline = json.loads((FIXTURES / fixture).read_text())
    analysis = baseline["source_analysis"]
    analysis["extra_metadata"] = {"preserve": ["unknown", "future"]}
    app = create_app(tmp_path, tmp_path / "no-frontend")
    track = {"id": "a" * 32, "created_at": "now", "status": "ready",
             "duration": 400, "runs": [], "beat_analysis": analysis}
    app.state.store.put(track)
    manifest = app.state.store.directory(track["id"]) / "track.json"
    original = manifest.read_bytes()

    def forbidden(*args):
        pytest.fail("Correction must not invoke analysis or update the store")

    app.state.beat_jobs.start = forbidden
    app.state.beat_jobs.runner = forbidden
    app.state.store.update = forbidden
    with TestClient(app) as client:
        response = client.get(f"/api/tracks/{track['id']}/beats/correction")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == status
        assert result["source_analysis"] == analysis
        assert result["report"]["source"]["provenance"] == analysis
        assert result["grid"]["downbeats"] == analysis["downbeats"]
        assert result["grid"]["time_signature"] == analysis["time_signature"]
        assert result["report"]["policy"]["downbeat_policy"] == "preserve_only; do not infer accents"
        if fixture == "comfortably_numb_duplicate_grid.json":
            removed = set(baseline["expected_removed_source_indices"])
            assert result["grid"]["beats"] == [b for i, b in enumerate(analysis["beats"]) if i not in removed]
            assert len(result["report"]["proposal"]["accepted_repairs"]) == 23
        elif status == "applied":
            playback_fixture = json.loads((FIXTURES / "easy_lover_correction.json").read_text())
            assert result["grid"] == playback_fixture["grid"]
            beats = result["grid"]["beats"]
            assert len(beats) == 646
            assert beats[:7] == analysis["beats"][:7]
            assert beats[28:] == analysis["beats"][38:]
            assert max(abs(a - b) for a, b in zip(beats, baseline["approved_beats"])) < 0.035
            assert len(result["report"]["proposal"]["accepted_repairs"]) == 1
        else:
            assert result["grid"]["beats"] == analysis["beats"]
            assert result["report"]["proposal"]["accepted_repairs"] == []
        assert client.get(f"/api/tracks/{track['id']}/beats/correction").json() == result
    assert manifest.read_bytes() == original


@pytest.mark.parametrize("analysis,code", [
    (None, 409),
    ({"status": "processing"}, 409),
    ({"status": "ready", "provider": "other"}, 409),
    ({"status": "ready", "provider": "CPJKU/beat_this", "beats": [2, 1],
      "downbeats": [], "time_signature": 4}, 422),
    ({"status": "ready", "provider": "CPJKU/beat_this"}, 422),
])
def test_correction_failures_are_explicit_and_preserve_source(tmp_path, analysis, code):
    app = create_app(tmp_path, tmp_path / "no-frontend")
    with TestClient(app) as client:
        # Seed after startup so interrupted-analysis recovery cannot alter the snapshot.
        app.state.store.put({"id": "a" * 32, "created_at": "now", "status": "ready",
                             "runs": [], "beat_analysis": analysis})
        manifest = app.state.store.directory("a" * 32) / "track.json"
        original = manifest.read_bytes()
        response = client.get(f"/api/tracks/{'a' * 32}/beats/correction")
        assert response.status_code == code
        assert "grid" not in response.json()
        assert client.get(f"/api/tracks/{'b' * 32}/beats/correction").status_code == 404
    assert manifest.read_bytes() == original

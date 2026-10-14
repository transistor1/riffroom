import json
from pathlib import Path

import pytest
from riffroom.beat_grid_prototype import (
    analyze_downbeat_phase,
    diagnose_beat_grid,
    propose_correction,
)


def test_diagnostic_reports_short_gaps_and_downbeat_contradictions():
    report = diagnose_beat_grid(
        [0, 0.5, 0.75, 1.0, 2.0, 2.5, 3.0],
        [0, 1.0, 2.0],
        4,
    )

    assert report["suspect_interval_indices"] == {
        "short_below_0.70_reference": [1, 2],
        "long_above_1.40_reference": [3],
    }
    assert report["downbeats"]["aligned_count"] == 3
    assert report["downbeats"]["contradictory_adjacent_pairs"] == 2


def test_phase_analysis_separates_raw_and_half_bar_evidence():
    report = analyze_downbeat_phase(
        list(range(25)),
        [0, 4, 8, 10, 12, 14, 16, 20, 24],
        4,
        section_seconds=12,
    )

    assert report["raw_marker_vote"]["winning_phase"] == 0
    assert report["raw_marker_vote"]["winning_share"] == pytest.approx(7 / 9)
    assert report["full_bar_transition_origins"] == {
        "transition_count": 4,
        "phase_histogram": {"0": 4, "1": 0, "2": 0, "3": 0},
    }
    assert report["half_bar_model"]["winning_groups"] == [[0, 2]]
    assert report["half_bar_model"]["equivalence_groups"][0]["share"] == 1
    assert report["half_bar_model"]["adjacent_transition_compatible_share"] == 1
    assert report["sections"][0]["phase_histogram"] == {
        "0": 3,
        "1": 0,
        "2": 1,
        "3": 0,
    }


def test_phase_analysis_validates_section_duration():
    with pytest.raises(ValueError, match="positive finite"):
        analyze_downbeat_phase([0, 1], [0], 4, section_seconds=0)


FIXTURES = Path(__file__).parent / "fixtures"


def mixed_defect_grid(period=0.5):
    pulses = [*range(7), 6.5, 7, 7.5, 8, 9.5, 10, 10.5, 11, 11.5, 12]
    pulses += [12.5 + index for index in range(9)]
    pulses += list(range(21, 81))
    return [pulse * period for pulse in pulses]


@pytest.mark.parametrize("period", [0.25, 0.413, 0.5, 0.83, 1.2])
@pytest.mark.parametrize("meter", [3, 4, 5, 7])
@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_defects_reconstruct_in_either_direction(period, meter, reverse):
    beats = mixed_defect_grid(period)
    if reverse:
        beats = [80 * period - beat for beat in reversed(beats)]
    result = propose_correction(beats, [], meter)
    proposal = result["proposal"]
    assert len(proposal["accepted_repairs"]) == 1
    assert proposal["accepted_repairs"][0]["direction"] == ("forward" if reverse else "backward")
    assert proposal["beats"] == pytest.approx([i * period for i in range(81)])
    for value, origin in zip(proposal["beats"], proposal["beat_origins"]):
        if origin["kind"] == "model":
            assert value == beats[origin["source_index"]]


@pytest.mark.parametrize("meter", [3, 4, 5, 7])
@pytest.mark.parametrize("scenario", ["clean", "quantized", "ramp", "tempo_step", "half_time",
                                      "subdivisions", "missing", "phase", "swing"])
def test_guardrails_preserve_musically_ambiguous_grids(meter, scenario):
    intervals = [0.5] * 160
    if scenario == "quantized":
        intervals = [0.44, 0.48, 0.46, 0.48] * 40
    elif scenario == "ramp":
        intervals = [0.4 + i * 0.001 for i in range(160)]
    elif scenario == "tempo_step":
        intervals[80:] = [0.7] * 80
    elif scenario == "half_time":
        intervals[60:68] = [1.0] * 8
    elif scenario == "subdivisions":
        intervals[60:68] = [0.25] * 8
    elif scenario == "missing":
        intervals[60] = 1.0
    elif scenario == "phase":
        intervals[60], intervals[80] = 0.75, 0.25
    elif scenario == "swing":
        intervals[60:80] = [0.33, 0.67] * 10
    beats = [0.0]
    for interval in intervals:
        beats.append(beats[-1] + interval)
    result = propose_correction(beats, [], meter)
    assert result["proposal"]["beats"] == beats
    assert result["proposal"]["accepted_repairs"] == []


def test_provenance_is_independent_and_downbeats_are_not_reinterpreted():
    beats = mixed_defect_grid()
    original = list(beats)
    downbeats = beats[::4]
    provenance = {"provider": "CPJKU/beat_this", "extra": {"models": ["final0"]}}
    result = propose_correction(beats, downbeats, 4, source_provenance=provenance)
    assert result["source"]["provenance"] == provenance
    result["source"]["provenance"]["extra"]["models"].append("changed")
    assert provenance["extra"]["models"] == ["final0"]
    assert beats == original
    assert result["source"]["beats"] == beats
    assert result["source"]["downbeats"] == downbeats
    assert result["proposal"]["downbeats"] == downbeats


@pytest.mark.parametrize("options", [
    {"flank_size": 0}, {"anchor_intervals": 3}, {"fit_intervals": 5},
    {"maximum_repair_beats": -1}, {"phase_tolerance": float("nan")},
    {"ratio_tolerance": 1}, {"flank_size": 4.5},
])
def test_invalid_policy_is_rejected(options):
    with pytest.raises(ValueError):
        propose_correction(list(range(100)), [], 4, **options)


def test_weak_or_oversized_evidence_is_deferred():
    beats = mixed_defect_grid()
    for options in ({"maximum_repair_beats": 5}, {"anchor_intervals": 100, "fit_intervals": 100},
                    {"phase_tolerance": 0.00001}):
        # Exact synthetic clock needs a separate drifting anchor for the residual gate.
        if "phase_tolerance" in options:
            beats[-20] += 0.002
        result = propose_correction(beats, [], 4, **options)
        assert result["proposal"]["beats"] == beats
        assert result["proposal"]["deferred_regions"]


def test_easy_lover_against_frozen_listening_approved_reference():
    baseline = json.loads((FIXTURES / "easy_lover_approved_groove.json").read_text())
    analysis = baseline["source_analysis"]
    approved = baseline["approved_beats"]
    result = propose_correction(analysis["beats"], analysis["downbeats"], analysis["time_signature"],
                                source_provenance=analysis)
    proposal = result["proposal"]["beats"]
    assert len(proposal) == len(approved) == 646
    assert proposal[:7] == analysis["beats"][:7] == approved[:7]
    assert proposal[28:] == analysis["beats"][38:] == approved[28:]
    errors = [abs(a - b) for a, b in zip(proposal[7:28], approved[7:28])]
    assert sum(errors) / len(errors) == pytest.approx(0.013060798356572954)
    assert max(errors) == pytest.approx(0.03402816901408201)
    assert sum(a == b for a, b in zip(proposal, approved)) == 625
    assert len(result["proposal"]["accepted_repairs"]) == 1
    assert result["source"]["beats"] == analysis["beats"]
    assert result["source"]["downbeats"] == analysis["downbeats"]
    assert result["source"]["provenance"] == analysis
    assert all(a < b for a, b in zip(proposal, proposal[1:]))


def test_approved_local_manifest_remains_exact_if_available():
    import hashlib

    baseline = json.loads((FIXTURES / "easy_lover_approved_groove.json").read_text())
    root = Path(__file__).parents[2]
    manifest_path = root / baseline["manifest_path"]
    if not manifest_path.exists():
        pytest.skip("excluded listening assets unavailable; portable baseline is still tested")
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == baseline["manifest_sha256"]
    assert hashlib.sha256((root / baseline["fixture_path"]).read_bytes()).hexdigest() == baseline["fixture_sha256"]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["variants"][1]["beats_seconds"] == baseline["approved_beats"]
    for audio in baseline["audio_files"].values():
        assert hashlib.sha256((manifest_path.parent / audio["file"]).read_bytes()).hexdigest() == audio["sha256"]


def test_reelin_original_grid_regression():
    baseline = json.loads((FIXTURES / "reelin_original_grid.json").read_text())
    analysis = baseline["source_analysis"]
    result = propose_correction(analysis["beats"], analysis["downbeats"], analysis["time_signature"])
    assert len(analysis["beats"]) == 615
    assert result["proposal"]["beats"] == analysis["beats"]
    assert result["proposal"]["downbeats"] == analysis["downbeats"]
    assert result["proposal"]["accepted_repairs"] == []
    assert len(result["proposal"]["deferred_regions"]) == 4


def test_reference_evaluation_does_not_force_pair_unequal_counts():
    import runpy

    compare = runpy.run_path(str(Path(__file__).parents[2] / "scripts/evaluate_beat_grid.py"))["compare"]
    result = compare([0.0, 0.5, 1.0], [0.0, 1.0])
    assert result["ordered_comparison"] is None
    assert result["proposal_count"] == 3
    assert result["reference_count"] == 2
    assert result["proposal_to_nearest_reference_max_seconds"] == 0.5
    with pytest.raises(ValueError, match="must not be empty"):
        compare([0.0], [])


def test_diagnostic_cli_retains_all_source_metadata():
    import subprocess
    import sys

    baseline = FIXTURES / "easy_lover_approved_groove.json"
    analysis = json.loads(baseline.read_text())["source_analysis"]
    # Actual excluded track includes status/message/error metadata too.
    track = Path(__file__).parents[2] / ".local-test-data/easy-lover-metronome-regression-case-track.json"
    if not track.exists():
        pytest.skip("local track unavailable; core portable regression still runs")
    completed = subprocess.run([sys.executable, "scripts/diagnose_beat_grid.py", str(track), "--full"],
                               cwd=Path(__file__).parents[2], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["source"]["provenance"] == {
        key: value for key, value in analysis.items() if key not in {"beats", "downbeats"}
    }
    assert result["policy"]["mode"].startswith("diagnostic_only")

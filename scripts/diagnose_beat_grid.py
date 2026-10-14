"""Print a reproducible, read-only beat-grid diagnostic/prototype report."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from riffroom.beat_grid_prototype import analyze_downbeat_phase, propose_correction  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("track_json", type=Path)
    parser.add_argument(
        "--full",
        action="store_true",
        help="include source/proposed timestamp arrays and per-beat provenance",
    )
    args = parser.parse_args()
    track = json.loads(args.track_json.read_text())
    analysis = track["beat_analysis"]
    metadata = {
        key: value
        for key, value in analysis.items()
        if key not in {"beats", "downbeats"}
    }
    result = propose_correction(
        analysis["beats"],
        analysis["downbeats"],
        analysis["time_signature"],
        source_provenance=metadata,
    )
    result["source_phase_analysis"] = analyze_downbeat_phase(
        analysis["beats"], analysis["downbeats"], analysis["time_signature"]
    )
    result["proposal_phase_analysis"] = analyze_downbeat_phase(
        result["proposal"]["beats"],
        analysis["downbeats"],
        analysis["time_signature"],
    )
    if not args.full:
        result = {
            "track": {
                "id": track.get("id"),
                "title": track.get("title"),
                "duration": track.get("duration"),
            },
            "prototype_version": result["prototype_version"],
            "policy": result["policy"],
            "source_provenance": result["source"]["provenance"],
            "accepted_repairs": result["proposal"]["accepted_repairs"],
            "deferred_regions": result["proposal"]["deferred_regions"],
            "source_diagnostics": result["source_diagnostics"],
            "proposal_diagnostics": result["proposal_diagnostics"],
            "source_phase_analysis": result["source_phase_analysis"],
            "proposal_phase_analysis": result["proposal_phase_analysis"],
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

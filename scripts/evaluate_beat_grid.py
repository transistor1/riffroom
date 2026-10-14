"""Compare a diagnostic proposal with an explicit reference; never tune to it.

Reference JSON must contain an exact beat array at --reference-key (default:
beats). Musical identity and reference data never enter the repair algorithm.
"""

import argparse
import json
import statistics
import sys
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from riffroom.beat_grid_prototype import propose_correction  # noqa: E402


def compare(proposal: list[float], reference: list[float]) -> dict:
    if not reference:
        raise ValueError("Reference beats must not be empty.")
    nearest_errors = []
    for value in proposal:
        index = bisect_left(reference, value)
        nearest_errors.append(min(abs(value - reference[i]) for i in (index - 1, index)
                                  if 0 <= i < len(reference)))
    result = {
        "proposal_count": len(proposal), "reference_count": len(reference),
        "proposal_to_nearest_reference_mean_seconds": statistics.mean(nearest_errors),
        "proposal_to_nearest_reference_max_seconds": max(nearest_errors),
        "warning": "reference comparison is evaluation, not independent musical validation",
    }
    if len(proposal) == len(reference):
        errors = [abs(a - b) for a, b in zip(proposal, reference)]
        result["ordered_comparison"] = {
            "exact_count": sum(a == b for a, b in zip(proposal, reference)),
            "mean_absolute_seconds": statistics.mean(errors), "max_absolute_seconds": max(errors),
            "mismatches": [{"index": i, "proposal": a, "reference": b, "delta_seconds": a - b}
                           for i, (a, b) in enumerate(zip(proposal, reference)) if a != b],
        }
    else:
        result["ordered_comparison"] = None  # Never silently align unequal sequences by index.
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("track_json", type=Path)
    parser.add_argument("reference_json", type=Path)
    parser.add_argument("--reference-key", default="beats")
    args = parser.parse_args()
    track = json.loads(args.track_json.read_text())
    analysis = track.get("beat_analysis", track.get("source_analysis", track))
    reference = json.loads(args.reference_json.read_text())[args.reference_key]
    result = propose_correction(analysis["beats"], analysis["downbeats"], analysis["time_signature"],
                                source_provenance=analysis)
    report = compare(result["proposal"]["beats"], reference)
    report["accepted_repairs"] = result["proposal"]["accepted_repairs"]
    report["deferred_regions"] = result["proposal"]["deferred_regions"]
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

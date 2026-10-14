"""Read-only beat-grid diagnostics and an intentionally isolated repair prototype.

The experimental web toggle calls this same conservative proposal without
changing its diagnostic policy. It never mutates a persisted Beat This! result.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from copy import deepcopy


def _intervals(beats: list[float]) -> list[float]:
    return [right - left for left, right in zip(beats, beats[1:])]


def _rounded_counts(values: list[float], digits: int = 2) -> dict[str, int]:
    counts = Counter(round(value, digits) for value in values)
    return {f"{value:.{digits}f}": count for value, count in sorted(counts.items())}


def _nearest_beat(beats: list[float], value: float) -> tuple[int, float]:
    index = min(range(len(beats)), key=lambda candidate: abs(beats[candidate] - value))
    return index, abs(beats[index] - value)


def diagnose_beat_grid(
    beats: list[float],
    downbeats: list[float],
    time_signature: int,
    *,
    alignment_tolerance: float = 0.07,
) -> dict:
    """Return deterministic measurements without judging musical correctness."""
    if len(beats) < 2 or time_signature < 1:
        raise ValueError("A diagnostic grid needs two beats and a positive time signature.")
    if any(not math.isfinite(value) for value in [*beats, *downbeats]):
        raise ValueError("Beat-grid times must be finite.")
    if any(right <= left for left, right in zip(beats, beats[1:])):
        raise ValueError("Beats must be strictly increasing.")

    intervals = _intervals(beats)
    reference = statistics.median(intervals)
    short = [index for index, value in enumerate(intervals) if value < reference * 0.70]
    long = [index for index, value in enumerate(intervals) if value > reference * 1.40]
    mapped = [_nearest_beat(beats, value) for value in downbeats]
    aligned = [(index, residual) for index, residual in mapped if residual <= alignment_tolerance]
    aligned_indices = [index for index, _ in aligned]
    step_counts = Counter(right - left for left, right in zip(aligned_indices, aligned_indices[1:]))
    contradictions = sum(
        step % time_signature != 0
        for step in (right - left for left, right in zip(aligned_indices, aligned_indices[1:]))
    )
    phase_counts = Counter(index % time_signature for index in aligned_indices)

    return {
        "beat_count": len(beats),
        "downbeat_count": len(downbeats),
        "interval_seconds": {
            "minimum": min(intervals),
            "median_reference": reference,
            "maximum": max(intervals),
            "rounded_histogram": _rounded_counts(intervals),
        },
        "suspect_interval_indices": {
            "short_below_0.70_reference": short,
            "long_above_1.40_reference": long,
        },
        "downbeats": {
            "alignment_tolerance_seconds": alignment_tolerance,
            "aligned_count": len(aligned),
            "unaligned_count": len(downbeats) - len(aligned),
            "maximum_alignment_error_seconds": max((residual for _, residual in mapped), default=0.0),
            "beat_step_histogram": {str(step): count for step, count in sorted(step_counts.items())},
            "contradictory_adjacent_pairs": contradictions,
            "phase_histogram": {str(phase): phase_counts.get(phase, 0) for phase in range(time_signature)},
        },
    }


def analyze_downbeat_phase(
    beats: list[float],
    downbeats: list[float],
    time_signature: int,
    *,
    alignment_tolerance: float = 0.07,
    section_seconds: float = 30.0,
) -> dict:
    """Describe model-marker phase without treating those markers as truth.

    The scores are deliberately empirical vote fractions, not calibrated
    probabilities.  For an even meter, the half-bar equivalence groups show
    how much evidence survives when a detector may mark both beat 1 and beat 3.
    """
    if section_seconds <= 0 or not math.isfinite(section_seconds):
        raise ValueError("Phase-analysis sections need a positive finite duration.")

    diagnostics = diagnose_beat_grid(
        beats,
        downbeats,
        time_signature,
        alignment_tolerance=alignment_tolerance,
    )
    mapped = [
        (value, *_nearest_beat(beats, value))
        for value in downbeats
    ]
    aligned = [
        (value, index)
        for value, index, residual in mapped
        if residual <= alignment_tolerance
    ]
    indices = [index for _, index in aligned]
    phase_counts = Counter(index % time_signature for index in indices)
    ranked = sorted(range(time_signature), key=lambda phase: (-phase_counts[phase], phase))
    total = len(indices)
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else winner

    steps = [right - left for left, right in zip(indices, indices[1:])]
    full_bar_origins = Counter(
        left % time_signature
        for left, right in zip(indices, indices[1:])
        if right - left == time_signature
    )

    section_counts: dict[int, Counter] = {}
    for value, index in aligned:
        section = math.floor(value / section_seconds)
        section_counts.setdefault(section, Counter())[index % time_signature] += 1
    sections = []
    for section, counts in sorted(section_counts.items()):
        maximum = max(counts.values())
        sections.append(
            {
                "time_start": section * section_seconds,
                "time_end": (section + 1) * section_seconds,
                "aligned_count": sum(counts.values()),
                "phase_histogram": {
                    str(phase): counts.get(phase, 0) for phase in range(time_signature)
                },
                "dominant_phases": [
                    phase for phase in range(time_signature) if counts[phase] == maximum
                ],
            }
        )

    half_bar = None
    if time_signature % 2 == 0:
        half = time_signature // 2
        groups = []
        for phase in range(half):
            phases = [phase, phase + half]
            count = sum(phase_counts[item] for item in phases)
            groups.append(
                {
                    "phases": phases,
                    "count": count,
                    "share": count / total if total else 0.0,
                }
            )
        group_maximum = max((group["count"] for group in groups), default=0)
        half_bar = {
            "equivalence_groups": groups,
            "winning_groups": [
                group["phases"] for group in groups if group["count"] == group_maximum
            ],
            "adjacent_transition_compatible_count": sum(
                step % half == 0 for step in steps
            ),
            "adjacent_transition_compatible_share": (
                sum(step % half == 0 for step in steps) / len(steps) if steps else 0.0
            ),
            "interpretation": "supports phase modulo half a bar; cannot distinguish the two phases",
        }

    return {
        "warning": "model-marker vote fractions are not ground-truth probabilities",
        "aligned_count": total,
        "unaligned_count": diagnostics["downbeats"]["unaligned_count"],
        "phase_histogram": {
            str(phase): phase_counts.get(phase, 0) for phase in range(time_signature)
        },
        "raw_marker_vote": {
            "winning_phase": winner,
            "winning_share": phase_counts[winner] / total if total else 0.0,
            "margin_over_runner_up": (
                (phase_counts[winner] - phase_counts[runner_up]) / total if total else 0.0
            ),
        },
        "full_bar_transition_origins": {
            "transition_count": sum(full_bar_origins.values()),
            "phase_histogram": {
                str(phase): full_bar_origins.get(phase, 0)
                for phase in range(time_signature)
            },
        },
        "half_bar_model": half_bar,
        "sections": sections,
    }


def _stable_runs(intervals: list[float], tolerance: float) -> list[tuple[int, int]]:
    """Maximal local cadence runs; no whole-song median is used for repair."""
    runs = []
    start = 0
    while start < len(intervals):
        end = start + 1
        while end < len(intervals):
            window = intervals[start : end + 1]
            period = statistics.mean(window)
            if max(abs(value / period - 1) for value in window) > tolerance:
                break
            end += 1
        runs.append((start, end))  # exclusive interval endpoint = final beat index
        start = end
    return runs


def _clock(beats: list[float], start: int, end: int) -> tuple[float, float]:
    """OLS slope, with phase pinned to an exact source timestamp."""
    values = beats[start : end + 1]
    center = (len(values) - 1) / 2
    mean = statistics.mean(values)
    period = sum((i - center) * (value - mean) for i, value in enumerate(values)) / sum(
        (i - center) ** 2 for i in range(len(values))
    )
    residual = max(abs(value - (values[0] + i * period)) for i, value in enumerate(values))
    return period, residual


def propose_correction(
    beats: list[float],
    downbeats: list[float],
    time_signature: int,
    *,
    source_provenance: dict | None = None,
    ratio_tolerance: float = 0.10,
    flank_size: int = 4,
    maximum_repair_beats: int = 32,
    anchor_intervals: int = 24,
    fit_intervals: int = 64,
    phase_tolerance: float = 0.08,
) -> dict:
    """Propose local clock continuation; never enables playback or infers accents.

    Timestamp evidence alone cannot distinguish an isolated harmonic tracking
    error from a real half-time/subdivision passage. Those regions are deferred.
    Acceptance requires *mixed* interval defects plus matching cadence and phase
    on both sides, including one long stable anchor. Stable off-phase plateaus
    inside that bounded uncertain span are not treated as trustworthy anchors.
    This is an empirical evidence gate, not a calibrated musical probability.
    """
    diagnostics = diagnose_beat_grid(beats, downbeats, time_signature)
    if not (0 < ratio_tolerance <= 0.15 and 0 < phase_tolerance <= 0.15):
        raise ValueError("Cadence and phase tolerances must be positive and at most 0.15.")
    if any(type(value) is not int or value < 1 for value in (
        flank_size, maximum_repair_beats, anchor_intervals, fit_intervals
    )) or flank_size < 2 or anchor_intervals < flank_size or fit_intervals < anchor_intervals:
        raise ValueError("Invalid positive integer anchor/repair limits.")

    intervals = _intervals(beats)
    runs = _stable_runs(intervals, ratio_tolerance)
    anchors = [(start, end) for start, end in runs if end - start >= anchor_intervals]
    accepted, deferred = [], []
    candidates = []
    # Include a short, stable prefix/suffix as corroboration, never as sole anchor.
    supports = [(start, end) for start, end in runs if end - start >= flank_size]
    if anchors:
        first, last = anchors[0], anchors[-1]
        left = next((run for run in supports if run[1] < first[0]), None)
        if left:
            candidates.append((left, first, "backward"))
        elif first[0] > 0:
            deferred.append({"time_start": beats[0], "time_end": beats[first[0]],
                             "reason": "no_left_phase_corroboration"})
        candidates.extend((left, right, "backward") for left, right in zip(anchors, anchors[1:]))
        right = next((run for run in reversed(supports) if run[0] > last[1]), None)
        if right:
            candidates.append((last, right, "forward"))
        elif last[1] < len(beats) - 1:
            deferred.append({"time_start": beats[last[1]], "time_end": beats[-1],
                             "reason": "no_right_phase_corroboration"})
    else:
        deferred.append({"time_start": beats[0], "time_end": beats[-1],
                         "reason": "no_long_stable_anchor"})

    edits = []
    for left_run, right_run, direction in candidates:
        start, end = left_run[1], right_run[0]
        if end <= start:
            continue
        anchor = right_run if direction == "backward" else left_run
        fit_start = anchor[0] if direction == "backward" else max(anchor[0], anchor[1] - fit_intervals)
        fit_end = min(anchor[1], fit_start + fit_intervals)
        period, residual = _clock(beats, fit_start, fit_end)
        origin_index = fit_start if direction == "backward" else fit_end
        origin = beats[origin_index]
        # Pin either direction to a source beat, not the fitted intercept.
        def phase_error(value: float) -> float:
            return abs((value - origin) / period - round((value - origin) / period))
        span_count = round((beats[end] - beats[start]) / period)
        record = {
            "interval_index_start": start, "interval_index_end": end - 1,
            "time_start": beats[start], "time_end": beats[end],
            "original_interval_count": end - start, "proposed_interval_count": span_count,
            "proposed_interval_seconds": period, "direction": direction,
            "anchor_source_indices": [fit_start, fit_end],
            "anchor_period_seconds": period, "anchor_max_residual_seconds": residual,
            "confidence": "uncalibrated_structural_evidence",
        }
        left_values = intervals[max(left_run[0], start - flank_size) : start]
        right_values = intervals[end : min(right_run[1], end + flank_size)]
        region = intervals[start:end]
        short = any(value < period * 0.70 for value in region)
        long = any(value > period * 1.40 for value in region)
        reason = None
        if span_count < 1 or span_count > maximum_repair_beats:
            reason = "region_too_large_or_short"
        elif residual > phase_tolerance * period:
            reason = "anchor_phase_drift"
        elif any(abs(statistics.mean(values) / period - 1) > ratio_tolerance
                 for values in (left_values, right_values)):
            reason = "flanks_disagree_possible_tempo_change"
        elif any(phase_error(value) > phase_tolerance for value in (
            *beats[max(left_run[0], start - flank_size) : start + 1],
            *beats[end : min(right_run[1], end + flank_size) + 1],
        )):
            reason = "phase_discontinuity_or_tempo_change_at_boundary"
        elif not (short and long) or span_count == end - start:
            reason = "ambiguous_harmonic_or_phase_change"
        if reason:
            record["reason"] = reason
            deferred.append(record)
            continue

        lo = round((beats[start] - origin) / period) + 1
        hi = round((beats[end] - origin) / period)
        interior, origins = [], []
        used = set()
        for offset in range(lo, hi):
            value = origin + offset * period
            index = min(range(start + 1, end), key=lambda i: abs(beats[i] - value), default=None)
            if index is not None and abs(beats[index] - value) <= phase_tolerance * period:
                # Keep reliable source timestamps byte-for-byte, including quantization.
                interior.append(beats[index])
                origins.append({"kind": "model", "source_index": index})
                used.add(index)
            else:
                interior.append(value)
                origins.append({"kind": "groove_continuation_prototype",
                                "anchor_source_indices": [fit_start, fit_end],
                                "pulse_offset": offset})
        record.update(kind="mixed_subdivision_missing_pulse_or_phase_repair",
                      preserved_interior_source_indices=sorted(used),
                      removed_source_indices=[i for i in range(start + 1, end) if i not in used])
        accepted.append(record)
        edits.append((start, end, interior, origins))

    corrected = list(beats)
    origins = [{"kind": "model", "source_index": index} for index in range(len(beats))]
    for start, end, interior, interior_origins in reversed(edits):
        corrected[start + 1 : end] = interior
        origins[start + 1 : end] = interior_origins
    return {
        "prototype_version": 2,
        "policy": {
            "ratio_tolerance": ratio_tolerance, "phase_tolerance": phase_tolerance,
            "flank_size": flank_size, "anchor_intervals": anchor_intervals,
            "fit_intervals": fit_intervals, "maximum_repair_beats": maximum_repair_beats,
            "mode": "diagnostic_only; explicit invocation; no playback integration",
            "downbeat_policy": "preserve_only; do not infer accents",
            "ambiguous_harmonic_policy": "defer without independent musical evidence",
        },
        "source": {"beats": list(beats), "downbeats": list(downbeats),
                   "time_signature": time_signature, "provenance": deepcopy(source_provenance or {})},
        "proposal": {"beats": corrected, "beat_origins": origins, "downbeats": list(downbeats),
                     "accepted_repairs": accepted, "deferred_regions": deferred},
        "source_diagnostics": diagnostics,
        "proposal_diagnostics": diagnose_beat_grid(corrected, downbeats, time_signature),
    }

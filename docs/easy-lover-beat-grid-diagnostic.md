# Conservative beat-grid continuation prototype (v2)

The algorithm is available through a read-only CLI and the opt-in EXPERIMENTAL
beat correction toggle. BeatJobs and stored analysis remain unchanged. See
[usage and current validation](experimental-beat-correction.md). No
song IDs, titles, reference timestamps, or approved fixes enter the algorithm.
The approved reference is used **only by tests and evaluation**.

## Preserved listening baseline

Before implementing v2, the exact user-listening-approved
`B_candidate_intro-groove-continuation` array, accent times, source analysis,
anchor/edit metadata and audio hashes were copied from the existing excluded
`.local-test-data/easy-lover-groove-anchor-20261014/clips/manifest.json` into
`backend/tests/fixtures/easy_lover_approved_groove.json`. The excluded original
manifest, WAVs and track fixture remain unchanged. Tests verify their hashes
when available; the portable JSON regression always runs without audio.

The source fixture SHA-256 is
`eb7b096dd4cce142d9ac04e188f87ad99cbe19bdf0ed23c35bd4499702887166`.
The approved B grid has 646 beats. It preserves source indices 0–6 and all 618
source beats from 13.40 s onward; it supplies 21 pulses between those endpoints.
Its historical anchor is 27.36 s, period 0.4655720992622401 s. Those values are
reference metadata, never algorithm parameters. Accent orientation remains a
listening convention, not verified bar numbering.

## Algorithm and guardrails

Repair uses local cadence runs, not the whole-song median. A run's intervals
must stay within 10% of their local mean. A long anchor requires 24 consecutive
intervals, with a least-squares slope fitted to at most 64 intervals. Phase is
pinned to an exact original timestamp, rather than a fitted intercept. Maximum
anchor residual is 8% of a pulse. The support on the opposite side needs four
stable intervals; both flank cadence and pulse phase must agree with the clock.
The maximum proposed repair span is 32 pulses.

The uncertain span can include a short, stable but off-phase plateau between
tracking defects. It is reconstructed backward from a later long anchor, or
forward from an earlier long anchor when only short trailing support exists.
Only spans with both short (<70% of anchor period) and long (>140%) intervals
and a changed pulse count qualify. Isolated subdivisions, missing pulses,
half-time runs and count-preserving phase shifts are detected/deferred rather
than automatically treated as errors. Tempo steps, ramps, quantization, swing
and insufficient phase support have dedicated preservation tests. A short
harmonic plateau cannot serve as the long anchor under the default policy.

Inside an accepted span, a source timestamp within 8% of a predicted pulse is
kept exactly; otherwise a new clock pulse is proposed. Outside the uncertain
interior, every original timestamp survives exactly. Each output beat carries
its original index or reconstruction anchor and pulse offset. Removed and
preserved interior source indices are explicit. Original beats, downbeats,
meter and a deep copy of provenance remain in the result. Downbeats are never
moved, inferred, deleted or interpreted as playback accents.

These are empirical structural gates, **not calibrated confidence probabilities**.
Timestamp evidence cannot prove that a mixed subdivision/gap pattern is a
tracking error instead of intentional music. The prototype can also abstain
from genuine isolated missing beats. It does not use audio to distinguish
instruments, syncopation or musical beat function. A legitimate mixed rhythmic
passage could satisfy the same gates; this is a material reason to retain the
opt-in diagnostic boundary. Thresholds need evaluation beyond these two songs.

## Objective result against approved B

`docs/beat-grid-prototype-evaluation.json` records every mismatch. The reference
is supplied to evaluation only after the proposal has been computed.

| Measurement | Result |
| --- | --- |
| Source / proposal / approved beat counts | 656 / 646 / 646 |
| Proposed repair | source indices 7–37; bounds 3.16–13.40 s |
| Automatically selected anchor fit | source indices 38–102; 13.40–43.20 s |
| Fitted period | 0.46560139860139854 s |
| Maximum anchor residual | 22.406 ms |
| Exact approved timestamps | 625 of 646 |
| First seven source timestamps | exact |
| All 618 source timestamps from 13.40 s onward | exact |
| Mean absolute difference, 21 repaired pulses | 13.061 ms |
| Maximum absolute difference | 34.028 ms |
| Full-song mean absolute difference | 0.425 ms |

The 21 repaired pulses all differ from B; there is no silent force-fitting.
Ten are source timestamps near the clock, retained exactly under the preservation
policy; eleven are synthesized. B replaced all 21. The automatic fit begins at
the first qualifying stable suffix (13.40 s), whereas B used the manually chosen
later groove at 27.36 s. For synthesized pulses, that anchor/phase difference
produces roughly 6.7–7.1 ms offsets from B. Preserving ten source timestamps
accounts for the larger offsets, including the maximum at 7.84 s versus B's
7.805971831 s. Similarity to an approved reference is regression evidence;
this altered proposal itself has not received listening approval.

The v1 bounded interpolation (12 intervals between 3.16 and 8.52 s) is superseded.
It compressed the period to 0.446666667 s and retained a subsequent off-phase
plateau. v2 does not reuse that endpoint-fitting strategy or infer bar phase.

## Reelin' in the Years

Local original audio and a completed analysis were available read-only via
`data/tracks/6bdbfc9324434ee297da4c083795bba8/`. The `data` directory is a
symlink outside this worker root; no file there was written. A portable copy of
the source analysis and track hash is in
`backend/tests/fixtures/reelin_original_grid.json`.

All 615 beats and all downbeats remain exactly unchanged. Four candidate regions
are deferred for anchor phase drift (around 44–48, 59–63, 89–91 and 172–178 s).
This verifies grid non-regression, not perceptual correctness; no new audio
inference or listening validation was performed.

## Reproduce and integration gate

From the worker root:

```sh
.env/bin/python -m pytest backend/tests/test_beat_grid_prototype.py -q
.env/bin/python -m pytest -q
.env/bin/python -m ruff check backend scripts
.env/bin/python scripts/diagnose_beat_grid.py .local-test-data/easy-lover-metronome-regression-case-track.json --full
.env/bin/python scripts/evaluate_beat_grid.py .local-test-data/easy-lover-metronome-regression-case-track.json backend/tests/fixtures/easy_lover_approved_groove.json --reference-key approved_beats
.env/bin/python scripts/diagnose_beat_grid.py data/tracks/6bdbfc9324434ee297da4c083795bba8/track.json
```

Synthetic tests cover mixed defects in both continuation directions at five
pulse periods (0.25–1.2 s), meters 3/4/5/7, clean and quantized grids, gradual
and abrupt tempo changes, bounded half-time, subdivisions, isolated missing
pulses, phase shifts, swing, weak/oversized evidence and provenance isolation.
The evaluation CLI refuses ordered index comparison when counts differ and
reports nearest-reference distance with its limitation instead.

Recommended integration gate: retain diagnostic-only operation until the actual
v2 proposal passes listening review at both splices and throughout the repaired
intro, and a musician-reviewed multi-song corpus demonstrates an agreed false
repair rate across tempo changes, odd meter, swing, sparse and syncopated music.
Require exact preservation outside reviewed spans, explicit abstention reasons,
separate bar/downbeat validation, retained source arrays/provenance, and an
explicit user opt-in before any playback use. The approved B reference does not
authorize v2's differing timestamps or accents automatically.

## Validation actually run (2026-10-14)

- `.env/bin/python -m pytest backend/tests/test_beat_grid_prototype.py -q`:
  **93 passed**, including local manifest/fixture/WAV hash checks.
- `.env/bin/python -m ruff check backend scripts`: **passed**.
- `.env/bin/python -m pytest -q`: **336 passed, 2 skipped, 1 failed**.
  The failure is `test_core_lock_closure_on_supported_python_and_platforms`:
  installed setuptools is 84.0.0 while `requirements-core-lock.txt` pins 83.0.0.
  No dependency or lock-file change was attempted.
- `npm test -- --reporter=dot` from `frontend`: **77 passed**, five test files.
- Both diagnostic CLI commands above completed successfully; Easy Lover
  evaluation generated the accompanying JSON containing all 21 mismatches.
- `git diff --check`: passed (these prototype files were already untracked or
  newly created, so this alone is not a whitespace check of their contents).

Exact files changed by this task (relative to the worker root):

- `backend/riffroom/beat_grid_prototype.py` (existing untracked prototype)
- `backend/tests/test_beat_grid_prototype.py` (existing untracked tests)
- `backend/tests/fixtures/easy_lover_approved_groove.json` (new)
- `backend/tests/fixtures/reelin_original_grid.json` (new)
- `scripts/diagnose_beat_grid.py` (existing untracked CLI; retain all metadata)
- `scripts/evaluate_beat_grid.py` (new)
- `docs/beat-grid-prototype-evaluation.json` (new)
- `docs/easy-lover-beat-grid-diagnostic.md` (existing untracked report)

The pre-existing untracked `data` symlink is untouched. No staging, commit,
branch operation, merge or push was performed.

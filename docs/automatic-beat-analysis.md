# Automatic beat preparation

Import queues one Beat This! analysis of `original.wav` after creating the song
and starting stem separation. Beat jobs use their own queue and background thread;
playback and separation do not wait for inference or weights. The first run can
download the checkpoint described in README.

Opening an older song with no analysis sends `POST /api/tracks/{id}/beats/prepare`.
The backend checks the current manifest under the store lock. Ready, queued,
processing, and failed attempts are retained. Duplicate opens, polling, take
changes, and browser reloads cannot requeue them. Missing dependencies produce a
persisted error without failing import. On server restart, interrupted queued or
processing analyses become errors rather than silently restarting.

Only an error displays the compact **Retry** button. It uses the existing
`POST /api/tracks/{id}/beats` endpoint, which permits retry of an error while
keeping active and ready analyses unchanged. Successful analysis retains the raw
source grid and provenance. Beat correction remains the compact, remembered,
default-off toggle; click/count-in still use the selected source/corrected grid
and the existing SoundTouch path.

## Validation (2026-10-14)

- `.env/bin/python -m pytest -q`: 348 passed, 2 skipped, 1 failed. The unrelated
  `test_core_lock_closure_on_supported_python_and_platforms` expects setuptools
  83.0.0; this environment has 84.0.0. Environment and lockfile were left unchanged.
- `.env/bin/python -m pytest -q backend/tests/test_app.py backend/tests/test_beat_correction.py`:
  70 passed after adding the queued-second-import case. Covers automatic import,
  original-mix provenance, missing dependencies, failure/manual retry, duplicate
  opens and requests, independent audio/separation access, serial beat queue,
  immutable ready results, and restart recovery.
- `.env/bin/python -m ruff check backend/riffroom/app.py backend/riffroom/beats.py backend/tests/test_app.py`:
  passed. Initial import-order lint finding was corrected.
- Frontend `npm run build`: passed (TypeScript and Vite).
- Frontend `npm test` and `npm test -- --maxWorkers=1`: stalled without test
  results and were interrupted. The first run emitted a Node localStorage warning.
  `npm test -- --pool=threads --maxWorkers=1` also produced no results and
  reached a 45-second subprocess timeout (exit 124).
- Browser tests could not run: `npm run dev -- --host 127.0.0.1 --port 8766`
  failed with `listen EPERM` under worker permissions. No permission escalation
  or alternate server was attempted. Process inspection was also denied.
- An initial dev-server invocation from the repository root failed because
  `package.json` is in `frontend`; the invocation above used the correct directory.

Added `frontend/e2e/automatic-beats.spec.ts` for legacy opening, reloads, pending
and failed playback, and manual retry. Existing beat-correction browser checks
remain unchanged. These browser checks were not executed here.

## Manual checks still needed

1. With Beat This! installed, import a song and play the original while beat
   analysis and stem separation run. Confirm one analysis and one persisted grid.
2. Open a legacy song with no analysis in two tabs, reload while queued/processing,
   and switch takes. Confirm one inference. Reopen a ready song and verify no run.
3. Disable the optional dependency or simulate inference failure. Confirm music
   remains usable, errors persist through reopen, and only explicit Retry restarts
   analysis after fixing the cause. Restart the server during an active analysis
   and confirm the interrupted error also requires Retry.
4. Listen to source/corrected click and count-in Off/1–4 bars at normal and reduced
   speed through SoundTouch. Confirm exact playhead/loop boundaries, correction
   switching, and remembered toggle state. No listening check was performed here.

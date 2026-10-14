# Experimental beat correction

The experimental **Beat correction** button appears beside Count-in and Click
when a song has stored ready beat analysis. It defaults off; an explicit choice
is remembered per song in this browser, including across separation results.
Off uses the original Beat This! grid. On uses a conservative proposal derived
from stored analysis, without inference, downloads, audio edits or manifest
writes. Switching grids cancels queued clicks and resumes at the current
position, speed, pitch and click volume without a new count-in.

The toggle retains its active/inactive styling and pressed state. State details
appear in its hover tooltip and accessible description, without persistent text
beside the controls:

- **Off:** the original source grid is used.
- **Applied:** a conservative beat repair is used; original analysis is preserved.
- **No confident repair:** correction is on, but the source grid is unchanged.
- **Preparing:** the proposal is pending. If correction is on, click and count-in
  are unavailable; turn correction off to restore the source grid while waiting.
- **Failed:** the tooltip and accessible description include the error and recovery
  guidance. **Retry correction** remains visible, with the same error details.
  If correction is on, click and count-in remain unavailable until correction is
  turned off or a retry succeeds. If off, the source grid remains available.

Music remains available during pending/failed correction. Downbeats are preserved;
bar/downbeat correction is not solved. Switching proposals does not establish
musical accent accuracy. The feature remains experimental and off by default.

## Launch this worktree

Use a normal terminal outside the restricted worker sandbox. From
`/Users/russosv/Documents/repos/riffroom/riffroom-worktree-test`:

```sh
npm run build --prefix frontend
RIFFROOM_DATA="$PWD/.local-test-data/practice" .env/bin/python -m uvicorn riffroom.app:app --host 127.0.0.1 --port 8876
```

Open http://127.0.0.1:8876. This serves this worktree's built interface and API
directly, without launcher reuse of another server. The isolated library starts
empty. To reuse existing analysis without reanalysis, copy desired track
directories into `.local-test-data/practice/tracks` **before starting**, e.g.:

```sh
mkdir -p .local-test-data/practice/tracks
cp -R data/tracks/fb1acac42a9e4cf1aef343e88631bbb6 .local-test-data/practice/tracks/
cp -R data/tracks/6bdbfc9324434ee297da4c083795bba8 .local-test-data/practice/tracks/
```

These are local Easy Lover and Reelin. Copy once into empty destinations;
audio/stems can require substantial disk space. The `data` symlink points
outside this worker root and was not written by this task. Ready analyses are reused without inference. New imports queue analysis automatically;
older songs without analysis start once on open. Failed or interrupted attempts
require **Retry**. Beat This! remains an optional installation described in README.

## Practice checks still needed

Compare source/corrected click through Easy Lover's intro and repair splices
(3.16–13.40 s). Try count-in Off and 1–4 bars, exact and between-beat playheads,
speed 0.5/0.75/0.9/1/1.1/1.25×, independent pitch, and selected loops crossing
repair boundaries. Switch while playing and paused; check position, click volume,
accents and duplicate handoff pulses. Pause/resume should not repeat count-in;
Stop then Play should. Reelin's on/off grid should sound unchanged. Reload checks
per-song persistence. Failure should expose its error through the tooltip/accessibility description,
keep Retry visible, and silence click/count-in until disabled or retried.

The algorithm produces 646 Easy Lover beats, preserving the first seven and all
618 source beats from 13.40 s onward. Repaired pulses differ from the earlier
listening-approved B reference by up to 34.028 ms; this proposal needs listening
review. Reelin's 615 beats and downbeats remain exact. The new
`backend/tests/fixtures/easy_lover_correction.json` freezes actual algorithm
output for frontend playback tests; the backend endpoint test verifies its grid
against current output. The original approved fixture remains unchanged.

## Validation in this restricted worker (2026-10-14)

- `.env/bin/python -m pytest -q`: initial run **343 passed, 2 skipped, 1 failed**.
  Failure: `test_core_lock_closure_on_supported_python_and_platforms`, installed
  setuptools **84.0.0** versus locked **83.0.0**. No dependency/lockfile edits.
- `.env/bin/python -m pytest backend/tests/test_beat_correction.py backend/tests/test_beat_grid_prototype.py -q -rs`:
  **100 passed**, including all seven endpoint fixture cases and local original
  manifest/fixture/WAV hashes. Earlier seven fixture failures do not reproduce.
  Prior failure logs were unavailable in this root; current fixtures include
  startup metadata and seed failure snapshots after startup so interrupted
  analysis recovery cannot alter them.
- `npm test --prefix frontend`: stalls after Vitest's RUN banner with no test
  results. `--pool=threads` also produced no results. A bounded full-suite
  attempt stopped after **35 seconds**, exit **124**. The earlier count-in
  failure cannot be claimed verified fixed. Current regression forbids inventing
  an interior pulse in a detector gap; six-speed SoundTouch handoff and live
  switching tests now use actual proposals rather than approved references.
- `npm run build --prefix frontend`: TypeScript and Vite production build passed.
- `.env/bin/python -m ruff check backend scripts` and `git diff --check`: passed.
- Isolated Uvicorn launch: startup succeeded, loopback bind failed with
  **operation not permitted**. No listening server remained.
- `npm run test:e2e --prefix frontend -- beat-correction.spec.ts`: first found
  a Node JSON import-attribute error, fixed using `readFileSync`. Rerun collected
  **2 tests**, both failed before test bodies: Chrome **SIGABRT**, cleanup
  **kill EPERM**. No GUI or audible SoundTouch validation occurred; permission
  boundaries were not bypassed. With the server above in a normal terminal, run:
  `RIFFROOM_TEST_URL=http://127.0.0.1:8876 npm run test:e2e --prefix frontend -- beat-correction.spec.ts`.
  This uses routed API/audio fixtures with real browser audio plumbing; backend
  tests separately check actual endpoint output and immutable raw data.

Final post-edit reruns:

- `.env/bin/python -m pytest -q -rs`: **343 passed, 2 skipped, 1 failed** in
  9.42 s. The same setuptools mismatch is the sole failure. Both skips are
  `backend/tests/test_demucs_cache.py`: MLX GPU/cached weights required.
  All correction/prototype tests, including the new playback-fixture equality,
  passed in this full run.
- `npm test --prefix frontend` (bounded by Python `subprocess.run(..., timeout=35)`):
  again no completion or individual test results; **exit 124** after 35 s.
- `npm run build --prefix frontend`: **passed**, TypeScript and Vite; 1594
  modules transformed, including production SoundTouch processor asset.
- `.env/bin/python -m ruff check backend scripts` and `git diff --check`:
  **passed**.

Readiness: available for
**experimental listening/practice review** outside the sandbox, not fully
validated. Frontend suite completion, browser execution and audible
speed/pitch/loop/accent review remain open. Correction stays off by default.
No Git state operations or unrelated dependency changes were performed.

Files edited in this continuation:

- `backend/tests/test_beat_correction.py`
- `backend/tests/fixtures/easy_lover_correction.json` (new)
- `frontend/src/audio.test.ts`
- `frontend/src/beatCorrection.test.ts`
- `frontend/e2e/beat-correction.spec.ts`
- `docs/easy-lover-beat-grid-diagnostic.md`
- `docs/experimental-beat-correction.md` (new)
- `README.md`

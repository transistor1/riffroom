# Default beat tracking and recovery

Standard source setup now provisions an isolated CPU beat environment through the
same installer used by the metronome recovery button. Core and MLX dependencies
remain in their existing locks. The new `scripts/requirements-beats-lock.txt`
pins the beat environment's closure, including matching torch/torchaudio 2.8.0.
Windows/Linux explicitly use official CPU wheels. This leaves the managed
Windows CUDA separation environment and macOS MLX environment independent.

Missing dependencies offer **Set up beat tracking**, including legacy persisted
missing-package errors. An explicit request queues setup, streams safe phase
messages, checks imports/dependencies, then analyzes the requested song. Setup
failure remains retryable. Reopening a failed song does not install or infer;
ordinary song failures retain **Retry**. Concurrent song requests share the serial
beat queue; an OS file lock also excludes overlapping launcher/UI installations.
Cancellation uses the existing process-group cleanup for the setup process only.
The ready marker is written after all checks pass, so partial installs can retry.

Supported installer targets: Apple Silicon macOS, Windows x86-64, Linux x86-64.
Unsupported targets print an explicit explanation without attempting installation.
CPU inference remains independent of stem separation. Existing grids are reused.

## Exact changed files

- `README.md`
- `backend/riffroom/beat_runtime.py` (new)
- `backend/riffroom/beats.py`
- `backend/tests/test_app.py`
- `backend/tests/test_beat_runtime.py` (new)
- `backend/tests/test_setup_portable.py`
- `docs/beat-tracking-setup.md` (new; this report)
- `frontend/src/components/Mixer.test.tsx`
- `frontend/src/components/Mixer.tsx`
- `frontend/src/types.ts`
- `scripts/requirements-beats-lock.txt` (new)
- `scripts/setup.sh`
- `scripts/setup_portable.py`

## Validation

Commands ran in the main worktree; installers, model downloads and production
services were not invoked. Tests use temporary data and mocked package installation.

```bash
PYTHONDONTWRITEBYTECODE=1 .env/bin/python -m pytest -q backend/tests/test_app.py backend/tests/test_beat_runtime.py backend/tests/test_setup_portable.py backend/tests/test_launchers.py
```

101 passed. Covers automatic setup wiring, pins/platform selection, install failure,
ready-marker reuse, concurrent setup locking, phase streaming, setup cancellation,
missing-package recovery, setup retry, duplicate requests, and ordinary analysis
failure behavior. Existing Starlette/httpx deprecation warnings remain.

```bash
npm test --prefix frontend
```

205 passed across six files. Includes setup/progress rendering, legacy error
migration, pending-request disabling, and preservation of normal analysis Retry.
Node emitted its existing experimental localStorage warning.

```bash
./frontend/node_modules/.bin/tsc -b frontend --pretty false
```

Passed. No frontend bundle was rebuilt.

```bash
PYTHONDONTWRITEBYTECODE=1 .env/bin/python -m ruff check backend/riffroom/beats.py backend/riffroom/beat_runtime.py backend/tests/test_app.py backend/tests/test_beat_runtime.py backend/tests/test_setup_portable.py scripts/setup_portable.py
bash -n scripts/setup.sh
git diff --check
```

Passed. One new test import-order issue was fixed before the final lint run.

Read-only Python `urllib`/`packaging` probes checked all pinned PyPI release metadata,
active dependency version constraints, and published wheel tags for Python
3.11/3.12/3.13 on each supported target. All pins had compatible published wheels;
constraints were compatible, accounting for the explicit CPU torch selection.
Sources: [Beat This! dependency manifest](https://github.com/CPJKU/beat_this/blob/main/pyproject.toml),
[PyTorch CPU wheel index](https://download.pytorch.org/whl/cpu/torch/), and PyPI
release JSON for each exact pin. This was metadata inspection, not fresh-host
installation or actual inference.

### Existing broader-test failure

```bash
PYTHONDONTWRITEBYTECODE=1 .env/bin/python -m pytest -q backend/tests/test_app.py backend/tests/test_beat_runtime.py backend/tests/test_setup_portable.py backend/tests/test_launchers.py backend/tests/test_beat_correction.py
```

At that point: 105 passed, one failed. The Easy Lover correction test expects a
beat list differing from the current correction engine's output. This is unrelated
to dependency setup; no correction code or fixtures were changed. It reproduced
with the original beat jobs loaded from `HEAD`, without changing Git state:

```bash
PYTHONDONTWRITEBYTECODE=1 .env/bin/python - <<'PY'
import subprocess
import pytest
import riffroom.beats
source = subprocess.check_output(['git', 'show', 'HEAD:backend/riffroom/beats.py'], text=True)
exec(compile(source, 'baseline-beats.py', 'exec'), riffroom.beats.__dict__)
raise SystemExit(pytest.main(['-q', 'backend/tests/test_beat_correction.py::test_read_only_correction_from_stored_analysis[easy_lover_approved_groove.json-applied]']))
PY
```

Same fixture assertion failed. Three additional setup-process tests were added
subsequently and passed in the final 101-test scoped run above.

## Remaining validation and guardrails

Fresh-host package installation, checkpoint download, real beat inference, Windows
process cleanup and multi-process Windows file locking still need host validation.
No production dependency installation, app restart, live song-data edits,
separation cancellation, staging, commit, push, or branch operation was performed.
The existing `.env` was used only to run checks; no setup/install command targeted it.

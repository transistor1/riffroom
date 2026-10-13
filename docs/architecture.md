# Architecture

```text
React UI / library / mixer
        │ same-origin HTTP
FastAPI on 127.0.0.1:8765
        ├── FFmpeg → normalized format, not loudness → original.wav
        ├── atomic JSON project store
        └── one-at-a-time job queue
                └── cancellable Python subprocess
                        ├── logical model → ordered trusted execution variants
                        │       ├── production MLX inference for validated profiles
                        │       └── managed audio-separator 0.47.0 venv → explicit model allowlist
                        └── aligned float WAV stems + waveform peaks

Browser Web Audio: shared AudioContext → one source/gain per stem
                   → master gain → shared SoundTouchJS AudioWorklet
                   → final compressor → speakers
```

## Boundaries

- `backend/riffroom/app.py`: HTTP routes, local-origin protection, upload handling, static frontend.
- `audio.py`: FFmpeg format conversion, metadata limits, waveforms, alignment validation.
- `store.py`: atomic manifests; each track owns its inputs and run folders.
- `jobs.py`: one inference job at a time; process-group cancellation; error and restart recovery.
- `runtimes.py`: discovery and atomic installation of the fixed `audio-separator==0.47.0` portable runtime
  in `data/runtimes/audio-separator/venv`. It honors an administrator executable override first, discovers `PATH`
  second, and otherwise uses the managed copy. Windows x86-64 uses the GPU extra with a CPU fallback; other hosts
  retain the CPU extra. Installation uses argv-only child processes, verifies the CLI before publishing the
  temporary runtime directory, and keeps installation state and errors in the server process.
- `models.py`: provider-aware declarative catalog consumed by the UI. The curated layer and the three validated
  portable community profiles are static server-owned metadata. When the optional MLX package is installed, the
  community layer additionally reads its bundled `models.json` and `models-scores.json`, admits entries with an
  explicit non-empty stem list, and derives opaque SHA-256-based IDs. Static portable rows win when the sources
  are merged, so those filenames remain one logical row even without MLX. A profile stores user-facing metadata once
  and has an ordered tuple of server-owned execution variants. Each variant names only a trusted provider,
  checkpoint filename, explicit validation state, stable supported platforms and separate experimental platform
  capabilities. The API computes compatibility
  across validated variants and reports the first available variant as the selected provider without duplicating
  the logical catalog row.
- `providers/`: the trusted separation-provider boundary. `base.py` defines separation and runtime-availability,
  `__init__.py` resolves provider IDs through an explicit server-owned registry, and `mlx.py` owns the current
  production `mlx-audio-separator` runtime. The MLX provider resolves its optional runtime only for availability
  checks and execution; importing the registry does not import `separator.py` or `mlx_audio_separator`. An
  unavailable MLX invocation fails explicitly rather than changing providers. `audio_separator.py` is an
  out-of-process bridge to the fixed portable
  executable resolved from administrator configuration, `PATH`, or the managed runtime. Portable routing is limited
  to an explicit server-owned table containing `UVR-MDX-NET-Inst_HQ_5.onnx`,
  `MDX23C-DrumSep-aufr33-jarredou.ckpt`, and
  `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`. Provider IDs never name an importable module, class
  or executable path.
- `separator.py`: low-level adapter for the pinned MLX runtime. It provides atomic downloads, a project-local
  Demucs conversion cache and the dedicated guitar profile behavior used by the MLX provider.
- `demucs_cache.py`: strict restoration of native MLX parameter paths, correcting the pinned upstream cached-weight loading bug.
- `worker.py`: shared isolated inference entry point, resolved-variant provider dispatch, phase messages,
  expected-stem/alignment validation, waveform generation and manifest writing. The job resolves exactly one
  variant before spawning the worker and passes that trusted provider ID into the process. There is no mid-job
  fallback: an execution failure fails the run, while a later retry resolves again from current availability.
  Successful aligned outputs are published together; partial outputs never appear as finished runs.
- `frontend/src/audio.ts`: audio scheduling independent of React. Shared start time, seek offsets and loop boundaries prevent HTML-audio-element drift. Gain changes use short ramps. Source playback rate controls tempo; one shared post-mix SoundTouchJS AudioWorklet compensates the rate-induced pitch change and applies the independent user pitch offset. The worklet uses the default Lanczos interpolation with exhaustive seeking and music-oriented WSOLA parameters; only at rates up to 0.55× do its sequence and seek windows use SoundTouch's tempo-aware auto sizing.
- `frontend/src/components/Mixer.tsx`: shared transport, loop controls, channel state and per-result local storage. The main and per-stem waveform range controls all seek the same audio engine and React playhead position.
- `frontend/src/components/Waveform.tsx`: waveform rendering from backend peaks.
- `frontend/src/App.tsx`: import, library, model selection and result selection.
- `frontend/src/modelPreferences.ts`: versioned browser-local model working-set preferences. It validates stored
  IDs against the complete API catalog, defaults to compatible curated models and prevents normal separation
  menus from becoming empty. The complete catalog remains in memory for Model Manager and historical run labels.

## Chained separation lineage

Runs form a persisted tree. A new root run records `source: {"type": "original"}`; a child records the exact
persisted parent with `source: {"type": "stem", "run_id": ..., "stem_name": ...}`. Legacy runs without a
`source` remain roots. The server resolves a child input only by finding that run and stem in the same track
manifest and then validating its safe manifest filename and existing WAV. Request paths and filenames are never
used to infer lineage.

Each run owns an `active_children` map from one of its stem names to a direct child run ID. The mixer walks these
choices recursively and replaces the parent channel with the selected child's effective channels; it never plays
both. Clearing a choice restores the parent without deleting any result. Because choices live on their parent
run, switching root takes preserves independent expansion trees and cannot expose a child from another root.
Deleting a run deletes its entire descendant subtree and clears references to it before best-effort filesystem
cleanup.

Only roots receive the track's monotonically increasing `take_number`, so child work cannot create gaps in the
top-level Listening to menu. Direct children of the same parent stem receive monotonic creation-order
`split_number` values and are labeled “split N”; a persisted per-stem next counter prevents reuse after deletion,
and those sibling numbers are never used as root take numbers.

## Adding a model

Add a curated logical profile with a unique ID, expected stem names, source, checkpoint terms and architecture,
then declare one or more ordered trusted execution variants with provider, checkpoint filename, explicit
validation state and platform capabilities. Registry presence alone is not validation. Beyond the three static
portable entries, eligible community profiles are generated only from the optional pinned MLX runtime metadata:
`models.json` must declare a safe checkpoint basename (and optional config basename),
and `models-scores.json` must explicitly list its output stems. Friendly names and filenames are not parsed to
guess outputs. For another architecture or provider, implement a reviewed provider that returns its expected
aligned stereo 44.1 kHz float WAV paths; the shared worker will validate them and write the unchanged stem
manifest. Add its fixed ID to the trusted registry rather than loading a module from metadata. Do not let raw user
input select arbitrary checkpoint files, paths, URLs, Python modules or executable code.

Compatibility is capability-driven across a profile's trusted variants, not inferred from an architecture name
or a UI operating-system check. Existing production profiles keep their `mlx-audio-separator` Apple Silicon
execution paths, and every curated portable candidate keeps MLX first. The three
portable-only community profiles are validated only through `audio-separator`; presence
in MLX's bundled registry is not treated as runtime proof. Stable capability grows only after the fixed managed
runtime successfully separates generated audio and produces every trusted expected stem as a readable WAV;
experimental candidates additionally require exact filename/config evidence from audio-separator 0.47.0. The
portable provider is available only when its administrator override, `PATH` command, or managed CLI resolves successfully.
Until then each portable-only row remains visible in Model Manager as **Runtime required** (or
**Experimental runtime required** for a model-specific Windows validation candidate), stays out of normal
selectors, and offers the portable installer. The user must explicitly
start the large install; opening Model Manager never installs software. Windows and Linux venv layouts are handled
by the installer. The explicit Demucs six-stem portable variant and three static portable community profiles are
execution-validated on `macos-arm64`. On Windows x86-64, Demucs 6 and MDX23C DrumSep are supported after real
CUDA separations; the other community pilots remain experimental. The exact `BS-Roformer-SW.ckpt`,
`htdemucs_ft.yaml`, and `vocals_mel_band_roformer.ckpt` curated variants are also supported after live Windows
CUDA runs. No arbitrary community model or architecture inherits that capability, and Windows ARM64 and Linux
remain unavailable.

The Phase 3D2 follow-up resolved the Demucs import blocker without a shim. `audio-separator` imports
`DiffQuantizer`, `UniformQuantizer`, and `restore_quantized_state` at module load; the validated `htdemucs_6s`
checkpoint is not quantized, but the real `diffq` package is still required for those imports. Installing
`diffq>=0.2` after Torch succeeded on Apple Silicon when its source build used the installed Command Line Tools.
With `samplerate` still absent, `htdemucs_6s.yaml` then separated a generated six-second stereo WAV and produced
exactly guitar, vocals, drums, bass, piano and other as readable stereo WAVs. The existing `demucs-6` logical
model therefore keeps MLX first and adds `audio-separator` second, with the same model ID and trusted stems.
`htdemucs_ft.yaml` initially did not reach inference because the worker could not resolve
`dl.fbaipublicfiles.com` for its missing checkpoint. Audio-separator 0.47.0's discovery code and the cached UVR
registry nevertheless recognized that exact Demucs v4 filename, so it was first exposed as an experimental
Windows validation candidate. Later live Windows CUDA runs completed that model plus the exact registry-backed
`BS-Roformer-SW.ckpt` and `vocals_mel_band_roformer.ckpt` variants end to end, promoting all three to supported
Windows capability. The registry provides no exact entry for the curated guitar specialists, which remain
MLX-only.

The install endpoint accepts no package, version, executable, or provider input. Status exposes only a fixed
user-facing phase label and the installation start timestamp while work is active; it never exposes argv, paths,
or subprocess output. It always creates a temporary
venv with the running Riffroom Python. Existing platforms install exactly `audio-separator[cpu]==0.47.0`.
Windows x86-64 installs `audio-separator[gpu]==0.47.0` and the matched
`torch==2.8.0+cu128`, `torchvision==0.23.0+cu128`, and `torchaudio==2.8.0+cu128` stack from the fixed official
CUDA 12.8 wheel index, plus `onnxruntime-gpu==1.23.2`. `onnx2torch-py313` depends on an otherwise-unbounded
`torchvision`; therefore the same exact stack is also supplied as a constraint to every later pip resolver step.
This prevents a newer torchvision from replacing CUDA Torch with its newer exact CPU Torch dependency. The
CUDA-enabled wheels retain CPU execution when no compatible NVIDIA driver/device is available and do not require
the CUDA Toolkit. It installs the remaining curated runtime dependencies before the real platform-specific DiffQ
package. On macOS the build selects
`/Library/Developer/CommandLineTools` when present; this avoids coupling the source build to an unlicensed or
incompatible full-Xcode selection while preserving the normal environment elsewhere. `samplerate==0.1.0` stays
excluded because its wheel bundles an x86_64-only library and none of the validated paths import it. The installer
checks the Windows Torch and companion versions and requires `torch.version.cuda` to be non-null, without requiring
`torch.cuda.is_available()` or an NVIDIA GPU. It then checks the expected CLI with `--help` and imports `Separator`,
`DemucsSeparator`, and `HTDemucs` before atomically promoting the directory. These imports require no model downloads. A failure removes the temporary
directory without replacing an existing runtime, and exposes only a bounded, path-free failure category. App
shutdown cancels an in-progress installer subprocess. Jobs pass a server-resolved executable to workers through
`RIFFROOM_AUDIO_SEPARATOR_BIN` only when the process environment does not already contain an explicit
administrator override; global `PATH` is not changed.

Managed runtime discovery checks a durable `VERSION` marker containing both the upstream version and a
Riffroom install-recipe revision. Windows x86-64 uses `recipe=5`; unchanged hosts retain `recipe=3`. Bump the
applicable revision whenever that dependency recipe or installation procedure changes, even when upstream remains
at `0.47.0`. A legacy version-only marker is stale and permits
explicit reinstallation from Model Manager. The new marker is written only after dependency installation
(including real DiffQ), staged execution-stack imports, and both staged and published CLI checks succeed. Replacement keeps the old runtime as
a backup until verification and marker writing finish, restoring it on failure. Status continues to report
upstream version `0.47.0`; on Windows x86-64 it also runs one bounded, cached probe through the managed Python to
report `cuda` with a sanitized GPU name or `cpu`. Probe failures report neither backend nor diagnostic internals.

Windows x86-64 recipe 5 retains the explicit `audioread>=3` install from recipe 3:
audio-separator's `spec_utils` imports it directly,
but upstream does not declare it and librosa 1.0 no longer supplies it transitively. The recipe also
includes upstream's conditional `audioop-lts>=0.2.1` dependency for Python 3.13, where the standard
library removed `audioop` used by pydub. Older recipe and version-only markers are stale and require
explicit reinstallation on Windows x86-64; unchanged hosts retain recipe 3. Import verification failures
preserve the previous managed runtime.

Prepared-file state is intentionally narrower than total provider disk use. Each curated profile declares the
exact checkpoint, config and/or converted MLX files that Riffroom owns beneath its configured `data/models`
directory. Community profiles use only the exact checkpoint/config basenames supplied by bundled `models.json`;
cleanup is disabled when a config is shared across registry entries. A profile is Prepared only when every
declared file is present and non-empty; otherwise it will
prepare on next use. Cleanup unlinks only those declared filenames (and their exact atomic-download `.part`
counterparts), never a request-supplied path. It does not touch track originals, run manifests, generated WAVs,
shared provider metadata (`download_checks.json`, `vr_model_data.json`, `mdx_model_data.json`), or provider-level
caches such as `data/models/torch` / `TORCH_HOME`. In particular,
removing Demucs prepared files may leave upstream Torch downloads on disk even though the next use converts the
model again.

Portable-routed community models are deliberately excluded from model-specific cache accounting and removal. The portable
runtime can own additional registry and model files that are not completely enumerated by Riffroom, so partial
cleanup would be misleading and unsafe.

## Packaging boundary

The base project dependency set contains only the web/audio application requirements. The Apple inference stack is
declared in the `mlx` optional dependency group with the same pinned MLX Audio Separator, Demucs, Torch and
Torchaudio versions used by the tested installation. MLX package resources are optional at import time: without
them the app, model catalog and explicit provider registry still import; the eight curated profiles remain visible
but runtime-unavailable, and the community catalog contains the three static portable profiles.

The Apple Silicon launcher continues to install the complete MLX stack from `requirements-lock.txt`.
Linux (`bash start.sh`) and Windows (`Riffroom.ps1`, wrapping `start.ps1`) use
`scripts/setup_portable.py`, a core-only installer with a project-local `.env`. Windows uses
`.env/Scripts/python.exe`; Linux/macOS use `.env/bin/python`. Portable setup requires Python 3.11–3.13,
Node.js 22+ with npm, and FFmpeg/ffprobe on PATH, and never invokes a system package manager.
On Windows, users who already have Conda may optionally use it to supply Node.js/npm and FFmpeg/ffprobe. Riffroom
does not create or manage a Conda environment. If those tools come from an activated Conda environment, it may
need to remain activated so they stay on PATH while Riffroom uses its separate project-local `.env` for its
Python interpreter and packages.
`requirements-core-lock.txt` pins the base dependency closure and editable-build setuptools; installation
uses `--no-deps --no-build-isolation` for the project. Maintain the core pins alongside the full lock;
the launcher tests check the closure against installed package metadata across Python/platform markers.
These are version locks, not artifact hashes. The core installer neither installs nor removes MLX in an
existing environment; use a fresh checkout/environment for a clean core-only installation.

Core setup fingerprints the platform, architecture, Python minor version, dependency files and launcher
sources. A successful dependency install, `pip check`, and frontend build writes the stamp; failures remain
retryable. The Mac stamp remains separate. Check mode reports prerequisites and stale dependencies without
creating an environment, installing packages, building, or starting a server. The shared launcher still reuses
an existing Riffroom on port 8765 and reports other port conflicts; Windows uses an exclusive probe socket.
The heavyweight managed audio-separator runtime remains an explicit in-app installation.

Every launcher defaults to `127.0.0.1`. `--host` (PowerShell `-BindAddress`) opts into another
plain-HTTP socket bind address; portable setup forwards it unchanged. PowerShell `-Lan` forwards the launcher's
existing `--lan` mode, which binds all IPv4 interfaces with a self-signed HTTPS certificate. It is mutually
exclusive with a non-default bind address and preserves `-NoBrowser`. The launcher resets the process-local
`RIFFROOM_BIND_HOST` setting before configuring the app: default trust remains localhost,
127.0.0.1 and testserver; a specific bind adds that host, while 0.0.0.0/:: permits any Host.
Bracketed IPv6 literals receive exact address matching before Starlette's hostname check.
Same-origin mutation checks remain active in every mode. Network binds print an unauthenticated
access warning. Wildcard binds use a loopback browser/readiness URL; remote clients use the
computer's LAN IP and port 8765. Only default launches reuse an existing server; explicit binds
probe the requested socket and report conflicts rather than silently reusing a loopback server.

Windows x86-64 is supported with limited model availability. Demucs 6, Demucs detailed 4, RoFormer 6,
RoFormer Kimberley vocals, and MDX23C DrumSep declare stable Windows capability after live runs, including CUDA
separations on an NVIDIA GeForce RTX 4070 Ti SUPER. UVR-MDX-NET Inst HQ 5 and Mel-Roformer-Karaoke
Aufr33-Viperx remain individually experimental until their exact filenames produce every trusted output stem in
a real Windows run; this does not imply broad hardware or driver coverage. Audio-separator 0.47.0 has no CUDA
CLI switch and automatically selects CUDA from `torch.cuda.is_available()`, otherwise using CPU. Windows ARM64,
Linux and Intel macOS remain outside this capability. Launcher support alone does
not certify inference support.

A lead/rhythm model would declare `lead_guitar` and `rhythm_guitar` stems. The mixer accepts arbitrary names; add display labels/icons and choose how the guitar presets target the new names.

## Practical tradeoffs

- This is a single-process local application. Do not start multiple Uvicorn workers against one data folder. A future multi-user service would need database-backed jobs and authentication.
- All selected stems are decoded into browser memory for sample-synchronized playback and audio-clock-scheduled region transitions. Very long tracks use significant RAM. Streaming or an AudioWorklet ring buffer is a future extension.
- Speed uses Web Audio source playbackRate for sample-synchronized transport and mirrors that value to `@soundtouchjs/audio-worklet` 2.1.1, whose shared post-mix processor preserves tuning. At 0.5×, SoundTouch's auto WSOLA heuristic lengthens its processing windows for the lower internal tempo; rates of 0.75× and above retain the existing fixed profile. The Pitch slider, exact-value field, and reset control independently set the processor's ±12-semitone offset. SoundTouchJS and its installed support packages are distributed under MPL-2.0.
- Switching results or effective child expansions remounts the audio engine and stops playback. Completing a root separation selects its result automatically; completing a child separation selects that child only for its parent stem. Deleting the selected root first applies the server-equivalent fallback in a synchronous client update, aborting its audio loads before the DELETE request; a failed deletion refreshes authoritative state. Deleting the last root switches to Original mix.
- Mix preferences and the personal model working set are in localStorage, while the library is on disk. The model
  working set affects only normal selection menus; Model Manager discovery and saved-run model labels use the full
  API catalog. Individual completed separation results can be removed without touching the normalized original or
  other results; deleting the selected result also removes its saved mix preference. Cross-browser preference sync
  and named saved mixes are future work.
- Model prepared-file cleanup is blocked while that model is queued or processing. It is idempotent and does not remove imported audio, track history or completed separation results.
- Manifests are simple JSON to keep the first version inspectable. SQLite can replace Store without changing the audio worker or mixer.
- Source audio is never modified. The imported copy is resampled to 44.1 kHz stereo to standardize model and browser alignment. Every stem must have exactly the same frame count before publication.
- A chained model can only work with the audio preserved by its parent stem. Leakage, missing content, and other
  first-stage artifacts propagate downstream and cannot be recovered by a later split.
- Progress reports phases, not fabricated percentages. More granular model callbacks can be added when the runtime provides a stable interface.


### Saved practice loops

`PUT /api/tracks/{track_id}/practice` validates up to 50 uniquely identified named
regions and atomically stores `{loops: [{id, name, a, b, enabled}]}` in `track.json`.
Missing practice data means an empty list. Boundaries retain fractional seconds,
with a minimum length of 0.05 seconds; overlapping regions are allowed.
The Mixer debounces edits by 300ms and serializes writes across result remounts.
Loop mode is transient and defaults off. Checkbox selection persists at song level.
The compact selected-loop editor accepts seconds or m:ss.mmm and offers ±0.1s nudges.
Waveform overlays remain visible with mode off; waveform zoom remains future work.

The engine sorts enabled regions by start time (stable list order breaks ties).
When starting inside overlapping regions, the first containing region wins.
Outside a region, playback begins at the next selected start, wrapping if needed.
A 100ms lookahead scheduler queues two seconds of AudioBufferSourceNode start/stop
events. Every stem uses identical AudioContext boundaries, scaled by playback rate.
The UI's 50ms polling only displays position. Pause, seek, rate and route edits
cancel queued nodes; the shared SoundTouch processor retains the existing tempo
and pitch processing design. Long main-thread stalls beyond the scheduling horizon
can underrun; SoundTouch's existing processing latency still applies.

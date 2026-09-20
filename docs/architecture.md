# Architecture

```text
React UI / library / mixer
        │ same-origin HTTP
FastAPI on 127.0.0.1:8765
        ├── FFmpeg → normalized format, not loudness → original.wav
        ├── atomic JSON project store
        └── one-at-a-time job queue
                └── cancellable Python subprocess
                        ├── trusted catalog profile → provider/runtime
                        │       ├── current production MLX inference
                        │       └── managed audio-separator 0.47.0 venv → one MDX pilot
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
- `runtimes.py`: discovery and atomic installation of the fixed `audio-separator[cpu]==0.47.0` portable runtime
  in `data/runtimes/audio-separator/venv`. It honors an administrator executable override first, discovers `PATH`
  second, and otherwise uses the managed copy. Installation uses argv-only child processes, verifies the CLI before
  publishing the temporary runtime directory, and keeps installation state and errors in the server process.
- `models.py`: provider-aware declarative catalog consumed by the UI. The curated layer is static. The community
  layer reads only the pinned runtime's bundled `models.json` and `models-scores.json`, admits entries with an
  explicit non-empty stem list, and derives opaque SHA-256-based IDs. Profiles describe architecture, runtime
  provider, supported platform capabilities, checkpoint terms, catalog origin and exact app-owned cache files.
  The API computes compatibility and prepared-file state without changing inference dispatch.
- `providers/`: the trusted separation-provider boundary. `base.py` defines separation and runtime-availability,
  `__init__.py` resolves provider IDs through an explicit server-owned registry, and `mlx.py` owns the current
  production `mlx-audio-separator` runtime. `audio_separator.py` is an out-of-process bridge to the fixed portable
  executable resolved from administrator configuration, `PATH`, or the managed runtime. Only
  `UVR-MDX-NET-Inst_HQ_5.onnx` routes through it. Provider IDs never name an importable module, class or executable
  path.
- `separator.py`: low-level adapter for the pinned MLX runtime. It provides atomic downloads, a project-local
  Demucs conversion cache and the dedicated guitar profile behavior used by the MLX provider.
- `demucs_cache.py`: strict restoration of native MLX parameter paths, correcting the pinned upstream cached-weight loading bug.
- `worker.py`: shared isolated inference entry point, provider dispatch, phase messages, expected-stem/alignment
  validation, waveform generation and manifest writing. Successful aligned outputs are published together;
  partial outputs never appear as finished runs.
- `frontend/src/audio.ts`: audio scheduling independent of React. Shared start time, seek offsets and loop boundaries prevent HTML-audio-element drift. Gain changes use short ramps. Source playback rate controls tempo; one shared post-mix SoundTouchJS AudioWorklet compensates the rate-induced pitch change and applies the independent user pitch offset. The worklet uses the default Lanczos interpolation with exhaustive seeking and music-oriented WSOLA parameters; only at rates up to 0.55× do its sequence and seek windows use SoundTouch's tempo-aware auto sizing.
- `frontend/src/components/Mixer.tsx`: shared transport, loop controls, channel state and per-result local storage. The main and per-stem waveform range controls all seek the same audio engine and React playhead position.
- `frontend/src/components/Waveform.tsx`: waveform rendering from backend peaks.
- `frontend/src/App.tsx`: import, library, model selection and result selection.
- `frontend/src/modelPreferences.ts`: versioned browser-local model working-set preferences. It validates stored
  IDs against the complete API catalog, defaults to compatible curated models and prevents normal separation
  menus from becoming empty. The complete catalog remains in memory for Model Manager and historical run labels.

## Adding a model

Add a curated profile with a unique ID, checkpoint filename, expected stem names, source, checkpoint terms,
architecture, provider and explicit platform capabilities. Eligible community profiles are generated only from
the pinned runtime metadata: `models.json` must declare a safe checkpoint basename (and optional config basename),
and `models-scores.json` must explicitly list its output stems. Friendly names and filenames are not parsed to
guess outputs. For another architecture or provider, implement a reviewed provider that returns its expected
aligned stereo 44.1 kHz float WAV paths; the shared worker will validate them and write the unchanged stem
manifest. Add its fixed ID to the trusted registry rather than loading a module from metadata. Do not let raw user
input select arbitrary checkpoint files, paths, URLs, Python modules or executable code.

Compatibility is capability-driven per profile and provider, not inferred from an architecture name or a UI
operating-system check. The current catalog keeps the existing `mlx-audio-separator` Apple Silicon execution
path unchanged. The `audio-separator` provider is available only when its administrator override, `PATH` command,
or managed CLI resolves successfully. Platform support and runtime readiness are separate API fields: on a
supported host the portable pilot remains visible in Model Manager as **Runtime required** but is excluded from
normal selectors until the runtime is ready. The user must explicitly start the large install; opening Model
Manager never installs software. Windows and Linux venv layouts are handled by the installer, but Riffroom setup,
the pilot profile, and end-to-end validation remain `macos-arm64` only in this phase.

The install endpoint accepts no package, version, executable, or provider input. It always creates a temporary
venv with the running Riffroom Python, installs exactly `audio-separator[cpu]==0.47.0`, and installs the pinned
package's pilot-required dependencies separately. The single MDX/ONNX pilot does not install `diffq`, whose source
build requires a local compiler because it has no Apple Silicon wheel, or `samplerate==0.1.0`, whose wheel bundles
an x86_64-only library. Neither package is imported by the pilot path. The installer checks the expected CLI with
`--help` and atomically promotes the directory. A failure removes the temporary directory without replacing an
existing runtime, and exposes only a bounded, path-free failure category. App shutdown cancels an in-progress
installer subprocess. Jobs pass a server-resolved executable to workers through
`RIFFROOM_AUDIO_SEPARATOR_BIN` only when the process environment does not already contain an explicit
administrator override; global `PATH` is not changed.

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

The portable pilot is deliberately excluded from model-specific cache accounting and removal. The upstream
runtime can own additional registry and model files that are not completely enumerated by Riffroom, so partial
cleanup would be misleading and unsafe.

A lead/rhythm model would declare `lead_guitar` and `rhythm_guitar` stems. The mixer accepts arbitrary names; add display labels/icons and choose how the guitar presets target the new names.

## Practical tradeoffs

- This is a single-process local application. Do not start multiple Uvicorn workers against one data folder. A future multi-user service would need database-backed jobs and authentication.
- All selected stems are decoded into browser memory for sample-synchronized playback and gapless native looping. Very long tracks use significant RAM. Streaming or an AudioWorklet ring buffer is a future extension.
- Speed uses Web Audio source playbackRate for sample-synchronized transport and mirrors that value to `@soundtouchjs/audio-worklet` 2.1.1, whose shared post-mix processor preserves tuning. At 0.5×, SoundTouch's auto WSOLA heuristic lengthens its processing windows for the lower internal tempo; rates of 0.75× and above retain the existing fixed profile. The Pitch slider, exact-value field, and reset control independently set the processor's ±12-semitone offset. SoundTouchJS and its installed support packages are distributed under MPL-2.0.
- Switching results remounts the audio engine and stops playback. Completing the first separation selects its result automatically.
- Mix preferences and the personal model working set are in localStorage, while the library is on disk. The model
  working set affects only normal selection menus; Model Manager discovery and saved-run model labels use the full
  API catalog. Individual completed separation results can be removed without touching the normalized original or
  other results; deleting the selected result also removes its saved mix preference. Cross-browser preference sync
  and named saved mixes are future work.
- Model prepared-file cleanup is blocked while that model is queued or processing. It is idempotent and does not remove imported audio, track history or completed separation results.
- Manifests are simple JSON to keep the first version inspectable. SQLite can replace Store without changing the audio worker or mixer.
- Source audio is never modified. The imported copy is resampled to 44.1 kHz stereo to standardize model and browser alignment. Every stem must have exactly the same frame count before publication.
- Progress reports phases, not fabricated percentages. More granular model callbacks can be added when the runtime provides a stable interface.

# Architecture

```text
React UI / library / mixer
        │ same-origin HTTP
FastAPI on 127.0.0.1:8765
        ├── FFmpeg → normalized format, not loudness → original.wav
        ├── atomic JSON project store
        └── one-at-a-time job queue
                └── cancellable Python subprocess
                        └── trusted catalog profile → provider/runtime
                                └── current MLX inference
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
- `models.py`: provider-aware declarative catalog consumed by the UI. The curated layer is static. The community
  layer reads only the pinned runtime's bundled `models.json` and `models-scores.json`, admits entries with an
  explicit non-empty stem list, and derives opaque SHA-256-based IDs. Profiles describe architecture, runtime
  provider, supported platform capabilities, checkpoint terms, catalog origin and exact app-owned cache files.
  The API computes compatibility and prepared-file state without changing inference dispatch.
- `separator.py`: version-specific runtime adapter. Atomic downloads, project-local Demucs conversion cache, dedicated guitar profile, non-normalizing float WAV writer.
- `demucs_cache.py`: strict restoration of native MLX parameter paths, correcting the pinned upstream cached-weight loading bug.
- `worker.py`: isolated inference entry point and phase messages. Successful aligned outputs are published together; partial outputs never appear as finished runs.
- `frontend/src/audio.ts`: audio scheduling independent of React. Shared start time, seek offsets and loop boundaries prevent HTML-audio-element drift. Gain changes use short ramps. Source playback rate controls tempo; one shared post-mix SoundTouchJS AudioWorklet compensates the rate-induced pitch change and applies the independent user pitch offset. The worklet uses the default Lanczos interpolation with exhaustive seeking and music-oriented WSOLA parameters; only at rates up to 0.55× do its sequence and seek windows use SoundTouch's tempo-aware auto sizing.
- `frontend/src/components/Mixer.tsx`: shared transport, loop controls, channel state and per-result local storage. The main and per-stem waveform range controls all seek the same audio engine and React playhead position.
- `frontend/src/components/Waveform.tsx`: waveform rendering from backend peaks.
- `frontend/src/App.tsx`: import, library, model selection and result selection.

## Adding a model

Add a curated profile with a unique ID, checkpoint filename, expected stem names, source, checkpoint terms,
architecture, provider and explicit platform capabilities. Eligible community profiles are generated only from
the pinned runtime metadata: `models.json` must declare a safe checkpoint basename (and optional config basename),
and `models-scores.json` must explicitly list its output stems. Friendly names and filenames are not parsed to
guess outputs. For another architecture or provider, implement a reviewed adapter that writes aligned stereo
44.1 kHz float WAVs and the same stem manifest. Do not let raw user input select arbitrary checkpoint files,
paths, URLs, Python modules or executable code.

Compatibility is capability-driven per profile and provider, not inferred from an architecture name or a UI
operating-system check. The current catalog keeps the existing `mlx-audio-separator` Apple Silicon execution
path unchanged. A later phase can add a portable provider, likely `python-audio-separator`, after its supported
backends and profiles are validated.

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

A lead/rhythm model would declare `lead_guitar` and `rhythm_guitar` stems. The mixer accepts arbitrary names; add display labels/icons and choose how the guitar presets target the new names.

## Practical tradeoffs

- This is a single-process local application. Do not start multiple Uvicorn workers against one data folder. A future multi-user service would need database-backed jobs and authentication.
- All selected stems are decoded into browser memory for sample-synchronized playback and gapless native looping. Very long tracks use significant RAM. Streaming or an AudioWorklet ring buffer is a future extension.
- Speed uses Web Audio source playbackRate for sample-synchronized transport and mirrors that value to `@soundtouchjs/audio-worklet` 2.1.1, whose shared post-mix processor preserves tuning. At 0.5×, SoundTouch's auto WSOLA heuristic lengthens its processing windows for the lower internal tempo; rates of 0.75× and above retain the existing fixed profile. The Pitch slider, exact-value field, and reset control independently set the processor's ±12-semitone offset. SoundTouchJS and its installed support packages are distributed under MPL-2.0.
- Switching results remounts the audio engine and stops playback. Completing the first separation selects its result automatically.
- Mix preferences are in localStorage, while the library is on disk. Individual completed separation results can be removed without touching the normalized original or other results; deleting the selected result also removes its saved mix preference. Cross-browser preference sync and named saved mixes are future work.
- Model prepared-file cleanup is blocked while that model is queued or processing. It is idempotent and does not remove imported audio, track history or completed separation results.
- Manifests are simple JSON to keep the first version inspectable. SQLite can replace Store without changing the audio worker or mixer.
- Source audio is never modified. The imported copy is resampled to 44.1 kHz stereo to standardize model and browser alignment. Every stem must have exactly the same frame count before publication.
- Progress reports phases, not fabricated percentages. More granular model callbacks can be added when the runtime provides a stable interface.

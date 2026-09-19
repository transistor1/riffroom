# Architecture

```text
React UI / library / mixer
        │ same-origin HTTP
FastAPI on 127.0.0.1:8765
        ├── FFmpeg → normalized format, not loudness → original.wav
        ├── atomic JSON project store
        └── one-at-a-time job queue
                └── cancellable Python subprocess
                        └── curated model profile → MLX inference
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
- `models.py`: declarative profile catalog consumed by the UI.
- `separator.py`: version-specific runtime adapter. Atomic downloads, project-local Demucs conversion cache, dedicated guitar profile, non-normalizing float WAV writer.
- `demucs_cache.py`: strict restoration of native MLX parameter paths, correcting the pinned upstream cached-weight loading bug.
- `worker.py`: isolated inference entry point and phase messages. Successful aligned outputs are published together; partial outputs never appear as finished runs.
- `frontend/src/audio.ts`: audio scheduling independent of React. Shared start time, seek offsets and loop boundaries prevent HTML-audio-element drift. Gain changes use short ramps. Source playback rate controls tempo; one shared post-mix SoundTouchJS AudioWorklet compensates the rate-induced pitch change and applies the independent user pitch offset. The worklet uses the default Lanczos interpolation with exhaustive seeking and fixed music-oriented WSOLA parameters.
- `frontend/src/components/Mixer.tsx`: transport, loop controls, channel state and per-result local storage.
- `frontend/src/components/Waveform.tsx`: waveform rendering from backend peaks.
- `frontend/src/App.tsx`: import, library, model selection and result selection.

## Adding a model

Add a profile with a unique id, checkpoint filename, expected stem names, source and licensing note. For a checkpoint in the upstream registry, the adapter handles the rest. For another architecture, implement a new adapter that writes aligned stereo 44.1 kHz float WAVs and the same stem manifest. Do not let raw user input select arbitrary checkpoint files or executable code.

A lead/rhythm model would declare `lead_guitar` and `rhythm_guitar` stems. The mixer accepts arbitrary names; add display labels/icons and choose how the guitar presets target the new names.

## Practical tradeoffs

- This is a single-process local application. Do not start multiple Uvicorn workers against one data folder. A future multi-user service would need database-backed jobs and authentication.
- All selected stems are decoded into browser memory for sample-synchronized playback and gapless native looping. Very long tracks use significant RAM. Streaming or an AudioWorklet ring buffer is a future extension.
- Speed uses Web Audio source `playbackRate` for sample-synchronized transport and mirrors that value to `@soundtouchjs/audio-worklet` 2.1.1. The worklet's `playbackRate` parameter is not a second tempo control: its processor computes `effectivePitch = requestedPitch / sourcePlaybackRate`, then uses a rate transposer and WSOLA stretch to undo the source's rate-induced pitch change without changing the duration of the blocks it receives. This source-rate-plus-mirror arrangement is the package's documented real-time integration. The Pitch slider, exact-value field, and reset control remain independent by contributing only `requestedPitch` (a ±12-semitone offset).
- SoundTouchJS 2.1.1 does not expose an independent tempo control on `SoundTouchNode`; the core package also documents that its former public tempo/rate controls were removed in favor of changing the source rate. Consequently, leaving sources at 1.0× and setting only the worklet's `playbackRate` to 0.5 would shift the worklet's effective pitch while retaining normal-duration transport, not produce 0.5× pitch-preserving playback. Its offline helper constructs the same mirrored source/worklet graph, so offline use can remove real-time scheduling risk but does not provide a higher-quality algorithm.
- At 0.5×, the neutral-pitch compensation drives SoundTouch's internal WSOLA tempo to 0.5, which can produce transient smearing, chorusing, or rhythmic discontinuities at a 2:1 stretch. The attempted tempo-aware auto-window profile did not improve listening quality, so Riffroom keeps the same fixed 80/20/12 ms exhaustive-search profile at all speeds. A materially cleaner 0.5× path therefore requires a different stretch engine rather than further SoundTouch parameter tuning. The most direct real-time successor is a higher-quality phase-vocoder or Rubber Band WASM processor kept in the same shared post-mix position, preserving stem sync and independent pitch at the cost of more CPU, bundle size, DSP latency, and implementation/licensing review. SoundTouchJS and its installed support packages are distributed under MPL-2.0.
- Switching results remounts the audio engine and stops playback. Completing the first separation selects its result automatically.
- Mix preferences are in localStorage, while the library is on disk. Cross-browser preference sync and named saved mixes are future work.
- Manifests are simple JSON to keep the first version inspectable. SQLite can replace Store without changing the audio worker or mixer.
- Source audio is never modified. The imported copy is resampled to 44.1 kHz stereo to standardize model and browser alignment. Every stem must have exactly the same frame count before publication.
- Progress reports phases, not fabricated percentages. More granular model callbacks can be added when the runtime provides a stable interface.

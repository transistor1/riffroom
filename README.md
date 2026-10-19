# Riffroom: turn a song into a backing track you can play with.

![Riffroom six-stem mixer with guitar muted and independent instrument levels](docs/images/riffroom-separation.jpg)

I built Riffroom for my own guitar practice and am sharing it in case you'd like to play with it too. Open a song, split it into instruments, then turn the guitar down or off and play along—or solo it to hear the part you're learning. Loop a tricky passage, slow it down without detuning, or transpose it to match your guitar. It all runs locally, with a mixer in your browser.

**Apple Silicon Mac and Windows x86-64 are supported song-splitting paths.** Windows has limited model availability and validation covers a specific CPU setup plus an NVIDIA GeForce RTX 4070 Ti SUPER, not every hardware or driver combination. Linux remains an unvalidated core-app experiment.

## A quick look

### Bring in a song and choose how to split it

![Riffroom import screen with local separation model choices](docs/images/riffroom-new-session.jpg)

Drop in an audio file, start with the recommended six-stem model, or choose a specialist for the part you want to practice. You can run another model later without importing the song again.

### Turn the hard parts into a practice session

![Riffroom loop editor with playhead capture, one-beat nudges, beat snapping, count-in, speed and pitch controls](docs/images/riffroom-practice-loops.jpg)

Save passages such as a chorus or solo, enable the ones you want, and cycle through them in timeline order. Slow the song down, change pitch, choose the instrument you play, and mute or solo it. Use beat-snapped boundaries and one-beat nudges to refine a passage, then add a count-in and click once beat analysis is ready.

## What Riffroom does

- **Make a backing track:** mix guitar, vocals, drums, bass, piano and other instruments with the six-stem options. Each separated part is called a *stem*.
- **Choose your part:** select an available instrument for the play-with-the-band and hear-just-that-part shortcuts, or combine manual solos to hear how parts fit together.
- **Work on a passage:** save and cycle through multiple practice loops, change speed while preserving tuning, and adjust pitch independently.
- **Start in time:** automatic local AI beat/downbeat analysis prepares a 1–4 bar count-in and optional click with its own volume control.
- **Choose the beat grid:** Auto applies confident timing repairs when available; Raw uses the original analysis. The experimental correction engine preserves the source grid.
- **Compare splitting methods:** keep multiple results for a song and switch between them and the original.
- **Keep your practice local:** save songs and results on your computer and download individual stems as WAV files. No account, API key, paid service or cloud upload is needed.

Song splitting is approximate: expect some instrument bleed and artifacts, especially in dense mixes. Different methods suit different songs.

## Practice

1. Choose a model, then drag an audio file into the window or click **Choose a track**.
2. Separation runs in the background; you can listen to the original while waiting. The library shows its status. One job runs at a time to limit GPU memory use.
3. Use the arrow beside **Play guitar with the band** to choose an available instrument. The shortcuts update to your choice: **Play guitar with the band** mutes the guitar; **Hear just the guitar** solos it. Click an active shortcut again to restore the previous mix.
4. Use each stem's **M**, **S**, and volume slider. Volume runs from 0–200%; the master sets overall output. Multiple solos work together; mute takes precedence.
5. Seek to a passage and click **Add loop**. Click a saved loop’s name to open its editor below the waveform. Capture Start/End at the playhead, type exact times, or nudge boundaries with optional **Snap to beat**. Select passage checkboxes and enable **Loop** to cycle in timeline order, skipping gaps. See [Practice loop editing](#practice-loop-editing).
6. When automatic beat analysis is ready, choose **Count-in** Off or 1–4 bars, enable **Click** to keep time during playback, and adjust **Click level** independently. See [Metronome and count-in](#metronome-and-count-in) and [Beat correction (experimental)](#beat-correction-experimental).
7. Try another model from the bottom of the track page. Each completed root run remains available in **Listening to**, alongside the original.
8. Use **Split further** on a stem to run another visible, compatible model on that part. The child stems replace
   their parent in the mixer; use the split selector to return to the unsplit parent or choose another saved split.
   Splits can be chained recursively. Because each stage only receives its parent stem, leakage or missing audio
   from an earlier stage carries into every later stage.
9. Use a stem's download arrow to save its WAV file.

Mix levels, mutes, and solos are remembered per result in this browser. Track audio and all completed separation results persist on disk. Named loops and their selection checkboxes are saved with the song and shared across results. Loop mode defaults off each time the mixer opens. Speed and pitch are remembered per song in this browser, across results and reloads. Play position and master output reset when changing results. Speed changes tempo while preserving tuning, and the Pitch control transposes playback independently.

### Practice loop editing

Click **Add loop** to create a passage near the playhead. Click a saved passage’s name to select it for editing; click it again, or use the editor’s disclosure button, to collapse the controls. The passage checkboxes independently choose which loops play when **Loop** is on.

- **Start (A) / End (B):** type seconds or **m:ss.mmm** and press Enter or leave the field. Typed times stay exact even with snapping enabled, within the song and the opposite boundary.
- **Set start/end at playhead:** capture the current playback position. Press **A** for Start or **B** for End when a loop editor is open and focus is outside form controls. An invalid capture leaves the loop unchanged.
- **Snap to beat:** off by default and remembered per song in this browser. When on, new loop boundaries and playhead captures align to the selected beat grid; the nudge buttons move to the previous/next legal beat. With snapping off, nudges move by **±0.1 seconds**.
- **Grid availability:** snapping follows **Grid → Auto / Raw**, including a corrected grid when Auto applies one. Without a usable selected grid, beat nudges are disabled and other edits remain free. Beat nudges stop at the last legal beat rather than crossing the other boundary.

The **?** button opens loop help. **Space** plays/pauses and **← / →** seek five seconds outside form controls. Count-in leads into the saved boundary exactly; it does not snap it again.

### Metronome and count-in

Local AI analysis of the original mix starts automatically on import and on first open of an older song without analysis. It runs in the background without blocking normal playback or stem separation. Ready grids are cached and reused across reloads and separation results. Failed or interrupted analysis requires an explicit **Retry** after fixing the cause; reopening does not restart it. See [optional beat tracking setup](#optional-beat-tracking-setup).

Once ready, choose **Count-in** Off or **1–4 bars**. Count-in works even with **Click** off; Click keeps the metronome running during playback, including loops. **Click level** adjusts click volume from **0–200%** in 5% steps, independently of the music master. Click and music pass through the same SoundTouch tempo processing to stay synchronized when speed changes.

Count-in leads into the exact playback start: it does not snap the playhead or shift a loop boundary to a beat. Loop mode still selects the next enabled loop when the playhead is outside one. Pausing cancels queued clicks; resuming continues without another count-in, including when paused during pre-roll.

### Beat correction (experimental)

Open **Grid** beside the click controls to choose **Auto** or **Raw**. **Auto** is the default for songs without a saved choice: it applies a conservative repair only when the engine finds one confidently, otherwise it uses the raw grid. **Raw** bypasses correction and uses the original analysis. The browser remembers the choice per song across reloads and separation results, including previously saved preferences.

The menu separates your chosen mode from the engine decision and shows whether playback uses a corrected or raw grid. **Advanced details** includes the analysis model and time signature. Correction uses existing analysis without reanalysis, audio edits, or overwriting the original timestamps or downbeats.

Correction does **not** solve downbeat/accent interpretation or all odd or changing-meter problems. Listening validation remains limited, primarily to **Easy Lover** and **Reelin’ in the Years**; broader testing is still needed. See [diagnostic evidence and limits](docs/easy-lover-beat-grid-diagnostic.md#preserved-listening-baseline).

While Auto is preparing, or if correction fails, click and count-in are unavailable; music remains playable. Choose **Raw** to use the original grid, or use **Retry correction** in the Grid menu after a failure. Switching grids cancels queued clicks and continues at the current position without a new count-in.

## Get started

Clone, download or unzip Riffroom into a writable folder, then use the launcher for your computer. First setup needs internet access to install dependencies and build the interface. Model weights download separately when first used.

### macOS · Apple Silicon

Double-click **`Riffroom.command`**, or run this from the project folder:

```bash
./start.sh
```

The launcher prepares the project and opens **http://127.0.0.1:8765**. Keep the Terminal window open; Control-C stops the server. Launching again reuses the running app.

An M1 or newer Mac is required; 16 GB memory is recommended. The app targets macOS 14 or later with a compatible MLX wheel. Existing validation used an M1 Mac on macOS 27; the pinned dependencies may need adjustment on older macOS versions. Intel Macs are outside the current supported path.

macOS keeps the full Apple Silicon stack and prefers MLX for the curated models. Setup accepts Python 3.11–3.13 and creates a standard virtual environment in `.env`; Conda is not required. If Python, Node.js/npm or FFmpeg/ffprobe is missing, it uses Homebrew to install the missing tool. If Homebrew is missing, it prints installation guidance. Apple's command-line tools are requested only if a package needs them.

### Linux · experimental

Install Python 3.11–3.13 with venv/pip support, Node.js 22+ with npm, and FFmpeg including ffprobe using your distribution's instructions. Then, from the project folder:

```bash
bash start.sh
```

Linux uses `scripts/setup_portable.py` and `requirements-core-lock.txt` to prepare the core app without installing MLX. It reports missing system tools rather than installing them for you.

### Windows x86-64 · supported with limited model availability

Install Python 3.11–3.13 with the Python launcher or PATH option, Node.js 22+ with npm, and FFmpeg with both `ffmpeg.exe` and `ffprobe.exe` on PATH. If you already use Conda, it is an optional convenient source for Node.js/npm and FFmpeg/ffprobe; Conda is not required, and Riffroom does not create or manage a Conda environment. Open or reopen PowerShell, navigate to the project folder, and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Riffroom.ps1
```

`Riffroom.ps1` delegates to `start.ps1`, which uses the same portable/core setup as Linux. The execution-policy override applies only to this invocation; it does not change machine-wide policy. No administrator shell is required. Add `-NoBrowser` to start without opening a browser.

If Node.js or FFmpeg comes from an activated Conda environment, that environment may need to remain activated while Riffroom runs so those executables stay on PATH. This is the arrangement used by the successful Windows separation test: Conda supplied host tools while Riffroom's Python packages remained in the project-local `.env` virtual environment. Riffroom still runs its application Python from `.env`; it does not combine the two environments into one or manage the Conda environment.

The core app, upload flow, portable CPU separation, and CUDA-accelerated separation have been user-confirmed on Windows x86-64. Demucs 6, Demucs detailed 4, RoFormer 6, RoFormer · Kimberley vocals, and MDX23C DrumSep have completed real Windows runs; other visible portable choices are explicitly marked experimental until each exact model completes end-to-end validation there. Model Manager installs the portable engine on request; the source launcher does not install it. The managed engine includes fixed CUDA-enabled PyTorch and ONNX Runtime wheels. It uses an NVIDIA GPU when PyTorch confirms CUDA is available and otherwise keeps the validated CPU fallback. Neither the CUDA Toolkit nor developer tools are required. During installation, Model Manager reports the current safe phase and elapsed time; afterward it reports the detected GPU/backend. This evidence does not claim broad GPU, driver, or model coverage. Linux splitting remains unavailable and unvalidated. See [validation notes](docs/validation.md#cross-platform-source-launcher-mvp) for the remaining checks.

### Setup checks and limits

Later launches reuse `.env` and refresh dependencies/builds when the setup fingerprint changes. Do not copy `.env` between machines or operating systems.

To inspect prerequisites without installing packages, building or starting the server:

```bash
# macOS or Linux
bash start.sh --check
```

```powershell
# Windows
powershell -NoProfile -ExecutionPolicy Bypass -File .\Riffroom.ps1 -Check
```

Uploads are limited to **512 MB and 20 minutes**. Decoded audio and stems use substantially more memory and disk than an MP3. The browser holds the selected result in memory, so shorter tracks and fewer tabs help on a 16 GB machine. A full song can take several minutes on an M1; progress reports stages, not a promised completion time.

### Optional beat tracking setup

The metronome uses [CPJKU Beat This!](https://github.com/CPJKU/beat_this) locally on the decoded original/full mix. Install its optional dependencies in the project’s `.env` environment, from the project folder:

```bash
# macOS / Linux
.env/bin/python -m pip install -e '.[beats]'
```

```powershell
# Windows (PowerShell)
.\.env\Scripts\python.exe -m pip install -e ".[beats]"
```

Restart Riffroom after installation, then use **Retry** for a song whose analysis failed before setup. The first analysis may download the official `final0` checkpoint (roughly 78 MB) into PyTorch’s user cache. Set `RIFFROOM_BEAT_MODEL` before launch to a local checkpoint path for pre-provisioned weights or another Beat This! checkpoint. After weights are present, analysis runs offline and stores timestamps plus model/version/provenance in the song manifest. Deleting a song removes its grid but retains shared cached weights. Beat This! and its published weights are MIT licensed.

This integration uses CPU inference and is intended for macOS, Windows, and Linux wherever the PyTorch/torchaudio dependencies install successfully; it has not been validated on every platform. Missing dependencies, unavailable checkpoints, or inference errors leave count-in/click unavailable, with an explicit error rather than a fixed-BPM substitute. Count-in may extend a valid grid’s phase backward for pre-roll before a sparse intro; it never changes persisted timestamps. For normal use, see [Metronome and count-in](#metronome-and-count-in); optional correction is [a separate step](#beat-correction-experimental).

### LAN access / testing another computer

The default is `127.0.0.1` (this computer only). Network binding is opt-in:

```bash
# macOS / Linux
./start.sh --host 0.0.0.0
# Optional: add --no-browser
```

```powershell
# Windows (start.ps1 accepts the same flags)
.\Riffroom.ps1 -Lan
# Optional: add -NoBrowser
```

Stop an existing server before changing its bind mode. On another computer, open the
`https://<server-LAN-IP>:8765` URL printed by the launcher and accept its self-signed
certificate warning. `-Lan` delegates to the launcher's HTTPS certificate handling;
it cannot be combined with a non-default `-BindAddress`. Using
`-BindAddress 0.0.0.0` directly remains available for plain HTTP testing, but remote
AudioWorklet playback requires a secure context and is therefore unsuitable in that mode.
Riffroom has no authentication: anyone who can reach the bound interface can access
the app and data. Use only on a trusted LAN. The HTTPS LAN launcher starts on the validated
Windows x86-64 host, but browser use was completed through SSH forwarding because direct LAN
access was blocked by the host/network firewall arrangement.

## Choosing a splitting method

These curated choices are available through the Apple Silicon setup. Windows x86-64 has a smaller validated curated catalog: Demucs 6, Demucs detailed 4, RoFormer 6, and RoFormer · Kimberley vocals. The community MDX23C DrumSep entry is also validated there; UVR-MDX-NET Inst HQ 5 and Mel-Roformer-Karaoke Aufr33-Viperx remain experimental until each exact model completes a real Windows run end to end. CPU fallback and optional NVIDIA CUDA acceleration have both completed real separations. Use Model Manager to explore entries and manage the models in your selection menus; availability depends on your platform and installed tools.

| Model | Outputs | When to use it |
|---|---|---|
| Demucs · 6 stems | Guitar, vocals, drums, bass, piano, other | Default: a dependable balance of speed, memory and independent band controls. |
| RoFormer · 6 stems | Guitar, vocals, drums, bass, piano, other | Compare with Demucs on difficult mixes. More demanding on memory. |
| RoFormer · guitar focus | All guitars, rest of band | Try the dedicated guitar extractor when you mainly need guitar isolation/removal. No individual drum/bass faders in this mode. |
| Demucs · detailed 4 stems | Vocals, drums, bass, other | Fine-tuned ensemble for rhythm-section practice. Guitar stays in Other. Slower than the default. |

There is no universal best separator for every song. Start with Demucs, compare the six-stem RoFormer, and try guitar focus when guitar clarity matters most. The smoke tests verify functioning inference and aligned output, **not perceptual superiority**. Dense distortion, effects, and overlapping instruments can leave bleed or remove useful detail. Demucs's piano output is experimental.

**Lead versus rhythm guitar:** the included models put them in one guitar stem. Research did not establish a dependable, openly available local lead/rhythm checkpoint suitable for this Mac. Riffroom does not relabel a stereo or frequency split as AI-separated lead/rhythm. The model adapter and arbitrary stem list allow such a model to be added later.

Model research, primary sources, and weight licensing are in [docs/models.md](docs/models.md). The application uses open-source tools. Community model weights have separate terms: the default Demucs option is MIT; the guitar specialist is authorized by its author for non-commercial use; the RoFormer SW weight redistribution license is unverified. Keep this distinction in mind if turning the personal app into a distributed product.

## Local files and privacy

- `data/tracks/<id>/original.wav`: imported, decoded 44.1 kHz stereo copy.
- `data/tracks/<id>/track.json`: track metadata and completed run references.
- `data/tracks/<id>/runs/<run-id>/`: model outputs, waveforms and diagnostic log.
- `data/models/`: downloaded/converted weights, reusable across songs.
- `data/runtimes/`: separately installed portable splitting engine, when requested in Model Manager.
- `.env/`: isolated, project-local standard Python virtual environment.

Deleting a track removes its Riffroom copy and results. It never touches the source file you imported. Back up `data/tracks` to preserve your library; browser local storage holds mixer preferences. Set `RIFFROOM_DATA` before launch to select another data folder: `RIFFROOM_DATA=/absolute/path ./start.sh` on macOS/Linux, or `$env:RIFFROOM_DATA = "C:\path\to\data"` in PowerShell before running the Windows launcher.

Models require internet for the initial download. Once their weights/configs are cached, normal separation runs locally. Cancelling a job keeps previous successful results and does not publish partial stems. Download files are committed atomically so interrupted downloads can be retried. Converted weights can occupy several GB; the four prepared curated profiles used roughly 3 GB on the development Mac. Other models and the optional portable engine need additional space.

The server listens on `127.0.0.1` by default and rejects unexpected hostnames. Explicit network binding permits the chosen host (any host for wildcard binds); cross-origin mutations remain rejected. It is a single-user local app, not an authenticated network service.

## Development

The stack is **Python/FastAPI + React/TypeScript/Vite + Web Audio**, with FFmpeg for decoding and MLX for the primary Apple Silicon splitting path. The portable engine uses a separate managed environment. Python suits the ML ecosystem; TypeScript keeps UI and audio state explicit. One production server serves both UI and API.

The commands below use the macOS/Linux environment layout; on Windows, the Python executable is `.env\Scripts\python.exe`. The macOS setup includes development tools; core-only installs need the `dev` extra for backend checks.

```bash
# Backend (do not use multiple workers; the job queue is local to this process)
.env/bin/python -m uvicorn riffroom.app:app --host 127.0.0.1 --port 8765

# Optional frontend dev server, in another terminal
npm run dev --prefix frontend

# Build after UI changes
npm run build --prefix frontend

# Checks
.env/bin/pytest -q
.env/bin/ruff check backend scripts
npm test --prefix frontend

# Browser integration test: uses installed Google Chrome and a running server
.env/bin/python scripts/make_test_audio.py
npm run test:e2e --prefix frontend
```

The browser test imports an original synthetic fixture, runs the real default ML model, verifies playback/mixer/loop/storage/cancellation/downloads, and deletes that test track. This workflow targets the validated Apple Silicon setup and needs GPU access and initially model-download access. See [docs/architecture.md](docs/architecture.md) for extension points and [docs/validation.md](docs/validation.md) for what was verified.

## Troubleshooting

- **First separation is slow:** weights need to download and convert once. Leave the server running.
- **Older Demucs stems sound buzzy/noisy:** the original cached-weight loader had a bug, now fixed. Select Demucs and click **Separate track** again; existing WAVs cannot be repaired in place. New workers load the corrected adapter automatically.
- **Job fails:** open its diagnostic log in the track page. Try again, or use Demucs six stems if RoFormer exhausts memory.
- **Click/count-in unavailable:** queued or running analysis shows its status. For failed or interrupted analysis, install the optional beats dependency or resolve the displayed error, then click **Retry**. If Auto correction is preparing or failed, choose **Grid → Raw** to use the original grid, or click **Retry correction** in the Grid menu after failure.
- **Click sounds wrong:** check **Click level** and compare **Grid → Auto** with **Raw**. Correction may leave timing unchanged and cannot establish correct bar accents; see [its limits](#beat-correction-experimental).
- **No sound:** press Play, check master/mute/solo controls and your computer's output device. Browser audio needs a user click.
- **Server was closed:** run your platform’s launcher again. Interrupted jobs are marked for retry; finished results remain.
- **Port 8765 in use:** the launcher reuses Riffroom if it owns the port; otherwise it asks you to stop the other app.
- **SDK build error:** make sure `xcrun --sdk macosx --show-sdk-path` resolves to an SDK compatible with the selected Xcode toolchain. Setup already includes the workaround used on this Mac.
- **Shared Homebrew on a multi-user Mac:** setup can use compatible tools that are already installed, including an unlinked supported Python. If another account owns Homebrew and a tool is missing, use that account or ask an administrator to install the tool.
- **No splitting options on Linux:** Linux model execution remains unavailable and unvalidated. On Windows x86-64, Model Manager can install the portable runtime for only explicitly allowlisted models. It prefers NVIDIA CUDA when detected and falls back to CPU; both paths have completed real separations under the tested configurations.

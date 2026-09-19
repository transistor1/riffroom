# Riffroom

A personal guitar practice room that runs on your Mac. Open or drop a song, separate its instruments, and mix a backing track in your browser.

## Start on this Mac

**Double-click `Riffroom.command`**, or run:

```bash
./start.sh
```

That is the whole installation process. On the first launch, Riffroom prepares its project environment, installs its packages, builds the interface, and then opens **http://127.0.0.1:8765**. Keep the Terminal window open; Control-C stops the server. Opening the launcher again reuses the running app. No account, API key, paid service, or cloud upload is needed.

## Practice

1. Choose a model, then drag an audio file into the window or click **Choose a track**.
2. Separation runs in the background; you can listen to the original while waiting. The library shows its status. One job runs at a time to limit GPU memory use.
3. **Play guitar with the band** mutes the guitar. **Hear just the guitar** solos it.
4. Use each stem's **M**, **S**, and volume slider. Volume runs from 0–200%; the master sets overall output. Multiple solos work together; mute takes precedence.
5. Seek to a passage, set **A** and **B**, and enable **Loop**. Space plays/pauses, and arrow keys skip five seconds when you aren't editing a control.
6. Try another model from the bottom of the track page. Each completed run remains available in **Listening to**, alongside the original.
7. Use a stem's download arrow to save its WAV file.

Mix levels, mutes, and solos are remembered per result in this browser. Track audio and all completed separation results persist on disk. Loop points, play position, speed, and master output currently reset when changing results. Speed changes tempo while preserving tuning, and the Pitch control transposes playback independently.

## Model choices

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
- `.env/`: isolated, project-local standard Python virtual environment.

Deleting a track removes its Riffroom copy and results. It never touches the source file you imported. Back up `data/tracks` to preserve your library; browser local storage holds mixer preferences. `RIFFROOM_DATA=/absolute/path ./start.sh` selects a different data folder before launch.

Models require internet for the initial download. Once their weights/configs are cached, normal separation runs locally. Cancelling a job keeps previous successful results and does not publish partial stems. Download files are committed atomically so interrupted downloads can be retried. Converted weights can occupy several GB; the four prepared profiles currently use roughly 3 GB.

The server listens only on `127.0.0.1`. It rejects unexpected hostnames and cross-origin mutations. It is a single-user local app, not an authenticated network service.

## Fresh installation

Riffroom currently requires an Apple Silicon Mac (M1 or newer); 16 GB memory is recommended. It targets macOS 14 or later with a compatible MLX wheel and was verified on the supplied M1 / macOS 27 machine. The lockfile reflects this Mac and may require adjustment on older macOS versions.

Clone, download, or unzip Riffroom, then double-click `Riffroom.command`. You can also run `./start.sh` from Terminal. No separate setup command is required.

Riffroom uses a standard Python virtual environment inside `.env` and does not require Conda. It accepts Python 3.11, 3.12, or 3.13. If Python, Node.js/npm, or FFmpeg/ffprobe is missing, the launcher uses Homebrew to install only the missing tool. If Homebrew itself is missing, the launcher shows its official installation command and asks you to double-click `Riffroom.command` again afterward. Apple's command-line tools are only requested if a package actually needs them.

First-time setup installs the pinned Python dependencies and npm lockfile, keeps the development checks available in this source checkout, and builds the UI. Later launches automatically refresh setup after dependency manifests change. An existing working `.env` is reused. Setup uses the SDK returned by `xcrun`, when available, to avoid a mismatched beta SDK/compiler. Model weights download when each profile is first used. A full song can take several minutes on an M1; there is no fake percentage or promised completion time.

Limits: 512 MB uploads and 20-minute tracks. Decoded audio/stems can use substantially more disk and memory than an MP3. The browser decodes one selected result into memory. Shorter tracks and fewer simultaneous tabs are preferable on a 16 GB Mac.

## Development

The stack is **Python/FastAPI + React/TypeScript/Vite + Web Audio + MLX**, with FFmpeg for decoding. Python suits the ML ecosystem; TypeScript keeps UI and audio state explicit. One production server serves both UI and API.

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

The browser test imports an original synthetic fixture, runs the real default ML model, verifies playback/mixer/loop/storage/cancellation/downloads, and deletes that test track. It needs GPU access and initially model-download access. See [docs/architecture.md](docs/architecture.md) for extension points and [docs/validation.md](docs/validation.md) for what was verified.

## Troubleshooting

- **First separation is slow:** weights need to download and convert once. Leave the server running.
- **Older Demucs stems sound buzzy/noisy:** the original cached-weight loader had a bug, now fixed. Select Demucs and click **Separate track** again; existing WAVs cannot be repaired in place. New workers load the corrected adapter automatically.
- **Job fails:** open its diagnostic log in the track page. Try again, or use Demucs six stems if RoFormer exhausts memory.
- **No sound:** press Play, check master/mute/solo controls and your Mac's output device. Browser audio needs a user click.
- **Server was closed:** reopen `Riffroom.command`. Interrupted jobs are marked for retry; finished results remain.
- **Port 8765 in use:** the launcher reuses Riffroom if it owns the port; otherwise it asks you to stop the other app.
- **SDK build error:** make sure `xcrun --sdk macosx --show-sdk-path` resolves to an SDK compatible with the selected Xcode toolchain. Setup already includes the workaround used on this Mac.
- **Shared Homebrew on a multi-user Mac:** setup can use compatible tools that are already installed, including an unlinked supported Python. If another account owns Homebrew and a tool is missing, use that account or ask an administrator to install the tool.

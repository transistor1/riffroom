# Model decision record · 2026-09-18

## Why these profiles

The target is an M1 MacBook Air with 16 GB unified memory. Independent guitar, drums and bass controls matter more here than vocal-only benchmark scores. Riffroom therefore includes several complementary profiles and retains each run for listening comparisons. No cross-model quality ranking is claimed from our synthetic smoke tests.

**Default: HTDemucs six sources (`htdemucs_6s`).** A mature, MIT-licensed baseline with guitar/piano added to the usual four sources. The authors explicitly describe piano separation as limited. The fine-tuned four-source ensemble (`htdemucs_ft`) is also included for drums/bass/vocals, with guitar in Other. [Demucs primary documentation](https://github.com/facebookresearch/demucs).

**Alternative: BS-RoFormer SW (`BS-Roformer-SW.ckpt`).** A six-source community checkpoint supported by the chosen runtime. It offers another architecture to compare when Demucs guitar extraction has bleed. The inference implementation is open source, but a clear license for redistribution of these particular weights was not established. We download through the runtime's public registry and do not commit or distribute the weights. [MLX separator documentation and BS-RoFormer SW profile](https://github.com/ssmall256/mlx-audio-separator), [original BS-RoFormer paper](https://arxiv.org/abs/2309.02612).

**Guitar specialist: becruily's Mel-Band RoFormer (`becruily_guitar.ckpt`).** Its published config targets Guitar and Other. It is a useful additional listening comparison for removing or learning guitar parts, at the cost of losing separate bass/drum faders in that result. The author's stated permission covers non-commercial use; this is not a claim of OSI-open weight licensing. [Author's model/config](https://huggingface.co/becruily/mel-band-roformer-guitar/blob/main/config_guitar_becruily.yaml), [author's licensing statement](https://huggingface.co/becruily/mel-band-roformer-guitar/discussions/9).

## Provider-aware catalog

The catalog has two layers. The four hand-reviewed profiles remain the curated, recommended set and are the only
cards on the import page. The Model Manager always exposes three execution-validated portable community profiles
whose logical metadata is trusted server-side. When installed, the optional `mlx-audio-separator` 0.1.7 wheel adds
the broader community layer generated from its bundled metadata. The API compares every profile's declared platform capabilities with a
stable current-platform key such as `macos-arm64`, `windows-x86_64` or `linux-x86_64`; the manager presents that
result instead of making its own operating-system assumptions.

The authoritative inputs for the broader optional community catalog are the installed package's
`mlx_audio_separator/models.json` and `mlx_audio_separator/models-scores.json` files. If the package or either
usable metadata file is absent, Riffroom does not fabricate those entries. In the inspected 0.1.7 package:

- `models.json` provides the friendly-name key, architecture registry group, checkpoint filename and, for MDXC
  and RoFormer entries, an optional config filename.
- `models-scores.json` is keyed by checkpoint filename and may provide `model_name`, `stems`, `target_stem`,
  median scores and per-track scores. Riffroom uses only its explicit, non-empty `stems` field for eligibility.
- Neither bundled file provides a per-checkpoint source URL or checkpoint license/usage terms.

The bundled registry contains 83 entries, but only 27 have a matching non-empty `stems` list in the bundled score
metadata. Those 27 are runnable community entries when the optional package is present; the other 56 are excluded rather than deriving outputs from
names or filenames. Riffroom does not use the runtime's separately downloaded, mutable `download_checks.json` to
expand the displayed catalog. Community source links therefore point to the runtime project page, not a fabricated
checkpoint page. Every community entry says **Checkpoint terms unverified** because the runtime's code license says
nothing about the checkpoint's usage rights.

Community IDs are `community-` plus the complete SHA-256 digest of the registry checkpoint filename. Clients can
submit only these generated IDs or curated IDs; the server resolves the ID back to its trusted profile. A raw
filename, path, URL, Python module or other user-supplied loading instruction is never accepted. Curated IDs take
precedence if a generated catalog entry ever collides.

All profiles support `macos-arm64`. A logical profile owns its model ID and user-facing metadata once, plus an
ordered tuple of explicitly validated execution variants. Most curated profiles have one `mlx-audio-separator`
variant; `demucs-6` has MLX first and a validated portable variant second. Portable routing is a server-owned
allowlist, not a consequence of appearing in either runtime's
registry. The `audio-separator` 0.47.0 allowlist contains exactly these execution-validated filenames:

- `htdemucs_6s.yaml`: Guitar, Vocals, Drums, Bass, Piano and Other; a second variant on curated `demucs-6`.
- `UVR-MDX-NET-Inst_HQ_5.onnx`: Instrumental and Vocals.
- `MDX23C-DrumSep-aufr33-jarredou.ckpt`: Kick, Snare, Toms, HH, Ride and Crash.
- `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`: Vocals and Instrumental.

The Phase 3D2 follow-up tested both curated Demucs candidates with a generated six-second stereo WAV on Apple
Silicon. `audio-separator` imports DiffQ symbols while loading its Demucs modules even though the unquantized
`htdemucs_6s` checkpoint does not exercise the quantized-state branches. The real `diffq 0.2.4` package built and
imported after Torch when the build selected the installed Command Line Tools; no compatibility shim is used.
`htdemucs_6s.yaml` then exited successfully and produced exactly its six trusted stems as readable 44.1 kHz
stereo WAVs. Its existing curated `demucs-6` row now has MLX first/preferred and `audio-separator` second, without
changing its logical ID, metadata, trusted stems, or prepared-file ownership. The `htdemucs_ft` attempt again
could not resolve `dl.fbaipublicfiles.com` to download its missing checkpoint, so it remains unvalidated and
MLX-only. Portable support remains declared `macos-arm64` only until Windows and Linux are tested independently.

Each of the three community entries remains one logical catalog row with its existing generated model ID and has
only a validated `audio-separator` variant. Its checkpoint terms remain unverified. The two additions were run
through the managed runtime on a generated six-second stereo WAV; the CLI exited successfully and every stem
declared by the trusted bundled metadata was produced as a readable stereo WAV. Registry presence alone did not
qualify any model, and no
other curated or community filename is routed to the portable provider. MLX variants are not inferred for these
logical models from MLX registry presence. Their filenames, friendly names, architectures and stem lists are now
copied into the server-owned catalog so they remain available when MLX is not installed. When bundled metadata is
present, these static rows override and deduplicate matching filenames. The server chooses the first validated, host-capable variant whose hard-coded
provider runtime is available. It freezes that provider for the job invocation and records the provider ID in new
run metadata; it never silently falls back after execution begins. A later retry resolves again. Existing history
without a provider ID remains valid. Model metadata cannot supply a Python module, class or executable path.
Providers produce the profile's stem WAV files, while the shared worker retains
expected-stem and alignment validation, waveform generation, progress sequencing and manifest writing. The manager
reports each profile as **Prepared** only when all of its declared Riffroom-owned files are present and non-empty;
otherwise it reports **Downloads on first use**. Choosing **Use model** changes the current import/separation
selection without starting work. It also adds that model to the browser's personal working set. The full curated
and community catalog always remains browsable in Model Manager, while normal separation menus show only this
smaller working set. A new browser profile starts with every compatible curated model shown and no community
models; users can show community models or hide curated models with **Show in separation menus**. The preference
is versioned local browser state, is validated against the current API catalog, and falls back to the compatible
curated set if storage is unavailable or invalid. At least one compatible model must remain visible. First-use
separation remains responsible for downloading and converting model files. The only separate install job is the
explicit portable runtime installation described below; it does not preload model weights.

The portable runtime is isolated from Riffroom's pinned MLX environment at
`data/runtimes/audio-separator/venv`. Installation is an explicit Model Manager action and always installs exactly
`audio-separator[cpu]==0.47.0`; the main project dependency and lock files do not include it. Riffroom installs the
dependencies required by the validated portable paths separately, installing Torch before the real `diffq>=0.2`
source package. On macOS, DiffQ's build selects the installed Command Line Tools when available. The unused,
x86_64-only library bundled by `samplerate==0.1.0` remains excluded. Riffroom creates a temporary venv with its
running Python, verifies the CLI and imports `Separator`, `DemucsSeparator`, and `HTDemucs`
without downloading models, then atomically promotes it. A valid
`RIFFROOM_AUDIO_SEPARATOR_BIN` administrator override takes precedence, followed by `PATH`, then the managed copy.
Package names, versions, executable paths and provider classes are not accepted from HTTP or model metadata.

Managed installations also carry a Riffroom recipe revision, separate from the displayed upstream `0.47.0`.
Dependency recipe changes invalidate older managed installations even if that upstream version is unchanged.
In particular, an old `VERSION` marker containing only `0.47.0` requires explicit reinstallation in Model Manager
to obtain the real DiffQ dependency. Installation writes the revision-aware marker only after all dependencies
and execution-stack import and CLI checks succeed; a failed replacement restores the previous runtime. Discovery uses the marker without
running Python imports or subprocess checks on each status request.

Recipe 2 explicitly installs `audioread>=3`: audio-separator's `spec_utils` imports it directly,
but upstream does not declare it and librosa 1.0 no longer supplies it transitively. The recipe also
includes upstream's conditional `audioop-lts>=0.2.1` dependency for Python 3.13, where the standard
library removed `audioop` used by pydub. Recipe 1 and version-only markers are stale and require
explicit reinstallation. Import verification failures preserve the previous managed runtime.

Catalog compatibility separates host capability from runtime readiness and computes both across validated
variants only. On Apple Silicon each allowlisted model selects `audio-separator` when the portable runtime is ready. Otherwise
its row stays browsable as **Runtime required · macOS (Apple Silicon)**, normal selectors exclude it, and
Model Manager offers the explicit portable installer. Installation is never triggered by page load, opening Model
Manager, or selecting a tab. The installer has portable POSIX/Windows venv path handling, but Riffroom setup and
these models' declared/validated support remain Apple Silicon macOS only; Windows and Linux setup and validation
are future work.

## Current Apple Silicon runtime

`mlx-audio-separator` 0.1.7 provides native Apple GPU inference for Demucs, MDXC/RoFormer, MDX and VR
architectures. Upstream publishes validation evidence and scoped MLX/PyTorch performance comparisons, but those
are not M1 timings or guarantees. This app uses one worker and batch size one to limit memory use. PyTorch is
installed for first-run checkpoint conversion. The package declares this complete inference stack in its optional
`mlx` dependency group, and the four curated profiles remain visible but report runtime-unavailable if that group
is missing. [Runtime source](https://github.com/ssmall256/mlx-audio-separator).

The original Demucs Python package is pinned to 4.0.1 with Torch/Torchaudio 2.8.0 for compatibility with the tested conversion path. Inference uses MLX, rather than PyTorch's MPS implementation.

This dependency split does not yet broaden supported platforms: all declared model variants remain
`macos-arm64`. The existing setup script still installs the full Apple stack from `requirements-lock.txt`; that
lock and the launch scripts are intentionally unchanged until the later cross-platform setup phase.

## Lead/rhythm guitar

The released profiles here target instrument classes, not musical roles. They cannot reliably label a solo guitar separately from simultaneously playing rhythm guitars. The [Demucs lead/rhythm discussion](https://github.com/facebookresearch/demucs/issues/588) illustrates that this requires a different training target. We did not establish a dependable local open checkpoint for that target during this research. Commercial services may offer role separation, but they do not satisfy this app's local-only requirement.

No stereo-center subtraction, EQ split, or duplicated guitar output is presented as lead/rhythm separation. A future model can add new named stems without changing the mixer engine.

## Weight management

Profiles are assembled in `backend/riffroom/models.py`: curated and validated portable definitions are static,
while the broader community definitions come only from the two optional pinned bundled metadata files described
above. The MLX provider owns the runtime's
construction, separation parameters and float WAV writer override; the lower-level adapter in `separator.py` uses
the upstream model registry for downloads and the author's published Hugging Face files for guitar focus. That
adapter and `mlx_audio_separator` are loaded only after the optional provider runtime is resolved, not while the
app or provider registry imports. Atomic
downloads prevent cancelled downloads from becoming valid cache hits. Model WAV outputs use float32 without
independently normalizing each stem, preserving the model's relative output levels. A final playback compressor
limits boosted sums; 100% faders are not guaranteed to reconstruct the original mix exactly because separation
itself is approximate.

Cache reporting and removal cover only exact model-specific files under Riffroom's configured `data/models`
root. For the two Demucs profiles this means the profile YAML, its specifically named top-level `.th`
checkpoints, and its `demucs-mlx/<profile>.safetensors` plus JSON conversion metadata. For BS-RoFormer SW it
means `BS-Roformer-SW.ckpt` and `BS-Roformer-SW.yaml`; for guitar focus it means
`becruily_guitar.ckpt` and `config_guitar_becruily.yaml`. Exact `.part` files left by an interrupted atomic
download are also attributed to their model for size reporting and cleanup.

Community cache accounting uses only checkpoint and config basenames explicitly present in `models.json`, under
Riffroom's configured model root. Cleanup is disabled when an eligible checkpoint shares a config filename with
another bundled registry entry. Shared provider metadata such as `download_checks.json`, `vr_model_data.json` and
`mdx_model_data.json` is never attributed to one model and is never removed by Model Manager.

Model-specific prepared-file reporting and cleanup are disabled for every portable-routed community model. `audio-separator` may own
additional registry and download artifacts that this slice cannot completely enumerate. Riffroom therefore does
not pretend that deleting only a checkpoint/config basename is complete or safe, and never removes provider-owned shared
caches.

**Remove prepared files** is safe and idempotent, and is unavailable while the selected model is queued or
processing. It does not touch track originals, completed stem WAVs, manifests, the shared
`download_checks.json` registry, or the `TORCH_HOME`/`data/models/torch` provider cache. Consequently the shown
size is the model-specific Riffroom cache size, not every byte a provider may have downloaded. Removing Demucs
files makes Riffroom prepare the MLX conversion again on next use, while shared upstream Torch checkpoint bytes
may remain.

Weights are not checked into this repository. Runtime and architecture source licenses are separate from checkpoint
licenses; an open runtime does not make a checkpoint open. The catalog therefore reports checkpoint terms as
open, non-commercial or unverified alongside the existing usage-terms text. Revisit the source terms before
distributing or commercializing the app.

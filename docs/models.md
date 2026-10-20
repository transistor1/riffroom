# Model decision record · 2026-09-18

## Why these profiles

The target is an M1 MacBook Air with 16 GB unified memory. Independent guitar, drums and bass controls matter more here than vocal-only benchmark scores. Riffroom therefore includes several complementary profiles and retains each run for listening comparisons. No cross-model quality ranking is claimed from our synthetic smoke tests.

**Default: HTDemucs six sources (`htdemucs_6s`).** A mature, MIT-licensed baseline with guitar/piano added to the usual four sources. The authors explicitly describe piano separation as limited. The fine-tuned four-source ensemble (`htdemucs_ft`) is also included for drums/bass/vocals, with guitar in Other. [Demucs primary documentation](https://github.com/facebookresearch/demucs).

**Alternative: BS-RoFormer SW (`BS-Roformer-SW.ckpt`).** A six-source community checkpoint supported by the chosen runtime. It offers another architecture to compare when Demucs guitar extraction has bleed. The inference implementation is open source, but a clear license for redistribution of these particular weights was not established. We download through the runtime's public registry and do not commit or distribute the weights. [MLX separator documentation and BS-RoFormer SW profile](https://github.com/ssmall256/mlx-audio-separator), [original BS-RoFormer paper](https://arxiv.org/abs/2309.02612).

**Guitar specialist: becruily's Mel-Band RoFormer (`becruily_guitar.ckpt`).** Its published config targets Guitar and Other. It is a useful additional listening comparison for removing or learning guitar parts, at the cost of losing separate bass/drum faders in that result. The author's stated permission covers non-commercial use; this is not a claim of OSI-open weight licensing. [Author's model/config](https://huggingface.co/becruily/mel-band-roformer-guitar/blob/main/config_guitar_becruily.yaml), [author's licensing statement](https://huggingface.co/becruily/mel-band-roformer-guitar/discussions/9).

**General guitar specialist: MVSep Mega 53 BS-RoFormer (`mvsep-guitar`).** Uses
`bs_mega_53stem_guitar_mvsep.ckpt` with `bs_mega_53stem_guitar_mvsep_config.yaml` from the
[upstream model page](https://huggingface.co/noblebarkrr/BS-Roformer-MVSep-Mega-53-stems).
The exact checkpoint/config pair has been validated on an actual Mac GPU through Riffroom's existing
`MlxAudioSeparatorProvider`: loading, MLX conversion and inference produced `guitar.wav` and `other.wav`.
This is general guitar-vs-other separation, not lead-vs-rhythm. It uses the existing BS-RoFormer path
on macOS Apple Silicon only. Checkpoint terms are unverified.

**Electric guitar specialist: MVSep Electric Guitar (`mvsep-electric-guitar`).** Separates
`electric-guitar` vs `other`, using `bs_mega_53stem_electric-guitar_mvsep.ckpt` and
`bs_mega_53stem_electric-guitar_mvsep_config.yaml` from the same upstream family.

**Acoustic guitar specialist: MVSep Acoustic Guitar (`mvsep-acoustic-guitar`).** Separates
`acoustic-guitar` vs `other`, using `bs_mega_53stem_acoustic-guitar_mvsep.ckpt` and
`bs_mega_53stem_acoustic-guitar_mvsep_config.yaml` from the same upstream family.

All three MVSep guitar choices use the existing MLX BS-RoFormer path on macOS Apple Silicon only,
with checkpoint terms unverified. Electric/acoustic describe instrument classes, not lead/rhythm roles.
The two additions have catalog, download-contract and output-naming test coverage; the actual Mac GPU
validation described above applies to the general guitar model.

**Vocal specialist: Kimberley Jensen's Mel-Band RoFormer (`vocals_mel_band_roformer.ckpt`).** The curated `roformer-vocals` profile adds vocals/instrumental separation for vocal practice and accompaniment, with MIT-licensed weights. It uses the upstream registry entry “Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen” and `vocals_mel_band_roformer.yaml`. MLX is validated on `macos-arm64`, and the exact audio-separator 0.47.0 variant is validated on Windows x86-64. [Author's model](https://huggingface.co/KimberleyJSN/melbandroformer).

## Provider-aware catalog

The catalog has two layers. The eight hand-reviewed profiles form the curated, recommended set and are the only
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
ordered tuple of explicitly reviewed execution variants. Every curated portable candidate retains
`mlx-audio-separator` first, so Apple Silicon continues to prefer MLX. Portable routing is a server-owned
allowlist, not a consequence of architecture support. The execution-validated portion of the
`audio-separator` 0.47.0 allowlist contains these filenames:

- `htdemucs_6s.yaml`: Guitar, Vocals, Drums, Bass, Piano and Other; a second variant on curated `demucs-6`.
- `htdemucs_ft.yaml`: Vocals, Drums, Bass and Other; a second variant on curated `demucs-ft`.
- `BS-Roformer-SW.ckpt`: Guitar, Vocals, Drums, Bass, Piano and Other; a second variant on curated `roformer-6`.
- `vocals_mel_band_roformer.ckpt`: Vocals and Instrumental; a second variant on curated `roformer-vocals`.
- `UVR-MDX-NET-Inst_HQ_5.onnx`: Instrumental and Vocals.
- `MDX23C-DrumSep-aufr33-jarredou.ckpt`: Kick, Snare, Toms, HH, Ride and Crash.
- `mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`: Vocals and Instrumental.

Windows x86-64 live execution is narrower: `htdemucs_6s.yaml`, `htdemucs_ft.yaml`,
`BS-Roformer-SW.ckpt`, `vocals_mel_band_roformer.ckpt`, and
`MDX23C-DrumSep-aufr33-jarredou.ckpt` are supported there after successful CUDA runs.
The MDX-Net and karaoke community pilots remain experimental on Windows because they have not completed a real
Windows run.

The first Windows CUDA run of `vocals_mel_band_roformer.ckpt` exposed an output-name mismatch: the runtime called
the backing stem `other` while the logical Riffroom profile calls it `instrumental`. The portable variant carries
an explicit trusted `other` to `instrumental` output alias. A live rerun after that fix completed successfully end
to end with readable, aligned logical outputs, validating this exact Windows variant.

`becruily_guitar.ckpt` and the three `bs_mega_53stem_*_mvsep.ckpt` specialists occur in neither the bundled
audio-separator registry nor the cached UVR registry. They remain MLX-only; architecture support by itself is not
evidence that those exact checkpoint/config pairs are downloadable or runnable.

The Phase 3D2 follow-up tested both curated Demucs candidates with a generated six-second stereo WAV on Apple
Silicon. `audio-separator` imports DiffQ symbols while loading its Demucs modules even though the unquantized
`htdemucs_6s` checkpoint does not exercise the quantized-state branches. The real `diffq 0.2.4` package built and
imported after Torch when the build selected the installed Command Line Tools; no compatibility shim is used.
`htdemucs_6s.yaml` then exited successfully and produced exactly its six trusted stems as readable 44.1 kHz
stereo WAVs. Its existing curated `demucs-6` row has MLX first/preferred and `audio-separator` second, without
changing its logical ID, metadata, trusted stems, or prepared-file ownership. The `htdemucs_ft` attempt again
could not resolve `dl.fbaipublicfiles.com` to download its missing checkpoint, so at that point it remained an
experimental Windows validation candidate rather than an execution-validated portable model. A later Windows
CUDA run obtained the model and completed end to end, superseding that earlier download-bound result for Windows
support.

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
`data/runtimes/audio-separator/venv`. Installation is an explicit Model Manager action. Existing platforms keep
the exact `audio-separator[cpu]==0.47.0` recipe. Windows x86-64 instead installs
`audio-separator[gpu]==0.47.0` without dependencies, then installs the matched
`torch==2.8.0+cu128`, `torchvision==0.23.0+cu128`, and `torchaudio==2.8.0+cu128` stack from PyTorch's fixed CUDA
12.8 wheel index and `onnxruntime-gpu==1.23.2`; the main project dependency and lock files do not include this
isolated runtime. `onnx2torch-py313` requires `torchvision>=0.9`, so an unconstrained resolver can select the newest
torchvision and replace CUDA Torch with the newer CPU Torch version it requires. Riffroom applies the three exact
CUDA package versions as constraints to every later dependency install. Those wheels supply the needed CUDA/cuDNN
runtime libraries, so a full CUDA Toolkit is not required. Riffroom installs the remaining dependencies separately before the real platform-specific DiffQ package. On
macOS, DiffQ's build selects the installed Command Line Tools when available. The unused,
x86_64-only library bundled by `samplerate==0.1.0` remains excluded. Riffroom creates a temporary venv with its
running Python, verifies that Torch and its companions still have the expected CUDA versions, verifies that
`torch.version.cuda` is non-null without calling `torch.cuda.is_available()`, then checks the CLI and imports
`Separator`, `DemucsSeparator`, and `HTDemucs` without downloading models or requiring an NVIDIA GPU. It then
atomically promotes the runtime. A valid
`RIFFROOM_AUDIO_SEPARATOR_BIN` administrator override takes precedence, followed by `PATH`, then the managed copy.
Package names, versions, executable paths and provider classes are not accepted from HTTP or model metadata.

Managed installations also carry a Riffroom recipe revision, separate from the displayed upstream `0.47.0`.
Dependency recipe changes invalidate older managed installations even if that upstream version is unchanged.
In particular, an old `VERSION` marker containing only `0.47.0` requires explicit reinstallation in Model Manager
to obtain the real DiffQ dependency. Installation writes the revision-aware marker only after all dependencies
and execution-stack import and CLI checks succeed; a failed replacement restores the previous runtime. Discovery
uses the marker without execution checks. On Windows x86-64, runtime status additionally performs one bounded,
cached probe of the managed interpreter. It exposes only `cuda` plus a sanitized GPU name, `cpu`, or an unknown
result; subprocess diagnostics and host paths are not returned.

Windows x86-64 recipe 5 retains the explicit `audioread>=3` install from recipe 3:
audio-separator's `spec_utils` imports it directly,
but upstream does not declare it and librosa 1.0 no longer supplies it transitively. The recipe also
includes upstream's conditional `audioop-lts>=0.2.1` dependency for Python 3.13, where the standard
library removed `audioop` used by pydub. Older recipe and version-only markers are stale and require
explicit reinstallation on Windows x86-64; unchanged hosts retain recipe 3. Import verification failures
preserve the previous managed runtime.

Catalog compatibility separates host capability from runtime readiness and computes both across trusted
variants only. Apple Silicon prefers a compatible MLX variant before considering the portable provider. On
Windows x86-64 each allowlisted portable model selects `audio-separator` when the runtime is ready. Otherwise
its row stays browsable as **Runtime required** (or **Experimental runtime required** for a validation candidate), normal selectors exclude it, and
Model Manager offers the explicit portable installer. Installation is never triggered by page load, opening Model
Manager, or selecting a tab. Windows x86-64 is supported with limited model availability; experimental labels are
model-specific. Windows ARM64 and Linux execution remain unavailable.

The CUDA versions follow the official [PyTorch 2.8 wheel matrix](https://pytorch.org/get-started/previous-versions/)
and [ONNX Runtime CUDA/PyTorch compatibility guidance](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).

## Current Apple Silicon runtime

`mlx-audio-separator` 0.1.7 provides native Apple GPU inference for Demucs, MDXC/RoFormer, MDX and VR
architectures. Upstream publishes validation evidence and scoped MLX/PyTorch performance comparisons, but those
are not M1 timings or guarantees. This app uses one worker and batch size one to limit memory use. PyTorch is
installed for first-run checkpoint conversion. The package declares this complete inference stack in its optional
`mlx` dependency group, and the eight curated profiles remain visible but report runtime-unavailable if that group
is missing. [Runtime source](https://github.com/ssmall256/mlx-audio-separator).

The original Demucs Python package is pinned to 4.0.1 with Torch/Torchaudio 2.8.0 for compatibility with the tested conversion path. Inference uses MLX, rather than PyTorch's MPS implementation.

This dependency split preserves the Apple Silicon MLX preference even where a curated model also has a portable
Windows candidate. The existing setup script still installs the full Apple stack from `requirements-lock.txt`.

## Lead/rhythm guitar

The curated `listra92-lead-rhythm` profile uses Mel-Band RoFormer to split an existing guitar stem.
Choose it in the guitar channel's existing **Split further** menu; the existing run lineage, child
selection, parent replacement, collapse and mixer controls apply without a separate workflow.
It produces `lead` and `rhythm`. The author's config has `num_stems: 1`, instruments `[Lead, Rhythm]`
and target `Lead`: lead is a learned prediction and rhythm is the upstream runtime's residual.
Use a guitar stem as input; on a full mix the residual will also contain other instruments.
Role separation quality varies with arrangement; a synthetic execution check does not establish quality.

Authoritative artifacts are in [listra92/MyModels](https://huggingface.co/listra92/MyModels/tree/aae55d81e0bce315bcb17bcf46c40f23cce41f5b/misc),
pinned at `aae55d81e0bce315bcb17bcf46c40f23cce41f5b`:

- Checkpoint `misc/model_mel_band_roformer_ep_72_sdr_3.2232.ckpt`, 337,073,664 bytes,
  SHA-256 `b3c47bca33609ca1ba0bb2d2076410bfd1eb941b051b72afc1f3e24d12b17eef`.
- Config `misc/config_mel_band_roformer_Lead_Rhythm_Guitar.yaml`, SHA-256
  `fc47975bba58b7b4c6de363bfe158943092c77bfb0b9a41c0c741eafba330359`.

The [MVSep-less mirror](https://huggingface.co/noblebarkrr/mvsepless_resources/tree/283025218e6447db47da1ad18df3c2f67ca8d66d/mel_band_roformer)
attributes the checkpoint to listra92 and exposes the identical checkpoint LFS SHA-256 under
`mbr_lead_rhythm_guitar_listra92.ckpt`. Its config changes inference batching/overlap; Riffroom downloads
the author's original config and applies only batch size 1 / overlap 2 for inference memory and overlap.
The author's repository card declares `openrail++`; no checkpoint-specific license text or grant was
found. Riffroom therefore reports terms as **unverified**, does not call the weights MIT or unrestricted,
and downloads them on demand rather than redistributing them.

The managed `audio-separator==0.47.0` runtime supports this Mel-Band architecture, two instrument names
and residual inference, but its bundled model registry lacks this exact checkpoint/config. The narrowly
scoped `providers/listra92.py` adapter runs using Python beside the selected audio-separator executable.
It overrides the trusted download lookup and delegates loading and inference to upstream MDXC.
The 0.47.0 Mel-Band constructor omits `mlp_expansion_factor` when creating its mask estimators,
silently retaining factor 4 despite this author's factor 2 config. The adapter scopes a constructor
correction to this isolated model load, then restores the original constructor. The checkpoint's
`[768, 384]` first mask weight confirms factor 2; strict state-dictionary loading is preserved.
Both downloads are revision-pinned, SHA-256 checked (including cache hits), and atomically published.
No Sound Razor dependency, new runtime installation recipe, alternate UI, arbitrary URL or config input
is introduced. Apple Silicon is the supported host; Windows x86-64 remains experimental until a real
Windows execution is recorded. Other models retain their existing provider routing.

## Weight management

Profiles are assembled in `backend/riffroom/models.py`: curated and validated portable definitions are static,
while the broader community definitions come only from the two optional pinned bundled metadata files described
above. The MLX provider owns the runtime's
construction, separation parameters and float WAV writer override; the lower-level adapter in `separator.py` uses
the upstream model registry for downloads and exact trusted Hugging Face files for becruily guitar focus and the three MVSep guitar specialists. That
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
`becruily_guitar.ckpt` and `config_guitar_becruily.yaml`; for MVSep guitar it means
`bs_mega_53stem_guitar_mvsep.ckpt` and `bs_mega_53stem_guitar_mvsep_config.yaml`. The electric and acoustic
profiles each own their respective checkpoint/YAML pair listed above. For Kimberley vocals it means
`vocals_mel_band_roformer.ckpt` and `vocals_mel_band_roformer.yaml`. Exact `.part` files left by an interrupted atomic
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

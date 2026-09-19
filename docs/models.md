# Model decision record · 2026-09-18

## Why these profiles

The target is an M1 MacBook Air with 16 GB unified memory. Independent guitar, drums and bass controls matter more here than vocal-only benchmark scores. Riffroom therefore includes several complementary profiles and retains each run for listening comparisons. No cross-model quality ranking is claimed from our synthetic smoke tests.

**Default: HTDemucs six sources (`htdemucs_6s`).** A mature, MIT-licensed baseline with guitar/piano added to the usual four sources. The authors explicitly describe piano separation as limited. The fine-tuned four-source ensemble (`htdemucs_ft`) is also included for drums/bass/vocals, with guitar in Other. [Demucs primary documentation](https://github.com/facebookresearch/demucs).

**Alternative: BS-RoFormer SW (`BS-Roformer-SW.ckpt`).** A six-source community checkpoint supported by the chosen runtime. It offers another architecture to compare when Demucs guitar extraction has bleed. The inference implementation is open source, but a clear license for redistribution of these particular weights was not established. We download through the runtime's public registry and do not commit or distribute the weights. [MLX separator documentation and BS-RoFormer SW profile](https://github.com/ssmall256/mlx-audio-separator), [original BS-RoFormer paper](https://arxiv.org/abs/2309.02612).

**Guitar specialist: becruily's Mel-Band RoFormer (`becruily_guitar.ckpt`).** Its published config targets Guitar and Other. It is a useful additional listening comparison for removing or learning guitar parts, at the cost of losing separate bass/drum faders in that result. The author's stated permission covers non-commercial use; this is not a claim of OSI-open weight licensing. [Author's model/config](https://huggingface.co/becruily/mel-band-roformer-guitar/blob/main/config_guitar_becruily.yaml), [author's licensing statement](https://huggingface.co/becruily/mel-band-roformer-guitar/discussions/9).

## Provider-aware catalog

The catalog has two layers. The four hand-reviewed profiles remain the curated, recommended set and are the only
cards on the import page. The Model Manager also exposes a community layer generated from metadata bundled in the
pinned `mlx-audio-separator` 0.1.7 wheel. The API compares every profile's declared platform capabilities with a
stable current-platform key such as `macos-arm64`, `windows-x86_64` or `linux-x86_64`; the manager presents that
result instead of making its own operating-system assumptions.

The authoritative community inputs are the installed package's `mlx_audio_separator/models.json` and
`mlx_audio_separator/models-scores.json` files. In the inspected 0.1.7 package:

- `models.json` provides the friendly-name key, architecture registry group, checkpoint filename and, for MDXC
  and RoFormer entries, an optional config filename.
- `models-scores.json` is keyed by checkpoint filename and may provide `model_name`, `stems`, `target_stem`,
  median scores and per-track scores. Riffroom uses only its explicit, non-empty `stems` field for eligibility.
- Neither bundled file provides a per-checkpoint source URL or checkpoint license/usage terms.

The bundled registry contains 83 entries, but only 27 have a matching non-empty `stems` list in the bundled score
metadata. Those 27 are runnable community entries; the other 56 are excluded rather than deriving outputs from
names or filenames. Riffroom does not use the runtime's separately downloaded, mutable `download_checks.json` to
expand the displayed catalog. Community source links therefore point to the runtime project page, not a fabricated
checkpoint page. Every community entry says **Checkpoint terms unverified** because the runtime's code license says
nothing about the checkpoint's usage rights.

Community IDs are `community-` plus the complete SHA-256 digest of the registry checkpoint filename. Clients can
submit only these generated IDs or curated IDs; the server resolves the ID back to its trusted profile. A raw
filename, path, URL, Python module or other user-supplied loading instruction is never accepted. Curated IDs take
precedence if a generated catalog entry ever collides.

All profiles use the existing `mlx-audio-separator` provider and support `macos-arm64`. The manager reports
each profile as **Prepared** only when all of its declared Riffroom-owned files are present and non-empty;
otherwise it reports **Downloads on first use**. Choosing **Use model** changes the current import/separation
selection without starting work. It also adds that model to the browser's personal working set. The full curated
and community catalog always remains browsable in Model Manager, while normal separation menus show only this
smaller working set. A new browser profile starts with every compatible curated model shown and no community
models; users can show community models or hide curated models with **Show in separation menus**. The preference
is versioned local browser state, is validated against the current API catalog, and falls back to the compatible
curated set if storage is unavailable or invalid. At least one compatible model must remain visible. First-use
separation remains responsible for downloading and converting files; there is no separate install or preload job.

The next provider is expected to be a validated portable adapter, likely based on `python-audio-separator`.
Adding it must not make every checkpoint universally compatible: compatibility stays per model and provider,
based on tested runtime, architecture and platform capabilities. Arbitrary remote catalog or file import remains
deferred.

## Current Apple Silicon runtime

`mlx-audio-separator` 0.1.7 provides native Apple GPU inference for Demucs, MDXC/RoFormer, MDX and VR
architectures. Upstream publishes validation evidence and scoped MLX/PyTorch performance comparisons, but those
are not M1 timings or guarantees. This app uses one worker and batch size one to limit memory use. PyTorch is
installed for first-run checkpoint conversion. [Runtime source](https://github.com/ssmall256/mlx-audio-separator).

The original Demucs Python package is pinned to 4.0.1 with Torch/Torchaudio 2.8.0 for compatibility with the tested conversion path. Inference uses MLX, rather than PyTorch's MPS implementation.

## Lead/rhythm guitar

The released profiles here target instrument classes, not musical roles. They cannot reliably label a solo guitar separately from simultaneously playing rhythm guitars. The [Demucs lead/rhythm discussion](https://github.com/facebookresearch/demucs/issues/588) illustrates that this requires a different training target. We did not establish a dependable local open checkpoint for that target during this research. Commercial services may offer role separation, but they do not satisfy this app's local-only requirement.

No stereo-center subtraction, EQ split, or duplicated guitar output is presented as lead/rhythm separation. A future model can add new named stems without changing the mixer engine.

## Weight management

Profiles are assembled in `backend/riffroom/models.py`: curated definitions are static, while community definitions
come only from the two pinned bundled metadata files described above. The adapter in `separator.py` uses the
upstream model registry for downloads and the author's published Hugging Face files for guitar focus. Atomic
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

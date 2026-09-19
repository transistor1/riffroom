# Model decision record · 2026-09-18

## Why these profiles

The target is an M1 MacBook Air with 16 GB unified memory. Independent guitar, drums and bass controls matter more here than vocal-only benchmark scores. Riffroom therefore includes several complementary profiles and retains each run for listening comparisons. No cross-model quality ranking is claimed from our synthetic smoke tests.

**Default: HTDemucs six sources (`htdemucs_6s`).** A mature, MIT-licensed baseline with guitar/piano added to the usual four sources. The authors explicitly describe piano separation as limited. The fine-tuned four-source ensemble (`htdemucs_ft`) is also included for drums/bass/vocals, with guitar in Other. [Demucs primary documentation](https://github.com/facebookresearch/demucs).

**Alternative: BS-RoFormer SW (`BS-Roformer-SW.ckpt`).** A six-source community checkpoint supported by the chosen runtime. It offers another architecture to compare when Demucs guitar extraction has bleed. The inference implementation is open source, but a clear license for redistribution of these particular weights was not established. We download through the runtime's public registry and do not commit or distribute the weights. [MLX separator documentation and BS-RoFormer SW profile](https://github.com/ssmall256/mlx-audio-separator), [original BS-RoFormer paper](https://arxiv.org/abs/2309.02612).

**Guitar specialist: becruily's Mel-Band RoFormer (`becruily_guitar.ckpt`).** Its published config targets Guitar and Other. It is a useful additional listening comparison for removing or learning guitar parts, at the cost of losing separate bass/drum faders in that result. The author's stated permission covers non-commercial use; this is not a claim of OSI-open weight licensing. [Author's model/config](https://huggingface.co/becruily/mel-band-roformer-guitar/blob/main/config_guitar_becruily.yaml), [author's licensing statement](https://huggingface.co/becruily/mel-band-roformer-guitar/discussions/9).

## Provider-aware catalog

The curated registry records each model's architecture, runtime provider, supported platform keys, output stems,
source, catalog origin and checkpoint-terms status. The API compares those declared capabilities with a stable
current-platform key such as `macos-arm64`, `windows-x86_64` or `linux-x86_64`; the model manager presents that
result instead of making its own operating-system assumptions.

This first phase is catalog and UI groundwork. All four profiles still use the existing
`mlx-audio-separator` provider and support `macos-arm64`. The manager does not claim that weights are installed:
curated weights download on first use, as before. Install/remove controls and cache state belong to a later phase.

The next provider is expected to be a validated portable adapter, likely based on `python-audio-separator`.
Adding it must not make every checkpoint universally compatible: compatibility stays per model and provider,
based on tested runtime, architecture and platform capabilities. Dynamic upstream catalogs are also deferred;
Riffroom continues to expose only reviewed profiles.

## Current Apple Silicon runtime

`mlx-audio-separator` 0.1.7 provides native Apple GPU inference for both Demucs and RoFormer architectures. Upstream publishes validation evidence and scoped MLX/PyTorch performance comparisons, but those are not M1 timings or guarantees. This app uses one worker and batch size one to limit memory use. PyTorch is installed for first-run checkpoint conversion. [Runtime source](https://github.com/ssmall256/mlx-audio-separator).

The original Demucs Python package is pinned to 4.0.1 with Torch/Torchaudio 2.8.0 for compatibility with the tested conversion path. Inference uses MLX, rather than PyTorch's MPS implementation.

## Lead/rhythm guitar

The released profiles here target instrument classes, not musical roles. They cannot reliably label a solo guitar separately from simultaneously playing rhythm guitars. The [Demucs lead/rhythm discussion](https://github.com/facebookresearch/demucs/issues/588) illustrates that this requires a different training target. We did not establish a dependable local open checkpoint for that target during this research. Commercial services may offer role separation, but they do not satisfy this app's local-only requirement.

No stereo-center subtraction, EQ split, or duplicated guitar output is presented as lead/rhythm separation. A future model can add new named stems without changing the mixer engine.

## Weight management

Profiles are curated in `backend/riffroom/models.py`. The adapter in `separator.py` uses the upstream model registry for supported profiles and the author's published Hugging Face files for guitar focus. Atomic downloads prevent cancelled downloads from becoming valid cache hits. Model WAV outputs use float32 without independently normalizing each stem, preserving the model's relative output levels. A final playback compressor limits boosted sums; 100% faders are not guaranteed to reconstruct the original mix exactly because separation itself is approximate.

Weights are not checked into this repository. Runtime and architecture source licenses are separate from checkpoint
licenses; an open runtime does not make a checkpoint open. The catalog therefore reports checkpoint terms as
open, non-commercial or unverified alongside the existing usage-terms text. Revisit the source terms before
distributing or commercializing the app.

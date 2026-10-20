"""One pinned checkpoint registration for the managed audio-separator interpreter.

Executed as a script so the application environment never imports Torch. Only the
download lookup and mask expansion are adapted; inference and residuals stay upstream.
"""

import hashlib
import os
import urllib.request
from contextlib import contextmanager
from functools import partial
from pathlib import Path

MODEL_ID = "listra92-lead-rhythm"
CHECKPOINT = "listra92_mel_band_roformer_lead_rhythm.ckpt"
CONFIG = "listra92_mel_band_roformer_lead_rhythm.yaml"
REVISION = "aae55d81e0bce315bcb17bcf46c40f23cce41f5b"
SOURCE = f"https://huggingface.co/listra92/MyModels/resolve/{REVISION}/misc/"
ARTIFACTS = (
    (CHECKPOINT, "model_mel_band_roformer_ep_72_sdr_3.2232.ckpt",
     "b3c47bca33609ca1ba0bb2d2076410bfd1eb941b051b72afc1f3e24d12b17eef"),
    (CONFIG, "config_mel_band_roformer_Lead_Rhythm_Guitar.yaml",
     "fc47975bba58b7b4c6de363bfe158943092c77bfb0b9a41c0c741eafba330359"),
)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_artifacts(cache: Path) -> None:
    """Download atomically and verify both new and already cached artifacts."""
    cache.mkdir(parents=True, exist_ok=True)
    for filename, upstream, expected in ARTIFACTS:
        path = cache / filename
        if path.is_symlink():
            raise ValueError(f"Refusing symlink model artifact: {filename}")
        if path.is_file() and _digest(path) == expected:
            continue
        partial = path.with_name(filename + ".part")
        owned_partial = False
        try:
            # Exclusive creation also rejects symlinks and concurrent writers.
            with partial.open("xb") as target:
                owned_partial = True
                with urllib.request.urlopen(SOURCE + upstream, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        target.write(chunk)
            if _digest(partial) != expected:
                raise ValueError(f"SHA-256 mismatch for {filename}")
            os.replace(partial, path)
        except FileExistsError:
            raise RuntimeError(f"Model download already in progress or interrupted: {filename}") from None
        finally:
            # Do not remove another writer's partial file.
            if owned_partial:
                partial.unlink(missing_ok=True)


@contextmanager
def mask_expansion_compatibility(module):
    """0.47.0 omits mlp_expansion_factor when constructing Mel mask estimators.

    This checkpoint's config and [768, 384] mask weights require factor 2.
    Keep the correction local to construction in this isolated model process.
    """
    original = module.MaskEstimator
    module.MaskEstimator = partial(original, mlp_expansion_factor=2)
    try:
        yield
    finally:
        module.MaskEstimator = original


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.output = args.output.resolve()
    args.cache = args.cache.resolve()

    from audio_separator.separator import Separator
    from audio_separator.separator.uvr_lib_v5.roformer import mel_band_roformer

    class ListraSeparator(Separator):
        def download_model_files(self, model_filename):
            if model_filename != CHECKPOINT:
                raise ValueError("Only the pinned listra92 checkpoint is allowed")
            prepare_artifacts(args.cache)
            self.model_is_uvr_vip = False
            self.model_friendly_name = "Mel-Band RoFormer Lead/Rhythm Guitar by listra92"
            return CHECKPOINT, "MDXC", self.model_friendly_name, str(args.cache / CHECKPOINT), str(args.cache / CONFIG)

    separator = ListraSeparator(
        model_file_dir=str(args.cache), output_dir=str(args.output),
        output_format="WAV", normalization_threshold=1.0, amplification_threshold=0.0,
        use_soundfile=True, mdxc_params={"batch_size": 1, "overlap": 2},
    )
    with mask_expansion_compatibility(mel_band_roformer):
        separator.load_model(CHECKPOINT)
    separator.separate(str(args.source), custom_output_names={"Lead": "lead", "Rhythm": "rhythm"})


if __name__ == "__main__":
    main()

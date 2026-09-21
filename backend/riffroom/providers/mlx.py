"""MLX Audio Separator provider with the existing Riffroom runtime settings."""

import logging
from collections.abc import Callable
from pathlib import Path

from riffroom.audio import write_float_stem
from riffroom.models import ExecutionVariant, ModelProfile
from riffroom.providers.base import normalized_stem_paths
from riffroom.separator import LocalSeparator, configure_demucs_cache


class MlxAudioSeparatorProvider:
    """Run a trusted catalog profile through mlx-audio-separator."""

    def is_available(self) -> bool:
        """The MLX runtime is installed as part of the current app environment."""
        return True

    def separate(
        self,
        profile: ModelProfile,
        variant: ExecutionVariant,
        source: Path,
        output: Path,
        cache: Path,
        *,
        on_model_loaded: Callable[[], None],
    ) -> dict[str, Path]:
        configure_demucs_cache(cache)
        separator = LocalSeparator(
            log_level=logging.INFO,
            model_file_dir=str(cache),
            output_dir=str(output),
            output_format="WAV",
            normalization_threshold=1.0,
            amplification_threshold=0.0,
            save_converted_safetensors=True,
            demucs_params={
                "segment_size": "Default",
                "shifts": 1,
                "overlap": 0.25,
                "segments_enabled": True,
                "batch_size": 1,
                "seed": 42,
            },
            mdxc_params={
                "segment_size": 256,
                "override_model_segment_size": False,
                "batch_size": 1,
                "overlap": 2,
                "pitch_shift": 0,
            },
        )
        separator.load_model(variant.filename)
        separator.model_instance.write_audio = lambda path, samples: write_float_stem(output, path, samples)
        on_model_loaded()
        names = {name: name for name in profile.stems}
        separator.separate(str(source), custom_output_names=names)
        return normalized_stem_paths(profile.stems, output)

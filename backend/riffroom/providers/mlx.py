"""MLX Audio Separator provider with the existing Riffroom runtime settings."""

import logging
from collections.abc import Callable
from importlib import import_module, util
from pathlib import Path
from types import ModuleType

from riffroom.audio import write_float_stem
from riffroom.models import ExecutionVariant, ModelProfile
from riffroom.providers.base import normalized_stem_paths

_RUNTIME_MODULES = ("mlx_audio_separator", "mlx", "demucs", "torch", "torchaudio")
_UNAVAILABLE_MESSAGE = (
    "The MLX audio-separator runtime is unavailable. "
    "Install this checkout with the 'mlx' optional dependencies "
    "(`python -m pip install '.[mlx]'`) on Apple Silicon macOS."
)


class MlxRuntimeUnavailableError(RuntimeError):
    """Raised when a trusted MLX profile is invoked without its optional runtime."""


def _load_runtime() -> ModuleType:
    """Resolve the optional MLX stack without coupling provider registry imports to it."""
    try:
        if any(util.find_spec(module_name) is None for module_name in _RUNTIME_MODULES):
            raise ModuleNotFoundError
        return import_module("riffroom.separator")
    except (ImportError, OSError, ValueError) as exc:
        raise MlxRuntimeUnavailableError(_UNAVAILABLE_MESSAGE) from exc


class MlxAudioSeparatorProvider:
    """Run a trusted catalog profile through mlx-audio-separator."""

    def is_available(self) -> bool:
        """Report whether the complete optional MLX runtime can be resolved."""
        try:
            _load_runtime()
        except MlxRuntimeUnavailableError:
            return False
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
        runtime = _load_runtime()
        try:
            runtime.configure_demucs_cache(cache)
            separator = runtime.LocalSeparator(
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
        except (ImportError, OSError) as exc:
            raise MlxRuntimeUnavailableError(_UNAVAILABLE_MESSAGE) from exc
        separator.model_instance.write_audio = lambda path, samples: write_float_stem(output, path, samples)
        on_model_loaded()
        names = {name: name for name in profile.stems}
        separator.separate(str(source), custom_output_names=names)
        return normalized_stem_paths(profile.stems, output)

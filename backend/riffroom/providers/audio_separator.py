"""Out-of-process bridge to a separately installed audio-separator runtime."""

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from riffroom.models import ExecutionVariant, ModelProfile
from riffroom.providers.base import normalized_stem_paths
from riffroom.providers.listra92 import MODEL_ID

_UNAVAILABLE_MESSAGE = (
    "The portable audio-separator runtime is not installed/configured. "
    "Install audio-separator or set RIFFROOM_AUDIO_SEPARATOR_BIN to its executable."
)
_MAX_ERROR_DETAIL = 500


class CompletedProcessLike(Protocol):
    """The subprocess result fields used by this provider."""

    returncode: int
    stdout: str | bytes | None
    stderr: str | bytes | None


Runner = Callable[..., CompletedProcessLike]
ExecutableResolver = Callable[[str], str | None]


class AudioSeparatorCliProvider:
    """Run trusted profiles through the portable audio-separator CLI."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        executable_resolver: ExecutableResolver | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._executable_resolver = shutil.which if executable_resolver is None else executable_resolver
        self._runner = subprocess.run if runner is None else runner

    def _executable(self) -> str | None:
        configured = self._environ.get("RIFFROOM_AUDIO_SEPARATOR_BIN")
        if configured is not None:
            path = Path(configured)
            return str(path) if path.is_file() and os.access(path, os.X_OK) else None
        return self._executable_resolver("audio-separator")

    def is_available(self) -> bool:
        """Report whether the separately managed CLI runtime can be invoked."""
        return self._executable() is not None

    @staticmethod
    def _runtime_python(executable: str) -> Path:
        """Use the selected CLI's environment, including Windows console launchers."""
        directory = Path(executable).absolute().parent
        candidates = (directory / "python.exe", directory / "python", directory / "python3")
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
        raise RuntimeError("The listra92 model requires Python beside the selected audio-separator executable.")

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
        executable = self._executable()
        if executable is None:
            raise RuntimeError(_UNAVAILABLE_MESSAGE)

        output_names = {name: name for name in profile.stems}
        for upstream_name, logical_name in variant.output_aliases:
            if logical_name not in output_names or upstream_name in output_names:
                raise ValueError(
                    f"Invalid trusted output alias for model {profile.id}: "
                    f"{upstream_name} -> {logical_name}"
                )
            del output_names[logical_name]
            output_names[upstream_name] = logical_name
        # The pinned 0.47.0 CLI has no CUDA device option. Separator automatically
        # chooses CUDA when its Torch runtime reports it available, else CPU.
        argv = [
            executable,
            str(source),
            "--model_filename",
            variant.filename,
            "--output_dir",
            str(output),
            "--model_file_dir",
            str(cache),
            "--output_format",
            "WAV",
            "--normalization",
            "1.0",
            "--amplification",
            "0.0",
            "--use_soundfile",
            "--custom_output_names",
            json.dumps(output_names, sort_keys=True, separators=(",", ":")),
        ]
        if profile.id == MODEL_ID:
            argv = [
                str(self._runtime_python(executable)),
                "-I",  # Keep this directory's audio_separator.py out of runtime imports.
                str(Path(__file__).with_name("listra92.py")),
                str(source), str(output), str(cache),
            ]
        on_model_loaded()
        try:
            result = self._runner(argv, check=False, shell=False)
        except OSError:
            raise RuntimeError(_UNAVAILABLE_MESSAGE) from None
        if result.returncode != 0:
            detail = self._error_detail(result)
            message = f"audio-separator failed with exit code {result.returncode}."
            if detail:
                message += f" {detail}"
            message += " Check the worker log for details."
            raise RuntimeError(message)
        return normalized_stem_paths(
            profile.stems,
            output,
            output_aliases=variant.output_aliases,
        )

    @staticmethod
    def _error_detail(result: CompletedProcessLike) -> str:
        for value in (getattr(result, "stderr", None), getattr(result, "stdout", None)):
            if isinstance(value, bytes):
                value = value.decode(errors="replace")
            if value:
                compact = " ".join(value.split())
                if len(compact) > _MAX_ERROR_DETAIL:
                    return compact[:_MAX_ERROR_DETAIL] + "…"
                return compact
        return ""

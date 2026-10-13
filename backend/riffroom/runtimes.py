"""Server-owned installation and discovery for portable separation runtimes."""

import asyncio
import errno
import inspect
import json
import os
import platform as platform_module
import re
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

AUDIO_SEPARATOR_ID = "audio-separator"
AUDIO_SEPARATOR_DISPLAY_NAME = "Portable audio-separator runtime"
AUDIO_SEPARATOR_VERSION = "0.47.0"
# Bump whenever Riffroom's dependency recipe or installation procedure changes,
# even if the upstream package version stays the same. Legacy markers had no revision.
AUDIO_SEPARATOR_MANAGED_REVISION = "3"
AUDIO_SEPARATOR_WINDOWS_CUDA_MANAGED_REVISION = "5"
_MANAGED_MARKER = f"{AUDIO_SEPARATOR_VERSION}\nrecipe={AUDIO_SEPARATOR_MANAGED_REVISION}"
_WINDOWS_CUDA_MANAGED_MARKER = (
    f"{AUDIO_SEPARATOR_VERSION}\nrecipe={AUDIO_SEPARATOR_WINDOWS_CUDA_MANAGED_REVISION}"
)
AUDIO_SEPARATOR_PACKAGE = f"audio-separator[cpu]=={AUDIO_SEPARATOR_VERSION}"
AUDIO_SEPARATOR_WINDOWS_CUDA_PACKAGE = f"audio-separator[gpu]=={AUDIO_SEPARATOR_VERSION}"
AUDIO_SEPARATOR_WINDOWS_CUDA_TORCH = "torch==2.8.0+cu128"
AUDIO_SEPARATOR_WINDOWS_CUDA_TORCHVISION = "torchvision==0.23.0+cu128"
AUDIO_SEPARATOR_WINDOWS_CUDA_TORCHAUDIO = "torchaudio==2.8.0+cu128"
AUDIO_SEPARATOR_WINDOWS_CUDA_STACK = (
    AUDIO_SEPARATOR_WINDOWS_CUDA_TORCH,
    AUDIO_SEPARATOR_WINDOWS_CUDA_TORCHVISION,
    AUDIO_SEPARATOR_WINDOWS_CUDA_TORCHAUDIO,
)
AUDIO_SEPARATOR_WINDOWS_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
AUDIO_SEPARATOR_WINDOWS_CUDA_ONNX_RUNTIME = "onnxruntime-gpu==1.23.2"
_WINDOWS_CUDA_CONSTRAINTS_FILE = "windows-cuda-constraints.txt"
# samplerate 0.1.0 bundles an x86_64-only dylib and is not imported by the
# execution-validated paths. Install the remaining dependencies separately so
# the platform-specific diffq package is installed only after its Torch
# dependency is available.
_AUDIO_SEPARATOR_COMMON_DEPENDENCIES = (
    # Imported directly by spec_utils; librosa >=1 no longer brings it transitively.
    "audioread>=3",
    'audioop-lts>=0.2.1; python_version >= "3.13"',
    "beartype<0.19.0,>=0.18.5",
    "einops>=0.7",
    "julius>=0.2",
    "librosa>=0.10",
    "ml_collections",
    "numpy>=2",
    "onnx-weekly",
    "onnx2torch-py313>=1.6",
    "packaging",
    "pydub>=0.25",
    "pyyaml",
    "requests>=2",
    "resampy>=0.4",
    "rotary-embedding-torch<0.7.0,>=0.6.1",
    "scipy<2.0.0,>=1.13.0",
    "six>=1.16",
    "soundfile>=0.12",
)
AUDIO_SEPARATOR_DEPENDENCIES = _AUDIO_SEPARATOR_COMMON_DEPENDENCIES + (
    "torch<3,>=2.13",
    "tqdm",
    "onnxruntime>=1.17",
)
AUDIO_SEPARATOR_WINDOWS_CUDA_DEPENDENCIES = _AUDIO_SEPARATOR_COMMON_DEPENDENCIES + (
    "tqdm",
    AUDIO_SEPARATOR_WINDOWS_CUDA_ONNX_RUNTIME,
)
AUDIO_SEPARATOR_DIFFQ_DEPENDENCY = "diffq>=0.2"
AUDIO_SEPARATOR_WINDOWS_DIFFQ_DEPENDENCY = "diffq-fixed>=0.2"
# Exercise lazy execution imports without constructing a separator or downloading models.
_AUDIO_SEPARATOR_IMPORT_CHECK = (
    "import audioread; "
    "from audio_separator.separator import Separator; "
    "from audio_separator.separator.architectures.demucs_separator import DemucsSeparator; "
    "from audio_separator.separator.uvr_lib_v5.demucs.htdemucs import HTDemucs"
)
_WINDOWS_CUDA_BUILD_CHECK = (
    "import sys, torch, torchaudio, torchvision; "
    "valid = (torch.__version__ == '2.8.0+cu128' "
    "and torch.version.cuda is not None "
    "and torchvision.__version__ == '0.23.0+cu128' "
    "and torchaudio.__version__ == '2.8.0+cu128'); "
    "sys.exit(0 if valid else 1)"
)
_CUDA_PROBE = (
    "import json, torch; "
    "available = bool(torch.cuda.is_available()); "
    "device = torch.cuda.get_device_name(0) if available else None; "
    "print(json.dumps({'available': available, 'device': device}))"
)
AUDIO_SEPARATOR_ENV = "RIFFROOM_AUDIO_SEPARATOR_BIN"
_VERSION_FILE = "VERSION"
_MAX_ERROR_LENGTH = 300
_PACKAGE_NAME = re.compile(r"Failed building wheel for ([A-Za-z0-9_.-]+)", re.IGNORECASE)
_MACOS_COMMAND_LINE_TOOLS = Path("/Library/Developer/CommandLineTools")

PHASE_CREATE_ENVIRONMENT = "Creating isolated environment"
PHASE_INSTALL_SEPARATOR = "Installing audio-separator"
PHASE_INSTALL_CUDA_TORCH = "Installing CUDA-enabled PyTorch"
PHASE_INSTALL_DEPENDENCIES = "Installing runtime dependencies"
PHASE_INSTALL_DEMUCS = "Installing Demucs dependency"
PHASE_VERIFY_CUDA_TORCH = "Verifying CUDA-capable Torch build"
PHASE_VERIFY_RUNTIME = "Verifying runtime"
PHASE_FINALIZE = "Finalizing installation"


def audio_separator_diffq_dependency(platform: str | None = None) -> str:
    """Return audio-separator's platform-specific Demucs dependency."""
    current_platform = sys.platform if platform is None else platform
    if current_platform == "win32":
        return AUDIO_SEPARATOR_WINDOWS_DIFFQ_DEPENDENCY
    return AUDIO_SEPARATOR_DIFFQ_DEPENDENCY


def is_windows_x86_64(
    platform: str | None = None,
    machine: str | None = None,
) -> bool:
    """Return whether this is the one host with an optional CUDA recipe."""
    current_platform = sys.platform if platform is None else platform
    current_machine = platform_module.machine() if machine is None else machine
    return current_platform == "win32" and current_machine.lower() in {"amd64", "x86_64"}


def audio_separator_managed_marker() -> str:
    """Return the host-specific marker without invalidating unchanged recipes."""
    return _WINDOWS_CUDA_MANAGED_MARKER if is_windows_x86_64() else _MANAGED_MARKER


class CompletedProcessLike(Protocol):
    returncode: int


Runner = Callable[..., CompletedProcessLike | Awaitable[CompletedProcessLike]]
ProbeRunner = Callable[..., CompletedProcessLike]
ExecutableResolver = Callable[[str], str | None]


def venv_executable_path(venv: Path, name: str, *, windows: bool | None = None) -> Path:
    """Return a venv executable path without assuming the current host layout."""
    is_windows = os.name == "nt" if windows is None else windows
    directory = "Scripts" if is_windows else "bin"
    suffix = ".exe" if is_windows else ""
    return venv / directory / f"{name}{suffix}"


def venv_python_path(venv: Path, *, windows: bool | None = None) -> Path:
    return venv_executable_path(venv, "python", windows=windows)


def venv_audio_separator_path(venv: Path, *, windows: bool | None = None) -> Path:
    return venv_executable_path(venv, "audio-separator", windows=windows)


def _valid_executable(path: Path, *, windows: bool | None = None) -> bool:
    is_windows = os.name == "nt" if windows is None else windows
    return path.is_file() and (is_windows or os.access(path, os.X_OK))


def _retarget_console_script(script: Path, python: Path, *, windows: bool | None = None) -> None:
    """Retarget pip's console launcher before its venv directory moves."""
    is_windows = os.name == "nt" if windows is None else windows
    content = script.read_bytes()
    archive_start = content.find(b"PK\x03\x04")
    launcher_end = archive_start if archive_start >= 0 else len(content)
    marker = content.rfind(b"#!", 0, launcher_end) if is_windows else 0
    line_end = content.find(b"\n", marker)
    if marker < 0 or line_end < 0 or content[marker : marker + 2] != b"#!":
        raise RuntimeError("Portable runtime installation produced an invalid executable.")
    shebang = b'#!"' + os.fsencode(python) + b'"\n' if is_windows else b"#!" + os.fsencode(python) + b"\n"
    script.write_bytes(content[:marker] + shebang + content[line_end + 1 :])


class AudioSeparatorRuntime:
    """Discover or atomically install the one pinned portable runtime."""

    def __init__(
        self,
        data: Path,
        *,
        environ: Mapping[str, str] | None = None,
        executable_resolver: ExecutableResolver | None = None,
        runner: Runner | None = None,
        probe_runner: ProbeRunner | None = None,
    ) -> None:
        self.root = data / "runtimes"
        self.runtime = self.root / AUDIO_SEPARATOR_ID
        self.venv = self.runtime / "venv"
        self._environ = os.environ if environ is None else environ
        self._executable_resolver = shutil.which if executable_resolver is None else executable_resolver
        self._runner = runner
        self._probe_runner = subprocess.run if probe_runner is None else probe_runner
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._state = "idle"
        self._error: str | None = None
        self._phase: str | None = None
        self._started_at: str | None = None
        self._compute_cache: tuple[Path, dict[str, str | None]] | None = None

    def _configured_executable(self) -> Path | None:
        configured = self._environ.get(AUDIO_SEPARATOR_ENV)
        if configured is None:
            return None
        path = Path(configured)
        return path if _valid_executable(path) else None

    def managed_executable(self) -> Path | None:
        executable = venv_audio_separator_path(self.venv)
        version_file = self.runtime / _VERSION_FILE
        try:
            version = version_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        return executable if version == audio_separator_managed_marker() and _valid_executable(executable) else None

    def executable(self) -> Path | None:
        """Resolve administrator override, PATH, then the managed copy."""
        if AUDIO_SEPARATOR_ENV in self._environ:
            return self._configured_executable()
        discovered = self._executable_resolver(AUDIO_SEPARATOR_ID)
        if discovered:
            path = Path(discovered)
            if _valid_executable(path):
                return path
        return self.managed_executable()

    def status(self) -> dict[str, object]:
        compute = self._managed_compute_status()
        return {
            "id": AUDIO_SEPARATOR_ID,
            "display_name": AUDIO_SEPARATOR_DISPLAY_NAME,
            "version": AUDIO_SEPARATOR_VERSION,
            "available": self.executable() is not None,
            "managed_installed": self.managed_executable() is not None,
            "installing": self._state == "installing",
            "install_phase": self._phase if self._state == "installing" else None,
            "install_started_at": self._started_at if self._state == "installing" else None,
            "error": self._error,
            **compute,
        }

    def _managed_compute_status(self) -> dict[str, str | None]:
        """Probe the managed Windows runtime once without exposing diagnostic output."""
        unknown = {"compute_backend": None, "compute_device": None}
        executable = self.managed_executable()
        if (
            executable is None
            or self.executable() != executable
            or not is_windows_x86_64()
        ):
            return unknown
        if self._compute_cache is not None and self._compute_cache[0] == executable:
            return self._compute_cache[1]
        try:
            result = self._probe_runner(
                [str(venv_python_path(self.venv)), "-c", _CUDA_PROBE],
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            stdout = getattr(result, "stdout", "")
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            payload = json.loads(stdout.strip().splitlines()[-1]) if stdout else None
            if result.returncode != 0 or not isinstance(payload, dict):
                return unknown
            available = payload.get("available") is True
            device = payload.get("device")
            if not isinstance(device, str):
                device = None
            elif device:
                device = " ".join(device.split())[:100]
            else:
                device = None
            compute = {
                "compute_backend": "cuda" if available else "cpu",
                "compute_device": device if available else None,
            }
            self._compute_cache = (executable, compute)
            return compute
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, IndexError):
            return unknown

    def start_install(self) -> dict[str, object]:
        """Start at most one installation task and return immediately."""
        if (
            (self._task is not None and not self._task.done())
            or self._configured_executable() is not None
            or self.managed_executable() is not None
        ):
            return self.status()
        self._state = "installing"
        self._error = None
        self._phase = PHASE_CREATE_ENVIRONMENT
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._task = asyncio.create_task(self._install())
        return self.status()

    def _set_phase(self, phase: str) -> None:
        self._phase = phase

    async def _run(self, argv: list[str], *, env: Mapping[str, str] | None = None) -> CompletedProcessLike:
        if self._runner is not None:
            kwargs: dict[str, object] = {"check": False, "shell": False}
            if env is not None:
                kwargs["env"] = env
            result = self._runner(argv, **kwargs)
            return await result if inspect.isawaitable(result) else result

        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await self._process.communicate()
            return subprocess.CompletedProcess(argv, self._process.returncode, stdout, stderr)
        except asyncio.CancelledError:
            if self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            raise
        finally:
            self._process = None

    @staticmethod
    def _failure_detail(result: CompletedProcessLike) -> str | None:
        values = (getattr(result, "stderr", None), getattr(result, "stdout", None))
        output = "\n".join(
            value.decode(errors="replace") if isinstance(value, bytes) else value for value in values if value
        )
        lowered = output.lower()
        if "no space left on device" in lowered:
            return "There is not enough free disk space."
        if "permission denied" in lowered or "operation not permitted" in lowered:
            return "A required file could not be written."
        if any(
            marker in lowered
            for marker in (
                "failed to resolve",
                "name or service not known",
                "nodename nor servname provided",
                "connection timed out",
                "connection refused",
                "network is unreachable",
            )
        ):
            return "The package server could not be reached."
        if "no matching distribution found" in lowered:
            return "A compatible package build is unavailable for this Python and platform."
        wheel = _PACKAGE_NAME.search(output)
        if wheel:
            return f"A required package wheel could not be built ({wheel.group(1)})."
        if "subprocess-exited-with-error" in lowered or "failed to build" in lowered:
            return "A required package build failed."
        if "incompatible architecture" in lowered:
            return "An installed package has an incompatible processor architecture."
        if "modulenotfounderror" in lowered:
            return "The installed runtime is missing a required Python module."
        if "bad interpreter" in lowered or "no such file or directory" in lowered:
            return "The installed runtime launcher is invalid."
        return None

    async def _checked_run(
        self,
        argv: list[str],
        phase: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        try:
            result = await self._run(argv, env=env)
        except OSError as exc:
            detail = (
                "There is not enough free disk space."
                if exc.errno == errno.ENOSPC
                else "A required file could not be accessed."
                if exc.errno in (errno.EACCES, errno.EPERM)
                else "A required program could not be started."
            )
            raise RuntimeError(f"Portable runtime installation failed while {phase}. {detail}") from exc
        if result.returncode != 0:
            detail = self._failure_detail(result)
            suffix = f" {detail}" if detail else ""
            raise RuntimeError(f"Portable runtime installation failed while {phase}.{suffix}")

    async def _install(self) -> None:
        temporary: Path | None = None
        backup: Path | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.root / f".{AUDIO_SEPARATOR_ID}-{uuid4().hex}.tmp"
            temporary.mkdir()
            temporary_venv = temporary / "venv"
            self._set_phase(PHASE_CREATE_ENVIRONMENT)
            await self._checked_run(
                [sys.executable, "-m", "venv", str(temporary_venv)],
                "creating its isolated environment",
            )
            child_python = venv_python_path(temporary_venv)
            windows_cuda = is_windows_x86_64()
            cuda_constraints: Path | None = None
            package = AUDIO_SEPARATOR_WINDOWS_CUDA_PACKAGE if windows_cuda else AUDIO_SEPARATOR_PACKAGE
            self._set_phase(PHASE_INSTALL_SEPARATOR)
            await self._checked_run(
                [
                    str(child_python),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    package,
                ],
                "installing the pinned package",
            )
            if windows_cuda:
                cuda_constraints = temporary / _WINDOWS_CUDA_CONSTRAINTS_FILE
                cuda_constraints.write_text(
                    "".join(f"{requirement}\n" for requirement in AUDIO_SEPARATOR_WINDOWS_CUDA_STACK),
                    encoding="utf-8",
                )
                self._set_phase(PHASE_INSTALL_CUDA_TORCH)
                await self._checked_run(
                    [
                        str(child_python),
                        "-m",
                        "pip",
                        "install",
                        "--index-url",
                        AUDIO_SEPARATOR_WINDOWS_CUDA_INDEX,
                        *AUDIO_SEPARATOR_WINDOWS_CUDA_STACK,
                    ],
                    "installing the pinned CUDA-enabled Torch stack",
                )
            dependencies = (
                AUDIO_SEPARATOR_WINDOWS_CUDA_DEPENDENCIES
                if windows_cuda
                else AUDIO_SEPARATOR_DEPENDENCIES
            )
            self._set_phase(PHASE_INSTALL_DEPENDENCIES)
            await self._checked_run(
                [
                    str(child_python),
                    "-m",
                    "pip",
                    "install",
                    *(["--constraint", str(cuda_constraints)] if cuda_constraints else []),
                    *dependencies,
                ],
                "installing the runtime dependencies",
            )
            diffq_dependency = audio_separator_diffq_dependency()
            diffq_environment = None
            if (
                diffq_dependency == AUDIO_SEPARATOR_DIFFQ_DEPENDENCY
                and sys.platform == "darwin"
                and _MACOS_COMMAND_LINE_TOOLS.is_dir()
            ):
                diffq_environment = {**os.environ, "DEVELOPER_DIR": str(_MACOS_COMMAND_LINE_TOOLS)}
            self._set_phase(PHASE_INSTALL_DEMUCS)
            await self._checked_run(
                [
                    str(child_python),
                    "-m",
                    "pip",
                    "install",
                    *(["--constraint", str(cuda_constraints)] if cuda_constraints else []),
                    diffq_dependency,
                ],
                "installing the Demucs dependency",
                env=diffq_environment,
            )
            if windows_cuda:
                self._set_phase(PHASE_VERIFY_CUDA_TORCH)
                await self._checked_run(
                    [str(child_python), "-c", _WINDOWS_CUDA_BUILD_CHECK],
                    "verifying the CUDA-enabled Torch build",
                )
            cli = venv_audio_separator_path(temporary_venv)
            if not _valid_executable(cli):
                raise RuntimeError("Portable runtime installation did not produce the expected executable.")
            self._set_phase(PHASE_VERIFY_RUNTIME)
            await self._checked_run([str(cli), "--help"], "verifying the installed runtime")
            await self._checked_run(
                [str(child_python), "-c", _AUDIO_SEPARATOR_IMPORT_CHECK],
                "verifying the separator and Demucs imports",
            )
            self._set_phase(PHASE_FINALIZE)
            _retarget_console_script(cli, venv_python_path(self.venv))

            if self.runtime.exists():
                backup = self.root / f".{AUDIO_SEPARATOR_ID}-{uuid4().hex}.backup"
                self.runtime.replace(backup)
            try:
                temporary.replace(self.runtime)
                temporary = None
                await self._checked_run(
                    [str(venv_audio_separator_path(self.venv)), "--help"],
                    "verifying the published runtime",
                )
                (self.runtime / _VERSION_FILE).write_text(
                    audio_separator_managed_marker() + "\n",
                    encoding="utf-8",
                )
            except BaseException:
                if self.runtime.exists():
                    shutil.rmtree(self.runtime, ignore_errors=True)
                if backup is not None and backup.exists() and not self.runtime.exists():
                    backup.replace(self.runtime)
                    backup = None
                raise
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
                backup = None
            self._state = "idle"
            self._error = None
            self._compute_cache = None
        except asyncio.CancelledError:
            self._state = "idle"
            raise
        except Exception as exc:
            self._state = "error"
            message = (
                str(exc)
                if isinstance(exc, RuntimeError)
                else "Portable runtime installation failed. Check disk space and permissions, then retry."
            )
            self._error = message[:_MAX_ERROR_LENGTH]
        finally:
            self._phase = None
            self._started_at = None
            if temporary is not None:
                shutil.rmtree(temporary, ignore_errors=True)
            if backup is not None and backup.exists() and not self.runtime.exists():
                backup.replace(self.runtime)
            if self._task is asyncio.current_task():
                self._task = None

    async def close(self) -> None:
        task = self._task
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


__all__ = [
    "AUDIO_SEPARATOR_ENV",
    "AUDIO_SEPARATOR_DEPENDENCIES",
    "AUDIO_SEPARATOR_DIFFQ_DEPENDENCY",
    "AUDIO_SEPARATOR_WINDOWS_DIFFQ_DEPENDENCY",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_DEPENDENCIES",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_INDEX",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_MANAGED_REVISION",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_ONNX_RUNTIME",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_PACKAGE",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_STACK",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_TORCH",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_TORCHAUDIO",
    "AUDIO_SEPARATOR_WINDOWS_CUDA_TORCHVISION",
    "AUDIO_SEPARATOR_PACKAGE",
    "AUDIO_SEPARATOR_MANAGED_REVISION",
    "AUDIO_SEPARATOR_VERSION",
    "AudioSeparatorRuntime",
    "audio_separator_diffq_dependency",
    "audio_separator_managed_marker",
    "is_windows_x86_64",
    "venv_audio_separator_path",
    "venv_executable_path",
    "venv_python_path",
]

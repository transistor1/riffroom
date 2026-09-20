"""Server-owned installation and discovery for portable separation runtimes."""

import asyncio
import errno
import inspect
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol
from uuid import uuid4

AUDIO_SEPARATOR_ID = "audio-separator"
AUDIO_SEPARATOR_DISPLAY_NAME = "Portable audio-separator runtime"
AUDIO_SEPARATOR_VERSION = "0.47.0"
AUDIO_SEPARATOR_PACKAGE = f"audio-separator[cpu]=={AUDIO_SEPARATOR_VERSION}"
# audio-separator declares two dependencies that the one portable MDX/ONNX pilot
# does not import: diffq has no macOS arm64 wheel and samplerate 0.1.0 bundles an
# x86_64-only dylib. Installing the remaining declared dependencies separately
# avoids a local compiler requirement and a knowingly unusable binary package.
AUDIO_SEPARATOR_PILOT_DEPENDENCIES = (
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
    "torch<3,>=2.13",
    "tqdm",
    "onnxruntime>=1.17",
)
AUDIO_SEPARATOR_ENV = "RIFFROOM_AUDIO_SEPARATOR_BIN"
_VERSION_FILE = "VERSION"
_MAX_ERROR_LENGTH = 300
_PACKAGE_NAME = re.compile(r"Failed building wheel for ([A-Za-z0-9_.-]+)", re.IGNORECASE)


class CompletedProcessLike(Protocol):
    returncode: int


Runner = Callable[..., CompletedProcessLike | Awaitable[CompletedProcessLike]]
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
    ) -> None:
        self.root = data / "runtimes"
        self.runtime = self.root / AUDIO_SEPARATOR_ID
        self.venv = self.runtime / "venv"
        self._environ = os.environ if environ is None else environ
        self._executable_resolver = shutil.which if executable_resolver is None else executable_resolver
        self._runner = runner
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._state = "idle"
        self._error: str | None = None

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
        return executable if version == AUDIO_SEPARATOR_VERSION and _valid_executable(executable) else None

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
        return {
            "id": AUDIO_SEPARATOR_ID,
            "display_name": AUDIO_SEPARATOR_DISPLAY_NAME,
            "version": AUDIO_SEPARATOR_VERSION,
            "available": self.executable() is not None,
            "managed_installed": self.managed_executable() is not None,
            "installing": self._state == "installing",
            "error": self._error,
        }

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
        self._task = asyncio.create_task(self._install())
        return self.status()

    async def _run(self, argv: list[str]) -> CompletedProcessLike:
        if self._runner is not None:
            result = self._runner(argv, check=False, shell=False)
            return await result if inspect.isawaitable(result) else result

        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
            return "A compatible package build is unavailable for this Python and Mac."
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

    async def _checked_run(self, argv: list[str], phase: str) -> None:
        try:
            result = await self._run(argv)
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
            await self._checked_run(
                [sys.executable, "-m", "venv", str(temporary_venv)],
                "creating its isolated environment",
            )
            child_python = venv_python_path(temporary_venv)
            await self._checked_run(
                [
                    str(child_python),
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    AUDIO_SEPARATOR_PACKAGE,
                ],
                "installing the pinned package",
            )
            await self._checked_run(
                [
                    str(child_python),
                    "-m",
                    "pip",
                    "install",
                    *AUDIO_SEPARATOR_PILOT_DEPENDENCIES,
                ],
                "installing the pilot dependencies",
            )
            cli = venv_audio_separator_path(temporary_venv)
            if not _valid_executable(cli):
                raise RuntimeError("Portable runtime installation did not produce the expected executable.")
            await self._checked_run([str(cli), "--help"], "verifying the installed runtime")
            _retarget_console_script(cli, venv_python_path(self.venv))
            (temporary / _VERSION_FILE).write_text(AUDIO_SEPARATOR_VERSION + "\n", encoding="utf-8")

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
    "AUDIO_SEPARATOR_PACKAGE",
    "AUDIO_SEPARATOR_PILOT_DEPENDENCIES",
    "AUDIO_SEPARATOR_VERSION",
    "AudioSeparatorRuntime",
    "venv_audio_separator_path",
    "venv_executable_path",
    "venv_python_path",
]

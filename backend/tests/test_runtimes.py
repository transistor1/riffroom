import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from riffroom.runtimes import (
    _AUDIO_SEPARATOR_IMPORT_CHECK,
    _MANAGED_MARKER,
    AUDIO_SEPARATOR_DEPENDENCIES,
    AUDIO_SEPARATOR_DIFFQ_DEPENDENCY,
    AUDIO_SEPARATOR_PACKAGE,
    AUDIO_SEPARATOR_VERSION,
    AudioSeparatorRuntime,
    _retarget_console_script,
    venv_audio_separator_path,
    venv_python_path,
)


def make_executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env python3\n")
    path.chmod(0o755)
    return path


def successful_runner(calls):
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1:3] == ["-m", "venv"]:
            venv = Path(argv[-1])
            make_executable(venv_python_path(venv))
            make_executable(venv_audio_separator_path(venv))
        return SimpleNamespace(returncode=0)

    return run


def test_venv_executable_layouts_are_portable(tmp_path):
    venv = tmp_path / "venv"
    assert venv_python_path(venv, windows=False) == venv / "bin" / "python"
    assert venv_audio_separator_path(venv, windows=False) == venv / "bin" / "audio-separator"
    assert venv_python_path(venv, windows=True) == venv / "Scripts" / "python.exe"
    assert venv_audio_separator_path(venv, windows=True) == venv / "Scripts" / "audio-separator.exe"


def test_windows_console_launcher_is_retargeted_for_atomic_move(tmp_path):
    launcher = tmp_path / "audio-separator.exe"
    launcher.write_bytes(b"MZ-launcher#!C:\\temp\\venv\\python.exe\nPK\x03\x04-zipapp")

    _retarget_console_script(launcher, Path("C:/Riffroom Data/runtime/venv/Scripts/python.exe"), windows=True)

    content = launcher.read_bytes()
    assert content.startswith(b"MZ-launcher")
    assert b'#!"C:/Riffroom Data/runtime/venv/Scripts/python.exe"\n' in content
    assert content.endswith(b"PK\x03\x04-zipapp")


def test_override_precedes_path_and_managed_runtime(tmp_path):
    override = make_executable(tmp_path / "override")
    managed = AudioSeparatorRuntime(
        tmp_path,
        environ={"RIFFROOM_AUDIO_SEPARATOR_BIN": str(override)},
        executable_resolver=lambda name: (_ for _ in ()).throw(AssertionError(name)),
    )
    make_executable(venv_audio_separator_path(managed.venv))
    (managed.runtime / "VERSION").write_text(_MANAGED_MARKER)

    assert managed.executable() == override
    assert managed.status()["available"] is True
    assert managed.status()["managed_installed"] is True


@pytest.mark.parametrize("marker", [AUDIO_SEPARATOR_VERSION, "0.47.0\nrecipe=1", _MANAGED_MARKER])
def test_managed_detection_requires_current_recipe_without_running_commands(tmp_path, marker):
    def unexpected_run(*args, **kwargs):
        pytest.fail("Discovery must not run subprocesses")

    runtime = AudioSeparatorRuntime(
        tmp_path, environ={}, executable_resolver=lambda name: None, runner=unexpected_run
    )
    executable = make_executable(venv_audio_separator_path(runtime.venv))
    (runtime.runtime / "VERSION").write_text(marker + "\n")
    current = marker == _MANAGED_MARKER
    assert runtime.managed_executable() == (executable if current else None)
    assert runtime.status()["managed_installed"] is current
    assert runtime.status()["available"] is current
    assert runtime.status()["version"] == "0.47.0"
    if current:
        assert runtime.start_install()["installing"] is False


@pytest.mark.parametrize("marker", [AUDIO_SEPARATOR_VERSION, _MANAGED_MARKER])
def test_path_precedes_managed_runtime_regardless_of_recipe(tmp_path, marker):
    external = make_executable(tmp_path / "external")
    runtime = AudioSeparatorRuntime(tmp_path, environ={}, executable_resolver=lambda name: str(external))
    make_executable(venv_audio_separator_path(runtime.venv))
    (runtime.runtime / "VERSION").write_text(marker)
    assert runtime.executable() == external
    assert runtime.status()["available"] is True


def test_invalid_explicit_override_fails_closed(tmp_path):
    runtime = AudioSeparatorRuntime(
        tmp_path,
        environ={"RIFFROOM_AUDIO_SEPARATOR_BIN": str(tmp_path / "missing")},
        executable_resolver=lambda name: "/should/not/be/used",
    )

    assert runtime.executable() is None
    assert runtime.status()["available"] is False


def test_valid_override_never_starts_a_managed_install(tmp_path):
    override = make_executable(tmp_path / "override")
    calls = []
    runtime = AudioSeparatorRuntime(
        tmp_path,
        environ={"RIFFROOM_AUDIO_SEPARATOR_BIN": str(override)},
        executable_resolver=lambda name: None,
        runner=lambda argv, **kwargs: calls.append(argv),
    )

    async def exercise():
        status = runtime.start_install()
        await asyncio.sleep(0)
        assert status["available"] is True
        assert status["managed_installed"] is False
        assert status["installing"] is False
        assert runtime._task is None

    asyncio.run(exercise())
    assert calls == []


def test_managed_install_is_atomic_and_uses_the_pinned_package(tmp_path, monkeypatch):
    calls = []
    command_line_tools = tmp_path / "CommandLineTools"
    command_line_tools.mkdir()
    monkeypatch.setattr("riffroom.runtimes._MACOS_COMMAND_LINE_TOOLS", command_line_tools)
    monkeypatch.setattr("riffroom.runtimes.sys.platform", "darwin")
    run = successful_runner(calls)

    def runner(argv, **kwargs):
        # Neither staging nor the published copy is marked current during verification.
        if argv[-1] == "--help" or argv[1:2] == ["-c"]:
            assert not (Path(argv[0]).parents[2] / "VERSION").exists()
        if len(calls) < 6:
            assert (runtime.runtime / "stale").read_text() == "old"
        return run(argv, **kwargs)

    runtime = AudioSeparatorRuntime(
        tmp_path, environ={}, executable_resolver=lambda name: None, runner=runner
    )
    make_executable(venv_audio_separator_path(runtime.venv))
    (runtime.runtime / "VERSION").write_text(AUDIO_SEPARATOR_VERSION)
    (runtime.runtime / "stale").write_text("old")

    async def exercise():
        assert runtime.start_install()["installing"] is True
        await runtime._task

    asyncio.run(exercise())

    assert runtime.managed_executable() == venv_audio_separator_path(runtime.venv)
    assert (runtime.runtime / "VERSION").read_text() == _MANAGED_MARKER + "\n"
    assert not (runtime.runtime / "stale").exists()
    assert calls[0][0][1:3] == ["-m", "venv"]
    assert calls[1][0][-2:] == ["--no-deps", AUDIO_SEPARATOR_PACKAGE]
    assert calls[2][0][-len(AUDIO_SEPARATOR_DEPENDENCIES) :] == list(AUDIO_SEPARATOR_DEPENDENCIES)
    assert calls[3][0][-1] == AUDIO_SEPARATOR_DIFFQ_DEPENDENCY
    assert calls[3][0][:4] == [calls[2][0][0], "-m", "pip", "install"]
    assert calls[4][0][0].endswith("/venv/bin/audio-separator")
    assert calls[4][0][1:] == ["--help"]
    assert calls[5][0] == [calls[2][0][0], "-c", _AUDIO_SEPARATOR_IMPORT_CHECK]
    assert "from audio_separator.separator import Separator" in calls[5][0][2]
    assert "architectures.demucs_separator import DemucsSeparator" in calls[5][0][2]
    assert "demucs.htdemucs import HTDemucs" in calls[5][0][2]
    assert calls[6][0] == [str(venv_audio_separator_path(runtime.venv)), "--help"]
    assert (runtime.runtime / "VERSION").read_text() == "0.47.0\nrecipe=2\n"
    assert all(kwargs["check"] is False and kwargs["shell"] is False for _, kwargs in calls)
    assert all("env" not in kwargs for _, kwargs in calls[:3])
    assert calls[3][1]["env"]["DEVELOPER_DIR"] == str(command_line_tools)
    assert not any(path.name.endswith((".tmp", ".backup")) for path in runtime.root.iterdir())


def test_runtime_installs_real_diffq_after_torch_and_omits_samplerate():
    dependencies = " ".join(AUDIO_SEPARATOR_DEPENDENCIES).lower()

    assert "audioread>=3" in AUDIO_SEPARATOR_DEPENDENCIES
    assert 'audioop-lts>=0.2.1; python_version >= "3.13"' in AUDIO_SEPARATOR_DEPENDENCIES
    assert "torch" in dependencies
    assert AUDIO_SEPARATOR_DIFFQ_DEPENDENCY == "diffq>=0.2"
    assert "diffq" not in dependencies
    assert "samplerate" not in dependencies


def test_failed_build_reports_bounded_cause_without_build_paths(tmp_path):
    calls = 0

    def runner(argv, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            venv = Path(argv[-1])
            make_executable(venv_python_path(venv))
        if calls < 4:
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        return SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=(
                b"Failed building wheel for diffq\n"
                b"/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk: unknown architecture\n"
            ),
        )

    runtime = AudioSeparatorRuntime(
        tmp_path, environ={}, executable_resolver=lambda name: None, runner=runner
    )

    asyncio.run(runtime._install())

    error = runtime.status()["error"]
    assert error == (
        "Portable runtime installation failed while installing the Demucs dependency. "
        "A required package wheel could not be built (diffq)."
    )
    assert "/Library" not in error
    assert list(runtime.root.iterdir()) == []


def test_failed_install_cleans_temp_and_preserves_existing_runtime(tmp_path):
    runtime = AudioSeparatorRuntime(
        tmp_path,
        environ={},
        executable_resolver=lambda name: None,
        runner=lambda argv, **kwargs: SimpleNamespace(returncode=1),
    )
    runtime.runtime.mkdir(parents=True)
    sentinel = runtime.runtime / "existing"
    sentinel.write_text("keep")

    asyncio.run(runtime._install())

    assert sentinel.read_text() == "keep"
    assert runtime.status()["error"]
    assert len(runtime.status()["error"]) <= 300
    assert [path for path in runtime.root.iterdir()] == [runtime.runtime]


@pytest.mark.parametrize("failed_call", [4, 5, 6, 7])
def test_failed_replacement_restores_previous_runtime(tmp_path, failed_call):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            venv = Path(argv[-1])
            make_executable(venv_python_path(venv))
            make_executable(venv_audio_separator_path(venv))
        return SimpleNamespace(
            returncode=1 if len(calls) == failed_call else 0,
            stderr=b"ModuleNotFoundError: No module named 'audioread'" if failed_call == 6 else b"",
        )

    runtime = AudioSeparatorRuntime(
        tmp_path, environ={}, executable_resolver=lambda name: None, runner=runner
    )
    old_cli = make_executable(venv_audio_separator_path(runtime.venv))
    old_content = old_cli.read_bytes()
    (runtime.runtime / "VERSION").write_text(AUDIO_SEPARATOR_VERSION)
    sentinel = runtime.runtime / "previous"
    sentinel.write_text("keep")

    asyncio.run(runtime._install())

    assert sentinel.read_text() == "keep"
    assert old_cli.read_bytes() == old_content
    assert (runtime.runtime / "VERSION").read_text() == AUDIO_SEPARATOR_VERSION
    assert runtime.managed_executable() is None
    assert runtime.status()["error"]
    if failed_call == 6:
        assert runtime.status()["error"] == (
            "Portable runtime installation failed while verifying the separator and Demucs imports. "
            "The installed runtime is missing a required Python module."
        )
    assert not any(path.name.endswith((".tmp", ".backup")) for path in runtime.root.iterdir())


def test_start_install_is_idempotent_while_running(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    async def runner(argv, **kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(returncode=1)

    async def exercise():
        runtime = AudioSeparatorRuntime(
            tmp_path, environ={}, executable_resolver=lambda name: None, runner=runner
        )
        first = runtime.start_install()
        task = runtime._task
        await started.wait()
        second = runtime.start_install()
        assert first["installing"] is True
        assert second["installing"] is True
        assert runtime._task is task
        release.set()
        await task

    asyncio.run(exercise())


def test_close_cancels_install_and_cleans_temporary_directory(tmp_path):
    started = asyncio.Event()

    async def runner(argv, **kwargs):
        started.set()
        await asyncio.Future()

    async def exercise():
        runtime = AudioSeparatorRuntime(
            tmp_path, environ={}, executable_resolver=lambda name: None, runner=runner
        )
        runtime.start_install()
        await started.wait()
        await runtime.close()
        assert runtime.status()["installing"] is False
        assert runtime._task is None
        assert list(runtime.root.iterdir()) == []

    asyncio.run(exercise())

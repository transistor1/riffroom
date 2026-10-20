"""Beat installer contracts; no package installation or model download."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from riffroom import beat_runtime as runtime


@pytest.mark.parametrize("system,machine,expected", [
    ("Darwin", "arm64", True), ("Darwin", "x86_64", False),
    ("Windows", "AMD64", True), ("Linux", "x86_64", True), ("Linux", "aarch64", False),
])
def test_supported_targets(system, machine, expected):
    assert runtime.supported(system, machine) is expected


@pytest.mark.parametrize("system", ["Darwin", "Windows", "Linux"])
def test_install_commands_isolate_and_pin_cpu_stack(monkeypatch, tmp_path, system):
    monkeypatch.setattr(runtime.platform, "system", lambda: system)
    commands = runtime.install_commands(tmp_path)
    torch = commands[1][1]
    assert runtime.TORCH == ("torch==2.8.0", "torchaudio==2.8.0")
    assert all(package in torch for package in runtime.TORCH)
    assert (runtime.CPU_INDEX in torch) is (system != "Darwin")
    assert commands[-1][1][-1] == "from beat_this.inference import File2Beats"
    assert all(str(runtime.python_path(tmp_path)) == command[0] for _, command in commands[1:])
    assert "--upgrade" not in torch
    lock = runtime.LOCK.read_text()
    assert all(package in lock for package in runtime.TORCH)


def test_setup_marks_ready_only_after_import_probe_and_reuses_it(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "supported", lambda: True)
    python = runtime.python_path(runtime.runtime_path(tmp_path))
    python.parent.mkdir(parents=True)
    python.touch()
    run = Mock(return_value=subprocess.CompletedProcess([], 0, ""))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.install(tmp_path)
    assert runtime.ready(tmp_path)
    assert run.call_count == 5
    assert runtime.install(tmp_path)
    assert run.call_count == 5


def test_failed_setup_is_retryable_and_has_no_ready_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "supported", lambda: True)
    run = Mock(return_value=subprocess.CompletedProcess([], 1, "No matching distribution found"))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="then retry setup"):
        runtime.install(tmp_path)
    assert not runtime.ready(tmp_path)
    assert not (runtime.runtime_path(tmp_path) / "ready").exists()


def test_unsupported_setup_does_not_install(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(runtime, "supported", lambda: False)
    run = Mock(side_effect=AssertionError("must not install"))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert not runtime.install(tmp_path)
    assert "unavailable on this platform" in capsys.readouterr().out
    run.assert_not_called()


def test_standard_installers_use_shared_beat_setup_and_fingerprint_inputs():
    root = Path(__file__).resolve().parents[2]
    for name in ("scripts/setup.sh", "scripts/setup_portable.py"):
        source = (root / name).read_text()
        assert "backend/riffroom/beat_runtime.py" in source
        assert "scripts/requirements-beats-lock.txt" in source
        assert "--install" in source


def test_setup_lock_prevents_concurrent_install_and_releases_after_failure(tmp_path):
    with pytest.raises(RuntimeError, match="injected failure"):
        with runtime.setup_lock(tmp_path):
            with pytest.raises(RuntimeError, match="already running"):
                with runtime.setup_lock(tmp_path):
                    pytest.fail("Concurrent setup acquired the lock")
            raise RuntimeError("injected failure")
    with runtime.setup_lock(tmp_path):
        pass


@pytest.mark.parametrize("exit_code", [0, 1])
def test_backend_setup_streams_progress_and_checks_result(monkeypatch, tmp_path, exit_code):
    import asyncio
    from types import SimpleNamespace

    from riffroom import beats
    from riffroom.store import Store

    store = Store(tmp_path / "tracks")
    store.put({"id": "a" * 32, "status": "ready"})
    jobs = beats.BeatJobs(store, available=lambda: exit_code == 0)
    seen = []

    async def lines():
        yield b"Installing CPU PyTorch\n"
        seen.append(store.get("a" * 32)["beat_analysis"])
        yield b"untrusted pip output is not a progress phase\n"

    async def wait():
        return exit_code

    process = SimpleNamespace(stdout=lines(), returncode=exit_code, wait=wait)
    spawned = []

    async def spawn(*argv, **kwargs):
        spawned.append((argv, kwargs))
        return process

    monkeypatch.setattr(beats.asyncio, "create_subprocess_exec", spawn)
    if exit_code:
        with pytest.raises(RuntimeError, match="retry setup"):
            asyncio.run(jobs._setup("a" * 32))
    else:
        asyncio.run(jobs._setup("a" * 32))
    assert seen[0]["message"] == "Installing CPU PyTorch…"
    assert seen[0]["setup_required"] is True
    assert spawned[0][0][-3:] == ("--install", "--data", str(tmp_path))
    assert spawned[0][1].items() >= beats._process_group_kwargs().items()


def test_backend_cancel_stops_only_setup_process_group(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from riffroom import beats
    from riffroom.store import Store

    jobs = beats.BeatJobs(Store(tmp_path / "tracks"), available=lambda: False)
    stopped = []

    async def lines():
        raise asyncio.CancelledError
        yield  # pragma: no cover

    process = SimpleNamespace(stdout=lines(), returncode=None)

    async def spawn(*args, **kwargs):
        return process

    async def terminate(target):
        stopped.append(target)

    monkeypatch.setattr(beats.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(beats, "_terminate_process", terminate)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(jobs._setup("a" * 32))
    assert stopped == [process]

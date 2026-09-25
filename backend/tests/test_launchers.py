"""Source-launcher contracts; simulated platforms do not constitute host validation."""

import importlib.util
import sys
import tomllib
from pathlib import Path
from unittest.mock import Mock

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_and_linux_venv_paths(tmp_path):
    setup = load_script("setup_portable")
    assert setup.venv_python(tmp_path, "Windows") == tmp_path / ".env/Scripts/python.exe"
    assert setup.venv_python(tmp_path, "Linux") == tmp_path / ".env/bin/python"


def test_fingerprint_tracks_platform_and_every_input(tmp_path):
    setup = load_script("setup_portable")
    for name in setup.INPUTS:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    original = setup.fingerprint(tmp_path, "Linux", "x86_64")
    assert original != setup.fingerprint(tmp_path, "Windows", "x86_64")
    assert original != setup.fingerprint(tmp_path, "Linux", "arm64")
    for name in setup.INPUTS:
        target = tmp_path / name
        original_bytes = target.read_bytes()
        target.write_bytes(original_bytes + b"\n")
        assert original != setup.fingerprint(tmp_path, "Linux", "x86_64"), name
        target.write_bytes(original_bytes)


def test_check_does_not_install_or_launch(monkeypatch, tmp_path):
    setup = load_script("setup_portable")
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "prerequisites", lambda: [])
    monkeypatch.setattr(setup, "fingerprint", lambda: "test")
    runner = Mock(side_effect=AssertionError("check must not mutate"))
    monkeypatch.setattr(setup, "run", runner)
    monkeypatch.setattr(sys, "argv", ["setup_portable.py", "--check"])
    assert setup.main() == 0
    assert not list(tmp_path.iterdir())
    runner.assert_not_called()


def test_core_lock_closure_on_supported_python_and_platforms():
    from importlib.metadata import distribution

    from packaging.markers import default_environment

    requirements = [Requirement(line) for line in (ROOT / "requirements-core-lock.txt").read_text().splitlines()
                    if line and not line.startswith("#")]
    locked = {canonicalize_name(r.name): next(iter(r.specifier)).version for r in requirements}
    assert not {"mlx", "mlx-audio-separator", "torch", "audio-separator", "pytest"} & locked.keys()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    for raw in project["project"]["dependencies"]:
        requirement = Requirement(raw)
        assert locked[canonicalize_name(requirement.name)] in requirement.specifier
    for system, sys_platform in [("Windows", "win32"), ("Linux", "linux")]:
        for minor in (11, 12, 13):
            environment = default_environment() | {
                "platform_system": system, "sys_platform": sys_platform,
                "python_version": f"3.{minor}", "python_full_version": f"3.{minor}.0", "extra": "",
            }
            for name, version in locked.items():
                package = distribution(name)
                assert package.version == version
                for raw in package.requires or []:
                    requirement = Requirement(raw)
                    if requirement.marker is None or requirement.marker.evaluate(environment):
                        assert locked[canonicalize_name(requirement.name)] in requirement.specifier


def test_launch_reuses_existing_server(monkeypatch):
    launch = load_script("launch")
    monkeypatch.setattr(sys, "argv", ["launch.py", "--no-browser"])
    monkeypatch.setattr(launch, "is_riffroom", lambda: True)
    server = Mock()
    monkeypatch.setattr(launch.uvicorn, "run", server)
    launch.main()
    server.assert_not_called()


def test_launch_busy_port(monkeypatch):
    import pytest

    launch = load_script("launch")
    monkeypatch.setattr(sys, "argv", ["launch.py", "--no-browser"])
    monkeypatch.setattr(launch, "is_riffroom", lambda: False)
    probe = Mock()
    probe.bind.side_effect = OSError("busy")
    context = Mock(__enter__=Mock(return_value=probe), __exit__=Mock(return_value=False))
    monkeypatch.setattr(launch.socket, "socket", lambda *args: context)
    with pytest.raises(SystemExit, match="Port 8765 is in use"):
        launch.main()


def test_windows_launch_uses_exclusive_socket(monkeypatch):
    from types import SimpleNamespace

    launch = load_script("launch")
    monkeypatch.setattr(sys, "argv", ["launch.py", "--no-browser"])
    monkeypatch.setattr(launch, "is_riffroom", lambda: False)
    monkeypatch.setattr(launch, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(launch.socket, "SO_EXCLUSIVEADDRUSE", 123, raising=False)
    probe = Mock()
    context = Mock(__enter__=Mock(return_value=probe), __exit__=Mock(return_value=False))
    monkeypatch.setattr(launch.socket, "socket", lambda *args: context)
    server = Mock()
    monkeypatch.setattr(launch.uvicorn, "run", server)
    launch.main()
    probe.setsockopt.assert_called_once_with(launch.socket.SOL_SOCKET, 123, 1)
    server.assert_called_once_with("riffroom.app:app", host="127.0.0.1", port=8765, log_level="info")


def test_host_binding_and_process_trust(monkeypatch, capsys):
    for host in (None, "0.0.0.0", "192.168.1.42", "::", "::1"):
        launch = load_script("launch")
        monkeypatch.setenv("RIFFROOM_BIND_HOST", "0.0.0.0")
        argv = ["launch.py", "--no-browser"] + (["--host", host] if host else [])
        monkeypatch.setattr(sys, "argv", argv)
        health = Mock(return_value=False)
        monkeypatch.setattr(launch, "is_riffroom", health)
        probe = Mock()
        factory = Mock(return_value=Mock(__enter__=Mock(return_value=probe),
                                       __exit__=Mock(return_value=False)))
        monkeypatch.setattr(launch.socket, "socket", factory)
        server = Mock()
        monkeypatch.setattr(launch.uvicorn, "run", server)
        launch.main()
        expected = host or "127.0.0.1"
        probe.bind.assert_called_once_with((expected, 8765))
        server.assert_called_once_with("riffroom.app:app", host=expected, port=8765, log_level="info")
        assert launch.os.environ.get("RIFFROOM_BIND_HOST") == host
        output = capsys.readouterr().out
        assert ("no authentication" in output) == (host in {"0.0.0.0", "192.168.1.42", "::"})
        if host == "0.0.0.0":
            assert "http://127.0.0.1:8765" in output
        if host:
            health.assert_not_called()


def test_portable_forwards_host_and_no_browser(monkeypatch, tmp_path):
    setup = load_script("setup_portable")
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(setup, "prerequisites", lambda: [])
    monkeypatch.setattr(setup, "fingerprint", lambda: "test")
    (tmp_path / ".env").mkdir()
    (tmp_path / ".env/.riffroom-core-fingerprint").write_text("test")
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/dist/index.html").touch()
    monkeypatch.setattr(setup, "run", Mock(side_effect=AssertionError("must not install")))
    monkeypatch.setattr(setup.os, "chdir", Mock())
    execute = Mock()
    monkeypatch.setattr(setup.os, "execv", execute)
    monkeypatch.setattr(sys, "argv", ["setup_portable.py", "--launch", "--host", "0.0.0.0", "--no-browser"])
    setup.main()
    assert execute.call_args.args[1][1:] == [str(tmp_path / "scripts/launch.py"),
                                           "--host", "0.0.0.0", "--no-browser"]


def test_powershell_forwards_bind_address():
    start = (ROOT / "start.ps1").read_text()
    wrapper = (ROOT / "Riffroom.ps1").read_text()
    for source in (start, wrapper):
        assert '[string]$BindAddress = "127.0.0.1"' in source
    assert "@('--host', $BindAddress)" in start
    assert "-BindAddress $BindAddress" in wrapper
    assert "-NoBrowser:$NoBrowser" in wrapper
    assert "$setupArgs += '--no-browser'" in start


def test_wildcard_browser_readiness_uses_loopback(monkeypatch):
    monkeypatch.delenv("RIFFROOM_BIND_HOST", raising=False)
    monkeypatch.setenv("RIFFROOM_BIND_HOST", "127.0.0.1")
    launch = load_script("launch")
    monkeypatch.setattr(sys, "argv", ["launch.py", "--host", "0.0.0.0"])
    monkeypatch.setattr(launch.socket, "socket", Mock(return_value=Mock(
        __enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))))
    monkeypatch.setattr(launch.uvicorn, "run", Mock())
    thread = Mock()
    monkeypatch.setattr(launch.threading, "Thread", thread)
    launch.main()
    thread.assert_called_once_with(target=launch.open_when_ready,
                                   args=("http://127.0.0.1:8765",), daemon=True)
    health = Mock(return_value=True)
    browser = Mock()
    monkeypatch.setattr(launch, "is_riffroom", health)
    monkeypatch.setattr(launch.webbrowser, "open", browser)
    launch.open_when_ready("http://127.0.0.1:8765")
    health.assert_called_once_with("http://127.0.0.1:8765")
    browser.assert_called_once_with("http://127.0.0.1:8765")

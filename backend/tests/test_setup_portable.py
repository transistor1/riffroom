"""Focused forwarding tests for the core portable setup launcher."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_setup_portable():
    spec = importlib.util.spec_from_file_location(
        "setup_portable_under_test", ROOT / "scripts/setup_portable.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ready_setup(monkeypatch, tmp_path):
    setup = load_setup_portable()
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
    return setup, execute


def test_lan_and_no_browser_are_forwarded_without_host(monkeypatch, tmp_path):
    setup, execute = ready_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["setup_portable.py", "--launch", "--lan", "--no-browser"],
    )

    assert setup.main() == 0
    assert execute.call_args.args[1][1:] == [
        str(tmp_path / "scripts/launch.py"),
        "--lan",
        "--no-browser",
    ]


def test_lan_rejects_non_default_host(monkeypatch, capsys):
    setup = load_setup_portable()
    monkeypatch.setattr(
        sys,
        "argv",
        ["setup_portable.py", "--launch", "--lan", "--host", "0.0.0.0"],
    )

    with pytest.raises(SystemExit) as exc:
        setup.main()

    assert exc.value.code == 2
    assert "--lan cannot be combined with a non-default --host" in capsys.readouterr().err


def test_powershell_launchers_expose_and_forward_lan_without_reimplementing_tls():
    wrapper = (ROOT / "Riffroom.ps1").read_text()
    launcher = (ROOT / "start.ps1").read_text()

    assert "[switch]$Lan" in wrapper
    assert "[switch]$Lan" in launcher
    assert "-Lan:$Lan" in wrapper
    assert "$setupArgs += '--lan'" in launcher
    assert "non-default -BindAddress" in launcher
    assert "certificate" not in wrapper.lower()
    assert "certificate" not in launcher.lower()

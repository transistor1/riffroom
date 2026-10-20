"""Shared standard-setup and in-app installer for isolated CPU beat tracking.

Also serves as the inference worker inside that environment; no app imports.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "scripts/requirements-beats-lock.txt"
TORCH = ("torch==2.8.0", "torchaudio==2.8.0")
CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def supported(system=None, machine=None):
    system, machine = system or platform.system(), (machine or platform.machine()).lower()
    return ((system == "Darwin" and machine == "arm64")
            or (system in {"Windows", "Linux"} and machine in {"amd64", "x86_64"}))


def runtime_path(data):
    return Path(data) / "runtimes/beat-tracking"


def python_path(runtime):
    return runtime / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def fingerprint():
    return hashlib.sha256(LOCK.read_bytes() + Path(__file__).read_bytes()).hexdigest()


def ready(data):
    runtime = runtime_path(data)
    marker = runtime / "ready"
    return (python_path(runtime).is_file() and marker.is_file()
            and marker.read_text().strip() == fingerprint())


def install_commands(runtime):
    python = str(python_path(runtime))
    torch = [python, "-m", "pip", "install", "--no-deps", *TORCH]
    if platform.system() != "Darwin":
        # CPU wheels avoid a second CUDA stack; separation has its own environment.
        torch += ["--index-url", CPU_INDEX]
    return [
        ("Creating beat environment", [sys.executable, "-m", "venv", str(runtime / "venv")]),
        ("Installing CPU PyTorch", torch),
        ("Installing beat tracking", [python, "-m", "pip", "install", "-r", str(LOCK)]),
        ("Checking beat dependencies", [python, "-m", "pip", "check"]),
        ("Checking beat imports", [python, "-c", "from beat_this.inference import File2Beats"]),
    ]


@contextmanager
def setup_lock(runtime):
    # OS locks are released on exit/crash. Keep the file so concurrent launchers
    # always lock the same inode, including when a setup attempt fails.
    with (runtime / "setup.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Beat setup is already running. Wait for it to finish, then retry.") from exc
        else:
            import fcntl

            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("Beat setup is already running. Wait for it to finish, then retry.") from exc
        yield


def install(data):
    if not supported():
        print("Beat tracking setup is unavailable on this platform. "
              "Supported: Apple Silicon macOS, Windows x86-64, Linux x86-64.", flush=True)
        return False
    if ready(data):
        return True
    runtime = runtime_path(data)
    runtime.mkdir(parents=True, exist_ok=True)
    with setup_lock(runtime):
        if ready(data):
            return True
        (runtime / "ready").unlink(missing_ok=True)
        for phase, command in install_commands(runtime):
            print(phase, flush=True)
            result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if result.returncode:
                print(result.stdout, flush=True)
                raise RuntimeError(f"{phase} failed. Check internet access and free disk space, then retry setup.")
        (runtime / "ready").write_text(fingerprint() + "\n")
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--data", type=Path, default=Path(os.environ.get("RIFFROOM_DATA", ROOT / "data")))
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--checkpoint", default="final0")
    args = parser.parse_args()
    if args.install:
        install(args.data)
    else:
        from beat_this.inference import File2Beats

        tracker = File2Beats(checkpoint_path=args.checkpoint, device="cpu", dbn=False)
        beats, downbeats = tracker(str(args.audio))
        print(json.dumps({"beats": list(map(float, beats)), "downbeats": list(map(float, downbeats))}))


if __name__ == "__main__":
    main()

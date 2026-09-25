"""Core-only source launcher for Linux and Windows; no system package changes."""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = (
    "pyproject.toml", "requirements-core-lock.txt", "frontend/package.json",
    "frontend/package-lock.json", "scripts/setup_portable.py", "scripts/setup.sh",
    "scripts/launch.py", "start.sh", "start.ps1", "Riffroom.ps1",
)


def venv_python(root=ROOT, system=None):
    return root / ".env" / ("Scripts/python.exe" if (system or platform.system()) == "Windows"
                            else "bin/python")


def fingerprint(root=ROOT, system=None, machine=None):
    digest = hashlib.sha256()
    digest.update(f"core:{system or platform.system()}:{machine or platform.machine()}:"
                  f"{sys.version_info[:2]}".encode())
    for name in INPUTS:
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def compatible(python):
    return subprocess.run(
        [str(python), "-c", "import sys; sys.exit(not ((3,11) <= sys.version_info[:2] < (3,14)))"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


def prerequisites(root=ROOT):
    errors = []
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        errors.append("Install Python 3.11–3.13 from python.org and add it to PATH.")
    python = venv_python(root)
    if (root / ".env").exists() and (not python.is_file() or not compatible(python)):
        errors.append("The .env is incomplete or incompatible. Move it aside and rerun the launcher.")
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        errors.append("Install Node.js 22 or newer with npm from nodejs.org and reopen your terminal.")
    elif int(subprocess.check_output([node, "-p", "process.versions.node.split('.')[0]"], text=True)) < 22:
        errors.append("Upgrade Node.js to 22 or newer (required by the locked frontend tools).")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        errors.append("Install FFmpeg including ffprobe (ffmpeg.org); add both executables to PATH.")
    return errors


def run(argv):
    subprocess.run([str(arg) for arg in argv], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="inspect without changing files")
    parser.add_argument("--fingerprint", action="store_true")
    parser.add_argument("--launch", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    if args.fingerprint:
        print(fingerprint())
        return 0
    errors = prerequisites()
    stamp = ROOT / ".env/.riffroom-core-fingerprint"
    current = fingerprint()
    ready = (stamp.is_file() and stamp.read_text().strip() == current
             and (ROOT / "frontend/dist/index.html").is_file())
    print(f"Riffroom core setup · {platform.system()} {platform.machine()}", flush=True)
    print("Linux/Windows launch and separation still require fresh host validation.", flush=True)
    for error in errors:
        print(f"- {error}", flush=True)
    if args.check:
        print("Dependencies/build: current" if ready else "Dependencies/build: setup required")
        return int(bool(errors))
    if errors:
        return 1
    python = venv_python()
    if not ready:
        if not python.is_file():
            run([sys.executable, "-m", "venv", ROOT / ".env"])
        # Install only pinned packages; editable installation must not resolve new dependencies.
        run([python, "-m", "pip", "install", "-r", "requirements-core-lock.txt"])
        run([python, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", "."])
        run([python, "-m", "pip", "check"])
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        run([npm, "ci", "--prefix", "frontend"])
        run([npm, "run", "build", "--prefix", "frontend"])
        stamp.write_text(current + "\n")
    if args.launch:
        command = [str(python), str(ROOT / "scripts/launch.py"), "--host", args.host]
        if args.no_browser:
            command.append("--no-browser")
        os.chdir(ROOT)
        if os.name == "nt":
            return subprocess.call(command)
        os.execv(str(python), command)
    print("Riffroom is ready.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Riffroom setup failed: {exc}\nFix the error above and rerun the launcher.", file=sys.stderr)
        raise SystemExit(1) from None

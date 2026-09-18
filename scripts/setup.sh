#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "Riffroom's current ML backend needs an Apple Silicon Mac."
  exit 1
fi
for tool in conda node npm ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null; then
    echo "Missing: $tool. See README.md for installation instructions."
    exit 1
  fi
done
if [[ ! -x .env/bin/python ]]; then
  CONDA_PKGS_DIRS="$PWD/.conda-pkgs" conda create --prefix "$PWD/.env" python=3.11 pip -y
fi
# Use the SDK belonging to the selected Xcode toolchain. This also avoids
# mismatched beta Command Line Tools SDKs on this development Mac.
if command -v xcrun >/dev/null; then
  riffroom_sdk="$(xcrun --sdk macosx --show-sdk-path)"
  export CMAKE_ARGS="${CMAKE_ARGS:-} -DCMAKE_OSX_SYSROOT=$riffroom_sdk"
fi
export MACOSX_DEPLOYMENT_TARGET=14.0
.env/bin/python -m pip install -r requirements-lock.txt -e '.[dev]'
npm ci --prefix frontend
npm run build --prefix frontend
echo "Riffroom is ready. Double-click Riffroom.command or run ./start.sh."

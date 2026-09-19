#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Finder-launched terminals often omit Homebrew's install locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

SETUP_STAMP=".env/.riffroom-setup-fingerprint"
FINGERPRINT_FILES=(
  pyproject.toml
  requirements-lock.txt
  frontend/package.json
  frontend/package-lock.json
  scripts/setup.sh
)

setup_fingerprint() {
  cksum "${FINGERPRINT_FILES[@]}" | cksum | awk '{print $1 "-" $2}'
}

python_is_compatible() {
  "$1" -c 'import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) else 1)' \
    >/dev/null 2>&1
}

find_compatible_python() {
  local candidate candidate_path brew_prefix prefix version
  for candidate in python3.11 python3.12 python3.13 python3; do
    candidate_path="$(command -v "$candidate" 2>/dev/null || true)"
    if [[ -n "$candidate_path" ]] && python_is_compatible "$candidate_path"; then
      printf '%s\n' "$candidate_path"
      return 0
    fi
  done

  # A shared Homebrew may be readable even when its Python is not linked into PATH.
  brew_prefix="$(homebrew_prefix 2>/dev/null || true)"
  for prefix in "$brew_prefix" /opt/homebrew /usr/local; do
    [[ -n "$prefix" && -d "$prefix" ]] || continue
    for version in 3.11 3.12 3.13; do
      for candidate_path in \
        "$prefix/opt/python@$version/bin/python$version" \
        "$prefix/opt/python@$version/libexec/bin/python3"; do
        if [[ -x "$candidate_path" ]] && python_is_compatible "$candidate_path"; then
          printf '%s\n' "$candidate_path"
          return 0
        fi
      done
    done
    for candidate_path in \
      "$prefix/opt/python/bin/python3" \
      "$prefix/opt/python/libexec/bin/python3"; do
      if [[ -x "$candidate_path" ]] && python_is_compatible "$candidate_path"; then
        printf '%s\n' "$candidate_path"
        return 0
      fi
    done
  done
  return 1
}

homebrew_prefix() {
  command -v brew >/dev/null 2>&1 || return 1
  brew --prefix 2>/dev/null
}

path_is_writable_or_creatable() {
  local path="$1" parent="$1"

  if [[ -e "$path" || -L "$path" ]]; then
    [[ -d "$path" && -w "$path" ]]
    return
  fi

  while [[ ! -e "$parent" && ! -L "$parent" ]]; do
    path="${parent%/*}"
    [[ -n "$path" && "$path" != "$parent" ]] || return 1
    parent="$path"
  done
  [[ -d "$parent" && -w "$parent" ]]
}

homebrew_can_install() {
  local prefix repository cellar path

  prefix="$(homebrew_prefix)" || return 1
  repository="$(brew --repository 2>/dev/null)" || return 1
  cellar="$(brew --cellar 2>/dev/null)" || return 1
  [[ -n "$prefix" && -n "$repository" && -n "$cellar" ]] || return 1

  for path in \
    "$prefix" \
    "$repository" \
    "$cellar" \
    "$prefix/opt" \
    "$prefix/bin" \
    "$prefix/sbin" \
    "$prefix/etc" \
    "$prefix/include" \
    "$prefix/lib" \
    "$prefix/share" \
    "$prefix/var/homebrew/linked"; do
    path_is_writable_or_creatable "$path" || return 1
  done
}

show_homebrew_help() {
  echo
  echo "Riffroom needs Homebrew to get the missing tools."
  echo "Install Homebrew with its official command:"
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo "Then double-click Riffroom.command again."
}

show_read_only_homebrew_help() {
  local missing_tools="$1"
  echo
  echo "Riffroom found Homebrew, but this account cannot modify that installation."
  echo "It belongs to another macOS account, so Riffroom cannot install $missing_tools."
  echo "Use the account that owns Homebrew, or ask an administrator to install $missing_tools."
}

require_homebrew_install() {
  local missing_tools="$1"
  if ! command -v brew >/dev/null 2>&1; then
    show_homebrew_help
    return 1
  fi
  if ! homebrew_can_install; then
    show_read_only_homebrew_help "$missing_tools"
    return 1
  fi
}

install_formula() {
  local formula="$1" tool_name="$2"
  require_homebrew_install "$tool_name" || exit 1
  echo
  echo "Installing $formula with Homebrew..."
  if ! brew install "$formula"; then
    echo
    echo "Homebrew could not install $formula. Fix the message above, then rerun Riffroom.command."
    exit 1
  fi
}

check_setup() {
  local status=0 missing_needs_brew=0 missing_read_only_brew=0
  local brew_available=0 brew_installable=0 candidate current_fingerprint saved_fingerprint
  local read_only_missing_tools=""

  echo "Checking Riffroom setup (no changes will be made)..."

  if command -v brew >/dev/null 2>&1; then
    brew_available=1
    if homebrew_can_install; then
      brew_installable=1
    fi
  fi

  if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo "- This Mac is not supported: Riffroom currently requires Apple Silicon."
    status=1
  else
    echo "- Apple Silicon Mac: ready"
  fi

  if [[ -x .env/bin/python ]]; then
    if python_is_compatible .env/bin/python; then
      echo "- Project Python: $(.env/bin/python --version 2>&1)"
    else
      echo "- Project Python: incompatible (Riffroom needs Python 3.11, 3.12, or 3.13)"
      status=1
    fi
  elif candidate="$(find_compatible_python)"; then
    echo "- Project Python: not created yet; would use $candidate"
  elif (( brew_installable != 0 )); then
    echo "- Project Python: not created yet; would install Python 3.11 with Homebrew"
  elif (( brew_available != 0 )); then
    echo "- Compatible Python: missing; this account cannot install it with the shared Homebrew"
    status=1
    missing_read_only_brew=1
    read_only_missing_tools="Python 3.11"
  else
    echo "- Compatible Python: missing"
    status=1
    missing_needs_brew=1
  fi

  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    echo "- Node.js and npm: ready"
  elif (( brew_installable != 0 )); then
    echo "- Node.js/npm: missing; would install node with Homebrew"
  elif (( brew_available != 0 )); then
    echo "- Node.js/npm: missing; this account cannot install it with the shared Homebrew"
    status=1
    missing_read_only_brew=1
    read_only_missing_tools="${read_only_missing_tools}${read_only_missing_tools:+, }Node.js/npm"
  else
    echo "- Node.js/npm: missing"
    status=1
    missing_needs_brew=1
  fi

  if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    echo "- FFmpeg and ffprobe: ready"
  elif (( brew_installable != 0 )); then
    echo "- FFmpeg/ffprobe: missing; would install ffmpeg with Homebrew"
  elif (( brew_available != 0 )); then
    echo "- FFmpeg/ffprobe: missing; this account cannot install it with the shared Homebrew"
    status=1
    missing_read_only_brew=1
    read_only_missing_tools="${read_only_missing_tools}${read_only_missing_tools:+, }FFmpeg/ffprobe"
  else
    echo "- FFmpeg/ffprobe: missing"
    status=1
    missing_needs_brew=1
  fi

  if [[ -f frontend/dist/index.html ]]; then
    echo "- Frontend build: ready"
  else
    echo "- Frontend build: missing; setup would build it"
  fi

  current_fingerprint="$(setup_fingerprint)"
  saved_fingerprint="$(sed -n '1p' "$SETUP_STAMP" 2>/dev/null || true)"
  if [[ "$saved_fingerprint" == "$current_fingerprint" ]]; then
    echo "- Dependency stamp: current"
  else
    echo "- Dependency stamp: missing or stale; setup would refresh dependencies"
  fi

  if (( missing_needs_brew != 0 )); then
    show_homebrew_help
  fi
  if (( missing_read_only_brew != 0 )); then
    show_read_only_homebrew_help "$read_only_missing_tools"
  fi
  return "$status"
}

case "${1:-}" in
  --check)
    check_setup
    exit $?
    ;;
  --fingerprint)
    setup_fingerprint
    exit 0
    ;;
  "")
    ;;
  *)
    echo "Usage: $0 [--check|--fingerprint]"
    exit 2
    ;;
esac

if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "Riffroom currently requires an Apple Silicon Mac."
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  install_formula node "Node.js/npm"
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Homebrew finished, but Node.js/npm is still unavailable. Rerun Riffroom.command in a new Terminal window."
    exit 1
  fi
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  install_formula ffmpeg "FFmpeg/ffprobe"
  if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "Homebrew finished, but FFmpeg/ffprobe is still unavailable. Rerun Riffroom.command in a new Terminal window."
    exit 1
  fi
fi

if [[ -x .env/bin/python ]]; then
  if ! python_is_compatible .env/bin/python; then
    echo "The existing project Python is not version 3.11, 3.12, or 3.13."
    echo "Move the .env folder aside and rerun Riffroom.command to create a compatible environment."
    exit 1
  fi
  echo "Reusing the existing project Python ($(.env/bin/python --version 2>&1))."
else
  riffroom_python="$(find_compatible_python || true)"
  if [[ -z "$riffroom_python" ]]; then
    install_formula python@3.11 "Python 3.11"
    riffroom_python="$(brew --prefix python@3.11)/bin/python3.11"
  fi

  if [[ ! -x "$riffroom_python" ]] || ! python_is_compatible "$riffroom_python"; then
    echo "Riffroom could not find a compatible Python after setup."
    echo "Rerun Riffroom.command; if this continues, review the Homebrew message above."
    exit 1
  fi

  echo "Creating Riffroom's project environment with $($riffroom_python --version 2>&1)..."
  "$riffroom_python" -m venv .env
fi

# Use the SDK belonging to the selected Xcode toolchain when one is available.
# This avoids mismatched beta SDKs when native Python packages need to compile.
riffroom_sdk=""
if command -v xcrun >/dev/null 2>&1; then
  riffroom_sdk="$(xcrun --sdk macosx --show-sdk-path 2>/dev/null || true)"
fi
if [[ -n "$riffroom_sdk" ]]; then
  export CMAKE_ARGS="${CMAKE_ARGS:-} -DCMAKE_OSX_SYSROOT=$riffroom_sdk"
fi
export MACOSX_DEPLOYMENT_TARGET=14.0

echo
echo "Installing Riffroom's Python packages..."
if ! .env/bin/python -m pip install -r requirements-lock.txt -e '.[dev]'; then
  echo
  echo "Python package installation failed."
  if [[ -z "$riffroom_sdk" ]]; then
    echo "A package may need Apple's command-line tools. Run 'xcode-select --install', then try again."
  else
    echo "Fix the error above, then rerun Riffroom.command."
  fi
  exit 1
fi

echo
echo "Installing and building Riffroom's interface..."
if ! npm ci --prefix frontend || ! npm run build --prefix frontend; then
  echo
  echo "The interface build failed. Fix the error above, then rerun Riffroom.command."
  exit 1
fi

setup_fingerprint > "$SETUP_STAMP"
echo
echo "Riffroom is ready."

#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

# Finder-launched terminals sometimes omit Homebrew from PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

setup_reason=""
if [[ ! -x .env/bin/python ]]; then
  setup_reason="the project environment is missing"
elif [[ ! -f frontend/dist/index.html ]]; then
  setup_reason="the interface has not been built"
else
  current_fingerprint="$(./scripts/setup.sh --fingerprint)"
  saved_fingerprint="$(sed -n '1p' .env/.riffroom-setup-fingerprint 2>/dev/null || true)"
  if [[ "$saved_fingerprint" != "$current_fingerprint" ]]; then
    setup_reason="dependencies have changed"
  fi
fi

if [[ -n "$setup_reason" ]]; then
  echo "Preparing Riffroom because $setup_reason..."
  ./scripts/setup.sh
fi

exec .env/bin/python scripts/launch.py "$@"

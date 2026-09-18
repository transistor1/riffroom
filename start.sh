#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
# Finder-launched terminals sometimes omit Homebrew from PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if [[ ! -x .env/bin/python || ! -f frontend/dist/index.html ]]; then
  echo "First, run ./scripts/setup.sh to install and build Riffroom."
  exit 1
fi
exec .env/bin/python scripts/launch.py "$@"

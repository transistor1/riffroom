#!/bin/bash
cd "$(dirname "$0")"

./start.sh "$@"
riffroom_status=$?

if (( riffroom_status != 0 && riffroom_status != 130 && riffroom_status != 143 )) && [[ -t 0 ]]; then
  echo
  read -r -p "Riffroom could not start. Press Return to close this window."
fi

exit "$riffroom_status"

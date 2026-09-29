#!/bin/sh
# values.sh is generated with validated keys and shell-quoted literal values.
# These assignments occur inside the process, NOT in Docker's configured environment.
set -eu
set -a
for role in $GROT_RUNTIME_ROLES; do
  file="/run/grot/$role/values.sh"
  if [ ! -r "$file" ]; then
    echo 'Runtime settings unavailable; relaunch with grot docker.' >&2
    exit 1
  fi
  . "$file"
done
set +a
exec "$@"

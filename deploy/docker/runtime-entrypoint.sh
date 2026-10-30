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
# Only application containers have OTEL_SERVICE_NAME. Do not stamp the gateway,
# database or collector's own identity onto application telemetry.
if [ -n "${OTEL_SERVICE_NAME:-}" ]; then
  : "${GROT_HOST_ID:?Missing Docker host identity; launch with grot docker}"
  : "${GROT_INSTANCE_PREFIX:?Missing instance identity; launch with grot docker}"
  export OTEL_RESOURCE_ATTRIBUTES="${OTEL_RESOURCE_ATTRIBUTES:+$OTEL_RESOURCE_ATTRIBUTES,}grafana.host.id=$GROT_HOST_ID,service.instance.id=$GROT_INSTANCE_PREFIX-$OTEL_SERVICE_NAME"
fi
exec "$@"

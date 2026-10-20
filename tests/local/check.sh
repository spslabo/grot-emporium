#!/usr/bin/env bash
# Offline acceptance: real application services, in-memory persistence, no model.
set -euo pipefail
cd "$(dirname "$0")/../.."
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-2}"
compose=(docker compose -f tests/local/compose.yaml)
cleanup() {
  code=$?
  if ((code != 0)); then "${compose[@]}" logs --tail 30; fi
  if [[ "${KEEP_LOCAL:-false}" != true ]]; then "${compose[@]}" down --volumes; fi
  exit "$code"
}
trap cleanup EXIT
if [[ "${SKIP_BUILD:-false}" != true ]]; then "${compose[@]}" build; fi
# Fresh evidence: never pass by finding traces left over from a previous run.
"${compose[@]}" down --volumes
"${compose[@]}" up -d --wait --wait-timeout 120
"${compose[@]}" run --rm k6
"${compose[@]}" run --rm browser
# Batch/export is asynchronous. Poll assertions instead of assuming a fixed delay.
for attempt in {1..15}; do
  if "${compose[@]}" run --rm verify-traces python /test.py /data/grot-traces.json --metrics; then
    echo 'Grot offline acceptance passed.'
    exit 0
  fi
  sleep 2
done
echo 'Telemetry verification failed' >&2
exit 1

#!/usr/bin/env bash
# Smoke-test the public quickstart, not an operator's private telemetry settings.
set -euo pipefail
cd "$(dirname "$0")/../.."
unset GROT_BACKEND_ENV_FILE GROT_UI_ENV_FILE
export GROT_IMAGE_PREFIX=grot GROT_IMAGE_TAG=portable-test
export GROT_PORT="${GROT_TEST_PORT:-18781}"
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-2}"
compose=(docker compose -p grot-portable-check -f deploy/docker/compose.yaml)
cleanup() {
  code=$?
  if ((code != 0)); then "${compose[@]}" logs --tail 20; fi
  "${compose[@]}" down
  exit "$code"
}
trap cleanup EXIT
"${compose[@]}" build
"${compose[@]}" up -d --wait --wait-timeout 120
for script in shopping browser; do
  image=grafana/k6:2.3.0
  if [[ "$script" == browser ]]; then image=grafana/k6:2.3.0-with-browser; fi
  docker run --rm --network grot-portable-check_default \
    -v "$PWD:/work:ro" -w /work -e K6_BROWSER_ARGS=no-sandbox "$image" \
    run -e BASE_URL=http://ui:8080 -e TARGET_AUTHORIZED=true "tests/k6/$script.js"
done
echo 'Portable quickstart passed without private configuration; telemetry disabled.'

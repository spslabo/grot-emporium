#!/usr/bin/env bash
# Smoke-test the public quickstart, not an operator's private telemetry settings.
set -euo pipefail
cd "$(dirname "$0")/../.."
unset GROT_BACKEND_ENV_FILE GROT_UI_ENV_FILE GROT_DATABASE_ENV_FILE GROT_ORDERS_DB_ENV_FILE
umask 077
credentials=$(mktemp -d "${TMPDIR:-/tmp}/grot-portable-db.XXXXXX")
export GROT_IMAGE_PREFIX=grot GROT_IMAGE_TAG=portable-test
export GROT_PORT="${GROT_TEST_PORT:-18781}"
export COMPOSE_PARALLEL_LIMIT="${COMPOSE_PARALLEL_LIMIT:-2}"
compose=(docker compose -p grot-portable-check -f deploy/docker/compose.yaml)
cleanup() {
  code=$?
  if ((code != 0)); then "${compose[@]}" logs --tail 20; fi
  "${compose[@]}" down || true
  rm -rf "$credentials"
  exit "$code"
}
trap cleanup EXIT
# Fresh local database passwords, not operator/cloud credentials. Deliver only
# the application password to orders; the admin/monitor keys stay isolated.
python3 - "$credentials" <<'PY'
from pathlib import Path
import sys
from scripts.grot_config import initialize, load
root = Path(sys.argv[1])
initialize(root)
password = load(root / 'database.env')['GROT_DB_APP_PASSWORD']
(root / 'orders-db.env').write_text('RETAIL_ORDERS_PERSISTENCE_PASSWORD=' + password + '\n')
(root / 'orders-db.env').chmod(0o600)
PY
export GROT_DATABASE_ENV_FILE="$credentials/database.env"
export GROT_ORDERS_DB_ENV_FILE="$credentials/orders-db.env"
"${compose[@]}" build
"${compose[@]}" up -d --wait --wait-timeout 120
for script in shopping browser; do
  image=grafana/k6:2.3.0
  if [[ "$script" == browser ]]; then image=grafana/k6:2.3.0-with-browser; fi
  docker run --rm --network grot-portable-check_default \
    -v "$PWD:/work:ro" -w /work -e K6_BROWSER_ARGS=no-sandbox "$image" \
    run -e BASE_URL=http://ui:8080 -e TARGET_AUTHORIZED=true "tests/k6/$script.js"
done
echo 'Portable quickstart passed without operator credentials; telemetry disabled.'

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 scripts/sync_grot_alloy.py --check
python3 tests/telemetry/check_destinations.py

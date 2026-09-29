#!/usr/bin/env bash
# Local-only, disposable k3s acceptance. No AWS, real stack or model calls.
set -euo pipefail
cd "$(dirname "$0")/../.."
for tool in docker k3d kubectl helm python3 openssl; do command -v "$tool" >/dev/null; done
umask 077
export GROT_K3S_TEST_DIR
GROT_K3S_TEST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/grot-k3s-test.XXXXXX")
export GROT_K3S_TEST_CLUSTER="grot-acceptance-$$-$RANDOM"
export KUBECONFIG="$GROT_K3S_TEST_DIR/kubeconfig"
created=false
cleanup() {
  if "$created"; then k3d cluster delete "$GROT_K3S_TEST_CLUSTER"; fi
  for image in alloy gateway; do
    docker image rm "grot-test/$image:$GROT_K3S_TEST_CLUSTER" >/dev/null 2>&1 || true
  done
  rm -rf "$GROT_K3S_TEST_DIR"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
# Shared application images; the acceptance-only images add a public test CA.
docker compose -f deploy/docker/compose.yaml build
api_port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
k3d cluster create "$GROT_K3S_TEST_CLUSTER" --image rancher/k3s:v1.33.6-k3s1 \
  --api-port "127.0.0.1:$api_port" --no-lb --servers-memory 5g \
  --kubeconfig-update-default=false --kubeconfig-switch-context=false \
  --k3s-arg '--disable=traefik,servicelb,metrics-server@server:0' \
  --k3s-arg '--secrets-encryption@server:0' --timeout 180s
created=true
k3d kubeconfig get "$GROT_K3S_TEST_CLUSTER" > "$KUBECONFIG"
kubectl --context "k3d-$GROT_K3S_TEST_CLUSTER" get --raw=/readyz
python3 tests/kubernetes/check.py

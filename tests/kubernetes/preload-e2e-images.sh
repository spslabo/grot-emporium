#!/usr/bin/env bash
# Preload vendor images so the disposable Kind test never pulls them during startup.
set -euo pipefail
cluster="${1:-kind}"
archive=$(mktemp "${TMPDIR:-/tmp}/grot-e2e-images.XXXXXX")
trap 'rm -f "$archive"' EXIT
nodes=$(kind get nodes --name "$cluster")
if [ -z "$nodes" ]; then echo "No nodes found in Kind cluster $cluster" >&2; exit 1; fi
images=(
  'docker.io/library/mysql:8.0 public.ecr.aws/docker/library/mysql:8.0'
  'docker.io/amazon/dynamodb-local:1.25.1 public.ecr.aws/aws-dynamodb-local/aws-dynamodb-local:1.25.1'
  'docker.io/library/postgres:16.1 public.ecr.aws/docker/library/postgres:16.1'
  'docker.io/library/rabbitmq:3-management public.ecr.aws/docker/library/rabbitmq:3-management'
  'docker.io/library/redis:6.0-alpine redis:6.0-alpine'
)
for pair in "${images[@]}"; do
  read -r source target <<< "$pair"
  echo "Preloading $source for $target"
  pulled=false
  for attempt in 1 2 3; do
    if docker pull "$source"; then pulled=true; break; fi
    if [ "$attempt" -lt 3 ]; then sleep "$((attempt * 5))"; fi
  done
  if ! "$pulled"; then echo "Unable to download $source; deployment was not attempted." >&2; exit 1; fi
  docker tag "$source" "$target"
  # Export only the installed platform; modern Docker stores multi-platform indexes.
  platform=$(docker image inspect "$source" --format '{{.Os}}/{{.Architecture}}')
  docker image save --platform "$platform" --output "$archive" "$target"
  for node in $nodes; do
    # Import the named runtime image, not attestation manifests as runnable images.
    docker exec --privileged -i "$node" ctr --namespace=k8s.io images import \
      --platform "$platform" --snapshotter=overlayfs - < "$archive"
  done
done

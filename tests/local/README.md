# Maintainer tests

Run from the repository root. Python tests require `tests/requirements.txt` and Helm; integration tests require Docker Compose 2.30+.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/sync_grot_alloy.py --check
bash tests/local/check.sh
bash tests/telemetry/check-destinations.sh
```

- `check.sh` builds five services with in-memory storage and a local trace collector. It checks shopping/browser journeys, trace parenting, latency histograms and metric-label cardinality. `SKIP_BUILD=true` reuses images. Containers and the trace volume are removed on exit; `KEEP_LOCAL=true` leaves the UI at `http://localhost:18770`.
- `check-destinations.sh` checks metrics, logs, traces, profiles and Faro against two isolated TLS fixtures. It also checks credential exposure, role isolation, proxy behavior and cleanup.

These tests use synthetic data and do not contact Grafana Cloud, AWS or model APIs.

## Kubernetes acceptance

Requires k3d, Docker, kubectl, Helm, Python 3 and OpenSSL:

```sh
bash tests/kubernetes/check.sh
```

Creates a disposable loopback-only k3s cluster with a separate temporary kubeconfig. Checks both launch modes, signal delivery, token rotation, retarget protection, namespace isolation, external-Secret preservation and partial-install cleanup. The cluster, temporary credentials and test images are removed on exit. Your normal Kubernetes context is unchanged.

## Deliberate Java regression

```sh
python3 scripts/prepare-orders-regression.py --output /tmp/grot-bad-orders
# The destination must not already exist.
docker build -t grot-orders:regression /tmp/grot-bad-orders/src/orders
```

The exported source assumes numeric SKUs, causing UUID product IDs to throw `NumberFormatException` before persistence. The working tree remains unchanged. Use this image only in an isolated demo; never merge the fixture into the healthy branch.

With a healthy local test stack running:

```sh
GROT_ORDERS_IMAGE=grot-orders:regression docker compose -f tests/local/compose.yaml up -d --no-build --wait orders
docker compose -f tests/local/compose.yaml run --rm k6
# Expect shopping failures and Orders error spans.

# Restore the healthy image and expect shopping to pass.
docker compose -f tests/local/compose.yaml up -d --no-build --wait orders
docker compose -f tests/local/compose.yaml run --rm k6
```

For Grafana Cloud query checks, use the [deployment verification commands](../../deploy/README.md#verification-and-limits).

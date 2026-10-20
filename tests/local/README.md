# Maintainer tests

Run from the repository root. Python tests require `tests/requirements.txt` and Helm; integration tests require Docker Compose 2.30+.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/sync_grot_alloy.py --check
bash tests/local/check.sh
bash tests/telemetry/check-destinations.sh
```

- `check.sh` builds five services with in-memory storage and a local trace collector. It checks shopping/browser journeys, trace parenting, latency histograms and metric-label cardinality. `SKIP_BUILD=true` reuses images. Containers and the trace volume are removed on exit; `KEEP_LOCAL=true` leaves the UI at `http://localhost:18770`.
- `check-destinations.sh` exercises the default PostgreSQL deployment against two isolated TLS fixtures: shopping writes actual order rows, the monitor can SELECT but has no DML privileges, and PostgreSQL health/query metrics, query-association logs and JDBC traces reach the destination alongside metrics/logs/traces/profiles/Faro. It checks generated DB passwords and ingestion tokens for exposure in Docker configuration, process arguments, logs, host files and telemetry buffers, plus role isolation, proxy behavior and cleanup. It also verifies cAdvisor/host metrics at the TLS destination, actual Grot container samples (not just exporter readiness), and bounded k6 shopping/browser traffic with passing thresholds and runner cleanup.

These tests use synthetic data and do not contact Grafana Cloud, AWS or model APIs.

## Kubernetes acceptance

Requires k3d, Docker, kubectl, Helm, Python 3 and OpenSSL:

```sh
bash tests/kubernetes/check.sh
```

Creates a disposable loopback-only k3s cluster with a separate temporary kubeconfig. Checks both launch modes, PostgreSQL/DB O11y, app signals, cluster inventory, kubelet cAdvisor, Linux node metrics and Kubernetes events. Also checks ingestion-token rotation, retarget protection, namespace ingress isolation, external-Secret preservation, shared-monitoring teardown and partial-install cleanup. The cluster, temporary credentials and test images are removed on exit. Your normal Kubernetes context is unchanged.

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

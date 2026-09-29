# Grot Emporium

A nine-product Grot squishy store with Java, Go and Node services, instrumented for **Grafana Cloud**. Based on the [AWS retail store sample](https://github.com/aws-containers/retail-store-sample-app).

**Grafana Cloud is required for the observability demo.** Cloud applications such as Application Observability require the corresponding products and permissions in your stack; this repository does not install them.

## Dependencies

| Dependency | Required for |
|---|---|
| Python 3 | Launcher and verification commands |
| Docker with Compose 2.30+ | Docker deployment and local browser/shopping probes |
| kubectl and Helm 3/4 | Kubernetes deployment; requires an existing cluster |
| [gcx](https://github.com/grafana/gcx) | Grafana Cloud query checks: `verify --grafana-context` and `verify-cloud` |
| Grafana Cloud stack and ingestion credentials | Telemetry export |

Install [gcx](https://github.com/grafana/gcx), then authenticate a named Cloud context:

```sh
gcx login demo-cloud
gcx --context demo-cloud config check
```

`gcx login demo-cloud` creates a named context (or reauthenticates an existing one). Follow the prompts to select your Grafana Cloud stack and sign in. Its query credentials are separate from the telemetry ingestion token.

`--grafana-context demo-cloud` tells the helper to run its read-only queries with `gcx --context demo-cloud`. This selects the stack to query, independently of the deployment alias; it does not change the app's telemetry destination.

The verification commands are optional helpers using fixed queries and assertions, with **no AI/model dependency, model credentials or model calls**. You can verify ingestion independently in Grafana Explore, the Cloud applications, or with your own queries and tooling. See [verification and limits](deploy/README.md#verification-and-limits).

## Docker

```sh
./grot docker customer-demo
./grot verify customer-demo --grafana-context demo-cloud
./grot stop customer-demo
```

Open `http://localhost:8080`. Hidden prompts collect ingestion settings. Credentials are held in memory-backed runtime files, not host profiles or image layers. Stop removes this demo's containers, credentials and telemetry buffers.

## Kubernetes quick — including k3s

Requires an existing cluster, kubectl, Helm 3/4 and registry-accessible images:

```sh
./grot k8s customer-demo --mode quick --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
./grot verify customer-demo --context "$CONTEXT" --grafana-context demo-cloud
./grot stop customer-demo --context "$CONTEXT"
```

The launcher prompts for settings and creates demo-owned Secrets in `grot-customer-demo`. Cleanup removes owned Secrets but retains the namespace and external Secrets.

## Kubernetes long-term

Supply the four runtime Secrets through your team's secret-management tooling:

```sh
./grot k8s customer-demo --mode long-term --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

Uses the same charts without modifying or deleting external Secrets. See the [deployment guide](deploy/README.md) for Secret keys, image publication, browser access, rotation and cleanup.

## Features and configuration

- Prometheus metrics, correlated logs, OTLP traces, Java/Go/Node profiles and Faro browser telemetry.
- [Optional AI shopping assistant and Agent Observability](docs/optional-ai-chat.md).
- [Verification and Cloud query checks](deploy/README.md#verification-and-limits).
- [Maintainer tests and deliberate failure scenario](tests/local/README.md).

**Synthetic data only.** The demo uses in-memory storage and does not process real payments. Model calls require explicit configuration. Automation routing is plan-only; launch commands do not post tickets, page production teams, merge PRs or deploy fixes.

Host/Docker/cluster administrators can access runtime credentials. Protect host swap/snapshots, and configure Kubernetes Secret encryption and access controls as described in the deployment guide.

Original [upstream documentation](README.upstream.md), attribution and [license](LICENSE) are retained.

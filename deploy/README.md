# Deployment guide

**The telemetry destination is Grafana Cloud.** Docker and Kubernetes are the application runtimes. Cloud applications such as Application Observability, Frontend Observability and Agent Observability require the corresponding products and permissions in your stack.

## Connection settings

Copy ingestion settings from your Grafana Cloud connection pages. Use each signal's **ingestion username**, not your Grafana login or an assumed shared stack ID.

The Docker and Kubernetes quick launchers prompt for:

| Input | Required value |
|---|---|
| OTLP (Traces) endpoint + username | OTLP HTTP base endpoint; not the Tempo query URL or `/v1/traces` |
| Metrics endpoint + username | Full Prometheus remote-write URL |
| Logs endpoint + username | Full Loki push URL ending in `/loki/api/v1/push` |
| Profiles endpoint + username | Pyroscope ingestion base URL |
| Shared ingestion API token | Stack-scoped access-policy token with `traces:write`, `metrics:write`, `logs:write`, `profiles:write` |
| Optional Faro URL | Collector URL from a Frontend Observability application; blank disables browser export |

Each hidden input is format-validated immediately. Invalid entries are re-prompted without losing earlier answers held in memory. Format validation does not authenticate credentials or prove delivery; use the verification commands below.

For Faro, allow the storefront origin and the browser probe origin in the application:

- Docker: `http://localhost:8080` (or your chosen storefront port), plus `http://gateway:8080`.
- Kubernetes: your storefront origin, plus `http://grot-gateway`.

The browser sends telemetry to the same-origin `/telemetry` proxy. The upstream collector URL stays server-side. Do not disable browser security.

For separate per-signal tokens or optional UI settings, use `--settings-stdin`. It accepts JSON grouped by `alloy`, `gateway`, and optional `backend`/`ui` roles, with string values matching `scripts/grot_config.py`. Stream the object from your credential tool; do not put credentials in command arguments, shell history or the repository. Internal backend/UI defaults are generated automatically.

## Docker

Requires Python 3, Docker Compose **2.30+**, and approximately 8 GiB available for services and browser probes. Run from the checkout on the Docker host.

```sh
./grot docker customer-demo
./grot verify customer-demo --grafana-context demo-cloud
./grot stop customer-demo
```

The launcher builds the five app images and starts Alloy, the app and the gateway. Open `http://localhost:8080`. Use `--port`, `--collector-port` and `--syslog-port` to choose distinct loopback ports for concurrent demos.

Credentials are passed through stdin into role-specific tmpfs volumes inside the Docker engine. Consumers mount their role files read-only. Credentials are not stored in Docker's configured environment or image layers. The trusted, network-disabled staging container keeps these volumes mounted.

Only ports, a destination fingerprint and Faro enablement are saved under `~/.local/state/grot-emporium/<alias>/`. Supply credentials again after teardown or loss of runtime storage. `stop` removes this project's workloads, credential volumes and telemetry buffers, not other projects.

A failed launch attempts to stop workloads and clear runtime credentials, retaining destination-bound buffers for retry. Use `stop` to discard a failed deployment completely. Cleanup requires a reachable Docker daemon.

Token rotation for the same destination is supported by relaunching. Endpoint/ingestion-user changes are rejected while an alias has buffered data; stop and clean up before reusing it for another destination.

For the store without telemetry:

```sh
docker compose -f deploy/docker/compose.yaml up -d --build --wait
docker compose -f deploy/docker/compose.yaml down
```

## Kubernetes quick

Requires Python 3, Helm 3/4, an authenticated kubectl context, registry-accessible images and permissions to manage the dedicated namespace's workloads, RBAC and Secrets. The launcher does not provision a cluster or cloud infrastructure.

```sh
./grot k8s customer-demo --mode quick --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

The namespace defaults to `grot-customer-demo`. Use `--namespace` for another dedicated `grot-*` namespace. Quick mode can create it if your permissions allow. Settings go directly to demo-owned Kubernetes Secrets without a local credential manifest.

For browser access:

```sh
kubectl --context "$CONTEXT" -n grot-customer-demo port-forward service/grot-gateway 8080:80
```

Verify and stop:

```sh
./grot verify customer-demo --context "$CONTEXT" --grafana-context demo-cloud
./grot stop customer-demo --context "$CONTEXT"
```

Cleanup waits for workloads to terminate, then removes only Secrets still owned by the installation. It also works after a partial install. Externally managed/adopted Secrets and the namespace are retained. Quick mode refuses to overwrite external Secrets or adopt unrelated Helm releases.

## Kubernetes long-term

Create the namespace and supply these Secrets through your team's existing tooling:

| Secret | Contents |
|---|---|
| `grot-backend-runtime` | Internal receiver settings and shared app identity |
| `grot-ui-runtime` | Faro enablement and optional model/Agent Observability settings |
| `grot-collector-runtime` | Collector identity and per-signal ingestion URLs, usernames and tokens |
| `grot-gateway-runtime` | `GRAFANA_FARO_URL`, blank when Faro is disabled |

Keys follow the role schema in `scripts/grot_config.py`. Backend tracing/profiling must be enabled against `http://alloy:4318` and `http://alloy:4040`. UI Faro uses `/telemetry` when a gateway destination is supplied. Backend and collector environment identities must match. Set `GROT_CLUSTER` to your cluster identity when correlating with infrastructure telemetry.

```sh
./grot k8s customer-demo --mode long-term --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

This mode validates existing Secrets in memory without modifying them. It requires only namespaced permissions. The charts use native Secret references, not CSI-only mounts. [External Secret references](external-secrets.example.yaml) are provided for teams using an existing controller; installing a secret manager is outside this repository.

After token rotation, rerun the installer to restart environment-based consumers, or use your approved restart controller. Changing destination endpoints/user IDs requires a separate deployment namespace. Verify/stop commands are the same as quick mode; long-term stop never deletes external Secrets. Clean up before changing an installation's mode.

### Images and networking

Run the **Publish Grot images** workflow, or push an approved `grot-v*` release tag, to publish amd64/arm64 images to your fork's GHCR namespace, tagged with the commit SHA. Set `IMAGE_PREFIX` and `VERSION` to those published images. For private registries, use `--pull-secret EXISTING_SECRET_NAME` or your cluster's native credential provider.

The telemetry chart uses namespace-scoped pod/log RBAC and collector ingress NetworkPolicy. No public ingress, load balancer, ClusterRole or host mount is created. Your CNI must enforce NetworkPolicy; the chart does not provide an egress allow-list. Kubernetes collector buffers are ephemeral and may lose queued telemetry on restart.

## Verification and limits

`grot verify` and `grot verify-cloud` are **optional verification helpers**, not a required ingestion component or a substitute for independent checks. They run fixed HTTP/browser tests, counter comparisons and datasource queries. They do not use AI, require model credentials, invoke chat or call a model API.

### Create and select a gcx context

Install [gcx](https://github.com/grafana/gcx) for query-side validation, then authenticate:

```sh
gcx login demo-cloud
gcx --context demo-cloud config check
```

`gcx login demo-cloud` creates a context named `demo-cloud`, or reauthenticates it if it exists. Follow the interactive prompts to enter your stack and authenticate; prefer browser OAuth. Keep its configuration outside the repository. This supplies **stack read/query access**, separate from the write-only ingestion token; Cloud platform-management login is not required.

```sh
# Shopping/browser probes, export acknowledgements and Cloud queries.
./grot verify customer-demo --grafana-context demo-cloud

# Read-only Cloud queries; no probes, rebuilds or restarts.
./grot verify-cloud customer-demo --grafana-context demo-cloud
```

`--grafana-context demo-cloud` passes `--context demo-cloud` to every gcx command. The saved context supplies the Grafana stack and query authentication; the helper does not create a context or switch the gcx default. Choose the context for the stack receiving your app's telemetry. The deployment alias (`customer-demo`) identifies the running app and defaults its cluster-label filter—it need not match the gcx context name. Selecting a query context does not reconfigure ingestion.

For Kubernetes, add `--context` and, if customized, `--namespace` to `verify`. `--context` selects kubectl; `--grafana-context` selects gcx. Set `--cloud-cluster YOUR_LABEL` if `GROT_CLUSTER` differs from the destination alias.

| Check | What it verifies |
|---|---|
| HTTP shopping | Catalog/cart/synthetic checkout requests |
| Chromium browser | Cart quantities/deletion, responsive images, checkout, and successful Faro responses when enabled |
| Alloy counters | Fresh destination acknowledgements for metrics, logs, traces and profiles |
| gcx queries | Current successful scrapes, recent trace matches and nonempty indexed profiles for all five services; recent deployment logs with per-service coverage reported |

Progress is printed per probe and signal. Private subprocess/query output is suppressed. Tests use synthetic data and do not call models. Without `--grafana-context`, verification is transport-only. With it, the Cloud stage also runs after a local-stage failure; either failure makes the combined command fail.

Cloud checks select the standard Cloud datasources, or a unique datasource of each required type. Ambiguous alternatives are rejected. Logs/traces/profiles use a 15-minute window; retry after indexing delays. Quiet services are reported separately rather than treated as failed log ingestion. Metrics/logs/profiles are scoped by cluster label. Traces match the Grot service namespace and service, so they are not deployment-unique when several deployments share that namespace.

Recent indexed presence is not exact probe correlation, complete trace parenting, per-span profile linking, Faro indexing or App Observability readiness. Those require separate checks in the Cloud applications. Hosted response integrations require separate validation.

### Verify independently

You can skip the helper and use Grafana Explore, Cloud applications, direct gcx commands or your own tests. Generate shopping traffic and inspect a matching recent time range:

- **Metrics:** query `up{service_namespace="grot-emporium",cluster="customer-demo"}` and inspect application request counters/histograms.
- **Logs:** query `{service_namespace="grot-emporium",cluster="customer-demo"}` and inspect timestamps and service labels.
- **Traces:** query `{resource.service.namespace="grot-emporium"}` in Tempo, then inspect a shopping trace's services and parent/child spans. Narrow the query when multiple deployments share this namespace.
- **Profiles:** select the Grot services and deployment labels in Profiles and inspect nonempty samples.
- **Browser telemetry:** inspect sessions/errors in your Frontend Observability application; a successful proxy response alone does not prove indexing.

Replace `customer-demo` with your actual `GROT_CLUSTER` label. Use the datasources and read permissions for the receiving stack.

### Cross-signal navigation

- **Browser → backend:** open a browser trace from Frontend Observability and check that the UI server span is a child of the browser request span. The browser service may use the registered Frontend application name rather than `grot-emporium-web`.
- **Trace → logs:** copy the trace ID and search Loki with `{service_namespace="grot-emporium",cluster="customer-demo"} |= "TRACE_ID"`. Check service labels and timestamps. In a shared stack, narrow the selector rather than searching every application's logs.
- **Logs → trace:** use the log's `trace_id`/`traceId` field to open that trace in Tempo. The Loki datasource's derived-field link must target the Tempo datasource. A quiet service may have spans without corresponding log lines.
- **Trace → profiles:** use the span's service and time range, widening by a minute if necessary for profile sampling/upload intervals. Map the trace's `service.name` to the profile's `service_name`, and select the matching namespace/cluster labels. Java and Go export CPU profiles; Node checkout exports wall-time and heap profiles. A CPU-only datasource shortcut will not show checkout's wall-time samples—select the wall profile type in Profiles instead.

With tracing and profiling enabled, all five backend services attach trace/span IDs to profile samples and `pyroscope.profile.id` to sampled **local entry spans**. Child work is attributed to that service-entry span, not separately to every internal span. Java/Go use CPU samples; checkout uses wall-time samples with async-context isolation. Heap profiles are not span-attributed. IDs are sample metadata, never Prometheus labels.

For an exact match, find a sampled span exemplar, open its trace in Tempo, and query Profiles with that span ID:

```sh
gcx --context demo-cloud profiles exemplars span -d grafanacloud-profiles \
  '{service_name="grot-ui",cluster="customer-demo"}' \
  --profile-type process_cpu:cpu:nanoseconds:cpu:nanoseconds --since 30m

gcx --context demo-cloud profiles query -d grafanacloud-profiles \
  '{service_name="grot-ui",cluster="customer-demo"}' \
  --profile-type process_cpu:cpu:nanoseconds:cpu:nanoseconds \
  --span-id SPAN_ID --since 30m
```

For checkout, select `wall:wall:nanoseconds:wall:nanoseconds`. Very short requests can finish between sampling intervals: a span attribute alone does not prove samples exist. A nonempty span-filtered profile, matched to the same Tempo span, establishes attribution. The normal verification helper checks indexed profile presence, not this exact-span join.

Do not change a shared datasource's default profile type just to accommodate one service without considering other applications.

## Optional AI chat

See [Optional AI chat](../docs/optional-ai-chat.md) for UI-role credentials, model selection and Agent Observability configuration. Normal launch prompts remain focused on telemetry.

## Security

- Use synthetic customer/payment data only. Storage is in-memory; this is not a production payment system.
- Host, Docker-daemon and cluster administrators can access runtime credentials. Protect host swap and VM snapshots as well as files.
- Kubernetes Secret base64 is not encryption. Configure at-rest encryption, backup protection, restricted Secret/pod-exec/pod-creation permissions and scoped, short-lived tokens.
- Put public demos behind access control, especially when paid chat is enabled.
- Keep credentials and private ingestion URLs out of Git, image layers, Helm values and command arguments.
- The launcher does not adopt installations without an ownership record. Legacy plaintext profiles are not read or automatically removed.

For test commands and the deliberate regression scenario, see [maintainer tests](../tests/local/README.md).

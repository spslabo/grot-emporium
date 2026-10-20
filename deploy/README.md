# Deployment guide

**The telemetry destination is Grafana Cloud.** Docker and Kubernetes are the application runtimes. Cloud applications such as Application Observability, Frontend Observability, Database Observability and Agent Observability require the corresponding products and permissions in your stack.

## Connection settings

Copy ingestion settings from your Grafana Cloud connection pages. Use each signal's **ingestion username**, not your Grafana login or an assumed shared stack ID.

The Docker and Kubernetes quick launchers prompt for:

| Input | Required value |
|---|---|
| OTLP (Traces) endpoint + username | HTTPS ingestion URL with path `/otlp`; not the Tempo query URL or `/otlp/v1/traces` |
| Metrics endpoint + username | HTTPS remote-write URL with path `/api/prom/push`; `/api/prom` alone is not sufficient |
| Logs endpoint + username | Full Loki push URL ending in `/loki/api/v1/push` |
| Profiles endpoint + username | HTTPS Pyroscope ingestion origin, with no path (or just `/`); do not append `/ingest` |
| Shared ingestion API token | Stack-scoped access-policy token with `traces:write`, `metrics:write`, `logs:write`, `profiles:write` |
| Optional Faro URL | Complete HTTPS collector URL with `/collect/<application-key>`; blank disables browser export |

Each hidden input is format-validated immediately: service-specific path, HTTPS, hostname/port syntax, absence of URL credentials/query/fragment, and nonempty whitespace-free ingestion usernames/tokens. Direct Grafana Cloud hostnames must match the selected ingestion service. JSON input and externally managed Secrets use the same field checks; duplicate JSON keys are rejected. Invalid entries are re-prompted without losing earlier answers held in memory. Format validation does not authenticate credentials or prove delivery; use the verification commands below.

For Faro, allow the storefront origin and the browser probe origin in the application:

- Docker: `http://localhost:8080` (or your chosen storefront port), plus `http://gateway:8080`.
- Kubernetes: your storefront origin, plus `http://grot-gateway`.

The browser sends telemetry to the same-origin `/telemetry` proxy. The upstream collector URL stays server-side. Do not disable browser security.

For separate per-signal tokens or optional UI settings, use `--settings-stdin`. It accepts JSON grouped by `alloy`, `gateway`, and optional `backend`/`ui`/`database` roles, with string values matching `scripts/grot_config.py`. Stream the object from your credential tool; do not put credentials in command arguments, shell history or the repository. Internal backend/UI defaults are generated automatically.

## Docker

Requires Python 3, Docker Compose **2.30+**, and approximately 8 GiB available for services and browser probes. Run from the checkout on the Docker host.

```sh
./grot docker customer-demo
./grot verify customer-demo --grafana-context demo-cloud
./grot stop customer-demo
```

The launcher builds the five app images and starts PostgreSQL for orders, Alloy with Database Observability, the app and the gateway. Database credentials are generated automatically. See [database setup and demo guide](../docs/database-observability.md). Open `http://localhost:8080`. Use `--port`, `--collector-port` and `--syslog-port` to choose distinct loopback ports for concurrent demos.

Credentials are passed through stdin into role-specific tmpfs volumes inside the Docker engine. Consumers mount their role files read-only. Credentials are not stored in Docker's configured environment or image layers. The trusted, network-disabled staging container keeps these volumes mounted.

Only ports, a destination fingerprint and Faro enablement are saved under `~/.local/state/grot-emporium/<alias>/`. Supply credentials again after teardown or loss of runtime storage. `stop` removes this project's workloads, credential volumes and telemetry buffers, not other projects.

A failed launch attempts to stop workloads and clear runtime credentials, retaining destination-bound buffers for retry. Use `stop` to discard a failed deployment completely. Cleanup requires a reachable Docker daemon.

Token rotation for the same destination is supported by relaunching. Endpoint/ingestion-user changes are rejected while an alias has buffered data; stop and clean up before reusing it for another destination.

Use the launcher rather than running `compose.yaml` alone: PostgreSQL now requires privately staged database/application credentials. The isolated legacy in-memory test fixture remains available under `tests/local/`.

**Order data is disposable:** Docker relaunch resets PostgreSQL; Kubernetes database pod replacement resets it. Restarting only the orders application retains rows. Long-term mode manages credentials, not durable storage.

## Kubernetes quick

Requires Python 3, Helm 3/4, an existing cluster and published Grot images. **First follow [cluster connection and image selection](../README.md#kubernetes-quick--including-k3s)** to set `CONTEXT`, `IMAGE_PREFIX` and `VERSION`.

kubectl normally uses `~/.kube/config`; set `KUBECONFIG` only for a separate connection file supplied by your cluster administrator/provider. List connection names with `kubectl config get-contexts`. No Grot-specific kubeconfig path is required. Keep the same terminal for subsequent commands.

Your cluster identity needs permission to manage the dedicated namespace's workloads, RBAC and Secrets. The launcher does not provision infrastructure.

```sh
./grot k8s customer-demo --mode quick --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

`customer-demo` is the **destination alias**, `$CONTEXT` selects the **cluster connection**, and the **namespace** defaults to `grot-customer-demo`. Use `--namespace` to override it. Quick mode can create the namespace if permitted. Settings go directly to demo-owned Secrets. The installer prints each phase and exact verify/access/stop commands when ready.

After deployment, the script automatically verifies shopping, browser, telemetry transport and database collection. Failure stops the sequence before browser access. On success, interactive deployment starts a loopback-only tunnel, prints the summary and URL, and opens **http://localhost:8080**. Leave the terminal running while browsing; Ctrl+C closes the tunnel, not Grot. Use `--no-open` to skip this or `--port PORT` to change the local port. Noninteractive/`--settings-stdin` deployments skip browser startup.

To reopen an existing deployment (no reinstall):

```sh
./grot open customer-demo --context "$CONTEXT"
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
| `grot-database-runtime` | Distinct `POSTGRES_PASSWORD`, `GROT_DB_APP_PASSWORD`, `GROT_DB_MONITOR_PASSWORD`; 32–128 URL-safe characters each |

Keys follow the role schema in `scripts/grot_config.py`. Backend tracing/profiling must be enabled against `http://alloy:4318` and `http://alloy:4040`. UI Faro uses `/telemetry` when a gateway destination is supplied. Backend and collector environment identities must match. Set `GROT_CLUSTER` to your cluster identity when correlating with infrastructure telemetry.

```sh
./grot k8s customer-demo --mode long-term --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

This mode validates existing app Secrets in memory without modifying them. Default infrastructure installation needs cluster-wide permissions. With `--skip-k8s-monitoring`, app installation requires only namespaced permissions. The charts use native Secret references, not CSI-only mounts. [External Secret references](external-secrets.example.yaml) are provided for teams using an existing controller; installing a secret manager is outside this repository.

Database passwords must be coordinated with PostgreSQL roles; Secret edits alone do not rotate database passwords. See [database credential lifecycle](../docs/database-observability.md).

After ingestion-token rotation, rerun the installer to restart environment-based consumers, or use your approved restart controller. Changing destination endpoints/user IDs requires a separate deployment namespace. Verify/stop commands are the same as quick mode; long-term stop never deletes external Secrets. Clean up before changing an installation's mode.

## Demo traffic

Use [the traffic presets and commands](../README.md#continuous-demo-traffic) after deployment. k6 executes inside the selected Compose network or app namespace and streams results to **Cloud k6** via `k6 cloud run --local-execution`; no public app endpoint is needed. Supply `--grafana-context CONTEXT` and, if needed, `--k6-project ID`. Existing gcx authentication supplies a k6-specific token, not the app's metrics/Loki token. Kubernetes stores it in the owned `grot-demo-traffic-cloud` Secret; Docker writes it through stdin into container tmpfs. Tokens are never literal command arguments, Job environment values, script ConfigMaps or host profiles. Test archives and Cloud-secret fetching are disabled; results and test logs are uploaded. Startup verifies the run in the selected project's Cloud history and prints its URL. Cloud limits/billing apply even with local execution; credentials must remain valid for the run.

Each run is finite; changing presets requires stop/start. On Kubernetes, `--repeat` creates a CronJob that checks each minute and starts another bounded run after the previous completes (`concurrencyPolicy: Forbid`, no overlap). It continues until explicitly stopped; owned credentials are retained between runs. A detected initial startup/Cloud-registration failure suspends the schedule for inspection. `grot stop` also removes the traffic runner and its owned Cloud credential Secret. Kubernetes Job logs expire one hour after completion; explicit traffic stop removes local logs immediately but does not delete Cloud test history. Use `--local-only` explicitly for offline/logs-only testing.

## Infrastructure monitoring

**Kubernetes:** both launch modes install Grafana Kubernetes Monitoring chart **4.5.3**, in a separate `grot-monitoring` namespace. It collects cluster/workload state, kubelet/cAdvisor metrics, Linux node metrics and Kubernetes events. No second cAdvisor is deployed. The chart's Alloy operator is restricted to its own namespace. It reuses metrics/Loki credentials via a separate owned Secret—never plaintext Helm values—and keeps app metrics/logs/traces/profiles with the existing Grot Alloy.

If Kubernetes Monitoring already exists, the installer refuses duplication; rerun with `--skip-k8s-monitoring` to leave existing monitoring alone. That monitoring must send data to the intended stack. Changing a Grot-managed infrastructure destination/cluster label is rejected; ingestion-token rotation is supported by rerunning installation.

```sh
# Add infrastructure to an existing deployment without restarting the app:
./grot infrastructure customer-demo --context "$CONTEXT" --verbose
# Optional read/query authentication to confirm infrastructure indexing too:
./grot infrastructure customer-demo --context "$CONTEXT" --grafana-context demo-cloud
# App stop preserves cluster-wide monitoring. Remove it explicitly:
./grot infrastructure customer-demo --context "$CONTEXT" --remove
```

Removal deletes only the Grot-owned monitoring release and credentials. The namespace/shared CRDs remain. Use the original app namespace for removal; add `--namespace` if it was customized. Existing externally managed monitoring is never removed.

**Docker / Linux VM:** cAdvisor **0.60.6** and node exporter **1.10.2** start with Grot. Alloy scrapes container CPU/memory/I/O plus Linux host CPU/memory/disk/filesystem metrics using the existing metrics destination. Container forwarding is restricted to this Compose project. No exporter host ports are published. Docker Desktop reports its Linux VM, not the macOS/Windows host. Host network-namespace metrics are deliberately not enabled. Rootful Linux Docker is the supported VM path; bare-VM binaries and rootless Docker are not covered. For nonstandard containerd installations, set `GROT_CONTAINERD_SOCKET` to the socket path as seen under cAdvisor's `/rootfs` host mount.

**Privileges:** cAdvisor is privileged and mounts the host filesystem/cgroups and Docker socket. A read-only socket mount does **not** make the Docker API read-only. Node exporter mounts host files read-only and uses host PID visibility. Neither receives ingestion credentials. Only run this on a host where that access is authorized. `grot stop` removes both Docker exporters.

**Verify:** Kubernetes infrastructure installation checks cAdvisor/state/node discovery and metrics/event destination acknowledgements. `--grafana-context` additionally checks indexed node/workload inventory, orders-container CPU, host CPU and events. Docker verification checks actual container/host samples, not just HTTP readiness. In Grafana Kubernetes Monitoring, select the `GROT_CLUSTER` label (normally your deployment alias). Confirm `kube_pod_info`, `container_cpu_usage_seconds_total`, `node_cpu_seconds_total` and Kubernetes events. Cluster monitoring needs time to scrape and index; healthy pods alone do not prove Cloud visibility.

### Images and networking

Run the **Publish Grot images** workflow, or push an approved `grot-v*` release tag, to publish amd64/arm64 images to your fork's GHCR namespace, tagged with the commit SHA. Set `IMAGE_PREFIX` and `VERSION` to those published images. For private registries, use `--pull-secret EXISTING_SECRET_NAME` or your cluster's native credential provider.

The app telemetry chart uses namespace-scoped pod/log RBAC and collector ingress NetworkPolicy. The separate Kubernetes Monitoring chart uses cluster-wide discovery/exporters and CRDs. Neither installation creates public ingress or a load balancer; infrastructure collectors require cluster RBAC and node-exporter host mounts. Your CNI must enforce NetworkPolicy; the chart does not provide an egress allow-list. Kubernetes collector buffers are ephemeral and may lose queued telemetry on restart.

## Verification and limits

Kubernetes installation automatically runs local verification. `grot verify` reruns checks; `grot verify-cloud` optionally checks Cloud indexing. These checks are not ingestion components or substitutes for inspecting the Cloud product views. They run fixed HTTP/browser tests, counter comparisons and datasource queries. They do not use AI, require model credentials, invoke chat or call a model API.

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
| PostgreSQL collection | Reachable database, successful statement scraping, query counters and DB O11y connection information |
| gcx queries | Current successful scrapes, recent trace matches and nonempty indexed profiles for all five services; recent deployment logs; PostgreSQL health/query metrics and query-association logs |

Progress is printed per probe and signal. Private subprocess/query output is suppressed. Tests use synthetic data and do not call models. Without `--grafana-context`, verification is transport-only. With it, the Cloud stage also runs after a local-stage failure; either failure makes the combined command fail.

Cloud checks select the standard Cloud datasources, or a unique datasource of each required type. Ambiguous alternatives are rejected. Logs/traces/profiles use a 15-minute window; retry after indexing delays. Quiet services are reported separately rather than treated as failed log ingestion. Metrics/logs/profiles are scoped by cluster label. Traces match the Grot service namespace and service, so they are not deployment-unique when several deployments share that namespace.

Recent indexed presence is not exact probe correlation, complete trace parenting, per-span profile linking, Faro indexing or App Observability readiness. Those require separate checks in the Cloud applications. Hosted response integrations require separate validation.

### Verify independently

You can skip the helper and use Grafana Explore, Cloud applications, direct gcx commands or your own tests. Generate shopping traffic and inspect a matching recent time range:

- **Metrics:** query `up{service_namespace="grot-emporium",cluster="customer-demo"}` and inspect application request counters/histograms.
- **Logs:** query `{service_namespace="grot-emporium",cluster="customer-demo"}` and inspect timestamps and service labels.
- **Traces:** query `{resource.service.namespace="grot-emporium"}` in Tempo, then inspect a shopping trace's services and parent/child spans. Narrow the query when multiple deployments share this namespace.
- **Profiles:** select the Grot services and deployment labels in Profiles and inspect nonempty samples.
- **Database telemetry:** check Database Observability's Telemetry status and Queries overview; see [DB O11y guide](../docs/database-observability.md) for queries, privacy, permissions and limits.
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

- Use synthetic customer/payment data only. Orders use disposable PostgreSQL storage; other services retain their existing lightweight storage. This is not a production payment system.
- Host, Docker-daemon and cluster administrators can access runtime credentials. Protect host swap and VM snapshots as well as files.
- Kubernetes Secret base64 is not encryption. Configure at-rest encryption, backup protection, restricted Secret/pod-exec/pod-creation permissions and scoped, short-lived tokens.
- Put public demos behind access control, especially when paid chat is enabled.
- Keep credentials and private ingestion URLs out of Git, image layers, Helm values and command arguments.
- The launcher does not adopt installations without an ownership record. Legacy plaintext profiles are not read or automatically removed.

For test commands and the deliberate regression scenario, see [maintainer tests](../tests/local/README.md).

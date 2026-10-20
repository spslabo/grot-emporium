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

Kubernetes installation runs local verification automatically; standalone verification and Cloud queries use fixed checks, with **no AI/model dependency, model credentials or model calls**. You can verify ingestion independently in Grafana Explore, the Cloud applications, or with your own queries and tooling. See [verification and limits](deploy/README.md#verification-and-limits).

Add **`--verbose`** (or `-v`) to any command to see validation, command activity and timings throughout—not just during waits. Credentials and captured command output remain hidden.

## Docker

```sh
./grot docker customer-demo
./grot verify customer-demo --grafana-context demo-cloud
./grot stop customer-demo
```

Open `http://localhost:8080`. Docker includes **cAdvisor container metrics and Linux host CPU/memory/disk metrics**, scraped by Alloy. On a VM these describe the Linux VM; on Docker Desktop they describe Docker's Linux VM, not macOS/Windows. cAdvisor needs privileged host/socket access. Hidden prompts collect ingestion settings. Credentials are held in memory-backed runtime files, not host profiles or image layers. Stop removes this demo's containers, credentials and telemetry buffers.

## Kubernetes quick — including k3s

Requires an existing cluster, kubectl, Helm 3/4 and published Grot images. Run from this repository. **Kubernetes Monitoring is included by default** (cluster/workload/node metrics, kubelet cAdvisor and events); installation requires cluster-admin-level permissions. If monitoring already exists, add `--skip-k8s-monitoring` to avoid a duplicate.

**Choose your cluster:** kubectl normally reads `~/.kube/config`. If your administrator/provider supplied a separate connection file, select it first:

```sh
# Only for a separate connection file; replace this path with yours:
export KUBECONFIG="/path/to/your/kubeconfig"
```

```sh
kubectl config get-contexts
export CONTEXT="name-from-the-NAME-column"
kubectl --context "$CONTEXT" get namespaces
```

If no contexts appear, obtain cluster access from your administrator/provider. For an expired AWS SSO session, run `aws sso login --profile YOUR_PROFILE`. Keep the same terminal for deployment and verification.

**Choose your images:** find the repository and tag in your fork's GitHub **Packages**, or the successful **Publish Grot images** workflow run. All five app images must have the same tag. The prefix excludes the service name; the version is the published commit SHA. These are not credentials.

```sh
export IMAGE_PREFIX="ghcr.io/YOUR_OWNER/grot-emporium"
export VERSION="PUBLISHED_COMMIT_SHA"

./grot k8s customer-demo --mode quick --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
./grot verify customer-demo --context "$CONTEXT" --namespace grot-customer-demo
./grot open customer-demo --context "$CONTEXT"  # Reopen browser access later
./grot stop customer-demo --context "$CONTEXT" --namespace grot-customer-demo
```

Kubernetes deployment prints progress, then **automatically verifies shopping, browser, telemetry transport and database collection**. If verification fails, it stops before browser access. On success, interactive deployment starts a local tunnel, prints the deployment summary and URL, and opens **http://localhost:8080**. Keep the terminal running while browsing; **Ctrl+C closes only the tunnel**. Then run verify/stop, or use another terminal with the same `KUBECONFIG`. Use `--no-open` to skip browser access or `--port 8081` to choose another local port (also allow that origin in Faro). Noninteractive/`--settings-stdin` deployments don't open a tunnel.

`customer-demo` is your deployment alias (**destination**), not a URL. The **context** selects the cluster connection; the **namespace** defaults to `grot-<destination>`. The launcher prompts for telemetry settings, prints progress and exact verify/access/stop commands. Add `--grafana-context demo-cloud` to verification for optional Cloud indexing checks.

For Frontend Observability, allow `http://localhost:8080` and `http://grot-gateway` in your Faro application, then paste its collector URL into the script's Faro prompt. See [endpoint formats](deploy/README.md#connection-settings). Cleanup retains the namespace and externally managed Secrets.

Complete the Kubernetes Monitoring app's **recording/alert-rule installation once per Grafana Cloud stack**; Helm installs collectors, not those Cloud-side rules. Data and product views may take a few minutes to populate.

Shared monitoring lives in `grot-monitoring` and survives app teardown. Add it to an already-running Grot without redeploying the app:

```sh
./grot infrastructure customer-demo --context "$CONTEXT"
# Explicitly remove shared monitoring when finished:
./grot infrastructure customer-demo --context "$CONTEXT" --remove
```

## Kubernetes long-term

Supply the five runtime Secrets (including database credentials) through your team's secret-management tooling:

```sh
./grot k8s customer-demo --mode long-term --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

Uses the same charts without modifying or deleting external Secrets. See the [deployment guide](deploy/README.md) for Secret keys, image publication, browser access, rotation and cleanup.

## Continuous demo traffic

k6 is bundled. Deployment verification is brief; **start sustained traffic explicitly** to keep app/DB telemetry and Faro active:

```sh
./grot traffic customer-demo start --context "$CONTEXT" --grafana-context demo-cloud --preset low --duration 1h
./grot traffic customer-demo status --context "$CONTEXT"
./grot traffic customer-demo stop --context "$CONTEXT"
# Docker / Linux VM: omit --context.
```

| Preset | Shopping journeys/min | Real browser journeys/min |
|---|---:|---:|
| low (default) | 6 | 1 |
| medium | 30 | 2 |
| high (opt-in) | 120 | 4 |

Each journey browses products, uses the cart and creates a synthetic order—**these are journeys, not requests/second**. Override with `--rate 15 --browser-rate 2`; use `--browser-rate 0` for HTTP-only traffic (no browser-generated Faro). Stop before changing settings. Runs are bounded (default 1h, launcher maximum 24h; Cloud project limits may be lower); app teardown also stops the runner. Startup prints the k6 logs command; final thresholds report failures/dropped iterations. App telemetry uses existing Alloy. **k6 results stream to Grafana Cloud k6 by default**, while execution stays inside your private cluster/Compose network. Supply an authenticated `gcx` context with `--grafana-context`; select `--k6-project ID` if it has multiple projects. The launcher obtains k6-specific authentication without printing tokens, verifies Cloud registration and prints the run URL. Cloud k6 usage may be billable, including local execution. Use `--local-only` explicitly for logs-only tests. More traffic grows the disposable database.

For longer Kubernetes demos, add **`--repeat`**. A CronJob starts the next bounded run on an available minute boundary after the previous run ends (`concurrencyPolicy: Forbid`); runs never overlap. It continues until `traffic stop` or app teardown, so Cloud k6 usage/billing continues too. Docker currently supports single bounded runs only.

### Guided LLM + Agent Observability setup

For an existing Kubernetes demo with a current UI image:

```sh
./grot agento11y my-demo --context my-kube-context \
  --capture-content --verify --allow-paid-ai --grafana-context my-stack
```

The wizard configures Bedrock/OpenAI, collects missing keys privately, configures content capture and labels, rolls UI, and optionally verifies one chat in Cloud. Existing credentials are reused. `--capture-content` consents to exporting **all demo chat content** to Agent Observability (not traces). Omit the last three flags to configure without a paid model request. [Provider/IAM wiring and image upgrade instructions](docs/optional-ai-chat.md#recommended-guided-kubernetes-setup).

### Optional paid chat traffic

After enabling a real chatbot provider and verifying Agent Observability ingestion, add `--chat-every 5m --chat-max-requests 60 --allow-paid-ai` to traffic start. This makes at most 60 synthetic chat requests per run, with one model request in flight at a time; the recurring-run budget resets each run. It is **off by default** and does not scale with low/medium/high presets. Prompts/responses are not printed in k6 logs; conversation IDs are logged for correlation. Model charges are separate from Cloud k6 usage. See [chat setup](docs/optional-ai-chat.md).

For occasional **labelled conversation failures**, enable `GROT_CHAT_SYNTHETIC_FAULTS_ENABLED=true` in the UI role and use `--chat-error-every 10`. An updated UI image is required. Every tenth synthetic request returns HTTP 503 and exports an errored generation/trace without calling Bedrock; normal chats are unchanged. These expected 503s pass the k6 fault check and increment `chat_injected_errors`; unexpected failures still fail checks. The header is a private-demo facility, not authentication.

### Optional synthetic failures

After deploying the **updated catalog image**, add `--failures` to traffic start:

```sh
./grot traffic customer-demo start --context "$CONTEXT" --grafana-context demo-cloud \
  --preset low --duration 1h --failures
# Optional: --error-percent 1 --slow-percent 5 --delay-ms 2000 --fault-rate 60
```

This adds **60 catalog probes/minute**, with 1% real HTTP 500s and 5% server-side 2-second delays, distributed over each 100 probes. Percentages apply to these probes, **not all shopping requests**. Normal shopping/browser journeys remain unchanged. Logs/spans are labeled synthetic; k6 separates expected injected failures from unexpected failures. Old catalog images are rejected by a capability check. Faults are request-local: stopping traffic leaves no fault settings behind; no pods, database connections or health checks are disabled. Stop the existing traffic run before changing settings. Defaults remain healthy.

## Features and configuration

- Prometheus metrics, correlated logs, OTLP traces, Java/Go/Node profiles and Faro browser telemetry.
- Kubernetes Monitoring on Kubernetes; cAdvisor + Linux host metrics on Docker/VMs. Existing ingestion credentials are reused.
- **PostgreSQL orders database and [Database Observability](docs/database-observability.md) enabled by default**: database health, query performance, query details, schema and available plans/wait samples.
- [Optional AI shopping assistant and Agent Observability](docs/optional-ai-chat.md).
- [Verification and Cloud query checks](deploy/README.md#verification-and-limits).
- [Maintainer tests and deliberate failure scenario](tests/local/README.md).

**Synthetic data only.** Orders use disposable PostgreSQL storage; other services retain lightweight storage. Database recreation resets orders; even Kubernetes long-term credential mode is not durable database storage. No real payments are processed. Model calls require explicit configuration. Automation routing is plan-only; launch commands do not post tickets, page production teams, merge PRs or deploy fixes.

Host/Docker/cluster administrators can access runtime credentials. Protect host swap/snapshots, and configure Kubernetes Secret encryption and access controls as described in the deployment guide.

Original [upstream documentation](README.upstream.md), attribution and [license](LICENSE) are retained.

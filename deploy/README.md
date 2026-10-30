# Deployment reference

[Quick start](../README.md) · [Load testing](../docs/demo-traffic.md) · [AI chat](../docs/optional-ai-chat.md)

## Connection settings

Copy these values from your Grafana Cloud stack's connection pages. Enter them when the launcher prompts.

| Setting | Value |
|---|---|
| Traces endpoint + username | HTTPS ingestion URL ending in `/otlp` |
| Metrics endpoint + username | HTTPS remote-write URL ending in `/api/prom/push` |
| Logs endpoint + username | HTTPS URL ending in `/loki/api/v1/push` |
| Profiles endpoint + username | HTTPS Pyroscope ingestion URL, without `/ingest` |
| Ingestion token | Access-policy token with `traces:write`, `metrics:write`, `logs:write`, `profiles:write` |
| Faro URL, optional | Full HTTPS URL containing `/collect/<application-key>` |

Use each signal's ingestion username, not your Grafana login.

For Faro, allow these origins in your Frontend Observability application:

- Docker: `http://localhost:8080` and `http://gateway:8080`.
- Kubernetes: `http://localhost:8080` and `http://grot-gateway`.
- If you change the browser port, update the localhost origin too.

For noninteractive setup, use `--settings-stdin` with role-grouped JSON from your credential manager. [Secret examples](external-secrets.example.yaml).

## Docker

Requires Python 3, Docker Compose 2.30+ and approximately 8 GiB available memory.

```sh
./grot docker my-demo
./grot stop my-demo
```

| Option | Purpose |
|---|---|
| `--port 8081` | Change the browser port |
| `--collector-port 12346 --syslog-port 15141` | Avoid port conflicts with another demo |
| `--host-id demo-host-01` | Override Docker host identity; use one stable actual-machine ID when multiple Docker engines share a host |
| `--no-demo-traffic` | Disable automatic shopping/browser activity |
| `--verbose` | Show deployment progress details |

- Rerun the launcher to update ingestion tokens.
- Use a new demo name when changing Grafana destinations.
- Docker relaunch resets order data.
- Docker and Kubernetes attach application host/instance identity automatically. Identified hosts can count toward **Application Observability host-hours billing**; see [identity and correlation](../docs/application-observability.md).

## Kubernetes quick

Set `CONTEXT`, `IMAGE_PREFIX` and `VERSION` using the [quick start](../README.md#kubernetes-quick--including-k3s).

```sh
./grot k8s my-demo --mode quick --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
./grot open my-demo --context "$CONTEXT"
./grot stop my-demo --context "$CONTEXT"
```

| Option | Purpose |
|---|---|
| `--namespace NAME` | Override the default `grot-my-demo` namespace |
| `--skip-k8s-monitoring` | Reuse existing cluster monitoring |
| `--no-open` | Deploy without opening the browser tunnel |
| `--port 8081` | Change the local browser port |
| `--no-demo-traffic` | Disable automatic shopping/browser activity |
| `--pull-secret NAME` | Use an existing registry credential Secret |

Keep the browser tunnel terminal open. Ctrl+C closes the tunnel, not the app.

### Cluster connection commands

**Kind:** install [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation), start Docker, then:

```sh
kind create cluster --name grot-demo
kubectl --context kind-grot-demo get namespaces
```

Kind creates the cluster and writes `~/.kube/config`.

**Existing AWS EKS cluster:** install the AWS CLI. For SSO, obtain your organization's SSO settings and run:

```sh
aws configure sso --profile demo
aws sso login --profile demo
aws eks list-clusters --profile demo --region YOUR_REGION
aws eks update-kubeconfig --profile demo --region YOUR_REGION --name YOUR_CLUSTER_NAME
kubectl get namespaces
```

Use the cluster's region and a name from `list-clusters`. `update-kubeconfig` writes the connection file; it does not create the cluster. Ask the administrator for access if permission is denied.

**Existing k3s server:** k3s creates `/etc/rancher/k3s/k3s.yaml`. On that server:

```sh
mkdir -p "$HOME/.kube"
sudo install -m 600 -o "$(id -u)" /etc/rancher/k3s/k3s.yaml "$HOME/.kube/grot-k3s.yaml"
export KUBECONFIG="$HOME/.kube/grot-k3s.yaml"
kubectl get namespaces
```

From another computer, obtain a kubeconfig from the administrator with a reachable server address and valid TLS certificate.

## Kubernetes long-term

Create the namespace and these Secrets using your secret manager:

| Secret | Contents |
|---|---|
| `grot-backend-runtime` | Internal telemetry receiver settings |
| `grot-ui-runtime` | Browser telemetry and optional AI settings |
| `grot-collector-runtime` | Grafana ingestion endpoints, usernames and tokens |
| `grot-gateway-runtime` | `GRAFANA_FARO_URL`; empty to disable Faro |
| `grot-database-runtime` | `POSTGRES_PASSWORD`, `GROT_DB_APP_PASSWORD`, `GROT_DB_MONITOR_PASSWORD` |

[Secret examples](external-secrets.example.yaml) · [Database credential requirements](../docs/database-observability.md#credentials)

```sh
./grot k8s my-demo --mode long-term --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

- External Secrets are retained on removal.
- Rerun after ingestion-token rotation.
- Database password changes also require PostgreSQL role updates.
- **Long-term mode does not make the database persistent.**

## Demo traffic

Shopping/browser traffic starts automatically. No extra command is required.

Optional load tests:

| Test | What it does |
|---|---|
| Shopping + browser | Browse products, update carts, place synthetic orders |
| HTTP-only | Shopping without browser sessions |
| Catalog faults | Inject request-scoped HTTP 500s and delays |
| AI chat | Send model requests; explicit paid opt-in required |

[Commands, rates and duration options](../docs/demo-traffic.md#optional-load-testing).

## Infrastructure monitoring

- Kubernetes monitoring is installed by default; requires cluster-admin access.
- Already installed? Add `--skip-k8s-monitoring`.
- Complete the Kubernetes Monitoring app's recording/alert-rule setup once per Grafana Cloud stack.
- Docker includes host/container monitoring. On Docker Desktop, host metrics describe its Linux VM.
- Docker monitoring requires privileged host and Docker-socket access.

App removal retains shared Kubernetes monitoring. Remove it separately:

```sh
./grot infrastructure my-demo --context "$CONTEXT" --remove
```

### Images and networking

- Run **Actions → Publish Grot images** in your repository.
- After success, copy the exports from **Summary → Kubernetes deployment settings**.
- For public images, set all five packages to **Public** in GitHub Package settings.
- For private images, create an image-pull Secret in the app namespace and pass `--pull-secret NAME`.
- No public ingress is created. Browser access uses a local tunnel.

## Verification and limits

Kubernetes checks the deployment automatically. To recheck it:

```sh
./grot verify my-demo --context "$CONTEXT"
```

For Grafana Cloud checks, install [gcx](https://github.com/grafana/gcx):

```sh
gcx login demo-cloud
./grot verify-cloud my-demo --grafana-context demo-cloud
```

- `--context` selects Kubernetes; `--grafana-context` selects Grafana Cloud.
- For Docker, omit `--context`.
- Allow a few minutes for Cloud indexing.
- These commands make no model calls.

### Verify independently

| Data | Where to look in Grafana Cloud |
|---|---|
| Application metrics, logs, traces | Application Observability / Explore |
| Browser sessions and errors | Frontend Observability |
| Database health and queries | Database Observability |
| CPU / wall-time profiles | Profiles; choose wall-time for Node checkout |
| Pods, nodes and events | Kubernetes Monitoring |

Select the deployment's cluster label, normally `my-demo`.

## Security

- Use synthetic data only. Database recreation deletes orders.
- Keep tokens and kubeconfigs out of Git and command arguments.
- Restrict host/cluster administrator access and enable Kubernetes Secret encryption.
- Protect public access, especially when paid chat is enabled.

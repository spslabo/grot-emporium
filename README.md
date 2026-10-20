# Grot Emporium

A demo shop with metrics, logs, traces, profiles, browser telemetry and PostgreSQL monitoring in Grafana Cloud.

**Synthetic data only. No real payments. Database data is disposable.**

**Shopping and browser traffic starts automatically with the app.** No extra script, Cloud k6 account or AI provider is needed.

## Start here

1. Clone this repository (or your fork) and open a terminal in its directory.
2. Install **Python 3** and **Docker with Compose 2.30+**. Start Docker.
3. Have a **Grafana Cloud stack** ready. The launcher prompts for its telemetry endpoints and ingestion credentials. [Where to find these settings](deploy/README.md#connection-settings).
4. Choose **Docker** for the simplest setup, or **Kubernetes** below.

## Docker — quickest option

Docker builds the app locally. No Kubernetes cluster, kubeconfig or image registry is needed.

```sh
./grot docker my-demo
```

- Answer the setup prompts. Credentials are entered privately.
- Open **http://localhost:8080**.
- Stop and remove the demo:

```sh
./grot stop my-demo
```

## Kubernetes quick — including k3s

Also install **kubectl** and **Helm 3/4**. Cluster-admin access is needed for the included Kubernetes Monitoring installation.

### 1. Connect to a cluster

**A kubeconfig is a connection file:** it tells kubectl where your cluster is and how to authenticate. **Grot does not create it.** Your cluster setup tool creates it, or your administrator supplies it.

Choose one:

- **Already use kubectl?** Keep your existing connection; no `KUBECONFIG` export is needed.
- **Need a local test cluster?** Install [Kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation), then run `kind create cluster --name grot-demo`. This creates the cluster and writes its connection to `~/.kube/config` automatically.
- **Administrator gave you a file?** Set `KUBECONFIG` to that file's actual path, for example `export KUBECONFIG="$HOME/Downloads/demo-kubeconfig.yaml"`.
- **AWS EKS or k3s?** Follow the [cluster connection commands](deploy/README.md#cluster-connection-commands).

Check and select your connection:

```sh
kubectl config get-contexts
# Select a NAME from the list above:
kubectl config use-context YOUR_CONTEXT_NAME
export CONTEXT="$(kubectl config current-context)"
kubectl --context "$CONTEXT" get namespaces
```

**Do not continue if that last command fails.** Fix cluster access first. Keep using this terminal.

### 2. Publish the app images

You need permission to run workflows in the GitHub repository; **fork it first if you do not**.

1. In that repository, open **Actions → Publish Grot images → Run workflow**.
2. Select the branch containing this setup and click **Run workflow**.
3. Wait for the **whole workflow to succeed**, including all five image builds.
4. Open the completed run's **Summary → Kubernetes deployment settings**. Copy its two `export` commands into your terminal. They contain the exact `IMAGE_PREFIX` and `VERSION`; do not invent these values.
5. Allow your cluster to pull the images: make the five demo packages public under **GitHub profile → Packages → package → Package settings**, or configure [private-registry access](deploy/README.md#images-and-networking).

For example, a fork at `github.com/alex/grot-emporium` publishes images under `ghcr.io/alex/grot-emporium`. `VERSION` identifies the exact build. **The workflow supplies both values for you.**

### 3. Deploy

```sh
./grot k8s my-demo --mode quick --context "$CONTEXT" \
  --image-prefix "$IMAGE_PREFIX" --image-tag "$VERSION"
```

- Answer the telemetry setup prompts.
- Already have Kubernetes Monitoring? Add `--skip-k8s-monitoring`.
- The launcher checks the deployment, starts a local tunnel and opens **http://localhost:8080**.
- Keep the terminal open. **Ctrl+C closes the tunnel, not the demo.**
- For Faro browser telemetry, allow `http://localhost:8080` and `http://grot-gateway` in your Grafana Faro application. Docker's automatic browser also needs `http://gateway:8080`.

### 4. Reopen or remove

```sh
# Reopen the browser tunnel:
./grot open my-demo --context "$CONTEXT"

# Remove the app and its disposable data:
./grot stop my-demo --context "$CONTEXT"

# Optional: also remove the shared monitoring installed by Grot:
./grot infrastructure my-demo --context "$CONTEXT" --remove
```

`my-demo` is a name you choose; its default namespace is `grot-my-demo`. App removal leaves shared monitoring and the namespace intact.

## Built-in demo traffic

- Starts automatically: **6 shopping journeys + 1 browser journey per minute**.
- Keeps app, database and browser telemetry active until you remove the demo.
- No model calls, injected faults or Cloud k6 runs.
- For a quiet deployment, add `--no-demo-traffic` to the launch command.
- [Optional load testing, higher rates and synthetic errors](docs/demo-traffic.md) are separate.

## More options

- [AI chat and Agent Observability](docs/optional-ai-chat.md)
- [Long-term credentials, security, verification and troubleshooting](deploy/README.md)
- [PostgreSQL and Database Observability](docs/database-observability.md)
- Add `--verbose` to a launcher command for more progress details.

Based on the [AWS retail store sample](https://github.com/aws-containers/retail-store-sample-app). [Upstream documentation](README.upstream.md) · [License](LICENSE)

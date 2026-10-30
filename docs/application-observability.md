# Application Observability

The managed `./grot docker` and `./grot k8s` deployments export application traces,
scraped runtime metrics, and host/instance identity to your configured destinations.
The telemetry-disabled Docker quickstart does not send data to Grafana Cloud.

| Deployment | Application host resource attribute | Instance identity in traces and scraped application metrics |
|---|---|---|
| Kubernetes | `k8s.node.name` from each application's `spec.nodeName` | Pod UID |
| Docker | `grafana.host.id`, defaulting to `docker-<target-engine-ID>` | Random launch ID plus service name |

Docker uses the **target engine**, including remote Docker contexts, not the CLI
machine's hostname. The host ID survives demo/container recreation; app instance
IDs change on launcher relaunch. The managed Compose deployment runs one instance
per service. Scaling it requires replica-aware discovery and identity, not reuse
of these single-instance scrape targets.

## Deploy

1. Follow the [deployment instructions](../deploy/README.md). No extra identity
   configuration is needed for the normal single-engine Docker host or Kubernetes.
2. If several Docker engines share one actual host, supply the same stable host ID
   for each engine. Reuse this override on every launch; different physical hosts
   must have different IDs:
   ```sh
   ./grot docker my-demo --host-id demo-host-01
   ```
3. In Grafana Cloud, enable Application Observability's trace-derived metrics if
   they are not already enabled. Grot does not change stack-level generation
   settings or add a second Alloy span-metrics/service-graph pipeline.
4. Check services under `grot-emporium/<service>` and the configured environment.
   Trace-generated `traces_target_info` should identify each host; its `instance`
   should match the application's scraped runtime metrics. Old instance series
   remain visible in historical time ranges after a rollout.

**Billing:** host identity enables Application Observability host-hours accounting.
The current documentation says unidentified services are excluded from host-hours
billing and show a configuration warning. Correcting an existing deployment can
therefore change its bill. Node-exporter/cAdvisor metrics alone do not identify
application hosts. See [host-hours pricing](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-applications/application-observability/pricing/).

Matching identity enables correlation; it does not translate runtime metric names
between instrumentation libraries or guarantee every optional runtime dashboard
panel is populated. See [required metrics and labels](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-applications/application-observability/setup/metrics-labels/).

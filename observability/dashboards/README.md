# Grot Emporium overview

1. Import `grot-emporium-overview.json` in Grafana.
2. Select your Prometheus, Loki, Tempo and Pyroscope datasources.
3. Select the deployment, Kubernetes namespace (if applicable), and app services.

| Section | Signals |
|---|---|
| Shopping | Accepted orders, item quantities, simulated order value |
| HTTP | Request rate, 5xx percentage, histogram p95 latency |
| PostgreSQL | Exporter reachability, commits, rollbacks, connections, JDBC pool |
| Kubernetes | Available replicas, restarts, CPU, memory, optional ephemeral storage and recurring traffic |
| AI | Model operation rate, histogram p95 latency, input/output tokens |
| Investigation | Application logs, Tempo and Pyroscope Explore links |

## Metric sources

- `src/orders/src/main/java/com/amazon/sample/orders/metrics/OrdersMetrics.java`: `grot.orders.created`, `grot.orders.items`, `grot.orders.value`. Observed Prometheus names are `grot_orders_total`, `grot_orders_items_total`, `grot_orders_value_total`.
- Spring/Micrometer HTTP metrics: `http_server_requests_seconds_*`.
- Catalog `src/catalog/telemetry.go` and checkout HTTP instrumentation: `http_server_request_duration_seconds_*`.
- `observability/components/database.alloy`: PostgreSQL exporter and Database Observability.
- Kubernetes Monitoring: kube-state-metrics and container resource metrics.
- `src/ui/src/main/java/com/amazon/sample/ui/chat/ChatTelemetry.java` and the Agent Observability SDK: `gen_ai_client_*`; scoped with `agento11y_tag_cluster` rather than the scrape `cluster` label.
- `observability/components/kubernetes.alloy`: application log labels.

## Interpretation

- Business panels cover the deployment; the service selector filters HTTP and logs. Infrastructure uses the namespace selector.
- HTTP panels exclude actuator/health/metrics routes. Deliberate fault traffic remains included. HTTP requests across services are not unique shopping journeys.
- Order values are synthetic, not revenue. Counter increases are extrapolated, not exact database counts.
- Missing optional signals stay missing; they are not converted to healthy zeroes. Docker-only deployments will not have Kubernetes panels.
- Ephemeral storage requires the independent Summary API exporter. PostgreSQL is disposable; this dashboard does not imply durable storage.
- AI token usage uses histogram sums, not observation counts. No pricing or evaluation scores are assumed. An HTTP 200 streaming response alone does not prove generation success.
- Use Frontend Observability for Faro/Web Vitals and Agent Observability for generation content/errors/evaluations; those are not fabricated as Prometheus KPIs here.

# PostgreSQL and Database Observability

## Default deployment

`grot docker` and both `grot k8s` modes now deploy PostgreSQL **17.11** for the Java **orders** service. Checkout creates real rows in `orders`, `order_items` and `shipping_addresses`; Spring Flyway creates the schema. Catalog/cart/checkout retain their lightweight existing storage. There is no database-engine selector and no RDS provisioning.

Alloy **1.20.0** runs both `prometheus.exporter.postgres` and `database_observability.postgres`. This is query-level Database Observability, not merely a PostgreSQL exporter dashboard:

- Database health, connections, database activity, locks, table and I/O statistics.
- `pg_stat_statements` query call counts and timings, plus query text associations in Loki.
- Query samples/wait events, schema details and explain-plan collection (where supported and permitted). Short queries may finish between samples; not every query will have a sample or plan.
- PostgreSQL server logs through the existing log pipeline, also supplied to the DB error collector.
- JDBC spans from the orders service's existing OpenTelemetry instrumentation. Automatic trace-to-query navigation in the Cloud UI must be verified separately; do not infer it from exporter health.

DB telemetry reuses the existing metrics/Loki destinations and credentials; no additional Cloud token or prompt is needed. Labels are `job="integrations/db-o11y"`, `service_name="grot-postgres"`, `cluster="<GROT_CLUSTER>"`, and `instance="<GROT_CLUSTER>/grot-postgres"`.

## Storage and credentials

**Disposable demo, not a production database.** Docker uses a 512 MiB tmpfs database. Kubernetes uses a size-limited emptyDir: database pod replacement deletes orders. Docker relaunch recreates the database and resets orders. An orders-service restart alone does not reset PostgreSQL. Kubernetes `--mode long-term` refers to externally managed credentials, **not durable database storage**. There are no backups, HA, PVCs or migration of earlier in-memory orders.

Quick launch generates three independent 48-character random passwords. They never enter Helm values, command arguments, images or Git:

| User | Purpose/access |
|---|---|
| `postgres` | Initialization administrator; only the database container receives it |
| `grot_orders` | Application schema owner; only orders and database initialization receive this password |
| `db-o11y` | Monitoring role (`pg_monitor`) and SELECT on application-created tables; no superuser, CREATE or DML grants |

Docker stages separate server/application/monitoring tmpfs volumes. Orders cannot mount admin/monitor credentials; Alloy cannot mount admin/application credentials. Kubernetes uses individual Secret key references for orders/Alloy and the full database Secret only for initialization. Existing quick-mode database credentials are reused on Kubernetes upgrades, not silently rotated.

Long-term Kubernetes requires the additional externally managed Secret **`grot-database-runtime`** with `POSTGRES_PASSWORD`, `GROT_DB_APP_PASSWORD`, `GROT_DB_MONITOR_PASSWORD`. Values must be distinct, 32–128 characters, using only letters, digits, `_` or `-`; this avoids ambiguous DSN escaping. Missing/invalid keys fail before Helm installation. Generate them through your secret manager. `scripts/grot_config.py init` also creates an owner-only `database.env` outside the repository for manual provisioning; protect and delete it appropriately. Do not paste it into chat or command arguments.

Changing this Secret alone does not change PostgreSQL roles. Coordinate password changes with database role changes and consumer restarts, or explicitly reset this disposable database. The launcher does not perform automatic role-password rotation.

No database port is published to the Docker host, and Kubernetes uses ClusterIP only. The database NetworkPolicy allows only same-namespace orders and Alloy pods; the CNI must enforce it. Internal demo database traffic uses `sslmode=disable`. For a real database use verified TLS (`verify-full` and a trusted CA), private networking, restricted database access, persistent storage, backups, patching and managed rotation. Do not expose this demo PostgreSQL publicly.

## What is collected and privacy

Initialization enables `pg_stat_statements`, `compute_query_id`, query tracking, and a 4096-byte activity-query buffer. Setup statements and the monitoring user's queries are excluded from statement tracking. Future tables created by `grot_orders` automatically grant SELECT to the monitor, avoiding broad access to unrelated databases.

Query sample redaction remains enabled. Raw SQL statement logging is disabled, and failing statements/parameters are not appended to server error logs. Per-query error association is consequently not enabled; global server-error collection remains available. SQL normalization is not a universal PII guarantee: schema names, identifiers, comments and error messages may still contain sensitive information. Use **synthetic data only**. Explain/schema collection requires read access; don't broaden privileges merely to obtain a plan for every write query.

## Verify and demonstrate

1. Launch normally; PostgreSQL and DB O11y are included automatically.
2. Complete several storefront checkouts, or run `./grot verify <alias>` (with Kubernetes context flags where needed).
3. The local verifier checks `pg_up`, successful statement scraping, nonempty query counters and DB O11y connection information. This proves collection, not Cloud indexing.
4. Run `./grot verify-cloud <alias> --grafana-context <explicit-context>` for read-only Cloud checks of PostgreSQL health, query metrics and query-association logs, alongside the application signals.
5. In Grafana Cloud, open **Database Observability → Configuration → Telemetry status**. Select `<GROT_CLUSTER>/grot-postgres`. Check required telemetry, then open **Queries overview** and inspect call counts, latency, query details and available plans/wait samples. Allow several minutes and keep shopping traffic running.
6. Open an orders trace in Application Observability/Tempo and inspect its PostgreSQL JDBC spans. Compare the query, database and time window with DB O11y. Validate any automatic navigation links before demonstrating them.

Useful independent queries (replace the cluster label):

```promql
pg_up{job="integrations/db-o11y",cluster="customer-demo"}
sum(rate(pg_stat_statements_calls_total{job="integrations/db-o11y",cluster="customer-demo"}[5m]))
pg_stat_database_numbackends{job="integrations/db-o11y",cluster="customer-demo",datname="orders"}
```

```logql
{job="integrations/db-o11y",cluster="customer-demo"} |= "query_association"
{service_name="grot-postgres",cluster="customer-demo"}
```

The Cloud product must be available to your stack/user. This deployment sends the required data; it does not enable product entitlements or install a second collector through the Cloud setup wizard. If using that wizard, avoid duplicate collection.

### Troubleshooting

- **Orders won't start:** check PostgreSQL readiness, the `RETAIL_ORDERS_PERSISTENCE_*` settings and Flyway errors. The Java binding uses `ENDPOINT`, `NAME`, `USERNAME`, `PASSWORD`, not the stale upstream documentation's nested `POSTGRES_*` keys.
- **`pg_up=0`:** check networking, Secret keys and database authentication. An Alloy readiness response is not proof of DB connectivity.
- **Health but no queries:** generate checkout traffic; confirm the extension, preload setting and monitoring grants; allow a scrape/collection interval.
- **Metrics but no details in Cloud:** verify Loki write permissions and the `integrations/db-o11y` labels; query details are log telemetry, not Prometheus metrics.
- **No samples/plans:** short queries may not be sampled; plans depend on supported statements and permissions. Keep privileges scoped and inspect collector errors privately.
- **Data disappeared:** database container recreation/pod replacement resets this demo by design.

## Coverage

| Area | Implementation |
|---|---|
| Logs, metrics, traces | Existing Alloy pipelines plus PostgreSQL signals |
| Application Observability | Existing app instrumentation; PostgreSQL JDBC spans included |
| Frontend Observability | Existing Faro/proxy integration; requires a configured Faro application URL |
| Database Observability | Default PostgreSQL + health and query-level Alloy collection |
| Continuous profiling | Existing Java, Go and Node profiles |
| Agent Observability | Separate [optional AI chat / Agent Observability guide](optional-ai-chat.md); not enabled by the DB change |

Sources: [self-managed PostgreSQL setup](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-applications/database-observability/set-up/postgres/postgres/), [Alloy PostgreSQL DB O11y component](https://grafana.com/docs/alloy/latest/reference/components/database_observability/database_observability.postgres/).

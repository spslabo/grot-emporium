# PostgreSQL and Database Observability

Included automatically: PostgreSQL for orders, database metrics, query statistics, logs and JDBC traces. Uses your existing Grafana ingestion settings.

## View database activity

1. Launch Grot. Automatic shopping traffic creates orders.
2. Open **Grafana Cloud → Database Observability → Configuration → Telemetry status**.
3. Select `my-demo/grot-postgres` (replace `my-demo` with your deployment's cluster label).
4. Open **Queries overview** for call counts, latency and available plans/wait samples.

Allow a few minutes for data to appear. Avoid adding a second collector through the Cloud setup wizard.

## Storage

**Disposable data. Not a production database.**

| Runtime | When orders are lost |
|---|---|
| Docker | Database recreation or demo relaunch |
| Kubernetes | Database pod replacement |

- Restarting only the orders service preserves data.
- Kubernetes `--mode long-term` manages credentials; it does not provide durable storage.
- No backups or high availability are configured.

## Credentials

Quick mode generates separate passwords automatically:

| User | Access |
|---|---|
| `postgres` | Database administration |
| `grot_orders` | Application schema and data |
| `db-o11y` | Read-only monitoring |

For long-term mode, create `grot-database-runtime` with:

- `POSTGRES_PASSWORD`
- `GROT_DB_APP_PASSWORD`
- `GROT_DB_MONITOR_PASSWORD`

Use distinct values, each 32–128 characters: letters, digits, `_` or `-`. Coordinate password changes with PostgreSQL roles; editing the Secret alone is insufficient.

## Troubleshooting

| Problem | Check |
|---|---|
| Orders won't start | PostgreSQL readiness, credentials and Flyway errors |
| `pg_up=0` | Database connectivity and monitoring credentials |
| Health metrics but no queries | Automatic demo activity is running; `pg_stat_statements` is enabled |
| Query metrics but no details | Loki ingestion permissions and `integrations/db-o11y` labels |
| Missing plans or wait samples | Query duration and supported statements; not every query produces a sample |
| Orders disappeared | Database container/pod was recreated |

Useful queries; replace `my-demo` with your cluster label:

```promql
pg_up{job="integrations/db-o11y",cluster="my-demo"}
sum(rate(pg_stat_statements_calls_total{job="integrations/db-o11y",cluster="my-demo"}[5m]))
```

```logql
{job="integrations/db-o11y",cluster="my-demo"} |= "query_association"
```

## Security

- Use synthetic data only; SQL redaction does not remove every sensitive identifier.
- Do not expose this database publicly. Internal database connections are unencrypted.
- Keep database credentials in your secret manager, not Git or command arguments.

# Demo traffic and load tests

## Automatic demo traffic

- Starts with the app: **6 shopping + 1 browser journey per minute**.
- Stops when the app is removed.
- No model calls, injected faults or Cloud k6 runs.
- Disable at launch with `--no-demo-traffic`.

## Optional load testing

| Test | Options |
|---|---|
| Shopping + browser | `--preset low`, `medium` or `high` |
| HTTP-only shopping | Add `--browser-rate 0` |
| Custom rate | `--rate 15 --browser-rate 2` |
| Catalog errors and delays | Add `--failures` |
| AI chat | Add `--chat-every 5m --chat-max-requests 60 --allow-paid-ai` |

Shopping journeys browse products, update carts and place synthetic orders.

| Preset | Shopping/min | Browser/min |
|---|---:|---:|
| low | 6 | 1 |
| medium | 30 | 2 |
| high | 120 | 4 |

### Run a 10-minute test

```sh
./grot traffic my-demo start --context "$CONTEXT" \
  --local-only --preset low --duration 10m
./grot traffic my-demo status --context "$CONTEXT"
./grot traffic my-demo stop --context "$CONTEXT"
```

- Docker: omit `--context "$CONTEXT"`.
- Stop the current test before changing options.
- Kubernetes: add `--repeat` to repeat until stopped.
- Built-in demo traffic continues alongside the test. Launch with `--no-demo-traffic` for isolated measurements.

### Send results to Cloud k6

1. Install [gcx](https://github.com/grafana/gcx) and run `gcx login demo-cloud`.
2. Replace `--local-only` with `--grafana-context demo-cloud`.
3. Add `--k6-project ID` if your stack has multiple projects.

**Cloud k6 usage may be billable.** Project duration limits apply.

### Catalog faults

`--failures` adds 60 catalog probes/minute: 1% HTTP 500s and 5% two-second delays.

Override with `--error-percent`, `--slow-percent`, `--delay-ms` and `--fault-rate`. Normal shopper requests are unaffected.

### AI chat

Complete [AI chat setup](optional-ai-chat.md) first. **Model usage is separately billable.** The request budget resets each repeated run.

For an injected error every tenth chat, enable `GROT_CHAT_SYNTHETIC_FAULTS_ENABLED=true` in the UI settings and add `--chat-error-every 10`. Injected errors do not call the model.

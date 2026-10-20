# Optional AI chat and Agent Observability

Chat is off by default. **Real model requests may incur charges.**

## Recommended: guided Kubernetes setup

For an existing quick-mode deployment:

```sh
./grot agento11y my-demo --context "$CONTEXT" --capture-content
```

1. Choose Bedrock or OpenAI and a model.
2. Enter provider credentials when prompted, if required.
3. Copy the endpoint, stack ID and token from **Grafana Cloud → Agent Observability → Connection**.
4. Wait for UI to restart, then open the shop's chat.

The Agent Observability token needs `sigil:write`. Credentials are entered privately and reused on reruns.

| Option | Purpose |
|---|---|
| `--capture-content` | Export prompts and responses for all demo chats |
| `--metadata-only` | Do not export prompt/response text |
| `--replace-credentials` | Replace saved credentials |
| `--ui-image IMAGE` | Upgrade an older UI image |
| `--verify --allow-paid-ai --grafana-context demo-cloud` | Make one model request and check its telemetry |

**Content capture is not sanitization. Use synthetic prompts only.** Prompt/response text is not added to traces.

### OpenAI or compatible endpoint

```sh
./grot agento11y my-demo --context "$CONTEXT" \
  --provider openai --model YOUR_MODEL --capture-content
```

- Enter the API key at the private prompt.
- Default endpoint: `https://api.openai.com`.
- For a compatible endpoint, add `--openai-base-url https://your-provider.example`.
- Azure-specific authentication and direct Anthropic/Gemini adapters are not included.

### AWS Bedrock

Before running setup:

1. Confirm your account has access to the model/inference profile.
2. Give the `ui` service account an AWS role using [IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html) or EKS Pod Identity.
3. Grant `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for the chosen profile and its destination model ARNs.
4. Allow outbound access to Bedrock Runtime and AWS identity endpoints.

Example model and region; choose ones available in your account:

```sh
aws bedrock get-inference-profile --region us-east-1 \
  --inference-profile-identifier us.amazon.nova-lite-v1:0 \
  --query '{profile:inferenceProfileArn,models:models[].modelArn}'

./grot agento11y my-demo --context "$CONTEXT" \
  --provider bedrock --model us.amazon.nova-lite-v1:0 --region us-east-1 \
  --capture-content
```

For IRSA, scope the role trust to your cluster OIDC provider, audience `sts.amazonaws.com` and subject `system:serviceaccount:grot-my-demo:ui`. Attach the approved role:

```sh
kubectl --context "$CONTEXT" -n grot-my-demo annotate serviceaccount ui \
  eks.amazonaws.com/role-arn=YOUR_UI_ROLE_ARN --overwrite
```

Attach the role before running setup. Local AWS CLI login does not give the pod AWS access. The launcher does not create IAM roles or request static AWS keys.

## Docker and externally managed Secrets

- Docker: add UI settings to the `ui` object of your complete launch JSON; pass it with `--settings-stdin`.
- Kubernetes long-term: update `grot-ui-runtime` through your secret manager and rerun the installer.

### Chat settings

| Key | Value |
|---|---|
| `RETAIL_UI_CHAT_ENABLED` | `true` |
| `RETAIL_UI_CHAT_PROVIDER` | `openai`, `bedrock` or `mock` |
| `RETAIL_UI_CHAT_MODEL` | Your model or inference-profile ID |
| `RETAIL_UI_CHAT_OPENAI_BASE_URL` | OpenAI-compatible HTTPS endpoint |
| `RETAIL_UI_CHAT_OPENAI_API_KEY` | OpenAI provider key |
| `RETAIL_UI_CHAT_BEDROCK_REGION` | AWS region for Bedrock |

Only set the keys for your provider. `mock` provides canned replies without model charges.

### Agent Observability settings

| Key | Value |
|---|---|
| `GROT_AGENT_OBSERVABILITY_ENABLED` | `true` |
| `AGENTO11Y_ENDPOINT` | Generation-ingestion endpoint from the Connection page |
| `AGENTO11Y_PROTOCOL` | `http` |
| `AGENTO11Y_AUTH_MODE` | `basic` |
| `AGENTO11Y_AUTH_TENANT_ID` | Stack ID from the Connection page |
| `AGENTO11Y_AUTH_TOKEN` | Token with `sigil:write` |
| `AGENTO11Y_CONTENT_CAPTURE_MODE` | `metadata_only` or `full_with_metadata_spans` |
| `AGENTO11Y_TAGS` | `app=grot-emporium,environment=demo,cluster=my-demo` |
| `OTEL_METRICS_EXPORTER` | `otlp` |

[Optional chat load tests](demo-traffic.md#ai-chat) · [Configure evaluations and experiments](https://grafana.com/docs/grafana-cloud/observe-and-act/agent-observability/evaluate-and-improve/experiments/)

## Disable

Set `RETAIL_UI_CHAT_ENABLED=false` and `GROT_AGENT_OBSERVABILITY_ENABLED=false` in the UI settings, then restart UI through your deployment method.

# Optional AI shopping assistant

**Not required for store or telemetry validation.** The normal launch prompts configure metrics, logs, traces, profiles and optional Faro. They do not configure AI chat. `grot verify` exercises shopping, not model calls.

Chat is an independent opt-in. Configure it in the **UI role**, never in Alloy's ingestion token fields. Enabling a real provider means browser chat requests can incur model charges; use an approved account/model and provider-side spending limits. Do not expose paid chat publicly without access control.

## Recommended: guided Kubernetes setup

For an existing launcher-owned Kubernetes installation, run from the repository in a terminal:

```sh
./grot agento11y my-demo --context my-kube-context \
  --capture-content --verify --allow-paid-ai --grafana-context my-stack
```

`agento11y` is an alias of `agent-observability`. Replace the destination and contexts with yours. This single command:

1. Reuses a configured real provider, or asks for Bedrock/OpenAI, model and provider settings. API keys are hidden inputs, never command arguments.
2. Collects missing Agent Observability connection settings securely; reuses existing credentials on reruns. Use `--replace-credentials` to replace them.
3. Enables generation export, OTLP metrics, app/environment/cluster labels and full generation content with metadata-only traces. Without `--capture-content`, it asks for consent; `--metadata-only` opts out of content export.
4. Patches the UI Secret and rolls UI once, without altering the app's other services or starting traffic.
5. With the three verification flags shown above, makes **one** synthetic chat request and checks the recorded content/model, the actual generation span in its trace, and labelled metrics in Cloud. Indexing is polled for up to two minutes; model requests are not retried. These are telemetry checks, not evaluations or experiments.

Omit `--verify --allow-paid-ai --grafana-context my-stack` for setup without a model request. Setup alone does **not** prove provider access or Cloud delivery. Verification uses the stack's standard `grafanacloud-prom` and `grafanacloud-traces` datasource UIDs.

**Use a current UI image.** Older images cannot capture content merely by changing configuration; verification reports that gap. If upgrading an existing install, add `--ui-image registry.example.com/team/grot-ui:your-version`. The command updates the image and uses its reference as agent version in the same rollout. Registry pull access must already work. To build/publish your own image, from the repository:

```sh
# Set UI_IMAGE to a registry/repository you control; authenticate using your registry's secure login.
export UI_IMAGE=registry.example.com/team/grot-ui:your-version
docker buildx build --platform linux/amd64,linux/arm64 --push -t "$UI_IMAGE" src/ui
```

For external-secret/long-term installations the command deliberately refuses to overwrite managed secrets: use the equivalent UI settings below through your secret manager. Docker uses the role-grouped launch configuration below, not this Kubernetes command.

### Wire OpenAI or an OpenAI-compatible endpoint

```sh
./grot agento11y my-demo --context my-kube-context \
  --provider openai --model YOUR_APPROVED_MODEL --capture-content
```

The command asks for the model-provider API key privately and defaults to `https://api.openai.com`. For an API-compatible service, specify its approved HTTPS base URL with `--openai-base-url`; that service receives your model prompts and key. Model-provider credentials are separate from Grafana ingestion credentials. Use provider-side spending limits and allow outbound HTTPS from UI. This adapter uses the OpenAI chat API; it does not automatically configure provider-specific Azure/other authentication schemes. Direct Anthropic/Gemini adapters are not included. To use an available Anthropic model through Bedrock, select `bedrock` and its approved inference-profile ID and IAM permissions instead.

### Wire AWS Bedrock (workload identity, not API keys)

```sh
./grot agento11y my-demo --context my-kube-context \
  --provider bedrock --model us.amazon.nova-lite-v1:0 --region us-east-2 \
  --capture-content
```

Choose a model/profile available in **your** AWS account and region; the example is not universal. Before setup:

1. Enable/confirm Bedrock model access and applicable quotas. For cross-region inference, inspect the profile's actual destination model ARNs:
   ```sh
   aws bedrock get-inference-profile --region us-east-2 \
     --inference-profile-identifier us.amazon.nova-lite-v1:0 \
     --query '{profile:inferenceProfileArn,models:models[].modelArn}'
   ```
2. Give the UI service account a narrowly scoped AWS workload identity ([EKS IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html) or EKS Pod Identity). For IRSA, trust only your cluster's OIDC provider, `aud=sts.amazonaws.com`, and `sub=system:serviceaccount:grot-my-demo:ui` (use your real namespace). Grant `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the chosen inference-profile ARN and its exact destination foundation-model ARNs. You can restrict the foundation-model statements with the `bedrock:InferenceProfileArn` condition. Do not grant wildcard model access or modify the worker-node role.
3. For IRSA, annotate the existing `ui` service account with the approved role, then run the setup command above (its rollout refreshes identity injection):
   ```sh
   kubectl --context my-kube-context -n grot-my-demo annotate serviceaccount ui \
     eks.amazonaws.com/role-arn=arn:aws:iam::YOUR_ACCOUNT:role/YOUR_UI_ROLE --overwrite
   ```
   For EKS Pod Identity, create the association for that service account instead of using the IRSA annotation. Ensure your Pod Identity agent/SDK prerequisites are satisfied.
4. Allow UI network access to Bedrock Runtime and the relevant AWS identity endpoints. `--verify --allow-paid-ai --grafana-context my-stack` verifies actual model access. A Ready pod alone does not.

The script configures the application, not AWS IAM, organization SCPs, model entitlements or registry access. It never asks for AWS access keys. Local AWS CLI login does not automatically grant the Kubernetes pod Bedrock access.

## Where to enter the settings

| Launch mode | Where settings go |
|---|---|
| Docker / Kubernetes quick | The `ui` object of the existing role-grouped JSON input, passed with `--settings-stdin` |
| Kubernetes long-term | Your team's managed `grot-ui-runtime` Secret; update through the existing secret manager and rerun the long-term installer to restart consumers |

JSON input must also contain your `alloy` ingestion settings and optional `gateway` Faro settings; a UI-only JSON object is not a complete launch configuration. Stream the full object from your credential tool, rather than saving credentials in the repository, command arguments or shell history.

### OpenAI: required UI settings

```json
{
  "RETAIL_UI_CHAT_ENABLED": "true",
  "RETAIL_UI_CHAT_PROVIDER": "openai",
  "RETAIL_UI_CHAT_MODEL": "<approved-model-id>",
  "RETAIL_UI_CHAT_OPENAI_BASE_URL": "https://api.openai.com",
  "RETAIL_UI_CHAT_OPENAI_API_KEY": "<model-provider-api-key>"
}
```

These are entries **inside `ui`**, not a standalone settings document. Replace placeholders in your private credential source, not a committed file. The model key is `RETAIL_UI_CHAT_MODEL` for both OpenAI and Bedrock. Supply the base URL explicitly.

### No credential manager? Optional terminal-only launch

Run from the repository in a macOS/Linux terminal. This prompts for telemetry settings, a model ID and an API key, then launches `ai-demo` on port 8081. Credentials pass through stdin without creating a credential file. Stop any existing demo first if Docker has insufficient memory for both.

Model requests are made when someone uses the chat UI, not during launch.

```sh
python3 - <<'PY' | ./grot docker ai-demo --settings-stdin --port 8081 --collector-port 12346 --syslog-port 15141
import contextlib, json, sys
from types import SimpleNamespace
from scripts import grot

with open('/dev/tty') as terminal, contextlib.redirect_stdout(sys.stderr):
    sys.stdin = terminal
    roles = grot.settings(SimpleNamespace(destination='ai-demo', settings_stdin=False))
    roles['ui'].update({
        'RETAIL_UI_CHAT_ENABLED': 'true',
        'RETAIL_UI_CHAT_PROVIDER': 'openai',
        'RETAIL_UI_CHAT_MODEL': grot.prompt_setting('Approved OpenAI model ID', 'ui', 'RETAIL_UI_CHAT_MODEL'),
        'RETAIL_UI_CHAT_OPENAI_BASE_URL': 'https://api.openai.com',
        'RETAIL_UI_CHAT_OPENAI_API_KEY': grot.prompt_setting('OpenAI API key', 'ui', 'RETAIL_UI_CHAT_OPENAI_API_KEY'),
    })
    roles = grot.make_roles(roles)
json.dump(roles, sys.stdout)
PY
```

Open `http://localhost:8081` and send one synthetic shopping question when ready to incur a model call. If enabling Faro here, also allow `http://localhost:8081` in that Faro application. Stop with `./grot stop ai-demo`.

For Kubernetes quick, stream the same full role-grouped JSON to `./grot k8s <alias> --mode quick --settings-stdin` with your usual context/image flags.

### Other providers

- **Mock:** set `RETAIL_UI_CHAT_ENABLED=true` and `RETAIL_UI_CHAT_PROVIDER=mock` for canned responses without external model calls.
- **Bedrock:** set `RETAIL_UI_CHAT_ENABLED=true`, `RETAIL_UI_CHAT_PROVIDER=bedrock`, `RETAIL_UI_CHAT_MODEL` and `RETAIL_UI_CHAT_BEDROCK_REGION`. The UI workload additionally needs your approved AWS identity, IAM permissions and regional model access. Prefer an existing Kubernetes workload identity; the launcher does not set up AWS credentials or infrastructure.

## Optional Agent Observability

Enabling chat does **not** automatically enable Grafana Agent Observability generation export. If you want that separate integration, add these UI settings from your stack's Agent Observability connection instructions:

- `GROT_AGENT_OBSERVABILITY_ENABLED=true`
- `AGENTO11Y_ENDPOINT` — generation-ingestion endpoint, **not** the OTLP trace endpoint
- `AGENTO11Y_PROTOCOL=http` — explicitly use HTTP generation ingestion for Cloud
- `AGENTO11Y_AUTH_MODE=basic`
- `AGENTO11Y_AUTH_TENANT_ID` — Grafana Cloud stack/instance ID from the Connection page
- `AGENTO11Y_AUTH_TOKEN` — authorized for that API; do not assume the telemetry token has this permission

For an existing launcher-owned Kubernetes UI, the guided command handles the provider and generation-export settings together:

```sh
./grot agent-observability <destination> --context <context>
```

Get the endpoint, stack/instance ID and ingestion token from your stack's Agent Observability plugin **Connection** tab. The token needs the [publicly documented `sigil:write` scope](https://grafana.com/docs/grafana-cloud/observe-and-act/agent-observability/privacy-and-access/security/); the existing Alloy credentials continue handling traces/metrics. Do not paste tokens into chat or command arguments. This command patches the UI Secret, rolls UI, reuses the model/provider unless you select a different one, and enables `OTEL_METRICS_EXPORTER=otlp` so Agent Observability metrics can reach the existing Alloy pipeline. It makes no model calls unless you explicitly enable the verification flags above. Externally managed Secrets must be updated through their secret manager instead.

For a supported bearer-auth deployment, use `AGENTO11Y_AUTH_MODE=bearer` and its token instead of a basic-auth stack/instance ID. Export defaults to `AGENTO11Y_CONTENT_CAPTURE_MODE=metadata_only`. Real model invocation and real Agent Observability indexing are separate checks; neither is implied by passing `grot verify`.

### Telemetry for evaluation, replay and model comparisons

After explicitly approving content export, set these **UI-role** values and restart UI (requires the updated image):

```text
AGENTO11Y_CONTENT_CAPTURE_MODE=full_with_metadata_spans
AGENTO11Y_TAGS=app=grot-emporium,environment=demo,cluster=<destination>
OTEL_METRICS_EXPORTER=otlp
```

This captures the actual system prompt, user message and complete streamed assistant response in Agent Observability, while excluding their text from OTel spans. It applies to **all chats**, not only synthetic traffic. Capture modes are not PII/secret sanitization: do not submit credentials or sensitive personal data to this demo. Restore `metadata_only` to disable future content export; previously stored content is not removed or reconstructed by changing the mode.

The recorder supplies requested model/provider, agent version, max tokens, temperature, usage, timing, first-token timing, finish reason, conversation/trace correlation and error state. Response model and response ID are recorded **only when the provider adapter supplies them**; the current Bedrock/Spring AI streaming adapter does not expose either, so neither is fabricated. Injected errors retain their fault labels and input, with no invented answer/token usage.

- Canonical generation model fields and OTel labels identify the model: `gen_ai_provider_name`, `gen_ai_request_model` (and response model when reported).
- Generation tags add `model_provider` and `requested_model` for filtering.
- Client `AGENTO11Y_TAGS` also becomes trace attributes / metric labels such as `agento11y_tag_cluster`. Use low-cardinality values only, never prompts, secrets, conversation IDs or user IDs.
- For an external experiment runner, send a UUID `conversationId` to `POST /chat/submit`; the runner can bind that same conversation to its trial. Do not attach fake experiment IDs to ordinary demo traffic.

**Experiment enablement is separate from app telemetry.** Java SDK 0.7.2 does not implement the experimental experiment-runner flag. Setting `AGENTO11Y_ENABLE_EXPERIMENTAL_FEATURES=true` on this UI would do nothing. Python/JavaScript runners need that flag for experimental cloud `trial.evaluate(...)` calls; it is not required to collect reusable conversations. `online_evaluations_enabled=true` is an explicit, immutable option when creating an actual experiment if its generations should also enter online evaluations (default false). `AGENTO11Y_EXPERIMENT_ID` belongs to supported runner helpers, not the live Java UI. No evaluators, experiment runs or comparison jobs are created by enabling content capture.

References: [capture-mode matrix](https://github.com/grafana/agento11y/blob/main/docs/concepts/content-capture-modes.md), [tags and metadata](https://github.com/grafana/agento11y/blob/main/docs/concepts/tags-and-metadata.md), [SDK experiment flags](https://github.com/grafana/agento11y/blob/main/llms.txt#offline-experiments), [experiment lifecycle and isolation](https://grafana.com/docs/grafana-cloud/observe-and-act/agent-observability/evaluate-and-improve/experiments/).

To disable chat again, set `RETAIL_UI_CHAT_ENABLED=false` in the UI role and relaunch/restart through the same mode. Also set `GROT_AGENT_OBSERVABILITY_ENABLED=false` if disabling generation export.

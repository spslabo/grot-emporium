# Optional AI shopping assistant

**Not required for store or telemetry validation.** The normal launch prompts configure metrics, logs, traces, profiles and optional Faro. They do not configure AI chat. `grot verify` exercises shopping, not model calls.

Chat is an independent opt-in. Configure it in the **UI role**, never in Alloy's ingestion token fields. Enabling a real provider means browser chat requests can incur model charges; use an approved account/model and provider-side spending limits. Do not expose paid chat publicly without access control.

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
- `AGENTO11Y_AUTH_MODE=basic`
- `AGENTO11Y_AUTH_TENANT_ID`
- `AGENTO11Y_AUTH_TOKEN` — authorized for that API; do not assume the telemetry token has this permission

For a supported bearer-auth deployment, use `AGENTO11Y_AUTH_MODE=bearer` and its token instead of a basic-auth tenant. Export is metadata-only: prompt/completion capture remains disabled. Real model invocation and real Agent Observability indexing are separate checks; neither is implied by passing `grot verify`.

To disable chat again, set `RETAIL_UI_CHAT_ENABLED=false` in the UI role and relaunch/restart through the same mode. Also set `GROT_AGENT_OBSERVABILITY_ENABLED=false` if disabling generation export.

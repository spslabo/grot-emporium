"""Guided Kubernetes provider + Agent Observability setup; secrets stay on stdin."""
import base64
import json
import sys
import time
import uuid
from urllib.parse import urlsplit


def setup_values(args, existing, api):
    print('Real-provider chat can incur model charges when used. Setup does not start traffic; optional verification makes one request.')
    values = dict(existing)
    provider = getattr(args, 'provider', None) or values.get('RETAIL_UI_CHAT_PROVIDER')
    if provider not in ('bedrock', 'openai'):
        provider = api.prompt_setting('LLM provider (bedrock or openai)', 'ui', 'RETAIL_UI_CHAT_PROVIDER')
    if provider not in ('bedrock', 'openai'):
        raise api.SafeError('Choose bedrock or openai; mock does not export generations.')
    same_provider = provider == existing.get('RETAIL_UI_CHAT_PROVIDER')
    model = getattr(args, 'model', None) or (values.get('RETAIL_UI_CHAT_MODEL') if same_provider else None)
    if not model:
        model = api.prompt_setting('Approved model ID (Bedrock: inference profile ID when required)', 'ui', 'RETAIL_UI_CHAT_MODEL')
    values.update(RETAIL_UI_CHAT_ENABLED='true', RETAIL_UI_CHAT_PROVIDER=provider, RETAIL_UI_CHAT_MODEL=model)
    if provider == 'bedrock':
        region = getattr(args, 'region', None) or values.get('RETAIL_UI_CHAT_BEDROCK_REGION')
        if not region:
            region = api.prompt_setting('Bedrock AWS region', 'ui', 'RETAIL_UI_CHAT_BEDROCK_REGION')
        values['RETAIL_UI_CHAT_BEDROCK_REGION'] = region
        print('Bedrock uses the UI workload AWS identity. IAM/model access must already be configured; no static AWS keys are collected. See docs/optional-ai-chat.md.')
    else:
        base = getattr(args, 'openai_base_url', None) or (values.get('RETAIL_UI_CHAT_OPENAI_BASE_URL') if same_provider else None) or 'https://api.openai.com'
        if urlsplit(base).scheme != 'https':
            raise api.SafeError('This setup requires HTTPS for the OpenAI-compatible provider endpoint.')
        values['RETAIL_UI_CHAT_OPENAI_BASE_URL'] = base
        if not values.get('RETAIL_UI_CHAT_OPENAI_API_KEY') or getattr(args, 'replace_credentials', False) or not same_provider:
            values['RETAIL_UI_CHAT_OPENAI_API_KEY'] = api.prompt_setting('LLM provider API key (hidden)', 'ui', 'RETAIL_UI_CHAT_OPENAI_API_KEY')

    mode = values.get('AGENTO11Y_CONTENT_CAPTURE_MODE', 'metadata_only')
    if getattr(args, 'capture_content', False):
        mode = 'full_with_metadata_spans'
    elif getattr(args, 'metadata_only', False):
        mode = 'metadata_only'
    elif mode == 'metadata_only':
        answer = input('Enable evaluation-ready content capture for ALL demo chats? Prompts/answers go to Cloud, not traces; do not enter secrets or PII. [y/N]: ').strip().lower()
        if answer not in ('', 'n', 'no', 'y', 'yes'):
            raise api.SafeError('Answer yes or no, or use --capture-content / --metadata-only.')
        if answer in ('y', 'yes'): mode = 'full_with_metadata_spans'
    values['AGENTO11Y_CONTENT_CAPTURE_MODE'] = mode
    tags = {}
    for entry in values.get('AGENTO11Y_TAGS', '').split(','):
        if not entry: continue
        key, separator, value = entry.partition('=')
        if not separator or not key.strip() or not value.strip():
            raise api.SafeError('AGENTO11Y_TAGS must contain comma-separated key=value entries.')
        tags[key.strip()] = value.strip()
    tags.update(app='grot-emporium', cluster=args.destination)
    tags.setdefault('environment', 'demo')
    values['AGENTO11Y_TAGS'] = ','.join(k + '=' + v for k, v in sorted(tags.items()))

    print('Use the target stack\'s Agent Observability Connection tab. Existing credentials are reused; --replace-credentials prompts for replacements. Inputs stay hidden.')
    prompts = [('AGENTO11Y_ENDPOINT', 'Generation ingestion endpoint (HTTPS)'),
               ('AGENTO11Y_AUTH_TENANT_ID', 'Grafana Cloud stack/instance ID'),
               ('AGENTO11Y_AUTH_TOKEN', 'Agent Observability ingestion token (sigil:write)')]
    for key, label in prompts:
        if not values.get(key) or getattr(args, 'replace_credentials', False):
            values[key] = api.prompt_setting(label, 'ui', key)
        if key == 'AGENTO11Y_ENDPOINT' and urlsplit(values[key]).scheme != 'https':
            raise api.SafeError('Cloud generation ingestion requires HTTPS.')
    values.update(GROT_AGENT_OBSERVABILITY_ENABLED='true', AGENTO11Y_PROTOCOL='http',
                  AGENTO11Y_AUTH_MODE='basic', OTEL_METRICS_EXPORTER='otlp')
    api.validate('ui', values)
    return values


def trace_has_span(trace, span_id):
    if not span_id: return False
    for resource in trace.get('trace', {}).get('resourceSpans', []):
        for scope in resource.get('scopeSpans', []):
            for span in scope.get('spans', []):
                actual = span.get('spanId', '')
                if actual == span_id: return True
                try:
                    if base64.b64decode(actual, validate=True).hex() == span_id: return True
                except ValueError:
                    pass
    return False


def verify(args, kube, values, api):
    """One ordinary model call; read-only Cloud checks. No evaluators/experiments."""
    cid = str(uuid.uuid4())
    prompt = 'Suggest a Grot desk companion in one short sentence.'
    try:
        response = api.run(kube + ['exec', '-i', 'deployment/ui', '--', 'curl', '--fail-with-body',
            '--max-time', '30', '-sS', '-H', 'Content-Type: application/json', '-H', 'Accept: text/event-stream',
            '--data-binary', '@-', 'http://grot-gateway/chat/submit'],
            data=json.dumps({'conversationId': cid, 'message': prompt}))
    except api.SafeError:
        raise api.SafeError('Chat verification failed. Check UI/gateway health, provider credentials, model access and Bedrock workload IAM. No model request was retried; Cloud delivery remains unverified.') from None
    try:
        answer = ''.join(json.loads(line[5:]).get('text', '') for line in response.splitlines() if line.startswith('data:'))
    except (ValueError, TypeError):
        raise api.SafeError('Model response was not a valid chat stream.') from None
    if not answer.strip(): raise api.SafeError('The chat returned no answer; check provider access and UI configuration.')
    cloud = ['gcx', '--context', args.grafana_context]
    deadline = time.monotonic() + 120
    generation = None
    trace_ok = metrics_ok = False
    while time.monotonic() < deadline:
        try:
            if generation is None:
                obj = json.loads(api.run(cloud + ['agento11y', 'conversations', 'get', cid, '-o', 'json']))
                generation = next(iter(obj.get('generations', [])), None)
            if generation:
                def text(messages):
                    return ''.join(p.get('text') or '' for m in messages for p in m.get('parts', []))
                if generation.get('model', {}).get('name') != values['RETAIL_UI_CHAT_MODEL'] or generation.get('model', {}).get('provider') != values['RETAIL_UI_CHAT_PROVIDER']:
                    raise ValueError('Recorded model/provider does not match configuration.')
                if values['AGENTO11Y_CONTENT_CAPTURE_MODE'] != 'metadata_only' and (
                    text(generation.get('input', [])) != prompt or text(generation.get('output', [])) != answer or not generation.get('system_prompt')):
                    raise ValueError('Content capture is incomplete. Deploy the updated UI image; older images hardcode metadata-only export.')
                if generation.get('error'): raise ValueError('Recorded generation contains an unexpected error.')
                trace_id = generation.get('trace_id')
                if trace_id and not trace_ok:
                    trace = json.loads(api.run(cloud + ['traces', 'get', trace_id, '-d', 'grafanacloud-traces', '--since', '15m', '-o', 'json']))
                    trace_ok = trace_has_span(trace, generation.get('span_id'))
                if not metrics_ok:
                    query = 'gen_ai_client_operation_duration_seconds_count{gen_ai_agent_name="grot-shopping-assistant",agento11y_tag_cluster=' + json.dumps(args.destination) + ',gen_ai_request_model=' + json.dumps(values['RETAIL_UI_CHAT_MODEL']) + ',gen_ai_provider_name=' + json.dumps(values['RETAIL_UI_CHAT_PROVIDER']) + '}'
                    metrics = json.loads(api.run(cloud + ['metrics', 'query', '-d', 'grafanacloud-prom', query, '-o', 'json']))
                    metrics_ok = bool(metrics.get('data', {}).get('result'))
                if trace_ok and metrics_ok:
                    print('Verified one chat, Cloud generation, model identity, linked trace and labelled metrics. Conversation: ' + cid)
                    return
        except api.SafeError:
            pass  # Indexing can lag; do not repeat the paid model call.
        except ValueError as error:
            raise api.SafeError(str(error)) from None
        time.sleep(5)
    raise api.SafeError('UI was configured but Cloud verification timed out. Check target context, exporter credentials and OTLP delivery. No additional model calls were made. Conversation: ' + cid)


def configure(args, api):
    if not sys.stdin.isatty():
        raise api.SafeError('Run this command in your terminal; connection settings and token are collected with hidden prompts.')
    if getattr(args, 'verify', False) and (not getattr(args, 'allow_paid_ai', False) or not getattr(args, 'grafana_context', None)):
        raise api.SafeError('--verify requires --allow-paid-ai and an explicit --grafana-context; it makes one model request.')
    kube = ['kubectl', '--context', args.context, '-n', args.namespace, '--request-timeout=45s']
    ledger = api.get_object(kube, 'configmap', api.LEDGER)
    if not ledger or ledger.get('data', {}).get('destination') != args.destination:
        raise api.SafeError('No matching Grot installation.')
    owner = ledger['data'].get('owner')
    secret = api.get_object(kube, 'secret', 'grot-ui-runtime')
    if not owner or not api.owned(ledger, owner) or not secret or not api.owned(secret, owner):
        raise api.SafeError('UI Secret is externally managed. Use docs/optional-ai-chat.md settings in its secret manager instead.')
    if getattr(args, 'verify', False):
        # Establish CLI authentication/conversation read access before mutation or paid calls.
        api.run(['gcx', '--context', args.grafana_context, 'agento11y', 'conversations', 'search',
                 '--filters', 'agent = "grot-shopping-assistant"', '-o', 'json'])
    existing = {k: base64.b64decode(v).decode() for k, v in secret['data'].items()}
    values = setup_values(args, existing, api)
    updates = {k: v for k, v in values.items() if existing.get(k) != v}
    payload = {'metadata': {'resourceVersion': secret['metadata']['resourceVersion']},
               'data': {k: base64.b64encode(v.encode()).decode() for k, v in updates.items()}}
    api.run(kube + ['patch', 'secret', 'grot-ui-runtime', '--field-manager=' + api.MANAGER,
                    '--type=merge', '--patch-file=/dev/stdin'], data=json.dumps(payload))
    template = {'metadata': {'annotations': {'grot-agento11y-revision': str(uuid.uuid4())}}}
    if getattr(args, 'ui_image', None):
        template['spec'] = {'containers': [{'name': 'ui', 'image': args.ui_image,
            'env': [{'name': 'SERVICE_VERSION', 'value': args.ui_image, 'valueFrom': None}]}]}
    api.run(kube + ['patch', 'deployment', 'ui', '--type=strategic', '--patch-file=/dev/stdin'],
            data=json.dumps({'spec': {'template': template}}))
    api.run(kube + ['rollout', 'status', 'deployment/ui', '--timeout=180s'])
    print('UI provider and generation export configured. Content capture mode: ' + values['AGENTO11Y_CONTENT_CAPTURE_MODE'] + '.')
    print('Model/provider tags are emitted by the updated UI; app/environment/cluster client labels and OTLP metrics are configured. No experiment flags or evaluation resources were created.')
    if getattr(args, 'verify', False): verify(args, kube, values, api)
    else: print('No model request was made and Cloud ingestion is not yet verified. Rerun with --verify --allow-paid-ai --grafana-context <stack> to check end-to-end. Updated UI image required; see --ui-image.')

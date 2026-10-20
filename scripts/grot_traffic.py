"""Bounded, opt-in k6 traffic against an existing Grot installation only."""
import json
import uuid
import re
import time

IMAGE = 'grafana/k6:2.3.0-with-browser'
NAME = 'grot-demo-traffic'
LABEL = 'grot-emporium/traffic-destination'
CLOUD_SECRET = NAME + '-cloud'
CLOUD_ENTRYPOINT = '''for i in $(seq 1 30); do [ -s /run/k6-cloud/token ] && break; sleep 1; done
[ -s /run/k6-cloud/token ] || exit 42
K6_CLOUD_TOKEN="$(cat /run/k6-cloud/token)"
export K6_CLOUD_TOKEN
exec k6 cloud run --local-execution --no-archive-upload --no-cloud-secrets --no-usage-report''' + ''.join(
    ' -e "' + key + '=$' + key + '"' for key in (
        'BASE_URL', 'TARGET_AUTHORIZED', 'JOURNEYS_PER_MINUTE', 'BROWSER_JOURNEYS_PER_MINUTE',
        'TRAFFIC_DURATION', 'TRAFFIC_PRESET', 'EXPECT_FARO', 'K6_CLOUD_PROJECT_ID', 'GROT_K6_TEST_NAME', 'GROT_K6_RUN_ID',
        'ALLOW_PAID_AI', 'GROT_CHAT_INTERVAL_SECONDS', 'GROT_CHAT_MAX_REQUESTS', 'GROT_CHAT_ERROR_EVERY',
        'GROT_FAILURES', 'GROT_ERROR_PERCENT', 'GROT_SLOW_PERCENT', 'GROT_DELAY_MS', 'GROT_FAULT_RATE', 'GROT_FAULT_BASE_URL'
    )) + ' /work/tests/k6/traffic.js'


def cloud_settings(args, api):
    if getattr(args, 'local_only', False): return {}, None
    context = getattr(args, 'grafana_context', None)
    if not context:
        raise api.SafeError('Cloud k6 requires --grafana-context CONTEXT. Use --local-only explicitly for logs-only traffic.')
    base = ['gcx', '--context', context]
    projects = json.loads(api.run(base + ['k6', 'projects', 'list', '-o', 'json'])) or []
    requested = getattr(args, 'k6_project', None)
    choices = [p for p in projects if requested is None or str(requested) == p['metadata']['name']]
    if len(choices) != 1:
        raise api.SafeError('Choose an accessible Cloud k6 project with --k6-project ID.')
    project = choices[0]['metadata']['name']
    namespace = choices[0]['metadata'].get('namespace', '')
    match = re.fullmatch(r'stacks-([0-9]+)', namespace)
    if not match: raise api.SafeError('Cloud k6 project did not identify its Grafana Cloud stack.')
    if not project.isdigit(): raise api.SafeError('Invalid Cloud k6 project ID.')
    token = api.run(base + ['k6', 'auth', 'token']).strip()
    if not token or any(c.isspace() for c in token): raise api.SafeError('Unable to obtain a valid Cloud k6 token from gcx.')
    print('Cloud k6 enabled: project ' + project + '. Local execution streams results to Cloud; usage may be billable.', flush=True)
    return {'K6_CLOUD_PROJECT_ID': project, 'K6_CLOUD_STACK_ID': match[1], 'GROT_K6_TEST_NAME': 'Grot Emporium - ' + args.destination,
            'GROT_K6_RUN_ID': uuid.uuid4().hex}, token
PRESETS = {'low': (6, 1), 'medium': (30, 2), 'high': (120, 4)}
FILES = {'chat-traffic.js': 'tests/k6/chat-traffic.js', 'faults.js': 'tests/k6/faults.js', 'traffic.js': 'tests/k6/traffic.js', 'shopping.js': 'tests/k6/shopping.js',
         'browser.js': 'tests/k6/browser.js', 'grots.json': 'src/catalog/grots.json'}


def settings(args, api):
    match = re.fullmatch(r'([1-9][0-9]*)(s|m|h)', args.duration)
    if not match: raise api.SafeError('Duration must be a whole number followed by s, m or h (maximum 24h).')
    seconds = int(match[1]) * {'s': 1, 'm': 60, 'h': 3600}[match[2]]
    if not 10 <= seconds <= 86400: raise api.SafeError('Duration must be between 10s and 24h.')
    rate, browsers = PRESETS[args.preset]
    rate = args.rate if args.rate is not None else rate
    browsers = args.browser_rate if args.browser_rate is not None else browsers
    if not 1 <= rate <= 600 or not 0 <= browsers <= 10:
        raise api.SafeError('Rate must be 1–600 shopping journeys/min; browser rate must be 0–10 journeys/min.')
    chat_interval = 0
    chat_every = getattr(args, 'chat_every', None)
    chat_budget = getattr(args, 'chat_max_requests', 60)
    if not 1 <= chat_budget <= 1000: raise api.SafeError('Chat request budget must be 1–1000 per run.')
    if chat_every:
        match = re.fullmatch(r'([1-9][0-9]*)(s|m|h)', chat_every)
        if not match: raise api.SafeError('--chat-every must be a whole duration such as 5m.')
        chat_interval = int(match[1]) * {'s': 1, 'm': 60, 'h': 3600}[match[2]]
        if not 60 <= chat_interval <= 3600: raise api.SafeError('Chat interval must be between 1m and 1h.')
        if not getattr(args, 'allow_paid_ai', False): raise api.SafeError('Chat makes paid model calls. Add --allow-paid-ai explicitly.')
    chat_error_every = getattr(args, 'chat_error_every', 0)
    if chat_error_every and (not chat_interval or not 2 <= chat_error_every <= 1000):
        raise api.SafeError('--chat-error-every requires --chat-every and a cadence of 2–1000 (0 disables errors).')
    failures = getattr(args, 'failures', False)
    errors, slow = getattr(args, 'error_percent', 1), getattr(args, 'slow_percent', 5)
    delay, fault_rate = getattr(args, 'delay_ms', 2000), getattr(args, 'fault_rate', 60)
    if not (0 <= errors <= 50 and 0 <= slow <= 50 and errors + slow <= 100 and 1 <= delay <= 5000 and 1 <= fault_rate <= 600):
        raise api.SafeError('Fault settings: error/slow percentages 0–50 each; delay 1–5000 ms; fault rate 1–600/min.')
    if not failures and (errors, slow, delay, fault_rate) != (1, 5, 2000, 60):
        raise api.SafeError('Use --failures to enable custom fault settings.')
    return seconds, {'GROT_CHAT_INTERVAL_SECONDS': str(chat_interval), 'GROT_CHAT_MAX_REQUESTS': str(chat_budget), 'GROT_CHAT_ERROR_EVERY': str(chat_error_every),
        'ALLOW_PAID_AI': str(bool(chat_interval and getattr(args, 'allow_paid_ai', False))).lower(), 'GROT_FAILURES': str(failures).lower(), 'GROT_ERROR_PERCENT': str(errors),
        'GROT_SLOW_PERCENT': str(slow), 'GROT_DELAY_MS': str(delay), 'GROT_FAULT_RATE': str(fault_rate), 'TARGET_AUTHORIZED': 'true', 'JOURNEYS_PER_MINUTE': str(rate),
        'BROWSER_JOURNEYS_PER_MINUTE': str(browsers), 'TRAFFIC_DURATION': args.duration,
        'TRAFFIC_PRESET': args.preset, 'K6_BROWSER_ARGS': 'no-sandbox', 'K6_BROWSER_HEADLESS': 'true'}


def kcommands(args):
    return ['kubectl', '--context', args.context, '-n', args.namespace, '--request-timeout=15s']


def docker_name(args):
    return 'grot-' + args.destination + '-traffic'


def docker_object(args, api):
    found = api.run(['docker', 'container', 'ls', '-a', '--filter', 'name=^/' + docker_name(args) + '$', '--format', '{{.ID}}'])
    if not found.strip(): return None
    return json.loads(api.run(['docker', 'container', 'inspect', docker_name(args)]))[0]


def stop(args, api):
    if args.context:
        kube = kcommands(args)
        for kind, name in (('cronjob', NAME), ('job', NAME), ('configmap', NAME), ('secret', CLOUD_SECRET)):
            obj = api.get_object(kube, kind, name)
            if not obj: continue
            if obj.get('metadata', {}).get('labels', {}).get(LABEL) != args.destination:
                raise api.SafeError('Refusing to remove traffic resources owned by another installation.')
            api.run(kube + ['delete', kind, name, '--cascade=foreground', '--wait=true', '--timeout=60s'])
    else:
        obj = docker_object(args, api)
        if obj:
            if obj.get('Config', {}).get('Labels', {}).get(LABEL) != args.destination:
                raise api.SafeError('Refusing to remove an unrelated container.')
            api.run(['docker', 'stop', '--time', '30', docker_name(args)])
            api.run(['docker', 'rm', docker_name(args)])


def status(args, api):
    if args.context:
        cron = api.get_object(kcommands(args), 'cronjob', NAME)
        if cron:
            if cron.get('metadata', {}).get('labels', {}).get(LABEL) != args.destination:
                raise api.SafeError('Traffic schedule belongs to another destination.')
            print(json.dumps({'cronjob': NAME, 'schedule': cron['spec']['schedule'], 'concurrencyPolicy': cron['spec']['concurrencyPolicy'], 'status': cron.get('status', {})}, indent=2))
            return
        obj = api.get_object(kcommands(args), 'job', NAME)
        if not obj: print('No demo traffic Job.'); return
        if obj.get('metadata', {}).get('labels', {}).get(LABEL) != args.destination:
            raise api.SafeError('Traffic Job belongs to another destination.')
        print(json.dumps({'job': NAME, 'status': obj.get('status', {})}, indent=2))
    else:
        obj = docker_object(args, api)
        if not obj: print('No demo traffic container.'); return
        if obj.get('Config', {}).get('Labels', {}).get(LABEL) != args.destination:
            raise api.SafeError('Traffic container belongs to another destination.')
        print(json.dumps({'container': docker_name(args), 'status': obj['State']['Status'], 'exitCode': obj['State']['ExitCode']}, indent=2))


def runner_failure(text, api):
    if 'Catalog image does not support request-scoped faults' in text:
        return api.SafeError('Deploy the updated catalog image before using --failures. No global chaos controls were changed. Stop this failed traffic runner before retrying.')
    limit = re.search(r'maximum allowed for your project \(([0-9]+) seconds\)', text)
    if limit:
        seconds = int(limit[1])
        duration = str(seconds // 3600) + 'h' if seconds % 3600 == 0 else str(seconds) + 's'
        return api.SafeError('Cloud k6 project duration limit is ' + duration + '. Stop the failed runner, then restart with --duration ' + duration + ' or less. Project limits were not changed.')
    return api.SafeError('k6 runner failed. Inspect its logs, then stop traffic to clean up. No local-only fallback was started.')


def verify_cloud_registration(args, env, api, job_name=NAME):
    """Match this runner's Cloud URL to the authenticated project's run history."""
    logs = kcommands(args) + ['logs', 'job/' + job_name, '--tail=2000'] if args.context else ['docker', 'logs', '--tail', '2000', docker_name(args)]
    base = ['gcx', '--context', args.grafana_context, 'k6']
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        text = api.run(logs)
        match = re.search(r'https://[a-zA-Z0-9.-]+\.grafana\.net/a/k6-app/runs/([0-9]+)', text)
        if match:
            runs = json.loads(api.run(base + ['runs', 'list', env['GROT_K6_TEST_NAME'], '--project-id', env['K6_CLOUD_PROJECT_ID'], '--limit', '0', '-o', 'json'])) or []
            if any(str(r['id']) == match[1] for r in runs):
                print('Cloud k6 registration verified: ' + match[0], flush=True)
                return
        if 'level=error' in text:
            raise runner_failure(text, api)
        time.sleep(3)
    raise api.SafeError('Runner started but Cloud k6 registration was not confirmed. Inspect logs or stop the traffic run.')


def run(args, api):
    if args.namespace and not args.context: raise api.SafeError('--namespace requires --context.')
    if args.action == 'stop':
        stop(args, api); print('Demo traffic stopped; app and monitoring unchanged.'); return
    if args.action == 'status': status(args, api); return
    if getattr(args, 'repeat', False) and not args.context:
        raise api.SafeError('--repeat currently requires Kubernetes; Docker runs remain bounded.')
    seconds, env = settings(args, api)
    runner_name = NAME
    cloud_env, token = cloud_settings(args, api)
    env.update(cloud_env)
    if args.context:
        kube = kcommands(args)
        ledger = api.get_object(kube, 'configmap', api.LEDGER)
        if not ledger or ledger.get('data', {}).get('destination') != args.destination or not api.owned(ledger, ledger['data'].get('owner')):
            raise api.SafeError('No matching Grot installation; refusing to generate traffic.')
        if api.get_object(kube, 'job', NAME) or api.get_object(kube, 'configmap', NAME) or api.get_object(kube, 'cronjob', NAME):
            raise api.SafeError('Traffic resources already exist. Stop traffic before changing settings or starting another run.')
        gateway = api.get_object(kube, 'secret', 'grot-gateway-runtime') or {}
        env['EXPECT_FARO'] = str(bool(gateway.get('data', {}).get('GRAFANA_FARO_URL'))).lower()
        env['BASE_URL'] = 'http://grot-gateway'
        env['GROT_FAULT_BASE_URL'] = 'http://catalog'
        labels = {LABEL: args.destination, 'app.kubernetes.io/name': NAME}
        if token:
            if api.get_object(kube, 'secret', CLOUD_SECRET):
                raise api.SafeError('Cloud k6 Secret already exists. Stop traffic to clean up owned resources before restarting.')
            api.run(kube + ['create', '-f', '-'], data=json.dumps({'apiVersion': 'v1', 'kind': 'Secret',
                'metadata': {'name': CLOUD_SECRET, 'labels': labels}, 'type': 'Opaque', 'stringData': {'token': token}}))
        cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': NAME, 'labels': labels},
              'data': {key: (api.ROOT / path).read_text() for key, path in FILES.items()}}
        api.run(kube + ['create', '-f', '-'], data=json.dumps(cm))
        job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': NAME, 'labels': labels},
               'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': seconds + 180, 'ttlSecondsAfterFinished': 3600,
                        'template': {'metadata': {'labels': labels}, 'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                            'containers': [{'name': 'k6', 'image': IMAGE, 'workingDir': '/work',
                                'args': ['run', '/work/tests/k6/traffic.js'],
                                'env': [{'name': k, 'value': v} for k, v in env.items()],
                                'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'cpu': '2', 'memory': '1536Mi'}},
                                'volumeMounts': [{'name': 'scripts', 'mountPath': '/work', 'readOnly': True}, {'name': 'shm', 'mountPath': '/dev/shm'}]}],
                            'volumes': [{'name': 'scripts', 'configMap': {'name': NAME, 'items': [{'key': k, 'path': v} for k, v in FILES.items()]}},
                                        {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '256Mi'}}]}}}}
        if token:
            spec = job['spec']['template']['spec']
            container = spec['containers'][0]
            container['command'] = ['/bin/sh', '-ec']
            container['args'] = [CLOUD_ENTRYPOINT]
            container['volumeMounts'].append({'name': 'cloud-auth', 'mountPath': '/run/k6-cloud', 'readOnly': True})
            spec['volumes'].append({'name': 'cloud-auth', 'secret': {'secretName': CLOUD_SECRET, 'defaultMode': 292}})
        if getattr(args, 'repeat', False):
            cron = {'apiVersion': 'batch/v1', 'kind': 'CronJob', 'metadata': {'name': NAME, 'labels': labels},
                    'spec': {'schedule': '* * * * *', 'timeZone': 'Etc/UTC', 'concurrencyPolicy': 'Forbid',
                             'startingDeadlineSeconds': 45, 'successfulJobsHistoryLimit': 1, 'failedJobsHistoryLimit': 1,
                             'jobTemplate': {'metadata': {'labels': labels}, 'spec': job['spec']}}}
            api.run(kube + ['create', '-f', '-'], data=json.dumps(cron))
            print('Recurring traffic scheduled: bounded runs, no overlap; continues until traffic stop. Waiting for first minute boundary...', flush=True)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                current = api.get_object(kube, 'cronjob', NAME) or {}
                active = current.get('status', {}).get('active', [])
                if active:
                    runner_name = active[0]['name']
                    break
                time.sleep(3)
            else: raise api.SafeError('Recurring schedule created but no active Job yet. Check traffic status; stop cancels the schedule.')
        else:
            api.run(kube + ['create', '-f', '-'], data=json.dumps(job))
        deadline = time.monotonic() + 180
        print('Waiting for the k6 runner (image pull may take a few minutes)...', flush=True)
        while time.monotonic() < deadline:
            pods = json.loads(api.run(kube + ['get', 'pods', '-l', 'job-name=' + runner_name, '-o', 'json']))['items']
            if any(p.get('status', {}).get('phase') in ('Running', 'Succeeded') for p in pods): break
            if any(p.get('status', {}).get('phase') == 'Failed' for p in pods):
                if getattr(args, 'repeat', False):
                    api.run(kube + ['patch', 'cronjob', NAME, '--type=merge', '-p', '{"spec":{"suspend":true}}'])
                raise runner_failure(api.run(kube + ['logs', 'job/' + runner_name, '--tail=100']), api)
            time.sleep(3)
        else: raise api.SafeError('k6 runner is not ready yet. Use traffic status and inspect the Job; it has a bounded deadline.')
        log_command = kube[:-1] + ['logs', '-f', 'job/' + runner_name]
    else:
        state = api.profile_path(args.destination) / 'run.json'
        if not state.exists(): raise api.SafeError('No matching local Grot deployment.')
        env['EXPECT_FARO'] = str(bool(json.loads(state.read_text()).get('faro'))).lower()
        if docker_object(args, api): raise api.SafeError('Traffic container already exists. Stop it before changing settings.')
        env['BASE_URL'] = 'http://gateway:8080'
        env['GROT_FAULT_BASE_URL'] = 'http://catalog:8080'
        command = ['docker', 'run', '-d', '--name', docker_name(args), '--label', LABEL + '=' + args.destination,
                   '--network', 'grot-' + args.destination + '_default', '--memory', '1536m', '--cpus', '2', '--shm-size', '256m',
                   '-v', str(api.ROOT / 'tests/k6') + ':/work/tests/k6:ro',
                   '-v', str(api.ROOT / 'src/catalog/grots.json') + ':/work/src/catalog/grots.json:ro', '-w', '/work']
        for key, value in env.items(): command += ['-e', key + '=' + value]
        if token:
            api.run(command + ['--tmpfs', '/run/k6-cloud:rw,noexec,nosuid,size=64k,mode=1777', '--entrypoint', '/bin/sh', IMAGE, '-ec', CLOUD_ENTRYPOINT])
            api.run(['docker', 'exec', '-i', docker_name(args), 'sh', '-ec',
                     'umask 077; cat > /run/k6-cloud/token'], data=token)
        else:
            api.run(command + [IMAGE, 'run', '/work/tests/k6/traffic.js'])
        time.sleep(2)
        obj = docker_object(args, api)
        if not obj or obj['State']['Status'] != 'running':
            raise runner_failure(api.run(['docker', 'logs', '--tail', '100', docker_name(args)]), api)
        log_command = ['docker', 'logs', '-f', docker_name(args)]
    print(f'Traffic started: {env["JOURNEYS_PER_MINUTE"]} shopping journeys/min + {env["BROWSER_JOURNEYS_PER_MINUTE"]} browser journeys/min, duration {args.duration}.')
    if env['GROT_CHAT_INTERVAL_SECONDS'] != '0':
        if env['GROT_CHAT_ERROR_EVERY'] != '0': print('Injected chat failure every ' + env['GROT_CHAT_ERROR_EVERY'] + ' requests; UI must explicitly enable synthetic faults.')
        print('Paid synthetic chat: one request every ' + env['GROT_CHAT_INTERVAL_SECONDS'] + ' seconds, maximum ' + env['GROT_CHAT_MAX_REQUESTS'] + ' per run. Recurring runs reset the budget.')
    if env['GROT_FAILURES'] == 'true':
        print('Synthetic catalog probes: ' + env['GROT_FAULT_RATE'] + '/min, ' + env['GROT_ERROR_PERCENT'] + '% errors, ' + env['GROT_SLOW_PERCENT'] + '% delayed by ' + env['GROT_DELAY_MS'] + ' ms. Percentages apply to probes, not shopping journeys.')
    print('Each journey makes multiple requests and creates a synthetic order. Rates are targets; capacity may limit throughput.')
    print('k6 logs/results: ' + api.shlex.join(log_command))
    if token:
        print('Cloud k6 run: ' + cloud_env['GROT_K6_TEST_NAME'] + ' (project ' + cloud_env['K6_CLOUD_PROJECT_ID'] + ').')
        try:
            verify_cloud_registration(args, cloud_env, api, job_name=runner_name)
        except api.SafeError:
            if getattr(args, 'repeat', False):
                api.run(kcommands(args) + ['patch', 'cronjob', NAME, '--type=merge', '-p', '{"spec":{"suspend":true}}'])
            raise
    else:
        print('LOCAL-ONLY: results stay in runner logs; no Cloud k6 run is created.')

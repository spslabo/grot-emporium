#!/usr/bin/env python3
"""One observability-destination contract; Compose and existing-cluster launch adapters."""
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import socket
import uuid
import shlex
from contextlib import contextmanager
from urllib.request import urlopen
try:
    from .grot_config import ROOT, TEMPLATES, private_path, validate as validate_settings
except ImportError:
    from grot_config import ROOT, TEMPLATES, private_path, validate as validate_settings

class SafeError(Exception):
    """An operator-facing message built only from fixed, non-secret text."""

CONFIG_ROOT = Path.home() / '.local/state/grot-emporium'
SECRET_NAMES = {'backend': 'grot-backend-runtime', 'ui': 'grot-ui-runtime',
    'alloy': 'grot-collector-runtime', 'gateway': 'grot-gateway-runtime'}
LEDGER = 'grot-installation'
OWNER = 'grot.emporium/owner'
MANAGER = 'grot-launcher'
SIGNALS = {
    'metrics': 'prometheus_remote_storage_samples_total',
    'logs': 'loki_write_sent_entries_total',
    'traces': 'otelcol_exporter_sent_spans_total',
    'profiles': 'pyroscope_write_sent_profiles_total',
}


def profile_path(name):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name):
        raise SafeError('Use a short lowercase destination alias, not a URL')
    path = private_path(CONFIG_ROOT / name, must_exist=False)
    if path.exists() and (not path.is_dir() or path.stat().st_mode & 0o077 or (hasattr(os, 'getuid') and path.stat().st_uid != os.getuid())):
        raise SafeError('Deployment state directory must be owner-only')
    return path


def run(command, *, env=None, data=None, visible=False):
    try:
        result = subprocess.run(command, cwd=ROOT, env=env, input=data, text=True,
            timeout=60 if command[0] == 'gcx' else None,
            stdout=None if visible else subprocess.PIPE, stderr=None if visible else subprocess.PIPE)
    except subprocess.TimeoutExpired:
        raise SafeError('gcx query timed out after 60 seconds; check connectivity and retry') from None
    if result.returncode:
        if command[0] == 'gcx':
            detail = ((result.stderr or '') + (result.stdout or '')).lower()
            reasons = [
                (r'\b401\b|unauthorized|expired.*token|not authenticated', 'authentication failed; sign in to the selected gcx context again'),
                (r'\b403\b|forbidden|access denied', 'access denied; check datasource query permissions'),
                (r'\b404\b|datasource.*not found', 'datasource or API endpoint not found'),
                (r'\b429\b|rate limit', 'Cloud query rate limit reached; retry later'),
                (r'unknown (flag|command)', 'gcx command/version mismatch; update gcx'),
                (r'timeout|deadline exceeded|connection refused|no such host', 'network connection or query timed out'),
                (r'parse error|invalid query|syntax error', 'query rejected; check verifier/query compatibility'),
            ]
            reason = next((message for pattern, message in reasons if re.search(pattern, detail)),
                'command failed; check gcx context connectivity and datasource availability')
            raise SafeError(f'gcx: {reason} (exit {result.returncode})')
        raise SafeError(f'{command[0]} failed (exit {result.returncode}); private command output was not displayed. Check the current operation and documented prerequisites.')
    return result.stdout or ''


def run_probe(command, label):
    """Report progress without dumping subprocess output that may contain private data."""
    print(label + ' — starting', flush=True)
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=10)
                break
            except subprocess.TimeoutExpired:
                print(f'{label} — still running ({int(time.monotonic() - started)}s)', flush=True)
        if process.returncode:
            output = (stdout or '') + (stderr or '')
            reasons = {
                'GROT_VERIFY_UI_OUTDATED': 'the running UI lacks the cart fixes; rebuild and restart the UI service',
                'GROT_VERIFY_CART_DUPLICATES': 'repeated additions created duplicate product rows; rebuild/restart the cart service with the quantity fix',
                'GROT_VERIFY_FARO_FAILED': 'no successful Faro export, or a rejected export; check the Faro URL, allowed origins and gateway',
            }
            reason = next((text for marker, text in reasons.items() if marker in output), None)
            if reason is None:
                if re.search(r'timeout|timed out', output, re.I):
                    reason = 'timed out waiting for a page or request; check the running app and test/image versions'
                else:
                    reason = 'a probe request, assertion or threshold failed; check the app and test/image versions'
            location = re.search(r'file:///work/tests/k6/(shopping|browser)\.js:(\d+):(\d+)', output)
            if location: reason += f' (tests/k6/{location[1]}.js:{location[2]})'
            raise SafeError(f'{label} failed: {reason} (exit {process.returncode})')
        print(label + ' — passed', flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.communicate(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.communicate()


def save(path, value):
    path = private_path(path, must_exist=Path(path).exists())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file: file.write(value)


def validate(role, values, *, partial=False):
    try:
        if not isinstance(values, dict) or any(not isinstance(v, str) or len(v) > 8192 or any(c in v for c in '\x00\r\n') for v in values.values()):
            raise ValueError('Settings must contain single-line string values')
        validate_settings(role, values, partial=partial)
    except ValueError as error:
        # This validator only emits fixed reasons/schema keys, never values.
        raise SafeError(f'{role} configuration: {error}') from None


def validate_managed(roles):
    expected = {'OTEL_SDK_DISABLED': 'false', 'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://alloy:4318',
        'PYROSCOPE_ENABLED': 'true', 'PYROSCOPE_SERVER_ADDRESS': 'http://alloy:4040'}
    for key, value in expected.items():
        if roles['backend'].get(key) != value:
            raise SafeError(f'Managed collector setup requires the internal backend setting for {key}; use the launch prompt to generate it')
    if any(roles['backend'].get(key) for key in ('OTEL_EXPORTER_OTLP_HEADERS', 'PYROSCOPE_BASIC_AUTH_USER', 'PYROSCOPE_BASIC_AUTH_PASSWORD')):
        raise SafeError('Managed cloud ingestion credentials belong only in the collector role, not backend headers/auth')
    if roles['backend'].get('DEPLOYMENT_ENVIRONMENT', 'demo') != roles['alloy']['DEPLOYMENT_ENVIRONMENT']:
        raise SafeError('Backend and collector deployment environments must match')
    faro = bool(roles['gateway'].get('GRAFANA_FARO_URL'))
    if (roles['ui'].get('FARO_ENABLED') == 'true') != faro or (faro and roles['ui'].get('FARO_COLLECTOR_URL') != '/telemetry'):
        raise SafeError('Managed Faro enablement must match the gateway destination and use /telemetry')


def fingerprint(roles):
    endpoints = [roles['alloy'][k] for k in sorted(roles['alloy']) if k.endswith(('_URL', '_ENDPOINT', '_USER'))]
    endpoints.append(roles['gateway'].get('GRAFANA_FARO_URL', ''))
    return hashlib.sha256('\n'.join(endpoints).encode()).hexdigest()


def make_roles(settings):
    """One schema for prompted setup, stdin automation, and both platforms."""
    if not isinstance(settings, dict) or set(settings) - set(TEMPLATES) or any(not isinstance(value, dict) for value in settings.values()):
        raise SafeError('Expected settings grouped by backend, ui, alloy and gateway roles')
    roles = {role: dict(line.split('=', 1) for line in text.splitlines()) for role, text in TEMPLATES.items()}
    for role in ('alloy', 'gateway'):
        roles[role].update(settings.get(role, {}))
        validate(role, roles[role])
    environment = roles['alloy']['DEPLOYMENT_ENVIRONMENT']
    roles['backend'].update(OTEL_SDK_DISABLED='false', OTEL_EXPORTER_OTLP_ENDPOINT='http://alloy:4318',
        PYROSCOPE_ENABLED='true', PYROSCOPE_SERVER_ADDRESS='http://alloy:4040', DEPLOYMENT_ENVIRONMENT=environment,
        OTEL_RESOURCE_ATTRIBUTES=f'service.namespace=grot-emporium,deployment.environment={environment},deployment.environment.name={environment}',
        PYROSCOPE_LABELS=f'service_namespace=grot-emporium,deployment_environment={environment}')
    roles['ui'].update(OTEL_METRICS_EXPORTER='otlp',
        FARO_ENABLED=str(bool(roles['gateway']['GRAFANA_FARO_URL'])).lower(), FARO_COLLECTOR_URL='/telemetry')
    for role in ('backend', 'ui'): roles[role].update(settings.get(role, {}))
    for role, values in roles.items(): validate(role, values)
    validate_managed(roles)
    return roles


def prompt_setting(label, role, key, *, optional=False):
    """Validate one hidden input; retain other answers only in process memory."""
    while True:
        value = getpass.getpass(label + ': ')
        try:
            if not value and not optional:
                raise SafeError('This field is required.')
            if value and value != value.strip():
                raise SafeError('Remove leading or trailing whitespace.')
            validate(role, {key: value}, partial=True)
            if value and key.endswith(('_USER', '_TOKEN')) and any(c.isspace() for c in value):
                raise SafeError('Ingestion usernames and tokens must not contain whitespace.')
            return value
        except SafeError as error:
            print(f'{error} Re-enter this field; earlier answers are still held in memory.')


def settings(args):
    if args.settings_stdin:
        raw = sys.stdin.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024: raise SafeError('Settings exceed the bounded input size')
        return make_roles(json.loads(raw))
    if not sys.stdin.isatty(): raise SafeError('Use an interactive terminal or --settings-stdin; credentials are never command arguments')
    print('Telemetry setup: metrics, logs, traces, profiles and optional Faro. Inputs are hidden and not saved to host files.')
    print('Optional AI chat is configured separately: docs/optional-ai-chat.md (not by these prompts).')
    collector = {'GROT_CLUSTER': args.destination}
    for signal, endpoint, label in [('OTLP', 'ENDPOINT', 'OTLP (Traces)'),
            ('METRICS', 'URL', 'Metrics (Prometheus remote write)'),
            ('LOGS', 'URL', 'Logs (Loki push)'), ('PROFILES', 'URL', 'Profiles (Pyroscope)')]:
        key = f'GRAFANA_{signal}_{endpoint}'
        collector[key] = prompt_setting(f'{label} ingestion endpoint', 'alloy', key)
        key = f'GRAFANA_{signal}_USER'
        collector[key] = prompt_setting(f'{label} ingestion username (from connection instructions)', 'alloy', key)
    token = prompt_setting('Shared ingestion API token (traces:write, metrics:write, logs:write, profiles:write)',
        'alloy', 'GRAFANA_OTLP_TOKEN')
    for signal in ('OTLP', 'METRICS', 'LOGS', 'PROFILES'): collector[f'GRAFANA_{signal}_TOKEN'] = token
    gateway = {'GRAFANA_FARO_URL': prompt_setting('Faro (Browser) collector URL (blank disables browser export)',
        'gateway', 'GRAFANA_FARO_URL', optional=True)}
    return make_roles({'alloy': collector, 'gateway': gateway})


def compose(path, args, state=None):
    env = dict(os.environ)
    for role in TEMPLATES: env[f'GROT_{role.upper()}_ENV_FILE'] = '/dev/null'
    values = state or vars(args)
    env.update(GROT_PORT=str(values.get('port', 8080)), GROT_SYSLOG_PORT=str(values.get('syslog_port', 15140)),
        GROT_COLLECTOR_PORT=str(values.get('collector_port', 12345)),
        GROT_IMAGE_PREFIX='grot', GROT_IMAGE_TAG='local', COMPOSE_PARALLEL_LIMIT='2')
    command = ['docker', 'compose', '-p', 'grot-' + args.destination, '-f', 'deploy/docker/compose.yaml', '-f', 'deploy/docker/compose.telemetry.yaml', '-f', 'deploy/docker/compose.runtime.yaml']
    return command, env


def runtime_volumes(destination):
    return {role: f'grot-{destination}_{role}-runtime' for role in TEMPLATES}


def stage_runtime(command, env, destination, roles):
    run(command + ['up', '-d', '--no-deps', 'runtime'], env=env)
    # Refuse a preexisting disk-backed or foreign volume BEFORE writing any values.
    volumes = json.loads(run(['docker', 'volume', 'inspect'] + list(runtime_volumes(destination).values())))
    for volume in volumes:
        if volume.get('Driver') != 'local' or (volume.get('Options') or {}).get('type') != 'tmpfs' or (volume.get('Labels') or {}).get('com.docker.compose.project') != 'grot-' + destination:
            raise SafeError('Runtime credentials require demo-owned tmpfs volumes; refusing persistent or foreign storage')
    for role, values in roles.items():
        validate(role, values)
        data = ''.join(f'{key}={shlex.quote(value)}\n' for key, value in values.items())
        # stdin only. The command and Docker configuration never contain credentials.
        run(command + ['exec', '-T', 'runtime', 'sh', '-c',
            f'umask 077; chmod 600 /secrets/{role}/values.sh 2>/dev/null || true; cat > /secrets/{role}/values.sh && chmod 444 /secrets/{role}/values.sh'], env=env, data=data)


def remove_runtime_volumes(destination, include_data=False):
    volumes = list(runtime_volumes(destination).values())
    if include_data: volumes.append('grot-' + destination + '_alloy-data')
    for volume in volumes:
        # Runtime tmpfs, and optionally this project's telemetry buffer, are cleanup candidates.
        found = run(['docker', 'volume', 'ls', '--filter', 'name=^' + volume + '$', '--format', '{{.Name}}']).splitlines()
        if volume not in found: continue
        info = json.loads(run(['docker', 'volume', 'inspect', volume]))[0]
        ours = (info.get('Labels') or {}).get('com.docker.compose.project') == 'grot-' + destination
        memory = (info.get('Options') or {}).get('type') == 'tmpfs'
        if ours and (memory or (include_data and volume.endswith('_alloy-data'))):
            run(['docker', 'volume', 'rm', volume])
        elif include_data: raise SafeError('Refusing to delete an unowned or unexpected volume; ownership state was retained')


def docker(args):
    path = profile_path(args.destination)
    roles = settings(args)
    state_path = path / 'run.json'
    old = json.loads(state_path.read_text()) if state_path.exists() else {}
    if old.get('fingerprint') not in (None, fingerprint(roles)):
        raise SafeError('Destination URLs changed. Use a new alias to isolate queued telemetry; never retarget an old WAL')
    ports = (args.port, args.syslog_port, args.collector_port)
    if any(port < 1 or port > 65535 for port in ports) or len(set(ports)) != 3:
        raise SafeError('Choose three distinct TCP ports in the range 1–65535')
    version = re.search(r'(\d+)\.(\d+)', run(['docker', 'compose', 'version', '--short']))
    if not version or tuple(map(int, version.groups())) < (2, 30):
        raise SafeError('Docker Compose 2.30+ is required for raw, non-interpolated private env files')
    if not old.get('fingerprint'):
        volume = 'grot-' + args.destination + '_alloy-data'
        existing = run(['docker', 'volume', 'ls', '--filter', 'name=^' + volume + '$', '--format', '{{.Name}}'])
        if volume in existing.splitlines():
            raise SafeError('An unbound collector buffer already exists for this alias. Choose a new alias; do not silently reuse another destination\'s queue')
    command, env = compose(path, args)
    print('Building shared app images (no destination settings are build arguments)...', flush=True)
    run(command + ['build'], env=env, visible=True)
    print('Starting the app, collector and private Faro proxy...', flush=True)
    # Bind the buffer before starting it, including when startup subsequently fails.
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    save(state_path, json.dumps(dict(port=args.port, syslog_port=args.syslog_port,
        collector_port=args.collector_port, fingerprint=fingerprint(roles), faro=bool(roles['gateway']['GRAFANA_FARO_URL']))))
    try:
        stage_runtime(command, env, args.destination, roles)
        # Receiver must be ready before Docker initializes application syslog drivers.
        for services in (['alloy'], ['catalog', 'cart', 'orders', 'checkout', 'ui'], ['gateway']):
            run(command + ['up', '-d', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180'] + services, env=env)
    except BaseException:
        # A failed/aborted launch must not strand staged credentials. Retain only the bound telemetry WAL.
        try:
            run(command + ['down'], env=env)
        finally:
            remove_runtime_volumes(args.destination)
        raise
    print(f'Storefront ready at http://localhost:{args.port}. Delivery is not yet verified: ./grot verify {args.destination}')


def stop(args):
    if args.context or args.namespace:
        if not args.context or not args.namespace: raise SafeError('Kubernetes stop requires both --context and --namespace')
        kube = ['kubectl', '--context', args.context, '-n', args.namespace]
        helm = ['helm', '--kube-context', args.context, '-n', args.namespace]
        ledger = get_object(kube, 'configmap', LEDGER)
        if not ledger or ledger.get('data', {}).get('destination') != args.destination or not owned(ledger, ledger['data'].get('owner')):
            raise SafeError('No matching launcher ownership record; refusing cleanup')
        releases = helm_releases(helm)
        names = [r['name'] for r in releases if r['name'] in ('grot', 'grot-telemetry')]
        if names: run(helm + ['uninstall'] + names + ['--cascade', 'foreground', '--wait', '--timeout', '180s'])
        if ledger['data']['mode'] == 'quick':
            for name in SECRET_NAMES.values(): delete_owned(kube, args.namespace, 'secrets', name, ledger['data']['owner'])
        delete_owned(kube, args.namespace, 'configmaps', LEDGER, ledger['data']['owner'])
        print('Removed demo releases and quick-mode-owned credentials. External Secrets and namespace were retained.')
        return
    path = profile_path(args.destination)
    state = json.loads((path / 'run.json').read_text())
    command, env = compose(path, args, state)
    run(command + ['down'], env=env)
    remove_runtime_volumes(args.destination, include_data=True)
    (path / 'run.json').unlink()
    print('Removed this demo, its runtime credentials and its telemetry buffers. Other projects were untouched.')


def counters(url):
    with urlopen(url, timeout=10) as response: text = response.read().decode()
    result = {signal: 0.0 for signal in SIGNALS}
    for line in text.splitlines():
        match = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{.*\})?\s+([0-9.eE+-]+)', line)
        if not match: continue
        for signal, metric in SIGNALS.items():
            if match[1] == metric: result[signal] += float(match[2])
    return result


def verify_transport(metrics_url, before, timeout=120):
    deadline = time.monotonic() + timeout
    after = dict(before)
    announced = set()
    last_report = time.monotonic()
    print('Exporter delivery — waiting for fresh metrics, logs, traces and profiles acknowledgements', flush=True)
    while time.monotonic() < deadline:
        after = counters(metrics_url)
        for key in SIGNALS:
            if after[key] > before[key] and key not in announced:
                announced.add(key)
                print(f'  {key}: fresh destination acknowledgement received', flush=True)
        if time.monotonic() - last_report >= 15:
            print('  Still waiting for: ' + ', '.join(key for key in SIGNALS if key not in announced), flush=True)
            last_report = time.monotonic()
        if all(after[key] > before[key] for key in SIGNALS):
            print('Destination transport accepted fresh metrics, logs, traces and profiles (not merely receiver readiness).')
            print('Confirm query-side visibility in the chosen stack before a customer demo; write-only tokens cannot prove indexing.')
            return
        time.sleep(3)
    raise SafeError('No fresh export acknowledgement for: ' + ', '.join(k for k in SIGNALS if after[k] <= before[k]) + '. Check collection, destination permissions/endpoints and network access; this alone does not diagnose a firewall.')


def verify_cloud(args):
    try:
        from .grot_cloud import verify as check_cloud
    except ImportError:
        from grot_cloud import verify as check_cloud
    return check_cloud(args, run, SafeError)


def verify(args):
    if not getattr(args, 'grafana_context', None):
        print('Transport-only verification; add --grafana-context CONTEXT for gcx indexing checks.', flush=True)
        return verify_local(args)
    failed = []
    for label, check in [('Local probes/transport', verify_local), ('Cloud indexing', verify_cloud)]:
        try: check(args)
        except (SafeError, ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            failed.append(label)
            print(str(error) if isinstance(error, SafeError) else label + ' failed; private output suppressed', flush=True)
    if failed: raise SafeError('Verification incomplete: ' + ', '.join(failed))


def verify_local(args):
    if args.context or args.namespace:
        if not args.context or not args.namespace:
            raise ValueError('Kubernetes verification requires both --context and --namespace')
        return verify_k8s(args)
    path = profile_path(args.destination)
    state = json.loads((path / 'run.json').read_text())
    metrics_url = f'http://127.0.0.1:{state["collector_port"]}/metrics'
    print('Reading baseline Alloy exporter counters...', flush=True)
    before = counters(metrics_url)
    for script, image in [('shopping', 'grafana/k6:2.3.0'), ('browser', 'grafana/k6:2.3.0-with-browser')]:
        label = ('HTTP shopping: catalog, cart and synthetic checkout' if script == 'shopping' else
            'Chromium browser: cart deletion, image layout, checkout and Faro')
        run_probe(['docker', 'run', '--rm', '--network', f'grot-{args.destination}_default', '-v', str(ROOT / 'tests/k6') + ':/work/tests/k6:ro',
            '-v', str(ROOT / 'src/catalog/grots.json') + ':/work/src/catalog/grots.json:ro', '-w', '/work',
            '-e', 'K6_BROWSER_ARGS=no-sandbox', image, 'run', '-e', 'BASE_URL=http://gateway:8080',
            '-e', 'TARGET_AUTHORIZED=true', '-e', 'VERIFY_TELEMETRY=true',
            '-e', 'EXPECT_FARO=' + str(state['faro']).lower(), f'tests/k6/{script}.js'], label)
    verify_transport(metrics_url, before)
    if state['faro']:
        print('Faro destination acknowledged browser telemetry through the private proxy. Query-side indexing still needs stack-side confirmation.')
    else: print('Faro intentionally disabled for this destination.')


@contextmanager
def forwarded_collector(args):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    process = subprocess.Popen(['kubectl', '--context', args.context, '-n', args.namespace,
        'port-forward', '--address=127.0.0.1', 'service/alloy', f'{port}:12345'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f'http://127.0.0.1:{port}/metrics'
        for _ in range(30):
            if process.poll() is not None: raise RuntimeError('Collector port-forward failed')
            try: counters(url); break
            except OSError: time.sleep(1)
        else: raise RuntimeError('Collector port-forward did not become ready')
        yield url
    finally:
        process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill(); process.wait()


def verify_k8s(args):
    kube = ['kubectl', '--context', args.context, '-n', args.namespace]
    values = json.loads(run(['helm', '--kube-context', args.context, '-n', args.namespace,
        'get', 'values', 'grot-telemetry', '-o', 'json']))
    if values.get('destinationId') != args.destination:
        raise ValueError('Destination does not match this namespace')
    gateway = json.loads(run(kube + ['get', 'secret', 'grot-gateway-runtime', '-o', 'json']))
    faro = bool(base64.b64decode(gateway.get('data', {}).get('GRAFANA_FARO_URL', '')).decode())
    name = 'grot-verify-' + uuid.uuid4().hex[:10]
    files = {'shopping.js': 'tests/k6/shopping.js', 'browser.js': 'tests/k6/browser.js', 'grots.json': 'src/catalog/grots.json'}
    config = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name},
        'data': {key: (ROOT / path).read_text() for key, path in files.items()}}
    run(kube + ['create', '-f', '-'], data=json.dumps(config))
    try:
        with forwarded_collector(args) as metrics_url:
            before = counters(metrics_url)
            for script, image in [('shopping', 'grafana/k6:2.3.0'), ('browser', 'grafana/k6:2.3.0-with-browser')]:
                pod_name = name + '-' + script
                pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': pod_name}, 'spec': {
                    'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'k6', 'image': image, 'workingDir': '/work',
                        'args': ['run', '-e', 'BASE_URL=http://grot-gateway:80', '-e', 'TARGET_AUTHORIZED=true',
                            '-e', 'VERIFY_TELEMETRY=true', '-e', 'EXPECT_FARO=' + str(faro).lower(), 'tests/k6/' + script + '.js'],
                        'env': [{'name': 'K6_BROWSER_ARGS', 'value': 'no-sandbox'}],
                        'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'memory': '1Gi'}},
                        'volumeMounts': [{'name': 'scripts', 'mountPath': '/work', 'readOnly': True}]}],
                    'volumes': [{'name': 'scripts', 'configMap': {'name': name,
                        'items': [{'key': key, 'path': path} for key, path in files.items()]}}]}}
                print(f'Kubernetes {script} probe — creating temporary k6 pod', flush=True)
                run(kube + ['create', '-f', '-'], data=json.dumps(pod))
                try:
                    for attempt in range(90):
                        status = json.loads(run(kube + ['get', 'pod', pod_name, '-o', 'json']))['status']
                        if status.get('phase') == 'Succeeded':
                            print(f'Kubernetes {script} probe — passed', flush=True)
                            break
                        if attempt % 5 == 0: print(f'Kubernetes {script} probe — {status.get("phase", "waiting")} ({attempt * 2}s)', flush=True)
                        if status.get('phase') == 'Failed': raise SafeError(f'Kubernetes {script} probe failed; private pod logs were not displayed')
                        time.sleep(2)
                    else: raise RuntimeError('Verification pod timed out')
                finally: run(kube + ['delete', 'pod', pod_name, '--ignore-not-found=true', '--wait=false'])
            verify_transport(metrics_url, before)
    finally: run(kube + ['delete', 'configmap', name, '--ignore-not-found=true'])
    print('Faro delivery acknowledgement verified.' if faro else 'Faro intentionally disabled for this destination.')


def helm_releases(helm):
    # Helm 4 removed --all/-a; explicit status filters work with Helm 3 and 4.
    return json.loads(run(helm + ['list', '--deployed', '--failed', '--pending',
        '--uninstalled', '--uninstalling', '--superseded', '-o', 'json']))


def get_object(kube, kind, name):
    raw = run(kube + ['get', kind, name, '--ignore-not-found', '--show-managed-fields=true', '-o', 'json'])
    return json.loads(raw) if raw.strip() else None


def owned(obj, owner):
    if not isinstance(owner, str) or not re.fullmatch('[0-9a-f]{32}', owner): return False
    metadata = obj.get('metadata', {})
    if metadata.get('ownerReferences') or any(field.get('manager') != MANAGER for field in metadata.get('managedFields', [])):
        return False  # A controller/operator adopted or modified it: leave it alone.
    labels = metadata.get('labels', {})
    return labels.get(OWNER) == owner and labels.get('app.kubernetes.io/managed-by') == MANAGER


def delete_owned(kube, namespace, kind, name, owner):
    obj = get_object(kube, kind, name)
    if not obj or not owned(obj, owner): return
    # Compare-and-delete: don't delete a replacement or externally modified object.
    body = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {
        'uid': obj['metadata']['uid'], 'resourceVersion': obj['metadata']['resourceVersion']}}
    run(kube + ['delete', '--raw', f'/api/v1/namespaces/{namespace}/{kind}/{name}', '-f', '-'], data=json.dumps(body))


def k8s(args):
    if not re.fullmatch(r'[a-z0-9][a-z0-9./:_-]*', args.image_prefix) or '://' in args.image_prefix or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', args.image_tag):
        raise ValueError('Supply a registry/repository prefix and an immutable version tag, not a URL or Helm expression')
    if not re.fullmatch(r'grot-[a-z0-9](?:[a-z0-9-]{0,53}[a-z0-9])?', args.namespace):
        raise ValueError('Use a dedicated grot-* namespace; shared/production namespaces are not installation targets')
    profile_path(args.destination)  # Validate the alias; no local credential files.
    quick = args.mode == 'quick'
    if not quick and args.settings_stdin: raise SafeError('Long-term mode reads existing Secrets, not stdin settings')
    if args.pull_secret and not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,62}', args.pull_secret):
        raise SafeError('Invalid pull Secret name')
    kube = ['kubectl', '--context', args.context, '-n', args.namespace]
    helm = ['helm', '--kube-context', args.context, '-n', args.namespace]
    # Long-term operators need only namespaced permissions, not cluster-wide namespace reads.
    namespace = get_object(kube, 'namespace', args.namespace) if quick else True
    roles = settings(args) if quick else {}
    if not namespace: run(kube + ['create', 'namespace', args.namespace])
    print('Using the selected existing cluster; no cloud infrastructure is provisioned.', flush=True)
    ledger = get_object(kube, 'configmap', LEDGER)
    if ledger and (ledger.get('data', {}).get('destination') != args.destination or ledger['data'].get('mode') != args.mode or not owned(ledger, ledger['data'].get('owner'))):
        raise SafeError('Namespace is bound to another destination/mode; use a separate namespace')
    existing = helm_releases(helm)
    if not ledger and any(r['name'] in ('grot', 'grot-telemetry') for r in existing):
        raise SafeError('Existing releases have no launcher ownership record; refusing to adopt them')
    owner = ledger['data']['owner'] if ledger else uuid.uuid4().hex
    current = {role: get_object(kube, 'secret', name) for role, name in SECRET_NAMES.items()}
    for role, obj in current.items():
        if quick:
            if obj and not owned(obj, owner): raise SafeError('Quick mode will not overwrite an externally managed Secret')
        else:
            if not obj: raise SafeError('Long-term mode requires all four existing runtime Secrets')
            roles[role] = {k: base64.b64decode(v).decode() for k, v in obj.get('data', {}).items()}
            validate(role, roles[role])
    validate_managed(roles)
    if ledger and ledger['data'].get('fingerprint') != fingerprint(roles):
        raise SafeError('Endpoints/tenant IDs changed; use a new destination namespace')
    labels = {OWNER: owner, 'app.kubernetes.io/managed-by': MANAGER}
    if not ledger:
        obj = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': LEDGER, 'labels': labels},
            'data': {'destination': args.destination, 'mode': args.mode, 'owner': owner, 'fingerprint': fingerprint(roles)}}
        run(kube + ['create', '--field-manager=' + MANAGER, '-f', '-'], data=json.dumps(obj))
    # Ownership is recorded before mutation so stop can clean up a partial install.
    if quick:
        for role, name in SECRET_NAMES.items():
            obj = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'labels': labels},
                'type': 'Opaque', 'data': {k: base64.b64encode(v.encode()).decode() for k, v in roles[role].items()}}
            if current[role]: obj['metadata']['resourceVersion'] = current[role]['metadata']['resourceVersion']
            run(kube + ['replace' if current[role] else 'create', '--field-manager=' + MANAGER, '-f', '-'], data=json.dumps(obj))
    run(['helm', 'dependency', 'build', 'src/app/chart'])
    # Helm 3 and 4 use different rollback flag names.
    rollback = '--rollback-on-failure' if '--rollback-on-failure' in run(['helm', 'upgrade', '--help']) else '--atomic'
    flags = ['--wait', '--timeout', '5m', rollback]
    command = helm + ['upgrade', '--install', 'grot', 'src/app/chart', '-f', 'src/app/chart/values-grot.yaml',
        '-f', 'src/app/chart/values-grot-profiles.yaml', '--set', 'global.grotBackendSecret=grot-backend-runtime', '--set', 'ui.runtimeSecret=grot-ui-runtime']
    command += ['--set-string', 'grotTelemetry.version=' + args.image_tag,
        '--set-string', 'grotTelemetry.environment=' + roles['alloy']['DEPLOYMENT_ENVIRONMENT'],
        '--set-string', 'grotTelemetry.cluster=' + roles['alloy']['GROT_CLUSTER']]
    if args.pull_secret:
        run(kube + ['get', 'secret', args.pull_secret, '-o', 'name'])
    for service in ('ui', 'cart', 'orders', 'catalog', 'checkout'):
        command += ['--set-string', f'{service}.image.repository={args.image_prefix}/{service}', '--set-string', f'{service}.image.tag={args.image_tag}']
        command += ['--set-string', f'{service}.podLabels.deployment\\.environment=' + roles['alloy']['DEPLOYMENT_ENVIRONMENT']]
        if args.pull_secret: command += ['--set-string', f'{service}.imagePullSecrets[0].name={args.pull_secret}']
    run(command + flags)
    run(helm + ['upgrade', '--install', 'grot-telemetry', 'deploy/telemetry-chart', '--set-string', 'destinationId=' + args.destination,
        '--set-string', 'destinationFingerprint=' + fingerprint(roles)] + flags)
    # Env-based Secret rotations require new pods, even if the chart did not change.
    deployments = ['ui', 'carts', 'orders', 'catalog', 'checkout', 'grot-alloy', 'grot-gateway']
    run(kube + ['rollout', 'restart'] + ['deployment/' + name for name in deployments])
    for name in deployments: run(kube + ['rollout', 'status', 'deployment/' + name, '--timeout=180s'])
    print('Installed app + collector + gateway. Run ./grot verify with the same destination, --context and --namespace. No public ingress was created.')


def main():
    parser = argparse.ArgumentParser(prog='grot', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    start = sub.add_parser('docker', help='Quick Compose demo; runtime-only credentials')
    start.add_argument('destination')
    start.add_argument('--settings-stdin', action='store_true', help='Read role-grouped JSON from stdin instead of hidden prompts')
    start.add_argument('--port', type=int, default=8080)
    start.add_argument('--syslog-port', type=int, default=15140)
    start.add_argument('--collector-port', type=int, default=12345)
    shutdown = sub.add_parser('stop')
    shutdown.add_argument('destination'); shutdown.add_argument('--context'); shutdown.add_argument('--namespace')
    check = sub.add_parser('verify')
    check.add_argument('destination'); check.add_argument('--context'); check.add_argument('--namespace')
    cloud = sub.add_parser('verify-cloud', help='Read-only Grafana Cloud indexing check using gcx; no probes or restarts')
    cloud.add_argument('destination')
    for target in (check, cloud):
        target.add_argument('--grafana-context', required=target is cloud, help='Explicit authenticated gcx context; never inferred from destination alias')
        target.add_argument('--cloud-cluster', help='GROT_CLUSTER label override; defaults to destination alias')
    install = sub.add_parser('k8s')
    install.add_argument('destination'); install.add_argument('--context', required=True)
    install.add_argument('--namespace', help='Dedicated namespace; defaults to grot-<destination>')
    install.add_argument('--image-prefix', required=True); install.add_argument('--image-tag', required=True)
    install.add_argument('--mode', choices=['quick', 'long-term'], required=True,
        help='quick creates demo-owned Secrets; long-term references existing Secrets without modifying them')
    install.add_argument('--settings-stdin', action='store_true', help='Quick mode: read role-grouped JSON from stdin')
    install.add_argument('--pull-secret', help='Existing registry pull Secret name, never credential values')
    args = parser.parse_args()
    try:
        profile_path(args.destination)
        if getattr(args, 'context', None) and not args.namespace: args.namespace = 'grot-' + args.destination
        {'docker': docker, 'stop': stop, 'verify': verify, 'verify-cloud': verify_cloud, 'k8s': k8s}[args.command](args)
    except KeyboardInterrupt:
        parser.exit(130, 'Cancelled. For a partial Kubernetes install, use grot stop with the same context and namespace.\n')
    except SafeError as error:
        parser.exit(1, str(error) + '\n')
    except (ValueError, RuntimeError, OSError, UnicodeError, subprocess.SubprocessError):
        # External command/parser exceptions can contain URLs/credentials. Don't echo them.
        parser.exit(1, 'Operation failed. Check configuration, tool availability, permissions and the documented prerequisites. Private values/output were not printed.\n')

if __name__ == '__main__': main()

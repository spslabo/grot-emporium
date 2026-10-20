"""Cluster-scoped infrastructure installation, separate from app lifecycle.

Credentials travel only through kubectl stdin into an owned Secret. Helm receives
public configuration and environment references, never ingestion URLs or tokens.
"""
import base64
import hashlib
import json
import re
import time

NAMESPACE = 'grot-monitoring'
RELEASE = 'grot-infrastructure'
COLLECTOR = 'grot-infrastructure-collector'
SECRET = 'grot-infrastructure-runtime'
LEDGER = 'grot-infrastructure-installation'
CHART_VERSION = '4.5.3'
REPO = 'https://grafana.github.io/helm-charts'
KEYS = tuple(f'GRAFANA_{signal}_{key}' for signal in ('METRICS', 'LOGS') for key in ('URL', 'USER', 'TOKEN'))


def binding(collector):
    return hashlib.sha256('\n'.join([collector['GROT_CLUSTER']] + [collector[k] for k in KEYS if not k.endswith('_TOKEN')]).encode()).hexdigest()


def commands(args):
    return (['kubectl', '--context', args.context, '-n', NAMESPACE, '--request-timeout=15s'],
            ['helm', '--kube-context', args.context, '-n', NAMESPACE])


def install(args, collector, api):
    api.validate('alloy', collector)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', collector['GROT_CLUSTER']):
        raise api.SafeError('Infrastructure monitoring requires a short GROT_CLUSTER label')
    kube, helm = commands(args)
    print('Infrastructure: checking for existing Kubernetes Monitoring (cluster-wide)...', flush=True)
    releases = api.helm_releases(['helm', '--kube-context', args.context], all_namespaces=True)
    others = [r for r in releases if r.get('chart', '').startswith('k8s-monitoring-')
              and (r.get('name'), r.get('namespace')) != (RELEASE, NAMESPACE)]
    if others:
        raise api.SafeError('Kubernetes Monitoring already exists. Use --skip-k8s-monitoring to reuse it; Grot will not install a duplicate or modify it.')
    target = next((r for r in releases if r.get('name') == RELEASE and r.get('namespace') == NAMESPACE), None)
    if target and not target.get('chart', '').startswith('k8s-monitoring-'):
        raise api.SafeError('The infrastructure release name is occupied by a different chart; refusing changes.')
    ledger = api.get_object(kube, 'configmap', LEDGER)
    if ledger and (not api.owned(ledger, ledger.get('data', {}).get('owner')) or ledger['data'].get('binding') != binding(collector)):
        raise api.SafeError('Infrastructure monitoring is owned externally or bound to another cluster label/destination; refusing changes.')
    if not ledger and any(r.get('name') == RELEASE and r.get('namespace') == NAMESPACE for r in releases):
        raise api.SafeError('Existing infrastructure release has no Grot ownership record; refusing adoption.')
    owner = ledger['data']['owner'] if ledger else api.uuid.uuid4().hex
    current = api.get_object(kube, 'secret', SECRET)
    if current and not api.owned(current, owner):
        raise api.SafeError('Refusing to overwrite an externally managed infrastructure Secret.')
    if not api.get_object(kube, 'namespace', NAMESPACE):
        api.run(kube + ['create', 'namespace', NAMESPACE])
    labels = {api.OWNER: owner, 'app.kubernetes.io/managed-by': api.MANAGER}
    if not ledger:
        api.run(kube + ['create', '--field-manager=' + api.MANAGER, '-f', '-'], data=json.dumps({
            'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': LEDGER, 'labels': labels},
            'data': {'owner': owner, 'binding': binding(collector), 'sourceNamespace': args.namespace,
                     'cluster': collector['GROT_CLUSTER']}}))
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': SECRET, 'labels': labels},
              'type': 'Opaque', 'data': {key: base64.b64encode(collector[key].encode()).decode() for key in KEYS}}
    if current: secret['metadata']['resourceVersion'] = current['metadata']['resourceVersion']
    api.run(kube + ['replace' if current else 'create', '--field-manager=' + api.MANAGER, '-f', '-'], data=json.dumps(secret))
    print('Infrastructure: installing cluster/workload metrics, kubelet cAdvisor, Linux node metrics and Kubernetes events...', flush=True)
    rollback = '--rollback-on-failure' if '--rollback-on-failure' in api.run(['helm', 'upgrade', '--help']) else '--atomic'
    revision = str(time.time_ns())
    api.run(helm + ['upgrade', '--install', RELEASE, 'k8s-monitoring', '--repo', REPO,
        '--version', CHART_VERSION, '-f', str(api.ROOT / 'deploy/kubernetes-monitoring/values.yaml'),
        '--set-string', 'cluster.name=' + collector['GROT_CLUSTER'],
        '--set-string', 'collectors.infrastructure.controller.podAnnotations.grot-runtime-revision=' + revision,
        '--wait', '--timeout', '5m', rollback])
    # Helm waits for its operator/exporters, but the Alloy CR creates a separate deployment.
    print('Infrastructure: waiting for the operator-managed Alloy collector...', flush=True)
    # Rotate through the Alloy CR, not its operator-owned Deployment. Direct
    # restarts can be reverted by reconciliation; bounded polling avoids stalled watches.
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if collector_ready(api.get_object(kube, 'deployment', COLLECTOR), revision): break
        time.sleep(2)
    else: raise api.SafeError('Infrastructure collector did not become ready. Check the Alloy operator in grot-monitoring.')
    verify_delivery(args, api)
    print('Infrastructure ready in grot-monitoring. Application telemetry collection is unchanged.', flush=True)
    if getattr(args, 'grafana_context', None):
        verify_cloud(args, collector['GROT_CLUSTER'], api)
    else:
        print('Cloud indexing not checked. Add --grafana-context CONTEXT to the infrastructure command for query-side verification.', flush=True)


def collector_ready(deployment, revision):
    if not deployment: return False
    spec, status = deployment.get('spec', {}), deployment.get('status', {})
    annotations = spec.get('template', {}).get('metadata', {}).get('annotations', {})
    return (annotations.get('grot-runtime-revision') == revision
            and status.get('observedGeneration', 0) >= deployment.get('metadata', {}).get('generation', 1)
            and status.get('updatedReplicas', 0) == spec.get('replicas', 1)
            and status.get('availableReplicas', 0) == spec.get('replicas', 1)
            and status.get('replicas', 0) == spec.get('replicas', 1))


def collected_and_delivered(text):
    def positive(name, contains=''):
        return any(float(m[2]) > 0 and contains in (m[1] or '') for m in re.finditer(
            r'^' + re.escape(name) + r'(\{[^\n]*\})?\s+([0-9.eE+-]+)', text, re.M))
    return (positive('prometheus_remote_storage_samples_total') and positive('loki_write_sent_entries_total')
            and all(positive('prometheus_target_scrape_pool_targets', 'prometheus.scrape.' + collector + '"')
                    for collector in ('cadvisor', 'kube_state_metrics', 'node_exporter')))


def verify_delivery(args, api):
    kube, _ = commands(args)
    path = f'/api/v1/namespaces/{NAMESPACE}/services/http:{COLLECTOR}:12345/proxy/metrics'
    print('Infrastructure: verifying cAdvisor/state/node discovery and destination acknowledgements...', flush=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            metrics = api.run(kube + ['get', '--request-timeout=10s', '--raw', path])
            if collected_and_delivered(metrics):
                print('Infrastructure targets discovered; destination accepted metrics and Kubernetes events. Cloud indexing is a separate check.', flush=True)
                return
        except api.SafeError:
            pass
        time.sleep(3)
    raise api.SafeError('Infrastructure installed but collection/delivery checks failed. Inspect grot-monitoring collector health and ingestion permissions; Cloud indexing is not yet verified.')


def verify_cloud(args, cluster, api):
    base = ['gcx', '--context', args.grafana_context, '--agent=false']
    api.run(base + ['config', 'check'])
    datasources = json.loads(api.run(base + ['datasources', 'list', '-o', 'json']))['datasources']
    selected = {}
    for kind, conventional in [('prometheus', 'grafanacloud-prom'), ('loki', 'grafanacloud-logs')]:
        choices = [d['uid'] for d in datasources if d['type'] == kind]
        if conventional in choices: selected[kind] = conventional
        elif len(choices) == 1: selected[kind] = choices[0]
        else: raise api.SafeError('Missing or ambiguous infrastructure datasource: ' + kind)
    scope = '{cluster=' + json.dumps(cluster) + '}'
    checks = [('node inventory', 'metrics', 'prometheus', 'count(kube_node_info' + scope + ')'),
              ('workload inventory', 'metrics', 'prometheus', 'count(kube_pod_info' + scope + ')'),
              ('cAdvisor container CPU', 'metrics', 'prometheus', 'count(container_cpu_usage_seconds_total' + scope[:-1] + ',namespace=' + json.dumps(args.namespace) + ',container="orders"})'),
              ('Linux host CPU', 'metrics', 'prometheus', 'count(node_cpu_seconds_total' + scope + ')'),
              ('Kubernetes events', 'logs', 'loki', 'sum(count_over_time(' + scope[:-1] + ',source="kubernetes-events"}[15m]))')]
    pending = list(checks)
    print('Infrastructure: checking Grafana Cloud indexing (up to 3 minutes)...', flush=True)
    for attempt in range(18):
        for check in pending[:]:
            label, group, kind, query = check
            response = json.loads(api.run(base + [group, 'query', '-d', selected[kind], query, '-o', 'json']))
            results = response.get('data', {}).get('result', [])
            found = False
            for item in results:
                samples = item.get('values', []) or [item.get('value', [])]
                for sample in samples:
                    value = sample.get('line') if isinstance(sample, dict) else sample[1] if len(sample) == 2 else 0
                    if float(value or 0) > 0: found = True
            if found:
                print('  Indexed: ' + label, flush=True)
                pending.remove(check)
        if not pending:
            print('Infrastructure Cloud verification PASSED.', flush=True)
            return
        if attempt < 17:
            print('  Waiting for: ' + ', '.join(c[0] for c in pending), flush=True)
            time.sleep(10)
    raise api.SafeError('Infrastructure installed, but Cloud indexing remains incomplete: ' + ', '.join(c[0] for c in pending))


def existing(args, api):
    """Install on an already-running Grot stack without reinstalling the app."""
    kube = ['kubectl', '--context', args.context, '-n', args.namespace]
    ledger = api.get_object(kube, 'configmap', api.LEDGER)
    if not ledger or ledger.get('data', {}).get('destination') != args.destination:
        raise api.SafeError('No matching Grot deployment in the selected namespace.')
    obj = api.get_object(kube, 'secret', api.SECRET_NAMES['alloy'])
    if not obj: raise api.SafeError('The Grot collector runtime Secret is missing.')
    collector = {key: base64.b64decode(value).decode() for key, value in obj.get('data', {}).items()}
    install(args, collector, api)


def remove(args, api):
    """Explicit opt-in teardown; ordinary app stop never removes shared monitoring."""
    kube, helm = commands(args)
    ledger = api.get_object(kube, 'configmap', LEDGER)
    if not ledger or not api.owned(ledger, ledger.get('data', {}).get('owner')):
        raise api.SafeError('No Grot-owned infrastructure record; refusing removal.')
    if ledger['data'].get('sourceNamespace') != args.namespace:
        raise api.SafeError('Use the original source namespace to remove shared infrastructure monitoring.')
    releases = api.helm_releases(helm)
    target = next((r for r in releases if r.get('name') == RELEASE), None)
    if target:
        if not target.get('chart', '').startswith('k8s-monitoring-'):
            raise api.SafeError('The infrastructure release was replaced by a different chart; refusing removal.')
        api.run(helm + ['uninstall', RELEASE, '--wait', '--timeout', '5m'])
    for kind, name in [('secrets', SECRET), ('configmaps', LEDGER)]:
        api.delete_owned(kube, NAMESPACE, kind, name, ledger['data']['owner'])
    print('Removed Grot-owned infrastructure monitoring. Namespace and shared CRDs are retained; Grot apps were not changed.')

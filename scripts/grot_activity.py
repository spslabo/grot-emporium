"""App-owned, automatic shopping/browser activity. No Cloud k6 or model calls."""
import hashlib
import json
import time

try:
    from .grot_traffic import FILES, IMAGE
except ImportError:
    from grot_traffic import FILES, IMAGE

NAME = 'grot-demo-activity'
LABEL = 'grot-emporium/activity-destination'


def environment(base_url, faro):
    return {'BASE_URL': base_url, 'TARGET_AUTHORIZED': 'true',
            'JOURNEYS_PER_MINUTE': '6', 'BROWSER_JOURNEYS_PER_MINUTE': '1',
            'TRAFFIC_DURATION': '1h', 'TRAFFIC_PRESET': 'demo',
            'EXPECT_FARO': str(bool(faro)).lower(),
            'GROT_FAILURES': 'false', 'GROT_CHAT_INTERVAL_SECONDS': '0',
            'ALLOW_PAID_AI': 'false', 'K6_NO_USAGE_REPORT': 'true',
            'K6_BROWSER_ARGS': 'no-sandbox', 'K6_BROWSER_HEADLESS': 'true'}


def docker_name(args):
    return 'grot-' + args.destination + '-activity'


def docker_object(args, api):
    name = docker_name(args)
    found = api.run(['docker', 'container', 'ls', '-a', '--filter', 'name=^/' + name + '$', '--format', '{{.ID}}'])
    if not found.strip(): return None
    obj = json.loads(api.run(['docker', 'container', 'inspect', name]))[0]
    labels = obj.get('Config', {}).get('Labels', {})
    if labels.get(LABEL) != args.destination or labels.get('app.kubernetes.io/managed-by') != api.MANAGER:
        raise api.SafeError('Refusing to change an unrelated demo-activity container.')
    return obj


def owned(obj, owner, api):
    # Deployment controllers legitimately maintain status and revision metadata.
    metadata = dict(obj.get('metadata', {}))
    metadata['managedFields'] = [field for field in metadata.get('managedFields', [])
        if field.get('subresource') != 'status' and field.get('manager') != 'kube-controller-manager']
    return api.owned(dict(obj, metadata=metadata), owner)


def stop(args, api):
    if getattr(args, 'context', None):
        kube = ['kubectl', '--context', args.context, '-n', args.namespace]
        ledger = api.get_object(kube, 'configmap', api.LEDGER)
        if not ledger or ledger.get('data', {}).get('destination') != args.destination or not api.owned(ledger, ledger['data'].get('owner')):
            raise api.SafeError('No matching installation; refusing demo-activity cleanup.')
        for kind, prefix in (('deployments', '/apis/apps/v1'), ('configmaps', '/api/v1')):
            obj = api.get_object(kube, kind, NAME)
            if not obj: continue
            if not owned(obj, ledger['data']['owner'], api):
                raise api.SafeError('Refusing to remove unrelated demo-activity resources.')
            body = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground',
                    'preconditions': {'uid': obj['metadata']['uid'], 'resourceVersion': obj['metadata']['resourceVersion']}}
            api.run(kube + ['delete', '--raw', prefix + '/namespaces/' + args.namespace + '/' + kind + '/' + NAME,
                            '-f', '-'], data=json.dumps(body))
            api.run(kube + ['wait', '--for=delete', kind + '/' + NAME, '--timeout=60s'])
    elif docker_object(args, api):
        api.run(['docker', 'stop', '--time', '30', docker_name(args)])
        api.run(['docker', 'rm', docker_name(args)])


def configure(args, api):
    if getattr(args, 'no_demo_traffic', False):
        stop(args, api)
        print('Automatic demo traffic disabled (--no-demo-traffic).', flush=True)
        return
    print('Starting automatic demo activity: 6 shopping + 1 browser journey/min; no Cloud k6 or model calls...', flush=True)
    if getattr(args, 'context', None):
        kube = ['kubectl', '--context', args.context, '-n', args.namespace]
        ledger = api.get_object(kube, 'configmap', api.LEDGER)
        if not ledger or ledger.get('data', {}).get('destination') != args.destination or not api.owned(ledger, ledger['data'].get('owner')):
            raise api.SafeError('No matching installation; refusing to generate demo activity.')
        owner = ledger['data']['owner']
        current = {kind: api.get_object(kube, kind, NAME) for kind in ('configmap', 'deployment')}
        if any(obj and not owned(obj, owner, api) for obj in current.values()):
            raise api.SafeError('Refusing to overwrite unrelated demo-activity resources.')
        gateway = api.get_object(kube, 'secret', 'grot-gateway-runtime') or {}
        env = environment('http://grot-gateway', gateway.get('data', {}).get('GRAFANA_FARO_URL'))
        labels = {api.OWNER: owner, 'app.kubernetes.io/managed-by': api.MANAGER,
                  'app.kubernetes.io/name': NAME, LABEL: args.destination}
        files = {key: (api.ROOT / path).read_text() for key, path in FILES.items()}
        revision = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        objects = [
            {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': NAME, 'labels': labels}, 'data': files},
            {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': NAME, 'labels': labels},
             'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
                      'selector': {'matchLabels': {'app.kubernetes.io/name': NAME, api.OWNER: owner}},
                      'template': {'metadata': {'labels': labels, 'annotations': {'grot-emporium/scripts-sha256': revision}},
                                   'spec': {'restartPolicy': 'Always', 'automountServiceAccountToken': False,
                                            'terminationGracePeriodSeconds': 35,
                                            'containers': [{'name': 'activity', 'image': IMAGE, 'workingDir': '/work',
                                                'args': ['run', '--no-usage-report', '/work/tests/k6/traffic.js'],
                                                'env': [{'name': k, 'value': v} for k, v in env.items()],
                                                'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'},
                                                              'limits': {'cpu': '2', 'memory': '1536Mi'}},
                                                'volumeMounts': [{'name': 'scripts', 'mountPath': '/work', 'readOnly': True},
                                                                 {'name': 'shm', 'mountPath': '/dev/shm'}]}],
                                            'volumes': [{'name': 'scripts', 'configMap': {'name': NAME,
                                                'items': [{'key': k, 'path': v} for k, v in FILES.items()]}},
                                                {'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '256Mi'}}]}}}}]
        for obj in objects:
            existing = current[obj['kind'].lower()]
            if existing: obj['metadata']['resourceVersion'] = existing['metadata']['resourceVersion']
            api.run(kube + ['replace' if existing else 'create', '--field-manager=' + api.MANAGER, '-f', '-'], data=json.dumps(obj))
        api.run(kube + ['rollout', 'status', 'deployment/' + NAME, '--timeout=180s'])
    else:
        path = api.profile_path(args.destination) / 'run.json'
        if not path.exists(): raise api.SafeError('No matching local Grot installation.')
        state = json.loads(path.read_text())
        stop(args, api)
        env = environment('http://gateway:8080', state.get('faro'))
        command = ['docker', 'run', '-d', '--name', docker_name(args), '--restart', 'unless-stopped',
                   '--label', LABEL + '=' + args.destination, '--label', 'app.kubernetes.io/managed-by=' + api.MANAGER,
                   '--network', 'grot-' + args.destination + '_default', '--memory', '1536m', '--cpus', '2',
                   '--shm-size', '256m', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=2',
                   '-v', str(api.ROOT / 'tests/k6') + ':/work/tests/k6:ro',
                   '-v', str(api.ROOT / 'src/catalog/grots.json') + ':/work/src/catalog/grots.json:ro', '-w', '/work']
        for key, value in env.items(): command += ['-e', key + '=' + value]
        api.run(command + [IMAGE, 'run', '--no-usage-report', '/work/tests/k6/traffic.js'])
        time.sleep(2)
        obj = docker_object(args, api)
        if not obj or obj.get('State', {}).get('Status') != 'running':
            raise api.SafeError('Automatic demo activity did not start. Inspect docker logs ' + docker_name(args) + '.')
    print('Demo activity runs automatically until the app is stopped. Existing app telemetry goes to Grafana Cloud.', flush=True)

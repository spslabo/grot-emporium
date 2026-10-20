"""Read-only Grafana Cloud indexing checks through gcx; no credential handling."""
import json
import re

SERVICES = {'grot-' + name for name in ('ui', 'cart', 'orders', 'catalog', 'checkout')}
DATASOURCES = {
    'metrics': ('prometheus', 'grafanacloud-prom'),
    'logs': ('loki', 'grafanacloud-logs'),
    'traces': ('tempo', 'grafanacloud-traces'),
    'profiles': ('grafana-pyroscope-datasource', 'grafanacloud-profiles'),
}


def positive_services(response):
    """Accept actual positive samples, not just nonempty success envelopes."""
    found = set()
    for series in response.get('data', {}).get('result', []):
        samples = series.get('values', []) or [series.get('value', [])]
        # gcx normalizes Loki samples to {timestamp, line}, with labels under
        # stream; Prometheus retains [timestamp, value] and metric labels.
        values = [sample.get('line') if isinstance(sample, dict) else sample[1]
                  for sample in samples if len(sample) == 2]
        if any(float(value) > 0 for value in values):
            labels = series.get('metric', series.get('stream', {}))
            found.add(labels.get('service_name'))
    return found


def verify(args, run, error):
    cluster = args.cloud_cluster or args.destination
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', cluster):
        raise error('Cloud cluster must be the short GROT_CLUSTER label, not a URL')
    base = ['gcx', '--context', args.grafana_context, '--agent=false']
    print('Grafana Cloud — checking the explicitly selected gcx context (read-only)', flush=True)
    run(base + ['config', 'check'])

    def query(command):
        return json.loads(run(base + command + ['-o', 'json']))

    datasources = query(['datasources', 'list'])['datasources']
    selected = {}
    for signal, (kind, conventional) in DATASOURCES.items():
        candidates = [d['uid'] for d in datasources if d['type'] == kind]
        if conventional in candidates: selected[signal] = conventional
        elif len(candidates) == 1: selected[signal] = candidates[0]
        else: raise error('Missing or ambiguous Cloud ' + signal + ' datasource; use the standard Cloud datasource UID')
    selector = '{service_namespace="grot-emporium",cluster=' + json.dumps(cluster) + '}'
    failed = []
    profile_types = {}
    try:
        series = query(['profiles', 'series', '-d', selected['profiles'], selector, '--since', '15m',
            '--label-name', 'service_name', '--label-name', '__profile_type__'])
        for item in series.get('labelsSet', []):
            labels = {label['name']: label['value'] for label in item.get('labels', [])}
            if labels.get('service_name') in SERVICES and labels.get('__profile_type__'):
                profile_types.setdefault(labels['service_name'], set()).add(labels['__profile_type__'])
    except (error, ValueError, KeyError, TypeError):
        failed.append('profiles: type discovery failed')

    def check(signal, service, command, predicate):
        print(f'Cloud {signal}: checking {service}...', flush=True)
        try:
            success = predicate(query(command))
        except error as failure:
            failed.append(signal + ': command failed')
            print(f'Cloud {signal}: {failure}', flush=True)
            return
        except (ValueError, KeyError, TypeError):
            failed.append(signal + ': response format not recognized')
            print(f'Cloud {signal}: could not parse the gcx response; this is a verifier compatibility error, not an ingestion or authentication diagnosis.', flush=True)
            return
        if not success:
            failed.append(signal + ': ' + service)
            print(f'Cloud {signal}: no qualifying indexed data for {service}', flush=True)
        else: print(f'Cloud {signal}: indexed data confirmed for {service}', flush=True)

    check('metrics', 'all five services', ['metrics', 'query', '-d', selected['metrics'],
        'count by(service_name) (up' + selector + ' == 1)'], lambda d: SERVICES <= positive_services(d))
    db_selector = '{job="integrations/db-o11y",cluster=' + json.dumps(cluster) + '}'
    for label, expression in [('database health', 'pg_up'), ('database queries', 'pg_stat_statements_calls_total')]:
        check(label, 'grot-postgres', ['metrics', 'query', '-d', selected['metrics'],
            'sum by(service_name) (' + expression + db_selector + ')'],
            lambda d: 'grot-postgres' in positive_services(d))
    check('database query details', 'grot-postgres', ['logs', 'query', '-d', selected['logs'],
        'sum by(service_name) (count_over_time(' + db_selector + ' |= "query_association" [15m]))', '--since', '15m'],
        lambda d: 'grot-postgres' in positive_services(d))
    def log_coverage(response):
        found = SERVICES & positive_services(response)
        if found:
            print('  Recent logs from: ' + ', '.join(sorted(found)), flush=True)
            quiet = SERVICES - found
            if quiet: print('  No recent log entries from: ' + ', '.join(sorted(quiet)) + ' (quiet services do not imply failed ingestion)', flush=True)
        return bool(found)

    check('logs', 'this deployment', ['logs', 'query', '-d', selected['logs'],
        'sum by(service_name) (count_over_time(' + selector + '[15m]))', '--since', '15m'], log_coverage)
    print('Trace scope: Grot service namespace + service + last 15m; not unique to a deployment when several share that namespace.', flush=True)
    for service in sorted(SERVICES):
        check('traces', service, ['traces', 'query', '-d', selected['traces'],
            '{resource.service.namespace="grot-emporium" && resource.service.name=' + json.dumps(service) + '}',
            '--since', '15m', '--limit', '1'], lambda d: bool(d.get('traces')))
        # Node exports wall/heap profiles; Java/Go can export CPU profiles.
        types = sorted(profile_types.get(service, []), key=lambda t: (0 if t.startswith('process_cpu:') else 1 if t.startswith('wall:') else 2, t))
        if not types:
            failed.append('profiles: ' + service)
            print(f'Cloud profiles: no indexed profile types for {service}', flush=True)
            continue
        check('profiles', service, ['profiles', 'query', '-d', selected['profiles'],
            selector[:-1] + ',service_name=' + json.dumps(service) + '}',
            '--profile-type', types[0], '--since', '15m', '--max-nodes', '10'],
            lambda d: float(d.get('flamegraph', {}).get('total', 0)) > 0)
    if failed:
        raise error('Cloud indexing check incomplete: ' + '; '.join(failed) + '. See the per-signal results above.')
    print('Cloud indexing confirmed for metrics, logs, traces, profiles and PostgreSQL health/query telemetry. This checks recent presence, not exact probe correlation, Faro indexing or App O11y readiness.', flush=True)

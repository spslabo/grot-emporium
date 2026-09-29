#!/usr/bin/env python3
"""Assert real parent/child links across all five services in OTLP JSONL output."""
import json
import sys
import re
from urllib.request import urlopen
from pathlib import Path

EXPECTED = {
    ('grot-ui', 'grot-catalog'),
    ('grot-ui', 'grot-cart'),
    ('grot-ui', 'grot-checkout'),
    ('grot-checkout', 'grot-orders'),
}

def trace_edges(records):
    spans = {}
    for record in records:
        for resource in record.get('resourceSpans', []):
            attrs = {a['key']: a['value'].get('stringValue') for a in resource['resource'].get('attributes', [])}
            service = attrs.get('service.name')
            if service and service.startswith('grot-'):
                assert attrs.get('service.namespace') == 'grot-emporium', 'Missing namespace'
            for scope in resource.get('scopeSpans', []):
                for span in scope.get('spans', []):
                    spans[(span['traceId'], span['spanId'])] = (service, span.get('parentSpanId'))
    edges = set()
    for (trace_id, _), (service, parent_id) in spans.items():
        parent = spans.get((trace_id, parent_id))
        if parent and parent[0] != service:
            edges.add((parent[0], service))
    return edges

if __name__ == '__main__':
    records = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
    edges = trace_edges(records)
    missing = EXPECTED - edges
    if missing:
        raise SystemExit(f'Missing cross-service parent/child links: {sorted(missing)}; found: {sorted(edges)}')
    print('Verified trace propagation: ' + ', '.join(f'{a} → {b}' for a, b in sorted(EXPECTED)))
    if '--order-errors' in sys.argv:
        found = any(
            attribute.get('key') in ('http.response.status_code', 'http.status_code')
            and int(attribute.get('value', {}).get('intValue', 0)) >= 500
            for record in records for resource in record.get('resourceSpans', [])
            if any(a.get('key') == 'service.name' and a.get('value', {}).get('stringValue') == 'grot-orders' for a in resource['resource']['attributes'])
            for scope in resource.get('scopeSpans', []) for span in scope.get('spans', [])
            for attribute in span.get('attributes', [])
        )
        assert found, 'Missing Orders server-error trace evidence'
        print('Verified Orders server-error trace evidence; exception details are in correlated application logs')
    if '--metrics' in sys.argv:
        for service, path, metric in [
            ('ui', '/actuator/prometheus', 'http_server_requests_seconds_bucket'),
            ('cart', '/actuator/prometheus', 'http_server_requests_seconds_bucket'),
            ('orders', '/actuator/prometheus', 'http_server_requests_seconds_bucket'),
            ('catalog', '/metrics', 'http_server_request_duration_seconds_bucket'),
            ('checkout', '/metrics', 'http_server_request_duration_seconds_bucket'),
        ]:
            with urlopen(f'http://{service}:8080{path}', timeout=5) as response:
                text = response.read().decode()
            assert metric in text, f'{service}: missing HTTP latency histogram {metric}'
            assert not re.search(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', text), f'{service}: UUID in metric labels'
        print('Verified HTTP latency histograms for all five services, without UUID labels')

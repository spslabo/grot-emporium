"""Test-only extraction of identity from OTLP and Prometheus protobuf envelopes.

No application content or arbitrary resource attributes are retained. The sink
uses only service, host and instance identity to test actual exported telemetry.
"""
SERVICES = {'grot-' + name for name in ('ui', 'cart', 'orders', 'catalog', 'checkout')}
RUNTIME_METRICS = {'jvm_memory_used_bytes', 'go_memstats_alloc_bytes', 'nodejs_heap_size_used_bytes'}


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data): raise ValueError('Truncated varint')
        byte = data[offset]; offset += 1
        value |= (byte & 127) << shift
        if not byte & 128: return value, offset
    raise ValueError('Invalid varint')


def fields(data):
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number: raise ValueError('Invalid field number')
        if wire == 0:
            _, offset = varint(data, offset)
            continue
        if wire == 2:
            size, offset = varint(data, offset)
        elif wire in (1, 5): size = 8 if wire == 1 else 4
        else: raise ValueError('Unsupported wire type')
        end = offset + size
        if end > len(data): raise ValueError('Truncated field')
        if wire == 2: yield number, data[offset:end]
        offset = end


def messages(data, number):
    return [value for key, value in fields(data) if key == number]


def text(data, number):
    values = messages(data, number)
    return values[-1].decode('utf-8') if values else ''


def otlp_identities(data):
    # Export{Trace,Metrics}ServiceRequest: field 1 is repeated ResourceSpans/Metrics.
    for item in messages(data, 1):
        for resource in messages(item, 1):
            attributes = {}
            for entry in messages(resource, 1):
                values = messages(entry, 2)
                if values: attributes[text(entry, 1)] = text(values[-1], 1)
            service = attributes.get('service.name')
            if service not in SERVICES: continue
            host = attributes.get('k8s.node.name', '') if attributes.get('k8s.cluster.name') else (attributes.get('host.id') or attributes.get('grafana.host.id', ''))
            yield service, host, attributes.get('service.instance.id', '')


def prometheus_identities(data):
    for series in messages(data, 1):
        labels = {text(label, 1): text(label, 2) for label in messages(series, 1)}
        # Require a real runtime metric, not merely 'up' or a fabricated target_info.
        if labels.get('__name__') not in RUNTIME_METRICS: continue
        service = labels.get('service_name')
        if service not in SERVICES: continue
        yield service, labels.get('k8s_node_name') or labels.get('grafana_host_id', ''), labels.get('instance', '')


def assert_identities(actual, tenant, expected):
    """Every current service must have matching trace and runtime-metric identity."""
    assert set(expected) == SERVICES
    for service, identity in expected.items():
        assert all(identity), 'Empty expected host/instance identity'
        for signal in ('traces', 'runtime-metrics'):
            assert list(identity) in actual.get(f'{tenant}:{signal}:{service}', []), f'Missing matching {signal} identity for {service}'

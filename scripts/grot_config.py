#!/usr/bin/env python3
"""Initialize/validate private runtime env files. Never prints configuration values."""
import argparse
import ipaddress
import math
import os
from pathlib import Path
import re
import stat
import secrets
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    'backend': '''OTEL_SDK_DISABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_HEADERS=
OTEL_METRICS_EXPORTER=none
OTEL_LOGS_EXPORTER=none
OTEL_RESOURCE_ATTRIBUTES=service.namespace=grot-emporium,deployment.environment=demo
DEPLOYMENT_ENVIRONMENT=demo
SERVICE_VERSION=development
PYROSCOPE_ENABLED=false
PYROSCOPE_LABELS=service_namespace=grot-emporium,deployment_environment=demo
PYROSCOPE_SERVER_ADDRESS=
''',
    'ui': '''OTEL_METRICS_EXPORTER=none
FARO_ENABLED=false
FARO_COLLECTOR_URL=
FARO_PUBLIC_URL_ACKNOWLEDGED=false
RETAIL_UI_CHAT_ENABLED=false
RETAIL_UI_CHAT_PROVIDER=mock
GROT_CHAT_SYNTHETIC_FAULTS_ENABLED=false
GROT_AGENT_OBSERVABILITY_ENABLED=false
AGENTO11Y_ENDPOINT=
AGENTO11Y_PROTOCOL=http
AGENTO11Y_CONTENT_CAPTURE_MODE=metadata_only
AGENTO11Y_TAGS=app=grot-emporium,environment=demo
AGENTO11Y_AUTH_MODE=basic
AGENTO11Y_AUTH_TENANT_ID=
AGENTO11Y_AUTH_TOKEN=
''',
    'database': '''POSTGRES_PASSWORD=
GROT_DB_APP_PASSWORD=
GROT_DB_MONITOR_PASSWORD=
''',
    'gateway': '''GRAFANA_FARO_URL=
''',
    'alloy': '''GROT_NAMESPACE=grot-emporium
GROT_CLUSTER=unknown
DEPLOYMENT_ENVIRONMENT=demo
GRAFANA_OTLP_ENDPOINT=
GRAFANA_OTLP_USER=
GRAFANA_OTLP_TOKEN=
GRAFANA_METRICS_URL=
GRAFANA_METRICS_USER=
GRAFANA_METRICS_TOKEN=
GRAFANA_LOGS_URL=
GRAFANA_LOGS_USER=
GRAFANA_LOGS_TOKEN=
GRAFANA_PROFILES_URL=
GRAFANA_PROFILES_USER=
GRAFANA_PROFILES_TOKEN=
''',
}
EXTRA_KEYS = {
    'backend': {'OTEL_TRACES_SAMPLER', 'OTEL_TRACES_SAMPLER_ARG', 'OTEL_METRIC_EXPORT_INTERVAL', 'PYROSCOPE_BASIC_AUTH_USER', 'PYROSCOPE_BASIC_AUTH_PASSWORD'},
    'ui': {'RETAIL_UI_CHAT_OPENAI_API_KEY', 'RETAIL_UI_CHAT_MODEL', 'RETAIL_UI_CHAT_OPENAI_BASE_URL', 'RETAIL_UI_CHAT_BEDROCK_REGION', 'AWS_REGION'},
    'alloy': set(),
    'gateway': set(),
    'database': set(),
}


def private_path(path, must_exist=True):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError('Symlink config files are not accepted')
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError('Private configuration must live outside the repository')
    if must_exist:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('Config must be a regular file accessible only by its owner (chmod 600)')
        if hasattr(os, 'getuid') and info.st_uid != os.getuid():
            raise ValueError('Config must be owned by the current user')
    return resolved


def load(path):
    path = private_path(path)
    result = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch('[A-Z][A-Z0-9_]*', key) or key in result or '\x00' in value:
            raise ValueError(f'Invalid or duplicate entry at line {number}; expected literal KEY=value')
        result[key] = value
    return result


def valid_url(value, public=False, cloud=False):
    try:
        # urlsplit silently strips some controls. Reject them before parsing;
        # these values can also become nginx configuration, not just HTTP URLs.
        if not isinstance(value, str) or re.search(r'''[^\x21-\x7e]|[\\"'{};$?#]''', value):
            return False
        url = urlsplit(value)
        host = url.hostname
        if not host or url.username is not None or url.password is not None or url.netloc.endswith(':'):
            return False
        if url.port is not None and not 1 <= url.port <= 65535:
            return False
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in host.split('.')):
                return False
            if re.fullmatch(r'[0-9.]+', host):
                return False
        if any(part in ('.', '..') for part in url.path.split('/')):
            return False
        local = host in ('127.0.0.1', '::1') or '.' not in host or host.endswith('.svc.cluster.local')
        return url.scheme == 'https' or (not cloud and local and url.scheme == 'http' and (not public or host == 'localhost'))
    except ValueError:
        return False


CLOUD_ENDPOINTS = {
    'GRAFANA_OTLP_ENDPOINT': ('/otlp', 'OTLP traces require the HTTP base endpoint ending in /otlp, not a Tempo query URL or /v1/traces'),
    'GRAFANA_METRICS_URL': ('/api/prom/push', 'Metrics require the full Prometheus remote-write URL ending in /api/prom/push, not the base URL'),
    'GRAFANA_LOGS_URL': ('/loki/api/v1/push', 'Logs require the full Loki push URL ending in /loki/api/v1/push, not the base URL'),
    'GRAFANA_PROFILES_URL': ('', 'Profiles require the Pyroscope ingestion origin with no path, not /ingest or a query URL'),
}
CLOUD_HOST_PREFIXES = {
    'GRAFANA_OTLP_ENDPOINT': 'otlp-gateway-', 'GRAFANA_METRICS_URL': 'prometheus-',
    'GRAFANA_LOGS_URL': 'logs-', 'GRAFANA_PROFILES_URL': 'profiles-',
    'GRAFANA_FARO_URL': 'faro-collector-',
}


def validate_cloud_endpoint(key, value):
    url = urlsplit(value)
    if key in CLOUD_ENDPOINTS:
        path, reason = CLOUD_ENDPOINTS[key]
        if url.path not in (('', '/') if key == 'GRAFANA_PROFILES_URL' else (path,)):
            raise ValueError(reason)
    elif key == 'GRAFANA_FARO_URL':
        if not re.fullmatch(r'/collect/[A-Za-z0-9._~-]+', url.path):
            raise ValueError('Faro requires the complete HTTPS collector URL with /collect/<application-key>')
    # Direct Grafana Cloud hosts identify the ingest service. A valid-looking
    # path on the stack UI or another signal's host is still the wrong endpoint.
    if url.hostname.endswith('.grafana.net') and not url.hostname.startswith(CLOUD_HOST_PREFIXES[key]):
        raise ValueError(f'{key} requires its ingestion service hostname, not the stack UI or another signal endpoint')


def validate(kind, values, *, partial=False):
    if kind not in TEMPLATES or not isinstance(values, dict):
        raise ValueError('Expected a recognized role and an object of string settings')
    allowed = {line.split('=')[0] for line in TEMPLATES[kind].splitlines()} | EXTRA_KEYS[kind]
    if set(values) - allowed:
        raise ValueError('Unrecognized configuration keys for this role')
    for key, value in values.items():
        if not isinstance(value, str) or len(value) > 8192 or (value and not value.isprintable()):
            raise ValueError('Settings must be bounded single-line printable strings')
        if value != value.strip():
            raise ValueError(f'{key} must not contain leading or trailing whitespace')
        if kind == 'alloy' and not value:
            raise ValueError(f'{key} is required for the supplied all-signal Alloy configuration')
        if value and key.endswith(('_USER', '_TOKEN', '_API_KEY', '_PASSWORD', '_TENANT_ID')):
            if not re.fullmatch(r'[\x21-\x7e]+', value):
                raise ValueError(f'{key} must not contain whitespace, controls or non-ASCII characters')
            if key.endswith(('_USER', '_TENANT_ID')) and ':' in value:
                raise ValueError(f'{key} must not contain a colon in a Basic-auth username')
        if key in ('GROT_NAMESPACE', 'GROT_CLUSTER', 'DEPLOYMENT_ENVIRONMENT') and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', value):
            raise ValueError(f'{key} must be a short identity label, not a URL or expression')
        if key == 'DEPLOYMENT_ENVIRONMENT' and value.lower() in ('prod', 'production'):
            raise ValueError('Use a non-production deployment environment for the demo')
        if kind == 'database' and not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', value):
            raise ValueError(f'{key} requires 32–128 URL-safe password characters')
        if key.endswith('_ENABLED') or key in ('OTEL_SDK_DISABLED', 'FARO_PUBLIC_URL_ACKNOWLEDGED'):
            if value not in ('true', 'false'):
                raise ValueError(f'{key} must be true or false')
        if value and (key.endswith(('_ENDPOINT', '_URL', '_SERVER_ADDRESS'))):
            if key == 'FARO_COLLECTOR_URL' and value.startswith('/'):
                if not re.fullmatch(r'/(?!/)[A-Za-z0-9_./~-]*', value) or any(p in ('.', '..') for p in value.split('/')):
                    raise ValueError('FARO_COLLECTOR_URL requires a safe same-origin path without query, fragment or traversal')
                continue
            if not valid_url(value, public=key == 'FARO_COLLECTOR_URL', cloud=key in CLOUD_HOST_PREFIXES or key == 'FARO_COLLECTOR_URL'):
                raise ValueError(f'{key} requires an allowed URL without embedded credentials/query/fragment')
            if key in CLOUD_HOST_PREFIXES:
                validate_cloud_endpoint(key, value)
            elif key == 'FARO_COLLECTOR_URL':
                validate_cloud_endpoint('GRAFANA_FARO_URL', value)
            elif key == 'OTEL_EXPORTER_OTLP_ENDPOINT' and urlsplit(value).path.rstrip('/').endswith(('/v1/traces', '/v1/metrics', '/v1/logs')):
                raise ValueError('OTEL_EXPORTER_OTLP_ENDPOINT requires a base URL, not a signal-specific /v1 path')
        enums = {
            'OTEL_EXPORTER_OTLP_PROTOCOL': ('http/protobuf',),
            'OTEL_METRICS_EXPORTER': ('none', 'otlp'), 'OTEL_LOGS_EXPORTER': ('none',),
            'OTEL_TRACES_SAMPLER': ('always_on', 'always_off', 'parentbased_always_on', 'parentbased_always_off', 'traceidratio', 'parentbased_traceidratio'),
            'AGENTO11Y_AUTH_MODE': ('basic', 'bearer'),
            'AGENTO11Y_PROTOCOL': ('http', 'grpc'),
            'AGENTO11Y_CONTENT_CAPTURE_MODE': ('metadata_only', 'full', 'no_tool_content', 'full_with_metadata_spans'),
            'RETAIL_UI_CHAT_PROVIDER': ('mock', 'openai', 'bedrock'),
        }
        if key in enums and value not in enums[key]:
            raise ValueError(f'{key} has an unsupported setting')
        if key == 'OTEL_TRACES_SAMPLER_ARG':
            try:
                if not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value): raise ValueError()
                ratio = float(value)
                if not math.isfinite(ratio) or not 0 <= ratio <= 1: raise ValueError()
            except ValueError:
                raise ValueError('OTEL_TRACES_SAMPLER_ARG must be a finite ratio between 0 and 1') from None
        if key == 'OTEL_METRIC_EXPORT_INTERVAL' and (not re.fullmatch(r'[0-9]{1,10}', value) or not 0 < int(value) <= 2147483647):
            raise ValueError('OTEL_METRIC_EXPORT_INTERVAL must be positive integer milliseconds')
    # Partial validation checks a field immediately; dependency checks wait
    # until the complete role is available, for every configuration route.
    if partial:
        return
    if kind == 'database':
        for key in allowed:
            if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', values.get(key, '')):
                raise ValueError(f'{key} requires 32–128 URL-safe password characters')
        if len(set(values.values())) != len(allowed):
            raise ValueError('Database admin, application and monitoring passwords must differ')
    if kind == 'backend':
        if values.get('OTEL_EXPORTER_OTLP_PROTOCOL', 'http/protobuf') != 'http/protobuf':
            raise ValueError('The shared backend contract requires http/protobuf OTLP')
        if values.get('OTEL_SDK_DISABLED') == 'false' and not values.get('OTEL_EXPORTER_OTLP_ENDPOINT'):
            raise ValueError('OTEL_EXPORTER_OTLP_ENDPOINT is required when tracing is enabled')
        if values.get('PYROSCOPE_ENABLED') == 'true' and not values.get('PYROSCOPE_SERVER_ADDRESS'):
            raise ValueError('PYROSCOPE_SERVER_ADDRESS is required when profiling is enabled')
    if kind == 'ui':
        if values.get('FARO_ENABLED') == 'true':
            url = values.get('FARO_COLLECTOR_URL', '')
            if not url:
                raise ValueError('FARO_COLLECTOR_URL is required when Faro is enabled')
            if not url.startswith('/') and values.get('FARO_PUBLIC_URL_ACKNOWLEDGED') != 'true':
                raise ValueError('Absolute Faro URLs are browser-visible; explicitly acknowledge this or use a same-origin proxy')
        if values.get('GROT_AGENT_OBSERVABILITY_ENABLED') == 'true':
            mode = values.get('AGENTO11Y_AUTH_MODE', 'basic')
            if mode not in ('basic', 'bearer'):
                raise ValueError('Authenticated generation export requires basic or bearer auth')
            required = ['AGENTO11Y_ENDPOINT', 'AGENTO11Y_AUTH_TOKEN']
            if mode == 'basic': required.append('AGENTO11Y_AUTH_TENANT_ID')
            for key in required:
                if not values.get(key):
                    raise ValueError(f'{key} is required for authenticated generation export')
        if values.get('RETAIL_UI_CHAT_ENABLED') == 'true':
            if values.get('RETAIL_UI_CHAT_PROVIDER') not in ('mock', 'openai', 'bedrock'):
                raise ValueError('Select a supported chat provider')
            if values.get('RETAIL_UI_CHAT_PROVIDER') == 'openai':
                for key in ('RETAIL_UI_CHAT_OPENAI_API_KEY', 'RETAIL_UI_CHAT_OPENAI_BASE_URL', 'RETAIL_UI_CHAT_MODEL'):
                    if not values.get(key): raise ValueError(f'{key} is required for the configured provider')
            if values.get('RETAIL_UI_CHAT_PROVIDER') == 'bedrock':
                if not values.get('RETAIL_UI_CHAT_MODEL') or not (values.get('RETAIL_UI_CHAT_BEDROCK_REGION') or values.get('AWS_REGION')):
                    raise ValueError('The configured provider requires a model and region')
    if kind == 'alloy':
        for key in allowed:
            if not values.get(key):
                raise ValueError(f'{key} is required for the supplied all-signal Alloy configuration')


def initialize(directory):
    directory = private_path(directory, must_exist=False)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError('Configuration directory must be owner-only (chmod 700)')
    if any((directory / f'{kind}.env').exists() for kind in TEMPLATES):
        raise ValueError('Configuration already exists; nothing will be overwritten')
    for kind, text in TEMPLATES.items():
        if kind == 'database':
            text = ''.join(line.split('=', 1)[0] + '=' + secrets.token_hex(24) + '\n' for line in text.splitlines())
        fd = os.open(directory / f'{kind}.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as file:
            file.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--directory', type=Path, default=Path.home() / '.config/grot-emporium')
    check = sub.add_parser('validate')
    check.add_argument('--kind', required=True, choices=TEMPLATES)
    check.add_argument('--file', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            initialize(args.directory)
            print('Created owner-only backend.env, ui.env, alloy.env, gateway.env and database.env outside Git. Optional features are disabled.')
        else:
            validate(args.kind, load(args.file))
            print(f'{args.kind} configuration is valid. Values are not displayed; no connection was attempted.')
    except (ValueError, OSError, UnicodeError):
        # Do not expose parser/file exceptions containing user-supplied secret values.
        parser.exit(1, 'Configuration rejected. Check role keys, required fields, file location/permissions and URL policy; no values were printed.\n')

if __name__ == '__main__':
    main()

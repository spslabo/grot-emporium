#!/usr/bin/env python3
"""Initialize/validate private runtime env files. Never prints configuration values."""
import argparse
import os
from pathlib import Path
import re
import stat
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
GROT_AGENT_OBSERVABILITY_ENABLED=false
AGENTO11Y_ENDPOINT=
AGENTO11Y_AUTH_MODE=basic
AGENTO11Y_AUTH_TENANT_ID=
AGENTO11Y_AUTH_TOKEN=
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
        # Values can enter a runtime proxy config: require URL-encoded special characters.
        if re.search(r'''[\s\\"'{};$]''', value):
            return False
        url = urlsplit(value)
        _ = url.port
        if not url.hostname or url.username or url.password or url.fragment or url.query:
            return False
        local = url.hostname in ('127.0.0.1', '::1') or '.' not in url.hostname or url.hostname.endswith('.svc.cluster.local')
        return url.scheme == 'https' or (not cloud and local and url.scheme == 'http' and (not public or url.hostname == 'localhost'))
    except ValueError:
        return False


def validate(kind, values, *, partial=False):
    allowed = {line.split('=')[0] for line in TEMPLATES[kind].splitlines()} | EXTRA_KEYS[kind]
    if set(values) - allowed:
        raise ValueError('Unrecognized configuration keys for this role')
    for key, value in values.items():
        if key in ('GROT_NAMESPACE', 'GROT_CLUSTER', 'DEPLOYMENT_ENVIRONMENT') and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', value):
            raise ValueError(f'{key} must be a short identity label, not a URL or expression')
        if key == 'DEPLOYMENT_ENVIRONMENT' and value.lower() in ('prod', 'production'):
            raise ValueError('Use a non-production deployment environment for the demo')
        if key.endswith('_ENABLED') or key in ('OTEL_SDK_DISABLED', 'FARO_PUBLIC_URL_ACKNOWLEDGED'):
            if value not in ('true', 'false'):
                raise ValueError(f'{key} must be true or false')
        if value and (key.endswith(('_ENDPOINT', '_URL', '_SERVER_ADDRESS'))):
            if key == 'FARO_COLLECTOR_URL' and value.startswith('/') and not value.startswith('//') and not any(c in value for c in ('\\', '?', '#')):
                continue
            if not valid_url(value, public=key == 'FARO_COLLECTOR_URL', cloud=kind == 'alloy'):
                raise ValueError(f'{key} requires an allowed URL without embedded credentials/query/fragment')
            if key == 'GRAFANA_LOGS_URL' and not urlsplit(value).path.endswith('/loki/api/v1/push'):
                raise ValueError('Logs require the full Loki push URL ending in /loki/api/v1/push, not the base URL')
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
            if values.get('RETAIL_UI_CHAT_PROVIDER') == 'openai' and not values.get('RETAIL_UI_CHAT_OPENAI_API_KEY'):
                raise ValueError('OpenAI requires its API key in the private UI config')
    if kind == 'alloy' and not partial:
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
            print('Created owner-only backend.env, ui.env, alloy.env and gateway.env outside Git. Optional features are disabled.')
        else:
            validate(args.kind, load(args.file))
            print(f'{args.kind} configuration is valid. Values are not displayed; no connection was attempted.')
    except (ValueError, OSError, UnicodeError):
        # Do not expose parser/file exceptions containing user-supplied secret values.
        parser.exit(1, 'Configuration rejected. Check role keys, required fields, file location/permissions and URL policy; no values were printed.\n')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Local-only destination fixtures. Credentials stay in memory, never env files."""
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.grot_config import private_path


def mock_settings(name):
    collector = dict(GRAFANA_OTLP_ENDPOINT=f'https://sink:18766/{name}/otlp',
        GRAFANA_METRICS_URL=f'https://sink:18766/{name}/metrics',
        GRAFANA_LOGS_URL=f'https://sink:18766/{name}/logs/loki/api/v1/push',
        GRAFANA_PROFILES_URL=f'https://sink:18766/{name}/profiles', GROT_CLUSTER=name)
    for signal in ('OTLP', 'METRICS', 'LOGS', 'PROFILES'):
        collector[f'GRAFANA_{signal}_USER'] = 'test-' + name
        collector[f'GRAFANA_{signal}_TOKEN'] = 'dummy-not-a-real-token'
    return {'alloy': collector, 'gateway': {'GRAFANA_FARO_URL': f'https://sink:18766/{name}/collect'}}


def certificate(root, hosts=('sink',)):
    root = private_path(root, must_exist=False)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2',
        '-subj', '/CN=sink', '-addext', 'subjectAltName=' + ','.join('DNS:' + host for host in hosts),
        '-addext', 'basicConstraints=critical,CA:TRUE',
        '-keyout', str(root / 'key.pem'), '-out', str(root / 'cert.pem')],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (root / 'key.pem').chmod(0o600)
    (root / 'cert.pem').chmod(0o644)  # Public CA must be readable by non-root consumers, even with umask 077.

if __name__ == '__main__': certificate(Path(sys.argv[1]))

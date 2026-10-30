import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import grot
from tests.telemetry.identity import SERVICES, assert_identities, fields, otlp_identities, prometheus_identities

ROOT = Path(__file__).resolve().parents[1]


def field(number, value):
    if isinstance(value, str): value = value.encode()
    length = len(value)
    size = bytearray()
    while length > 127:
        size.append((length & 127) | 128); length >>= 7
    size.append(length)
    return bytes([number << 3 | 2]) + size + value


def otlp(attributes):
    resource = b''.join(field(1, field(1, key) + field(2, field(1, value))) for key, value in attributes.items())
    return field(1, field(1, resource))


class DockerIdentityTests(unittest.TestCase):
    def test_remote_engine_not_cli_hostname_and_explicit_override(self):
        with patch.object(grot, 'run', return_value='remote-engine-uuid\n') as run:
            self.assertEqual('docker-remote-engine-uuid', grot.docker_host_id())
            run.assert_called_once_with(['docker', 'info', '--format', '{{.ID}}'])
        with patch.object(grot, 'run', side_effect=AssertionError('must not guess')):
            self.assertEqual('shared-machine-01', grot.docker_host_id('shared-machine-01'))
        for invalid in ('', 'a,b=c', 'a b', 'a\nb', '$(hostname)', 'a' * 129):
            with self.subTest(invalid=invalid), self.assertRaises(grot.SafeError): grot.docker_host_id(invalid)
        with patch.object(grot, 'run', return_value=''), self.assertRaises(grot.SafeError): grot.docker_host_id()

    def test_compose_passes_same_identity_only_to_apps_and_collector(self):
        command, env = grot.compose(None, argparse.Namespace(destination='identity-test'),
            {'host_id': 'host-1', 'instance_prefix': 'launch-1'})
        config = json.loads(subprocess.run(command + ['config', '--format', 'json'], cwd=ROOT, env=env,
            check=True, capture_output=True, text=True).stdout)
        for service in ('ui', 'cart', 'orders', 'catalog', 'checkout', 'alloy'):
            values = config['services'][service]['environment']
            self.assertEqual('host-1', values['GROT_HOST_ID'])
            self.assertEqual('launch-1', values['GROT_INSTANCE_PREFIX'])
        for service in ('postgres', 'gateway', 'runtime'):
            self.assertNotIn('GROT_HOST_ID', config['services'][service].get('environment', {}))

    def entrypoint(self, **values):
        env = dict(PATH=os.environ['PATH'], GROT_RUNTIME_ROLES='', **values)
        return subprocess.run(['sh', str(ROOT / 'deploy/docker/runtime-entrypoint.sh'), sys.executable, '-c',
            'import os; print(os.environ.get("OTEL_RESOURCE_ATTRIBUTES", ""))'], env=env, capture_output=True, text=True)

    def test_all_five_apps_inject_identity_and_preserve_other_attributes(self):
        for service in SERVICES:
            result = self.entrypoint(OTEL_SERVICE_NAME=service, GROT_HOST_ID='actual-engine-host', GROT_INSTANCE_PREFIX='launch-id',
                HOSTNAME='not-a-host-identifier', OTEL_RESOURCE_ATTRIBUTES='service.namespace=grot-emporium,custom.label=keep-me')
            self.assertEqual(0, result.returncode, result.stderr)
            attrs = dict(item.split('=', 1) for item in result.stdout.strip().split(','))
            self.assertEqual('actual-engine-host', attrs['grafana.host.id'])
            self.assertEqual('launch-id-' + service, attrs['service.instance.id'])
            self.assertEqual('keep-me', attrs['custom.label'])
            self.assertEqual('grot-emporium', attrs['service.namespace'])

    def test_missing_identity_fails_closed_and_non_apps_are_unchanged(self):
        self.assertNotEqual(0, self.entrypoint(OTEL_SERVICE_NAME='grot-ui').returncode)
        self.assertNotEqual(0, self.entrypoint(OTEL_SERVICE_NAME='grot-ui', GROT_HOST_ID='host').returncode)
        result = self.entrypoint()
        self.assertEqual(0, result.returncode)
        self.assertEqual('', result.stdout.strip())


class WireIdentityTests(unittest.TestCase):
    def test_extract_real_otlp_resources_and_kubernetes_precedence(self):
        attrs = {'service.name': 'grot-ui', 'service.instance.id': 'pod-uid', 'k8s.cluster.name': 'demo',
            'k8s.node.name': 'node-1', 'host.id': 'wrong-vm', 'grafana.host.id': 'fallback'}
        self.assertEqual([('grot-ui', 'node-1', 'pod-uid')], list(otlp_identities(otlp(attrs))))
        del attrs['k8s.node.name']
        self.assertEqual([('grot-ui', '', 'pod-uid')], list(otlp_identities(otlp(attrs))))
        del attrs['k8s.cluster.name']
        self.assertEqual([('grot-ui', 'wrong-vm', 'pod-uid')], list(otlp_identities(otlp(attrs))))
        del attrs['host.id']
        self.assertEqual([('grot-ui', 'fallback', 'pod-uid')], list(otlp_identities(otlp(attrs))))

    def test_runtime_series_are_checked_not_just_up(self):
        labels = {'__name__': 'jvm_memory_used_bytes', 'service_name': 'grot-ui', 'instance': 'pod-uid', 'k8s_node_name': 'node-1'}
        def encode(): return field(1, b''.join(field(1, field(1, key) + field(2, value)) for key, value in labels.items()))
        self.assertEqual([('grot-ui', 'node-1', 'pod-uid')], list(prometheus_identities(encode())))
        labels['__name__'] = 'up'
        self.assertEqual([], list(prometheus_identities(encode())))

    def test_missing_or_mismatched_exports_fail_acceptance(self):
        expected = {service: ('host', service + '-instance') for service in SERVICES}
        actual = {f'alpha:{signal}:{service}': [list(identity)] for service, identity in expected.items()
            for signal in ('traces', 'runtime-metrics')}
        assert_identities(actual, 'alpha', expected)
        actual['alpha:runtime-metrics:grot-ui'] = [['host', 'ip:8080']]
        with self.assertRaises(AssertionError): assert_identities(actual, 'alpha', expected)
        with self.assertRaises(AssertionError): assert_identities({}, 'alpha', expected)

    def test_malformed_protobuf_is_rejected(self):
        for data in (b'\x0a\x05x', b'\x80', b'\x0f', b'\x00'):
            with self.subTest(data=data), self.assertRaises(ValueError): list(fields(data))


if __name__ == '__main__': unittest.main()

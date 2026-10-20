"""Configuration rejection matrix; synthetic values only, no remote calls."""
import argparse
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import grot
from scripts.grot_config import validate, CLOUD_HOST_PREFIXES
from tests.test_destination_workflow import fixture, FakeCluster

ENDPOINTS = {
    'GRAFANA_OTLP_ENDPOINT': ('alloy', '/otlp'),
    'GRAFANA_METRICS_URL': ('alloy', '/api/prom/push'),
    'GRAFANA_LOGS_URL': ('alloy', '/loki/api/v1/push'),
    'GRAFANA_PROFILES_URL': ('alloy', ''),
    'GRAFANA_FARO_URL': ('gateway', '/collect/synthetic-key'),
}


class ConfigurationValidationTests(unittest.TestCase):
    def test_all_endpoint_paths_for_partial_and_complete_roles(self):
        paths = ['', '/', '/api/prom', '/api/prom/push', '/api/prom/push/', '/api/prom/push/push',
                 '/loki', '/loki/api/v1/push', '/loki/api/v1/push/', '/otlp', '/otlp/',
                 '/otlp/v1/traces', '/v1/traces', '/api/traces', '/profiles', '/ingest',
                 '/collect', '/collect/', '/collect/synthetic-key', '/collect/key/extra',
                 '//api/prom/push', '/api/../api/prom/push', '/api/prom/%70ush']
        for key, (role, correct) in ENDPOINTS.items():
            for path in paths:
                accepted = path == correct or (key == 'GRAFANA_PROFILES_URL' and path == '/')
                for partial in (True, False):
                    with self.subTest(key=key, path=path, partial=partial):
                        values = {key: 'https://synthetic.example.invalid' + path}
                        if not partial: values = dict(fixture()[role], **values)
                        if accepted: validate(role, values, partial=partial)
                        else:
                            with self.assertRaises(ValueError): validate(role, values, partial=partial)

    def test_bad_url_syntax_rejected_for_every_endpoint(self):
        hosts = ['http://synthetic.example.invalid', 'ftp://synthetic.example.invalid',
                 'https://', 'https://@synthetic.example.invalid', 'https://user:secret@synthetic.example.invalid',
                 'https://bad..host', 'https://bad_host', 'https://-bad.host', 'https://bad-.host',
                 'https://999.999.999.999', 'https://host:0', 'https://host:65536', 'https://host:',
                 'https://host:abc', 'https://[broken', 'https://host\\evil', 'https://host\x00',
                 'https://host\n', 'https://host\t', 'https://host\x7f', ' https://host',
                 'https://host;injection', 'https://host$variable', 'https://host"', 'https://host\u200b']
        for key, (role, path) in ENDPOINTS.items():
            for host in hosts:
                with self.subTest(key=key, host=host), self.assertRaises(ValueError):
                    validate(role, {key: host + path}, partial=True)
            for suffix in ('?', '?key=canary', '#', '#canary', ' ', '\n', '\r', '\t'):
                with self.subTest(key=key, suffix=suffix), self.assertRaises(ValueError):
                    validate(role, {key: 'https://synthetic.example.invalid' + path + suffix}, partial=True)

    def test_cloud_service_host_must_match_field(self):
        prefixes = CLOUD_HOST_PREFIXES
        for key, (role, path) in ENDPOINTS.items():
            for prefix in [*prefixes.values(), 'stack-']:
                with self.subTest(key=key, prefix=prefix):
                    value = 'https://' + prefix + 'synthetic.grafana.net' + path
                    if prefix == prefixes[key]: validate(role, {key: value}, partial=True)
                    else:
                        with self.assertRaises(ValueError): validate(role, {key: value}, partial=True)

    def test_required_and_optional_empty_values(self):
        roles = fixture()
        for key in roles['alloy']:
            for partial in (True, False):
                with self.subTest(key=key, partial=partial), self.assertRaises(ValueError):
                    validate('alloy', {key: ''} if partial else dict(roles['alloy'], **{key: ''}), partial=partial)
        validate('gateway', {'GRAFANA_FARO_URL': ''})

    def test_usernames_and_tokens_share_validation_across_routes(self):
        for signal in ('OTLP', 'METRICS', 'LOGS', 'PROFILES'):
            for field in ('USER', 'TOKEN'):
                key = f'GRAFANA_{signal}_{field}'
                for value in (' leading', 'trailing ', 'embedded space', '\tcanary', 'canary\n', 'canary\x00', 'canary\x7f', 'canary\u200b'):
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        validate('alloy', {key: value}, partial=True)
            with self.assertRaises(ValueError): validate('alloy', {f'GRAFANA_{signal}_USER': 'user:password'}, partial=True)

    def test_types_controls_bounds_and_unknown_keys(self):
        for role in ('backend', 'ui', 'alloy', 'gateway'):
            with self.assertRaises(ValueError): validate(role, {'UNKNOWN_PRIVATE_CANARY': 'x'})
            with self.assertRaises(ValueError): validate(role, [])
        for value in (None, 123, True, [], {}, 'x' * 8193, 'x\x01y', 'x\ud800', 'x\x85y', 'x\u2028y'):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                validate('alloy', {'GRAFANA_OTLP_TOKEN': value}, partial=True)
            with self.assertRaises(ValueError):
                validate('backend', {'OTEL_RESOURCE_ATTRIBUTES': value}, partial=True)

    def test_enums_numeric_fields_and_required_dependencies(self):
        for role, key, value in [('backend', 'OTEL_SDK_DISABLED', 'yes'), ('backend', 'OTEL_EXPORTER_OTLP_PROTOCOL', 'grpc'),
                                 ('backend', 'OTEL_METRICS_EXPORTER', 'invalid'), ('backend', 'OTEL_LOGS_EXPORTER', 'otlp'),
                                 ('backend', 'OTEL_TRACES_SAMPLER', 'invalid'), ('ui', 'AGENTO11Y_AUTH_MODE', 'none'),
                                 ('ui', 'RETAIL_UI_CHAT_PROVIDER', 'invalid')]:
            with self.subTest(key=key), self.assertRaises(ValueError): validate(role, {key: value}, partial=True)
        for value in ('NaN', 'inf', '-1', '1.1', 'invalid', '0_0.5'):
            with self.subTest(ratio=value), self.assertRaises(ValueError): validate('backend', {'OTEL_TRACES_SAMPLER_ARG': value}, partial=True)
        for value in ('0', '1', '0.5', '1e-2'): validate('backend', {'OTEL_TRACES_SAMPLER_ARG': value}, partial=True)
        for value in ('0', '-1', '1.5', '2147483648', 'invalid'):
            with self.subTest(interval=value), self.assertRaises(ValueError): validate('backend', {'OTEL_METRIC_EXPORT_INTERVAL': value}, partial=True)
        for values in ({'OTEL_SDK_DISABLED': 'false'}, {'PYROSCOPE_ENABLED': 'true'}):
            validate('backend', values, partial=True)
            with self.assertRaises(ValueError): validate('backend', values)
        with self.assertRaises(ValueError): validate('ui', {'FARO_ENABLED': 'true'})
        with self.assertRaises(ValueError): validate('ui', {'GROT_AGENT_OBSERVABILITY_ENABLED': 'true'})
        with self.assertRaises(ValueError): validate('ui', {'RETAIL_UI_CHAT_ENABLED': 'true', 'RETAIL_UI_CHAT_PROVIDER': 'openai'})

    def test_relative_faro_paths_and_backend_signal_suffixes(self):
        for path in ('//evil', '/a b', '/a?x', '/a#x', '/a/../b', '/%2f%2fevil', '/a\x01'):
            with self.subTest(path=path), self.assertRaises(ValueError): validate('ui', {'FARO_COLLECTOR_URL': path})
        validate('ui', {'FARO_COLLECTOR_URL': '/telemetry'})
        for path in ('/v1/traces', '/otlp/v1/traces', '/v1/metrics', '/v1/logs'):
            with self.assertRaises(ValueError): validate('backend', {'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://alloy:4318' + path})

    def test_every_prompt_retries_the_same_field(self):
        for key, (role, path) in ENDPOINTS.items():
            good = 'https://synthetic.example.invalid' + path
            bad = 'https://synthetic.example.invalid/incorrect-private-canary'
            with self.subTest(key=key), patch.object(grot.getpass, 'getpass', side_effect=[bad, good]) as prompt, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(good, grot.prompt_setting('Current field', role, key))
                self.assertEqual(2, prompt.call_count)
                self.assertEqual(prompt.call_args_list[0], prompt.call_args_list[1])
                self.assertNotIn('private-canary', output.getvalue())

    def test_invalid_json_and_managed_secrets_rejected_before_mutation(self):
        for key, (role, _) in ENDPOINTS.items():
            roles = fixture(); roles[role][key] = 'https://synthetic.example.invalid/wrong-private-canary'
            args = argparse.Namespace(destination='team-a', context='test', namespace='grot-team-a', image_prefix='registry.example.invalid/team', image_tag='test', mode='quick', settings_stdin=True, pull_secret=None)
            cluster = FakeCluster()
            with self.subTest(key=key), patch.object(grot, 'run', side_effect=cluster), patch.object(grot.sys, 'stdin', io.StringIO(json.dumps(roles))), self.assertRaises(grot.SafeError):
                grot.k8s(args)
            self.assertFalse(any(any(action in c for action in ('create', 'replace', 'upgrade', 'install', 'delete')) for c, _ in cluster.calls))
            args.mode = 'long-term'; args.settings_stdin = False
            for r, name in grot.SECRET_NAMES.items():
                cluster.objects[('secret', name)] = {'data': {k: base64.b64encode(v.encode()).decode() for k, v in roles[r].items()}}
            cluster.calls = []
            with patch.object(grot, 'run', side_effect=cluster), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(grot.SafeError): grot.k8s(args)
            self.assertFalse(any(any(action in c for action in ('create', 'replace', 'upgrade', 'install', 'delete')) for c, _ in cluster.calls))

    def test_real_launcher_rejects_bad_json_before_calling_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docker').write_text('#!/bin/sh\nprintf unexpected > "$HOME/unexpected-call"\nexit 99\n')
            (root / 'docker').chmod(0o700)
            env = dict(os.environ, HOME=directory, XDG_STATE_HOME=str(root / 'state'), PATH=directory + os.pathsep + os.environ['PATH'])
            for key, (role, _) in ENDPOINTS.items():
                roles = fixture()
                roles[role][key] = 'https://synthetic.example.invalid/wrong-private-canary'
                with self.subTest(key=key):
                    result = subprocess.run(['./grot', 'docker', 'validation-test', '--settings-stdin'],
                        input=json.dumps(roles), cwd=grot.ROOT, env=env, text=True, capture_output=True, timeout=10)
                    self.assertEqual(1, result.returncode)
                    self.assertNotIn('wrong-private-canary', result.stdout + result.stderr)
                    self.assertFalse((root / 'unexpected-call').exists())
                    self.assertFalse((root / 'state').exists())

    def test_duplicate_json_keys_rejected_without_echo(self):
        for payload in ('{"alloy":{},"alloy":{}}', '{"alloy":{"GRAFANA_OTLP_TOKEN":"secret-canary","GRAFANA_OTLP_TOKEN":"other"}}'):
            with patch.object(grot.sys, 'stdin', io.StringIO(payload)), self.assertRaises(grot.SafeError) as caught:
                grot.settings(argparse.Namespace(settings_stdin=True))
            self.assertNotIn('secret-canary', str(caught.exception))

    @unittest.skipUnless(os.name == 'posix', 'Hidden-input terminal test requires a POSIX PTY')
    def test_real_terminal_rejects_metrics_base_before_username_and_keeps_answers(self):
        import pty
        pid, fd = pty.fork()
        if pid == 0:
            code = ('from scripts import grot; from types import SimpleNamespace; '
                    'r=grot.settings(SimpleNamespace(destination="terminal-test",settings_stdin=False)); '
                    'assert r["alloy"]["GRAFANA_OTLP_USER"]=="saved-trace-user"; '
                    'assert r["alloy"]["GRAFANA_METRICS_URL"].endswith("/api/prom/push"); '
                    'print("TERMINAL_VALIDATION_PASSED")')
            os.execv(sys.executable, [sys.executable, '-c', code])
        transcript = b''
        def expect(text):
            nonlocal transcript
            deadline = time.monotonic() + 10
            data = b''
            while text.encode() not in data:
                if time.monotonic() > deadline: self.fail('Terminal did not reach expected prompt: ' + text)
                if select.select([fd], [], [], 0.2)[0]:
                    try: chunk = os.read(fd, 65536)
                    except OSError: self.fail('Terminal exited before expected prompt')
                    if not chunk: self.fail('Terminal closed before expected prompt')
                    data += chunk; transcript += chunk
            return data
        steps = [
            ('OTLP (Traces) ingestion endpoint: ', 'https://synthetic.example.invalid'),
            ('OTLP (Traces) ingestion endpoint: ', 'https://synthetic.example.invalid/otlp/v1/traces'),
            ('OTLP (Traces) ingestion endpoint: ', 'https://synthetic.example.invalid/otlp'),
            ('OTLP (Traces) ingestion username', 'bad:user'),
            ('OTLP (Traces) ingestion username', 'saved-trace-user'),
            ('Metrics (Prometheus remote write) ingestion endpoint: ', 'https://synthetic.example.invalid/api/prom'),
            ('Metrics (Prometheus remote write) ingestion endpoint: ', 'https://synthetic.example.invalid/api/prom/push'),
            ('Metrics (Prometheus remote write) ingestion username', ''),
            ('Metrics (Prometheus remote write) ingestion username', 'metrics-user'),
            ('Logs (Loki push) ingestion endpoint: ', 'https://synthetic.example.invalid'),
            ('Logs (Loki push) ingestion endpoint: ', 'https://synthetic.example.invalid/loki/api/v1/push'),
            ('Logs (Loki push) ingestion username', 'bad user'),
            ('Logs (Loki push) ingestion username', 'logs-user'),
            ('Profiles (Pyroscope) ingestion endpoint: ', 'https://synthetic.example.invalid/ingest'),
            ('Profiles (Pyroscope) ingestion endpoint: ', 'https://synthetic.example.invalid'),
            ('Profiles (Pyroscope) ingestion username', 'trailing '),
            ('Profiles (Pyroscope) ingestion username', 'profiles-user'),
            ('Shared ingestion API token', 'bad token'),
            ('Shared ingestion API token', 'private-canary-token'),
            ('Faro (Browser) collector URL', 'https://synthetic.example.invalid/collect'),
            ('Faro (Browser) collector URL', 'https://synthetic.example.invalid/collect/test-key'),
        ]
        try:
            for label, answer in steps:
                data = expect(label)
                if answer.endswith('/api/prom/push'):
                    self.assertNotIn(b'ingestion username', data)
                    self.assertIn(b'full Prometheus remote-write URL', data)
                os.write(fd, (answer + '\n').encode())
            expect('TERMINAL_VALIDATION_PASSED')
            self.assertEqual(3, transcript.count(b'OTLP (Traces) ingestion endpoint: '))
            self.assertEqual(2, transcript.count(b'OTLP (Traces) ingestion username'))
            self.assertNotIn(b'private-canary-token', transcript)
            self.assertNotIn(b'https://synthetic.example.invalid', transcript)
            _, status = os.waitpid(pid, 0); pid = None
            self.assertEqual(0, os.waitstatus_to_exitcode(status))
        finally:
            os.close(fd)
            if pid is not None:
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)

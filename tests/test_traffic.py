import argparse
import contextlib
import io
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from scripts import grot, grot_traffic as traffic


class TrafficTests(unittest.TestCase):
    def args(self, **overrides):
        values = dict(destination='demo', context='test', namespace='grot-demo', action='start', local_only=True, preset='low', duration='1h', rate=None, browser_rate=None)
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_chat_is_off_by_default_and_requires_paid_consent(self):
        self.assertEqual('0', traffic.settings(self.args(), grot)[1]['GROT_CHAT_INTERVAL_SECONDS'])
        with self.assertRaises(grot.SafeError): traffic.settings(self.args(chat_every='5m'), grot)
        _, env = traffic.settings(self.args(chat_every='5m', allow_paid_ai=True, chat_max_requests=60), grot)
        self.assertEqual('300', env['GROT_CHAT_INTERVAL_SECONDS'])
        self.assertEqual('60', env['GROT_CHAT_MAX_REQUESTS'])
        self.assertEqual('true', env['ALLOW_PAID_AI'])
        self.assertIn('chat-traffic.js', traffic.FILES)
        for opts in [dict(chat_every='30s'), dict(chat_every='2h'), dict(chat_every='invalid'), dict(chat_max_requests=0), dict(chat_max_requests=1001)]:
            with self.assertRaises(grot.SafeError): traffic.settings(self.args(allow_paid_ai=True, **opts), grot)

    def test_chat_errors_are_explicit_and_bounded(self):
        self.assertEqual('0', traffic.settings(self.args(), grot)[1]['GROT_CHAT_ERROR_EVERY'])
        with self.assertRaises(grot.SafeError): traffic.settings(self.args(chat_error_every=10), grot)
        for cadence in [-1, 1, 1001]:
            with self.assertRaises(grot.SafeError): traffic.settings(self.args(chat_every='5m', allow_paid_ai=True, chat_error_every=cadence), grot)
        _, env = traffic.settings(self.args(chat_every='5m', allow_paid_ai=True, chat_error_every=10), grot)
        self.assertEqual('10', env['GROT_CHAT_ERROR_EVERY'])
        self.assertIn('GROT_CHAT_ERROR_EVERY', traffic.CLOUD_ENTRYPOINT)

    def test_recurring_schedule_is_bounded_and_non_overlapping(self):
        objects = []
        ledger = {'data': {'destination': 'demo', 'owner': 'test'}}
        def get(kube, kind, name):
            if name == grot.LEDGER: return ledger
            if kind == 'cronjob' and any(o['kind'] == 'CronJob' for o in objects):
                return {'status': {'active': [{'name': 'grot-demo-traffic-123'}]}}
            return None
        def execute(command, **kwargs):
            if 'data' in kwargs: objects.append(json.loads(kwargs['data']))
            return '{"items":[{"status":{"phase":"Running"}}]}' if 'pods' in command else ''
        with patch.object(grot, 'get_object', side_effect=get), patch.object(grot, 'owned', return_value=True), patch.object(grot, 'run', side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
            traffic.run(self.args(repeat=True), grot)
        cron = next(o for o in objects if o['kind'] == 'CronJob')
        self.assertEqual('Forbid', cron['spec']['concurrencyPolicy'])
        self.assertEqual(45, cron['spec']['startingDeadlineSeconds'])
        self.assertEqual(3780, cron['spec']['jobTemplate']['spec']['activeDeadlineSeconds'])
        self.assertFalse(any(o['kind']=='Job' for o in objects))

    def test_fault_defaults_and_limits(self):
        _, env = traffic.settings(self.args(failures=True), grot)
        self.assertEqual(('true', '1', '5', '2000', '60'), tuple(env[k] for k in ('GROT_FAILURES', 'GROT_ERROR_PERCENT', 'GROT_SLOW_PERCENT', 'GROT_DELAY_MS', 'GROT_FAULT_RATE')))
        self.assertEqual('false', traffic.settings(self.args(), grot)[1]['GROT_FAILURES'])
        for fields in [dict(error_percent=51), dict(slow_percent=-1), dict(delay_ms=5001), dict(fault_rate=0)]:
            with self.assertRaises(grot.SafeError): traffic.settings(self.args(failures=True, **fields), grot)
        with self.assertRaises(grot.SafeError): traffic.settings(self.args(error_percent=10), grot)
        self.assertIn('faults.js', traffic.FILES)
        self.assertIn('GROT_FAILURES=$GROT_FAILURES', traffic.CLOUD_ENTRYPOINT)

    def test_old_images_fail_closed(self):
        error = traffic.runner_failure('Catalog image does not support request-scoped faults private-canary', grot)
        self.assertIn('updated catalog image', str(error))
        self.assertNotIn('private-canary', str(error))

    def test_cloud_requires_explicit_context(self):
        with self.assertRaises(grot.SafeError):
            traffic.cloud_settings(self.args(local_only=False), grot)

    def test_cloud_auth_stays_out_of_command_arguments(self):
        responses = ['[{"metadata":{"name":"123","namespace":"stacks-456"}}]', 'synthetic-k6-token']
        with patch.object(grot, 'run', autospec=True, side_effect=responses) as run, contextlib.redirect_stdout(io.StringIO()):
            env, token = traffic.cloud_settings(self.args(local_only=False, grafana_context='cloud', k6_project=123), grot)
        self.assertEqual('synthetic-k6-token', token)
        self.assertEqual('123', env['K6_CLOUD_PROJECT_ID'])
        self.assertEqual('456', env['K6_CLOUD_STACK_ID'])
        self.assertNotIn(token, json.dumps(env))
        self.assertNotIn(token, str(run.call_args_list))
        self.assertIn('--local-execution', traffic.CLOUD_ENTRYPOINT)
        self.assertIn('--no-archive-upload', traffic.CLOUD_ENTRYPOINT)

    def test_cloud_job_token_only_in_secret_stdin(self):
        calls = []
        def execute(command, **kwargs):
            calls.append((command, kwargs))
            return '{"items":[{"status":{"phase":"Running"}}]}' if 'pods' in command else ''
        ledger = {'data': {'destination': 'demo', 'owner': 'test'}}
        env = {'K6_CLOUD_PROJECT_ID': '123', 'K6_CLOUD_STACK_ID': '456', 'GROT_K6_TEST_NAME': 'test'}
        with patch.object(traffic, 'cloud_settings', return_value=(env, 'sensitive-canary')), patch.object(traffic, 'verify_cloud_registration'), patch.object(grot, 'get_object', side_effect=lambda k,t,n: ledger if n == grot.LEDGER else None), patch.object(grot, 'owned', return_value=True), patch.object(grot, 'run', side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
            traffic.run(self.args(local_only=False), grot)
        objects = [json.loads(kw['data']) for _, kw in calls if 'data' in kw]
        secret = next(o for o in objects if o['kind']=='Secret')
        self.assertEqual('sensitive-canary', secret['stringData']['token'])
        for obj in objects:
            if obj['kind'] != 'Secret': self.assertNotIn('sensitive-canary', json.dumps(obj))
        self.assertNotIn('sensitive-canary', json.dumps([c for c,_ in calls]))
        self.assertNotIn('-e "K6_CLOUD_TOKEN', traffic.CLOUD_ENTRYPOINT)
        self.assertIn('-e "BASE_URL=$BASE_URL"', traffic.CLOUD_ENTRYPOINT)

    def test_cloud_registration_matches_runner_run_id(self):
        env = {'GROT_K6_TEST_NAME': 'test', 'K6_CLOUD_PROJECT_ID': '123'}
        with patch.object(grot, 'run', side_effect=['output: cloud (https://test.grafana.net/a/k6-app/runs/99)', '[{"id":99,"status":"running"}]']), contextlib.redirect_stdout(io.StringIO()) as output:
            traffic.verify_cloud_registration(self.args(grafana_context='cloud'), env, grot)
        self.assertIn('registration verified', output.getvalue())

    def test_cloud_duration_limit_is_reported_without_private_log_output(self):
        error = traffic.runner_failure('private-canary maximum allowed for your project (18000 seconds)', grot)
        self.assertIn('--duration 5h', str(error))
        self.assertNotIn('private-canary', str(error))

    def test_docker_cloud_token_uses_stdin_and_tmpfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'run.json').write_text('{"faro":true}')
            env = {'K6_CLOUD_PROJECT_ID': '123', 'K6_CLOUD_STACK_ID': '456', 'GROT_K6_TEST_NAME': 'test'}
            with patch.object(grot, 'profile_path', return_value=root), patch.object(traffic, 'cloud_settings', return_value=(env, 'secret-canary')), patch.object(traffic, 'verify_cloud_registration'), patch.object(traffic, 'docker_object', side_effect=[None, {'State': {'Status': 'running'}}]), patch.object(traffic.time, 'sleep'), patch.object(grot, 'run', autospec=True, return_value='') as run, contextlib.redirect_stdout(io.StringIO()):
                traffic.run(self.args(context=None, namespace=None, local_only=False), grot)
            self.assertEqual('secret-canary', run.call_args.kwargs['data'])
            commands = [c.args[0] for c in run.call_args_list]
            self.assertNotIn('secret-canary', json.dumps(commands))
            self.assertIn('--tmpfs', commands[0])
            self.assertIn('exec', commands[1])

    def test_presets_and_custom_rates(self):
        for preset, expected in traffic.PRESETS.items():
            seconds, env = traffic.settings(self.args(preset=preset), grot)
            self.assertEqual(3600, seconds)
            self.assertEqual(expected, (int(env['JOURNEYS_PER_MINUTE']), int(env['BROWSER_JOURNEYS_PER_MINUTE'])))
        self.assertEqual('0', traffic.settings(self.args(rate=11, browser_rate=0), grot)[1]['BROWSER_JOURNEYS_PER_MINUTE'])

    def test_invalid_settings(self):
        for values in [dict(duration='0s'), dict(duration='25h'), dict(duration='forever'), dict(rate=0), dict(rate=601), dict(browser_rate=-1), dict(browser_rate=11)]:
            with self.assertRaises(grot.SafeError): traffic.settings(self.args(**values), grot)

    def test_job_is_bounded_and_has_no_credentials_or_service_account(self):
        calls = []
        def execute(command, **kwargs):
            calls.append((command, kwargs))
            return '{"items":[{"status":{"phase":"Running"}}]}' if 'pods' in command else ''
        ledger = {'data': {'destination': 'demo', 'owner': 'test'}}
        def get(kube, kind, name): return ledger if name == grot.LEDGER else None
        with patch.object(grot, 'get_object', side_effect=get), patch.object(grot, 'owned', return_value=True), patch.object(grot, 'run', side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
            traffic.run(self.args(), grot)
        objects = [json.loads(kw['data']) for _, kw in calls if 'data' in kw]
        job = next(o for o in objects if o['kind'] == 'Job')
        self.assertEqual(0, job['spec']['backoffLimit'])
        self.assertEqual(3780, job['spec']['activeDeadlineSeconds'])
        spec = job['spec']['template']['spec']
        self.assertFalse(spec['automountServiceAccountToken'])
        self.assertNotIn('secret', json.dumps(spec).lower())
        self.assertEqual('http://grot-gateway', next(e['value'] for e in spec['containers'][0]['env'] if e['name'] == 'BASE_URL'))
        self.assertEqual(set(traffic.FILES), set(objects[0]['data']))

    def test_start_requires_owned_app(self):
        with patch.object(grot, 'get_object', return_value=None), self.assertRaises(grot.SafeError):
            traffic.run(self.args(), grot)

    def test_stop_refuses_unrelated_job(self):
        with patch.object(grot, 'get_object', return_value={'metadata': {}}), patch.object(grot, 'run') as run:
            with self.assertRaises(grot.SafeError): traffic.stop(self.args(), grot)
            run.assert_not_called()

    def test_docker_targets_compose_gateway_port_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'run.json').write_text('{"faro":true}')
            with patch.object(grot, 'profile_path', return_value=root), patch.object(traffic, 'docker_object', side_effect=[None, {'State': {'Status': 'running'}}]), patch.object(traffic.time, 'sleep'), patch.object(grot, 'run', autospec=True, return_value='') as run, contextlib.redirect_stdout(io.StringIO()):
                traffic.run(self.args(context=None, namespace=None), grot)
            command = run.call_args.args[0]
            self.assertIn('BASE_URL=http://gateway:8080', command)
            self.assertIn('EXPECT_FARO=true', command)
            self.assertNotIn('/run/grot', ' '.join(command))

    def test_docker_lookup_uses_supported_runner_signature(self):
        with patch.object(grot, 'run', autospec=True, return_value='') as run:
            self.assertIsNone(traffic.docker_object(self.args(context=None, namespace=None), grot))
            self.assertIn('ls', run.call_args.args[0])

    def test_docker_refuses_unrelated_container(self):
        with patch.object(traffic, 'docker_object', return_value={'Config': {'Labels': {}}}), patch.object(grot, 'run') as run:
            with self.assertRaises(grot.SafeError): traffic.stop(self.args(context=None, namespace=None), grot)
            run.assert_not_called()

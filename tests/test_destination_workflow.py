import argparse
import base64
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml
from scripts import grot
from scripts.sync_grot_alloy import outputs


def fixture():
    collector = {'GROT_CLUSTER': 'team-a'}
    for signal, field in [('OTLP', 'ENDPOINT'), ('METRICS', 'URL'), ('LOGS', 'URL'), ('PROFILES', 'URL')]:
        collector[f'GRAFANA_{signal}_{field}'] = 'https://private.example.invalid' + {'OTLP': '/otlp', 'METRICS': '/api/prom/push', 'LOGS': '/loki/api/v1/push', 'PROFILES': ''}[signal]
        collector[f'GRAFANA_{signal}_USER'] = 'test-tenant'
        collector[f'GRAFANA_{signal}_TOKEN'] = 'synthetic-private-token'
    return grot.make_roles({'alloy': collector, 'gateway': {'GRAFANA_FARO_URL': 'https://private-faro.example.invalid/collect/test-key'}})


class FakeCluster:
    def __init__(self): self.objects = {}; self.calls = []; self.releases = []
    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[0] == 'helm':
            if 'list' in command: return json.dumps(self.releases)
            if '--help' in command: return '--atomic'
            return ''
        if 'get' in command:
            at = command.index('get'); kind, name = command[at+1:at+3]
            if kind == 'namespace': return '{"metadata":{"name":"grot-team-a"}}'
            return json.dumps(self.objects[(kind.rstrip('s'), name)]) if (kind.rstrip('s'), name) in self.objects else ''
        if '-f' in command and ('create' in command or 'replace' in command):
            obj = json.loads(kwargs['data']); meta = obj['metadata']
            meta.update(uid=meta.get('uid', 'test-uid'), resourceVersion='1')
            self.objects[(obj['kind'].lower(), meta['name'])] = obj
        return ''


class DestinationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(grot, 'CONFIG_ROOT', self.root / 'state')
        patcher.start(); self.addCleanup(patcher.stop)
        infrastructure = patch.object(grot, 'setup_infrastructure')
        infrastructure.start(); self.addCleanup(infrastructure.stop)
        verifier = patch.object(grot, 'verify_k8s')
        verifier.start(); self.addCleanup(verifier.stop)
        self.roles = fixture()
        self.args = argparse.Namespace(destination='team-a', context='test', namespace='grot-team-a',
            image_prefix='registry.example.invalid/team', image_tag='test-sha', mode='quick', settings_stdin=False, pull_secret=None)

    def test_install_prints_progress_and_exact_followup_commands_without_secrets(self):
        cluster = FakeCluster()
        self.args.context = 'test context'
        self.args.namespace = 'grot-custom'
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', return_value=self.roles), contextlib.redirect_stdout(io.StringIO()) as output:
            grot.k8s(self.args)
        text = output.getvalue()
        for step in range(1, 9): self.assertIn(f'[{step}/8]', text)
        self.assertIn('Waiting for grot-alloy', text)
        self.assertIn("Ready: destination=team-a, context='test context', namespace=grot-custom", text)
        self.assertIn("./grot verify team-a --context 'test context' --namespace grot-custom", text)
        self.assertIn("kubectl --context 'test context' -n grot-custom port-forward service/grot-gateway 8080:80", text)
        self.assertIn("./grot stop team-a --context 'test context' --namespace grot-custom", text)
        self.assertIn('same terminal/KUBECONFIG', text)
        self.assertIn('View the app: http://localhost:8080 (after starting port-forward below)', text)
        self.assertIn('leave it running while browsing', text)
        for value in self.roles['database'].values(): self.assertNotIn(value, text)
        self.assertNotIn('synthetic-private-token', text)
        self.assertNotIn('https://private', text)

    def test_prompt_retries_only_invalid_field_and_preserves_prior_answers(self):
        answers = [
            'https://example.invalid/otlp', 'trace-user',
            'https://example.invalid/api/prom/push', 'metrics-user',
            'https://example.invalid/loki/api/v1/push', 'logs-user',
            'https://example.invalid/private-canary?bad=true',
            'https://profiles.example.invalid ',
            'https://profiles.example.invalid', 'profiles-user',
            '', 'token with whitespace', 'synthetic-token',
            'invalid-faro-canary', 'https://example.invalid/collect/test',
        ]
        output = io.StringIO()
        with patch.object(grot.sys.stdin, 'isatty', return_value=True), patch.object(grot.getpass, 'getpass', side_effect=answers) as prompt, contextlib.redirect_stdout(output):
            roles = grot.settings(self.args)
        labels = [call.args[0] for call in prompt.call_args_list]
        self.assertEqual(3, labels.count('Profiles (Pyroscope) ingestion endpoint: '))
        self.assertEqual(1, labels.count('OTLP (Traces) ingestion endpoint: '))
        self.assertEqual('trace-user', roles['alloy']['GRAFANA_OTLP_USER'])
        self.assertEqual('https://profiles.example.invalid', roles['alloy']['GRAFANA_PROFILES_URL'])
        for signal in ('OTLP', 'METRICS', 'LOGS', 'PROFILES'):
            self.assertEqual('synthetic-token', roles['alloy'][f'GRAFANA_{signal}_TOKEN'])
        for value in answers:
            if value: self.assertNotIn(value, output.getvalue())
        self.assertIn('leading or trailing whitespace', output.getvalue())
        self.assertIn('Optional AI chat is configured separately', output.getvalue())
        self.assertNotIn('Model calls remain disabled', output.getvalue())
        self.assertEqual([], list(self.root.iterdir()))

    def test_logs_prompt_rejects_base_url_without_loki_push_path(self):
        with patch.object(grot.getpass, 'getpass', side_effect=['https://logs.example.invalid', 'https://logs.example.invalid/loki/api/v1/push']) as prompt, contextlib.redirect_stdout(io.StringIO()) as output:
            value = grot.prompt_setting('Logs', 'alloy', 'GRAFANA_LOGS_URL')
        self.assertEqual(2, prompt.call_count)
        self.assertTrue(value.endswith('/loki/api/v1/push'))
        self.assertIn('not the base URL', output.getvalue())
        self.assertNotIn('logs.example.invalid', output.getvalue())

    def test_profiles_url_format_and_partial_validation_keep_full_requirements(self):
        # Synthetic hostname with the same region/number shape as the reported URL;
        # private stack endpoints must not become repository fixtures.
        grot.validate('alloy', {'GRAFANA_PROFILES_URL': 'https://profiles-prod-006.example.invalid'}, partial=True)
        with self.assertRaises(grot.SafeError):
            grot.validate('alloy', {'GRAFANA_PROFILES_URL': 'https://profiles-prod-006.example.invalid'})

    def test_optional_chat_settings_use_actual_spring_model_property(self):
        self.roles['ui'].update({
            'RETAIL_UI_CHAT_ENABLED': 'true', 'RETAIL_UI_CHAT_PROVIDER': 'openai',
            'RETAIL_UI_CHAT_MODEL': 'approved-test-model',
            'RETAIL_UI_CHAT_OPENAI_BASE_URL': 'https://model.example.invalid',
            'RETAIL_UI_CHAT_OPENAI_API_KEY': 'synthetic-model-key',
        })
        roles = grot.make_roles(self.roles)
        self.assertEqual('approved-test-model', roles['ui']['RETAIL_UI_CHAT_MODEL'])
        self.assertEqual('false', roles['ui']['GROT_AGENT_OBSERVABILITY_ENABLED'])
        for obsolete in ('RETAIL_UI_CHAT_OPENAI_MODEL', 'RETAIL_UI_CHAT_BEDROCK_MODEL'):
            with self.assertRaises(grot.SafeError):
                grot.validate('ui', {obsolete: 'silently-ignored-by-app'})

    def test_optional_faro_blank_is_accepted(self):
        with patch.object(grot.getpass, 'getpass', return_value='') as prompt:
            self.assertEqual('', grot.prompt_setting('Faro', 'gateway', 'GRAFANA_FARO_URL', optional=True))
        prompt.assert_called_once()

    def test_probe_reports_heartbeat_and_pass_without_printing_private_output(self):
        process = unittest.mock.Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired('probe', 10), ('private-output-canary', 'private-error-canary')]
        process.returncode = 0
        process.poll.return_value = 0
        output = io.StringIO()
        with patch.object(grot.subprocess, 'Popen', return_value=process), contextlib.redirect_stdout(output):
            grot.run_probe(['test-probe'], 'Browser test')
        for expected in ('starting', 'still running', 'passed'):
            self.assertIn(expected, output.getvalue())
        self.assertNotIn('canary', output.getvalue())

    def test_probe_failure_names_stage_without_leaking_output(self):
        process = unittest.mock.Mock()
        process.communicate.return_value = ('private-output-canary', 'private-error-canary')
        process.returncode = 1
        process.poll.return_value = 1
        with patch.object(grot.subprocess, 'Popen', return_value=process), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(grot.SafeError, 'Shopping test failed') as error:
            grot.run_probe(['test-probe'], 'Shopping test')
        self.assertNotIn('canary', str(error.exception))

    def test_stale_ui_probe_error_is_actionable_without_exposing_output(self):
        process = unittest.mock.Mock()
        process.communicate.return_value = ('private-canary', 'GROT_VERIFY_UI_OUTDATED')
        process.returncode = 99
        process.poll.return_value = 99
        with patch.object(grot.subprocess, 'Popen', return_value=process), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(grot.SafeError) as error:
            grot.run_probe(['test-probe'], 'Browser')
        self.assertIn('rebuild and restart the UI', str(error.exception))
        self.assertNotIn('private-canary', str(error.exception))

    def test_gcx_timeout_has_safe_reason(self):
        with patch.object(grot.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gcx', 60, output='private-canary')), self.assertRaises(grot.SafeError) as error:
            grot.run(['gcx', 'logs', 'query'])
        self.assertIn('timed out after 60 seconds', str(error.exception))
        self.assertNotIn('private-canary', str(error.exception))

    def test_gcx_permission_failure_has_safe_reason(self):
        result = subprocess.CompletedProcess(['gcx'], 1, '', 'HTTP 403 Forbidden private-canary')
        with patch.object(grot.subprocess, 'run', return_value=result), self.assertRaises(grot.SafeError) as error:
            grot.run(['gcx', 'logs', 'query'])
        self.assertIn('query permissions', str(error.exception))
        self.assertNotIn('private-canary', str(error.exception))

    def test_release_discovery_works_without_removed_helm4_all_flag(self):
        with patch.object(grot, 'run', return_value='[]') as run:
            self.assertEqual([], grot.helm_releases(['helm']))
        command = run.call_args.args[0]
        self.assertNotIn('-a', command)
        for state in ('deployed', 'failed', 'pending', 'uninstalled', 'uninstalling', 'superseded'):
            self.assertIn('--' + state, command)

    def test_apps_only_know_internal_receivers(self):
        self.assertEqual('http://alloy:4318', self.roles['backend']['OTEL_EXPORTER_OTLP_ENDPOINT'])
        self.assertEqual('/telemetry', self.roles['ui']['FARO_COLLECTOR_URL'])
        self.assertEqual('false', self.roles['ui']['RETAIL_UI_CHAT_ENABLED'])
        for role in ('backend', 'ui'): self.assertNotIn('synthetic-private-token', json.dumps(self.roles[role]))

    def test_rotation_is_not_retargeting(self):
        before = grot.fingerprint(self.roles)
        self.roles['alloy']['GRAFANA_OTLP_TOKEN'] = 'rotated'
        self.assertEqual(before, grot.fingerprint(self.roles))
        self.roles['alloy']['GRAFANA_OTLP_USER'] = 'different-tenant'
        self.assertNotEqual(before, grot.fingerprint(self.roles))

    def test_quick_creates_owned_secrets_without_host_files_or_helm_values(self):
        cluster = FakeCluster()
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', return_value=self.roles), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(self.args)
        secrets = [obj for (kind, _), obj in cluster.objects.items() if kind == 'secret']
        self.assertEqual(5, len(secrets))
        owner = cluster.objects[('configmap', grot.LEDGER)]['data']['owner']
        self.assertTrue(all(grot.owned(obj, owner) for obj in secrets))
        self.assertEqual([], list(self.root.iterdir()))
        for command, _ in cluster.calls:
            self.assertNotIn('synthetic-private-token', str(command))
            self.assertNotIn('https://private.example.invalid', str(command))

    def test_quick_refuses_external_secrets_before_any_write(self):
        cluster = FakeCluster()
        cluster.objects[('secret', 'grot-ui-runtime')] = {'metadata': {'name': 'grot-ui-runtime'}}
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', return_value=self.roles), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(grot.SafeError):
            grot.k8s(self.args)
        self.assertFalse(any('data' in kwargs for _, kwargs in cluster.calls))

    def test_long_term_never_prompts_or_mutates_secrets(self):
        cluster = FakeCluster(); self.args.mode = 'long-term'
        for role, name in grot.SECRET_NAMES.items():
            cluster.objects[('secret', name)] = {'data': {k: base64.b64encode(v.encode()).decode() for k, v in self.roles[role].items()}}
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', side_effect=AssertionError('no prompt')), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(self.args)
        written = [json.loads(kwargs['data']) for _, kwargs in cluster.calls if 'data' in kwargs]
        self.assertFalse(any(obj['kind'] == 'Secret' for obj in written))
        self.assertEqual([], list(self.root.iterdir()))

    def test_demo_activity_starts_after_verification_by_default(self):
        cluster = FakeCluster()
        def verify(*args, **kwargs):
            self.assertNotIn(('deployment', 'grot-demo-activity'), cluster.objects)
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', return_value=self.roles), patch.object(grot, 'verify_k8s', side_effect=verify), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(self.args)
        self.assertIn(('deployment', 'grot-demo-activity'), cluster.objects)

    def test_quiet_deployment_does_not_create_demo_activity(self):
        cluster = FakeCluster()
        self.args.no_demo_traffic = True
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', return_value=self.roles), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(self.args)
        self.assertNotIn(('deployment', 'grot-demo-activity'), cluster.objects)
        self.assertNotIn(('configmap', 'grot-demo-activity'), cluster.objects)

    def test_quick_retarget_is_rejected_before_secret_updates(self):
        cluster = FakeCluster()
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', return_value=self.roles), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(self.args)
            cluster.calls.clear()
            self.roles['alloy']['GRAFANA_OTLP_USER'] = 'different-tenant'
            with self.assertRaises(grot.SafeError): grot.k8s(self.args)
        self.assertFalse(any('data' in kwargs for _, kwargs in cluster.calls))

    def test_partial_quick_cleanup_preserves_replaced_external_secret(self):
        cluster = FakeCluster()
        with patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', return_value=self.roles), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(self.args)
            cluster.objects[('secret', 'grot-ui-runtime')]['metadata']['labels'] = {}
            cluster.calls.clear(); grot.stop(self.args)
        deleted = [command[command.index('--raw')+1] for command, _ in cluster.calls if '--raw' in command]
        self.assertEqual(7, len(deleted))  # Four owned Secrets, ledger, activity Deployment + ConfigMap.
        self.assertIn('/apis/apps/v1/namespaces/grot-team-a/deployments/grot-demo-activity', deleted)
        self.assertIn('/api/v1/namespaces/grot-team-a/configmaps/grot-demo-activity', deleted)
        self.assertFalse(any('grot-ui-runtime' in path for path in deleted))
        for command, kwargs in cluster.calls:
            if '--raw' in command: self.assertIn('resourceVersion', json.loads(kwargs['data'])['preconditions'])

    def test_cleanup_after_partial_secret_creation(self):
        cluster = FakeCluster()
        def fail(command, **kwargs):
            if 'create' in command and 'data' in kwargs:
                obj = json.loads(kwargs['data'])
                if obj['kind'] == 'Secret' and obj['metadata']['name'] == 'grot-ui-runtime':
                    raise grot.SafeError('simulated interrupted install')
            return cluster(command, **kwargs)
        with patch.object(grot, 'run', side_effect=fail), patch.object(grot, 'settings', return_value=self.roles), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(grot.SafeError):
            grot.k8s(self.args)
        cluster.calls.clear()
        with patch.object(grot, 'run', side_effect=cluster), contextlib.redirect_stdout(io.StringIO()): grot.stop(self.args)
        deleted = [cmd for cmd, _ in cluster.calls if '--raw' in cmd]
        self.assertEqual(2, len(deleted))  # The one created Secret and the ledger.

    def test_controller_adoption_cancels_launcher_ownership(self):
        owner = 'a' * 32
        obj = {'metadata': {'labels': {grot.OWNER: owner, 'app.kubernetes.io/managed-by': grot.MANAGER}}}
        self.assertTrue(grot.owned(obj, owner))
        obj['metadata']['managedFields'] = [{'manager': 'external-secrets'}]
        self.assertFalse(grot.owned(obj, owner))
        obj['metadata']['managedFields'] = []
        obj['metadata']['ownerReferences'] = [{'kind': 'ExternalSecret'}]
        self.assertFalse(grot.owned(obj, owner))

    def test_failed_docker_start_clears_runtime_and_binds_buffer(self):
        args = argparse.Namespace(destination='team-a', port=8080, collector_port=12345, syslog_port=15140)
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if 'version' in command: return '2.40.0'
            if command[:2] == ['docker', 'info']: return 'target-engine-id'
            if 'up' in command: raise grot.SafeError('simulated failed start')
            return ''
        with patch.object(grot, 'settings', return_value=self.roles), patch.object(grot, 'stage_runtime'), patch.object(grot, 'remove_runtime_volumes') as cleanup, patch.object(grot, 'run', side_effect=run), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(grot.SafeError):
            grot.docker(args)
        self.assertTrue(any('down' in cmd for cmd in calls)); cleanup.assert_called_once_with('team-a')
        state = json.loads((grot.profile_path('team-a') / 'run.json').read_text())
        self.assertEqual(grot.fingerprint(self.roles), state['fingerprint'])
        self.assertNotIn('synthetic-private-token', json.dumps(state))

    def test_long_term_cleanup_never_deletes_secrets(self):
        cluster = FakeCluster(); owner = 'a' * 32
        cluster.releases = [{'name': 'grot'}, {'name': 'grot-telemetry'}]
        cluster.objects[('configmap', grot.LEDGER)] = {'metadata': {'name': grot.LEDGER, 'uid': 'x', 'resourceVersion': '1',
            'labels': {grot.OWNER: owner, 'app.kubernetes.io/managed-by': grot.MANAGER}},
            'data': {'owner': owner, 'mode': 'long-term', 'destination': 'team-a'}}
        with patch.object(grot, 'run', side_effect=cluster), contextlib.redirect_stdout(io.StringIO()): grot.stop(self.args)
        self.assertFalse(any('/secrets/' in str(cmd) for cmd, _ in cluster.calls))
        uninstall = next(cmd for cmd, _ in cluster.calls if 'uninstall' in cmd)
        self.assertEqual('foreground', uninstall[uninstall.index('--cascade') + 1])
        self.assertIn('--wait', uninstall)

    def test_docker_refuses_disk_backed_runtime_before_writing(self):
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            return '[{"Driver":"local","Options":null}]' if 'inspect' in command else ''
        with patch.object(grot, 'run', side_effect=run), self.assertRaises(grot.SafeError):
            grot.stage_runtime(['docker', 'compose'], {}, 'team-a', self.roles)
        self.assertFalse(any('data' in kwargs for _, kwargs in calls))

    def test_runtime_values_are_quoted_stdin_not_arguments(self):
        marker = self.root / 'must-not-exist'
        token = f"test'$(touch${{IFS}}{marker})$variable;#literal"
        self.roles['alloy']['GRAFANA_OTLP_TOKEN'] = token
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if 'inspect' in command: return json.dumps([{'Driver': 'local', 'Options': {'type': 'tmpfs'}, 'Labels': {'com.docker.compose.project': 'grot-team-a'}}])
            return ''
        with patch.object(grot, 'run', side_effect=run): grot.stage_runtime(['docker', 'compose'], {}, 'team-a', self.roles)
        data = next(kwargs['data'] for _, kwargs in calls if 'GRAFANA_OTLP_TOKEN=' in kwargs.get('data', ''))
        result = subprocess.run(['sh'], input=data + '\nprintf "%s" "$GRAFANA_OTLP_TOKEN"', capture_output=True, text=True, check=True)
        self.assertEqual(token, result.stdout); self.assertFalse(marker.exists())
        self.assertNotIn(token, str([command for command, _ in calls]))

    def test_missing_export_acknowledgements_fail(self):
        zeros = dict.fromkeys(grot.SIGNALS, 0)
        with patch.object(grot, 'counters', return_value=zeros), patch.object(grot.time, 'sleep'), self.assertRaises(grot.SafeError):
            grot.verify_transport('http://localhost/metrics', zeros, timeout=0.001)


class CollectorContractTests(unittest.TestCase):
    def test_generated_configs_are_current(self):
        for path, text in outputs().items(): self.assertEqual(text, path.read_text(), str(path))

    def test_chart_is_namespace_scoped_and_references_secrets(self):
        result = subprocess.run(['helm', 'template', 'grot-telemetry', 'deploy/telemetry-chart', '--namespace', 'grot-team'], cwd=grot.ROOT, capture_output=True, text=True, check=True)
        objects = list(yaml.safe_load_all(result.stdout))
        self.assertFalse(any(obj['kind'] in ('Secret', 'ClusterRole', 'ClusterRoleBinding') for obj in objects))
        role = next(obj for obj in objects if obj['kind'] == 'Role')
        self.assertEqual(['pods', 'pods/log'], role['rules'][0]['resources'])
        for pod in [obj for obj in objects if obj['kind'] == 'Deployment']:
            for container in pod['spec']['template']['spec']['containers']:
                self.assertIn('secretRef', container['envFrom'][0])
                self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])

    def test_only_cadvisor_mounts_docker_socket_not_apps_or_alloy(self):
        text = (grot.ROOT / 'deploy/docker/compose.telemetry.yaml').read_text()
        services = yaml.safe_load(text.replace('!reset', ''))['services']
        holders = [name for name, spec in services.items() if any('docker.sock' in mount for mount in spec.get('volumes', []))]
        self.assertEqual(['cadvisor'], holders)
        self.assertIn('driver: syslog', text)

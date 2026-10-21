import argparse
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from scripts import grot, grot_activity as activity


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.owner = 'a' * 32
        self.args = argparse.Namespace(destination='demo', context='test', namespace='grot-demo', no_demo_traffic=False)
        self.objects = {('configmap', grot.LEDGER): self.obj(grot.LEDGER)}
        self.objects[('configmap', grot.LEDGER)]['data'] = {'destination': 'demo', 'owner': self.owner}
        self.calls = []
        self.container = None
        self.api = argparse.Namespace(ROOT=grot.ROOT, MANAGER=grot.MANAGER, OWNER=grot.OWNER,
            LEDGER=grot.LEDGER, SafeError=grot.SafeError, owned=grot.owned,
            get_object=lambda kube, kind, name: self.objects.get((kind.rstrip('s'), name)),
            profile_path=lambda destination: self.path, run=self.run_command)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__(); self.addCleanup(quiet.__exit__, None, None, None)
        sleeper = patch.object(activity.time, 'sleep')
        sleeper.start(); self.addCleanup(sleeper.stop)

    def obj(self, name):
        return {'metadata': {'name': name, 'uid': 'test-uid', 'resourceVersion': '1',
            'labels': {grot.OWNER: self.owner, 'app.kubernetes.io/managed-by': grot.MANAGER},
            'managedFields': [{'manager': grot.MANAGER}]}}

    def run_command(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[0] == 'kubectl' and ('create' in command or 'replace' in command):
            obj = json.loads(kwargs['data'])
            obj['metadata'].update(uid='test-uid', resourceVersion='2', managedFields=[{'manager': grot.MANAGER}])
            self.objects[(obj['kind'].lower(), obj['metadata']['name'])] = obj
        if command[:3] == ['docker', 'container', 'ls']:
            return 'test-container' if self.container else ''
        if command[:3] == ['docker', 'container', 'inspect']:
            return json.dumps([self.container])
        if command[:3] == ['docker', 'run', '-d']:
            self.container = {'Config': {'Labels': {activity.LABEL: 'demo', 'app.kubernetes.io/managed-by': grot.MANAGER}},
                              'State': {'Status': 'running'}}
        if command[:2] == ['docker', 'rm']: self.container = None
        return ''

    def test_default_environment_cannot_start_paid_calls_or_cloud_runs(self):
        env = activity.environment('http://grot-gateway', False)
        self.assertEqual(('6', '1'), (env['JOURNEYS_PER_MINUTE'], env['BROWSER_JOURNEYS_PER_MINUTE']))
        self.assertEqual('false', env['ALLOW_PAID_AI'])
        self.assertEqual('0', env['GROT_CHAT_INTERVAL_SECONDS'])
        self.assertEqual('false', env['GROT_FAILURES'])
        self.assertEqual('true', env['K6_NO_USAGE_REPORT'])
        self.assertFalse(any('CLOUD' in key or 'TOKEN' in key for key in env))

    def test_kubernetes_runs_one_owned_restarting_local_runner(self):
        activity.configure(self.args, self.api)
        obj = self.objects[('deployment', activity.NAME)]
        spec = obj['spec']['template']['spec']
        self.assertEqual(1, obj['spec']['replicas'])
        self.assertEqual('Recreate', obj['spec']['strategy']['type'])
        self.assertEqual('Always', spec['restartPolicy'])
        self.assertFalse(spec['automountServiceAccountToken'])
        self.assertFalse(any('secret' in volume for volume in spec['volumes']))
        container = spec['containers'][0]
        self.assertEqual(['run', '--no-usage-report', '/work/tests/k6/traffic.js'], container['args'])
        self.assertNotIn('envFrom', container)
        self.assertEqual('http://grot-gateway', next(e['value'] for e in container['env'] if e['name'] == 'BASE_URL'))
        self.assertTrue(all(command[0] == 'kubectl' for command, _ in self.calls))
        self.assertEqual(set(activity.FILES), set(self.objects[('configmap', activity.NAME)]['data']))

    def test_redeploy_replaces_owned_objects_without_duplicate_runners(self):
        activity.configure(self.args, self.api)
        self.objects[('deployment', activity.NAME)]['metadata']['managedFields'].append({'manager': 'kube-controller-manager'})
        self.calls.clear()
        activity.configure(self.args, self.api)
        replacements = [json.loads(kw['data']) for cmd, kw in self.calls if 'replace' in cmd]
        self.assertEqual(['ConfigMap', 'Deployment'], [obj['kind'] for obj in replacements])
        self.assertTrue(all(obj['metadata']['resourceVersion'] == '2' for obj in replacements))
        self.assertFalse(any('create' in cmd for cmd, _ in self.calls))

    def test_refuses_foreign_resource_before_any_writes(self):
        self.objects[('deployment', activity.NAME)] = self.obj(activity.NAME)
        self.objects[('deployment', activity.NAME)]['metadata']['labels'][grot.OWNER] = 'b' * 32
        with self.assertRaises(grot.SafeError): activity.configure(self.args, self.api)
        with self.assertRaises(grot.SafeError): activity.stop(self.args, self.api)
        self.assertEqual([], self.calls)

    def test_refuses_externally_edited_deployment(self):
        obj = self.obj(activity.NAME)
        obj['metadata']['managedFields'].append({'manager': 'kubectl-edit'})
        self.assertFalse(activity.owned(obj, self.owner, self.api))

    def test_cleanup_uses_correct_api_groups_and_compare_and_delete(self):
        activity.configure(self.args, self.api)
        self.calls.clear()
        activity.stop(self.args, self.api)
        deletes = [(cmd[cmd.index('--raw') + 1], json.loads(kw['data'])) for cmd, kw in self.calls if '--raw' in cmd]
        self.assertEqual(['/apis/apps/v1/namespaces/grot-demo/deployments/' + activity.NAME,
                          '/api/v1/namespaces/grot-demo/configmaps/' + activity.NAME], [path for path, _ in deletes])
        for _, body in deletes:
            self.assertEqual({'uid': 'test-uid', 'resourceVersion': '2'}, body['preconditions'])
            self.assertEqual('Foreground', body['propagationPolicy'])
        self.assertFalse(any('grot-demo-traffic' in ' '.join(cmd) for cmd, _ in self.calls))

    def test_opt_out_removes_existing_activity_without_creating_anything(self):
        activity.configure(self.args, self.api)
        self.calls.clear()
        self.args.no_demo_traffic = True
        activity.configure(self.args, self.api)
        self.assertTrue(any('--raw' in cmd for cmd, _ in self.calls))
        self.assertFalse(any('create' in cmd or 'replace' in cmd for cmd, _ in self.calls))

    def test_docker_lifecycle_has_no_cloud_credentials_and_auto_restarts(self):
        self.args.context = None
        (self.path / 'run.json').write_text(json.dumps({'faro': True}))
        activity.configure(self.args, self.api)
        cmd = next(cmd for cmd, _ in self.calls if cmd[:3] == ['docker', 'run', '-d'])
        self.assertEqual('unless-stopped', cmd[cmd.index('--restart') + 1])
        self.assertEqual('grot-demo_default', cmd[cmd.index('--network') + 1])
        self.assertIn('EXPECT_FARO=true', cmd)
        self.assertNotIn('cloud', cmd)
        self.assertNotIn('--privileged', cmd)
        activity.stop(self.args, self.api)
        self.assertIsNone(self.container)

    def test_docker_does_not_touch_unrelated_container(self):
        self.args.context = None
        self.container = {'Config': {'Labels': {activity.LABEL: 'someone-else'}}}
        with self.assertRaises(grot.SafeError): activity.stop(self.args, self.api)
        self.assertFalse(any(cmd[:2] in (['docker', 'stop'], ['docker', 'rm']) for cmd, _ in self.calls))

    def test_docker_requires_matching_launcher_state(self):
        self.args.context = None
        with self.assertRaises(grot.SafeError): activity.configure(self.args, self.api)
        self.assertEqual([], self.calls)


if __name__ == '__main__':
    unittest.main()

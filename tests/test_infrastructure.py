import argparse
import base64
import contextlib
import io
import json
import unittest
from unittest.mock import patch
import yaml
from scripts import grot, grot_infrastructure as infra
from tests.test_destination_workflow import fixture, FakeCluster


class InfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(destination='team-a', context='test', namespace='grot-team-a')
        self.collector = fixture()['alloy']
        self.cluster = FakeCluster()
        self.cluster.objects[('deployment', infra.COLLECTOR)] = {
            'metadata': {'name': infra.COLLECTOR, 'generation': 2},
            'spec': {'replicas': 1, 'template': {'metadata': {'annotations': {'grot-runtime-revision': '123'}}}},
            'status': {'observedGeneration': 2, 'replicas': 1, 'updatedReplicas': 1, 'availableReplicas': 1}}

    def install(self):
        with patch.object(infra.time, 'time_ns', return_value=123), patch.object(infra, 'verify_delivery'), patch.object(grot, 'run', side_effect=self.cluster), contextlib.redirect_stdout(io.StringIO()):
            infra.install(self.args, self.collector, grot)

    def test_install_secret_only_has_metrics_and_logs_and_no_helm_credentials(self):
        self.install()
        secret = self.cluster.objects[('secret', infra.SECRET)]
        self.assertEqual(set(infra.KEYS), set(secret['data']))
        for key in infra.KEYS:
            self.assertEqual(self.collector[key], base64.b64decode(secret['data'][key]).decode())
        helm_text = json.dumps([c for c, kw in self.cluster.calls if c[0] == 'helm'])
        self.assertNotIn('synthetic-private-token', helm_text)
        self.assertNotIn('https://private', helm_text)
        self.assertIn(infra.CHART_VERSION, helm_text)
        listing = next(c for c, _ in self.cluster.calls if c[0]=='helm' and 'list' in c)
        self.assertGreater(listing.index('--all-namespaces'), listing.index('list'))

    def test_operator_readiness_requires_current_revision_and_completed_rollout(self):
        obj = self.cluster.objects[('deployment', infra.COLLECTOR)]
        self.assertTrue(infra.collector_ready(obj, '123'))
        self.assertFalse(infra.collector_ready(obj, 'old'))
        self.assertFalse(infra.collector_ready(None, '123'))
        for key in ('observedGeneration', 'updatedReplicas', 'availableReplicas', 'replicas'):
            changed = json.loads(json.dumps(obj))
            changed['status'][key] = 0
            self.assertFalse(infra.collector_ready(changed, '123'))
        self.install()
        self.assertFalse(any('rollout' in c for c, _ in self.cluster.calls))
        self.assertTrue(any('collectors.infrastructure.controller.podAnnotations.grot-runtime-revision=123' in c for c, _ in self.cluster.calls))

    def test_delivery_requires_all_sources_and_both_acknowledgements(self):
        lines = ['prometheus_remote_storage_samples_total 4', 'loki_write_sent_entries_total 2'] + [
            'prometheus_target_scrape_pool_targets{component_id="prometheus.scrape.' + source + '"} 1'
            for source in ('cadvisor', 'kube_state_metrics', 'node_exporter')]
        self.assertTrue(infra.collected_and_delivered('\n'.join(lines)))
        for i in range(len(lines)):
            self.assertFalse(infra.collected_and_delivered('\n'.join(lines[:i] + lines[i+1:])))
        self.assertFalse(infra.collected_and_delivered(''))

    def test_cloud_verifier_checks_inventory_containers_hosts_and_events(self):
        self.args.grafana_context = 'test-cloud'
        calls = []
        def execute(command):
            calls.append(command)
            if 'config' in command: return ''
            if 'datasources' in command:
                return json.dumps({'datasources': [{'type': 'prometheus', 'uid': 'grafanacloud-prom'}, {'type': 'loki', 'uid': 'grafanacloud-logs'}]})
            return '{"data":{"result":[{"metric":{},"value":[123,"1"]}]}}'
        with patch.object(grot, 'run', side_effect=execute), contextlib.redirect_stdout(io.StringIO()) as output:
            infra.verify_cloud(self.args, 'team-a', grot)
        self.assertIn('Cloud verification PASSED', output.getvalue())
        self.assertTrue(all(c[:3] == ['gcx', '--context', 'test-cloud'] for c in calls))
        queries = [c for c in calls if 'query' in c]
        self.assertEqual(5, len(queries))
        self.assertTrue(any('container_cpu_usage_seconds_total' in ' '.join(c) and 'container="orders"' in ' '.join(c) for c in queries))

    def test_existing_cluster_monitoring_is_not_duplicated(self):
        self.cluster.releases = [{'name': 'existing', 'namespace': 'observability', 'chart': 'k8s-monitoring-4.5.3'}]
        with self.assertRaisesRegex(grot.SafeError, 'already exists'): self.install()
        self.assertFalse(any('upgrade' in c for c, _ in self.cluster.calls))
        self.assertNotIn(('secret', infra.SECRET), self.cluster.objects)

    def test_foreign_secret_is_not_adopted(self):
        self.cluster.objects[('secret', infra.SECRET)] = {'metadata': {'name': infra.SECRET}}
        with self.assertRaisesRegex(grot.SafeError, 'externally managed'): self.install()

    def test_same_destination_rotation_is_allowed_retarget_is_not(self):
        self.install()
        self.collector['GRAFANA_METRICS_TOKEN'] = 'rotated-token'
        self.install()
        self.collector['GRAFANA_METRICS_USER'] = 'other-tenant'
        with self.assertRaisesRegex(grot.SafeError, 'another cluster label/destination'): self.install()

    def test_unowned_release_is_not_adopted(self):
        self.cluster.releases = [{'name': infra.RELEASE, 'namespace': infra.NAMESPACE, 'chart': 'k8s-monitoring-4.5.3'}]
        with self.assertRaisesRegex(grot.SafeError, 'ownership record'): self.install()

    def test_remove_requires_owned_record_and_original_source_namespace(self):
        with patch.object(grot, 'run', side_effect=self.cluster), self.assertRaises(grot.SafeError):
            infra.remove(self.args, grot)
        self.install()
        self.args.namespace = 'grot-other'
        with patch.object(grot, 'run', side_effect=self.cluster), self.assertRaisesRegex(grot.SafeError, 'original source namespace'):
            infra.remove(self.args, grot)

    def test_docker_verification_rejects_http_only_or_other_project_metrics(self):
        args = argparse.Namespace(destination='team-a')
        host = 'node_cpu_seconds_total{cpu="0"} 1\nnode_memory_MemTotal_bytes 100\n'
        prefix = 'container_memory_working_set_bytes{container_label_com_docker_compose_project="grot-'
        for project, accepted in [('team-a', True), ('other', False)]:
            metrics = prefix + project + '",container_label_com_docker_compose_service="orders"} 123\n'
            with patch.object(grot, 'compose', return_value=(['docker','compose'], {})), patch.object(grot, 'profile_path'), patch.object(grot, 'run', side_effect=[metrics, host]), contextlib.redirect_stdout(io.StringIO()):
                if accepted: grot.verify_docker_infrastructure(args, {})
                else:
                    with self.assertRaises(grot.SafeError): grot.verify_docker_infrastructure(args, {})

    def test_chart_features_do_not_duplicate_application_collection(self):
        values = yaml.safe_load((grot.ROOT / 'deploy/kubernetes-monitoring/values.yaml').read_text())
        self.assertTrue(values['clusterMetrics']['enabled'])
        self.assertTrue(values['clusterMetrics']['cadvisor']['enabled'])
        self.assertTrue(values['hostMetrics']['linuxHosts']['enabled'])
        self.assertTrue(values['clusterEvents']['enabled'])
        for key in ('podLogs', 'applicationObservability', 'annotationAutodiscovery', 'profiling'):
            self.assertFalse(values.get(key, {}).get('enabled', False))
        self.assertTrue(values['alloy-operator']['ownNamespaceOnly'])
        self.assertNotEqual(infra.RELEASE, values['collectors']['infrastructure']['fullnameOverride'])
        self.assertEqual(infra.COLLECTOR, values['collectors']['infrastructure']['fullnameOverride'])
        self.assertEqual({'metrics','logs'}, set(values['destinations']))
        for destination in values['destinations'].values():
            self.assertNotIn('url', destination)
            self.assertIn('sys.env', destination['urlFrom'])

    def test_docker_exporters_private_and_only_compose_labels_collected(self):
        values = yaml.safe_load((grot.ROOT / 'deploy/docker/compose.telemetry.yaml').read_text().replace('!reset', ''))
        for service in ('cadvisor', 'node-exporter'):
            self.assertNotIn('ports', values['services'][service])
            self.assertNotIn('env_file', values['services'][service])
        self.assertIn('--store_container_labels=false', values['services']['cadvisor']['command'])
        config = (grot.ROOT / 'observability/components/docker-infrastructure.alloy').read_text()
        self.assertIn('GROT_DOCKER_PROJECT', config)
        self.assertIn('action = "keep"', config)


if __name__ == '__main__': unittest.main()

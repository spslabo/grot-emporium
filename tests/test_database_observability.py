import argparse
import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch
import yaml
from scripts import grot
from scripts.grot_config import validate
from tests.test_destination_workflow import fixture, FakeCluster
from tests.telemetry.snappy_block import decode


class DatabaseTests(unittest.TestCase):
    def test_generated_passwords_are_distinct_valid_and_not_fingerprint_inputs(self):
        a, b = fixture(), fixture()
        validate('database', a['database'])
        self.assertEqual(3, len(set(a['database'].values())))
        self.assertNotEqual(a['database'], b['database'])
        self.assertEqual(grot.fingerprint(a), grot.fingerprint(b))

    def test_reject_unsafe_missing_short_and_reused_database_passwords(self):
        good = fixture()['database']
        for value in ['', 'short', 'a' * 31, 'a' * 129, 'a' * 32 + ':', 'a' * 32 + '/', 'a' * 32 + '\n']:
            for partial in (True, False):
                with self.subTest(value_length=len(value), partial=partial), self.assertRaises(ValueError):
                    validate('database', dict(good, GROT_DB_MONITOR_PASSWORD=value), partial=partial)
        with self.assertRaises(ValueError): validate('database', {})
        with self.assertRaises(ValueError): validate('database', dict(good, GROT_DB_APP_PASSWORD=good['POSTGRES_PASSWORD']))

    def test_kubernetes_upgrade_preserves_existing_database_credentials(self):
        cluster = FakeCluster()
        args = argparse.Namespace(destination='team-a', context='test', namespace='grot-team-a',
            image_prefix='registry.example.invalid/team', image_tag='sha', mode='quick', settings_stdin=False, pull_secret=None)
        with patch.object(grot, 'setup_infrastructure'), patch.object(grot, 'verify_k8s'), patch.object(grot, 'run', side_effect=cluster), patch.object(grot, 'settings', side_effect=[fixture(), fixture()]), contextlib.redirect_stdout(io.StringIO()):
            grot.k8s(args)
            first = cluster.objects[('secret', 'grot-database-runtime')]['data'].copy()
            grot.k8s(args)
        self.assertEqual(first, cluster.objects[('secret', 'grot-database-runtime')]['data'])

    def render(self):
        # Tests must work from a clean checkout, without another test having
        # populated the chart dependencies first.
        subprocess.run(['helm', 'dependency', 'build', 'src/app/chart'],
            cwd=grot.ROOT, check=True, capture_output=True, text=True)
        text = subprocess.check_output(['helm', 'template', 'grot', 'src/app/chart', '-f',
            'src/app/chart/values-grot.yaml'], cwd=grot.ROOT, text=True)
        return [o for o in yaml.safe_load_all(text) if o]

    def test_helm_default_database_is_private_ephemeral_and_credential_scoped(self):
        objects = self.render()
        db = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'grot-postgres')
        spec = db['spec']['template']['spec']
        self.assertFalse(spec['automountServiceAccountToken'])
        self.assertEqual('Recreate', db['spec']['strategy']['type'])
        self.assertTrue(any('emptyDir' in v and v['name'] == 'data' for v in spec['volumes']))
        self.assertFalse(any(o['kind'] == 'PersistentVolumeClaim' for o in objects))
        svc = next(o for o in objects if o['kind'] == 'Service' and o['metadata']['name'] == 'postgres')
        self.assertEqual('ClusterIP', svc['spec'].get('type', 'ClusterIP'))
        policy = next(o for o in objects if o['kind'] == 'NetworkPolicy' and o['metadata']['name'] == 'grot-postgres')
        self.assertEqual([{'protocol': 'TCP', 'port': 5432}], policy['spec']['ingress'][0]['ports'])
        app = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'orders')
        container = app['spec']['template']['spec']['containers'][0]
        env = {e['name']: e for e in container['env']}
        self.assertEqual('postgres', env['RETAIL_ORDERS_PERSISTENCE_PROVIDER']['value'])
        self.assertEqual('GROT_DB_APP_PASSWORD', env['RETAIL_ORDERS_PERSISTENCE_PASSWORD']['valueFrom']['secretKeyRef']['key'])
        self.assertNotIn({'secretRef': {'name': 'grot-database-runtime'}}, container['envFrom'])

    def test_collector_only_receives_monitoring_password(self):
        text = subprocess.check_output(['helm', 'template', 'grot-telemetry', 'deploy/telemetry-chart'], cwd=grot.ROOT, text=True)
        db_keys = [e['valueFrom']['secretKeyRef']['key']
            for obj in yaml.safe_load_all(text) if obj and obj['kind'] == 'Deployment'
            for c in obj['spec']['template']['spec']['containers'] for e in c.get('env', [])
            if e.get('valueFrom', {}).get('secretKeyRef', {}).get('name') == 'grot-database-runtime']
        self.assertEqual(['GROT_DB_MONITOR_PASSWORD'], db_keys)

    def test_collection_verifier_requires_query_data_not_just_up(self):
        def response(text):
            obj = io.BytesIO(text.encode()); return obj
        metrics = 'pg_up 1\npg_stat_statements_calls_total{queryid="1"} 3\npg_exporter_last_scrape_error 0\n'
        with patch.object(grot, 'urlopen', side_effect=[response(metrics), response('database_observability_connection_info 1\n')]), contextlib.redirect_stdout(io.StringIO()):
            grot.verify_database('http://example.invalid/metrics', timeout=1)
        with patch.object(grot.time, 'monotonic', side_effect=[0, 0, 2]), patch.object(grot.time, 'sleep'), patch.object(grot, 'urlopen', side_effect=[response('pg_up 1\n'), response('database_observability_connection_info 1\n')]), self.assertRaises(grot.SafeError):
            grot.verify_database('http://example.invalid/metrics', timeout=1)

    def test_raw_snappy_decoder_handles_literals_and_overlapping_copies(self):
        self.assertEqual(b'hello', decode(b'\x05\x10hello'))
        self.assertEqual(b'aaaaa', decode(b'\x05\x00a\x01\x01'))
        self.assertEqual(b'ababab', decode(b'\x06\x04ab\x0e\x02\x00'))
        for invalid in [b'\x05\x10hel', b'\x01\x01\x00', b'\x7f', b'\x01\x10hello']:
            with self.assertRaises((ValueError, IndexError)): decode(invalid)

    def test_config_enables_query_redaction_and_disables_statement_logging(self):
        alloy = (grot.ROOT / 'observability/components/database.alloy').read_text()
        self.assertIn('disable_query_redaction = false', alloy)
        self.assertIn('database_observability.postgres', alloy)
        sql = (grot.ROOT / 'deploy/postgres/init.sql').read_text()
        self.assertIn('ALTER DEFAULT PRIVILEGES FOR ROLE grot_orders', sql)
        config = (grot.ROOT / 'deploy/postgres/postgresql.conf').read_text()
        self.assertIn("log_statement = 'none'", config)
        self.assertIn("shared_preload_libraries = 'pg_stat_statements'", config)


if __name__ == '__main__': unittest.main()

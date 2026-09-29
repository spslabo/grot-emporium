import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class CatalogTests(unittest.TestCase):
    def test_seed_catalogs_and_images_are_in_sync(self):
        subprocess.run(['python3', 'scripts/sync-grot-catalog.py', '--check'], cwd=ROOT, check=True)
        products = json.loads((ROOT / 'src/catalog/grots.json').read_text())
        self.assertEqual(9, len(products))
        self.assertTrue(all('Grot' in p['name'] for p in products))
        self.assertEqual({'original','oncall','cloud','firefighter','space','zen','disco','golden','sparkly'}, {p['slug'] for p in products})

class HelmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(['helm', 'dependency', 'build', 'src/app/chart'], cwd=ROOT, check=True, capture_output=True)

    def render(self, *extra):
        result = subprocess.run(['helm','template','grot-emporium','src/app/chart','--namespace','grot-emporium','-f','src/app/chart/values-grot.yaml', *extra], cwd=ROOT, check=True, capture_output=True, text=True)
        return [obj for obj in yaml.safe_load_all(result.stdout) if obj]

    def test_all_service_identities_and_pod_uid_attributes(self):
        deployments = [d for d in self.render() if d['kind']=='Deployment']
        self.assertEqual(5, len(deployments))
        seen = set()
        for d in deployments:
            pod = d['spec']['template']
            self.assertEqual('grot-emporium', pod['metadata']['labels']['app.kubernetes.io/part-of'])
            env = pod['spec']['containers'][0]['env']
            self.assertEqual(len(env), len({v['name'] for v in env}))
            env = {v['name']:v for v in env}
            name = env['OTEL_SERVICE_NAME']['value']; seen.add(name)
            self.assertEqual(name, pod['metadata']['labels']['service_name'])
            self.assertEqual('metadata.uid', env['POD_UID']['valueFrom']['fieldRef']['fieldPath'])
            self.assertIn('k8s.pod.uid=$(POD_UID)', env['OTEL_RESOURCE_ATTRIBUTES']['value'])
        self.assertEqual({'grot-ui','grot-cart','grot-orders','grot-catalog','grot-checkout'}, seen)

    def test_profiles_are_opt_in_and_cover_all_services(self):
        for enabled in (False, True):
            extra = ['-f','src/app/chart/values-grot-profiles.yaml'] if enabled else []
            for d in self.render(*extra):
                if d['kind']!='Deployment': continue
                env = {v['name']:v for v in d['spec']['template']['spec']['containers'][0]['env']}
                name = env['OTEL_SERVICE_NAME']['value']
                if name in ('grot-ui','grot-cart','grot-orders'):
                    self.assertEqual(enabled, 'PYROSCOPE_APPLICATION_NAME' in env)
                    if enabled: self.assertEqual(name, env['PYROSCOPE_APPLICATION_NAME']['value'])
                else: self.assertEqual(enabled, 'PYROSCOPE_ENABLED' in env)

    def test_runtime_secret_precedence_and_ui_isolation(self):
        rendered = self.render('--set', 'global.grotBackendSecret=backend-private', '--set', 'ui.runtimeSecret=ui-private', '--namespace', 'other-team')
        for obj in rendered:
            if obj['kind'] != 'Deployment': continue
            container = obj['spec']['template']['spec']['containers'][0]
            refs = [entry['secretRef']['name'] for entry in container['envFrom'] if 'secretRef' in entry]
            self.assertIn('backend-private', refs)
            is_ui = any(e.get('value') == 'grot-ui' for e in container['env'])
            self.assertEqual(is_ui, 'ui-private' in refs)
            if is_ui: self.assertEqual('ui-private', container['envFrom'][-1]['secretRef']['name'])
        config = next(o for o in rendered if o['kind'] == 'ConfigMap' and o['metadata']['name'] == 'grot-emporium-telemetry')
        self.assertEqual('true', config['data']['OTEL_SDK_DISABLED'])
        self.assertIn('k8s.namespace.name=other-team', config['data']['GROT_RESOURCE_ATTRIBUTES'])

    def test_inline_telemetry_endpoint_is_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.render('--set', 'grotTelemetry.endpoint=https://private.example.invalid/otlp')

    def test_plaintext_model_key_is_rejected(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.render('--set','ui.app.chat.enabled=true','--set','ui.app.chat.provider=openai','--set','ui.app.chat.openai.apiKey=do-not-store-keys-here')

if __name__ == '__main__': unittest.main()

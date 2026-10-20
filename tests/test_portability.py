import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.grot_config import ROOT, initialize, load, private_path, validate


class PrivateConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        initialize(self.path)

    def test_defaults_are_disabled_and_owner_only(self):
        for kind in ('backend', 'ui'):
            path = self.path / f'{kind}.env'
            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            validate(kind, load(path))
        self.assertEqual('true', load(self.path / 'backend.env')['OTEL_SDK_DISABLED'])
        self.assertEqual('false', load(self.path / 'ui.env')['RETAIL_UI_CHAT_ENABLED'])

    def test_no_overwrite_or_in_repository_config(self):
        before = (self.path / 'ui.env').read_bytes()
        with self.assertRaises(ValueError): initialize(self.path)
        self.assertEqual(before, (self.path / 'ui.env').read_bytes())
        with self.assertRaises(ValueError): private_path(ROOT / '.private/runtime.env', False)

    def test_loose_permissions_and_symlinks_rejected(self):
        path = self.path / 'backend.env'
        path.chmod(0o644)
        with self.assertRaises(ValueError): load(path)
        path.chmod(0o600)
        link = self.path / 'linked.env'
        link.symlink_to(path)
        with self.assertRaises(ValueError): load(link)

    def test_role_separation_and_literal_values(self):
        path = self.path / 'backend.env'
        with path.open('a') as file: file.write('OTEL_TRACES_SAMPLER=parentbased_always_on\n')
        values = load(path)
        values['OTEL_EXPORTER_OTLP_HEADERS'] = 'Authorization=Bearer dummy$literal#value'
        validate('backend', values)
        values['RETAIL_UI_CHAT_OPENAI_API_KEY'] = 'not-a-real-key'
        with self.assertRaises(ValueError): validate('backend', values)

    def test_enabled_tracing_requires_safe_destination(self):
        base = dict(load(self.path / 'backend.env'), OTEL_SDK_DISABLED='false')
        for url in ('', 'http://cloud.example.invalid', 'https://user:password@example.invalid', 'https://example.invalid?token=dummy'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate('backend', dict(base, OTEL_EXPORTER_OTLP_ENDPOINT=url))
        for url in ('https://collector.example.invalid/otlp', 'http://alloy:4318'):
            validate('backend', dict(base, OTEL_EXPORTER_OTLP_ENDPOINT=url))

    def test_faro_public_disclosure_is_explicit(self):
        base = dict(load(self.path / 'ui.env'), FARO_ENABLED='true')
        validate('ui', dict(base, FARO_COLLECTOR_URL='/telemetry'))
        external = dict(base, FARO_COLLECTOR_URL='https://collector.example.invalid/collect/test-key')
        with self.assertRaises(ValueError): validate('ui', external)
        validate('ui', dict(external, FARO_PUBLIC_URL_ACKNOWLEDGED='true'))
        with self.assertRaises(ValueError): validate('ui', dict(base, FARO_COLLECTOR_URL='//other.invalid/collect'))

    def test_cli_never_echoes_bad_values(self):
        secret = 'private-value-that-must-not-be-printed'
        (self.path / 'ui.env').write_text('FARO_ENABLED=' + secret)
        result = subprocess.run(['python3', str(ROOT / 'scripts/grot_config.py'), 'validate', '--kind', 'ui', '--file', str(self.path / 'ui.env')], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn(secret, result.stdout + result.stderr)

    def test_compose_preserves_literal_values_and_ui_isolation(self):
        import json
        sentinel = 'not-real$literal#credential'
        with (self.path / 'ui.env').open('a') as file:
            file.write('RETAIL_UI_CHAT_OPENAI_API_KEY=' + sentinel + '\n')
        environment = dict(os.environ, GROT_BACKEND_ENV_FILE=str(self.path / 'backend.env'),
            GROT_UI_ENV_FILE=str(self.path / 'ui.env'), GROT_IMAGE_PREFIX='grot', GROT_IMAGE_TAG='test')
        # Synthetic values only; never print the resolved configuration.
        result = subprocess.run(['docker', 'compose', '-f', 'deploy/docker/compose.yaml', 'config', '--format', 'json'],
            cwd=ROOT, env=environment, check=True, capture_output=True, text=True)
        services = json.loads(result.stdout)['services']
        # Compose escapes dollars in its re-loadable config output; this is not
        # interpolation or the value delivered to the container.
        rendered = services['ui']['environment']['RETAIL_UI_CHAT_OPENAI_API_KEY']
        self.assertEqual(sentinel, rendered.replace('$$', '$'))
        for name in ('catalog', 'checkout', 'cart', 'orders'):
            self.assertNotIn('RETAIL_UI_CHAT_OPENAI_API_KEY', services[name]['environment'])

    def test_alloy_requires_all_export_destinations(self):
        with self.assertRaises(ValueError): validate('alloy', load(self.path / 'alloy.env'))


class SharedConfigurationTests(unittest.TestCase):
    def test_public_docs_and_setup_have_no_live_connection_literals(self):
        import re
        paths = [ROOT / 'README.md', ROOT / 'scripts/grot_agent.py']
        paths += list((ROOT / 'docs').glob('*.md')) + list((ROOT / 'evals').glob('*.yaml'))
        patterns = [
            r'arn:aws[^\s\"\']*:\d{12}:',
            r'/Users/[^/\s\"\']+/',
            r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
            r'\b(?:glc_|glsa_|ghp_)[A-Za-z0-9_+/=-]{30,}',
            r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        ]
        for path in paths:
            text = path.read_text()
            for pattern in patterns:
                self.assertFalse(re.search(pattern, text), str(path.relative_to(ROOT)))
            hosts = re.findall(r'https?://([A-Za-z0-9.-]+\.grafana\.net)', text)
            self.assertTrue(all(h in ('test.grafana.net', 'example.grafana.net') for h in hosts), str(path.relative_to(ROOT)))

    def test_no_real_cloud_stack_destinations_in_shared_configuration(self):
        import re
        for folder in ('deploy', 'observability', 'automation', 'src/app/chart'):
            for path in (ROOT / folder).rglob('*'):
                if not path.is_file() or path.suffix not in ('.yaml', '.yml', '.alloy', '.py', '.md'): continue
                text = path.read_text()
                self.assertFalse(re.search(r'https?://[^\s\"\']*\.(?:grafana\.net|grafana\.com)(?:[:/]|$)', text), str(path))

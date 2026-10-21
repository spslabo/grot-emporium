import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from scripts.grot_config import ROOT


class PublicationInstructionsTests(unittest.TestCase):
    def test_release_uses_ghcr_without_upstream_aws_or_bot_pr_permissions(self):
        directory = ROOT / '.github/workflows'
        workflows = {p.name: yaml.load(p.read_text(), Loader=yaml.BaseLoader)
                     for p in directory.iterdir() if p.suffix in ('.yaml', '.yml')}
        for name, workflow in workflows.items():
            text = (directory / name).read_text()
            self.assertNotIn('googleapis/release-please-action', text)
            self.assertNotIn('secrets.AWS_ROLE_ARN', text)
            self.assertNotIn('secrets.AWS_ECR_REPOSITORY', text)
            for job in workflow['jobs'].values():
                reference = job.get('uses', '')
                if reference.startswith('./'):
                    self.assertTrue((ROOT / reference).is_file(), reference)
        publication = workflows['grot-publish.yml']
        self.assertEqual({'workflow_dispatch', 'push'}, set(publication['on']))
        self.assertEqual({'tags': ['grot-v*']}, publication['on']['push'])
        self.assertEqual({'contents': 'read'}, publication['permissions'])
        self.assertEqual({'contents': 'read', 'packages': 'write'}, publication['jobs']['publish']['permissions'])
        steps = publication['jobs']['publish']['steps']
        build = next(step for step in steps if step.get('uses', '').startswith('docker/build-push-action@'))
        self.assertEqual('linux/amd64,linux/arm64', build['with']['platforms'])
        self.assertEqual('true', build['with']['push'])

    def test_kubernetes_ci_requires_readiness_and_keeps_failure_diagnostics(self):
        steps = yaml.safe_load((ROOT / '.github/workflows/e2e-test.yml').read_text())['jobs']['kubernetes']['steps']
        deploy = next(step['run'] for step in steps if step.get('name') == 'Deploy')
        wait = next(line for line in deploy.splitlines() if 'kubectl wait' in line)
        self.assertNotIn('||', wait)
        self.assertIn('tests/kubernetes/e2e-offline-images.yaml', deploy)
        load = next(step['run'] for step in steps if step.get('name') == 'Load images')
        self.assertLess(load.index('preload-e2e-images.sh'), load.index('docker system prune'))
        diagnostics = next(step for step in steps if step.get('name') == 'Kubernetes failure diagnostics')
        self.assertEqual('failure()', diagnostics['if'])
        self.assertIn('describe pods', diagnostics['run'])
        self.assertIn('--previous', diagnostics['run'])

    def test_summary_uses_actual_repository_and_sha_after_all_images(self):
        jobs = yaml.safe_load((ROOT / '.github/workflows/grot-publish.yml').read_text())['jobs']
        self.assertEqual('publish', jobs['deployment-settings']['needs'])
        self.assertEqual('verify', jobs['publish']['needs'])
        self.assertEqual({'ui', 'cart', 'orders', 'catalog', 'checkout'}, set(jobs['publish']['strategy']['matrix']['service']))
        script = jobs['deployment-settings']['steps'][0]['run']
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / 'summary.md'
            subprocess.run(['bash', '-e', '-c', script], check=True, env={
                'PATH': os.defpath, 'GITHUB_REPOSITORY': 'Example/Grot-Emporium',
                'GITHUB_SHA': '0123456789' * 4, 'GITHUB_STEP_SUMMARY': str(summary)})
            text = summary.read_text()
        self.assertIn('export IMAGE_PREFIX="ghcr.io/example/grot-emporium"', text)
        self.assertIn('export VERSION="' + '0123456789' * 4 + '"', text)
        self.assertIn('Kubernetes deployment settings', text)


if __name__ == '__main__':
    unittest.main()

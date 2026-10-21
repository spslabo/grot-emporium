import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from scripts.grot_config import ROOT


class KubernetesCiTests(unittest.TestCase):
    def test_all_deployed_images_are_preloaded_and_cannot_pull(self):
        plan = (ROOT / 'tests/kubernetes/preload-e2e-images.sh').read_text()
        releases = yaml.safe_load((ROOT / 'src/app/helmfile.yaml').read_text())['releases']
        dependencies = set()
        for release in releases:
            chart = (ROOT / 'src/app' / release['chart']).resolve()
            with tempfile.TemporaryDirectory() as directory:
                values = Path(directory) / 'values.yaml'
                values.write_text(yaml.safe_dump(release['values'][-1]))
                rendered = subprocess.check_output(['helm', 'template', release['name'], str(chart),
                    '-f', str(values), '-f', str(ROOT / 'tests/kubernetes/e2e-offline-images.yaml'),
                    '--set', 'image.tag=e2e'], text=True)
            for obj in yaml.safe_load_all(rendered):
                if not obj or obj['kind'] not in ('Deployment', 'StatefulSet', 'DaemonSet'): continue
                spec = obj['spec']['template']['spec']
                for container in spec.get('containers', []) + spec.get('initContainers', []):
                    self.assertEqual('Never', container.get('imagePullPolicy'), container['image'])
                    image = container['image']
                    if image.startswith('public.ecr.aws/aws-containers/retail-store-sample-'):
                        self.assertTrue(image.endswith(':e2e'))
                    else:
                        self.assertIn(image, plan)
                        dependencies.add(image)
        self.assertEqual(5, len(dependencies))

    def run_preload(self, fail=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for tool in ('docker', 'kind', 'sleep'):
                executable = path / tool
                executable.write_text('#!/bin/sh\nprintf "%s %s\\n" "' + tool + '" "$*" >> "$CALLS"\n'
                    + ('if [ "$1" = pull ] && [ "$FAIL_PULL" = true ]; then exit 1; fi\nif [ "$1 $2" = "image inspect" ]; then echo linux/amd64; fi\n' if tool == 'docker' else 'echo isolated-test-control-plane\n' if tool == 'kind' else ''))
                executable.chmod(0o700)
            calls = path / 'calls'
            result = subprocess.run(['bash', str(ROOT / 'tests/kubernetes/preload-e2e-images.sh'), 'isolated-test'],
                text=True, capture_output=True,
                env={'PATH': str(path) + os.pathsep + os.defpath, 'CALLS': str(calls), 'FAIL_PULL': str(fail).lower()})
            return result, calls.read_text().splitlines()

    def test_preload_uses_vendor_sources_and_named_cluster(self):
        result, calls = self.run_preload()
        self.assertEqual(0, result.returncode, result.stderr)
        pulls = [line for line in calls if line.startswith('docker pull ')]
        self.assertEqual(5, len(pulls))
        self.assertTrue(all(line.startswith('docker pull docker.io/') for line in pulls))
        self.assertIn('kind get nodes --name isolated-test', calls)
        self.assertEqual(5, sum(line.startswith('docker exec --privileged -i isolated-test-control-plane ctr ') for line in calls))
        self.assertTrue(all('--platform linux/amd64' in line and '--digests' not in line for line in calls if line.startswith('docker exec ')))
        self.assertEqual(5, sum(line.startswith('docker image save --platform linux/amd64 ') for line in calls))

    def test_failed_download_is_bounded_and_does_not_load_an_image(self):
        result, calls = self.run_preload(fail=True)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(3, sum(line.startswith('docker pull ') for line in calls))
        self.assertFalse(any(line.startswith('docker exec ') for line in calls))
        self.assertIn('deployment was not attempted', result.stderr)


if __name__ == '__main__':
    unittest.main()

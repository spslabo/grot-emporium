import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from scripts.grot_config import ROOT


class PublicationInstructionsTests(unittest.TestCase):
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

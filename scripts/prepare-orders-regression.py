#!/usr/bin/env python3
"""Export an intentionally broken Orders build context; never alter the worktree.
Usage: python scripts/prepare-orders-regression.py --output /tmp/grot-bad-orders
Only build/deploy this fixture into the explicitly approved demo environment.
Reset by redeploying the normal Orders image. No database reset is required:
the injected failure occurs before repository.save().
"""
import argparse
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = args.output.resolve()
if output == root or root in output.parents:
    parser.error('The output must be outside the repository.')
if output.exists():
    parser.error('Output already exists; choose a new directory (nothing is overwritten).')
output.mkdir(parents=True)
shutil.copytree(root / 'src/orders', output / 'src/orders',
                ignore=shutil.ignore_patterns('target', '.git', '*.log'))
patch = root / 'tests/fixtures/orders-numeric-sku.patch'
subprocess.run(['git', 'apply', '--check', str(patch)], cwd=output, check=True)
subprocess.run(['git', 'apply', str(patch)], cwd=output, check=True)
print(f'INTENTIONALLY BROKEN demo build context: {output / "src/orders"}')
print('Expected: UUID product IDs throw NumberFormatException before order persistence.')
print('The working repository is unchanged. No image was built, pushed, or deployed.')

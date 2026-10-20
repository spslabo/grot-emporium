#!/usr/bin/env python3
"""Generate matching backend/UI seed catalogs and existing ID-based image URLs."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
products = json.loads((ROOT / 'src/catalog/grots.json').read_text())
assert len(products) == 9
assert len({p['id'] for p in products}) == len(products)
assert len({p['slug'] for p in products}) == len(products)
tags = [{'name': name, 'displayName': title} for name, title in [
    ('classics', 'Classic Grots'), ('crew', 'On-Call Crew'),
    ('adventures', 'Adventurous Grots'), ('rare', 'Rare Grots')]]
assert all(set(p['tags']) <= {t['name'] for t in tags} for p in products)
assert all(p['price'] > 0 for p in products)
catalog = [{k: v for k, v in p.items() if k != 'slug'} for p in products]
expected = {}
for folder in ['src/catalog/repository', 'src/ui/src/main/resources/data']:
    expected[ROOT / folder / 'products.json'] = (json.dumps(catalog, indent=2) + '\n').encode()
    expected[ROOT / folder / 'tags.json'] = (json.dumps(tags, indent=2) + '\n').encode()
for p in products:
    source = ROOT / 'src/ui/src/main/resources/static/assets/img/grots' / (p['slug'] + '.jpeg')
    expected[ROOT / 'src/ui/src/main/resources/static/assets/img/products' / (p['id'] + '.jpg')] = source.read_bytes()
stale = []
for target, data in expected.items():
    if args.check:
        if not target.exists() or target.read_bytes() != data:
            stale.append(str(target.relative_to(ROOT)))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
if stale:
    print('Stale generated assets: ' + ', '.join(stale), file=sys.stderr)
    sys.exit(1)
print(f'{"Checked" if args.check else "Generated"} {len(products)} Grot products and matching images.')

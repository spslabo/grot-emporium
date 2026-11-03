#!/usr/bin/env python3
"""One synthetic storefront purchase plus SELECT-only PostgreSQL verification.

Requires explicit authorization. Does not inject faults or restart workloads.
This single probe is not the experiment's sustained recovery verdict.
"""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import http.cookiejar
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = set()
        self.radios = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        if tag == 'input' and attrs.get('type') == 'radio' and attrs.get('value'):
            self.radios.append(attrs['value'])

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())

    def order_id(self):
        if 'order-subtotal' not in self.ids:
            raise ValueError('Missing order confirmation')
        try:
            value = self.text[self.text.index('Order ID') + 1]
            return str(uuid.UUID(value))
        except (ValueError, IndexError) as exc:
            raise ValueError('Missing or invalid confirmation order ID') from exc


def persistence_sql(order_id, product_id, email, unit_cost):
    # Validate before interpolation; never accept arbitrary SQL from callers.
    order_id = str(uuid.UUID(order_id))
    product_id = str(uuid.UUID(product_id))
    if not re.fullmatch(r'aaif-[0-9a-f]{32}@example\.test', email):
        raise ValueError('Invalid synthetic probe email')
    if type(unit_cost) is not int or unit_cost < 0:
        raise ValueError('Invalid expected unit cost')
    return f"""BEGIN READ ONLY;
SELECT json_build_object(
 'read_only_role', NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
   AND NOT has_table_privilege(current_user, 'orders', 'INSERT,UPDATE,DELETE,TRUNCATE'),
 'matched', EXISTS (
 SELECT 1 FROM orders o JOIN shipping_addresses s ON s.order_id=o.id
 WHERE o.id='{order_id}' AND s.email='{email}'
 AND (SELECT count(*) FROM order_items i WHERE i.order_id=o.id)=1
 AND EXISTS (SELECT 1 FROM order_items i WHERE i.order_id=o.id
             AND i.product_id='{product_id}' AND i.quantity=1
             AND i.unit_cost={unit_cost} AND i.total_cost={unit_cost})));
ROLLBACK;
"""


def verify_database(args, order_id, product_id, email, unit_cost):
    # Password stays inside the existing database pod, never in local output/argv.
    command = ['kubectl', '--context', args.context, '-n', args.namespace,
               '--request-timeout=15s', 'exec', '-i', 'deploy/grot-postgres', '--',
               'sh', '-c', 'export PGPASSWORD="$GROT_DB_MONITOR_PASSWORD"; '
               'exec psql -h 127.0.0.1 -U db-o11y -d orders -Atq -v ON_ERROR_STOP=1']
    result = subprocess.run(command, input=persistence_sql(order_id, product_id, email, unit_cost),
                            text=True, capture_output=True, timeout=25)
    if result.returncode:
        raise RuntimeError('Database verification command failed; check cluster access and monitor role')
    result = json.loads(result.stdout)
    if result.get('read_only_role') is not True:
        raise RuntimeError('Database verification role is not restricted as expected')
    return result.get('matched') is True


def probe(args):
    result = {'probe_id': uuid.uuid4().hex, 'started_at': datetime.now(timezone.utc).isoformat(),
              'outcome': 'unknown', 'stage': 'initialization'}
    email = 'aaif-' + result['probe_id'] + '@example.test'
    catalog = json.loads((Path(__file__).resolve().parents[1] / 'src/catalog/grots.json').read_text())
    product = str(uuid.UUID(catalog[0]['id']))
    unit_cost = catalog[0]['price']
    result.update(product_id=product, expected_unit_cost=unit_cost, synthetic_email=email)
    base = args.base_url.rstrip('/')
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, data=None, required=None):
        result['stage'] = path
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        with opener.open(base + path, data=body, timeout=15) as response:
            if not response.url.startswith(base + '/'):
                raise RuntimeError('Unexpected redirect outside storefront')
            page = Page(response.read(2_000_000).decode('utf-8'))
        if required and required not in page.ids:
            raise ValueError('Missing expected shopping stage: ' + required)
        return page

    try:
        request('/')
        request('/catalog/' + product)
        request('/cart', {'productId': product, 'quantity': '1'})
        request('/cart', required='checkout')
        request('/checkout', required='firstName')
        delivery = request('/checkout', {'firstName': 'AAIF', 'lastName': 'Probe',
                           'address1': '1 Example Street', 'city': 'Demo City',
                           'state': 'CA', 'zipCode': '90210', 'email': email})
        if not delivery.radios:
            raise ValueError('No delivery option')
        request('/checkout/delivery', {'token': delivery.radios[0]}, required='cardNumber')
        page = request('/checkout/payment', {'cardHolder': 'AAIF Probe',
                       'cardNumber': '4242424242424242', 'expiryDate': '12/35', 'cvc': '123'})
        result['order_id'] = page.order_id()
        result['stage'] = 'persistence'
        matched = verify_database(args, result['order_id'], product, email, unit_cost)
        result.update(outcome='passed' if matched else 'failed', persistence_matched=matched)
    except urllib.error.HTTPError as exc:
        result.update(outcome='failed', error='HTTP ' + str(exc.code))
    except ValueError as exc:
        # A malformed database response is missing evidence, not a proven failed purchase.
        result.update(outcome='unknown' if result['stage'] == 'persistence' else 'failed', error=str(exc))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        result.update(outcome='unknown', error=type(exc).__name__)
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--context', required=True)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--authorized-demo', action='store_true', help='Authorize one synthetic purchase')
    args = parser.parse_args()
    if not args.authorized_demo:
        parser.error('--authorized-demo is required: this creates a synthetic order')
    url = urllib.parse.urlsplit(args.base_url)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        parser.error('Provide an HTTP(S) storefront URL without credentials, query or fragment')
    result = probe(args)
    print(json.dumps(result, indent=2))
    return {'passed': 0, 'failed': 1, 'unknown': 2}[result['outcome']]


if __name__ == '__main__':
    raise SystemExit(main())

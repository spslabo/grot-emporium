import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

name = sys.argv[1]
expected = {name + ':' + signal for signal in ('metrics', 'logs', 'traces', 'profiles', 'faro')}
# Explicitly test stripping of browser credentials, using synthetic values only.
payload = json.dumps({'meta': {'app': {'name': 'grot-emporium-web'}}, 'events': [{'name': 'grot_probe'}]}).encode()
response = urlopen(Request('http://gateway:8080/telemetry', data=payload,
    headers={'Content-Type': 'application/json', 'Cookie': 'synthetic=not-real', 'Authorization': 'Bearer synthetic-not-real',
        'X-Goog-IAP-JWT-Assertion': 'synthetic-not-real', 'X-Forwarded-For': '192.0.2.1'}), timeout=15)
assert response.status == 200
try:
    urlopen(Request('http://gateway:8080/telemetry', data=payload.replace(b'grot_probe', b'grot_probe_redirect')), timeout=10)
    raise AssertionError('An upstream redirect must not reach the browser')
except HTTPError as error:
    assert error.code == 502
    assert not error.headers.get('Location')
    assert b'private-upstream' not in error.read()
with urlopen('http://gateway:8080/catalog', timeout=10) as response:
    page = response.read()
    assert b'https://sink' not in page and b'dummy-not-a-real-token' not in page
for _ in range(40):
    with urlopen('https://sink:18766/stats', timeout=5) as response: counts = json.load(response)
    if all(counts.get(signal, 0) > 0 for signal in expected): break
    time.sleep(3)
else: raise SystemExit('Not all five signal types reached the selected destination')
assert not counts.get('credential_leak'), 'Proxy forwarded browser credentials'
other = 'beta' if name == 'alpha' else 'alpha'
assert not any(key.startswith(other + ':') for key in counts), 'Cross-destination telemetry leak'
print('Selected destination received metrics, logs, traces, profiles and Faro; no cross-destination data or browser credentials.')

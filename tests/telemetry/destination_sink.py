"""TLS mock destinations for offline transport tests. Never retains payloads/tokens."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit, parse_qs
import json
import base64
import os
import ssl
import gzip
from snappy_block import decode

counts = Counter()
lock = Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        if self.path != '/stats': self.send_error(404); return
        with lock: data = json.dumps(dict(counts)).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        path = urlsplit(self.path).path
        # Match real ingestion paths; identify tenants by authentication, not
        # artificial URL prefixes that would bypass production validation.
        destination = None
        rotated = False
        if path.startswith('/collect/'):
            destination = path.removeprefix('/collect/')
            if destination not in ('alpha', 'beta'): self.send_error(404); return
        else:
            tokens = ('dummy-not-a-real-token', 'dummy-rotated-not-a-real-token')
            for tenant in ('alpha', 'beta'):
                expected = ['Basic ' + base64.b64encode(f'test-{tenant}:{token}'.encode()).decode() for token in tokens]
                if self.headers.get('Authorization') in expected:
                    destination = tenant
                    rotated = self.headers.get('Authorization') == expected[1]
                    break
            if destination is None: self.send_error(401); return
        size = int(self.headers.get('Content-Length', '0'))
        if size > 16 * 1024 * 1024: self.send_error(413); return
        body = self.rfile.read(size)
        if not body: self.send_error(400); return
        if 'collect' in path and b'grot_probe_redirect' in body:
            self.send_response(302)
            self.send_header('Location', 'https://private-redirect.example.invalid/collect/private-key')
            self.end_headers()
            self.wfile.write(b'private-upstream-error-body')
            return
        if 'collect' in path:
            signal = 'faro'
            # No incoming browser credentials may pass through the gateway.
            if any(self.headers.get(key) for key in ('Cookie', 'Authorization', 'X-Goog-IAP-JWT-Assertion', 'X-Forwarded-For')):
                with lock: counts['credential_leak'] += 1
        elif path == '/otlp/v1/traces': signal = 'traces'
        elif path in ('/ingest', '/push.v1.PusherService/Push'): signal = 'profiles'
        elif path == '/loki/api/v1/push': signal = 'logs'
        elif path in ('/api/prom/push', '/otlp/v1/metrics'): signal = 'metrics'
        else: self.send_error(404); return
        db_markers = []
        if signal == 'traces':
            decoded = gzip.decompress(body) if self.headers.get('Content-Encoding') == 'gzip' else body
            if b'postgresql' in decoded and b'db.system' in decoded:
                db_markers.append('db-traces')
        if path in ('/api/prom/push', '/loki/api/v1/push'):
            try:
                decoded = decode(body)
                for needle, marker in [(b'container_cpu_usage_seconds_total', 'infra-containers'),
                                       (b'node_cpu_seconds_total', 'infra-host'),
                                       (b'kube_pod_info', 'infra-kube-state'),
                                       (b'kubernetes-events', 'infra-events')]:
                    if needle in decoded: db_markers.append(marker)
                if b'integrations/db-o11y' in decoded:
                    if b'pg_stat_statements_calls_total' in decoded: db_markers.append('db-query-metrics')
                    if b'query_association' in decoded and b'querytext=' in decoded: db_markers.append('db-query-details')
                    if b'pg_stat_database_numbackends' in decoded: db_markers.append('db-health')
            except (ValueError, IndexError):
                self.send_error(400); return
        with lock:
            for marker in db_markers: counts[destination + ':' + marker] += 1
            counts[destination + ':' + signal] += 1
            if rotated: counts[destination + ':rotated:' + signal] += 1
            if signal == 'profiles':
                profile = parse_qs(urlsplit(self.path).query).get('name', [''])[0]
                for service in ('ui', 'cart', 'orders', 'catalog', 'checkout'):
                    if 'grot-' + service in profile: counts[destination + ':profile:' + service] += 1
        self.send_response(200)
        # An empty protobuf ExportTraceServiceResponse is a successful OTLP response.
        self.send_header('Content-Type', 'application/x-protobuf' if signal == 'traces' else 'application/json')
        self.end_headers()
        if signal != 'traces': self.wfile.write(b'{}')

if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', 18766), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain('/certs/cert.pem', '/certs/key.pem')
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    server.serve_forever()

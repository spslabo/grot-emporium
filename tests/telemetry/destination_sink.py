"""TLS mock destinations for offline transport tests. Never retains payloads/tokens."""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from urllib.parse import urlsplit, parse_qs
import json
import base64
import os
import ssl

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
        parts = path.strip('/').split('/')
        if len(parts) < 2 or parts[0] not in ('alpha', 'beta'):
            self.send_error(404); return
        rotated = False
        if 'collect' not in path:
            tokens = ('dummy-not-a-real-token', 'dummy-rotated-not-a-real-token')
            expected = ['Basic ' + base64.b64encode(f'test-{parts[0]}:{token}'.encode()).decode() for token in tokens]
            if self.headers.get('Authorization') not in expected:
                self.send_error(401); return
            rotated = self.headers.get('Authorization') == expected[1]
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
        elif 'traces' in path: signal = 'traces'
        elif 'profiles' in path: signal = 'profiles'
        elif 'logs' in path: signal = 'logs'
        elif 'metrics' in path: signal = 'metrics'
        else: self.send_error(404); return
        with lock:
            counts[parts[0] + ':' + signal] += 1
            if rotated: counts[parts[0] + ':rotated:' + signal] += 1
            if signal == 'profiles':
                profile = parse_qs(urlsplit(self.path).query).get('name', [''])[0]
                for service in ('ui', 'cart', 'orders', 'catalog', 'checkout'):
                    if 'grot-' + service in profile: counts[parts[0] + ':profile:' + service] += 1
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

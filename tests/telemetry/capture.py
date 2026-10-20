"""Local-only telemetry smoke receiver. No Grafana credentials or cloud export.
Reports counts/signal types only, never captured payloads. Not for deployment.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import Counter
from threading import Lock
from urllib.parse import urlparse, parse_qs
import gzip
import json
import os

counts = Counter()
lock = Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def cors(self):
        self.send_header('Access-Control-Allow-Origin', os.environ.get('ALLOWED_ORIGIN', 'http://host.docker.internal:18765'))
        self.send_header('Access-Control-Allow-Headers', self.headers.get('Access-Control-Request-Headers', 'Content-Type'))
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
    def do_OPTIONS(self):
        with lock: counts['preflight'] += 1
        self.send_response(204); self.cors(); self.end_headers()
    def do_GET(self):
        if self.path != '/stats': self.send_error(404); return
        with lock: result = json.dumps(dict(counts)).encode()
        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(result)
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 8 * 1024 * 1024: self.send_error(413); return
        body = self.rfile.read(length)
        path = urlparse(self.path)
        with lock:
            counts[path.path] += 1
            counts['bytes'] += len(body)
            if path.path == '/ingest':
                app = parse_qs(path.query).get('name', ['unknown'])[0].split('{')[0]
                counts['profile:' + app] += 1
            if path.path == '/collect':
                try:
                    if self.headers.get('Content-Encoding') == 'gzip': body = gzip.decompress(body)
                    payload = json.loads(body)
                    for key in ['events', 'measurements', 'exceptions', 'traces', 'logs']:
                        if payload.get(key): counts['faro:' + key] += 1
                except (ValueError, OSError): counts['invalid_json'] += 1
        self.send_response(200); self.cors(); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{}')

if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 18766), Handler).serve_forever()

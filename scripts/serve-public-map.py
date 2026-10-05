#!/usr/bin/env python3
"""Serve only exported viewer assets and public map JSON on loopback."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nbmap.map_server import ASSETS, MAX_BYTES
from nbmap.public_map import validate_public
import json


def create_server(root, port=8766, dataset_path=None):
    root = Path(root).absolute()
    dataset_path = Path(dataset_path).resolve() if dataset_path else root / 'dataset.json'
    validate_public(json.loads(dataset_path.read_bytes()))
    allowed = {('/index.html' if route == '/' else route): (file, mime) for route, (file, mime) in ASSETS.items()}
    allowed['/'] = ('index.html', 'text/html; charset=utf-8')
    allowed['/dataset.json'] = ('dataset.json', 'application/json; charset=utf-8')
    for vendor in ('leaflet', 'gcoord', 'lucide'):
        allowed[f'/vendor/{vendor}/LICENSE'] = (f'vendor/{vendor}/LICENSE', 'text/plain; charset=utf-8')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            entry = allowed.get(urlsplit(self.path).path)
            if entry is None:
                self.send_error(404)
                return
            filename, mime = entry
            active_root = root.resolve()
            target = dataset_path if filename == 'dataset.json' else (active_root / filename).resolve()
            if filename != 'dataset.json' and not target.is_relative_to(active_root):
                self.send_error(404)
                return
            try:
                with target.open('rb') as stream:
                    body = stream.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError('oversized')
            except (OSError, ValueError):
                self.send_error(503)
                return
            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        do_HEAD = do_GET

        def unsupported(self):
            self.send_error(405)

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = unsupported

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    server = create_server(args.root, args.port, args.dataset)
    print(f'Static map origin: http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

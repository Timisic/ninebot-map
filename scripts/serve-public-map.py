#!/usr/bin/env python3
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nbmap.map_server import ASSETS, MAX_BYTES
from nbmap.public_map import validate_public
from nbmap.public_updates import PublicUpdates
import json
import re


def create_server(root, port=8766, dataset_path=None, *, updates_config=None, updates_state=None, updates=None):
    root = Path(root).absolute()
    dataset_path = Path(dataset_path).resolve() if dataset_path else root / 'dataset.json'
    validate_public(json.loads(dataset_path.read_bytes()))
    updates = updates or PublicUpdates(updates_config, updates_state, dataset_path)
    allowed = {('/index.html' if route == '/' else route): (file, mime) for route, (file, mime) in ASSETS.items()}
    allowed['/'] = ('index.html', 'text/html; charset=utf-8')
    allowed['/dataset.json'] = ('dataset.json', 'application/json; charset=utf-8')
    for vendor in ('leaflet', 'gcoord', 'lucide'):
        allowed[f'/vendor/{vendor}/LICENSE'] = (f'vendor/{vendor}/LICENSE', 'text/plain; charset=utf-8')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/api/update':
                state = updates.snapshot()
                self.update_reply(503 if state['phase'] == 'unavailable' else 200, state)
                return
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

        def update_reply(self, status, state=None):
            body = json.dumps(state if state is not None else updates.snapshot(), separators=(',', ':')).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def do_POST(self):
            if self.path != '/api/update':
                self.unsupported()
                return
            if updates.allowed_origin is None:
                self.update_reply(503)
                return
            origins = self.headers.get_all('Origin', [])
            fetch_sites = self.headers.get_all('Sec-Fetch-Site', [])
            if origins != [updates.allowed_origin] or (fetch_sites and (len(fetch_sites) != 1 or fetch_sites[0] not in ('same-origin', 'none'))):
                self.update_reply(403)
                return
            if len(self.headers.get_all('Content-Type', [])) != 1 or self.headers.get_content_type() != 'application/json' or self.headers.get('Content-Encoding'):
                self.update_reply(415)
                return
            lengths = self.headers.get_all('Content-Length', [])
            if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not re.fullmatch(r'[0-9]+', lengths[0]):
                self.update_reply(400)
                return
            if len(lengths[0]) > 2 or int(lengths[0]) > 64:
                self.update_reply(413)
                return
            try:
                self.connection.settimeout(5)
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]) or json.loads(raw) != {}:
                    raise ValueError('Invalid update body')
            except (OSError, ValueError):
                self.update_reply(400)
                return
            result = updates.request_update()
            self.update_reply(result.status, result.snapshot)

        def unsupported(self):
            if self.path == '/api/update':
                self.update_reply(405)
            else:
                self.send_error(405)

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = unsupported

    class Server(ThreadingHTTPServer):
        def server_close(self):
            updates.close()
            super().server_close()

    try:
        server = Server(('127.0.0.1', port), Handler)
    except OSError:
        updates.close()
        raise
    server.daemon_threads = True
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--updates-config', type=Path)
    parser.add_argument('--updates-state', type=Path)
    args = parser.parse_args()
    server = create_server(args.root, args.port, args.dataset,
                           updates_config=args.updates_config, updates_state=args.updates_state)
    print(f'Static map origin: http://127.0.0.1:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

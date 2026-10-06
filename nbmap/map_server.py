import json
import hashlib
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .dataset import validate_dataset
from .viewer_resources import ASSETS, WEB_ROOT, viewer_resources

MAX_BYTES = 40 * 1024 * 1024


def read_map_dataset(path):
    with Path(path).open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('地图数据超过 40 MB 上限，请缩小范围')
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('地图文件不是有效 JSON') from None
    validate_dataset(data)
    if len(data['rides']) > 25000 or sum(len(t['points']) for t in data['tracks']) > 300000:
        raise ValueError('地图数据超过 25,000 条行程或 300,000 个点上限')
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def create_server(dataset_path=None, port=0):
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError('端口必须在 0 到 65535 之间')
    dataset_path = Path(dataset_path).resolve() if dataset_path else None
    snapshot = read_map_dataset(dataset_path) if dataset_path else None
    dataset_lock = threading.Lock()
    revision = hashlib.sha256(snapshot).hexdigest() if snapshot else None
    signature = None
    def current_snapshot():
        nonlocal snapshot, revision, signature
        with dataset_lock:
            path = dataset_path
            # Old generation-specific launch commands also follow the atomic pointer.
            if path.parent.parent.name == 'prepared' and (path.parent.parent / 'latest.json').exists():
                try:
                    pointer = json.loads((path.parent.parent / 'latest.json').read_text())
                    candidate = (path.parent.parent / pointer['directory'] / 'dataset.json').resolve()
                    if candidate.is_relative_to(path.parent.parent):
                        path = candidate
                except (ValueError, KeyError, OSError, TypeError):
                    pass
            try:
                stat = path.stat()
                current = (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino)
                if current != signature:
                    candidate = read_map_dataset(path)
                    snapshot = candidate
                    revision = hashlib.sha256(candidate).hexdigest()
                    signature = current
            except (ValueError, OSError):
                pass  # Keep the last validated dataset during failed/invalid replacement.
            return snapshot, revision
    resources = viewer_resources(WEB_ROOT).routes

    class Handler(BaseHTTPRequestHandler):
        server_version = 'LocalRideMap'
        sys_version = ''

        def log_message(self, *args):
            pass

        def _reply(self, status, content=b'', mime='text/plain; charset=utf-8', etag=None):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.send_header('Cache-Control', 'no-store')
            if etag:
                self.send_header('ETag', '"' + etag + '"')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(content)

        def _valid_request(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            return self.headers.get('Host') == expected and self.headers.get('Origin') in (None, 'http://' + expected) and self.headers.get('Sec-Fetch-Site') not in ('cross-site',)

        def do_GET(self):
            if not self._valid_request():
                self._reply(403, b'Forbidden')
                return
            raw_target = self.requestline.split()[1]
            if raw_target == self.path == '/dataset.json' and dataset_path:
                content, etag = current_snapshot()
                self._reply(200, content, 'application/json; charset=utf-8', etag)
                return
            resource = resources.get(raw_target) if raw_target == self.path else None
            if resource is None:
                self._reply(404, b'Not found')
                return
            self._reply(200, *resource)

        do_HEAD = do_GET

        def _unsupported(self):
            self._reply(405, b'Method not allowed')

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _unsupported

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def serve_map(dataset_path=None, port=8765, no_open=False):
    server = create_server(dataset_path, port)
    url = f'http://127.0.0.1:{server.server_port}/'
    print(f'本地骑行地图：{url}', flush=True)
    print('仅本机访问；默认离线。按 Ctrl-C 关闭。', flush=True)
    if not no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n本地地图已关闭。', flush=True)
    finally:
        server.server_close()
    return 0

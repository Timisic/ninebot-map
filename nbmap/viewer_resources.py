"""One allowlisted viewer snapshot for local serving and public export."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parent.parent / 'web'
ASSETS = {
    '/theme-init.js': ('theme-init.js', 'text/javascript'),
    '/wheel-zoom.mjs': ('wheel-zoom.mjs', 'text/javascript'),
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
    '/app.mjs': ('app.mjs', 'text/javascript; charset=utf-8'),
    '/vendor/gcoord/gcoord.mjs': ('vendor/gcoord/gcoord.mjs', 'text/javascript; charset=utf-8'),
    '/model.mjs': ('model.mjs', 'text/javascript; charset=utf-8'),
    '/icons.mjs': ('icons.mjs', 'text/javascript; charset=utf-8'),
    '/map-layer.mjs': ('map-layer.mjs', 'text/javascript; charset=utf-8'),
    '/vendor/leaflet/leaflet.js': ('vendor/leaflet/leaflet.js', 'text/javascript; charset=utf-8'),
    '/vendor/leaflet/leaflet.css': ('vendor/leaflet/leaflet.css', 'text/css; charset=utf-8'),
}
for _image in ('layers.png', 'layers-2x.png', 'marker-icon.png', 'marker-icon-2x.png', 'marker-shadow.png'):
    ASSETS['/vendor/leaflet/images/' + _image] = ('vendor/leaflet/images/' + _image, 'image/png')

IMMUTABLE_FILES = {filename: mime for filename, mime in ASSETS.values() if filename != 'index.html'}
BUNDLE_HASH = re.compile(r'[a-f0-9]{64}')


@dataclass(frozen=True)
class ViewerResources:
    bundle_hash: str
    files: dict[str, tuple[bytes, str]]
    routes: dict[str, tuple[bytes, str]]


def viewer_resources(web_root):
    files = {filename: (Path(web_root).joinpath(filename).read_bytes(), mime) for filename, mime in ASSETS.values()}
    digest = hashlib.sha256()
    for filename, (body, _) in sorted(files.items()):
        digest.update(filename.encode() + b'\0')
        digest.update(len(body).to_bytes(8, 'big'))
        digest.update(body)
    bundle_hash = digest.hexdigest()
    prefix = f'assets/{bundle_hash}/'
    html, mime = files['index.html']

    def version_entry(match):
        attribute, filename, quote = match.groups()
        return attribute + './' + prefix + filename + quote if filename in IMMUTABLE_FILES else match.group()

    html = re.sub(r'((?:src|href)=["\'])\./([^"\']+)(["\'])', version_entry, html.decode()).encode()
    files['index.html'] = (html, mime)
    routes = {route: files[filename] for route, (filename, _) in ASSETS.items()}
    for filename in IMMUTABLE_FILES:
        routes['/' + prefix + filename] = files[filename]
        files[prefix + filename] = files[filename]
    return ViewerResources(bundle_hash, files, routes)

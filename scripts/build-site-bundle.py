#!/usr/bin/env python3
"""Build an allowlisted static site plus a separate standard-library host runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from nbmap.public_map import export_site

parser = argparse.ArgumentParser()
parser.add_argument('--dataset', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Output must be a new directory.')
args.output.mkdir(parents=True, mode=0o700)
export_site(json.loads(args.dataset.read_text()), args.output / 'public')
code_files = ['nbmap/__init__.py', 'nbmap/public_map.py', 'nbmap/stops.py', 'nbmap/public_updates.py', 'nbmap/map_server.py', 'nbmap/viewer_resources.py', 'nbmap/dataset.py', 'nbmap/storage.py',
              'scripts/serve-public-map.py', 'scripts/receive-public-map.py']
for relative in code_files:
    target = args.output / 'code' / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / relative, target)
shutil.copyfile(ROOT / 'templates/map-site.service', args.output / 'map-site.service')
shutil.copyfile(ROOT / 'templates/map-update.json', args.output / 'map-update.example.json')
manifest = {'schema_version': 1, 'files': {}}
for path in sorted(args.output.rglob('*')):
    if path.is_file():
        data = path.read_bytes()
        manifest['files'][str(path.relative_to(args.output))] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
(args.output / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
archive = args.output.with_suffix('.tar.gz')
with tarfile.open(archive, 'w:gz') as tar:
    for name in [*manifest['files'], 'manifest.json']:
        tar.add(args.output / name, arcname=name, recursive=False)
print(json.dumps({'archive': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': len(manifest['files'])}))

import copy
import hashlib
import json
import tempfile
import unittest
import subprocess
import sys
import threading
import http.client
import importlib.util
import re
import shutil
from unittest.mock import patch
from pathlib import Path

from nbmap.public_map import public_dataset, publish_dataset, export_site, validate_public
from nbmap.map_server import ASSETS
from nbmap.viewer_resources import viewer_resources, WEB_ROOT, IMMUTABLE_FILES

FIXTURE = Path(__file__).parent / 'fixtures/synthetic-map.json'


class PublicMapTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(FIXTURE.read_text())

    def test_deployment_bundle_runs_without_the_source_checkout(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'bundle'
            subprocess.run([sys.executable, str(root / 'scripts/build-site-bundle.py'),
                            '--dataset', str(FIXTURE.resolve()), '--output', str(bundle)],
                           check=True, capture_output=True, cwd=directory)
            for script in ('serve-public-map.py', 'receive-public-map.py'):
                result = subprocess.run([sys.executable, '-I', str(bundle / 'code/scripts' / script), '--help'],
                                        capture_output=True, text=True, cwd=directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)

    def test_export_only_contains_map_fields_and_aggregate_history(self):
        self.dataset['private_note'] = 'PRIVATE_SENTINEL'
        self.dataset['rides'][0]['account'] = 'ACCOUNT_SENTINEL'
        result = public_dataset(self.dataset)
        raw = json.dumps(result)
        for private in ['PRIVATE_SENTINEL', 'ACCOUNT_SENTINEL', self.dataset['dataset_id'], 'started_at', 'ended_at', 'source_month', 'snapshot_ids', '"duration_s"', 'speed_mps']:
            self.assertNotIn(private, raw)
        self.assertEqual(result['summary'], self.dataset['summary'])
        self.assertEqual(result['tracks'][0]['points'][0], [self.dataset['tracks'][0]['points'][0]['longitude'], self.dataset['tracks'][0]['points'][0]['latitude']])
        self.assertRegex(result['tracks'][0]['date'], r'^\d{4}-\d{2}-\d{2}$')

    def test_published_place_annotations_are_explicit_and_retain_historical_members(self):
        first, absent = 'r_' + 'a' * 24, 'r_' + 'b' * 24
        annotations = {'labels': {first: '合成球馆🏸', absent: '🏸' * 40},
                       'merges': [{'anchorId': first, 'memberIds': [first, absent]}]}
        self.dataset['place_annotations'] = annotations
        self.assertNotIn('place_annotations', public_dataset(self.dataset))
        self.assertEqual(public_dataset(self.dataset, place_annotations=annotations)['place_annotations'], annotations)
        self.assertEqual(public_dataset(self.dataset, place_annotations={})['place_annotations'], {})
        c1_name = {'labels': {first: '\u0085合成球馆'}}
        self.assertEqual(public_dataset(self.dataset, place_annotations=c1_name)['place_annotations'], c1_name)
        broken = [None, [], {'unknown': True}, {'labels': []}, {'labels': {'private-id': 'name'}},
                  {'labels': {first: ''}}, {'labels': {first: '\ufeff合成球馆'}}, {'labels': {first + '\n': 'name'}}, {'labels': {first: ' leading'}}, {'labels': {first: '🏸' * 41}},
                  {'merges': {}}, {'merges': [{'anchorId': first, 'memberIds': [first]}]},
                  {'merges': [{'anchorId': first, 'memberIds': [first, first]}]},
                  {'merges': [{'anchorId': first, 'memberIds': [absent, 'r_' + 'c' * 24]}]},
                  {'merges': [{'anchorId': first, 'memberIds': [first, 'private-id']}]},
                  {'merges': [{'anchorId': first, 'memberIds': [first, absent], 'private': True}]}]
        group = {'anchorId': first, 'memberIds': [first, absent]}
        broken.append({'merges': [group] * 12501})
        for annotations in broken:
            with self.subTest(annotations=str(annotations)[:120]):
                data = public_dataset(self.dataset)
                data['place_annotations'] = annotations
                with self.assertRaises(ValueError):
                    validate_public(data)

    def test_public_summary_includes_excluded_history_without_individual_records(self):
        ride = self.dataset['rides'][0]
        track = next(t for t in self.dataset['tracks'] if t['ride_id'] == ride['id'])
        ride.update(track_kind='missing', source_point_count=0, map_status='insufficient_points')
        self.dataset['tracks'].remove(track)
        summary = self.dataset['summary']
        summary['map_ride_count'] -= 1
        summary['map_distance_m'] -= ride['distance_m']
        summary['map_point_count'] -= len(track['points'])
        summary['map_exclusions'] = {'insufficient_points': 1}
        result = public_dataset(self.dataset)
        self.assertEqual(result['summary']['ride_count'], 12)
        self.assertEqual(len(result['tracks']), 11)
        self.assertNotIn('rides', result)
        self.assertNotIn('months', result)
        self.assertEqual(result['summary']['map_exclusions'], {'insufficient_points': 1})

    def test_opaque_existing_ids_remain_stable_for_destination_tie_breaks(self):
        old = self.dataset['rides'][0]['id']
        opaque = 'r_' + 'a' * 24
        self.dataset['rides'][0]['id'] = opaque
        next(t for t in self.dataset['tracks'] if t['ride_id'] == old)['ride_id'] = opaque
        self.assertEqual(public_dataset(self.dataset)['tracks'][0]['id'], opaque)

    def test_unknown_fields_and_invalid_summary_cannot_replace_live_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dataset.json'
            data = public_dataset(self.dataset)
            publish_dataset(data, path)
            original = path.read_bytes()
            for mutate in [lambda d: d.update(updated_at='2026-10-05 08:00:00+00:00'), lambda d: d['summary'].update(total_distance_m=0, known_distance_m=0, missing_distance_count=999), lambda d: d.update(schema_version=True), lambda d: d.update(tokens='secret'), lambda d: d['tracks'][0].update(started_at='secret'), lambda d: d['summary'].update(map_ride_count=999), lambda d: d['tracks'][0]['points'].append([999, 0])]:
                broken = copy.deepcopy(data)
                mutate(broken)
                with self.assertRaises(ValueError):
                    publish_dataset(broken, path)
                self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_static_folder_is_an_allowlist_and_cannot_overwrite_existing_export(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / 'site'
            export_site(self.dataset, site)
            paths = {str(p.relative_to(site)) for p in site.rglob('*') if p.is_file()}
            snapshot = viewer_resources(WEB_ROOT)
            expected = {filename for filename, _ in ASSETS.values()} | {'dataset.json', 'vendor/leaflet/LICENSE', 'vendor/gcoord/LICENSE', 'vendor/lucide/LICENSE'}
            expected |= {f'assets/{snapshot.bundle_hash}/{filename}' for filename, _ in ASSETS.values() if filename != 'index.html'}
            self.assertEqual(paths, expected)
            validate_public(json.loads((site / 'dataset.json').read_text()))
            html = (site / 'index.html').read_text()
            self.assertNotIn('type="file"', html)
            self.assertNotIn('import-button', html)
            self.assertIn(f'src="./assets/{snapshot.bundle_hash}/app.mjs"', html)
            self.assertIn(f'src="./assets/{snapshot.bundle_hash}/startup.js"', html)
            self.assertNotIn('theme-init.js', html)
            preloads = re.findall(r'<link rel="modulepreload" href="([^"]+)"', html)
            dependencies = set()
            pending = ['app.mjs']
            while pending:
                filename = pending.pop()
                for relative in re.findall(r"from ['\"](\./[^'\"]+)['\"]", snapshot.files[filename][0].decode()):
                    dependency = (Path(filename).parent / relative).as_posix()
                    if dependency not in dependencies:
                        dependencies.add(dependency)
                        pending.append(dependency)
            self.assertEqual(set(preloads), {f'./assets/{snapshot.bundle_hash}/{filename}' for filename in dependencies})
            self.assertIn('id="empty" class="empty-state" hidden', html)
            self.assertEqual((site / f'assets/{snapshot.bundle_hash}/app.mjs').read_bytes(), (WEB_ROOT / 'app.mjs').read_bytes())
            for filename in ['fonts/smiley-sans/SmileySans-Oblique.woff2', 'fonts/smiley-sans/LICENSE']:
                self.assertEqual((site / filename).read_bytes(), (WEB_ROOT / filename).read_bytes())
                self.assertEqual((site / f'assets/{snapshot.bundle_hash}/{filename}').read_bytes(), (WEB_ROOT / filename).read_bytes())
            with self.assertRaises(ValueError):
                export_site(self.dataset, site)

    def test_bundle_hash_changes_for_any_allowed_source_without_rewriting_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            web = Path(directory) / 'web'
            shutil.copytree(WEB_ROOT, web)
            original = viewer_resources(web)
            self.assertEqual(original.bundle_hash, viewer_resources(web).bundle_hash)
            (web / 'model.mjs').write_bytes((web / 'model.mjs').read_bytes() + b'\n')
            changed = viewer_resources(web)
            self.assertNotEqual(changed.bundle_hash, original.bundle_hash)
            self.assertEqual(changed.files['app.mjs'], original.files['app.mjs'])
            self.assertEqual(changed.files['vendor/leaflet/leaflet.css'], original.files['vendor/leaflet/leaflet.css'])
            with patch('nbmap.public_map.WEB_ROOT', web):
                site = export_site(self.dataset, Path(directory) / 'site')
            self.assertIn(f'./assets/{changed.bundle_hash}/app.mjs', (site / 'index.html').read_text())
            self.assertFalse(any('?' in str(p) for p in site.rglob('*')))

    def test_receiver_validates_stdin_and_rejects_old_or_private_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'public/dataset.json'
            data = public_dataset(self.dataset)
            def send(payload):
                return subprocess.run([sys.executable, 'scripts/receive-public-map.py', '--target', str(target)], input=json.dumps(payload).encode(), capture_output=True)
            self.assertEqual(send(data).returncode, 0)
            original = target.read_bytes()
            old = copy.deepcopy(data)
            old['updated_at'] = '2020-01-01T00:00:00Z'
            old['tracks'][0]['points'][0][0] += .0001
            result = send(old)
            self.assertEqual(result.returncode, 0)
            receipt = json.loads(result.stdout.decode().split('Public map receipt: ')[1])
            self.assertEqual(receipt['status'], 'skipped_older')
            self.assertEqual(receipt['reason'], 'current_is_newer')
            self.assertEqual(target.read_bytes(), original)
            receipt = json.loads(send(data).stdout.decode().split('Public map receipt: ')[1])
            self.assertEqual(receipt['status'], 'unchanged')
            self.assertEqual(target.read_bytes(), original)
            result = send({**data, 'tokens': 'PRIVATE_SENTINEL'})
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(b'PRIVATE_SENTINEL', result.stderr)
            self.assertEqual(target.read_bytes(), original)
            newer = copy.deepcopy(data)
            newer['updated_at'] = '2026-10-05T08:00:00Z'
            receipt = json.loads(send(newer).stdout.decode().split('Public map receipt: ')[1])
            self.assertEqual(receipt['status'], 'published')
            self.assertEqual(json.loads(target.read_bytes())['updated_at'], newer['updated_at'])

    def test_loopback_static_server_allows_only_get_head_and_exported_paths(self):
        spec = importlib.util.spec_from_file_location('static_map_server', 'scripts/serve-public-map.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            site = export_site(self.dataset, Path(directory) / 'site')
            current = Path(directory) / 'current'
            current.symlink_to(site, target_is_directory=True)
            server = module.create_server(current, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, method='GET'):
                    client = http.client.HTTPConnection('127.0.0.1', server.server_port)
                    client.request(method, path)
                    response = client.getresponse()
                    result = response.status, dict(response.headers), response.read()
                    client.close()
                    return result
                self.assertEqual(server.server_address[0], '127.0.0.1')
                self.assertEqual(request('/')[0], 200)
                self.assertEqual(request('/')[1]['Referrer-Policy'], 'strict-origin-when-cross-origin')
                self.assertEqual(request('/index.html')[0], 200)
                self.assertEqual(request('/dataset.json')[1]['ETag'], request('/dataset.json', 'HEAD')[1]['ETag'])
                bundle_hash = re.search(r'\./assets/([a-f0-9]{64})/', (site / 'index.html').read_text()).group(1)
                for filename in IMMUTABLE_FILES:
                    asset = request(f'/assets/{bundle_hash}/{filename}')
                    self.assertEqual(asset[0], 200, filename)
                    self.assertEqual(asset[2], (site / filename).read_bytes())
                    self.assertEqual(asset[1]['Cache-Control'], 'public, max-age=31536000, immutable')
                for path in ['/upload', '/import', '/.private/tokens.json', '/dataset.lock', '/data/', '/scripts/']:
                    self.assertEqual(request(path)[0], 404)
                for method in ['POST', 'PUT', 'PATCH', 'DELETE']:
                    self.assertEqual(request('/dataset.json', method)[0], 405)
                replacement = export_site(self.dataset, Path(directory) / 'replacement')
                (replacement / 'styles.css').write_text('body { color: red; }')
                pending = Path(directory) / 'next'
                pending.symlink_to(replacement, target_is_directory=True)
                pending.replace(current)
                self.assertEqual(request('/styles.css')[2], b'body { color: red; }')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_public_host_retains_old_bundles_and_rejects_paths_outside_allowlist(self):
        spec = importlib.util.spec_from_file_location('static_map_server', 'scripts/serve-public-map.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / 'web'
            shutil.copytree(WEB_ROOT, web)
            with patch('nbmap.public_map.WEB_ROOT', web):
                old = export_site(self.dataset, root / 'old')
                old_hash = viewer_resources(web).bundle_hash
                (web / 'styles.css').write_bytes((web / 'styles.css').read_bytes() + b'\nbody {color: red;}\n')
                new = export_site(self.dataset, root / 'new')
                new_hash = viewer_resources(web).bundle_hash
            assets = root / 'retained-assets'
            shutil.copytree(old / 'assets', assets)
            shutil.copytree(new / 'assets', assets, dirs_exist_ok=True)
            historical_theme = assets / old_hash / 'theme-init.js'
            historical_theme_bytes = b"document.documentElement.dataset.theme = 'light';\n"
            historical_theme.write_bytes(historical_theme_bytes)
            current = root / 'current'
            current.symlink_to(old, target_is_directory=True)
            server = module.create_server(current, 0, assets_root=assets)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path):
                    client = http.client.HTTPConnection('127.0.0.1', server.server_port)
                    client.request('GET', path)
                    response = client.getresponse()
                    result = response.status, response.read()
                    client.close()
                    return result
                old_route = f'/assets/{old_hash}/styles.css'
                previous = request(old_route)[1]
                pending = root / 'next'
                pending.symlink_to(new, target_is_directory=True)
                pending.replace(current)
                shutil.rmtree(old)
                self.assertEqual(request(old_route), (200, previous))
                self.assertEqual(request(f'/assets/{old_hash}/theme-init.js'), (200, historical_theme_bytes))
                self.assertEqual(request('/theme-init.js')[0], 404)
                self.assertEqual(request(f'/assets/{new_hash}/theme-init.js')[0], 404)
                self.assertEqual(request(f'/assets/{new_hash}/styles.css')[1], (web / 'styles.css').read_bytes())
                self.assertIn(new_hash.encode(), request('/')[1])
                for route in [old_route + '?version=1', '/assets/' + '0' * 64 + '/styles.css',
                              f'/assets/{old_hash}/index.html', f'/assets/{old_hash}/dataset.json',
                              f'/assets/{old_hash}/vendor/leaflet/../../README.md',
                              f'/assets/{old_hash}/../{new_hash}/styles.css',
                              f'/assets/{old_hash}/.private/tokens.json', f'/assets/{old_hash}/%73tyles.css',
                              '/dataset.json?refresh=1', '//styles.css']:
                    self.assertEqual(request(route)[0], 404, route)
                outside = root / 'private-token'
                outside.write_bytes(b'PRIVATE_SENTINEL')
                known = assets / new_hash / 'startup.js'
                known.unlink()
                known.symlink_to(outside)
                self.assertEqual(request(f'/assets/{new_hash}/startup.js')[0], 404)
                historical_theme.unlink()
                historical_theme.symlink_to(outside)
                self.assertEqual(request(f'/assets/{old_hash}/theme-init.js')[0], 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_publisher_sends_only_public_json_and_removes_temporary_identity(self):
        from unittest.mock import patch
        from nbmap.cloud import publish_site_data
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'private-dataset.json'
            source.write_text(json.dumps(self.dataset))
            annotations = {'labels': {'r_' + 'a' * 24: '合成球馆🏸'}, 'merges': []}
            calls = []
            def send(args, **kwargs):
                calls.append((args, kwargs))
                key_path = Path(args[args.index('-i') + 1])
                self.assertTrue(key_path.exists())
                self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
                validate_public(json.loads(kwargs['data']))
                self.assertEqual(json.loads(kwargs['data'])['place_annotations'], annotations)
                self.assertNotIn(b'snapshot_ids', kwargs['data'])
                return subprocess.CompletedProcess(args, 0, stdout=('Public map receipt: ' + json.dumps({'status':'published','reason':'accepted','sha256':hashlib.sha256(kwargs['data']).hexdigest(),'updated_at':'2026-10-05T08:00:00Z','requested_updated_at':'2026-10-05T08:00:00Z'}) + '\n').encode(), stderr=b'')
            with patch.dict('os.environ', {'MAP_DEPLOY_KEY': 'synthetic-secret'}), patch('nbmap.cloud.command', side_effect=send):
                publish_site_data(root, source, {'host': 'example.invalid', 'user': 'map', 'known_hosts': 'synthetic public host key', 'place_annotations': annotations}, '2026-10-05T08:00:00Z')
            self.assertEqual(len(calls), 1)
            self.assertIn('StrictHostKeyChecking=yes', calls[0][0])
            self.assertEqual(calls[0][0][-1], 'publish-map')
            self.assertEqual(list(root.iterdir()), [source])
            with patch.dict('os.environ', {'MAP_DEPLOY_KEY': 'synthetic-secret'}), patch('nbmap.cloud.command', return_value=subprocess.CompletedProcess([], 0, stdout=b'Published public map wrong', stderr=b'')):
                with self.assertRaisesRegex(ValueError, '回执'):
                    publish_site_data(root, source, {'host': 'example.invalid', 'user': 'map', 'known_hosts': 'synthetic public host key'}, '2026-10-05T08:00:00Z')
            self.assertEqual(list(root.iterdir()), [source])

    def test_publisher_hash_matches_the_real_receiver_protocol(self):
        from unittest.mock import patch
        from nbmap.cloud import publish_site_data
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sender = root / 'sender'
            sender.mkdir()
            target = root / 'server/data/dataset.json'
            source = sender / 'source.json'
            source.write_text(json.dumps(self.dataset))
            def receive(args, **kwargs):
                result = subprocess.run([sys.executable, 'scripts/receive-public-map.py', '--target', str(target)], input=kwargs['data'], capture_output=True)
                self.assertEqual(result.returncode, 0)
                return result
            with patch.dict('os.environ', {'MAP_DEPLOY_KEY': 'synthetic-secret'}), patch('nbmap.cloud.command', side_effect=receive):
                receipt = publish_site_data(sender, source, {'host': 'example.invalid', 'user': 'map', 'known_hosts': 'synthetic public host key'}, '2026-10-05T08:00:00Z')
            self.assertEqual(receipt['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(json.loads(target.read_bytes())['updated_at'], '2026-10-05T08:00:00Z')
            self.assertEqual(list(sender.iterdir()), [source])


if __name__ == '__main__':
    unittest.main()

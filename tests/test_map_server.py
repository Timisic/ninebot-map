import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nbmap.map_server import ASSETS, create_server
from nbmap.viewer_resources import viewer_resources, WEB_ROOT
from nbmap.__main__ import main
from nbmap.archive import RideArchive

FIXTURE = Path(__file__).parent / 'fixtures' / 'synthetic-map.json'


class MapServerTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(FIXTURE, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = f'127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path='/', method='GET', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.headers), response.read()
        connection.close()
        return result

    def test_all_allowed_assets_and_snapshot_are_available(self):
        for route in ASSETS:
            status, headers, body = self.request(route)
            self.assertEqual(status, 200, route)
            self.assertGreater(len(body), 0)
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        status, headers, body = self.request('/dataset.json')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body)['summary']['ride_count'], 12)
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_local_font_and_license_have_correct_types_and_bytes(self):
        for filename, content_type in [('fonts/smiley-sans/SmileySans-Oblique.woff2', 'font/woff2'),
                                       ('fonts/smiley-sans/LICENSE', 'text/plain; charset=utf-8')]:
            status, headers, body = self.request('/' + filename)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], content_type)
            self.assertEqual(body, (WEB_ROOT / filename).read_bytes())

    def test_only_literal_allowed_routes_are_served(self):
        for path in ['/.private/tokens.json', '/tokens.json', '/data/', '/../README.md', '/%2e%2e/.private/tokens.json', '//dataset.json', '/dataset.json?x=1', '/web/app.mjs', '/vendor/leaflet/../../README.md']:
            self.assertEqual(self.request(path)[0], 404, path)
        self.assertEqual(self.request('/')[0], 200)

    def test_versioned_assets_are_exact_aliases_and_keep_relative_imports(self):
        snapshot = viewer_resources(WEB_ROOT)
        prefix = f'/assets/{snapshot.bundle_hash}/'
        html = self.request('/')[2].decode()
        entries = re.findall(r'(?:src|href)="(\./assets/[^\"]+)"', html)
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(self.request(entry[1:])[0], 200, entry)
        for filename, (body, _) in snapshot.files.items():
            if filename.startswith('assets/'):
                self.assertEqual(self.request('/' + filename)[2], body)
        self.assertIn(b"from './model.mjs'", self.request(prefix + 'app.mjs')[2])
        self.assertEqual(self.request(prefix + 'vendor/leaflet/images/marker-icon.png')[2], self.request('/vendor/leaflet/images/marker-icon.png')[2])
        for path in [prefix + 'styles.css?version=1', '/assets/' + '0' * 64 + '/styles.css',
                     prefix + '../styles.css', prefix + 'index.html', prefix + 'dataset.json',
                     prefix + '.private/tokens.json', prefix + 'vendor/leaflet/../../README.md',
                     '/assets/' + snapshot.bundle_hash.upper() + '/styles.css']:
            self.assertEqual(self.request(path)[0], 404, path)

    def test_host_origin_and_cross_site_requests_are_rejected(self):
        for headers in [{'Host': 'evil.example'}, {'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}]:
            self.assertEqual(self.request('/dataset.json', headers=headers)[0], 403)
        self.assertEqual(self.request('/dataset.json', headers={'Origin': 'http://' + self.host})[0], 200)

    def test_unsupported_methods_and_head(self):
        for method in ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE', 'CONNECT']:
            self.assertEqual(self.request('/dataset.json', method)[0], 405)
        self.assertEqual(self.request('/', 'HEAD')[0], 200)
        self.assertEqual(self.request('/', 'HEAD')[2], b'')

    def test_running_server_reloads_valid_updates_and_retains_snapshot_on_invalid_update(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_bytes(FIXTURE.read_bytes())
            server = create_server(path, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                dataset = json.loads(FIXTURE.read_text())
                dataset['dataset_id'] = 'synthetic-update'
                path.write_text(json.dumps(dataset))
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', '/dataset.json')
                response = connection.getresponse()
                etag = response.getheader('ETag')
                self.assertEqual(json.loads(response.read())['dataset_id'], 'synthetic-update')
                connection.close()
                path.write_text('{}')
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', '/dataset.json')
                response = connection.getresponse()
                self.assertEqual(response.getheader('ETag'), etag)
                self.assertEqual(json.loads(response.read())['dataset_id'], 'synthetic-update')
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_generation_specific_path_follows_latest_atomic_pointer(self):
        from nbmap.storage import write_json
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'prepared'
            dataset = json.loads(FIXTURE.read_text())
            write_json(parent / 'old/dataset.json', dataset)
            server = create_server(parent / 'old/dataset.json', 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                dataset['dataset_id'] = 'synthetic-new-generation'
                write_json(parent / 'new/dataset.json', dataset)
                write_json(parent / 'latest.json', {'directory': 'new'})
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                connection.request('GET', '/dataset.json')
                self.assertEqual(json.loads(connection.getresponse().read())['dataset_id'], 'synthetic-new-generation')
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_invalid_input_rejected_before_serving(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for raw in ['{', '{}', json.dumps({'format': 'wrong'})]:
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    create_server(path, 0)

    def test_cli_map_branches_before_credentials_or_client(self):
        with patch('nbmap.__main__.Client', side_effect=AssertionError('must not construct client')), patch('nbmap.__main__.private_dir', side_effect=AssertionError('must not read private directory')), patch('nbmap.map_server.serve_map', return_value=0) as serve:
            self.assertEqual(main(['map', '--dataset', str(FIXTURE), '--no-open', '--port', '0']), 0)
            serve.assert_called_once_with(FIXTURE, 0, True)


class MapSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.config = self.root / 'config'
        self.config.mkdir()
        self.serve = self.enterContext(patch('nbmap.map_server.serve_map', return_value=0))
        self.enterContext(patch('nbmap.__main__.Client', side_effect=AssertionError('no account access')))
        self.enterContext(patch('nbmap.__main__.private_dir', side_effect=AssertionError('no storage creation')))
        self.prepare = self.enterContext(patch('nbmap.__main__.prepare_configured', side_effect=AssertionError('auto must not prepare')))
        self.addCleanup(self.temp.cleanup)

    def dataset(self, serial):
        path = RideArchive.for_vehicle(self.data, serial).path / 'prepared' / 'dataset.json'
        path.parent.mkdir(parents=True)
        path.write_bytes(FIXTURE.read_bytes())
        return path

    def run_map(self, *options):
        self.assertEqual(main(['--data-dir', str(self.data), '--config-dir', str(self.config), 'map', '--no-open', *options]), 0)
        return self.serve.call_args.args[0]

    def test_selected_vehicle_wins_over_other_prepared_data(self):
        self.dataset('other')
        selected = self.dataset('selected')
        (self.config / 'preferences.json').write_text(json.dumps({'sn': 'selected'}))
        self.assertEqual(self.run_map(), selected)
        self.serve.assert_called_once_with(selected, 8765, True)

    def test_unique_prepared_dataset_opens_without_preferences(self):
        selected = self.dataset('unique')
        RideArchive.for_vehicle(self.data, 'not-prepared').path.mkdir()
        self.assertEqual(self.run_map(), selected)

    def test_empty_ambiguous_and_missing_selected_require_prepared_data(self):
        with self.assertRaises(ValueError):
            self.run_map()
        self.dataset('one')
        self.dataset('two')
        with self.assertRaises(ValueError):
            self.run_map()
        (self.config / 'preferences.json').write_text(json.dumps({'sn': 'missing'}))
        with self.assertRaises(ValueError):
            self.run_map()

    def test_explicit_dataset_does_not_read_preferences(self):
        selected = self.dataset('one')
        (self.config / 'preferences.json').write_text('{broken')
        self.assertEqual(self.run_map('--dataset', str(selected)), selected)

    def test_latest_is_strict_and_preserves_prepare_behavior(self):
        with self.assertRaises(ValueError):
            self.run_map('--latest')
        selected = self.dataset('one')
        self.assertEqual(self.run_map('--latest'), selected)
        selected.unlink()
        self.prepare.side_effect = None
        self.prepare.return_value = selected.parent
        self.assertEqual(self.run_map('--latest'), selected)
        self.prepare.assert_called_once()

    def test_symlinked_data_directory_remains_readable(self):
        selected = self.dataset('one')
        destination = self.root / 'Application Support' / 'Ninebot Map' / 'data'
        destination.parent.mkdir(parents=True)
        self.data.rename(destination)
        self.data.symlink_to(destination, target_is_directory=True)
        self.assertEqual(self.run_map(), selected)

    def test_source_options_are_mutually_exclusive(self):
        for options in [('--empty', '--latest'), ('--empty', '--dataset', str(FIXTURE)), ('--latest', '--dataset', str(FIXTURE))]:
            with self.assertRaises(SystemExit) as raised:
                self.run_map(*options)
            self.assertEqual(raised.exception.code, 2)


if __name__ == '__main__':
    unittest.main()

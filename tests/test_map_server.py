import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nbmap.map_server import ASSETS, create_server
from nbmap.__main__ import main

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

    def test_only_literal_allowed_routes_are_served(self):
        for path in ['/.private/tokens.json', '/tokens.json', '/data/', '/../README.md', '/%2e%2e/.private/tokens.json', '//dataset.json', '/dataset.json?x=1', '/web/app.mjs', '/vendor/leaflet/../../README.md']:
            self.assertEqual(self.request(path)[0], 404, path)
        self.assertEqual(self.request('/')[0], 200)

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
            self.assertEqual(main(['map', '--no-open', '--port', '0']), 0)
            serve.assert_called_once_with(None, 0, True)


if __name__ == '__main__':
    unittest.main()

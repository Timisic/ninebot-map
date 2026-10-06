import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from nbmap.public_map import export_site, public_dataset, publish_dataset
from nbmap.public_updates import (API_VERSION, COOLDOWN_US, PublicUpdates, RUN_PREFIX,
                                 WORKER_STEP, _github_request)

FIXTURE = Path(__file__).parent / 'fixtures/synthetic-map.json'
ORIGIN = 'https://map.example.invalid'
CONTRACT = {'phase', 'can_request', 'requested_at', 'next_allowed_at'}


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.dispatch_status = 200
        self.dispatch_body = {'workflow_run_id': 42, 'html_url': 'https://private.invalid/PRIVATE_SENTINEL'}
        self.dispatch_error = None
        self.run = None
        self.listed_runs = []
        self.jobs = []
        self.entered = threading.Event()
        self.release = None

    def __call__(self, settings, method, path, body=None):
        self.calls.append((method, path, body))
        if method == 'POST':
            self.entered.set()
            if self.release:
                self.release.wait(5)
            if self.dispatch_error:
                raise self.dispatch_error
            return self.dispatch_status, json.dumps(self.dispatch_body).encode()
        if '/jobs?' in path:
            return 200, json.dumps({'total_count': len(self.jobs), 'jobs': self.jobs}).encode()
        if '/workflows/sync.yml/runs?' in path:
            return 200, json.dumps({'workflow_runs': self.listed_runs}).encode()
        if path.endswith('/actions/runs/42'):
            return 200, json.dumps(self.run).encode()
        raise AssertionError('Unexpected GitHub request')

    def payload(self):
        return json.loads(next(body for method, _, body in reversed(self.calls) if method == 'POST'))

    def set_run(self, request_id, status='completed', conclusion='success'):
        self.run = {'id': 42, 'display_title': RUN_PREFIX + request_id, 'event': 'workflow_dispatch',
                    'head_branch': 'main', 'path': '.github/workflows/sync.yml',
                    'status': status, 'conclusion': conclusion, 'run_attempt': 1}
        self.listed_runs = [self.run]
        self.jobs = [{'name': 'sync', 'run_id': 42, 'status': 'completed', 'conclusion': 'success',
                      'steps': [{'name': WORKER_STEP, 'status': 'completed', 'conclusion': 'success'}]}]


class PublicUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 10, 6, tzinfo=timezone.utc)
        self.source = json.loads(FIXTURE.read_text())
        self.dataset = public_dataset(self.source, '2026-10-05T00:00:00Z')
        self.dataset_path = self.root / 'dataset.json'
        publish_dataset(self.dataset, self.dataset_path)
        self.config = self.root / 'update.json'
        self.config.write_text(json.dumps({'repository': 'owner/private-sync', 'origin': ORIGIN}))
        self.credentials = self.root / 'credentials'
        self.credentials.mkdir()
        (self.credentials / 'github-token').write_text('github_pat_SYNTHETIC')
        self.state = self.root / 'state/update.sqlite3'
        self.github = FakeGitHub()

    def broker(self, **kwargs):
        updates = PublicUpdates(self.config, self.state, self.dataset_path, clock=lambda: self.now,
                                transport=self.github, credentials_dir=self.credentials,
                                start_observer=kwargs.pop('start_observer', False), **kwargs)
        self.addCleanup(updates.close)
        return updates

    def admitted_run(self, updates, **kwargs):
        result = updates.request_update()
        self.assertEqual(result.status, 202)
        self.github.set_run(self.github.payload()['inputs']['public_request_id'], **kwargs)
        return result

    def newer_dataset(self):
        newer = copy.deepcopy(self.dataset)
        newer['updated_at'] = '2026-10-06T00:01:00Z'
        publish_dataset(newer, self.dataset_path)

    def test_strict_twelve_hour_boundary_and_fixed_dispatch(self):
        updates = self.broker()
        self.assertEqual(updates.snapshot(), {'phase': 'idle', 'can_request': True, 'requested_at': None, 'next_allowed_at': None})
        first = updates.request_update()
        self.assertEqual(first.status, 202)
        self.assertEqual(first.snapshot, {'phase': 'queued', 'can_request': False,
                                       'requested_at': '2026-10-06T00:00:00Z', 'next_allowed_at': '2026-10-06T12:00:00Z'})
        payload = self.github.payload()
        self.assertEqual(set(payload), {'ref', 'inputs'})
        self.assertEqual(payload['ref'], 'main')
        self.assertEqual(payload['inputs']['force'], True)
        self.assertEqual(payload['inputs']['publish_only'], False)
        self.assertRegex(payload['inputs']['public_request_id'], r'^[a-f0-9-]{36}$')
        self.now += timedelta(microseconds=COOLDOWN_US)
        self.assertFalse(updates.snapshot()['can_request'])
        self.assertEqual(updates.request_update().status, 429)
        self.assertEqual(len([c for c in self.github.calls if c[0] == 'POST']), 1)
        self.now += timedelta(microseconds=1)
        self.assertTrue(updates.snapshot()['can_request'])
        self.assertEqual(updates.request_update().status, 202)
        self.assertEqual(len([c for c in self.github.calls if c[0] == 'POST']), 2)

    def test_concurrent_requests_reserve_once_before_network(self):
        updates = self.broker()
        self.github.release = threading.Event()
        with ThreadPoolExecutor(max_workers=20) as pool:
            first = pool.submit(updates.request_update)
            self.assertTrue(self.github.entered.wait(2))
            others = [pool.submit(updates.request_update) for _ in range(30)]
            results = [future.result(timeout=5) for future in others]
            self.assertEqual([result.status for result in results], [429] * 30)
            self.github.release.set()
            self.assertEqual(first.result(timeout=5).status, 202)
        self.assertEqual(len([call for call in self.github.calls if call[0] == 'POST']), 1)

    def test_restart_preserves_clock_and_adopts_uncertain_dispatch(self):
        updates = self.broker()
        self.admitted_run(updates, status='in_progress', conclusion=None)
        identifier = self.github.payload()['inputs']['public_request_id']
        updates._update(identifier, phase='dispatching')
        updates.close()
        restarted = self.broker()
        self.assertEqual(restarted.snapshot()['phase'], 'unknown')
        self.assertEqual(restarted.request_update().status, 429)
        restarted._reconcile()
        self.assertEqual(restarted.snapshot()['phase'], 'running')
        self.assertEqual(len([call for call in self.github.calls if call[0] == 'POST']), 1)

    def test_timeout_reconciles_by_uuid_without_redispatch(self):
        self.github.dispatch_error = TimeoutError('PRIVATE_SENTINEL')
        updates = self.broker()
        result = updates.request_update()
        self.assertEqual(result.status, 202)
        self.assertEqual(result.snapshot['phase'], 'unknown')
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result.snapshot))
        self.github.set_run(self.github.payload()['inputs']['public_request_id'])
        self.newer_dataset()
        updates._reconcile()
        self.assertEqual(updates.snapshot()['phase'], 'succeeded')
        self.assertEqual(len([call for call in self.github.calls if call[0] == 'POST']), 1)
        self.assertIn('event=workflow_dispatch', self.github.calls[1][1])

    def test_legacy_empty_or_malformed_acknowledgements_are_uncertain(self):
        for status, body in [(204, None), (200, {'workflow_run_id': True}), (200, {'html_url': 'PRIVATE_SENTINEL'}), (503, {'message': 'PRIVATE_SENTINEL'})]:
            with self.subTest(status=status, body=body):
                self.state = self.root / str(len(self.github.calls)) / 'state.sqlite3'
                self.github.dispatch_status, self.github.dispatch_body = status, body
                updates = self.broker()
                result = updates.request_update()
                self.assertEqual(result.status, 202)
                self.assertEqual(result.snapshot['phase'], 'unknown')
                self.assertEqual(updates.request_update().status, 429)
                self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result.snapshot))

    def test_invalid_json_acknowledgement_never_retries_dispatch(self):
        updates = self.broker()
        updates.transport = lambda *args: (200, b'invalid JSON PRIVATE_SENTINEL')
        result = updates.request_update()
        self.assertEqual(result.status, 202)
        self.assertEqual(result.snapshot['phase'], 'unknown')
        self.assertEqual(updates.request_update().status, 429)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result.snapshot))

    def test_rejected_dispatch_consumes_interval(self):
        self.github.dispatch_status = 422
        self.github.dispatch_body = {'message': 'github_pat_SYNTHETIC PRIVATE_SENTINEL'}
        updates = self.broker()
        result = updates.request_update()
        self.assertEqual(result.status, 502)
        self.assertEqual(result.snapshot['phase'], 'failed')
        self.assertEqual(updates.request_update().status, 429)
        self.assertEqual(set(result.snapshot), CONTRACT)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result.snapshot))

    def test_workflow_failure_and_skipped_collection_never_succeed(self):
        for outcome in ('workflow_failed', 'sync_skipped', 'worker_skipped', 'worker_missing'):
            with self.subTest(outcome=outcome):
                self.state = self.root / outcome / 'state.sqlite3'
                updates = self.broker()
                self.admitted_run(updates)
                self.newer_dataset()
                if outcome == 'workflow_failed':
                    self.github.run['conclusion'] = 'failure'
                elif outcome == 'sync_skipped':
                    self.github.jobs[0]['conclusion'] = 'skipped'
                elif outcome == 'worker_skipped':
                    self.github.jobs[0]['steps'][0]['conclusion'] = 'skipped'
                else:
                    self.github.jobs[0]['steps'] = []
                updates._reconcile()
                self.assertEqual(updates.snapshot()['phase'], 'failed')

    def test_green_run_requires_newer_valid_served_file(self):
        for outcome in ('stale', 'invalid', 'older'):
            with self.subTest(outcome=outcome):
                self.state = self.root / outcome / 'state.sqlite3'
                self.dataset_path.write_text(json.dumps(self.dataset))
                updates = self.broker()
                self.admitted_run(updates)
                candidate = copy.deepcopy(self.dataset)
                if outcome == 'invalid':
                    candidate.update(updated_at='2026-10-06T00:01:00Z', private='PRIVATE_SENTINEL')
                elif outcome == 'older':
                    candidate['updated_at'] = '2026-10-04T00:00:00Z'
                self.dataset_path.write_text(json.dumps(candidate))
                updates._reconcile()
                self.assertEqual(updates.snapshot()['phase'], 'unknown')

    def test_success_records_digest_of_actual_served_dataset(self):
        updates = self.broker()
        self.admitted_run(updates)
        self.newer_dataset()
        updates._reconcile()
        self.assertEqual(updates.snapshot()['phase'], 'succeeded')
        record = updates._record()
        self.assertEqual(record.dataset_sha256, hashlib.sha256(self.dataset_path.read_bytes()).hexdigest())
        self.assertGreater(record.dataset_us, record.baseline_us)
        before = len(self.github.calls)
        for _ in range(10):
            self.assertEqual(updates.snapshot()['phase'], 'succeeded')
        self.assertEqual(len(self.github.calls), before)

    def test_wrong_run_and_duplicate_uuid_are_not_success(self):
        updates = self.broker()
        self.admitted_run(updates)
        self.newer_dataset()
        self.github.run['display_title'] = 'Unrelated run'
        with self.assertRaises(ValueError):
            updates._reconcile()
        self.assertEqual(updates.snapshot()['phase'], 'queued')
        identifier = self.github.payload()['inputs']['public_request_id']
        updates._update(identifier, phase='unknown')
        self.github.set_run(identifier)
        self.github.listed_runs.append({**self.github.run, 'id': 43})
        updates._update(identifier, phase='unknown', run_id=None)
        with sqlite3.connect(self.state) as connection:
            connection.execute('UPDATE latest SET run_id=NULL')
        with self.assertRaises(ValueError):
            updates._reconcile()
        self.assertEqual(updates.snapshot()['phase'], 'unknown')

    def test_observation_window_is_bounded_and_retains_cooldown(self):
        updates = self.broker()
        self.admitted_run(updates, status='in_progress', conclusion=None)
        self.now += timedelta(hours=7)
        before = len(self.github.calls)
        updates._reconcile()
        self.assertEqual(len(self.github.calls), before)
        self.assertEqual(updates.snapshot()['phase'], 'unknown')
        self.assertEqual(updates.request_update().status, 429)

    def test_missing_configuration_or_credential_is_unavailable(self):
        self.config.unlink()
        updates = self.broker()
        self.assertEqual(updates.request_update().status, 503)
        self.assertEqual(updates.snapshot(), {'phase': 'unavailable', 'can_request': False, 'requested_at': None, 'next_allowed_at': None})
        self.assertFalse(self.state.exists())
        self.assertEqual(self.github.calls, [])
        self.config.write_text(json.dumps({'repository': 'owner/private-sync', 'origin': ORIGIN}))
        (self.credentials / 'github-token').unlink()
        self.assertEqual(self.broker().request_update().status, 503)

    def test_corrupt_existing_storage_fails_closed_without_replacement(self):
        self.state.parent.mkdir()
        for raw in (b'', b'corrupt database PRIVATE_SENTINEL'):
            with self.subTest(raw=raw):
                self.state.write_bytes(raw)
                updates = self.broker()
                self.assertEqual(updates.request_update().status, 503)
                self.assertEqual(self.state.read_bytes(), raw)
                self.assertEqual(self.github.calls, [])
        self.state.unlink()
        updates = self.broker()
        self.admitted_run(updates)
        with sqlite3.connect(self.state) as connection:
            connection.execute('UPDATE latest SET accepted_us=-1')
        self.assertEqual(updates.request_update().status, 503)
        self.assertEqual(updates.snapshot()['phase'], 'unavailable')

    def test_second_broker_cannot_own_same_database(self):
        first = self.broker()
        second = self.broker()
        self.assertEqual(first.snapshot()['phase'], 'idle')
        self.assertEqual(second.request_update().status, 503)
        first.close()
        self.assertEqual(self.broker().snapshot()['phase'], 'idle')

    def test_daemon_adopts_queued_run_and_closes_without_browser(self):
        updates = self.broker()
        self.admitted_run(updates)
        self.newer_dataset()
        updates.close()
        original = self.github.__call__
        completed = threading.Event()

        def observe(settings, method, path, body=None):
            reply = original(settings, method, path, body)
            if '/jobs?' in path:
                completed.set()
            return reply

        restarted = PublicUpdates(self.config, self.state, self.dataset_path, clock=lambda: self.now,
                                  transport=observe, credentials_dir=self.credentials)
        self.addCleanup(restarted.close)
        self.assertTrue(completed.wait(3))
        restarted.close()
        self.assertFalse(restarted._observer.is_alive())
        self.assertEqual(restarted._record().phase, 'succeeded')

    def test_github_transport_pins_version_and_does_not_follow_response_urls(self):
        updates = self.broker()

        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, size):
                return b'{"workflow_run_id":42}'

        with patch('nbmap.public_updates.build_opener') as build:
            build.return_value.open.return_value = Response()
            status, body = _github_request(updates.settings, 'POST', '/repos/owner/private-sync/actions/workflows/sync.yml/dispatches', b'{}')
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.github.com/repos/owner/private-sync/actions/workflows/sync.yml/dispatches')
            self.assertEqual(request.get_header('X-github-api-version'), API_VERSION)
            self.assertEqual(build.return_value.open.call_args.kwargs['timeout'], 10)
            self.assertEqual(status, 200)
            self.assertEqual(body, b'{"workflow_run_id":42}')
            self.assertIsNone(build.call_args.args[0].redirect_request(None, None, None, None, None, None))

    def test_http_admission_and_fixed_allowlist(self):
        spec = importlib.util.spec_from_file_location('along_public_server', 'scripts/serve-public-map.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        site = export_site(self.source, self.root / 'public')
        updates = self.broker()
        server = module.create_server(site, 0, self.dataset_path, updates=updates)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(path='/api/update', method='POST', body='{}', headers=None):
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            client.request(method, path, body=body, headers=headers if headers is not None else {'Origin': ORIGIN, 'Content-Type': 'application/json', 'Sec-Fetch-Site': 'same-origin'})
            response = client.getresponse()
            result = response.status, dict(response.headers), response.read()
            client.close()
            if path == '/api/update' and method != 'HEAD':
                self.assertEqual(set(json.loads(result[2])), CONTRACT)
                self.assertEqual(result[1]['Cache-Control'], 'no-store')
                self.assertNotIn('Access-Control-Allow-Origin', result[1])
                self.assertNotIn(b'PRIVATE_SENTINEL', result[2])
                self.assertNotIn(b'github_pat_SYNTHETIC', result[2])
            return result

        self.assertEqual(request(method='GET', body=None)[0], 200)
        self.assertEqual(request(method='HEAD', body=None)[2], b'')
        for headers in ({'Content-Type': 'application/json'}, {'Origin': 'https://evil.invalid', 'Content-Type': 'application/json'}, {'Origin': ORIGIN, 'Content-Type': 'application/json', 'Sec-Fetch-Site': 'cross-site'}, {'Origin': ORIGIN, 'Content-Type': 'application/json', 'Sec-Fetch-Site': 'same-site'}):
            self.assertEqual(request(headers=headers)[0], 403)
        self.assertEqual(request(headers={'Origin': ORIGIN, 'Content-Type': 'text/plain'})[0], 415)
        for body in ('[]', '{"force":true}', 'not json', ''):
            self.assertEqual(request(body=body)[0], 400)
        self.assertEqual(request(body=' ' * 65)[0], 413)
        self.assertEqual(request(headers={'Origin': ORIGIN, 'Content-Type': 'application/json', 'Transfer-Encoding': 'chunked'})[0], 400)
        self.assertEqual(self.github.calls, [])
        self.assertEqual(request()[0], 202)
        self.assertEqual(request()[0], 429)
        for method in ('PUT', 'PATCH', 'DELETE', 'OPTIONS'):
            self.assertEqual(request(method=method)[0], 405)
        for path in ('/api/update?force=true', '/api/update/', '/dataset.json', '/scripts/serve-public-map.py', '/.private/tokens.json'):
            self.assertEqual(request(path=path)[0], 405)
        for path in ('/state/update.sqlite3', '/api/update/', '/code/nbmap/public_updates.py', '/etc/along-map/github-token', '/.private/tokens.json'):
            self.assertEqual(request(path=path, method='GET', body=None)[0], 404)
        before = len(self.github.calls)
        for _ in range(5):
            self.assertEqual(request(method='GET', body=None)[0], 200)
        self.assertEqual(len(self.github.calls), before)

    def test_http_missing_configuration_returns_frozen_contract(self):
        spec = importlib.util.spec_from_file_location('along_disabled_server', 'scripts/serve-public-map.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        site = export_site(self.source, self.root / 'public')
        server = module.create_server(site, 0, self.dataset_path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for method in ('GET', 'POST'):
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            client.request(method, '/api/update', body='{}', headers={'Content-Type': 'application/json', 'Origin': ORIGIN})
            response = client.getresponse()
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(response.read()), {'phase': 'unavailable', 'can_request': False, 'requested_at': None, 'next_allowed_at': None})
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
            client.close()

    def test_bundle_contains_runtime_and_example_without_state_or_credential(self):
        source = self.root / 'source.json'
        source.write_text(json.dumps(self.source))
        output = self.root / 'bundle'
        result = subprocess.run([sys.executable, 'scripts/build-site-bundle.py', '--dataset', str(source), '--output', str(output)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        manifest = json.loads((output / 'manifest.json').read_bytes())
        self.assertIn('code/nbmap/public_updates.py', manifest['files'])
        self.assertIn('map-update.example.json', manifest['files'])
        self.assertIn('map-site.service', manifest['files'])
        self.assertFalse(any('state.sqlite3' in path or 'github-token' in path for path in manifest['files']))
        for path, expected in manifest['files'].items():
            actual = (output / path).read_bytes()
            self.assertEqual(hashlib.sha256(actual).hexdigest(), expected['sha256'])


if __name__ == '__main__':
    unittest.main()

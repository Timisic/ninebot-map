"""Synthetic cloud state, merge, due-time and image fixtures. No production account."""
import copy
import hashlib
import io
import json
import tempfile
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from PIL import Image

from nbmap.acquisition import collect_month
from nbmap.archive import RideArchive
from nbmap.cloud import execute_worker, is_cloud_due, readme_image, publish_image, public_fingerprint, CommandFailure, IMAGE_PATH, manage, deploy_code
from nbmap.cloud_state import checkpoint, import_archives, restore, seal, unseal
from nbmap.dataset import prepare
from nbmap.storage import read_json, write_json
from nbmap.track_image import render_tracks

NOW = datetime(2026, 10, 4, 3, tzinfo=timezone.utc)


class Source:
    def __init__(self, ids=('one',), simple=False, fail=False):
        self.ids, self.simple, self.fail = ids, simple, fail
        self.requests = []
    def month(self, sn, month, page):
        self.requests.append(('month', month))
        if self.fail:
            raise RuntimeError('synthetic upstream outage')
        return {'times': len(self.ids), 'total_mileages': len(self.ids), 'list': [
            {'travel_id': rid + month, 'mileages': 1, 'start_time': 1791080000} for rid in self.ids]}
    def detail(self, sn, rid):
        self.requests.append(('detail', rid))
        return {'trail': '116,39,1;116.001,39.001,2' if self.simple else '116,39,1;116.0005,39.0005,2;116.001,39.001,3',
                'is_show_simple_point': self.simple, 'mileages': 1, 'duration': 120, 'start_time': 1791080000}


class CloudTests(unittest.TestCase):
    def setUp(self):
        notification = patch('nbmap.schedule.notify')
        self.notification = notification.start()
        self.addCleanup(notification.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config, self.data = self.root / 'sessions', self.root / 'data'
        write_json(self.config / 'config.json', {'device_id': 'synthetic-device'})
        write_json(self.config / 'tokens.json', {'access_token': 'synthetic-secret', 'refresh_token': 'synthetic-refresh'})
        write_json(self.config / 'preferences.json', {'sn': 'synthetic-sn'})
        write_json(self.config / 'schedule.json', {'interval_days': 10, 'enabled': True})
        self.archive = RideArchive.for_vehicle(self.data, 'synthetic-sn')
        collect_month(Source(), 'synthetic-sn', '202609', self.archive)
        prepare(self.archive, map_from='2026-01-01')
        self.key = Fernet.generate_key()
        self.session = {'revision': NOW.isoformat(), 'files': {name: read_json(self.config / name)
            for name in ('config.json', 'tokens.json', 'preferences.json')}}
        self.payload = checkpoint(self.config, self.data, self.session['revision'])
    def tearDown(self):
        self.temp.cleanup()

    def test_site_failure_keeps_success_clock_and_retries_publication(self):
        from nbmap.cloud import worker
        self.payload['files']['sessions/schedule-state.json'] = {'status': 'success', 'last_success': NOW.isoformat(), 'publication_pending': False}
        for failure, publish_only in ((True, False), (False, False), (True, True), (False, True)):
            with self.subTest(failure=failure, publish_only=publish_only):
                root = self.root / f'worker-{failure}-{publish_only}'
                root.mkdir()
                write_json(root / 'sync-settings.json', {'interval_days': 10, 'publish_repos': [], 'site': {'host': 'example.invalid'}})
                (root / 'github-known-hosts').write_text('synthetic public host key')
                updated = copy.deepcopy(self.payload)
                updated['files']['sessions/schedule-state.json'] = {'status': 'success', 'last_success': NOW.isoformat(), 'publication_pending': True}
                def git(args, **kwargs):
                    if args[:2] == ['git', 'worktree']:
                        (root / 'work/state-publish').mkdir(parents=True)
                    return subprocess.CompletedProcess(args, 0, stdout=seal(self.payload, self.key) if args[:2] == ['git', 'show'] else b'', stderr=b'')
                log = io.StringIO()
                with patch.dict('os.environ', {'CLOUD_STATE_KEY': self.key.decode(), 'NINEBOT_SESSION': 'not JSON' if publish_only else json.dumps(self.session), 'SYNC_FORCE': 'false', 'SYNC_PUBLISH_ONLY': str(publish_only).lower()}), patch('nbmap.cloud.command', side_effect=git), patch('nbmap.cloud.execute_worker', return_value=(updated, 0, [self.archive.path / 'prepared/dataset.json'])) as executor, patch('nbmap.cloud.publish_image'), patch('nbmap.cloud.publish_site_data', return_value={'status':'published','sha256':'a' * 64,'updated_at':NOW.isoformat()}, side_effect=RuntimeError('PRIVATE_SENTINEL') if failure else None), redirect_stdout(log):
                    self.assertEqual(worker(root), 1 if failure else 0)
                state = unseal((root / 'work/state-publish/state.enc').read_bytes(), self.key)['files']['sessions/schedule-state.json']
                self.assertEqual(state['last_success'], NOW.isoformat())
                self.assertEqual(state['publication_pending'], failure)
                self.assertEqual('site_published_at' in state, not failure)
                self.assertNotIn('PRIVATE_SENTINEL', log.getvalue())
                self.assertEqual(executor.call_args.kwargs['publish_only'], publish_only)
                if publish_only:
                    self.assertIsNone(executor.call_args.args[2])
                receipt = json.loads(next(line.split('Publication receipt: ', 1)[1] for line in log.getvalue().splitlines() if line.startswith('Publication receipt: ')))
                self.assertEqual(receipt['mode'], 'publish_only' if publish_only else 'sync')
                self.assertEqual(receipt['last_success_before'], receipt['last_success_after'])
                self.assertEqual(receipt['publication_pending'], failure)

    def test_due_collection_automatically_publishes_site_and_keeps_png_path(self):
        from nbmap.cloud import worker
        root = self.root / 'normal-pipeline'
        root.mkdir()
        site = {'host': 'example.invalid', 'user': 'map', 'port': 22, 'known_hosts': 'synthetic public host key'}
        images = [{'repo': 'fixture/map', 'branch': 'main'}, {'repo': 'fixture/profile', 'branch': 'main'}]
        write_json(root / 'sync-settings.json', {'interval_days': 10, 'publish_repos': images, 'site': site})
        (root / 'github-known-hosts').write_text('synthetic public host key')
        previous = (NOW - timedelta(days=11)).isoformat()
        self.payload['files']['sessions/schedule-state.json'] = {'status': 'success', 'last_success': previous, 'publication_pending': False}
        source = Source()
        target = self.root / 'synthetic-server/data/dataset.json'
        def transport(args, **kwargs):
            if args[0] == 'ssh':
                return subprocess.run([sys.executable, 'scripts/receive-public-map.py', '--target', str(target)], input=kwargs['data'], capture_output=True)
            if args[:2] == ['git', 'worktree']:
                (root / 'work/state-publish').mkdir(parents=True)
            return subprocess.CompletedProcess(args, 0, stdout=seal(self.payload, self.key) if args[:2] == ['git', 'show'] else b'', stderr=b'')
        def collect(*args, **kwargs):
            return execute_worker(*args, **{**kwargs, 'source': source, 'now': NOW})
        with patch.dict('os.environ', {'CLOUD_STATE_KEY': self.key.decode(), 'NINEBOT_SESSION': json.dumps(self.session), 'MAP_DEPLOY_KEY': 'synthetic-key', 'SYNC_FORCE': 'false', 'SYNC_PUBLISH_ONLY': 'false'}), patch('nbmap.cloud.command', side_effect=transport), patch('nbmap.cloud.execute_worker', side_effect=collect), patch('nbmap.cloud.publish_image') as png, redirect_stdout(io.StringIO()):
            self.assertEqual(worker(root), 0)
        self.assertGreater(len(source.requests), 0)
        self.assertEqual(png.call_args.args[2], images)
        state = unseal((root / 'work/state-publish/state.enc').read_bytes(), self.key)['files']['sessions/schedule-state.json']
        self.assertEqual(state['last_success'], NOW.isoformat())
        self.assertFalse(state['publication_pending'])
        self.assertEqual(read_json(target)['updated_at'], NOW.isoformat())
        self.assertEqual(state['site_sha256'], hashlib.sha256(target.read_bytes()).hexdigest())

    def test_authenticated_compact_roundtrip_and_no_plaintext(self):
        blob = seal(self.payload, self.key)
        self.assertNotIn(b'synthetic-secret', blob)
        self.assertNotIn(b'"longitude"', blob)
        self.assertEqual(unseal(blob, self.key), self.payload)
        with self.assertRaises(ValueError):
            unseal(blob[:-2] + b'xx', self.key)
        self.assertTrue(all('/raw/' not in p and '/reports/' not in p for p in self.payload['files']))
        restored = self.root / 'restored'
        restore(self.payload, restored)
        archive = RideArchive(restored / 'data', self.archive.vehicle_key)
        self.assertEqual(archive.read_months(), self.archive.read_months())

    def test_untrusted_paths_rejected_before_restore(self):
        bad = copy.deepcopy(self.payload)
        bad['files']['sessions/../../public.txt'] = {'secret': True}
        with self.assertRaises(ValueError):
            unseal(seal(bad, self.key), self.key)
        with self.assertRaises(ValueError):
            restore(bad, self.root / 'bad')
        self.assertFalse((self.root / 'public.txt').exists())

    def test_cloud_worker_due_gate_and_repeated_force_are_idempotent(self):
        source = Source()
        result, code, paths = execute_worker(self.payload, self.key, self.session, {'interval_days': 10},
                                             self.root / 'first', source=source, now=NOW, force=True)
        self.assertEqual(code, 0)
        self.assertEqual(read_json(paths[0])['summary']['ride_count'], 2)
        result['files']['sessions/schedule-state.json']['publication_pending'] = False
        requests = len(source.requests)
        skipped, code, paths = execute_worker(result, self.key, self.session, {'interval_days': 10},
                                              self.root / 'second', source=source, now=NOW + timedelta(days=9))
        self.assertIsNone(skipped)
        self.assertEqual(len(source.requests), requests)
        repeated, code, paths = execute_worker(result, self.key, self.session, {'interval_days': 10},
                                               self.root / 'repeat', source=source, now=NOW, force=True)
        self.assertEqual(read_json(paths[0])['summary']['ride_count'], 2)
        due, code, paths = execute_worker(result, self.key, self.session, {'interval_days': 10},
                                          self.root / 'late', source=source, now=NOW + timedelta(days=40))
        self.assertEqual(code, 0)
        self.assertEqual(due['files']['sessions/schedule-state.json']['last_success'], (NOW + timedelta(days=40)).isoformat())

    def test_publish_only_reuses_successful_archive_without_collection_or_clock_change(self):
        source = Source()
        saved, _, _ = execute_worker(self.payload, self.key, self.session, {'interval_days': 10}, self.root / 'collected', source=source, now=NOW, force=True)
        saved['files']['sessions/schedule-state.json']['publication_pending'] = False
        previous = copy.deepcopy(saved['files']['sessions/schedule-state.json'])
        revised_session = {**self.session, 'revision': (NOW + timedelta(days=1)).isoformat()}
        for days in (1, 20):
            with self.subTest(days=days), patch('nbmap.cloud.run_due', side_effect=AssertionError('must not collect')) as collect:
                result, code, paths = execute_worker(saved, self.key, revised_session, {'interval_days': 10}, self.root / f'publish-{days}', publish_only=True, now=NOW + timedelta(days=days))
                collect.assert_not_called()
                self.assertEqual(code, 0)
                self.assertEqual(result['credential_revision'], saved['credential_revision'])
                state = result['files']['sessions/schedule-state.json']
                self.assertEqual({**state, 'publication_pending': False}, previous)
                self.assertEqual(result['files']['sessions/tokens.json'], saved['files']['sessions/tokens.json'])
                self.assertEqual({k: v for k, v in result['files'].items() if k.startswith('data/')}, {k: v for k, v in saved['files'].items() if k.startswith('data/')})
                self.assertEqual(read_json(paths[0])['summary']['ride_count'], 2)
        self.assertFalse(is_cloud_due(saved, self.session, {'interval_days': 10}, now=NOW + timedelta(hours=1)))
        self.assertTrue(is_cloud_due(saved, self.session, {'interval_days': 10}, publish_only=True, now=NOW + timedelta(hours=1)))
        with self.assertRaises(ValueError):
            is_cloud_due(saved, self.session, {'interval_days': 10}, force=True, publish_only=True)
        with self.assertRaises(ValueError):
            execute_worker(saved, self.key, self.session, {'interval_days': 10}, self.root / 'conflict', force=True, publish_only=True)
        with self.assertRaises(ValueError):
            execute_worker(self.payload, self.key, self.session, {'interval_days': 10}, self.root / 'no-success', publish_only=True)
        self.assertFalse(is_cloud_due(saved, None, {'interval_days': 10, 'enabled': False}, publish_only=True))
        with self.assertRaises(ValueError):
            execute_worker(saved, self.key, None, {'interval_days': 10, 'enabled': False}, self.root / 'disabled', publish_only=True)

    def test_cloud_gate_respects_interval_retry_publication_and_disable(self):
        payload = copy.deepcopy(self.payload)
        state = {'last_success': NOW.isoformat(), 'publication_pending': False}
        payload['files']['sessions/schedule-state.json'] = state
        self.assertFalse(is_cloud_due(payload, self.session, {'interval_days': 10}, now=NOW + timedelta(days=9)))
        self.assertTrue(is_cloud_due(payload, self.session, {'interval_days': 10}, now=NOW + timedelta(days=10)))
        state['retry_at'] = (NOW + timedelta(hours=1)).isoformat()
        self.assertFalse(is_cloud_due(payload, self.session, {'interval_days': 10}, now=NOW))
        self.assertTrue(is_cloud_due(payload, self.session, {'interval_days': 10}, now=NOW + timedelta(hours=1)))
        state['publication_pending'] = True
        self.assertTrue(is_cloud_due(payload, self.session, {'interval_days': 10}, now=NOW))
        self.assertFalse(is_cloud_due(payload, self.session, {'interval_days': 10, 'enabled': False}, now=NOW, force=True))

    def test_failed_cloud_sync_keeps_published_archive_and_retries(self):
        result, _, _ = execute_worker(self.payload, self.key, self.session, {'interval_days': 10},
                                      self.root / 'first', source=Source(), now=NOW, force=True)
        before = {p: v for p, v in result['files'].items() if '/snapshots/' in p}
        failed, code, paths = execute_worker(result, self.key, self.session, {'interval_days': 10},
                                             self.root / 'fail', source=Source(fail=True), now=NOW, force=True)
        self.assertEqual(code, 1)
        self.assertEqual(paths, [])
        self.assertEqual({p: v for p, v in failed['files'].items() if '/snapshots/' in p}, before)
        self.assertEqual(failed['files']['sessions/schedule-state.json']['retry_at'], (NOW + timedelta(hours=1)).isoformat())
        self.notification.assert_not_called()

    def test_cloud_status_uses_workflow_state_and_preserves_success_history(self):
        payload = copy.deepcopy(self.payload)
        payload['files']['sessions/schedule-state.json'] = {'status': 'success', 'last_success': NOW.isoformat()}
        settings = {'repo': 'synthetic/private', 'interval_days': 10}
        for workflow_state in ('active', 'disabled_manually'):
            with self.subTest(workflow_state=workflow_state):
                output = io.StringIO()
                with patch('nbmap.cloud.cloud_config', return_value=settings), patch('nbmap.cloud.download_state', return_value=payload), \
                     patch('nbmap.cloud.gh_json', side_effect=[{'state': workflow_state}, []]), redirect_stdout(output):
                    self.assertEqual(manage('status', self.config, self.data, self.root), 0)
                text = output.getvalue()
                self.assertIn('上次成功：2026-10-04T11:00:00+08:00', text)
                if workflow_state == 'active':
                    self.assertIn('下次到期：2026-10-14T11:00:00+08:00', text)
                else:
                    self.assertIn('云端定时执行：未启用。', text)
                    self.assertNotIn('下次到期', text)

    def test_reinstall_preserves_site_annotations_without_copying_another_repos_site(self):
        from nbmap.cloud import setup
        site = {'host': 'map.example.invalid', 'user': 'map', 'place_annotations': {'labels': {'r_' + 'a' * 24: '合成球馆🏸'}}}
        repo = 'synthetic/private'
        folder = self.root / 'work/github-actions' / hashlib.sha256(repo.encode()).hexdigest()[:12]
        (self.config / 'cloud-state.key').write_bytes(self.key)
        for source in ('local', 'checkout', 'other-repo'):
            with self.subTest(source=source):
                previous = {'repo': repo if source != 'other-repo' else 'synthetic/other', 'site': site}
                if source == 'checkout':
                    del previous['site']
                write_json(self.config / 'cloud.json', previous)
                write_json(folder / 'sync-settings.json', {'site': site} if source == 'checkout' else {})
                success = subprocess.CompletedProcess([], 0, stdout=b'', stderr=b'')
                with patch('nbmap.cloud.gh_json', return_value={'login': 'synthetic'}), patch('nbmap.cloud.bootstrap', return_value=self.session), patch('nbmap.cloud.command', return_value=success), patch('nbmap.cloud.private_repo'), patch('nbmap.cloud.secret'), patch('nbmap.cloud.deploy_code') as deploy, redirect_stdout(io.StringIO()):
                    self.assertEqual(setup(self.config, self.data, self.root, repo=repo, interval_days=3, publish_repos=[]), 0)
                settings = deploy.call_args.args[3]
                local = read_json(self.config / 'cloud.json')
                self.assertEqual(settings['interval_days'], 3)
                if source == 'other-repo':
                    self.assertNotIn('site', settings)
                    self.assertNotIn('site', local)
                else:
                    self.assertEqual(settings['site'], site)
                    self.assertEqual(local['site'], site)

    def test_private_deploy_keeps_project_skills_and_relocated_docs(self):
        source = Path(__file__).resolve().parents[1]
        destination = self.root / 'deploy'
        destination.mkdir()
        (destination / 'CONTEXT.md').write_text('obsolete managed context')
        staged = []

        def run(args, **kwargs):
            if args[:3] == ['git', 'ls-files', '--']:
                return subprocess.CompletedProcess(args, 0, stdout=b'CONTEXT.md\n', stderr=b'')
            if args[:2] == ['git', 'add']:
                staged.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=b'', stderr=b'')

        with patch('nbmap.cloud.command', side_effect=run), patch('nbmap.cloud.gh_json', return_value={'ssh_keys': ['ssh-ed25519 synthetic-public-key']}):
            deploy_code(source, destination, 'fixture/private', {'interval_days': 10})
        self.assertFalse((destination / 'CONTEXT.md').exists())
        self.assertEqual((destination / 'docs/CONTEXT.md').read_bytes(), (source / 'docs/CONTEXT.md').read_bytes())
        self.assertEqual((destination / '.agents/skills/verify-ninebot-map/SKILL.md').read_bytes(),
                         (source / '.agents/skills/verify-ninebot-map/SKILL.md').read_bytes())
        self.assertTrue((destination / 'docs/design/DESIGN.md').is_file())
        self.assertTrue((destination / 'schemas/ride-dataset-v1.schema.json').is_file())
        self.assertEqual((destination / '.gitignore').read_bytes(), (source / '.gitignore').read_bytes())
        self.assertEqual(staged[0][:4], ['git', 'add', '--all', '--'])
        self.assertIn('CONTEXT.md', staged[0])
        self.assertIn('.agents', staged[0])
        self.assertFalse(any((destination / name).exists() for name in ('.private', 'data', 'work')))
        check = subprocess.run([sys.executable, str(destination / 'scripts/check-project.py')],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_image_retry_does_not_request_rides_or_reset_sync_clock(self):
        source = Source()
        result, _, _ = execute_worker(self.payload, self.key, self.session, {'interval_days': 10},
                                      self.root / 'first', source=source, now=NOW, force=True)
        requests = list(source.requests)
        retry, code, paths = execute_worker(result, self.key, self.session, {'interval_days': 10},
                                            self.root / 'publication-only', source=source, now=NOW + timedelta(minutes=5))
        self.assertEqual(source.requests, requests)
        self.assertEqual(code, 0)
        self.assertEqual(len(paths), 1)
        self.assertEqual(retry['files']['sessions/schedule-state.json']['last_success'], NOW.isoformat())

    def test_pull_merges_local_only_rides_and_keeps_better_geometry_and_cutoff(self):
        remote = self.root / 'remote'
        a = RideArchive.for_vehicle(remote, 'synthetic-sn')
        collect_month(Source(ids=('one','cloud'), simple=True), 'synthetic-sn', '202609', a)
        prepare(a, map_from='2026-10-01')
        collect_month(Source(ids=('one','local')), 'synthetic-sn', '202609', self.archive)
        before = self.archive.read_month('202609')
        outputs = import_archives(remote, self.data)
        merged = self.archive.read_month('202609')
        self.assertEqual(len(merged['rides']), 3)
        self.assertEqual(next(r['coordinate_count'] for r in merged['rides'] if r['ride_id']=='one202609'), 3)
        self.assertEqual([p for p in merged['points'] if p['ride_id']=='one202609'],
                         [p for p in before['points'] if p['ride_id']=='one202609'])
        self.assertEqual(read_json(outputs[0])['selection']['map_from'], '2026-01-01T00:00:00+08:00')
        import_archives(remote, self.data)
        self.assertEqual(len(self.archive.read_month('202609')['rides']), 3)

    def test_invalid_remote_snapshot_never_overwrites_local(self):
        remote = self.root / 'remote'
        restore(self.payload, remote)
        a = RideArchive(remote / 'data', self.archive.vehicle_key)
        pointer = read_json(a.path / 'months/202609.json')
        snapshot = read_json(a.path / pointer['snapshot'])
        snapshot['rides'][0]['coordinate_count'] = 999
        write_json(a.path / pointer['snapshot'], snapshot)
        before = self.archive.read_month('202609')
        with self.assertRaises(ValueError):
            import_archives(remote / 'data', self.data)
        self.assertEqual(self.archive.read_month('202609'), before)

    def test_image_has_pixels_without_geo_metadata_and_readme_edit_is_idempotent(self):
        dataset = read_json(self.archive.path / 'prepared/dataset.json')
        path = render_tracks(dataset, self.root / 'tracks.png')
        with Image.open(path) as image:
            self.assertLessEqual(image.width, 1200)
            self.assertLessEqual(image.height, 900)
            self.assertEqual(image.info, {})
            self.assertGreater(len(image.getcolors(image.width * image.height)), 1)
        original = '# Existing project\n\nKeep this text.\n'
        updated = readme_image(original)
        self.assertTrue(updated.startswith(original.rstrip()))
        self.assertEqual(readme_image(updated), updated)
        self.assertIn(IMAGE_PATH, updated)

    def test_readme_replaces_legacy_image_block_without_changing_surrounding_text(self):
        original = ('# Existing project\n\nKeep this text.\n\n'
                    '<!-- ninebot-track-image:start -->\n\n## 骑行轨迹\n\n'
                    '![无底图骑行轨迹](assets/ninebot-tracks.png)\n\n'
                    '<!-- ninebot-track-image:end -->\n\nKeep this footer.\n')
        expected = ('# Existing project\n\nKeep this text.\n\n'
                    '<!-- ninebot-track-image:start -->\n\n'
                    '![骑行轨迹](assets/ninebot-tracks.png)\n\n'
                    '<!-- ninebot-track-image:end -->\n\nKeep this footer.\n')
        self.assertEqual(readme_image(original), expected)

    def test_readme_keeps_top_image_block_and_body_after_repeated_updates(self):
        original = ('<!-- ninebot-track-image:start -->\n\n'
                    '![骑行轨迹](assets/ninebot-tracks.png)\n\n'
                    '<!-- ninebot-track-image:end -->\n\n'
                    '# Ninebot Map\n\nKeep the setup instructions.\n')
        updated = readme_image(original)
        self.assertEqual(updated, original)
        self.assertEqual(readme_image(updated), original)

    def test_public_image_publish_stages_only_png_and_readme(self):
        import subprocess
        image = self.root / 'tracks.png'
        image.write_bytes(b'synthetic-image')
        (self.root / 'known-hosts').write_text('synthetic-host')
        seen = []
        def git(args, **kwargs):
            seen.append(args)
            if args[:2] == ['git','clone']:
                directory = Path(args[-1])
                (directory / 'README.md').write_text('# Keep me\n')
            output = b'assets/ninebot-tracks.png\nREADME.md\n' if args[:4]==['git','diff','--cached','--name-only'] else b''
            return subprocess.CompletedProcess(args, 0, stdout=output)
        with patch.dict('os.environ', {'PUBLIC_DEPLOY_KEY_1':'synthetic-deploy-key'}), patch('nbmap.cloud.command', side_effect=git):
            publish_image(self.root, image, [{'repo':'fixture/public','branch':'main'}])
        self.assertIn(['git','add','--',IMAGE_PATH,'README.md'], seen)
        self.assertFalse((self.root / 'publish-1.key').exists())
        self.assertTrue((self.root / 'publish-1/README.md').read_text().startswith('# Keep me'))

    def test_public_image_commits_belong_to_owner_for_both_destinations(self):
        image = self.root / 'tracks.png'
        image.write_bytes(b'synthetic-image')
        (self.root / 'known-hosts').write_text('synthetic-host')
        origins = {}
        destinations = [{'repo': 'fixture/map', 'branch': 'main'}, {'repo': 'fixture/profile', 'branch': 'main'}]
        for index, destination in enumerate(destinations, 1):
            origin = self.root / f'origin-{index}'
            subprocess.run(['git', 'init', '-b', 'main', str(origin)], check=True, capture_output=True)
            (origin / 'README.md').write_text('# Keep me\n')
            subprocess.run(['git', 'add', 'README.md'], cwd=origin, check=True, capture_output=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '-m', 'Seed fixture'], cwd=origin, check=True, capture_output=True)
            origins[destination['repo']] = origin

        def local_transport(args, **kwargs):
            if args[0] == 'ssh-keygen':
                return subprocess.CompletedProcess(args, 0, stdout=b'synthetic-public-key', stderr=b'')
            if args[:2] == ['git', 'clone']:
                repo = args[-2].removeprefix('git@github.com:').removesuffix('.git')
                args = [*args[:-2], str(origins[repo]), args[-1]]
            if args[:2] == ['git', 'push']:
                return subprocess.CompletedProcess(args, 0, stdout=b'', stderr=b'')
            return subprocess.run(args, capture_output=True, **kwargs)

        with patch.dict('os.environ', {'PUBLIC_DEPLOY_KEY_1': 'synthetic-key-1', 'PUBLIC_DEPLOY_KEY_2': 'synthetic-key-2'}), \
             patch('nbmap.cloud.command', side_effect=local_transport):
            publish_image(self.root, image, destinations)
        expected = ['Timisic', '91100723+Timisic@users.noreply.github.com'] * 2
        for index in (1, 2):
            target = self.root / f'publish-{index}'
            identity = subprocess.run(['git', 'log', '-1', '--format=%an%n%ae%n%cn%n%ce'],
                                      cwd=target, check=True, capture_output=True, text=True).stdout.splitlines()
            self.assertEqual(identity, expected)
            changes = subprocess.run(['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'],
                                     cwd=target, check=True, capture_output=True, text=True).stdout.splitlines()
            self.assertEqual(set(changes), {IMAGE_PATH, 'README.md'})
            count = subprocess.run(['git', 'rev-list', '--count', 'HEAD'], cwd=target,
                                   check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(count, '2')
            self.assertFalse((self.root / f'publish-{index}.key').exists())

    def test_trimmed_secret_key_parses_and_matches_its_target(self):
        key_path = self.root / 'synthetic-generated-key'
        subprocess.run(['ssh-keygen', '-t', 'ed25519', '-N', '', '-f', str(key_path)], check=True, capture_output=True)
        trimmed = key_path.read_text().strip()
        fingerprint = public_fingerprint(key_path.with_suffix('.pub').read_text())
        image = self.root / 'tracks.png'
        image.write_bytes(b'synthetic-image')
        (self.root / 'known-hosts').write_text('synthetic-host')
        def run(args, **kwargs):
            if args[0] == 'ssh-keygen':
                return subprocess.run(args, capture_output=True, check=True)
            if args[:2] == ['git', 'clone']:
                (Path(args[-1]) / 'README.md').write_text('# Synthetic\n')
            output = b'assets/ninebot-tracks.png\nREADME.md\n' if args[:4] == ['git', 'diff', '--cached', '--name-only'] else b''
            return subprocess.CompletedProcess(args, 0, stdout=output, stderr=b'')
        with patch.dict('os.environ', {'PUBLIC_DEPLOY_KEY_1': trimmed}), patch('nbmap.cloud.command', side_effect=run):
            publish_image(self.root, image, [{'repo': 'fixture/public', 'branch': 'main', 'key_fingerprint': fingerprint}])
        failure = CommandFailure(['git', 'clone'], subprocess.CompletedProcess([], 128,
            stderr=b'Load key: invalid format\nPermission denied (publickey). synthetic-secret'))
        self.assertEqual(failure.category, 'deploy_key_format')
        self.assertNotIn('synthetic-secret', str(failure))

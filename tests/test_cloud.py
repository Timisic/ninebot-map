"""Synthetic cloud state, merge, due-time and image fixtures. No production account."""
import copy
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
        for failure in (True, False):
            with self.subTest(failure=failure):
                root = self.root / ('worker-failed' if failure else 'worker-success')
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
                with patch.dict('os.environ', {'CLOUD_STATE_KEY': self.key.decode(), 'NINEBOT_SESSION': json.dumps(self.session)}), patch('nbmap.cloud.command', side_effect=git), patch('nbmap.cloud.execute_worker', return_value=(updated, 0, [self.archive.path / 'prepared/dataset.json'])), patch('nbmap.cloud.publish_image'), patch('nbmap.cloud.publish_site_data', side_effect=RuntimeError('PRIVATE_SENTINEL') if failure else None), redirect_stdout(log):
                    self.assertEqual(worker(root), 1 if failure else 0)
                state = unseal((root / 'work/state-publish/state.enc').read_bytes(), self.key)['files']['sessions/schedule-state.json']
                self.assertEqual(state['last_success'], NOW.isoformat())
                self.assertEqual(state['publication_pending'], failure)
                self.assertEqual('site_published_at' in state, not failure)
                self.assertNotIn('PRIVATE_SENTINEL', log.getvalue())

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
            self.assertEqual(image.size, (1200, 900))
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

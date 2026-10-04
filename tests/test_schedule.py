"""Synthetic time, provider and process fixtures. No credentials or production rides."""
import multiprocessing
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from nbmap.acquisition import Acquisition, collect_month
from nbmap.archive import RideArchive
from nbmap.dataset import prepare
from nbmap.schedule import run_due, next_due, sync_start, manage, relocate_storage
from nbmap.storage import read_json, write_json, sync_lock

NOW = datetime(2026, 10, 4, 3, tzinfo=timezone.utc)


class Source:
    def __init__(self):
        self.fail = False
        self.detail_calls = []
        self.extra = False
        self.trail = '116,39,1;116.01,39.01,2;116.02,39.02,3'
        self.simple = False
        self.duration = 120

    def month(self, sn, month, page):
        if self.fail:
            raise RuntimeError('synthetic network failure')
        ids = [month] + ([month + '-new'] if self.extra else [])
        return {'times': len(ids), 'total_mileages': len(ids),
                'list': [{'travel_id': rid, 'mileages': 1, 'start_time': 1791080000} for rid in ids]}

    def detail(self, sn, rid):
        self.detail_calls.append(rid)
        return {'trail': self.trail, 'is_show_simple_point': self.simple,
                'mileages': 1, 'duration': self.duration, 'start_time': 1791080000}


def lock_worker(root, queue):
    try:
        with sync_lock(root):
            queue.put('acquired')
    except RuntimeError:
        queue.put('busy')


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        notification = patch('nbmap.schedule.notify')
        self.notification = notification.start()
        self.addCleanup(notification.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config, self.data = self.root / 'private', self.root / 'data'
        write_json(self.config / 'preferences.json', {'sn': 'synthetic-sn'})
        write_json(self.config / 'schedule.json', {'enabled': True, 'interval_days': 10})
        self.archive = RideArchive.for_vehicle(self.data, 'synthetic-sn')
        self.source = Source()

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, now=NOW, force=False):
        return run_due(self.config, self.data, source=self.source, now=now, force=force)

    def test_direct_worker_failure_has_no_local_notification(self):
        self.source.fail = True
        self.assertEqual(run_due(self.config, self.data, source=self.source, now=NOW), 1)
        state = read_json(self.config / 'schedule-state.json')
        self.assertEqual(state['status'], 'failed')
        self.assertEqual(state['retry_at'], (NOW + timedelta(hours=1)).isoformat())
        self.notification.assert_not_called()

    def test_local_run_notifies_once_and_disabled_force_run_stays_quiet(self):
        class FailedClient(Source):
            tokens = {'refresh_token': 'synthetic-token'}
            def recover_session(self):
                pass
            def session(self):
                pass
        client = FailedClient()
        client.fail = True
        with patch('nbmap.schedule.Client', return_value=client), patch('nbmap.schedule.utcnow', return_value=NOW):
            self.assertEqual(manage('run', self.config, self.data, self.root), 1)
            self.notification.assert_called_once_with('failed')
            self.assertEqual(manage('run', self.config, self.data, self.root, force=True), 1)
            self.notification.assert_called_once_with('failed')
            self.assertEqual(read_json(self.config / 'schedule-state.json')['failures'], 2)
            write_json(self.config / 'schedule.json', {'enabled': False, 'interval_days': 10})
            write_json(self.config / 'schedule-state.json', {'status': 'success'})
            self.notification.reset_mock()
            self.assertEqual(manage('run', self.config, self.data, self.root, force=True), 1)
            self.assertEqual(read_json(self.config / 'schedule-state.json')['status'], 'failed')
            self.notification.assert_not_called()

    def test_inactive_status_keeps_history_without_due_or_hourly_claims(self):
        write_json(self.config / 'schedule-state.json', {'status': 'success', 'last_success': NOW.isoformat()})
        for enabled, loaded in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(enabled=enabled, loaded=loaded):
                write_json(self.config / 'schedule.json', {'enabled': enabled, 'interval_days': 10, 'label': 'synthetic-label'})
                output = io.StringIO()
                result = subprocess.CompletedProcess([], 0 if loaded else 1, stdout='')
                with patch('nbmap.schedule.sys.platform', 'darwin'), patch('nbmap.schedule.launchctl', return_value=result), redirect_stdout(output):
                    self.assertEqual(manage('status', self.config, self.data, self.root), 0)
                text = output.getvalue()
                self.assertIn('上次成功：2026-10-04T11:00:00+08:00', text)
                if enabled and loaded:
                    self.assertIn('下次到期：2026-10-14T11:00:00+08:00', text)
                    self.assertIn('每小时检查', text)
                else:
                    self.assertNotIn('下次到期', text)
                    self.assertNotIn('每小时检查', text)

    def test_continuous_ten_days_across_month_and_missed_wakeup(self):
        state = {'last_success': '2026-01-27T00:00:00+00:00'}
        settings = {'interval_days': 10}
        self.assertEqual(next_due(settings, state), datetime(2026, 2, 6, tzinfo=timezone.utc))
        self.assertEqual(self.run_sync(), 0)
        state = read_json(self.config / 'schedule-state.json')
        self.assertEqual(next_due(settings, state), NOW + timedelta(days=10))
        count = len(self.source.detail_calls)
        self.assertEqual(self.run_sync(NOW + timedelta(days=9)), 0)
        self.assertEqual(len(self.source.detail_calls), count)
        self.assertEqual(self.run_sync(NOW + timedelta(days=40)), 0)
        self.assertEqual(read_json(self.config / 'schedule-state.json')['requested_months'], ['202610', '202611'])

    def test_incremental_idempotent_and_range_settings_preserved(self):
        collect_month(self.source, 'synthetic-sn', '202609', self.archive)
        prepare(self.archive, map_from='2026-01-01')
        settings = read_json(self.archive.path / 'dataset-settings.json')
        self.assertEqual(self.run_sync(), 0)
        dataset = read_json(self.archive.path / 'prepared/dataset.json')
        self.assertEqual(dataset['summary']['ride_count'], 2)
        self.source.detail_calls.clear()
        self.assertEqual(self.run_sync(force=True), 0)
        repeat = read_json(self.archive.path / 'prepared/dataset.json')
        self.assertEqual(repeat['rides'], dataset['rides'])
        self.assertEqual(repeat['tracks'], dataset['tracks'])
        self.assertEqual(self.source.detail_calls, [])
        self.source.extra = True
        self.assertEqual(self.run_sync(force=True), 0)
        updated = read_json(self.archive.path / 'prepared/dataset.json')
        self.assertEqual(updated['summary']['ride_count'], 4)
        self.assertEqual(read_json(self.archive.path / 'dataset-settings.json'), settings)

    def test_failed_refresh_retains_dataset_and_backs_off(self):
        self.assertEqual(self.run_sync(), 0)
        path = self.archive.path / 'prepared/dataset.json'
        before = path.read_bytes()
        pointer = (self.archive.path / 'prepared/latest.json').read_bytes()
        self.source.fail = True
        for i, hours in enumerate((1, 6, 24, 24), 1):
            self.assertEqual(self.run_sync(force=True), 1)
            state = read_json(self.config / 'schedule-state.json')
            self.assertEqual(state['failures'], i)
            self.assertEqual(datetime.fromisoformat(state['retry_at']), NOW + timedelta(hours=hours))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((self.archive.path / 'prepared/latest.json').read_bytes(), pointer)
        self.assertEqual(state['last_success'], NOW.isoformat())
        self.assertEqual(self.run_sync(), 0)  # no extra request before retry
        self.source.fail = False
        self.assertEqual(self.run_sync(NOW + timedelta(days=2)), 0)
        self.assertEqual(read_json(self.config / 'schedule-state.json')['failures'], 0)

    def test_recent_incomplete_detail_retried_and_old_sampled_geometry_preserved(self):
        self.source.duration = 0
        self.assertEqual(self.run_sync(), 0)
        self.source.detail_calls.clear()
        self.source.duration = 120
        self.assertEqual(self.run_sync(force=True), 0)
        self.assertEqual(len(self.source.detail_calls), 2)
        self.source.trail = '116,39,1;116.02,39.02,3'
        self.source.simple = True
        self.source.detail_calls.clear()
        before = self.archive.read_month('202610')['points']
        report = collect_month(self.source, 'synthetic-sn', '202610', self.archive, refresh_details=True)
        self.assertTrue(report['published'])
        self.assertEqual(self.archive.read_month('202610')['points'], before)
        # Same guarantee after removing the separate detail cache.
        for p in (self.archive.path / 'details').glob('*'):
            p.unlink()
        collect_month(self.source, 'synthetic-sn', '202610', self.archive, refresh_details=True)
        self.assertEqual(self.archive.read_month('202610')['points'], before)

    def test_no_ride_deletion_and_first_failed_capture_is_not_published(self):
        self.source.extra = True
        self.assertEqual(self.run_sync(), 0)
        before = self.archive.read_month('202610')
        self.source.extra = False
        report = collect_month(self.source, 'synthetic-sn', '202610', self.archive)
        self.assertFalse(report['published'])
        self.assertEqual(self.archive.read_month('202610'), before)
        class Broken(Source):
            def detail(self, *args):
                raise RuntimeError('synthetic detail failure')
        report = collect_month(Broken(), 'synthetic-sn', '202608', self.archive)
        self.assertFalse(report['published'])
        self.assertFalse((self.archive.path / 'months/202608.json').exists())

    def test_process_lock_releases_and_schedule_does_not_change_when_busy(self):
        ctx = multiprocessing.get_context('spawn')
        queue = ctx.Queue()
        with sync_lock(self.data):
            process = ctx.Process(target=lock_worker, args=(self.data, queue))
            process.start()
            self.assertEqual(queue.get(timeout=5), 'busy')
            process.join(timeout=5)
            self.assertEqual(process.exitcode, 0)
            with self.assertRaises(RuntimeError):
                self.run_sync()
        process = ctx.Process(target=lock_worker, args=(self.data, queue))
        process.start()
        self.assertEqual(queue.get(timeout=5), 'acquired')
        process.join(timeout=5)
        self.assertFalse((self.config / 'schedule-state.json').exists())

    def test_missing_login_is_visible_and_checked_only_daily(self):
        class NoSession:
            tokens = {}
            def recover_session(self):
                pass
        with patch('nbmap.schedule.Client', return_value=NoSession()), patch('nbmap.schedule.notify') as notification:
            self.assertEqual(run_due(self.config, self.data, now=NOW, local_notifications=True), 1)
            state = read_json(self.config / 'schedule-state.json')
            self.assertEqual(state['status'], 'login_required')
            self.assertEqual(datetime.fromisoformat(state['retry_at']), NOW + timedelta(days=1))
            self.assertEqual(run_due(self.config, self.data, now=NOW), 0)
            notification.assert_called_once_with('login_required')

    def test_period_change_uses_last_success_and_disabled_run_is_quiet(self):
        self.assertEqual(self.run_sync(), 0)
        state = read_json(self.config / 'schedule-state.json')
        self.assertEqual(next_due({'interval_days': 3}, state), NOW + timedelta(days=3))
        write_json(self.config / 'schedule.json', {'enabled': False, 'interval_days': 3})
        self.source.extra = True
        self.source.detail_calls.clear()
        self.assertEqual(self.run_sync(NOW + timedelta(days=30)), 0)
        self.assertEqual(self.source.detail_calls, [])

    def test_refresh_rejection_and_mid_sync_expiration_are_visible(self):
        class ExpiredClient:
            tokens = {'refresh_token': 'synthetic-token', 'access_token': 'synthetic-access'}
            def recover_session(self):
                pass
            def session(inner):
                write_json(self.config / 'last-error.json', {'timestamp': NOW.isoformat(),
                    'stage': 'refresh', 'category': '服务端拒绝请求', 'code': '123', 'description': '会话失效'})
                raise RuntimeError('synthetic refresh rejected')
        with patch('nbmap.schedule.Client', return_value=ExpiredClient()), patch('nbmap.schedule.notify'):
            self.assertEqual(run_due(self.config, self.data, now=NOW), 1)
        self.assertEqual(read_json(self.config / 'schedule-state.json')['status'], 'login_required')
        # A network outage at the same auth boundary remains retryable, without claiming expiry.
        class NetworkClient(ExpiredClient):
            def session(inner):
                write_json(self.config / 'last-error.json', {'timestamp': NOW.isoformat(),
                    'stage': 'refresh', 'category': '网络错误', 'code': None, 'description': '连接失败'})
                raise RuntimeError('synthetic network outage')
        with patch('nbmap.schedule.Client', return_value=NetworkClient()), patch('nbmap.schedule.notify'):
            self.assertEqual(run_due(self.config, self.data, now=NOW, force=True), 1)
        self.assertEqual(read_json(self.config / 'schedule-state.json')['status'], 'failed')

    def test_protected_storage_move_retains_contents_and_link(self):
        protected = self.root / 'Downloads'
        original = protected / 'private'
        original.mkdir(parents=True)
        (original / 'fixture.json').write_text('{"synthetic":true}')
        destination = self.root / 'background-private'
        with patch('nbmap.schedule.Path.home', return_value=self.root):
            self.assertEqual(relocate_storage(original, destination), destination)
        self.assertTrue(original.is_symlink())
        self.assertEqual((original / 'fixture.json').read_text(), '{"synthetic":true}')
        self.assertEqual((destination / 'fixture.json').read_text(), '{"synthetic":true}')

    def test_corrupted_detail_cache_is_refetched(self):
        collect_month(self.source, 'synthetic-sn', '202610', self.archive)
        for path in (self.archive.path / 'details').glob('*.json'):
            write_json(path, [])
        self.source.detail_calls.clear()
        self.assertTrue(collect_month(self.source, 'synthetic-sn', '202610', self.archive)['published'])
        self.assertEqual(self.source.detail_calls, ['202610'])

    def test_install_idempotent_and_uninstall_keeps_private_history(self):
        import subprocess
        venv = self.root / '.venv/bin/python'
        venv.parent.mkdir(parents=True)
        venv.touch()
        agent = self.root / 'LaunchAgents/test.plist'
        with patch('nbmap.schedule.sys.platform', 'darwin'), patch('nbmap.schedule.agent_path', return_value=agent), \
             patch('nbmap.schedule.launchctl', return_value=subprocess.CompletedProcess([], 0)), \
             patch('nbmap.schedule.prepare_background_runtime', return_value=(self.root, self.config, self.data)), \
             patch('nbmap.schedule.is_loaded', return_value=True):
            self.assertEqual(manage('install', self.config, self.data, self.root, interval_days=7), 0)
            before = agent.read_bytes()
            self.assertEqual(manage('install', self.config, self.data, self.root), 0)
            self.assertEqual(agent.read_bytes(), before)
            self.assertEqual(read_json(self.config / 'schedule.json')['interval_days'], 7)
            self.assertEqual(manage('disable', self.config, self.data, self.root), 0)
            self.assertFalse(read_json(self.config / 'schedule.json')['enabled'])
            self.assertEqual(manage('uninstall', self.config, self.data, self.root), 0)
            self.assertFalse(agent.exists())
            self.assertTrue((self.config / 'preferences.json').exists())
        for invalid in (0, -1, float('nan'), float('inf')):
            with patch('nbmap.schedule.sys.platform', 'darwin'), self.assertRaises(ValueError):
                manage('install', self.config, self.data, self.root, interval_days=invalid)

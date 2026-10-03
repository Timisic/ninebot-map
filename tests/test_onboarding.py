"""Fresh-user onboarding: synthetic credentials, empty storage and no network."""
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from nbmap.__main__ import main
from nbmap.archive import RideArchive
from nbmap.storage import read_json


class OnboardingTests(unittest.TestCase):
    def test_fresh_user_can_login_collect_and_prepare_own_data(self):
        with tempfile.TemporaryDirectory() as d:
            config, data = Path(d) / 'session', Path(d) / 'rides'
            prefix = ['--config-dir', str(config), '--data-dir', str(data)]

            def login(username, password, **kwargs):
                self.assertEqual(username, 'synthetic-new-user')
                self.assertEqual(password, 'synthetic-new-password')
                return {'username': username, 'access_token': 'synthetic-new-access',
                        'refresh_token': 'synthetic-new-refresh',
                        'accessTokenValidity': str(int(time.time() * 1000) + 3600000)}

            def business(tokens, device_id):
                tokens['business_uid'] = 'synthetic-new-business'

            with patch('sys.stdin.isatty', return_value=True), \
                 patch('builtins.input', side_effect=['synthetic-new-user', '202601']), \
                 patch('getpass.getpass', return_value='synthetic-new-password'), \
                 patch('nbmap.__main__.current_month', return_value='202601'), \
                 patch('nbmap.client.api.passport_login', side_effect=login), \
                 patch('nbmap.client.api.business_login', side_effect=business), \
                 patch('nbmap.client.api.vehicles', return_value=[{'wnumber': 'synthetic-new-vehicle', 'vehicle_name': 'Fixture'}]), \
                 patch('nbmap.client.api.travel_list', return_value={'times': 1, 'total_mileages': '1', 'list': [
                     {'travel_id': 'synthetic-new-ride', 'mileages': 1, 'start_time': 1767254400, 'end_time': 1767254460}]}), \
                 patch('nbmap.client.api.travel_detail', return_value={'trail': '116,39,1;116.01,39,1', 'is_show_simple_point': False}), \
                 patch('nbmap.client.time.sleep'), \
                 patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network')), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(main(prefix + ['start']), 0)
                self.assertEqual(main(prefix + ['prepare', '--all-map-tracks']), 0)
                self.assertNotIn('synthetic-new-password', output.getvalue())
                self.assertNotIn('synthetic-new-access', output.getvalue())
            self.assertEqual(read_json(config / 'tokens.json')['username'], 'synthetic-new-user')
            self.assertEqual(read_json(config / 'preferences.json')['sn'], 'synthetic-new-vehicle')
            archive = RideArchive.discover(data)[0]
            marker = read_json(archive.path / 'prepared/latest.json')
            dataset = read_json(archive.path / 'prepared' / marker['directory'] / 'dataset.json')
            self.assertEqual(dataset['summary']['ride_count'], 1)
            self.assertEqual(dataset['summary']['map_ride_count'], 1)
            self.assertIsNone(dataset['selection']['map_from'])


if __name__ == '__main__':
    unittest.main()

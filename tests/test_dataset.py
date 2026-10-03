import copy
from datetime import datetime
import unittest

from nbmap.dataset import build_dataset, validate_dataset


def fixture():
    rides, points = [], []
    for rid, timestamp, kind, distance in [
        ('old', int(datetime.fromisoformat('2026-07-06T09:00:00+08:00').timestamp()), 'sampled_unverified', 1),
        ('new', int(datetime.fromisoformat('2026-07-06T20:40:00+08:00').timestamp()), 'sampled_unverified', 2),
        ('simple', int(datetime.fromisoformat('2026-07-06T21:00:00+08:00').timestamp()), 'server_simplified', 3),
        ('unknown-time', None, 'sampled_unverified', None),
    ]:
        rides.append({'ride_id': rid, 'start_time_raw': timestamp, 'end_time_raw': timestamp + 60 if timestamp else None,
                      'distance_km': distance, 'duration_seconds': 60, 'energy_wh': None,
                      'geometry_kind': kind, 'coordinate_count': 2})
        points.extend({'ride_id': rid, 'index': i, 'longitude': 116 + i * .001,
                       'latitude': 39, 'timestamp': None} for i in range(2))
    return [{'coverage': {'month': '202607', 'vehicle_key': 'a' * 24, 'run_id': 'synthetic',
                          'upstream_ride_count': 4, 'upstream_distance_km': 6, 'list_complete': True},
             'rides': rides, 'points': points}]


class DatasetTests(unittest.TestCase):
    def test_all_mileage_kept_but_only_selected_sampled_track_exported(self):
        data = build_dataset(fixture(), dataset_id='fixture', map_from='2026-07-06T19:20:00+08:00')
        self.assertEqual(len(data['rides']), 4)
        self.assertEqual(data['summary']['known_distance_m'], 6000)
        self.assertIsNone(data['summary']['total_distance_m'])
        self.assertEqual(len(data['tracks']), 1)
        self.assertEqual(data['summary']['map_point_count'], 2)
        self.assertEqual(data['summary']['map_distance_m'], 2000)
        self.assertEqual(data['selection']['statistics_scope'], 'all_rides')
        self.assertEqual(data['coordinate_system'], 'unverified')
        self.assertEqual({r['map_status'] for r in data['rides']},
                         {'before_map_start', 'included', 'simplified', 'unknown_start_time'})
        validate_dataset(data)

    def test_boundary_is_inclusive_and_millisecond_timestamps_normalize(self):
        source = fixture()
        source[0]['rides'][1]['start_time_raw'] *= 1000
        data = build_dataset(source, dataset_id='fixture', map_from='2026-07-06T20:40:00+08:00')
        self.assertEqual(data['summary']['map_ride_count'], 1)

    def test_bad_date_or_timezone_rejected(self):
        for value in ['2026-13-01', '2026-01-01T08:00:00']:
            with self.assertRaises(ValueError):
                build_dataset(fixture(), dataset_id='fixture', map_from=value)

    def test_validator_rejects_orphan_tracks_and_incorrect_counts(self):
        data = build_dataset(fixture(), dataset_id='fixture', map_from='2026-07-06T19:20:00+08:00')
        broken = copy.deepcopy(data)
        broken['tracks'][0]['ride_id'] = 'missing'
        with self.assertRaises(ValueError):
            validate_dataset(broken)
        broken = copy.deepcopy(data)
        broken['summary']['map_point_count'] = 99
        with self.assertRaises(ValueError):
            validate_dataset(broken)

    def test_external_source_ids_need_not_follow_ninebot_conventions(self):
        data = build_dataset(fixture(), dataset_id='fixture', map_from='2026-07-06T19:20:00+08:00')
        selected = next(r for r in data['rides'] if r['map_status'] == 'included')
        original = selected['id']
        selected['id'] = 'my-gpx-ride-001'
        for track in data['tracks']:
            if track['ride_id'] == original:
                track['ride_id'] = selected['id']
        data['provenance'] = {'source': 'personal_gpx_converter', 'snapshot_ids': []}
        validate_dataset(data)


if __name__ == '__main__':
    unittest.main()

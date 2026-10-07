import copy
import json
import unittest
from pathlib import Path

from nbmap.stops import stop_durations
from nbmap.public_map import public_dataset, validate_public


class StopDurationTests(unittest.TestCase):
    def test_shared_parking_cases(self):
        cases = json.loads((Path(__file__).parent / 'fixtures/stop-duration-cases.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                self.assertEqual(stop_durations(case['data']), case['expected'])
                reordered = copy.deepcopy(case['data'])
                reordered['rides'].reverse()
                self.assertEqual(stop_durations(reordered), case['expected'])

    def test_public_duration_is_optional_and_allowlisted(self):
        data = json.loads((Path(__file__).parent / 'fixtures/synthetic-map.json').read_text())
        exported = public_dataset(data)
        self.assertEqual([t['stop_duration_s'] for t in exported['tracks']],
                         [stop_durations(data)[t['ride_id']] for t in data['tracks']])
        for track in exported['tracks']:
            self.assertEqual(set(track), {'id', 'date', 'distance_m', 'points', 'stop_duration_s'})
        for bad in [True, -1, float('nan'), 86401, '60']:
            changed = copy.deepcopy(exported)
            changed['tracks'][0]['stop_duration_s'] = bad
            with self.subTest(value=bad), self.assertRaises(ValueError):
                validate_public(changed)
        for track in exported['tracks']:
            del track['stop_duration_s']
        validate_public(exported)

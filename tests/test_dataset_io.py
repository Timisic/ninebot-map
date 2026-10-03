import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nbmap.acquisition import Acquisition
from nbmap.archive import RideArchive
from nbmap.dataset import prepare, validate_dataset
from nbmap.storage import read_json


class Source:
    def month(self, sn, month, page):
        return {'times': 1, 'total_mileages': '1', 'list': [{'travel_id': 'fixture', 'mileages': 1,
                'start_time': 1783341600, 'end_time': 1783341660, 'duration': 60}]}

    def detail(self, *args):
        return {'trail': '116,39,1;116.01,39,1', 'is_show_simple_point': False}


class DatasetIOTests(unittest.TestCase):
    def test_configured_acquisition_refreshes_dataset_without_extra_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, 'fixture-sn')
            task = Acquisition(Source(), a)
            self.assertIsNone(task.run('fixture-sn', '202607', '202607').dataset_directory)
            prepare(a, map_from='2026-07-01')
            result = task.run('fixture-sn', '202607', '202607')
            data = validate_dataset(read_json(Path(result.dataset_directory) / 'dataset.json'))
            self.assertEqual(data['selection']['map_from'], '2026-07-01T00:00:00+08:00')
            self.assertEqual(data['summary']['map_ride_count'], 1)

    def test_interrupted_preparation_keeps_previous_pointer_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, 'fixture-sn')
            Acquisition(Source(), a).run('fixture-sn', '202607', '202607')
            prepare(a, map_from='2026-07-01')
            pointer = read_json(a.path / 'prepared/latest.json')
            settings = read_json(a.path / 'dataset-settings.json')
            with patch('nbmap.dataset.write_csv', side_effect=OSError('synthetic interruption')):
                with self.assertRaises(OSError):
                    prepare(a, map_from='2026-07-05')
            self.assertEqual(read_json(a.path / 'prepared/latest.json'), pointer)
            self.assertEqual(read_json(a.path / 'dataset-settings.json'), settings)


if __name__ == '__main__':
    unittest.main()

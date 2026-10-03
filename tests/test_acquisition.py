import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from nbmap.acquisition import Acquisition
from nbmap.archive import RideArchive
from nbmap.storage import read_json


class Source:
    def __init__(self):
        self.interrupt = True
        self.calls = []

    def month(self, sn, month, page):
        self.calls.append(('month', month))
        if month == '202610' and self.interrupt:
            raise KeyboardInterrupt()
        return {'times': 1, 'total_mileages': '1', 'list': [{'travel_id': month, 'mileages': 1}]}

    def detail(self, sn, rid):
        self.calls.append(('detail', rid))
        return {'trail': '116,39,1;116.1,39.1,2', 'is_show_simple_point': False}


class AcquisitionTests(unittest.TestCase):
    def test_failed_refresh_preserves_published_month_and_reports_gap(self):
        with tempfile.TemporaryDirectory() as d:
            archive = RideArchive.for_vehicle(d, 'fixture-sn')
            source = Source()
            task = Acquisition(source, archive)
            task.run('fixture-sn', '202609', '202609')
            before = archive.read_month('202609')
            def failure(*args):
                raise RuntimeError('synthetic connection failure')
            source.month = failure
            result = task.run('fixture-sn', '202609', '202609')
            self.assertTrue(result.has_gaps)
            self.assertFalse(result.reports[0]['published'])
            self.assertEqual(archive.read_month('202609'), before)
            self.assertEqual(result.summary['listed_rides'], 1)

    def test_cross_month_interrupt_checkpoint_and_resume_without_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            archive = RideArchive.for_vehicle(d, 'fixture-sn')
            source = Source()
            task = Acquisition(source, archive)
            with self.assertRaises(KeyboardInterrupt):
                task.run('fixture-sn', '202609', '202610')
            checkpoint = read_json(archive.path / 'last-task.json')
            self.assertEqual(checkpoint['status'], 'interrupted')
            self.assertEqual(len(checkpoint['reports']), 1)
            self.assertEqual(archive.read_month('202609')['coverage']['listed_rides'], 1)
            source.interrupt = False
            source.calls.clear()
            events, stdout = [], io.StringIO()
            with redirect_stdout(stdout):
                result = task.run('fixture-sn', '202609', '202610', progress=events.append)
            self.assertEqual(stdout.getvalue(), '')
            self.assertNotIn(('detail', '202609'), source.calls)
            self.assertIn(('detail', '202610'), source.calls)
            self.assertEqual(result.summary['listed_rides'], 2)
            self.assertFalse(result.has_gaps)
            self.assertEqual([e['month'] for e in events if e['kind'] == 'month'], ['202609', '202610'])
            self.assertEqual(read_json(archive.path / 'last-task.json')['status'], 'completed')
            self.assertTrue((Path(result.report_directory) / 'rides.csv').exists())

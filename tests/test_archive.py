import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nbmap.archive import RideArchive
from nbmap.acquisition import collect_month
from nbmap.summary import summarize
from nbmap.storage import read_json, write_json


class Source:
    def __init__(self, distance=1):
        self.distance = distance

    def month(self, *args):
        return {"times": 1, "total_mileages": str(self.distance), "list": [{"travel_id": "ride", "mileages": self.distance}]}

    def detail(self, *args):
        return {"trail": "116,39,1;116.01,39.01,2", "is_show_simple_point": True, "show_simple_point_days": 180}


class ArchiveTests(unittest.TestCase):
    def test_incomplete_refresh_does_not_downgrade_complete_archive(self):
        class Paged(Source):
            def month(self, sn, month, page):
                return {'times': 2, 'total_mileages': '2', 'list': [{'travel_id': str(page), 'mileages': 1}]}
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, 'fixture-sn')
            collect_month(Paged(), 'fixture-sn', '202609', a)
            before = a.read_month('202609')
            attempt = collect_month(Paged(), 'fixture-sn', '202609', a, max_pages=1)
            self.assertFalse(attempt['published'])
            self.assertEqual(a.read_month('202609'), before)

    def test_failed_detail_refresh_keeps_previous_published_coordinates(self):
        class Failed(Source):
            def detail(self, *args):
                raise RuntimeError('synthetic failure')
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, 'fixture-sn')
            collect_month(Source(), 'fixture-sn', '202609', a)
            before = a.read_month('202609')
            attempt = collect_month(Failed(), 'fixture-sn', '202609', a, refresh_details=True)
            self.assertFalse(attempt['published'])
            self.assertEqual(attempt['detail_failures'], 1)
            self.assertEqual(a.read_month('202609'), before)

    def test_interrupted_publication_leaves_previous_month_readable(self):
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, "fixture-sn")
            collect_month(Source(1), "fixture-sn", "202609", a)
            before = a.read_month("202609")
            from nbmap import archive
            original = archive.write_json
            def fail_pointer(path, value):
                if Path(path).name == "202609.json" and Path(path).parent.name == "months":
                    raise OSError("simulated interrupted publication")
                return original(path, value)
            with patch.object(archive, "write_json", side_effect=fail_pointer):
                with self.assertRaises(OSError):
                    collect_month(Source(9), "fixture-sn", "202609", a)
            self.assertEqual(a.read_month("202609"), before)

    def test_read_and_summary_need_neither_cache_nor_private_account(self):
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, "fixture-sn")
            collect_month(Source(), "fixture-sn", "202609", a)
            shutil.rmtree(a.path / "details")
            shutil.rmtree(a.path / "raw")
            view = RideArchive(d, a.vehicle_key)
            summary = summarize(view)
            self.assertEqual(summary["geometry_kinds"], {"server_simplified": 1})
            self.assertEqual(summary["coordinate_points"], 2)
            self.assertTrue(summary["list_complete"])

    def test_mismatched_points_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, "fixture-sn")
            collect_month(Source(), "fixture-sn", "202609", a)
            snapshot = a.read_month("202609")
            snapshot["rides"][0]["coordinate_count"] = 3
            with self.assertRaises(ValueError):
                a.publish(snapshot)

    def test_interrupted_report_keeps_previous_report_directory(self):
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, 'fixture-sn')
            collect_month(Source(), 'fixture-sn', '202609', a)
            summarize(a)
            before = a.report_path()
            from nbmap import archive
            original = archive.write_csv
            def fail_points(path, *args):
                if Path(path).name == 'points.csv':
                    raise OSError('simulated interruption')
                return original(path, *args)
            with patch.object(archive, 'write_csv', side_effect=fail_points):
                with self.assertRaises(OSError):
                    summarize(a)
            self.assertEqual(a.report_path(), before)

    def test_legacy_import_is_offline_idempotent_and_preserves_originals(self):
        with tempfile.TemporaryDirectory() as d:
            a = RideArchive.for_vehicle(d, 'fixture-sn')
            collect_month(Source(), 'fixture-sn', '202609', a)
            snapshot = a.read_month('202609')
            legacy = a.path / 'exports/202609'
            write_json(legacy / 'rides.json', snapshot['rides'])
            write_json(legacy / 'points.json', snapshot['points'])
            write_json(legacy / 'coverage.json', snapshot['coverage'])
            before = {p.name: p.read_bytes() for p in legacy.iterdir()}
            shutil.rmtree(a.path / 'months')
            shutil.rmtree(a.path / 'details')
            self.assertEqual(a.import_legacy(), ['202609'])
            self.assertEqual(a.import_legacy(), [])
            self.assertEqual({p.name: p.read_bytes() for p in legacy.iterdir()}, before)
            self.assertEqual(a.read_month('202609')['rides'], snapshot['rides'])

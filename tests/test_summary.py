import tempfile
import unittest
from pathlib import Path

from nbmap.acquisition import collect_month
from nbmap.archive import RideArchive
from nbmap.summary import summarize
from nbmap.storage import read_json


class TwoRideClient:
    def month(self, sn, month, page):
        return {"times": 2, "total_mileages": "3.1", "list": [
            {"travel_id": "simplified", "mileages": "1"},
            {"travel_id": "sampled", "mileages": "2"}]}

    def detail(self, sn, rid):
        return {"trail": "116,39,1;116.01,39.01,1", "is_show_simple_point": rid == "simplified",
                "show_simple_point_days": 180}


class SummaryTests(unittest.TestCase):
    def test_in_progress_month_is_reported_as_pending(self):
        from nbmap.archive import key
        with tempfile.TemporaryDirectory() as d:
            collect_month(TwoRideClient(), "fixture-sn", "202609", RideArchive.for_vehicle(d, "fixture-sn"))
            (Path(d) / key("fixture-sn") / "raw" / "202610").mkdir()
            report = summarize(RideArchive.for_vehicle(d, "fixture-sn"))
            self.assertEqual(report["pending_months"], ["202610"])
            self.assertFalse(report["list_complete"])

    def test_simplified_routes_and_different_distance_totals_stay_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            collect_month(TwoRideClient(), "fixture-sn", "202609", RideArchive.for_vehicle(d, "fixture-sn"))
            report = summarize(RideArchive.for_vehicle(d, "fixture-sn"))
            self.assertTrue(report["list_complete"])
            self.assertEqual(report["geometry_kinds"], {"server_simplified": 1, "sampled_unverified": 1})
            self.assertEqual(report["upstream_month_distance_sum_km"], 3.1)
            self.assertEqual(report["detail_distance_sum_km"], 3.0)
            combined = RideArchive.for_vehicle(d, 'fixture-sn').report_path()
            self.assertEqual(len(read_json(combined / 'rides.json')), 2)
            self.assertIn('server_simplified', (combined / 'points.csv').read_text())


if __name__ == '__main__':
    unittest.main()

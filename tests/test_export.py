"""Synthetic server fixtures: no real rider data or live requests."""
import json
import tempfile
import unittest
from pathlib import Path

from nbmap.acquisition import collect_month, month_range
from nbmap.archive import RideArchive, parse_trail


class FakeClient:
    def __init__(self, pages, fail_details=()):
        self.pages = pages
        self.fail_details = {str(value) for value in fail_details}
        self.calls = []

    def month(self, sn, month, page):
        self.calls.append(("page", page))
        return self.pages[min(page - 1, len(self.pages) - 1)]

    def detail(self, sn, ride_id):
        self.calls.append(("detail", ride_id))
        if ride_id in self.fail_details:
            raise RuntimeError("synthetic failure")
        return {"travel_id": ride_id, "trail": "116.1,39.1,12;116.2,39.2,13"}


def page(ids, total):
    return {"times": total, "total_mileages": 99, "list": [
        {"travel_id": str(i), "mileages": 1} for i in ids]}


class ExportTests(unittest.TestCase):
    def run_export(self, client, path, **kw):
        return collect_month(client, "SN_SYNTHETIC", "202609", RideArchive.for_vehicle(path, "SN_SYNTHETIC"), **kw)

    def test_reads_beyond_twenty_and_deduplicates_page_overlap(self):
        client = FakeClient([page(range(20), 25), page(range(19, 25), 25)])
        with tempfile.TemporaryDirectory() as d:
            report = self.run_export(client, d)
            self.assertEqual(report["listed_rides"], 25)
            self.assertTrue(report["list_complete"])
            self.assertEqual(report["rides_with_coordinates"], 25)
            self.assertEqual(sum(c[0] == "detail" for c in client.calls), 25)

    def test_repeated_page_stops_and_reports_missing_rides(self):
        client = FakeClient([page(range(20), 300)])
        with tempfile.TemporaryDirectory() as d:
            report = self.run_export(client, d)
            self.assertEqual(report["stop_reason"], "repeated_page")
            self.assertFalse(report["list_complete"])
            self.assertEqual(report["missing_listed_rides"], 280)
            self.assertEqual(report["upstream_summary"]["total_mileages"], 99)

    def test_retry_missing_detail_but_keep_successful_details(self):
        client = FakeClient([page([1, 2], 2)], fail_details=[2])
        with tempfile.TemporaryDirectory() as d:
            first = self.run_export(client, d)
            self.assertEqual(first["detail_failures"], 1)
            client.fail_details.clear()
            client.calls.clear()
            second = self.run_export(client, d)
            self.assertEqual(second["detail_failures"], 0)
            self.assertNotIn(("detail", "1"), client.calls)
            self.assertIn(("detail", "2"), client.calls)
            self.assertIn(("page", 1), client.calls)

    def test_unrecognized_schema_is_not_an_empty_month(self):
        with tempfile.TemporaryDirectory() as d:
            report = self.run_export(FakeClient([{"unexpected": []}]), d)
            self.assertFalse(report["list_complete"])
            self.assertEqual(report["stop_reason"], "schema_error")
            self.assertTrue(list(Path(d).rglob("page-0001.json")))

    def test_short_page_does_not_stop_when_total_is_larger(self):
        with tempfile.TemporaryDirectory() as d:
            report = self.run_export(FakeClient([page([1], 2), page([2], 2)]), d)
            self.assertTrue(report["list_complete"])

    def test_empty_month_and_unknown_total_are_distinguished(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(self.run_export(FakeClient([page([], 0)]), d)["list_complete"])
            self.assertIsNone(self.run_export(FakeClient([{"list": []}]), d)["list_complete"])

    def test_real_empty_month_null_list_requires_zero_total(self):
        with tempfile.TemporaryDirectory() as d:
            report = self.run_export(FakeClient([{"times": 0, "total_mileages": "0.0", "list": None}]), d)
            self.assertTrue(report["list_complete"])
            bad = self.run_export(FakeClient([{"times": 20, "list": None}]), d)
            self.assertFalse(bad["list_complete"])
            self.assertEqual(bad["stop_reason"], "schema_error")

    def test_point_order_and_unknown_timestamps_preserved(self):
        points, invalid = parse_trail("116,39,12,2;bad;117,40,0;181,40,8")
        self.assertEqual([p["index"] for p in points], [0, 2])
        self.assertEqual(points[0]["extra_fields"], ["2"])
        self.assertIsNone(points[0]["timestamp"])
        self.assertEqual(invalid, 2)

    def test_month_validation_and_year_boundary(self):
        self.assertEqual(month_range("202512", "202602"), ["202512", "202601", "202602"])
        for start, end in [("202600", "202601"), ("202612", "202601"), ("202601x", "202602")]:
            with self.assertRaises(ValueError):
                month_range(start, end)


if __name__ == "__main__":
    unittest.main()

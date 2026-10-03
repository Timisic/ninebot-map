"""Offline merge and evidence-bounded audit of the latest monthly exports."""
from collections import Counter
from datetime import datetime, timezone



def summarize(archive):
    """Read only published snapshots. No account, raw cache or provider fields needed."""
    reports, rides, points, monthly = [], [], [], []
    pending = archive.pending_months()
    seen, duplicate_ids = set(), []
    quality = Counter()
    for snapshot in archive.read_months():
        report, month_rides, month_points = snapshot['coverage'], snapshot['rides'], snapshot['points']
        reports.append(report)
        for row in month_rides:
            rid = row['ride_id']
            if rid in seen:
                duplicate_ids.append(rid)
            seen.add(rid)
            quality[row['geometry_kind']] += 1
        rides.extend(month_rides)
        points.extend(month_points)
        monthly.append({"month": report["month"], "upstream_ride_count": report["upstream_ride_count"],
                        "listed_rides": report["listed_rides"], "upstream_distance_km": report["upstream_distance_km"],
                        "detail_distance_sum_km": round(sum(r["distance_km"] or 0 for r in month_rides), 3),
                        "rides_with_coordinates": report["rides_with_coordinates"],
                        "coordinate_points": report["coordinate_points"], "list_complete": report["list_complete"],
                        "pages_received": report["pages_received"], "detail_failures": report["detail_failures"]})
    totals = [r["upstream_distance_km"] for r in reports]
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "vehicle_key": archive.vehicle_key,
               "months": len(reports), "first_month": reports[0]["month"] if reports else None,
               "last_month": reports[-1]["month"] if reports else None,
               "upstream_ride_count": sum(r["upstream_ride_count"] for r in reports) if all(r["upstream_ride_count"] is not None for r in reports) else None,
               "listed_rides": len(rides), "unique_rides": len(seen), "duplicate_ride_ids": duplicate_ids,
               "upstream_month_distance_sum_km": round(sum(totals), 3) if all(v is not None for v in totals) else None,
               "detail_distance_sum_km": round(sum(r["distance_km"] or 0 for r in rides), 3),
               "missing_distance_values": sum(r["distance_km"] is None for r in rides),
               "list_complete": bool(reports) and all(r["list_complete"] is True for r in reports) and not duplicate_ids and not pending,
               "pending_months": pending,
               "details_failed": sum(r["detail_failures"] for r in reports),
               "rides_with_coordinates": sum(r["coordinate_count"] > 0 for r in rides),
               "coordinate_points": len(points), "geometry_kinds": dict(quality),
               "coordinate_system": "unverified", "point_timestamps": "unknown",
               "monthly": monthly}
    archive.write_report(summary, rides, points, monthly)
    return summary

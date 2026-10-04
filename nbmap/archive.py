"""Self-contained ride snapshots; one atomic pointer publishes each complete batch.

Readers need only the data directory and a non-secret vehicle key. Raw evidence,
Ninebot field interpretation and legacy conversion remain inside this module.
"""
import hashlib
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .storage import private_dir, read_json, write_csv, write_json

def number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def count(value):
    result = number(value)
    return int(result) if result is not None and result >= 0 and result.is_integer() else None


def key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:24]


def ride_id(row):
    if not isinstance(row, dict):
        raise ValueError("行程条目不是对象")
    value = row.get("travel_id", row.get("travelId", row.get("id")))
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ValueError("行程缺少 ID")
    return str(value)


def parse_trail(trail):
    """Known upstream shape: lon,lat,speed[,extra...];... . No invented times/CRS."""
    if trail in (None, ""):
        return [], 0
    if not isinstance(trail, str):
        return [], 1
    points, invalid = [], 0
    for index, chunk in enumerate(trail.split(";")):
        if not chunk.strip():
            continue
        fields = chunk.split(",")
        lon, lat = (number(fields[0]), number(fields[1])) if len(fields) >= 2 else (None, None)
        if lon is None or lat is None or not -180 <= lon <= 180 or not -90 <= lat <= 90 or (lon == lat == 0):
            invalid += 1
            continue
        points.append({"index": index, "longitude": lon, "latitude": lat,
                       "speed_raw": number(fields[2]) if len(fields) > 2 else None,
                       "timestamp": None, "extra_fields": fields[3:],
                       "coordinate_system": "unverified"})
    return points, invalid


def geometry_kind(detail, point_count):
    if not point_count:
        return "none"
    if detail.get("is_show_simple_point") in (True, 1, "1"):
        return "server_simplified"
    return "single_point" if point_count == 1 else "sampled_unverified"


def geometry_downgraded(old_kind, old_count, old_invalid, new_kind, new_count, new_invalid):
    rank = {'none': 0, 'single_point': 1, 'server_simplified': 2, 'sampled_unverified': 3}
    return (rank[new_kind] < rank[old_kind] or new_count < old_count or new_invalid > old_invalid)



def _month(value):
    if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", value):
        raise ValueError("月份格式应为 YYYYMM")
    return value


def _generation():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("档案引用越过了数据目录")
    return path


def _normalize(row, detail, state, month, detail_file=None):
    rid = ride_id(row)
    detail = detail or {}
    points, invalid = parse_trail(detail.get('trail'))
    kind = geometry_kind(detail, len(points))
    merged = {**row, **detail}
    ride = {'ride_id': rid, 'month': month,
            'start_time_raw': merged.get('start_time', merged.get('start_time_format')),
            'end_time_raw': merged.get('end_time', merged.get('end_time_format')),
            'distance_km': number(merged.get('mileages', merged.get('mileage'))),
            'duration_seconds': number(merged.get('duration')), 'energy_wh': number(merged.get('ec')),
            'declared_speed_raw': number(merged.get('speed')),
            'detail_status': state, 'coordinate_count': len(points), 'invalid_point_count': invalid,
            'geometry_kind': kind, 'server_simplified': detail.get('is_show_simple_point'),
            'server_simple_point_days': detail.get('show_simple_point_days'),
            'detail_file': detail_file}
    return ride, [{'ride_id': rid, 'month': month, **p, 'geometry_kind': kind} for p in points]


class RideArchive:
    """Publish and read consistent, normalized month snapshots on local storage."""
    def __init__(self, root, vehicle_key):
        if not re.fullmatch(r'[a-f0-9]{24}', vehicle_key):
            raise ValueError('无效的档案车辆标识')
        self.root = Path(root)
        self.vehicle_key = vehicle_key
        self.path = self.root / vehicle_key

    @classmethod
    def for_vehicle(cls, root, sn):
        return cls(root, key(sn))

    @classmethod
    def discover(cls, root):
        root = Path(root)
        return [cls(root, p.name) for p in sorted(root.glob('*'))
                if p.is_dir() and re.fullmatch(r'[a-f0-9]{24}', p.name)]

    def capture(self, month):
        return _Capture(self, _month(month))

    def publish(self, snapshot):
        snapshot = self._normalize_coverage(snapshot)
        self._validate(snapshot)
        month = snapshot['coverage']['month']
        generation = _generation()
        relative = f'snapshots/{month}/{generation}.json'
        private_dir(self.root)
        private_dir(self.path)
        write_json(self.path / relative, snapshot)
        # Commit point: before this single atomic replacement, readers keep the old batch.
        write_json(self.path / 'months' / f'{month}.json', {
            'schema_version': 2, 'snapshot': relative, 'month': month})
        return snapshot['coverage']

    @staticmethod
    def _normalize_coverage(snapshot):
        coverage = snapshot['coverage']
        # Provider spelling stays behind the archive seam, including older v2 files.
        return {**snapshot, 'coverage': {**coverage, 'upstream_distance_km':
            number(coverage['upstream_distance_km']) if 'upstream_distance_km' in coverage else
            number(coverage['upstream_summary'].get('total_mileages'))}}

    def _validate(self, snapshot):
        if snapshot.get('schema_version') != 2:
            raise ValueError('不支持的档案版本')
        report, rides, points = snapshot['coverage'], snapshot['rides'], snapshot['points']
        month = _month(report['month'])
        if report['vehicle_key'] != self.vehicle_key:
            raise ValueError('档案车辆不一致')
        ids = [r['ride_id'] for r in rides]
        if len(ids) != len(set(ids)) or report['listed_rides'] != len(rides):
            raise ValueError('档案行程数或唯一性不一致')
        per_ride = Counter(p['ride_id'] for p in points)
        if set(per_ride) - set(ids) or report['coordinate_points'] != len(points):
            raise ValueError('档案坐标归属或数量不一致')
        quality = {r['ride_id']: r['geometry_kind'] for r in rides}
        if any(r['month'] != month or r['coordinate_count'] != per_ride[r['ride_id']] for r in rides):
            raise ValueError('档案行程与坐标数量不一致')
        if any(p['month'] != month or p['geometry_kind'] != quality[p['ride_id']] for p in points):
            raise ValueError('档案坐标与轨迹类型不一致')
        if report['rides_with_coordinates'] != sum(bool(per_ride[rid]) for rid in ids):
            raise ValueError('含坐标行程数不一致')
        if report['list_complete'] is True and report['upstream_ride_count'] != len(rides):
            raise ValueError('清单完整性声明与行程数不一致')

    def read_month(self, month):
        month = _month(month)
        manifest = read_json(self.path / 'months' / f'{month}.json')
        if manifest.get('schema_version') != 2 or manifest.get('month') != month:
            raise ValueError('档案索引版本或月份不一致')
        snapshot = self._normalize_coverage(read_json(_inside(self.path, manifest['snapshot'])))
        self._validate(snapshot)
        if snapshot['coverage']['month'] != month:
            raise ValueError('索引与档案月份不一致')
        return snapshot

    def read_months(self):
        return [self.read_month(p.stem) for p in sorted((self.path / 'months').glob('20????.json'))]

    def pending_months(self):
        candidates = {p.name for parent in ('raw', 'exports') for p in (self.path / parent).glob('20????') if p.is_dir()}
        published = {p.stem for p in (self.path / 'months').glob('20????.json')}
        return sorted(candidates - published)

    def save_task(self, result):
        write_json(self.path / 'last-task.json', result)

    def import_legacy(self):
        """Explicit offline conversion; keep every old export and raw response intact."""
        imported = []
        for folder in sorted((self.path / 'exports').glob('20????')):
            month = _month(folder.name)
            if (self.path / 'months' / f'{month}.json').exists():
                continue
            if not all((folder / name).exists() for name in ('coverage.json', 'rides.json', 'points.json')):
                continue
            report = read_json(folder / 'coverage.json')
            old_rides = read_json(folder / 'rides.json')
            old_points = read_json(folder / 'points.json')
            grouped = {}
            for p in old_points:
                grouped.setdefault(p['ride_id'], []).append(p)
            rides, points = [], []
            for old in old_rides:
                if 'geometry_kind' in old and 'server_simple_point_days' in old:
                    # Already self-describing exports need no raw-detail dependency.
                    ride = {k: v for k, v in old.items() if k != 'list_raw'}
                    ps = [{**p, 'month': month, 'geometry_kind': ride['geometry_kind']} for p in grouped.get(old['ride_id'], [])]
                else:
                    detail_file = old.get('detail_file')
                    detail = read_json(_inside(self.root, detail_file)) if detail_file else {}
                    ride, ps = _normalize(old['list_raw'], detail, old['detail_status'], month, detail_file)
                    fields = ('index', 'longitude', 'latitude', 'speed_raw')
                    if [[p.get(k) for k in fields] for p in ps] != [[p.get(k) for k in fields] for p in grouped.get(old['ride_id'], [])]:
                        raise ValueError(f'{month} 旧导出与详情缓存的坐标不一致，已停止迁移')
                if ride['coordinate_count'] != old['coordinate_count'] or ride['distance_km'] != old['distance_km']:
                    raise ValueError(f'{month} 旧导出与详情缓存不一致，已停止迁移')
                rides.append(ride)
                points.extend(ps)
            self.publish({'schema_version': 2, 'coverage': report, 'rides': rides, 'points': points,
                          'origin': 'validated_legacy_import'})
            imported.append(month)
        return imported

    def write_report(self, summary, rides, points, monthly):
        """Materialize human-readable files, publishing their directory only when complete."""
        generation = _generation()
        output = private_dir(self.path / 'reports' / generation)
        write_json(output / 'summary.json', summary)
        write_json(output / 'rides.json', rides)
        write_csv(output / 'rides.csv', rides, ['ride_id', 'month', 'start_time_raw', 'end_time_raw', 'distance_km',
                  'duration_seconds', 'energy_wh', 'coordinate_count', 'geometry_kind', 'server_simple_point_days', 'detail_file'])
        write_csv(output / 'points.csv', points, ['ride_id', 'month', 'index', 'longitude', 'latitude', 'speed_raw',
                  'timestamp', 'coordinate_system', 'geometry_kind'])
        write_csv(output / 'months.csv', monthly, ['month', 'upstream_ride_count', 'listed_rides', 'upstream_distance_km',
                  'detail_distance_sum_km', 'rides_with_coordinates', 'coordinate_points', 'list_complete', 'pages_received', 'detail_failures'])
        write_json(self.path / 'reports' / 'latest.json', {'schema_version': 2, 'directory': generation})
        return output

    def report_path(self):
        manifest = read_json(self.path / 'reports' / 'latest.json')
        return _inside(self.path / 'reports', manifest['directory'])


class _Capture:
    """Internal acquisition adapter: evidence + cache + normalization for a month."""
    def __init__(self, archive, month):
        self.archive, self.month, self.run_id = archive, month, _generation()
        private_dir(archive.root)
        private_dir(archive.path)
        self.path = private_dir(archive.path / 'raw' / month / self.run_id)
        self.details = private_dir(archive.path / 'details')
        self.rides, self.points = [], []

    def save_page(self, page, payload):
        write_json(self.path / f'page-{page:04d}.json', payload)

    def detail(self, rid, fetch, refresh=False, retry_incomplete=False):
        cached = self.details / (key(rid) + '.json')
        previous = None
        if cached.exists():
            try:
                previous = read_json(cached)
                if not isinstance(previous, dict):
                    raise ValueError('未知缓存结构')
                points, invalid = parse_trail(previous.get('trail'))
                usable = points and not invalid and geometry_kind(previous, len(points)) == 'sampled_unverified'
                if 'duration' in previous and not number(previous['duration']):
                    usable = False
                if 'mileages' in previous and not number(previous['mileages']):
                    usable = False
                if points and not refresh and (not retry_incomplete or usable):
                    return previous, 'cached'
            except (ValueError, OSError):
                previous = None
        candidate = fetch()
        write_json(self.path / ('detail-' + key(rid) + '.json'), candidate)
        if not isinstance(candidate, dict) or not candidate:
            raise ValueError('未知详情结构')
        if previous:
            old_points, old_invalid = parse_trail(previous.get('trail'))
            new_points, new_invalid = parse_trail(candidate.get('trail'))
            if geometry_downgraded(geometry_kind(previous, len(old_points)), len(old_points), old_invalid,
                                   geometry_kind(candidate, len(new_points)), len(new_points), new_invalid):
                return previous, 'cached'
        write_json(cached, candidate)
        return candidate, 'fetched'

    def add(self, row, detail, state):
        evidence = str((self.details / (key(ride_id(row)) + '.json')).relative_to(self.archive.root)) if detail else None
        ride, points = _normalize(row, detail, state, self.month, evidence)
        self.rides.append(ride)
        self.points.extend(points)

    def finish(self, coverage):
        previous = None
        if (self.archive.path / 'months' / f'{self.month}.json').exists():
            previous = self.archive.read_month(self.month)
            old_rides = {r['ride_id']: r for r in previous['rides']}
            old_points = {}
            for p in previous['points']:
                old_points.setdefault(p['ride_id'], []).append(p)
            # The self-contained snapshot protects geometry even if caches were removed.
            retained = set()
            for i, ride in enumerate(self.rides):
                old = old_rides.get(ride['ride_id'])
                if old and geometry_downgraded(old['geometry_kind'], old['coordinate_count'], old['invalid_point_count'],
                                               ride['geometry_kind'], ride['coordinate_count'], ride['invalid_point_count']):
                    self.rides[i] = {**old, 'detail_status': ride['detail_status']}
                    retained.add(ride['ride_id'])
            self.points = [p for p in self.points if p['ride_id'] not in retained]
            self.points.extend(p for rid in retained for p in old_points.get(rid, []))
        states = Counter(r['detail_status'] for r in self.rides)
        report = {**coverage, 'schema_version': 2, 'month': self.month, 'vehicle_key': self.archive.vehicle_key,
                  'run_id': self.run_id, 'source': 'ninebot_cloud_unofficial', 'listed_rides': len(self.rides),
                  'details_fetched': states['fetched'], 'details_cached': states['cached'], 'detail_failures': states['unavailable'],
                  'rides_with_coordinates': sum(r['coordinate_count'] > 0 for r in self.rides),
                  'coordinate_points': len(self.points), 'invalid_points': sum(r['invalid_point_count'] for r in self.rides),
                  'coordinate_system': 'unverified', 'point_timestamps': 'not_provided_by_known_trail_format',
                  'raw_snapshot': str(self.path.relative_to(self.archive.root))}
        report['published'] = (coverage['list_complete'] is True and not coverage['errors']
                               and not report['detail_failures'] and not report['invalid_points'])
        if previous and not {r['ride_id'] for r in previous['rides']}.issubset({r['ride_id'] for r in self.rides}):
            report['published'] = False
        if previous:
            old_distance = number(previous['coverage'].get('upstream_distance_km'))
            new_distance = number(coverage['upstream_summary'].get('total_mileages'))
            if old_distance is not None and (new_distance is None or new_distance + 1e-6 < old_distance):
                report['published'] = False
        if not report['published']:
            report['publication_reason'] = 'incomplete_or_regressing_capture'
        snapshot = {'schema_version': 2, 'coverage': report, 'rides': self.rides, 'points': self.points}
        write_json(self.path / 'coverage.json', report)
        if not report['published']:
            # Evidence and successful detail caches survive, but a failed list request
            # never replaces a previously readable month with an empty archive.
            return report
        return self.archive.publish(snapshot)

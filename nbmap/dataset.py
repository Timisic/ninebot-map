"""Portable, provider-independent dataset for statistics and future map consumers.

All rides retain their mileage. Only selected, sampled tracks carry coordinates.
The authoritative format is dataset.json, not the convenience CSV tables.
"""
import hashlib
import math
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .storage import private_dir, read_json, write_csv, write_json

FORMAT = 'ride-dataset'
VERSION = 1
KINDS = {'sampled_unverified': 'sampled', 'server_simplified': 'simplified',
         'single_point': 'single_point', 'none': 'missing'}
STATUSES = {'included', 'before_map_start', 'unknown_start_time', 'simplified', 'insufficient_points'}


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('无效的 IANA 时区') from None


def _aware(value):
    if not isinstance(value, str):
        raise ValueError('时间必须为带时区的 ISO 8601 字符串')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('时间必须为带时区的 ISO 8601 字符串') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('时间必须显式指定时区偏移')
    return result


def _cutoff(value, tz):
    if value is None:
        return None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            return datetime.fromisoformat(value).replace(tzinfo=tz)
        except ValueError:
            raise ValueError('无效的地图起始日期') from None
    return _aware(value).astimezone(tz)


def _timestamp(value, tz):
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10_000_000_000 else value
            result = datetime.fromtimestamp(seconds, tz)
        elif isinstance(value, str):
            result = _aware(value).astimezone(tz)
        else:
            return None
        return result.isoformat() if 2000 <= result.year <= 2200 else None
    except (ValueError, OverflowError, OSError):
        return None


def _nonnegative(value):
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def _meters(km):
    value = _nonnegative(km)
    return round(float(Decimal(str(value)) * 1000), 6) if value is not None else None


def _sum_known(values):
    return round(sum(v for v in values if v is not None), 6)


def _distance(values):
    return _sum_known(values) if all(v is not None for v in values) else None


def _summary(rides, tracks, months):
    selected = [r for r in rides if r['map_status'] == 'included']
    distances = [r['distance_m'] for r in rides]
    map_distances = [r['distance_m'] for r in selected]
    return {'ride_count': len(rides), 'total_distance_m': _distance(distances),
            'known_distance_m': _sum_known(distances), 'missing_distance_count': distances.count(None),
            'reported_month_distance_m': _distance([m['reported_distance_m'] for m in months]),
            'map_ride_count': len(selected), 'map_distance_m': _distance(map_distances),
            'map_point_count': sum(len(t['points']) for t in tracks),
            'map_exclusions': dict(sorted(Counter(r['map_status'] for r in rides if r['map_status'] != 'included').items()))}


def build_dataset(snapshots, *, dataset_id, map_from=None, timezone_name='Asia/Shanghai'):
    """Convert self-contained archive records without reading credentials or raw caches."""
    tz = _zone(timezone_name)
    since = _cutoff(map_from, tz)
    rides, tracks, months, sources, seen = [], [], [], [], set()
    for snapshot in snapshots:
        coverage = snapshot['coverage']
        grouped = defaultdict(list)
        for point in snapshot['points']:
            grouped[point['ride_id']].append(point)
        for row in snapshot['rides']:
            source_id = str(row['ride_id'])
            uid = 'r_' + hashlib.sha256((dataset_id + '\0' + source_id).encode()).hexdigest()[:24]
            if uid in seen:
                raise ValueError('档案存在跨月重复行程，停止生成数据集')
            seen.add(uid)
            start, end = _timestamp(row.get('start_time_raw'), tz), _timestamp(row.get('end_time_raw'), tz)
            pts = sorted(grouped[source_id], key=lambda p: p['index'])
            kind = KINDS[row['geometry_kind']]
            if start is None:
                status = 'unknown_start_time'
            elif since is not None and _aware(start) < since:
                status = 'before_map_start'
            elif kind == 'simplified':
                status = 'simplified'
            elif kind != 'sampled' or len(pts) < 2:
                status = 'insufficient_points'
            else:
                status = 'included'
            rides.append({'id': uid, 'source_month': coverage['month'],
                          'started_at': start, 'ended_at': end, 'distance_m': _meters(row.get('distance_km')),
                          'duration_s': _nonnegative(row.get('duration_seconds')), 'energy_wh': _nonnegative(row.get('energy_wh')),
                          'track_kind': kind, 'source_point_count': len(pts), 'map_status': status})
            if status == 'included':
                tracks.append({'ride_id': uid, 'points': [
                    {'sequence': index, 'longitude': p['longitude'], 'latitude': p['latitude'],
                     'recorded_at': None, 'speed_mps': None} for index, p in enumerate(pts)]})
        month_rows = rides[-len(snapshot['rides']):] if snapshot['rides'] else []
        months.append({'month': coverage['month'], 'reported_ride_count': coverage.get('upstream_ride_count'),
                       'reported_distance_m': _meters(coverage.get('upstream_distance_km')),
                       'listed_ride_count': len(month_rows), 'listed_distance_m': _distance([r['distance_m'] for r in month_rows]),
                       'list_complete': coverage.get('list_complete')})
        sources.append({'month': coverage['month'], 'snapshot_id': coverage['run_id']})
    rides.sort(key=lambda r: (r['started_at'] or '', r['id']))
    tracks_by_id = {t['ride_id']: t for t in tracks}
    tracks = [tracks_by_id[r['id']] for r in rides if r['id'] in tracks_by_id]
    result = {'format': FORMAT, 'schema_version': VERSION, 'dataset_id': dataset_id,
              'generated_at': datetime.now(timezone.utc).isoformat(), 'timezone': timezone_name,
              'coordinate_system': 'unverified',
              'selection': {'statistics_scope': 'all_rides', 'map_from': since.isoformat() if since else None,
                            'map_rule': 'ride_start_at_or_after', 'allowed_track_kinds': ['sampled']},
              'provenance': {'source': 'normalized_ride_archive', 'snapshot_ids': sources},
              'rides': rides, 'tracks': tracks, 'months': months, 'summary': _summary(rides, tracks, months)}
    validate_dataset(result)
    return result


def _number(value, nullable=False):
    if value is None and nullable:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('数值必须是非负有限数或允许的 null')


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('计数必须是非负整数')


def validate_dataset(data):
    """Validate the public contract plus relationships, scopes and reported totals."""
    try:
        if data['format'] != FORMAT or type(data['schema_version']) is not int or data['schema_version'] != VERSION:
            raise ValueError('不支持的数据集格式或版本')
        if not isinstance(data['dataset_id'], str) or not data['dataset_id']:
            raise ValueError('数据集缺少标识')
        _zone(data['timezone'])
        _aware(data['generated_at'])
        if data['coordinate_system'] not in ('unverified', 'wgs84', 'gcj02', 'bd09'):
            raise ValueError('未知坐标系声明')
        selection = data['selection']
        if selection['statistics_scope'] != 'all_rides' or selection['map_rule'] != 'ride_start_at_or_after' or selection['allowed_track_kinds'] != ['sampled']:
            raise ValueError('不支持的范围约定')
        since = _aware(selection['map_from']) if selection['map_from'] is not None else None
        for name in ('rides', 'tracks', 'months'):
            if not isinstance(data[name], list):
                raise ValueError(f'{name} 必须是数组')
        if not isinstance(data['provenance']['source'], str) or not isinstance(data['provenance']['snapshot_ids'], list):
            raise ValueError('缺少来源说明')
        for source in data['provenance']['snapshot_ids']:
            if not re.fullmatch(r'20\d{2}(0[1-9]|1[0-2])', source['month']) or not isinstance(source['snapshot_id'], str):
                raise ValueError('来源快照标识无效')
        rides = {}
        for r in data['rides']:
            if not isinstance(r['id'], str) or not r['id'] or r['id'] in rides:
                raise ValueError('行程标识为空或重复')
            rides[r['id']] = r
            if not re.fullmatch(r'20\d{2}(0[1-9]|1[0-2])', r['source_month']):
                raise ValueError('行程月份格式无效')
            for field in ('started_at', 'ended_at'):
                if r[field] is not None:
                    _aware(r[field])
            if r['started_at'] is not None and r['ended_at'] is not None and _aware(r['ended_at']) < _aware(r['started_at']):
                raise ValueError('行程结束时间早于开始时间')
            for field in ('distance_m', 'duration_s', 'energy_wh'):
                _number(r[field], nullable=True)
            _integer(r['source_point_count'])
            if r['track_kind'] not in set(KINDS.values()) or r['map_status'] not in STATUSES:
                raise ValueError('行程质量或地图状态无效')
            if r['started_at'] is None:
                expected = 'unknown_start_time'
            elif since is not None and _aware(r['started_at']) < since:
                expected = 'before_map_start'
            elif r['track_kind'] == 'simplified':
                expected = 'simplified'
            elif r['track_kind'] != 'sampled' or r['source_point_count'] < 2:
                expected = 'insufficient_points'
            else:
                expected = 'included'
            if r['map_status'] != expected:
                raise ValueError('地图筛选状态与日期/质量条件不一致')
        track_ids = set()
        for track in data['tracks']:
            rid = track['ride_id']
            if rid not in rides or rid in track_ids or rides[rid]['map_status'] != 'included':
                raise ValueError('地图轨迹无对应行程、重复或超出筛选范围')
            track_ids.add(rid)
            if not isinstance(track['points'], list):
                raise ValueError('轨迹坐标必须为数组')
            if len(track['points']) != rides[rid]['source_point_count'] or len(track['points']) < 2:
                raise ValueError('轨迹点数量与行程声明不一致')
            for index, point in enumerate(track['points']):
                _integer(point['sequence'])
                if point['sequence'] != index or isinstance(point['sequence'], bool):
                    raise ValueError('轨迹顺序必须从 0 连续编号')
                for name, limit in [('longitude', 180), ('latitude', 90)]:
                    value = point[name]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
                        raise ValueError('无效经纬度')
                if point['recorded_at'] is not None:
                    _aware(point['recorded_at'])
                _number(point['speed_mps'], nullable=True)
        if track_ids != {r['id'] for r in rides.values() if r['map_status'] == 'included'}:
            raise ValueError('缺少应导出的地图轨迹')
        grouped = defaultdict(list)
        for r in rides.values():
            grouped[r['source_month']].append(r)
        months = set()
        for month in data['months']:
            name = month['month']
            if not re.fullmatch(r'20\d{2}(0[1-9]|1[0-2])', name) or name in months:
                raise ValueError('月份无效或重复')
            months.add(name)
            if month['reported_ride_count'] is not None:
                _integer(month['reported_ride_count'])
            _number(month['reported_distance_m'], nullable=True)
            _integer(month['listed_ride_count'])
            _number(month['listed_distance_m'], nullable=True)
            if month['list_complete'] is not None and type(month['list_complete']) is not bool:
                raise ValueError('清单覆盖声明无效')
            if month['listed_ride_count'] != len(grouped[name]) or month['listed_distance_m'] != _distance([r['distance_m'] for r in grouped[name]]):
                raise ValueError('月份统计与行程不一致')
            if month['list_complete'] is True and month['reported_ride_count'] != month['listed_ride_count']:
                raise ValueError('月份完整性声明不一致')
        if set(grouped) - months:
            raise ValueError('行程缺少对应月份记录')
        for field in ('ride_count', 'missing_distance_count', 'map_ride_count', 'map_point_count'):
            _integer(data['summary'][field])
        for field in ('total_distance_m', 'known_distance_m', 'reported_month_distance_m', 'map_distance_m'):
            _number(data['summary'][field], nullable=field != 'known_distance_m')
        if not isinstance(data['summary']['map_exclusions'], dict):
            raise ValueError('地图排除统计必须为对象')
        for value in data['summary']['map_exclusions'].values():
            _integer(value)
        if data['summary'] != _summary(data['rides'], data['tracks'], data['months']):
            raise ValueError('汇总与数据内容不一致')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('数据集缺少必需字段或字段类型错误') from None
    return data


def prepare(archive, *, map_from=None, timezone_name='Asia/Shanghai', save_settings=True):
    dataset = build_dataset(archive.read_months(), dataset_id='rides_' + archive.vehicle_key,
                            map_from=map_from, timezone_name=timezone_name)
    parent = archive.path / 'prepared'
    generation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex
    directory = private_dir(parent / generation)
    write_json(directory / 'dataset.json', dataset)
    write_csv(directory / 'rides.csv', dataset['rides'], ['id', 'source_month', 'started_at', 'ended_at', 'distance_m',
              'duration_s', 'energy_wh', 'track_kind', 'source_point_count', 'map_status'])
    point_rows = [{'ride_id': t['ride_id'], **p} for t in dataset['tracks'] for p in t['points']]
    write_csv(directory / 'map-points.csv', point_rows, ['ride_id', 'sequence', 'longitude', 'latitude', 'recorded_at', 'speed_mps'])
    write_csv(directory / 'months.csv', dataset['months'], ['month', 'reported_ride_count', 'reported_distance_m',
              'listed_ride_count', 'listed_distance_m', 'list_complete'])
    write_json(directory / 'summary.json', dataset['summary'])
    write_json(parent / 'latest.json', {'format': FORMAT, 'schema_version': VERSION, 'directory': generation})
    # Stable local entrypoint for a running map; replacement is atomic.
    write_json(parent / 'dataset.json', dataset)
    if save_settings:
        write_json(archive.path / 'dataset-settings.json', {'map_from': dataset['selection']['map_from'], 'timezone': timezone_name})
    return directory


def prepare_configured(archive):
    path = archive.path / 'dataset-settings.json'
    if not path.exists():
        return None
    settings = read_json(path)
    return prepare(archive, map_from=settings['map_from'], timezone_name=settings['timezone'], save_settings=False)

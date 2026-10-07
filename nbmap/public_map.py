"""Allowlisted public map data and static assets, separate from private archives."""
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .dataset import validate_dataset
from .stops import stop_durations
from .map_server import MAX_BYTES
from .viewer_resources import WEB_ROOT, viewer_resources

FORMAT = 'public-ride-map'
NAME_TRIM_CHARACTERS = '\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
SUMMARY_FIELDS = {'ride_count', 'total_distance_m', 'known_distance_m', 'missing_distance_count',
                  'reported_month_distance_m', 'map_ride_count', 'map_distance_m', 'map_point_count', 'map_exclusions'}


def public_dataset(dataset, updated_at=None, place_annotations=None):
    validate_dataset(dataset)
    zone = ZoneInfo(dataset['timezone'])
    rides = {ride['id']: ride for ride in dataset['rides']}
    stops = stop_durations(dataset)
    result = {'format': FORMAT, 'schema_version': 1, 'dataset_id': 'ninebot-public-map',
              'updated_at': updated_at or dataset['generated_at'], 'timezone': dataset['timezone'],
              'coordinate_system': dataset['coordinate_system'],
              'summary': {name: dataset['summary'][name] for name in sorted(SUMMARY_FIELDS)}, 'tracks': []}
    for track in dataset['tracks']:
        ride = rides[track['ride_id']]
        result['tracks'].append({'id': ride['id'] if re.fullmatch(r'r_[a-f0-9]{24}', ride['id']) else 'r_' + hashlib.sha256(ride['id'].encode()).hexdigest()[:24],
                                'date': datetime.fromisoformat(ride['started_at']).astimezone(zone).date().isoformat(),
                                'distance_m': ride['distance_m'], 'stop_duration_s': stops[ride['id']],
                                'points': [[point['longitude'], point['latitude']] for point in track['points']]})
    if place_annotations is not None:
        result['place_annotations'] = place_annotations
    validate_public(result)
    return result


def validate_public(data):
    from math import isfinite
    def require(value, message):
        if not value:
            raise ValueError(message)
    def number(value, nullable=False):
        return (nullable and value is None) or (type(value) in (int, float) and isfinite(value) and value >= 0)
    def integer(value):
        return type(value) is int and 0 <= value <= 9007199254740991
    fields = {'format', 'schema_version', 'dataset_id', 'updated_at', 'timezone', 'coordinate_system', 'summary', 'tracks'}
    require(isinstance(data, dict) and fields <= set(data) <= fields | {'place_annotations'}, '公开地图字段不符合白名单')
    if 'place_annotations' in data:
        annotations = data['place_annotations']
        require(isinstance(annotations, dict) and set(annotations) <= {'labels', 'merges'}, '公开地点标注字段无效')
        labels, merges = annotations.get('labels', {}), annotations.get('merges', [])
        valid_id = lambda value: isinstance(value, str) and re.fullmatch(r'r_[a-f0-9]{24}', value)
        require(isinstance(labels, dict) and len(labels) <= 25000, '公开地点名称超限或无效')
        require(all(valid_id(key) and isinstance(value, str) and value == value.strip(NAME_TRIM_CHARACTERS) and 0 < len(value) <= 40 for key, value in labels.items()), '公开地点名称无效')
        require(isinstance(merges, list) and len(merges) <= 25000, '公开地点合并超限或无效')
        member_count = 0
        for group in merges:
            require(isinstance(group, dict) and set(group) == {'anchorId', 'memberIds'}, '公开地点合并字段无效')
            members = group['memberIds']
            require(isinstance(members, list) and 2 <= len(members) <= 25000 and all(valid_id(value) for value in members), '公开地点合并成员无效')
            member_count += len(members)
            require(member_count <= 25000 and len(set(members)) == len(members) and valid_id(group['anchorId']) and group['anchorId'] in members, '公开地点合并锚点、成员重复或总量无效')
    require(data['format'] == FORMAT and type(data['schema_version']) is int and data['schema_version'] == 1 and data['dataset_id'] == 'ninebot-public-map', '公开地图格式无效')
    require(isinstance(data['updated_at'], str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)', data['updated_at']), '更新时间必须使用完整 ISO 8601 格式')
    updated = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))
    require(updated.tzinfo is not None, '更新时间必须带时区')
    ZoneInfo(data['timezone'])
    require(data['coordinate_system'] in ('unverified', 'wgs84', 'gcj02', 'bd09'), '坐标来源声明无效')
    summary = data['summary']
    require(isinstance(summary, dict) and set(summary) == SUMMARY_FIELDS, '公开汇总字段无效')
    for name in ('ride_count', 'map_ride_count', 'map_point_count', 'missing_distance_count'):
        require(integer(summary[name]), '公开计数无效')
    for name in ('total_distance_m', 'known_distance_m', 'reported_month_distance_m', 'map_distance_m'):
        require(number(summary[name], True), '公开里程无效')
    exclusions = summary['map_exclusions']
    require(isinstance(exclusions, dict) and set(exclusions) <= {'before_map_start', 'unknown_start_time', 'simplified', 'insufficient_points'} and all(integer(n) for n in exclusions.values()), '公开排除计数无效')
    require(isinstance(data['tracks'], list) and len(data['tracks']) <= 25000, '公开轨迹超限')
    ids, count, distances = set(), 0, []
    min_lon = min_lat = float('inf')
    max_lon = max_lat = float('-inf')
    for track in data['tracks']:
        require(isinstance(track, dict) and {'id', 'date', 'distance_m', 'points'} <= set(track) <= {'id', 'date', 'distance_m', 'points', 'stop_duration_s'}, '公开轨迹字段无效')
        require(isinstance(track['id'], str) and re.fullmatch(r'r_[a-f0-9]{24}', track['id']) and track['id'] not in ids, '公开轨迹标识无效')
        ids.add(track['id'])
        require(isinstance(track['date'], str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', track['date']), '公开日期无效')
        datetime.strptime(track['date'], '%Y-%m-%d')
        require(number(track['distance_m'], True), '公开轨迹里程无效')
        require('stop_duration_s' not in track or (number(track['stop_duration_s'], True) and (track['stop_duration_s'] is None or track['stop_duration_s'] <= 86400)), '公开停留时长无效')
        distances.append(track['distance_m'])
        require(isinstance(track['points'], list) and len(track['points']) >= 2, '公开轨迹点无效')
        count += len(track['points'])
        require(count <= 300000, '公开轨迹点超限')
        for point in track['points']:
            require(isinstance(point, list) and len(point) == 2 and all(type(n) in (float, int) and isfinite(n) for n in point) and abs(point[0]) <= 180 and abs(point[1]) <= 90, '公开经纬度无效')
            min_lon, max_lon = min(min_lon, point[0]), max(max_lon, point[0])
            min_lat, max_lat = min(min_lat, point[1]), max(max_lat, point[1])
    require(not count or (max_lon - min_lon <= 3 and max_lat - min_lat <= 3 and max(abs(min_lat), abs(max_lat)) <= 75), '公开地图超出支持的区域范围')
    require(summary['map_ride_count'] == len(ids) and summary['map_point_count'] == count, '公开轨迹与汇总不一致')
    require(summary['ride_count'] == len(ids) + sum(exclusions.values()), '公开历史与范围不一致')
    distance = None if None in distances else round(sum(distances), 6)
    require(summary['map_distance_m'] == distance, '公开地图里程不一致')
    missing = distances.count(None)
    known = round(sum(value for value in distances if value is not None), 6)
    excluded = summary['ride_count'] - len(ids)
    require(missing <= summary['missing_distance_count'] <= missing + excluded, '公开缺失里程计数不一致')
    require(number(summary['known_distance_m']) and summary['known_distance_m'] >= known, '公开历史里程小于地图已知里程')
    require(excluded != 0 or summary['known_distance_m'] == known, '公开已知里程不一致')
    require((summary['missing_distance_count'] > 0 and summary['total_distance_m'] is None) or (summary['missing_distance_count'] == 0 and summary['total_distance_m'] == summary['known_distance_m']), '公开总里程与缺失状态不一致')
    return data


def publish_dataset(data, target):
    validate_public(data)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('公开地图超过大小上限')
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        previous = validate_public(json.loads(target.read_bytes()))
        if datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00')) < datetime.fromisoformat(previous['updated_at'].replace('Z', '+00:00')):
            raise ValueError('较旧数据不能覆盖当前公开地图')
        if target.read_bytes() == raw:
            return target
    fd, temporary = tempfile.mkstemp(prefix='.dataset-', suffix='.json', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def export_site(dataset, output, updated_at=None):
    public = public_dataset(dataset, updated_at)
    output = Path(output)
    if output.exists():
        raise ValueError('静态输出目录已存在，请使用新的目录；数据更新使用 publish_dataset。')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.map-site-', dir=output.parent))
    try:
        for filename, (body, _) in viewer_resources(WEB_ROOT).files.items():
            target = temporary / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        for relative in ('leaflet/LICENSE', 'gcoord/LICENSE', 'lucide/LICENSE', 'pinhead/LICENSE', 'pinhead/PROVENANCE.md'):
            target = temporary / 'vendor' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(WEB_ROOT / 'vendor' / relative, target)
        publish_dataset(public, temporary / 'dataset.json')
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary)
        raise
    return output

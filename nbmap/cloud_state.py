"""Authenticated, compact cloud checkpoints and conservative local archive imports."""
import copy
import gzip
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .archive import RideArchive, geometry_downgraded
from .dataset import build_dataset, prepare_configured, prepare
from .storage import read_json, write_json

FORMAT = 'ninebot-cloud-state'
MAX_BYTES = 256 * 1024 * 1024
PRIVATE_FILES = ('config.json', 'tokens.json', 'preferences.json', 'schedule.json', 'schedule-state.json', 'last-error.json')
FILE_PATTERN = re.compile(r'(?:sessions/(?:config|tokens|preferences|schedule|schedule-state|last-error)\.json|'
                          r'data/[a-f0-9]{24}/(?:dataset-settings\.json|months/20\d{4}\.json|'
                          r'snapshots/20\d{4}/[a-zA-Z0-9_-]+\.json|details/[a-f0-9]{24}\.json))')


def seal(payload, key):
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('云端档案超过大小上限')
    return Fernet(key).encrypt(gzip.compress(raw, mtime=0))


def unseal(blob, key):
    try:
        compressed = Fernet(key).decrypt(blob)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as source:
            raw = source.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('云端档案超过大小上限')
        payload = json.loads(raw)
        if payload['format'] != FORMAT or payload['version'] != 1 or not isinstance(payload['files'], dict):
            raise ValueError('未知云端档案格式')
        if any(not FILE_PATTERN.fullmatch(path) for path in payload['files']):
            raise ValueError('云端档案包含不允许的路径')
        return payload
    except (InvalidToken, KeyError, TypeError, UnicodeError, OSError):
        raise ValueError('云端档案认证或格式校验失败，未改动本机档案。') from None


def checkpoint(config, data, revision):
    files = {}
    for name in PRIVATE_FILES:
        path = config / name
        if path.exists():
            files['sessions/' + name] = read_json(path)
    for archive in RideArchive.discover(data):
        archive.read_months()  # Validate each snapshot before encrypting it.
        for pointer in sorted((archive.path / 'months').glob('*.json')):
            manifest = read_json(pointer)
            snapshot = archive.path / manifest['snapshot']
            for path in (pointer, snapshot):
                files['data/' + str(path.relative_to(data))] = read_json(path)
        for path in (archive.path / 'details').glob('*.json'):
            files['data/' + str(path.relative_to(data))] = read_json(path)
        settings = archive.path / 'dataset-settings.json'
        if settings.exists():
            files['data/' + str(settings.relative_to(data))] = read_json(settings)
    return {'format': FORMAT, 'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
            'credential_revision': revision, 'files': files}


def restore(payload, root):
    if any(not FILE_PATTERN.fullmatch(relative) for relative in payload['files']):
        raise ValueError('云端档案路径不允许')
    for relative, value in payload['files'].items():
        write_json(root / relative, value)


def merge_snapshot(previous, incoming):
    if previous is None:
        return copy.deepcopy(incoming)
    result = copy.deepcopy(incoming)
    old = {r['ride_id']: r for r in previous['rides']}
    new = {r['ride_id']: r for r in incoming['rides']}
    selected = {rid: (ride, previous) for rid, ride in old.items()}
    for rid, ride in new.items():
        prior = old.get(rid)
        downgrade = prior and geometry_downgraded(prior['geometry_kind'], prior['coordinate_count'], prior['invalid_point_count'],
                                                  ride['geometry_kind'], ride['coordinate_count'], ride['invalid_point_count'])
        if not downgrade:
            if prior:
                ride = {**ride}
                for field in ('distance_km', 'duration_seconds', 'energy_wh'):
                    if ride.get(field) is None:
                        ride[field] = prior.get(field)
                if prior.get('distance_km') is not None and ride['distance_km'] < prior['distance_km']:
                    ride['distance_km'] = prior['distance_km']
                if not ride.get('duration_seconds') and prior.get('duration_seconds'):
                    ride['duration_seconds'] = prior['duration_seconds']
            selected[rid] = (ride, incoming)
    result['rides'] = [copy.deepcopy(pair[0]) for pair in selected.values()]
    result['points'] = []
    for rid, (_, snapshot) in selected.items():
        result['points'].extend(copy.deepcopy(p) for p in snapshot['points'] if p['ride_id'] == rid)
    coverage = result['coverage']
    counts = Counter(r['detail_status'] for r in result['rides'])
    coverage.update(listed_rides=len(result['rides']), coordinate_points=len(result['points']),
                    rides_with_coordinates=sum(r['coordinate_count'] > 0 for r in result['rides']),
                    invalid_points=sum(r['invalid_point_count'] for r in result['rides']),
                    details_fetched=counts['fetched'], details_cached=counts['cached'], detail_failures=counts['unavailable'],
                    list_complete=coverage['list_complete'] is True and coverage['upstream_ride_count'] == len(result['rides']))
    prior_distance = previous['coverage'].get('upstream_distance_km')
    if prior_distance is not None and (coverage.get('upstream_distance_km') is None or coverage['upstream_distance_km'] < prior_distance):
        coverage['upstream_distance_km'] = prior_distance
        coverage['list_complete'] = False
    result['origin'] = 'validated_local_cloud_merge'
    return result


def import_archives(remote_data, local_data):
    plans = []
    # Prepare and validate every combined dataset before publishing any local month.
    for remote in RideArchive.discover(remote_data):
        local = RideArchive(local_data, remote.vehicle_key)
        old = {s['coverage']['month']: s for s in local.read_months()}
        merged = dict(old)
        updates = []
        for incoming in remote.read_months():
            month = incoming['coverage']['month']
            snapshot = merge_snapshot(old.get(month), incoming)
            local._validate(snapshot)
            merged[month] = snapshot
            updates.append(snapshot)
        settings_path = local.path / 'dataset-settings.json'
        remote_settings = remote.path / 'dataset-settings.json'
        settings = read_json(settings_path) if settings_path.exists() else (read_json(remote_settings) if remote_settings.exists() else {'map_from': None, 'timezone': 'Asia/Shanghai'})
        build_dataset([merged[m] for m in sorted(merged)], dataset_id='rides_' + local.vehicle_key,
                      map_from=settings['map_from'], timezone_name=settings['timezone'])
        plans.append((local, updates, settings))
    outputs = []
    for local, updates, settings in plans:
        for snapshot in updates:
            local.publish(snapshot)
        directory = prepare(local, map_from=settings['map_from'], timezone_name=settings['timezone'])
        outputs.append(local.path / 'prepared/dataset.json')
    return outputs

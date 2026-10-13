"""Shared place-name ledger stored beside a dataset snapshot."""
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# Local datasets keep the ride id select() already uses. Public tracks use r_ plus 24 hex digits.
_RIDE_ID = re.compile(r'(?:r_[a-f0-9]{24}|[A-Za-z0-9][A-Za-z0-9_-]{0,199})\Z')
_MAX_KEYS = 25000
MAX_PLACE_BODY = 1024 * 1024


@dataclass(frozen=True)
class ServedDataset:
    body: bytes
    etag: str


class PlaceNameRejected(ValueError):
    def __init__(self, status, public_message):
        super().__init__(public_message)
        self.status = status
        self.public_message = public_message


class PlaceNameUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('名称没有保存，请重试。')
        self.status = 500
        self.public_message = '名称没有保存，请重试。'


@dataclass(frozen=True)
class _Ledger:
    overrides: dict
    cleared: frozenset


def _stored_place_name(value):
    from .public_map import stored_place_name
    return stored_place_name(value)


def _ledger_path(dataset_path):
    path = Path(dataset_path)
    if path.name == 'dataset.json' and path.parent.name != 'prepared' and path.parent.parent.name == 'prepared':
        return path.parent.parent / 'place-names.json'
    return path.parent / 'place-names.json'


def _canonical(ledger):
    payload = {'cleared': sorted(ledger.cleared), 'overrides': ledger.overrides}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _project(base, ledger):
    projected = {ride_id: name for ride_id, name in base.items() if ride_id not in ledger.cleared}
    projected.update(ledger.overrides)
    return projected


def _parse_ledger(raw):
    if raw is None:
        return _Ledger({}, frozenset())
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise PlaceNameUnavailable from None
    if not isinstance(data, dict) or set(data) != {'cleared', 'overrides'}:
        raise PlaceNameUnavailable
    overrides, cleared = data['overrides'], data['cleared']
    if not isinstance(overrides, dict) or not isinstance(cleared, list):
        raise PlaceNameUnavailable
    parsed = {}
    for ride_id, name in overrides.items():
        if not isinstance(ride_id, str) or _RIDE_ID.fullmatch(ride_id) is None:
            raise PlaceNameUnavailable
        try:
            parsed[ride_id] = _stored_place_name(name)
        except ValueError:
            raise PlaceNameUnavailable from None
    if any(not isinstance(ride_id, str) or _RIDE_ID.fullmatch(ride_id) is None for ride_id in cleared):
        raise PlaceNameUnavailable
    cleared_ids = frozenset(cleared)
    if len(cleared_ids) != len(cleared) or parsed.keys() & cleared_ids:
        raise PlaceNameUnavailable
    return _Ledger(parsed, cleared_ids)


def _parse_request(request_body):
    try:
        data = json.loads(request_body)
    except (ValueError, UnicodeError):
        raise PlaceNameRejected(400, '名称无效。') from None
    if not isinstance(data, dict) or set(data) != {'rideIds', 'name'}:
        raise PlaceNameRejected(400, '名称无效。')
    ride_ids, name = data['rideIds'], data['name']
    if not isinstance(ride_ids, list) or any(not isinstance(ride_id, str) or _RIDE_ID.fullmatch(ride_id) is None for ride_id in ride_ids):
        raise PlaceNameRejected(400, '名称无效。')
    if len(ride_ids) != len(set(ride_ids)) or not ride_ids:
        raise PlaceNameRejected(400, '名称无效。')
    if len(ride_ids) > _MAX_KEYS:
        raise PlaceNameRejected(413, '名称太多。')
    if name is None:
        return ride_ids, None
    try:
        return ride_ids, _stored_place_name(name)
    except ValueError:
        raise PlaceNameRejected(400, '名称无效。') from None


def _apply(ledger, ride_ids, name):
    overrides = dict(ledger.overrides)
    cleared = set(ledger.cleared)
    for ride_id in ride_ids:
        overrides.pop(ride_id, None)
        cleared.discard(ride_id)
        if name is None:
            cleared.add(ride_id)
        else:
            overrides[ride_id] = name
    return _Ledger(overrides, frozenset(cleared))


def _base(dataset):
    try:
        data = json.loads(dataset)
    except (ValueError, UnicodeError):
        raise PlaceNameUnavailable from None
    if not isinstance(data, dict) or data.get('format') != 'public-ride-map' or not isinstance(data.get('place_annotations'), dict):
        return {}
    labels = data['place_annotations'].get('labels', {})
    if not isinstance(labels, dict):
        return {}
    return {ride_id: name for ride_id, name in labels.items() if isinstance(ride_id, str) and isinstance(name, str)}


def _serve(dataset, ledger):
    try:
        data = json.loads(dataset)
    except (ValueError, UnicodeError):
        raise ValueError('dataset') from None
    if not isinstance(data, dict):
        raise ValueError('dataset')
    annotations = data.get('place_annotations')
    publisher = data.get('format') == 'public-ride-map' and isinstance(annotations, dict)
    base = {}
    if publisher:
        labels = annotations.get('labels', {})
        base = labels if isinstance(labels, dict) else {}
        base = {ride_id: name for ride_id, name in base.items() if isinstance(ride_id, str) and isinstance(name, str)}
    else:
        data.pop('place_annotations', None)
    projected = _project(base, ledger)
    if publisher:
        served = dict(annotations)
        served['labels'] = projected
        if 'merges' not in annotations:
            served['merges'] = []
        data['place_annotations'] = served
    else:
        data['place_annotations'] = {'labels': projected}
    return json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()


def _labels_response(projected):
    return json.dumps({'labels': projected}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


class PlaceNames:
    def __init__(self, path):
        self.path = path
        self._thread = threading.Lock()
        self._cache = {}

    @staticmethod
    def open(dataset_path):
        return PlaceNames(_ledger_path(dataset_path))

    def _read_raw(self):
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None

    @contextmanager
    def _exclusive(self):
        self._thread.acquire()
        lock_file = None
        try:
            lock_file = open(self.path.with_name(self.path.name + '.lock'), 'a')
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if lock_file is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            self._thread.release()

    def overlay(self, dataset):
        raw = self._read_raw()
        key = (hashlib.sha256(dataset).digest(), hashlib.sha256(b'' if raw is None else raw).digest())
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            ledger = _parse_ledger(raw)
        except PlaceNameUnavailable:
            ledger = _Ledger({}, frozenset())
        body = _serve(dataset, ledger)
        served = ServedDataset(body, hashlib.sha256(body).hexdigest())
        self._cache[key] = served
        if len(self._cache) > 4:
            self._cache.pop(next(iter(self._cache)))
        return served

    def _replace(self, canonical):
        fd, temporary = tempfile.mkstemp(prefix='.place-names-', suffix='.json', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(canonical)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, request_body, dataset):
        ride_ids, name = _parse_request(request_body)
        with self._exclusive():
            raw = self._read_raw()
            ledger = _parse_ledger(raw)
            next_ledger = _apply(ledger, ride_ids, name)
            projected = _project(_base(dataset), next_ledger)
            if len(next_ledger.overrides) + len(next_ledger.cleared) > _MAX_KEYS or len(projected) > _MAX_KEYS:
                raise PlaceNameRejected(413, '名称太多。')
            canonical = _canonical(next_ledger)
            if raw != canonical:
                self._replace(canonical)
                self._cache.clear()
            return _labels_response(projected)

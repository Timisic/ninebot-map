from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid

from .map_server import MAX_BYTES
from .public_map import validate_public

COOLDOWN_US = 43_200_000_000
OBSERVATION_US = 21_600_000_000
API_VERSION = '2026-03-10'
API_ROOT = 'https://api.github.com'
MAX_REPLY_BYTES = 1024 * 1024
WORKFLOW = 'sync.yml'
REF = 'main'
RUN_PREFIX = 'Along public '
WORKER_STEP = 'Acquire rides, persist encrypted state, and publish approved map outputs'
PHASES = {'idle', 'dispatching', 'queued', 'running', 'succeeded', 'failed', 'unknown'}
RUN_STATUSES = {'queued', 'requested', 'waiting', 'pending', 'in_progress', 'completed'}
REASONS = {'dispatch_unconfirmed', 'dispatch_rejected', 'workflow_failed', 'collection_skipped',
           'publication_unconfirmed', 'observation_expired'}


def _micros(value):
    if value.tzinfo is None:
        raise ValueError('A UTC-aware clock is required')
    delta = value.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _iso(value):
    if value is None:
        return None
    return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value)).isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class Settings:
    repository: str
    origin: str
    token: str = field(repr=False)

    @classmethod
    def read(cls, path, credentials_dir):
        raw = json.loads(Path(path).read_bytes())
        if not isinstance(raw, dict) or set(raw) != {'repository', 'origin'}:
            raise ValueError('Invalid update configuration')
        repo, origin = raw['repository'], raw['origin']
        if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', repo):
            raise ValueError('Invalid update repository')
        if not isinstance(origin, str):
            raise ValueError('Invalid update origin')
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or origin != f'https://{parsed.netloc}' or parsed.port not in (None, 443):
            raise ValueError('Invalid update origin')
        if not credentials_dir:
            raise ValueError('Missing update credential')
        token = (Path(credentials_dir) / 'github-token').read_text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{1,4096}', token):
            raise ValueError('Invalid update credential')
        return cls(repo, origin, token)


@dataclass(frozen=True)
class UpdateRecord:
    request_id: str | None
    accepted_us: int | None
    phase: str
    run_id: int | None
    baseline_us: int | None
    baseline_sha256: str | None
    dataset_us: int | None
    dataset_sha256: str | None
    reason: str | None

    @classmethod
    def read(cls, row):
        record = cls(*row)
        if record.phase not in PHASES:
            raise ValueError('Invalid update state')
        if record.phase == 'idle':
            if any(value is not None for value in row[:2] + row[3:]):
                raise ValueError('Invalid idle state')
            return record
        if not isinstance(record.request_id, str) or str(uuid.UUID(record.request_id)) != record.request_id or uuid.UUID(record.request_id).version != 4:
            raise ValueError('Invalid request state')
        if any(type(value) is not int or not 0 <= value <= 253402300799999999 for value in (record.accepted_us, record.baseline_us)):
            raise ValueError('Invalid request clock')
        if record.accepted_us > 253402300799999999 - COOLDOWN_US:
            raise ValueError('Invalid cooldown clock')
        if not isinstance(record.baseline_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', record.baseline_sha256):
            raise ValueError('Invalid baseline evidence')
        if record.run_id is not None and (type(record.run_id) is not int or record.run_id <= 0):
            raise ValueError('Invalid run state')
        if record.reason is not None and record.reason not in REASONS:
            raise ValueError('Invalid update outcome')
        if record.phase in ('queued', 'running') and record.run_id is None:
            raise ValueError('Missing run state')
        if record.phase != 'succeeded' and (record.dataset_us is not None or record.dataset_sha256 is not None):
            raise ValueError('Unexpected success evidence')
        if record.phase == 'succeeded' and (record.run_id is None or type(record.dataset_us) is not int or not record.baseline_us < record.dataset_us <= 253402300799999999 or not isinstance(record.dataset_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', record.dataset_sha256)):
            raise ValueError('Invalid success evidence')
        return record

    def public(self, now_us):
        next_us = None if self.accepted_us is None else self.accepted_us + COOLDOWN_US
        return {'phase': 'queued' if self.phase == 'dispatching' else self.phase,
                'can_request': next_us is None or now_us > next_us,
                'requested_at': _iso(self.accepted_us), 'next_allowed_at': _iso(next_us)}


@dataclass(frozen=True)
class UpdateResult:
    status: int
    snapshot: dict


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _github_request(settings, method, path, body=None):
    request = Request(API_ROOT + path, data=body, method=method, headers={
        'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + settings.token,
        'X-GitHub-Api-Version': API_VERSION, 'Content-Type': 'application/json',
        'User-Agent': 'Along-map-update'})
    opener = build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=10)
    except HTTPError as error:
        with error:
            return error.code, b''
    with response:
        data = response.read(MAX_REPLY_BYTES + 1)
        if len(data) > MAX_REPLY_BYTES:
            raise ValueError('Oversized Actions response')
        return response.status, data


def _dataset_evidence(path):
    with Path(path).open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversized map dataset')
    data = validate_public(json.loads(raw))
    return _micros(datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))), hashlib.sha256(raw).hexdigest()


class PublicUpdates:
    def __init__(self, settings_path, state_path, dataset_path, *, clock=None, transport=None,
                 credentials_dir=None, start_observer=True):
        self.dataset_path = Path(dataset_path)
        self.state_path = Path(state_path) if state_path else None
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.transport = transport or _github_request
        self.settings = None
        self._owner = None
        self._closed = threading.Event()
        self._wake = threading.Event()
        self._observer = None
        try:
            if not settings_path or not self.state_path:
                return
            self.settings = Settings.read(settings_path, credentials_dir or os.environ.get('CREDENTIALS_DIRECTORY'))
            self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._owner = open(str(self.state_path) + '.lock', 'a')
            os.chmod(self._owner.name, 0o600)
            fcntl.flock(self._owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._initialize()
            current = self._record()
            if current.phase == 'dispatching':
                self._update(current.request_id, phase='unknown', reason='dispatch_unconfirmed')
            if start_observer:
                self._observer = threading.Thread(target=self._observe, name='along-update-observer', daemon=True)
                self._observer.start()
        except (OSError, ValueError, TypeError, sqlite3.Error):
            self.settings = None
            if self._owner:
                self._owner.close()
                self._owner = None

    @property
    def allowed_origin(self):
        return self.settings.origin if self.settings else None

    def _connect(self):
        connection = sqlite3.connect(self.state_path, timeout=5, isolation_level=None)
        connection.execute('PRAGMA busy_timeout=5000')
        return connection

    def _initialize(self):
        existed = self.state_path.exists()
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            if existed:
                if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)] or connection.execute('PRAGMA user_version').fetchone()[0] != 1:
                    raise ValueError('Unavailable update database')
                self._record(connection)
            else:
                connection.execute('''CREATE TABLE latest (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1), request_id TEXT,
                    accepted_us INTEGER, phase TEXT NOT NULL, run_id INTEGER,
                    baseline_us INTEGER, baseline_sha256 TEXT, dataset_us INTEGER,
                    dataset_sha256 TEXT, reason TEXT)''')
                connection.execute("INSERT INTO latest VALUES (1, NULL, NULL, 'idle', NULL, NULL, NULL, NULL, NULL, NULL)")
                connection.execute('PRAGMA user_version=1')
            connection.commit()
            os.chmod(self.state_path, 0o600)
        finally:
            connection.close()

    def _record(self, connection=None):
        owned = connection is None
        connection = connection or self._connect()
        try:
            rows = connection.execute('SELECT request_id, accepted_us, phase, run_id, baseline_us, baseline_sha256, dataset_us, dataset_sha256, reason FROM latest').fetchall()
            if len(rows) != 1:
                raise ValueError('Unavailable update singleton')
            return UpdateRecord.read(rows[0])
        finally:
            if owned:
                connection.close()

    def _update(self, request_id, *, phase, run_id=None, reason=None, evidence=None):
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('''UPDATE latest SET phase=?, run_id=COALESCE(?, run_id), reason=?,
                dataset_us=?, dataset_sha256=? WHERE singleton=1 AND request_id=?''',
                (phase, run_id, reason, *(evidence or (None, None)), request_id))
            connection.commit()
        finally:
            connection.close()

    def _unavailable(self):
        return {'phase': 'unavailable', 'can_request': False, 'requested_at': None, 'next_allowed_at': None}

    def snapshot(self):
        if not self.settings or self._closed.is_set():
            return self._unavailable()
        try:
            return self._record().public(_micros(self.clock()))
        except (OSError, ValueError, TypeError, sqlite3.Error):
            return self._unavailable()

    def request_update(self):
        if not self.settings or self._closed.is_set():
            return UpdateResult(503, self._unavailable())
        connection = None
        try:
            cached = self._record().public(_micros(self.clock()))
            if not cached['can_request']:
                return UpdateResult(429, cached)
            baseline = _dataset_evidence(self.dataset_path)
            connection = self._connect()
            connection.execute('BEGIN IMMEDIATE')
            now_us = _micros(self.clock())
            previous = self._record(connection)
            if previous.accepted_us is not None and now_us <= previous.accepted_us + COOLDOWN_US:
                return UpdateResult(429, previous.public(now_us))
            request_id = str(uuid.uuid4())
            connection.execute('''UPDATE latest SET request_id=?, accepted_us=?, phase='dispatching',
                run_id=NULL, baseline_us=?, baseline_sha256=?, dataset_us=NULL, dataset_sha256=NULL,
                reason=NULL WHERE singleton=1''', (request_id, now_us, *baseline))
            connection.commit()
        except (OSError, ValueError, TypeError, sqlite3.Error):
            return UpdateResult(503, self._unavailable())
        finally:
            if connection:
                connection.close()
        phase, run_id, reason, status = 'unknown', None, 'dispatch_unconfirmed', 202
        body = json.dumps({'ref': REF, 'inputs': {'force': True, 'publish_only': False,
                                              'public_request_id': request_id}}).encode()
        try:
            upstream, raw = self.transport(self.settings, 'POST', f'/repos/{self.settings.repository}/actions/workflows/{WORKFLOW}/dispatches', body)
            if upstream == 200:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and type(parsed.get('workflow_run_id')) is int and parsed['workflow_run_id'] > 0:
                    phase, run_id, reason = 'queued', parsed['workflow_run_id'], None
            elif upstream in (400, 401, 403, 404, 405, 409, 410, 422, 429):
                phase, reason, status = 'failed', 'dispatch_rejected', 502
        except (OSError, ValueError, TypeError):
            pass
        try:
            self._update(request_id, phase=phase, run_id=run_id, reason=reason)
        except (OSError, ValueError, sqlite3.Error):
            return UpdateResult(503, self._unavailable())
        self._wake.set()
        return UpdateResult(status, self.snapshot())

    def _get(self, path):
        if self._closed.is_set():
            raise ValueError('Update observer is closed')
        status, raw = self.transport(self.settings, 'GET', f'/repos/{self.settings.repository}' + path)
        if self._closed.is_set():
            raise ValueError('Update observer is closed')
        if status != 200 or len(raw) > MAX_REPLY_BYTES:
            raise ValueError('Actions metadata unavailable')
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError('Invalid Actions metadata')
        return parsed

    def _matching_run(self, run, record):
        if not isinstance(run, dict) or type(run.get('id')) is not int or run['id'] <= 0:
            return False
        path = run.get('path')
        return (run.get('display_title') == RUN_PREFIX + record.request_id
                and run.get('event') == 'workflow_dispatch' and run.get('head_branch') == REF
                and isinstance(path, str) and path.split('@', 1)[0] == '.github/workflows/' + WORKFLOW)

    def _discover_run(self, record):
        matches = []
        for page in range(1, 11):
            query = urlencode({'event': 'workflow_dispatch', 'branch': REF,
                               'created': '>=' + _iso(record.accepted_us - 120_000_000),
                               'exclude_pull_requests': 'true', 'per_page': 100, 'page': page})
            data = self._get(f'/actions/workflows/{WORKFLOW}/runs?' + query)
            runs = data.get('workflow_runs')
            if not isinstance(runs, list) or len(runs) > 100:
                raise ValueError('Invalid workflow listing')
            matches.extend(run for run in runs if self._matching_run(run, record))
            if len(runs) < 100:
                break
        else:
            raise ValueError('Workflow listing exceeds observation limit')
        if len(matches) > 1:
            raise ValueError('Ambiguous workflow correlation')
        return matches[0] if matches else None

    def _collection_succeeded(self, run):
        attempt = run.get('run_attempt')
        if type(attempt) is not int or attempt <= 0:
            raise ValueError('Invalid workflow attempt')
        data = self._get(f"/actions/runs/{run['id']}/attempts/{attempt}/jobs?per_page=100")
        jobs = data.get('jobs')
        if not isinstance(jobs, list) or type(data.get('total_count')) is not int or data['total_count'] != len(jobs) or len(jobs) > 100 or any(not isinstance(job, dict) for job in jobs):
            raise ValueError('Invalid workflow jobs')
        selected = [job for job in jobs if job.get('name') == 'sync' and job.get('run_id') == run['id']]
        if len(selected) != 1:
            return False
        job = selected[0]
        steps = job.get('steps')
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise ValueError('Invalid workflow steps')
        workers = [step for step in steps if step.get('name') == WORKER_STEP]
        return (job.get('status') == 'completed' and job.get('conclusion') == 'success'
                and len(workers) == 1 and workers[0].get('status') == 'completed'
                and workers[0].get('conclusion') == 'success')

    def _reconcile(self):
        record = self._record()
        if record.phase not in ('queued', 'running', 'unknown') or _micros(self.clock()) > record.accepted_us + OBSERVATION_US:
            if record.phase in ('queued', 'running'):
                self._update(record.request_id, phase='unknown', reason='observation_expired')
            return
        run = self._get(f'/actions/runs/{record.run_id}') if record.run_id else self._discover_run(record)
        if run is None:
            return
        if not self._matching_run(run, record) or (record.run_id is not None and run['id'] != record.run_id) or run.get('status') not in RUN_STATUSES:
            raise ValueError('Uncorrelated workflow run')
        run_id, status = run['id'], run['status']
        if status != 'completed':
            self._update(record.request_id, phase='running' if status == 'in_progress' else 'queued', run_id=run_id)
        elif run.get('conclusion') != 'success':
            self._update(record.request_id, phase='failed', run_id=run_id, reason='workflow_failed')
        elif not self._collection_succeeded(run):
            self._update(record.request_id, phase='failed', run_id=run_id, reason='collection_skipped')
        else:
            try:
                evidence = _dataset_evidence(self.dataset_path)
                if evidence[0] <= record.baseline_us or evidence[1] == record.baseline_sha256:
                    raise ValueError('Published dataset is stale')
            except (OSError, ValueError, TypeError):
                self._update(record.request_id, phase='unknown', run_id=run_id, reason='publication_unconfirmed')
                return
            self._update(record.request_id, phase='succeeded', run_id=run_id, evidence=evidence)

    def _observe(self):
        while not self._closed.is_set():
            self._wake.clear()
            try:
                self._reconcile()
                record = self._record()
                interval = 60 if record.accepted_us is None or _micros(self.clock()) - record.accepted_us > 300_000_000 else 15
            except (OSError, ValueError, TypeError, sqlite3.Error):
                interval = 60
            self._wake.wait(interval)

    def close(self):
        self._closed.set()
        self._wake.set()
        if self._observer:
            self._observer.join(timeout=15)
        if self._owner and (not self._observer or not self._observer.is_alive()):
            self._owner.close()
            self._owner = None

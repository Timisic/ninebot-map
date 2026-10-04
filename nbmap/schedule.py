"""Local due-time scheduler. launchd only wakes this bounded, noninteractive worker."""
import hashlib
import json
import math
import os
import re
import shutil
import plistlib
import subprocess
import sys
import tempfile
import venv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .acquisition import Acquisition, month_range
from .archive import RideArchive
from .client import Client, safe_error
from .dataset import prepare, _timestamp
from .storage import private_dir, read_json, write_json, sync_lock, write_text

DAY = 86400
RETRIES = (3600, 6 * 3600, DAY)


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.isoformat()


def read_state(config):
    path = config / 'schedule-state.json'
    return read_json(path) if path.exists() else {}


def read_settings(config):
    path = config / 'schedule.json'
    return read_json(path) if path.exists() else {}


def next_due(settings, state):
    if state.get('retry_at'):
        return datetime.fromisoformat(state['retry_at'])
    if state.get('last_success'):
        return datetime.fromisoformat(state['last_success']) + timedelta(days=settings['interval_days'])
    return datetime.min.replace(tzinfo=timezone.utc)


def sync_start(archive, state, now, recent_days=180):
    """Catch missed months and retry recent gaps, while keeping old history offline."""
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    current = local.strftime('%Y%m')
    recent = (local - timedelta(days=recent_days)).strftime('%Y%m')
    cutoff = now - timedelta(days=recent_days)
    snapshots = archive.read_months()
    # Recheck the previous month for late-arriving rides across a month boundary.
    previous = (local.replace(day=1) - timedelta(days=1)).strftime('%Y%m')
    candidates = [previous]
    if state.get('last_success'):
        candidates.append(datetime.fromisoformat(state['last_success']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m'))
    elif snapshots:
        candidates.append(snapshots[-1]['coverage']['month'])
    def incomplete_recent(ride):
        incomplete = (ride['geometry_kind'] != 'sampled_unverified' or ride['invalid_point_count']
                      or not ride.get('duration_seconds') or not ride.get('distance_km'))
        timestamp = _timestamp(ride.get('start_time_raw'), ZoneInfo('Asia/Shanghai'))
        return incomplete and (timestamp is None or datetime.fromisoformat(timestamp) >= cutoff)
    for snapshot in snapshots:
        month = snapshot['coverage']['month']
        if recent <= month <= current and (snapshot['coverage']['list_complete'] is not True or any(
            incomplete_recent(r) for r in snapshot['rides'])):
            candidates.append(month)
    candidates.extend(m for m in archive.pending_months() if recent <= m <= current)
    return min(candidates), current


def notify(kind):
    if sys.platform != 'darwin':
        return
    message = ('九号同步需要重新登录。请在终端运行 ./run login，再运行 ./run schedule run --force。'
               if kind == 'login_required' else '九号自动同步未完成，已有地图保留。请运行 ./run schedule status 查看。')
    script = f'display notification {json.dumps(message, ensure_ascii=False)} with title "Ninebot Map"'
    try:
        subprocess.run(['/usr/bin/osascript', '-e', script], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _login_required(config, started):
    path = config / 'last-error.json'
    if not path.exists():
        return False
    error = read_json(path)
    if datetime.fromisoformat(error['timestamp']) < started:
        return False
    if str(error.get('code')) == '401':
        return True
    if error['category'] in ('网络错误', '网络超时', 'HTTP 请求失败'):
        return False
    description = error.get('description', '')
    return (error['stage'] in ('refresh', 'business_login') or
            bool(re.search(r'登录|会话|token|auth', description, re.I) and
                 re.search(r'过期|失效|无效|expired|invalid|unauthorized', description, re.I)))


def run_due(config, data, *, force=False, now=None, source=None, local_notifications=False):
    with sync_lock(data), sync_lock(config):
        settings, state = read_settings(config), read_state(config)
        if not settings:
            raise ValueError('请先运行 ./run schedule install。')
        started = now or utcnow()
        if not force and (not settings['enabled'] or started < next_due(settings, state)):
            return 0
        old_status = state.get('status')
        state.update(status='running', last_attempt=stamp(started))
        write_json(config / 'schedule-state.json', state)
        try:
            prefs_path = config / 'preferences.json'
            prefs = read_json(prefs_path) if prefs_path.exists() else {}
            sn = prefs.get('sn')
            if not sn:
                raise ValueError('请先运行 ./run vehicles 选择自己的车辆。')
            client = source or Client(config)
            if not source:
                client.recover_session()
                if not client.tokens or (not client.tokens.get('refresh_token') and not client.tokens.get('access_token')):
                    state['status'] = 'login_required'
                    raise RuntimeError('登录状态不可用，请运行 ./run login。')
                client.session()
            archive = RideArchive.for_vehicle(data, sn)
            archive.import_legacy()
            start, end = sync_start(archive, state, started)
            recent_month = (started - timedelta(days=180)).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m')
            result = Acquisition(client, archive).run(sn, start, end, retry_incomplete=True,
                                                       retry_incomplete_since=recent_month)
            if not all(r.get('published') and r['list_complete'] is True and not r['errors'] for r in result.reports):
                raise RuntimeError('本次清单或详情请求未完成，保留上次标准数据。')
            # Missing coordinates are a provider limitation, not an endless failed run.
            directory = result.dataset_directory
            if not directory:
                directory = str(prepare(archive))
            dataset = read_json(Path(directory) / 'dataset.json')
            finished = now or utcnow()
            state.update(status='success', last_success=stamp(finished), failures=0,
                         retry_at=None, message='同步成功', requested_months=month_range(start, end),
                         dataset=str(archive.path / 'prepared' / 'dataset.json'), summary=dataset['summary'])
            write_json(config / 'schedule-state.json', state)
            print('自动同步完成，标准数据已更新。', flush=True)
            return 0
        except (ValueError, RuntimeError, OSError) as exc:
            failures = state.get('failures', 0) + 1
            login_required = state.get('status') == 'login_required' or _login_required(config, started)
            status = 'login_required' if login_required else 'failed'
            delay = DAY if login_required else RETRIES[min(failures - 1, len(RETRIES) - 1)]
            message = '请在自己的终端运行 ./run login，然后 ./run schedule run --force。' if login_required else safe_error(exc)
            state.update(status=status, failures=failures, message=message,
                         retry_at=stamp((now or utcnow()) + timedelta(seconds=delay)))
            write_json(config / 'schedule-state.json', state)
            if local_notifications and status != old_status:
                notify(status)
            print('自动同步未完成；请运行 ./run schedule status。', flush=True)
            return 1


def identity(root, config):
    suffix = hashlib.sha256(f'{root}\0{config}'.encode()).hexdigest()[:12]
    return 'local.ninebot-map.sync.' + suffix


def launchctl(*args):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True, timeout=15)


def agent_path(label):
    return Path.home() / 'Library' / 'LaunchAgents' / (label + '.plist')


def is_loaded(label):
    return launchctl('print', f'gui/{os.getuid()}/{label}').returncode == 0


def relocate_storage(path, destination):
    """Move only protected local storage; preserve the original CLI path as a link."""
    protected = [Path.home() / name for name in ('Downloads', 'Documents', 'Desktop')]
    if not any(path.is_relative_to(folder) for folder in protected):
        return path
    if destination.exists():
        raise ValueError('后台存储位置已有不同档案，已停止迁移。')
    if path.is_symlink():
        return path.resolve()
    path.rename(destination)
    try:
        path.symlink_to(destination, target_is_directory=True)
    except OSError:
        destination.rename(path)
        raise
    return destination


def prepare_background_runtime(root, config, data, label):
    """Keep launchd execution outside macOS protected desktop folders."""
    home = private_dir(Path.home() / 'Library/Application Support/Ninebot Map' / label.rsplit('.', 1)[-1])
    config = relocate_storage(config, home / 'sessions')
    data = relocate_storage(data, home / 'data')
    runtime = private_dir(home / 'runtime')
    # This contains application code and installed dependencies, never personal files.
    package = runtime / 'nbmap'
    if package.exists():
        shutil.rmtree(package)
    shutil.copytree(root / 'nbmap', package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    environment = runtime / '.venv'
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    source_sites = list((root / '.venv/lib').glob('python*/site-packages'))
    destination_sites = list((environment / 'lib').glob('python*/site-packages'))
    if len(source_sites) != 1 or len(destination_sites) != 1:
        raise ValueError('无法确定后台 Python 依赖目录，请检查本地虚拟环境。')
    shutil.copytree(source_sites[0], destination_sites[0], dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return runtime, config, data


def manage(action, config, data, root, *, interval_days=None, force=False):
    if action == 'run':
        return run_due(config, data, force=force,
                       local_notifications=read_settings(config).get('enabled', False))
    if action == 'status':
        settings, state = read_settings(config), read_state(config)
        print('本地自动同步：' + ('已启用' if settings.get('enabled') else '未启用'))
        if settings:
            label = settings['label']
            result = launchctl('print', f'gui/{os.getuid()}/{label}') if sys.platform == 'darwin' else None
            loaded = result is not None and result.returncode == 0
            print(f"周期：{settings['interval_days']:g} 天；系统任务：{'已加载' if loaded else '未加载'}")
            exit_code = re.search(r'last exit code = (\d+)', result.stdout) if loaded else None
            if exit_code:
                print('系统任务上次退出码：' + exit_code.group(1))
            if settings.get('enabled') and loaded:
                print('下次到期：' + (next_due(settings, state).astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
                                      if state.get('last_success') or state.get('retry_at') else '首次检查立即运行'))
                print('实际运行在到期后的下一次每小时检查，休眠或关机后在恢复登录时补跑。')
            else:
                print('本地定时执行：' + ('已停用。' if not settings.get('enabled') else '系统任务未加载，不会自动运行。'))
        if state:
            print('状态：' + state.get('status', 'unknown'))
            print('上次成功：' + (datetime.fromisoformat(state['last_success']).astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
                                   if state.get('last_success') else '尚无'))
            print('提示：' + state.get('message', ''))
            if state.get('dataset'):
                print('地图数据：' + state['dataset'])
        return 0
    if sys.platform != 'darwin':
        raise ValueError('系统任务安装当前支持 macOS；其他系统可定期调用 schedule run。')
    if interval_days is not None and (not math.isfinite(interval_days) or interval_days < 1):
        raise ValueError('同步周期至少为 1 天。')
    with sync_lock(data), sync_lock(config):
        settings = read_settings(config)
        label = settings.get('label', identity(root, config))
        path = agent_path(label)
        target = f'gui/{os.getuid()}/{label}'
        if action in ('disable', 'uninstall'):
            if is_loaded(label):
                result = launchctl('bootout', target)
                if result.returncode:
                    raise RuntimeError('系统任务停用失败；请检查 launchctl 状态。')
            if settings:
                write_json(config / 'schedule.json', {**settings, 'enabled': False})
            if action == 'uninstall':
                path.unlink(missing_ok=True)
            print('自动同步已' + ('卸载，历史档案与会话保留。' if action == 'uninstall' else '停用。'))
            return 0
        if action != 'install':
            raise ValueError('未知调度操作')
        if not (root / '.venv/bin/python').exists():
            raise ValueError('请先运行 ./scripts/setup.sh。')
        if not (config / 'preferences.json').exists():
            raise ValueError('请先运行 ./run vehicles。')
        if is_loaded(label):
            if launchctl('bootout', target).returncode:
                raise RuntimeError('旧系统任务停用失败。')
        runtime, config, data = prepare_background_runtime(root, config, data, label)
        settings = {**settings, 'schema_version': 1, 'enabled': True, 'label': label,
                    'interval_days': interval_days if interval_days is not None else settings.get('interval_days', 10),
                    'data_dir': str(data), 'config_dir': str(config), 'runtime_dir': str(runtime)}
        log = config / 'scheduler.log'
        if not log.exists():
            write_text(log, '')
        plist = {'Label': label, 'ProgramArguments': [str(runtime / '.venv/bin/python'), '-m', 'nbmap',
                  '--config-dir', str(config), '--data-dir', str(data), 'schedule', 'run'],
                 'WorkingDirectory': str(runtime), 'RunAtLoad': True, 'StartCalendarInterval': {'Minute': 5},
                 'ProcessType': 'Background', 'Umask': 0o077,
                 'StandardOutPath': str(log), 'StandardErrorPath': str(log)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.ninebot-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(plistlib.dumps(plist))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        write_json(config / 'schedule.json', settings)
    result = launchctl('bootstrap', f'gui/{os.getuid()}', str(path))
    if result.returncode or not is_loaded(label):
        write_json(config / 'schedule.json', {**settings, 'enabled': False})
        raise RuntimeError('launchd 安装未完成；配置已保留，请检查系统权限后重新 install。')
    print(f"已启用本机 launchd 同步，间隔 {settings['interval_days']:g} 天。")
    return 0

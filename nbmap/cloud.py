"""Private GitHub runner; explicit local downloads, with no Mac background process."""
import argparse
import base64
import gzip
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet

from .archive import RideArchive
from .cloud_state import checkpoint, import_archives, restore, seal, unseal
from .dataset import prepare_configured, prepare, validate_dataset
from .schedule import next_due, read_state, run_due
from .storage import private_dir, read_json, sync_lock, write_json, write_text
from .track_image import render_tracks

IMAGE_PATH = 'assets/ninebot-tracks.png'
START, END = '<!-- ninebot-track-image:start -->', '<!-- ninebot-track-image:end -->'
REPO_PATTERN = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')


class CommandFailure(RuntimeError):
    def __init__(self, args, result):
        error = result.stderr.decode(errors='replace').lower()
        patterns = {'load key': 'deploy_key_format', 'host key verification failed': 'host_key_verification',
                    'permission denied (publickey)': 'deploy_key_authentication',
                    'repository not found': 'repository_permission',
                    'protected branch': 'protected_branch', 'non-fast-forward': 'concurrent_update',
                    'connection timed out': 'connection_timeout'}
        self.category = next((label for pattern, label in patterns.items() if pattern in error), 'git_or_github_error')
        self.operation = ' '.join(args[:2])
        self.exit_code = result.returncode
        super().__init__('GitHub 或 Git 操作未完成；未输出请求正文或凭据。')


def command(args, *, cwd=None, data=None, env=None, timeout=120, check=True):
    result = subprocess.run(args, cwd=cwd, input=data, capture_output=True, env=env, timeout=timeout)
    if check and result.returncode:
        raise CommandFailure(args, result)
    return result


def gh_json(*args):
    return json.loads(command(['gh', *args]).stdout)


def repo_info(repo):
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError('仓库格式必须为 owner/name')
    return gh_json('api', 'repos/' + repo)


def private_repo(repo):
    info = repo_info(repo)
    if not info['private']:
        raise ValueError('同步档案必须存入独立私有仓库；未上传会话或档案。')
    return info


def secret(repo, name, value):
    private_repo(repo)
    command(['gh', 'secret', 'set', name, '--repo', repo], data=value)


def bootstrap(config):
    return {'revision': datetime.now(timezone.utc).isoformat(),
            'files': {name: read_json(config / name) for name in ('config.json', 'tokens.json', 'preferences.json')}}


def cloud_config(config):
    path = config / 'cloud.json'
    if not path.exists():
        raise ValueError('请先运行 ./run cloud install。')
    return read_json(path)


def download_state(config):
    settings = cloud_config(config)
    private_repo(settings['repo'])
    blob = command(['gh', 'api', f"repos/{settings['repo']}/contents/state.enc?ref=state",
                    '-H', 'Accept: application/vnd.github.raw+json']).stdout
    return unseal(blob, (config / 'cloud-state.key').read_bytes().strip())


def readme_image(text):
    block = f'{START}\n\n![骑行轨迹]({IMAGE_PATH})\n\n{END}'
    if START in text and END in text:
        return text[:text.index(START)] + block + text[text.index(END) + len(END):]
    return text.rstrip() + '\n\n' + block + '\n'


def public_fingerprint(public):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(base64.b64decode(public.split()[1])).digest()).decode().rstrip('=')


def is_cloud_due(payload, session, settings, *, force=False, now=None):
    state = payload['files'].get('sessions/schedule-state.json', {})
    return bool(settings.get('enabled', True) and (force or state.get('publication_pending') or
        session['revision'] != payload.get('credential_revision') or
        (now or datetime.now(timezone.utc)) >= next_due(settings, state)))


def gate(root):
    settings = read_json(root / 'sync-settings.json')
    command(['git', 'fetch', '--depth', '1', 'origin', 'state'], cwd=root)
    blob = command(['git', 'show', 'FETCH_HEAD:state.enc'], cwd=root).stdout
    payload = unseal(blob, os.environ['CLOUD_STATE_KEY'].encode())
    session = json.loads(os.environ['NINEBOT_SESSION'])
    due = is_cloud_due(payload, session, settings, force=os.environ.get('SYNC_FORCE', '').lower() == 'true')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('due=' + str(due).lower() + '\n')
    print('Due-time checked; no Ninebot requests.')
    return 0


def publish_image(root, image, destinations):
    for index, destination in enumerate(destinations, 1):
        key = os.environ.get(f'PUBLIC_DEPLOY_KEY_{index}', '')
        if not key:
            raise ValueError('缺少指定公开仓库的图片发布密钥')
        target = private_dir(root / f'publish-{index}')
        key_path = root / f'publish-{index}.key'
        # Secret stores may trim the trailing LF required by OpenSSH's key parser.
        write_text(key_path, key.replace('\r\n', '\n').strip() + '\n')
        public = command(['ssh-keygen', '-y', '-f', str(key_path)]).stdout.decode().strip()
        if destination.get('key_fingerprint') and public_fingerprint(public) != destination['key_fingerprint']:
            raise ValueError('图片发布密钥与目标仓库不一致')
        hosts = root / 'known-hosts'
        env = {**os.environ, 'GIT_SSH_COMMAND': f'ssh -i {shlex.quote(str(key_path))} -p 443 -o HostName=ssh.github.com -o HostKeyAlias=github.com -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile={shlex.quote(str(hosts))}'}
        command(['git', 'clone', '--depth', '1', '--branch', destination['branch'],
                 'git@github.com:' + destination['repo'] + '.git', str(target)], env=env)
        output = target / IMAGE_PATH
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, output)
        readme = target / 'README.md'
        readme.write_text(readme_image(readme.read_text() if readme.exists() else ''))
        command(['git', 'add', '--', IMAGE_PATH, 'README.md'], cwd=target, env=env)
        paths = command(['git', 'diff', '--cached', '--name-only'], cwd=target).stdout.decode().splitlines()
        if set(paths) - {IMAGE_PATH, 'README.md'}:
            raise ValueError('公开发布包含图片之外的未授权文件')
        if paths:
            command(['git', '-c', 'user.name=Ninebot Map Sync', '-c', 'user.email=sync@users.noreply.github.com',
                     'commit', '-m', 'Update basemap-free ride image'], cwd=target, env=env)
            command(['git', 'push', 'origin', 'HEAD:' + destination['branch']], cwd=target, env=env)
        key_path.unlink(missing_ok=True)


def publish_site_data(root, dataset, destination, updated_at):
    from .public_map import public_dataset
    host, user = destination['host'], destination['user']
    port = destination.get('port', 22)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', host) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user) or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('静态发布目标无效')
    key = os.environ.get('MAP_DEPLOY_KEY', '')
    if not key or not destination.get('known_hosts'):
        raise ValueError('静态发布缺少专用密钥或已核对的主机公钥')
    public = public_dataset(read_json(dataset), updated_at)
    body = json.dumps(public, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    with tempfile.TemporaryDirectory(prefix='site-publish-', dir=root) as directory:
        key_path, hosts_path = Path(directory) / 'identity', Path(directory) / 'known_hosts'
        write_text(key_path, key.replace('\r\n', '\n').strip() + '\n')
        write_text(hosts_path, destination['known_hosts'].strip() + '\n')
        command(['ssh', '-T', '-i', str(key_path), '-p', str(port), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                 '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={hosts_path}',
                 f'{user}@{host}', 'publish-map'], data=body, timeout=120)


def execute_worker(payload, key, session, settings, root, *, force=False, source=None, now=None):
    restore(payload, root)
    config, data = root / 'sessions', root / 'data'
    revised = session['revision'] != payload.get('credential_revision')
    revision = payload.get('credential_revision')
    if revised:
        for name, value in session['files'].items():
            if name not in ('config.json', 'tokens.json', 'preferences.json'):
                raise ValueError('不允许的会话字段')
            write_json(config / name, value)
        revision = session['revision']
    clock = now or datetime.now(timezone.utc)
    interval = settings['interval_days']
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval < 1:
        raise ValueError('同步周期至少为 1 天')
    schedule = {'enabled': settings.get('enabled', True), 'interval_days': interval}
    write_json(config / 'schedule.json', schedule)
    state = read_state(config)
    due = schedule['enabled'] and (force or revised or clock >= next_due(schedule, state))
    if not due and not state.get('publication_pending'):
        return None, 0, []
    if due:
        code = run_due(config, data, force=force or revised, source=source, now=now,
                       local_notifications=False)
        state = read_state(config)
        if code == 0:
            state['publication_pending'] = True
            write_json(config / 'schedule-state.json', state)
    else:
        code = 0
    paths = []
    if state.get('status') == 'success' and state.get('publication_pending'):
        sn = read_json(config / 'preferences.json')['sn']
        archive = RideArchive.for_vehicle(data, sn)
        directory = prepare_configured(archive) or prepare(archive)
        paths = [Path(directory) / 'dataset.json']
    return checkpoint(config, data, revision), code, paths


def worker(root):
    # Every failure message is fixed text; never print upstream bodies, secret envs or tracebacks.
    settings = read_json(root / 'sync-settings.json')
    command(['git', 'fetch', '--depth', '1', 'origin', 'state'], cwd=root)
    blob = command(['git', 'show', 'FETCH_HEAD:state.enc'], cwd=root).stdout
    key = os.environ['CLOUD_STATE_KEY'].encode()
    payload = unseal(blob, key)
    session = json.loads(os.environ['NINEBOT_SESSION'])
    temporary = private_dir(root / 'work' / 'cloud-worker')
    updated, code, datasets = execute_worker(payload, key, session, settings, temporary,
                                            force=os.environ.get('SYNC_FORCE', '').lower() == 'true')
    if updated is None:
        print('Not due; no Ninebot requests and no archive writes.')
        return 0
    if datasets:
        try:
            image = render_tracks(read_json(datasets[0]), temporary / 'tracks.png')
            shutil.copyfile(root / 'github-known-hosts', temporary / 'known-hosts')
            publish_image(temporary, image, settings.get('publish_repos', []))
            if settings.get('site'):
                publish_site_data(temporary, datasets[0], settings['site'], updated['files']['sessions/schedule-state.json']['last_success'])
            publication = updated['files']['sessions/schedule-state.json']
            publication['publication_pending'] = False
            publication.pop('publication_error', None)
            if settings.get('site'):
                publication['site_published_at'] = datetime.now(timezone.utc).isoformat()
            if settings.get('publish_repos'):
                publication['image_published_at'] = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            code = 1
            updated['files']['sessions/schedule-state.json']['publication_pending'] = True
            diagnostic = ({'operation': exc.operation, 'category': exc.category, 'exit_code': exc.exit_code}
                          if isinstance(exc, CommandFailure) else {'category': type(exc).__name__})
            updated['files']['sessions/schedule-state.json']['publication_error'] = diagnostic
            print('Publication diagnostic: ' + json.dumps(diagnostic))
            print('Publication incomplete; encrypted data remains recoverable. Publication will retry.')
    output = root / 'work' / 'state-publish'
    command(['git', 'worktree', 'add', '--detach', str(output), 'FETCH_HEAD'], cwd=root)
    (output / 'state.enc').write_bytes(seal(updated, key))
    command(['git', 'add', '--', 'state.enc'], cwd=output)
    command(['git', '-c', 'user.name=Ninebot Map Sync', '-c', 'user.email=sync@users.noreply.github.com',
             'commit', '-m', 'Update encrypted sync state'], cwd=output)
    command(['git', 'push', 'origin', 'HEAD:state'], cwd=output)
    print('Encrypted checkpoint saved. Only configured display outputs were published.')
    return code


def deploy_code(root, folder, repo, settings):
    if not (folder / '.git').exists():
        command(['git', 'init', '-b', 'main', str(folder)])
        command(['git', 'remote', 'add', 'origin', 'git@github.com:' + repo + '.git'], cwd=folder)
    for name in ('pyproject.toml', 'uv.lock', 'LICENSE', 'run', 'package.json', 'package-lock.json', 'AGENTS.md'):
        shutil.copyfile(root / name, folder / name)
    (folder / 'run').chmod(0o755)
    for name in ('web', 'tests', 'docs', 'examples', 'schemas', 'scripts', 'templates', '.agents'):
        shutil.copytree(root / name, folder / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(root / 'nbmap', folder / 'nbmap', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    workflows = folder / '.github/workflows'
    workflows.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'templates/cloud-sync.yml', workflows / 'sync.yml')
    shutil.copyfile(root / '.gitignore', folder / '.gitignore')
    write_json(folder / 'sync-settings.json', settings)
    write_text(folder / 'README.md', '# Private ride sync\n\nCollector snapshot, encrypted checkpoint on the `state` branch, and image-only public publishing. Never change this repository to public.\n')
    keys = gh_json('api', 'meta')['ssh_keys']
    aliases = 'github.com,[github.com]:443,ssh.github.com,[ssh.github.com]:443'
    write_text(folder / 'github-known-hosts', ''.join(aliases + ' ' + key + '\n' for key in keys))
    obsolete = folder / 'CONTEXT.md'
    obsolete.unlink(missing_ok=True)
    paths = ['nbmap', '.github', '.gitignore', 'sync-settings.json', 'github-known-hosts', 'README.md',
             'LICENSE', 'pyproject.toml', 'uv.lock', 'run', 'package.json', 'package-lock.json', 'AGENTS.md',
             'web', 'tests', 'docs', 'examples', 'schemas', 'scripts', 'templates', '.agents']
    if command(['git', 'ls-files', '--', 'CONTEXT.md'], cwd=folder).stdout:
        paths.append('CONTEXT.md')
    command(['git', 'add', '--all', '--', *paths], cwd=folder)
    if command(['git', 'diff', '--cached', '--quiet'], cwd=folder, check=False).returncode:
        command(['git', '-c', 'user.name=Ninebot Map Sync', '-c', 'user.email=sync@users.noreply.github.com',
                 'commit', '-m', 'Configure private ride sync and public image publishing'], cwd=folder)
    command(['git', 'push', '-u', 'origin', 'main'], cwd=folder)


def setup(config, data, root, *, repo=None, interval_days=None, publish_repos=None):
    path = config / 'cloud.json'
    previous = read_json(path) if path.exists() else {}
    owner = gh_json('api', 'user')['login']
    repo = repo or previous.get('repo') or owner + '/ninebot-map-sync'
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError('仓库格式必须为 owner/name')
    interval = interval_days if interval_days is not None else previous.get('interval_days', 10)
    if not math.isfinite(interval) or interval < 1:
        raise ValueError('同步周期至少为 1 天')
    session = bootstrap(config)
    if len(json.dumps(session).encode()) > 48000:
        raise ValueError('会话超过 GitHub Secrets 大小上限')
    key_path = config / 'cloud-state.key'
    exists = command(['gh', 'api', 'repos/' + repo], check=False).returncode == 0
    if not exists:
        command(['gh', 'repo', 'create', repo, '--private', '--description', 'Private encrypted Ninebot archive and image publishing'])
    private_repo(repo)
    if exists and not key_path.exists():
        raise ValueError('私有仓库已存在但本机缺少解密密钥，已停止覆盖。')
    if not key_path.exists():
        write_text(key_path, Fernet.generate_key().decode() + '\n')
    key = key_path.read_bytes().strip()
    destinations = []
    selected = publish_repos if publish_repos is not None else [x['repo'] for x in previous.get('publish_repos', [])]
    if len(selected) > 2:
        raise ValueError('当前支持最多两个图片展示仓库')
    for index, target_repo in enumerate(selected, 1):
        info = repo_info(target_repo)
        if info['private']:
            raise ValueError('图片展示目标应为明确选择的公开仓库')
        key_file = config / ('cloud-publish-' + hashlib.sha256(target_repo.encode()).hexdigest()[:12] + '.key')
        if not key_file.exists():
            command(['ssh-keygen', '-t', 'ed25519', '-N', '', '-C', 'ninebot-image-sync', '-f', str(key_file)])
        public = key_file.with_suffix(key_file.suffix + '.pub').read_text().strip()
        keys = gh_json('api', 'repos/' + target_repo + '/keys')
        if not any(k['key'].split()[:2] == public.split()[:2] for k in keys):
            request = json.dumps({'title': 'Ninebot Map image sync', 'key': public, 'read_only': False}).encode()
            command(['gh', 'api', 'repos/' + target_repo + '/keys', '--method', 'POST', '--input', '-'], data=request)
        secret(repo, f'PUBLIC_DEPLOY_KEY_{index}', key_file.read_bytes())
        destinations.append({'repo': target_repo, 'branch': info['default_branch'], 'key_fingerprint': public_fingerprint(public)})
    secret(repo, 'CLOUD_STATE_KEY', key)
    if not previous or previous.get('repo') != repo:
        secret(repo, 'NINEBOT_SESSION', json.dumps(session).encode())
    suffix = hashlib.sha256(repo.encode()).hexdigest()[:12]
    folder = private_dir(root / 'work' / 'github-actions' / suffix)
    settings = {'enabled': True, 'interval_days': interval, 'publish_repos': destinations}
    # Seed once, before scheduling. Existing cloud history is never reset on reinstall.
    branch = command(['gh', 'api', 'repos/' + repo + '/git/ref/heads/state'], check=False)
    if branch.returncode:
        seed = private_dir(root / 'work' / 'cloud-seed' / suffix)
        if not (seed / '.git').exists():
            command(['git', 'init', '-b', 'state', str(seed)])
            command(['git', 'remote', 'add', 'origin', 'git@github.com:' + repo + '.git'], cwd=seed)
        payload = checkpoint(config, data, session['revision'])
        (seed / 'state.enc').write_bytes(seal(payload, key))
        command(['git', 'add', '--', 'state.enc'], cwd=seed)
        command(['git', '-c', 'user.name=Ninebot Map Sync', '-c', 'user.email=sync@users.noreply.github.com',
                 'commit', '-m', 'Seed encrypted local archive'], cwd=seed)
        command(['git', 'push', '-u', 'origin', 'state'], cwd=seed)
    deploy_code(root, folder, repo, settings)
    command(['gh', 'api', 'repos/' + repo, '--method', 'PATCH', '-f', 'default_branch=main'])
    write_json(path, {'repo': repo, 'interval_days': interval, 'publish_repos': destinations})
    command(['gh', 'workflow', 'enable', 'sync.yml', '--repo', repo])
    print('私有 Actions 已配置：' + repo + '；本机没有定时后台任务。')
    return 0


def manage(action, config, data, root, *, repo=None, interval_days=None, publish_repos=None, port=8765, no_open=False):
    if action == 'install':
        with sync_lock(data), sync_lock(config):
            return setup(config, data, root, repo=repo, interval_days=interval_days, publish_repos=publish_repos)
    settings = cloud_config(config)
    if action == 'run':
        private_repo(settings['repo'])
        command(['gh', 'workflow', 'run', 'sync.yml', '--repo', settings['repo'], '-f', 'force=true'])
        print('已触发云端同步；用 ./run cloud status 查看结果。')
        return 0
    if action == 'disable':
        command(['gh', 'workflow', 'disable', 'sync.yml', '--repo', settings['repo']])
        print('云端定时任务已停用。')
        return 0
    if action == 'credentials':
        secret(settings['repo'], 'NINEBOT_SESSION', json.dumps(bootstrap(config)).encode())
        print('会话已更新至 GitHub Secrets；密码未上传。')
        return 0
    payload = download_state(config)
    state = payload['files'].get('sessions/schedule-state.json', {})
    if action == 'status':
        workflow = gh_json('api', 'repos/' + settings['repo'] + '/actions/workflows/sync.yml')
        print('私有 Actions：' + settings['repo'] + '；工作流：' + workflow['state'])
        runs = gh_json('run', 'list', '--repo', settings['repo'], '--workflow', 'sync.yml', '--limit', '1',
                       '--json', 'status,conclusion,url')
        if runs:
            print('最近云端执行：' + runs[0]['status'] + ' ' + (runs[0]['conclusion'] or ''))
            print('执行详情：' + runs[0]['url'])
        else:
            print('尚无云端执行，当前档案来自本机初始化。')
        print('周期：' + str(settings['interval_days']) + ' 天；已保存的档案状态：' + state.get('status', '尚无'))
        if state.get('last_success'):
            print('上次成功：' + datetime.fromisoformat(state['last_success']).astimezone(ZoneInfo('Asia/Shanghai')).isoformat())
        if workflow['state'] == 'active' and settings.get('enabled', True) and state.get('last_success'):
            print('下次到期：' + next_due(settings, state).astimezone(ZoneInfo('Asia/Shanghai')).isoformat())
        elif workflow['state'] != 'active' or not settings.get('enabled', True):
            print('云端定时执行：未启用。')
        if state.get('message'):
            print('提示：' + state['message'])
        if state.get('publication_pending'):
            print('图片发布：等待重试；' + state.get('publication_error', {}).get('category', '尚未完成'))
        elif state.get('image_published_at'):
            print('图片已发布：' + datetime.fromisoformat(state['image_published_at']).astimezone(ZoneInfo('Asia/Shanghai')).isoformat())
        return 0
    if action in ('pull', 'map'):
        archive_payload = {**payload, 'files': {p: v for p, v in payload['files'].items() if p.startswith('data/')}}
        del payload
        with sync_lock(data), sync_lock(config), tempfile.TemporaryDirectory(dir=private_dir(root / 'work')) as tmp:
            temporary = Path(tmp)
            restore(archive_payload, temporary)
            paths = import_archives(temporary / 'data', data)
            write_json(config / 'cloud-last-pull.json', {'downloaded_at': datetime.now(timezone.utc).isoformat(),
                                                        'remote_updated_at': archive_payload['created_at'], 'status': state.get('status')})
        del archive_payload
        print('云端档案已合并；本机已有轨迹及地图范围保留。')
        if action == 'map':
            sn = read_json(config / 'preferences.json')['sn']
            path = RideArchive.for_vehicle(data, sn).path / 'prepared/dataset.json'
            from .map_server import serve_map
            return serve_map(path, port, no_open)
        return 0
    raise ValueError('未知云端操作')


if __name__ == '__main__':
    try:
        if sys.argv[1:] not in (['worker'], ['gate']):
            raise ValueError('请通过 ./run cloud 调用本机管理命令。')
        raise SystemExit(gate(Path.cwd()) if sys.argv[1] == 'gate' else worker(Path.cwd()))
    except Exception:
        print('Cloud sync could not complete. Existing encrypted state and public image are retained. Check credentials and workflow settings.', file=sys.stderr)
        raise SystemExit(1)

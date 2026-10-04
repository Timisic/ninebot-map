import argparse
import getpass
import importlib.metadata
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .client import Client, safe_error
from .acquisition import Acquisition, month_range
from .archive import RideArchive
from .summary import summarize
from .dataset import prepare, prepare_configured, validate_dataset
from .storage import private_dir, read_json, write_json, sync_lock
from .vendor import ninebot_api as api

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".private"
DATA = ROOT / "data"


def current_month():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m")


def login(client):
    if not sys.stdin.isatty():
        raise RuntimeError("请在你自己的终端运行 ./run login，交互输入账号密码。")
    print("账号信息只在本机输入，密码不显示、不保存，不进入命令历史。")
    print("登录可能使 iPhone 上的九号 App 会话失效；届时在 App 重新登录即可。")
    username = input("九号账号（手机号）：").strip()
    area = "86"
    password = getpass.getpass("九号账号密码（不是短信验证码）：")
    if not username or not password:
        raise ValueError("手机号和密码不能为空。")
    client.login(username, password, area)
    del password
    print(f"登录成功，会话保存在：{client.config}")


def select_vehicle(client, config, data, interactive=False):
    vehicles = client.vehicles()
    write_json(data / "vehicles.json", vehicles)
    valid = [v for v in vehicles if isinstance(v, dict) and (v.get("wnumber") or v.get("sn"))]
    if not valid:
        raise ValueError("接口没有返回可读取的车辆；请确认此账号在官方 App 中能看到车辆。")
    prefs_path = config / "preferences.json"
    prefs = read_json(prefs_path) if prefs_path.exists() else {}
    for index, vehicle in enumerate(valid, 1):
        sn = str(vehicle.get("wnumber") or vehicle.get("sn"))
        name = vehicle.get("vehicle_name") or vehicle.get("device_name") or "九号车辆"
        print(f"{index}. {name}  SN …{sn[-4:]}")
    selected = next((v for v in valid if str(v.get("wnumber") or v.get("sn")) == prefs.get("sn")), None)
    if len(valid) == 1:
        selected = valid[0]
    elif interactive:
        choice = input("选择车辆编号：").strip()
        if not choice.isdigit() or not 1 <= int(choice) <= len(valid):
            raise ValueError("车辆编号无效")
        selected = valid[int(choice) - 1]
    elif selected is None:
        raise ValueError("有多辆车，请先运行 ./run vehicles 在终端选择。")
    sn = str(selected.get("wnumber") or selected.get("sn"))
    write_json(prefs_path, {**prefs, "sn": sn})
    return sn


def show_progress(event):
    month = event['month']
    if event['kind'] == 'page':
        print(f"{month} 第 {event['page']} 页：累计 {event['listed']} 条行程", flush=True)
    elif event['kind'] == 'detail':
        print(f"{month} 详情 {event['completed']}/{event['total']}", flush=True)
    elif event['kind'] == 'month':
        r = event['report']
        total = r['upstream_ride_count'] if r['upstream_ride_count'] is not None else '未知'
        print(f"{month}：清单 {r['listed_rides']}/{total} 条，有坐标 {r['rides_with_coordinates']} 条。", flush=True)
        if r.get('published') is False:
            print('本次未发布新档案；已有快照保持可读，采集证据已保留。', flush=True)


def sync(client, sn, start, end, data, max_pages=100, refresh_details=False):
    if end > current_month():
        raise ValueError('结束月份不能晚于本月。')
    archive = RideArchive.for_vehicle(data, sn)
    archive.import_legacy()
    result = Acquisition(client, archive).run(sn, start, end, max_pages=max_pages,
        refresh_details=refresh_details, progress=show_progress)
    print(f"合并导出：{result.report_directory}")
    if result.dataset_directory:
        print(f"标准数据：{result.dataset_directory}/dataset.json")
    if result.has_gaps:
        print('本次采集有缺口或未知项；详见档案中的 last-task.json 和合并报告。')
        return 2
    print('清单已对账；坐标系及轨迹完整性仍以质量说明为准。')
    return 0


def offline_archive(command, vehicle_key, data):
    archives = [RideArchive(data, vehicle_key)] if vehicle_key else RideArchive.discover(data)
    if not archives:
        raise ValueError('没有本地档案，请先登录并采集。')
    for archive in archives:
        if command == 'migrate':
            months = archive.import_legacy()
            print(f"档案 {archive.vehicle_key}：迁移 {len(months)} 个月，旧数据保留。")
        report = summarize(archive)
        print(f"{report['months']} 个月 / {report['listed_rides']} 条行程 / {report['coordinate_points']} 个坐标点")
        print(f"导出：{archive.report_path()}")
        dataset_directory = prepare_configured(archive)
        if dataset_directory:
            print(f"标准数据：{dataset_directory}/dataset.json")
    return 0


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="九号骑行数据导出（本地保存，云端只读）")
    parser.add_argument("--data-dir", type=Path, default=DATA, help="本地档案目录")
    parser.add_argument("--config-dir", type=Path, default=CONFIG, help="私密会话目录")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="本地依赖和加密自检，不连接账号")
    doctor.add_argument("--network", action="store_true", help="另检查四个九号域名的 TLS/HTTP 连通性，不发送账号信息")
    sub.add_parser("login", help="交互式密码登录")
    sub.add_parser("vehicles", help="读取并选择车辆")
    sub.add_parser("start", help="首次使用：登录、选车、导出")
    dataset = sub.add_parser('prepare', help='离线生成统计与地图共用的标准数据')
    dataset.add_argument('--vehicle', help='档案车辆标识；省略时处理所有本地车辆')
    dataset.add_argument('--map-from', help='地图起点：YYYY-MM-DD 或带时区的 ISO 时间；省略时复用已保存设置')
    dataset.add_argument('--timezone', help='IANA 时区；默认复用已保存设置或 Asia/Shanghai')
    dataset.add_argument('--all-map-tracks', action='store_true', help='清除地图起始时间，使用全部可用采样轨迹')
    viewer = sub.add_parser('map', help='离线打开本地骑行地图，不读取账号')
    viewer.add_argument('--dataset', type=Path, help='显式选择 Ride Dataset v1 文件；省略则打开空白导入页')
    viewer.add_argument('--port', type=int, default=8765, help='本地端口；0 表示自动选择')
    viewer.add_argument('--no-open', action='store_true', help='只启动本地服务，不打开浏览器')
    viewer.add_argument('--latest', action='store_true', help='读取本地最新标准数据，自动跟随同步更新')
    schedule = sub.add_parser('schedule', help='管理本机定期增量同步')
    schedule.add_argument('action', choices=('install', 'status', 'run', 'disable', 'uninstall'))
    schedule.add_argument('--interval-days', type=float, help='连续间隔天数，默认 10；重复安装时保留已设周期')
    schedule.add_argument('--force', action='store_true', help='手动立即同步，不等待到期')
    cloud = sub.add_parser('cloud', help='私有 GitHub Actions 同步与本机下载')
    cloud.add_argument('action', choices=('install', 'status', 'run', 'pull', 'map', 'credentials', 'disable'))
    cloud.add_argument('--repo', help='私有同步仓库 owner/name')
    cloud.add_argument('--interval-days', type=float, help='连续间隔天数，默认 10')
    cloud.add_argument('--publish-repo', action='append', dest='publish_repos', help='仅接收无底图 PNG 的公开仓库，可指定两次')
    cloud.add_argument('--port', type=int, default=8765)
    cloud.add_argument('--no-open', action='store_true')
    check = sub.add_parser('validate', help='离线校验任意来源的标准 dataset.json')
    check.add_argument('path', type=Path)
    for command in ("migrate", "summarize"):
        offline = sub.add_parser(command, help="离线迁移旧档案" if command == "migrate" else "离线汇总已发布档案")
        offline.add_argument("--vehicle", help="档案车辆标识；省略时处理数据目录中的全部车辆")
    p = sub.add_parser("sync", help="批量获取月度列表及全部可用详情")
    p.add_argument("--from", dest="start", default=current_month(), help="开始月份 YYYYMM")
    p.add_argument("--to", dest="end", default=current_month(), help="结束月份 YYYYMM")
    p.add_argument("--max-pages", type=int, default=100, help="每月请求上限，默认 100 页")
    p.add_argument("--refresh-details", action="store_true", help="重新请求已成功缓存的详情")
    args = parser.parse_args(argv)
    if args.command == 'map':
        from .map_server import serve_map
        path = args.dataset
        if args.latest:
            if path:
                raise ValueError('--latest 与 --dataset 不能同时使用')
            prefs_path = args.config_dir / 'preferences.json'
            prefs = read_json(prefs_path) if prefs_path.exists() else {}
            archives = RideArchive.discover(args.data_dir)
            archive = RideArchive.for_vehicle(args.data_dir, prefs['sn']) if prefs.get('sn') else (archives[0] if len(archives) == 1 else None)
            if archive is None:
                raise ValueError('请指定 --dataset 或先选择车辆并运行 prepare。')
            path = archive.path / 'prepared' / 'dataset.json'
            if not path.exists():
                directory = prepare_configured(archive)
                if not directory:
                    raise ValueError('请先运行 ./run prepare。')
        return serve_map(path, args.port, args.no_open)
    config, data = args.config_dir.resolve(), args.data_dir.resolve()
    if args.command == 'cloud':
        from .cloud import manage
        return manage(args.action, config, data, ROOT, repo=args.repo, interval_days=args.interval_days,
                      publish_repos=args.publish_repos, port=args.port, no_open=args.no_open)
    if args.command == 'schedule':
        from .schedule import manage
        return manage(args.action, config, data, ROOT, interval_days=args.interval_days, force=args.force)
    if args.command == 'validate':
        dataset = validate_dataset(read_json(args.path))
        print(f"数据有效：{dataset['summary']['ride_count']} 条行程，{dataset['summary']['map_ride_count']} 条地图轨迹。")
        return 0
    if args.command == 'prepare':
        if args.map_from and args.all_map_tracks:
            raise ValueError('--map-from 与 --all-map-tracks 不能同时使用')
        with sync_lock(data), sync_lock(config):
            archives = [RideArchive(data, args.vehicle)] if args.vehicle else RideArchive.discover(data)
            if not archives:
                raise ValueError('没有本地档案，请先采集。')
            for archive in archives:
                settings_path = archive.path / 'dataset-settings.json'
                settings = read_json(settings_path) if settings_path.exists() else {}
                cutoff = None if args.all_map_tracks else args.map_from or settings.get('map_from')
                directory = prepare(archive, map_from=cutoff, timezone_name=args.timezone or settings.get('timezone', 'Asia/Shanghai'))
                print(f'标准数据：{directory}/dataset.json')
        return 0
    if args.command in ("migrate", "summarize"):
        with sync_lock(data), sync_lock(config):
            return offline_archive(args.command, args.vehicle, data)
    if args.command == "doctor":
        api.self_test()
        print(f"Python {sys.version.split()[0]} / cryptography {importlib.metadata.version('cryptography')}")
        print("本地自检通过。此检查未访问账号或验证服务器当前数据。")
        if args.network:
            failed = False
            for url in (api.PASSPORT_BASE, api.BIZ_BASE, api.TRAVEL_BASE, api.EBIKE_BASE):
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=10) as response:
                        status = response.status
                except urllib.error.HTTPError as exc:
                    status = exc.code
                except (urllib.error.URLError, TimeoutError, OSError):
                    print(f"{url}：连接失败，请检查网络或代理后重试。")
                    failed = True
                    continue
                print(f"{url}：TLS/HTTP 可达（HTTP {status}，不代表已通过账号认证）")
            return 1 if failed else 0
        return 0
    if args.command == "sync":
        month_range(args.start, args.end)
        if args.max_pages < 1 or args.end > current_month():
            raise ValueError("请检查月份和 max-pages 参数。")
    private_dir(config)
    private_dir(data)
    with sync_lock(data), sync_lock(config):
        return connected_command(args, config, data)


def connected_command(args, config, data):
    client = Client(config, progress=lambda message: print(message, flush=True))
    if args.command == "login":
        login(client)
        return 0
    if args.command == "start":
        if not sys.stdin.isatty():
            raise ValueError("请在终端运行 ./start.command。")
        client.recover_session()
        if not client.tokens:
            login(client)
        else:
            try:
                client.session()
            except Exception as exc:
                print(safe_error(exc))
                print("已有会话连接失败，未自动再次提交密码。需要重新认证时可运行 ./run login。")
                return 1
        sn = select_vehicle(client, config, data, interactive=True)
        start = input(f"从哪个月开始导出？YYYYMM [默认 {current_month()}]：").strip() or current_month()
        return sync(client, sn, start, current_month(), data)
    sn = select_vehicle(client, config, data, interactive=sys.stdin.isatty() and args.command == "vehicles")
    if args.command == "vehicles":
        return 0
    return sync(client, sn, args.start, args.end, data, args.max_pages, args.refresh_details)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n已中止。已落盘的原始数据和详情保留，下次运行可继续。", file=sys.stderr)
        sys.exit(130)
    except ValueError as exc:
        print(f"未完成：{exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"未完成：{safe_error(exc)}", file=sys.stderr)
        sys.exit(1)

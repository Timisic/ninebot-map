# Ninebot Map

采集九号骑行数据，在本机查看轨迹地图，导出 CSV 和 JSON，并通过 GitHub Actions 定期同步。

九号官方只提供最近 180 天的详细轨迹数据。

<!-- ninebot-track-image:start -->

![骑行轨迹](assets/ninebot-tracks.png)

<!-- ninebot-track-image:end -->

## 开始使用

安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后在 macOS 或 Linux 终端运行：

```bash
git clone https://github.com/Timisic/ninebot-map.git
cd ninebot-map
./scripts/setup.sh
./run start
```

按提示登录自己的账号、选择车辆和起始月份。脚本配置 Python 3.11+ 环境及依赖，密码隐藏输入。

```bash
./run sync                            # 同步本月并汇总
./run sync --from 202601 --to 202603    # 同步指定月份
./run prepare --all-map-tracks         # 生成全部已保存轨迹的地图数据
./run prepare --map-from 2026-01-01    # 或选择指定日期之后的轨迹
./run map --latest                    # 打开最新本地地图
```

地图支持路线叠加、日期筛选、经过区域次数和终点地点列表。后续同步沿用已保存的地图范围。

## 云端同步

先完成首次采集，并登录 [GitHub CLI](https://cli.github.com/)，再运行：

```bash
./run cloud install --publish-repo owner/ninebot-map --publish-repo owner/owner
./run cloud run                       # 立即触发云端同步
./run cloud status                    # 查看状态和下次到期时间
./run cloud map                       # 下载最新档案并打开本地地图
./run cloud pull                      # 下载档案并更新本地地图数据
./run cloud install --interval-days 7 # 修改同步周期
./run cloud disable                   # 停用云端调度
```

默认每 10 天同步一次，GitHub Actions 每小时检查到期时间。会话和完整历史档案加密保存在独立私有仓库，公开仓库更新轨迹 PNG 和 README 图片。

在本机运行 `cloud map` 或 `cloud pull` 下载最新数据，已打开的地图随后刷新。需要重新登录时，运行 `./run login`、`./run cloud credentials` 和 `./run cloud run`。

## 导入本地数据

```bash
./run map                              # 打开本地导入页
./run map --dataset /path/to/dataset.json
./run map --dataset tests/fixtures/synthetic-map.json --no-open
```

地图默认离线，可选择坐标系并开启在线道路底图。关闭终端服务按 Ctrl-C。会话存于 `.private/`，采集档案存于 `data/`，这两个目录由 Git 忽略。

[项目文档](docs/README.md) · [地图说明](docs/map-viewer.md) · [MIT License](LICENSE)

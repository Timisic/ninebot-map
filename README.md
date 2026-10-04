# Ninebot Map

非官方九号骑行数据采集工具：登录自己的账号，将行程、里程和可获取的轨迹保存在本机，导出 CSV / JSON。

**当前只做数据采集与整理，地图可视化尚未实现。**

> **云端多点轨迹通常只提供最近约 180 天的数据。** 更早的行程通常被简化为起点、终点及里程等汇总，无法据此还原道路路线。建议及时同步；已保存到本地的轨迹可继续保留。历史里程与轨迹范围分别统计。

## 功能

- 密码登录、选择本人车辆，按月分页获取行程及详情。
- 本地缓存、失败补取、覆盖检查，支持重复同步。
- 保留全部可获取里程，按日期筛选地图轨迹，生成独立的 `dataset.json`。

## 开始使用

需要 [uv](https://docs.astral.sh/uv/getting-started/installation/)；脚本会配置 Python 3.11+ 环境和依赖。终端脚本适用于 macOS / Linux。

```bash
git clone https://github.com/Timisic/ninebot-map.git
cd ninebot-map
./scripts/setup.sh
./run start
```

按提示输入**自己的手机号和账号密码**（国家码固定 86），选择车辆及起始月份。密码隐藏输入、不保存；成功会话仅存本机。短信登录及人机验证暂不支持，登录可能使手机 App 的现有会话失效。

```bash
./run sync                            # 同步本月并汇总
./run sync --from 202601 --to 202603    # 指定月份范围（示例）
./run prepare --all-map-tracks         # 生成可供后续地图读取的标准数据
./run prepare --map-from 2026-01-01    # 或只选指定日期之后的轨迹
./run summarize                       # 离线汇总，复用已保存的筛选设置
```

输出路径会显示在终端。运行 `prepare` 后，后续同步会沿用该车辆的范围设置并更新标准数据。

## 让 Agent 帮忙配置

可以把下面这段话交给本机 Agent：

> 按 README 配置 Python 和 uv，运行 setup 和 doctor。让我在本机终端输入自己的账号密码；不要索取或保存密码。登录后帮我读取车辆、同步行程并生成标准数据，不要上传会话、原始数据或坐标。

## 数据与隐私

- `.private/` 保存会话，`data/` 保存档案；两者默认被 Git 忽略，未包含在仓库中。示例和测试数据均为合成数据。
- 不要提交或上传这两个目录，也不要把令牌贴进 Issue。可用 `--config-dir`、`--data-dir` 指定其他本地目录。
- `dataset.json` 与九号账号解耦，可供后续统计或地图读取；坐标系尚未核实，不直接当作 WGS84 GeoJSON。
- 兼容性受车型、地区及九号服务端变化影响；180 天内也不保证每条轨迹完整。

[数据格式](docs/data-format.md) · [架构](docs/architecture.md) · [来源](docs/data-source.md) · [MIT License](LICENSE)

<!-- ninebot-track-image:start -->

## 骑行轨迹

![无底图骑行轨迹](assets/ninebot-tracks.png)

<!-- ninebot-track-image:end -->

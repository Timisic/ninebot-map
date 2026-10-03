# Ride Dataset v1

这是统计和未来地图共用的数据契约，不是九号云端响应格式。消费者只读取 `dataset.json`；不要求账号、车辆 SN、本地档案目录或 Python 运行环境。JSON Schema 位于 `schemas/ride-dataset-v1.schema.json`，合成示例位于 `examples/ride-dataset.json`。

## 顶层约定

| 字段 | 含义 |
| --- | --- |
| `format`, `schema_version` | 固定为 `ride-dataset`、`1` |
| `dataset_id` | 提供者指定的稳定数据集标识，不要求来自九号 |
| `generated_at` | 带时区的生成时间 |
| `timezone` | IANA 时区，明确日期的解释方式 |
| `coordinate_system` | `unverified` / `wgs84` / `gcj02` / `bd09`，不能凭字段名猜测 |
| `selection` | 统计范围恒为全部已提供行程；地图起点及筛选规则单独记录 |
| `provenance` | 数据来源说明及可选的来源快照标识，不含凭据或私有文件路径 |
| `rides` | 全部历史行程，含不进入地图的记录 |
| `tracks` | 地图范围内的采样轨迹，通过 `ride_id` 关联行程 |
| `months` | 全部来源月份的声明汇总、已列行程汇总与清单覆盖 |
| `summary` | 可根据上述内容重复计算的对账结果 |

“全部历史”指提供给数据集的全部行程，并不自动保证来源平台没有漏记录。消费者检查 `months.list_complete`、声明次数和实际次数，不能把缺少的月份补成零。

## 时间和单位

- 时间使用带时区的 ISO 8601，例如 `2026-07-01T08:30:00+08:00`。
- `distance_m` 是米，`duration_s` 是秒，`energy_wh` 是瓦时；未知值为 `null`。
- 坐标为经度、纬度数值（度），解释方式由 `coordinate_system` 指定。
- 逐点 `recorded_at`、`speed_mps` 没有可靠依据时为 `null`。当前转换器不从总时长插值 GPS 时间，也不猜测原始速度单位。
- 行程 ID 只须非空且在数据集中唯一。当前九号转换器生成稳定的不透明 ID；其他转换器可以保留自己的 GPX/CSV 标识。

## 地图范围与全部里程互不替代

`selection.map_from` 为带时区的时间或 `null`。规则固定为：行程开始时间大于等于起点，才进入候选范围；没有起点时使用全部候选行程。整条行程作为筛选单位，不伪造跨边界的中间切点。

候选行程还需为 `sampled` 且至少两个坐标点。仅保留符合这些条件的 `tracks`；所有行程仍在 `rides` 中，距离也仍参与全部历史统计。

每条行程有 `map_status`：

| 状态 | 说明 |
| --- | --- |
| `included` | 有对应的地图轨迹 |
| `before_map_start` | 早于地图起点；仅在统计中保留 |
| `unknown_start_time` | 无法可靠确定开始时间 |
| `simplified` | 简化轨迹；不能连线当作真实道路 |
| `insufficient_points` | 缺坐标或点数不足 |

时间范围优先于质量排除；因此一条早期简化行程的 `map_status` 可为 `before_map_start`，同时 `track_kind` 仍为 `simplified`。这两个字段说明不同事情。

质量类型 `track_kind` 为 `sampled`、`simplified`、`single_point` 或 `missing`。`sampled` 只表示有采样序列，不承诺从头到尾完整。`source_point_count` 记录来源中的点数，但范围外行程不附带坐标。

地图起点之后的全部行程按时间处理，不另加城市范围或地理围栏。未来骑到别处仍属于这一阶段，不会被自动丢弃。

## 关联与对账

- 每个 `tracks.ride_id` 必须关联唯一的 `rides.id`，且该行程 `map_status=included`。
- 每条轨迹的 `points.sequence` 从 0 连续递增，坐标顺序不变；不跨行程连接、不自动平滑或吸附道路。
- `source_point_count` 与实际点数一致。所有 `included` 行程都必须有轨迹，其他行程不能附带地图轨迹。
- `months.reported_*` 表示来源声明值；`listed_*` 由行程计算，两者分别保留。
- `summary.total_distance_m` 只有在每条行程里程均已知时才有值；否则为 `null`，并同时给出 `known_distance_m` 和 `missing_distance_count`，避免把缺失值当零。
- `map_distance_m` 只计算进入地图的行程，不能代替全部历史里程。

JSON Schema 负责形状和类型；`./run validate 文件路径` 另外检查上述关联、筛选和计数关系，完全离线执行。

## 其他数据来源如何使用

任何转换器都可以生成同样的 JSON：统一时间和单位、提供稳定行程 ID、按真实依据标注坐标系和轨迹质量，再执行校验。无须包含九号字段或调用九号模块。当前仓库没有实现 GPX/其他 CSV 的自动导入，也尚未实现可视化页面。

普通地图软件通常要求已知的 WGS84 GeoJSON。当前 `unverified` 坐标不会自动输出为 GeoJSON；后续在与底图叠加前应核实坐标系，然后进行明确的转换。

## 当前命令与持久化

```bash
./run prepare --map-from 2026-07-01
./run prepare --map-from 2026-07-01T08:30:00+08:00
./run prepare --all-map-tracks
./run validate examples/ride-dataset.json
```

个人范围设置只存 `data/<车辆档案标识>/dataset-settings.json`，没有写进公共代码。设置后，`sync` 与 `summarize` 会重新生成标准数据；`prepare` 也可独立离线执行。

每次生成一个独立目录，含 `dataset.json`、`rides.csv`、`map-points.csv`、`months.csv` 和 `summary.json`。文件写齐并验证通过后才切换 `prepared/latest.json`。JSON 是权威数据，CSV 仅便于人工查看；CSV 不承载完整元数据。

筛选只影响这份派生数据；原始响应、全部历史档案和已保留的采样点不删除。数据集里仍含真实出行时间和所选区域坐标，上传或公开前应另做隐私处理。

# 骑行档案与采集任务

## 两个实际 seam

**骑行档案 module** 把原始字段解释、轨迹质量、文件组织和批次发布收拢在一个 implementation。离线处理程序通过 `RideArchive(data_directory, vehicle_key)` 读取，不需要账号、SN、网络连接或详情缓存。一个本地文件 adapter 已足够，不引入数据库插件。最终可视化消费者读取下面描述的标准 `dataset.json`，不依赖 Python 档案模块。

**采集任务 module** 接受真实 `Client` 或合成读取 adapter，以及一个 `RideArchive`。`Acquisition.run(...)` 返回结果，进度通过事件回调提供。终端 adapter 负责把结果映射为文案与退出码；任务本身不读输入、不打印，也不依赖项目全局目录。

```python
from nbmap.archive import RideArchive
from nbmap.acquisition import Acquisition
from nbmap.summary import summarize

archive = RideArchive.for_vehicle(data_directory, vehicle_sn)
result = Acquisition(source, archive).run(vehicle_sn, "202609", "202610")

# 离线阅读：车辆档案标识可以从 RideArchive.discover(data_directory) 获取。
for snapshot in archive.read_months():
    rides = snapshot["rides"]
    points = snapshot["points"]
    coverage = snapshot["coverage"]
summary = summarize(archive)
```

## 一次发布的含义

每个月的 schema v2 快照自包含三部分：`rides`、`points`、`coverage`。其中质量类型、简化标记和来源说明在采集时形成，消费者不重新解释九号详情。

发布先校验行程唯一性、坐标归属、每条与总坐标数、轨迹类型、月份及覆盖声明，然后写入一个独立快照文件，最后以单次原子替换更新月份索引。读者先读取一次索引，再读取不会被后续采集覆盖的快照。未切换前，上一快照一直可用。

“发布完成”表示这批数据内部一致，不代表云端给出了全部轨迹。重复页、缺失详情等保留在覆盖说明中。清单请求失败或结构不认识时，只保存本次采集证据，不替换上一份已发布月档案。

已有完整月份时，不完整的新清单不会取代它；已有快照时，带详情请求失败的新尝试也不发布。失败证据与任务结果照常保存。首次采集尚无旧快照时，可发布内部一致但有已知覆盖缺口的结果。这个策略保护失败刷新的已有成果，并不推断不同成功响应之间哪一条路线更真实。

合并 CSV/JSON 同样写入新报告目录，文件齐备后才切换 `reports/latest.json`。旧报告和未完成批次暂时保留，没有自动清理策略。

文件原子替换提供进程中断时的一致性。常规 CLI、调度与云端导入使用数据目录的进程锁，同一目录的同步任务互斥；各月独立发布完整快照。

## 流程与恢复

`Acquisition` 负责按月执行、逐月检查点与最终合并。每次运行的 `last-task.json` 记录请求月份、已完成报告、当前月份和状态。中断后重新执行相同范围：重新读清单，复用成功详情，补取缺失项。恢复不依赖终端输出，也不跳过可能新增行程的已完成月份。

任务结果的缺口判断针对本次采集；合并报告反映全部已发布档案。如果本次某月请求失败，报告可以继续展示上一份有效月档案，任务状态仍会明确标为有缺口。

## 旧数据迁移

`import_legacy()` 是显式离线转换。读取旧 `exports/<月份>/`，必要时仅在迁移阶段读取旧详情缓存补足质量证据；比对坐标与里程，校验后发布 v2 快照。原文件保留，不进行删除或重命名。迁移中断时已发布月份有效，重跑跳过它们；不一致的月份停止迁移，避免静默猜测。

迁移完成后，离线汇总与未来地图只读取 v2 快照；`detail_file` 只是可选的证据定位，读取档案无需该文件存在。

## 保持 locality 的测试

- 档案 interface：更新途中中断仍可读上一快照；不一致坐标不得发布；移除缓存后仍可读及汇总。
- 报告 interface：生成中断仍指向上一份完整报告。
- 任务 interface：跨月中断保留检查点；重跑补取且不重复请求成功详情；非交互调用无需捕获终端行为。
- 读取 seam：真实 Client 与合成 source 使用相同行为入口，保留协议贯穿测试。

字段解释和批次规则只在档案 module 中变化，提供 locality；采集、汇总和未来地图共享档案，获得 leverage。小的 interface 背后承担实际恢复和校验行为，增加 depth，而不是增加一组转发函数。

## 面向可视化的独立数据契约

`dataset.py` 把已发布档案转换成 Ride Dataset v1：完整行程统计与地图范围分别表达。`build_dataset` 是纯转换，`validate_dataset` 检查跨记录关系，`prepare` 负责本地持久化；均不需要账号或网络。格式细节见 `docs/data-format.md` 和 `schemas/ride-dataset-v1.schema.json`。

个人的地图起点保存在数据目录中的设置里。配置后，采集任务自动生成新数据集，并在结果中返回位置；离线 `summarize` 同样可更新。后续地图 module 只依赖这个已写好的数据契约，九号读取 adapter 不进入可视化依赖链。其他数据来源需要一个转换器，但不需要复刻九号采集流程。

一次性 ninecli 对照脚本及旧汇总兼容脚本已退出当前仓库入口；既往对照证据仅作为来源记录保留。Python 依赖以 `pyproject.toml` 为准，地图浏览器库及许可固定打包在 `web/vendor/`。

# 项目文档

| 内容 | 入口 |
| --- | --- |
| 地图使用、统计口径与交互 | [地图说明](map-viewer.md) |
| 采集、本地下载与公开发布 | [运行说明](operations.md) |
| 静态只读网站与数据发布 | [静态部署](static-deployment.md) |
| 数据契约与示例 | [数据格式](data-format.md) |
| 档案与采集模块 | [架构](architecture.md) |
| 项目术语 | [领域上下文](CONTEXT.md) |
| 协议来源 | [数据来源](data-source.md) |
| 产品、样式与设计预览 | [设计文档](design/README.md) |
| Agent 的项目验收流程 | [九号验证技能](../.agents/skills/verify-ninebot-map/SKILL.md) |

在仓库根运行 `npm run verify:doctor` 检查验证环境，运行 `npm run verify:smoke` 验证地图刷新，运行 `npm run verify` 执行完整合成验收。

# 静态地图部署

页面只读取地图数据，不提供导入、上传或远程命名接口。地点名称仍保存在访问者浏览器中。更换域名会使用新的浏览器存储，不会把本人本机名称公开上传。

## 构建

运行 `./run export-site --dataset <标准数据文件> --output <新目录>` 导出可由普通静态服务器托管的目录。该目录只包含固定网页资源、许可证和 `dataset.json`。

公开数据使用 `public-ride-map` v1。保留全部历史的汇总里程和行程数、地图范围内的轨迹点、按来源时区划分的日期、每条地图行程的里程、稳定匿名标识、坐标来源声明和更新时间。日期筛选、经过次数、终点分组与地点命名继续工作。公开数据不包含被排除行程的逐条记录、精确出发结束时刻、速度、电量、车辆和账号标识、原始快照或会话。

`generated_at` 在导出时作为默认更新时间。自动发布使用采集任务的 `last_success`，发布重试不会把旧数据伪装成新采集。

需要标准库托管进程和接收器时，运行 `python scripts/build-site-bundle.py --dataset <文件> --output <新目录>`。它生成 `public/`、单独的 `code/`、服务模板、SHA-256 文件清单和同名 tar.gz。`code/` 和服务模板放在网页根目录之外。

## 服务器布局

目标主机为用户指定的服务器。示例部署根目录为 `/home/ubuntu/hong/ninebot-map-site`。

- `releases/<版本>/` 存放一个版本的 `public/` 内容。
- `current` 指向活动资源版本。
- `data/dataset.json` 保存单独更新的公开地图数据。
- `code/` 保存接收器和只读托管进程，网页不能读取它。
- `staging/` 接收初次部署包并核对清单。

服务模板见 `templates/map-site.service`。它只监听 `127.0.0.1:8766`，所有写入请求返回 405，只允许固定资源路径。`/` 和 `/index.html` 均可直接打开，目录浏览、会话和代码路径不可读取。

资源部署先在 staging 核对每个文件的类型、相对路径和 SHA-256，再放入新 releases 目录，最后原子切换 current。首次把公开数据放入 data，后续资源部署保留当前 data 文件。不要覆盖其他站点或将整个项目作为网页根目录。

## 数据单独更新

`receive-public-map.py --target <data/dataset.json>` 从标准输入读取单个公开地图 JSON，上限 40 MiB。它拒绝额外字段、统计不一致、越界坐标和比当前更旧的更新时间。验证通过后使用临时文件和原子替换发布。失败时保留已有文件，重复相同输入不改写。

接收器不接受压缩包、命令、路径参数或源码作为标准输入。脚本路径和目标文件由管理员固定。将专用 SSH 公钥限制为该 forced command，并使用 OpenSSH restrict 禁止转发和交互会话。新增这项持续访问权限须事先取得具体授权。私钥由用户安全录入私有同步仓库的 `MAP_DEPLOY_KEY` Secret，Agent 不读取或输出实际私钥。

私有同步配置的可选 site 对象包含 `host`、`user`、`port` 和已核对的 `known_hosts` 公共主机密钥行。采集器只向指定接收器发送筛选后的 JSON，不传送账号会话或原始档案。服务器不需要出站访问 GitHub。未配置 site 时保留原有图片发布行为。

失败保留 `publication_pending`，下一次到期检查重试发布，采集成功时间不前移。采集周期仍是 10 天，Actions 每天北京时间 10:17 左右检查一次，并保留手动触发。

## 域名与验证

在已存在的远程托管 Cloudflare Tunnel 中，仅新增用户授权的 `map.timisic.cc` 到 `http://127.0.0.1:8766` 的 published application 路由。不要修改其他路由、公开新的服务器监听端口或输出 Tunnel token。配置方法见 [Cloudflare 官方说明](https://developers.cloudflare.com/tunnel/get-started/)。

先运行 `npm run verify`。部署后验证实际 HTTPS 域名、静态资源、更新时间和数据摘要。用一次获授权同步验证 GitHub Actions 到服务器的数据发布，并核对服务端数据哈希。DNS 配置完成不等于网站部署完成，本地或模拟测试不等于真实链路通过。

## 仅重新发布已有档案

`sync.yml` 提供 `publish_only` 手动输入。将它设为 true，保持 force=false，会跳过10天采集门控并只发布已保存的成功档案。它不调用九号、不采用新的会话revision，也不改写 last_success。没有成功档案或已停用同步时拒绝操作，force与publish_only不能同时为true。

首次启用网站发布前，先由用户确认专用权限并安全设置MAP_DEPLOY_KEY，再把经核对的site目标加入私有配置。之后手动触发 publish_only=true 即可验收，无须重新采集。公开PNG仍走原有发布逻辑，完整展示JSON只经SSH发给指定接收器，不提交公开GitHub。

发布回执记录 mode、last_success_before、last_success_after、publication_pending 和 site_sha256。验收要求mode为publish_only、两个成功时间相同、pending=false，并且网站dataset.json的实际SHA-256等于site_sha256。网站更新时间仍采用原采集成功时间，不采用本次重新发布时间。

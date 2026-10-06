# 静态地图部署

Along 页面读取地图数据，并可通过指定服务器请求 GitHub Actions 更新。不提供导入、上传或远程命名接口。地点名称仍保存在访问者浏览器中。更换域名会使用新的浏览器存储，不会把本人本机名称公开上传。

## 构建

运行 `./run export-site --dataset <标准数据文件> --output <新目录>` 导出可由普通静态服务器托管的目录。该目录只包含固定网页资源、许可证和 `dataset.json`。

导出页面通过 `assets/<SHA-256>/` 加载同一批脚本、样式与图片。哈希包含白名单内全部原始网页资源，任一资源变化都会产生新的目录。目录内保留原有相对路径，模块导入、Leaflet 样式和默认标记图片无需改写。目录名不采用查询参数。`dataset.json` 与 `api/update` 仍相对于页面地址请求，不带资源版本。导出也保留原有资源路径，供旧入口访问。

公开数据使用 `public-ride-map` v1。保留全部历史的汇总里程和行程数、地图范围内的轨迹点、按来源时区划分的日期、每条地图行程的里程、稳定匿名标识、坐标来源声明和更新时间。日期筛选、经过次数、终点分组与地点命名继续工作。公开数据不包含被排除行程的逐条记录、精确出发结束时刻、速度、电量、车辆和账号标识、原始快照或会话。

`generated_at` 在导出时作为默认更新时间。自动发布使用采集任务的 `last_success`，发布重试不会把旧数据伪装成新采集。

需要标准库托管进程和接收器时，运行 `python scripts/build-site-bundle.py --dataset <文件> --output <新目录>`。它生成 `public/`、单独的 `code/`、服务模板、更新配置示例、SHA-256 文件清单和同名 tar.gz。`code/`、服务模板和更新配置放在网页根目录之外。构建只复制固定文件，不包含服务端令牌或更新状态数据库。

## 服务器布局

目标主机为用户指定的服务器。示例部署根目录为 `/home/ubuntu/hong/ninebot-map-site`。

- `releases/<版本>/` 存放一个版本的 `public/` 内容。
- `current` 指向活动资源版本。
- `assets/<SHA-256>/` 保留各版本的固定资源，独立于 `current`。
- `data/dataset.json` 保存单独更新的公开地图数据。
- `code/` 保存接收器、托管进程和更新代理，网页不能读取它。
- `staging/` 接收初次部署包并核对清单。

服务模板见 `templates/map-site.service`。它只监听 `127.0.0.1:8766`，只允许固定资源路径。模板使用 `--assets-root /home/ubuntu/hong/ninebot-map-site/assets` 读取持久资源。省略该选项时，使用网页根目录内的 `assets/`。版本资源要求完整的小写 SHA-256 和固定文件名，拒绝查询参数、目录穿越、网页数据及私有路径。解析后的文件必须位于资源根目录内。

唯一可接收 POST 的路径是 `/api/update`，其他写入请求返回 405。`/` 和 `/index.html` 均可直接打开，目录浏览、会话、代码、令牌和更新数据库路径不可读取。

资源部署先在 staging 核对每个文件的类型、相对路径和 SHA-256，再放入新 releases 目录。切换前，把本版本 `assets/<SHA-256>/` 完整复制到持久 `assets/` 目录。同名目录应核对现有字节并复用，不能覆盖成不同内容。最后原子切换 current。不要删除已发布的资源目录，旧页面仍可能请求旧版本的模块或图片。部署回滚同样保留这些目录。

版本资源返回 `Cache-Control: public, max-age=31536000, immutable`。HTML 和公开数据返回 `no-cache`，更新接口返回 `no-store`。即使 CDN 延长脚本与样式的缓存时间，新页面也会请求新的哈希目录。首次把公开数据放入 data，后续资源部署保留当前 data 文件。不要覆盖其他站点或将整个项目作为网页根目录。

## 数据单独更新

`receive-public-map.py --target <data/dataset.json>` 从标准输入读取单个公开地图 JSON，上限 40 MiB。它拒绝额外字段、统计不一致、越界坐标和比当前更旧的更新时间。验证通过后使用临时文件和原子替换发布。失败时保留已有文件，重复相同输入不改写。

接收器不接受压缩包、命令、路径参数或源码作为标准输入。脚本路径和目标文件由管理员固定。将专用 SSH 公钥限制为该 forced command，并使用 OpenSSH restrict 禁止转发和交互会话。新增这项持续访问权限须事先取得具体授权。私钥由用户安全录入私有同步仓库的 `MAP_DEPLOY_KEY` Secret，Agent 不读取或输出实际私钥。

私有同步配置的可选 site 对象包含 `host`、`user`、`port` 和已核对的 `known_hosts` 公共主机密钥行。采集器只向指定接收器发送筛选后的 JSON，不传送账号会话或原始档案。只接收数据时，服务器无需出站访问 GitHub。启用公开更新按钮后，服务器需要访问 `https://api.github.com`。未配置 site 时保留原有图片发布行为，公开更新请求则拒绝执行。

失败保留 `publication_pending`，下一次到期检查重试发布，采集成功时间不前移。采集周期仍是 10 天，Actions 每天北京时间 10:17 左右检查一次，并保留手动触发。

## 启用公开更新

任何访客都可以请求更新。服务器对所有访客共享一个时钟，两次接纳请求必须间隔严格大于 12 小时。恰好 12 小时仍返回 429。已经接纳的请求即使失败、超时或无法确认，也占用该间隔。重复点击不会创建另一个 Actions 运行。本人手动运行和原有 10 天调度继续使用各自的策略。

部署前保持服务器 UTC 时钟同步。冷却时间使用服务器时钟，时钟向后调整延长等待，向前跳变可能缩短实际等待。更新数据库位于 `/var/lib/along-map-update/state.sqlite3`，独立于网页版本和地图数据。资源升级和服务重启保留它。数据库损坏时关闭更新入口，不创建新的时钟。

配置需要以下步骤。

1. 将 `templates/map-update.json` 复制到 `/etc/along-map/update.json`。仅配置私有同步仓库和公开网站的精确 HTTPS Origin。工作流固定为 `sync.yml`，分支固定为 `main`。
2. 创建仅限该私有仓库的细粒度 PAT，授予 Actions read and write。不要授予 Contents、Secrets 或组织权限。服务器仅调用固定工作流的 dispatch 和运行状态接口。[GitHub dispatch 权限说明](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)。
3. 由管理员将令牌安全录入 `/etc/along-map/github-token`，文件由 root 所有且权限为 0600。令牌不要进入仓库、部署包、命令参数或浏览器。
4. 在 systemd 服务中启用 `LoadCredential=github-token:/etc/along-map/github-token`。服务通过 systemd credential 读取令牌。`StateDirectory=along-map-update` 和 `UMask=0077` 限制状态文件权限。
5. 私有工作流采用 `templates/cloud-sync.yml`。公开请求携带服务器生成的 UUID v4，工作流使用 `Along public <UUID>` 的运行名称。采集端要求网站和两个不同的 PNG 目标均已配置。
6. 重载 systemd 并重启 `ninebot-map-site.service`。先检查只读 `GET /api/update`，再用一次获授权的 POST 检查真实 Actions、地图和两处 PNG 发布。

缺少配置或 credential 时，网页和已有地图继续可用，更新状态为 `unavailable`。普通静态托管不会获得触发能力。配置令牌后再向服务添加 credential 指令，避免未配置时影响地图托管。

API 仅返回 `phase`、`can_request`、`requested_at` 和 `next_allowed_at`。`phase` 为 `idle`、`queued`、`running`、`succeeded`、`failed`、`unknown` 或 `unavailable`。GET 读取数据库，不访问 GitHub。POST 必须携带 JSON 空对象、匹配配置的 Origin，且不能来自 cross-site 或 same-site 页面。请求体上限为 64 字节。不返回 CORS 头、私有仓库地址、上游错误正文、运行 URL 或令牌。

POST 返回 202 表示接纳，429 表示冷却，503 表示配置或存储不可用，502 表示 GitHub 明确拒绝，403 表示来源不符。202 不表示完成。独立于浏览器的服务端观察线程每 15 秒读取 Actions 状态，五分钟后降为每 60 秒，最长观察六小时。超时、崩溃、204 和无法解析的响应只通过 UUID 查询恢复，不重新发送 dispatch。服务重启接管已保存请求。

成功要求关联 UUID 的运行成功、`sync` job 和采集发布 step 成功，并且实际提供的 `dataset.json` 通过校验且采集更新时间晚于请求前版本。数据库保存实际文件的 SHA-256 作为内部证据。跳过采集、工作流失败、旧文件或无效文件均不会报告成功。`unknown` 表示结果尚无法确认，仍保留冷却时间。页面显示的更新于时间继续来自有效地图数据。

## 域名与验证

在已存在的远程托管 Cloudflare Tunnel 中，仅新增用户授权的 `map.timisic.cc` 到 `http://127.0.0.1:8766` 的 published application 路由。不要修改其他路由、公开新的服务器监听端口或输出 Tunnel token。配置方法见 [Cloudflare 官方说明](https://developers.cloudflare.com/tunnel/get-started/)。

先运行 `npm run verify`。静态验收在同一浏览器中先打开旧样式，再切换导出版本并正常导航。服务器将脚本与样式缓存设为四小时，该流程不拦截请求。验收要求新页面读取新哈希目录、Running 恢复无边框、暗色地图恢复中性灰，并验证默认 Leaflet 标记图片。

部署后验证实际 HTTPS 域名、静态资源、更新时间和数据摘要。用一次获授权同步验证 GitHub Actions 到服务器的数据发布，并核对服务端数据哈希。DNS 配置完成不等于网站部署完成，本地或模拟测试不等于真实链路通过。

## 仅重新发布已有档案

`sync.yml` 提供 `publish_only` 手动输入。将它设为 true，保持 force=false，会跳过10天采集门控并只发布已保存的成功档案。它不调用九号、不采用新的会话revision，也不改写 last_success。没有成功档案或已停用同步时拒绝操作，force与publish_only不能同时为true。

首次启用网站发布前，先由用户确认专用权限并安全设置MAP_DEPLOY_KEY，再把经核对的site目标加入私有配置。之后手动触发 publish_only=true 即可验收，无须重新采集。公开PNG仍走原有发布逻辑，完整展示JSON只经SSH发给指定接收器，不提交公开GitHub。

发布回执记录 mode、last_success_before、last_success_after、publication_pending 和 site_sha256。验收要求mode为publish_only、两个成功时间相同、pending=false，并且网站dataset.json的实际SHA-256等于site_sha256。网站更新时间仍采用原采集成功时间，不采用本次重新发布时间。

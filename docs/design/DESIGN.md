---
name: Along
description: 以路线为中心的 Along 地图与跟随系统的外观
colors:
  panel: "#2a2c2e"
  ink: "#eceeed"
  secondary: "#b6babb"
  primary: "#d4dedc"
  line: "#44484a"
  focus: "#b4cbc8"
  background: "#202123"
  map-background: "#202123"
  hover: "#343739"
  hover-line: "#6c7375"
  active: "#3b4042"
  selected: "#3b4444"
  selection: "#becdca"
  selection-ink: "#202b2a"
  error-panel: "#472d2c"
  error-line: "#c78880"
  error-ink: "#ffe2dd"
  marker: "#b2efdf"
  marker-selected: "#f3fff9"
  marker-fill: "#2a2c2e"
  marker-shadow: "#151718"
  on-primary: "#202b2a"
  route: "#36b9bf"
  light-panel: "#ffffff"
  light-ink: "#203534"
  light-secondary: "#596e6a"
  light-primary: "#136c70"
  light-line: "#dbe5e1"
  light-focus: "#117f85"
  light-map-background: "#edf2ef"
  light-hover: "#eef4f2"
  light-hover-line: "#a9c2bb"
  light-active: "#dfede8"
  light-selected: "#e4f1ed"
  light-selection: "#c7e7de"
  light-selection-ink: "#173e35"
  light-error-panel: "#fff0ed"
  light-error-line: "#cf9184"
  light-error-ink: "#783626"
  light-marker: "#076974"
  light-marker-selected: "#063e47"
  light-marker-fill: "#ffffff"
  light-marker-shadow: "#ffffff"
  light-on-primary: "#ffffff"
  light-background: "#f4f7f6"
typography:
  title:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "20px"
    lineHeight: 1.5
    fontWeight: 600
  section:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "16px"
    lineHeight: 1.5
    fontWeight: 600
  empty-title:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "20px"
    lineHeight: 1.5
    fontWeight: 600
  mobile-title:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "16px"
    lineHeight: 1.5
    fontWeight: 600
  count:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "18px"
    lineHeight: 1.5
    fontWeight: 550
  body:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  control:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    lineHeight: 1.5
  drag-prompt:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "24px"
    lineHeight: 1.5
  mobile-label:
    fontFamily: '"Smiley Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    lineHeight: 1.5
rounded:
  marker: "#b2efdf"
  place-row: "7px"
  control: "8px"
  notice: "9px"
  popover: "10px"
  panel: "#2a2c2e"
spacing:
  compact: "8px"
  popover: "12px"
  edge: "16px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  field:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 10px"
  place-panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.panel}"
    width: "320px"
  place-selected:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.ink}"
    padding: "8px"
    rounded: "{rounded.place-row}"
  destination-marker:
    textColor: "{colors.marker}"
    rounded: "{rounded.marker}"
    size: "44px"
---

# Along 地图界面

桌面使用 64px 顶栏，700px 以下使用 56px。左上显示 Riding ｜ Running，浏览器标题使用 Along。Running 仅显示“正在running中...”的小提示，提示锚定到按钮，不切换地图。右侧保留外观和常去地点。地图左上使用透明更新按钮，圆角刷新图标与“更新”并排。旁边一行小字显示最近一次成功采集的月、日和时分，完整日期保存在 time 元素及提示文字中。按钮保留 44px 点击区域，不使用永久填色或阴影。只有排队、运行、等待数据与失败等必要状态另占一行。成功结果保留在无视觉占位的 aria-live 区域。左下将当前地图、全部历史的次数与里程合并到路线图例，全部使用现有图例的 11px 字阶，不新增框。网页不提供日期筛选、导入或上传入口。右下保留全图、图层与 44px 缩放控件。

首次打开跟随系统。外观菜单允许浅色、深色和跟随系统，选择保存在浏览器。跟随系统时立即响应系统外观变化，手动选择不受系统变化影响。深色地图使用 #202123 石墨灰，面板使用 #2a2c2e，路线保留蓝绿色。浅色保持白色面板与浅灰绿地图。所有界面文字使用本地得意黑 Smiley Sans v2.0.1，保留系统字体作为加载失败时的后备。只加载真实的 regular 字体文件，禁用合成粗体和斜体。来源与许可证见[字体说明](font.md)。控件采用 9px 圆角，浮动工具组 12px，弹层 14px。浮动工具使用柔和偏移阴影，停靠面板使用分隔线。地图自身建立层叠上下文，原生缩放按钮不能覆盖设置弹层。

更新按钮复用公开站点的同源更新接口，浏览器不持有凭证。所有访客共用服务端 12 小时间隔。冷却期仍可点击，显示“正在Riding中...”，与 Running 共用同一个提示组件。排队和运行时显示小字状态；工作流成功后继续等待新数据，只有观察到该次请求之后的采集时间才显示“地图已更新”。失败保留当前地图。未配置接口的本地或静态页面禁用更新按钮，仅通过按钮提示说明原因。

地点面板在宽屏占右侧 320px，中屏 290px；700px 以下停靠底部，高度不超过 260px 或视口的 34%。地图尺寸同步调整，不被面板覆盖。未选地点时不预留详情空间，选中后显示紧凑详情，列表独立滚动。560 至 700px 时列表与详情并排，短横屏压缩详情标题，保留完整操作。标题行提供“统计口径”入口。显式选中后将所选行滚入可见范围，保留骑行日与自然时长；主题切换和刷新不触发此滚动。命名地点保留地图针，未命名地点仅在三秒提示期间显示临时针。选中针使用浅色圆盘与深色轮廓，位于其他地图针上方。圆盘使用深色细边，使浅色地图中的选择也可辨认。三秒提示增加浅色范围和地图针上方的小号地点名称。名称为非交互文本，宽度不超过 180px。重复点击或定位重新开始三秒提示，并保留选择与草稿。重绘及同一数据集刷新保留原截止时间和动画进度。提示结束不改变选择、草稿或视角。减少动画偏好显示静态提示。明确取消、地点删除、数据集切换及页面关闭清除提示。关闭面板保留选择和草稿。定位由明确按钮触发。

单次路线先画完整底线。暗色底线 #36b9bf，叠加 #53b9bb；浅色底线 #167e87，叠加 #053d48。暗色重复经过变亮，浅色变深。线宽限制在 1.8–2.8px，随缩放小幅变化；主题对应衬线帮助分离底图。选择地点后其他路线弱化，取消选择恢复。图例只描述强弱，不声称道路精确次数。

连续缩放保留目标级别、指针地理锚点和动画帧状态。路线与缩放同步绘制。底图不订阅每帧 setView 的 viewprereset 全量清空事件，保留原生层级更新、瓦片替换与回收。减少动画偏好直接应用小数级缩放。页面始终绘制原始坐标，不修改文件中的来源声明。道路底图开关只控制瓦片。

视觉参考 [Apple 地图](https://www.apple.com.cn/maps/) 和 [Mapbox Light](https://www.mapbox.com/maps/light)。不引入它们的 SDK 或服务。界面继续使用原生 HTML、CSS、JavaScript 及现有 Leaflet、gcoord、Lucide。放大、缩小、全图与刷新使用本地 SVG，统一圆角线帽与连接点。全图保留可访问名称与提示文字。外观图标在 44px 按钮内居中，只有展开箭头使用自动左边距。

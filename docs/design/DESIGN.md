---
name: 骑行地图
description: 以路线为中心的本地骑行地图与可切换深浅色控件
colors:
  panel: "#213237"
  ink: "#eef6f3"
  secondary: "#b1c5bf"
  primary: "#8adbd1"
  line: "#3d5559"
  focus: "#9ae7de"
  background: "#142126"
  map-background: "#142126"
  hover: "#30484a"
  hover-line: "#688681"
  active: "#365451"
  selected: "#2d504e"
  selection: "#75c8c3"
  selection-ink: "#142b2a"
  error-panel: "#472d2c"
  error-line: "#c78880"
  error-ink: "#ffe2dd"
  marker: "#b2efdf"
  marker-selected: "#f3fff9"
  marker-fill: "#213237"
  marker-shadow: "#10282b"
  on-primary: "#142b2a"
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
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "20px"
    lineHeight: 1.5
    fontWeight: 600
  section:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "16px"
    lineHeight: 1.5
    fontWeight: 600
  empty-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "20px"
    lineHeight: 1.5
    fontWeight: 600
  mobile-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "16px"
    lineHeight: 1.5
    fontWeight: 600
  count:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "18px"
    lineHeight: 1.5
    fontWeight: 550
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  control:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    lineHeight: 1.5
  drag-prompt:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "24px"
    lineHeight: 1.5
  mobile-label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    lineHeight: 1.5
rounded:
  marker: "#b2efdf"
  place-row: "7px"
  control: "8px"
  notice: "9px"
  popover: "10px"
  panel: "#213237"
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

# 骑行地图界面

桌面使用 64px 顶栏，700px 以下使用 56px。标题、主题、导入和常去地点保留在顶栏。左上统计以当前地图为主、全部历史为次，日期按需展开。右下统一全图、图层与 44px 缩放控件。“图层”仅含道路底图和经过次数两个开关，移除坐标菜单和数据隐私折叠块。左下只显示路线叠加图例。

默认深色，浅色选择保存在浏览器。白色面板搭配浅灰绿地图；深色为低饱和蓝绿。字体使用系统中文无衬线字体。控件采用 9px 圆角，浮动工具组 12px，统计和弹层 14px。浮动工具使用柔和偏移阴影，停靠面板使用分隔线。地图自身建立层叠上下文，原生缩放按钮不能覆盖设置弹层。

地点面板在宽屏占右侧 320px，中屏 290px；700px 以下停靠底部。地图尺寸同步调整，不被面板覆盖。560–700px 的底部面板把列表和地点详情并排显示。选中详情保留固定空间，命名由按钮进入，列表不会因选中缩成一行。重复选中保持状态，关闭面板保留选择和草稿。定位由明确按钮触发。

单次路线先画完整底线。暗色底线 #36b9bf，叠加 #53b9bb；浅色底线 #167e87，叠加 #053d48。暗色重复经过变亮，浅色变深。线宽限制在 1.8–2.8px，随缩放小幅变化；主题对应衬线帮助分离底图。选择地点后其他路线弱化，取消选择恢复。图例只描述强弱，不声称道路精确次数。

连续缩放保留目标级别、指针地理锚点和动画帧状态。路线与缩放同步绘制。底图不订阅每帧 setView 的 viewprereset 全量清空事件，保留原生层级更新、瓦片替换与回收。减少动画偏好直接应用小数级缩放。页面始终绘制原始坐标，不修改文件中的来源声明。道路底图开关只控制瓦片。

视觉参考 [Apple 地图](https://www.apple.com.cn/maps/) 和 [Mapbox Light](https://www.mapbox.com/maps/light)。不引入它们的 SDK 或服务。界面继续使用原生 HTML、CSS、JavaScript 及现有 Leaflet、gcoord、Lucide。

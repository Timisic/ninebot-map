---
name: 骑行地图
description: 以路线为中心的本地骑行地图与可切换深浅色控件
colors:
  panel: "#203235"
  ink: "#edf5f2"
  secondary: "#b6c9c6"
  primary: "#75c8c3"
  line: "#4b6467"
  focus: "#9fe4de"
  background: "#172426"
  map-background: "#172426"
  hover: "#30484b"
  hover-line: "#718f91"
  active: "#3b575a"
  selected: "#31534f"
  selection: "#75c8c3"
  selection-ink: "#142b2a"
  error-panel: "#472d2c"
  error-line: "#c78880"
  error-ink: "#ffe2dd"
  marker: "#a9eee4"
  marker-selected: "#e1fff8"
  marker-fill: "#203235"
  marker-shadow: "#132022"
  on-primary: "#142b2a"
  route: "#75c8c3"
  light-panel: "#fafaf7"
  light-ink: "#26332f"
  light-secondary: "#59665f"
  light-primary: "#25675f"
  light-line: "#d8ded7"
  light-focus: "#26766b"
  light-map-background: "#e6eadf"
  light-hover: "#e9efea"
  light-hover-line: "#aab9ae"
  light-active: "#dce8df"
  light-selected: "#e4efea"
  light-selection: "#c8e3da"
  light-selection-ink: "#203d34"
  light-error-panel: "#fff0ef"
  light-error-line: "#bd756c"
  light-error-ink: "#722e28"
  light-marker: "#125950"
  light-marker-selected: "#123e35"
  light-marker-fill: "#fafaf7"
  light-marker-shadow: "#fff"
  light-on-primary: "#fff"
  light-background: "#e6eadf"
typography:
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "18px"
    lineHeight: 1.5
    fontWeight: 600
  section:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "15px"
    lineHeight: 1.5
    fontWeight: 600
  empty-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "20px"
    lineHeight: 1.5
    fontWeight: 600
  mobile-title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "16px"
    lineHeight: 1.5
    fontWeight: 600
  count:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "17px"
    lineHeight: 1.5
    fontWeight: 550
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  control:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "13px"
    lineHeight: 1.5
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "12px"
    lineHeight: 1.5
  drag-prompt:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "24px"
    lineHeight: 1.5
  mobile-label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "11px"
    lineHeight: 1.5
rounded:
  marker: "6px"
  place-row: "7px"
  control: "8px"
  notice: "9px"
  popover: "10px"
  panel: "12px"
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
    width: "256px"
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

地图占据主画面，52px顶栏保留标题、明暗切换、导入、全图和地点入口。默认深色，明确选择保存在此浏览器；切换时保留视角、筛选、地点选择和未保存的命名草稿。

无前缀颜色记录深色，light-前缀记录浅色。浅色底图保留OpenStreetMap原色；深色只对瓦片使用invert(1) hue-rotate(180deg)，不增加模糊或缩放。路线在浅色背景上增加深色衬线，两种主题均用Canvas lighter叠加路线。

地点面板默认收起，展开宽256px，限制高度并在内部滚动。名称14px、次数17px。地图针16px，选中时19px；透明按钮保持44px点击区域。顶部主题按钮同样保留44px区域和可访问名称。

左下角保留经过次数和设置。设置只直接显示道路底图、坐标系及必要的禁用原因；解释和诊断放入数据与隐私。日期与设置均可键盘展开。

700px以下隐藏顶栏状态，标题单行省略，操作不压缩。日期弹层右对齐，地点面板位于右下。字体与圆角尺度记录全部已使用尺寸；减少动画偏好下关闭过渡。

滚轮累计到阈值后立即围绕指针改变一级，连续输入锁定到短暂停顿，避免惯性连跳；保留整数缩放。触摸、键盘和按钮继续使用Leaflet原有处理。高分屏在线缩放上限跟随有效瓦片上限，关闭底图后恢复离线上限。

样式以web/styles.css为准，交互以web/app.mjs、web/map-layer.mjs和web/wheel-zoom.mjs为准。设计预览在.impeccable/design.json，色阶仅用于预览。布局参考[oil-ui](https://github.com/oil-oil/oil-ui)及[Trail](https://ui.oiloil.org/works/trail/)。Lucide固定图标子集的ISC许可与来源保留在web/vendor/lucide/。

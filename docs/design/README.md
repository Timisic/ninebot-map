# 地图设计文档

- [PRODUCT.md](PRODUCT.md) 保存产品目的与使用场景。
- [DESIGN.md](DESIGN.md) 保存地图布局、主题、字阶和交互规范。
- [字体说明](font.md) 保存得意黑的来源、版本、文件校验与许可证。
- [.impeccable/design.json](.impeccable/design.json) 是设计预览产物，属于项目文档。

Impeccable 本体由 Agent 的技能环境提供，仓库不复制它的全局安装。使用已安装技能的 launcher，从仓库根运行 `impeccable context --target docs/design`，能够读取此处的产品与设计文档。launcher 的实际路径由当前技能安装位置提供。

加载上下文后，代码路径仍以仓库根为准，主要是 `web/`。直接把 `web/` 文件传给 Impeccable 的 context 或检测命令会重新定位文档查找位置；这类命令不会自动找到这里的文档。先加载上述设计上下文，并显式阅读本目录规范，再执行针对源码的操作。

修改界面后，运行 `npm run verify -- --suite map`；修改缩放时增加 `--suite wheel`，修改数据刷新时增加 `--suite refresh`。

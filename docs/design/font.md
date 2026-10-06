# 得意黑字体

Along 使用 atelierAnchor 官方发布的得意黑 Smiley Sans v2.0.1。字体文件来自[官方发布](https://github.com/atelier-anchor/smiley-sans/releases/tag/v2.0.1)，保留原始字形和文件内容。

| 文件 | SHA-256 |
| --- | --- |
| `web/fonts/smiley-sans/SmileySans-Oblique.woff2` | `731f22973349404b15a88a99ef3b5dd4104c0965c23b7e485c1f11e84fea99e2` |
| `web/fonts/smiley-sans/LICENSE` | `9401f4050f1b66c26b6ccdc8b0e14a3c1cc37aac122eda84386f25854a9bec72` |

字体采用 SIL Open Font License 1.1，版权所有者为 atelierAnchor。保留字体名为 Smiley 和得意黑。[完整许可证](../../web/fonts/smiley-sans/LICENSE)随字体一并提供。

CSS 使用一个真实的 regular face，文件本身带有得意黑的倾斜字形。`font-synthesis: none` 禁止浏览器制造粗体或额外斜体。界面、表单与 Leaflet 文字优先使用该字体，系统字体在字体文件无法加载时提供后备。

WOFF2 与许可证进入 `viewer_resources.ASSETS` 的固定资源白名单。版本资源图、公开静态导出与本地地图都包含相同文件。字体通过 CSS 相对路径读取，不请求远程字体服务。

运行 `npm run verify -- --suite map` 检查实际 FontFaceSet 加载和字号。运行 `npm run verify -- --suite static` 检查嵌套路径、字体 MIME、原始字节和许可证。Python 地图服务与公开导出测试检查固定资源和版本资源中的文件内容。

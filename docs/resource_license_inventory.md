# 公开源码资源许可清单

本清单覆盖 `src/dxband/resources/` 中的非 Python 文件。新增资源时须先确定来源、可再分发条件，并同步更新本页及 `scripts/check_open_source_resources.py`。检查脚本还会核对整个 Git 暂存文件列表，拒绝模型权重、未登记的音视频和本轮排除的 `website/`、`docs/releases/`；资源目录内未登记的文件或缺少许可说明也会失败。

| 文件或目录 | 主要资源数 | 权利来源与处理 |
| --- | ---: | --- |
| `dx_band_icon.png`、`dx_band_icon.ico`、`dx_band_icon.icns`、`dx_band_sidebar_logo.png` | 4 | 项目所有者确认原创，可随源码公开；DX Band 名称与标志的商标使用边界见 `LICENSING.md`。 |
| `controls/*.svg` | 31 | Font Awesome Free 7.2.0 Classic Solid；SVG 适用 CC BY 4.0。保留每个 SVG 的上游注释、`controls/NOTICE.md` 的逐项映射及上游 `LICENSE.txt`。仅改填充色。 |
| `fontawesome/*.svg` | 4 | Font Awesome Free 7.2.0 Classic Solid；SVG 适用 CC BY 4.0。保留上游注释及 `fontawesome/NOTICE.md`。 |
| `instruments/bass-clef.svg`、`instruments/piano-keys.svg` | 2 | DX Band 自绘；见 `instruments/NOTICE.md`，随项目自研素材公开。 |
| `background_videos/*.mp4` | 3 | 项目所有者确认原创的观众屏预设循环背景视频；保留程序使用的原文件名。 |
| `fonts/audience/{longcang,mashanzheng,zcoolqingkehuangyou,zcoolxiaowei}/` | 4 款字体及各自 `OFL.txt` | Google Fonts 上游 SIL OFL 1.1；保留每款字体原许可证。`fonts/audience/README.md` 记录来源。 |
| `web_musician/index.html`、`web_singer/index.html`、`raw_score_preview/index.html` | 3 | DX Band 自研页面，带 GPL-3.0-only SPDX 声明。 |
| `web_musician/vendor/jianpurender/` | 3 | 官方 `jianpurender@1.8.1` 的 JS、Apache-2.0 `LICENSE`、`NOTICE`；JS 与许可证已核对为上游原件。 |

加上各目录中的许可证、署名文件及 `fonts/audience/README.md`，程序资源目录共 63 个文件。README 使用的界面截图、项目客服二维码和精简演示视频位于 `docs/assets/`，来源与用途见 [LICENSING.md](../LICENSING.md)。本仓库仅收录已登记的三段原创预设背景视频和一段精简演示视频；不收录模型权重、用户歌曲音频或客户资料。

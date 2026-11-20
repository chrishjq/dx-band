# 为 DX Band 做贡献

项目自研代码采用 [GPL-3.0-only](LICENSE)，适用范围见[许可说明](LICENSING.md)。贡献自研代码即同意按 GPL-3.0-only 提交；提交者保留自己贡献的版权。不要将无权再分发的第三方代码或素材提交到仓库。

## 从哪里开始

请先阅读 [项目说明](README.zh-CN.md)。算法改进先创建 Issue，写清输入特征、当前输出、期望输出、复现步骤和判断改进是否有效的指标。音频、歌词和截图只能使用你有权公开分享的内容；无法公开时提供可合成的最小样例。

适合讨论的方向包括节拍与小节线、和弦、旋律、歌词逐字对齐、六轨播放时钟和多屏同步。大型设计变更先在 Issue 说明接口和数据格式影响。

## 本地开发

- Python 3.11 或 3.12、[uv](https://docs.astral.sh/uv/)；创建歌曲还需要 FFmpeg。
- 在仓库根目录执行 `uv sync --extra ai --extra dev`，再运行 `uv run pytest -q tests/analysis tests/creation tests/integration tests/services tests/unit` 和 `uv run pytest -q tests/ui`。分成两个进程运行，避免本机 Qt WebEngine 混合全量测试时偶发原生崩溃。另运行 `uv run ruff check src scripts/check_open_source_resources.py scripts/beat_benchmark.py scripts/run_beat_this.py`、`uv run mypy src` 和 `uv run python scripts/check_open_source_resources.py`。
- 节拍改进可先用[合成节拍基准](docs/beat_benchmark.md)生成没有版权负担的 WAV 与参考拍点，再报告同一模型版本下的前后精确率、召回率和 F1。
- 需要真实 AI 推理时，按[用户自备模型方案](docs/model_self_setup.md)从原站自行准备模型。模型权重的许可和下载条件应单独遵守；基础测试不下载模型。
- 当前发布按 macOS 本机验证；修改平台相关逻辑时，请说明实际验证的平台。

## 提交与评审

1. 每个 PR 聚焦一个问题，链接对应 Issue，说明原因、改动和验证结果。
2. 更改分析算法时提供可公开的复现样例及前后结果。更改歌曲包格式时同步更新 schema、示例与相关测试。
3. 遵守 README 的模块边界：核心逻辑不依赖 `ui/`，新增终端先定义可序列化协议。
4. 不提交歌曲、歌词、模型权重、构建产物、私钥、令牌、客户数据或未经授权的字体与媒体。发现疑似安全问题时不要先公开凭据或可利用细节，先联系维护者处理。
5. 提交中使用的第三方代码和资源须注明来源、许可证及修改内容。贡献者应有权按 GPL-3.0-only 提交自研代码；第三方资源保留原许可，不能用项目许可证覆盖。

维护者会按问题可复现性、项目方向、兼容性和测试结果评审；提交 PR 不保证合并。参与社区请遵守[行为准则](CODE_OF_CONDUCT.md)，漏洞及敏感信息按[安全报告说明](SECURITY.md)私密提交。

# 用户自备模型指南

DX Band 源码仓库不包含模型权重。创建歌曲前，请阅读各模型原站的使用条款，自行下载所需文件并放在本机。程序从本地目录或 Hugging Face 缓存读取模型；缺少资源时会提示来源和配置方法。模型许可与项目源码许可分别适用，详见 [MODEL_NOTICES.md](../MODEL_NOTICES.md)。

## 权利边界

- [SheetSage2](https://huggingface.co/m-a-p/SheetSage2) 和 [MERT-v2-FullSong](https://huggingface.co/m-a-p/MERT-v2-FullSong) 的模型页标为 CC BY-NC 4.0，商业使用须取得适用授权。
- [HTDemucs-6s](https://huggingface.co/adefossez/HTDemucs-6s) 的模型仓库未声明明确的权重许可。[上游讨论](https://github.com/facebookresearch/demucs/issues/327)指出预训练权重不受 Demucs 源码 MIT 许可覆盖，仅供科研用途。
- Fun-ASR 的模型代码和权重是不同的许可对象。使用 [ModelScope 模型](https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512)时，请核对所下载权重文件的许可；其已核对修订未提供明确的权重许可文件。

自行下载并不扩大上游授予的权利。若要商业使用涉及受限权重的功能，请先取得权利人许可或更换模型。

## 配置模型

| 功能 | 模型来源与本地配置 |
| --- | --- |
| 音符与和弦分析 | 设置页会优先从 [魔搭 SheetSage2](https://www.modelscope.cn/models/m-a-p/SheetSage2) / [MERT](https://www.modelscope.cn/models/m-a-p/MERT-v2-FullSong) 下载到本机（国内 CDN）；失败时再试 HF 镜像。也可自行放置：`DX_BAND_SHEETSAGE2_MODEL_DIR` 指向 SheetSage2 目录，`DX_BAND_MERT_MODEL_DIR` 指向 MERT 目录，或用 `DX_BAND_SHEETSAGE2_HF_HOME` 指向含 MERT 的 Hugging Face 缓存。 |
| 六轨分离 | 从 HTDemucs-6s 模型页取得 `htdemucs_6s.yaml` 与 `5c90dfd2.safetensors`，放入标准 Hugging Face 缓存。 |
| 中文、英文和粤语歌词对齐 | 使用下方命令将对应 CTC 模型放入标准 Hugging Face 缓存；也可设置 `DX_BAND_ALIGNER_ZH_MODEL_DIR`、`DX_BAND_ALIGNER_EN_MODEL_DIR`、`DX_BAND_ALIGNER_YUE_MODEL_DIR` 指向本地模型目录。 |
| 节拍分析 | 从 [Beat This!](https://github.com/CPJKU/beat_this) 取得 `final0` checkpoint，设置 `DX_BAND_BEAT_THIS_CHECKPOINT` 指向本地文件。 |
| 歌词识别 | 从 [Fun-ASR](https://github.com/QwenAudio/Fun-ASR) 取得模型代码，设置 `DX_BAND_FUN_ASR_MODEL_CODE`；从原站取得权重，设置 `DX_BAND_FUN_ASR_MODEL_DIR` 指向包含 `configuration.json` 或 `config.yaml` 的目录。 |

在阅读相应模型许可后，可从用户自己的终端运行以下命令，下载 Demucs 和 CTC 模型到标准缓存：

```bash
uv run hf download adefossez/HTDemucs-6s htdemucs_6s.yaml 5c90dfd2.safetensors
uv run hf download parseh/aligner-zh --revision 920ed68179700a9380364a119744e046e04fb14d
uv run hf download parseh/aligner-en --revision c0f8960268a23db8e3705ef24d3236e419739975
uv run hf download ctl/wav2vec2-large-xlsr-cantonese --revision 11cb21cb68b4ed15f4c6633494ae6cc90a89bc34
```

也可在桌面应用的「设置 → 创建所需资源」查看各功能资源是否就绪，并点击「下载缺失资源」一次性安装多媒体组件与缺失模型。设置页只显示功能名称（如节拍模型、歌词适配模型），不展示具体上游模型名。下载仍表示你同意遵守各模型原站许可。

下载顺序：优先公共节点（魔搭、GitHub 代理、HF 镜像等）；仅当公共节点失败时，才回退到国内静态备用节点（`DX_BAND_MODEL_MIRROR`，默认 `http://106.55.161.238/dxband-models`）。设为 `0` 可禁用备用节点以完全不走该服务器。

准备好所需模型后，在项目根目录执行 `uv run dx-band`。基础测试和播放已有歌曲不需要模型权重。

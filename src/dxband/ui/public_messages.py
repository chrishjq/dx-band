# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Keep implementation details out of user-facing status and error text."""

import re

_INTERNAL_TECHNOLOGY = re.compile(
    r"demucs|htdemucs|sheet\s?sage|beat\s?this|ctc(?:-segmentation)?|"
    r"mert|ffmpeg|torch|transformers|onnx|pytorch|\bmodel\b|"
    r"\b(?:gpu|cpu|cuda|mps)\b|"
    r"模型|声学|算法|推理引擎|Python 环境|uv sync|separating",
    re.IGNORECASE,
)


def public_message(message: str, fallback: str) -> str:
    """Return a useful public fallback when a backend message reveals internals."""
    return fallback if _INTERNAL_TECHNOLOGY.search(message) else message


_CREATION_MODEL_GUIDANCE = (
    (
        ("未配置 SheetSage2 模型目录",),
        "缺少 SheetSage2 模型。请从 https://huggingface.co/m-a-p/SheetSage2 "
        "自行取得，并设置 DX_BAND_SHEETSAGE2_MODEL_DIR。",
    ),
    (
        ("未配置 Beat This! 模型文件", "Beat This! 模型文件不存在"),
        "缺少 Beat This! 模型。请从 https://github.com/CPJKU/beat_this "
        "自行取得，并设置 DX_BAND_BEAT_THIS_CHECKPOINT。",
    ),
    (
        ("缺少本机 Demucs htdemucs_6s 权重",),
        "缺少 Demucs 六轨分离权重。请从 "
        "https://huggingface.co/adefossez/HTDemucs-6s 自行取得并放入本机模型缓存。",
    ),
    (
        ("缺少 Fun-ASR 模型代码",),
        "缺少 Fun-ASR 模型代码。请从 https://github.com/QwenAudio/Fun-ASR "
        "自行取得，并设置 DX_BAND_FUN_ASR_MODEL_CODE。",
    ),
    (
        ("缺少本机 Fun-ASR 模型",),
        "缺少 Fun-ASR 模型。请从 "
        "https://modelscope.cn/models/FunAudioLLM/Fun-ASR-Nano-2512 "
        "自行取得，并设置 DX_BAND_FUN_ASR_MODEL_DIR。",
    ),
    (
        ("缺少本机zh歌词对齐模型", "缺少zh歌词对齐模型文件"),
        "缺少中文歌词对齐模型。请从 https://huggingface.co/parseh/aligner-zh "
        "自行取得，并设置 DX_BAND_ALIGNER_ZH_MODEL_DIR。",
    ),
    (
        ("缺少本机en歌词对齐模型", "缺少en歌词对齐模型文件"),
        "缺少英文歌词对齐模型。请从 https://huggingface.co/parseh/aligner-en "
        "自行取得，并设置 DX_BAND_ALIGNER_EN_MODEL_DIR。",
    ),
    (
        ("缺少本机yue歌词对齐模型", "缺少yue歌词对齐模型文件"),
        "缺少粤语歌词对齐模型。请从 "
        "https://huggingface.co/ctl/wav2vec2-large-xlsr-cantonese "
        "自行取得，并设置 DX_BAND_ALIGNER_YUE_MODEL_DIR。",
    ),
)


def creation_error_message(message: str) -> str:
    """Give source users fixed setup advice without showing arbitrary backend output."""
    for prefixes, guidance in _CREATION_MODEL_GUIDANCE:
        if message.startswith(prefixes):
            return guidance
    return public_message(message, "歌曲处理失败，请重试")

# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Keep implementation details out of user-facing status and error text."""

import re

from dxband.creation.model_download import missing_model_download_key, model_role

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


def creation_error_message(message: str) -> str:
    """Give source users fixed setup advice without showing arbitrary backend output."""
    key = missing_model_download_key(message)
    if key is not None:
        role = model_role(key)
        return f"缺少{role.label}。请到设置页下载到本机后重试。"
    return public_message(message, "歌曲处理失败，请重试")

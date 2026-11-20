# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Recognize title and credit rows that are not sung lyrics."""

import re

_CREDIT_LABELS = frozenset(
    {
        "词",
        "曲",
        "编曲",
        "作词",
        "作曲",
        "演唱",
        "制作",
        "制作人",
        "制作统筹",
        "项目统筹",
        "配唱制作",
        "配唱制作人",
        "原唱",
        "翻唱",
        "主唱",
        "出品",
        "发行",
        "监制",
        "吉他",
        "贝斯",
        "鼓",
        "弦乐",
        "小提琴",
        "中提琴",
        "大提琴",
        "弦乐录音",
        "弦乐监制",
        "弦乐编写",
        "弦乐录音棚",
        "乐队监制",
        "乐谱",
        "合声",
        "合声编写",
        "和声",
        "和声编写",
        "和声编写及和声",
        "人声录音",
        "人声录音师",
        "人声录音棚",
        "人声编辑",
        "音乐编辑",
        "混音",
        "母带",
        "母带处理",
        "录音",
        "录音师",
        "录音棚",
        "录音室",
        "op",
        "sp",
        "lyricist",
        "composer",
        "producer",
        "arranger",
        "written by",
        "performed by",
    }
)
_CREDIT_LABEL_SEPARATOR = re.compile(r"\s*[/／]\s*")
_ENGLISH_CREDIT_SUFFIX = re.compile(r"[a-z\s]+", re.IGNORECASE)
_PARENTHETICAL = re.compile(r"\([^)]*\)|（[^）]*）")
_TITLE_SEPARATOR = re.compile(r"\s+[-–—]\s+")


def _normalized_name(text: str) -> str:
    return "".join(char for char in _PARENTHETICAL.sub("", text).casefold() if char.isalnum())


def _is_credit_label(label: str) -> bool:
    normalized = label.strip().casefold()
    if normalized in _CREDIT_LABELS:
        return True
    chinese_label = _ENGLISH_CREDIT_SUFFIX.sub("", normalized).strip()
    return bool(chinese_label and chinese_label in _CREDIT_LABELS)


def is_lyric_metadata(text: str, title: str, start_ms: int | None = None) -> bool:
    stripped = text.strip()
    label, separator, _value = stripped.partition("：")
    if not separator:
        label, separator, _value = stripped.partition(":")
    if separator and all(_is_credit_label(part) for part in _CREDIT_LABEL_SEPARATOR.split(label)):
        return True
    if not title:
        return False
    title_parts = {title, *re.split(r"\s*[-–—]\s*", title)}
    normalized_titles = {_normalized_name(part) for part in title_parts}
    normalized_titles.discard("")
    if (
        start_ms is not None
        and start_ms <= 1_000
        and _normalized_name(stripped) in normalized_titles
    ):
        return True
    heading_parts = _TITLE_SEPARATOR.split(stripped)
    return len(heading_parts) == 2 and any(
        _normalized_name(part) in normalized_titles for part in heading_parts
    )

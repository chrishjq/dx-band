# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Select the lyric timing backend without changing the supplied LRC text."""

from dxband.lyrics.metadata import is_lyric_metadata
from dxband.models.lyric import LyricsDocument


def timing_language(language: str, document: LyricsDocument) -> str:
    code = language.strip().lower().replace("_", "-").split("-", 1)[0]
    if code not in {"", "auto", "und"}:
        if code not in {"zh", "yue", "en"}:
            raise ValueError(f"不支持的歌词对齐语言：{language}")
        return code
    for line in document.lines:
        if is_lyric_metadata(line.text, document.title, line.start_ms):
            continue
        # Bilingual LRCs normally list the sung lyric before its translation.
        for text in line.text.split(" / "):
            for character in text:
                if "\u3400" <= character <= "\u9fff":
                    return "zh"
                if character.isascii() and character.isalpha():
                    return "en"
    raise ValueError("LRC 没有可识别语言的歌词行，请手动选择语言")

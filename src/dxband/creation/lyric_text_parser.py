# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Turn untimed, one-line-per-phrase lyrics into an alignment reference."""

from dxband.lyrics.instrumental_markers import instrumental_marker_text
from dxband.models.lyric import LyricLine, LyricsDocument


def parse_lyric_text(text: str, title: str, language: str, duration_ms: int) -> LyricsDocument:
    phrases = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and instrumental_marker_text(line) is None
    ]
    if not phrases:
        raise ValueError("歌词文本没有可演唱的内容")
    if len(phrases) > duration_ms:
        raise ValueError("歌词行数超过歌曲时长，无法生成对齐参考")
    lines = [
        LyricLine(
            id=f"line-{index + 1:04d}",
            start_ms=index * duration_ms // len(phrases),
            end_ms=(index + 1) * duration_ms // len(phrases),
            text=phrase,
            words=[],
        )
        for index, phrase in enumerate(phrases)
    ]
    return LyricsDocument(
        schema_version=1,
        title=title,
        language=language if language != "auto" else "und",
        timing_mode="line",
        lines=lines,
    )

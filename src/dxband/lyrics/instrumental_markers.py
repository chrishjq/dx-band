# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Represent long non-vocal gaps as lyric paragraphs for stage displays."""

from dxband.lyrics.character_timing import (
    is_title_metadata_line,
    sung_interval,
)
from dxband.models.lyric import LyricLine, LyricsDocument


def instrumental_marker_text(text: str) -> str | None:
    normalized = text.strip().replace("(", "（").replace(")", "）")
    if normalized in {"（前奏）", "（间奏）", "（尾奏）"}:
        return normalized[1:-1]
    return None


def instrumental_marker_label(line: LyricLine) -> str | None:
    return instrumental_marker_text(line.text)


def with_instrumental_markers(document: LyricsDocument) -> LyricsDocument:
    """Add display-only intro/interlude paragraphs without altering sung text."""
    source = [
        line
        for line in document.lines
        if not is_title_metadata_line(line, document.title)
    ]
    if not source:
        return document
    next_id = max(int(line.id.removeprefix("line-")) for line in document.lines) + 1
    result: list[LyricLine] = []
    previous_vocal_end = 0
    vocal_count = 0
    for original in source:
        marker_label = instrumental_marker_label(original)
        if marker_label is not None:
            result.append(original)
            previous_vocal_end = original.end_ms
            continue
        line = original
        interval = sung_interval(line)
        vocal_start, vocal_end = interval if interval is not None else (
            line.start_ms,
            line.end_ms,
        )
        minimum = 1_200 if vocal_count == 0 else 3_500
        if vocal_start - previous_vocal_end >= minimum:
            if result and result[-1].end_ms > previous_vocal_end:
                result[-1] = result[-1].model_copy(
                    update={"end_ms": previous_vocal_end}
                )
            label = "前奏" if vocal_count == 0 else "间奏"
            result.append(
                LyricLine(
                    id=f"line-{next_id:04d}",
                    start_ms=previous_vocal_end,
                    end_ms=vocal_start,
                    text=f"（{label}）",
                )
            )
            next_id += 1
            if line.start_ms < vocal_start:
                line = line.model_copy(update={"start_ms": vocal_start})
        result.append(line)
        previous_vocal_end = vocal_end
        vocal_count += 1
    if result == document.lines:
        return document
    return LyricsDocument.model_validate(
        {
            **document.model_dump(),
            "timing_mode": "line",
            "lines": [line.model_dump() for line in result],
        }
    )

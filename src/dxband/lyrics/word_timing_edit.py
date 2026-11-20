# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Keep character timings while replacing lyric text."""

from collections.abc import Callable
from difflib import SequenceMatcher

from dxband.models.lyric import LyricLine, WordTiming


def retime_edited_text(
    line: LyricLine,
    text: str,
    *,
    normalize: Callable[[str], str] | None = None,
) -> list[WordTiming]:
    """Reuse equal spans and distribute changed spans over their original duration."""
    if not line.words:
        return []
    old_chars = [char for char in line.text if not char.isspace()]
    new_chars = [char for char in text if not char.isspace()]
    old_words: list[WordTiming] = []
    for word in line.words:
        chars = [char for char in word.text if not char.isspace()]
        duration = word.end_ms - word.start_ms
        if duration < len(chars):
            return []
        for index, char in enumerate(chars):
            old_words.append(
                WordTiming(
                    text=char,
                    start_ms=word.start_ms + duration * index // len(chars),
                    end_ms=word.start_ms + duration * (index + 1) // len(chars),
                )
            )
    if [word.text for word in old_words] != old_chars:
        return []
    if line.end_ms - line.start_ms < len(new_chars):
        raise ValueError("歌词时长不足以为每个字分配时间")

    compare = normalize or (lambda char: char)
    spans: list[tuple[int, int] | None] = [None] * len(new_chars)
    matcher = SequenceMatcher(
        None,
        [compare(char) for char in old_chars],
        [compare(char) for char in new_chars],
        autojunk=False,
    )
    for kind, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        same_length = old_end - old_start == new_end - new_start
        if kind == "equal" or (kind == "replace" and same_length):
            for offset in range(new_end - new_start):
                word = old_words[old_start + offset]
                spans[new_start + offset] = (word.start_ms, word.end_ms)
        elif kind == "replace" and old_start < old_end and new_start < new_end:
            start_ms = old_words[old_start].start_ms
            end_ms = old_words[old_end - 1].end_ms
            count = new_end - new_start
            if end_ms - start_ms >= count:
                for offset in range(count):
                    spans[new_start + offset] = (
                        start_ms + (end_ms - start_ms) * offset // count,
                        start_ms + (end_ms - start_ms) * (offset + 1) // count,
                    )

    index = 0
    while index < len(spans):
        if spans[index] is not None:
            index += 1
            continue
        start = index
        while index < len(spans) and spans[index] is None:
            index += 1
        end = index
        left = start - 1
        right = end
        left_span = spans[left] if left >= 0 else None
        right_span = spans[right] if right < len(spans) else None
        begin_ms = left_span[1] if left_span is not None else line.start_ms
        finish_ms = right_span[0] if right_span is not None else line.end_ms
        while finish_ms - begin_ms < end - start:
            if left >= 0:
                existing = spans[left]
                assert existing is not None
                start = left
                begin_ms = existing[0]
                left -= 1
            elif right < len(spans):
                existing = spans[right]
                assert existing is not None
                end = right + 1
                finish_ms = existing[1]
                right += 1
            else:
                raise ValueError("歌词时长不足以为每个字分配时间")
        count = end - start
        for offset in range(count):
            spans[start + offset] = (
                begin_ms + (finish_ms - begin_ms) * offset // count,
                begin_ms + (finish_ms - begin_ms) * (offset + 1) // count,
            )

    result: list[WordTiming] = []
    for char, span in zip(new_chars, spans, strict=True):
        assert span is not None
        result.append(WordTiming(text=char, start_ms=span[0], end_ms=span[1]))
    return result

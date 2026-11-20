# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Map lyric timestamps to character positions while preserving spaces."""

from dxband.models.lyric import LyricLine, WordTiming


def _timed_characters(line: LyricLine) -> list[WordTiming]:
    result: list[WordTiming] = []
    for word in line.words:
        characters = [character for character in word.text if not character.isspace()]
        duration = word.end_ms - word.start_ms
        if not characters or duration < len(characters):
            continue
        for index, character in enumerate(characters):
            result.append(
                WordTiming(
                    text=character,
                    start_ms=word.start_ms + duration * index // len(characters),
                    end_ms=word.start_ms + duration * (index + 1) // len(characters),
                )
            )
    return result


def character_index_at(line: LyricLine, timestamp_ms: int) -> int:
    """Return an index in ``line.text`` for a timestamp."""
    text_indices = [index for index, character in enumerate(line.text) if not character.isspace()]
    timed = _timed_characters(line)
    if timed and len(timed) == len(text_indices):
        timed_index = min(
            range(len(timed)),
            key=lambda index: abs(timed[index].start_ms - timestamp_ms),
        )
        return text_indices[timed_index]
    fraction = (timestamp_ms - line.start_ms) / max(1, line.end_ms - line.start_ms)
    return min(
        max(0, round(fraction * max(0, len(line.text) - 1))),
        max(0, len(line.text) - 1),
    )


def character_timestamp(line: LyricLine, character_index: int) -> int:
    """Return the best available start time for a character in ``line.text``."""
    text_indices = [index for index, character in enumerate(line.text) if not character.isspace()]
    timed = _timed_characters(line)
    if timed and len(timed) == len(text_indices):
        if character_index in text_indices:
            return timed[text_indices.index(character_index)].start_ms
        previous = [
            timed[index].end_ms
            for index, text_index in enumerate(text_indices)
            if text_index < character_index
        ]
        following = [
            timed[index].start_ms
            for index, text_index in enumerate(text_indices)
            if text_index > character_index
        ]
        if previous and following:
            return (previous[-1] + following[0]) // 2
        if previous:
            return previous[-1]
        if following:
            return following[0]
    if len(line.text) <= 1:
        return line.start_ms
    fraction = character_index / (len(line.text) - 1)
    timestamp_ms = line.start_ms + round((line.end_ms - line.start_ms) * fraction)
    return min(line.end_ms - 1, timestamp_ms)


def unique_character_indices(
    line: LyricLine, timestamps_ms: list[int] | tuple[int, ...]
) -> tuple[int | None, ...]:
    """Map ordered timestamps to distinct lyric cells without dropping close events."""
    cell_count = len(line.text)
    if cell_count == 0:
        return (None,) * len(timestamps_ms)
    assigned: set[int] = set()
    result: list[int | None] = []
    visible_count = min(len(timestamps_ms), cell_count)
    for order, timestamp_ms in enumerate(timestamps_ms):
        if order >= cell_count:
            result.append(None)
            continue
        target = character_index_at(line, timestamp_ms)
        earliest = order
        latest = cell_count - visible_count + order
        position = max(earliest, min(target, latest))
        while position < cell_count and position in assigned:
            position += 1
        if position >= cell_count:
            result.append(None)
            continue
        assigned.add(position)
        result.append(position)
    return tuple(result)


def sung_interval(line: LyricLine) -> tuple[int, int] | None:
    """Return the actual timed lyric interval when character timings are available."""
    timed = _timed_characters(line)
    text_characters = [character for character in line.text if not character.isspace()]
    if not timed or len(timed) != len(text_characters):
        return None
    return timed[0].start_ms, timed[-1].end_ms


def is_title_metadata_line(line: LyricLine, title: str) -> bool:
    """Identify a leading title card that occupies the intro in some LRC files."""
    if line.words or line.start_ms > 1_000 or line.end_ms - line.start_ms < 10_000:
        return False
    normalized_title = "".join(character for character in title.casefold() if character.isalnum())
    normalized_line = "".join(
        character for character in line.text.casefold() if character.isalnum()
    )
    return bool(normalized_title and normalized_title in normalized_line)

# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Two-bar musician rows with lyrics and chords anchored to the beat grid."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import pairwise
from math import ceil
from statistics import median

from dxband.lyrics.character_timing import (
    character_timestamp,
    is_title_metadata_line,
    sung_interval,
)
from dxband.lyrics.instrumental_markers import instrumental_marker_label
from dxband.models.chord import ChordTimeline
from dxband.models.lyric import LyricLine, LyricsDocument


@dataclass(frozen=True, slots=True)
class MusicianBarRow:
    start_ms: int
    end_ms: int
    beat_times_ms: tuple[int, ...]
    chord_cells: tuple[tuple[str, ...], ...]
    lyric_cells: tuple[str, ...]
    section_label: str = ""
    lyric_sources: tuple[tuple[tuple[str, int], ...], ...] = ()


def complete_beat_grid(
    beat_times_ms: tuple[int, ...],
    downbeat_times_ms: tuple[int, ...],
    beats_per_bar: int | None,
    duration_ms: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Extend the beat grid through a quiet outro using its recent tempo."""
    if not beat_times_ms or not downbeat_times_ms or beats_per_bar not in (3, 4):
        return beat_times_ms, downbeat_times_ms
    intervals = [right - left for left, right in pairwise(beat_times_ms) if right > left]
    if not intervals:
        return beat_times_ms, downbeat_times_ms
    interval = max(1, round(median(intervals[-16:])))
    beats = list(beat_times_ms)
    while beats[-1] + interval < duration_ms:
        beats.append(beats[-1] + interval)

    downbeats = list(downbeat_times_ms)
    beat_indices = {timestamp: index for index, timestamp in enumerate(beats)}
    last_index = beat_indices.get(downbeats[-1])
    if last_index is None:
        return tuple(beats), tuple(downbeats)
    following = last_index + beats_per_bar
    while following < len(beats):
        downbeats.append(beats[following])
        following += beats_per_bar
    return tuple(beats), tuple(downbeats)


def _timed_characters(line: LyricLine) -> tuple[tuple[int, int], ...]:
    """Return exact syllable intervals only when the saved words cover the whole line."""
    text = "".join(character for character in line.text if not character.isspace())
    timed_text = "".join(
        character for word in line.words for character in word.text if not character.isspace()
    )
    if not text or timed_text != text:
        return ()
    result: list[tuple[int, int]] = []
    for word in line.words:
        characters = [character for character in word.text if not character.isspace()]
        duration = word.end_ms - word.start_ms
        if duration < len(characters):
            return ()
        for index in range(len(characters)):
            result.append(
                (
                    word.start_ms + duration * index // len(characters),
                    word.start_ms + duration * (index + 1) // len(characters),
                )
            )
    return tuple(result)


def _lyric_units(
    line: LyricLine,
    keep_words_whole: bool,
) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Return display units and their original character indices."""
    if not keep_words_whole:
        return tuple((character, (index,)) for index, character in enumerate(line.text))
    word_starts = [
        index
        for index, character in enumerate(line.text)
        if not character.isspace() and (index == 0 or line.text[index - 1].isspace())
    ]
    if not word_starts:
        return ()
    boundaries = [0, *word_starts[1:], len(line.text)]
    return tuple(
        (line.text[start:end], tuple(range(start, end))) for start, end in pairwise(boundaries)
    )


def _word_start_at(text: str, character_index: int) -> int:
    """Return the start of the whitespace-delimited word containing an index."""
    start = character_index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    return start


def build_musician_bar_rows(
    document: LyricsDocument | None,
    beat_times_ms: tuple[int, ...],
    downbeat_times_ms: tuple[int, ...],
    beats_per_bar: int | None,
    chords: ChordTimeline | None,
    bars_per_row: int = 2,
) -> tuple[MusicianBarRow, ...]:
    """Keep the configured number of bars on each row, including instrumentals."""
    if (
        document is None
        or beats_per_bar not in (3, 4)
        or not beat_times_ms
        or not downbeat_times_ms
        or bars_per_row < 1
    ):
        return ()
    first_beat = bisect_left(beat_times_ms, downbeat_times_ms[0])
    if first_beat == len(beat_times_ms) or beat_times_ms[first_beat] != downbeat_times_ms[0]:
        return ()
    beats = beat_times_ms[first_beat:]
    beats_per_row = bars_per_row * beats_per_bar
    row_count = ceil(len(beats) / beats_per_row)
    row_starts = tuple(
        0 if index == 0 else beats[index * beats_per_row] for index in range(row_count)
    )
    interval = beats[-1] - beats[-2] if len(beats) > 1 else 500
    final_end = max(
        beats[-1] + interval,
        max((line.end_ms for line in document.lines), default=0),
        max((segment.end_ms for segment in chords.segments), default=0) if chords else 0,
    )
    row_ends = (*row_starts[1:], final_end)
    lyric_groups: list[list[tuple[str, list[tuple[str, int]]]]] = [[] for _ in beats]
    chord_cells: list[list[str]] = [[] for _ in beats]
    labels = ["" for _ in range(row_count)]
    vocal_intervals: list[tuple[int, int]] = []
    timed_lyric_beats: list[tuple[int, int, int, str, int]] = []
    line_text_by_id = {line.id: line.text for line in document.lines}
    keep_words_whole = document.language.strip().lower().replace("_", "-").split("-", 1)[0] == "en"

    def beat_index_at(timestamp: int) -> int:
        return max(0, min(len(beats) - 1, bisect_right(beats, timestamp) - 1))

    for line in document.lines:
        if is_title_metadata_line(line, document.title):
            continue
        marker = instrumental_marker_label(line)
        if marker is not None:
            for index, (start, end) in enumerate(zip(row_starts, row_ends, strict=True)):
                if line.start_ms < end and line.end_ms > start:
                    labels[index] = marker
            continue
        vocal_intervals.append(sung_interval(line) or (line.start_ms, line.end_ms))
        line_lyrics = ["" for _ in beats]
        line_sources: list[list[tuple[str, int]]] = [[] for _ in beats]
        displayed_beat_by_character: dict[int, int] = {}
        for text, character_indices in _lyric_units(line, keep_words_whole):
            sung_indices = [index for index in character_indices if not line.text[index].isspace()]
            if not sung_indices:
                continue
            timestamp = character_timestamp(line, sung_indices[0])
            # A sung syllable belongs to the beat interval in which it starts.
            # The dot and chord remain on the original beat grid.
            beat_index = beat_index_at(timestamp)
            line_lyrics[beat_index] += text
            line_sources[beat_index].extend(
                (line.id, character_index) for character_index in character_indices
            )
            displayed_beat_by_character.update(
                (character_index, beat_index) for character_index in sung_indices
            )
        for beat_index, text in enumerate(line_lyrics):
            if text:
                lyric_groups[beat_index].append((text, line_sources[beat_index]))
        timed_characters = _timed_characters(line)
        if timed_characters:
            timed_lyric_beats.extend(
                (
                    start,
                    end,
                    displayed_beat_by_character.get(character_index, beat_index_at(start)),
                    line.id,
                    character_index,
                )
                for character_index, (start, end) in zip(
                    (index for index, character in enumerate(line.text) if not character.isspace()),
                    timed_characters,
                    strict=True,
                )
            )

    if chords is not None:
        anchors: dict[tuple[int, str], tuple[int, int]] = {}
        for segment in chords.segments:
            following = bisect_left(beats, segment.start_ms)
            if following == 0:
                index = 0
            elif following == len(beats):
                index = len(beats) - 1
            else:
                index = min(
                    (following - 1, following),
                    key=lambda candidate: abs(beats[candidate] - segment.start_ms),
                )
            if segment.chord not in chord_cells[index]:
                chord_cells[index].append(segment.chord)
            source = next(
                (
                    (beat_index, line_id, character_index)
                    for start, end, beat_index, line_id, character_index in timed_lyric_beats
                    if start <= segment.start_ms < end
                ),
                None,
            )
            if source is not None and index == source[0] + 1:
                key = (source[0], source[1])
                anchored_character = source[2]
                previous = anchors.get(key)
                if previous is None or anchored_character < previous[1]:
                    anchors[key] = (index, anchored_character)

        aligned_groups: list[list[tuple[str, list[tuple[str, int]]]]] = [[] for _ in beats]
        previous_target = -1
        previous_anchored = False

        def append_group(
            text: str,
            sources: list[tuple[str, int]],
            preferred_target: int,
            *,
            anchored: bool,
        ) -> None:
            nonlocal previous_target, previous_anchored
            if not text:
                return
            minimum = previous_target + (1 if previous_anchored else 0)
            target = min(max(preferred_target, minimum), len(beats) - 1)
            aligned_groups[target].append((text, sources))
            previous_target = target
            previous_anchored = anchored and target == preferred_target

        for source_index, groups in enumerate(lyric_groups):
            for text, sources in groups:
                line_id = sources[0][0]
                anchor = anchors.get((source_index, line_id))
                if anchor is None:
                    append_group(text, sources, source_index, anchored=False)
                    continue
                target, character_index = anchor
                if keep_words_whole:
                    character_index = _word_start_at(line_text_by_id[line_id], character_index)
                split_at = next(
                    (
                        index
                        for index, source in enumerate(sources)
                        if source == (line_id, character_index)
                    ),
                    0,
                )
                append_group(text[:split_at], sources[:split_at], source_index, anchored=False)
                append_group(text[split_at:], sources[split_at:], target, anchored=True)
        lyric_groups = aligned_groups

    if vocal_intervals:
        first_vocal = min(start for start, _end in vocal_intervals)
        last_vocal = max(end for _start, end in vocal_intervals)
        for index, (start, end) in enumerate(zip(row_starts, row_ends, strict=True)):
            if labels[index] or any(
                lyric_groups[index * beats_per_row : (index + 1) * beats_per_row]
            ):
                continue
            if end <= first_vocal:
                labels[index] = "前奏"
            elif start >= last_vocal:
                labels[index] = "尾奏"
            elif any(
                previous_end <= start
                and end <= following_start
                and following_start - previous_end >= 3_500
                for (_previous_start, previous_end), (following_start, _following_end) in pairwise(
                    vocal_intervals
                )
            ):
                labels[index] = "间奏"

    return tuple(
        MusicianBarRow(
            start_ms=row_starts[index],
            end_ms=row_ends[index],
            beat_times_ms=beats[index * beats_per_row : (index + 1) * beats_per_row],
            chord_cells=tuple(
                tuple(cell)
                for cell in chord_cells[index * beats_per_row : (index + 1) * beats_per_row]
            ),
            lyric_cells=tuple(
                "".join(text for text, _sources in cell).strip()
                for cell in lyric_groups[index * beats_per_row : (index + 1) * beats_per_row]
            ),
            section_label=labels[index],
            lyric_sources=tuple(
                tuple(source for _text, sources in cell for source in sources)
                for cell in lyric_groups[index * beats_per_row : (index + 1) * beats_per_row]
            ),
        )
        for index in range(row_count)
    )

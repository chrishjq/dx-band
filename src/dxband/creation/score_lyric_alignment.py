# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Align known lyric text to a timed vocal score after acoustic alignment.

The acoustic word times are evidence, not score positions.  A monotone
alignment lets a phrase move when CTC drifts, while note duration and the
silence before a new lyric line help distinguish neighboring syllables.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import pairwise
from statistics import median
from typing import cast

import numpy as np

from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
from dxband.models.melody import MelodyDocument, MelodyNote


def _english_word_units(lyrics: LyricsDocument) -> LyricsDocument:
    """Match English display words to notes, not CTC's individual letters."""
    lines: list[LyricLine] = []
    for line in lyrics.lines:
        timed_characters: list[tuple[int, WordTiming]] = []
        cursor = 0
        for timing in line.words:
            position = line.text.find(timing.text, cursor)
            if position < 0:
                raise ValueError(f"歌词“{line.text}”的逐字顺序与文本不一致")
            timed_characters.append((position, timing))
            cursor = position + len(timing.text)
        words: list[WordTiming] = []
        for match in re.finditer(r"\S+", line.text):
            members = [
                timing
                for position, timing in timed_characters
                if match.start() <= position < match.end()
            ]
            if not members:
                raise ValueError(f"歌词“{line.text}”缺少单词时间")
            words.append(
                WordTiming(
                    text=match.group(),
                    start_ms=members[0].start_ms,
                    end_ms=members[-1].end_ms,
                )
            )
        lines.append(
            LyricLine(
                id=line.id,
                start_ms=words[0].start_ms,
                end_ms=words[-1].end_ms,
                text=line.text,
                words=words,
            )
        )
    return lyrics.model_copy(update={"lines": lines})


def _beat_duration_ms(melody: MelodyDocument) -> float:
    intervals = [
        right - left
        for bar in melody.bars
        for left, right in pairwise(bar.beat_times_ms)
        if 300 <= right - left <= 2_000
    ]
    return float(median(intervals)) if intervals else 900.0


def _apply_repeated_line_consensus(
    units: list[tuple[LyricLine, int, WordTiming]],
    vocal: list[MelodyNote],
    path: list[int],
) -> None:
    """Reuse an identical sung rhythm when two other repeats agree."""
    positions: dict[str, list[int]] = defaultdict(list)
    for unit_index, (line, _character_index, _word) in enumerate(units):
        positions[line.id].append(unit_index)
    groups: dict[str, list[list[int]]] = defaultdict(list)
    for indices in positions.values():
        groups[units[indices[0]][0].text].append(indices)
    by_step = {
        note.start_16th: index for index, note in enumerate(vocal) if note.start_16th is not None
    }
    for repeated in groups.values():
        if len(repeated) < 3:
            continue
        patterns: list[tuple[int, ...] | None] = []
        for indices in repeated:
            starts = [vocal[path[index]].start_16th for index in indices]
            patterns.append(
                tuple(cast(int, start) - cast(int, starts[0]) for start in starts)
                if all(start is not None for start in starts)
                else None
            )
        common = Counter(pattern for pattern in patterns if pattern is not None)
        if not common:
            continue
        template, support = common.most_common(1)[0]
        if support < 2 or len(template) < 3:
            continue
        reference = next(
            indices
            for indices, pattern in zip(repeated, patterns, strict=True)
            if pattern == template
        )
        reference_durations = [vocal[path[index]].duration_16ths for index in reference]
        for indices, pattern in zip(repeated, patterns, strict=True):
            if pattern == template:
                continue
            first_step = vocal[path[indices[0]]].start_16th
            if first_step is None:
                continue
            proposed = [by_step.get(first_step + offset) for offset in template]
            if any(index is None for index in proposed):
                continue
            selected = [int(index) for index in proposed if index is not None]
            if any(right <= left for left, right in pairwise(selected)):
                continue
            if indices[0] > 0 and selected[0] <= path[indices[0] - 1]:
                continue
            if indices[-1] + 1 < len(path) and selected[-1] >= path[indices[-1] + 1]:
                continue
            duration_matches = 0
            for reference_duration, note_index in zip(reference_durations, selected, strict=True):
                candidate_duration = vocal[note_index].duration_16ths
                if (
                    reference_duration is not None
                    and candidate_duration is not None
                    and abs(reference_duration - candidate_duration) <= 1
                ):
                    duration_matches += 1
            if duration_matches * 4 < len(selected) * 3:
                continue
            path[indices[0] : indices[-1] + 1] = selected


def _partially_link_acoustic_onsets(
    lyrics: LyricsDocument,
    melody: MelodyDocument,
    units: list[tuple[LyricLine, int, WordTiming]],
    vocal_indices: list[int],
    beat_ms: float,
) -> tuple[LyricsDocument, MelodyDocument]:
    """Keep unsupported words at acoustic times and link only nearby notes."""
    unit_count = len(units)
    note_count = len(vocal_indices)
    costs = np.full((unit_count + 1, note_count + 1), np.inf)
    decisions = np.zeros((unit_count + 1, note_count + 1), dtype=np.uint8)
    costs[0, :] = np.arange(note_count + 1) * 0.4
    costs[:, 0] = np.arange(unit_count + 1) * 0.6
    decisions[0, 1:] = 1  # skip note
    decisions[1:, 0] = 2  # leave word unlinked
    # CTC character peaks can fall between two score onsets. The previous
    # 0.4-beat gate dropped syllables even when the vocal score contained the
    # corresponding note. Keep the gate below one beat and let the monotone
    # path reject competing notes.
    maximum_distance_ms = (
        min(450.0, max(280.0, beat_ms * 0.7))
        if lyrics.language.lower() in {"zh", "yue"}
        else beat_ms * 0.4
    )
    for unit_index, (_line, _character_index, word) in enumerate(units, 1):
        for note_index, original_index in enumerate(vocal_indices, 1):
            note = melody.notes[original_index]
            skip_note = costs[unit_index, note_index - 1] + 0.4
            skip_word = costs[unit_index - 1, note_index] + 0.6
            best = min(skip_note, skip_word)
            decision = 1 if skip_note <= skip_word else 2
            distance = abs(note.start_ms - word.start_ms) / beat_ms
            if abs(note.start_ms - word.start_ms) <= maximum_distance_ms:
                match = costs[unit_index - 1, note_index - 1] + distance
                if match < best:
                    best = match
                    decision = 3
            costs[unit_index, note_index] = best
            decisions[unit_index, note_index] = decision
    assignments: list[tuple[int, int]] = []
    unit_index, note_index = unit_count, note_count
    while unit_index and note_index:
        decision = decisions[unit_index, note_index]
        if decision == 3:
            assignments.append((unit_index - 1, vocal_indices[note_index - 1]))
            unit_index -= 1
            note_index -= 1
        elif decision == 1:
            note_index -= 1
        else:
            unit_index -= 1
    updated_notes = list(melody.notes)
    for unit_index, original_index in assignments:
        line, character_index, _word = units[unit_index]
        updated_notes[original_index] = updated_notes[original_index].model_copy(
            update={"lyric_line_id": line.id, "lyric_character_index": character_index}
        )
    return lyrics, MelodyDocument.model_validate(
        {
            **melody.model_dump(mode="python"),
            "notes": [note.model_dump(mode="python") for note in updated_notes],
        },
        strict=True,
    )


def align_lyrics_to_score(
    lyrics: LyricsDocument, melody: MelodyDocument
) -> tuple[LyricsDocument, MelodyDocument]:
    """Link every timed lyric unit to a distinct vocal onset in score order.

    LRC timestamps are never read here.  ``lyrics`` contains the independent
    text-to-vocals CTC result; the score supplies the final displayed times.
    Missing or weak score matches remain timed by the vocal evidence without
    an invented pitch link.
    """
    if lyrics.language.lower().startswith("en"):
        lyrics = _english_word_units(lyrics)
    units: list[tuple[LyricLine, int, WordTiming]] = []
    for line in lyrics.lines:
        cursor = 0
        for word in line.words:
            index = line.text.find(word.text, cursor)
            if index < 0:
                raise ValueError(f"歌词“{line.text}”的逐字顺序与文本不一致")
            units.append((line, index, word))
            cursor = index + len(word.text)
    vocal_indices = [index for index, note in enumerate(melody.notes) if note.source == "vocals"]
    if not units or not vocal_indices:
        raise ValueError("缺少歌词或人声谱面音符，无法关联")
    vocal = [melody.notes[index] for index in vocal_indices]
    count = len(units)
    note_count = len(vocal)
    beat_ms = _beat_duration_ms(melody)
    if note_count < count:
        return _partially_link_acoustic_onsets(lyrics, melody, units, vocal_indices, beat_ms)
    word_starts = np.asarray([word.start_ms for _, _, word in units], dtype=float)
    word_durations = np.asarray([word.end_ms - word.start_ms for _, _, word in units], dtype=float)
    note_starts = np.asarray([note.start_ms for note in vocal], dtype=float)
    note_durations = np.asarray([note.end_ms - note.start_ms for note in vocal], dtype=float)
    preceding_gaps = np.asarray(
        [beat_ms, *(max(0, right.start_ms - left.end_ms) for left, right in pairwise(vocal))],
        dtype=float,
    )
    # Short extra notes often belong to a held or ornamented syllable.  A
    # long note is expensive to skip, especially at the start of a phrase.
    skip_cost = np.minimum(3.0, 0.15 + note_durations / (beat_ms * 1.22))
    skipped_prefix = np.r_[0.0, np.cumsum(skip_cost)]
    previous = np.full(note_count, np.inf)
    backtrack = np.full((count, note_count), -1, dtype=np.int32)

    def match_cost(unit_index: int) -> np.ndarray:
        line = units[unit_index][0]
        distance = np.abs(word_starts[unit_index] - note_starts) / beat_ms
        inside_phrase = (
            (note_starts >= line.start_ms - beat_ms * 0.65)
            & (note_starts <= line.end_ms + beat_ms * 0.55)
            & (distance <= 3.0)
        )
        duration_cost = 2.2 * np.minimum(
            2.0,
            np.abs(np.log((word_durations[unit_index] + 100.0) / (note_durations + 100.0))),
        )
        line_start = unit_index == 0 or units[unit_index][0].id != units[unit_index - 1][0].id
        phrase_bonus = (
            2.5 * np.minimum(3.0, preceding_gaps / (beat_ms * 0.44)) if line_start else 0.0
        )
        return np.where(inside_phrase, distance + duration_cost - phrase_bonus, np.inf)

    previous[:] = skipped_prefix[1:] + match_cost(0)
    for unit_index in range(1, count):
        current = np.full(note_count, np.inf)
        for note_index in range(unit_index, note_count):
            prior_indices = np.arange(unit_index - 1, note_index)
            interval_difference = np.abs(
                (note_starts[note_index] - note_starts[prior_indices])
                - (word_starts[unit_index] - word_starts[unit_index - 1])
            )
            transition_cost = np.minimum(3.0, interval_difference / beat_ms)
            costs = (
                previous[prior_indices]
                + skipped_prefix[note_index]
                - skipped_prefix[prior_indices + 1]
                + transition_cost
            )
            best = int(np.argmin(costs))
            current[note_index] = costs[best]
            backtrack[unit_index, note_index] = int(prior_indices[best])
        previous = current + match_cost(unit_index)

    end_costs = previous + skipped_prefix[note_count] - skipped_prefix[np.arange(note_count) + 1]
    if not np.isfinite(end_costs).any():
        return _partially_link_acoustic_onsets(lyrics, melody, units, vocal_indices, beat_ms)
    path = [int(np.argmin(end_costs))]
    for unit_index in range(count - 1, 0, -1):
        path.append(int(backtrack[unit_index, path[-1]]))
    path.reverse()
    _apply_repeated_line_consensus(units, vocal, path)
    if any(right <= left for left, right in pairwise(path)):
        raise ValueError("歌词与人声音符未形成单调对应")
    worst = max(
        range(count),
        key=lambda index: abs(note_starts[path[index]] - word_starts[index]),
    )
    if abs(note_starts[path[worst]] - word_starts[worst]) > 3 * beat_ms:
        return _partially_link_acoustic_onsets(lyrics, melody, units, vocal_indices, beat_ms)

    updated_notes: list[MelodyNote] = list(melody.notes)
    for (line, character_index, _word), original_index in zip(
        units, (vocal_indices[index] for index in path), strict=True
    ):
        updated_notes[original_index] = updated_notes[original_index].model_copy(
            update={"lyric_line_id": line.id, "lyric_character_index": character_index}
        )
    updated_lines: list[LyricLine] = []
    unit_cursor = 0
    for line in lyrics.lines:
        line_units = units[unit_cursor : unit_cursor + len(line.words)]
        line_path = path[unit_cursor : unit_cursor + len(line.words)]
        starts = [vocal[note_index].start_ms for note_index in line_path]
        following_start = (
            vocal[path[unit_cursor + len(line.words)]].start_ms
            if unit_cursor + len(line.words) < count
            else melody.coverage_end_ms
        )
        last_end = vocal[line_path[-1]].end_ms
        if following_start is not None:
            last_end = min(last_end, following_start)
        last_end = max(starts[-1] + 1, last_end)
        boundaries = [*starts, last_end]
        words = [
            WordTiming(text=unit[2].text, start_ms=boundaries[index], end_ms=boundaries[index + 1])
            for index, unit in enumerate(line_units)
        ]
        updated_lines.append(
            LyricLine(
                id=line.id,
                start_ms=starts[0],
                end_ms=last_end,
                text=line.text,
                words=words,
            )
        )
        unit_cursor += len(line.words)
    return (
        LyricsDocument(
            schema_version=lyrics.schema_version,
            title=lyrics.title,
            language=lyrics.language,
            timing_mode="word",
            lines=updated_lines,
        ),
        MelodyDocument.model_validate(
            {
                **melody.model_dump(mode="python"),
                "notes": [note.model_dump(mode="python") for note in updated_notes],
            },
            strict=True,
        ),
    )


def link_lyrics_to_score_without_retiming(
    lyrics: LyricsDocument, melody: MelodyDocument,
) -> tuple[LyricsDocument, MelodyDocument]:
    """Link ASR-timed characters to distinct notes while preserving ASR times."""
    units: list[tuple[LyricLine, int, WordTiming]] = []
    for line in lyrics.lines:
        cursor = 0
        for word in line.words:
            index = line.text.find(word.text, cursor)
            if index < 0:
                raise ValueError(f"歌词“{line.text}”的逐字顺序与文本不一致")
            units.append((line, index, word))
            cursor = index + len(word.text)
    vocal_indices = [index for index, note in enumerate(melody.notes)
                     if note.source == "vocals"]
    if not units or not vocal_indices:
        raise ValueError("缺少歌词或人声音符")
    return _partially_link_acoustic_onsets(
        lyrics, melody, units, vocal_indices, _beat_duration_ms(melody),
    )

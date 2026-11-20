# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Refine vocal notation using independent acoustic lyric times."""

from bisect import bisect_left, bisect_right
from itertools import pairwise

from dxband.models.lyric import LyricsDocument
from dxband.models.melody import MelodyDocument


def refine_vocal_notation(
    melody: MelodyDocument,
    acoustic: LyricsDocument,
) -> MelodyDocument:
    """Recognize complete sung triplets and label pickups into a vocal section."""
    if not melody.bars or not melody.notes:
        return melody
    bars = list(melody.bars)
    notes = list(melody.notes)
    bar_starts = [bar.start_ms for bar in bars]
    beats = [
        (start, end, bar_index, beat_index, bar.start_16th + 4 * beat_index)
        for bar_index, bar in enumerate(bars)
        if bar.start_16th is not None and bar.end_16th is not None and not bar.leading_rest_beats
        for beat_index, (start, end) in enumerate(pairwise([*bar.beat_times_ms, bar.end_ms]))
        if bar.start_16th + 4 * (beat_index + 1) <= bar.end_16th
    ]
    beat_starts = [beat[0] for beat in beats]
    vocal = [index for index, note in enumerate(notes) if note.source == "vocals"]
    vocal_starts = [notes[index].start_ms for index in vocal]
    for line in acoustic.lines:
        index = bisect_right(bar_starts, line.start_ms) - 1
        if 0 <= index < len(bars) - 1:
            bar, following = bars[index], bars[index + 1]
            if (
                bar.section_label in {"前奏", "间奏"}
                and following.section_label in {"主歌", "预副歌", "副歌", "桥段"}
                and line.start_ms >= bar.beat_times_ms[-1] - 100
                and line.end_ms > bar.end_ms
            ):
                bars[index] = bar.model_copy(
                    update={
                        "section_label": following.section_label + "弱起",
                    }
                )
        if not acoustic.language.lower().startswith(("zh", "yue")):
            continue
        word_indices = []
        cursor = 0
        for word in line.words:
            cursor = line.text.find(word.text, cursor)
            if cursor < 0:
                break
            word_indices.append(cursor)
            cursor += len(word.text)
        if len(word_indices) != len(line.words):
            continue
        for offset in range(len(line.words) - 2):
            words = line.words[offset : offset + 3]
            # The acoustic aligner pads the first word 350 ms before its CTC peak.
            onset = words[0].start_ms + (350 if offset == 0 else 0)
            near = bisect_left(beat_starts, onset)
            for start, end, bar_index, beat_index, step in beats[max(0, near - 1) : near + 1]:
                length = end - start
                bar = bars[bar_index]
                if beat_index in bar.triplet_beats or not 400 <= length <= 1400:
                    continue
                phases = [
                    (time - start) / length
                    for time in (
                        onset,
                        words[1].start_ms,
                        words[2].start_ms,
                    )
                ]
                target = (0, 1 / 3, 2 / 3)
                errors = [
                    abs(actual - expected) for actual, expected in zip(phases, target, strict=True)
                ]
                binary_error = min(
                    sum(
                        abs(actual - expected)
                        for actual, expected in zip(phases, binary, strict=True)
                    )
                    for binary in ((0, 0.25, 0.5), (0, 0.25, 0.75), (0, 0.5, 0.75))
                )
                if (
                    max(errors) > 0.13
                    or sum(errors) + 0.045 >= binary_error
                    or abs(words[-1].end_ms - end) > length * 0.19
                ):
                    continue
                chars = word_indices[offset : offset + 3]
                next_char = word_indices[offset + 3 : offset + 4]
                first = bisect_left(vocal_starts, start - length * 0.26)
                last = bisect_right(vocal_starts, end + length * 0.30)
                for group_start in range(first, last - 2):
                    group = vocal[group_start : group_start + 3]
                    selected = [notes[i] for i in group]
                    if (
                        any(
                            note.lyric_line_id not in (None, line.id)
                            or (
                                note.lyric_line_id == line.id
                                and note.lyric_character_index not in (*chars, *next_char)
                            )
                            for note in selected
                        )
                        or sum(
                            note.lyric_line_id == line.id and note.lyric_character_index in chars
                            for note in selected
                        )
                        < 2
                    ):
                        continue
                    deviations = [
                        (note.start_ms - start) / length - phase
                        for note, phase in zip(selected, target, strict=True)
                    ]
                    short_pickup = (
                        offset == 0
                        and len(bar.beat_times_ms) == 2
                        and beat_index == 1
                        and bar_index + 1 < len(bars)
                        and len(bars[bar_index + 1].beat_times_ms) == 4
                    )
                    # Only a short pickup may override disagreeing model times.
                    # Elsewhere ordinary syncopation can look ternary in CTC alone.
                    if max(deviations) - min(deviations) > 0.23 or max(map(abs, deviations)) > (
                        0.58 if short_pickup else 0.10
                    ):
                        continue
                    if any(
                        i not in group
                        and (
                            (note.start_16th is not None and step <= note.start_16th < step + 4)
                            or (
                                note.lyric_line_id == line.id
                                and note.lyric_character_index in chars
                            )
                        )
                        for i, note in enumerate(notes)
                    ):
                        continue
                    for i, char, position, duration in zip(
                        group,
                        chars,
                        (step, step + 1, step + 3),
                        (1, 2, 1),
                        strict=True,
                    ):
                        notes[i] = notes[i].model_copy(
                            update={
                                "start_16th": position,
                                "duration_16ths": duration,
                                "lyric_line_id": line.id,
                                "lyric_character_index": char,
                            }
                        )
                    bars[bar_index] = bar.model_copy(
                        update={
                            "triplet_beats": sorted([*bar.triplet_beats, beat_index]),
                        }
                    )
                    break
    return melody.model_copy(update={"bars": bars, "notes": notes})

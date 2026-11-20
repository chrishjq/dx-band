# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Reconcile short bars inside phrases with independently supported downbeats."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import pairwise
from statistics import median

from dxband.models.melody import MelodyBar, MelodyDocument


@dataclass(frozen=True)
class MeterRepair:
    first: int
    last: int  # exclusive
    beat_groups: tuple[tuple[int, ...], ...]
    model_end_ms: int


def _nearest(values: tuple[int, ...], time: int) -> int:
    right = min(bisect_left(values, time), len(values) - 1)
    return min((max(0, right - 1), right), key=lambda index: abs(values[index] - time))


def _span(bar: MelodyBar) -> int:
    return (bar.end_16th or 0) - (bar.start_16th or 0)


def _beat_groups(
    beats: tuple[int, ...],
    downbeats: tuple[int, ...],
    quarter: float,
) -> list[tuple[int, ...]]:
    groups = []
    for start, end in pairwise(downbeats):
        pulses = (start, *beats[bisect_right(beats, start) : bisect_left(beats, end)])
        gaps = [right - left for left, right in pairwise((*pulses, end))]
        if len(pulses) == 3 and 3.6 <= (end - start) / quarter <= 4.45:
            missing = [i for i, gap in enumerate(gaps) if 1.7 <= gap / quarter <= 2.5]
            if len(missing) == 1:
                index = missing[0]
                pulses = (
                    *pulses[: index + 1],
                    pulses[index] + round(gaps[index] / 2),
                    *pulses[index + 1 :],
                )
                gaps = [right - left for left, right in pairwise((*pulses, end))]
        groups.append(
            pulses
            if len(pulses) in (2, 4) and all(0.68 <= gap / quarter <= 1.32 for gap in gaps)
            else ()
        )
    return groups


def plan_meter_repairs(
    document: MelodyDocument,
    beats: tuple[int, ...],
    downbeats: tuple[int, ...],
    quarter: float,
) -> list[MeterRepair]:
    bars = document.bars
    if not bars or sum(_span(bar) == 16 for bar in bars) < len(bars) * 0.75:
        return []
    sheet_pulses = [end - start for bar in bars for start, end in pairwise(bar.beat_times_ms)]
    if not sheet_pulses or abs(median(sheet_pulses) / quarter - 1) > 0.20:
        return []  # An ambiguous half-/double-time phase cannot resolve short bars.
    groups = _beat_groups(beats, downbeats, quarter)
    anchors = [_nearest(downbeats, bar.start_ms) for bar in bars]
    aligned = [
        not bar.leading_rest_beats
        and bar.start_16th is not None
        and abs(downbeats[anchor] - bar.start_ms) <= quarter * 0.49
        for bar, anchor in zip(bars, anchors, strict=True)
    ]
    repairs = []
    floor = 0
    for index in range(1, len(bars) - 1):
        short = bars[index]
        if index < floor or _span(short) not in (4, 12):
            continue
        candidates = []
        for first in range(max(floor, index - 16), index + 1):
            if not aligned[first]:
                continue
            for last in range(index + 1, min(len(bars), index + 17)):
                if not aligned[last]:
                    continue
                begin, end = anchors[first], anchors[last]
                replacement = groups[begin:end]
                if (
                    len(replacement) < 3
                    or any(not group for group in replacement)
                    or len(replacement[0]) != 4
                    or len(replacement[-1]) != 4
                ):
                    continue
                short_groups = [i for i in range(begin, end) if len(groups[i]) == 2]
                if any(
                    len(groups[i - 1]) != 4
                    or len(groups[i + 1]) != 4
                    or not any(
                        _span(bar) in (4, 8)
                        and bar.start_ms < downbeats[i + 1]
                        and bar.end_ms > downbeats[i]
                        for bar in bars[first:last]
                    )
                    for i in short_groups
                ):
                    continue
                if any(
                    _span(bar) == 8
                    and not any(
                        abs(bar.start_ms - downbeats[i]) < quarter * 0.55
                        and abs(bar.end_ms - downbeats[i + 1]) < quarter * 0.55
                        for i in short_groups
                    )
                    for bar in bars[first:last]
                ):
                    continue
                if any(
                    len(groups[i]) == _span(short) / 4
                    and abs(short.start_ms - downbeats[i]) <= quarter * 0.35
                    and abs(short.end_ms - downbeats[i + 1]) <= quarter * 0.35
                    for i in range(begin, end)
                ):
                    continue
                if _span(short) == 4 and not any(
                    short.start_ms < downbeats[i + 1] and short.end_ms > downbeats[i]
                    for i in short_groups
                ):
                    continue  # A complementary 3+1 or merge has separate evidence.
                error = abs(bars[first].start_ms - downbeats[begin]) + abs(
                    bars[last].start_ms - downbeats[end]
                )
                candidates.append((last - first, error, first, last, tuple(replacement)))
        if candidates:
            _, _, first, last, selected_groups = min(candidates)
            repairs.append(MeterRepair(first, last, selected_groups, downbeats[anchors[last]]))
            floor = last
    return repairs


def apply_meter_repairs(document: MelodyDocument, repairs: list[MeterRepair]) -> MelodyDocument:
    """Reproject events onto local beat anchors while preserving their audio time."""
    if not repairs:
        return document
    bars = document.bars
    output: list[MelodyBar] = []
    windows = []
    shift = 0
    cursor = 0
    for repair in repairs:
        first, last = repair.first, repair.last
        output.extend(_shift_bar(bar, shift) for bar in bars[cursor:first])
        old_start = bars[first].start_16th
        old_end = bars[last].start_16th
        assert old_start is not None and old_end is not None
        start, end = bars[first].start_ms, bars[last].start_ms
        groups = repair.beat_groups
        grid = [start]
        step = old_start + shift
        for index, group in enumerate(groups):
            left = start if index == 0 else group[0]
            right = groups[index + 1][0] if index + 1 < len(groups) else end
            model_end = groups[index + 1][0] if index + 1 < len(groups) else repair.model_end_ms
            pulses = [
                left,
                *(
                    round(left + (t - group[0]) * (right - left) / (model_end - group[0]))
                    for t in group[1:]
                ),
            ]
            source = next(bar for bar in bars[first:last] if (left + right) / 2 < bar.end_ms)
            next_step = step + 4 * len(group)
            output.append(
                MelodyBar(
                    start_ms=left,
                    end_ms=right,
                    beat_times_ms=pulses,
                    start_16th=step,
                    end_16th=next_step,
                    section_label=source.section_label,
                )
            )
            grid.extend([*pulses[1:], right])
            step = next_step
        windows.append((start, end, old_start + shift, tuple(grid), step - old_end))
        shift = step - old_end
        cursor = last
    output.extend(_shift_bar(bar, shift) for bar in bars[cursor:])

    def project(time: int, old_step: int) -> int:
        offset = 0
        for start, end, step, grid, next_offset in windows:
            if time < start:
                break
            if time < end:
                beat = bisect_right(grid, time) - 1
                fraction = (time - grid[beat]) / (grid[beat + 1] - grid[beat])
                return step + beat * 4 + round(fraction * 4)
            offset = next_offset
        return old_step + offset

    data = document.model_dump(mode="python")
    data["bars"] = [bar.model_dump(mode="python") for bar in output]
    notes = [note for note in data["notes"] if note["start_16th"] is not None]
    projected = [project(note["start_ms"], note["start_16th"]) for note in notes]
    # Reserve one position per distinct original attack. The lead renderer
    # would otherwise truncate the first of two notes rounded to one tick.
    if projected:
        projected[-1] = min(projected[-1], (output[-1].end_16th or 1) - 1)
    for index in range(len(projected) - 2, -1, -1):
        separate = int(notes[index]["start_16th"] != notes[index + 1]["start_16th"])
        projected[index] = min(projected[index], projected[index + 1] - separate)
    if projected and projected[0] < (output[0].start_16th or 0):
        return document
    for note, start in zip(notes, projected, strict=True):
        end = project(note["end_ms"], note["start_16th"] + note["duration_16ths"])
        note["start_16th"] = start
        note["duration_16ths"] = max(1, end - start)
    for event in [*data["chords"], *data["key_changes"]]:
        if event["start_16th"] is not None:
            event["start_16th"] = project(event["at_ms"], event["start_16th"])
    return MelodyDocument.model_validate(data, strict=True)


def _shift_bar(bar: MelodyBar, shift: int) -> MelodyBar:
    if not shift or bar.start_16th is None or bar.end_16th is None:
        return bar
    return bar.model_copy(
        update={
            "start_16th": bar.start_16th + shift,
            "end_16th": bar.end_16th + shift,
        }
    )

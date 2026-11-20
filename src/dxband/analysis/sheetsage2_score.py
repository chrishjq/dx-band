# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Build a reviewable melody draft from SheetSage2's timed score events.

The model's downbeats delimit bars.  Preserve short and irregular measures
instead of forcing a constant meter or regrouping consecutive two-beat bars.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping
from itertools import pairwise
from statistics import median
from typing import Any

from dxband.models.melody import (
    MelodyBar,
    MelodyChord,
    MelodyDocument,
    MelodyKeyChange,
    MelodyNote,
)

_PITCH_CLASSES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SECTIONS = {
    "intro": "前奏",
    "verse": "主歌",
    "pre-chorus": "预副歌",
    "chorus": "副歌",
    "post-chorus": "后副歌",
    "bridge": "桥段",
    "interlude": "间奏",
    "outro": "尾奏",
    "solo": "独奏",
}


def _pitch_class(label: str) -> int | None:
    match = re.match(r"^([A-G])([#b]?)", label)
    if match is None:
        return None
    return (_PITCH_CLASSES[match[1]] + {"#": 1, "b": -1, "": 0}[match[2]]) % 12


def _event_value(event: Mapping[str, Any], field: str) -> Any:
    return event.get("values", {}).get(field)


def evenly_spaced_beat_times(start_ms: int, end_ms: int, count: int) -> list[int]:
    """Place beat arrivals evenly between two model detected downbeats."""
    if count < 1 or end_ms <= start_ms:
        raise ValueError("beat grid requires a positive duration and beat count")
    return [start_ms + round((end_ms - start_ms) * index / count) for index in range(count)]


def normalize_melody_beat_grid(document: MelodyDocument) -> MelodyDocument:
    """Place each bar's score beat positions between its downbeat boundaries."""
    data = document.model_dump(mode="python")
    for bar in data["bars"]:
        bar["beat_times_ms"] = evenly_spaced_beat_times(
            bar["start_ms"], bar["end_ms"], len(bar["beat_times_ms"])
        )
    return MelodyDocument.model_validate(data, strict=True)


def complete_two_beat_opening(document: MelodyDocument) -> MelodyDocument:
    """Notate a half-length opening as two rests followed by four eighth notes.

    SheetSage2 occasionally marks the four attacks of a two-beat pickup as
    four quarter notes.  Correct this only when the following full measures
    establish a steady beat and all four opening attacks support the change.
    Audio times and pitches are preserved.
    """
    if len(document.bars) < 3:
        return document
    first = document.bars[0]
    if (
        first.leading_rest_beats
        or first.start_16th is None
        or first.end_16th != first.start_16th + 16
        or len(first.beat_times_ms) != 4
    ):
        return document
    later_lengths = [
        (bar.end_ms - bar.start_ms) / len(bar.beat_times_ms)
        for bar in document.bars[1:6]
        if len(bar.beat_times_ms) == 4
    ]
    if len(later_lengths) < 2:
        return document
    beat_ms = median(later_lengths)
    opening_beat_ms = (first.end_ms - first.start_ms) / 2
    if not 0.88 <= opening_beat_ms / beat_ms <= 1.12:
        return document
    opening_notes = [
        note for note in document.notes if first.start_ms <= note.start_ms < first.end_ms
    ]
    expected_steps = [first.start_16th + 4 * index for index in range(4)]
    if (
        len(opening_notes) != 4
        or [note.start_16th for note in opening_notes] != expected_steps
        or any(note.duration_16ths is None or note.duration_16ths > 4 for note in opening_notes)
        or any(
            abs(note.start_ms - beat) > 140
            for note, beat in zip(opening_notes, first.beat_times_ms, strict=True)
        )
    ):
        return document
    data = document.model_dump(mode="python")
    data["bars"][0]["beat_times_ms"] = [first.beat_times_ms[0], first.beat_times_ms[2]]
    data["bars"][0]["leading_rest_beats"] = 2
    for index, note in enumerate(
        note for note in data["notes"] if first.start_ms <= note["start_ms"] < first.end_ms
    ):
        note["start_16th"] = first.start_16th + 8 + index * 2
        note["duration_16ths"] = min(note["duration_16ths"], 2)
    return MelodyDocument.model_validate(data, strict=True)


def _last_bar_end(
    events: list[dict[str, Any]],
    downbeat_steps: list[int],
    quarter_steps: list[int],
    time_by_step: dict[int, int],
) -> tuple[int, int]:
    start = downbeat_steps[-1]
    if start == max(time_by_step) and not any(
        _event_value(event, "melody") or (_event_value(event, "rhythm") or {}).get("meter")
        for event in events
        if int(event["global_subbeat"]) == start
    ):
        # The decoder often emits a final downbeat exactly at the audio end.
        # It closes the previous bar; it is not a new full empty measure.
        return start, time_by_step[start]
    meter = next(
        (
            rhythm["meter"]
            for event in reversed(events)
            if int(event["global_subbeat"]) <= start
            for rhythm in [_event_value(event, "rhythm") or {}]
            if rhythm.get("meter")
        ),
        None,
    )
    numerator = int(meter[0]) if isinstance(meter, list) and meter else 4
    denominator = int(meter[1]) if isinstance(meter, list) and len(meter) > 1 else 4
    numerator = max(1, min(numerator, 12))
    if denominator not in (2, 4, 8, 16):
        raise ValueError(f"unsupported SheetSage2 meter denominator: {denominator}")
    last_step = max(step for step in quarter_steps if step >= start)
    end = min(start + numerator * 16 // denominator, last_step + 4)
    if end in time_by_step:
        return end, time_by_step[end]
    observed = [time_by_step[step] for step in quarter_steps if step in time_by_step]
    intervals = [right - left for left, right in pairwise(observed) if right > left]
    beat_ms = round(median(intervals[-12:])) if intervals else 500
    return end, time_by_step[last_step] + round((end - last_step) / 4 * beat_ms)


def build_sheetsage2_melody(
    event_document: Mapping[str, Any], *, min_note_ms: int = 80
) -> MelodyDocument:
    """Use decoded score positions and downbeats as the notation time base."""
    events = sorted(event_document["events"], key=lambda item: int(item["global_subbeat"]))
    time_by_step = {
        int(event["global_subbeat"]): round(float(event["time"]) * 1000) for event in events
    }
    quarter_steps = sorted(
        {
            int(event["global_subbeat"])
            for event in events
            if (_event_value(event, "rhythm") or {}).get("eighth_position") in (0, 2, 4, 6)
        }
    )
    downbeat_steps = sorted(
        {
            int(event["global_subbeat"])
            for event in events
            if (_event_value(event, "rhythm") or {}).get("eighth_position") == 0
        }
    )
    raw_notes = [
        (int(event["global_subbeat"]), note)
        for event in events
        for note in (_event_value(event, "melody") or [])
        if round(float(note["end_time"]) * 1000) - time_by_step[int(event["global_subbeat"])]
        >= min_note_ms
    ]
    if not raw_notes or len(downbeat_steps) < 2:
        raise ValueError("SheetSage2 events have no usable melody and downbeats")
    first_note_step = min(step for step, _ in raw_notes)
    first_step = downbeat_steps[max(0, bisect_right(downbeat_steps, first_note_step) - 1)]
    final_step, final_time = _last_bar_end(events, downbeat_steps, quarter_steps, time_by_step)
    time_by_step[final_step] = final_time
    boundaries = [step for step in downbeat_steps if step >= first_step]
    if final_step > boundaries[-1]:
        boundaries.append(final_step)
    key_events = [
        (int(event["global_subbeat"]), _event_value(event, "key"))
        for event in events
        if _event_value(event, "key")
    ]
    key_label = key_events[0][1] if key_events else "C:major"
    for step, label in key_events:
        if step > first_step:
            break
        key_label = label
    tonic = _pitch_class(key_label)
    if tonic is None:
        raise ValueError(f"unsupported SheetSage2 key: {key_label}")
    key_changes = []
    current_tonic = tonic
    for step, label in key_events:
        if step <= first_step:
            continue
        next_tonic = _pitch_class(label)
        if next_tonic is None:
            raise ValueError(f"unsupported SheetSage2 key: {label}")
        if next_tonic != current_tonic and first_step <= step < final_step:
            key_changes.append(
                MelodyKeyChange(
                    at_ms=time_by_step[step],
                    tonic_midi=60 + next_tonic,
                    start_16th=step,
                )
            )
        current_tonic = next_tonic

    section_at_step: dict[int, str] = {}
    current_section = ""
    for event in events:
        section = _event_value(event, "structure")
        if section:
            current_section = _SECTIONS.get(section, section)
        section_at_step[int(event["global_subbeat"])] = current_section
    bars = []
    observed_steps = sorted(time_by_step)

    def beat_time(step: int) -> int:
        if step in time_by_step:
            return time_by_step[step]
        following = bisect_right(observed_steps, step)
        if following == 0 or following == len(observed_steps):
            raise ValueError(f"SheetSage2 beat {step} has no surrounding time anchors")
        before_step, after_step = observed_steps[following - 1], observed_steps[following]
        before, after = time_by_step[before_step], time_by_step[after_step]
        return round(before + (after - before) * (step - before_step) / (after_step - before_step))

    for start, end in pairwise(boundaries):
        beat_steps = list(range(start, end, 4))
        section = next(
            (
                section_at_step[int(event["global_subbeat"])]
                for event in events
                if int(event["global_subbeat"]) == start
            ),
            current_section,
        )
        bars.append(
            MelodyBar(
                start_ms=time_by_step[start],
                end_ms=time_by_step[end],
                beat_times_ms=[beat_time(step) for step in beat_steps],
                start_16th=start,
                end_16th=end,
                section_label=section,
                review="candidate" if end - start == 16 else "needs_review",
            )
        )
    coverage_end = bars[-1].end_ms
    notes = []
    for step, note in raw_notes:
        if not first_step <= step < final_step:
            continue
        start_ms = time_by_step[step]
        end_ms = min(coverage_end, round(float(note["end_time"]) * 1000))
        steps = min(int(note["duration_steps"]), final_step - step)
        if end_ms - start_ms < min_note_ms or steps < 1:
            continue
        notes.append(
            MelodyNote(
                start_ms=start_ms,
                end_ms=end_ms,
                midi=int(note["pitch"]),
                source="vocals" if int(note["track"]) == 0 else "other",
                review="needs_review",
                evidence=["sheetsage2"],
                start_16th=step,
                duration_16ths=steps,
            )
        )
    notes.sort(key=lambda note: (note.start_ms, note.midi))
    chords = [
        MelodyChord(
            at_ms=time_by_step[int(event["global_subbeat"])],
            chord=_event_value(event, "chord"),
            start_16th=int(event["global_subbeat"]),
        )
        for event in events
        if first_step <= int(event["global_subbeat"]) < final_step
        and _event_value(event, "chord")
        and _event_value(event, "chord") != "N"
    ]
    return MelodyDocument(
        tonic_midi=60 + tonic,
        coverage_end_ms=coverage_end,
        notes=notes,
        chords=chords,
        key_changes=key_changes,
        bars=bars,
    )

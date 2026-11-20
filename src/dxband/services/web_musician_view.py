# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Create JSON-safe chord and lyric rows for the musician browser view."""

from __future__ import annotations

import re
from bisect import bisect_right
from copy import deepcopy
from typing import Any, cast

from dxband.analysis.chord_notation import (
    CHORD_DISPLAY_MODES,
    capo_for_c_chords,
    chord_for_mode,
    chord_reference_key,
    degree_reference_offset,
    transpose_for_display_key,
)
from dxband.creation.package_validator import SongPackage
from dxband.lyrics.character_timing import character_timestamp, is_title_metadata_line
from dxband.lyrics.musician_bar_rows import build_musician_bar_rows, complete_beat_grid

_LYRIC_NOTE_TOLERANCE_MS = 250


def _labels_by_mode(chords: tuple[str, ...] | list[str], key: str) -> dict[str, list[str]]:
    visible = tuple(chord for chord in chords if chord != "N")
    return {
        mode: [chord_for_mode(chord, key, mode) for chord in visible]
        for mode in CHORD_DISPLAY_MODES
    }


def _selected_labels(chords: tuple[str, ...] | list[str], key: str, mode: str) -> list[str]:
    return [chord_for_mode(chord, key, mode) for chord in chords if chord != "N"]


def _chord_changes(events: list[Any] | tuple[Any, ...]) -> list[Any]:
    """Keep actual chord changes and hide repeated recognition events.

    ``N`` is not displayed, but it resets the sounding chord. Therefore a
    chord repeated after a no-chord interval remains a real instruction.
    """
    visible: list[Any] = []
    previous: str | None = None
    for event in events:
        chord = event.chord
        if chord == "N":
            previous = None
        elif chord != previous:
            visible.append(event)
            previous = chord
    return visible


def _melody_bpm(package: SongPackage) -> int | None:
    melody = package.melody
    if melody is None or not melody.bars:
        return None
    # The first measure may be a pickup or a local half/double-time segment.
    # The full-song transcription already provides the nominal tempo.
    return package.config.musical.bpm


def _c_to_original_key_transpose(original_key: str) -> int | None:
    return transpose_for_display_key(original_key, "C")


def _numbered_tonic_midi(package: SongPackage, tonic_midi: int) -> int:
    return tonic_midi + (degree_reference_offset(package.config.musical.original_key) or 0)


def _numbered_pitch_name(package: SongPackage, tonic_midi: int) -> str:
    sharp_names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    flat_names = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
    reference_key = chord_reference_key(package.config.musical.original_key)
    names = flat_names if "b" in reference_key else sharp_names
    return names[tonic_midi % 12]


def _melody_tonic_at(package: SongPackage, at_ms: int, step: int | None) -> int:
    document = package.melody
    assert document is not None
    tonic = document.tonic_midi
    for change in document.key_changes:
        if step is not None and change.start_16th is not None:
            if change.start_16th > step:
                break
        elif change.at_ms > at_ms:
            break
        tonic = change.tonic_midi
    return _numbered_tonic_midi(package, tonic)


def _melody_key_fields(package: SongPackage, at_ms: int, step: int | None) -> dict[str, int]:
    document = package.melody
    if document is None or not document.key_changes:
        return {}
    tonic = _melody_tonic_at(package, at_ms, step)
    return {"melody_key": tonic % 12, "melody_tonic_midi": tonic}


def _add_melody_to_rows(
    package: SongPackage,
    rows: list[dict[str, Any]],
    lyric_beat_times: dict[tuple[str, int], int],
) -> None:
    document = package.melody
    if document is None:
        return
    has_linked_notes = any(note.lyric_line_id is not None for note in document.notes)
    beats = [beat for row in rows if row["layout"] == "bars" for beat in row["beats"]]
    beat_times = [int(beat["at_ms"]) for beat in beats]
    scored_beats = [
        (int(beat["start_16th"]), index)
        for index, beat in enumerate(beats)
        if beat.get("start_16th") is not None
    ]
    score_steps = [step for step, _ in scored_beats]
    score_times_by_step = {step: beat_times[index] for step, index in scored_beats}
    for beat in beats:
        beat["melody_notes"] = []
    # This is a single lead line. A new attack ends the preceding note even
    # when the transcription model gives its sustain a later release.
    grid_notes = sorted(
        (note.start_16th, index, note)
        for index, note in enumerate(document.notes)
        if note.start_16th is not None and note.duration_16ths is not None
    )
    triplet_steps = {
        bar.start_16th + 4 * beat + slot
        for bar in document.bars if bar.start_16th is not None
        for beat in bar.triplet_beats
        for slot in (0, 1, 3)
    }
    effective_durations: dict[int, int] = {}
    for position, (step, index, note) in enumerate(grid_notes):
        duration = cast(int, note.duration_16ths)
        if position + 1 < len(grid_notes):
            next_step, _, following = grid_notes[position + 1]
            distance = next_step - step
            if (
                distance - duration == 1
                and step not in triplet_steps
                and note.source == following.source
                and -60 <= following.start_ms - note.end_ms <= 60
            ):
                duration = distance  # The apparent sixteenth rest is rounding, not a silence.
            duration = min(duration, distance)
        effective_durations[index] = duration
    occupied_notes = [
        (step, step + effective_durations[index])
        for step, index, _ in grid_notes
        if effective_durations[index] > 0
    ]
    bar_boundaries = {
        bar.start_16th: bar.start_ms for bar in document.bars[1:] if bar.start_16th is not None
    }
    key_boundaries = [
        change.start_16th for change in document.key_changes if change.start_16th is not None
    ]
    for note_index, note in enumerate(document.notes):
        duration_16ths = effective_durations.get(note_index, note.duration_16ths)
        if duration_16ths is not None and duration_16ths <= 0:
            continue
        anchor = note.display_ms if note.display_ms is not None else note.start_ms
        if (
            not document.bars
            and note.lyric_line_id is not None
            and note.lyric_character_index is not None
        ):
            anchor = lyric_beat_times.get((note.lyric_line_id, note.lyric_character_index), anchor)
        elif document.bars and note.source == "vocals":
            anchor = note.start_ms
        if beat_times:
            positions = [note.start_16th] if note.start_16th is not None else []
            if note.start_16th is not None and duration_16ths is not None:
                positions.extend(
                    step
                    for step in sorted(bar_boundaries)
                    if note.start_16th < step < note.start_16th + duration_16ths
                )
                positions.extend(
                    step
                    for step in key_boundaries
                    if note.start_16th < step < note.start_16th + duration_16ths
                )
                # Split syncopated sustains and releases inside a later beat.
                # Otherwise a held note followed by a rest is reduced to an
                # ambiguous dash and the actual release is not notated.
                note_end = note.start_16th + duration_16ths
                if note.start_16th not in score_times_by_step or (
                    note_end not in score_times_by_step and duration_16ths > 4
                ):
                    positions.extend(
                        step for step in score_steps if note.start_16th < step < note_end
                    )
                positions = sorted(set(positions))
            for part, part_step in enumerate(positions or [None]):
                if part_step is not None and score_steps:
                    score_index = max(0, bisect_right(score_steps, part_step) - 1)
                    index = scored_beats[score_index][1]
                else:
                    index = max(0, min(len(beats) - 1, bisect_right(beat_times, anchor) - 1))
                    if index + 1 < len(beats) and beat_times[index + 1] - anchor <= 80:
                        index += 1
                segment_end_step = (
                    positions[part + 1]
                    if part_step is not None and part + 1 < len(positions)
                    else note.start_16th + duration_16ths
                    if part_step is not None
                    and note.start_16th is not None
                    and duration_16ths is not None
                    else None
                )
                item: dict[str, Any] = {
                    "midi": note.midi,
                    "review": note.review,
                    "at_ms": (
                        note.start_ms
                        if part == 0 or part_step is None
                        else score_times_by_step[part_step]
                    ),
                }
                if part_step is not None and segment_end_step is not None:
                    item["start_16th"] = part_step
                    item["duration_16ths"] = segment_end_step - part_step
                item.update(_melody_key_fields(package, item["at_ms"], part_step))
                if len(positions) > 1:
                    item.update(
                        tie_id=note_index, tie_in=part > 0, tie_out=part < len(positions) - 1
                    )
                beats[index]["melody_notes"].append(item)
                for later in range(index + 1, len(beats)):
                    if (
                        part_step is not None
                        and segment_end_step is not None
                        and beats[later].get("start_16th") is not None
                    ):
                        if beats[later]["start_16th"] >= segment_end_step:
                            break
                    elif beat_times[later] >= note.end_ms:
                        break
                    beats[later]["melody_hold"] = True
    for index, beat in enumerate(beats):
        beat_end = beat_times[index + 1] if index + 1 < len(beats) else package.config.duration_ms
        if beat.get("rest") or beat["melody_notes"] or beat.get("melody_hold"):
            continue
        beat["melody_gap"] = next(
            (
                gap.label
                for gap in document.gaps
                if gap.start_ms < beat_end and gap.end_ms > beat_times[index]
            ),
            "",
        )
        if beat.get("start_16th") is not None and not beat["melody_gap"]:
            beat["rest"] = True
    for row in rows:
        if row["layout"] == "line":
            start, end = int(row["start_ms"]), int(row["end_ms"])
            row["melody_notes"] = [
                {
                    "midi": note.midi,
                    "review": note.review,
                    "at_ms": note.start_ms,
                    **_melody_key_fields(package, note.start_ms, None),
                }
                for note in document.notes
                if start
                <= (note.display_ms if note.display_ms is not None else note.start_ms)
                < end
            ]
    # A score note list records attacks, not the silence between them. Derive
    # rests from the occupied sixteenth-note intervals in every measure so a
    # late attack or an early release does not silently consume part of a beat.
    if not any(note.start_16th is not None for note in document.notes):
        return
    for row in rows:
        if not row.get("score_bar"):
            continue
        bar_beats = row["beats"]
        if not bar_beats or bar_beats[0].get("start_16th") is None:
            continue
        bar = next((item for item in document.bars if item.start_ms == row["start_ms"]), None)
        if bar is None or bar.end_16th is None:
            continue
        for beat in bar_beats:
            start = int(beat["start_16th"])
            end = min(start + 4, bar.end_16th)
            if end <= start:
                continue
            if any(note.get("start_16th") is None for note in beat["melody_notes"]):
                continue
            occupied = sorted(
                (
                    max(start, note_start),
                    min(end, note_end),
                    note_start,
                )
                for note_start, note_end in occupied_notes
                if note_start < end and note_end > start
            )
            events = [{"kind": "note", **item} for item in beat["melody_notes"]]
            cursor = start
            for occupied_start, occupied_end, note_start in occupied:
                if occupied_start > cursor and not beat.get("melody_gap"):
                    events.append(
                        {
                            "kind": "rest",
                            "start_16th": cursor,
                            "duration_16ths": occupied_start - cursor,
                        }
                    )
                if (
                    note_start < start
                    and occupied_start == start
                    and not any(item.get("start_16th") == start for item in beat["melody_notes"])
                ):
                    events.append(
                        {
                            "kind": "hold",
                            "start_16th": start,
                            "duration_16ths": occupied_end - start,
                        }
                    )
                cursor = max(cursor, occupied_end)
            if cursor < end and not beat.get("melody_gap"):
                events.append(
                    {"kind": "rest", "start_16th": cursor, "duration_16ths": end - cursor}
                )
            if events:
                events.sort(
                    key=lambda event: (
                        event.get("start_16th", start),
                        {"hold": 0, "note": 1, "rest": 2}[event["kind"]],
                    )
                )
                beat["melody_events"] = events
                beat["rest"] = all(event["kind"] == "rest" for event in events)
            units = beat.get("lyric_units", [])
            claimed = {unit.get("start_16th") for unit in units}
            available = [
                note
                for note in beat["melody_notes"]
                if note.get("start_16th") is not None
                and not note.get("tie_in")
                and note["start_16th"] not in claimed
            ]
            for unit in units:
                if has_linked_notes:
                    continue
                if unit.get("start_16th") is not None or not available:
                    continue
                nearest = min(available, key=lambda note: abs(note["at_ms"] - unit["at_ms"]))
                if abs(nearest["at_ms"] - unit["at_ms"]) <= _LYRIC_NOTE_TOLERANCE_MS:
                    unit["start_16th"] = nearest["start_16th"]
                    available.remove(nearest)


def _apply_melody_bars(
    package: SongPackage, rows: list[dict[str, Any]], chord_mode: str
) -> list[dict[str, Any]]:
    """Place lyrics and score chords on the transcription's sixteenth-note axis."""
    document = package.melody
    if document is None or not document.bars:
        return rows
    original = [
        (beat, row.get("section", ""))
        for row in rows
        if row["layout"] == "bars"
        for beat in row["beats"]
        if int(beat["at_ms"]) >= 0
    ]
    line_by_id = {line.id: line for line in package.lyrics.lines}
    line_order = {line.id: index for index, line in enumerate(package.lyrics.lines)}
    vocal_onsets: dict[tuple[str, int], int] = {}
    vocal_steps: dict[tuple[str, int], int] = {}
    for note in document.notes:
        if (
            note.source != "vocals"
            or note.lyric_line_id is None
            or note.lyric_character_index is None
        ):
            continue
        key = (note.lyric_line_id, note.lyric_character_index)
        vocal_onsets[key] = min(note.start_ms, vocal_onsets.get(key, note.start_ms))
        if note.start_16th is not None:
            vocal_steps[key] = note.start_16th
    explicit_sources = set(vocal_onsets)
    # Grid-aware transcriptions can contain more accurate sung onsets than the
    # original word timestamps, without having lyric IDs attached to notes.
    grid_vocals = [
        note for note in document.notes if note.source == "vocals" and note.start_16th is not None
    ]
    if grid_vocals and not explicit_sources:
        lyric_sources = {
            source
            for beat, _ in original
            for source in beat.get("lyric_sources", [])
            if source[0] in line_by_id
        }
        ordered_sources = sorted(
            lyric_sources,
            key=lambda source: (line_order[source[0]], source[1]),
        )
        note_cursor = 0
        for source in ordered_sources:
            line = line_by_id[source[0]]
            original_time = character_timestamp(line, source[1])
            if original_time >= document.bars[-1].end_ms or note_cursor >= len(grid_vocals):
                continue
            candidates = [
                index
                for index in range(note_cursor, len(grid_vocals))
                if abs(grid_vocals[index].start_ms - original_time) <= _LYRIC_NOTE_TOLERANCE_MS
            ]
            if not candidates:
                continue
            match = min(
                candidates,
                key=lambda index: abs(grid_vocals[index].start_ms - original_time),
            )
            vocal_onsets.setdefault(source, grid_vocals[match].start_ms)
            vocal_steps.setdefault(source, cast(int, grid_vocals[match].start_16th))
            note_cursor = match + 1
    score_rows: list[dict[str, Any]] = []
    key_change_by_step = {
        change.start_16th: change
        for change in document.key_changes
        if change.start_16th is not None
    }
    usual_beats = package.config.musical.beats_per_bar or 4
    previous_meter = f"{usual_beats}/4"
    for bar_index, bar in enumerate(document.bars):
        score_beats: list[dict[str, Any]] = []
        section = bar.section_label
        score_span = (
            bar.end_16th - bar.start_16th
            if bar.start_16th is not None and bar.end_16th is not None
            else None
        )
        if score_span is None:
            meter_beats = len(bar.beat_times_ms) + bar.leading_rest_beats
            actual_meter = f"{meter_beats}/4"
        elif score_span % 4 == 0:
            actual_meter = f"{score_span // 4}/4"
        elif score_span % 2 == 0:
            actual_meter = f"{score_span // 2}/8"
        else:
            actual_meter = f"{score_span}/16"
        partial_ending = (
            bar_index == len(document.bars) - 1
            and bar.review == "needs_review"
            and bar.end_ms == document.coverage_end_ms
            and score_span is not None and score_span < usual_beats * 4
        )
        meter = actual_meter if actual_meter != previous_meter and not partial_ending else None
        previous_meter = actual_meter
        beat_starts = list(bar.beat_times_ms)
        if bar.leading_rest_beats:
            interval = (
                beat_starts[1] - beat_starts[0]
                if len(beat_starts) > 1
                else bar.end_ms - beat_starts[0]
            )
            beat_starts = [
                beat_starts[0] - interval * index
                for index in range(bar.leading_rest_beats, 0, -1)
            ] + beat_starts
        for index, start in enumerate(beat_starts):
            end = beat_starts[index + 1] if index + 1 < len(beat_starts) else bar.end_ms
            members = [(beat, label) for beat, label in original if start <= beat["at_ms"] < end]
            if members and not section:
                section = next((label for _, label in members if label), "")
            score_beats.append(
                {
                    "at_ms": start,
                    "bar_start": index == 0,
                    "lyrics": "",
                    "chords": [],
                    "chord_modes": {mode: [] for mode in CHORD_DISPLAY_MODES},
                    "rest": index < bar.leading_rest_beats,
                    **({"triplet": True} if index - bar.leading_rest_beats in bar.triplet_beats
                       else {}),
                    **(
                        {"start_16th": bar.start_16th + 4 * index}
                        if bar.start_16th is not None
                        else {}
                    ),
                }
            )
        change = key_change_by_step.get(bar.start_16th) if bar.start_16th is not None else None
        if change is not None:
            tonic_midi = _numbered_tonic_midi(package, change.tonic_midi)
            score_beats[0]["melody_key_change"] = (
                f"1={_numbered_pitch_name(package, tonic_midi)}"
            )
        score_rows.append(
            {
                "layout": "bars",
                "start_ms": bar.start_ms,
                "end_ms": bar.end_ms,
                "section": section,
                "meter": meter,
                **({"meter_uncertain": True} if meter and bar.review == "needs_review"
                   and score_span is not None and score_span < usual_beats * 4 else {}),
                "beats": score_beats,
                "score_bar": True,
            }
        )
    score_beats = [beat for row in score_rows for beat in row["beats"]]
    score_times = [int(beat["at_ms"]) for beat in score_beats]
    score_steps = [beat.get("start_16th") for beat in score_beats]
    display_model_chords = _chord_changes(document.chords)
    positioned_chords = [
        chord for chord in display_model_chords if chord.start_16th is not None
    ]
    if positioned_chords and all(step is not None for step in score_steps):
        # The score and its chord events share the same sixteenth-note axis.
        # Millisecond chord segments can drift when the display beat grid is rebuilt.
        for chord in positioned_chords:
            target = bisect_right(score_steps, chord.start_16th) - 1
            if not 0 <= target < len(score_beats):
                continue
            beat = score_beats[target]
            unit = {
                "start_16th": chord.start_16th,
                "chord": chord.chord,
                "chord_modes": _labels_by_mode([chord.chord], package.config.musical.original_key),
            }
            beat.setdefault("chord_units", []).append(unit)
        for beat in score_beats:
            chord_units = beat.get("chord_units", [])
            beat["chord_modes"] = {
                mode: [unit["chord_modes"][mode][0] for unit in chord_units]
                for mode in CHORD_DISPLAY_MODES
            }
            beat["chords"] = _selected_labels(
                [unit["chord"] for unit in chord_units],
                package.config.musical.original_key,
                chord_mode,
            )
    else:
        chord_cells: list[list[str]] = [[] for _ in score_beats]
        all_chord_segments = package.chords.segments if package.chords is not None else []
        chord_segments = _chord_changes(all_chord_segments)
        for segment in chord_segments:
            if segment.chord == "N" or not score_times:
                continue
            if score_times[0] - 120 <= segment.start_ms < document.bars[-1].end_ms:
                target = max(
                    0,
                    min(
                        len(score_times) - 1,
                        bisect_right(score_times, segment.start_ms + 120) - 1,
                    ),
                )
                if segment.chord not in chord_cells[target]:
                    chord_cells[target].append(segment.chord)
        for index, beat in enumerate(score_beats):
            if index == 0:
                active = next(
                    (
                        segment.chord
                        for segment in all_chord_segments
                        if segment.chord != "N"
                        and segment.start_ms <= beat["at_ms"] < segment.end_ms
                    ),
                    None,
                )
                near_boundary_change = any(
                    segment.chord != "N" and abs(segment.start_ms - beat["at_ms"]) <= 150
                    for segment in all_chord_segments
                )
                if (
                    active is not None
                    and not near_boundary_change
                    and active not in chord_cells[index]
                ):
                    chord_cells[index].insert(0, active)
            if not chord_cells[index] and document.chords:
                beat_start = beat["at_ms"]
                beat_end = (
                    score_times[index + 1]
                    if index + 1 < len(score_times)
                    else document.bars[-1].end_ms
                )
                for model_chord in display_model_chords:
                    if beat_start - 120 <= model_chord.at_ms < beat_end - 120:
                        chord_cells[index].append(model_chord.chord)
            labels = _labels_by_mode(chord_cells[index], package.config.musical.original_key)
            beat["chords"] = _selected_labels(
                chord_cells[index], package.config.musical.original_key, chord_mode
            )
            beat["chord_modes"] = labels
    lyric_items: list[list[tuple[int, int, str, int | None, int]]] = [[] for _ in score_beats]
    placed_sources: set[tuple[str, int]] = set()
    original_sources = {
        (line_id, char_index)
        for beat, _ in original
        for line_id, char_index in beat.get("lyric_sources", [])
    }
    units: list[tuple[str, int, str, tuple[tuple[str, int], ...]]] = []
    if package.lyrics.language.lower().startswith("en"):
        for line_id, lyric_line in line_by_id.items():
            for word_match in re.finditer(r"\S+\s*", lyric_line.text):
                indices = tuple(
                    (line_id, index) for index in range(word_match.start(), word_match.end())
                )
                if indices[0] in original_sources:
                    text = word_match.group() + (
                        " " if word_match.end() == len(lyric_line.text) else ""
                    )
                    units.append((line_id, word_match.start(), text, indices))
    else:
        for line_id, char_index in sorted(
            original_sources, key=lambda source: (line_order[source[0]], source[1])
        ):
            source_line = line_by_id.get(line_id)
            if source_line is not None and char_index < len(source_line.text):
                units.append(
                    (line_id, char_index, source_line.text[char_index], ((line_id, char_index),))
                )
    for line_id, char_index, unit_text, sources in units:
        lyric_line = line_by_id[line_id]
        original_time = character_timestamp(lyric_line, char_index)
        explicit_anchor = (line_id, char_index) in explicit_sources
        onset = (
            None
            if package.lyrics.language.lower().startswith("en") and not explicit_anchor
            else vocal_onsets.get((line_id, char_index))
        )
        # A word timestamp can precede its audible onset. Use the model
        # only for display when it stays close enough to the original word.
        anchor = (
            onset
            if onset is not None
            and (explicit_anchor or abs(onset - original_time) <= _LYRIC_NOTE_TOLERANCE_MS)
            else original_time
        )
        if not score_times or not score_times[0] <= anchor < document.bars[-1].end_ms:
            continue
        following = bisect_right(score_times, original_time)
        target = max(0, following - 1)
        if (
            following < len(score_times)
            and score_times[following] - original_time <= original_time - score_times[target]
        ):
            target = following
        step = (
            vocal_steps.get((line_id, char_index))
            if onset is not None
            and (explicit_anchor or abs(onset - original_time) <= _LYRIC_NOTE_TOLERANCE_MS)
            else None
        )
        if step is not None and all(value is not None for value in score_steps):
            positioned_steps = [cast(int, value) for value in score_steps]
            note_target = max(
                0,
                min(len(positioned_steps) - 1, bisect_right(positioned_steps, step) - 1),
            )
            target = note_target
        lyric_items[target].append((line_order[line_id], char_index, unit_text, step, anchor))
        placed_sources.update(sources)
    for beat, items in zip(score_beats, lyric_items, strict=True):
        ordered = sorted(items)
        beat["lyrics"] = "".join(char for _, _, char, _, _ in ordered)
        beat["lyric_units"] = [
            {"text": char, "at_ms": anchor, **({"start_16th": step} if step is not None else {})}
            for _, _, char, step, anchor in ordered
        ]
    # The song's ordinary grid resumes at the first full bar after score coverage.
    first_score_start = document.bars[0].start_ms
    cutoff = document.bars[-1].end_ms
    preceding = []
    remainder = []
    for row in rows:
        if row["layout"] != "bars":
            if row["end_ms"] <= first_score_start:
                preceding.append(row)
            elif row["start_ms"] >= cutoff:
                remainder.append(row)
            continue
        before = [
            deepcopy(beat)
            for beat in row["beats"]
            if 0 <= beat["at_ms"] < first_score_start
        ]
        if before:
            preceding.append({**row, "end_ms": first_score_start, "beats": before})
        beats = [deepcopy(beat) for beat in row["beats"] if beat["at_ms"] >= cutoff]
        if beats:
            for beat in beats:
                remaining_sources = [
                    tuple(source)
                    for source in beat.get("lyric_sources", [])
                    if tuple(source) not in placed_sources
                ]
                beat["lyric_sources"] = remaining_sources
                beat["lyrics"] = "".join(
                    line_by_id[line_id].text[char_index]
                    for line_id, char_index in remaining_sources
                    if line_id in line_by_id and char_index < len(line_by_id[line_id].text)
                )
            remainder.append({**row, "start_ms": beats[0]["at_ms"], "beats": beats})
    # The ordinary beat grid can run beyond the transcription to the media
    # duration. Its final rows are only placeholders when they contain no
    # lyrics or new harmony; do not show extra all-rest measures after the
    # score has ended. Earlier score bars can still contain audible backing.
    while remainder and remainder[-1].get("layout") == "bars" and not any(
        beat.get("lyrics") or beat.get("chords") or beat.get("lyric_sources")
        for beat in remainder[-1].get("beats", [])
    ):
        remainder.pop()
    return preceding + score_rows + remainder


def build_web_musician_song(package: SongPackage, chord_mode: str) -> dict[str, object]:
    musical = package.config.musical
    beat_times_ms, downbeat_times_ms = complete_beat_grid(
        tuple(musical.beat_times_ms),
        tuple(musical.downbeat_times_ms),
        musical.beats_per_bar,
        package.config.duration_ms,
    )
    rows = build_musician_bar_rows(
        package.lyrics,
        beat_times_ms,
        downbeat_times_ms,
        # The temporary rows only locate syllables on beat cells; score bars
        # immediately replace their grouping. Keep lyrics available for 3/8,
        # 1/8 and other meters that the old fixed-row builder cannot group.
        musical.beats_per_bar if musical.beats_per_bar in (3, 4) else 4,
        package.chords,
    )
    payload_rows: list[dict[str, Any]] = []
    lyric_beat_times = {
        source: row.beat_times_ms[index]
        for row in rows
        for index, sources in enumerate(row.lyric_sources)
        for source in sources
    }
    if rows:
        first_downbeat = downbeat_times_ms[0]
        pickup_beats = tuple(beat for beat in beat_times_ms if beat < first_downbeat)
        if pickup_beats:
            beat_duration = (
                pickup_beats[1] - pickup_beats[0]
                if len(pickup_beats) > 1
                else first_downbeat - pickup_beats[0]
            )
            # The silent slots precede the audio; keep their beat times before 0
            # so melody notes at the song start still attach to audible beats.
            missing_beats = max(0, (musical.beats_per_bar or 4) - len(pickup_beats))
            pickup_payload = [
                {
                    "at_ms": pickup_beats[0] - (missing_beats - index) * beat_duration,
                    "lyrics": "",
                    "chords": [],
                    "chord_modes": {mode: [] for mode in CHORD_DISPLAY_MODES},
                    "rest": True,
                }
                for index in range(missing_beats)
            ]
            for beat_time in pickup_beats:
                pickup_payload.append(
                    {
                        "at_ms": beat_time,
                        "lyrics": "",
                        "chords": [],
                        "chord_modes": {mode: [] for mode in CHORD_DISPLAY_MODES},
                    }
                )
            payload_rows.append(
                {
                    "layout": "bars",
                    "pickup": True,
                    "start_ms": 0,
                    "end_ms": first_downbeat,
                    "section": "前奏",
                    "beats": pickup_payload,
                }
            )
        for row in rows:
            payload_beats: list[dict[str, object]] = []
            for index, beat_time in enumerate(row.beat_times_ms):
                labels_by_mode = _labels_by_mode(row.chord_cells[index], musical.original_key)
                payload_beats.append(
                    {
                        "at_ms": beat_time,
                        "lyrics": row.lyric_cells[index],
                        "lyric_sources": row.lyric_sources[index],
                        "chords": _selected_labels(
                            row.chord_cells[index], musical.original_key, chord_mode
                        ),
                        "chord_modes": labels_by_mode,
                    }
                )
            payload_rows.append(
                {
                    "layout": "bars",
                    "start_ms": max(row.start_ms, first_downbeat),
                    "end_ms": row.end_ms,
                    "section": row.section_label,
                    "beats": payload_beats,
                }
            )
    else:
        chords = _chord_changes(package.chords.segments) if package.chords is not None else []
        for line in package.lyrics.lines:
            if is_title_metadata_line(line, package.lyrics.title):
                continue
            source_chords = [
                segment.chord
                for segment in chords
                if line.start_ms <= segment.start_ms < line.end_ms and segment.chord != "N"
            ]
            labels_by_mode = _labels_by_mode(source_chords, musical.original_key)
            payload_rows.append(
                {
                    "layout": "line",
                    "start_ms": line.start_ms,
                    "end_ms": line.end_ms,
                    "section": "",
                    "lyrics": line.text,
                    "chords": _selected_labels(
                        row.chord_cells[index], musical.original_key, chord_mode
                    ),
                    "chord_modes": labels_by_mode,
                }
            )

    payload_rows = _apply_melody_bars(package, payload_rows, chord_mode)
    _add_melody_to_rows(package, payload_rows, lyric_beat_times)
    melody = package.melody
    melody_tonic_midi = (
        _numbered_tonic_midi(package, melody.tonic_midi) if melody is not None else None
    )
    return {
        "id": package.config.song_id,
        "title": package.config.title,
        "artist": package.config.artist,
        "duration_ms": package.config.duration_ms,
        "original_key": musical.original_key,
        "numbered_key": chord_reference_key(musical.original_key),
        "bpm": musical.bpm,
        "beats_per_bar": musical.beats_per_bar,
        "capo": capo_for_c_chords(musical.original_key),
        "melody_reference": (
            f"{_numbered_pitch_name(package, melody_tonic_midi)}{melody_tonic_midi // 12 - 1}"
            if melody_tonic_midi is not None
            else None
        ),
        "melody_transpose": _c_to_original_key_transpose(musical.original_key),
        "melody_key": melody_tonic_midi % 12 if melody_tonic_midi is not None else None,
        "melody_tonic_midi": melody_tonic_midi,
        "melody_coverage_end_ms": melody.coverage_end_ms if melody is not None else None,
        "melody_bpm": _melody_bpm(package),
        "melody_review_pending": (
            bool(melody.gaps) or any(note.review != "reviewed" for note in melody.notes)
            if melody is not None
            else False
        ),
        "rows": payload_rows,
    }

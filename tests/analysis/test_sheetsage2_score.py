# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.analysis.sheetsage2_score import (
    build_sheetsage2_melody,
    complete_two_beat_opening,
    normalize_melody_beat_grid,
)
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote


def test_half_length_opening_becomes_two_rests_and_four_eighth_notes() -> None:
    melody = MelodyDocument(
        tonic_midi=60,
        bars=[
            MelodyBar(
                start_ms=510, end_ms=2280,
                beat_times_ms=[510, 952, 1395, 1838],
                start_16th=2, end_16th=18,
            ),
            MelodyBar(
                start_ms=2280, end_ms=5810,
                beat_times_ms=[2280, 3162, 4045, 4928],
                start_16th=18, end_16th=34,
            ),
            MelodyBar(
                start_ms=5810, end_ms=9320,
                beat_times_ms=[5810, 6688, 7565, 8442],
                start_16th=34, end_16th=50,
            ),
        ],
        notes=[
            MelodyNote(
                start_ms=at, end_ms=at + 440, midi=pitch, source="other",
                start_16th=2 + 4 * index, duration_16ths=4,
            )
            for index, (at, pitch) in enumerate(
                zip((510, 950, 1390, 1830), (64, 67, 72, 76), strict=True)
            )
        ],
    )

    corrected = complete_two_beat_opening(melody)

    assert corrected.bars[0].leading_rest_beats == 2
    assert corrected.bars[0].beat_times_ms == [510, 1395]
    assert [(note.start_ms, note.start_16th, note.duration_16ths) for note in corrected.notes] == [
        (510, 10, 2), (950, 12, 2), (1390, 14, 2), (1830, 16, 2)
    ]
    assert [note.midi for note in corrected.notes] == [64, 67, 72, 76]


def test_sheet_sage_downbeats_preserve_mixed_meter_and_sections() -> None:
    events = []
    for step in range(0, 44, 4):
        values = {
            "rhythm": {
                "eighth_position": 0 if step in (0, 16, 24, 40) else 2,
            }
        }
        if step == 0:
            values.update(key="F:major", structure="intro", chord="F:maj")
        if step == 16:
            values["chord"] = "A#:maj7"
        if step == 24:
            values["structure"] = "verse"
        if step == 40:
            values["rhythm"]["meter"] = [1, 4]
        if step in (0, 24):
            values["melody"] = [
                {
                    "pitch": 72,
                    "track": 0 if step == 24 else 1,
                    "duration_steps": 2,
                    "end_time": 0.5 + step / 4 + 0.5,
                }
            ]
        events.append({"global_subbeat": step, "time": 0.5 + step / 4, "values": values})

    melody = build_sheetsage2_melody({"events": events})

    assert [(bar.start_16th, bar.end_16th) for bar in melody.bars] == [
        (0, 16),
        (16, 24),
        (24, 40),
        (40, 44),
    ]
    assert [len(bar.beat_times_ms) for bar in melody.bars] == [4, 2, 4, 1]
    assert [bar.section_label for bar in melody.bars] == [
        "前奏",
        "前奏",
        "主歌",
        "主歌",
    ]
    assert [note.source for note in melody.notes] == ["other", "vocals"]


def test_eighth_note_transition_bar_and_terminal_downbeat() -> None:
    events = []
    for step in (0, 4, 8, 12, 16, 18, 22, 26, 30, 34):
        rhythm = {"eighth_position": 0 if step in (0, 16, 18, 34) else 2}
        if step == 16:
            rhythm["meter"] = [1, 8]
        if step == 18:
            rhythm["meter"] = [4, 4]
        values = {"rhythm": rhythm}
        if step == 0:
            values["key"] = "C:major"
            values["melody"] = [
                {"pitch": 60, "track": 0, "duration_steps": 4, "end_time": 0.4}
            ]
        events.append({"global_subbeat": step, "time": step / 10, "values": values})

    melody = build_sheetsage2_melody({"events": events})

    assert [(bar.start_16th, bar.end_16th) for bar in melody.bars] == [
        (0, 16), (16, 18), (18, 34)
    ]
    assert [len(bar.beat_times_ms) for bar in melody.bars] == [4, 1, 4]


def test_missing_beat_event_is_interpolated_on_score_grid() -> None:
    events = []
    for step in (0, 4, 8, 12, 16, 20, 28, 32):
        values = {"rhythm": {"eighth_position": 0 if step in (0, 16, 32) else 2}}
        if step == 0:
            values["key"] = "C:major"
            values["melody"] = [
                {"pitch": 60, "track": 0, "duration_steps": 4, "end_time": 0.4}
            ]
        events.append({"global_subbeat": step, "time": step / 10, "values": values})

    melody = build_sheetsage2_melody({"events": events})

    assert melody.bars[1].beat_times_ms == [1600, 2000, 2400, 2800]


def test_beat_lights_are_evenly_rebuilt_between_downbeats() -> None:
    times = {
        0: 0.0,
        4: 0.7,
        8: 1.0,
        12: 1.7,
        16: 2.0,
        20: 2.3,
        24: 3.2,
        28: 3.5,
        32: 4.0,
    }
    events = []
    for step, at_seconds in times.items():
        values = {"rhythm": {"eighth_position": 0 if step in (0, 16, 32) else 2}}
        if step == 0:
            values["key"] = "C:major"
            values["melody"] = [
                {"pitch": 60, "track": 0, "duration_steps": 4, "end_time": 0.4}
            ]
        events.append({"global_subbeat": step, "time": at_seconds, "values": values})

    melody = normalize_melody_beat_grid(build_sheetsage2_melody({"events": events}))

    assert melody.bars[0].beat_times_ms == [0, 500, 1000, 1500]
    assert melody.bars[1].beat_times_ms == [2000, 2500, 3000, 3500]


def test_sheet_sage_key_change_keeps_its_original_score_position() -> None:
    events = []
    for step in range(0, 32, 4):
        values = {"rhythm": {"eighth_position": 0 if step in (0, 16) else 2}}
        if step == 0:
            values["key"] = "A:major"
            values["melody"] = [
                {"pitch": 81, "track": 0, "duration_steps": 4, "end_time": 1.0}
            ]
        if step == 16:
            values["key"] = "B:major"
            values["melody"] = [
                {"pitch": 83, "track": 0, "duration_steps": 4, "end_time": 5.0}
            ]
        events.append({"global_subbeat": step, "time": step / 4, "values": values})

    melody = build_sheetsage2_melody({"events": events})

    assert melody.tonic_midi == 69
    assert [
        (change.start_16th, change.at_ms, change.tonic_midi)
        for change in melody.key_changes
    ] == [
        (16, 4000, 71)
    ]
    assert [note.midi for note in melody.notes] == [81, 83]

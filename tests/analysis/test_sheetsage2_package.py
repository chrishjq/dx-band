# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

from dxband.analysis.sheetsage2_package import (
    read_sheetsage2_chords,
    read_sheetsage2_package,
)


def test_chord_reading_does_not_require_score_events(tmp_path: Path) -> None:
    (tmp_path / "chord.lab").write_text("0 1.25 C:maj\n1.25 3 G:maj\n")

    chords = read_sheetsage2_chords(tmp_path, 2500)

    assert [(item.start_ms, item.end_ms, item.chord) for item in chords.segments] == [
        (0, 1250, "C:maj"),
        (1250, 2500, "G:maj"),
    ]


def test_final_partial_bar_ends_at_audio_duration(tmp_path: Path) -> None:
    events = []
    for step in (0, 4, 8, 12, 16, 20):
        values = {"rhythm": {"eighth_position": 0 if step in (0, 16) else 2}}
        if step == 0:
            values["key"] = "C:major"
            values["melody"] = [
                {"pitch": 60, "track": 0, "duration_steps": 4, "end_time": 1.0}
            ]
        events.append({"global_subbeat": step, "time": step / 4, "values": values})
    (tmp_path / "events.json").write_text(json.dumps({"events": events}))
    (tmp_path / "key.lab").write_text("0 5.5 C:major\n")
    (tmp_path / "chord.lab").write_text("0 5.5 C:maj\n")

    analysis = read_sheetsage2_package(tmp_path, 5500)

    assert analysis.melody.coverage_end_ms == 5500
    assert analysis.melody.bars[-1].end_ms == 5500
    assert analysis.melody.bars[-1].review == "needs_review"


def test_normalizing_beat_lights_does_not_relabel_the_detected_bpm(tmp_path: Path) -> None:
    events = []
    for step, seconds in ((0, 0.0), (4, 0.66), (8, 1.0), (12, 1.66), (16, 2.0)):
        values = {"rhythm": {"eighth_position": 0 if step in (0, 8, 16) else 2}}
        if step == 0:
            values["key"] = "C:major"
            values["melody"] = [
                {"pitch": 60, "track": 0, "duration_steps": 4, "end_time": 0.4}
            ]
        events.append({"global_subbeat": step, "time": seconds, "values": values})
    (tmp_path / "events.json").write_text(json.dumps({"events": events}))
    (tmp_path / "key.lab").write_text("0 2 C:major\n")
    (tmp_path / "chord.lab").write_text("0 2 C:maj\n")

    analysis = read_sheetsage2_package(tmp_path, 2000)

    assert analysis.bpm == 91
    assert analysis.beat_times_ms == [0, 500, 1000, 1500]

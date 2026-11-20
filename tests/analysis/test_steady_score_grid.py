# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.analysis.steady_score_grid import regrid_steady_four_beat_score
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote


def test_short_decoded_bar_is_replaced_by_four_steady_beats() -> None:
    bars = []
    now = 0
    step = 0
    for index in range(26):
        beats = 3 if index == 10 else 4
        end = now + beats * 900
        bars.append(
            MelodyBar(
                start_ms=now,
                end_ms=end,
                beat_times_ms=[now + beat * 900 for beat in range(beats)],
                start_16th=step,
                end_16th=step + beats * 4,
            )
        )
        now = end
        step += beats * 4
    note = MelodyNote(
        start_ms=36_225,
        end_ms=36_450,
        midi=72,
        source="piano",
        start_16th=161,
        duration_16ths=1,
    )
    document = MelodyDocument(tonic_midi=60, coverage_end_ms=now, bars=bars, notes=[note])

    fixed, bpm = regrid_steady_four_beat_score(document, now)  # type: ignore[misc]

    assert bpm == 67
    assert len(fixed.bars[10].beat_times_ms) == 4
    assert fixed.bars[10].end_ms == fixed.bars[11].start_ms
    assert fixed.notes[0].start_ms == note.start_ms
    assert fixed.notes[0].midi == note.midi
    assert fixed.notes[0].start_16th == 162
    assert fixed.bars[-1].end_ms == now


def test_short_mixed_meter_score_is_preserved() -> None:
    bars = [
        MelodyBar(
            start_ms=index * 2700,
            end_ms=(index + 1) * 2700,
            beat_times_ms=[index * 2700 + beat * 900 for beat in range(3)],
            start_16th=index * 12,
            end_16th=(index + 1) * 12,
        )
        for index in range(4)
    ]
    document = MelodyDocument(tonic_midi=60, coverage_end_ms=10_800, bars=bars)
    assert regrid_steady_four_beat_score(document, 10_800) is None

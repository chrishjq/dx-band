# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.creation.score_notation import refine_vocal_notation
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote


def test_acoustic_triplet_repairs_three_late_score_attacks_in_short_pickup() -> None:
    words = [
        WordTiming(text=char, start_ms=start, end_ms=end)
        for char, start, end in zip(
            "一二三四", (650, 1330, 1660, 1995), (1330, 1660, 1995, 2400), strict=True
        )
    ]
    lyrics = LyricsDocument(
        schema_version=1,
        title="测试",
        language="yue",
        timing_mode="word",
        lines=[LyricLine(id="line-0001", text="一二三四", start_ms=650, end_ms=2400, words=words)],
    )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=6000,
        bars=[
            MelodyBar(start_ms=0, end_ms=2000, beat_times_ms=[0, 1000], start_16th=0, end_16th=8),
            MelodyBar(
                start_ms=2000,
                end_ms=6000,
                beat_times_ms=[2000, 3000, 4000, 5000],
                start_16th=8,
                end_16th=24,
            ),
        ],
        notes=[
            MelodyNote(
                start_ms=time,
                end_ms=time + 200,
                midi=67,
                source="vocals",
                lyric_line_id="line-0001",
                lyric_character_index=i + 1,
                start_16th=step,
                duration_16ths=1,
            )
            for i, (time, step) in enumerate(((1390, 6), (1850, 7), (2180, 9)))
        ],
    )

    refined = refine_vocal_notation(melody, lyrics)

    assert refined.bars[0].triplet_beats == [1]
    assert [(n.start_16th, n.lyric_character_index) for n in refined.notes] == [
        (4, 0),
        (5, 1),
        (7, 2),
    ]
    assert [n.start_ms for n in refined.notes] == [1390, 1850, 2180]

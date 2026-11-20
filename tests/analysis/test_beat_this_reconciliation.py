# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json

import pytest

from dxband.analysis.beat_this_reconciliation import (
    BeatThisResult,
    reconcile_score_with_beat_this,
)
from dxband.models.melody import MelodyBar, MelodyChord, MelodyDocument, MelodyNote


def test_beat_this_rejects_results_from_another_source(tmp_path) -> None:
    path = tmp_path / "beat_this.json"
    path.write_text(
        json.dumps(
            {
                "source_sha256": "wrong",
                "beats_s": list(range(9)),
                "downbeats_s": [0, 4, 8],
            }
        )
    )
    with pytest.raises(ValueError, match="SHA-256"):
        BeatThisResult.read(path, "expected")


def test_unsupported_short_bar_merges_but_confirmed_two_four_stays() -> None:
    score = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=14000,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=3500,
                beat_times_ms=[0, 875, 1750, 2625],
                start_16th=0,
                end_16th=16,
            ),
            MelodyBar(start_ms=3500, end_ms=4000, beat_times_ms=[3500], start_16th=16, end_16th=18),
            MelodyBar(
                start_ms=4000,
                end_ms=8000,
                beat_times_ms=[4000, 5000, 6000, 7000],
                start_16th=18,
                end_16th=34,
            ),
            MelodyBar(
                start_ms=8000, end_ms=10000, beat_times_ms=[8000, 9000], start_16th=34, end_16th=42
            ),
            MelodyBar(
                start_ms=10000,
                end_ms=14000,
                beat_times_ms=[10000, 11000, 12000, 13000],
                start_16th=42,
                end_16th=58,
            ),
        ],
        notes=[
            MelodyNote(
                start_ms=3500,
                end_ms=4000,
                midi=64,
                source="vocals",
                lyric_line_id="line-1",
                lyric_character_index=0,
                start_16th=16,
                duration_16ths=2,
            ),
        ],
        chords=[MelodyChord(at_ms=3500, chord="C:maj", start_16th=16)],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 14001, 1000)),
        downbeats_ms=(0, 4000, 8000, 10000, 14000),
    )

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert comparison.merged_bars == 1
    assert [(decision.start_ms, decision.decision) for decision in comparison.decisions] == [
        (3500, "beat_this_merge"),
        (8000, "sheet"),
    ]
    assert len(result.bars) == 4
    assert result.bars[0].end_ms == 4000
    assert result.bars[0].end_16th == result.bars[1].start_16th == 16
    assert result.bars[2].end_ms == 10000
    assert result.bars[2].end_16th - result.bars[2].start_16th == 8
    assert (
        result.notes[0].start_ms,
        result.notes[0].midi,
        result.notes[0].lyric_character_index,
    ) == (3500, 64, 0)
    assert (result.notes[0].start_16th, result.notes[0].duration_16ths) == (14, 2)
    assert result.chords[0].start_16th == 14


def test_three_beat_bar_in_four_four_song_is_regridded_without_moving_audio() -> None:
    score = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=8800,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=3000,
                beat_times_ms=[0, 750, 1500, 2250],
                start_16th=0,
                end_16th=16,
            ),
            MelodyBar(
                start_ms=3000,
                end_ms=5800,
                beat_times_ms=[3000, 3933, 4867],
                start_16th=16,
                end_16th=28,
            ),
            MelodyBar(
                start_ms=5800,
                end_ms=8800,
                beat_times_ms=[5800, 6550, 7300, 8050],
                start_16th=28,
                end_16th=44,
            ),
        ],
        notes=[
            MelodyNote(
                start_ms=3933,
                end_ms=4867,
                midi=64,
                source="vocals",
                start_16th=20,
                duration_16ths=4,
            )
        ],
        chords=[MelodyChord(at_ms=5800, chord="G:maj", start_16th=28)],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 9001, 750)),
        downbeats_ms=(0, 2900, 6000, 8800),
    )

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert comparison.regridded_bars == 1
    assert comparison.decisions[0].decision == "meter_regrid"
    assert [(bar.start_ms, bar.end_ms) for bar in result.bars] == [
        (0, 3000),
        (3000, 5800),
        (5800, 8800),
    ]
    assert result.bars[1].end_16th - result.bars[1].start_16th == 16
    assert len(result.bars[1].beat_times_ms) == 4
    assert (result.notes[0].start_ms, result.notes[0].start_16th) == (3933, 21)
    assert result.chords[0].start_16th == 32


def test_three_beat_audio_span_is_not_stretched_to_four_beats() -> None:
    score = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=8250,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=3000,
                beat_times_ms=[0, 750, 1500, 2250],
                start_16th=0,
                end_16th=16,
            ),
            MelodyBar(
                start_ms=3000,
                end_ms=5250,
                beat_times_ms=[3000, 3750, 4500],
                start_16th=16,
                end_16th=28,
            ),
            MelodyBar(
                start_ms=5250,
                end_ms=8250,
                beat_times_ms=[5250, 6000, 6750, 7500],
                start_16th=28,
                end_16th=44,
            ),
        ],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 9000, 750)),
        downbeats_ms=(0, 3000, 6000, 8250),
    )

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert comparison.regridded_bars == 0
    assert comparison.decisions[0].decision == "song_profile_meter"
    assert result.bars[1].review == "candidate"
    assert result.bars[1].end_16th - result.bars[1].start_16th == 12


def test_three_plus_one_phrase_uses_beat_this_downbeats_to_remove_one_beat_bar() -> None:
    score = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=12800,
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=3200,
                beat_times_ms=[0, 800, 1600, 2400],
                start_16th=0,
                end_16th=16,
            ),
            MelodyBar(
                start_ms=3200,
                end_ms=5600,
                beat_times_ms=[3200, 4000, 4800],
                start_16th=16,
                end_16th=28,
            ),
            MelodyBar(
                start_ms=5600,
                end_ms=8800,
                beat_times_ms=[5600, 6400, 7200, 8000],
                start_16th=28,
                end_16th=44,
            ),
            MelodyBar(start_ms=8800, end_ms=9600, beat_times_ms=[8800], start_16th=44, end_16th=48),
            MelodyBar(
                start_ms=9600,
                end_ms=12800,
                beat_times_ms=[9600, 10400, 11200, 12000],
                start_16th=48,
                end_16th=64,
            ),
        ],
        notes=[
            MelodyNote(
                start_ms=8800,
                end_ms=9200,
                midi=64,
                source="vocals",
                start_16th=44,
                duration_16ths=2,
            )
        ],
        chords=[MelodyChord(at_ms=8800, chord="G:maj", start_16th=44)],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 12801, 800)),
        downbeats_ms=(0, 3200, 6400, 9600, 12800),
    )

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert comparison.merged_bars == 1
    assert [row.decision for row in comparison.decisions] == [
        "beat_this_phrase_start",
        "beat_this_phrase_rebar",
    ]
    assert len(result.bars) == 4
    assert [(bar.start_ms, bar.end_ms) for bar in result.bars[1:3]] == [(3200, 6400), (6400, 9600)]
    assert all(bar.end_16th - bar.start_16th == 16 for bar in result.bars)
    assert result.notes[0].start_ms == 8800
    assert result.chords[0].at_ms == 8800


def test_half_or_one_beat_fragment_joins_its_five_four_measure() -> None:
    score = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=27000,
        bars=[
            MelodyBar(
                start_ms=0, end_ms=4000, beat_times_ms=[0, 1000, 2000, 3000],
                start_16th=0, end_16th=16,
            ),
            MelodyBar(
                start_ms=4000, end_ms=8500,
                beat_times_ms=[4000, 5000, 6000, 7000, 8000],
                start_16th=16, end_16th=34, review="needs_review",
            ),
            MelodyBar(
                start_ms=8500, end_ms=9000, beat_times_ms=[8500],
                start_16th=34, end_16th=36, review="needs_review",
            ),
            MelodyBar(
                start_ms=9000, end_ms=13000,
                beat_times_ms=[9000, 10000, 11000, 12000],
                start_16th=36, end_16th=52,
            ),
            MelodyBar(
                start_ms=13000, end_ms=17000,
                beat_times_ms=[13000, 14000, 15000, 16000],
                start_16th=52, end_16th=68,
            ),
            MelodyBar(
                start_ms=17000, end_ms=18000, beat_times_ms=[17000],
                start_16th=68, end_16th=72, review="needs_review",
            ),
            MelodyBar(
                start_ms=18000, end_ms=22000,
                beat_times_ms=[18000, 19000, 20000, 21000],
                start_16th=72, end_16th=88,
            ),
        ],
        notes=[
            MelodyNote(
                start_ms=8500, end_ms=8800, midi=64, source="vocals",
                start_16th=34, duration_16ths=1,
            ),
            MelodyNote(
                start_ms=17000, end_ms=17500, midi=67, source="vocals",
                start_16th=68, duration_16ths=2,
            ),
        ],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 23000, 1000)),
        downbeats_ms=(0, 4000, 9000, 13000, 18000, 22000),
    )

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert [(bar.start_ms, bar.end_ms, bar.end_16th - bar.start_16th)
            for bar in result.bars] == [
        (0, 4000, 16),
        (4000, 9000, 20),
        (9000, 13000, 16),
        (13000, 18000, 20),
        (18000, 22000, 16),
    ]
    assert comparison.merged_bars == 2
    assert [row.decision for row in comparison.decisions] == [
        "extended_meter_merge", "extended_meter_merge",
    ]
    assert [(note.start_ms, note.start_16th, note.midi) for note in result.notes] == [
        (8500, 34, 64), (17000, 68, 67),
    ]


def test_empty_transition_uses_song_tempo_when_beat_tracker_is_double_time() -> None:
    starts = (0, 4000, 8000, 12000, 16000, 17000, 21000, 25000)
    spans = (16, 16, 16, 16, 4, 16, 16)
    step = 0
    bars = []
    for index, span in enumerate(spans):
        start, end = starts[index : index + 2]
        bars.append(MelodyBar(
            start_ms=start, end_ms=end,
            beat_times_ms=[start + round((end - start) * beat / (span // 4))
                           for beat in range(span // 4)],
            start_16th=step, end_16th=step + span,
            section_label="前奏" if index < 4 else "主歌弱起" if index == 4 else "主歌",
            review="needs_review" if index == 4 else "candidate",
        ))
        step += span
    score = MelodyDocument(
        tonic_midi=60, coverage_end_ms=25000, bars=bars,
        chords=[
            MelodyChord(at_ms=15000, chord="G:maj", start_16th=60),
            MelodyChord(at_ms=16000, chord="G:maj", start_16th=64),
            MelodyChord(at_ms=17000, chord="A:min", start_16th=68),
        ],
        notes=[MelodyNote(start_ms=17000, end_ms=17500, midi=69,
                          source="vocals", start_16th=68, duration_16ths=2)],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 25500, 500)),
        downbeats_ms=(0, 4000, 8000, 12000, 16000, 20000, 24000),
    )

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert [(bar.start_ms, bar.end_ms, bar.end_16th - bar.start_16th)
            for bar in result.bars[3:5]] == [(12000, 17000, 20), (17000, 21000, 16)]
    assert any(row.decision == "song_profile_merge" for row in comparison.decisions)
    assert [(note.start_ms, note.start_16th) for note in result.notes] == [(17000, 68)]
    assert [(chord.at_ms, chord.start_16th) for chord in result.chords] == [
        (15000, 60), (16000, 64), (17000, 68),
    ]


def test_double_time_disagreement_does_not_erase_short_bars() -> None:
    beat_counts = [4] * 60
    for index, count in {3: 2, 21: 1, 24: 2, 32: 3, 54: 3}.items():
        beat_counts[index] = count
    bars = []
    now = 0
    step = 8
    for count in beat_counts:
        bars.append(
            MelodyBar(
                start_ms=now,
                end_ms=now + count * 1000,
                beat_times_ms=[now + beat * 1000 for beat in range(count)],
                start_16th=step,
                end_16th=step + count * 4,
            )
        )
        now += count * 1000
        step += count * 4
    score = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=now,
        bars=bars,
        notes=[
            MelodyNote(
                start_ms=85_250,
                end_ms=85_750,
                midi=67,
                source="vocals",
                lyric_line_id="line-1",
                lyric_character_index=2,
                start_16th=349,
                duration_16ths=2,
            )
        ],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, now + 1, 500)),
        downbeats_ms=tuple(range(0, now + 1, 2000)),
    )

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert result.bars == score.bars
    assert comparison.regridded_bars == 0
    assert result.notes[0].start_ms == 85_250
    assert result.notes[0].midi == 67
    assert result.notes[0].lyric_line_id == "line-1"
    assert result.notes[0].lyric_character_index == 2


def test_continuous_local_downbeats_rebar_one_phase_reset() -> None:
    starts = [0, 4000, 8000, 11000, 15100, 19400, 23900, 27900]
    counts = [4, 4, 3, 4, 4, 4, 4]
    bars = []
    step = 0
    for start, end, count in zip(starts[:-1], starts[1:], counts, strict=True):
        bars.append(MelodyBar(
            start_ms=start, end_ms=end,
            beat_times_ms=[start + round((end - start) * beat / count) for beat in range(count)],
            start_16th=step, end_16th=step + 4 * count,
        ))
        step += 4 * count
    score = MelodyDocument(tonic_midi=60, coverage_end_ms=starts[-1], bars=bars)
    rhythm = BeatThisResult(tuple(range(0, 29000, 1000)), tuple(range(0, 29000, 4000)))

    result, comparison = reconcile_score_with_beat_this(score, rhythm)

    assert [bar.start_ms for bar in result.bars] == [0, 4000, 8000, 12000, 16000, 20000, 23900]
    assert all(len(bar.beat_times_ms) == 4 for bar in result.bars)
    assert [row.decision for row in comparison.decisions] == ["local_meter_rebar"]

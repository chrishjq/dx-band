# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Regression cases from the preview-to-production analysis workflow."""

from dxband.analysis.beat_led_score import beat_led_melody
from dxband.analysis.beat_this_reconciliation import BeatThisResult
from dxband.analysis.vocal_track_alignment import align_other_to_vocals
from dxband.creation.asr_lyrics import correct_asr_lyrics
from dxband.models.lyric import LyricLine, LyricsDocument
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote


def test_missing_beat_does_not_create_short_bar() -> None:
    original = MelodyDocument(
        tonic_midi=60, coverage_end_ms=8_000,
        notes=[MelodyNote(start_ms=6_400, end_ms=6_600, midi=60, source="vocals")],
        bars=[MelodyBar(
            start_ms=start, end_ms=start + 2_000,
            beat_times_ms=[start + offset for offset in (0, 500, 1_000, 1_500)],
        ) for start in range(0, 8_000, 2_000)],
    )
    beats = tuple(time for time in range(0, 8_000, 500) if time not in {3_000, 7_000})
    rhythm = BeatThisResult(beats_ms=beats, downbeats_ms=(0, 2_000, 6_000))

    result = beat_led_melody(original, rhythm, 8_000)

    assert [bar.start_ms for bar in result.bars] == [0, 2_000, 4_000, 6_000]
    assert result.bars[1].beat_times_ms == [2_000, 2_500, 3_000, 3_500]
    assert all(bar.end_16th - bar.start_16th == 16 for bar in result.bars)


def test_half_pulse_keeps_sixteen_sixteenths_in_one_four_beat_bar() -> None:
    original = MelodyDocument(
        tonic_midi=60, coverage_end_ms=8_000,
        notes=[MelodyNote(
            start_ms=step * 250, end_ms=(step + 1) * 250,
            midi=60 + step % 5, source="other",
            start_16th=step, duration_16ths=1,
        ) for step in range(32)],
        bars=[MelodyBar(
            start_ms=start, end_ms=start + 4_000,
            beat_times_ms=[start + offset for offset in (0, 1_000, 2_000, 3_000)],
            start_16th=index * 16, end_16th=(index + 1) * 16,
        ) for index, start in enumerate((0, 4_000))],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 8_000, 500)),
        downbeats_ms=tuple(range(0, 8_000, 2_000)),
    )

    result = beat_led_melody(original, rhythm, 8_000)

    assert [bar.start_ms for bar in result.bars] == [0, 4_000]
    assert result.bars[0].beat_times_ms == [0, 1_000, 2_000, 3_000]
    assert [(note.start_16th, note.duration_16ths) for note in result.notes[:16]] == [
        (step, 1) for step in range(16)
    ]


def test_missing_three_subbeats_does_not_reverse_or_skip_intro_notes() -> None:
    original = MelodyDocument(
        tonic_midi=60, coverage_end_ms=12_000,
        notes=[MelodyNote(start_ms=step * 250, end_ms=(step + 1) * 250,
                          midi=60, source="other", start_16th=step,
                          duration_16ths=1) for step in range(48)],
        bars=[MelodyBar(start_ms=start, end_ms=start + 4_000,
                        beat_times_ms=[start + offset for offset in (0, 1_000, 2_000, 3_000)])
              for start in (0, 4_000, 8_000)],
    )
    beats = tuple(time for time in range(0, 12_000, 500)
                  if time not in {6_500, 7_000, 7_500})
    rhythm = BeatThisResult(beats_ms=beats,
                            downbeats_ms=tuple(range(0, 12_000, 2_000)))

    result = beat_led_melody(original, rhythm, 12_000)

    assert [bar.start_ms for bar in result.bars] == [0, 4_000, 8_000]
    assert [note.start_16th for note in result.notes[:16]] == list(range(16))


def test_supported_one_beat_transition_resets_later_bar_phase() -> None:
    starts_and_beats = ((0, 4), (4_000, 1), (5_000, 4), (9_000, 4))
    original = MelodyDocument(
        tonic_midi=60, coverage_end_ms=13_000,
        notes=[MelodyNote(start_ms=4_960 if step == 20 else step * 250,
                          end_ms=5_210 if step == 20 else (step + 1) * 250,
                          midi=60, source="other", start_16th=step,
                          duration_16ths=1) for step in range(52)],
        bars=[MelodyBar(start_ms=start, end_ms=start + beats * 1_000,
                        beat_times_ms=[start + beat * 1_000 for beat in range(beats)])
              for start, beats in starts_and_beats],
    )
    rhythm = BeatThisResult(
        beats_ms=tuple(range(0, 13_000, 500)),
        downbeats_ms=(0, 2_000, 4_000, 5_000, 7_000, 9_000, 11_000),
    )

    result = beat_led_melody(original, rhythm, 13_000)

    assert [bar.start_ms for bar in result.bars] == [0, 4_000, 5_000, 9_000]
    assert [len(bar.beat_times_ms) for bar in result.bars] == [4, 1, 4, 4]
    assert result.bars[2].start_16th == 20
    assert result.notes[20].start_16th == 20


def test_asr_times_survive_supplied_lyric_correction() -> None:
    reference = LyricsDocument(
        schema_version=1, title="测试", language="yue", timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=500, text="如果"),
            LyricLine(id="line-0002", start_ms=500, end_ms=1_000, text="人来"),
        ],
    )
    tokens = [
        {"token": text, "start_s": start}
        for text, start in (("如", 2.0), ("果", 2.2), ("人", 5.0), ("來", 5.2))
    ]

    result = correct_asr_lyrics(reference, tokens, 8_000)

    assert [line.text for line in result.lines] == ["如果", "人来"]
    assert [[word.start_ms for word in line.words] for line in result.lines] == [
        [2_000, 2_200], [5_000, 5_200],
    ]


def test_accompaniment_inside_vocal_gap_stays_inside_corrected_gap() -> None:
    starts = (0, 200, 400, 3_000, 3_200, 3_400)
    pitches = (60, 62, 64, 60, 62, 64)

    def notes(offset: int) -> list[MelodyNote]:
        return [MelodyNote(start_ms=start + offset, end_ms=start + offset + 100,
                           midi=pitch, source="vocals")
                for start, pitch in zip(starts, pitches, strict=True)]

    other = [MelodyNote(start_ms=1_500, end_ms=1_750, midi=48, source="other")]
    shifted = align_other_to_vocals(notes(0), other, notes(100), notes(300),
                                    [0, 2_000, 4_000])

    assert shifted[0].start_ms == 1_800
    assert shifted[0].end_ms == 2_050

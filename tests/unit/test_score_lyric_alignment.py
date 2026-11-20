# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.creation.score_lyric_alignment import align_lyrics_to_score
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
from dxband.models.melody import MelodyBar, MelodyDocument, MelodyNote


def test_repeated_phrase_uses_score_rhythm_when_acoustic_alignment_drifting() -> None:
    phrase = "一起长大的约定"
    score_offsets = [0, 2, 4, 6, 8, 14, 16]
    notes: list[MelodyNote] = []
    lines: list[LyricLine] = []
    for index, base in enumerate((0, 10_000, 20_000)):
        for step in sorted([*score_offsets, *([7] if index == 2 else [])]):
            notes.append(
                MelodyNote(
                    start_ms=base + step * 250,
                    end_ms=base + step * 250 + 200,
                    midi=60,
                    source="vocals",
                    start_16th=base // 250 + step,
                    duration_16ths=2,
                )
            )
        acoustic_offsets = score_offsets if index < 2 else [0, 2, 4, 6, 7, 8, 14]
        words = [
            WordTiming(
                text=character,
                start_ms=base + step * 250,
                end_ms=base + step * 250 + 200,
            )
            for character, step in zip(phrase, acoustic_offsets, strict=True)
        ]
        lines.append(
            LyricLine(
                id=f"line-{index + 1:04d}",
                start_ms=words[0].start_ms,
                end_ms=words[-1].end_ms,
                text=phrase,
                words=words,
            )
        )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=28_000,
        notes=notes,
        bars=[
            MelodyBar(
                start_ms=index * 4_000,
                end_ms=(index + 1) * 4_000,
                beat_times_ms=[index * 4_000 + beat * 1_000 for beat in range(4)],
                start_16th=index * 16,
                end_16th=(index + 1) * 16,
            )
            for index in range(7)
        ],
    )
    lyrics = LyricsDocument(
        schema_version=1, title="测试", language="zh", timing_mode="word", lines=lines
    )

    aligned_lyrics, aligned_melody = align_lyrics_to_score(lyrics, melody)

    assert [word.start_ms for word in aligned_lyrics.lines[2].words] == [
        20_000,
        20_500,
        21_000,
        21_500,
        22_000,
        23_500,
        24_000,
    ]
    assert [
        note.start_16th for note in aligned_melody.notes if note.lyric_line_id == "line-0003"
    ] == [80, 82, 84, 86, 88, 94, 96]
    assert (
        next(note for note in aligned_melody.notes if note.start_16th == 87).lyric_line_id is None
    )


def test_english_ctc_letters_are_linked_as_display_words() -> None:
    text = "Hello world"
    letter_starts = [0, 100, 200, 300, 400, 1_000, 1_100, 1_200, 1_300, 1_400]
    line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=1_500,
        text=text,
        words=[
            WordTiming(text=letter, start_ms=start, end_ms=start + 100)
            for letter, start in zip(text.replace(" ", ""), letter_starts, strict=True)
        ],
    )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=4_000,
        notes=[
            MelodyNote(
                start_ms=start,
                end_ms=start + 500,
                midi=60,
                source="vocals",
                start_16th=start // 250,
                duration_16ths=2,
            )
            for start in (0, 1_000)
        ],
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=4_000,
                beat_times_ms=[0, 1_000, 2_000, 3_000],
                start_16th=0,
                end_16th=16,
            )
        ],
    )
    lyrics = LyricsDocument(
        schema_version=1, title="Test", language="en", timing_mode="word", lines=[line]
    )

    aligned_lyrics, aligned_melody = align_lyrics_to_score(lyrics, melody)

    assert [word.text for word in aligned_lyrics.lines[0].words] == ["Hello", "world"]
    assert [note.lyric_character_index for note in aligned_melody.notes] == [0, 6]


def test_missing_score_note_keeps_acoustic_word_without_inventing_pitch() -> None:
    line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=2_500,
        text="一二三",
        words=[
            WordTiming(text=character, start_ms=start, end_ms=start + 500)
            for character, start in zip("一二三", (0, 1_000, 2_000), strict=True)
        ],
    )
    lyrics = LyricsDocument(
        schema_version=1, title="测试", language="zh", timing_mode="word", lines=[line]
    )
    melody = MelodyDocument(
        tonic_midi=60,
        coverage_end_ms=4_000,
        notes=[
            MelodyNote(
                start_ms=start,
                end_ms=start + 500,
                midi=60,
                source="vocals",
                start_16th=start // 250,
                duration_16ths=2,
            )
            for start in (0, 2_000)
        ],
        bars=[
            MelodyBar(
                start_ms=0,
                end_ms=4_000,
                beat_times_ms=[0, 1_000, 2_000, 3_000],
                start_16th=0,
                end_16th=16,
            )
        ],
    )

    aligned_lyrics, aligned_melody = align_lyrics_to_score(lyrics, melody)

    assert [word.start_ms for word in aligned_lyrics.lines[0].words] == [0, 1_000, 2_000]
    assert [note.lyric_character_index for note in aligned_melody.notes] == [0, 2]


def test_ctc_peak_between_score_onsets_still_links_syllable() -> None:
    line = LyricLine(
        id="line-0001", start_ms=0, end_ms=1_100, text="一二",
        words=[
            WordTiming(text="一", start_ms=0, end_ms=500),
            WordTiming(text="二", start_ms=730, end_ms=1_100),
        ],
    )
    melody = MelodyDocument(
        tonic_midi=60, coverage_end_ms=2_000,
        notes=[
            MelodyNote(start_ms=0, end_ms=400, midi=60, source="vocals"),
            MelodyNote(start_ms=500, end_ms=900, midi=62, source="vocals"),
        ],
        bars=[MelodyBar(start_ms=0, end_ms=2_000, beat_times_ms=[0, 500, 1_000, 1_500])],
    )
    lyrics = LyricsDocument(
        schema_version=1, title="测试", language="zh", timing_mode="word", lines=[line]
    )

    _, linked = align_lyrics_to_score(lyrics, melody)

    assert [note.lyric_character_index for note in linked.notes] == [0, 1]

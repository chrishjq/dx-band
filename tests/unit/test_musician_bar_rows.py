# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.lyrics.musician_bar_rows import build_musician_bar_rows, complete_beat_grid
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming


def _character_timings(
    text: str,
    starts: tuple[int, ...],
    duration_ms: int = 180,
) -> list[WordTiming]:
    characters = [character for character in text if not character.isspace()]
    return [
        WordTiming(text=character, start_ms=start, end_ms=start + duration_ms)
        for character, start in zip(characters, starts, strict=True)
    ]


def test_complete_beat_grid_extends_quiet_outro() -> None:
    beats, downbeats = complete_beat_grid(
        (0, 1_000, 2_000, 3_000, 4_000),
        (0, 4_000),
        4,
        8_500,
    )

    assert beats == tuple(range(0, 8_000 + 1, 1_000))
    assert downbeats == (0, 4_000, 8_000)


def test_english_words_are_never_split_across_beat_cells() -> None:
    text = "The snow glows white"
    document = LyricsDocument(
        schema_version=1,
        title="English song",
        language="en",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=900,
                end_ms=6_500,
                text=text,
                words=_character_timings(
                    text,
                    (
                        900, 1_100, 1_300,
                        1_800, 2_100, 2_400, 2_700,
                        3_200, 3_400, 3_700, 4_100, 4_300,
                        5_000, 5_250, 5_500, 5_750, 6_000,
                    ),
                ),
            )
        ],
    )

    row = build_musician_bar_rows(
        document,
        tuple(range(0, 8_000, 1_000)),
        (0, 4_000),
        4,
        None,
    )[0]

    assert row.lyric_cells == ("The", "snow", "", "glows", "", "white", "", "")
    assert row.lyric_sources[0] == tuple(("line-0001", index) for index in range(4))
    assert row.lyric_sources[1] == tuple(("line-0001", index) for index in range(4, 9))


def test_english_chord_alignment_moves_a_whole_word() -> None:
    text = "say hello now"
    document = LyricsDocument(
        schema_version=1,
        title="English song",
        language="en-US",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=2_000,
                end_ms=5_500,
                text=text,
                words=_character_timings(
                    text,
                    (
                        2_000, 2_200, 2_400,
                        3_000, 3_200, 3_400, 3_600, 4_000,
                        4_500, 4_700, 4_900,
                    ),
                ),
            )
        ],
    )
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=3_750, end_ms=5_500, chord="G:maj")]
    )

    row = build_musician_bar_rows(
        document,
        tuple(range(0, 8_000, 1_000)),
        (0, 4_000),
        4,
        chords,
    )[0]

    assert row.chord_cells[4] == ("G:maj",)
    assert row.lyric_cells[2:6] == ("say", "", "hello", "now")
    fragments = {"h", "he", "hel", "hell", "ello", "llo", "lo", "o"}
    assert all(cell not in fragments for cell in row.lyric_cells)


def test_musician_rows_keep_two_bars_with_lyrics_and_chords_on_the_same_beats() -> None:
    text = "甲乙丙丁戊己庚辛壬癸"
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1_000,
                end_ms=11_000,
                text=text,
                words=[
                    WordTiming(
                        text=character,
                        start_ms=(index + 1) * 1_000,
                        end_ms=(index + 1) * 1_000 + 100,
                    )
                    for index, character in enumerate(text)
                ],
            )
        ],
    )
    chords = ChordTimeline(
        segments=[
            ChordSegment(start_ms=1_000, end_ms=5_000, chord="C:maj"),
            ChordSegment(start_ms=5_000, end_ms=11_000, chord="G:maj"),
        ]
    )

    rows = build_musician_bar_rows(
        document,
        tuple(range(1_000, 13_000, 1_000)),
        (1_000, 5_000, 9_000),
        4,
        chords,
    )

    assert len(rows) == 2
    assert rows[0].beat_times_ms == tuple(range(1_000, 9_000, 1_000))
    assert rows[0].lyric_cells == tuple(text[:8])
    assert rows[0].chord_cells[0] == ("C:maj",)
    assert rows[0].chord_cells[4] == ("G:maj",)
    assert rows[1].lyric_cells[:2] == tuple(text[8:])
    assert rows[1].chord_cells[0] == ()


def test_musician_rows_can_group_four_bars_on_wide_screens() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=16_000, text="宽屏歌词")],
    )

    rows = build_musician_bar_rows(
        document,
        tuple(range(0, 16_000, 1_000)),
        (0, 4_000, 8_000, 12_000),
        4,
        None,
        bars_per_row=4,
    )

    assert len(rows) == 1
    assert rows[0].beat_times_ms == tuple(range(0, 16_000, 1_000))
    assert len(rows[0].lyric_cells) == 16


def test_sustained_chord_is_not_repeated_at_next_two_bar_row() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=16_000, text="长句歌词")],
    )
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=7_000, end_ms=10_000, chord="G:maj")]
    )

    rows = build_musician_bar_rows(
        document,
        tuple(range(0, 16_000, 1_000)),
        (0, 4_000, 8_000, 12_000),
        4,
        chords,
    )

    assert rows[0].chord_cells[7] == ("G:maj",)
    assert rows[1].chord_cells[0] == ()


def test_musician_rows_show_instrumental_bars_and_require_a_downbeat_grid() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=9_000, end_ms=11_000, text="开唱")],
    )
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=0, end_ms=11_000, chord="C:maj")]
    )
    beats = tuple(range(1_000, 13_000, 1_000))
    rows = build_musician_bar_rows(document, beats, (1_000, 5_000, 9_000), 4, chords)

    assert rows[0].section_label == "前奏"
    assert rows[0].lyric_cells == ("",) * 8
    assert rows[1].section_label == ""
    assert "".join(rows[1].lyric_cells) == "开唱"
    assert build_musician_bar_rows(document, beats, (), 4, chords) == ()


def test_chord_on_a_sustained_syllable_splits_lyric_group_at_that_syllable() -> None:
    text = "甲乙丙丁戊己庚辛"
    starts = (1_000, 1_500, 2_200, 2_700, 3_200, 3_700, 4_200, 4_700)
    ends = (1_500, 2_200, 2_700, 3_200, 3_700, 4_200, 4_700, 5_200)
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1_000,
                end_ms=5_200,
                text=text,
                words=[
                    WordTiming(text=character, start_ms=start, end_ms=end)
                    for character, start, end in zip(text, starts, ends, strict=True)
                ],
            )
        ],
    )
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=3_900, end_ms=5_200, chord="G:maj")]
    )

    rows = build_musician_bar_rows(
        document,
        tuple(range(1_000, 9_000, 1_000)),
        (1_000, 5_000),
        4,
        chords,
    )

    assert rows[0].beat_times_ms[3] == 4_000
    assert rows[0].chord_cells[3] == ("G:maj",)
    assert rows[0].lyric_cells[:5] == ("甲乙", "丙丁", "戊", "己", "庚辛")
    assert "".join(rows[0].lyric_cells) == text


def test_lyric_groups_can_follow_chords_across_a_bar_line() -> None:
    text = "这一刹我只需要"
    starts = (3_000, 3_400, 3_600, 4_200, 4_700, 5_200, 5_700)
    ends = (3_400, 3_600, 4_200, 4_700, 5_200, 5_700, 6_300)
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=3_000,
                end_ms=6_300,
                text=text,
                words=[
                    WordTiming(text=character, start_ms=start, end_ms=end)
                    for character, start, end in zip(text, starts, ends, strict=True)
                ],
            )
        ],
    )
    chords = ChordTimeline(
        segments=[
            ChordSegment(start_ms=3_900, end_ms=5_600, chord="D:min"),
            ChordSegment(start_ms=5_600, end_ms=7_000, chord="Bb:maj"),
        ]
    )

    row = build_musician_bar_rows(
        document,
        tuple(range(0, 8_000, 1_000)),
        (0, 4_000),
        4,
        chords,
    )[0]

    assert row.chord_cells[4] == ("D:min",)
    assert row.chord_cells[6] == ("Bb:maj",)
    assert row.lyric_cells[3:7] == ("这一", "刹", "我只", "需要")
    assert row.lyric_sources[4] == (
        ("line-0001", 2),
    )


def test_chord_alignment_keeps_previous_character_out_of_chord_cell() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="后来",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=2_500,
                end_ms=5_200,
                text="消失在人海",
                words=[
                    WordTiming(text="消", start_ms=2_500, end_ms=3_200),
                    WordTiming(text="失", start_ms=3_200, end_ms=3_600),
                    WordTiming(text="在", start_ms=3_600, end_ms=4_200),
                    WordTiming(text="人", start_ms=4_200, end_ms=4_500),
                    WordTiming(text="海", start_ms=4_500, end_ms=5_200),
                ],
            )
        ],
    )
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=3_900, end_ms=6_000, chord="G:min")]
    )

    row = build_musician_bar_rows(
        document,
        tuple(range(0, 8_000, 1_000)),
        (0, 4_000),
        4,
        chords,
    )[0]

    assert row.chord_cells[4] == ("G:min",)
    assert row.lyric_cells[2:6] == ("消", "失", "在", "人海")
    assert row.lyric_sources[3] == (("line-0001", 1),)
    assert row.lyric_sources[4] == (("line-0001", 2),)


def test_chord_alignment_splits_phrase_at_exact_character_across_row_boundary() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=7_100,
                end_ms=8_400,
                text="可惜你",
                words=[
                    WordTiming(text="可", start_ms=7_100, end_ms=7_500),
                    WordTiming(text="惜", start_ms=7_500, end_ms=7_900),
                    WordTiming(text="你", start_ms=7_900, end_ms=8_400),
                ],
            )
        ],
    )
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=7_990, end_ms=10_000, chord="C:min")]
    )

    rows = build_musician_bar_rows(
        document,
        tuple(range(0, 16_000, 1_000)),
        (0, 4_000, 8_000, 12_000),
        4,
        chords,
    )

    assert rows[0].lyric_cells[7] == "可惜"
    assert rows[1].chord_cells[0] == ("C:min",)
    assert rows[1].lyric_cells[0] == "你"


def test_manual_lyric_on_previous_beat_is_not_moved_with_next_line() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=3_000,
                end_ms=3_100,
                text="手填",
            ),
            LyricLine(
                id="line-0002",
                start_ms=3_100,
                end_ms=5_000,
                text="下一句",
                words=[
                    WordTiming(text="下", start_ms=3_100, end_ms=4_200),
                    WordTiming(text="一", start_ms=4_200, end_ms=4_500),
                    WordTiming(text="句", start_ms=4_500, end_ms=4_900),
                ],
            ),
        ],
    )
    chords = ChordTimeline(
        segments=[ChordSegment(start_ms=3_700, end_ms=6_000, chord="G:maj")]
    )

    row = build_musician_bar_rows(
        document,
        tuple(range(0, 8_000, 1_000)),
        (0, 4_000),
        4,
        chords,
    )[0]

    assert row.lyric_cells[3] == "手填"
    assert row.lyric_cells[4] == "下"
    assert row.lyric_sources[3] == (("line-0001", 0), ("line-0001", 1))

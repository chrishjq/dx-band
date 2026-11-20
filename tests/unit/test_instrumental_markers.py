# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dxband.lyrics.instrumental_markers import with_instrumental_markers
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming


def test_title_card_and_word_timed_gap_become_independent_markers() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="棋子",
        language="zh",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001", start_ms=0, end_ms=20_000, text="棋子 - 王菲"
            ),
            LyricLine(
                id="line-0002",
                start_ms=20_000,
                end_ms=30_000,
                text="第一句",
                words=[
                    WordTiming(text="第", start_ms=20_000, end_ms=20_500),
                    WordTiming(text="一", start_ms=20_500, end_ms=21_000),
                    WordTiming(text="句", start_ms=21_000, end_ms=22_000),
                ],
            ),
            LyricLine(
                id="line-0003",
                start_ms=30_000,
                end_ms=35_000,
                text="第二句",
                words=[
                    WordTiming(text="第", start_ms=30_000, end_ms=30_500),
                    WordTiming(text="二", start_ms=30_500, end_ms=31_000),
                    WordTiming(text="句", start_ms=31_000, end_ms=32_000),
                ],
            ),
        ],
    )

    displayed = with_instrumental_markers(document)

    assert [line.text for line in displayed.lines] == [
        "（前奏）", "第一句", "（间奏）", "第二句"
    ]
    assert [(line.start_ms, line.end_ms) for line in displayed.lines] == [
        (0, 20_000), (20_000, 22_000), (22_000, 30_000), (30_000, 35_000)
    ]
    assert displayed.lines[1].words == document.lines[1].words
    assert with_instrumental_markers(displayed) == displayed
    assert document.lines[0].text == "棋子 - 王菲"


def test_intro_before_first_timed_word_moves_display_line_start() -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=4_000,
                text="唱",
                words=[WordTiming(text="唱", start_ms=2_000, end_ms=3_000)],
            )
        ],
    )

    displayed = with_instrumental_markers(document)

    assert [(line.text, line.start_ms, line.end_ms) for line in displayed.lines] == [
        ("（前奏）", 0, 2_000),
        ("唱", 2_000, 4_000),
    ]
    assert displayed.timing_mode == "line"

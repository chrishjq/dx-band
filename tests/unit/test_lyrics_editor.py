# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import pytest

from dxband.lyrics.editor_commands import LyricsEditError, LyricsEditor
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming


def _document() -> LyricsDocument:
    return LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1_000,
                end_ms=2_000,
                text="第一句",
                words=[WordTiming(text="第一句", start_ms=1_000, end_ms=2_000)],
            ),
            LyricLine(
                id="line-0002",
                start_ms=3_000,
                end_ms=4_000,
                text="第二句",
                words=[WordTiming(text="第二句", start_ms=3_000, end_ms=4_000)],
            ),
            LyricLine(
                id="line-0003",
                start_ms=5_000,
                end_ms=6_000,
                text="第三句",
                words=[WordTiming(text="第三句", start_ms=5_000, end_ms=6_000)],
            ),
        ],
    )


def _character_document() -> LyricsDocument:
    return LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1_000,
                end_ms=1_800,
                text="我爱你",
                words=[
                    WordTiming(text="我", start_ms=1_000, end_ms=1_100),
                    WordTiming(text="爱", start_ms=1_200, end_ms=1_300),
                    WordTiming(text="你", start_ms=1_400, end_ms=1_500),
                ],
            ),
            LyricLine(
                id="line-0002",
                start_ms=2_000,
                end_ms=2_600,
                text="春天",
                words=[
                    WordTiming(text="春", start_ms=2_000, end_ms=2_200),
                    WordTiming(text="天", start_ms=2_200, end_ms=2_400),
                ],
            ),
        ],
    )


def test_replace_text_keeps_unchanged_characters_and_other_lines() -> None:
    original = _character_document()

    edited = LyricsEditor(duration_ms=3_000).replace_text(original, 0, "我想你")

    assert edited.timing_mode == "word"
    assert [(word.text, word.start_ms, word.end_ms) for word in edited.lines[0].words] == [
        ("我", 1_000, 1_100),
        ("想", 1_200, 1_300),
        ("你", 1_400, 1_500),
    ]
    assert edited.lines[1].words == original.lines[1].words


def test_replace_text_divides_changed_span_when_character_count_changes() -> None:
    edited = LyricsEditor(duration_ms=3_000).replace_text(_character_document(), 0, "我喜欢你")

    assert edited.timing_mode == "word"
    assert [(word.text, word.start_ms, word.end_ms) for word in edited.lines[0].words] == [
        ("我", 1_000, 1_100),
        ("喜", 1_200, 1_250),
        ("欢", 1_250, 1_300),
        ("你", 1_400, 1_500),
    ]


def test_insert_and_delete_characters_use_local_time_only() -> None:
    editor = LyricsEditor(duration_ms=3_000)
    inserted = editor.replace_text(_character_document(), 0, "我爱上你")
    deleted = editor.replace_text(_character_document(), 0, "我你")

    assert [(word.text, word.start_ms, word.end_ms) for word in inserted.lines[0].words] == [
        ("我", 1_000, 1_100),
        ("爱", 1_200, 1_300),
        ("上", 1_300, 1_400),
        ("你", 1_400, 1_500),
    ]
    assert [(word.text, word.start_ms, word.end_ms) for word in deleted.lines[0].words] == [
        ("我", 1_000, 1_100),
        ("你", 1_400, 1_500),
    ]


def test_insert_without_time_gap_borrows_only_neighboring_character() -> None:
    original = _character_document()
    line = original.lines[0].model_copy(
        update={
            "words": [
                WordTiming(text="我", start_ms=1_000, end_ms=1_100),
                WordTiming(text="爱", start_ms=1_100, end_ms=1_200),
                WordTiming(text="你", start_ms=1_200, end_ms=1_300),
            ]
        }
    )
    document = original.model_copy(update={"lines": [line, original.lines[1]]})

    edited = LyricsEditor(duration_ms=3_000).replace_text(document, 0, "我爱上你")

    assert [(word.text, word.start_ms, word.end_ms) for word in edited.lines[0].words] == [
        ("我", 1_000, 1_100),
        ("爱", 1_100, 1_150),
        ("上", 1_150, 1_200),
        ("你", 1_200, 1_300),
    ]


def test_split_line_keeps_word_times_on_unaffected_lines() -> None:
    edited = LyricsEditor(duration_ms=3_000).split_line(_character_document(), 0)

    assert edited.timing_mode == "line"
    assert edited.lines[0].words == []
    assert edited.lines[1].words == []
    assert edited.lines[2].words == _character_document().lines[1].words


def test_offset_from_row_only_shifts_selected_line_and_following_lines() -> None:
    document = _document()

    shifted = LyricsEditor(duration_ms=10_000).apply_offset_from_row(document, 1, 750)

    assert [(line.start_ms, line.end_ms) for line in shifted.lines] == [
        (1_000, 2_000),
        (3_750, 4_750),
        (5_750, 6_750),
    ]
    assert shifted.lines[0].words[0].start_ms == 1_000
    assert shifted.lines[1].words[0].start_ms == 3_750
    assert shifted.lines[2].words[0].end_ms == 6_750


def test_offset_from_row_rejects_overlap_with_unchanged_previous_line() -> None:
    with pytest.raises(LyricsEditError, match="与上一句重叠"):
        LyricsEditor(duration_ms=10_000).apply_offset_from_row(_document(), 1, -1_500)


def test_offset_from_row_rejects_lyrics_past_song_duration() -> None:
    with pytest.raises(LyricsEditError, match="超出歌曲范围"):
        LyricsEditor(duration_ms=6_500).apply_offset_from_row(_document(), 1, 750)

# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import replace

from PySide6.QtWidgets import QFrame, QLabel
from pytestqt.qtbot import QtBot

from dxband.lyrics.instrumental_markers import with_instrumental_markers
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
from dxband.ui.dialogs.chord_edit_dialog import ChordEditDialog


def lyrics() -> LyricsDocument:
    return LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1000,
                end_ms=5000,
                text="第一句歌词",
            )
        ],
    )


def test_chord_editor_can_edit_in_each_mode_without_duplicating_timeline(
    qtbot: QtBot,
) -> None:
    dialog = ChordEditDialog(
        timeline=ChordTimeline(segments=[ChordSegment(start_ms=1000, end_ms=2000, chord="G:maj")]),
        document=lyrics(),
        title="测试歌曲",
        original_key="D",
        duration_ms=10_000,
        initial_mode="degree",
    )
    qtbot.addWidget(dialog)

    assert dialog.mode_combo.itemText(0) == "级数谱"
    assert dialog.chord_edits[0].text() == "4"
    dialog.chord_edits[0].setText("5")
    dialog.chord_edits[0].editingFinished.emit()
    assert dialog.timeline.segments[0].chord == "A:maj"

    dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData("chord"))
    assert dialog.chord_edits[0].text() == "A"
    dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData("chord_c"))
    assert dialog.chord_edits[0].text() == "G"
    assert len(dialog.timeline.segments) == 1


def test_chord_reanalysis_only_replaces_the_pending_editor_timeline(qtbot: QtBot) -> None:
    original = ChordTimeline(segments=[ChordSegment(start_ms=1000, end_ms=2000, chord="G:maj")])
    recognized = ChordTimeline(segments=[ChordSegment(start_ms=1200, end_ms=2400, chord="A:min")])
    dialog = ChordEditDialog(original, lyrics(), "测试歌曲", "D", 10_000)
    qtbot.addWidget(dialog)

    dialog.apply_reanalysis(recognized)

    assert dialog.timeline == recognized
    assert "尚未保存" in dialog.status_label.text()


def test_chord_editor_uses_absolute_mode_when_original_key_is_missing(qtbot: QtBot) -> None:
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=1000, end_ms=2000, chord="G:maj")]),
        lyrics(),
        "测试歌曲",
        "",
        10_000,
        initial_mode="degree",
    )
    qtbot.addWidget(dialog)

    assert dialog.current_mode() == "chord"
    assert dialog.chord_edits[0].text() == "G"


def test_chords_are_positioned_above_lyrics_without_time_columns(qtbot: QtBot) -> None:
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=3000, end_ms=4000, chord="G:maj")]),
        lyrics(),
        "测试歌曲",
        "D",
        10_000,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    row = dialog.lyric_rows[0]
    assert "".join(label.text() for label in row.character_labels) == "第一句歌词"
    assert len(row.editors) == len("第一句歌词")
    assert all(editor.font().pointSize() >= 16 for _char, _segment, editor in row.editors)
    assert all(label.font().pointSize() >= 20 for label in row.character_labels)
    assert not hasattr(dialog, "table")


def test_more_chords_than_lyric_characters_adds_blank_cells(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=8000, text="已经足够")],
    )
    timeline = ChordTimeline(
        segments=[
            ChordSegment(start_ms=index * 1000, end_ms=(index + 1) * 1000, chord="D:maj")
            for index in range(8)
        ]
    )

    dialog = ChordEditDialog(timeline, document, "测试歌曲", "D", 8000)
    qtbot.addWidget(dialog)

    row = dialog.lyric_rows[0]
    assert len(row.editors) == 8
    assert len(dialog.chord_edits) == 8
    displayed_lyrics = "".join(
        label.text().replace("\u00a0", "") for label in row.character_labels
    )
    assert displayed_lyrics == "已经足够"
    assert sum(label.text() == "\u00a0" for label in row.character_labels) == 4
    assert "未显示" not in dialog.status_label.text()


def test_chord_in_short_gap_is_shown_as_interlude(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=1500,
                text="前句",
                words=[
                    WordTiming(text="前", start_ms=0, end_ms=500),
                    WordTiming(text="句", start_ms=500, end_ms=1000),
                ],
            ),
            LyricLine(
                id="line-0002",
                start_ms=2000,
                end_ms=3000,
                text="后句",
                words=[
                    WordTiming(text="后", start_ms=2000, end_ms=2500),
                    WordTiming(text="句", start_ms=2500, end_ms=3000),
                ],
            ),
        ],
    )
    timeline = ChordTimeline(
        segments=[ChordSegment(start_ms=1400, end_ms=1900, chord="D:maj")]
    )

    dialog = ChordEditDialog(timeline, document, "测试歌曲", "D", 3000)
    qtbot.addWidget(dialog)

    assert len(dialog.instrumental_rows) == 1
    assert len(dialog.chord_edits) == 1
    assert "未显示" not in dialog.status_label.text()


def test_inputs_with_chords_use_highlight_property(qtbot: QtBot) -> None:
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=1000, end_ms=2000, chord="D:maj")]),
        lyrics(),
        "测试歌曲",
        "D",
        10_000,
    )
    qtbot.addWidget(dialog)
    filled = dialog.lyric_rows[0].editors[0][2]
    empty = dialog.lyric_rows[0].editors[1][2]

    assert filled.property("hasChord") is True
    assert empty.property("hasChord") is False

    empty.setText("4")
    assert empty.property("hasChord") is True
    empty.clear()
    assert empty.property("hasChord") is False


def test_empty_character_input_can_add_a_chord(qtbot: QtBot) -> None:
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=1000, end_ms=1500, chord="D:maj")]),
        lyrics(),
        "测试歌曲",
        "D",
        10_000,
    )
    qtbot.addWidget(dialog)
    empty_editor = dialog.lyric_rows[0].editors[1][2]

    empty_editor.setText("4")
    empty_editor.editingFinished.emit()

    assert [segment.chord for segment in dialog.timeline.segments] == ["D:maj", "G:maj"]
    assert dialog.lyric_rows[0].editors[1][2].text() == "4"


def test_added_chord_stays_in_selected_input_without_word_timing(qtbot: QtBot) -> None:
    dialog = ChordEditDialog(
        ChordTimeline(),
        lyrics(),
        "测试歌曲",
        "D",
        10_000,
    )
    qtbot.addWidget(dialog)
    selected_index = 3
    selected_editor = dialog.lyric_rows[0].editors[selected_index][2]

    selected_editor.setText("4")
    selected_editor.editingFinished.emit()

    assert dialog.lyric_rows[0].editors[selected_index][2].text() == "4"
    assert all(
        not editor.text()
        for index, _segment, editor in dialog.lyric_rows[0].editors
        if index != selected_index
    )


def test_lyric_rows_are_left_aligned_and_keep_natural_control_height(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id=f"line-{index + 1:04d}",
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                text="长短不一的歌词" if index % 2 else "短句",
            )
            for index in range(12)
        ],
    )
    dialog = ChordEditDialog(ChordTimeline(), document, "测试歌曲", "D", 12_000)
    qtbot.addWidget(dialog)
    dialog.resize(900, 520)
    dialog.show()
    qtbot.wait(20)

    assert {row.character_cells[0].x() for row in dialog.lyric_rows} == {12}
    assert all(row.height() == 96 for row in dialog.lyric_rows)
    assert all(row.editors[0][2].height() == 38 for row in dialog.lyric_rows)
    assert dialog.lyrics_scroll.verticalScrollBar().maximum() > 0


def test_word_timing_maps_chord_to_original_character_index_with_spaces(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=3000,
                text="我 爱你",
                words=[
                    WordTiming(text="我", start_ms=1000, end_ms=1200),
                    WordTiming(text="爱", start_ms=1500, end_ms=1700),
                    WordTiming(text="你", start_ms=1800, end_ms=2000),
                ],
            )
        ],
    )
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=1500, end_ms=1800, chord="G:maj")]),
        document,
        "测试歌曲",
        "D",
        3000,
    )
    qtbot.addWidget(dialog)

    assert dialog.lyric_rows[0].editors[2][2].text() == "4"
    assert all(not editor.text() for _index, _segment, editor in dialog.lyric_rows[0].editors[:2])


def test_intro_chords_are_shown_separately_from_word_timed_lyrics(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=5000,
                text="测试",
                words=[
                    WordTiming(text="测", start_ms=2000, end_ms=2200),
                    WordTiming(text="试", start_ms=2400, end_ms=2600),
                ],
            )
        ],
    )
    dialog = ChordEditDialog(
        ChordTimeline(
            segments=[
                ChordSegment(start_ms=500, end_ms=1000, chord="D:maj"),
                ChordSegment(start_ms=2100, end_ms=2500, chord="G:maj"),
            ]
        ),
        document,
        "测试歌曲",
        "D",
        5000,
    )
    qtbot.addWidget(dialog)

    assert len(dialog.chord_edits) == 2
    assert len(dialog.instrumental_rows) == 1
    assert len(dialog.instrumental_rows[0].editors) == 8
    assert dialog.instrumental_rows[0].editors[0][1].text() == "1"
    assert all(not editor.text() for _segment, editor in dialog.instrumental_rows[0].editors[1:])
    assert dialog.lyric_rows[0].editors[0][2].text() == "4"


def test_interlude_chords_have_own_editable_rows(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1000,
                end_ms=3000,
                text="前句",
                words=[
                    WordTiming(text="前", start_ms=1000, end_ms=1300),
                    WordTiming(text="句", start_ms=1500, end_ms=1800),
                ],
            ),
            LyricLine(
                id="line-0002",
                start_ms=12_000,
                end_ms=14_000,
                text="后句",
                words=[
                    WordTiming(text="后", start_ms=12_000, end_ms=12_300),
                    WordTiming(text="句", start_ms=12_500, end_ms=12_800),
                ],
            ),
        ],
    )
    chords = ChordTimeline(
        segments=[
            ChordSegment(start_ms=1000, end_ms=1700, chord="D:maj"),
            *[
                ChordSegment(start_ms=start, end_ms=start + 800, chord="G:maj")
                for start in (3000, 4500, 6000, 7500, 9000)
            ],
            ChordSegment(start_ms=12_000, end_ms=12_700, chord="A:maj"),
        ]
    )
    dialog = ChordEditDialog(chords, document, "测试歌曲", "D", 14_000)
    qtbot.addWidget(dialog)

    assert [
        row.findChild(QLabel, "instrumentalChordHeading").text() for row in dialog.instrumental_rows
    ] == ["（间奏）", "（间奏·续）"]
    assert len(dialog.chord_edits) == 7
    assert len(dialog.instrumental_rows[0].editors) == 8
    assert len(dialog.instrumental_rows[1].editors) == 8
    assert sum(bool(editor.text()) for _segment, editor in dialog.instrumental_rows[0].editors) == 4
    assert sum(bool(editor.text()) for _segment, editor in dialog.instrumental_rows[1].editors) == 1
    assert dialog.instrumental_rows[0].editors[0][1].text() == "4"
    dialog.instrumental_rows[0].editors[0][1].setText("5")
    dialog.instrumental_rows[0].editors[0][1].editingFinished.emit()
    assert dialog.timeline.segments[1].chord == "A:maj"
    assert len(dialog.chord_edits) == 7


def test_empty_instrumental_slot_can_add_a_chord(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=4_000,
                text="测试",
                words=[
                    WordTiming(text="测", start_ms=2_000, end_ms=2_300),
                    WordTiming(text="试", start_ms=2_500, end_ms=2_800),
                ],
            )
        ],
    )
    dialog = ChordEditDialog(ChordTimeline(), document, "测试歌曲", "D", 4_000)
    qtbot.addWidget(dialog)

    assert len(dialog.instrumental_rows) == 1
    row = dialog.instrumental_rows[0]
    assert len(row.editors) == 8
    assert all(segment_index is None for segment_index, _editor in row.editors)

    editor = row.editors[3][1]
    editor.setText("4")
    editor.editingFinished.emit()

    assert len(dialog.timeline.segments) == 1
    assert dialog.timeline.segments[0].start_ms == 750
    assert dialog.timeline.segments[0].chord == "G:maj"
    assert any(
        segment_index == 0 and current.text() == "4"
        for segment_index, current in dialog.instrumental_rows[0].editors
    )


def test_persisted_marker_is_not_rendered_as_fake_lyric_cells(qtbot: QtBot) -> None:
    document = with_instrumental_markers(
        LyricsDocument(
            schema_version=1,
            title="测试歌曲",
            language="zh-CN",
            timing_mode="line",
            lines=[
                LyricLine(id="line-0001", start_ms=5_000, end_ms=7_000, text="第一句"),
                LyricLine(id="line-0002", start_ms=12_000, end_ms=14_000, text="第二句"),
            ],
        )
    )
    chords = ChordTimeline(
        segments=[
            ChordSegment(start_ms=1_000, end_ms=2_000, chord="D:maj"),
            ChordSegment(start_ms=8_000, end_ms=9_000, chord="G:maj"),
        ]
    )
    dialog = ChordEditDialog(chords, document, "测试歌曲", "D", 14_000)
    qtbot.addWidget(dialog)

    assert [row.line.text for row in dialog.lyric_rows] == ["第一句", "第二句"]
    assert [
        row.findChild(QLabel, "instrumentalChordHeading").text() for row in dialog.instrumental_rows
    ] == ["（前奏）", "（间奏）"]
    assert len(dialog.chord_edits) == 2


def test_intro_chords_are_not_placed_over_lrc_title_card(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="只是太爱你",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=18_000,
                text="只是太爱你 - 张敬轩",
            )
        ],
    )
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=1000, end_ms=3000, chord="D:maj")]),
        document,
        "只是太爱你",
        "D",
        18_000,
    )
    qtbot.addWidget(dialog)

    assert not dialog.chord_edits
    assert "1 个和弦未显示" in dialog.status_label.text()


def test_beat_editor_has_four_bars_and_editable_chord_and_lyric_per_beat(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=1_000, end_ms=4_000, text="第一句歌词")],
    )
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=1_000, end_ms=4_000, chord="D:maj")]),
        document,
        "测试歌曲",
        "D",
        4_000,
        beat_times_ms=tuple(range(0, 4_000, 500)),
        downbeat_times_ms=(0, 2_000),
        beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    assert len(dialog.beat_rows) == 1
    row = dialog.beat_rows[0]
    assert len(row.chord_editors) == len(row.lyric_editors) == 16
    assert len(row.measures) == 4
    assert len(row.findChildren(QFrame, "chordBeatMeasureSeparator")) == 3
    assert row.findChild(QLabel, "chordBeatRowHeading").text() == "第 1–4 小节"
    assert row.chord_editors[2].text() == "1"
    lyric_index = next(index for index, editor in enumerate(row.lyric_editors) if editor.text())
    old_text = row.lyric_editors[lyric_index].text()
    row.lyric_editors[lyric_index].setText("新" + old_text[1:])
    row.lyric_editors[lyric_index].editingFinished.emit()
    assert "新" in dialog.document.lines[0].text
    assert dialog.beat_rows[0].lyric_editors[lyric_index].text().startswith("新")

    dialog.beat_rows[0].chord_editors[4].setText("4")
    dialog.beat_rows[0].chord_editors[4].editingFinished.emit()
    assert [(segment.start_ms, segment.chord) for segment in dialog.timeline.segments] == [
        (1_000, "D:maj"),
        (2_000, "G:maj"),
    ]


def test_chord_search_prefers_visible_lyric_cell_when_source_index_is_stale(
    qtbot: QtBot,
) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=1_500,
                text="明带",
                words=[
                    WordTiming(text="明", start_ms=0, end_ms=500),
                    WordTiming(text="带", start_ms=1_000, end_ms=1_500),
                ],
            )
        ],
    )
    dialog = ChordEditDialog(
        ChordTimeline(),
        document,
        document.title,
        "C",
        4_000,
        beat_times_ms=tuple(range(0, 4_000, 500)),
        downbeat_times_ms=(0, 2_000),
        beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    controls = dialog.beat_rows[0]
    bright_index = next(
        index for index, editor in enumerate(controls.lyric_editors) if editor.text() == "明"
    )
    target_index = next(
        index for index, editor in enumerate(controls.lyric_editors) if editor.text() == "带"
    )
    sources = list(dialog._beat_rows[0].lyric_sources)
    sources[target_index] = (("line-0001", 0),)
    dialog._beat_rows = (
        replace(dialog._beat_rows[0], lyric_sources=tuple(sources)),
    )

    dialog.lyric_search_edit.setText("带")

    assert dialog._lyric_search_highlight is controls.lyric_editors[target_index]
    assert not controls.lyric_editors[bright_index].property("searchMatch")
    assert controls.lyric_editors[target_index].height() >= 34
    assert dialog.lyrics_layout.contentsMargins().bottom() == 24


def test_beat_lyric_edit_preserves_unaffected_word_timing(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="word",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1_000,
                end_ms=3_000,
                text="甲乙丙丁",
                words=[
                    WordTiming(text=char, start_ms=1_000 + index * 500, end_ms=1_300 + index * 500)
                    for index, char in enumerate("甲乙丙丁")
                ],
            )
        ],
    )
    dialog = ChordEditDialog(
        ChordTimeline(), document, "测试歌曲", "C", 4_000,
        beat_times_ms=tuple(range(0, 4_000, 500)),
        downbeat_times_ms=(0, 2_000), beats_per_bar=4,
    )
    qtbot.addWidget(dialog)
    editor = next(editor for editor in dialog.beat_rows[0].lyric_editors if editor.text() == "乙")
    editor.setText("新")
    editor.editingFinished.emit()

    assert dialog.document.lines[0].text == "甲新丙丁"
    assert [(word.start_ms, word.end_ms) for word in dialog.document.lines[0].words] == [
        (word.start_ms, word.end_ms) for word in document.lines[0].words
    ]


def test_beat_editor_places_chord_on_exact_syllable_without_previous_character(
    qtbot: QtBot,
) -> None:
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
    dialog = ChordEditDialog(
        ChordTimeline(
            segments=[ChordSegment(start_ms=3_900, end_ms=6_000, chord="G:min")]
        ),
        document,
        "后来",
        "D#",
        8_000,
        beat_times_ms=tuple(range(0, 8_000, 1_000)),
        downbeat_times_ms=(0, 4_000),
        beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    row = dialog.beat_rows[0]
    assert row.lyric_editors[3].text() == "失"
    assert row.chord_editors[4].text() == "3m"
    assert row.lyric_editors[4].text() == "在"


def test_typing_existing_lyric_into_adjacent_empty_beat_moves_its_timing(
    qtbot: QtBot,
) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="后来",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=12_307, text="（前奏）"),
            LyricLine(
                id="line-0002",
                start_ms=12_307,
                end_ms=14_078,
                text="后来",
                words=[
                    WordTiming(text="后", start_ms=12_307, end_ms=13_067),
                    WordTiming(text="来", start_ms=13_067, end_ms=14_078),
                ],
            ),
        ],
    )
    dialog = ChordEditDialog(
        ChordTimeline(
            segments=[
                ChordSegment(start_ms=11_820, end_ms=13_400, chord="Bb:maj"),
                ChordSegment(start_ms=13_400, end_ms=15_040, chord="Eb:maj"),
            ]
        ),
        document,
        "后来",
        "D#",
        15_040,
        beat_times_ms=(
            620,
            1_420,
            2_240,
            3_040,
            3_820,
            4_640,
            5_420,
            6_220,
            7_040,
            7_820,
            8_640,
            9_420,
            10_220,
            11_040,
            11_840,
            12_620,
            13_440,
            14_240,
        ),
        downbeat_times_ms=(620, 3_820, 7_040, 10_220, 13_440),
        beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    assert dialog.beat_rows[0].lyric_editors[14].text() == "后"
    target = dialog.beat_rows[0].lyric_editors[15]
    assert target.text() == ""
    target.setText("后")
    target.editingFinished.emit()

    line = dialog.document.lines[1]
    assert line.text == "后来"
    assert (line.words[0].start_ms, line.words[0].end_ms) == (12_620, 13_067)
    assert dialog.beat_rows[0].lyric_editors[14].text() == ""
    assert dialog.beat_rows[0].lyric_editors[15].text() == "后"
    assert "第 4 拍" in dialog.status_label.text()


def test_existing_phrase_can_move_into_intro_and_shorten_marker(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="用背脊唱情歌",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=15_002, text="（前奏）"),
            LyricLine(
                id="line-0002",
                start_ms=15_002,
                end_ms=16_743,
                text="麻烦 各位都不望我",
                words=[
                    WordTiming(text=character, start_ms=start, end_ms=end)
                    for character, start, end in (
                        ("麻", 15_002, 15_057),
                        ("烦", 15_057, 15_113),
                        ("各", 15_113, 15_169),
                        ("位", 15_169, 15_224),
                        ("都", 15_224, 15_280),
                        ("不", 15_280, 15_336),
                        ("望", 15_336, 15_392),
                        ("我", 15_392, 16_743),
                    )
                ],
            ),
        ],
    )
    beat_times = (
        380, 1_200, 2_020, 2_800, 3_580, 4_360, 5_140, 5_920,
        6_720, 7_500, 8_280, 9_060, 9_840, 10_660, 11_460, 12_260,
        13_040, 13_860, 14_620, 15_380, 16_180, 16_960, 17_760, 18_560,
    )
    dialog = ChordEditDialog(
        ChordTimeline(
            segments=[
                ChordSegment(start_ms=13_070, end_ms=14_680, chord="C#:maj"),
                ChordSegment(start_ms=14_680, end_ms=15_090, chord="F#:maj"),
                ChordSegment(start_ms=15_090, end_ms=16_180, chord="F:7"),
                ChordSegment(start_ms=16_180, end_ms=19_380, chord="Bb:min"),
            ]
        ),
        document,
        "用背脊唱情歌",
        "C#",
        19_380,
        beat_times_ms=beat_times,
        downbeat_times_ms=(380, 3_580, 6_720, 9_840, 13_040, 16_180),
        beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    target = dialog.beat_rows[1].lyric_editors[0]
    assert target.text() == ""
    target.setText("麻烦")
    target.editingFinished.emit()

    assert dialog.document.lines[0].text == "（前奏）"
    assert dialog.document.lines[0].end_ms == 13_040
    lyric = dialog.document.lines[1]
    assert lyric.text == "麻烦 各位都不望我"
    assert lyric.start_ms == 13_040
    assert [(word.start_ms, word.end_ms) for word in lyric.words[:2]] == [
        (13_040, 13_450),
        (13_450, 13_860),
    ]
    assert dialog.beat_rows[1].lyric_editors[0].text() == "麻烦"
    assert "第 1 拍" in dialog.status_label.text()

    third_beat = dialog.beat_rows[1].lyric_editors[2]
    third_beat.setText("各位都")
    third_beat.editingFinished.emit()
    fourth_beat = dialog.beat_rows[1].lyric_editors[3]
    fourth_beat.setText("不望")
    fourth_beat.editingFinished.emit()

    assert dialog.document.lines[1].text == "麻烦 各位都不望我"
    assert [editor.text() for editor in dialog.beat_rows[1].lyric_editors[:5]] == [
        "麻烦", "", "各位都", "不望", "我",
    ]


def test_cut_then_paste_phrase_rebuilds_timing_without_losing_lyrics(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="用背脊唱情歌",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=12_308, end_ms=14_620, text="（前奏）"),
            LyricLine(
                id="line-0002", start_ms=14_620, end_ms=17_000,
                text="麻烦各位都不望我",
                words=[
                    WordTiming(
                        text=char,
                        start_ms=(
                            14_620 + i * 100 if i < 2
                            else 16_180 if i == 7
                            else 15_380 + (i - 2) * 100
                        ),
                        end_ms=(
                            14_720 + i * 100 if i < 2
                            else 16_280 if i == 7
                            else 15_480 + (i - 2) * 100
                        ),
                    )
                    for i, char in enumerate("麻烦各位都不望我")
                ],
            ),
        ],
    )
    beats = (
        380, 1_200, 2_020, 2_800, 3_580, 4_360, 5_140, 5_920,
        6_720, 7_500, 8_280, 9_060, 9_840, 10_660, 11_460, 12_260,
        13_040, 13_860, 14_620, 15_380, 16_180, 16_960, 17_760, 18_560,
    )
    dialog = ChordEditDialog(
        ChordTimeline(), document, document.title, "C#", 19_380,
        beat_times_ms=beats,
        downbeat_times_ms=(380, 3_580, 6_720, 9_840, 13_040, 16_180),
        beats_per_bar=4,
    )
    qtbot.addWidget(dialog)
    source = next(
        editor for editor in dialog.beat_rows[1].lyric_editors
        if editor.text() == "麻烦"
    )
    source.setText("")
    source.editingFinished.emit()
    assert source.text() == ""
    assert dialog.document == document

    target = dialog.beat_rows[1].lyric_editors[0]
    target.setText("麻烦")
    target.editingFinished.emit()
    assert dialog.beat_rows[1].lyric_editors[0].text() == "麻烦"
    assert dialog.document.lines[1].text == "麻烦各位都不望我"
    assert dialog.document.lines[1].words[0].start_ms == 13_040

    source = dialog.beat_rows[1].lyric_editors[3]
    assert source.text() == "各位都不望"
    source.setText("不望")
    source.editingFinished.emit()
    assert source.text() == "不望"
    assert dialog.document.lines[1].text == "麻烦各位都不望我"

    target = dialog.beat_rows[1].lyric_editors[2]
    target.setText("各位都")
    target.editingFinished.emit()
    assert [editor.text() for editor in dialog.beat_rows[1].lyric_editors[:5]] == [
        "麻烦", "", "各位都", "不望", "我",
    ]
    assert dialog.document.lines[1].text == "麻烦各位都不望我"


def test_typing_in_beat_editor_suspends_playback_scroll_follow(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=8_000, text="测试歌词")],
    )
    dialog = ChordEditDialog(
        ChordTimeline(), document, "测试歌曲", "C", 8_000,
        beat_times_ms=tuple(range(0, 8_000, 500)),
        downbeat_times_ms=(0, 2_000, 4_000, 6_000), beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    editor = dialog.beat_rows[0].lyric_editors[0]
    editor.textEdited.emit("测")
    assert not dialog._position_follow_enabled

    dialog.set_position_ms(4_500)
    assert dialog._active_measure_index == 2
    assert not dialog._position_follow_enabled

    dialog.resume_position_follow()
    assert dialog._position_follow_enabled


def test_three_four_beat_editor_uses_twelve_cells_per_four_bar_row(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=3_000, text="六拍歌词")],
    )
    dialog = ChordEditDialog(
        ChordTimeline(), document, "测试歌曲", "C", 3_000,
        beat_times_ms=tuple(range(0, 3_000, 500)),
        downbeat_times_ms=(0, 1_500), beats_per_bar=3,
    )
    qtbot.addWidget(dialog)
    assert len(dialog.beat_rows) == 1
    assert len(dialog.beat_rows[0].chord_editors) == 12
    assert len(dialog.beat_rows[0].lyric_editors) == 12


def test_empty_beat_in_gap_can_add_a_new_lyric_line(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=1_000, end_ms=3_000, text="原句")],
    )
    dialog = ChordEditDialog(
        ChordTimeline(), document, "测试歌曲", "C", 4_000,
        beat_times_ms=tuple(range(0, 4_000, 500)),
        downbeat_times_ms=(0, 2_000), beats_per_bar=4,
    )
    qtbot.addWidget(dialog)
    editor = dialog.beat_rows[0].lyric_editors[0]
    editor.setText("新增")
    editor.editingFinished.emit()

    assert [(line.start_ms, line.end_ms, line.text) for line in dialog.document.lines] == [
        (0, 500, "新增"),
        (1_000, 3_000, "原句"),
    ]
    assert dialog.beat_rows[0].lyric_editors[0].text() == "新增"


def test_offbeat_chord_uses_nearest_beat_input(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=4_000, text="逐拍输入和弦")],
    )
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=1_620, end_ms=4_000, chord="G:maj")]),
        document, "测试歌曲", "C", 4_000,
        beat_times_ms=tuple(range(0, 4_000, 500)),
        downbeat_times_ms=(0, 2_000), beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    assert [editor.text() for editor in dialog.beat_rows[0].chord_editors] == [
        "", "", "", "5", "5", "", "", "",
        "", "", "", "", "", "", "", "",
    ]


def test_editing_carried_chord_starts_a_change_on_that_bar(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=8_000, text="逐拍和弦编辑测试")],
    )
    dialog = ChordEditDialog(
        ChordTimeline(segments=[ChordSegment(start_ms=0, end_ms=8_000, chord="C:maj")]),
        document, "测试歌曲", "C", 8_000,
        beat_times_ms=tuple(range(0, 8_000, 500)),
        downbeat_times_ms=(0, 2_000, 4_000, 6_000), beats_per_bar=4,
    )
    qtbot.addWidget(dialog)

    carried = dialog.beat_rows[0].chord_editors[8]
    assert carried.text() == "1"
    carried.editingFinished.emit()
    assert len(dialog.timeline.segments) == 1
    carried.setText("4")
    carried.editingFinished.emit()
    segments = [
        (segment.start_ms, segment.end_ms, segment.chord)
        for segment in dialog.timeline.segments
    ]
    assert segments == [
        (0, 4_000, "C:maj"),
        (4_000, 8_000, "F:maj"),
    ]

# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from itertools import pairwise

from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from dxband.lyrics.instrumental_markers import with_instrumental_markers
from dxband.lyrics.musician_bar_rows import MusicianBarRow
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
from dxband.ui.render.musician_widget import MusicianWidget


def test_current_lyric_is_in_upper_middle_of_ten_rows(qtbot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="word",
        lines=[
            LyricLine(
                id=f"line-{index + 1:04d}",
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                text=f"第{index + 1}句",
                words=[WordTiming(text="第", start_ms=index * 1000, end_ms=index * 1000 + 100)],
            )
            for index in range(15)
        ],
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)
    widget.set_chords(
        ChordTimeline(segments=[ChordSegment(start_ms=2200, end_ms=3100, chord="G:maj")])
    )
    widget.set_music_info("D", 120, title="测试", artist="歌手")
    widget.set_position_ms(2500)
    assert len(widget.visible_lines()) == 10
    assert widget.visible_lines()[widget.current_row] == document.lines[2]
    assert widget.chords_for_line(document.lines[2])[0].chord == "G:maj"
    widget.set_font_size(40)
    assert widget.font_size == 40
    widget.set_chord_mode("chord")
    assert widget.chord_mode == "chord"
    widget.set_chord_mode("chord_c")
    assert widget.chord_label("G:maj") == "F"
    assert widget.chord_color(True).name() == "#ffd34e"
    assert widget.chord_color(False).name() == "#8fe1c8"
    widget.show()
    QApplication.processEvents()
    assert not widget.grab().isNull()


def test_guide_countdown_paints_blue_number_and_extinguishing_beat_dots(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 500)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="再见二丁目",
            language="zh",
            timing_mode="line",
            lines=[
                LyricLine(id="line-0001", start_ms=0, end_ms=5_000, text="（前奏）"),
                LyricLine(id="line-0002", start_ms=5_000, end_ms=7_000, text="第一句"),
            ],
        )
    )
    widget.set_music_info("C", 120, beats_per_bar=4, title="再见二丁目")
    widget.set_guide_countdown(8, 8)
    widget.show()
    QApplication.processEvents()

    ratio = widget.devicePixelRatioF()
    row_height = round((widget.height() - 58 - 60) / widget.row_count * ratio) / ratio
    panel = widget._guide_panel_rect(58, row_height)
    marker_index = next(
        index
        for index, line in enumerate(widget._document_lines)
        if line.id in widget._marker_line_ids and "前奏" in line.text
    )
    marker_top = widget._document_layer_offset(58, row_height) + marker_index * row_height
    assert panel.center().x() == widget.width() / 2
    assert panel.bottom() < marker_top
    first_dot_x = round(panel.center().x() - 114)
    dot_y = round(panel.top() + panel.height() * 0.73)

    def dot_color(x: int) -> QColor:
        pixmap = widget.grab()
        pixel_ratio = pixmap.devicePixelRatio()
        return QColor(pixmap.toImage().pixel(round(x * pixel_ratio), round(dot_y * pixel_ratio)))

    assert widget.guide_countdown == (8, 8)
    assert dot_color(first_dot_x).name() == "#69c8ff"
    widget.set_guide_countdown(7, 8)
    QApplication.processEvents()
    assert dot_color(first_dot_x).name() == "#0b1a2b"
    assert dot_color(first_dot_x + 30).name() == "#69c8ff"
    widget.set_guide_countdown(0, 0)
    QApplication.processEvents()
    assert dot_color(first_dot_x).name() == "#000000"


def test_lyrics_scroll_continuously_between_line_starts(qtbot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=900, text="第一句", words=[]),
            LyricLine(id="line-0002", start_ms=1000, end_ms=1900, text="第二句", words=[]),
            LyricLine(id="line-0003", start_ms=2000, end_ms=2900, text="第三句", words=[]),
        ],
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)

    widget.set_position_ms(250)
    assert widget.scroll_progress() == 0.25
    assert widget.document_scroll_position() == 0.25
    assert widget.visible_lines()[widget.current_row] == document.lines[0]
    widget.set_position_ms(750)
    assert widget.scroll_progress() == 0.75
    assert widget.document_scroll_position() == 0.75
    widget.set_position_ms(1000)
    assert widget.scroll_progress() == 0.0
    assert widget.document_scroll_position() == 1.0
    assert widget.visible_lines()[widget.current_row - 1] == document.lines[0]
    assert widget.visible_lines()[widget.current_row] == document.lines[1]


def test_musician_scroll_ignores_small_clock_backsteps_but_allows_seek(qtbot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=900, text="第一句", words=[]),
            LyricLine(id="line-0002", start_ms=1000, end_ms=1900, text="第二句", words=[]),
        ],
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)

    widget.set_position_ms(600)
    assert widget.document_scroll_position() == 0.6
    widget.set_position_ms(585)
    assert widget.document_scroll_position() == 0.6

    widget.set_position_ms(400)
    assert widget.document_scroll_position() == 0.4


def test_musician_moves_one_prerendered_document_layer_while_scrolling(qtbot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[
            LyricLine(
                id=f"line-{index + 1:04d}",
                start_ms=index * 1000,
                end_ms=(index + 1) * 1000,
                text=f"第{index + 1}句",
                words=[],
            )
            for index in range(12)
        ],
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(1280, 720)
    widget.set_document(document)
    widget.set_position_ms(2500)
    widget.show()
    QApplication.processEvents()
    assert not widget.grab().isNull()

    document_tiles = widget._document_tiles
    assert document_tiles
    assert widget._frame_buffers is not None
    first_buffers = widget._frame_buffers
    pixel_ratio = widget.devicePixelRatioF()
    raw_row_height = (
        widget.height() - max(60, round(widget.height() * 0.1)) - 58
    ) / widget.row_count
    row_height = max(1, round(raw_row_height * pixel_ratio)) / pixel_ratio
    first_offset = widget._document_layer_offset(58, row_height)
    first_positions = [first_offset + index * row_height for index in range(3)]

    widget.set_position_ms(2600)
    QApplication.processEvents()
    second_offset = widget._document_layer_offset(58, row_height)
    second_positions = [second_offset + index * row_height for index in range(3)]

    assert widget._document_tiles is document_tiles
    assert widget._frame_buffers is first_buffers
    assert first_positions[1] - first_positions[0] == row_height
    assert first_positions[2] - first_positions[1] == row_height
    assert {
        round(after - before, 6)
        for before, after in zip(first_positions, second_positions, strict=True)
    } == {round(second_offset - first_offset, 6)}


def test_font_control_scales_lyrics_and_chords_without_changing_header(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(1280, 720)
    row_height = (widget.height() - max(60, round(widget.height() * 0.1)) - 58) / 10

    widget.set_font_size(24)
    small_lyric, small_chord = widget.content_font_sizes(row_height)
    header_size = widget._info_font().pointSize()
    widget.set_font_size(40)
    large_lyric, large_chord = widget.content_font_sizes(row_height)

    assert large_lyric > small_lyric
    assert large_chord > small_chord
    assert widget._info_font().pointSize() == header_size


def test_musician_font_size_has_no_maximum_layout_limit(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)

    widget.set_font_size(999)

    assert widget.font_size == 999


def test_chord_to_lyric_gap_uses_font_metrics_instead_of_window_height(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    lyric_metrics = QFontMetrics(QFont(widget.lyrics_style.font_family, 32))
    chord_metrics = QFontMetrics(QFont(widget.lyrics_style.font_family, 20))

    lyric_baseline, chord_baseline = widget._vocal_line_baselines(
        0, 110, lyric_metrics, chord_metrics
    )
    tall_lyric_baseline, tall_chord_baseline = widget._vocal_line_baselines(
        0, 180, lyric_metrics, chord_metrics
    )
    gap = (
        lyric_baseline
        + lyric_metrics.tightBoundingRect("歌词").top()
        - (chord_baseline + chord_metrics.tightBoundingRect("4maj7").bottom())
    )
    tall_gap = (
        tall_lyric_baseline
        + lyric_metrics.tightBoundingRect("歌词").top()
        - (tall_chord_baseline + chord_metrics.tightBoundingRect("4maj7").bottom())
    )

    assert 3 <= gap <= 6
    assert round(tall_gap, 6) == round(gap, 6)


def test_only_chord_quality_seven_is_superscripted() -> None:
    assert MusicianWidget._chord_superscript_indices("57") == frozenset({1})
    assert MusicianWidget._chord_superscript_indices("2m7") == frozenset({2})
    assert MusicianWidget._chord_superscript_indices("F#m7") == frozenset({3})
    assert MusicianWidget._chord_superscript_indices("7") == frozenset()
    assert MusicianWidget._chord_superscript_indices("3m/7") == frozenset()


def test_musician_uses_original_text_index_when_lyrics_contain_spaces() -> None:
    line = LyricLine(
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

    assert MusicianWidget._character_index(line, 1500) == 2


def test_musician_hides_chords_outside_timed_singing_interval(qtbot) -> None:
    line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=5000,
        text="测试",
        words=[
            WordTiming(text="测", start_ms=2000, end_ms=2200),
            WordTiming(text="试", start_ms=2400, end_ms=2600),
        ],
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_chords(
        ChordTimeline(
            segments=[
                ChordSegment(start_ms=500, end_ms=1000, chord="D:maj"),
                ChordSegment(start_ms=2100, end_ms=2500, chord="G:maj"),
            ]
        )
    )

    assert [segment.chord for segment in widget.chords_for_line(line)] == ["G:maj"]


def test_musician_hides_intro_chords_on_lrc_title_card(qtbot) -> None:
    line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=18_000,
        text="只是太爱你 - 张敬轩",
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_music_info("D", 120, title="只是太爱你")
    widget.set_chords(
        ChordTimeline(segments=[ChordSegment(start_ms=1000, end_ms=3000, chord="D:maj")])
    )

    assert widget.chords_for_line(line) == ()


def test_updating_chords_invalidates_prerendered_lyrics_and_active_row(qtbot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[LyricLine(id="line-0001", start_ms=0, end_ms=3000, text="测试歌词")],
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 480)
    widget.set_document(document)
    widget.set_chords(
        ChordTimeline(segments=[ChordSegment(start_ms=500, end_ms=1500, chord="D:maj")])
    )
    widget._prepare_document_layer(40, 24, 16)
    assert widget._document_tiles
    assert widget._document_layer_signature is not None
    widget._active_row_pixmap(document.lines[0], 40, 24, 16)
    assert widget._active_row_pixmaps

    updated = ChordTimeline(segments=[ChordSegment(start_ms=1500, end_ms=2500, chord="G:maj")])
    widget.set_chords(updated)

    assert widget.chords is updated
    assert widget._document_tiles == ()
    assert widget._active_row_pixmaps == {}
    assert widget._document_layer_signature is None
    widget._prepare_document_layer(40, 24, 16)
    assert widget._document_tiles


def test_adjacent_chords_are_all_drawn_instead_of_hiding_later_chord(qtbot, monkeypatch) -> None:
    line = LyricLine(
        id="line-0034",
        start_ms=202_620,
        end_ms=211_180,
        text="我也可畅游异国再找寄托",
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(760, 480)
    widget.set_music_info("F", 71, title="再见二丁目", artist="杨千嬅")
    widget.set_chords(
        ChordTimeline(
            segments=[
                ChordSegment(start_ms=209_468, end_ms=210_324, chord="G:min"),
                ChordSegment(start_ms=210_324, end_ms=211_179, chord="C:maj"),
                ChordSegment(start_ms=211_179, end_ms=211_180, chord="F:maj"),
            ]
        )
    )
    drawn: list[str] = []

    def capture_label(_self, _painter, label, _x, _baseline, _font) -> None:
        drawn.append(label)

    monkeypatch.setattr(MusicianWidget, "_draw_chord_label", capture_label)
    pixmap = QPixmap(760, 100)
    painter = QPainter(pixmap)
    widget._draw_line(
        painter,
        line,
        active=True,
        row_top=0,
        row_height=100,
        lyric_size=32,
        chord_size=18,
    )
    painter.end()

    assert drawn == ["2m", "5", "1"]


def test_chord_carried_from_previous_line_is_not_drawn_twice(qtbot) -> None:
    previous = LyricLine(
        id="line-0030",
        start_ms=189_710,
        end_ms=192_680,
        text="如能忘掉渴望",
    )
    current = LyricLine(
        id="line-0031",
        start_ms=192_680,
        end_ms=196_000,
        text="岁月长衣裳薄",
    )
    document = LyricsDocument(
        schema_version=1,
        title="再见二丁目",
        language="zh",
        timing_mode="line",
        lines=[previous, current],
    )
    carried = ChordSegment(start_ms=191_330, end_ms=193_000, chord="A#:maj7")
    new_chord = ChordSegment(start_ms=193_000, end_ms=194_700, chord="C:maj")
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)
    widget.set_chords(ChordTimeline(segments=[carried, new_chord]))
    widget.set_music_info("F", 71, title="再见二丁目")

    assert widget.chords_for_line(previous) == (carried,)
    assert widget.chords_for_line(current) == (new_chord,)


def test_dense_consecutive_chords_expand_only_the_lyric_gaps_between_them(qtbot) -> None:
    line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=7000,
        text="我知道这样不应该",
    )
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(760, 480)
    lyric_font = QFont(widget.lyrics_style.font_family, 32)
    chord_font = QFont(widget.lyrics_style.font_family, 18)
    chord_font.setWeight(QFont.Weight.DemiBold)

    expansions = widget._lyric_gap_expansions(
        line,
        ((2, "7m7"), (3, "3m7"), (4, "6m7")),
        lyric_font,
        chord_font,
        712,
    )

    assert expansions[2] > 0
    assert expansions[3] > 0
    assert expansions[:2] == (0.0, 0.0)
    assert expansions[4:] == (0.0,) * (len(line.text) - 5)
    metrics = QFontMetrics(lyric_font)
    positions = widget._lyric_prefix_positions(line.text, metrics, expansions)
    anchors = [positions[index] for index in (2, 3, 4)]
    labels = ("7m7", "3m7", "6m7")
    assert all(
        next_anchor >= anchor + widget._chord_width(label, chord_font) + 4
        for (anchor, next_anchor), label in zip(pairwise(anchors), labels, strict=False)
    )


def test_word_timed_interlude_owns_its_chords_instead_of_previous_lyric(qtbot) -> None:
    first = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=30_000,
        text="我爱你",
        words=[
            WordTiming(text="我", start_ms=1_000, end_ms=1_500),
            WordTiming(text="爱", start_ms=1_500, end_ms=2_000),
            WordTiming(text="你", start_ms=2_000, end_ms=3_000),
        ],
    )
    second = LyricLine(
        id="line-0002",
        start_ms=30_000,
        end_ms=38_000,
        text="下一句",
        words=[
            WordTiming(text="下", start_ms=35_000, end_ms=35_500),
            WordTiming(text="一", start_ms=35_500, end_ms=36_000),
            WordTiming(text="句", start_ms=36_000, end_ms=36_500),
        ],
    )
    vocal_chord = ChordSegment(start_ms=1_200, end_ms=2_500, chord="E:maj")
    interlude_chord = ChordSegment(start_ms=10_000, end_ms=20_000, chord="A:maj")
    next_chord = ChordSegment(start_ms=35_000, end_ms=37_000, chord="B:maj")
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="word",
            lines=[first, second],
        )
    )
    widget.set_chords(ChordTimeline(segments=[vocal_chord, interlude_chord, next_chord]))
    widget.set_music_info("E", 130, title="测试")

    assert [line.text for line in widget._document_lines] == [
        "我爱你",
        "（间奏）",
        "间奏",
        "下一句",
    ]
    marker, interlude = widget._document_lines[1:3]
    assert widget.chords_for_line(marker) == ()
    assert (interlude.start_ms, interlude.end_ms) == (3_000, 35_000)
    assert widget.chords_for_line(first) == (vocal_chord,)
    assert widget.chords_for_line(interlude) == (interlude_chord,)
    assert widget.chords_for_line(second) == (next_chord,)
    widget.set_position_ms(2_999)
    before_interlude = widget.document_scroll_position()
    widget.set_position_ms(3_000)
    assert widget.document_scroll_position() == 2.0
    assert 0.0 < widget.document_scroll_position() - before_interlude < 0.01
    widget.set_position_ms(10_000)
    assert widget.visible_lines()[widget.current_row] == interlude
    widget.resize(900, 600)
    widget.show()
    QApplication.processEvents()
    assert not widget.grab().isNull()


def test_title_card_intro_becomes_chord_cue_on_musician_screen(qtbot) -> None:
    title = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=18_000,
        text="只是太爱你 - 张敬轩",
    )
    first = LyricLine(
        id="line-0002",
        start_ms=18_000,
        end_ms=22_000,
        text="第一句",
        words=[
            WordTiming(text="第", start_ms=20_000, end_ms=20_500),
            WordTiming(text="一", start_ms=20_500, end_ms=21_000),
            WordTiming(text="句", start_ms=21_000, end_ms=21_500),
        ],
    )
    intro_chord = ChordSegment(start_ms=2_000, end_ms=4_000, chord="D:maj")
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="只是太爱你",
            language="zh",
            timing_mode="line",
            lines=[title, first],
        )
    )
    widget.set_chords(ChordTimeline(segments=[intro_chord]))
    widget.set_music_info("D", 120, title="只是太爱你")

    assert [line.text for line in widget._document_lines] == ["（前奏）", "前奏", "第一句"]
    marker, intro = widget._document_lines[:2]
    assert widget.chords_for_line(marker) == ()
    assert (intro.start_ms, intro.end_ms) == (0, 20_000)
    assert widget.chords_for_line(intro) == (intro_chord,)
    assert widget.chords_for_line(first) == ()
    widget.set_position_ms(3_000)
    assert widget.visible_lines()[widget.current_row] == intro


def test_persisted_intro_marker_does_not_duplicate_musician_marker(qtbot) -> None:
    document = with_instrumental_markers(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="line",
            lines=[
                LyricLine(id="line-0001", start_ms=5_000, end_ms=7_000, text="第一句"),
                LyricLine(id="line-0002", start_ms=12_000, end_ms=14_000, text="第二句"),
            ],
        )
    )
    intro_chord = ChordSegment(start_ms=1_000, end_ms=2_000, chord="D:maj")
    interlude_chord = ChordSegment(start_ms=8_000, end_ms=9_000, chord="G:maj")
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)
    widget.set_chords(ChordTimeline(segments=[intro_chord, interlude_chord]))

    assert [line.text for line in widget._document_lines] == [
        "（前奏）",
        "前奏",
        "第一句",
        "（间奏）",
        "间奏",
        "第二句",
    ]
    assert widget.chords_for_line(widget._document_lines[0]) == ()
    assert widget.chords_for_line(widget._document_lines[1]) == (intro_chord,)
    assert widget.chords_for_line(widget._document_lines[3]) == ()
    assert widget.chords_for_line(widget._document_lines[4]) == (interlude_chord,)


def test_long_interlude_keeps_every_chord_across_aligned_cue_rows(qtbot, monkeypatch) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试",
        language="zh",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=1_000, text="前一句"),
            LyricLine(id="line-0002", start_ms=20_000, end_ms=21_000, text="后一句"),
        ],
    )
    chords = [
        ChordSegment(start_ms=start, end_ms=start + 1_000, chord="C:maj")
        for start in (2_000, 5_000, 8_000, 11_000, 14_000)
    ]
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)
    widget.set_chords(ChordTimeline(segments=chords))

    assert [line.text for line in widget._document_lines] == [
        "前一句",
        "（间奏）",
        "间奏",
        "间奏·续",
        "后一句",
    ]
    first_cue, second_cue = widget._document_lines[2:4]
    assert widget.chords_for_line(first_cue) == tuple(chords[:4])
    assert widget.chords_for_line(second_cue) == (chords[4],)
    widget.resize(900, 600)
    x_positions: list[float] = []
    monkeypatch.setattr(
        MusicianWidget,
        "_draw_chord_label",
        classmethod(lambda _cls, _painter, _label, x, _baseline, _font: x_positions.append(x)),
    )
    pixmap = QPixmap(900, 200)
    painter = QPainter(pixmap)
    font = QFont(widget.lyrics_style.font_family, 18)
    widget._draw_instrumental_cue(
        painter, first_cue, active=False, row_top=0, row_height=80, chord_font=font
    )
    widget._draw_instrumental_cue(
        painter, second_cue, active=False, row_top=80, row_height=80, chord_font=font
    )
    painter.end()
    assert x_positions[:4] == sorted(x_positions[:4])
    assert x_positions[4] == x_positions[0]
    widget.set_position_ms(14_000)
    assert widget.visible_lines()[widget.current_row] == second_cue


def test_instrumental_cues_show_each_beat_with_chord_on_nearest_dot(qtbot) -> None:
    first_line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=12_000,
        text="第一句",
        words=[
            WordTiming(text="第", start_ms=10_000, end_ms=10_500),
            WordTiming(text="一", start_ms=10_500, end_ms=11_000),
            WordTiming(text="句", start_ms=11_000, end_ms=11_500),
        ],
    )
    chords = [
        ChordSegment(start_ms=0, end_ms=1_550, chord="C:maj"),
        ChordSegment(start_ms=1_550, end_ms=5_250, chord="D:maj"),
        ChordSegment(start_ms=5_250, end_ms=10_000, chord="G:maj"),
    ]
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="word",
            lines=[first_line],
        )
    )
    widget.set_chords(ChordTimeline(segments=chords))
    widget.set_music_info("C", 60, beat_times_ms=list(range(0, 10_000, 1_000)))

    assert [line.text for line in widget._document_lines] == [
        "（前奏）",
        "前奏",
        "前奏·续",
        "第一句",
    ]
    cues = widget._document_lines[1:3]
    assert [widget._cue_beats_by_line_id[line.id] for line in cues] == [
        (0, 1_000, 2_000, 3_000, 4_000, 5_000, 6_000, 7_000),
        (8_000, 9_000),
    ]
    assert widget._cue_beat_labels_by_line_id[cues[0].id] == ("1", "", "2", "", "", "5", "", "")
    assert widget._cue_beat_labels_by_line_id[cues[1].id] == ("", "")
    widget.set_chord_mode("chord")
    assert widget._cue_beat_labels_by_line_id[cues[0].id][0] == widget.chord_label("C:maj")
    assert widget._cue_beat_labels_by_line_id[cues[0].id][2] == widget.chord_label("D:maj")


def test_two_bar_view_keeps_lyric_cells_centered_under_fixed_beats(qtbot, monkeypatch) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(960, 600)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="line",
            lines=[
                LyricLine(id="line-0001", start_ms=1_000, end_ms=9_000, text="甲乙丙丁戊己庚辛")
            ],
        )
    )
    widget.set_chords(
        ChordTimeline(
            segments=[
                ChordSegment(start_ms=1_000, end_ms=5_000, chord="C:maj"),
                ChordSegment(start_ms=5_000, end_ms=9_000, chord="G:maj"),
            ]
        )
    )
    widget.set_music_info(
        "C",
        60,
        beat_times_ms=tuple(range(1_000, 9_000, 1_000)),
        downbeat_times_ms=(1_000, 5_000),
        beats_per_bar=4,
    )

    assert len(widget._bar_rows) == 1
    assert "".join(widget._bar_rows[0].lyric_cells) == "甲乙丙丁戊己庚辛"
    assert widget._bar_rows[0].chord_cells[0] == ("C:maj",)
    assert widget._bar_rows[0].chord_cells[4] == ("G:maj",)
    grid_left, slot_width = widget._bar_grid_metrics(widget.width())
    assert grid_left == widget.width() * 0.04
    assert widget._bar_separator_xs(widget.width()) == (
        grid_left,
        grid_left + slot_width * 4,
    )
    for index in range(8):
        assert abs(
            widget._two_bar_lyric_rect(index, 0, 100).center().x()
            - widget._beat_x(index, widget.width())
        ) < 0.001
    chord_sizes: list[int] = []
    monkeypatch.setattr(
        MusicianWidget,
        "_draw_chord_label",
        classmethod(
            lambda _cls, _painter, _label, _x, _baseline, font: chord_sizes.append(
                font.pointSize()
            )
        ),
    )
    pixmap = QPixmap(960, 120)
    pixmap.fill(QColor("black"))
    painter = QPainter(pixmap)
    widget._draw_two_bar_row(painter, widget._bar_rows[0], 0, 120, active=True)
    lyric_size = painter.font().pointSize()
    painter.end()
    assert chord_sizes and set(chord_sizes) == {lyric_size}

    widget.show()
    QApplication.processEvents()
    assert not widget.grab().isNull()


def test_wide_musician_view_switches_between_two_and_four_bars_per_row(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(1_279, 600)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="line",
            lines=[LyricLine(id="line-0001", start_ms=0, end_ms=16_000, text="宽屏歌词")],
        )
    )
    widget.set_music_info(
        "C",
        60,
        beat_times_ms=tuple(range(0, 16_000, 1_000)),
        downbeat_times_ms=(0, 4_000, 8_000, 12_000),
        beats_per_bar=4,
    )

    assert widget.cue_bars_per_row == 2
    assert [len(row.beat_times_ms) for row in widget._bar_rows] == [8, 8]

    widget.show()
    QApplication.processEvents()
    widget.resize(1_280, 600)
    QApplication.processEvents()
    assert widget.cue_bars_per_row == 4
    assert [len(row.beat_times_ms) for row in widget._bar_rows] == [16]
    assert len(widget._bar_separator_xs(widget.width())) == 4

    widget.resize(1_279, 600)
    QApplication.processEvents()
    assert widget.cue_bars_per_row == 2
    assert [len(row.beat_times_ms) for row in widget._bar_rows] == [8, 8]


def test_two_bar_view_uses_one_font_size_for_dense_lyrics_and_sparse_interlude(
    qtbot, monkeypatch
) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(1068, 1152)
    widget.set_font_size(52)
    lyric_row = MusicianBarRow(
        start_ms=0,
        end_ms=8000,
        beat_times_ms=tuple(range(0, 8000, 1000)),
        chord_cells=(("C:maj",), (), (), (), ("G:maj",), (), (), ()),
        lyric_cells=("那味道", "似是什", "么都", "不紧", "要", "国民谣", "突然被", ""),
    )
    interlude_row = MusicianBarRow(
        start_ms=8000,
        end_ms=16_000,
        beat_times_ms=tuple(range(8000, 16_000, 1000)),
        chord_cells=(("A:min",), (), (), (), ("F:maj",), (), (), ()),
        lyric_cells=("",) * 8,
        section_label="间奏",
    )
    widget._bar_rows = (lyric_row, interlude_row)
    chord_sizes: list[int] = []
    monkeypatch.setattr(
        MusicianWidget,
        "_draw_chord_label",
        classmethod(
            lambda _cls, _painter, _label, _x, _baseline, font: chord_sizes.append(
                font.pointSize()
            )
        ),
    )
    pixmap = QPixmap(1068, 400)
    pixmap.fill(QColor("black"))
    painter = QPainter(pixmap)
    font_sizes = []
    for index, row in enumerate(widget._bar_rows):
        widget._draw_two_bar_row(painter, row, index * 190, 190, active=index == 0)
        font_sizes.append(painter.font().pointSize())
    painter.end()

    assert font_sizes[0] < widget.content_font_sizes(190)[0]
    assert font_sizes == [font_sizes[0], font_sizes[0]]
    assert set(chord_sizes) == {font_sizes[0]}


def test_musician_beat_light_switch_controls_bar_dots_without_bottom_lights(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(960, 600)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="line",
            lines=[LyricLine(id="line-0001", start_ms=1_000, end_ms=9_000, text="甲乙")],
        )
    )
    widget.set_music_info(
        "C",
        60,
        beat_times_ms=tuple(range(1_000, 9_000, 1_000)),
        downbeat_times_ms=(1_000, 5_000),
        beats_per_bar=4,
    )
    widget.set_position_ms(0)
    widget.show()
    QApplication.processEvents()
    bottom = widget.height() - max(60, round(widget.height() * 0.1))
    row_height = (bottom - 58) / widget.bar_view_row_count
    dot_x = round(widget._beat_x(0, widget.width()))
    dot_y = round(58 + widget.bar_view_current_row * row_height + row_height * 0.57)

    def color_at(x: int, y: int) -> str:
        image = widget.grab().toImage()
        scale = image.devicePixelRatio()
        return image.pixelColor(round(x * scale), round(y * scale)).name()

    assert color_at(dot_x, dot_y) != "#000000"
    old_light = widget._beat_light_rects()[0].center()
    assert color_at(round(old_light.x()), round(old_light.y())) == "#000000"
    widget.set_beat_lights_visible(False)
    assert color_at(dot_x, dot_y) == color_at(dot_x + 20, dot_y)


def test_two_bar_first_beat_lights_when_reached(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.set_music_info("C", 60, beats_per_bar=4)
    row = MusicianBarRow(
        start_ms=1_000,
        end_ms=5_000,
        beat_times_ms=(1_000, 2_000, 3_000, 4_000),
        chord_cells=((), (), (), ()),
        lyric_cells=("", "", "", ""),
    )

    def first_dot_color(position_ms: int) -> QColor:
        widget.set_position_ms(position_ms)
        pixmap = QPixmap(800, 190)
        pixmap.fill(QColor("black"))
        painter = QPainter(pixmap)
        widget._draw_two_bar_row(painter, row, 0, 190, active=True)
        painter.end()
        return pixmap.toImage().pixelColor(round(widget._beat_x(0, 800)), round(190 * 0.57))

    assert first_dot_color(1_000) == first_dot_color(999)


def test_beat_dots_light_up_one_at_a_time_and_restore_on_seek(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 400)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="line",
            lines=[LyricLine(id="line-0001", start_ms=8_000, end_ms=9_000, text="开唱")],
        )
    )
    widget.set_chords(
        ChordTimeline(segments=[ChordSegment(start_ms=0, end_ms=8_000, chord="C:maj")])
    )
    widget.set_music_info("C", 60, beat_times_ms=list(range(0, 8_000, 1_000)))
    first_cue = widget._document_lines[1]
    assert widget._cue_beats_by_line_id[first_cue.id] == tuple(range(0, 8_000, 1_000))

    def dot_colors(position_ms: int) -> tuple[QColor, QColor, QColor]:
        widget.set_position_ms(position_ms)
        pixmap = QPixmap(800, 400)
        pixmap.fill(QColor("black"))
        painter = QPainter(pixmap)
        widget._draw_beat_dots(painter, 80, 1)
        painter.end()
        image = pixmap.toImage()
        return tuple(
            image.pixelColor(round(widget._beat_x(index, 800)), 80 + 56) for index in range(3)
        )

    before = dot_colors(0)
    after_first = dot_colors(500)
    after_second = dot_colors(1_000)
    restored = dot_colors(0)
    assert before == (QColor("black"),) * 3
    assert after_first == before
    assert after_second == before
    assert restored == before


def test_beat_dot_arrival_pulse_peaks_at_1_7_then_settles_at_1_45() -> None:
    beat_ms = 1_000
    peak_ms = beat_ms + round(
        MusicianWidget.beat_dot_pulse_duration_ms * MusicianWidget.beat_dot_peak_progress
    )

    assert MusicianWidget._beat_dot_scale(beat_ms, beat_ms - 1) == 1.0
    assert abs(MusicianWidget._beat_dot_scale(beat_ms, peak_ms) - 1.7) < 0.01
    assert MusicianWidget._beat_dot_scale(beat_ms, beat_ms + 240) == 1.45


def test_three_four_meter_uses_six_beat_rows_for_two_bars(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="line",
            lines=[LyricLine(id="line-0001", start_ms=12_000, end_ms=13_000, text="开唱")],
        )
    )
    widget.set_chords(
        ChordTimeline(segments=[ChordSegment(start_ms=0, end_ms=12_000, chord="C:maj")])
    )
    widget.set_music_info(
        "C",
        60,
        beat_times_ms=list(range(0, 12_000, 1_000)),
        downbeat_times_ms=[0, 3_000, 6_000, 9_000],
        beats_per_bar=3,
    )
    cues = [line for line in widget._document_lines if line.id in widget._cue_beats_by_line_id]
    assert [len(widget._cue_beats_by_line_id[line.id]) for line in cues] == [6, 6]


def test_interlude_starting_mid_bar_ends_row_at_second_bar_boundary(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="line",
            lines=[
                LyricLine(id="line-0001", start_ms=0, end_ms=1_500, text="前句"),
                LyricLine(id="line-0002", start_ms=10_000, end_ms=11_000, text="后句"),
            ],
        )
    )
    widget.set_chords(
        ChordTimeline(segments=[ChordSegment(start_ms=1_500, end_ms=10_000, chord="C:maj")])
    )
    widget.set_music_info(
        "C",
        60,
        beat_times_ms=list(range(0, 10_000, 1_000)),
        downbeat_times_ms=[0, 4_000, 8_000],
        beats_per_bar=4,
    )
    cues = [line for line in widget._document_lines if line.id in widget._cue_beats_by_line_id]
    assert [widget._cue_beats_by_line_id[line.id] for line in cues] == [
        (2_000, 3_000, 4_000, 5_000, 6_000, 7_000),
        (8_000, 9_000),
    ]


def test_outro_chords_are_rendered_after_the_last_sung_word(qtbot) -> None:
    last_line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=20_000,
        text="最后一句",
        words=[
            WordTiming(text="最", start_ms=1_000, end_ms=1_500),
            WordTiming(text="后", start_ms=1_500, end_ms=2_000),
            WordTiming(text="一", start_ms=2_000, end_ms=2_500),
            WordTiming(text="句", start_ms=2_500, end_ms=3_000),
        ],
    )
    chords = [
        ChordSegment(start_ms=start, end_ms=start + 1_000, chord="C:maj")
        for start in (4_000, 7_000, 10_000, 13_000, 16_000)
    ]
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="word",
            lines=[last_line],
        )
    )
    widget.set_chords(ChordTimeline(segments=chords))

    assert [line.text for line in widget._document_lines] == [
        "最后一句",
        "（尾奏）",
        "尾奏",
        "尾奏·续",
    ]
    marker, first_cue, second_cue = widget._document_lines[1:]
    assert widget.chords_for_line(marker) == ()
    assert widget.chords_for_line(first_cue) == tuple(chords[:4])
    assert widget.chords_for_line(second_cue) == (chords[4],)
    widget.set_position_ms(4_000)
    assert widget.visible_lines()[widget.current_row] == first_cue
    widget.set_position_ms(16_000)
    assert widget.visible_lines()[widget.current_row] == second_cue


def test_outro_displays_a_chord_sustained_from_the_last_lyric(qtbot) -> None:
    last_line = LyricLine(
        id="line-0001",
        start_ms=0,
        end_ms=20_000,
        text="最后一句",
        words=[
            WordTiming(text="最", start_ms=1_000, end_ms=1_500),
            WordTiming(text="后", start_ms=1_500, end_ms=2_000),
            WordTiming(text="一", start_ms=2_000, end_ms=2_500),
            WordTiming(text="句", start_ms=2_500, end_ms=3_000),
        ],
    )
    sustained = ChordSegment(start_ms=2_500, end_ms=18_000, chord="D:maj")
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试",
            language="zh",
            timing_mode="word",
            lines=[last_line],
        )
    )
    widget.set_chords(ChordTimeline(segments=[sustained]))

    assert [line.text for line in widget._document_lines] == [
        "最后一句",
        "（尾奏）",
        "尾奏",
    ]
    tail = widget._document_lines[-1]
    assert widget.chords_for_line(last_line) == (sustained,)
    assert widget.chords_for_line(tail) == (
        ChordSegment(start_ms=3_000, end_ms=18_000, chord="D:maj"),
    )


def test_transpose_and_capo_follow_selected_chord_key(qtbot) -> None:
    widget = MusicianWidget()
    qtbot.addWidget(widget)
    widget.set_music_info("F#m", 90, title="测试")

    assert widget.music_info_text == "测试 · 原KEY F#m · 90 BPM"
    widget.set_chord_mode("chord")
    assert widget.music_info_text == "测试 · 原KEY F#m · 90 BPM"
    widget.set_chord_mode("chord_c")
    assert widget.music_info_text == "测试 · 原KEY F#m · 移调-3 · Capo 9 · 90 BPM"
    widget.set_chord_mode("key:A")
    assert widget.music_info_text == "测试 · 原KEY F#m · 移调-3 · Capo 9 · 90 BPM"
    widget.set_chord_mode("key:D")
    assert widget.music_info_text == "测试 · 原KEY F#m · 移调+4 · Capo 4 · 90 BPM"

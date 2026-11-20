# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QMouseEvent
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from dxband.models.lyric import LyricLine, LyricsDocument
from dxband.models.song import MusicalConfig
from dxband.ui.render.audience_widget import AudienceWidget
from dxband.ui.render.singer_widget import SingerWidget
from dxband.ui.services.screen_manager import ScreenManager


def _lyrics() -> LyricsDocument:
    return LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=5_000,
                text="测试歌词",
                words=[],
            )
        ],
    )


def test_singer_shows_intro_and_interlude_as_current_lyric(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001", start_ms=5_000, end_ms=7_000, text="第一句"
            ),
            LyricLine(
                id="line-0002", start_ms=12_000, end_ms=14_000, text="第二句"
            ),
        ],
    )
    widget = SingerWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)

    assert widget.timeline is not None
    assert [line.text for line in widget.timeline.document.lines] == [
        "（前奏）", "第一句", "（间奏）", "第二句"
    ]
    widget.set_position_ms(1_000)
    assert widget.timeline.context_at(widget.position_ms).current.text == "（前奏）"
    widget.set_position_ms(9_000)
    assert widget.timeline.context_at(widget.position_ms).current.text == "（间奏）"


def test_singer_fills_three_rows_forward_during_intro(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=5_000, end_ms=7_000, text="第一句"),
            LyricLine(id="line-0002", start_ms=7_000, end_ms=9_000, text="第二句"),
            LyricLine(id="line-0003", start_ms=9_000, end_ms=11_000, text="第三句"),
        ],
    )
    widget = SingerWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)
    widget.set_position_ms(1_000)

    assert widget.timeline is not None
    context = widget.timeline.context_at(widget.position_ms)
    rows = widget._visible_lyric_rows(context)
    assert [line.text for line, _color, _is_current in rows] == [
        "（前奏）",
        "第一句",
        "第二句",
    ]
    assert [is_current for _line, _color, is_current in rows] == [True, False, False]


def test_singer_fills_three_rows_before_first_short_intro(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=500, end_ms=2_000, text="第一句"),
            LyricLine(id="line-0002", start_ms=2_000, end_ms=4_000, text="第二句"),
            LyricLine(id="line-0003", start_ms=4_000, end_ms=6_000, text="第三句"),
        ],
    )
    widget = SingerWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)
    widget.set_position_ms(100)

    assert widget.timeline is not None
    context = widget.timeline.context_at(widget.position_ms)
    assert context.current is None
    assert [line.text for line, _color, _is_current in widget._visible_lyric_rows(context)] == [
        "第一句",
        "第二句",
        "第三句",
    ]


def test_singer_holds_previous_lyric_during_short_gap(qtbot: QtBot) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=2_000, text="第一句"),
            LyricLine(id="line-0002", start_ms=2_600, end_ms=4_000, text="第二句"),
        ],
    )
    widget = SingerWidget()
    qtbot.addWidget(widget)
    widget.set_document(document)

    assert widget.timeline is not None
    widget.set_position_ms(2_300)
    context = widget.timeline.context_at(widget.position_ms)
    assert context.current is not None
    assert context.current.text == "第一句"
    assert context.next is not None
    assert context.next.text == "第二句"
    assert document.lines[0].end_ms == 2_000


def test_audience_shows_song_title_during_intro_only(qtbot: QtBot, monkeypatch) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="舞台歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=2_000, text="（前奏）"),
            LyricLine(id="line-0002", start_ms=2_000, end_ms=4_000, text="第一句"),
            LyricLine(id="line-0003", start_ms=4_000, end_ms=6_000, text="（间奏）"),
        ],
    )
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.set_document(document)
    window.show()
    painted: list[str] = []
    original_paint_line = window._paint_line

    def record_line(painter, line, *args, **kwargs) -> None:
        painted.append(line.text)
        original_paint_line(painter, line, *args, **kwargs)

    monkeypatch.setattr(window, "_paint_line", record_line)

    for position_ms, expected in ((1_000, "舞台歌曲"), (3_000, "第一句"), (5_000, "（间奏）")):
        window.set_position_ms(position_ms)
        window.grab()
        assert painted[-1] == expected

    assert [line.text for line in document.lines] == ["（前奏）", "第一句", "（间奏）"]


def test_audience_video_and_lyric_overlay_fill_fullscreen(
    qtbot: QtBot, tmp_path: Path
) -> None:
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.set_document(_lyrics())
    window.set_position_ms(2_000)
    sample = tmp_path / "background.mp4"
    sample.write_bytes(b"test video placeholder")
    window.set_background_video(sample)
    window.show()
    window.toggle_fullscreen()
    qtbot.wait(20)

    assert window._video_view.isVisible()
    assert window._video_overlay.isVisible()
    assert window._video_view.size() == window.size()
    assert window._video_item.size() == window.size()
    assert window._video_item.offset() == QPointF()
    assert window._video_overlay.boundingRect().size() == window.size()
    window._video_view.grab()
    assert len(window._path_cache) == 1

    window.toggle_fullscreen()
    qtbot.wait(20)
    assert window._video_view.size() == window.size()
    assert window._video_item.size() == window.size()
    assert window._video_overlay.boundingRect().size() == window.size()


def test_audience_lyrics_are_painted_above_video(
    qtbot: QtBot, monkeypatch, tmp_path: Path
) -> None:
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.resize(640, 480)
    sample = tmp_path / "background.mp4"
    sample.write_bytes(b"test video placeholder")
    window.set_background_video(sample)
    monkeypatch.setattr(
        window,
        "_paint_current_line",
        lambda painter: painter.fillRect(QRect(80, 80, 100, 100), QColor("lime")),
    )
    window.show()
    frame_image = QImage(640, 360, QImage.Format.Format_RGB32)
    frame_image.fill(QColor("blue"))
    window.background_video.video_sink.setVideoFrame(QVideoFrame(frame_image))
    qtbot.wait(20)

    composite = window._video_view.grab().toImage()
    ratio = composite.devicePixelRatio()
    assert composite.pixelColor(round(100 * ratio), round(100 * ratio)) == QColor("lime")
    assert composite.pixelColor(0, 0).blue() > 150
    assert composite.pixelColor(round(300 * ratio), round(200 * ratio)).blue() > 150


def _open_outputs(
    manager: ScreenManager,
    document: LyricsDocument,
    audience_fingerprint: str,
    singer_fingerprint: str,
    musical: MusicalConfig | None = None,
    *,
    title: str = "",
    artist: str = "",
) -> None:
    manager.open_audience_output(document, audience_fingerprint)
    manager.open_singer_output(
        document,
        singer_fingerprint,
        musical,
        title=title,
        artist=artist,
    )


def test_output_window_can_toggle_fullscreen(qtbot: QtBot) -> None:
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.show()
    window.set_windowed_size_limits(640, 360)

    assert not window.isFullScreen()
    assert window.maximumSize() == QSize(640, 360)
    window.toggle_fullscreen()
    assert window.isFullScreen()
    assert window.maximumWidth() == 16_777_215
    window.toggle_fullscreen()
    assert not window.isFullScreen()
    assert window.maximumSize() == QSize(640, 360)


def test_output_window_can_be_dragged_from_its_content(qtbot: QtBot) -> None:
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.show()
    start = window.pos()
    local = QPointF(120, 90)
    global_start = QPointF(window.mapToGlobal(QPoint(120, 90)))
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local,
        global_start,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, press)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        local + QPointF(40, 30),
        global_start + QPointF(40, 30),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, move)
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        local + QPointF(40, 30),
        global_start + QPointF(40, 30),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, release)

    assert window.pos() == start + QPoint(40, 30)
    assert window._drag_offset is None


def test_window_geometry_never_exceeds_available_display_area() -> None:
    available = QRect(0, 0, 420, 220)
    default = ScreenManager._window_geometry(available, 0, False)
    restored = ScreenManager._geometry_with_size(
        available,
        default,
        QSize(4_000, 3_000),
    )

    assert available.contains(default)
    assert available.contains(restored)
    assert restored.width() <= available.width()
    assert restored.height() <= available.height()


def test_screen_manager_opens_two_windowed_outputs_on_one_screen(
    qtbot: QtBot,
) -> None:
    manager = ScreenManager()
    assert manager._render_timer.interval() == 33
    descriptor = manager.descriptors()[0]
    _open_outputs(
        manager,
        _lyrics(),
        descriptor.fingerprint,
        descriptor.fingerprint,
    )
    assert manager.audience_window is not None
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)

    assert manager.audience_window.isVisible()
    assert manager.singer_window.isVisible()
    assert not manager.audience_window.isFullScreen()
    assert not manager.singer_window.isFullScreen()
    manager.close_outputs()


def test_screen_manager_controls_outputs_independently_and_tracks_manual_close(
    qtbot: QtBot,
) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    states: list[tuple[bool, bool]] = []
    manager.output_state_changed.connect(lambda audience, singer: states.append((audience, singer)))

    manager.open_audience_output(_lyrics(), descriptor.fingerprint)
    assert manager.audience_window is not None
    audience = manager.audience_window
    assert states[-1] == (True, False)

    manager.open_singer_output(_lyrics(), descriptor.fingerprint)
    assert manager.singer_window is not None
    singer = manager.singer_window
    qtbot.addWidget(singer)
    assert states[-1] == (True, True)

    audience.close()
    assert manager.audience_window is None
    assert manager.singer_window is singer
    assert states[-1] == (False, True)

    manager.close_singer_output()
    assert manager.singer_window is None
    assert states[-1] == (False, False)
    assert not manager._render_timer.isActive()


def test_screen_manager_opens_musician_without_changing_singer(qtbot: QtBot) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    musical = MusicalConfig(original_key="D", bpm=120, beat_times_ms=[1000, 1500])
    manager.set_musician_beat_lights_visible(False)
    manager.set_guide_countdown(8, 8)
    manager.open_singer_output(_lyrics(), descriptor.fingerprint, musical)
    singer = manager.singer_window
    assert singer is not None
    qtbot.addWidget(singer)
    manager.open_musician_output(
        _lyrics(), descriptor.fingerprint, musical, title="测试歌曲", artist="歌手"
    )
    musician = manager.musician_window
    assert musician is not None
    qtbot.addWidget(musician)
    assert manager.singer_window is singer
    assert musician.music_info_text == "测试歌曲 · 歌手 · 原KEY D · 120 BPM"
    assert musician.guide_countdown == (8, 8)
    manager.set_guide_countdown(7, 8)
    assert musician.guide_countdown == (7, 8)
    assert not musician.beat_lights_visible
    manager.set_musician_beat_lights_visible(True)
    assert not musician.beat_lights_visible
    manager.update_from_master(1000)
    manager._render_outputs()
    assert musician.beat_pulse_active
    manager.set_musician_offset(200)
    manager._render_outputs()
    assert musician.position_ms == 1200
    assert musician.beat_position_ms == 1000
    manager.clear_song()
    assert musician.guide_countdown == (0, 0)
    musician.close()
    assert manager.musician_window is None
    assert manager.singer_window is singer
    manager.close_outputs()


def test_screen_manager_closes_outputs_when_their_screen_is_removed(
    qtbot: QtBot,
) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    _open_outputs(manager, _lyrics(), descriptor.fingerprint, descriptor.fingerprint)
    assert manager.audience_window is not None
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)
    errors: list[str] = []
    manager.error_raised.connect(errors.append)

    manager._screen_removed(descriptor.screen)

    assert manager.audience_window is None
    assert manager.singer_window is None
    assert not manager._render_timer.isActive()
    # 不在 Qt/macOS 的 screenRemoved 回调内同步弹出模态错误框。
    assert errors == []
    qtbot.waitUntil(lambda: errors == ["观众屏、歌手屏已断开"])


def test_screen_manager_applies_font_sizes_before_and_after_open(
    qtbot: QtBot,
) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    manager.set_subtitle_font_sizes(90, 56)
    _open_outputs(manager, _lyrics(), descriptor.fingerprint, descriptor.fingerprint)
    assert manager.audience_window is not None
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)

    assert manager.audience_window.font_size == 90
    assert manager.singer_window.font_size == 56
    manager.set_subtitle_font_sizes(100, 60)
    assert manager.audience_window.font_size == 100
    assert manager.singer_window.font_size == 60
    manager.close_outputs()


def test_screen_manager_applies_singer_display_options_before_and_after_open(
    qtbot: QtBot,
) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    manager.set_singer_display_options(False, True)
    manager.open_singer_output(_lyrics(), descriptor.fingerprint)
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)

    assert not manager.singer_window.beat_lights_visible
    assert manager.singer_window.music_info_visible
    manager.set_singer_display_options(True, False)
    assert not manager.singer_window.beat_lights_visible
    assert not manager.singer_window.music_info_visible
    manager.close_outputs()


def test_singer_font_size_has_no_previous_72_point_limit(qtbot: QtBot) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    manager.set_subtitle_font_sizes(90, 160)
    _open_outputs(manager, _lyrics(), descriptor.fingerprint, descriptor.fingerprint)
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)

    assert manager.singer_font_size == 160
    assert manager.singer_window.font_size == 160
    manager.close_outputs()


def test_audience_font_size_has_no_120_point_limit(qtbot: QtBot) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    manager.set_subtitle_font_sizes(180, 42)
    _open_outputs(manager, _lyrics(), descriptor.fingerprint, descriptor.fingerprint)
    assert manager.audience_window is not None

    assert manager.audience_font_size == 180
    assert manager.audience_window.font_size == 180
    manager.close_outputs()


def test_singer_window_shows_key_and_bpm_in_top_left(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    window.set_document(_lyrics())
    window.set_music_info("F#m", 127, title="再见二丁目", artist="杨千嬅")

    assert window.music_info_text == ("再见二丁目 · 杨千嬅 · 原KEY F#m · 127 BPM")

    window.set_music_info("", 0)
    assert window.music_info_text == ""
    window.set_music_info("", 0, title="没有调性信息", artist="测试歌手")
    assert window.music_info_text == "没有调性信息 · 测试歌手"


def test_singer_window_elides_long_song_name_before_key(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.set_music_info(
        "F#m",
        127,
        title="非常非常长的歌曲名称需要在窄窗口中缩短",
        artist="名字也很长的歌手",
    )
    visible = window._visible_music_info(QFontMetrics(QFont("Arial", 18)), 350)

    assert visible.endswith("原KEY F#m · 127 BPM")
    assert "非常非常长的歌曲名称需要在窄窗口中缩短" not in visible


def test_singer_countdown_is_drawn_at_top_right(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    window.set_document(
        LyricsDocument(
            schema_version=1,
            title="测试歌曲",
            language="zh-CN",
            timing_mode="line",
            lines=[
                LyricLine(id="line-0001", start_ms=0, end_ms=1_000, text="第一句", words=[]),
                LyricLine(id="line-0002", start_ms=3_000, end_ms=5_000, text="第二句", words=[]),
            ],
        )
    )
    window.set_position_ms(500)
    image = window.grab().toImage()
    color = window.lyrics_style.countdown_color.name()
    scale = image.devicePixelRatio()

    assert color == "#888888"
    assert any(
        image.pixelColor(round(x * scale), round(y * scale)).name() == color
        for y in range(20, 100)
        for x in range(700, 950)
    )

    window.set_music_info_visible(False)
    hidden_image = window.grab().toImage()
    assert not any(
        hidden_image.pixelColor(round(x * scale), round(y * scale)).name() == color
        for y in range(20, 100)
        for x in range(700, 950)
    )
    assert not any(
        image.pixelColor(round(x * scale), round(y * scale)).name() == color
        for y in range(460, 530)
        for x in range(700, 950)
    )


def test_singer_four_beat_bar_keeps_timing_without_drawing_lights(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    window.set_document(_lyrics())
    window.set_music_info(
        "F",
        60,
        beat_times_ms=(1_000, 2_000, 3_000, 4_000, 5_000, 6_000, 7_000, 8_000),
        downbeat_times_ms=(1_000, 5_000),
        beats_per_bar=4,
    )

    def light_colors(position_ms: int) -> tuple[str, ...]:
        window.set_position_ms(position_ms)
        image = window.grab().toImage()
        scale = image.devicePixelRatio()
        return tuple(
            image.pixelColor(
                round(bar.center().x() * scale),
                round(bar.center().y() * scale),
            ).name()
            for bar in window._beat_light_rects()
        )

    lights = window._beat_light_rects()
    assert len(lights) == 4
    assert lights[0].left() == pytest.approx(window.width() - lights[-1].right())
    assert all(light.width() >= light.height() * 3 for light in lights)

    idle_colors = light_colors(900)
    for beat_number, position_ms in enumerate(range(1_000, 5_000, 1_000)):
        colors = light_colors(position_ms)
        assert window.active_beat_light_index == beat_number
        assert colors == idle_colors
    assert light_colors(5_000) == idle_colors


def test_singer_beat_lights_follow_three_beat_bar(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.set_music_info(
        "F",
        180,
        beat_times_ms=(1_000, 1_333, 1_667, 2_000, 2_333, 2_667),
        downbeat_times_ms=(1_000, 2_000),
        beats_per_bar=3,
    )

    assert len(window._beat_light_rects()) == 3
    for beat_number, position_ms in enumerate((1_000, 1_333, 1_667)):
        window.set_position_ms(position_ms)
        assert window.active_beat_light_index == beat_number


def test_singer_beat_lights_follow_a_short_transition_bar(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.set_music_info(
        "F",
        60,
        beat_times_ms=(1_000, 2_000, 3_000, 4_000, 5_000, 6_000, 7_000, 8_000),
        downbeat_times_ms=(1_000, 5_000, 7_000),
        beats_per_bar=4,
    )

    window.set_position_ms(5_000)
    assert window.beat_light_count == 2
    assert window.active_beat_light_index == 0
    window.set_position_ms(6_000)
    assert window.active_beat_light_index == 1
    window.set_position_ms(7_000)
    assert window.beat_light_count == 4
    assert window.active_beat_light_index == 0


def test_singer_display_options_hide_beat_bars_and_music_info(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    window.set_document(_lyrics())
    window.set_music_info(
        "F",
        60,
        beat_times_ms=(1_000, 2_000),
        title="测试歌曲",
        artist="测试歌手",
    )
    window.set_position_ms(1_000)

    visible_image = window.grab().toImage()
    scale = visible_image.devicePixelRatio()
    assert not window.beat_lights_visible
    assert all(
        visible_image.pixelColor(
            round(bar.center().x() * scale),
            round(bar.center().y() * scale),
        ).name()
        == "#000000"
        for bar in window._beat_light_rects()
    )
    assert any(
        visible_image.pixelColor(round(x * scale), round(y * scale)).name() != "#000000"
        for y in range(20, 65)
        for x in range(25, 500)
    )

    window.set_beat_lights_visible(False)
    window.set_music_info_visible(False)
    hidden_image = window.grab().toImage()
    assert all(
        hidden_image.pixelColor(
            round(bar.center().x() * scale),
            round(bar.center().y() * scale),
        ).name()
        == "#000000"
        for bar in window._beat_light_rects()
    )
    assert all(
        hidden_image.pixelColor(round(x * scale), round(y * scale)).name() == "#000000"
        for y in range(20, 65)
        for x in range(25, 500)
    )


def test_singer_beat_bar_uses_audio_clock_instead_of_lyric_offset(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.set_document(_lyrics())
    window.set_music_info(
        "F",
        60,
        beat_times_ms=(1_000, 2_000, 3_000, 4_000),
    )

    window.set_position_ms(1_150, beat_position_ms=900)
    assert not window.beat_pulse_active
    window.set_position_ms(1_150, beat_position_ms=1_000)
    assert window.beat_pulse_active


def test_singer_beat_bar_uses_local_beat_interval_instead_of_bpm(qtbot: QtBot) -> None:
    window = SingerWidget()
    qtbot.addWidget(window)
    window.set_music_info(
        "F",
        240,
        beat_times_ms=(1_000, 2_000, 3_000),
    )

    window.set_position_ms(1_100)

    assert window.beat_pulse_active


def test_screen_manager_passes_music_info_to_singer_window(qtbot: QtBot) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    _open_outputs(
        manager,
        _lyrics(),
        descriptor.fingerprint,
        descriptor.fingerprint,
        MusicalConfig(
            original_key="D",
            bpm=76,
            beat_times_ms=[800, 1_589, 2_378, 3_167, 3_956],
            downbeat_times_ms=[800, 3_956],
            beats_per_bar=4,
        ),
        title="测试歌曲",
        artist="测试歌手",
    )
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)

    assert manager.singer_window.music_info_text == ("测试歌曲 · 测试歌手 · 原KEY D · 76 BPM")
    assert manager.singer_window.beat_times_ms == (800, 1_589, 2_378, 3_167, 3_956)
    assert manager.singer_window.downbeat_times_ms == (800, 3_956)
    assert manager.singer_window.beats_per_bar == 4
    manager.close_outputs()


def test_screen_manager_does_not_apply_singer_offset_to_beat_clock(qtbot: QtBot) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    manager.set_offsets(0, 150)
    _open_outputs(
        manager,
        _lyrics(),
        descriptor.fingerprint,
        descriptor.fingerprint,
        MusicalConfig(
            original_key="D",
            bpm=60,
            beat_times_ms=[1_000, 2_000, 3_000],
        ),
    )
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)

    manager.update_from_master(1_000)
    manager._render_outputs()

    assert manager.singer_window.position_ms == 1_150
    assert manager.singer_window.beat_position_ms == 1_000
    assert manager.singer_window.beat_pulse_active
    manager.close_outputs()


def test_screen_manager_restores_records_and_resets_window_sizes(
    qtbot: QtBot,
) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    manager.set_window_sizes(620, 350, 700, 400, 720, 430)
    recorded: list[tuple[int, int, int, int, int, int]] = []
    manager.window_sizes_changed.connect(
        lambda *values: recorded.append(tuple(int(value) for value in values))
    )
    _open_outputs(manager, _lyrics(), descriptor.fingerprint, descriptor.fingerprint)
    assert manager.audience_window is not None
    assert manager.singer_window is not None
    qtbot.addWidget(manager.singer_window)

    assert manager.audience_window.size().width() == 620
    assert manager.audience_window.size().height() == 350
    assert manager.singer_window.size().width() == 700
    assert manager.singer_window.size().height() == 400

    manager.audience_window.resize(650, 370)
    qtbot.wait(350)
    assert recorded[-1] == (650, 370, 700, 400, 720, 430)

    manager.close_outputs()
    manager.open_musician_output(_lyrics(), descriptor.fingerprint)
    assert manager.musician_window is not None
    qtbot.addWidget(manager.musician_window)
    assert manager.musician_window.size().width() == 720
    assert manager.musician_window.size().height() == 430
    manager.musician_window.resize(730, 440)
    qtbot.wait(350)
    assert recorded[-1] == (650, 370, 700, 400, 730, 440)

    manager.reset_window_sizes()
    assert recorded[-1] == (0, 0, 0, 0, 0, 0)
    assert manager.musician_window.size().width() != 730
    manager.close_outputs()


def test_audience_window_shows_only_current_line_at_a_stable_random_position(
    qtbot: QtBot,
) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=0,
                end_ms=4_000,
                text="当前句",
                words=[],
            ),
            LyricLine(
                id="line-0002",
                start_ms=4_000,
                end_ms=8_000,
                text="下一句",
                words=[],
            ),
        ],
    )
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    window.set_document(document)
    window.set_position_ms(1_000)
    window.show()
    qtbot.wait(20)
    first_image = window.grab().toImage()

    assert len(window._path_cache) == 1
    center = next(iter(window._path_cache.values())).boundingRect().center()
    assert abs(center.x() - window.width() / 2) > 30 or abs(center.y() - window.height() / 2) > 30

    window.set_position_ms(3_000)
    qtbot.wait(20)
    second_image = window.grab().toImage()
    assert first_image == second_image


def test_audience_window_does_not_show_the_next_line_during_a_gap(
    qtbot: QtBot,
) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(
                id="line-0001",
                start_ms=1_000,
                end_ms=3_000,
                text="还没有开始",
                words=[],
            ),
        ],
    )
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    window.set_document(document)
    window.set_position_ms(0)
    window.show()
    qtbot.wait(20)
    window.grab()

    assert window._path_cache == {}


def test_audience_line_fades_in_and_out(qtbot: QtBot) -> None:
    window = AudienceWidget()
    qtbot.addWidget(window)
    line = LyricLine(
        id="line-9999",
        start_ms=1_000,
        end_ms=3_000,
        text="渐显渐隐",
        words=[],
    )

    window.position_ms = 1_000
    assert window._line_opacity(line) == 0.0
    window.position_ms = 1_150
    assert window._line_opacity(line) == 0.5
    window.position_ms = 1_300
    assert window._line_opacity(line) == 1.0
    window.position_ms = 2_775
    assert window._line_opacity(line) == 0.5
    window.position_ms = 3_000
    assert window._line_opacity(line) == 0.0


def test_audience_adjacent_lines_use_different_vertical_positions(
    qtbot: QtBot,
) -> None:
    document = LyricsDocument(
        schema_version=1,
        title="测试歌曲",
        language="zh-CN",
        timing_mode="line",
        lines=[
            LyricLine(id="line-0001", start_ms=0, end_ms=4_000, text="上一句", words=[]),
            LyricLine(id="line-0002", start_ms=4_000, end_ms=8_000, text="下一句", words=[]),
        ],
    )
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    window.set_document(document)

    assert (
        window._random_anchor(document.lines[0])[1] != window._random_anchor(document.lines[1])[1]
    )


def test_audience_text_uses_white_fill_and_black_shadow(qtbot: QtBot) -> None:
    window = AudienceWidget()
    qtbot.addWidget(window)

    assert window.lyrics_style.font_family == "PingFang SC"
    assert window.lyrics_style.highlight_color.name() == "#ffffff"
    assert window.lyrics_style.shadow_color.name() == "#000000"
    assert window.lyrics_style.shadow_offset == (3.0, 4.0)
    assert window.lyrics_style.shadow_blur_width == 5.0


def test_screen_manager_applies_audience_font_before_and_after_open(
    qtbot: QtBot,
) -> None:
    manager = ScreenManager()
    descriptor = manager.descriptors()[0]
    manager.set_audience_font_family("Long Cang")
    _open_outputs(manager, _lyrics(), descriptor.fingerprint, descriptor.fingerprint)
    assert manager.audience_window is not None

    assert manager.audience_window.lyrics_style.font_family == "Long Cang"
    manager.set_audience_font_family("Ma Shan Zheng")
    assert manager.audience_window.lyrics_style.font_family == "Ma Shan Zheng"
    manager.close_outputs()


def test_audience_font_size_changes_rendered_text_height(qtbot: QtBot) -> None:
    window = AudienceWidget()
    qtbot.addWidget(window)
    window.resize(960, 540)
    line = _lyrics().lines[0]

    window.set_font_size(48)
    small_height = window._path_for_line(line, 270, window.font_size).boundingRect().height()
    window.set_font_size(96)
    large_height = window._path_for_line(line, 270, window.font_size).boundingRect().height()

    assert large_height > small_height

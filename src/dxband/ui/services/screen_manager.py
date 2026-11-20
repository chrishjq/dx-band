# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QScreen

from dxband.analysis.chord_notation import valid_display_mode
from dxband.constants import MUSICIAN_FONT_SIZE_MIN
from dxband.models.chord import ChordTimeline
from dxband.models.lyric import LyricsDocument
from dxband.models.song import MusicalConfig
from dxband.ui.render.audience_widget import AudienceWidget
from dxband.ui.render.musician_widget import MusicianWidget
from dxband.ui.render.singer_widget import SingerWidget
from dxband.ui.render.web_musician_window import WebMusicianWindow
from dxband.ui.render.web_singer_window import WebSingerWindow
from dxband.ui.screen import ScreenDescriptor

OutputWindow = (
    AudienceWidget | SingerWidget | WebSingerWindow | MusicianWidget | WebMusicianWindow
)


class ScreenManager(QObject):
    screens_changed = Signal(object)
    error_raised = Signal(str)
    window_sizes_changed = Signal(int, int, int, int, int, int)
    output_state_changed = Signal(bool, bool)
    singer_window_closed = Signal()
    musician_state_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None, *, language: str = "zh") -> None:
        super().__init__(parent)
        self.language = language if language in {"zh", "en"} else "zh"
        self.audience_window: AudienceWidget | None = None
        self.singer_window: SingerWidget | WebSingerWindow | None = None
        self.musician_window: MusicianWidget | WebMusicianWindow | None = None
        self.audience_offset_ms = 0
        self.singer_offset_ms = 150
        self.musician_offset_ms = 0
        self.audience_font_size = 72
        self.singer_font_size = 42
        self.musician_font_size = 32
        self.musician_chord_mode = "degree"
        self.musician_beat_lights_visible = False
        self.audience_font_family = "PingFang SC"
        self.singer_beat_lights_visible = False
        self.singer_music_info_visible = True
        self._background_video_path: Path | None = None
        self._background_video_playing = False
        self._audience_screen: QScreen | None = None
        self._singer_screen: QScreen | None = None
        self._musician_screen: QScreen | None = None
        self._master_ms = 0
        self._guide_countdown = (0, 0)
        self._last_rendered_master_ms: int | None = None
        self._audience_window_size: QSize | None = None
        self._singer_window_size: QSize | None = None
        self._musician_window_size: QSize | None = None
        self._ignore_window_size_events = False
        self._pending_disconnected_outputs: list[str] = []
        self._disconnect_notice_scheduled = False
        self._render_timer = QTimer(self)
        # 音频优先：三屏最多约 30 Hz 重绘，降低绘制与实时音频回调争用。
        self._render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._render_timer.setInterval(33)
        self._render_timer.timeout.connect(self._render_outputs)
        self._size_save_timer = QTimer(self)
        self._size_save_timer.setSingleShot(True)
        self._size_save_timer.setInterval(300)
        self._size_save_timer.timeout.connect(self._emit_window_sizes)
        application = QGuiApplication.instance()
        if not isinstance(application, QGuiApplication):
            raise RuntimeError("屏幕管理器需要已启动的 Qt 应用")
        application.screenAdded.connect(self._screen_added)
        application.screenRemoved.connect(self._screen_removed)

    def descriptors(self) -> tuple[ScreenDescriptor, ...]:
        return tuple(self._descriptor(screen) for screen in QGuiApplication.screens())

    def set_language(self, language: str) -> None:
        self.language = language if language in {"zh", "en"} else "zh"
        for window in (self.singer_window, self.musician_window):
            if isinstance(window, SingerWidget):
                window.language = self.language
                window.update()

    def open_audience_output(
        self,
        document: LyricsDocument,
        fingerprint: str,
    ) -> None:
        screen = self._match(fingerprint)
        if screen is None:
            raise ValueError("已选择的观众输出显示器当前不可用")
        self.close_audience_output()
        window = AudienceWidget()
        window.set_font_size(self.audience_font_size)
        window.set_font_family(self.audience_font_family)
        window.set_background_video(self._background_video_path)
        window.set_background_video_playing(self._background_video_playing)
        window.set_document(document)
        window.windowed_size_changed.connect(self._audience_window_resized)
        window.closed.connect(self._audience_window_closed)
        self.audience_window = window
        self._audience_screen = screen
        self._show_windowed(
            window,
            screen,
            0,
            screen is self._singer_screen,
            self._audience_window_size,
        )
        self._arrange_shared_output_windows()
        self._output_opened()

    def open_singer_output(
        self,
        document: LyricsDocument,
        fingerprint: str,
        musical: MusicalConfig | None = None,
        *,
        title: str = "",
        artist: str = "",
    ) -> None:
        screen = self._match(fingerprint)
        if screen is None:
            raise ValueError("已选择的歌手输出显示器当前不可用")
        self.close_singer_output()
        window = SingerWidget(language=self.language)
        window.set_font_size(self.singer_font_size)
        window.set_beat_lights_visible(self.singer_beat_lights_visible)
        window.set_music_info_visible(self.singer_music_info_visible)
        window.set_document(document)
        self._set_singer_music_info(
            window,
            musical,
            title=title,
            artist=artist,
        )
        window.windowed_size_changed.connect(self._singer_window_resized)
        window.closed.connect(self._singer_window_closed)
        self.singer_window = window
        self._singer_screen = screen
        self._show_windowed(
            window,
            screen,
            1,
            screen is self._audience_screen,
            self._singer_window_size,
        )
        self._arrange_shared_output_windows()
        self._output_opened()

    def open_web_singer_output(self, url: str, fingerprint: str) -> None:
        screen = self._match(fingerprint)
        if screen is None:
            raise ValueError("已选择的歌手输出显示器当前不可用")
        if self.singer_window is not None:
            self.close_singer_output()
        window = WebSingerWindow(url, self.singer_font_size)
        window.windowed_size_changed.connect(self._singer_window_resized)
        window.closed.connect(self._singer_window_closed)
        self.singer_window = window
        self._singer_screen = screen
        self._show_windowed(
            window,
            screen,
            1,
            screen is self._audience_screen,
            self._singer_window_size,
        )
        self._arrange_shared_output_windows()
        self._output_opened()

    def _arrange_shared_output_windows(self) -> None:
        """多路窗口共用显示器时按列排开；单窗口保持自己的位置。"""
        outputs = (
            (self.audience_window, self._audience_screen, self._audience_window_size),
            (self.singer_window, self._singer_screen, self._singer_window_size),
            (self.musician_window, self._musician_screen, self._musician_window_size),
        )
        self._ignore_window_size_events = True
        try:
            for screen in QGuiApplication.screens():
                group = [
                    (window, preferred)
                    for window, assigned, preferred in outputs
                    if window is not None and assigned is screen and not window.isFullScreen()
                ]
                if len(group) < 2:
                    continue
                if len(group) == 2:
                    for index, (window, preferred) in enumerate(group):
                        self._show_windowed(window, screen, index, True, preferred)
                    continue
                available = screen.availableGeometry()
                margin = max(10, round(min(available.width(), available.height()) * 0.02))
                columns = 3 if available.width() >= 3 * 480 + 4 * margin else 2
                if columns == 2 and available.width() < 2 * 480 + 3 * margin:
                    columns = 1
                width = max(1, (available.width() - (columns + 1) * margin) // columns)
                rows = (len(group) + columns - 1) // columns
                height = max(1, (available.height() - (rows + 1) * margin) // rows)
                for index, (window, _preferred) in enumerate(group):
                    geometry = QRect(
                        available.x() + margin + (index % columns) * (width + margin),
                        available.y() + margin + (index // columns) * (height + margin),
                        width,
                        height,
                    )
                    window.setGeometry(self._clamp_geometry(available, geometry, margin))
        finally:
            self._ignore_window_size_events = False

    def open_musician_output(
        self,
        document: LyricsDocument,
        fingerprint: str,
        musical: MusicalConfig | None = None,
        chords: ChordTimeline | None = None,
        *,
        title: str = "",
        artist: str = "",
    ) -> None:
        screen = self._match(fingerprint)
        if screen is None:
            raise ValueError("已选择的乐手输出显示器当前不可用")
        self.close_musician_output()
        window = MusicianWidget(language=self.language)
        window.set_font_size(self.musician_font_size)
        window.set_chord_mode(self.musician_chord_mode)
        window.set_beat_lights_visible(self.musician_beat_lights_visible)
        window.set_document(document)
        window.set_chords(chords)
        self._set_singer_music_info(window, musical, title=title, artist=artist)
        window.set_guide_countdown(*self._guide_countdown)
        window.windowed_size_changed.connect(self._musician_window_resized)
        window.closed.connect(self._musician_window_closed)
        self.musician_window = window
        self._musician_screen = screen
        self._show_windowed(
            window,
            screen,
            2,
            screen in (self._audience_screen, self._singer_screen),
            self._musician_window_size,
        )
        self._arrange_shared_output_windows()
        self._output_opened()

    def open_web_musician_output(self, url: str, fingerprint: str) -> None:
        screen = self._match(fingerprint)
        if screen is None:
            raise ValueError("已选择的乐手输出显示器当前不可用")
        if self.musician_window is not None:
            self.close_musician_output()
        window = WebMusicianWindow(url, self.musician_font_size)
        window.windowed_size_changed.connect(self._musician_window_resized)
        window.closed.connect(self._musician_window_closed)
        self.musician_window = window
        self._musician_screen = screen
        self._show_windowed(
            window,
            screen,
            2,
            screen in (self._audience_screen, self._singer_screen),
            self._musician_window_size,
        )
        self._arrange_shared_output_windows()
        self._output_opened()

    def _output_opened(self) -> None:
        self._last_rendered_master_ms = None
        self._render_outputs()
        self._render_timer.start()
        self._emit_output_state()

    def close_audience_output(self) -> None:
        window = self.audience_window
        self.audience_window = None
        self._audience_screen = None
        if window is not None:
            window.close()
            window.deleteLater()
        self._arrange_shared_output_windows()
        self._output_closed()

    def close_singer_output(self) -> None:
        window = self.singer_window
        self.singer_window = None
        self._singer_screen = None
        if window is not None:
            window.close()
            window.deleteLater()
        self._arrange_shared_output_windows()
        self._output_closed()

    def close_musician_output(self) -> None:
        window = self.musician_window
        self.musician_window = None
        self._musician_screen = None
        if window is not None:
            window.close()
            window.deleteLater()
        self._arrange_shared_output_windows()
        self._output_closed()

    def close_outputs(self) -> None:
        if self._size_save_timer.isActive():
            self._size_save_timer.stop()
            self._emit_window_sizes()
        audience_window = self.audience_window
        singer_window = self.singer_window
        musician_window = self.musician_window
        self.audience_window = None
        self.singer_window = None
        self.musician_window = None
        self._audience_screen = None
        self._singer_screen = None
        self._musician_screen = None
        for window in (audience_window, singer_window, musician_window):
            if window is not None:
                window.close()
                window.deleteLater()
        self._render_timer.stop()
        self._last_rendered_master_ms = None
        self._emit_output_state()

    def _output_closed(self) -> None:
        if (
            self.audience_window is None
            and self.singer_window is None
            and self.musician_window is None
        ):
            self._render_timer.stop()
        self._last_rendered_master_ms = None
        self._emit_output_state()

    def _audience_window_closed(self) -> None:
        if self.sender() is not self.audience_window:
            return
        window = self.audience_window
        self.audience_window = None
        self._audience_screen = None
        if window is not None:
            window.deleteLater()
        self._output_closed()

    def _singer_window_closed(self) -> None:
        if self.sender() is not self.singer_window:
            return
        window = self.singer_window
        self.singer_window = None
        self._singer_screen = None
        if window is not None:
            window.deleteLater()
        self._output_closed()
        self.singer_window_closed.emit()

    def _musician_window_closed(self) -> None:
        if self.sender() is not self.musician_window:
            return
        window = self.musician_window
        self.musician_window = None
        self._musician_screen = None
        if window is not None:
            window.deleteLater()
        self._output_closed()

    def _emit_output_state(self) -> None:
        self.output_state_changed.emit(
            self.audience_window is not None and self.audience_window.isVisible(),
            self.singer_window is not None and self.singer_window.isVisible(),
        )
        self.musician_state_changed.emit(
            self.musician_window is not None and self.musician_window.isVisible()
        )

    def update_from_master(self, master_ms: int) -> None:
        self._master_ms = master_ms

    def set_offsets(self, audience_offset_ms: int, singer_offset_ms: int) -> None:
        self.audience_offset_ms = audience_offset_ms
        self.singer_offset_ms = singer_offset_ms
        self._last_rendered_master_ms = None

    def set_musician_offset(self, musician_offset_ms: int) -> None:
        self.musician_offset_ms = musician_offset_ms
        self._last_rendered_master_ms = None

    def set_musician_font_size(self, point_size: int) -> None:
        self.musician_font_size = max(MUSICIAN_FONT_SIZE_MIN, point_size)
        if self.musician_window is not None:
            self.musician_window.set_font_size(self.musician_font_size)

    def set_musician_chord_mode(self, mode: str) -> None:
        if not valid_display_mode(mode):
            raise ValueError("无效的乐手屏和弦模式")
        self.musician_chord_mode = mode
        if isinstance(self.musician_window, MusicianWidget):
            self.musician_window.set_chord_mode(mode)

    def set_musician_beat_lights_visible(self, visible: bool) -> None:
        self.musician_beat_lights_visible = False
        if isinstance(self.musician_window, MusicianWidget):
            self.musician_window.set_beat_lights_visible(False)

    def set_subtitle_font_sizes(self, audience: int, singer: int) -> None:
        """设置双屏字幕字号，并立即更新已打开的输出窗口。"""
        self.audience_font_size = max(36, audience)
        self.singer_font_size = max(24, singer)
        if self.audience_window is not None:
            self.audience_window.set_font_size(self.audience_font_size)
        if self.singer_window is not None:
            self.singer_window.set_font_size(self.singer_font_size)

    def set_singer_display_options(
        self,
        beat_lights_visible: bool,
        music_info_visible: bool,
    ) -> None:
        """保存歌手屏显示项状态，并立即同步到已打开的窗口。"""
        self.singer_beat_lights_visible = False
        self.singer_music_info_visible = music_info_visible
        if isinstance(self.singer_window, SingerWidget):
            self.singer_window.set_beat_lights_visible(False)
            self.singer_window.set_music_info_visible(music_info_visible)

    def set_background_video(self, path: Path | None) -> None:
        self._background_video_path = path
        if self.audience_window is not None:
            self.audience_window.set_background_video(path)

    def set_audience_font_family(self, family: str) -> None:
        self.audience_font_family = family.strip() or "PingFang SC"
        if self.audience_window is not None:
            self.audience_window.set_font_family(self.audience_font_family)

    def set_background_video_playing(self, playing: bool) -> None:
        self._background_video_playing = playing
        if self.audience_window is not None:
            self.audience_window.set_background_video_playing(playing)

    def set_window_sizes(
        self,
        audience_width: int,
        audience_height: int,
        singer_width: int,
        singer_height: int,
        musician_width: int,
        musician_height: int,
    ) -> None:
        """设置下次打开三个输出窗口时优先采用的尺寸。"""
        self._audience_window_size = self._valid_window_size(audience_width, audience_height)
        self._singer_window_size = self._valid_window_size(singer_width, singer_height)
        self._musician_window_size = self._valid_window_size(musician_width, musician_height)

    def reset_window_sizes(self) -> None:
        """清除用户尺寸，并将已打开窗口恢复为当前屏幕的默认尺寸。"""
        self._audience_window_size = None
        self._singer_window_size = None
        self._musician_window_size = None
        self._size_save_timer.stop()
        self._ignore_window_size_events = True
        try:
            same_screen = self._audience_screen is self._singer_screen
            if self.audience_window is not None and self._audience_screen is not None:
                if self.audience_window.isFullScreen():
                    self.audience_window.showNormal()
                self._show_windowed(
                    self.audience_window,
                    self._audience_screen,
                    0,
                    same_screen,
                    None,
                )
            if self.singer_window is not None and self._singer_screen is not None:
                if self.singer_window.isFullScreen():
                    self.singer_window.showNormal()
                self._show_windowed(
                    self.singer_window,
                    self._singer_screen,
                    1,
                    same_screen,
                    None,
                )
            if self.musician_window is not None and self._musician_screen is not None:
                if self.musician_window.isFullScreen():
                    self.musician_window.showNormal()
                self._show_windowed(
                    self.musician_window,
                    self._musician_screen,
                    2,
                    self._musician_screen in (self._audience_screen, self._singer_screen),
                    None,
                )
        finally:
            self._ignore_window_size_events = False
        self.window_sizes_changed.emit(0, 0, 0, 0, 0, 0)

    def set_document(self, document: LyricsDocument | None) -> None:
        if self.audience_window is not None:
            self.audience_window.set_document(document)
        if isinstance(self.singer_window, SingerWidget):
            self.singer_window.set_document(document)
        if isinstance(self.musician_window, MusicianWidget):
            self.musician_window.set_document(document)
        self._last_rendered_master_ms = None

    def set_chords(self, chords: ChordTimeline | None) -> None:
        if isinstance(self.musician_window, MusicianWidget):
            self.musician_window.set_chords(chords)

    def set_guide_countdown(self, remaining: int, total: int) -> None:
        self._guide_countdown = (remaining, total)
        if isinstance(self.musician_window, MusicianWidget):
            self.musician_window.set_guide_countdown(remaining, total)

    def clear_song(self) -> None:
        """切歌时清空旧歌词和音乐信息，保留输出窗口及其位置。"""
        self.set_background_video_playing(False)
        self.set_document(None)
        self.set_chords(None)
        self.set_guide_countdown(0, 0)
        self.set_music_info(None)
        self._master_ms = 0
        self._last_rendered_master_ms = None
        self._render_outputs()

    def set_music_info(
        self, musical: MusicalConfig | None, *, title: str = "", artist: str = ""
    ) -> None:
        for window in (self.singer_window, self.musician_window):
            if isinstance(window, SingerWidget):
                self._set_singer_music_info(window, musical, title=title, artist=artist)

    @staticmethod
    def _set_singer_music_info(
        window: SingerWidget,
        musical: MusicalConfig | None,
        *,
        title: str = "",
        artist: str = "",
    ) -> None:
        if musical is None:
            window.set_music_info("", 0, title=title, artist=artist)
            return
        window.set_music_info(
            musical.original_key,
            musical.bpm,
            musical.beat_times_ms,
            musical.downbeat_times_ms,
            musical.beats_per_bar,
            title=title,
            artist=artist,
        )

    def _match(self, fingerprint: str) -> QScreen | None:
        for descriptor in self.descriptors():
            if descriptor.fingerprint == fingerprint:
                return descriptor.screen
        return None

    @staticmethod
    def _show_windowed(
        window: OutputWindow,
        screen: QScreen,
        index: int,
        same_screen: bool,
        preferred_size: QSize | None,
    ) -> None:
        available = screen.availableGeometry()
        ScreenManager._set_window_size_limits(window, available)
        geometry = ScreenManager._window_geometry(available, index, same_screen)
        if preferred_size is not None:
            geometry = ScreenManager._geometry_with_size(available, geometry, preferred_size)
        window.setGeometry(geometry)
        window.show()
        handle = window.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
        window.showNormal()
        client_available = ScreenManager._client_available_geometry(window, available)
        ScreenManager._set_window_size_limits(window, client_available)
        geometry = ScreenManager._window_geometry(client_available, index, same_screen)
        if preferred_size is not None:
            geometry = ScreenManager._geometry_with_size(client_available, geometry, preferred_size)
        window.setGeometry(geometry)

    @staticmethod
    def _client_available_geometry(
        window: OutputWindow,
        available: QRect,
    ) -> QRect:
        """扣除系统窗口边框，返回可安全容纳客户区的显示器区域。"""
        margin = max(8, round(min(available.width(), available.height()) * 0.01))
        handle = window.windowHandle()
        frame = handle.frameMargins() if handle is not None else None
        left = margin + (max(0, frame.left()) if frame is not None else 0)
        top = margin + (max(0, frame.top()) if frame is not None else 0)
        right = margin + (max(0, frame.right()) if frame is not None else 0)
        bottom = margin + (max(0, frame.bottom()) if frame is not None else 0)
        bounded = available.adjusted(left, top, -right, -bottom)
        return bounded if bounded.width() > 0 and bounded.height() > 0 else available

    @staticmethod
    def _set_window_size_limits(
        window: OutputWindow,
        available: QRect,
    ) -> None:
        maximum_width = max(1, available.width())
        maximum_height = max(1, available.height())
        window.set_windowed_size_limits(maximum_width, maximum_height)

    @staticmethod
    def _window_geometry(available: QRect, index: int, same_screen: bool) -> QRect:
        margin = max(10, round(min(available.width(), available.height()) * 0.02))
        if same_screen:
            if available.width() < 1_100:
                width = available.width() - margin * 2
                height = round(available.height() * 0.62)
                offset = index * 30
                geometry = QRect(
                    available.x() + margin + offset,
                    available.y() + margin + offset,
                    width,
                    height,
                )
            else:
                width = (available.width() - margin * 3) // 2
                height = round(available.height() * 0.62)
                x = available.x() + margin + index * (width + margin)
                y = available.y() + max(margin, (available.height() - height) // 2)
                geometry = QRect(x, y, width, height)
        else:
            width = round(available.width() * 0.72)
            height = round(available.height() * 0.72)
            x = available.x() + (available.width() - width) // 2
            y = available.y() + (available.height() - height) // 2
            geometry = QRect(x, y, width, height)
        return ScreenManager._clamp_geometry(available, geometry, margin)

    @staticmethod
    def _geometry_with_size(
        available: QRect, default_geometry: QRect, preferred_size: QSize
    ) -> QRect:
        margin = max(10, round(min(available.width(), available.height()) * 0.02))
        geometry = QRect(0, 0, preferred_size.width(), preferred_size.height())
        geometry.moveCenter(default_geometry.center())
        return ScreenManager._clamp_geometry(available, geometry, margin)

    @staticmethod
    def _clamp_geometry(available: QRect, geometry: QRect, margin: int) -> QRect:
        maximum_width = max(1, available.width() - margin * 2)
        maximum_height = max(1, available.height() - margin * 2)
        minimum_width = min(480, maximum_width)
        minimum_height = min(270, maximum_height)
        width = max(minimum_width, min(geometry.width(), maximum_width))
        height = max(minimum_height, min(geometry.height(), maximum_height))
        bounded = QRect(0, 0, width, height)
        bounded.moveCenter(geometry.center())
        if bounded.left() < available.left() + margin:
            bounded.moveLeft(available.left() + margin)
        if bounded.top() < available.top() + margin:
            bounded.moveTop(available.top() + margin)
        if bounded.right() > available.right() - margin:
            bounded.moveRight(available.right() - margin)
        if bounded.bottom() > available.bottom() - margin:
            bounded.moveBottom(available.bottom() - margin)
        return bounded

    @staticmethod
    def _valid_window_size(width: int, height: int) -> QSize | None:
        if width < 480 or height < 270:
            return None
        return QSize(width, height)

    def _audience_window_resized(self, width: int, height: int) -> None:
        if self._ignore_window_size_events:
            return
        self._audience_window_size = self._valid_window_size(width, height)
        self._size_save_timer.start()

    def _singer_window_resized(self, width: int, height: int) -> None:
        if self._ignore_window_size_events:
            return
        self._singer_window_size = self._valid_window_size(width, height)
        self._size_save_timer.start()

    def _musician_window_resized(self, width: int, height: int) -> None:
        if self._ignore_window_size_events:
            return
        self._musician_window_size = self._valid_window_size(width, height)
        self._size_save_timer.start()

    def _emit_window_sizes(self) -> None:
        self.window_sizes_changed.emit(
            (self._audience_window_size.width() if self._audience_window_size is not None else 0),
            (self._audience_window_size.height() if self._audience_window_size is not None else 0),
            (self._singer_window_size.width() if self._singer_window_size is not None else 0),
            (self._singer_window_size.height() if self._singer_window_size is not None else 0),
            (self._musician_window_size.width() if self._musician_window_size is not None else 0),
            (self._musician_window_size.height() if self._musician_window_size is not None else 0),
        )

    def _render_outputs(self) -> None:
        if self._last_rendered_master_ms == self._master_ms:
            return
        self._last_rendered_master_ms = self._master_ms
        if self.audience_window is not None and self.audience_window.isVisible():
            self.audience_window.set_position_ms(
                self._master_ms + self.audience_offset_ms,
                background_position_ms=self._master_ms,
            )
        if isinstance(self.singer_window, SingerWidget) and self.singer_window.isVisible():
            self.singer_window.set_position_ms(
                self._master_ms + self.singer_offset_ms,
                beat_position_ms=self._master_ms,
            )
        if isinstance(self.musician_window, MusicianWidget) and self.musician_window.isVisible():
            self.musician_window.set_position_ms(
                self._master_ms + self.musician_offset_ms,
                beat_position_ms=self._master_ms,
            )

    def _screen_added(self, _screen: QScreen) -> None:
        self.screens_changed.emit(self.descriptors())

    def _screen_removed(self, screen: QScreen) -> None:
        if screen is self._audience_screen and self.audience_window is not None:
            self.close_audience_output()
            self._pending_disconnected_outputs.append("观众屏")
        if screen is self._singer_screen and self.singer_window is not None:
            self.close_singer_output()
            self._pending_disconnected_outputs.append("歌手屏")
        if screen is self._musician_screen and self.musician_window is not None:
            self.close_musician_output()
            self._pending_disconnected_outputs.append("乐手屏")
        self.screens_changed.emit(self.descriptors())
        if self._pending_disconnected_outputs and not self._disconnect_notice_scheduled:
            # macOS 正处于 screenRemoved 回调时不能启动模态对话框：
            # 外接屏休眠/唤醒时会使 AppKit 反复重入显示器配置，占满主线程。
            self._disconnect_notice_scheduled = True
            QTimer.singleShot(0, self._emit_disconnected_outputs)

    def _emit_disconnected_outputs(self) -> None:
        outputs = tuple(dict.fromkeys(self._pending_disconnected_outputs))
        self._pending_disconnected_outputs.clear()
        self._disconnect_notice_scheduled = False
        if outputs:
            self.error_raised.emit(f"{'、'.join(outputs)}已断开")

    @staticmethod
    def _descriptor(screen: QScreen) -> ScreenDescriptor:
        geometry = screen.geometry()
        raw = "|".join(
            (
                screen.name(),
                screen.manufacturer(),
                screen.model(),
                screen.serialNumber(),
                f"{geometry.x()},{geometry.y()},{geometry.width()},{geometry.height()}",
            )
        )
        fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return ScreenDescriptor(
            fingerprint=fingerprint,
            name=screen.name(),
            manufacturer=screen.manufacturer(),
            model=screen.model(),
            serial_number=screen.serialNumber(),
            geometry=geometry,
            screen=screen,
        )

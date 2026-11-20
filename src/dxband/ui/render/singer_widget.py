# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import math
from bisect import bisect_right

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

from dxband.lyrics.instrumental_markers import with_instrumental_markers
from dxband.lyrics.timeline import LyricTimeline, TimelineContext
from dxband.models.lyric import LyricLine, LyricsDocument
from dxband.ui.render.output_window import OutputWindow
from dxband.ui.render.style import SingerStyle


class SingerWidget(OutputWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("歌手屏", parent)
        self.timeline: LyricTimeline | None = None
        # 歌词位置允许应用歌手屏补偿；节拍位置必须始终跟随可听音频时钟。
        self.position_ms = 0
        self.beat_position_ms = 0
        self.lyrics_style = SingerStyle()
        self.font_size = 42
        self.song_title = ""
        self.artist = ""
        self.original_key = ""
        self.bpm = 0
        self.beat_times_ms: tuple[int, ...] = ()
        self.downbeat_times_ms: tuple[int, ...] = ()
        self.beats_per_bar: int | None = None
        self.beat_lights_visible = False
        self.music_info_visible = True
        self._render_signature: (
            tuple[str | None, str | None, str | None, int | None, int] | None
        ) = None

    def set_document(self, document: LyricsDocument | None) -> None:
        self.timeline = (
            LyricTimeline(
                with_instrumental_markers(document),
                hold_previous_until_next=True,
            )
            if document is not None
            else None
        )
        self._render_signature = None
        self.update()

    def set_position_ms(
        self,
        position_ms: int,
        *,
        beat_position_ms: int | None = None,
    ) -> None:
        self.position_ms = position_ms
        self.beat_position_ms = position_ms if beat_position_ms is None else beat_position_ms
        signature = self._current_render_signature()
        if signature == self._render_signature:
            return
        self._render_signature = signature
        self.update()

    def _current_render_signature(
        self,
    ) -> tuple[str | None, str | None, str | None, int | None, int] | None:
        """仅在歌词行或按秒显示的倒计时变化时重绘歌手屏。"""
        if self.timeline is None:
            return None
        context = self.timeline.context_at(self.position_ms)
        countdown_seconds = (
            max(0, math.ceil(context.next_countdown_ms / 1000))
            if self.music_info_visible and context.next_countdown_ms is not None
            else None
        )
        return (
            context.previous.id if context.previous is not None else None,
            context.current.id if context.current is not None else None,
            context.next.id if context.next is not None else None,
            countdown_seconds,
            self.active_beat_light_index if self.beat_lights_visible else -1,
        )

    def set_font_size(self, point_size: int) -> None:
        """设置当前句字号，辅助歌词与倒计时按比例缩放。"""
        normalized = max(24, point_size)
        if self.font_size == normalized:
            return
        self.font_size = normalized
        self.update()

    def set_beat_lights_visible(self, visible: bool) -> None:
        """兼容旧设置；歌手屏和乐手屏不再显示拍子灯。"""
        self.beat_lights_visible = False

    def set_music_info_visible(self, visible: bool) -> None:
        """控制歌手屏顶部歌曲信息是否显示。"""
        if self.music_info_visible == visible:
            return
        self.music_info_visible = visible
        self._render_signature = None
        self.update()

    def set_music_info(
        self,
        original_key: str,
        bpm: int,
        beat_times_ms: tuple[int, ...] | list[int] = (),
        downbeat_times_ms: tuple[int, ...] | list[int] = (),
        beats_per_bar: int | None = None,
        *,
        title: str = "",
        artist: str = "",
    ) -> None:
        self.song_title = title.strip()
        self.artist = artist.strip()
        self.original_key = original_key.strip()
        self.bpm = max(0, bpm)
        self.beat_times_ms = tuple(beat_times_ms)
        self.downbeat_times_ms = tuple(downbeat_times_ms)
        self.beats_per_bar = (
            beats_per_bar if beats_per_bar is not None and 1 <= beats_per_bar <= 12 else None
        )
        self._render_signature = None
        self.update()

    @property
    def music_info_text(self) -> str:
        song_info = " · ".join(part for part in (self.song_title, self.artist) if part)
        musical_info = self._musical_info_text()
        return " · ".join(part for part in (song_info, musical_info) if part)

    def _musical_info_text(self) -> str:
        if not self.original_key or self.bpm <= 0:
            return ""
        return f"原KEY {self.original_key} · {self.bpm} BPM"

    def _visible_music_info(self, metrics: QFontMetrics, width: int) -> str:
        """窄窗口优先保留原 Key 和 BPM，仅截短歌名、歌手。"""
        song_info = " · ".join(part for part in (self.song_title, self.artist) if part)
        musical_info = self._musical_info_text()
        if not musical_info:
            return metrics.elidedText(song_info, Qt.TextElideMode.ElideRight, width)
        if not song_info:
            return metrics.elidedText(musical_info, Qt.TextElideMode.ElideRight, width)
        separator = " · "
        if metrics.horizontalAdvance(separator + musical_info) >= width:
            return metrics.elidedText(musical_info, Qt.TextElideMode.ElideRight, width)
        song_width = max(0, width - metrics.horizontalAdvance(separator + musical_info))
        return (
            metrics.elidedText(song_info, Qt.TextElideMode.ElideRight, song_width)
            + separator
            + musical_info
        )

    @property
    def beat_pulse_active(self) -> bool:
        """完全按照逐拍时间表点亮，不使用摘要 BPM 推算节奏。"""
        if not self.beat_times_ms:
            return False
        detected_index = self._active_detected_beat_index()
        if detected_index < 0:
            return False
        beat_age_ms = self.beat_position_ms - self.beat_times_ms[detected_index]
        interval_ms = self._beat_interval_ms(detected_index)
        pulse_ms = max(80.0, min(140.0, interval_ms * 0.22))
        return beat_age_ms < pulse_ms

    @property
    def beat_light_count(self) -> int:
        """有可靠小节信息时按拍号显示，否则兼容为一个拍子灯。"""
        if not self.downbeat_times_ms or self.beats_per_bar is None:
            return 1
        bar = bisect_right(self.downbeat_times_ms, self.beat_position_ms) - 1
        if 0 <= bar < len(self.downbeat_times_ms) - 1:
            start = bisect_right(self.beat_times_ms, self.downbeat_times_ms[bar]) - 1
            following = bisect_right(self.beat_times_ms, self.downbeat_times_ms[bar + 1]) - 1
            return max(1, following - start)
        return self.beats_per_bar

    @property
    def active_beat_light_index(self) -> int:
        """返回当前亮起的小节内拍号，静止阶段返回 -1。"""
        if not self.beat_pulse_active:
            return -1
        detected_index = self._active_detected_beat_index()
        if detected_index < 0 or self.beat_light_count == 1:
            return 0 if detected_index >= 0 else -1

        bar = max(0, bisect_right(self.downbeat_times_ms, self.beat_position_ms) - 1)
        downbeat_index = bisect_right(self.beat_times_ms, self.downbeat_times_ms[bar]) - 1
        return min(self.beat_light_count - 1, max(0, detected_index - downbeat_index))

    def _active_detected_beat_index(self) -> int:
        """返回可听位置对应的拍点；超出拍点表尾部后停止提示。"""
        detected_index = bisect_right(self.beat_times_ms, self.beat_position_ms) - 1
        if detected_index < 0:
            return -1
        interval_ms = self._beat_interval_ms(detected_index)
        beat_age_ms = self.beat_position_ms - self.beat_times_ms[detected_index]
        if beat_age_ms > interval_ms * 1.5:
            return -1
        return detected_index

    def _beat_interval_ms(self, detected_index: int) -> float:
        """使用拍点表中的局部间隔，保留真实演奏的速度波动。"""
        if detected_index + 1 < len(self.beat_times_ms):
            return float(
                self.beat_times_ms[detected_index + 1] - self.beat_times_ms[detected_index]
            )
        if detected_index > 0:
            return float(
                self.beat_times_ms[detected_index] - self.beat_times_ms[detected_index - 1]
            )
        return 500.0

    def _info_font(self) -> QFont:
        font = QFont(
            self.lyrics_style.font_family,
            max(15, round(self.font_size * 3 / 7)),
        )
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _beat_light_rects(self) -> tuple[QRectF, ...]:
        """在歌手屏底部居中排列适合舞台远看的三或四个长条灯。"""
        count = self.beat_light_count
        bar_width = max(44.0, min(96.0, self.width() * 0.07))
        bar_height = max(12.0, min(22.0, self.height() * 0.035))
        gap = max(10.0, min(20.0, self.width() * 0.015))
        total_width = bar_width * count + gap * (count - 1)
        left = (self.width() - total_width) / 2.0
        top = self.height() - max(24.0, self.height() * 0.07) - bar_height
        return tuple(
            QRectF(
                left + index * (bar_width + gap),
                top,
                bar_width,
                bar_height,
            )
            for index in range(count)
        )

    def _visible_lyric_rows(
        self,
        context: TimelineContext,
    ) -> tuple[tuple[LyricLine, QColor, bool], ...]:
        """Keep a three-line window visible, including at the song boundaries."""
        if self.timeline is None or not self.timeline.document.lines:
            return ()

        lines = self.timeline.document.lines
        line_indices = {line.id: index for index, line in enumerate(lines)}
        current_index = line_indices[context.current.id] if context.current is not None else None
        next_index = line_indices[context.next.id] if context.next is not None else None
        previous_index = line_indices[context.previous.id] if context.previous is not None else None

        if current_index is not None:
            preferred_start = current_index - 1
        elif next_index is not None:
            preferred_start = next_index
        elif previous_index is not None:
            preferred_start = previous_index - 2
        else:
            preferred_start = 0
        start = min(max(0, preferred_start), max(0, len(lines) - 3))

        rows: list[tuple[LyricLine, QColor, bool]] = []
        for index, line in enumerate(lines[start : start + 3], start=start):
            is_current = current_index == index
            if current_index is not None:
                is_previous = index < current_index
            else:
                is_previous = previous_index is not None and index <= previous_index
            if is_current:
                color = self.lyrics_style.current_color
            elif is_previous:
                color = self.lyrics_style.previous_color
            else:
                color = self.lyrics_style.next_color
            rows.append((line, color, is_current))
        return tuple(rows)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        info_font = self._info_font()
        context = self.timeline.context_at(self.position_ms) if self.timeline else None
        countdown_visible = (
            self.music_info_visible
            and context is not None
            and context.next_countdown_ms is not None
        )
        music_info = self.music_info_text
        if self.music_info_visible and music_info:
            painter.setPen(self.lyrics_style.next_color)
            painter.setFont(info_font)
            right_margin = max(210, round(self.width() * 0.24)) if countdown_visible else 30
            info_rect = self.rect().adjusted(30, 22, -right_margin, 0)
            painter.drawText(
                info_rect,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                self._visible_music_info(QFontMetrics(info_font), info_rect.width()),
            )
        if context is None:
            return
        width = self.width() - 100
        secondary_font_size = max(18, round(self.font_size * 5 / 7))
        rows = self._visible_lyric_rows(context)
        vertical_ratios = (0.25, 0.50, 0.75)
        for (line, color, is_current), vertical_ratio in zip(
            rows, vertical_ratios[: len(rows)], strict=True
        ):
            painter.setPen(color)
            point_size = self.font_size if is_current else secondary_font_size
            font = QFont(
                self.lyrics_style.font_family,
                point_size,
            )
            font.setWeight(QFont.Weight.Bold if is_current else QFont.Weight.Normal)
            painter.setFont(font)
            row_height = max(100, round(point_size * 1.8))
            painter.drawText(
                50,
                round(self.height() * vertical_ratio - row_height / 2),
                width,
                row_height,
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                line.text,
            )
        if countdown_visible and context.next_countdown_ms is not None:
            painter.setPen(self.lyrics_style.countdown_color)
            painter.setFont(info_font)
            painter.drawText(
                self.rect().adjusted(0, 22, -30, 0),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                self.format_countdown(context.next_countdown_ms),
            )

    def _paint_beat_indicator(self, painter: QPainter) -> None:
        """按小节内拍号逐个点亮，第一拍使用重拍色。"""
        if not self.beat_lights_visible or not self.beat_times_ms:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        active_index = self.active_beat_light_index
        for index, light in enumerate(self._beat_light_rects()):
            color = QColor("#ffd166" if index == 0 and index == active_index else "#45d483")
            color.setAlpha(255 if index == active_index else 62)
            painter.setBrush(color)
            painter.drawRoundedRect(light, light.height() / 2, light.height() / 2)
        painter.restore()

    @staticmethod
    def format_countdown(countdown_ms: int) -> str:
        seconds = max(0, math.ceil(countdown_ms / 1000))
        return f"{seconds} 秒下句"

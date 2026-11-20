# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import hashlib
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QResizeEvent,
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QFrame, QGraphicsObject, QGraphicsScene, QGraphicsView, QWidget

from dxband.lyrics.instrumental_markers import instrumental_marker_label
from dxband.lyrics.timeline import LyricTimeline
from dxband.models.lyric import LyricLine, LyricsDocument
from dxband.ui.render.background_renderer import BackgroundRenderer
from dxband.ui.render.output_window import OutputWindow
from dxband.ui.render.style import AudienceStyle
from dxband.ui.render.text_layout import fitting_font
from dxband.video.background_video_engine import BackgroundVideoEngine


class _AudienceVideoOverlay(QGraphicsObject):
    """与视频在同一场景内绘制，避免系统视频层遮挡歌词。"""

    def __init__(self, audience: "AudienceWidget") -> None:
        super().__init__()
        self._audience = audience
        self._size = QSizeF()
        self.setZValue(1)

    def set_size(self, size: QSizeF) -> None:
        if size == self._size:
            return
        self.prepareGeometryChange()
        self._size = size

    def boundingRect(self) -> QRectF:
        return QRectF(QPointF(), self._size)

    def paint(self, painter: QPainter, _option: object, _widget: QWidget | None = None) -> None:
        painter.fillRect(self.boundingRect(), QColor(0, 0, 0, 48))
        self._audience._paint_current_line(painter)


class AudienceWidget(OutputWindow):
    _FADE_IN_DURATION_MS = 300
    _FADE_OUT_DURATION_MS = 450
    _RANDOM_ANCHORS = (
        (0.25, 0.25),
        (0.50, 0.25),
        (0.75, 0.25),
        (0.25, 0.50),
        (0.75, 0.50),
        (0.25, 0.75),
        (0.50, 0.75),
        (0.75, 0.75),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("观众屏", parent)
        self.document: LyricsDocument | None = None
        self.timeline: LyricTimeline | None = None
        self._intro_title_lines: dict[str, LyricLine] = {}
        self.position_ms = 0
        self.lyrics_style = AudienceStyle()
        self.font_size = 72
        self.background_mode = "gradient"
        self.background = BackgroundRenderer()
        self._video_view = QGraphicsView(self)
        self._video_view.setFrameShape(QFrame.Shape.NoFrame)
        self._video_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._video_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._video_view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._video_scene = QGraphicsScene(self)
        self._video_scene.setBackgroundBrush(QColor("#0b1023"))
        self._video_view.setScene(self._video_scene)
        self._video_item = QGraphicsVideoItem()
        self._video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        self._video_scene.addItem(self._video_item)
        self._video_overlay = _AudienceVideoOverlay(self)
        self._video_scene.addItem(self._video_overlay)
        self._resize_video_scene()
        self._video_view.hide()
        self.background_video = BackgroundVideoEngine(self, video_output=self._video_item)
        self._background_video_path: Path | None = None
        self._background_video_playing = False
        self._background_video_position_ms = 0
        self._path_cache: dict[tuple[str, int, int, int, int, int], QPainterPath] = {}
        self._anchor_indices: dict[str, int] = {}
        self._render_signature: tuple[str | None, int] | None = None

    def set_document(self, document: LyricsDocument | None) -> None:
        self.document = document
        self.timeline = LyricTimeline(document) if document is not None else None
        self._intro_title_lines = (
            {
                line.id: line.model_copy(update={"text": document.title})
                for line in document.lines
                if instrumental_marker_label(line) == "前奏"
            }
            if document is not None
            else {}
        )
        self._anchor_indices = self._build_anchor_indices(document)
        self._render_signature = None
        self._path_cache.clear()
        self._update_content()

    def set_position_ms(
        self, position_ms: int, *, background_position_ms: int | None = None
    ) -> None:
        self.position_ms = position_ms
        self._background_video_position_ms = (
            position_ms if background_position_ms is None else background_position_ms
        )
        if self._background_video_path is not None:
            self.background_video.synchronize(
                self._background_video_position_ms,
                self._background_video_playing,
            )
        signature = self._current_render_signature()
        if signature == self._render_signature:
            return
        self._render_signature = signature
        self._update_content()

    def _current_render_signature(
        self,
    ) -> tuple[str | None, int] | None:
        """返回当前歌词与渐变阶段，避免画面未变化时重复重绘。"""
        if self.timeline is None:
            return None
        context = self.timeline.context_at(self.position_ms)
        return (
            context.current.id if context.current is not None else None,
            round(self._line_opacity(context.current) * 20 if context.current is not None else 20),
        )

    def set_font_size(self, point_size: int) -> None:
        """设置观众屏当前歌词字号。"""
        normalized = max(36, point_size)
        if self.font_size == normalized:
            return
        self.font_size = normalized
        self._path_cache.clear()
        self._update_content()

    def set_font_family(self, family: str) -> None:
        normalized = family.strip() or "PingFang SC"
        if self.lyrics_style.font_family == normalized:
            return
        self.lyrics_style = replace(self.lyrics_style, font_family=normalized)
        self._path_cache.clear()
        self._update_content()

    def set_background_video(self, path: Path | None) -> None:
        normalized = path.resolve() if path is not None else None
        if normalized == self._background_video_path:
            return
        self._background_video_path = normalized
        if normalized is None:
            self.background_video.clear()
            self._video_view.hide()
        else:
            self._video_view.show()
            self.background_video.load(normalized)
            self.background_video.synchronize(
                self._background_video_position_ms,
                self._background_video_playing,
            )
        self._update_content()

    def set_background_video_playing(self, playing: bool) -> None:
        self._background_video_playing = playing
        if self._background_video_path is not None:
            self.background_video.synchronize(self._background_video_position_ms, playing)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        self.background.paint(painter, self.rect(), self.background_mode)
        if self._background_video_path is None:
            self._paint_current_line(painter)

    def _paint_current_line(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.timeline is None:
            return
        context = self.timeline.context_at(self.position_ms)
        current = context.current
        if current is None:
            return
        current_anchor = self._random_anchor(current)
        self._paint_line(
            painter,
            self._intro_title_lines.get(current.id, current),
            current_anchor[1],
            self.font_size,
            self.lyrics_style.highlight_color,
            center_x=current_anchor[0],
            opacity=self._line_opacity(current),
        )

    def _update_content(self) -> None:
        if self._background_video_path is None:
            self.update()
        else:
            self._video_overlay.update()

    def _resize_video_scene(self) -> None:
        size = QSizeF(self.size())
        rect = QRectF(QPointF(), size)
        self._video_view.setGeometry(self.rect())
        self._video_scene.setSceneRect(rect)
        self._video_item.setSize(size)
        self._video_item.setOffset(QPointF())
        self._video_overlay.set_size(size)

    def _paint_line(
        self,
        painter: QPainter,
        line: LyricLine,
        center_y: float,
        maximum_font_size: int,
        color: QColor,
        opacity: float = 1.0,
        center_x: float | None = None,
    ) -> None:
        path = self._path_for_line(
            line,
            center_y,
            maximum_font_size,
            center_x=center_x,
        )
        painter.save()
        painter.setOpacity(opacity)

        painter.save()
        painter.translate(*self.lyrics_style.shadow_offset)
        shadow_edge = QColor(self.lyrics_style.shadow_color)
        shadow_edge.setAlpha(max(1, shadow_edge.alpha() // 3))
        shadow_pen = QPen(shadow_edge, self.lyrics_style.shadow_blur_width)
        shadow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        shadow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(shadow_pen)
        painter.setBrush(self.lyrics_style.shadow_color)
        painter.drawPath(path)
        painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)
        painter.restore()

    def _path_for_line(
        self,
        line: LyricLine,
        center_y: float,
        maximum_font_size: int,
        *,
        center_x: float | None = None,
    ) -> QPainterPath:
        resolved_center_x = self.width() / 2 if center_x is None else center_x
        cache_key = (
            line.id,
            self.width(),
            self.height(),
            round(resolved_center_x),
            round(center_y),
            maximum_font_size,
        )
        cached = self._path_cache.get(cache_key)
        if cached is not None:
            return cached
        available_width = max(100, self.width() - 120)
        font = fitting_font(
            line.text,
            self.lyrics_style.font_family,
            maximum_font_size,
            24,
            available_width,
        )
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        metrics = QFontMetricsF(font)
        text_width = metrics.horizontalAdvance(line.text)
        bounds = metrics.boundingRect(line.text)
        baseline_y = center_y - (bounds.top() + bounds.bottom()) / 2
        start_x = max(
            60,
            min(
                self.width() - 60 - text_width,
                resolved_center_x - text_width / 2,
            ),
        )
        path = QPainterPath()
        path.addText(QPointF(start_x, baseline_y), font, line.text)
        self._path_cache[cache_key] = path
        return path

    def _random_anchor(self, line: LyricLine) -> tuple[float, float]:
        anchor_index = self._anchor_indices.get(line.id, self._base_anchor_index(line))
        anchor = self._RANDOM_ANCHORS[anchor_index]
        return anchor[0] * self.width(), anchor[1] * self.height()

    def _build_anchor_indices(self, document: LyricsDocument | None) -> dict[str, int]:
        """为每句生成稳定锚点，并保证相邻歌词不在同一水平带。"""
        if document is None:
            return {}
        indices: dict[str, int] = {}
        previous_index: int | None = None
        for line in document.lines:
            start_index = self._base_anchor_index(line)
            anchor_index = start_index
            if previous_index is not None:
                previous_y = self._RANDOM_ANCHORS[previous_index][1]
                for offset in range(len(self._RANDOM_ANCHORS)):
                    candidate = (start_index + offset) % len(self._RANDOM_ANCHORS)
                    if self._RANDOM_ANCHORS[candidate][1] != previous_y:
                        anchor_index = candidate
                        break
            indices[line.id] = anchor_index
            previous_index = anchor_index
        return indices

    @classmethod
    def _base_anchor_index(cls, line: LyricLine) -> int:
        digest = hashlib.sha256(f"{line.id}:{line.text}".encode()).digest()
        return digest[0] % len(cls._RANDOM_ANCHORS)

    def _line_opacity(self, line: LyricLine) -> float:
        duration_ms = max(1, line.end_ms - line.start_ms)
        fade_in_ms = max(1, min(self._FADE_IN_DURATION_MS, duration_ms // 2))
        fade_out_ms = max(1, min(self._FADE_OUT_DURATION_MS, duration_ms // 2))
        fade_in = (self.position_ms - line.start_ms) / fade_in_ms
        fade_out = (line.end_ms - self.position_ms) / fade_out_ms
        return max(0.0, min(1.0, fade_in, fade_out))

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._path_cache.clear()
        self.background.clear_cache()
        self._resize_video_scene()
        super().resizeEvent(event)

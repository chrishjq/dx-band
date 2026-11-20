# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from dxband.constants import TrackKind
from dxband.resource_paths import (
    CUSTOM_INSTRUMENT_ICON_ROOT,
    INSTRUMENT_ICON_ROOT,
)

TRACK_COLORS: dict[TrackKind, str] = {
    TrackKind.VOCALS: "#ff5f6d",
    TrackKind.DRUMS: "#f2aa4c",
    TrackKind.BASS: "#9b7aef",
    TrackKind.GUITAR: "#58c978",
    TrackKind.PIANO: "#b77ee8",
    TrackKind.OTHER: "#43cbb4",
}

TRACK_ICON_PATHS: dict[TrackKind, Path] = {
    TrackKind.VOCALS: INSTRUMENT_ICON_ROOT / "microphone.svg",
    TrackKind.DRUMS: INSTRUMENT_ICON_ROOT / "drum.svg",
    TrackKind.BASS: CUSTOM_INSTRUMENT_ICON_ROOT / "bass-clef.svg",
    TrackKind.GUITAR: INSTRUMENT_ICON_ROOT / "guitar.svg",
    TrackKind.PIANO: CUSTOM_INSTRUMENT_ICON_ROOT / "piano-keys.svg",
    TrackKind.OTHER: INSTRUMENT_ICON_ROOT / "music.svg",
}


class TrackMuteButton(QAbstractButton):
    """用乐器图标和颜色表达轨道静音状态。"""

    def __init__(
        self,
        track: TrackKind,
        label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.track = track
        self.label = label
        self.accent = QColor(TRACK_COLORS[track])
        self._icon_renderer = QSvgRenderer(str(TRACK_ICON_PATHS[track]), self)
        self._icon_cache: dict[str, QImage] = {}
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(108, 40)
        self.setObjectName("trackMuteButton")
        self.setProperty("track", track.value)
        self.setAccessibleName(f"{label}轨道静音开关")
        self.setToolTip(f"点击切换{label}轨道；彩色为启用，灰色为静音")

    def sizeHint(self) -> QSize:
        return QSize(118, 40)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        muted = self.isChecked()
        if not self.isEnabled():
            painter.setOpacity(0.55)
        inactive = muted
        foreground = QColor("#68717e") if inactive else QColor(self.accent)
        border = QColor("#343b46") if inactive else QColor(self.accent)
        background = QColor("#14181f") if inactive else QColor(self.accent)
        if not inactive:
            background.setAlpha(30 if not self.isDown() else 48)

        card = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(background)
        painter.drawRoundedRect(card, 8, 8)

        icon_rect, label_rect = self._content_rects(card)
        painter.drawImage(icon_rect, self._icon_image(foreground))
        painter.setPen(foreground)
        font = painter.font()
        font.setPointSize(11)
        font.setBold(not inactive)
        painter.setFont(font)
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.label,
        )

    @staticmethod
    def _content_rects(card: QRectF) -> tuple[QRectF, QRectF]:
        """将图标与标题排成一行，并在不同按钮宽度下保持间距。"""
        icon_size = min(26.0, max(22.0, card.height() - 20.0))
        icon_rect = QRectF(
            card.left() + 10,
            card.center().y() - icon_size / 2,
            icon_size,
            icon_size,
        )
        label_left = icon_rect.right() + 8
        label_rect = QRectF(
            label_left,
            card.top(),
            max(0.0, card.right() - 8 - label_left),
            card.height(),
        )
        return icon_rect, label_rect

    def _icon_image(self, color: QColor) -> QImage:
        cache_key = color.name(QColor.NameFormat.HexArgb)
        cached = self._icon_cache.get(cache_key)
        if cached is not None:
            return cached
        image = QImage(96, 96, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        icon_painter = QPainter(image)
        icon_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._icon_renderer.render(icon_painter, self._fitted_icon_rect(QRectF(6, 6, 84, 84)))
        icon_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        icon_painter.fillRect(image.rect(), color)
        icon_painter.end()
        self._icon_cache[cache_key] = image
        return image

    def _fitted_icon_rect(self, bounds: QRectF) -> QRectF:
        """在目标区域内保持 SVG 原始纵横比并居中。"""
        source = self._icon_renderer.viewBoxF()
        if source.width() <= 0 or source.height() <= 0:
            return bounds
        scale = min(bounds.width() / source.width(), bounds.height() / source.height())
        width = source.width() * scale
        height = source.height() * scale
        return QRectF(
            bounds.center().x() - width / 2,
            bounds.center().y() - height / 2,
            width,
            height,
        )

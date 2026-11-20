# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from typing import Literal

from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

SingerDisplayOption = Literal["beat_lights", "music_info"]


class SingerDisplayOptionButton(QAbstractButton):
    """歌手屏显示项的紧凑图标开关。"""

    def __init__(
        self,
        option: SingerDisplayOption,
        label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.option = option
        self.label = label
        self.accent = QColor("#43cbb4")
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(58, 88)
        self.setAccessibleName(f"歌手屏{label}显示开关")
        self.setToolTip(f"点击显示或隐藏歌手屏的{label}")

    def sizeHint(self) -> QSize:
        return QSize(70, 88)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked() and self.isEnabled()
        if not self.isEnabled():
            painter.setOpacity(0.72)

        foreground = QColor(self.accent) if active else QColor("#68717e")
        border = QColor(self.accent) if active else QColor("#343b46")
        background = QColor(self.accent) if active else QColor("#14181f")
        if active:
            background.setAlpha(30 if not self.isDown() else 48)

        card = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(background)
        painter.drawRoundedRect(card, 8, 8)

        icon_bounds = QRectF(card.center().x() - 18, card.top() + 9, 36, 36)
        if self.option == "beat_lights":
            self._paint_beat_lights(painter, icon_bounds, foreground)
        else:
            self._paint_music_info(painter, icon_bounds, foreground)

        painter.setPen(foreground)
        font = painter.font()
        font.setPointSize(9)
        font.setBold(active)
        painter.setFont(font)
        painter.drawText(
            QRectF(card.left(), card.bottom() - 29, card.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            self.label,
        )

    @staticmethod
    def _paint_beat_lights(
        painter: QPainter,
        bounds: QRectF,
        color: QColor,
    ) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        bar_width = 6.0
        bar_height = 14.0
        gap = 2.5
        total_width = bar_width * 4 + gap * 3
        left = bounds.center().x() - total_width / 2
        top = bounds.center().y() - bar_height / 2
        for index in range(4):
            light = QColor(color)
            light.setAlpha(255 if index == 0 else 100)
            painter.setBrush(light)
            painter.drawRoundedRect(
                QRectF(
                    left + index * (bar_width + gap),
                    top,
                    bar_width,
                    bar_height,
                ),
                bar_width / 2,
                bar_width / 2,
            )

    @staticmethod
    def _paint_music_info(
        painter: QPainter,
        bounds: QRectF,
        color: QColor,
    ) -> None:
        center = bounds.center()
        painter.setPen(QPen(color, 2.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(center.x() - 14, center.y() - 14, 28, 28))
        detail_pen = QPen(color, 2.6)
        detail_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(detail_pen)
        painter.drawPoint(QPointF(center.x(), center.y() - 7))
        painter.drawLine(QLineF(center.x(), center.y() - 1, center.x(), center.y() + 8))

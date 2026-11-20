# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import QLineF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget


class OutputScreenButton(QAbstractButton):
    """以屏幕卡片表达单个舞台输出窗口的开关状态。"""

    def __init__(
        self,
        label: str,
        accent: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.label = label
        self.accent = QColor(accent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumSize(96, 88)
        self.setObjectName("outputScreenButton")
        self.setAccessibleName(f"{label}屏输出开关")
        self.setToolTip(f"点击打开或关闭{label}屏输出窗口；彩色为已打开")

    def sizeHint(self) -> QSize:
        return QSize(112, 88)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked()
        if not self.isEnabled():
            painter.setOpacity(0.55)

        foreground = QColor(self.accent) if active else QColor("#68717e")
        border = QColor(self.accent) if active else QColor("#343b46")
        background = QColor(self.accent) if active else QColor("#14181f")
        if active:
            background.setAlpha(30 if not self.isDown() else 48)

        card = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(background)
        painter.drawRoundedRect(card, 8, 8)

        self._paint_screen_icon(painter, card, foreground)
        painter.setPen(foreground)
        font = painter.font()
        font.setPointSize(11)
        font.setBold(active)
        painter.setFont(font)
        painter.drawText(
            QRectF(card.left(), card.bottom() - 29, card.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            self.label,
        )

    @staticmethod
    def _paint_screen_icon(
        painter: QPainter,
        card: QRectF,
        color: QColor,
    ) -> None:
        """绘制简洁的显示器图标，保持与音轨图标卡片相同的视觉重量。"""
        screen = QRectF(card.center().x() - 19, card.top() + 11, 38, 27)
        painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(screen, 3, 3)
        painter.drawLine(
            QLineF(
                screen.center().x(),
                screen.bottom() + 1,
                screen.center().x(),
                screen.bottom() + 7,
            )
        )
        painter.drawLine(
            QLineF(
                screen.center().x() - 8,
                screen.bottom() + 7,
                screen.center().x() + 8,
                screen.bottom() + 7,
            )
        )

        # 屏幕中的状态点让图标在较小尺寸下仍能清楚表达“输出”。
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(screen.center().x() - 2.5, screen.center().y() - 2.5, 5, 5))

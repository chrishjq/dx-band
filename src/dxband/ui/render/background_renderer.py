# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap


class BackgroundRenderer:
    def __init__(self) -> None:
        self._cached_size: tuple[int, int] | None = None
        self._cached_gradient: QPixmap | None = None

    def paint(self, painter: QPainter, rect: QRect, mode: str = "gradient") -> None:
        if mode == "solid":
            painter.fillRect(rect, QColor("#101218"))
            return
        size = (rect.width(), rect.height())
        if self._cached_size != size or self._cached_gradient is None:
            self._cached_gradient = self._create_gradient(rect)
            self._cached_size = size
        painter.drawPixmap(rect.topLeft(), self._cached_gradient)

    def clear_cache(self) -> None:
        self._cached_size = None
        self._cached_gradient = None

    @staticmethod
    def _create_gradient(rect: QRect) -> QPixmap:
        pixmap = QPixmap(rect.size())
        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor("#11162B"))
        gradient.setColorAt(0.5, QColor("#2A1645"))
        gradient.setColorAt(1.0, QColor("#071D2B"))
        cache_painter = QPainter(pixmap)
        cache_painter.fillRect(pixmap.rect(), gradient)
        cache_painter.end()
        return pixmap

# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QWidget


class OutputWindow(QWidget):
    """可移动、可缩放且可独立全屏的歌词输出窗口。"""

    windowed_size_changed = Signal(int, int)
    closed = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(f"{title}（双击或 F11 全屏）")
        self._windowed_minimum_size = QSize(480, 270)
        self._windowed_maximum_size = QSize(16_777_215, 16_777_215)
        self._apply_windowed_size_limits()
        self.resize(960, 540)
        self._drag_offset: QPoint | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self._apply_windowed_size_limits()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16_777_215, 16_777_215)
            self.showFullScreen()
            self.setCursor(Qt.CursorShape.BlankCursor)

    def set_windowed_size_limits(self, maximum_width: int, maximum_height: int) -> None:
        """限制普通窗口不超过目标显示器，同时不影响真正的全屏模式。"""
        maximum = QSize(max(1, maximum_width), max(1, maximum_height))
        self._windowed_maximum_size = maximum
        self._windowed_minimum_size = QSize(
            min(480, maximum.width()),
            min(270, maximum.height()),
        )
        if not self.isFullScreen():
            self._apply_windowed_size_limits()

    def _apply_windowed_size_limits(self) -> None:
        self.setMinimumSize(0, 0)
        self.setMaximumSize(self._windowed_maximum_size)
        self.setMinimumSize(self._windowed_minimum_size)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_fullscreen()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.isFullScreen():
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.raise_()
            self.activateWindow()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self.isFullScreen()
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            if not self.isFullScreen():
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible() and not self.isFullScreen():
            size = event.size()
            self.windowed_size_changed.emit(size.width(), size.height())

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit()

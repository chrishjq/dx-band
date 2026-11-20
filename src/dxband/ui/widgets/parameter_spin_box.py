# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QSpinBox, QWidget


class ParameterSpinBox(QSpinBox):
    """适合演出参数的数值框：支持滚轮，提交后主动释放焦点。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editingFinished.connect(lambda: QTimer.singleShot(0, self._release_focus))

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().wheelEvent(event)

    def _release_focus(self) -> None:
        self.clearFocus()
        self.lineEdit().deselect()


class PlaybackBpmSpinBox(ParameterSpinBox):
    """调节一步 BPM 后立即退出编辑，避免后续快捷键误改速度。"""

    def stepBy(self, steps: int) -> None:
        super().stepBy(steps)
        QTimer.singleShot(0, self._release_focus)

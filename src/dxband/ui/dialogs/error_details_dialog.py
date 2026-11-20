# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


class ErrorDetailsDialog(QDialog):
    """展示简短错误和可复制的详细信息。"""

    def __init__(
        self,
        title: str,
        message: str,
        details: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 360)
        layout = QVBoxLayout(self)
        label = QLabel(message, self)
        label.setWordWrap(True)
        layout.addWidget(label)
        if details:
            detail_view = QPlainTextEdit(self)
            detail_view.setReadOnly(True)
            detail_view.setPlainText(details)
            layout.addWidget(detail_view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

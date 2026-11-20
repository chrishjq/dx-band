# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Application-styled confirmation dialogs."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from dxband.resource_paths import CONTROL_ICON_ROOT
from dxband.ui.page_layout import set_button_icon


class DestructiveConfirmationDialog(QDialog):
    """Show a destructive confirmation using the application's visual language."""

    def __init__(
        self,
        title: str,
        message: str,
        detail: str,
        confirm_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("confirmationDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(18)

        content = QHBoxLayout()
        content.setSpacing(16)
        content.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_label = QLabel(self)
        icon_label.setObjectName("confirmationIcon")
        icon_label.setFixedSize(36, 36)
        icon_label.setPixmap(
            QIcon(str(CONTROL_ICON_ROOT / "delete.svg")).pixmap(QSize(28, 28))
        )
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(8)
        title_label = QLabel(title, self)
        title_label.setObjectName("confirmationTitle")
        copy.addWidget(title_label)

        message_label = QLabel(message, self)
        message_label.setObjectName("confirmationMessage")
        message_label.setWordWrap(True)
        copy.addWidget(message_label)

        detail_label = QLabel(detail, self)
        detail_label.setObjectName("confirmationDetail")
        detail_label.setWordWrap(True)
        copy.addWidget(detail_label)
        content.addLayout(copy, 1)
        root.addLayout(content)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        self.cancel_button = QPushButton("取消", self)
        set_button_icon(self.cancel_button, "remove.svg")
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        actions.addWidget(self.cancel_button)

        self.confirm_button = QPushButton(confirm_text, self)
        set_button_icon(self.confirm_button, "delete.svg")
        self.confirm_button.setProperty("role", "danger")
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.clicked.connect(self.accept)
        actions.addWidget(self.confirm_button)
        root.addLayout(actions)

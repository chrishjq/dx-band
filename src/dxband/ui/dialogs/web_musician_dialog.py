# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Share dialog for the local browser musician display."""

import qrcode
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class WebMusicianDialog(QDialog):
    def __init__(
        self, url: str, parent: QWidget | None = None, *, display_name: str = "乐手"
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.setWindowTitle(f"网页{display_name}屏")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(13)
        title = QLabel(f"扫码打开{display_name}屏", self)
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("手机或 iPad 需要与这台电脑连接同一个局域网。", self)
        hint.setObjectName("mutedText")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        qr_label = QLabel(self)
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setPixmap(_qr_pixmap(url, 6))
        layout.addWidget(qr_label)

        url_label = QLabel(url, self)
        url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        url_label.setWordWrap(True)
        layout.addWidget(url_label)

        buttons = QHBoxLayout()
        copy_button = QPushButton("复制链接", self)
        close_button = QPushButton("关闭", self)
        copy_button.clicked.connect(self._copy_url)
        close_button.clicked.connect(self.close)
        buttons.addStretch(1)
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _copy_url(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.url)


def _qr_pixmap(value: str, scale: int) -> QPixmap:
    code = qrcode.QRCode(version=None, box_size=1, border=4)
    code.add_data(value)
    code.make(fit=True)
    matrix = code.get_matrix()
    side = len(matrix) * scale
    image = QImage(side, side, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#090c11"))
    for row_index, row in enumerate(matrix):
        for column_index, filled in enumerate(row):
            if filled:
                painter.drawRect(
                    column_index * scale,
                    row_index * scale,
                    scale,
                    scale,
                )
    painter.end()
    return QPixmap.fromImage(image)

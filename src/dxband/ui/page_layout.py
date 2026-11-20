# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from dxband.resource_paths import CONTROL_ICON_ROOT

PAGE_CONTENT_MARGINS = (34, 28, 34, 26)
PAGE_SECTION_SPACING = 14
PAGE_HEADER_SPACING = 4
BUTTON_ROW_SPACING = 8
BUTTON_ICON_SIZE = QSize(17, 17)
BUTTON_ICON_DIR = CONTROL_ICON_ROOT


def create_page_layout(page: QWidget) -> QVBoxLayout:
    """创建四个主工作区共用的页面布局。"""
    layout = QVBoxLayout(page)
    layout.setContentsMargins(*PAGE_CONTENT_MARGINS)
    layout.setSpacing(PAGE_SECTION_SPACING)
    return layout


def add_page_header(
    layout: QVBoxLayout,
    page: QWidget,
    title_text: str,
    subtitle_text: str,
    trailing: QWidget | None = None,
) -> tuple[QLabel, QLabel]:
    """添加统一的主标题、副标题以及可选的右侧操作控件。"""
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(16)
    heading_widget = QWidget(page)
    heading = QVBoxLayout(heading_widget)
    heading.setContentsMargins(0, 0, 0, 0)
    heading.setSpacing(PAGE_HEADER_SPACING)
    title = QLabel(title_text, page)
    title.setObjectName("pageTitle")
    subtitle = QLabel(subtitle_text, page)
    subtitle.setObjectName("pageSubtitle")
    heading.addWidget(title)
    heading.addWidget(subtitle)
    header.addWidget(heading_widget, 1, Qt.AlignmentFlag.AlignTop)
    if trailing is not None:
        header.addWidget(trailing, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addLayout(header)
    return title, subtitle


def set_button_icon(
    button: QPushButton,
    icon_name: str,
    size: QSize = BUTTON_ICON_SIZE,
) -> None:
    """为标准按钮应用统一尺寸的界面图标。"""
    button.setIcon(QIcon(str(BUTTON_ICON_DIR / icon_name)))
    button.setIconSize(size)

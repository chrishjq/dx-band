# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import sys

from PySide6.QtGui import QIcon, QPixmap

from dxband.resource_paths import RESOURCE_ROOT

APP_NAME = "DX Band"
APP_DISPLAY_NAME = "大象乐队工作站"
APP_WINDOW_TITLE = "大象乐队工作站 · DX Band"
APP_ICON_PATH = RESOURCE_ROOT / "dx_band_icon.png"
APP_WINDOWS_ICON_PATH = RESOURCE_ROOT / "dx_band_icon.ico"
SIDEBAR_LOGO_PATH = RESOURCE_ROOT / "dx_band_sidebar_logo.png"


def application_icon() -> QIcon:
    """加载 DX Band 的大象应用图标。"""
    path = APP_WINDOWS_ICON_PATH if sys.platform == "win32" else APP_ICON_PATH
    return QIcon(str(path))


def sidebar_logo() -> QPixmap:
    """加载去除透明安全边距的侧栏大象图。"""
    return QPixmap(str(SIDEBAR_LOGO_PATH))

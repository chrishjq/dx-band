# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from dxband.services.runtime_environment import configure_runtime_environment
from dxband.services.sleep_inhibitor import sleep_inhibitor
from dxband.ui.branding import APP_DISPLAY_NAME, APP_NAME, application_icon
from dxband.ui.main_window import MainWindow
from dxband.ui.theme import apply_professional_theme
from dxband.utils.logging_setup import configure_logging


def main(argv: Sequence[str] | None = None) -> int:
    """启动 Qt 应用。"""
    arguments = list(argv) if argv is not None else sys.argv
    configure_runtime_environment()
    configure_logging()
    application = QApplication(arguments)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(APP_DISPLAY_NAME)
    application.setOrganizationName("DXBand")
    application.setWindowIcon(application_icon())
    application.aboutToQuit.connect(sleep_inhibitor.close)
    apply_professional_theme(application)
    window = MainWindow()
    window.show()
    return application.exec()

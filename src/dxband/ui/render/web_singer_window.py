# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Desktop singer output rendered by the shared browser page."""

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout

from dxband.ui.render.output_window import OutputWindow


class WebSingerWindow(OutputWindow):
    def __init__(self, url: str, font_size: int) -> None:
        super().__init__("歌手屏")
        self.setWindowTitle("歌手屏（F11 全屏）")
        self._font_size = max(24, font_size)
        self._remove_windowed_size_limits()
        self.browser = QWebEngineView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.browser.loadFinished.connect(self._page_loaded)
        self.browser.setUrl(QUrl(url))
        self._fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        self._fullscreen_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._escape_shortcut.activated.connect(self._leave_fullscreen)

    def set_windowed_size_limits(self, maximum_width: int, maximum_height: int) -> None:
        self._remove_windowed_size_limits()

    def _remove_windowed_size_limits(self) -> None:
        unrestricted = QSize(16_777_215, 16_777_215)
        self._windowed_minimum_size = QSize(0, 0)
        self._windowed_maximum_size = unrestricted
        if not self.isFullScreen():
            self.setMinimumSize(0, 0)
            self.setMaximumSize(unrestricted)

    def set_font_size(self, point_size: int) -> None:
        self._font_size = max(24, point_size)
        self._apply_font_size()

    def _page_loaded(self, loaded: bool) -> None:
        if loaded:
            self._apply_font_size()

    def _apply_font_size(self) -> None:
        self.browser.page().runJavaScript(
            f"window.dxBandSetSingerFontSize?.({self._font_size})"
        )

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()

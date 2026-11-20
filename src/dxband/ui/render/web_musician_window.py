# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Desktop output window that renders the shared browser musician page."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSize, Qt, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import QKeySequence, QPageLayout, QPageSize, QShortcut
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QMessageBox, QVBoxLayout

from dxband.ui.render.output_window import OutputWindow


class WebMusicianWindow(OutputWindow):
    def __init__(self, url: str, font_size: int) -> None:
        super().__init__("乐手屏")
        self.setWindowTitle("乐手屏（F11 全屏）")
        self._remove_windowed_size_limits()
        self._font_size = font_size
        self.browser = QWebEngineView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.browser.loadFinished.connect(self._page_loaded)
        self.browser.urlChanged.connect(self._url_changed)
        self._pdf_exporting = False
        self._pdf_path: str | None = None
        self._pdf_browser: QWebEngineView | None = None
        self._pdf_ready_attempts = 0
        self._pdf_print_started = False
        self._pdf_ready_timer = QTimer(self)
        self._pdf_ready_timer.setInterval(100)
        self._pdf_ready_timer.timeout.connect(self._check_pdf_ready)
        self.browser.setUrl(QUrl(url))
        self._fullscreen_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        self._fullscreen_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._fullscreen_shortcut.activated.connect(self.toggle_fullscreen)
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._escape_shortcut.activated.connect(self._leave_fullscreen)

    def set_windowed_size_limits(self, maximum_width: int, maximum_height: int) -> None:
        """Keep the musician output freely resizable on every display."""
        self._remove_windowed_size_limits()

    def _remove_windowed_size_limits(self) -> None:
        unrestricted = QSize(16_777_215, 16_777_215)
        self._windowed_minimum_size = QSize(0, 0)
        self._windowed_maximum_size = unrestricted
        if not self.isFullScreen():
            self.setMinimumSize(0, 0)
            self.setMaximumSize(unrestricted)

    def set_font_size(self, point_size: int) -> None:
        self._font_size = point_size
        self._apply_font_size()

    def _page_loaded(self, loaded: bool) -> None:
        if loaded:
            self._apply_font_size()

    def _apply_font_size(self) -> None:
        scale = max(0.56, self._font_size / 32)
        self.browser.page().runJavaScript(f"window.dxBandSetFontScale?.({scale!r})")

    def _url_changed(self, url: QUrl) -> None:
        if url.fragment() != "dx-export-pdf":
            return
        self.browser.page().runJavaScript(
            "history.replaceState(null, '', location.pathname + location.search)"
        )
        self._export_requested()

    def _export_requested(self) -> None:
        if self._pdf_exporting:
            return
        self._pdf_exporting = True
        self.browser.page().runJavaScript(
            "document.getElementById('songTitle')?.textContent || '乐手谱'",
            self._save_pdf,
        )

    def _save_pdf(self, title: object) -> None:
        if not self._pdf_exporting:
            return
        safe_title = re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(title or "乐手谱")).strip(" .")[:80]
        suggested = str(Path.home() / f"{safe_title or '乐手谱'}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "导出乐手谱 PDF", suggested, "PDF 文件 (*.pdf)")
        if not path:
            self._finish_pdf_export()
            return
        if Path(path).suffix.lower() != ".pdf":
            path += ".pdf"
        self._pdf_path = path
        self._pdf_print_started = False
        self._pdf_browser = QWebEngineView(self)
        self._pdf_browser.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self._pdf_browser.resize(1200, 800)
        self._pdf_browser.loadFinished.connect(self._pdf_page_loaded)
        self._pdf_browser.page().pdfPrintingFinished.connect(self._pdf_finished)
        print_url = QUrl(self.browser.url())
        print_url.setFragment("")
        query = QUrlQuery(print_url)
        query.addQueryItem("pdf", "1")
        print_url.setQuery(query)
        self._pdf_browser.show()
        self._pdf_browser.setUrl(print_url)

    def _pdf_page_loaded(self, loaded: bool) -> None:
        if not self._pdf_exporting:
            return
        if not loaded:
            self._pdf_failed("无法加载 PDF 排版页面。")
            return
        self._pdf_ready_attempts = 0
        self._pdf_ready_timer.start()

    def _check_pdf_ready(self) -> None:
        if self._pdf_browser is None or not self._pdf_exporting:
            self._pdf_ready_timer.stop()
            return
        self._pdf_ready_attempts += 1
        if self._pdf_ready_attempts > 200:
            self._pdf_failed("等待谱面排版超时，请重试。")
            return
        self._pdf_browser.page().runJavaScript(
            "window.dxBandPdfReady?.() === true", self._on_pdf_ready
        )

    def _on_pdf_ready(self, ready: object) -> None:
        if (
            ready is not True
            or self._pdf_browser is None
            or not self._pdf_exporting
            or self._pdf_print_started
            or self._pdf_path is None
        ):
            return
        self._pdf_print_started = True
        self._pdf_ready_timer.stop()
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(10, 10, 10, 10),
            QPageLayout.Unit.Millimeter,
        )
        self._pdf_browser.page().printToPdf(self._pdf_path, layout)

    def _pdf_finished(self, path: str, success: bool) -> None:
        if path != self._pdf_path:
            return
        if not success:
            self._pdf_failed("无法保存乐手谱 PDF，请检查保存位置。")
            return
        self._finish_pdf_export()

    def _pdf_failed(self, message: str) -> None:
        self._finish_pdf_export()
        QMessageBox.warning(self, "导出 PDF 失败", message)

    def _finish_pdf_export(self) -> None:
        self._pdf_exporting = False
        self._pdf_path = None
        self._pdf_print_started = False
        self._pdf_ready_timer.stop()
        if self._pdf_browser is not None:
            self._pdf_browser.close()
            self._pdf_browser.deleteLater()
            self._pdf_browser = None

    def _leave_fullscreen(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()

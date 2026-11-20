# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from pytestqt.qtbot import QtBot

from dxband.services.web_singer_server import WebSingerServer
from dxband.ui.render.web_singer_window import WebSingerWindow
from dxband.ui.services.screen_manager import ScreenManager


def test_web_singer_uses_english_controls_and_keeps_lyrics(qtbot: QtBot) -> None:
    server = WebSingerServer(language="en")
    server.start(preferred_port=0)
    server.set_song({
        "title": "测试歌曲",
        "artist": "测试歌手",
        "original_key": "C",
        "bpm": 120,
        "lines": [{"id": "line-0001", "start_ms": 0, "end_ms": 1000, "text": "播放"}],
    })
    server.set_transport(state="paused", position_ms=200)
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.show()
    assert server.local_url is not None
    browser.setUrl(QUrl(server.local_url))
    readings: list[object] = []

    def read() -> dict[str, object] | None:
        browser.page().runJavaScript(
            "JSON.stringify({lang: document.documentElement?.lang, title: document.title, "
            "button: document.querySelector('#info-toggle')?.textContent, "
            "info: document.querySelector('#info')?.textContent, "
            "lyric: document.querySelector('.line.current')?.textContent})",
            readings.append,
        )
        value = readings.pop(0) if readings else None
        return json.loads(value) if isinstance(value, str) and value else None

    try:
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and value.get("lang") == "en"
            and value.get("title") == "DX Band Singer Screen"
            and value.get("lyric") == "播放",
            timeout=10000,
        )
        browser.page().runJavaScript("window.dxBandSetSingerInfoVisible(true)")
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and value.get("button") == "Hide song info"
            and "Original key C" in str(value.get("info")),
            timeout=10000,
        )
        server.set_language("zh")
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and value.get("lang") == "zh-CN"
            and value.get("button") == "隐藏歌曲信息"
            and "原KEY C" in str(value.get("info"))
            and value.get("lyric") == "播放",
            timeout=10000,
        )
    finally:
        browser.close()
        server.stop()


def test_web_singer_follows_transport_and_display_settings(qtbot: QtBot) -> None:
    server = WebSingerServer()
    server.start(preferred_port=0)
    server.set_song({
        "title": "测试歌曲",
        "artist": "测试歌手",
        "original_key": "C",
        "bpm": 120,
        "lines": [
            {"id": "line-0001", "start_ms": 1000, "end_ms": 2000, "text": "第一句"},
            {"id": "line-0002", "start_ms": 4000, "end_ms": 5000, "text": "第二句"},
            {"id": "line-0003", "start_ms": 6000, "end_ms": 7000, "text": "第三句"},
        ],
    })
    server.set_singer_display(offset_ms=0, font_size=42, music_info_visible=True)
    server.set_transport(state="paused", position_ms=2500)
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.resize(800, 500)
    browser.show()
    assert server.local_url is not None
    browser.setUrl(QUrl(server.local_url))
    readings: list[object] = []

    def read() -> dict[str, object] | None:
        browser.page().runJavaScript(
            """JSON.stringify((() => ({title: document.title,
              current: document.querySelector('.line.current')?.textContent,
              countdown: document.querySelector('#countdown')?.textContent,
              info: document.querySelector('#info')?.textContent,
              infoButton: document.querySelector('#info-toggle')?.textContent,
              infoPressed: document.querySelector('#info-toggle')
                ?.getAttribute('aria-pressed')}))())""",
            readings.append,
        )
        value = readings.pop(0) if readings else None
        return json.loads(value) if isinstance(value, str) else None

    try:
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and value.get("current") == "第一句"
            and value.get("countdown") == "2 秒下句",
            timeout=10000,
        )
        browser.page().runJavaScript("window.dxBandSetSingerInfoVisible(true)")
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and "测试歌曲" in value.get("info", "")
            and value.get("infoButton") == "隐藏歌曲信息"
            and value.get("infoPressed") == "true",
            timeout=10000,
        )
        browser.page().runJavaScript("document.querySelector('#info-toggle').click()")
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and value.get("info") == ""
            and value.get("infoButton") == "显示歌曲信息"
            and value.get("infoPressed") == "false"
            and value.get("countdown") == "2 秒下句",
            timeout=10000,
        )
        browser.page().runJavaScript("document.querySelector('#info-toggle').click()")
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and "测试歌曲" in value.get("info", "")
            and value.get("infoButton") == "隐藏歌曲信息",
            timeout=10000,
        )
        browser.page().runJavaScript(
            "window.dxBandSetSingerFontSize(42); document.querySelector('#larger').click()"
        )
        font_readings: list[object] = []

        def font_size() -> float | None:
            browser.page().runJavaScript(
                """(() => { const line = document.querySelector('.line.current');
                  return line ? parseFloat(getComputedStyle(line).fontSize) : null; })()""",
                font_readings.append,
            )
            value = font_readings.pop(0) if font_readings else None
            return float(value) if isinstance(value, (int, float)) else None

        qtbot.waitUntil(lambda: font_size() == 46, timeout=10000)
        server.set_transport(state="paused", position_ms=4200)
        server.set_singer_display(offset_ms=0, font_size=42, music_info_visible=False)
        qtbot.waitUntil(
            lambda: (value := read()) is not None
            and value.get("current") == "第二句"
            and value.get("info") == ""
            and value.get("infoButton") == "显示歌曲信息"
            and value.get("countdown") == "2 秒下句",
            timeout=10000,
        )
    finally:
        browser.close()
        server.stop()


def test_desktop_singer_uses_same_page_and_font_controls(qtbot: QtBot) -> None:
    server = WebSingerServer()
    server.start(preferred_port=0)
    server.set_song({
        "title": "测试歌曲",
        "artist": "测试歌手",
        "original_key": "C",
        "bpm": 120,
        "lines": [{"id": "line-0001", "start_ms": 0, "end_ms": 5000, "text": "第一句"}],
    })
    server.set_singer_display(offset_ms=0, font_size=42, music_info_visible=True)
    server.set_transport(state="paused", position_ms=1000)
    manager = ScreenManager()
    assert server.local_url is not None
    manager.set_subtitle_font_sizes(72, 52)
    readings: list[object] = []

    def font_size() -> float | None:
        window = manager.singer_window
        assert isinstance(window, WebSingerWindow)
        window.browser.page().runJavaScript(
            """(() => { const line = document.querySelector('.line.current');
              return line ? parseFloat(getComputedStyle(line).fontSize) : null; })()""",
            readings.append,
        )
        value = readings.pop(0) if readings else None
        return float(value) if isinstance(value, (int, float)) else None

    try:
        manager.open_web_singer_output(
            server.local_url, manager.descriptors()[0].fingerprint
        )
        window = manager.singer_window
        assert isinstance(window, WebSingerWindow)
        qtbot.addWidget(window)
        assert window.browser.url().toString() == server.local_url
        qtbot.waitUntil(lambda: font_size() == 52, timeout=10000)
        window.browser.page().runJavaScript("document.querySelector('#larger').click()")
        qtbot.waitUntil(lambda: font_size() == 56, timeout=10000)
        manager.set_subtitle_font_sizes(72, 64)
        qtbot.waitUntil(lambda: font_size() == 64, timeout=10000)
        remote = server.subscribe()
        second_remote = server.subscribe()
        assert remote is not second_remote
        server.unsubscribe(remote)
        server.unsubscribe(second_remote)
    finally:
        manager.close_outputs()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        server.stop()

# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import http.client
import json
from functools import partial
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QRectF, QSettings, QSize, QUrl
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFileDialog, QLabel
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband.services.web_musician_server import WebMusicianServer
from dxband.ui.controllers.playback_controller import PlaybackController
from dxband.ui.dialogs.web_musician_dialog import WebMusicianDialog
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.render.web_musician_window import WebMusicianWindow
from dxband.ui.services.screen_manager import ScreenManager
from dxband.ui.services.settings_service import SettingsService


def test_web_musician_button_starts_and_stops_local_server(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    settings = QSettings(str(tmp_path / "web.ini"), QSettings.Format.IniFormat)
    settings_service = SettingsService(settings)
    controller = PlaybackController(page, settings_service)
    monkeypatch.setattr(controller, "_show_web_musician_dialog", lambda: None)

    page.web_musician_button.click()
    assert controller._web_musician_server.running
    assert page.web_musician_button.isChecked()
    assert not hasattr(page, "web_musician_url_label")

    server = controller._web_musician_server
    assert server.port is not None
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=3)
    try:
        connection.request(
            "POST",
            "/local-mode?local=1",
            body=b'{"mode":"chord_c"}',
        )
        response = connection.getresponse()
        assert response.status == 200
        response.read()
    finally:
        connection.close()
    controller._drain_messages()
    assert settings_service.load_musician_display_settings().chord_mode == "chord_c"

    page.web_musician_button.click()
    assert not controller._web_musician_server.running
    assert not page.web_musician_button.isChecked()
    controller.close()


def test_web_musician_dialog_builds_qr_code(qtbot: QtBot) -> None:
    url = "http://192.168.1.2:8765/"
    dialog = WebMusicianDialog(url)
    qtbot.addWidget(dialog)

    labels = dialog.findChildren(QLabel)
    pixmaps = [label.pixmap() for label in labels]
    assert any(pixmap is not None and not pixmap.isNull() for pixmap in pixmaps)
    assert any(label.text() == url for label in labels)


def test_web_singer_button_starts_and_stops_local_server(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    settings = SettingsService(QSettings(str(tmp_path / "singer.ini"), QSettings.Format.IniFormat))
    controller = PlaybackController(page, settings)
    monkeypatch.setattr(controller, "_show_web_singer_dialog", lambda: None)
    try:
        assert page.web_singer_qr_button.isHidden()
        page.web_singer_button.click()
        assert controller._web_singer_server.running
        assert page.web_singer_button.text() == "关闭扫码"
        assert not page.web_singer_qr_button.isHidden()
        page.web_singer_button.click()
        assert not controller._web_singer_server.running
        assert page.web_singer_button.text() == "开启扫码"
        assert page.web_singer_qr_button.isHidden()
    finally:
        controller.close()


def test_enabled_qr_displays_resume_on_next_launch(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "resume.ini"), QSettings.Format.IniFormat)
    service = SettingsService(settings)
    first_page = PlaybackPage()
    qtbot.addWidget(first_page)
    first = PlaybackController(first_page, service)
    monkeypatch.setattr(first, "_show_web_musician_dialog", lambda: None)
    monkeypatch.setattr(first, "_show_web_singer_dialog", lambda: None)
    try:
        first_page.web_singer_button.click()
        first_page.web_musician_button.click()
        musician_url = first._web_musician_server.url
        singer_url = first._web_singer_server.url
        assert service.load_web_display_enabled("singer")
        assert service.load_web_display_enabled("musician")
    finally:
        first.close()

    next_page = PlaybackPage()
    qtbot.addWidget(next_page)
    second = PlaybackController(next_page, service)
    monkeypatch.setattr(second, "_show_web_musician_dialog", lambda: None)
    monkeypatch.setattr(second, "_show_web_singer_dialog", lambda: None)
    try:
        second.restore_web_displays()
        assert second._web_musician_server.url == musician_url
        assert second._web_singer_server.url == singer_url
        assert next_page.web_musician_button.isChecked()
        assert next_page.web_singer_button.isChecked()
        next_page.web_musician_button.click()
        next_page.web_singer_button.click()
        assert not service.load_web_display_enabled("musician")
        assert not service.load_web_display_enabled("singer")
    finally:
        second.close()


def test_local_musician_output_loads_shared_browser_page(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    selected: list[str] = []
    server.on_local_chord_mode = selected.append
    manager = ScreenManager()
    states: list[bool] = []
    manager.musician_state_changed.connect(states.append)
    try:
        server.start(preferred_port=0)
        url = server.local_url
        assert url is not None
        manager.open_web_musician_output(url, manager.descriptors()[0].fingerprint)
        assert states == [True]
        window = manager.musician_window
        assert isinstance(window, WebMusicianWindow)
        qtbot.waitUntil(lambda: window.browser.page().title() == "DX Band 乐手屏", timeout=10000)
        qtbot.waitUntil(lambda: len(server._subscribers) == 1, timeout=10000)
        assert window.browser.url().toString() == url
        remote = server.subscribe()
        assert remote is not None
        server.unsubscribe(remote)
        window.browser.page().runJavaScript(
            '''(() => { const select = document.querySelector("#chordKeySelect");
              select.value = "key:C"; select.dispatchEvent(new Event("change", {bubbles: true})); })()'''
        )
        qtbot.waitUntil(lambda: selected == ["key:C"], timeout=10000)
        manager.set_musician_font_size(40)
        assert window._font_size == 40
        window.set_windowed_size_limits(640, 360)
        assert window.minimumSize() == QSize(0, 0)
        assert window.maximumSize() == QSize(16_777_215, 16_777_215)
    finally:
        manager.close_outputs()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        server.stop()


def test_musician_highlights_only_the_playing_measure(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.local_url is not None
    server.set_song(
        {
            "title": "小节高亮测试",
            "artist": "测试",
            "original_key": "C",
            "bpm": 120,
            "beats_per_bar": 4,
            "rows": [
                {
                    "layout": "bars",
                    "score_bar": True,
                    "start_ms": bar * 2000,
                    "end_ms": (bar + 1) * 2000,
                    "beats": [
                        {"at_ms": bar * 2000 + beat * 500, "bar_start": beat == 0}
                        for beat in range(4)
                    ],
                }
                for bar in range(4)
            ],
        }
    )
    server.set_transport(state="paused", position_ms=2500)
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.resize(1100, 760)
    browser.show()
    browser.setUrl(QUrl(server.local_url))
    try:
        readings: list[object] = []

        def current_measure() -> dict[str, object] | None:
            browser.page().runJavaScript(
                """JSON.stringify((() => {
                  const bars = Array.from(document.querySelectorAll('.bar-measure'));
                  const active = bars.filter(bar => bar.classList.contains('active'));
                  return {
                    active: active.map(bar => bars.indexOf(bar)),
                    rows: document.querySelectorAll('.score-row.active').length,
                    background: active.length ? getComputedStyle(active[0]).backgroundImage : ''
                  };
                })())""",
                readings.append,
            )
            return json.loads(readings[-1]) if readings and readings[-1] else None

        qtbot.waitUntil(lambda: (current_measure() or {}).get("active") == [1], timeout=10000)
        first = current_measure()
        assert first is not None and first["rows"] == 0
        assert "gradient" in first["background"]

        server.set_transport(state="paused", position_ms=4500)
        qtbot.waitUntil(lambda: (current_measure() or {}).get("active") == [2], timeout=10000)
    finally:
        browser.close()
        server.stop()


def test_scanned_musician_page_fits_phone_and_ipad(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    rows = []
    for bar in range(8):
        beat_count = (4, 3, 5, 4)[bar % 4]
        beats = []
        for beat in range(beat_count):
            dense = beat_count == 5 and beat == 4
            notes = 4 if dense else 1
            beats.append(
                {
                    "at_ms": 2000 * bar + round(2000 * beat / beat_count),
                    "bar_start": beat == 0,
                    "chord_modes": {"degree": ["6m7/5"], "chord": ["F#m7/C#"]},
                    "lyrics": "再次相遇",
                    "lyric_units": [
                        {"start_16th": 24 * bar + 4 * beat + note, "text": "再见你我"[note]}
                        for note in range(notes)
                    ] if dense else [],
                    "melody_notes": [
                        {
                            "midi": 60 + note,
                            "start_16th": 24 * bar + 4 * beat + note,
                            "duration_16ths": 1 if dense else 4,
                        }
                        for note in range(notes)
                    ],
                }
            )
        rows.append(
            {
                "layout": "bars",
                "score_bar": True,
                "start_ms": 2000 * bar,
                "end_ms": 2000 * (bar + 1),
                "beats": beats,
            }
        )
    server.set_song(
        {
            "title": "移动端布局测试",
            "artist": "测试歌手",
            "original_key": "C",
            "bpm": 120,
            "beats_per_bar": 4,
            "melody_reference": "C4",
            "melody_transpose": 0,
            "melody_key": 0,
            "melody_tonic_midi": 60,
            "rows": rows,
        }
    )
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(390, 844)
    browser.show()
    browser.setUrl(QUrl(server.url))
    try:
        def read_layout(readings: list[object], width: int, expected_bars: int) -> bool:
            browser.page().runJavaScript(
                """JSON.stringify((() => {
                  const firstRow = document.querySelector('.bar-grid');
                  if (!firstRow) return null;
                  const cells = Array.from(document.querySelectorAll('.beat-cell'));
                  const notationOverflow = cells.filter(cell => {
                    const bounds = cell.getBoundingClientRect();
                    return Array.from(cell.querySelectorAll(
                      '.chords, .melody-group'
                    )).some(item => {
                      const rect = item.getBoundingClientRect();
                      return rect.left < bounds.left - 1 || rect.right > bounds.right + 1;
                    });
                  }).length;
                  const lyricRows = Array.from(document.querySelectorAll('.bar-grid'))
                    .map(grid => Array.from(grid.querySelectorAll('.lyrics'))
                      .flatMap(label => label.classList.contains('positioned-lyrics')
                        ? Array.from(label.querySelectorAll('.lyric-unit'))
                        : label.textContent.trim() ? [label] : [])
                      .map(label => label.getBoundingClientRect())
                      .sort((left, right) => left.left - right.left));
                  const lyricOverlaps = lyricRows.reduce((count, rects) => count +
                    rects.filter((rect, index) => index + 1 < rects.length &&
                      rect.right > rects[index + 1].left + 1).length, 0);
                  const lyricOffscreen = lyricRows.flat().filter(rect =>
                    rect.left < -1 || rect.right > innerWidth + 1).length;
                  const lyricLabels = Array.from(document.querySelectorAll('.lyrics'))
                    .filter(label => label.textContent.trim());
                  const score = document.getElementById('score').getBoundingClientRect();
                  const controls = document.querySelector('.header-controls')
                    .getBoundingClientRect();
                  return {
                    width: innerWidth,
                    bars: firstRow.querySelectorAll('.bar-measure').length,
                    rowHeight: firstRow.closest('.score-row').getBoundingClientRect().height,
                    anchored: document.querySelectorAll('.positioned-lyrics').length,
                    documentWidth: document.documentElement.scrollWidth,
                    scoreRight: score.right,
                    controlsRight: controls.right,
                    notationOverflow, lyricOverlaps, lyricOffscreen,
                    lyricFontSizes: new Set(lyricLabels.map(label =>
                      getComputedStyle(label).fontSize)).size,
                    scaledLyrics: lyricLabels.filter(label =>
                      getComputedStyle(label).transform !== 'none').length,
                    positionedReady: Array.from(document.querySelectorAll('.lyric-unit'))
                      .every(unit => Boolean(unit.style.left))
                  };
                })())""",
                readings.append,
            )
            if not readings or not isinstance(readings[-1], str):
                return False
            data = json.loads(readings[-1])
            return (
                data is not None
                and data["width"] == width
                and data["bars"] == expected_bars
                and data["positionedReady"]
                and data["notationOverflow"] == 0
                and data["lyricOverlaps"] == 0
                and data["lyricOffscreen"] == 0
            )

        for width, height, expected_bars in (
            (390, 844, 1),
            (320, 700, 1),
            (844, 390, 1),
            (744, 1133, 2),
            (768, 1024, 2),
            (1024, 768, 2),
        ):
            browser.setFixedSize(width, height)
            readings: list[object] = []
            qtbot.waitUntil(partial(read_layout, readings, width, expected_bars), timeout=10000)
            data = json.loads(readings[-1])
            assert data["anchored"] > 0
            assert data["documentWidth"] <= width
            assert data["scoreRight"] <= width + 1
            assert data["controlsRight"] <= width + 1
            assert data["notationOverflow"] == 0, (width, data)
            assert data["lyricOverlaps"] == 0, (width, data)
            assert data["lyricOffscreen"] == 0, (width, data)
            assert data["lyricFontSizes"] == 1, (width, data)
            assert data["scaledLyrics"] == 0, (width, data)
            if width <= 390 and height > width:
                assert data["rowHeight"] < 170
            if width == 768:
                assert data["rowHeight"] < 190

        browser.setFixedSize(744, 1133)
        final_layout_readings: list[object] = []
        qtbot.waitUntil(
            lambda: read_layout(final_layout_readings, 744, 2), timeout=10000
        )
        browser.page().runJavaScript("window.dxBandSetFontScale(1.2)")
        enlarged_layout_readings: list[object] = []
        qtbot.waitUntil(
            lambda: read_layout(enlarged_layout_readings, 744, 2), timeout=10000
        )
        browser.page().runJavaScript("window.dxBandSetFontScale(1)")
        reset_layout_readings: list[object] = []
        qtbot.waitUntil(
            lambda: read_layout(reset_layout_readings, 744, 2), timeout=10000
        )
        mode_readings: list[object] = []
        browser.page().runJavaScript(
            """JSON.stringify((() => {
              const row = document.querySelector('.score-row');
              const before = row.querySelector('.chords').textContent;
              const select = document.querySelector('#chordKeySelect');
              const defaultKey = select.value;
              const defaultLabel = select.selectedOptions[0]?.textContent;
              select.value = 'key:C'; select.dispatchEvent(new Event('change', {bubbles: true}));
              return {
                sameRow: document.querySelector('.score-row') === row,
                before, defaultKey, defaultLabel,
                after: row.querySelector('.chords').textContent,
                selected: select.classList.contains('active'),
                subtitle: document.querySelector('#songSubtitle').textContent
              };
            })())""",
            mode_readings.append,
        )
        qtbot.waitUntil(lambda: bool(mode_readings), timeout=10000)
        mode_data = json.loads(mode_readings[0])
        assert mode_data["sameRow"]
        assert mode_data["defaultKey"] == "key:C"
        assert mode_data["defaultLabel"] == "C(原key)"
        assert mode_data["before"] != mode_data["after"]
        assert mode_data["selected"] is True
        assert "移调+0" in mode_data["subtitle"]
        assert "Capo 0" in mode_data["subtitle"]
        key_readings: list[object] = []
        browser.page().runJavaScript(
            """JSON.stringify((() => {
              const select = document.querySelector('#chordKeySelect');
              const options = Array.from(select.options).filter((option) => option.value);
              select.value = 'key:D'; select.dispatchEvent(new Event('change', {bubbles: true}));
              return {
                count: options.length,
                labels: options.map((option) => option.textContent),
                original: options.find((option) => option.value === 'key:C')?.textContent,
                selected: select.value,
                chord: document.querySelector('.score-row .chords').textContent,
                subtitle: document.querySelector('#songSubtitle').textContent
              };
            })())""",
            key_readings.append,
        )
        qtbot.waitUntil(lambda: bool(key_readings), timeout=10000)
        key_data = json.loads(key_readings[0])
        assert key_data["count"] == 12
        assert all("调" not in label for label in key_data["labels"])
        assert key_data["original"] == "C(原key)"
        assert key_data["selected"] == "key:D"
        assert "G♯m7/D♯" in key_data["chord"]
        assert "移调-2" in key_data["subtitle"]
        assert "Capo 10" in key_data["subtitle"]
        return_readings: list[object] = []
        browser.page().runJavaScript(
            """JSON.stringify((() => {
              document.querySelector('[data-chord-mode="degree"]').click();
              const select = document.querySelector('#chordKeySelect');
              const retained = select.value;
              select.dispatchEvent(new Event('pointerdown', {bubbles: true}));
              return {retained, active: select.classList.contains('active')};
            })())""",
            return_readings.append,
        )
        qtbot.waitUntil(lambda: bool(return_readings), timeout=10000)
        assert json.loads(return_readings[0]) == {"retained": "key:D", "active": True}

        f_selected: list[object] = []
        browser.page().runJavaScript(
            'const select = document.querySelector("#chordKeySelect"); '
            'select.value = "key:F"; select.dispatchEvent(new Event("change", {bubbles: true})); '
            'select.value',
            f_selected.append,
        )
        qtbot.waitUntil(lambda: f_selected == ["key:F"], timeout=10000)
        server.set_song(
            {
                "title": "换调后的歌曲",
                "artist": "测试歌手",
                "original_key": "G",
                "numbered_key": "G",
                "bpm": 120,
                "beats_per_bar": 4,
                "rows": rows,
            }
        )
        changed_song_readings: list[object] = []

        def key_matches_changed_song() -> bool:
            browser.page().runJavaScript(
                """JSON.stringify((() => {
                  const select = document.querySelector('#chordKeySelect');
                  return {
                    subtitle: document.querySelector('#songSubtitle').textContent,
                    selected: select.value,
                    label: select.selectedOptions[0]?.textContent,
                    original: Array.from(select.options).find(option => option.value === 'key:G')?.textContent
                  };
                })())""",
                changed_song_readings.append,
            )
            if not changed_song_readings or not isinstance(changed_song_readings[-1], str):
                return False
            data = json.loads(changed_song_readings[-1])
            return (
                data["subtitle"].startswith("原KEY G · Capo 2")
                and data["label"] == "F"
                and data["original"] == "G(原key)"
            )

        qtbot.waitUntil(key_matches_changed_song, timeout=10000)
        assert json.loads(changed_song_readings[-1])["selected"] == "key:F"
        server.set_song(
            {
                "title": "小调歌曲",
                "artist": "测试歌手",
                "original_key": "Fm",
                "numbered_key": "Ab",
                "bpm": 120,
                "beats_per_bar": 4,
                "rows": rows,
            }
        )
        minor_key_readings: list[object] = []

        def minor_key_labels_are_distinct() -> bool:
            browser.page().runJavaScript(
                """JSON.stringify({
                  subtitle: document.querySelector('#songSubtitle').textContent,
                  original: Array.from(document.querySelector('#chordKeySelect').options)
                    .find(option => option.value === 'key:F')?.textContent
                })""",
                minor_key_readings.append,
            )
            if not minor_key_readings or not isinstance(minor_key_readings[-1], str):
                return False
            data = json.loads(minor_key_readings[-1])
            return data["subtitle"].startswith("原KEY Fm · Capo 0") and data["original"] == "F(原key Fm)"

        qtbot.waitUntil(minor_key_labels_are_distinct, timeout=10000)
    finally:
        browser.close()
        server.stop()


def test_musician_font_controls_resize_all_lyrics(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    server.set_song(
        {
            "title": "歌词字号测试",
            "artist": "",
            "original_key": "C",
            "bpm": 120,
            "beats_per_bar": 4,
            "melody_key": 0,
            "melody_tonic_midi": 60,
            "rows": [
                {
                    "layout": "bars",
                    "score_bar": True,
                    "section": "主歌" if bar == 0 else "",
                    "start_ms": 2000 * bar,
                    "end_ms": 2000 * (bar + 1),
                    "beats": [
                        {
                            "at_ms": 2000 * bar,
                            "bar_start": True,
                            "lyrics": "普通歌词" if bar != 1 else "",
                            "lyric_units": [
                                {"start_16th": 16 + note, "text": text}
                                for note, text in enumerate("定位歌词")
                            ] if bar == 1 else [],
                            "melody_notes": [
                                {
                                    "midi": 60 + note,
                                    "start_16th": 16 * bar + note,
                                    "duration_16ths": 1,
                                }
                                for note in range(4 if bar == 1 else 1)
                            ],
                        }
                    ],
                }
                for bar in range(4)
            ],
        }
    )
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(744, 1133)
    browser.show()
    browser.setUrl(QUrl(server.url))
    readings: list[object] = []

    def read_sizes() -> dict[str, object] | None:
        browser.page().runJavaScript(
            """JSON.stringify((() => {
              const plain = document.querySelector('.lyrics:not(.positioned-lyrics)');
              const positioned = document.querySelector('.lyrics.positioned-lyrics');
              if (!plain || !positioned) return null;
              const bar = document.querySelector('.bar-measure');
              const melody = bar.querySelector('.melody-cell').getBoundingClientRect();
              const line = getComputedStyle(bar, '::after');
              const textTop = node => {
                const range = document.createRange();
                range.selectNodeContents(node);
                return range.getBoundingClientRect().top;
              };
              return {
                scale: parseFloat(getComputedStyle(document.documentElement)
                  .getPropertyValue('--font-scale')),
                fitted: document.getElementById('score').style
                  .getPropertyValue('--fitted-lyric-size'),
                plain: parseFloat(getComputedStyle(plain).fontSize),
                positioned: parseFloat(getComputedStyle(positioned).fontSize),
                lyricTopDrift: Math.abs(textTop(plain.firstChild) -
                  textTop(positioned.querySelector('.lyric-unit').firstChild)),
                lineTopDrift: Math.abs(bar.getBoundingClientRect().top +
                  parseFloat(line.top) - melody.top),
                lineHeightDrift: Math.abs(parseFloat(line.height) - melody.height),
                sections: document.querySelectorAll('.section-label').length
              };
            })())""",
            readings.append,
        )
        return json.loads(readings[-1]) if readings and isinstance(readings[-1], str) else None

    try:
        qtbot.waitUntil(lambda: read_sizes() is not None, timeout=10000)
        browser.page().runJavaScript("window.dxBandSetFontScale(1)")
        qtbot.waitUntil(
            lambda: (data := read_sizes()) is not None
            and data["scale"] == 1
            and data["fitted"] == ""
        )
        qtbot.waitUntil(
            lambda: (data := read_sizes()) is not None
            and data["lineTopDrift"] < 1
            and data["lineHeightDrift"] < 1,
            timeout=10000,
        )
        normal = read_sizes()
        assert normal is not None
        assert normal["plain"] >= 13
        assert normal["lyricTopDrift"] < 1
        assert normal["sections"] == 0

        browser.page().runJavaScript("document.getElementById('larger').click()")
        qtbot.waitUntil(
            lambda: (data := read_sizes()) is not None
            and data["scale"] == 1.1
            and data["plain"] > normal["plain"] * 1.09
            and data["positioned"] > normal["positioned"] * 1.09
            and data["lineTopDrift"] < 1
            and data["lineHeightDrift"] < 1
        )

        browser.page().runJavaScript(
            "document.getElementById('smaller').click();"
            "document.getElementById('smaller').click();"
        )
        qtbot.waitUntil(
            lambda: (data := read_sizes()) is not None
            and data["scale"] == 0.9
            and data["plain"] < normal["plain"] * 0.91
            and data["positioned"] < normal["positioned"] * 0.91
            and data["lineTopDrift"] < 1
            and data["lineHeightDrift"] < 1
        )
    finally:
        browser.page().runJavaScript("window.dxBandSetFontScale(1)")
        browser.close()
        server.stop()


def test_long_live_lyrics_keep_the_same_visual_font_size(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    rows: list[dict[str, object]] = []
    for bar in range(4):
        beats: list[dict[str, object]] = []
        for beat in range(4):
            step = 16 * bar + 4 * beat
            item: dict[str, object] = {
                "at_ms": 2000 * bar + 500 * beat,
                "bar_start": beat == 0,
                "start_16th": step,
                "lyrics": "你似季候风还在" if (bar, beat) == (0, 3)
                else "抵" if (bar, beat) == (1, 0) else "",
            }
            if (bar, beat) == (1, 2):
                item["lyrics"] = "将消失了"
                item["lyric_units"] = [
                    {"text": char, "start_16th": step + index}
                    for index, char in enumerate("将消失了")
                ]
                item["melody_notes"] = [
                    {"midi": 60 + index, "start_16th": step + index, "duration_16ths": 1}
                    for index in range(4)
                ]
            beats.append(item)
        rows.append({
            "layout": "bars", "score_bar": True,
            "start_ms": 2000 * bar, "end_ms": 2000 * (bar + 1), "beats": beats,
        })
    server.set_song({
        "title": "歌词宽度测试", "artist": "", "original_key": "C", "bpm": 120,
        "beats_per_bar": 4, "melody_key": 0, "melody_tonic_midi": 60,
        "rows": rows,
    })
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(1024, 768)
    browser.show()
    browser.setUrl(QUrl(server.url))
    readings: list[object] = []

    def read_lyrics() -> dict[str, object] | None:
        browser.page().runJavaScript(
            """JSON.stringify((() => {
              const plain = Array.from(document.querySelectorAll('.lyrics'))
                .find(label => label.textContent === '你似季候风还在');
              const positioned = Array.from(document.querySelectorAll('.lyrics'))
                .find(label => label.textContent === '将消失了');
              const next = Array.from(document.querySelectorAll('.lyrics'))
                .find(label => label.textContent === '抵');
              if (!plain || !positioned || !next) return null;
              return {
                plainFont: getComputedStyle(plain).fontSize,
                positionedFont: getComputedStyle(positioned).fontSize,
                plainTransform: getComputedStyle(plain).transform,
                positionedTransform: getComputedStyle(positioned).transform,
                textWidth: plain.getBoundingClientRect().width,
                cellWidth: plain.closest('.beat-cell').getBoundingClientRect().width,
                gapToNext: next.getBoundingClientRect().left -
                  plain.getBoundingClientRect().right,
                neighborShift: parseFloat(next.style.left) || 0,
                positionedReady: Boolean(positioned.querySelector('.lyric-unit')?.style.left)
              };
            })())""",
            readings.append,
        )
        return json.loads(readings[-1]) if readings and isinstance(readings[-1], str) else None

    try:
        qtbot.waitUntil(
            lambda: (data := read_lyrics()) is not None and data["positionedReady"],
            timeout=10000,
        )
        data = read_lyrics()
        assert data is not None
        assert data["textWidth"] > data["cellWidth"]
        assert data["plainFont"] == data["positionedFont"]
        assert data["plainTransform"] == "none"
        assert data["positionedTransform"] == "none"
        assert data["neighborShift"] > 0
        assert data["gapToNext"] >= 1
    finally:
        browser.close()
        server.stop()


def test_musician_rest_cells_have_no_beat_lights(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    server.set_song(
        {
            "title": "休止拍灯测试",
            "artist": "",
            "original_key": "C",
            "bpm": 120,
            "beats_per_bar": 4,
            "rows": [
                {
                    "layout": "bars",
                    "score_bar": True,
                    "start_ms": 0,
                    "end_ms": 500,
                    "beats": [{"at_ms": 0, "bar_start": True, "rest": True}],
                }
            ],
        }
    )
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(640, 360)
    browser.show()
    browser.setUrl(QUrl(server.url))
    readings: list[object] = []

    def read_without_lights() -> bool | None:
        browser.page().runJavaScript(
            "Boolean(document.querySelector('.beat-cell.rest')) && document.querySelectorAll('.beat-dot').length === 0",
            readings.append,
        )
        return readings[-1] if readings and isinstance(readings[-1], bool) else None

    try:
        qtbot.waitUntil(lambda: read_without_lights() is True, timeout=10000)
    finally:
        browser.close()
        server.stop()


def test_score_chord_stays_above_its_sixteenth_note_after_mode_change(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    server.set_song({
        "title": "谱面位置测试", "artist": "", "original_key": "C", "bpm": 120,
        "beats_per_bar": 4, "melody_key": 0, "melody_tonic_midi": 60,
        "rows": [{
            "layout": "bars", "score_bar": True, "start_ms": 0, "end_ms": 4000,
            "beats": [{
                "at_ms": 0, "bar_start": True, "start_16th": 0,
                "chords": ["1"],
                "chord_modes": {"degree": ["1"], "chord": ["C"], "chord_c": ["C"]},
                "chord_units": [{"start_16th": 2, "chord_modes": {
                    "degree": ["1"], "chord": ["C"], "chord_c": ["C"],
                }}],
                "lyric_units": [{"text": "唱", "start_16th": 2, "at_ms": 500}],
                "lyrics": "唱",
                "melody_notes": [{"midi": 60, "start_16th": 2, "duration_16ths": 2}],
            }, *({"at_ms": index * 1000, "start_16th": index * 4, "lyrics": ""}
                 for index in range(1, 4))],
        }],
    })
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(800, 500)
    browser.show()
    browser.setUrl(QUrl(server.url))
    readings: list[object] = []

    def read_alignment() -> dict[str, object] | None:
        browser.page().runJavaScript("""JSON.stringify((() => {
          const chord = document.querySelector('.chord-unit[data-start16th="2"]');
          const note = document.querySelector('.melody-note[data-start16th="2"] .melody-pitch');
          const lyric = document.querySelector('.lyric-unit[data-start16th="2"]');
          if (!chord || !note || !lyric) return null;
          const center = (element) => { const rect = element.getBoundingClientRect(); return (rect.left + rect.right) / 2; };
          return {chord: center(chord), note: center(note), lyric: center(lyric),
            label: chord.textContent, positioned: Boolean(chord.style.left)};
        })())""", readings.append)
        return json.loads(readings[-1]) if readings and isinstance(readings[-1], str) else None

    try:
        qtbot.waitUntil(
            lambda: (value := read_alignment()) is not None and value["positioned"],
            timeout=10000,
        )
        initial = read_alignment()
        assert initial is not None
        assert initial["label"] == "1"
        assert abs(initial["chord"] - initial["note"]) < 2, initial
        assert abs(initial["lyric"] - initial["note"]) < 2, initial
        browser.page().runJavaScript('''(() => { const select = document.querySelector("#chordKeySelect");
          select.value = "key:C"; select.dispatchEvent(new Event("change", {bubbles: true})); })()''')
        qtbot.waitUntil(
            lambda: (value := read_alignment()) is not None
            and value["label"] == "C" and abs(value["chord"] - value["note"]) < 2
            and abs(value["lyric"] - value["note"]) < 2,
            timeout=10000,
        )
    finally:
        browser.close()
        server.stop()


def test_meter_label_sits_on_barline_without_covering_chord(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    server.set_song({
        "title": "拍号位置测试", "artist": "", "original_key": "C", "bpm": 120,
        "beats_per_bar": 4, "melody_key": 0, "melody_tonic_midi": 60,
        "rows": [
            {
                "layout": "bars", "score_bar": True, "start_ms": 0, "end_ms": 4000,
                "beats": [
                    {"at_ms": index * 1000, "bar_start": index == 0, "lyrics": ""}
                    for index in range(4)
                ],
            },
            {
                "layout": "bars", "score_bar": True, "start_ms": 4000, "end_ms": 7000,
                "meter": "3/4",
                "beats": [
                    {
                        "at_ms": 4000 + index * 1000, "bar_start": index == 0,
                        "lyrics": "", "chords": ["3"] if index == 0 else [],
                        "chord_modes": {
                            "degree": ["3"] if index == 0 else [],
                            "chord": ["E"] if index == 0 else [],
                            "chord_c": ["E"] if index == 0 else [],
                        },
                    }
                    for index in range(3)
                ],
            },
        ],
    })
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(800, 500)
    browser.show()
    browser.setUrl(QUrl(server.url))
    readings: list[object] = []

    def read_positions() -> dict[str, object] | None:
        browser.page().runJavaScript("""JSON.stringify((() => {
          const measure = document.querySelector('.bar-measure[data-meter="3/4"]');
          const meter = measure?.querySelector('.meter-label');
          const chord = measure?.querySelector('.chord-token');
          if (!measure || !meter || !chord) return null;
          const m = measure.getBoundingClientRect();
          const l = meter.getBoundingClientRect();
          const c = chord.getBoundingClientRect();
          return {
            divider: m.left,
            labelCenter: (l.left + l.right) / 2,
            labelRight: l.right,
            chordLeft: c.left,
            overlap: l.left < c.right && l.right > c.left &&
              l.top < c.bottom && l.bottom > c.top,
          };
        })())""", readings.append)
        return json.loads(readings[-1]) if readings and isinstance(readings[-1], str) else None

    try:
        qtbot.waitUntil(lambda: read_positions() is not None, timeout=10000)
        positions = read_positions()
        assert positions is not None
        assert abs(positions["labelCenter"] - positions["divider"]) <= 1
        assert positions["overlap"] is False
        assert positions["labelRight"] < positions["chordLeft"]
    finally:
        browser.close()
        server.stop()


def test_musician_score_can_scroll_and_resume_following(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    server.set_song(
        {
            "title": "滚动测试",
            "artist": "测试歌手",
            "original_key": "C",
            "bpm": 120,
            "beats_per_bar": 4,
            "rows": [
                {
                    "layout": "bars",
                    "score_bar": True,
                    "start_ms": 2000 * bar,
                    "end_ms": 2000 * (bar + 1),
                    "beats": [
                        {"at_ms": 2000 * bar, "bar_start": True, "lyrics": f"第{bar + 1}小节"}
                    ],
                }
                for bar in range(12)
            ],
        }
    )
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(640, 360)
    browser.show()
    browser.setUrl(QUrl(server.url))
    try:
        readings: list[object] = []

        def read_scroll() -> dict[str, object] | None:
            browser.page().runJavaScript(
                """JSON.stringify((() => {
                  const stage = document.getElementById('stage');
                  if (!stage) return null;
                  return {
                    rows: document.querySelectorAll('.score-row').length,
                    top: stage.scrollTop,
                    max: stage.scrollHeight - stage.clientHeight,
                    overflow: getComputedStyle(stage).overflowY,
                    transform: getComputedStyle(document.getElementById('score')).transform,
                    railHidden: document.getElementById('scrollRail').hidden,
                    followHidden: document.getElementById('followPlayback').hidden
                  };
                })())""",
                readings.append,
            )
            return json.loads(readings[-1]) if readings and isinstance(readings[-1], str) else None

        qtbot.waitUntil(
            lambda: (data := read_scroll()) is not None
            and data["rows"] == 12
            and data["max"] > 200
            and data["railHidden"] is False
        )
        data = read_scroll()
        assert data is not None
        assert data["max"] > 200
        assert data["overflow"] == "scroll"
        assert data["transform"] == "none"
        assert data["railHidden"] is False

        server.set_transport(state="playing", position_ms=12000)
        qtbot.waitUntil(lambda: (data := read_scroll()) is not None and data["top"] > 150)
        browser.page().runJavaScript(
            "const stage = document.getElementById('stage');"
            "stage.dispatchEvent(new WheelEvent('wheel', {deltaY: -400, bubbles: true}));"
            "stage.scrollTop = 0;"
        )
        qtbot.waitUntil(
            lambda: (data := read_scroll()) is not None
            and data["top"] == 0
            and data["followHidden"] is False
        )
        qtbot.wait(120)
        data = read_scroll()
        assert data is not None and data["top"] == 0

        browser.page().runJavaScript("document.getElementById('followPlayback').click()")
        qtbot.waitUntil(
            lambda: (data := read_scroll()) is not None
            and data["top"] > 150
            and data["followHidden"] is True
        )
    finally:
        browser.close()
        server.stop()


def test_musician_low_octave_dots_keep_duration_lines_aligned(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    note_groups = (
        ((48, 0, 2), (60, 2, 2)),
        ((60, 0, 2), (62, 2, 2)),
        ((48, 0, 1), (60, 1, 1), (62, 2, 1), (64, 3, 1)),
        ((60, 0, 1), (61, 1, 1), (64, 2, 1), (65, 3, 1)),
    )
    server.set_song(
        {
            "title": "低音下划线测试",
            "artist": "",
            "original_key": "C",
            "bpm": 120,
            "beats_per_bar": 4,
            "melody_key": 0,
            "melody_tonic_midi": 60,
            "rows": [
                {
                    "layout": "bars",
                    "score_bar": True,
                    "start_ms": 2000 * bar,
                    "end_ms": 2000 * (bar + 1),
                    "beats": [
                        {
                            "at_ms": 2000 * bar,
                            "bar_start": True,
                            "melody_notes": [
                                {
                                    "midi": midi,
                                    "start_16th": 16 * bar + start,
                                    "duration_16ths": duration,
                                }
                                for midi, start, duration in notes
                            ],
                        }
                    ],
                }
                for bar, notes in enumerate(note_groups)
            ],
        }
    )
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(1024, 768)
    browser.show()
    browser.setUrl(QUrl(server.url))
    try:
        readings: list[object] = []

        def read_lines() -> dict[str, object] | None:
            browser.page().runJavaScript(
                """JSON.stringify((() => {
                  const grid = document.querySelector('.bar-grid');
                  if (!grid) return null;
                  const tops = level => Array.from(grid.querySelectorAll(
                    `.melody-beam-line[data-level="${level}"]`
                  )).map(line => line.getBoundingClientRect().top);
                  return {
                    bars: grid.querySelectorAll('.bar-measure').length,
                    first: tops(1),
                    second: tops(2),
                    lowDots: Array.from(grid.querySelectorAll('.melody-octave.down'))
                      .map(dot => dot.getBoundingClientRect().bottom),
                    accidentals: Array.from(grid.querySelectorAll('.melody-pitch.has-accidental'))
                      .map(pitch => {
                        const accidental = pitch.querySelector('.melody-accidental').getBoundingClientRect();
                        const number = pitch.querySelector('.melody-number').getBoundingClientRect();
                        return {above: accidental.top < number.top, left: accidental.right <= number.left + 3};
                      })
                  };
                })())""",
                readings.append,
            )
            return json.loads(readings[-1]) if readings and isinstance(readings[-1], str) else None

        qtbot.waitUntil(
            lambda: (data := read_lines()) is not None
            and data["bars"] == 4
            and len(data["first"]) >= 4
            and len(data["second"]) >= 2
        )
        data = read_lines()
        assert data is not None
        assert len(data["lowDots"]) == 2
        assert max(data["first"]) - min(data["first"]) < 1
        assert max(data["second"]) - min(data["second"]) < 1
        assert min(data["first"]) - max(data["lowDots"]) >= 2
        assert data["accidentals"] and all(
            accidental["above"] and accidental["left"] for accidental in data["accidentals"]
        )
    finally:
        browser.close()
        server.stop()


def test_musician_rest_duration_lines_align_with_note_beams(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.url is not None
    events = [
        [{"kind": "note", "midi": 60, "start_16th": step, "duration_16ths": 2}
         for step in (0, 2)],
        [
            {"kind": "rest", "start_16th": 4, "duration_16ths": 2},
            {"kind": "note", "midi": 62, "start_16th": 6, "duration_16ths": 2},
        ],
        [
            {"kind": "rest", "start_16th": 8, "duration_16ths": 1},
            *({"kind": "note", "midi": 64, "start_16th": step, "duration_16ths": 1}
              for step in (9, 10, 11)),
        ],
        [
            {"kind": "note", "midi": 69, "start_16th": step, "duration_16ths": duration}
            for step, duration in ((12, 1), (13, 2), (15, 1))
        ],
    ]
    server.set_song({
        "title": "休止符下划线测试", "artist": "", "original_key": "C", "bpm": 120,
        "beats_per_bar": 4, "melody_key": 0, "melody_tonic_midi": 60,
        "rows": [{
            "layout": "bars", "score_bar": True, "start_ms": 0, "end_ms": 4000,
            "beats": [
                {"at_ms": index * 1000, "bar_start": index == 0,
                 "start_16th": index * 4, "melody_events": beat_events, "triplet": index == 3}
                for index, beat_events in enumerate(events)
            ],
        }],
    })
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.setFixedSize(1024, 768)
    browser.show()
    browser.setUrl(QUrl(server.url))
    try:
        readings: list[object] = []

        def read_lines() -> dict[str, object] | None:
            browser.page().runJavaScript(
                """JSON.stringify((() => {
                  const grid = document.querySelector('.bar-grid');
                  if (!grid) return null;
                  const tops = selector => Array.from(grid.querySelectorAll(selector))
                    .map(line => line.getBoundingClientRect().top);
                  const triplet = grid.querySelector('.melody-triplet');
                  return {
                    first: tops('.melody-beam-line[data-level="1"]'),
                    second: tops('.melody-beam-line[data-level="2"]'),
                    rests: tops('.melody-beam-line.rest-beam'),
                    triplet: triplet?.querySelectorAll('.melody-note').length ?? 0,
                    numeral: triplet ? getComputedStyle(triplet, '::before').content : ''
                  };
                })())""",
                readings.append,
            )
            return json.loads(readings[-1]) if readings and isinstance(readings[-1], str) else None

        qtbot.waitUntil(
            lambda: (data := read_lines()) is not None
            and len(data["first"]) >= 3
            and len(data["second"]) >= 2
            and len(data["rests"]) == 3
            and data["triplet"] == 3
        )
        data = read_lines()
        assert data is not None
        assert max(data["first"]) - min(data["first"]) < 1
        assert max(data["second"]) - min(data["second"]) < 1
        assert data["numeral"] == '"3"'
    finally:
        browser.close()
        server.stop()


def test_local_musician_exports_adaptive_bars_per_pdf_row(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "乐手谱.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(pdf_path), "PDF 文件 (*.pdf)"),
    )
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.local_url is not None
    def beats(bar: int) -> list[dict[str, object]]:
        count = 3 + bar % 3
        return [
            {
                "at_ms": 2000 * bar + round(2000 * beat / count),
                "bar_start": beat == 0,
                "chord_modes": {"degree": ["1"], "chord": ["C"], "chord_c": ["C"]},
                "lyrics": "你我他" if bar == 5 else "我" if beat == 0 else "",
                "lyric_units": (
                    [{"text": "我", "start_16th": 24 * bar}]
                    if beat == 0 and bar % 2 and bar != 5 else []
                ),
                "melody_notes": [
                    {"midi": 60 + note, "start_16th": 24 * bar + 4 * beat + note,
                     "duration_16ths": 1 if count == 5 and beat == count - 1 else 4}
                    for note in range(4 if count == 5 and beat == count - 1 else 1)
                ],
            }
            for beat in range(count)
        ]
    server.set_song(
        {
            "title": "测试歌曲",
            "artist": "测试歌手",
            "original_key": "D",
            "bpm": 120,
            "beats_per_bar": 4,
            "melody_reference": "D4",
            "melody_transpose": 2,
            "melody_key": 2,
            "melody_tonic_midi": 62,
            "rows": [
                {
                    "layout": "bars",
                    "score_bar": True,
                    "section": "主歌" if bar == 0 else "",
                    "start_ms": 2000 * bar,
                    "end_ms": 2000 * (bar + 1),
                    "beats": beats(bar),
                }
                for bar in range(45)
            ],
        }
    )
    window = WebMusicianWindow(server.local_url, 32)
    qtbot.addWidget(window)
    window.show()
    try:
        print_layout: list[object] = []
        original_pdf_ready = window._on_pdf_ready
        inspection_started = False

        def inspect_pdf_layout(ready: object) -> None:
            nonlocal inspection_started
            if ready is not True or inspection_started or window._pdf_browser is None:
                original_pdf_ready(ready)
                return
            inspection_started = True
            window._pdf_ready_timer.stop()

            def complete_inspection(value: object) -> None:
                print_layout.append(value)
                original_pdf_ready(ready)

            window._pdf_browser.page().runJavaScript(
                """JSON.stringify((() => {
                  const rows = Array.from(document.querySelectorAll('.pdf-bar-grid'));
                  const positions = rows.map(row => Array.from(
                    row.querySelectorAll('.bar-measure')
                  ).map(bar => bar.getBoundingClientRect().left));
                  const rowBars = positions.map(row => row.length);
                  const misaligned = positions.flatMap(row => {
                    const reference = positions.find(other => other.length === row.length);
                    return row.map((x, index) => Math.abs(x - reference[index]));
                  }).filter(error => error > 1).length;
                  const overlaps = Array.from(document.querySelectorAll(
                    '.beat-cell .melody-group'
                  )).filter(group => {
                    const notes = group.querySelectorAll('.melody-note');
                    if (!notes.length) return false;
                    const cell = group.closest('.beat-cell').getBoundingClientRect();
                    return notes[0].getBoundingClientRect().left < cell.left + 1 ||
                      notes[notes.length - 1].getBoundingClientRect().right > cell.right - 1;
                  }).length;
                  const lyricTops = rows.map(row => Array.from(row.querySelectorAll('.lyrics'))
                    .filter(label => label.textContent.trim()).map(label => {
                      const text = label.querySelector('.lyric-unit')?.firstChild ||
                        label.firstChild;
                      const range = document.createRange();
                      range.selectNodeContents(text);
                      return range.getBoundingClientRect().top;
                    }));
                  const lyricTopDrift = Math.max(0, ...lyricTops.map(tops =>
                    Math.max(...tops) - Math.min(...tops)));
                  const smallLyrics = Array.from(document.querySelectorAll('.lyrics'))
                    .filter(label => label.textContent.trim() &&
                      parseFloat(getComputedStyle(label).fontSize) < 16).length;
                  const lyricCollisions = rows.reduce((count, grid) => {
                    const bounds = grid.getBoundingClientRect();
                    const labels = Array.from(grid.querySelectorAll('.lyrics'))
                      .filter(label => label.textContent.trim());
                    const rects = labels.flatMap(label => label.classList.contains('positioned-lyrics')
                      ? Array.from(label.querySelectorAll('.lyric-unit')).map(unit => unit.getBoundingClientRect())
                      : [label.getBoundingClientRect()]).sort((left, right) => left.left - right.left);
                    return count + rects.filter((rect, index) =>
                      rect.left < bounds.left + 1 || rect.right > bounds.right - 1 ||
                      (index + 1 < rects.length && rect.right + 1 > rects[index + 1].left)
                    ).length;
                  }, 0);
                  const visibleSections = Array.from(document.querySelectorAll('.section-label'))
                    .filter(label => getComputedStyle(label).display !== 'none').length;
                  return {misaligned, overlaps, rows: rows.length, rowBars,
                    lyricTopDrift, smallLyrics, lyricCollisions, visibleSections};
                })())""",
                complete_inspection,
            )

        monkeypatch.setattr(window, "_on_pdf_ready", inspect_pdf_layout)
        row_counts: list[object] = []

        def read_rows() -> None:
            window.browser.page().runJavaScript(
                "JSON.stringify([document.querySelectorAll('.score-row').length, "
                "document.querySelectorAll('.beat-cell').length])",
                row_counts.append,
            )

        def rows_loaded() -> bool:
            read_rows()
            return (
                bool(row_counts)
                and isinstance(row_counts[-1], str)
                and json.loads(row_counts[-1])[1] == 180
            )

        qtbot.waitUntil(rows_loaded, timeout=10000)
        initial_rows = json.loads(row_counts[-1])[0]
        window.browser.page().runJavaScript(
            "window.__pdfLayoutChanges = [];"
            "new MutationObserver(() => window.__pdfLayoutChanges.push('root'))"
            ".observe(document.documentElement, {attributes: true, attributeFilter: ['class']});"
            "new MutationObserver(() => window.__pdfLayoutChanges.push('score'))"
            ".observe(document.getElementById('score'), {childList: true});"
        )
        window.browser.page().runJavaScript("document.getElementById('exportPdf').click()")
        qtbot.waitUntil(lambda: pdf_path.exists() and pdf_path.stat().st_size > 1000, timeout=20000)
        qtbot.waitUntil(lambda: not window._pdf_exporting, timeout=20000)
        assert print_layout
        layout = json.loads(print_layout[-1])
        assert layout["misaligned"] == 0
        assert layout["overlaps"] == 0
        assert layout["rows"] == 13
        assert layout["rowBars"].count(2) == 2
        assert layout["rowBars"].count(4) == 10
        assert layout["rowBars"].count(1) == 1
        assert layout["lyricTopDrift"] < 1
        assert layout["smallLyrics"] == 0
        assert layout["lyricCollisions"] == 0
        assert layout["visibleSections"] == 0
        unchanged_layout: list[object] = []
        def read_unchanged_layout() -> bool:
            window.browser.page().runJavaScript(
                "JSON.stringify([window.__pdfLayoutChanges, "
                "document.querySelectorAll('.score-row').length, "
                "document.documentElement.classList.contains('pdf-export')])",
                unchanged_layout.append,
            )
            return (
                bool(unchanged_layout)
                and isinstance(unchanged_layout[-1], str)
                and unchanged_layout[-1].startswith("[")
            )

        qtbot.waitUntil(read_unchanged_layout, timeout=10000)
        assert json.loads(unchanged_layout[-1]) == [[], initial_rows, False]
        pdf = QPdfDocument()
        assert pdf.load(str(pdf_path)) == QPdfDocument.Error.None_
        assert pdf.pageCount() >= 2
        first_page_text = pdf.getAllText(0).text()
        assert "大象乐队工作站" in first_page_text
        assert "DX Band" in first_page_text
        assert "www.dx-band.site" in first_page_text
        assert "测试歌曲" in first_page_text
        assert "测试歌手" in first_page_text
        assert "1=D4" in first_page_text
        assert "移调+2" in first_page_text
        assert "主歌" not in first_page_text
        all_rows: list[list[QRectF]] = []
        for page in range(pdf.pageCount()):
            page_text = pdf.getAllText(page).text()
            assert "大象乐队工作站" in page_text
            assert "DX Band" in page_text
            assert "www.dx-band.site" in page_text
            lyric_positions = [
                pdf.getSelectionAtIndex(page, index, 1).boundingRectangle()
                for index, character in enumerate(page_text)
                if character == "我"
            ]
            rows: dict[int, list[QRectF]] = {}
            for position in lyric_positions:
                rows.setdefault(round(position.y()), []).append(position)
            all_rows.extend(rows.values())
        assert [len(row) for row in all_rows] == [4, 6, 2] + [4] * 9 + [1]
        pdf.close()
    finally:
        window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        server.stop()


def test_browser_musician_pdf_uses_separate_page(qtbot: QtBot) -> None:
    server = WebMusicianServer()
    server.start(preferred_port=0)
    assert server.local_url is not None
    server.set_song(
        {
            "title": "浏览器测试",
            "artist": "",
            "original_key": "C",
            "bpm": 120,
            "beats_per_bar": 4,
            "rows": [
                {
                    "layout": "bars",
                    "score_bar": True,
                    "start_ms": 0,
                    "end_ms": 2000,
                    "beats": [{"at_ms": 0, "bar_start": True, "lyrics": "我"}],
                }
            ],
        }
    )
    browser = QWebEngineView()
    qtbot.addWidget(browser)
    browser.show()
    browser.setUrl(QUrl(server.local_url.split("?", 1)[0]))
    try:
        rows: list[object] = []

        def loaded() -> bool:
            browser.page().runJavaScript(
                "document.querySelectorAll('.score-row').length", rows.append
            )
            return bool(rows) and rows[-1] == 1

        qtbot.waitUntil(loaded, timeout=10000)
        result: list[object] = []
        browser.page().runJavaScript(
            "window.open = url => { window.__pdfUrl = url; return {}; };"
            "document.getElementById('exportPdf').click();"
            "JSON.stringify([window.__pdfUrl, "
            "document.documentElement.classList.contains('pdf-export'), "
            "document.querySelectorAll('.score-row').length])",
            result.append,
        )
        qtbot.waitUntil(lambda: bool(result), timeout=10000)
        opened_url, changed_layout, row_count = json.loads(result[-1])
        assert "pdf=1" in opened_url
        assert "offline=1" in opened_url
        assert not changed_layout
        assert row_count == 1
    finally:
        browser.close()
        server.stop()

# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband import __version__
from dxband.ui.branding import APP_ICON_PATH
from dxband.ui.main_window import MainWindow
from dxband.ui.render.web_musician_window import WebMusicianWindow


def test_chord_backfill_prompt_starts_batch_and_progress(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    missing = (object(), object())
    started: list[object] = []
    monkeypatch.setattr(
        window.library_controller, "missing_chord_packages", lambda: missing
    )
    monkeypatch.setattr(
        window.library_controller,
        "start_chord_backfill",
        lambda packages: started.append(packages) or True,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    window.settings_page.chord_fill_button.click()

    assert started == [missing]
    assert window.settings_page.chord_fill_progress.maximum() == 2
    assert window.settings_page.chord_fill_progress.value() == 0


def test_main_window_opens_playback_with_embedded_playlist(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.navigation.count() == 3
    assert window.pages.count() == 4
    assert [window.navigation.item(index).text() for index in range(3)] == [
        "播放控制",
        "歌曲库",
        "设置",
    ]
    assert all(
        not window.navigation.item(index).icon().isNull()
        for index in range(window.navigation.count())
    )
    sidebar_text = " ".join(label.text() for label in window.findChildren(QLabel))
    assert "LOCAL AUDIO ENGINE" not in sidebar_text
    assert "DX STAGE M10" not in sidebar_text

    assert window.pages.currentWidget() is window.playback_page
    assert window.navigation.currentRow() == 0
    assert window.playlist_page.parentWidget() is window.playback_page
    assert window.playlist_page.property("embedded") is True
    assert window.centralWidget().objectName() == "applicationRoot"
    assert window.playback_page.play_button.property("role") == "play"
    assert window.playback_page.song_label.objectName() == "songTitle"
    assert window.windowTitle() == "大象乐队工作站 · DX Band"
    assert window.brand_title.text() == "DX BAND"
    assert window.brand_subtitle.text() == "大象乐队工作站"
    assert window.version_label.text() == f"版本 {__version__}"
    assert window.version_label.objectName() == "sidebarVersion"
    assert not window.windowIcon().isNull()
    assert window.brand_icon.pixmap() is not None
    assert not window.brand_icon.pixmap().isNull()
    assert window.brand_icon.pixmap().width() == window.brand_icon.width()
    assert window.brand_icon.pixmap().height() <= window.brand_icon.height()

    app_icon = QImage(str(APP_ICON_PATH))
    black_background = app_icon.pixelColor(app_icon.width() // 2, 100)
    assert black_background.alpha() == 255
    assert (
        max(
            black_background.red(),
            black_background.green(),
            black_background.blue(),
        )
        < 20
    )
    assert app_icon.pixelColor(40, app_icon.height() // 2).alpha() == 0
    assert app_icon.pixelColor(100, app_icon.height() // 2).alpha() == 255


def test_library_create_button_opens_creation_and_can_return(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.navigation.setCurrentRow(1)
    window.library_page.create_button.click()
    assert window.pages.currentWidget() is window.create_song_page
    assert window.navigation.currentRow() == 1

    window.creation_controller.creation_active_changed.emit(True)
    assert window.library_page.create_button.text() == "查看创建进度"
    window.create_song_page.back_button.click()
    assert window.pages.currentWidget() is window.library_page
    window.library_page.create_button.click()
    assert window.pages.currentWidget() is window.create_song_page
    window.navigation.itemClicked.emit(window.navigation.item(1))
    assert window.pages.currentWidget() is window.library_page

    window.creation_controller.creation_active_changed.emit(False)
    assert window.library_page.create_button.text() == "创建歌曲"


def test_created_song_opens_the_existing_song_editor(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    created_path = Path("/tmp/created-song")
    edit_requests: list[Path] = []
    window.library_controller.edit_path = edit_requests.append  # type: ignore[method-assign]

    window.pages.setCurrentWidget(window.create_song_page)
    window.creation_controller.song_created.emit(created_path)

    assert window.pages.currentWidget() is window.library_page
    assert window.navigation.currentRow() == 1
    assert edit_requests == [created_path]


def test_space_toggles_playback_only_on_playback_page(qtbot: QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.playback_page.play_button.setEnabled(True)
    requests: list[bool] = []
    window.playback_page.play_pause_requested.connect(lambda: requests.append(True))

    window.activateWindow()
    QApplication.processEvents()
    window.setFocus()
    qtbot.keyClick(window, Qt.Key.Key_Space)
    assert requests == [True]

    window.navigation.setCurrentRow(1)
    qtbot.keyClick(window, Qt.Key.Key_Space)
    assert requests == [True]

    window.navigation.setCurrentRow(0)
    editor = QLineEdit(window.playback_page)
    editor.show()
    editor.setFocus()
    qtbot.keyClick(editor, Qt.Key.Key_Space)
    assert requests == [True]
    assert editor.text() == " "


def test_main_window_can_open_browser_musician_output(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    window = MainWindow()
    window.show()
    server = window.playback_controller._web_musician_server
    manager = window.playback_controller.screen_manager
    try:
        server.start(preferred_port=0)
        url = server.local_url
        assert url is not None
        manager.open_web_musician_output(url, manager.descriptors()[0].fingerprint)
        assert isinstance(manager.musician_window, WebMusicianWindow)
        qtbot.waitUntil(lambda: len(server._subscribers) == 1, timeout=10000)
    finally:
        window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()

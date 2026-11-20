# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband import __version__
from dxband.constants import TrackKind
from dxband.ui import main_window
from dxband.ui.branding import APP_ICON_PATH
from dxband.ui.i18n import UiTranslator
from dxband.ui.main_window import MainWindow
from dxband.ui.render.web_musician_window import WebMusicianWindow
from dxband.ui.services.settings_service import SettingsService


def test_language_changes_immediately_without_restart(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    service = SettingsService(QSettings(str(tmp_path / "language.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr(main_window, "SettingsService", lambda: service)
    translator = UiTranslator(application)
    window = MainWindow(translator=translator)
    qtbot.addWidget(window)
    window.show()
    translator.set_language("zh")

    window.settings_page.language_combo.setCurrentIndex(
        window.settings_page.language_combo.findData("en")
    )
    assert service.load_language() == "en"
    assert window.navigation.item(0).text() == "Playback"
    assert window.brand_subtitle.text() == "Power by Siwen"
    assert window.playback_page.track_checks[TrackKind.VOCALS].label == "Vocals"
    assert window.playback_page.audience_output_button.label == "Audience"
    assert window.playback_page.current_lyric_label.text() == "Current: —"
    assert window.playback_controller._web_singer_server._state["language"] == "en"
    window.playback_page.set_empty_playlist()
    translator.translate_all()
    assert window.playback_page.song_label.text() == "The playlist is empty; add a song first"
    window.playback_page.set_song("歌词", "", 1000)
    translator.translate_all()
    assert window.playback_page.song_label.text() == "歌词"
    window.playback_page.music_info_label.setText("原KEY Fm  ·  63 BPM")
    translator.translate_all()
    assert window.playback_page.music_info_label.text() == "Original key Fm · 63 BPM"

    window.settings_page.language_combo.setCurrentIndex(
        window.settings_page.language_combo.findData("zh")
    )
    assert service.load_language() == "zh"
    assert window.navigation.item(0).text() == "播放控制"
    assert window.brand_subtitle.text() == "大象乐队工作站"
    assert window.playback_page.track_checks[TrackKind.VOCALS].label == "人声"
    assert window.playback_page.audience_output_button.label == "观众"
    assert window.playback_page.current_lyric_label.text() == "当前句：—"
    assert window.playback_page.song_label.text() == "歌词"
    assert window.playback_page.music_info_label.text() == "原KEY Fm  ·  63 BPM"


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

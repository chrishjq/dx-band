# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtWidgets import QApplication, QLabel, QSpinBox, QTableWidget, QTableWidgetItem
from pytestqt.qtbot import QtBot

from dxband.services.web_singer_server import WebSingerServer
from dxband.ui.i18n import UiTranslator, english
from dxband.ui.render.musician_widget import MusicianWidget
from dxband.ui.render.singer_widget import SingerWidget
from dxband.ui.render.web_singer_window import WebSingerWindow


def test_english_translates_interface_text_without_changing_song_text(qtbot: QtBot) -> None:
    heading = QLabel("设置")
    lyric = QLabel("当前句：播放")
    lyric.setObjectName("currentLyric")
    song_title = QLabel("歌词")
    song_title.setObjectName("songTitle")
    spin = QSpinBox()
    spin.setSpecialValueText("未设置")
    library = QTableWidget(1, 7)
    library.setObjectName("songLibraryTable")
    library.setItem(0, 0, QTableWidgetItem("歌词"))
    library.setItem(0, 6, QTableWidgetItem("已加入"))
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    translator = UiTranslator(application)
    translator.language = "en"
    for widget in (heading, lyric, song_title, spin, library):
        qtbot.addWidget(widget)
        translator._translate_widget(widget)

    assert heading.text() == "Settings"
    assert lyric.text() == "Current: 播放"
    assert song_title.text() == "歌词"
    assert spin.specialValueText() == "Not Set"
    assert library.item(0, 0).text() == "歌词"
    assert library.item(0, 6).text() == "Added"
    assert english("修改和弦 · 傻女") == "Edit Chords · 傻女"
    assert english("阶段：正在分离音轨") == "Stage: Separating audio stems"
    assert english("已加入 3 首歌曲") == "Added 3 songs"

    translator.language = "zh"
    for widget in (heading, lyric, song_title, spin, library):
        translator._translate_widget(widget)
    assert heading.text() == "设置"
    assert lyric.text() == "当前句：播放"
    assert library.item(0, 6).text() == "已加入"


def test_desktop_stage_labels_follow_selected_language(qtbot: QtBot) -> None:
    singer = SingerWidget(language="en")
    musician = MusicianWidget(language="en")
    qtbot.addWidget(singer)
    qtbot.addWidget(musician)
    for screen in (singer, musician):
        screen.set_music_info("C", 120)
        assert screen.music_info_text == "Original key C · 120 BPM"


def test_translator_does_not_scan_webengine_widgets(qtbot: QtBot) -> None:
    application = QApplication.instance()
    assert isinstance(application, QApplication)
    server = WebSingerServer(language="en")
    server.start(preferred_port=0)
    assert server.local_url is not None
    window = WebSingerWindow(server.local_url, 42)
    qtbot.addWidget(window)
    translator = UiTranslator(application)
    try:
        window.show()
        translator.set_language("en")
        qtbot.wait(400)
        assert window.windowTitle() == "Singer Screen (F11 for full screen)"
        translator.set_language("zh")
        assert window.windowTitle() == "歌手屏（F11 全屏）"
    finally:
        window.close()
        server.stop()



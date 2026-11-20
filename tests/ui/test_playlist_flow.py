# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband.services.playlist_service import PlaylistService
from dxband.ui import main_window
from dxband.ui.services.settings_service import SettingsService


def _copy_song(source: Path, song_id: str, title: str) -> Path:
    destination = source.parent / song_id
    shutil.copytree(source, destination)
    song_path = destination / "song.json"
    payload = json.loads(song_path.read_text(encoding="utf-8"))
    payload.update(song_id=song_id, title=title)
    song_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    lyrics_path = destination / "lyrics.json"
    lyrics_payload = json.loads(lyrics_path.read_text(encoding="utf-8"))
    lyrics_payload["title"] = title
    lyrics_path.write_text(json.dumps(lyrics_payload, ensure_ascii=False), encoding="utf-8")
    return destination


def test_playlist_manual_next_stays_stopped_and_auto_next_plays(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    first_path = package_factory()
    second_id = "20260930-193001-b1c2d3e4"
    second_path = _copy_song(first_path, second_id, "第二首歌")

    settings = QSettings(str(tmp_path / "playlist.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path))
    settings_service = SettingsService(settings)
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    window = main_window.MainWindow()
    qtbot.addWidget(window)

    window._add_to_playlist((first_path, second_path))
    assert window.playlist_service.load() == (first_path.name, second_id)
    window.playback_controller._package = window._available_songs[first_path.name]
    window._refresh_playlist()
    playing_color = QColor("#173a2b")
    assert all(
        window.playlist_page.song_list.item(0, column).background().color() == playing_color
        for column in range(4)
    )
    assert all(window.playlist_page.song_list.item(0, column).font().bold() for column in range(4))
    assert all(
        window.playlist_page.song_list.item(1, column).background().color() != playing_color
        for column in range(4)
    )
    assert window.playback_page.next_song_label.text() == "下一首：第二首歌 — 测试歌手"
    assert window.playback_page.next_song_button.isEnabled()
    assert not window.playback_page.previous_song_button.isEnabled()

    requests: list[tuple[Path, bool]] = []
    stopped: list[bool] = []
    monkeypatch.setattr(
        window.library_controller,
        "load_path",
        lambda path, auto_play=False: requests.append((path, auto_play)),
    )
    monkeypatch.setattr(
        window.playback_controller,
        "stop_for_song_change",
        lambda: stopped.append(True),
    )
    window.playback_page.auto_play_next_check.setChecked(True)
    assert settings_service.load_auto_play_next()

    window.playback_page.next_song_button.click()
    assert requests == [(second_path, False)]
    assert stopped == [True]

    window._song_finished()
    assert requests[-1] == (second_path, True)
    assert len(stopped) == 1

    window.playback_controller._package = window._available_songs[second_id]
    window._refresh_playlist()
    assert not window.playback_page.next_song_button.isEnabled()
    assert "暂无后续歌曲" in window.playback_page.next_song_label.text()
    assert window.playback_page.previous_song_button.isEnabled()
    assert "测试歌曲" in window.playback_page.previous_song_button.toolTip()

    window.playback_page.previous_song_button.click()
    assert requests[-1] == (first_path, False)
    assert stopped == [True, True]
    window.close()


def test_library_double_click_opens_editor_without_changing_playlist_or_playing(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    first_path = package_factory()
    second_id = "20260930-193001-b1c2d3e4"
    second_path = _copy_song(first_path, second_id, "第二首歌")

    settings = QSettings(str(tmp_path / "playlist-duplicate.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path))
    monkeypatch.setattr(main_window, "SettingsService", lambda: SettingsService(settings))
    window = main_window.MainWindow()
    qtbot.addWidget(window)
    window._add_to_playlist((first_path, second_path))
    window.playback_controller._package = window._available_songs[first_path.name]
    window._refresh_playlist()
    playlist_before = window.playlist_service.load()
    current_index_before = window._current_playlist_index
    pending_before = window._pending_playlist_entry

    load_requests: list[tuple[Path, bool]] = []
    edit_requests: list[Path] = []
    monkeypatch.setattr(
        window.library_controller,
        "load_path",
        lambda path, auto_play=False: load_requests.append((path, auto_play)),
    )
    monkeypatch.setattr(window.library_controller, "edit_path", edit_requests.append)
    row = next(
        row
        for row in range(window.library_page.song_list.rowCount())
        if window.library_page.song_list.item(row, 0).toolTip() == str(second_path)
    )
    window.library_page.song_list.cellDoubleClicked.emit(row, 0)

    assert edit_requests == [second_path]
    assert load_requests == []
    assert window.playlist_service.load() == playlist_before
    assert window._current_playlist_index == current_index_before
    assert window._pending_playlist_entry == pending_before
    window.close()


def test_playback_defaults_to_first_song_in_saved_playlist_without_playing(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    first_path = package_factory()
    second_id = "20260930-193001-b1c2d3e4"
    third_id = "20260930-193002-c1d2e3f4"
    _copy_song(first_path, second_id, "第二首歌")
    _copy_song(first_path, third_id, "第三首歌")
    PlaylistService(tmp_path).add((first_path.name, second_id, third_id))
    settings = QSettings(str(tmp_path / "playlist-default.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path))
    monkeypatch.setattr(main_window, "SettingsService", lambda: SettingsService(settings))
    requests: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        main_window.LibraryController,
        "load_path",
        lambda _controller, path, auto_play=False: requests.append((path, auto_play)),
    )
    window = main_window.MainWindow()
    qtbot.addWidget(window)

    assert requests == [(first_path, False)]
    assert window.playback_page.song_label.text() == "测试歌曲 — 测试歌手"
    assert window.playback_page.state_label.text() == "正在加载"
    assert window.playback_page.next_song_label.text() == "下一首：第二首歌 — 测试歌手"
    assert not window.playback_page.play_button.isEnabled()
    window._refresh_playlist()
    assert requests == [(first_path, False)]
    assert not any(
        button.text() == "加载到播放控制"
        for button in window.playlist_page.findChildren(QPushButton)
    )
    loaded: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        window.playback_controller,
        "load_package",
        lambda package, auto_play=False: loaded.append((package.config.song_id, auto_play)),
    )
    window.library_controller.song_load_requested.emit(
        (window._available_songs[first_path.name], False)
    )
    assert loaded == [(first_path.name, False)]
    assert window._current_playlist_index == 0
    window.close()


def test_adding_first_song_while_on_playback_page_starts_loading_without_playing(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    song_path = package_factory()
    settings = QSettings(str(tmp_path / "playlist-empty.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path))
    monkeypatch.setattr(main_window, "SettingsService", lambda: SettingsService(settings))
    window = main_window.MainWindow()
    qtbot.addWidget(window)
    requests: list[tuple[Path, bool]] = []
    monkeypatch.setattr(
        window.library_controller,
        "load_path",
        lambda path, auto_play=False: requests.append((path, auto_play)),
    )

    window.navigation.setCurrentRow(0)
    assert window.playback_page.song_label.text() == "播放列表为空，请先添加歌曲"
    assert requests == []

    window._add_to_playlist((song_path,))
    assert requests == [(song_path, False)]
    assert window.library_page.song_list.item(0, 6).text() == "已加入"
    assert window.playback_page.song_label.text() == "测试歌曲 — 测试歌手"
    assert window.playback_page.state_label.text() == "正在加载"
    window.close()


def test_explicit_library_load_is_not_replaced_by_default_playlist_song(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    first_path = package_factory()
    second_path = _copy_song(first_path, "20260930-193001-b1c2d3e4", "指定歌曲")
    PlaylistService(tmp_path).add((first_path.name,))
    settings = QSettings(str(tmp_path / "playlist-explicit.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path))
    monkeypatch.setattr(main_window, "SettingsService", lambda: SettingsService(settings))
    window = main_window.MainWindow()
    qtbot.addWidget(window)
    requests: list[Path] = []
    monkeypatch.setattr(
        window.library_controller,
        "load_path",
        lambda path, auto_play=False: requests.append(path),
    )

    window.library_page.load_requested.emit(second_path)
    window.navigation.setCurrentRow(0)

    assert requests == [second_path]
    assert window.playback_page.song_label.text() == "指定歌曲 — 测试歌手"
    window._song_load_failed("测试加载失败")
    assert window.playback_page.state_label.text() == "加载失败"
    window.close()

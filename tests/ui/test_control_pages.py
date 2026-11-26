# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import math
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPlainTextEdit
from pytestqt.qtbot import QtBot

from dxband.constants import TrackKind
from dxband.ui.controllers.creation_controller import CreationController
from dxband.ui.pages.create_song_page import CreateSongPage
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.pages.settings_page import SettingsPage


def test_master_volume_displays_live_percentage(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    values: list[float] = []
    page.master_volume_requested.connect(values.append)

    assert page.volume_value_label.text() == "85%"
    page.volume_slider.setValue(63)
    assert page.volume_value_label.text() == "63%"
    assert values == [0.63]

    page.set_master_volume(0.42)
    assert page.volume_value_label.text() == "42%"
    assert values == [0.63]


def test_each_stem_has_persistent_gain_control(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    values: list[tuple[str, float]] = []
    page.track_gain_requested.connect(lambda track, gain: values.append((track, gain)))

    assert set(page.track_volume_sliders) == set(TrackKind)
    assert all(slider.singleStep() == 10 for slider in page.track_volume_sliders.values())
    page.track_volume_sliders[TrackKind.GUITAR].setValue(54)
    assert page.track_volume_sliders[TrackKind.GUITAR].value() == 50
    assert page.track_volume_labels[TrackKind.GUITAR].text() == "50%"
    assert values[-1][0] == TrackKind.GUITAR.value
    assert values[-1][1] == pytest.approx(-6.0206, abs=0.001)

    page.set_track_gains_db({TrackKind.GUITAR: 20 * math.log10(1.25)})
    assert page.track_volume_sliders[TrackKind.GUITAR].value() == 130
    assert page.track_volume_labels[TrackKind.GUITAR].text() == "130%"
    assert len(values) == 1


def test_muted_track_disables_its_volume_slider(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    values: list[tuple[str, bool]] = []
    page.track_mute_requested.connect(lambda track, muted: values.append((track, muted)))

    page.set_available_tracks(set(TrackKind))
    page.set_track_mutes({TrackKind.BASS: True})
    assert not page.track_volume_sliders[TrackKind.BASS].isEnabled()
    assert not page.track_volume_labels[TrackKind.BASS].isEnabled()
    assert page.track_volume_sliders[TrackKind.PIANO].isEnabled()
    assert values == []

    page.track_checks[TrackKind.BASS].click()
    assert page.track_volume_sliders[TrackKind.BASS].isEnabled()
    assert page.track_volume_labels[TrackKind.BASS].isEnabled()
    assert values == [(TrackKind.BASS.value, False)]

    page.set_available_tracks(set(TrackKind) - {TrackKind.PIANO})
    page.set_track_mutes({TrackKind.PIANO: False})
    assert not page.track_volume_sliders[TrackKind.PIANO].isEnabled()


def test_playback_bpm_uses_song_tempo_and_resets_on_song_change(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    values: list[int] = []
    page.playback_bpm_requested.connect(values.append)

    assert not page.playback_bpm_spin.isEnabled()
    page.set_song("第一首", "歌手", 60_000, "G", 75)
    assert page.playback_bpm_spin.value() == 75
    assert page.playback_bpm_spin.minimum() == 20
    assert page.playback_bpm_spin.maximum() == 150
    page.playback_bpm_spin.setValue(90)
    assert values == [90]
    page.set_song("第二首", "歌手", 60_000, "D", 120)
    assert page.playback_bpm_spin.value() == 120
    assert values == [90]


def test_playback_bpm_releases_focus_after_keyboard_commit(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    page.set_song("测试歌曲", "歌手", 60_000, "G", 75)
    values: list[int] = []
    page.playback_bpm_requested.connect(values.append)

    page.playback_bpm_spin.setFocus()
    page.playback_bpm_spin.lineEdit().selectAll()
    qtbot.keyClicks(page.playback_bpm_spin, "90")
    qtbot.keyClick(page.playback_bpm_spin, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: page.playback_bpm_spin.lineEdit().selectedText() == "", timeout=500
    )

    assert page.playback_bpm_spin.value() == 90
    assert values == [90]
    assert page.playback_bpm_spin.lineEdit().selectedText() == ""


def test_playback_bpm_releases_focus_after_step(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    page.show()
    page.activateWindow()
    page.set_song("测试歌曲", "歌手", 60_000, "G", 75)
    spin = page.playback_bpm_spin
    spin.setFocus()
    spin.lineEdit().selectAll()

    qtbot.keyClick(spin, Qt.Key.Key_Up)
    qtbot.waitUntil(lambda: spin.lineEdit().selectedText() == "", timeout=500)

    assert spin.value() == 76

    spin.setFocus()
    spin.lineEdit().selectAll()
    wheel = QWheelEvent(
        QPointF(10, 10),
        QPointF(spin.mapToGlobal(QPoint(10, 10))),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(spin, wheel)
    qtbot.waitUntil(lambda: spin.lineEdit().selectedText() == "", timeout=500)

    assert spin.value() == 77


def test_now_playing_displays_key_and_bpm(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)

    page.set_song("K歌之王", "陈奕迅", 222_407, "D", 76)

    assert page.song_label.text() == "K歌之王 — 陈奕迅"
    assert page.music_info_label.text() == "原KEY D  ·  76 BPM"
    assert not page.music_info_label.isHidden()

    page.set_song("旧歌曲", "", 60_000)
    assert page.music_info_label.text() == ""
    assert page.music_info_label.isHidden()


def test_previous_song_and_restart_are_separate_actions(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    page.set_song("当前歌曲", "歌手", 60_000)
    page.set_previous_song("上一首歌", "另一歌手")
    previous_requests: list[bool] = []
    restart_requests: list[bool] = []
    seeks: list[int] = []
    page.previous_song_requested.connect(lambda: previous_requests.append(True))
    page.restart_requested.connect(lambda: restart_requests.append(True))
    page.seek_requested.connect(seeks.append)

    page.previous_song_button.click()
    assert previous_requests == [True]
    assert seeks == []

    page.restart_button.click()
    assert previous_requests == [True]
    assert restart_requests == [True]
    assert seeks == []
    assert page.restart_button.text() == ""
    assert not page.restart_button.icon().isNull()


def test_queue_navigation_buttons_follow_neighbor_availability(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)

    page.set_previous_song(None)
    page.set_next_song(None)
    assert not page.previous_song_button.isEnabled()
    assert not page.next_song_button.isEnabled()
    assert page.previous_song_button.toolTip() == "播放列表中没有上一首歌曲"
    assert page.next_song_button.toolTip() == "播放列表中没有下一首歌曲"

    page.set_previous_song("上一首歌", "歌手甲")
    page.set_next_song("下一首歌", "歌手乙")
    assert page.previous_song_button.isEnabled()
    assert page.next_song_button.isEnabled()
    assert "上一首歌 — 歌手甲" in page.previous_song_button.toolTip()
    assert "下一首歌 — 歌手乙" in page.next_song_button.toolTip()

    page.set_empty_playlist()
    assert not page.previous_song_button.isEnabled()
    assert not page.next_song_button.isEnabled()


def test_transport_buttons_use_icons_and_accessible_names(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    buttons = (
        page.previous_song_button,
        page.restart_button,
        page.backward_button,
        page.play_button,
        page.forward_button,
        page.stop_button,
        page.next_song_button,
    )

    assert all(button.text() == "" for button in buttons)
    assert all(not button.icon().isNull() for button in buttons)
    assert all(button.accessibleName() for button in buttons)
    page.set_playback_state("playing")
    playing_icon_key = page.play_button.icon().cacheKey()
    assert page.play_button.toolTip() == "暂停（空格键）"
    page.set_playback_state("paused")
    assert page.play_button.text() == ""
    assert page.play_button.icon().cacheKey() != playing_icon_key


def test_output_screen_cards_toggle_independently(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    audience_values: list[bool] = []
    singer_values: list[bool] = []
    page.audience_output_toggled.connect(audience_values.append)
    page.singer_output_toggled.connect(singer_values.append)

    assert page.audience_output_button.accessibleName() == "观众屏输出开关"
    assert page.singer_output_button.accessibleName() == "歌手屏输出开关"
    assert not page.audience_output_button.isChecked()
    assert not page.singer_output_button.isChecked()

    page.audience_output_button.click()
    assert audience_values == [True]
    assert singer_values == []

    page.set_output_states(False, True)
    assert audience_values == [True]
    assert singer_values == []
    assert not page.audience_output_button.isChecked()
    assert page.singer_output_button.isChecked()


def test_singer_display_checkboxes_are_in_playback_output(
    qtbot: QtBot,
) -> None:
    playback = PlaybackPage()
    settings = SettingsPage()
    qtbot.addWidget(playback)
    qtbot.addWidget(settings)
    values: list[tuple[bool, bool]] = []
    playback.singer_display_options_changed.connect(lambda beat, info: values.append((beat, info)))

    assert not hasattr(settings, "singer_beat_lights_checkbox")
    assert not hasattr(settings, "singer_music_info_checkbox")
    playback.set_singer_display_options(True, False)
    assert values == []
    assert not playback.singer_beat_lights_checkbox.isChecked()
    assert not playback.singer_beat_lights_checkbox.isVisible()
    assert not playback.singer_music_info_checkbox.isChecked()

    playback.singer_music_info_checkbox.click()
    assert values == [(False, True)]


def test_musician_chord_mode_is_not_in_playback_output(qtbot: QtBot) -> None:
    playback = PlaybackPage()
    qtbot.addWidget(playback)
    assert not hasattr(playback, "musician_chord_mode_combo")
    assert not hasattr(playback, "musician_chord_mode_changed")


def test_musician_beat_light_checkbox_is_in_playback_output(qtbot: QtBot) -> None:
    playback = PlaybackPage()
    settings = SettingsPage()
    qtbot.addWidget(playback)
    qtbot.addWidget(settings)
    values: list[bool] = []
    playback.musician_beat_lights_changed.connect(values.append)

    assert not hasattr(settings, "musician_beat_lights_checkbox")
    playback.set_musician_beat_lights_visible(False)
    assert values == []
    assert not playback.musician_beat_lights_checkbox.isChecked()

    assert not playback.musician_beat_lights_checkbox.isVisible()


def test_web_musician_controls_reflect_server_state(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    values: list[bool] = []
    page.web_musician_toggled.connect(values.append)

    assert not hasattr(page, "web_musician_url_label")
    assert page.web_musician_qr_button.isHidden()
    assert page.web_musician_button.text() == "开启扫码"
    page.web_musician_button.click()
    assert values == [True]

    page.set_web_musician_state(True)
    assert values == [True]
    assert page.web_musician_button.isChecked()
    assert page.web_musician_button.text() == "关闭扫码"
    assert not page.web_musician_qr_button.isHidden()

    page.set_web_musician_state(False)
    assert page.web_musician_button.text() == "开启扫码"


def test_subtitle_font_sizes_update_without_emitting_and_user_changes_emit(
    qtbot: QtBot,
) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    values: list[tuple[int, int]] = []
    page.subtitle_font_sizes_changed.connect(
        lambda audience, singer: values.append((audience, singer))
    )

    assert page.audience_font_size.value() == 72
    assert page.singer_font_size.value() == 42
    assert page.audience_font_size.maximum() == 2_147_483_647
    assert page.singer_font_size.maximum() == 2_147_483_647
    page.set_subtitle_font_sizes(88, 54)
    assert page.audience_font_size.value() == 88
    assert page.singer_font_size.value() == 54
    assert values == []

    page.singer_font_size.setValue(56)
    assert values == [(88, 56)]
    page.singer_font_size.setValue(160)
    assert values[-1] == (88, 160)
    page.audience_font_size.setValue(180)
    assert values[-1] == (180, 160)


def test_stage_parameter_spin_supports_wheel_and_releases_focus_on_commit(
    qtbot: QtBot,
) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    page.show()
    spin = page.audience_font_size
    page.activateWindow()
    qtbot.mouseClick(spin.lineEdit(), Qt.MouseButton.LeftButton)
    starting_value = spin.value()
    wheel = QWheelEvent(
        QPointF(10, 10),
        QPointF(spin.mapToGlobal(QPoint(10, 10))),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(spin, wheel)
    assert spin.value() == starting_value + 1

    spin.lineEdit().selectAll()
    qtbot.keyClick(spin, Qt.Key.Key_Return)
    qtbot.wait(1)
    assert spin.lineEdit().selectedText() == ""


def test_output_screen_cards_align_with_track_cards(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    assert page.minimumSizeHint().height() <= 800
    page.resize(1066, 800)
    page.show()

    track_top = page.track_checks[TrackKind.VOCALS].mapTo(page, QPoint()).y()
    audience_top = page.audience_output_button.mapTo(page, QPoint()).y()
    singer_top = page.singer_output_button.mapTo(page, QPoint()).y()
    musician_top = page.musician_output_button.mapTo(page, QPoint()).y()

    assert abs(audience_top - track_top) <= 4
    assert abs(singer_top - track_top) <= 4
    assert abs(musician_top - track_top) <= 4
    assert not page.singer_beat_lights_checkbox.isVisible()
    assert not page.musician_beat_lights_checkbox.isVisible()
    track_positions = [page.track_checks[track].mapTo(page, QPoint()) for track in TrackKind]
    assert len({position.x() for position in track_positions}) == 1
    assert len({position.y() for position in track_positions}) == len(TrackKind)
    assert [position.y() for position in track_positions] == sorted(
        position.y() for position in track_positions
    )


def test_output_channels_use_only_a_vertical_separator(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)

    assert page.findChildren(QFrame, "outputChannelPanel") == []
    separator = page.findChild(QFrame, "outputChannelSeparator")
    assert separator is not None
    assert separator.frameShape() == QFrame.Shape.VLine


def test_playback_page_omits_removed_lock_and_output_action_buttons(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    assert not hasattr(page, "mix_lock_button")
    assert not hasattr(page, "output_lock_button")
    assert not hasattr(page, "reset_output_sizes_button")
    assert page.volume_slider.isEnabled()
    assert page.volume_label.isEnabled()
    assert page.volume_value_label.isEnabled()
    assert all(button.isEnabled() for button in page.track_checks.values())
    assert all(
        widget.isEnabled()
        for widget in (
            page.audience_selector,
            page.audience_offset,
            page.singer_selector,
            page.singer_offset,
            page.audience_font_size,
            page.singer_font_size,
            page.audience_output_button,
            page.singer_output_button,
        )
    )


def test_create_song_file_picker_accepts_mp3_aac_and_wav(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)

    assert "*.mp3" in page.source_input.file_filter
    assert "*.aac" in page.source_input.file_filter
    assert "*.wav" in page.source_input.file_filter


def test_create_song_requires_lrc_before_start(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    requests: list[object] = []
    page.start_requested.connect(requests.append)
    page.source_input.edit.setText("/tmp/测试歌曲.mp3")

    page._request_start()

    assert not requests
    assert page.stage_label.text() == "阶段：发生错误：请选择 LRC 歌词文件或输入歌词文本"


def test_create_song_accepts_text_lyrics(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    requests: list[object] = []
    page.start_requested.connect(requests.append)
    page.source_input.edit.setText("/tmp/测试歌曲.wav")
    page.lyrics_text_input.setPlainText("第一句\n第二句")

    page._request_start()

    assert len(requests) == 1
    assert requests[0]["lyrics_text"] == "第一句\n第二句"  # type: ignore[index]
    assert requests[0]["lrc_path"] is None  # type: ignore[index]


def test_create_song_rejects_two_lyrics_sources(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    requests: list[object] = []
    page.start_requested.connect(requests.append)
    page.source_input.edit.setText("/tmp/测试歌曲.wav")
    page.lrc_input.edit.setText("/tmp/歌词.lrc")
    page.lyrics_text_input.setPlainText("第一句")

    page._request_start()

    assert not requests
    assert "不要同时提供" in page.stage_label.text()


def test_create_song_page_only_shows_processing_progress(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)

    assert page.findChildren(QPlainTextEdit) == [page.lyrics_text_input]
    assert "任务日志" not in {label.text() for label in page.findChildren(QLabel)}


def test_lrc_input_keeps_language_selection_for_alignment(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    page.language_combo.setCurrentIndex(page.language_combo.findData("yue"))

    page.lrc_input.edit.setText("/tmp/已有歌词.lrc")

    assert page.language_combo.isEnabled()
    assert "三种语言均以 LRC 或输入文本" in page.language_combo.toolTip()
    assert page.language_combo.currentData() == "yue"

    page.lrc_input.edit.clear()

    assert page.language_combo.isEnabled()
    assert "三种语言均以 LRC 或输入文本" in page.language_combo.toolTip()
    assert page.language_combo.currentData() == "yue"


def test_create_song_page_resets_song_content_for_next_song(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    page.language_combo.setCurrentIndex(page.language_combo.findData("yue"))
    page.source_input.edit.setText("/tmp/上一首.mp3")
    page.lrc_input.edit.setText("/tmp/上一首.lrc")
    page.lyrics_text_input.setPlainText("上一首的歌词")
    page.title_edit.setText("上一首")
    page.artist_edit.setText("上一位歌手")
    page.progress.setValue(75)

    page.reset_for_next_song()

    assert page.source_input.edit.text() == ""
    assert page.lrc_input.edit.text() == ""
    assert page.lyrics_text_input.toPlainText() == ""
    assert page.title_edit.text() == ""
    assert page.artist_edit.text() == ""
    assert page.language_combo.currentData() == "auto"
    assert page.progress.minimum() == 0
    assert page.progress.maximum() == 100
    assert page.progress.value() == 0
    assert page.stage_label.text() == "阶段：歌曲创建完成，可以创建下一首"
    assert page.focusWidget() is page.source_input.edit


def test_create_song_extracts_percentage_without_showing_logs(qtbot: QtBot) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    page.set_running(True)
    page.set_stage("正在下载 SheetSage2 模型")
    page.consume_progress_message("开始下载")
    page.consume_progress_message("22%|████      | 648M/2.88G [00:30<03:08, 12.7MiB/s]")
    page.consume_progress_message("23%|████▏     | 673M/2.88G [00:31<02:42, 14.7MiB/s]")

    assert page.findChildren(QPlainTextEdit) == [page.lyrics_text_input]
    assert page.stage_label.text() == "阶段：正在处理歌曲"
    assert page.progress.minimum() == 0
    assert page.progress.maximum() == 100
    assert page.progress.value() == 23

    page.consume_progress_message("下载完成")
    assert page.progress.value() == 23

    page.show_error("Beat This! 模型无法启动")
    assert page.stage_label.text() == "阶段：发生错误：歌曲处理失败，请重试"

    page.show_error("Beat This! 模型文件不存在：/private/path")
    assert "节拍模型" in page.stage_label.text()
    assert "设置页" in page.stage_label.text()
    assert "/private/path" not in page.stage_label.text()
    assert "Beat This" not in page.stage_label.text()


def test_creation_controller_keeps_stage_when_receiving_log_progress(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    controller = CreationController(page, library_root=tmp_path)
    controller._timer.stop()
    page.set_running(True)

    controller._messages.put(("stage", "正在进行四轨分离"))
    controller._messages.put(("log", "22%|████      | 648M/2.88G [00:30<03:08, 12.7MiB/s]"))
    controller._messages.put(("log", "23%|████▏     | 673M/2.88G [00:31<02:42, 14.7MiB/s]"))
    controller._messages.put(("progress", "0.42"))
    controller._drain_messages()

    assert page.stage_label.text() == "阶段：正在进行四轨分离"
    assert page.findChildren(QPlainTextEdit) == [page.lyrics_text_input]
    assert page.progress.value() == 42


def test_completed_package_prepares_creation_page_for_next_song(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page = CreateSongPage()
    qtbot.addWidget(page)
    controller = CreationController(page, library_root=tmp_path)
    controller._timer.stop()
    page.source_input.edit.setText("/tmp/已完成.mp3")
    page.title_edit.setText("已完成歌曲")
    created_paths: list[Path] = []
    controller.song_created.connect(created_paths.append)
    package_path = tmp_path / "created-package"

    controller._messages.put(("package_completed", package_path))
    controller._drain_messages()

    assert created_paths == [package_path]
    assert page.source_input.edit.text() == ""
    assert page.title_edit.text() == ""
    assert page.start_button.isEnabled()
    assert not page.cancel_button.isEnabled()

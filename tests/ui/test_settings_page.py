# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path
from threading import Event

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox, QPushButton
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband.audio.output_device import AudioOutputDevice
from dxband.ui import main_window
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.pages.settings_page import SettingsPage
from dxband.ui.services.audience_font_library import AudienceFontResource
from dxband.ui.services.background_video_library import BackgroundVideoResource
from dxband.ui.services.settings_service import (
    ApplicationSettings,
    BackgroundVideoSettings,
    SettingsService,
)


def _device(index: int, name: str) -> AudioOutputDevice:
    return AudioOutputDevice(
        index=index,
        name=name,
        channels=2,
        default_sample_rate_hz=48_000,
    )


def _settings(device: int | None = None) -> ApplicationSettings:
    return ApplicationSettings(
        library_root=Path("/tmp/music"),
        audio_output_device=device,
        audience_screen_fingerprint="",
        singer_screen_fingerprint="",
        audience_offset_ms=0,
        singer_offset_ms=150,
    )


def test_refresh_output_devices_keeps_current_selection(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_values(_settings(2), (_device(1, "内置扬声器"), _device(2, "调音台")))
    requests: list[bool] = []
    page.refresh_output_devices_requested.connect(lambda: requests.append(True))

    page.refresh_output_devices_button.click()
    page.set_output_devices((_device(1, "内置扬声器"), _device(2, "调音台"), _device(3, "新设备")))

    assert requests == [True]
    assert page.output_combo.currentData() == 2
    assert page.output_combo.count() == 4
    assert page.output_combo.itemData(3) == 3


def test_chord_fill_progress_reports_batch_state(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)

    page.begin_chord_fill(3)
    page.update_chord_fill(1, 3, "测试歌曲")

    assert page.chord_fill_progress.maximum() == 3
    assert page.chord_fill_progress.value() == 1
    assert page.chord_fill_status.text() == "正在补充和弦：测试歌曲（1/3）"

    page.finish_chord_fill(2, 1)

    assert page.chord_fill_progress.value() == 3
    assert page.chord_fill_status.text() == "和弦数据补充完成：成功 2 首，失败 1 首"


def test_refresh_output_devices_falls_back_to_system_default(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_values(_settings(2), (_device(2, "已断开设备"),))

    page.set_output_devices((_device(3, "新设备"),))

    assert page.output_combo.currentData() is None
    assert page.output_combo.currentText() == "系统默认设备"


def test_settings_page_has_no_save_button_and_emits_changes_immediately(
    qtbot: QtBot,
) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    page.set_values(
        _settings(1),
        (_device(1, "内置扬声器"), _device(2, "调音台")),
    )
    application_changes: list[ApplicationSettings] = []
    page.save_requested.connect(application_changes.append)
    page.set_background_resources(
        (
            BackgroundVideoResource("none", "无背景视频", None, True),
            BackgroundVideoResource(
                "builtin:test.mp4",
                "测试背景",
                Path("test.mp4"),
                True,
            ),
        ),
        "none",
    )

    assert page.findChild(QPushButton, "settingsSaveButton") is None
    assert not hasattr(page, "background_mode_combo")
    assert not hasattr(page, "background_fixed_combo")
    page.output_combo.setCurrentIndex(page.output_combo.findData(2))

    assert application_changes[-1].audio_output_device == 2


def test_beat_prompt_sound_option_is_loaded_in_playback_output(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)

    page.set_beat_prompt_sound_enabled(True)

    assert page.beat_prompt_sound_checkbox.text() == "引导拍子声"
    assert page.beat_prompt_sound_checkbox.accessibleName() == "引导拍子声开关"
    assert page.beat_prompt_sound_enabled()

    changes: list[bool] = []
    page.beat_prompt_sound_changed.connect(changes.append)
    page.beat_prompt_sound_checkbox.setChecked(False)
    assert changes == [False]


def test_main_window_refresh_button_rescans_output_devices(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "devices.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path / "library"))
    settings_service = SettingsService(settings)
    scans = [(_device(1, "内置扬声器"),), (_device(1, "内置扬声器"), _device(4, "USB 声卡"))]
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    monkeypatch.setattr(main_window, "list_output_devices", lambda: scans.pop(0))
    window = main_window.MainWindow()
    qtbot.addWidget(window)

    window.settings_page.refresh_output_devices_button.click()

    assert window.settings_page.output_combo.count() == 3
    assert window.settings_page.output_combo.itemData(2) == 4
    assert window.settings_page.status_label.text() == "已刷新音频输出设备：发现 2 个设备"
    window.close()


def test_missing_saved_output_device_uses_system_default_on_startup(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "missing-device.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path / "library"))
    settings.setValue("audio/output_device", 3)
    settings_service = SettingsService(settings)
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    monkeypatch.setattr(main_window, "list_output_devices", lambda: (_device(1, "内置扬声器"),))

    window = main_window.MainWindow()
    qtbot.addWidget(window)

    assert settings_service.load().audio_output_device is None
    assert window.playback_controller.settings.audio_output_device is None
    assert window.settings_page.output_combo.currentData() is None
    assert window.settings_page.status_label.text() == (
        "原音频输出设备已断开，已切换为系统默认设备"
    )
    window.close()


def test_refresh_disconnects_selected_output_device_in_playback_settings(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "disconnected-device.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path / "library"))
    settings.setValue("audio/output_device", 3)
    settings_service = SettingsService(settings)
    scans = [(_device(3, "USB 声卡"),), (_device(1, "内置扬声器"),)]
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    monkeypatch.setattr(main_window, "list_output_devices", lambda: scans.pop(0))
    window = main_window.MainWindow()
    qtbot.addWidget(window)

    window.settings_page.refresh_output_devices_button.click()

    assert settings_service.load().audio_output_device is None
    assert window.playback_controller.settings.audio_output_device is None
    assert window.settings_page.output_combo.currentData() is None
    assert window.settings_page.status_label.text() == (
        "原音频输出设备已断开，已切换为系统默认设备"
    )
    window.close()


def test_main_window_saves_beat_prompt_sound_option(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "beat-prompt.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path / "library"))
    settings_service = SettingsService(settings)
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    monkeypatch.setattr(main_window, "list_output_devices", lambda: ())
    window = main_window.MainWindow()
    qtbot.addWidget(window)

    window.playback_page.beat_prompt_sound_checkbox.setChecked(True)

    assert settings_service.load_beat_prompt_sound_enabled()
    assert window.playback_controller._beat_prompt_sound_enabled
    assert window.playback_page.status_label.text() == (
        "引导拍子声已开启；打开乐手屏时，从歌曲开头播放前响两小节"
    )
    window.playback_page.beat_prompt_sound_checkbox.setChecked(False)
    assert window.playback_page.status_label.text() == "引导拍子声已关闭"
    window.close()


def test_main_window_saves_stage_display_options_from_playback(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "stage-display.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path / "library"))
    settings_service = SettingsService(settings)
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    monkeypatch.setattr(main_window, "list_output_devices", lambda: ())
    window = main_window.MainWindow()
    qtbot.addWidget(window)

    window.playback_page.singer_music_info_checkbox.setChecked(False)
    window.playback_page.musician_beat_lights_checkbox.setChecked(False)

    singer = settings_service.load_singer_display_settings()
    musician = settings_service.load_musician_display_settings()
    assert not singer.beat_lights_visible
    assert not singer.music_info_visible
    assert musician.chord_mode == "degree"
    assert not musician.beat_lights_visible
    assert window.playback_controller._singer_music_info_visible is False
    assert window.playback_controller._musician_chord_mode == "degree"
    assert window.playback_controller._musician_beat_lights_visible is False
    window.close()


def test_main_window_auto_saves_output_device_and_playback_background_mode(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "auto-save.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path / "library"))
    settings_service = SettingsService(settings)
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    monkeypatch.setattr(
        main_window,
        "list_output_devices",
        lambda: (_device(7, "USB 声卡"),),
    )
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, message: messages.append((title, message)),
    )
    window = main_window.MainWindow()
    qtbot.addWidget(window)

    window.settings_page.output_combo.setCurrentIndex(window.settings_page.output_combo.findData(7))
    window.playback_page.audience_background_combo.setCurrentIndex(
        window.playback_page.audience_background_combo.findData("__random__")
    )

    assert settings_service.load().audio_output_device == 7
    assert messages == [
        (
            "音频输出设备已更改",
            "新设备已保存，将在下次加载歌曲时生效。\n当前歌曲仍使用原来的音频输出设备。",
        )
    ]
    assert settings_service.load_background_video_settings().mode == "random"
    window.close()


def test_main_window_optimizes_uploaded_background_off_ui_thread(
    qtbot: QtBot, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    settings = QSettings(str(tmp_path / "background-upload.ini"), QSettings.Format.IniFormat)
    settings.setValue("library/root", str(tmp_path / "library"))
    settings_service = SettingsService(settings)
    monkeypatch.setattr(main_window, "SettingsService", lambda: settings_service)
    monkeypatch.setattr(main_window, "list_output_devices", lambda: ())
    window = main_window.MainWindow()
    qtbot.addWidget(window)
    window.background_video_library.user_root = tmp_path / "backgrounds"
    release_worker = Event()
    source = tmp_path / "source.mp4"

    def import_file(_source: Path) -> BackgroundVideoResource:
        assert release_worker.wait(2)
        path = window.background_video_library.user_root / "source.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"optimized")
        return BackgroundVideoResource("user:source.mp4", "source（用户上传）", path, False)

    monkeypatch.setattr(window.background_video_library, "import_file", import_file)
    window._upload_background_video(source)

    assert window._background_video_import_busy
    assert "正在后台优化" in window.settings_page.status_label.text()
    release_worker.set()
    qtbot.waitUntil(lambda: not window._background_video_import_busy, timeout=3000)
    assert settings_service.load_background_video_settings().fixed_resource_id == (
        "user:source.mp4"
    )
    window.close()


def test_background_resources_remain_in_settings_for_preview(qtbot: QtBot, tmp_path: Path) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    custom_path = tmp_path / "custom.mp4"
    custom_path.write_bytes(b"video")
    resources = (
        BackgroundVideoResource("none", "无背景视频", None, True),
        BackgroundVideoResource("user:custom.mp4", "custom（用户上传）", custom_path, False),
    )

    page.set_background_resources(resources, "user:custom.mp4")

    assert not hasattr(page, "background_mode_combo")
    assert not hasattr(page, "background_fixed_combo")
    assert page.background_resource_list.currentItem().data(256) == "user:custom.mp4"
    assert page.delete_background_button.isEnabled()
    assert page._preview_path == custom_path
    assert page._preview_audio_output.isMuted()
    assert page.background_preview_stack.width() * 9 == (
        page.background_preview_stack.height() * 16
    )
    assert page.background_preview_stack.width() >= 480
    assert "qlineargradient" in page.background_preview_placeholder.styleSheet()


def test_playback_background_selector_combines_random_and_resources(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    custom_path = tmp_path / "custom.mp4"
    custom_path.write_bytes(b"video")
    resources = (
        BackgroundVideoResource("none", "无背景视频", None, True),
        BackgroundVideoResource("user:custom.mp4", "custom（用户上传）", custom_path, False),
    )
    changes: list[BackgroundVideoSettings] = []
    page.background_video_settings_changed.connect(changes.append)

    page.set_background_resources(
        resources,
        BackgroundVideoSettings(mode="fixed", fixed_resource_id="user:custom.mp4"),
    )

    assert page.audience_background_combo.count() == 3
    assert page.audience_background_combo.itemText(0) == "随机模式"
    assert page.audience_background_combo.currentData() == "user:custom.mp4"
    assert changes == []

    page.audience_background_combo.setCurrentIndex(0)
    assert changes[-1] == BackgroundVideoSettings(
        mode="random",
        fixed_resource_id="none",
    )
    page.audience_background_combo.setCurrentIndex(page.audience_background_combo.findData("none"))
    assert changes[-1] == BackgroundVideoSettings(
        mode="fixed",
        fixed_resource_id="none",
    )


def test_audience_font_selector_uses_stable_resource_ids(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    resources = (
        AudienceFontResource("default", "系统默认黑体", "PingFang SC", None),
        AudienceFontResource("longcang", "龙藏体", "Long Cang", Path("font.ttf")),
    )

    page.set_audience_fonts(resources, "longcang")

    assert page.audience_font_combo.currentText() == "龙藏体"
    assert page.audience_font_combo.parentWidget().objectName() == "settingsResourcePane"
    assert page.audience_font_id() == "longcang"
    assert page.audience_font_preview.text() == "字幕字体预览"
    assert page.audience_font_preview.font().family() == "Long Cang"
    assert page.audience_font_preview.font().pointSize() == 32
    assert page.audience_font_preview.geometry() == page.background_preview_stack.rect()
    assert page.audience_font_preview.graphicsEffect() is not None


def test_audience_font_selector_emits_change_immediately(qtbot: QtBot) -> None:
    page = SettingsPage()
    qtbot.addWidget(page)
    resources = (
        AudienceFontResource("default", "系统默认黑体", "PingFang SC", None),
        AudienceFontResource("longcang", "龙藏体", "Long Cang", Path("font.ttf")),
    )
    changes: list[str] = []
    page.audience_font_changed.connect(changes.append)

    page.set_audience_fonts(resources, "default")
    page.audience_font_combo.setCurrentIndex(1)

    assert changes == ["longcang"]
    assert page.audience_font_preview.font().family() == "Long Cang"


def test_playback_audience_font_selector_uses_same_resources(qtbot: QtBot) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    resources = (
        AudienceFontResource("default", "系统默认黑体", "PingFang SC", None),
        AudienceFontResource("longcang", "龙藏体", "Long Cang", Path("font.ttf")),
    )
    changes: list[str] = []
    page.audience_font_changed.connect(changes.append)

    page.set_audience_fonts(resources, "longcang")
    assert page.audience_font_combo.currentData() == "longcang"
    assert changes == []

    page.audience_font_combo.setCurrentIndex(0)
    assert changes == ["default"]

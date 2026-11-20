# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pathlib import Path

from PySide6.QtCore import QSettings

import dxband.ui.services.settings_service as settings_module
from dxband.constants import TrackKind
from dxband.ui.services.settings_service import (
    ApplicationSettings,
    BackgroundVideoSettings,
    MixerSettings,
    MusicianDisplaySettings,
    OutputWindowSizes,
    SettingsService,
    SingerDisplaySettings,
    SubtitleFontSizes,
)


def test_existing_settings_are_copied_to_new_name(monkeypatch, tmp_path: Path) -> None:
    current = QSettings(str(tmp_path / "dxband.ini"), QSettings.Format.IniFormat)
    previous = QSettings(str(tmp_path / "previous.ini"), QSettings.Format.IniFormat)
    previous.setValue("library/root", str(tmp_path / "songs"))
    previous.setValue("screens/singer_offset_ms", 275)

    def settings_factory(organization: str, application: str) -> QSettings:
        return current if organization == "DXBand" else previous

    monkeypatch.setattr(settings_module, "QSettings", settings_factory)
    service = settings_module.SettingsService()

    assert service.load().library_root == tmp_path / "songs"
    assert service.load().singer_offset_ms == 275
    assert current.value("library/root") == str(tmp_path / "songs")


def test_musician_screen_selection_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "musician.ini"
    service = SettingsService(QSettings(str(path), QSettings.Format.IniFormat))
    settings = ApplicationSettings(
        library_root=tmp_path,
        audio_output_device=None,
        audience_screen_fingerprint="audience",
        singer_screen_fingerprint="singer",
        audience_offset_ms=0,
        singer_offset_ms=150,
        musician_screen_fingerprint="musician",
        musician_offset_ms=-120,
    )
    service.save(settings)
    reopened = SettingsService(QSettings(str(path), QSettings.Format.IniFormat))
    assert reopened.load().musician_screen_fingerprint == "musician"
    assert reopened.load().musician_offset_ms == -120


def test_output_window_sizes_are_persisted(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    service = SettingsService(settings)
    expected = OutputWindowSizes(
        audience_width=840,
        audience_height=470,
        singer_width=720,
        singer_height=405,
        musician_width=760,
        musician_height=430,
    )

    service.save_output_window_sizes(expected)

    assert service.load_output_window_sizes() == expected


def test_subtitle_font_sizes_are_persisted_and_clamped(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "subtitle-settings.ini"), QSettings.Format.IniFormat)
    service = SettingsService(settings)

    service.save_subtitle_font_sizes(SubtitleFontSizes(audience=88, singer=54, musician=38))
    assert service.load_subtitle_font_sizes() == SubtitleFontSizes(
        audience=88, singer=54, musician=38
    )

    settings.setValue("screens/audience_font_size", 999)
    settings.setValue("screens/singer_font_size", 1)
    settings.setValue("screens/musician_font_size", 1)
    assert service.load_subtitle_font_sizes() == SubtitleFontSizes(
        audience=999, singer=24, musician=18
    )

    settings.setValue("screens/singer_font_size", 180)
    settings.setValue("screens/musician_font_size", 999)
    assert service.load_subtitle_font_sizes().singer == 180
    assert service.load_subtitle_font_sizes().musician == 999


def test_musician_chord_mode_is_persisted_and_invalid_mode_falls_back(tmp_path: Path) -> None:
    settings_path = tmp_path / "musician-display.ini"
    service = SettingsService(QSettings(str(settings_path), QSettings.Format.IniFormat))
    assert service.load_musician_display_settings() == MusicianDisplaySettings()

    service.save_musician_display_settings(
        MusicianDisplaySettings(chord_mode="chord", beat_lights_visible=False)
    )
    reopened = SettingsService(QSettings(str(settings_path), QSettings.Format.IniFormat))
    assert reopened.load_musician_display_settings().chord_mode == "chord"
    assert not reopened.load_musician_display_settings().beat_lights_visible

    reopened.settings.setValue("screens/musician_chord_mode", "unsupported")
    assert reopened.load_musician_display_settings() == MusicianDisplaySettings(
        beat_lights_visible=False
    )

    reopened.save_musician_display_settings(MusicianDisplaySettings(chord_mode="chord_c"))
    assert reopened.load_musician_display_settings().chord_mode == "chord_c"
    reopened.save_musician_display_settings(MusicianDisplaySettings(chord_mode="key:Eb"))
    assert reopened.load_musician_display_settings().chord_mode == "key:Eb"
    assert not reopened.load_musician_display_settings().beat_lights_visible


def test_singer_display_options_are_visible_by_default_and_persisted(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "singer-display.ini"
    service = SettingsService(QSettings(str(settings_path), QSettings.Format.IniFormat))
    assert service.load_singer_display_settings() == SingerDisplaySettings()

    expected = SingerDisplaySettings(
        beat_lights_visible=False,
        music_info_visible=True,
    )
    service.save_singer_display_settings(expected)

    reopened = SettingsService(QSettings(str(settings_path), QSettings.Format.IniFormat))
    assert reopened.load_singer_display_settings() == expected


def test_mixer_settings_are_persisted(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "stage.ini"), QSettings.Format.IniFormat)
    service = SettingsService(settings)
    assert service.load_mixer_settings() == MixerSettings()

    service.save_mixer_settings(
        MixerSettings(
            master_volume=0.64,
            muted_tracks=frozenset({TrackKind.DRUMS, TrackKind.OTHER}),
            track_gain_db={TrackKind.VOCALS: -6.0, TrackKind.GUITAR: 3.0},
        )
    )

    reopened = SettingsService(QSettings(str(tmp_path / "stage.ini"), QSettings.Format.IniFormat))
    assert reopened.load_mixer_settings() == MixerSettings(
        master_volume=0.64,
        muted_tracks=frozenset({TrackKind.DRUMS, TrackKind.OTHER}),
        track_gain_db={TrackKind.VOCALS: -6.0, TrackKind.GUITAR: 3.0},
    )


def test_beat_prompt_sound_is_disabled_by_default_and_persisted(tmp_path: Path) -> None:
    settings_path = tmp_path / "beat-prompt.ini"
    service = SettingsService(QSettings(str(settings_path), QSettings.Format.IniFormat))

    assert not service.load_beat_prompt_sound_enabled()
    service.save_beat_prompt_sound_enabled(True)

    reopened = SettingsService(QSettings(str(settings_path), QSettings.Format.IniFormat))
    assert reopened.load_beat_prompt_sound_enabled()


def test_background_video_settings_are_persisted_and_invalid_mode_falls_back(
    tmp_path: Path,
) -> None:
    settings = QSettings(str(tmp_path / "background.ini"), QSettings.Format.IniFormat)
    service = SettingsService(settings)
    expected = BackgroundVideoSettings(
        mode="fixed",
        fixed_resource_id="builtin:wave.mp4",
    )

    service.save_background_video_settings(expected)
    assert service.load_background_video_settings() == expected

    settings.setValue("background_video/mode", "unsupported")
    assert service.load_background_video_settings() == BackgroundVideoSettings(
        mode="fixed",
        fixed_resource_id="builtin:wave.mp4",
    )


def test_audience_font_selection_is_persisted(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "font.ini"), QSettings.Format.IniFormat)
    service = SettingsService(settings)

    assert service.load_audience_font_id() == "default"
    service.save_audience_font_id("longcang")
    assert service.load_audience_font_id() == "longcang"

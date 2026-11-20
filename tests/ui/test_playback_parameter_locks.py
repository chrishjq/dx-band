# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband.audio.pcm_cache import PcmSongData
from dxband.audio.stem_mixer import PlaybackState, StemMixerEngine
from dxband.constants import TrackKind
from dxband.creation.package_validator import SongPackageValidator
from dxband.models.song import MusicalConfig
from dxband.ui.controllers.playback_controller import PlaybackController
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.render.musician_widget import MusicianWidget
from dxband.ui.services.settings_service import (
    SettingsService,
    SingerDisplaySettings,
    SubtitleFontSizes,
)


def test_parameters_persist_immediately_without_lock_controls(
    qtbot: QtBot,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package_root = package_factory()
    package = SongPackageValidator().validate(package_root, verify_media=False)
    settings = QSettings(str(tmp_path / "playback-locks.ini"), QSettings.Format.IniFormat)
    settings_service = SettingsService(settings)
    page = PlaybackPage()
    qtbot.addWidget(page)
    controller = PlaybackController(page, settings_service)
    engine = StemMixerEngine(parent=controller)
    controller._package = package
    controller._engine = engine

    page.track_checks[TrackKind.BASS].click()
    page.volume_slider.setValue(63)

    saved_song = json.loads((package_root / "song.json").read_text(encoding="utf-8"))
    assert "default_muted" not in saved_song["audio"]["tracks"]["bass"]
    assert "playback" not in saved_song
    mix_settings = settings_service.load_mixer_settings()
    assert mix_settings.master_volume == 0.63
    assert mix_settings.muted_tracks == frozenset({TrackKind.BASS})

    page.volume_slider.setValue(71)
    assert settings_service.load_mixer_settings().master_volume == 0.71

    page.audience_offset.setValue(320)
    page.singer_offset.setValue(470)
    page.musician_offset.setValue(-120)
    page.audience_font_size.setValue(92)
    page.singer_font_size.setValue(56)
    page.musician_font_size.setValue(40)
    controller.apply_musician_chord_mode("chord")
    controller.apply_musician_beat_lights_visible(False)
    saved_settings = settings_service.load()
    assert saved_settings.audience_offset_ms == 320
    assert saved_settings.singer_offset_ms == 470
    assert saved_settings.musician_offset_ms == -120
    assert settings_service.load_subtitle_font_sizes() == SubtitleFontSizes(
        audience=92,
        singer=56,
        musician=40,
    )
    assert settings_service.load_musician_display_settings().chord_mode == "chord"
    assert not settings_service.load_musician_display_settings().beat_lights_visible
    page.audience_offset.setValue(510)
    assert settings_service.load().audience_offset_ms == 510

    controller.apply_singer_display_options(False, False)
    assert settings_service.load_singer_display_settings() == SingerDisplaySettings(
        beat_lights_visible=False,
        music_info_visible=False,
    )
    assert not controller.screen_manager.singer_beat_lights_visible
    assert not controller.screen_manager.singer_music_info_visible

    page.audience_selector.addItem("测试观众屏", "audience-test")
    page.audience_selector.setCurrentIndex(page.audience_selector.count() - 1)
    page.singer_selector.addItem("测试歌手屏", "singer-test")
    page.singer_selector.setCurrentIndex(page.singer_selector.count() - 1)
    page.musician_selector.addItem("测试乐手屏", "musician-test")
    page.musician_selector.setCurrentIndex(page.musician_selector.count() - 1)
    selected_screens = settings_service.load()
    assert selected_screens.audience_screen_fingerprint == "audience-test"
    assert selected_screens.singer_screen_fingerprint == "singer-test"
    assert selected_screens.musician_screen_fingerprint == "musician-test"
    controller.close()


def test_all_tracks_are_available_without_activation(qtbot: QtBot, tmp_path: Path) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    service = SettingsService(QSettings(str(tmp_path / "mix.ini"), QSettings.Format.IniFormat))
    controller = PlaybackController(page, service)
    for track in TrackKind:
        assert page.track_checks[track].isEnabled()
        page.track_checks[track].click()
        assert controller._mix_muted[track]
    assert page.musician_output_button.isEnabled()
    assert page.web_musician_button.isEnabled()
    controller.close()


def test_musician_output_does_not_analyze_missing_chords(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    settings_service = SettingsService(
        QSettings(str(tmp_path / "missing-chords.ini"), QSettings.Format.IniFormat)
    )
    page = PlaybackPage()
    qtbot.addWidget(page)
    controller = PlaybackController(page, settings_service)
    controller._package = package
    opened: list[bool] = []
    monkeypatch.setattr(
        controller.screen_manager,
        "open_web_musician_output",
        lambda *_args, **_kwargs: opened.append(True),
    )

    controller._set_musician_output_enabled(True)

    assert opened == [True]
    assert page.status_label.text() == ("没有和弦数据，请到“歌曲库”的修改页面中，重新分析和弦数据")
    assert not (package.root / "chords.json").exists()
    controller.close()


def test_guide_beats_require_visible_musician_output(
    qtbot: QtBot,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    package = replace(
        package,
        config=package.config.model_copy(
            update={
                "musical": MusicalConfig(
                    original_key="C",
                    bpm=120,
                    beat_times_ms=[1_400, 1_900],
                )
            }
        ),
    )
    settings_service = SettingsService(
        QSettings(str(tmp_path / "beat-prompt.ini"), QSettings.Format.IniFormat)
    )
    settings_service.save_beat_prompt_sound_enabled(True)
    page = PlaybackPage()
    qtbot.addWidget(page)
    controller = PlaybackController(page, settings_service)
    samples = np.zeros((2_000, 2), dtype=np.float32)
    engine = StemMixerEngine(parent=controller)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=1_000,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        )
    )
    controller._package = package
    controller._engine = engine

    controller._sync_beat_prompt()
    assert not engine._guide_enabled
    assert controller.screen_manager._guide_countdown == (0, 0)

    musician = MusicianWidget()
    qtbot.addWidget(musician)
    musician.show()
    controller.screen_manager.musician_window = musician
    controller._musician_output_state_changed(True)
    assert engine._guide_enabled
    assert engine._count_in_start_frame == -2_600
    assert engine._count_in_target_frame == 1_400
    assert controller.screen_manager._guide_countdown == (8, 8)

    controller._set_singer_beat_lights_visible(False)
    assert engine._guide_enabled

    musician.hide()
    controller._musician_output_state_changed(False)
    assert not engine._guide_enabled
    assert controller.screen_manager._guide_countdown == (0, 0)
    controller.close()


def test_restart_then_play_starts_two_bar_guide_again(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    package = replace(
        package,
        config=package.config.model_copy(
            update={
                "musical": MusicalConfig(
                    original_key="C", bpm=120, beat_times_ms=[1_400, 1_900]
                )
            }
        ),
    )
    settings_service = SettingsService(
        QSettings(str(tmp_path / "restart-guide.ini"), QSettings.Format.IniFormat)
    )
    settings_service.save_beat_prompt_sound_enabled(True)
    page = PlaybackPage()
    qtbot.addWidget(page)
    controller = PlaybackController(page, settings_service)
    samples = np.zeros((2_000, 2), dtype=np.float32)
    engine = StemMixerEngine(parent=controller)
    engine.load_pcm(
        PcmSongData(
            sample_rate_hz=1_000,
            channels=2,
            canonical_frames=len(samples),
            tracks={track: samples for track in TrackKind},
        )
    )
    monkeypatch.setattr(engine, "_ensure_stream", lambda: None)
    controller._package = package
    controller._engine = engine
    musician = MusicianWidget()
    qtbot.addWidget(musician)
    musician.show()
    controller.screen_manager.musician_window = musician
    controller._sync_beat_prompt()
    page.set_song(package.config.title, package.config.artist, 2_000)

    assert controller.screen_manager._guide_countdown == (8, 8)
    page.play_button.click()
    assert engine.state() == PlaybackState.PLAYING
    assert engine._position_frames == -2_600
    engine.seek_ms(500)
    assert engine.guide_countdown() == (0, 0)

    page.restart_button.click()
    assert engine.state() == PlaybackState.STOPPED
    assert engine.position_ms() == 0
    assert controller.screen_manager._guide_countdown == (8, 8)
    page.play_button.click()
    assert engine.state() == PlaybackState.PLAYING
    assert engine._position_frames == -2_600
    assert engine.guide_countdown() == (8, 8)
    controller.close()

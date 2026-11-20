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
from dxband.constants import TrackKind
from dxband.creation.package_validator import SongPackageValidator
from dxband.models.song import MusicalConfig
from dxband.ui.controllers.playback_controller import PlaybackController
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.services.background_video_library import BackgroundVideoLibrary
from dxband.ui.services.settings_service import (
    BackgroundVideoSettings,
    MixerSettings,
    SettingsService,
)


def test_switching_songs_keeps_both_output_windows(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    second = replace(
        package,
        config=package.config.model_copy(
            update={
                "song_id": "20260930-193001-b1c2d3e4",
                "title": "第二首歌",
                "musical": MusicalConfig(original_key="G", bpm=96),
            }
        ),
        lyrics=package.lyrics.model_copy(
            update={
                "title": "第二首歌",
                "lines": [
                    line.model_copy(update={"text": "第二首歌词"}) for line in package.lyrics.lines
                ],
            }
        ),
    )
    pcm_data = np.zeros((4_410, 2), dtype=np.float32)
    pcm = PcmSongData(
        sample_rate_hz=44_100,
        channels=2,
        canonical_frames=len(pcm_data),
        tracks={track: pcm_data for track in TrackKind},
    )
    settings = QSettings(str(tmp_path / "song-switch.ini"), QSettings.Format.IniFormat)
    page = PlaybackPage()
    qtbot.addWidget(page)
    settings_service = SettingsService(settings)
    settings_service.save_mixer_settings(
        MixerSettings(master_volume=0.62, muted_tracks=frozenset({TrackKind.BASS}))
    )
    settings_service.save_background_video_settings(BackgroundVideoSettings(mode="random"))
    user_videos = tmp_path / "background_videos"
    user_videos.mkdir()
    (user_videos / "background.mp4").write_bytes(b"test video placeholder")
    background_choices: list[str] = []

    def choose_background(candidates: tuple[object, ...]) -> object:
        selected = candidates[len(background_choices) % len(candidates)]
        background_choices.append(str(selected))
        return selected

    monkeypatch.setattr(
        "dxband.ui.controllers.playback_controller.random.choice",
        choose_background,
    )
    controller = PlaybackController(
        page,
        settings_service,
        background_video_library=BackgroundVideoLibrary(user_root=user_videos),
    )
    monkeypatch.setattr(controller, "_load_pcm_in_background", lambda *_args: None)

    controller.load_package(package)
    assert len(background_choices) == 1
    controller._finish_load(package, pcm)
    assert len(background_choices) == 1
    assert controller._engine is not None
    assert page.playback_bpm_spin.value() == package.config.musical.bpm
    page.playback_bpm_spin.setValue(90)
    assert controller._engine.playback_rate() == 90 / package.config.musical.bpm
    assert controller._engine.is_track_muted(TrackKind.BASS)
    assert page.volume_value_label.text() == "62%"
    controller._set_audience_output_enabled(True)
    controller._set_singer_output_enabled(True)
    audience = controller.screen_manager.audience_window
    singer = controller.screen_manager.singer_window
    assert audience is not None and singer is not None
    assert singer.browser.url().toString() == controller._web_singer_server.local_url
    qtbot.addWidget(audience)
    qtbot.addWidget(singer)
    assert audience.isVisible() and singer.isVisible()
    assert audience.background_video.audio_output.isMuted()
    audience_size = audience.size()
    singer_size = singer.size()

    page.track_checks[TrackKind.VOCALS].click()
    page.volume_slider.setValue(73)
    page.audience_offset.setValue(333)

    controller.load_package(second)
    assert len(background_choices) == 2
    assert controller.screen_manager.audience_window is audience
    assert controller.screen_manager.singer_window is singer
    assert audience.isVisible() and singer.isVisible()
    assert audience.size() == audience_size
    assert singer.size() == singer_size
    assert audience.timeline is None
    snapshot = json.loads(controller._web_singer_server.snapshot_event().split(b"data: ")[1])
    assert snapshot["song"] is None

    controller._finish_load(second, pcm)
    assert controller._engine is not None
    assert page.playback_bpm_spin.value() == 96
    assert controller._engine.playback_rate() == 1.0
    assert controller._engine.is_track_muted(TrackKind.BASS)
    assert controller._engine.is_track_muted(TrackKind.VOCALS)
    assert page.volume_value_label.text() == "73%"
    assert controller.screen_manager.audience_window is audience
    assert controller.screen_manager.singer_window is singer
    assert audience.size() == audience_size
    assert singer.size() == singer_size
    assert audience.document is second.lyrics
    snapshot = json.loads(controller._web_singer_server.snapshot_event().split(b"data: ")[1])
    assert snapshot["song"]["lines"][-1]["text"] == "第二首歌词"
    assert snapshot["song"]["title"] == "第二首歌"
    assert snapshot["song"]["original_key"] == "G"
    assert snapshot["display"]["offset_ms"] == 150
    assert audience.position_ms == 333
    assert audience._background_video_position_ms == 0
    monkeypatch.setattr(controller, "_show_web_singer_dialog", lambda: None)
    page.web_singer_button.click()
    assert controller._web_singer_server.running
    singer.close()
    assert controller.screen_manager.singer_window is None
    assert controller._web_singer_server.running
    page.web_singer_button.click()
    assert not controller._web_singer_server.running
    controller.close()

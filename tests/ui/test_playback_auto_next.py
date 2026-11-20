# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot

from dxband.audio.pcm_cache import PcmSongData
from dxband.audio.stem_mixer import PlaybackState, StemMixerEngine
from dxband.constants import TrackKind
from dxband.creation.package_validator import SongPackageValidator
from dxband.services.sleep_inhibitor import sleep_inhibitor
from dxband.ui.controllers.playback_controller import PlaybackController
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.services.settings_service import SettingsService


def test_only_started_song_emits_natural_finish(qtbot: QtBot, tmp_path: Path) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    settings = QSettings(str(tmp_path / "playback.ini"), QSettings.Format.IniFormat)
    controller = PlaybackController(page, SettingsService(settings))
    finished: list[bool] = []
    controller.song_finished.connect(lambda: finished.append(True))

    controller._state_changed(PlaybackState.ENDED)
    assert finished == []
    controller._state_changed(PlaybackState.PLAYING)
    controller._state_changed(PlaybackState.ENDED)
    controller._state_changed(PlaybackState.ENDED)
    assert finished == [True]

    controller._state_changed(PlaybackState.PLAYING)
    controller._state_changed(PlaybackState.STOPPED)
    controller._state_changed(PlaybackState.ENDED)
    assert finished == [True]
    controller.close()


def test_pause_keeps_sleep_inhibited_until_playback_stops(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    page = PlaybackPage()
    qtbot.addWidget(page)
    settings = QSettings(str(tmp_path / "sleep.ini"), QSettings.Format.IniFormat)
    controller = PlaybackController(page, SettingsService(settings))
    acquired: list[str] = []
    released: list[str] = []
    monkeypatch.setattr(
        sleep_inhibitor,
        "acquire",
        lambda reason: acquired.append(reason) or "playback-token",
    )
    monkeypatch.setattr(
        sleep_inhibitor,
        "release",
        lambda token: released.append(token) if token is not None else None,
    )

    controller._state_changed(PlaybackState.PLAYING)
    controller._state_changed(PlaybackState.PAUSED)
    controller._state_changed(PlaybackState.PLAYING)

    assert acquired == ["正式播放"]
    assert released == []

    controller._state_changed(PlaybackState.STOPPED)

    assert released == ["playback-token"]
    controller.close()


def test_loading_next_song_only_plays_when_requested(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    package_factory: Callable[[], Path],
) -> None:
    package = SongPackageValidator().validate(package_factory(), verify_media=False)
    samples = np.zeros((4_410, 2), dtype=np.float32)
    pcm = PcmSongData(
        sample_rate_hz=44_100,
        channels=2,
        canonical_frames=len(samples),
        tracks={track: samples for track in TrackKind},
    )
    settings = QSettings(str(tmp_path / "auto-play.ini"), QSettings.Format.IniFormat)
    page = PlaybackPage()
    qtbot.addWidget(page)
    controller = PlaybackController(page, SettingsService(settings))
    monkeypatch.setattr(controller, "_load_pcm_in_background", lambda *_args: None)
    played: list[bool] = []
    monkeypatch.setattr(StemMixerEngine, "play", lambda _self: played.append(True))

    controller.load_package(package, auto_play=False)
    controller._finish_load(package, pcm)
    assert played == []

    controller.load_package(package, auto_play=True)
    controller._finish_load(package, pcm)
    assert played == [True]
    controller.close()

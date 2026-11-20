# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import math
import queue
import random
import threading
import time
import traceback
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from dxband.audio.pcm_cache import PcmCacheService, PcmSongData
from dxband.audio.stem_mixer import PlaybackState, StemMixerEngine
from dxband.constants import TrackKind
from dxband.creation.package_validator import SongPackage
from dxband.lyrics.timeline import LyricTimeline
from dxband.services.paths import resolve_package_path
from dxband.services.sleep_inhibitor import sleep_inhibitor
from dxband.services.web_musician_server import WebMusicianServer
from dxband.services.web_musician_view import build_web_musician_song
from dxband.services.web_singer_server import WebSingerServer, build_web_singer_song
from dxband.ui.dialogs.error_details_dialog import ErrorDetailsDialog
from dxband.ui.dialogs.web_musician_dialog import WebMusicianDialog
from dxband.ui.pages.playback_page import PlaybackPage
from dxband.ui.public_messages import public_message
from dxband.ui.services.audience_font_library import AudienceFontLibrary
from dxband.ui.services.background_video_library import BackgroundVideoLibrary
from dxband.ui.services.screen_manager import ScreenManager
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


class PlaybackController(QObject):
    song_loaded = Signal(str)
    song_load_failed = Signal(str)
    song_finished = Signal()
    settings_changed = Signal(object)

    def __init__(
        self,
        page: PlaybackPage,
        settings_service: SettingsService,
        background_video_library: BackgroundVideoLibrary | None = None,
        audience_font_library: AudienceFontLibrary | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self.settings_service = settings_service
        self.settings = settings_service.load()
        self.background_video_library = background_video_library or BackgroundVideoLibrary()
        self.background_video_settings = settings_service.load_background_video_settings()
        self.audience_font_library = audience_font_library or AudienceFontLibrary()
        self.audience_font_id = settings_service.load_audience_font_id()
        self._beat_prompt_sound_enabled = settings_service.load_beat_prompt_sound_enabled()
        singer_display_settings = settings_service.load_singer_display_settings()
        self._singer_beat_lights_visible = singer_display_settings.beat_lights_visible
        self._singer_music_info_visible = singer_display_settings.music_info_visible
        musician_display_settings = settings_service.load_musician_display_settings()
        self._musician_chord_mode = musician_display_settings.chord_mode
        self._musician_beat_lights_visible = musician_display_settings.beat_lights_visible
        mix_settings = settings_service.load_mixer_settings()
        self._mix_muted = {track: track in mix_settings.muted_tracks for track in TrackKind}
        self._mix_gain_db = {
            track: self._snap_track_gain_db(mix_settings.track_gain_db.get(track, 0.0))
            for track in TrackKind
        }
        self._mix_volume = mix_settings.master_volume
        self._playback_rate = 1.0
        language = settings_service.load_language()
        self.screen_manager = ScreenManager(self, language=language)
        self._pcm_cache = PcmCacheService()
        self._messages: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._load_generation = 0
        self._load_thread: threading.Thread | None = None
        self._package: SongPackage | None = None
        self._timeline: LyricTimeline | None = None
        self._engine: StemMixerEngine | None = None
        self._last_preview_line_id = ""
        self._auto_play_after_load = False
        self._playback_started = False
        self._sleep_token: str | None = None
        self._current_background_resource_id = "none"
        self._playback_state = PlaybackState.EMPTY.value
        self._last_web_transport_push = 0.0
        self._web_musician_server = WebMusicianServer(language=language)
        self._web_musician_server.on_local_chord_mode = lambda mode: self._messages.put(
            ("musician_chord_mode", mode)
        )
        self._web_musician_dialog: WebMusicianDialog | None = None
        self._web_singer_server = WebSingerServer(language=language)
        self._web_singer_dialog: WebMusicianDialog | None = None

        self._message_timer = QTimer(self)
        self._message_timer.setInterval(40)
        self._message_timer.timeout.connect(self._drain_messages)
        self._message_timer.start()

        self.page.play_pause_requested.connect(self._toggle_playback)
        self.page.restart_requested.connect(self._restart)
        self.page.stop_requested.connect(self._stop)
        self.page.seek_requested.connect(self._seek)
        self.page.track_mute_requested.connect(self._set_track_mute)
        self.page.track_gain_requested.connect(self._set_track_gain)
        self.page.master_volume_requested.connect(self._set_master_volume)
        self.page.playback_bpm_requested.connect(self._set_playback_bpm)
        self.page.audience_output_toggled.connect(self._set_audience_output_enabled)
        self.page.singer_output_toggled.connect(self._set_singer_output_enabled)
        self.page.musician_output_toggled.connect(self._set_musician_output_enabled)
        self.page.web_musician_toggled.connect(self._set_web_musician_enabled)
        self.page.web_musician_qr_requested.connect(self._show_web_musician_dialog)
        self.page.web_singer_toggled.connect(self._set_web_singer_enabled)
        self.page.web_singer_qr_requested.connect(self._show_web_singer_dialog)
        self.page.musician_offset_changed.connect(self._set_musician_offset)
        self.page.musician_font_size_changed.connect(self._set_musician_font_size)
        self.page.offsets_changed.connect(self._set_offsets)
        self.page.subtitle_font_sizes_changed.connect(self._set_subtitle_font_sizes)
        self.page.audience_selector.fingerprint_changed.connect(self._screen_selection_changed)
        self.page.singer_selector.fingerprint_changed.connect(self._screen_selection_changed)
        self.page.musician_selector.fingerprint_changed.connect(self._screen_selection_changed)
        self.screen_manager.screens_changed.connect(self._screens_changed)
        self.screen_manager.error_raised.connect(self._show_error)
        self.screen_manager.window_sizes_changed.connect(self._save_output_sizes)
        self.screen_manager.output_state_changed.connect(self._output_state_changed)
        self.screen_manager.singer_window_closed.connect(self._singer_window_closed)
        self.screen_manager.musician_state_changed.connect(self._musician_output_state_changed)

        self.page.set_screens(
            self.screen_manager.descriptors(),
            self.settings.audience_screen_fingerprint,
            self.settings.singer_screen_fingerprint,
            self.settings.musician_screen_fingerprint,
        )
        self.page.set_offsets(
            self.settings.audience_offset_ms,
            self.settings.singer_offset_ms,
            self.settings.musician_offset_ms,
        )
        self.page.set_track_mutes(self._mix_muted)
        self.page.set_track_gains_db(self._mix_gain_db)
        self.page.set_master_volume(self._mix_volume)
        self.screen_manager.set_offsets(
            self.settings.audience_offset_ms, self.settings.singer_offset_ms
        )
        self.screen_manager.set_musician_offset(self.settings.musician_offset_ms)
        window_sizes = self.settings_service.load_output_window_sizes()
        self.screen_manager.set_window_sizes(
            window_sizes.audience_width,
            window_sizes.audience_height,
            window_sizes.singer_width,
            window_sizes.singer_height,
            window_sizes.musician_width,
            window_sizes.musician_height,
        )
        font_sizes = self.settings_service.load_subtitle_font_sizes()
        self.page.set_subtitle_font_sizes(
            font_sizes.audience, font_sizes.singer, font_sizes.musician
        )
        self.screen_manager.set_subtitle_font_sizes(font_sizes.audience, font_sizes.singer)
        self.screen_manager.set_musician_font_size(font_sizes.musician)
        self.screen_manager.set_musician_chord_mode(self._musician_chord_mode)
        self.screen_manager.set_musician_beat_lights_visible(self._musician_beat_lights_visible)
        self.screen_manager.set_singer_display_options(
            self._singer_beat_lights_visible,
            self._singer_music_info_visible,
        )
        self.screen_manager.set_audience_font_family(
            self.audience_font_library.find(self.audience_font_id).family
        )

    def set_language(self, language: str) -> None:
        self.screen_manager.set_language(language)
        self._web_musician_server.set_language(language)
        self._web_singer_server.set_language(language)

    @property
    def current_song_id(self) -> str | None:
        return self._package.config.song_id if self._package is not None else None

    def load_package(self, value: object, auto_play: bool = False) -> None:
        if not isinstance(value, SongPackage):
            self._show_error("加载的歌曲包数据无效")
            return
        self._load_generation += 1
        generation = self._load_generation
        self._auto_play_after_load = auto_play
        self._playback_started = False
        self._close_engine()
        self._package = None
        self._timeline = None
        self._last_preview_line_id = ""
        self._playback_state = PlaybackState.EMPTY.value
        if self._web_musician_server.running:
            self._web_musician_server.set_song(None)
            self._web_musician_server.set_guide_countdown(0, 0)
            self._web_musician_server.set_transport(state=self._playback_state, position_ms=0)
        if self._web_singer_server.running:
            self._web_singer_server.set_song(None)
            self._web_singer_server.set_transport(state=self._playback_state, position_ms=0)
        self.screen_manager.clear_song()
        self._select_background_for_song()
        self.page.set_loading(value.config.title, value.config.artist)
        self.page.set_position(0)
        self.page.set_lyrics_preview("", "")
        self._load_thread = threading.Thread(
            target=self._load_pcm_in_background,
            args=(generation, value),
            name="playback-pcm-load",
            daemon=True,
        )
        self._load_thread.start()

    def apply_settings(self, value: ApplicationSettings) -> None:
        self.settings = value
        self.screen_manager.set_offsets(value.audience_offset_ms, value.singer_offset_ms)
        self.screen_manager.set_musician_offset(value.musician_offset_ms)
        self.page.set_offsets(
            value.audience_offset_ms, value.singer_offset_ms, value.musician_offset_ms
        )
        self._publish_web_singer_display()
        self.page.set_screens(
            self.screen_manager.descriptors(),
            value.audience_screen_fingerprint,
            value.singer_screen_fingerprint,
            value.musician_screen_fingerprint,
        )

    def apply_background_video_settings(self, value: BackgroundVideoSettings) -> None:
        self.background_video_settings = value
        self._select_background_for_song()

    def apply_beat_prompt_sound_enabled(self, enabled: bool) -> None:
        self._beat_prompt_sound_enabled = enabled
        self._sync_beat_prompt()

    def apply_singer_display_options(self, beat_lights: bool, music_info: bool) -> None:
        self._singer_beat_lights_visible = False
        self._singer_music_info_visible = music_info
        self._apply_and_save_singer_display_options()

    def apply_audience_font(self, font_id: str) -> None:
        resource = self.audience_font_library.find(font_id)
        self.audience_font_id = resource.id
        self.screen_manager.set_audience_font_family(resource.family)

    def update_package_lyrics(self, value: object) -> None:
        if not isinstance(value, SongPackage) or self._package is None:
            return
        if value.config.song_id != self._package.config.song_id:
            return
        self._package = value
        self._timeline = LyricTimeline(value.lyrics)
        self._last_preview_line_id = ""
        self.screen_manager.set_document(value.lyrics)
        self.screen_manager.set_chords(value.chords)
        self.screen_manager.set_music_info(
            value.config.musical, title=value.config.title, artist=value.config.artist
        )
        self._sync_beat_prompt()
        position_ms = self._engine.position_ms() if self._engine is not None else 0
        self.page.set_song(
            value.config.title,
            value.config.artist,
            value.config.duration_ms,
            value.config.musical.original_key,
            value.config.musical.bpm,
        )
        self._position_changed(position_ms)
        self._publish_web_song()
        self._publish_web_singer_song()
        self.page.show_status("已加载修改后的歌曲信息和歌词")

    def update_package_chords(self, value: object) -> None:
        if not isinstance(value, SongPackage) or self._package is None:
            return
        if value.config.song_id != self._package.config.song_id:
            return
        self._package = replace(self._package, chords=value.chords)
        self.screen_manager.set_chords(value.chords)
        self._publish_web_song()
        self.page.show_status("已加载修改后的和弦表")

    def close(self) -> None:
        self._load_generation += 1
        self.screen_manager.close_outputs()
        self._close_engine()
        self._message_timer.stop()
        self._web_musician_server.stop()
        self._web_singer_server.stop()
        self._release_sleep_inhibitor()

    def restore_web_displays(self) -> None:
        """Resume displays that were sharing a QR link before the app exited."""
        if self.settings_service.load_web_display_enabled("singer"):
            self._set_web_singer_enabled(True, show_qr=False)
        if self.settings_service.load_web_display_enabled("musician"):
            self._set_web_musician_enabled(True, show_qr=False)

    def stop_for_song_change(self) -> None:
        """手动切歌时立刻停止当前歌曲，等待下一首完成加载。"""
        self._stop()

    def _load_pcm_in_background(self, generation: int, package: SongPackage) -> None:
        try:
            paths = {
                track: resolve_package_path(package.root, package.config.audio.tracks[track].file)
                for track in package.config.audio.tracks
            }
            pcm = self._pcm_cache.load(
                paths,
                on_progress=lambda track, current, total: self._messages.put(
                    (
                        "progress",
                        (generation, f"正在解码 {track.value}（{current}/{total}）"),
                    )
                ),
            )
            self._messages.put(("loaded", (generation, package, pcm)))
        except Exception as exc:
            self._messages.put(
                (
                    "failed",
                    (generation, str(exc), traceback.format_exc()),
                )
            )

    def _drain_messages(self) -> None:
        while True:
            try:
                event, payload = self._messages.get_nowait()
            except queue.Empty:
                return
            if event == "progress" and isinstance(payload, tuple):
                generation, message = payload
                if generation == self._load_generation:
                    self.page.show_status(str(message))
            elif event == "loaded" and isinstance(payload, tuple):
                generation, package, pcm = payload
                if (
                    generation == self._load_generation
                    and isinstance(package, SongPackage)
                    and isinstance(pcm, PcmSongData)
                ):
                    self._finish_load(package, pcm)
            elif event == "failed" and isinstance(payload, tuple):
                generation, message, details = payload
                if generation == self._load_generation:
                    self._show_error(str(message), str(details))
                    self.song_load_failed.emit(str(message))
            elif event == "musician_chord_mode" and isinstance(payload, str):
                self.apply_musician_chord_mode(payload)

    def _finish_load(self, package: SongPackage, pcm: PcmSongData) -> None:
        self._package = package
        self._playback_rate = 1.0
        self._timeline = LyricTimeline(package.lyrics)
        self._engine = StemMixerEngine(
            output_device=self.settings.audio_output_device,
            parent=self,
        )
        default_mutes = dict(self._mix_muted)
        self._engine.load_pcm(
            pcm,
            default_muted=default_mutes,
            gain_db=self._mix_gain_db,
            mute_fade_ms=12,
            master_volume=self._mix_volume,
        )
        self._engine.set_playback_rate(self._playback_rate)
        self._sync_beat_prompt()
        self._engine.position_changed.connect(self._position_changed)
        self._engine.guide_countdown_changed.connect(self._set_guide_countdown)
        self._engine.state_changed.connect(self._state_changed)
        self._engine.track_mute_changed.connect(self._track_mute_changed)
        self._engine.error_raised.connect(self._show_error)
        self.screen_manager.set_document(package.lyrics)
        self.screen_manager.set_chords(package.chords)
        self.screen_manager.set_music_info(
            package.config.musical,
            title=package.config.title,
            artist=package.config.artist,
        )
        self.page.set_song(
            package.config.title,
            package.config.artist,
            pcm.duration_ms,
            package.config.musical.original_key,
            package.config.musical.bpm,
        )
        self.page.set_master_volume(self._mix_volume)
        self.page.set_available_tracks(set(pcm.tracks))
        self.page.set_track_mutes(default_mutes)
        self.page.set_track_gains_db(self._mix_gain_db)
        self.page.set_playback_state(PlaybackState.STOPPED.value)
        self._playback_state = PlaybackState.STOPPED.value
        self._position_changed(0)
        self._publish_web_song()
        self._publish_web_singer_song()
        self.song_loaded.emit(package.config.song_id)
        if self._auto_play_after_load:
            self._auto_play_after_load = False
            self._engine.play()
            self._playback_started = self._engine.state() == PlaybackState.PLAYING

    def _toggle_playback(self) -> None:
        if self._engine is None:
            return
        if self._engine.state() == PlaybackState.PLAYING:
            self._engine.pause()
        else:
            self._engine.play()
            self._playback_started = self._engine.state() == PlaybackState.PLAYING
        self._set_guide_countdown(*self._engine.guide_countdown())

    def _stop(self) -> None:
        if self._engine is not None:
            self._playback_started = False
            self._engine.stop()
            self._set_guide_countdown(*self._engine.guide_countdown())

    def _restart(self) -> None:
        """Return to the start so the next Play begins with the optional guide."""
        self._stop()
        if self._engine is not None:
            self.page.set_playback_state(PlaybackState.STOPPED.value)
            self._position_changed(0)

    def _seek(self, position_ms: int) -> None:
        if self._engine is not None:
            if self._package is not None and position_ms >= self._package.config.duration_ms:
                self._playback_started = False
            self._engine.seek_ms(position_ms)
            self._position_changed(self._engine.position_ms())

    def _set_track_mute(self, track_value: str, muted: bool) -> None:
        try:
            track = TrackKind(track_value)
        except ValueError:
            return
        self._mix_muted[track] = muted
        if self._engine is not None:
            self._engine.set_track_muted(track, muted)
        self._save_mixer_settings()

    def _set_track_gain(self, track_value: str, value_db: float) -> None:
        try:
            track = TrackKind(track_value)
        except ValueError:
            return
        value_db = self._snap_track_gain_db(value_db)
        self._mix_gain_db[track] = value_db
        if self._engine is not None:
            self._engine.set_track_gain_db(track, value_db)
        self._save_mixer_settings()

    @staticmethod
    def _snap_track_gain_db(value_db: float) -> float:
        percentage = 0 if value_db <= -96.0 else round(100 * math.pow(10.0, value_db / 20.0))
        percentage = max(0, min(150, ((percentage + 5) // 10) * 10))
        return -96.0 if percentage == 0 else 20.0 * math.log10(percentage / 100.0)

    def _set_playback_bpm(self, bpm: int) -> None:
        if self._package is None:
            return
        original_bpm = self._package.config.musical.bpm
        value = bpm / original_bpm
        if not 0.2 <= value <= 2.0:
            return
        self._playback_rate = value
        if self._engine is not None:
            self._engine.set_playback_rate(value)

    def _set_master_volume(self, value: float) -> None:
        self._mix_volume = value
        if self._engine is not None:
            self._engine.set_master_volume(value)
        self._save_mixer_settings()

    def _save_mixer_settings(self) -> None:
        """混音参数一经修改便保存。"""
        try:
            self.settings_service.save_mixer_settings(
                MixerSettings(
                    master_volume=self._mix_volume,
                    muted_tracks=frozenset(
                        track for track, muted in self._mix_muted.items() if muted
                    ),
                    track_gain_db=dict(self._mix_gain_db),
                )
            )
        except Exception as exc:
            self._show_error("保存系统混音参数失败", str(exc))

    def _set_audience_output_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.screen_manager.close_audience_output()
            self.page.show_status("观众屏窗口已关闭")
            return
        if self._package is None:
            self._show_error("请先加载歌曲")
            self.page.set_output_states(False, self.screen_manager.singer_window is not None)
            return
        try:
            self.screen_manager.open_audience_output(
                self._package.lyrics,
                self.page.audience_selector.fingerprint(),
            )
        except Exception as exc:
            self.page.set_output_states(False, self.screen_manager.singer_window is not None)
            self._show_error("打开观众屏输出失败", str(exc))
            return
        self.page.show_status("观众屏窗口已打开，可拖动或全屏")

    def _set_singer_output_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.screen_manager.close_singer_output()
            if not self.page.web_singer_button.isChecked():
                self._web_singer_server.stop()
            self.page.show_status("歌手屏窗口已关闭")
            return
        if self._package is None:
            self._show_error("请先加载歌曲")
            self.page.set_output_states(self.screen_manager.audience_window is not None, False)
            return
        try:
            self._web_singer_server.start()
            self._publish_web_singer_display()
            self._publish_web_singer_song()
            position_ms = self._engine.position_ms() if self._engine is not None else 0
            self._web_singer_server.set_transport(
                state=self._playback_state, position_ms=position_ms
            )
            url = self._web_singer_server.local_url
            if url is None:
                raise RuntimeError("本地网页歌手屏地址不可用")
            self.screen_manager.open_web_singer_output(
                url, self.page.singer_selector.fingerprint()
            )
        except Exception as exc:
            if not self.page.web_singer_button.isChecked():
                self._web_singer_server.stop()
            self.page.set_output_states(self.screen_manager.audience_window is not None, False)
            self._show_error("打开歌手屏输出失败", str(exc))
            return
        self.page.show_status("歌手屏窗口已打开，可拖动或全屏")

    def _set_musician_output_enabled(self, enabled: bool) -> None:
        if not enabled:
            self.screen_manager.close_musician_output()
            self.page.show_status("乐手屏窗口已关闭")
            return
        package = self._package
        if package is None:
            self._show_error("请先加载歌曲")
            self.page.set_musician_output_state(False)
            return
        try:
            self._web_musician_server.start()
            self._web_musician_server.set_guide_countdown(0, 0)
            self._publish_web_display()
            self._publish_web_song()
            position_ms = self._engine.position_ms() if self._engine is not None else 0
            self._web_musician_server.set_transport(
                state=self._playback_state, position_ms=position_ms
            )
            url = self._web_musician_server.local_url
            if url is None:
                raise RuntimeError("本地网页乐手屏地址不可用")
            self.screen_manager.open_web_musician_output(
                url, self.page.musician_selector.fingerprint()
            )
            self._sync_beat_prompt()
        except Exception as exc:
            self.page.set_musician_output_state(False)
            if not self.page.web_musician_button.isChecked():
                self._web_musician_server.stop()
            self._show_error("打开乐手屏输出失败", str(exc))
            return
        if package.chords is None or not package.chords.segments:
            self.page.show_status("没有和弦数据，请到“歌曲库”的修改页面中，重新分析和弦数据")
        else:
            self.page.show_status("乐手屏窗口已打开，可拖动或全屏")

    def _set_web_musician_enabled(self, enabled: bool, *, show_qr: bool = True) -> None:
        if not enabled:
            if self._web_musician_dialog is not None:
                self._web_musician_dialog.close()
                self._web_musician_dialog = None
            if self.screen_manager.musician_window is None:
                self._web_musician_server.set_guide_countdown(0, 0)
                self._web_musician_server.stop()
            self._sync_beat_prompt()
            self.page.set_web_musician_state(False)
            self.settings_service.save_web_display_enabled("musician", False)
            self.page.show_status("网页乐手屏已关闭")
            return
        try:
            self._web_musician_server.start()
            self._web_musician_server.set_guide_countdown(0, 0)
            self._publish_web_display()
            self._publish_web_song()
            position_ms = self._engine.position_ms() if self._engine is not None else 0
            self._web_musician_server.set_transport(
                state=self._playback_state,
                position_ms=position_ms,
            )
            self._sync_beat_prompt()
        except Exception as exc:
            self._web_musician_server.stop()
            self.page.set_web_musician_state(False)
            if show_qr:
                self._show_error("启动网页乐手屏失败", str(exc))
            else:
                self.page.show_status(f"网页乐手屏自动恢复失败：{exc}")
            return
        self.page.set_web_musician_state(True)
        self.settings_service.save_web_display_enabled("musician", True)
        self.page.show_status("网页乐手屏已开启；手机或 iPad 与电脑连接同一局域网后扫码访问")
        if show_qr:
            self._show_web_musician_dialog()

    def _show_web_musician_dialog(self) -> None:
        url = self._web_musician_server.url
        if url is None:
            return
        if self._web_musician_dialog is not None:
            self._web_musician_dialog.close()
        dialog = WebMusicianDialog(url, parent=self.page.window())
        dialog.finished.connect(lambda _result: self._clear_web_musician_dialog(dialog))
        self._web_musician_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_web_musician_dialog(self, dialog: WebMusicianDialog) -> None:
        if self._web_musician_dialog is dialog:
            self._web_musician_dialog = None

    def _set_web_singer_enabled(self, enabled: bool, *, show_qr: bool = True) -> None:
        if not enabled:
            if self._web_singer_dialog is not None:
                self._web_singer_dialog.close()
                self._web_singer_dialog = None
            if self.screen_manager.singer_window is None:
                self._web_singer_server.stop()
            self.page.set_web_singer_state(False)
            self.settings_service.save_web_display_enabled("singer", False)
            self.page.show_status("网页歌手屏已关闭")
            return
        try:
            self._web_singer_server.start()
            self._publish_web_singer_display()
            self._publish_web_singer_song()
            position_ms = self._engine.position_ms() if self._engine is not None else 0
            self._web_singer_server.set_transport(
                state=self._playback_state, position_ms=position_ms
            )
        except Exception as exc:
            if self.screen_manager.singer_window is None:
                self._web_singer_server.stop()
            self.page.set_web_singer_state(False)
            if show_qr:
                self._show_error("启动网页歌手屏失败", str(exc))
            else:
                self.page.show_status(f"网页歌手屏自动恢复失败：{exc}")
            return
        self.page.set_web_singer_state(True)
        self.settings_service.save_web_display_enabled("singer", True)
        self.page.show_status("网页歌手屏已开启；手机或 iPad 与电脑连接同一局域网后扫码访问")
        if show_qr:
            self._show_web_singer_dialog()

    def _show_web_singer_dialog(self) -> None:
        url = self._web_singer_server.url
        if url is None:
            return
        if self._web_singer_dialog is not None:
            self._web_singer_dialog.close()
        dialog = WebMusicianDialog(url, parent=self.page.window(), display_name="歌手")
        dialog.finished.connect(lambda _result: self._clear_web_singer_dialog(dialog))
        self._web_singer_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _clear_web_singer_dialog(self, dialog: WebMusicianDialog) -> None:
        if self._web_singer_dialog is dialog:
            self._web_singer_dialog = None

    def _publish_web_singer_display(self) -> None:
        if self._web_singer_server.running:
            self._web_singer_server.set_singer_display(
                offset_ms=self.page.singer_offset.value(),
                font_size=self.page.singer_font_size.value(),
                music_info_visible=self._singer_music_info_visible,
            )

    def _publish_web_singer_song(self) -> None:
        if not self._web_singer_server.running:
            return
        package = self._package
        self._web_singer_server.set_song(
            build_web_singer_song(
                package.lyrics,
                title=package.config.title,
                artist=package.config.artist,
                original_key=package.config.musical.original_key,
                bpm=package.config.musical.bpm,
            )
            if package is not None
            else None
        )

    def _publish_web_display(self) -> None:
        if not self._web_musician_server.running:
            return
        self._web_musician_server.set_display(
            chord_mode=self._musician_chord_mode,
            offset_ms=self.page.musician_offset.value(),
        )

    def _publish_web_song(self) -> None:
        if not self._web_musician_server.running:
            return
        package = self._package
        self._web_musician_server.set_song(
            build_web_musician_song(package, self._musician_chord_mode)
            if package is not None
            else None
        )

    def _set_guide_countdown(self, remaining: int, total: int) -> None:
        self.screen_manager.set_guide_countdown(remaining, total)
        if self._web_musician_server.running:
            self._web_musician_server.set_guide_countdown(remaining, total)

    def _set_offsets(self, audience_ms: int, singer_ms: int) -> None:
        self.screen_manager.set_offsets(audience_ms, singer_ms)
        self._publish_web_singer_display()
        self._save_runtime_screen_settings()

    def _set_musician_offset(self, musician_ms: int) -> None:
        self.screen_manager.set_musician_offset(musician_ms)
        self._publish_web_display()
        self._save_runtime_screen_settings()

    def _set_subtitle_font_sizes(self, audience: int, singer: int) -> None:
        self.screen_manager.set_subtitle_font_sizes(audience, singer)
        self._publish_web_singer_display()
        try:
            self.settings_service.save_subtitle_font_sizes(
                SubtitleFontSizes(
                    audience=audience,
                    singer=singer,
                    musician=self.page.musician_font_size.value(),
                )
            )
        except Exception as exc:
            self._show_error("保存字幕字号失败", str(exc))
            return
        self.page.show_status(f"字幕字号已保存：观众 {audience} pt，歌手 {singer} pt")

    def _set_musician_font_size(self, musician: int) -> None:
        self.screen_manager.set_musician_font_size(musician)
        try:
            self.settings_service.save_subtitle_font_sizes(
                SubtitleFontSizes(
                    audience=self.page.audience_font_size.value(),
                    singer=self.page.singer_font_size.value(),
                    musician=musician,
                )
            )
        except Exception as exc:
            self._show_error("保存乐手屏字号失败", str(exc))
            return
        self.page.show_status(f"乐手屏字号已保存：{musician} pt")

    def apply_musician_chord_mode(self, mode: str) -> None:
        try:
            self.screen_manager.set_musician_chord_mode(mode)
            self._musician_chord_mode = mode
            self._publish_web_display()
            self._publish_web_song()
            self._save_musician_display_settings()
        except Exception as exc:
            self._show_error("保存乐手屏和弦模式失败", str(exc))

    def apply_musician_beat_lights_visible(self, visible: bool) -> None:
        try:
            self.screen_manager.set_musician_beat_lights_visible(False)
            self._musician_beat_lights_visible = False
            self._publish_web_display()
            self._save_musician_display_settings()
        except Exception as exc:
            self._show_error("保存乐手屏拍子灯设置失败", str(exc))

    def _save_musician_display_settings(self) -> None:
        self.settings_service.save_musician_display_settings(
            MusicianDisplaySettings(
                chord_mode=self._musician_chord_mode,
                beat_lights_visible=self._musician_beat_lights_visible,
            )
        )

    def _set_singer_beat_lights_visible(self, visible: bool) -> None:
        self._singer_beat_lights_visible = visible
        self._apply_and_save_singer_display_options()
        self.page.show_status(f"歌手屏拍子灯已{'显示' if visible else '隐藏'}")

    def _set_singer_music_info_visible(self, visible: bool) -> None:
        self._singer_music_info_visible = visible
        self._apply_and_save_singer_display_options()
        self.page.show_status(f"歌手屏歌曲信息已{'显示' if visible else '隐藏'}")

    def _apply_and_save_singer_display_options(self) -> None:
        """即时更新歌手屏，并保存两个显示项的组合状态。"""
        self.screen_manager.set_singer_display_options(
            self._singer_beat_lights_visible,
            self._singer_music_info_visible,
        )
        self._publish_web_singer_display()
        self._sync_beat_prompt()
        try:
            self.settings_service.save_singer_display_settings(
                SingerDisplaySettings(
                    beat_lights_visible=self._singer_beat_lights_visible,
                    music_info_visible=self._singer_music_info_visible,
                )
            )
        except Exception as exc:
            self._show_error("保存歌手屏显示设置失败", str(exc))

    def _screen_selection_changed(self, _fingerprint: str) -> None:
        self._save_runtime_screen_settings()

    def _save_runtime_screen_settings(self) -> None:
        """即时保存显示器与补偿参数，并同步设置页面。"""
        try:
            self._persist_runtime_screen_settings(
                self.page.audience_selector.fingerprint(),
                self.page.singer_selector.fingerprint(),
                self.page.musician_selector.fingerprint(),
            )
        except Exception as exc:
            self._show_error("保存舞台三屏输出参数失败", str(exc))

    def _save_output_sizes(
        self,
        audience_width: int,
        audience_height: int,
        singer_width: int,
        singer_height: int,
        musician_width: int,
        musician_height: int,
    ) -> None:
        self.settings_service.save_output_window_sizes(
            OutputWindowSizes(
                audience_width=audience_width,
                audience_height=audience_height,
                singer_width=singer_width,
                singer_height=singer_height,
                musician_width=musician_width,
                musician_height=musician_height,
            )
        )

    def _persist_runtime_screen_settings(self, audience: str, singer: str, musician: str) -> None:
        self.settings = replace(
            self.settings,
            audience_screen_fingerprint=audience,
            singer_screen_fingerprint=singer,
            musician_screen_fingerprint=musician,
            audience_offset_ms=self.page.audience_offset.value(),
            singer_offset_ms=self.page.singer_offset.value(),
            musician_offset_ms=self.page.musician_offset.value(),
        )
        self.settings_service.save(self.settings)
        self.settings_changed.emit(self.settings)

    def _screens_changed(self, _screens: object) -> None:
        self.page.set_screens(
            self.screen_manager.descriptors(),
            self.settings.audience_screen_fingerprint,
            self.settings.singer_screen_fingerprint,
            self.settings.musician_screen_fingerprint,
        )

    def _position_changed(self, position_ms: int) -> None:
        self.page.set_position(position_ms)
        self.screen_manager.update_from_master(position_ms)
        now = time.monotonic()
        if (
            self._web_musician_server.running or self._web_singer_server.running
        ) and now - self._last_web_transport_push >= 0.1:
            self._last_web_transport_push = now
            for server in (self._web_musician_server, self._web_singer_server):
                if server.running:
                    server.set_transport(state=self._playback_state, position_ms=position_ms)
        if self._timeline is None:
            return
        context = self._timeline.context_at(position_ms)
        current_id = context.current.id if context.current is not None else ""
        if current_id != self._last_preview_line_id:
            self._last_preview_line_id = current_id
            self.page.set_lyrics_preview(
                context.current.text if context.current is not None else "",
                context.next.text if context.next is not None else "",
            )

    def _state_changed(self, state: object) -> None:
        self._playback_state = str(state)
        self.page.set_playback_state(self._playback_state)
        position_ms = self._engine.position_ms() if self._engine is not None else 0
        self._last_web_transport_push = time.monotonic()
        if self._web_musician_server.running:
            self._web_musician_server.set_transport(
                state=self._playback_state,
                position_ms=position_ms,
            )
        if self._web_singer_server.running:
            self._web_singer_server.set_transport(
                state=self._playback_state, position_ms=position_ms
            )
        self.screen_manager.set_background_video_playing(state == PlaybackState.PLAYING)
        if state == PlaybackState.PLAYING:
            if self._sleep_token is None:
                self._sleep_token = sleep_inhibitor.acquire("正式播放")
            self._playback_started = True
        elif state == PlaybackState.ENDED and self._playback_started:
            self._release_sleep_inhibitor()
            self._playback_started = False
            self.song_finished.emit()
        elif state in {PlaybackState.STOPPED, PlaybackState.ERROR}:
            self._release_sleep_inhibitor()
            self._playback_started = False

    def _release_sleep_inhibitor(self) -> None:
        sleep_inhibitor.release(self._sleep_token)
        self._sleep_token = None

    def _select_background_for_song(self) -> None:
        resource = None
        if self.background_video_settings.mode == "random":
            candidates = self.background_video_library.playable_resources()
            if candidates:
                resource = random.choice(candidates)
        else:
            resource = self.background_video_library.find(
                self.background_video_settings.fixed_resource_id
            )
        if resource is None:
            self._current_background_resource_id = "none"
            self.screen_manager.set_background_video(None)
            return
        self._current_background_resource_id = resource.id
        self.screen_manager.set_background_video(resource.path)

    def _track_mute_changed(self, _track: str, _muted: bool) -> None:
        if self._engine is None:
            return
        self.page.set_track_mutes(
            {track: self._engine.is_track_muted(track) for track in TrackKind}
        )

    def _show_error(self, message: str, details: str = "") -> None:
        message = public_message(message, "播放操作失败，请重试")
        details = public_message(details, "请重试或检查歌曲文件")
        self.page.show_status(f"错误：{message}")
        dialog = ErrorDetailsDialog("发生错误", message, details, parent=self.page.window())
        dialog.exec()

    def _close_engine(self) -> None:
        if self._engine is not None:
            self._engine.close()
            self._engine.deleteLater()
            self._engine = None

    def _output_state_changed(self, audience_open: bool, singer_open: bool) -> None:
        self.page.set_output_states(audience_open, singer_open)

    def _singer_window_closed(self) -> None:
        if not self.page.web_singer_button.isChecked():
            self._web_singer_server.stop()

    def _musician_output_state_changed(self, visible: bool) -> None:
        self.page.set_musician_output_state(visible)
        if not visible and not self.page.web_musician_button.isChecked():
            self._web_musician_server.stop()
        self._sync_beat_prompt()

    def _sync_beat_prompt(self) -> None:
        """Prepare the optional two-bar guide before the song starts."""
        if self._engine is None:
            return
        musical = self._package.config.musical if self._package is not None else None
        musician = self.screen_manager.musician_window
        musician_visible = musician is not None and musician.isVisible()
        self._engine.set_guide_beats(
            self._beat_prompt_sound_enabled
            and (musician_visible or self._web_musician_server.running),
            bpm=musical.bpm if musical is not None else None,
            beats_per_bar=(musical.beats_per_bar or 4) if musical is not None else None,
            count_in_bars=2,
            first_beat_ms=(musical.beat_times_ms[0] if musical and musical.beat_times_ms else None),
        )
        self._set_guide_countdown(*self._engine.guide_countdown())

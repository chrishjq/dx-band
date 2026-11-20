# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSettings

from dxband.analysis.chord_notation import valid_display_mode
from dxband.constants import MUSICIAN_FONT_SIZE_MIN, TrackKind
from dxband.services.application_paths import default_library_root


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    library_root: Path
    audio_output_device: int | None
    audience_screen_fingerprint: str
    singer_screen_fingerprint: str
    audience_offset_ms: int
    singer_offset_ms: int
    musician_screen_fingerprint: str = ""
    musician_offset_ms: int = 0


@dataclass(frozen=True, slots=True)
class OutputWindowSizes:
    audience_width: int = 0
    audience_height: int = 0
    singer_width: int = 0
    singer_height: int = 0
    musician_width: int = 0
    musician_height: int = 0


@dataclass(frozen=True, slots=True)
class SubtitleFontSizes:
    audience: int = 72
    singer: int = 42
    musician: int = 32


@dataclass(frozen=True, slots=True)
class MusicianDisplaySettings:
    chord_mode: str = "degree"
    beat_lights_visible: bool = False


@dataclass(frozen=True, slots=True)
class MixerSettings:
    master_volume: float = 0.85
    muted_tracks: frozenset[TrackKind] = frozenset()
    track_gain_db: dict[TrackKind, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BackgroundVideoSettings:
    mode: str = "fixed"
    fixed_resource_id: str = "none"


@dataclass(frozen=True, slots=True)
class SingerDisplaySettings:
    beat_lights_visible: bool = False
    music_info_visible: bool = True


class SettingsService:
    """使用 QSettings 保存应用级配置。"""

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings if settings is not None else QSettings("DXBand", "DX Band")
        if settings is None and not self.settings.allKeys():
            previous = QSettings("DXStage", "DX Stage")
            for key in previous.allKeys():
                self.settings.setValue(key, previous.value(key))
            if previous.allKeys():
                self.settings.sync()

    def load(self) -> ApplicationSettings:
        raw_device = self.settings.value("audio/output_device", None)
        try:
            output_device = self._to_int(raw_device, 0) if raw_device not in {None, ""} else None
        except (TypeError, ValueError):
            output_device = None
        stored_root = self.settings.value("library/root", None)
        library_root = (
            Path(str(stored_root)).expanduser() if stored_root else default_library_root()
        )
        return ApplicationSettings(
            library_root=library_root,
            audio_output_device=output_device,
            audience_screen_fingerprint=str(
                self.settings.value("screens/audience_fingerprint", "")
            ),
            singer_screen_fingerprint=str(self.settings.value("screens/singer_fingerprint", "")),
            audience_offset_ms=self._to_int(
                self.settings.value("screens/audience_offset_ms", 0), 0
            ),
            singer_offset_ms=self._to_int(
                self.settings.value("screens/singer_offset_ms", 150), 150
            ),
            musician_screen_fingerprint=str(
                self.settings.value("screens/musician_fingerprint", "")
            ),
            musician_offset_ms=self._to_int(
                self.settings.value("screens/musician_offset_ms", 0), 0
            ),
        )

    def save(self, value: ApplicationSettings) -> None:
        self.settings.setValue("library/root", str(value.library_root.expanduser()))
        self.settings.setValue("audio/output_device", value.audio_output_device)
        self.settings.setValue("screens/audience_fingerprint", value.audience_screen_fingerprint)
        self.settings.setValue("screens/singer_fingerprint", value.singer_screen_fingerprint)
        self.settings.setValue("screens/musician_fingerprint", value.musician_screen_fingerprint)
        self.settings.setValue("screens/audience_offset_ms", value.audience_offset_ms)
        self.settings.setValue("screens/singer_offset_ms", value.singer_offset_ms)
        self.settings.setValue("screens/musician_offset_ms", value.musician_offset_ms)
        self.settings.sync()

    def load_language(self) -> str:
        language = str(self.settings.value("appearance/language", "zh"))
        return language if language in {"zh", "en"} else "zh"

    def save_language(self, language: str) -> None:
        if language not in {"zh", "en"}:
            raise ValueError("Unsupported interface language")
        self.settings.setValue("appearance/language", language)
        self.settings.sync()

    def load_output_window_sizes(self) -> OutputWindowSizes:
        """读取两个歌词输出窗口上次使用的窗口尺寸。"""
        return OutputWindowSizes(
            audience_width=max(
                0,
                self._to_int(self.settings.value("screens/audience_window_width", 0), 0),
            ),
            audience_height=max(
                0,
                self._to_int(self.settings.value("screens/audience_window_height", 0), 0),
            ),
            singer_width=max(
                0,
                self._to_int(self.settings.value("screens/singer_window_width", 0), 0),
            ),
            singer_height=max(
                0,
                self._to_int(self.settings.value("screens/singer_window_height", 0), 0),
            ),
            musician_width=max(
                0,
                self._to_int(self.settings.value("screens/musician_window_width", 0), 0),
            ),
            musician_height=max(
                0,
                self._to_int(self.settings.value("screens/musician_window_height", 0), 0),
            ),
        )

    def save_output_window_sizes(self, value: OutputWindowSizes) -> None:
        """持久化两个歌词输出窗口的窗口尺寸。"""
        self.settings.setValue("screens/audience_window_width", value.audience_width)
        self.settings.setValue("screens/audience_window_height", value.audience_height)
        self.settings.setValue("screens/singer_window_width", value.singer_width)
        self.settings.setValue("screens/singer_window_height", value.singer_height)
        self.settings.setValue("screens/musician_window_width", value.musician_width)
        self.settings.setValue("screens/musician_window_height", value.musician_height)
        self.settings.sync()

    def load_subtitle_font_sizes(self) -> SubtitleFontSizes:
        """读取观众屏与歌手屏的字幕字号。"""
        return SubtitleFontSizes(
            audience=max(
                36,
                self._to_int(self.settings.value("screens/audience_font_size", 72), 72),
            ),
            singer=max(
                24,
                self._to_int(self.settings.value("screens/singer_font_size", 42), 42),
            ),
            musician=max(
                MUSICIAN_FONT_SIZE_MIN,
                self._to_int(self.settings.value("screens/musician_font_size", 32), 32),
            ),
        )

    def save_subtitle_font_sizes(self, value: SubtitleFontSizes) -> None:
        """持久化观众屏与歌手屏的字幕字号。"""
        self.settings.setValue("screens/audience_font_size", value.audience)
        self.settings.setValue("screens/singer_font_size", value.singer)
        self.settings.setValue("screens/musician_font_size", value.musician)
        self.settings.sync()

    def load_musician_display_settings(self) -> MusicianDisplaySettings:
        mode = str(self.settings.value("screens/musician_chord_mode", "degree"))
        return MusicianDisplaySettings(
            chord_mode=mode if valid_display_mode(mode) else "degree",
        )

    def save_musician_display_settings(self, value: MusicianDisplaySettings) -> None:
        if not valid_display_mode(value.chord_mode):
            raise ValueError("无效的乐手屏和弦模式")
        self.settings.setValue("screens/musician_chord_mode", value.chord_mode)
        self.settings.remove("screens/musician_beat_lights_visible")
        self.settings.sync()

    def load_singer_display_settings(self) -> SingerDisplaySettings:
        """读取歌手屏歌曲信息的显示状态。"""
        return SingerDisplaySettings(
            music_info_visible=self._to_bool(
                self.settings.value("screens/singer_music_info_visible", True)
            ),
        )

    def save_singer_display_settings(self, value: SingerDisplaySettings) -> None:
        """持久化歌手屏歌曲信息的显示状态。"""
        self.settings.remove("screens/singer_beat_lights_visible")
        self.settings.setValue("screens/singer_music_info_visible", value.music_info_visible)
        self.settings.sync()

    def load_auto_play_next(self) -> bool:
        """读取播放列表的自动续播开关。"""
        return str(self.settings.value("playback/auto_play_next", False)).lower() in {"true", "1"}

    def save_auto_play_next(self, enabled: bool) -> None:
        """保存自动续播开关，与具体歌曲无关。"""
        self.settings.setValue("playback/auto_play_next", enabled)
        self.settings.sync()

    def load_web_display_enabled(self, display: str) -> bool:
        if display not in {"musician", "singer"}:
            raise ValueError("无效的网页屏幕类型")
        return self._to_bool(self.settings.value(f"web/{display}_enabled", False))

    def save_web_display_enabled(self, display: str, enabled: bool) -> None:
        if display not in {"musician", "singer"}:
            raise ValueError("无效的网页屏幕类型")
        self.settings.setValue(f"web/{display}_enabled", enabled)
        self.settings.sync()

    def load_beat_prompt_sound_enabled(self) -> bool:
        """读取引导拍子声开关，沿用原设置键以保留用户选择。"""
        return self._to_bool(self.settings.value("playback/beat_prompt_sound_enabled", False))

    def save_beat_prompt_sound_enabled(self, enabled: bool) -> None:
        """保存引导拍子声开关。"""
        self.settings.setValue("playback/beat_prompt_sound_enabled", enabled)
        self.settings.sync()

    def load_mixer_settings(self) -> MixerSettings:
        """读取跨歌曲共用的音轨静音和主音量。"""
        raw_volume = self.settings.value("mix/master_volume", 0.85)
        try:
            volume = max(0.0, min(1.0, float(str(raw_volume))))
        except (TypeError, ValueError):
            volume = 0.85
        muted = frozenset(
            track
            for track in TrackKind
            if self._to_bool(self.settings.value(f"mix/muted/{track.value}", False))
        )
        track_gain_db: dict[TrackKind, float] = {}
        for track in TrackKind:
            raw_gain = self.settings.value(f"mix/gain_db/{track.value}", 0.0)
            try:
                gain_db = max(-96.0, min(3.52, float(str(raw_gain))))
            except (TypeError, ValueError):
                gain_db = 0.0
            if gain_db != 0.0:
                track_gain_db[track] = gain_db
        return MixerSettings(
            master_volume=volume,
            muted_tracks=muted,
            track_gain_db=track_gain_db,
        )

    def save_mixer_settings(self, value: MixerSettings) -> None:
        """同步全局混音参数到应用配置。"""
        self.settings.setValue("mix/master_volume", value.master_volume)
        for track in TrackKind:
            self.settings.setValue(f"mix/muted/{track.value}", track in value.muted_tracks)
            self.settings.setValue(
                f"mix/gain_db/{track.value}",
                max(-96.0, min(3.52, value.track_gain_db.get(track, 0.0))),
            )
        self.settings.sync()

    def load_background_video_settings(self) -> BackgroundVideoSettings:
        mode = str(self.settings.value("background_video/mode", "fixed"))
        if mode not in {"random", "fixed"}:
            mode = "fixed"
        return BackgroundVideoSettings(
            mode=mode,
            fixed_resource_id=str(
                self.settings.value("background_video/fixed_resource_id", "none")
            ),
        )

    def save_background_video_settings(self, value: BackgroundVideoSettings) -> None:
        if value.mode not in {"random", "fixed"}:
            raise ValueError("背景视频播放策略必须为 random 或 fixed")
        self.settings.setValue("background_video/mode", value.mode)
        self.settings.setValue("background_video/fixed_resource_id", value.fixed_resource_id)
        self.settings.sync()

    def load_audience_font_id(self) -> str:
        return str(self.settings.value("appearance/audience_font_id", "default"))

    def save_audience_font_id(self, font_id: str) -> None:
        self.settings.setValue("appearance/audience_font_id", font_id)
        self.settings.sync()

    @staticmethod
    def _to_int(value: object, default: int) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_bool(value: object) -> bool:
        return str(value).lower() in {"true", "1"}

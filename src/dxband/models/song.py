# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from datetime import datetime
from itertools import pairwise
from typing import Literal

from pydantic import Field, field_validator, model_validator

from dxband.constants import (
    LEGACY_TRACK_KINDS,
    SIX_STEM_TRACK_KINDS,
    TRACK_FILENAMES,
    TrackKind,
)
from dxband.models.base import StrictModel
from dxband.models.track import SHA256_PATTERN, TrackConfig


class SourceConfig(StrictModel):
    original_filename: str = Field(min_length=1)
    sha256: str
    original_copied: bool = False
    lrc_filename: str | None = None
    lrc_sha256: str | None = None

    @field_validator("sha256", "lrc_sha256")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("sha256 must contain exactly 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def validate_lrc_pair(self) -> "SourceConfig":
        if (self.lrc_filename is None) != (self.lrc_sha256 is None):
            raise ValueError("lrc_filename and lrc_sha256 must either both be set or both be null")
        return self


class SeparationConfig(StrictModel):
    engine: Literal["demucs"]
    model: Literal["htdemucs_ft", "htdemucs_6s"]
    demucs_version: str = Field(min_length=1)
    device: str = Field(min_length=1)
    output_format: Literal["mp3"]
    bitrate_kbps: Literal[320]
    mp3_preset: int = Field(ge=0, le=9)


class AudioConfig(StrictModel):
    sample_rate_hz: Literal[44100]
    channels: Literal[2]
    canonical_frames: int = Field(gt=0)
    tracks: dict[TrackKind, TrackConfig]

    @model_validator(mode="after")
    def validate_tracks(self) -> "AudioConfig":
        actual = set(self.tracks)
        supported = (LEGACY_TRACK_KINDS, SIX_STEM_TRACK_KINDS)
        if actual not in supported:
            expected = SIX_STEM_TRACK_KINDS
            missing = sorted(track.value for track in expected - actual)
            extra = sorted(str(track) for track in actual - expected)
            raise ValueError(
                "tracks must contain either the legacy four stems or all six stems; "
                f"missing={missing}, extra={extra}"
            )
        for track in actual:
            expected_file = TRACK_FILENAMES[track]
            if self.tracks[track].file != expected_file:
                raise ValueError(f"{track.value} track file must be {expected_file}")
        return self


class MusicalConfig(StrictModel):
    """歌曲音乐属性；逐拍时间表是播放时节奏提示的唯一时间依据。"""

    original_key: str = Field(min_length=1, max_length=16)
    bpm: int = Field(ge=20, le=400)
    beat_times_ms: list[int] = Field(default_factory=list)
    downbeat_times_ms: list[int] = Field(default_factory=list)
    beats_per_bar: int | None = Field(default=None, ge=1, le=12)

    @field_validator("original_key")
    @classmethod
    def normalize_original_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("original_key must not be blank")
        return value

    @model_validator(mode="after")
    def validate_rhythm(self) -> "MusicalConfig":
        """确保逐拍和小节重拍数据可以无歧义地组成小节。"""
        for field_name, values in (
            ("beat_times_ms", self.beat_times_ms),
            ("downbeat_times_ms", self.downbeat_times_ms),
        ):
            if any(value < 0 for value in values):
                raise ValueError(f"{field_name} must not contain negative values")
            if any(right <= left for left, right in pairwise(values)):
                raise ValueError(f"{field_name} must be strictly increasing")

        if bool(self.downbeat_times_ms) != (self.beats_per_bar is not None):
            raise ValueError(
                "downbeat_times_ms and beats_per_bar must either both be set or both be empty"
            )
        beat_set = set(self.beat_times_ms)
        if any(value not in beat_set for value in self.downbeat_times_ms):
            raise ValueError("every downbeat must also be present in beat_times_ms")
        return self


# Read-only compatibility for song packages created before lyric transcription
# was removed. New creation jobs only write LRC or supplied-text metadata.
class WhisperConfig(StrictModel):
    model: str = Field(min_length=1)
    device: str = Field(min_length=1)
    word_timestamps: bool
    whisper_version: str = Field(min_length=1)


class LyricsConfig(StrictModel):
    file: Literal["lyrics.json"]
    source: Literal["lrc", "text", "whisper"]
    verified: bool
    verified_at: datetime | None
    language: str = Field(min_length=1)
    whisper: WhisperConfig | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_source_details(self) -> "LyricsConfig":
        if self.verified != (self.verified_at is not None):
            raise ValueError("verified_at must be set exactly when lyrics are verified")
        if self.verified_at is not None and self.verified_at.utcoffset() is None:
            raise ValueError("verified_at must include a timezone offset")
        if self.source == "whisper" and self.whisper is None:
            raise ValueError("whisper metadata is required for Whisper lyrics")
        return self


class SongConfig(StrictModel):
    schema_version: Literal[2, 3]
    song_id: str = Field(pattern=r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
    title: str = Field(min_length=1)
    artist: str
    language: str = Field(min_length=1)
    created_at: datetime
    duration_ms: int = Field(gt=0)
    source: SourceConfig
    separation: SeparationConfig
    audio: AudioConfig
    musical: MusicalConfig
    lyrics: LyricsConfig

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("song title must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("created_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def validate_consistency(self) -> "SongConfig":
        actual_tracks = set(self.audio.tracks)
        expected_tracks = LEGACY_TRACK_KINDS if self.schema_version == 2 else SIX_STEM_TRACK_KINDS
        if actual_tracks != expected_tracks:
            raise ValueError(
                f"schema version {self.schema_version} requires {len(expected_tracks)} audio stems"
            )
        expected_model = "htdemucs_ft" if self.schema_version == 2 else "htdemucs_6s"
        if self.separation.model != expected_model:
            raise ValueError(
                f"schema version {self.schema_version} requires separation model {expected_model}"
            )
        expected_frames = round(self.duration_ms * self.audio.sample_rate_hz / 1000)
        tolerance_frames = self.audio.sample_rate_hz // 10
        if abs(self.audio.canonical_frames - expected_frames) > tolerance_frames:
            raise ValueError("canonical_frames and duration_ms differ by more than 100ms")
        if any(
            abs(track.duration_ms - self.duration_ms) > 100 for track in self.audio.tracks.values()
        ):
            raise ValueError("track duration differs from song duration by more than 100ms")
        if self.lyrics.language != self.language:
            raise ValueError("song and lyrics language must match")
        return self

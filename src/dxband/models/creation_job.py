# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, field_validator

from dxband.models.base import StrictModel


class CreationJobState(StrEnum):
    IDLE = "idle"
    VALIDATING_INPUT = "validating_input"
    SEPARATING = "separating"
    VALIDATING_STEMS = "validating_stems"
    IMPORTING_LRC = "importing_lrc"
    IMPORTING_TEXT = "importing_text"
    BUILDING_LYRICS_DRAFT = "building_lyrics_draft"
    AWAITING_LYRIC_REVIEW = "awaiting_lyric_review"
    PACKAGING = "packaging"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class CreateSongRequest(StrictModel):
    source_mp3: Path
    lrc_path: Path | None = None
    lyrics_text: str | None = None
    title: str = Field(min_length=1)
    artist: str = ""
    language: str = Field(default="auto", min_length=1)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("歌曲名不能为空")
        return value


class CreationJob(StrictModel):
    schema_version: Literal[1] = 1
    job_id: str = Field(pattern=r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
    state: CreationJobState = CreationJobState.IDLE
    request: CreateSongRequest
    workspace_dir: Path
    created_at: datetime
    updated_at: datetime
    original_source_filename: str | None = None
    original_source_sha256: str | None = None
    original_lrc_filename: str | None = None
    original_lrc_sha256: str | None = None
    duration_ms: int | None = Field(default=None, gt=0)
    selected_device: str | None = None
    demucs_version: str | None = None
    separation_output_dir: Path | None = None
    stem_paths: dict[str, Path] = Field(default_factory=dict)
    stem_metadata: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    original_key: str | None = None
    bpm: int | None = Field(default=None, ge=20, le=400)
    beat_times_ms: list[int] = Field(default_factory=list)
    downbeat_times_ms: list[int] = Field(default_factory=list)
    beats_per_bar: int | None = Field(default=None, ge=1, le=12)
    score_output_dir: Path | None = None
    solo_score_output_dir: Path | None = None
    beat_output_dir: Path | None = None
    asr_output_path: Path | None = None
    lyrics_source: Literal["lrc", "text"] | None = None
    lyrics_draft_path: Path | None = None
    lyrics_confirmed_path: Path | None = None
    lyrics_verified_at: datetime | None = None
    resolved_language: str | None = None
    package_path: Path | None = None
    error_message: str | None = None

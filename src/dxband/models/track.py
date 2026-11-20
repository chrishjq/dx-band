# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import re

from pydantic import Field, field_validator

from dxband.models.base import StrictModel

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TrackConfig(StrictModel):
    file: str
    sha256: str
    duration_ms: int = Field(gt=0)
    trim_start_frames: int = Field(default=0, ge=0)
    pad_end_frames: int = Field(default=0, ge=0)

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        if not value or "\\" in value or value.startswith("/"):
            raise ValueError("track file must be a non-empty POSIX relative path")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("track file contains an unsafe path component")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("sha256 must contain exactly 64 lowercase hexadecimal characters")
        return value

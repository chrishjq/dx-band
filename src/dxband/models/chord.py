# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Optional chord timeline for the musician output."""

from pydantic import Field, model_validator

from dxband.models.base import StrictModel


class ChordSegment(StrictModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    chord: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_interval(self) -> "ChordSegment":
        if self.end_ms <= self.start_ms:
            raise ValueError("chord end must be after start")
        return self


class ChordTimeline(StrictModel):
    schema_version: int = 1
    segments: list[ChordSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_segments(self) -> "ChordTimeline":
        previous_end = 0
        for segment in self.segments:
            if segment.start_ms < previous_end:
                raise ValueError("chord segments must be ordered and not overlap")
            previous_end = segment.end_ms
        return self

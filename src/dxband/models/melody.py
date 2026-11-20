# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Timed lead-melody notes used by the musician display."""

from itertools import pairwise
from typing import Literal

from pydantic import Field, model_validator

from dxband.models.base import StrictModel


class MelodyNote(StrictModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    display_ms: int | None = Field(default=None, ge=0)
    lyric_line_id: str | None = None
    lyric_character_index: int | None = Field(default=None, ge=0)
    midi: int = Field(ge=0, le=127)
    source: Literal["piano", "vocals", "guitar", "other"]
    review: Literal["candidate", "needs_review", "reviewed"] = "candidate"
    evidence: list[Literal["sheetsage2"]] = Field(
        default_factory=list
    )
    # Optional score positions in sixteenth-note units.  These preserve a
    # transcription model's rhythmic grid when milliseconds drift around beats.
    start_16th: int | None = Field(default=None, ge=0)
    duration_16ths: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_interval(self) -> "MelodyNote":
        if self.end_ms <= self.start_ms:
            raise ValueError("melody note end must follow start")
        if (self.lyric_line_id is None) != (self.lyric_character_index is None):
            raise ValueError("lyric note anchor requires both line and character")
        if (self.start_16th is None) != (self.duration_16ths is None):
            raise ValueError("melody note score position requires a duration")
        return self


class MelodyGap(StrictModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    label: str = Field(default="待校", min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_interval(self) -> "MelodyGap":
        if self.end_ms <= self.start_ms:
            raise ValueError("melody gap end must follow start")
        return self


class MelodyChord(StrictModel):
    at_ms: int = Field(ge=0)
    chord: str = Field(min_length=1)
    start_16th: int | None = Field(default=None, ge=0)


class MelodyKeyChange(StrictModel):
    at_ms: int = Field(ge=0)
    tonic_midi: int = Field(ge=0, le=127)
    start_16th: int | None = Field(default=None, ge=0)


class MelodyBar(StrictModel):
    """A score bar with its own meter and absolute beat positions."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    beat_times_ms: list[int] = Field(min_length=1, max_length=12)
    # A trimmed opening may contain only the audible half of a full measure.
    # These score-only beats precede the first audio beat and have no timestamp.
    leading_rest_beats: int = Field(default=0, ge=0, le=3)
    # Zero-based audible beat indices. Each marked beat contains three eighth
    # triplets. The lead events retain integer display anchors within the beat.
    triplet_beats: list[int] = Field(default_factory=list)
    section_label: str = ""
    review: Literal["candidate", "needs_review", "reviewed"] = "candidate"
    start_16th: int | None = Field(default=None, ge=0)
    end_16th: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_beats(self) -> "MelodyBar":
        if (
            self.beat_times_ms[0] != self.start_ms
            or any(not self.start_ms <= beat < self.end_ms for beat in self.beat_times_ms)
            or any(right <= left for left, right in pairwise(self.beat_times_ms))
        ):
            raise ValueError("melody bar beats must be ordered inside the bar")
        if sorted(set(self.triplet_beats)) != self.triplet_beats or any(
            not 0 <= index < len(self.beat_times_ms) for index in self.triplet_beats
        ):
            raise ValueError("triplet beat indices must be unique and inside the bar")
        if (self.start_16th is None) != (self.end_16th is None):
            raise ValueError("melody bar score positions must be paired")
        if (
            self.start_16th is not None
            and self.end_16th is not None
            and not (
                (len(self.beat_times_ms) + self.leading_rest_beats - 1) * 4
                < self.end_16th - self.start_16th
                <= (len(self.beat_times_ms) + self.leading_rest_beats) * 4
            )
        ):
            raise ValueError("melody bar score duration must match its beat anchors")
        return self


class MelodyDocument(StrictModel):
    schema_version: Literal[1] = 1
    # Absolute pitch displayed as scale degree 1 by JianpuRender.
    tonic_midi: int = Field(ge=0, le=127)
    coverage_end_ms: int | None = Field(default=None, ge=1)
    notes: list[MelodyNote] = Field(default_factory=list)
    chords: list[MelodyChord] = Field(default_factory=list)
    key_changes: list[MelodyKeyChange] = Field(default_factory=list)
    gaps: list[MelodyGap] = Field(default_factory=list)
    bars: list[MelodyBar] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_order(self) -> "MelodyDocument":
        if any(bar.leading_rest_beats for bar in self.bars[1:]):
            raise ValueError("only the opening melody bar may have leading rests")
        if any(right.start_ms < left.start_ms for left, right in pairwise(self.notes)):
            raise ValueError("melody notes must be ordered by start time")
        if any(right.at_ms < left.at_ms for left, right in pairwise(self.chords)):
            raise ValueError("melody chords must be ordered by start time")
        if any(right.at_ms <= left.at_ms for left, right in pairwise(self.key_changes)):
            raise ValueError("melody key changes must be strictly ordered")
        if any(right.start_ms < left.start_ms for left, right in pairwise(self.gaps)):
            raise ValueError("melody gaps must be ordered by start time")
        if any(right.start_ms != left.end_ms for left, right in pairwise(self.bars)):
            raise ValueError("melody bars must be contiguous")
        if any(
            left.end_16th is not None
            and right.start_16th is not None
            and left.end_16th != right.start_16th
            for left, right in pairwise(self.bars)
        ):
            raise ValueError("melody bar score positions must be contiguous")
        if self.coverage_end_ms is not None and (
            any(note.end_ms > self.coverage_end_ms for note in self.notes)
            or any(
                note.display_ms is not None and note.display_ms > self.coverage_end_ms
                for note in self.notes
            )
            or any(gap.end_ms > self.coverage_end_ms for gap in self.gaps)
            or any(chord.at_ms > self.coverage_end_ms for chord in self.chords)
            or any(change.at_ms >= self.coverage_end_ms for change in self.key_changes)
            or any(bar.start_ms >= self.coverage_end_ms for bar in self.bars)
        ):
            raise ValueError("melody event exceeds coverage")
        return self

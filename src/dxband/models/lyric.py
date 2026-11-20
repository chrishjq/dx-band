# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from typing import Literal

from pydantic import Field, model_validator

from dxband.models.base import StrictModel


class WordTiming(StrictModel):
    text: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> "WordTiming":
        if not self.text.strip():
            raise ValueError("word text must not be blank")
        if self.end_ms <= self.start_ms:
            raise ValueError("word end_ms must be greater than start_ms")
        return self


class LyricLine(StrictModel):
    id: str = Field(pattern=r"^line-[0-9]{4,}$")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1)
    words: list[WordTiming] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timing(self) -> "LyricLine":
        if not self.text.strip():
            raise ValueError("lyric text must not be blank")
        if self.end_ms <= self.start_ms:
            raise ValueError("line end_ms must be greater than start_ms")
        previous_end_ms = self.start_ms
        for word in self.words:
            if word.start_ms < self.start_ms or word.end_ms > self.end_ms:
                raise ValueError("word timing must be contained by its lyric line")
            if word.start_ms < previous_end_ms:
                raise ValueError("word timings must be ordered and must not overlap")
            previous_end_ms = word.end_ms
        return self


class LyricsDocument(StrictModel):
    schema_version: Literal[1]
    title: str = Field(min_length=1)
    language: str = Field(min_length=1)
    timing_mode: Literal["line", "word"]
    lines: list[LyricLine] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lines(self) -> "LyricsDocument":
        if not self.title.strip():
            raise ValueError("lyrics title must not be blank")
        previous_end_ms = -1
        seen_ids: set[str] = set()
        for line in self.lines:
            if line.id in seen_ids:
                raise ValueError(f"duplicate lyric line id: {line.id}")
            if line.start_ms < previous_end_ms:
                raise ValueError("lyric lines must be ordered and must not overlap")
            seen_ids.add(line.id)
            previous_end_ms = line.end_ms
        if self.timing_mode == "word" and any(not line.words for line in self.lines):
            raise ValueError("word timing mode requires word timings for every lyric line")
        return self

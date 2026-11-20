# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import pytest
from pydantic import ValidationError

from dxband.models.lyric import LyricsDocument


def test_empty_lyrics_are_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        LyricsDocument.model_validate(
            {
                "schema_version": 1,
                "title": "Song",
                "language": "en",
                "timing_mode": "line",
                "lines": [],
            }
        )


def test_overlapping_lines_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must not overlap"):
        LyricsDocument.model_validate(
            {
                "schema_version": 1,
                "title": "Song",
                "language": "en",
                "timing_mode": "line",
                "lines": [
                    {
                        "id": "line-0001",
                        "start_ms": 0,
                        "end_ms": 2000,
                        "text": "one",
                        "words": [],
                    },
                    {
                        "id": "line-0002",
                        "start_ms": 1900,
                        "end_ms": 3000,
                        "text": "two",
                        "words": [],
                    },
                ],
            }
        )


def test_word_must_be_inside_its_line() -> None:
    with pytest.raises(ValidationError, match="contained"):
        LyricsDocument.model_validate(
            {
                "schema_version": 1,
                "title": "Song",
                "language": "en",
                "timing_mode": "word",
                "lines": [
                    {
                        "id": "line-0001",
                        "start_ms": 1000,
                        "end_ms": 2000,
                        "text": "one",
                        "words": [{"text": "one", "start_ms": 900, "end_ms": 1500}],
                    }
                ],
            }
        )

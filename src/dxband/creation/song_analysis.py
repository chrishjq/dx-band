# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""The shared score/lyric assembly used by creation and full reanalysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dxband.analysis.beat_led_score import read_beat_led_analysis
from dxband.analysis.sheetsage2_package import SheetSage2Analysis
from dxband.creation.asr_lyrics import correct_asr_lyrics
from dxband.creation.score_lyric_alignment import (
    align_lyrics_to_score,
    link_lyrics_to_score_without_retiming,
)
from dxband.creation.score_notation import refine_vocal_notation
from dxband.models.lyric import LyricsDocument
from dxband.models.melody import MelodyDocument


@dataclass(frozen=True, slots=True)
class SongAnalysis:
    score: SheetSage2Analysis
    lyrics: LyricsDocument
    melody: MelodyDocument


def assemble_song_analysis(
    score_output: Path, solo_output: Path, beat_output: Path,
    reference: LyricsDocument, duration_ms: int,
    *, asr_output: Path | None = None, source_sha256: str | None = None,
    corrected_lyrics: LyricsDocument | None = None,
) -> SongAnalysis:
    score = read_beat_led_analysis(
        score_output, beat_output, duration_ms, source_sha256,
        solo_output=solo_output, asr_output=asr_output,
    )
    if asr_output is not None:
        tokens = json.loads(asr_output.read_text(encoding="utf-8")).get("tokens", [])
        lyrics = corrected_lyrics or correct_asr_lyrics(reference, tokens, duration_ms)
        lyrics, melody = link_lyrics_to_score_without_retiming(lyrics, score.melody)
    else:
        lyrics, melody = align_lyrics_to_score(reference, score.melody)
    return SongAnalysis(score, lyrics, refine_vocal_notation(melody, lyrics))

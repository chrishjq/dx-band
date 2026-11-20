# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Convert one full SheetSage2 transcription into package music data."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from statistics import median

from dxband.analysis.beat_this_reconciliation import (
    BeatThisResult,
    RhythmComparison,
    reconcile_score_with_beat_this,
)
from dxband.analysis.sheetsage2_score import (
    build_sheetsage2_melody,
    complete_two_beat_opening,
    normalize_melody_beat_grid,
)
from dxband.analysis.steady_score_grid import regrid_steady_four_beat_score
from dxband.models.chord import ChordTimeline
from dxband.models.melody import MelodyDocument
from dxband.models.song import SongConfig


@dataclass(frozen=True, slots=True)
class SheetSage2Analysis:
    original_key: str
    bpm: int
    beat_times_ms: list[int]
    downbeat_times_ms: list[int]
    beats_per_bar: int
    chords: ChordTimeline
    melody: MelodyDocument
    rhythm_comparison: RhythmComparison | None = None


def melody_rhythm_summary(
    melody: MelodyDocument,
) -> tuple[int, list[int], list[int], int]:
    """Return BPM, beat positions, downbeats and prevailing meter for a score."""
    if not melody.bars:
        raise ValueError("简谱没有可用于节奏定位的小节")
    beat_times = [time for bar in melody.bars for time in bar.beat_times_ms]
    intervals = [
        right - left
        for bar in melody.bars
        for left, right in pairwise(bar.beat_times_ms)
        if 300 <= right - left <= 2000
    ]
    if not intervals:
        raise ValueError("SheetSage2 未生成稳定的逐拍时间表")
    bpm = round(60_000 / median(intervals))
    meter = Counter(
        len(bar.beat_times_ms) + bar.leading_rest_beats for bar in melody.bars
    ).most_common(1)[0][0]
    downbeats = [
        bar.start_ms for bar in melody.bars if not bar.leading_rest_beats
    ]
    return bpm, beat_times, downbeats, meter


def apply_melody_rhythm_to_config(config: SongConfig, melody: MelodyDocument) -> SongConfig:
    """Update the score timing grid used for note, lyric and chord layout."""
    _bpm, beat_times, downbeats, meter = melody_rhythm_summary(melody)
    data = config.model_dump(mode="python")
    data["musical"].update(
        beat_times_ms=beat_times,
        downbeat_times_ms=downbeats,
        beats_per_bar=meter,
    )
    return SongConfig.model_validate(data, strict=True)


def read_sheetsage2_chords(output: Path, duration_ms: int) -> ChordTimeline:
    """Read the model's timed chords without depending on score bar inference."""
    segments = []
    for line in (output / "chord.lab").read_text(encoding="utf-8").splitlines():
        start, end, chord = line.split(maxsplit=2)
        start_ms = round(float(start) * 1000)
        end_ms = min(duration_ms, round(float(end) * 1000))
        if end_ms > start_ms:
            segments.append({"start_ms": start_ms, "end_ms": end_ms, "chord": chord})
    return ChordTimeline.model_validate({"segments": segments}, strict=True)


def read_sheetsage2_package(
    output: Path,
    duration_ms: int,
    beat_this_output: Path | None = None,
    source_sha256: str | None = None,
) -> SheetSage2Analysis:
    melody = build_sheetsage2_melody(
        json.loads((output / "events.json").read_text(encoding="utf-8"))
    )
    if melody.bars[-1].end_ms > duration_ms:
        if (
            melody.bars[-1].start_ms >= duration_ms
            or melody.bars[-1].beat_times_ms[-1] >= duration_ms
        ):
            raise ValueError(
                f"SheetSage2 谱面终点 {melody.bars[-1].end_ms}ms 超过歌曲时长 {duration_ms}ms"
            )
        data = melody.model_dump(mode="python")
        data["coverage_end_ms"] = duration_ms
        data["bars"][-1]["end_ms"] = duration_ms
        data["bars"][-1]["review"] = "needs_review"
        data["notes"] = [
            {**note, "end_ms": min(note["end_ms"], duration_ms)}
            for note in data["notes"]
            if note["start_ms"] < duration_ms
        ]
        data["chords"] = [chord for chord in data["chords"] if chord["at_ms"] <= duration_ms]
        data["key_changes"] = [
            change for change in data["key_changes"] if change["at_ms"] < duration_ms
        ]
        melody = MelodyDocument.model_validate(data, strict=True)
    bpm, _raw_beats, _raw_downbeats, _raw_meter = melody_rhythm_summary(melody)
    melody = normalize_melody_beat_grid(melody)
    melody = complete_two_beat_opening(melody)
    rhythm_comparison = None
    if beat_this_output is not None:
        rhythm = BeatThisResult.read(beat_this_output, source_sha256)
        melody, rhythm_comparison = reconcile_score_with_beat_this(melody, rhythm)
    else:
        steady = regrid_steady_four_beat_score(melody, duration_ms)
        if steady is not None:
            melody, bpm = steady
    key_line = (output / "key.lab").read_text(encoding="utf-8").splitlines()[0]
    tonic, mode = key_line.split()[-1].split(":", 1)
    key = tonic + ("m" if mode.startswith("minor") else "")
    _normalized_bpm, beat_times, downbeat_times, meter = melody_rhythm_summary(melody)
    chords = read_sheetsage2_chords(output, duration_ms)
    return SheetSage2Analysis(
        original_key=key,
        bpm=bpm,
        beat_times_ms=beat_times,
        downbeat_times_ms=downbeat_times,
        beats_per_bar=meter,
        chords=chords,
        melody=melody,
        rhythm_comparison=rhythm_comparison,
    )


def apply_analysis_to_config(config: SongConfig, analysis: SheetSage2Analysis) -> SongConfig:
    data = config.model_dump(mode="python")
    data["musical"].update(
        original_key=analysis.original_key,
        bpm=analysis.bpm,
        beat_times_ms=analysis.beat_times_ms,
        downbeat_times_ms=analysis.downbeat_times_ms,
        beats_per_bar=analysis.beats_per_bar,
    )
    return SongConfig.model_validate(data, strict=True)

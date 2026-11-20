# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Build the score on Beat This! bars while retaining SheetSage2 pitches and chords.

The two models answer different questions: Beat This! supplies the pulse and
bar phase; SheetSage2 supplies note and chord events.  A missing downbeat is
inferred from the surrounding pulse, never turned into a short bar by itself.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from statistics import median

from dxband.analysis.beat_this_reconciliation import BeatThisResult
from dxband.analysis.sheetsage2_package import (
    SheetSage2Analysis,
    melody_rhythm_summary,
    read_sheetsage2_chords,
)
from dxband.analysis.sheetsage2_score import build_sheetsage2_melody
from dxband.analysis.vocal_track_alignment import (
    align_other_to_vocals,
    align_vocals_to_asr,
    notes_from_events,
)
from dxband.models.melody import MelodyBar, MelodyDocument


def _pulse_grid(raw: tuple[int, ...], period: float) -> list[int]:
    grid = [raw[0]]
    for arrival in raw[1:]:
        gap = arrival - grid[-1]
        if gap < period * .45:
            continue
        steps = max(1, round(gap / period))
        previous = grid[-1]
        grid.extend(round(previous + gap * step / steps) for step in range(1, steps))
        grid.append(arrival)
    return grid


def _nearest_distance(values: tuple[int, ...], value: int) -> int:
    index = bisect_right(values, value)
    return min(abs(values[min(index, len(values) - 1)] - value),
               abs(values[max(0, index - 1)] - value))


def _bar_starts(
    grid: list[int], rhythm: BeatThisResult, sheet_starts: tuple[int, ...],
    ticks_per_bar: int, period: float, first_note_ms: int,
) -> list[int]:
    # Select the downbeat phase globally.  A SheetSage2 downbeat is positive
    # evidence only where Beat This! does not provide a close downbeat.
    phases: list[tuple[float, int]] = []
    eligible_phases = [phase for phase in range(min(ticks_per_bar, len(grid)))
                       if grid[phase] <= first_note_ms + period]
    for phase in eligible_phases or range(min(ticks_per_bar, len(grid))):
        indices = range(phase, len(grid), ticks_per_bar)
        score = sum(
            1.0 if _nearest_distance(rhythm.downbeats_ms, grid[index]) < period * .3
            else .35 if sheet_starts and _nearest_distance(sheet_starts, grid[index]) < period * .3
            else 0.0
            for index in indices
        )
        phases.append((score / max(1, len(indices)), phase))
    phase = max(phases, key=lambda item: (item[0], -item[1]))[1]
    return list(range(phase, len(grid), ticks_per_bar))


def _supported_short_rephase(
    indices: list[int], grid: list[int], rhythm: BeatThisResult,
    source: MelodyDocument, ticks_per_quarter: int, ticks_per_bar: int,
    period: float,
) -> list[int]:
    """Follow a short transition only when both models locate its next downbeat."""
    for bar in source.bars:
        short_beats = len(bar.beat_times_ms)
        if short_beats >= ticks_per_bar // ticks_per_quarter:
            continue
        if (
            abs((bar.end_ms - bar.start_ms) - short_beats * ticks_per_quarter * period)
            > period * .45
        ):
            continue
        before = min(indices, key=lambda index: abs(grid[index] - bar.start_ms))
        if abs(grid[before] - bar.start_ms) > period * .35:
            continue
        after = min(range(before + 1, min(len(grid), before + ticks_per_bar)),
                    key=lambda index: abs(grid[index] - bar.end_ms), default=None)
        if after is None or after - before != short_beats * ticks_per_quarter:
            continue
        if abs(grid[after] - bar.end_ms) > period * .35:
            continue
        if _nearest_distance(rhythm.downbeats_ms, grid[after]) > period * .35:
            continue
        indices = [index for index in indices if index <= before]
        indices.extend(range(after, len(grid), ticks_per_bar))
    return indices


def beat_led_melody(
    source: MelodyDocument, rhythm: BeatThisResult, duration_ms: int,
    *, meter: int | None = None,
) -> MelodyDocument:
    """Replace score-derived bar lines and score steps with a continuous pulse grid."""
    intervals = [right - left for left, right in pairwise(rhythm.beats_ms)
                 if 180 <= right - left <= 3200]
    if len(intervals) < 6:
        raise ValueError("Beat This! 没有足够的稳定拍点")
    observed = float(median(sorted(intervals)[:max(6, round(len(intervals) * .6))]))
    source_bpm, _, _, score_meter = melody_rhythm_summary(source)
    meter = meter or (score_meter if score_meter in {3, 4} else 4)
    # Beat This! can mark eighth-note subdivisions as beats.  Keep its timing
    # and phase, but use the source score's quarter-note scale when its bars
    # and tempo independently agree on a 2:1 relationship.  Otherwise a full
    # bar of sixteen sixteenths becomes two bars of eighths.
    source_quarter = 60_000 / source_bpm
    source_bar_lengths = [bar.end_ms - bar.start_ms for bar in source.bars
                          if len(bar.beat_times_ms) == meter]
    half_pulse = (
        source_bar_lengths
        and 1.8 <= source_quarter / observed <= 2.2
        and 1.8 <= median(source_bar_lengths) / (meter * observed) <= 2.2
    )
    ticks_per_quarter = 2 if half_pulse else 1
    period = observed
    grid = _pulse_grid(rhythm.beats_ms, period)
    sheet_starts = tuple(bar.start_ms for bar in source.bars)
    indices = _bar_starts(grid, rhythm, sheet_starts,
                          meter * ticks_per_quarter, period,
                          min((note.start_ms for note in source.notes), default=grid[0]))
    indices = _supported_short_rephase(
        indices, grid, rhythm, source, ticks_per_quarter,
        meter * ticks_per_quarter, period,
    )
    if len(indices) < 2:
        raise ValueError("Beat This! 无法形成连续小节")
    boundaries = [grid[index] for index in indices]
    # Keep a final full bar only while there is audible score material.  Do
    # not render trailing all-rest measures produced by the audio container.
    audible_end = min(duration_ms, max((note.end_ms for note in source.notes), default=0))
    while len(boundaries) > 2 and boundaries[-2] >= audible_end:
        boundaries.pop()
    while boundaries[-1] < audible_end and boundaries[-1] < duration_ms:
        boundaries.append(min(duration_ms, round(
            boundaries[-1] + meter * ticks_per_quarter * period)))
    if boundaries[-1] <= boundaries[-2]:
        boundaries.pop()
    bars: list[MelodyBar] = []
    next_step = 0
    for start, end in pairwise(boundaries):
        if start >= duration_ms:
            break
        end = min(end, duration_ms)
        if end <= start:
            break
        bar_meter = min(meter, max(1, round((end - start) / (ticks_per_quarter * period))))
        beats = [round(start + (end - start) * part / bar_meter) for part in range(bar_meter)]
        source_bar = min(source.bars, key=lambda bar: abs(bar.start_ms - start))
        bars.append(MelodyBar(
            start_ms=start, end_ms=end, beat_times_ms=beats,
            section_label=source_bar.section_label, start_16th=next_step,
            end_16th=next_step + bar_meter * 4,
        ))
        next_step += bar_meter * 4
    if not bars:
        raise ValueError("Beat This! 小节超出歌曲范围")

    def position(at_ms: int) -> int:
        index = max(0, min(len(bars) - 1,
                           bisect_right([bar.start_ms for bar in bars],
                                        at_ms + min(80, round(period * .2))) - 1))
        bar = bars[index]
        assert bar.start_16th is not None
        bar_steps = len(bar.beat_times_ms) * 4
        return bar.start_16th + max(0, min(bar_steps - 1,
            round((at_ms - bar.start_ms) * bar_steps / (bar.end_ms - bar.start_ms))))

    notes = []
    for note in source.notes:
        if note.start_ms >= bars[-1].end_ms:
            continue
        end_ms = min(note.end_ms, bars[-1].end_ms)
        if end_ms <= note.start_ms:
            continue
        start_step = position(note.start_ms)
        end_step = max(start_step + 1, position(min(end_ms, bars[-1].end_ms - 1)))
        notes.append(note.model_copy(update={
            "end_ms": end_ms,
            "start_16th": start_step,
            "duration_16ths": max(1, end_step - start_step),
        }))
    chords = [chord.model_copy(update={"start_16th": position(chord.at_ms)})
              for chord in source.chords if chord.at_ms < bars[-1].end_ms]
    changes = [change.model_copy(update={"start_16th": position(change.at_ms)})
               for change in source.key_changes if change.at_ms < bars[-1].end_ms]
    return MelodyDocument(
        tonic_midi=source.tonic_midi, coverage_end_ms=bars[-1].end_ms,
        notes=notes, chords=chords, key_changes=changes, bars=bars,
    )


def read_beat_led_analysis(
    score_output: Path, beat_output: Path, duration_ms: int,
    source_sha256: str | None = None,
    *, solo_output: Path | None = None, asr_output: Path | None = None,
) -> SheetSage2Analysis:
    # Read model events directly.  The legacy SheetSage2 package reader
    # normalizes and re-bars its score before returning, which would bring
    # the superseded meter decisions into this Beat This! led path.
    raw = json.loads((score_output / "events.json").read_text(encoding="utf-8"))
    source_melody = build_sheetsage2_melody(raw)
    source_bpm, source_beats, source_downbeats, source_meter = melody_rhythm_summary(
        source_melody,
    )
    key_line = (score_output / "key.lab").read_text(encoding="utf-8").splitlines()[0]
    tonic, mode = key_line.split()[-1].split(":", 1)
    key = tonic + ("m" if mode.startswith("minor") else "")
    base = SheetSage2Analysis(
        original_key=key, bpm=source_bpm, beat_times_ms=source_beats,
        downbeat_times_ms=source_downbeats, beats_per_bar=source_meter,
        chords=read_sheetsage2_chords(score_output, duration_ms),
        melody=source_melody,
    )
    rhythm = BeatThisResult.read(beat_output, source_sha256)
    melody = beat_led_melody(base.melody, rhythm, duration_ms)
    if solo_output is not None:
        solo_raw = [note for note in notes_from_events(
            json.loads((solo_output / "events.json").read_text(encoding="utf-8")),
            duration_ms,
        ) if note.source == "vocals"]
        if not solo_raw:
            raise ValueError("纯人声 SheetSage2 没有可用音符")
        asr_tokens = [] if asr_output is None else json.loads(
            asr_output.read_text(encoding="utf-8")
        ).get("tokens", [])
        solo_aligned, _matched = align_vocals_to_asr(solo_raw, asr_tokens)
        original_vocals = [note for note in base.melody.notes if note.source == "vocals"]
        original_other = [note for note in base.melody.notes if note.source == "other"]
        shifted_other = align_other_to_vocals(
            original_vocals, original_other, solo_raw, solo_aligned,
            [bar.start_ms for bar in melody.bars] + [melody.bars[-1].end_ms],
        )
        shifted = sorted([*solo_aligned, *shifted_other],
                         key=lambda note: (note.start_ms, note.midi))
        melody = beat_led_melody(base.melody.model_copy(update={"notes": shifted}),
                                 rhythm, duration_ms)
    bpm, beats, downbeats, meter = melody_rhythm_summary(melody)
    return replace(base, melody=melody, bpm=bpm, beat_times_ms=beats,
                   downbeat_times_ms=downbeats, beats_per_bar=meter)

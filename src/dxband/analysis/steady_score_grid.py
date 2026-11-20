# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Repair a steady four-beat score whose decoded bar boundaries lost beats.

The decoder's pitch and onset timestamps remain the evidence.  Only score
positions and beat-light timestamps are placed back on a stable time grid.
"""

from __future__ import annotations

from itertools import pairwise
from statistics import median

from dxband.models.melody import MelodyBar, MelodyDocument


def steady_four_beat_bpm(document: MelodyDocument) -> int | None:
    """Return an early, stable tempo only for a predominantly 4/4 score."""
    bars = document.bars
    if len(bars) < 24 or sum(len(bar.beat_times_ms) == 4 for bar in bars) < len(bars) * 0.85:
        return None
    full = [bar for bar in bars if not bar.leading_rest_beats]
    opening = full[:8]
    if len(opening) != 8 or any(len(bar.beat_times_ms) != 4 for bar in opening):
        return None
    quarters = [(bar.end_ms - bar.start_ms) / 4 for bar in opening]
    quarter_ms = median(quarters)
    if not 350 <= quarter_ms <= 1500 or any(
        abs(value - quarter_ms) > quarter_ms * 0.06 for value in quarters
    ):
        return None
    return round(60_000 / quarter_ms)


def regrid_steady_four_beat_score(
    document: MelodyDocument, duration_ms: int
) -> tuple[MelodyDocument, int] | None:
    """Rebuild score bars when the decoder contradicts an established 4/4 pulse.

    A short opening pickup is kept intact.  A partial final measure remains
    partial; every complete measure after the pickup has four beat anchors.
    """
    bpm = steady_four_beat_bpm(document)
    if bpm is None or not document.bars:
        return None
    full = [bar for bar in document.bars if not bar.leading_rest_beats]
    if not full:
        return None
    anchor = full[0].start_ms
    quarter_ms = 60_000 / bpm
    unit_ms = quarter_ms / 4
    # A mostly regular transcription does not need its time base rewritten.
    if (
        all(len(bar.beat_times_ms) == 4 for bar in full[:-1])
        and median(
            abs(
                bar.start_ms
                - (anchor + round((bar.start_ms - anchor) / (quarter_ms * 4)) * quarter_ms * 4)
            )
            for bar in full
        )
        < quarter_ms * 0.12
    ):
        return None
    first = document.bars[0]
    pickup = [first] if first.leading_rest_beats else []
    start_step = first.end_16th if pickup else first.start_16th
    if start_step is None:
        return None
    bars: list[MelodyBar] = list(pickup)
    index = 0
    while True:
        start = anchor + round(index * quarter_ms * 4)
        if start >= duration_ms:
            break
        end = min(duration_ms, anchor + round((index + 1) * quarter_ms * 4))
        if end <= start:
            break
        count = min(4, max(1, (end - start - 1) // round(quarter_ms) + 1))
        # The final beat must begin inside this bar even with rounded times.
        while count > 1 and start + round((count - 1) * quarter_ms) >= end:
            count -= 1
        beat_times = [start + round(beat * quarter_ms) for beat in range(count)]
        old = min(full, key=lambda bar: abs((bar.start_ms + bar.end_ms) / 2 - (start + end) / 2))
        partial_steps = min(count * 4, max((count - 1) * 4 + 1, round((end - start) / unit_ms)))
        bars.append(
            MelodyBar(
                start_ms=start,
                end_ms=end,
                beat_times_ms=beat_times,
                start_16th=start_step + index * 16,
                end_16th=start_step + index * 16 + (16 if count == 4 else partial_steps),
                section_label=old.section_label,
                review="needs_review" if count != 4 else "candidate",
            )
        )
        index += 1
    if not bars or bars[-1].end_ms != duration_ms:
        return None

    def score_step(at_ms: int) -> int:
        return max(start_step, start_step + round((at_ms - anchor) / unit_ms))

    data = document.model_dump(mode="python")
    data["bars"] = [bar.model_dump(mode="python") for bar in bars]
    data["coverage_end_ms"] = duration_ms
    last_step = bars[-1].end_16th
    assert last_step is not None
    for note in data["notes"]:
        if note["start_ms"] < anchor:
            continue
        start = min(last_step - 1, score_step(note["start_ms"]))
        end = min(last_step, max(start + 1, score_step(note["end_ms"])))
        note["start_16th"] = start
        note["duration_16ths"] = end - start
    for chord in data["chords"]:
        if chord["at_ms"] >= anchor:
            chord["start_16th"] = min(last_step - 1, score_step(chord["at_ms"]))
    for change in data["key_changes"]:
        if change["at_ms"] >= anchor:
            change["start_16th"] = min(last_step - 1, score_step(change["at_ms"]))
    result = MelodyDocument.model_validate(data, strict=True)
    assert all(left.end_ms == right.start_ms for left, right in pairwise(result.bars))
    return result, bpm

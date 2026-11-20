# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Reconcile SheetSage2 score bars with Beat This! beats and prevailing meter."""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from collections import Counter
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any

from dxband.analysis.local_meter import apply_meter_repairs, plan_meter_repairs
from dxband.models.melody import MelodyBar, MelodyDocument


@dataclass(frozen=True, slots=True)
class BeatThisResult:
    beats_ms: tuple[int, ...]
    downbeats_ms: tuple[int, ...]
    source_sha256: str | None = None

    @classmethod
    def read(cls, path: Path, expected_sha256: str | None = None) -> BeatThisResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        actual_hash = data.get("source_sha256")
        if expected_sha256 is not None and actual_hash != expected_sha256:
            raise ValueError("Beat This! source SHA-256 does not match the song")
        beats = tuple(round(float(value) * 1000) for value in data["beats_s"])
        downbeats = tuple(round(float(value) * 1000) for value in data["downbeats_s"])
        for label, values in (("beats", beats), ("downbeats", downbeats)):
            if (
                not values
                or any(value < 0 for value in values)
                or any(right <= left for left, right in pairwise(values))
            ):
                raise ValueError(f"Beat This! {label} must be positive and strictly ordered")
        if len(beats) < 8 or len(downbeats) < 2:
            raise ValueError("Beat This! returned too few beats/downbeats")
        return cls(beats, downbeats, actual_hash)


@dataclass(frozen=True, slots=True)
class RhythmDecision:
    bar_index: int
    start_ms: int
    end_ms: int
    sheet_beats: float
    decision: str
    reason: str


@dataclass(frozen=True, slots=True)
class RhythmComparison:
    prevailing_meter: str
    beat_this_bpm: int
    decisions: tuple[RhythmDecision, ...]

    @property
    def merged_bars(self) -> int:
        return sum(
            row.decision in {
                "beat_this_merge", "beat_this_phrase_rebar", "extended_meter_merge",
                "song_profile_merge",
            }
            for row in self.decisions
        )

    @property
    def regridded_bars(self) -> int:
        return sum(
            row.decision in {"meter_regrid", "local_meter_rebar"} for row in self.decisions
        )


def comparison_payload(comparison: RhythmComparison, source_sha256: str) -> dict[str, object]:
    """Persist decisions without copying raw model beat arrays into a song package."""
    return {
        "schema_version": 1,
        "source_sha256": source_sha256,
        "score_model": "SheetSage2",
        "beat_model": "Beat This! final0",
        "prevailing_meter": comparison.prevailing_meter,
        "beat_this_bpm": comparison.beat_this_bpm,
        "merged_bars": comparison.merged_bars,
        "regridded_bars": comparison.regridded_bars,
        "decisions": [asdict(row) for row in comparison.decisions],
    }


def _nearest(values: tuple[int, ...], at_ms: int) -> tuple[int, int]:
    index = bisect_left(values, at_ms)
    candidates = (max(0, index - 1), min(len(values) - 1, index))
    selected = min(candidates, key=lambda item: abs(values[item] - at_ms))
    return selected, abs(values[selected] - at_ms)


def _score_span(bar: MelodyBar) -> int | None:
    start = bar.start_16th
    end = bar.end_16th
    return end - start if start is not None and end is not None else None


def _phrase_score_step(at_ms: int, boundaries: list[int], start_step: int) -> int:
    count = len(boundaries) - 1
    measure = max(0, min(count - 1, bisect_left(boundaries, at_ms + 1) - 1))
    left, right = boundaries[measure], boundaries[measure + 1]
    return min(
        start_step + count * 16,
        start_step + measure * 16 + round((at_ms - left) * 16 / (right - left)),
    )


def _regrid_short_bars(document: MelodyDocument, start_times: set[int]) -> MelodyDocument:
    """Give short bars a full score grid when their audio spans a full bar."""
    adjusted = [
        bar for bar in document.bars
        if bar.start_ms in start_times and (_score_span(bar) or 16) < 16
    ]
    if not adjusted:
        return document

    def map_step(step: int) -> int:
        shift = 0
        for bar in adjusted:
            assert bar.start_16th is not None and bar.end_16th is not None
            if step < bar.start_16th:
                break
            if step < bar.end_16th:
                return bar.start_16th + shift + round(
                    (step - bar.start_16th) * 16 / (bar.end_16th - bar.start_16th)
                )
            shift += 16 - (bar.end_16th - bar.start_16th)
        return step + shift

    data: dict[str, Any] = document.model_dump(mode="python")
    for bar in data["bars"]:
        original_start = bar["start_16th"]
        original_end = bar["end_16th"]
        if original_start is None or original_end is None:
            continue
        bar["start_16th"] = map_step(original_start)
        bar["end_16th"] = map_step(original_end)
        if bar["start_ms"] in start_times and original_end - original_start < 16:
            start_ms, end_ms = bar["start_ms"], bar["end_ms"]
            bar["beat_times_ms"] = [
                start_ms + round((end_ms - start_ms) * beat / 4) for beat in range(4)
            ]
            bar["review"] = "candidate"
    for note in data["notes"]:
        if note["start_16th"] is None:
            continue
        start = map_step(note["start_16th"])
        end = map_step(note["start_16th"] + note["duration_16ths"])
        note["start_16th"] = start
        note["duration_16ths"] = max(1, end - start)
    for chord in data["chords"]:
        if chord["start_16th"] is not None:
            chord["start_16th"] = map_step(chord["start_16th"])
    for change in data["key_changes"]:
        if change["start_16th"] is not None:
            change["start_16th"] = map_step(change["start_16th"])
    return MelodyDocument.model_validate(data, strict=True)


def _rebar_complementary_phrase(
    document: MelodyDocument, rhythm: BeatThisResult, beat_ms: float
) -> tuple[MelodyDocument, tuple[RhythmDecision, ...]]:
    """Replace a 3/4 + full bars + 1/4 phrase with supported 4/4 downbeats."""
    bars = document.bars
    for first in range(1, len(bars) - 2):
        if _score_span(bars[first]) != 12:
            continue
        for last in range(first + 1, min(first + 8, len(bars) - 1)):
            if _score_span(bars[last]) != 4 or any(
                _score_span(bars[index]) != 16 for index in range(first + 1, last)
            ):
                continue
            start_ms, end_ms = bars[first].start_ms, bars[last].end_ms
            first_beat, start_delta = _nearest(rhythm.beats_ms, start_ms)
            last_beat, end_delta = _nearest(rhythm.beats_ms, end_ms)
            _downbeat, downbeat_delta = _nearest(rhythm.downbeats_ms, end_ms)
            count = last - first
            if not (
                last_beat - first_beat == count * 4
                and start_delta <= beat_ms * 0.4
                and end_delta <= beat_ms * 0.3
                and downbeat_delta <= beat_ms * 0.3
            ):
                continue
            boundaries = [
                start_ms,
                *(rhythm.beats_ms[first_beat + 4 * index] for index in range(1, count)),
                end_ms,
            ]
            if any(right - left < beat_ms * 2.8 for left, right in pairwise(boundaries)):
                continue
            start_step = bars[first].start_16th
            end_step = bars[last].end_16th
            if start_step is None or end_step != start_step + count * 16:
                continue

            data: dict[str, Any] = document.model_dump(mode="python")
            replacement = []
            for index in range(count):
                left, right = boundaries[index], boundaries[index + 1]
                midpoint = (left + right) / 2
                source = min(
                    bars[first : last + 1],
                    key=lambda bar: abs((bar.start_ms + bar.end_ms) / 2 - midpoint),
                )
                replacement.append(
                    MelodyBar(
                        start_ms=left,
                        end_ms=right,
                        beat_times_ms=[
                            left if beat == 0 else rhythm.beats_ms[first_beat + index * 4 + beat]
                            for beat in range(4)
                        ],
                        section_label=source.section_label,
                        start_16th=start_step + index * 16,
                        end_16th=start_step + (index + 1) * 16,
                    ).model_dump(mode="python")
                )
            data["bars"][first : last + 1] = replacement
            for note in data["notes"]:
                if note["start_16th"] is None:
                    continue
                old_end = note["start_16th"] + note["duration_16ths"]
                start = (
                    _phrase_score_step(note["start_ms"], boundaries, start_step)
                    if start_ms <= note["start_ms"] < end_ms
                    else note["start_16th"]
                )
                end = (
                    _phrase_score_step(note["end_ms"], boundaries, start_step)
                    if start_ms < note["end_ms"] <= end_ms
                    else old_end
                )
                note["start_16th"] = start
                note["duration_16ths"] = max(1, end - start)
            for chord in data["chords"]:
                if chord["start_16th"] is not None and start_ms <= chord["at_ms"] < end_ms:
                    chord["start_16th"] = _phrase_score_step(chord["at_ms"], boundaries, start_step)
            for change in data["key_changes"]:
                if change["start_16th"] is not None and start_ms <= change["at_ms"] < end_ms:
                    change["start_16th"] = _phrase_score_step(
                        change["at_ms"], boundaries, start_step
                    )
            result = MelodyDocument.model_validate(data, strict=True)
            return result, (
                RhythmDecision(
                    first + 1,
                    start_ms,
                    bars[first].end_ms,
                    3.0,
                    "beat_this_phrase_start",
                    "paired with a later one-beat bar",
                ),
                RhythmDecision(
                    last + 1,
                    bars[last].start_ms,
                    end_ms,
                    1.0,
                    "beat_this_phrase_rebar",
                    "Beat This! supports a continuous 4/4 phrase",
                ),
            )
    return document, ()


def _rebar_local_phrases(
    document: MelodyDocument, rhythm: BeatThisResult, beat_ms: float
) -> tuple[MelodyDocument, tuple[RhythmDecision, ...]]:
    repairs = plan_meter_repairs(document, rhythm.beats_ms, rhythm.downbeats_ms, beat_ms)
    rebuilt = apply_meter_repairs(document, repairs)
    if rebuilt is document:
        return document, ()
    decisions = tuple(
        RhythmDecision(
            index + 1,
            document.bars[index].start_ms,
            document.bars[index].end_ms,
            (_score_span(document.bars[index]) or 0) / 4,
            "local_meter_rebar",
            "matched phrase endpoints and successive Beat This! downbeats support the replacement",
        )
        for repair in repairs
        for index in range(repair.first, repair.last)
        if _score_span(document.bars[index]) in (4, 12)
    )
    return rebuilt, decisions


def _merge_extended_five_four(
    document: MelodyDocument, rhythm: BeatThisResult, beat_ms: float
) -> tuple[MelodyDocument, tuple[RhythmDecision, ...]]:
    """Join a model-created half/one-beat fragment to its 5/4 parent bar."""
    bars = document.bars
    merge_after: set[int] = set()
    decisions: list[RhythmDecision] = []
    for index in range(1, len(bars) - 1):
        left, right = bars[index], bars[index + 1]
        left_span, right_span = _score_span(left), _score_span(right)
        if (
            left_span is None
            or right_span is None
            or left_span + right_span != 20
            or min(left_span, right_span) > 4
            or left.leading_rest_beats
            or right.leading_rest_beats
            or left.section_label != right.section_label
            or not (left.review == "needs_review" or right.review == "needs_review")
        ):
            continue
        _start, start_delta = _nearest(rhythm.downbeats_ms, left.start_ms)
        _end, end_delta = _nearest(rhythm.downbeats_ms, right.end_ms)
        duration_beats = (right.end_ms - left.start_ms) / beat_ms
        if (
            start_delta > beat_ms * 0.58
            or end_delta > beat_ms * 0.58
            or not 4.35 <= duration_beats <= 5.65
        ):
            continue
        merge_after.add(index)
        decisions.append(
            RhythmDecision(
                index + 2,
                left.start_ms,
                right.end_ms,
                5.0,
                "extended_meter_merge",
                "adjacent score fragments form one downbeat-supported 5/4 measure",
            )
        )
    if not merge_after:
        return document, ()
    data: dict[str, Any] = document.model_dump(mode="python")
    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(bars):
        if index not in merge_after:
            merged.append(bars[index].model_dump(mode="python"))
            index += 1
            continue
        left, right = bars[index], bars[index + 1]
        assert left.start_16th is not None and right.end_16th is not None
        merged.append(
            MelodyBar(
                start_ms=left.start_ms,
                end_ms=right.end_ms,
                beat_times_ms=[
                    left.start_ms + round((right.end_ms - left.start_ms) * beat / 5)
                    for beat in range(5)
                ],
                section_label=left.section_label,
                review="candidate",
                start_16th=left.start_16th,
                end_16th=right.end_16th,
            ).model_dump(mode="python")
        )
        index += 2
    data["bars"] = merged
    return MelodyDocument.model_validate(data, strict=True), tuple(decisions)


def _merge_profile_rest_transition(
    document: MelodyDocument, rhythm: BeatThisResult | None = None
) -> tuple[MelodyDocument, tuple[RhythmDecision, ...]]:
    """Absorb an isolated empty beat after a full bar using the song's own tempo.

    An unconfirmed one-beat rest between regular four-beat measures is much
    more plausibly the tail of an extended measure than a new 1/4 meter.
    Absolute audio times and the model's score positions remain unchanged.
    """
    bars = document.bars
    full = [bar for bar in bars if _score_span(bar) == 16 and not bar.leading_rest_beats]
    if len(full) < 3 or len(full) < len(bars) * .65:
        return document, ()
    pulse = median((bar.end_ms - bar.start_ms) / 4 for bar in full)
    pairs: set[int] = set()
    decisions: list[RhythmDecision] = []
    for index in range(1, len(bars) - 1):
        left, short, following = bars[index - 1 : index + 2]
        preceding_chords = [
            chord.chord for chord in document.chords if chord.at_ms < short.start_ms
        ]
        sounding_chord = preceding_chords[-1] if preceding_chords else None
        if (
            _score_span(left) != 16
            or _score_span(short) != 4
            or _score_span(following) != 16
            or short.review != "needs_review"
            or index - 1 in pairs
            or any(short.start_ms <= note.start_ms < short.end_ms for note in document.notes)
            or any(
                short.start_ms <= chord.at_ms < short.end_ms and chord.chord != sounding_chord
                for chord in document.chords
            )
            or not .72 <= (short.end_ms - short.start_ms) / pulse <= 1.32
            or not 4.55 <= (short.end_ms - left.start_ms) / pulse <= 5.45
        ):
            continue
        if rhythm is not None:
            start_db, start_error = _nearest(rhythm.downbeats_ms, short.start_ms)
            end_db, end_error = _nearest(rhythm.downbeats_ms, short.end_ms)
            if start_db != end_db and max(start_error, end_error) < pulse * .30:
                continue  # Independent downbeats genuinely support the short measure.
        pairs.add(index - 1)
        decisions.append(RhythmDecision(
            index + 1, short.start_ms, short.end_ms, 1.0,
            "song_profile_merge",
            "an empty beat extends the preceding 4/4 bar at the song's local tempo",
        ))
    if not pairs:
        return document, ()
    data: dict[str, Any] = document.model_dump(mode="python")
    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(bars):
        if index not in pairs:
            merged.append(bars[index].model_dump(mode="python"))
            index += 1
            continue
        left, short = bars[index], bars[index + 1]
        merged.append(MelodyBar(
            start_ms=left.start_ms,
            end_ms=short.end_ms,
            beat_times_ms=[*left.beat_times_ms, short.start_ms],
            section_label=left.section_label,
            review="candidate",
            start_16th=left.start_16th,
            end_16th=short.end_16th,
        ).model_dump(mode="python"))
        index += 2
    data["bars"] = merged
    return MelodyDocument.model_validate(data, strict=True), tuple(decisions)


def reconcile_score_with_beat_this(
    document: MelodyDocument, rhythm: BeatThisResult
) -> tuple[MelodyDocument, RhythmComparison]:
    """Choose supported short bars, full-meter repairs, or model-backed merges."""
    beat_intervals = [
        right - left for left, right in pairwise(rhythm.beats_ms) if 250 <= right - left <= 2000
    ]
    if not beat_intervals:
        raise ValueError("Beat This! has no stable beat intervals")
    beat_ms = float(median(beat_intervals))
    document, extended_decisions = _merge_extended_five_four(document, rhythm, beat_ms)
    document, phrase_decisions = _rebar_complementary_phrase(document, rhythm, beat_ms)
    document, local_decisions = _rebar_local_phrases(document, rhythm, beat_ms)
    document, profile_decisions = _merge_profile_rest_transition(document, rhythm)
    spans = Counter(
        span
        for bar in document.bars
        if (span := _score_span(bar)) is not None and not bar.leading_rest_beats
    )
    dominant = spans.most_common(1)[0][0] if spans else None
    prevailing = (
        f"{dominant // 4}/4"
        if dominant is not None and dominant % 4 == 0
        else (f"{dominant // 2}/8" if dominant is not None and dominant % 2 == 0 else "unknown")
    )
    decisions: list[RhythmDecision] = [
        *extended_decisions, *phrase_decisions, *local_decisions, *profile_decisions,
    ]
    confirmed: set[int] = set()
    merges: list[tuple[int, int, int, int]] = []  # previous index, short index, old start, old end
    skip: set[int] = set()
    for index, bar in enumerate(document.bars):
        span = _score_span(bar)
        if span is None or span >= (dominant or 0) or index == 0 or index == len(document.bars) - 1:
            continue
        start_db, start_delta = _nearest(rhythm.downbeats_ms, bar.start_ms)
        end_db, end_delta = _nearest(rhythm.downbeats_ms, bar.end_ms)
        sheet_beats = span / 4
        supported = (
            start_db != end_db
            and start_delta <= beat_ms * 0.35
            and end_delta <= beat_ms * 0.35
            and abs(
                (
                    _nearest(rhythm.beats_ms, rhythm.downbeats_ms[end_db])[0]
                    - _nearest(rhythm.beats_ms, rhythm.downbeats_ms[start_db])[0]
                )
                - sheet_beats
            )
            <= 0.5
        )
        if supported:
            confirmed.add(bar.start_ms)
            if any(row.start_ms < bar.end_ms and row.end_ms > bar.start_ms
                   for row in local_decisions):
                decision = "beat_this_transition"
                reason = "the replacement contains a supported short transition"
            else:
                decision, reason = "sheet", "Beat This! confirms both short-bar downbeats"
        else:
            previous = document.bars[index - 1]
            previous_span = _score_span(previous)
            previous_db, previous_delta = _nearest(rhythm.downbeats_ms, previous.start_ms)
            beat_count = (
                _nearest(rhythm.beats_ms, rhythm.downbeats_ms[end_db])[0]
                - _nearest(rhythm.beats_ms, rhythm.downbeats_ms[previous_db])[0]
            )
            combined_ms = bar.end_ms - previous.start_ms
            model_ms = rhythm.downbeats_ms[end_db] - rhythm.downbeats_ms[previous_db]
            can_merge = (
                dominant == 16
                and span <= 8
                and previous_span == dominant
                and index - 1 not in skip
                and previous.start_16th is not None
                and bar.end_16th is not None
                and start_delta > beat_ms * 0.45
                and previous_db < end_db
                and previous_delta <= beat_ms * 0.58
                and end_delta <= beat_ms * 0.58
                and beat_count == 4
                and model_ms > 0
                and abs(combined_ms - model_ms) <= model_ms * 0.16
            )
            if can_merge:
                decision = "beat_this_merge"
                reason = "short bar lacks a downbeat inside a supported 4/4 span"
                assert previous.start_16th is not None and bar.end_16th is not None
                merges.append((index - 1, index, previous.start_16th, bar.end_16th))
                skip.add(index)
            else:
                decision = "review"
                reason = "models disagree without a safe contiguous 4/4 replacement"
        decisions.append(
            RhythmDecision(index + 1, bar.start_ms, bar.end_ms, sheet_beats, decision, reason)
        )

    # Compare ambiguous short bars with the song's prevailing meter and local
    # full-bar tempo. Beat This! may be in double time, so its lack of a useful
    # downbeat is not evidence in favor of the source meter.
    regrid_starts: set[int] = set()
    resolved: list[RhythmDecision] = []
    for row in decisions:
        if row.decision != "review":
            resolved.append(row)
            continue
        index = row.bar_index - 1
        bar = document.bars[index]
        neighbors = [
            document.bars[neighbor].end_ms - document.bars[neighbor].start_ms
            for neighbor in (index - 2, index - 1, index + 1, index + 2)
            if 0 <= neighbor < len(document.bars)
            and _score_span(document.bars[neighbor]) == dominant
        ]
        profile_bars = [
            candidate.end_ms - candidate.start_ms
            for candidate in document.bars
            if _score_span(candidate) == dominant
        ]
        normal_ms = median(neighbors or profile_bars) if neighbors or profile_bars else None
        duration_ms = bar.end_ms - bar.start_ms
        if (
            dominant == 16
            and _score_span(bar) in (4, 8, 12)
            and normal_ms is not None
            and abs(duration_ms - normal_ms) < abs(
                duration_ms - normal_ms * (_score_span(bar) or 16) / 16
            )
            and duration_ms <= normal_ms * 1.3
        ):
            regrid_starts.add(bar.start_ms)
            resolved.append(
                RhythmDecision(
                    row.bar_index,
                    row.start_ms,
                    row.end_ms,
                    row.sheet_beats,
                    "meter_regrid",
                    "audio duration is closer to the song's prevailing 4/4 bar",
                )
            )
        else:
            confirmed.add(bar.start_ms)
            resolved.append(
                RhythmDecision(
                    row.bar_index,
                    row.start_ms,
                    row.end_ms,
                    row.sheet_beats,
                    "song_profile_meter",
                    "short audio span is closer to its own beat count at the song's local tempo",
                )
            )

    comparison = RhythmComparison(prevailing, round(60_000 / beat_ms), tuple(resolved))
    # A final measure may end with the recording rather than another downbeat.
    # Resolve its meter from the same local pulse instead of exposing a pending
    # question mark for a normal three-beat outro.
    ending = document.bars[-1]
    ending_span = _score_span(ending)
    if ending.review == "needs_review" and ending_span is not None:
        full_durations = [
            (bar.end_ms - bar.start_ms) / (span / 4)
            for bar in document.bars[-6:-1]
            if (span := _score_span(bar)) is not None and span >= 12
        ]
        if full_durations and .72 <= (
            (ending.end_ms - ending.start_ms) / (ending_span / 4)
        ) / median(full_durations) <= 1.32:
            confirmed.add(ending.start_ms)
            resolved.append(RhythmDecision(
                len(document.bars), ending.start_ms, ending.end_ms,
                ending_span / 4, "song_profile_ending",
                "recording ends after a locally timed partial measure",
            ))
            comparison = RhythmComparison(prevailing, round(60_000 / beat_ms), tuple(resolved))
    if confirmed:
        document = document.model_copy(update={"bars": [
            bar.model_copy(update={"review": "candidate"})
            if bar.start_ms in confirmed and bar.review == "needs_review" else bar
            for bar in document.bars
        ]})
    if not merges:
        return _regrid_short_bars(document, regrid_starts), comparison

    def map_step(step: int) -> int:
        removed = 0
        for _previous_index, short_index, old_start, old_end in merges:
            short_span = _score_span(document.bars[short_index])
            assert short_span is not None
            if step < old_start:
                break
            if step < old_end:
                return old_start - removed + round((step - old_start) * 16 / (old_end - old_start))
            removed += short_span
        return step - removed

    data: dict[str, Any] = document.model_dump(mode="python")
    by_previous = {previous: short for previous, short, _, _ in merges}
    removed_indices = {short for _, short, _, _ in merges}
    bars: list[dict[str, Any]] = []
    for index, original in enumerate(document.bars):
        if index in removed_indices:
            continue
        bar_data = original.model_dump(mode="python")
        if index in by_previous:
            short = document.bars[by_previous[index]]
            bar_data["end_ms"] = short.end_ms
            bar_data["beat_times_ms"] = [
                original.start_ms + round((short.end_ms - original.start_ms) * beat / 4)
                for beat in range(4)
            ]
            bar_data["review"] = "needs_review"
            assert short.end_16th is not None
            bar_data["end_16th"] = map_step(short.end_16th)
        if bar_data["start_16th"] is not None:
            bar_data["start_16th"] = map_step(bar_data["start_16th"])
        if index not in by_previous and bar_data["end_16th"] is not None:
            bar_data["end_16th"] = map_step(bar_data["end_16th"])
        bars.append(bar_data)
    data["bars"] = bars
    changed_ranges = [
        (document.bars[previous].start_ms, document.bars[short].end_ms)
        for previous, short, _, _ in merges
    ]
    for note in data["notes"]:
        if note["start_16th"] is not None:
            start = map_step(note["start_16th"])
            end = map_step(note["start_16th"] + note["duration_16ths"])
            note["start_16th"] = start
            note["duration_16ths"] = max(1, end - start)
            if any(left <= note["start_ms"] < right for left, right in changed_ranges):
                note["review"] = "needs_review"
    for chord in data["chords"]:
        if chord["start_16th"] is not None:
            chord["start_16th"] = map_step(chord["start_16th"])
    for change in data["key_changes"]:
        if change["start_16th"] is not None:
            change["start_16th"] = map_step(change["start_16th"])
    result = MelodyDocument.model_validate(data, strict=True)
    assert len(result.bars) == len(document.bars) - len(merges)
    assert all(math.isfinite(float(beat)) for bar in result.bars for beat in bar.beat_times_ms)
    return _regrid_short_bars(result, regrid_starts), comparison

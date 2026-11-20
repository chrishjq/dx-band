# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Align isolated vocal notes to ASR times, then move accompaniment with vocals."""

from __future__ import annotations

from itertools import pairwise
from statistics import median
from typing import Any

from dxband.models.melody import MelodyNote


def notes_from_events(events: dict[str, Any], duration_ms: int) -> list[MelodyNote]:
    notes = []
    for event in events.get("events", []):
        start = round(float(event["time"]) * 1000)
        for value in event.get("values", {}).get("melody") or []:
            end = min(duration_ms, round(float(value["end_time"]) * 1000))
            if 0 <= start < end - 80 and start < duration_ms:
                notes.append(MelodyNote(
                    start_ms=start, end_ms=end, midi=int(value["pitch"]),
                    source="vocals" if int(value["track"]) == 0 else "other",
                    evidence=["sheetsage2"], review="needs_review",
                ))
    return sorted(notes, key=lambda note: (note.start_ms, note.midi))


def align_vocals_to_asr(
    notes: list[MelodyNote], tokens: list[dict[str, Any]],
) -> tuple[list[MelodyNote], int]:
    """One token may anchor one note; token timestamps are never moved."""
    vocal = [note for note in notes if note.source == "vocals"]
    timed = sorted((token for token in tokens if token.get("token") and
                    token.get("start_s") is not None),
                   key=lambda token: float(token["start_s"]))
    rows, columns = len(timed), len(vocal)
    if not rows or not columns:
        return vocal, 0
    skip_token, skip_note, limit = 1.1, .18, 750
    previous = [j * skip_note for j in range(columns + 1)]
    actions = [bytearray(columns + 1) for _ in range(rows + 1)]
    for i, token in enumerate(timed, 1):
        current = [previous[0] + skip_token]
        actions[i][0] = 1
        target = round(float(token["start_s"]) * 1000)
        for j, note in enumerate(vocal, 1):
            best, action = previous[j] + skip_token, 1
            if current[j - 1] + skip_note < best:
                best, action = current[j - 1] + skip_note, 2
            distance = abs(target - note.start_ms)
            paired = previous[j - 1] + distance / 1000 if distance <= limit else float("inf")
            if paired <= best:
                best, action = paired, 3
            current.append(best)
            actions[i][j] = action
        previous = current
    anchors = []
    i, j = rows, columns
    while i and j:
        action = actions[i][j]
        if action == 3:
            anchors.append((j - 1, vocal[j - 1].start_ms,
                            round(float(timed[i - 1]["start_s"]) * 1000)))
            i -= 1
            j -= 1
        elif action == 2:
            j -= 1
        else:
            i -= 1
    anchors.reverse()
    starts = []
    right = 0
    for index, note in enumerate(vocal):
        while right < len(anchors) and anchors[right][0] < index:
            right += 1
        after = anchors[right] if right < len(anchors) else None
        before = anchors[right - 1] if right else None
        if after is not None and after[0] == index:
            start = after[2]
        elif before and after and 0 < after[1] - before[1] <= 3000:
            fraction = (note.start_ms - before[1]) / (after[1] - before[1])
            start = round(note.start_ms + (1 - fraction) * (before[2] - before[1]) +
                          fraction * (after[2] - after[1]))
        else:
            near = min((item for item in (before, after) if item),
                       key=lambda item: abs(note.start_ms - item[1]), default=None)
            start = note.start_ms + (near[2] - near[1]) if near and abs(
                note.start_ms - near[1]) <= 1200 else note.start_ms
        starts.append(max(0, start))
    result = []
    for index, note in enumerate(vocal):
        start = starts[index]
        end = start + max(50, note.end_ms - note.start_ms)
        if index + 1 < len(starts) and starts[index + 1] > start:
            end = min(end, starts[index + 1])
        result.append(note.model_copy(update={"start_ms": start, "end_ms": end}))
    return result, len(anchors)


def _phrases(notes: list[MelodyNote]) -> list[list[tuple[int, MelodyNote]]]:
    phrases: list[list[tuple[int, MelodyNote]]] = []
    for index, note in enumerate(notes):
        if not phrases or note.start_ms - max(n.end_ms for _, n in phrases[-1]) > 900:
            phrases.append([])
        phrases[-1].append((index, note))
    return phrases


def align_other_to_vocals(
    original_vocals: list[MelodyNote], original_other: list[MelodyNote],
    solo_raw: list[MelodyNote], solo_aligned: list[MelodyNote],
    bar_boundaries: list[int],
) -> list[MelodyNote]:
    """Use phrase endpoints for instrumental gaps and reliable local offsets elsewhere."""
    orange = sorted(original_vocals, key=lambda note: note.start_ms)
    raw = sorted(solo_raw, key=lambda note: note.start_ms)
    aligned = sorted(solo_aligned, key=lambda note: note.start_ms)
    if len(raw) != len(aligned):
        raise ValueError("纯人声音符校准前后数量不一致")
    orange_phrases, raw_phrases = _phrases(orange), _phrases(raw)
    matches: dict[int, list[tuple[int, MelodyNote]]] = {}
    previous_target = -1
    for source_index, source in enumerate(orange_phrases):
        candidates = []
        for target_index, target in enumerate(raw_phrases):
            if target_index <= previous_target:
                continue
            ratio = len(target) / len(source)
            prefix = min(3, len(source), len(target))
            pitch_agreement = sum(source[i][1].midi == target[i][1].midi
                                  for i in range(prefix))
            delta = abs(source[0][1].start_ms - target[0][1].start_ms)
            if delta > 1600 or not .7 <= ratio <= 1.4 or pitch_agreement < min(2, prefix):
                continue
            score = delta + 80 * abs(len(source) - len(target)) + 50 * abs(
                source[-1][1].end_ms - target[-1][1].end_ms) / 1000
            candidates.append((score, target_index))
        if candidates:
            previous_target = min(candidates)[1]
            matches[source_index] = raw_phrases[previous_target]
    gaps = []
    for index, (prior, following) in enumerate(pairwise(orange_phrases)):
        before, after = matches.get(index), matches.get(index + 1)
        if not before or not after:
            continue
        raw_start = prior[-1][1].end_ms
        raw_end = following[0][1].start_ms
        target_start = solo_aligned[before[-1][0]].end_ms
        target_end = solo_aligned[after[0][0]].start_ms
        length = raw_end - raw_start
        ratio = (target_end - target_start) / length if length else 0
        if length > 450 and target_end - target_start > 300 and .7 <= ratio <= 1.4:
            gaps.append((raw_start, raw_end, target_start, ratio))
    anchors = []
    for start, end in pairwise(bar_boundaries):
        sources = [note for note in orange if start <= note.start_ms < end]
        targets = [note for note in aligned if start <= note.start_ms < end]
        pairs = [(left, right) for left in sources for right in targets
                 if left.midi == right.midi and abs(left.start_ms - right.start_ms) <= 900]
        offsets = [right.start_ms - left.start_ms for left, right in pairs]
        if len(sources) >= 2 and len(targets) >= 2 and offsets:
            center = median(offsets)
            inliers = [item for item in offsets if abs(item - center) <= 220]
            if len(inliers) >= 2 and abs(median(inliers)) <= 750:
                anchors.append(((start + end) / 2, median(inliers)))

    def local_shift(time: int) -> int:
        if not anchors:
            return 0
        before = [item for item in anchors if item[0] <= time]
        after = [item for item in anchors if item[0] > time]
        if before and after:
            left, right = before[-1], after[0]
            fraction = (time - left[0]) / (right[0] - left[0])
            return round(left[1] + fraction * (right[1] - left[1]))
        return round((before[-1] if before else after[0])[1])

    result = []
    for note in original_other:
        gap = next((item for item in gaps if item[0] <= note.start_ms < item[1]), None)
        if gap:
            source_start, _, target_start, ratio = gap
            start = round(target_start + (note.start_ms - source_start) * ratio)
            end = round(target_start + (note.end_ms - source_start) * ratio)
        else:
            offset = local_shift(note.start_ms)
            start, end = note.start_ms + offset, note.end_ms + offset
        result.append(note.model_copy(update={"start_ms": max(0, start),
                                       "end_ms": max(max(0, start) + 1, end)}))
    return result

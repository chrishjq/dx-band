# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from bisect import bisect_right
from dataclasses import dataclass

from dxband.models.lyric import LyricLine, LyricsDocument


@dataclass(frozen=True, slots=True)
class KaraokeProgress:
    line_progress: float


@dataclass(frozen=True, slots=True)
class TimelineContext:
    previous: LyricLine | None
    current: LyricLine | None
    next: LyricLine | None
    next_countdown_ms: int | None
    progress: KaraokeProgress


class LyricTimeline:
    def __init__(
        self,
        document: LyricsDocument,
        *,
        hold_previous_until_next: bool = False,
    ) -> None:
        self.document = document
        self._starts_ms = [line.start_ms for line in document.lines]
        self._hold_previous_until_next = hold_previous_until_next

    def context_at(self, position_ms: int) -> TimelineContext:
        candidate_index = bisect_right(self._starts_ms, position_ms) - 1
        current_index: int | None = None
        previous_index: int | None = None
        next_index: int | None = None
        if candidate_index >= 0:
            candidate = self.document.lines[candidate_index]
            following_index = (
                candidate_index + 1
                if candidate_index + 1 < len(self.document.lines)
                else None
            )
            hold_candidate = (
                self._hold_previous_until_next
                and following_index is not None
                and position_ms < self.document.lines[following_index].start_ms
            )
            if position_ms < candidate.end_ms or hold_candidate:
                current_index = candidate_index
                previous_index = candidate_index - 1 if candidate_index > 0 else None
                next_index = following_index
            else:
                previous_index = candidate_index
                next_index = following_index
        elif self.document.lines:
            next_index = 0

        previous = self.document.lines[previous_index] if previous_index is not None else None
        current = self.document.lines[current_index] if current_index is not None else None
        next_line = self.document.lines[next_index] if next_index is not None else None
        countdown_ms = max(0, next_line.start_ms - position_ms) if next_line is not None else None
        return TimelineContext(
            previous=previous,
            current=current,
            next=next_line,
            next_countdown_ms=countdown_ms,
            progress=self._progress(current, position_ms),
        )

    @staticmethod
    def _progress(line: LyricLine | None, position_ms: int) -> KaraokeProgress:
        if line is None:
            return KaraokeProgress(0.0)
        duration_ms = max(1, line.end_ms - line.start_ms)
        line_progress = min(1.0, max(0.0, (position_ms - line.start_ms) / duration_ms))
        return KaraokeProgress(line_progress)

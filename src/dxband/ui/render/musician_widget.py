# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Ten-line musician cue with degree chords above their lyric positions."""

import re
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from itertools import pairwise
from math import ceil

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QResizeEvent

from dxband.analysis.chord_notation import (
    capo_for_display_key,
    capo_for_selected_tonic,
    chord_for_mode,
    valid_display_mode,
)
from dxband.constants import MUSICIAN_FONT_SIZE_MIN
from dxband.lyrics.character_timing import (
    character_index_at,
    is_title_metadata_line,
    sung_interval,
    unique_character_indices,
)
from dxband.lyrics.instrumental_markers import instrumental_marker_label
from dxband.lyrics.musician_bar_rows import MusicianBarRow, build_musician_bar_rows
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.lyric import LyricLine, LyricsDocument
from dxband.ui.render.singer_widget import SingerWidget


class MusicianWidget(SingerWidget):
    row_count = 10
    current_row = 3
    clock_backstep_tolerance_ms = 50
    instrumental_gap_min_ms = 3_500
    intro_gap_min_ms = 1_200
    cue_chords_per_row = 4
    cue_bars_per_row = 2
    wide_cue_bars_per_row = 4
    wide_layout_min_width = 1280
    bar_view_row_count = 5
    bar_view_current_row = 2
    beat_dot_pulse_duration_ms = 240
    beat_dot_peak_progress = 0.48
    beat_dot_peak_scale = 1.7
    beat_dot_lit_scale = 1.45

    def __init__(self) -> None:
        super().__init__()
        self.cue_bars_per_row = self._bars_per_row_for_width(self.width())
        self.setWindowTitle("乐手屏（双击或 F11 全屏）")
        self.chords: ChordTimeline | None = None
        self._source_document: LyricsDocument | None = None
        self._bar_rows: tuple[MusicianBarRow, ...] = ()
        self._bar_font_signature: tuple[object, ...] | None = None
        self._bar_font_size = 12
        self.chord_mode = "degree"
        self._source_lines: tuple[LyricLine, ...] = ()
        self._document_lines: tuple[LyricLine, ...] = ()
        self._line_starts_ms: tuple[int, ...] = ()
        self._cue_line_ids: frozenset[str] = frozenset()
        self._cue_chords_by_line_id: dict[str, tuple[ChordSegment, ...]] = {}
        self._cue_beats_by_line_id: dict[str, tuple[int, ...]] = {}
        self._cue_beat_labels_by_line_id: dict[str, tuple[str, ...]] = {}
        self._marker_line_ids: frozenset[str] = frozenset()
        self._display_position_ms = 0
        self._last_clock_position_ms: int | None = None
        self._document_tiles: tuple[tuple[float, QPixmap], ...] = ()
        self._active_row_pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._document_layer_signature: tuple[object, ...] | None = None
        self._frame_buffers: tuple[QPixmap, QPixmap] | None = None
        self._frame_buffer_signature: tuple[int, int, float] | None = None
        self._frame_buffer_index = 0
        self._chord_owner_signature: tuple[object, ...] | None = None
        self._chord_owner_line_ids: tuple[str | None, ...] = ()
        self.guide_countdown = (0, 0)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def set_guide_countdown(self, remaining: int, total: int) -> None:
        countdown = (max(0, remaining), max(0, total))
        if countdown[0] > countdown[1]:
            countdown = (countdown[1], countdown[1])
        if countdown != self.guide_countdown:
            self.guide_countdown = countdown
            self.update()

    def set_document(self, document: LyricsDocument | None) -> None:
        """一次性建立整首歌词的纵向坐标索引。"""
        self._source_document = document
        self._source_lines = tuple(document.lines) if document is not None else ()
        self._display_position_ms = self.position_ms
        self._last_clock_position_ms = None
        super().set_document(document)
        self._rebuild_document_lines()
        self._rebuild_bar_rows()

    def set_font_size(self, point_size: int) -> None:
        normalized = max(MUSICIAN_FONT_SIZE_MIN, point_size)
        if self.font_size != normalized:
            self.font_size = normalized
            self._bar_font_signature = None
            self.update()

    @classmethod
    def _bars_per_row_for_width(cls, width: int) -> int:
        return cls.wide_cue_bars_per_row if width >= cls.wide_layout_min_width else 2

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        bars_per_row = self._bars_per_row_for_width(event.size().width())
        if bars_per_row == self.cue_bars_per_row:
            return
        self.cue_bars_per_row = bars_per_row
        self._rebuild_document_lines()
        self._rebuild_bar_rows()

    def set_chord_mode(self, mode: str) -> None:
        if not valid_display_mode(mode):
            raise ValueError("无效的乐手屏和弦模式")
        if self.chord_mode != mode:
            self.chord_mode = mode
            self._bar_font_signature = None
            self._rebuild_document_lines()
            self.update()

    def _musical_info_text(self) -> str:
        if not self.original_key or self.bpm <= 0:
            return ""
        musical_info = f"原KEY {self.original_key} · {self.bpm} BPM"
        if self.chord_mode == "chord_c":
            selected_key = "C"
        elif self.chord_mode.startswith("key:"):
            selected_key = self.chord_mode[4:]
        else:
            return musical_info
        capo = (
            capo_for_selected_tonic(self.original_key, selected_key)
            if self.chord_mode.startswith("key:")
            else capo_for_display_key(self.original_key, selected_key)
        )
        transpose = (
            capo if capo is not None and capo <= 5 else capo - 12
        ) if capo is not None else None
        if capo is None or transpose is None:
            return musical_info
        sign = "+" if transpose >= 0 else ""
        return (
            f"原KEY {self.original_key} · 移调{sign}{transpose} · "
            f"Capo {capo} · {self.bpm} BPM"
        )

    def set_chords(self, chords: ChordTimeline | None) -> None:
        self.chords = chords
        self._rebuild_document_lines()
        self._rebuild_bar_rows()
        self.update()

    def _rebuild_bar_rows(self) -> None:
        self._bar_rows = build_musician_bar_rows(
            self._source_document,
            self.beat_times_ms,
            self.downbeat_times_ms,
            self.beats_per_bar,
            self.chords,
            self.cue_bars_per_row,
        )
        self._bar_font_signature = None
        self.update()

    def set_music_info(
        self,
        original_key: str,
        bpm: int,
        beat_times_ms: tuple[int, ...] | list[int] = (),
        downbeat_times_ms: tuple[int, ...] | list[int] = (),
        beats_per_bar: int | None = None,
        *,
        title: str = "",
        artist: str = "",
    ) -> None:
        previous_title = self.song_title
        previous_beat_times = self.beat_times_ms
        previous_downbeats = self.downbeat_times_ms
        previous_meter = self.beats_per_bar
        previous_key = self.original_key
        super().set_music_info(
            original_key,
            bpm,
            beat_times_ms,
            downbeat_times_ms,
            beats_per_bar,
            title=title,
            artist=artist,
        )
        if (
            self.song_title != previous_title
            or self.beat_times_ms != previous_beat_times
            or self.downbeat_times_ms != previous_downbeats
            or self.beats_per_bar != previous_meter
            or self.original_key != previous_key
        ):
            self._rebuild_document_lines()
            self._rebuild_bar_rows()

    def _instrumental_cue_rows(
        self,
        label: str,
        start_ms: int,
        end_ms: int,
        segments: tuple[ChordSegment, ...],
        next_id: int,
    ) -> tuple[
        list[tuple[int, LyricLine]],
        dict[str, tuple[ChordSegment, ...]],
        dict[str, tuple[int, ...]],
        dict[str, tuple[str, ...]],
        int,
    ]:
        """Build two-bar cue rows, keeping chord changes on their nearest beat."""
        rows: list[tuple[int, LyricLine]] = []
        chords_by_line_id: dict[str, tuple[ChordSegment, ...]] = {}
        beats_by_line_id: dict[str, tuple[int, ...]] = {}
        labels_by_line_id: dict[str, tuple[str, ...]] = {}
        if not segments:
            return rows, chords_by_line_id, beats_by_line_id, labels_by_line_id, next_id

        beats = tuple(beat for beat in self.beat_times_ms if start_ms <= beat < end_ms)
        if beats:
            beats_per_row = self._beats_per_cue_row()
            row_starts = [0]
            if self.downbeat_times_ms and self.beats_per_bar:
                anchor = bisect_left(self.beat_times_ms, self.downbeat_times_ms[0])
                first_global_beat = bisect_left(self.beat_times_ms, beats[0])
                first_bar = (first_global_beat - anchor) // self.beats_per_bar
                current_group = 0
                for index in range(1, len(beats)):
                    bar = (first_global_beat + index - anchor) // self.beats_per_bar
                    group = (bar - first_bar) // self.cue_bars_per_row
                    if group != current_group:
                        row_starts.append(index)
                        current_group = group
            else:
                row_starts.extend(range(beats_per_row, len(beats), beats_per_row))
            row_starts.append(len(beats))
            beat_labels: list[list[str]] = [[] for _beat in beats]
            for segment in segments:
                chord_text = self.chord_label(segment.chord)
                if not chord_text:
                    continue
                beat_index = min(
                    range(len(beats)), key=lambda index: abs(beats[index] - segment.start_ms)
                )
                if not beat_labels[beat_index] or beat_labels[beat_index][-1] != chord_text:
                    beat_labels[beat_index].append(chord_text)
            for first, following in pairwise(row_starts):
                row_beats = beats[first:following]
                cue_start = start_ms if first == 0 else row_beats[0]
                cue_end = beats[following] if following < len(beats) else end_ms
                cue = LyricLine(
                    id=f"line-{next_id:04d}",
                    start_ms=cue_start,
                    end_ms=cue_end,
                    text=label if first == 0 else f"{label}·续",
                )
                next_id += 1
                rows.append((cue_start, cue))
                beats_by_line_id[cue.id] = row_beats
                row_labels = ["→".join(labels) for labels in beat_labels[first:following]]
                labels_by_line_id[cue.id] = tuple(row_labels)
                chords_by_line_id[cue.id] = tuple(
                    segment
                    for segment in segments
                    if segment.start_ms < cue_end and segment.end_ms > cue_start
                )
            return rows, chords_by_line_id, beats_by_line_id, labels_by_line_id, next_id

        # Legacy songs without a beat grid keep their chord-only cue rows.
        for first in range(0, len(segments), self.cue_chords_per_row):
            following = first + self.cue_chords_per_row
            cue_start = start_ms if first == 0 else segments[first].start_ms
            cue_end = segments[following].start_ms if following < len(segments) else end_ms
            cue = LyricLine(
                id=f"line-{next_id:04d}",
                start_ms=cue_start,
                end_ms=cue_end,
                text=label if first == 0 else f"{label}·续",
            )
            next_id += 1
            rows.append((cue_start, cue))
            chords_by_line_id[cue.id] = segments[first:following]
        return rows, chords_by_line_id, beats_by_line_id, labels_by_line_id, next_id

    def _rebuild_document_lines(self) -> None:
        """Add chord-bearing instrumental rows without changing the lyric document."""
        if self.chords is None or not self.chords.segments:
            self._document_lines = tuple(
                line
                for line in self._source_lines
                if not is_title_metadata_line(line, self.song_title)
            )
            self._line_starts_ms = tuple(line.start_ms for line in self._document_lines)
            self._cue_line_ids = frozenset()
            self._cue_chords_by_line_id = {}
            self._cue_beats_by_line_id = {}
            self._cue_beat_labels_by_line_id = {}
            self._marker_line_ids = frozenset(
                line.id
                for line in self._document_lines
                if instrumental_marker_label(line) is not None
            )
            self._invalidate_document_layer()
            return

        vocals = tuple(
            line for line in self._source_lines if not is_title_metadata_line(line, self.song_title)
        )
        entries: list[tuple[int, LyricLine]] = []
        cue_ids: set[str] = set()
        cue_chords_by_line_id: dict[str, tuple[ChordSegment, ...]] = {}
        cue_beats_by_line_id: dict[str, tuple[int, ...]] = {}
        cue_beat_labels_by_line_id: dict[str, tuple[str, ...]] = {}
        marker_ids: set[str] = set()
        next_id = (
            max(
                (int(line.id.removeprefix("line-")) for line in self._source_lines),
                default=0,
            )
            + 1
        )
        previous_end = 0
        for index, line in enumerate(vocals):
            explicit_label = instrumental_marker_label(line)
            if explicit_label is not None:
                entries.append((line.start_ms, line))
                marker_ids.add(line.id)
                marker_chords = tuple(
                    segment
                    for segment in self.chords.segments
                    if segment.start_ms < line.end_ms and segment.end_ms > line.start_ms
                )
                cue_rows, cue_chords, cue_beats, cue_labels, next_id = self._instrumental_cue_rows(
                    explicit_label,
                    line.start_ms,
                    line.end_ms,
                    marker_chords,
                    next_id,
                )
                entries.extend(cue_rows)
                cue_ids.update(cue.id for _start, cue in cue_rows)
                cue_chords_by_line_id.update(cue_chords)
                cue_beats_by_line_id.update(cue_beats)
                cue_beat_labels_by_line_id.update(cue_labels)
                previous_end = line.end_ms
                continue
            interval = sung_interval(line)
            vocal_start, vocal_end = (
                interval
                if interval is not None
                else (
                    line.start_ms,
                    line.end_ms,
                )
            )
            gap_start = previous_end
            gap_end = vocal_start
            gap_chords = tuple(
                segment
                for segment in self.chords.segments
                if segment.start_ms < gap_end and segment.end_ms > gap_start
            )
            minimum = self.intro_gap_min_ms if index == 0 else self.instrumental_gap_min_ms
            if gap_end - gap_start >= minimum and gap_chords:
                label = "前奏" if index == 0 else "间奏"
                marker = LyricLine(
                    id=f"line-{next_id:04d}",
                    start_ms=gap_start,
                    end_ms=gap_end,
                    text=f"（{label}）",
                )
                next_id += 1
                entries.append((gap_start, marker))
                marker_ids.add(marker.id)
                cue_rows, cue_chords, cue_beats, cue_labels, next_id = self._instrumental_cue_rows(
                    label,
                    gap_start,
                    gap_end,
                    gap_chords,
                    next_id,
                )
                entries.extend(cue_rows)
                cue_ids.update(cue.id for _start, cue in cue_rows)
                cue_chords_by_line_id.update(cue_chords)
                cue_beats_by_line_id.update(cue_beats)
                cue_beat_labels_by_line_id.update(cue_labels)
            entries.append((vocal_start, line))
            previous_end = vocal_end

        tail_end = max(
            previous_end,
            vocals[-1].end_ms if vocals else previous_end,
            max(
                (segment.end_ms for segment in self.chords.segments),
                default=previous_end,
            ),
        )
        tail_chords = tuple(
            ChordSegment(
                start_ms=max(previous_end, segment.start_ms),
                end_ms=segment.end_ms,
                chord=segment.chord,
            )
            for segment in self.chords.segments
            if segment.start_ms < tail_end and segment.end_ms > previous_end
        )
        if vocals and tail_end - previous_end >= self.instrumental_gap_min_ms and tail_chords:
            marker = LyricLine(
                id=f"line-{next_id:04d}",
                start_ms=previous_end,
                end_ms=tail_end,
                text="（尾奏）",
            )
            next_id += 1
            entries.append((previous_end, marker))
            marker_ids.add(marker.id)
            cue_rows, cue_chords, cue_beats, cue_labels, next_id = self._instrumental_cue_rows(
                "尾奏",
                previous_end,
                tail_end,
                tail_chords,
                next_id,
            )
            entries.extend(cue_rows)
            cue_ids.update(cue.id for _start, cue in cue_rows)
            cue_chords_by_line_id.update(cue_chords)
            cue_beats_by_line_id.update(cue_beats)
            cue_beat_labels_by_line_id.update(cue_labels)

        self._document_lines = tuple(line for _start, line in entries)
        self._line_starts_ms = tuple(start for start, _line in entries)
        self._cue_line_ids = frozenset(cue_ids)
        self._cue_chords_by_line_id = cue_chords_by_line_id
        self._cue_beats_by_line_id = cue_beats_by_line_id
        self._cue_beat_labels_by_line_id = cue_beat_labels_by_line_id
        self._marker_line_ids = frozenset(marker_ids)
        self._invalidate_document_layer()

    def _invalidate_document_layer(self) -> None:
        # 歌词与和弦按整首预渲染；改动时间轴后须清除两种行缓存。
        self._document_tiles = ()
        self._active_row_pixmaps.clear()
        self._document_layer_signature = None
        self._chord_owner_signature = None
        self._chord_owner_line_ids = ()

    def set_position_ms(
        self,
        position_ms: int,
        *,
        beat_position_ms: int | None = None,
    ) -> None:
        """乐手屏含连续滚动，每次时钟更新都需要重绘。"""
        previous_position = self.position_ms
        previous_beat_position = self.beat_position_ms
        if self._last_clock_position_ms is None:
            self._display_position_ms = position_ms
        elif (
            position_ms < self._display_position_ms
            and self._display_position_ms - position_ms <= self.clock_backstep_tolerance_ms
        ):
            # 音频设备回调重新校时时可能倒退几毫秒。显示时钟不跟随这种
            # 微小回退，避免整页歌词向下抖动；较大回退仍视为用户拖动。
            pass
        else:
            self._display_position_ms = position_ms
        self._last_clock_position_ms = position_ms
        super().set_position_ms(position_ms, beat_position_ms=beat_position_ms)
        if self.position_ms != previous_position or self.beat_position_ms != previous_beat_position:
            self.update()

    def visible_lines(self) -> tuple[LyricLine | None, ...]:
        if not self._document_lines:
            return (None,) * self.row_count
        lines = self._document_lines
        current = self._current_line_index()
        return tuple(
            lines[index] if 0 <= index < len(lines) else None
            for index in range(
                current - self.current_row,
                current + self.row_count - self.current_row,
            )
        )

    def _current_line_index(self) -> int:
        if not self._document_lines:
            return 0
        return max(0, bisect_right(self._line_starts_ms, self._display_position_ms) - 1)

    def _next_active_line_index(self, current: int) -> int:
        """Skip marker rows that share a timestamp with the next chord row."""
        following = bisect_right(self._line_starts_ms, self._line_starts_ms[current])
        if following >= len(self._line_starts_ms):
            return len(self._line_starts_ms)
        return bisect_right(self._line_starts_ms, self._line_starts_ms[following]) - 1

    def document_scroll_position(self) -> float:
        """返回整首歌词坐标系中的连续行位置。"""
        if not self._document_lines:
            return 0.0
        current = self._current_line_index()
        line = self._document_lines[current]
        next_index = self._next_active_line_index(current)
        target_ms = (
            self._line_starts_ms[next_index]
            if next_index < len(self._document_lines)
            else line.end_ms
        )
        span_ms = max(1, target_ms - line.start_ms)
        progress = max(
            0.0,
            min(1.0, (self._display_position_ms - line.start_ms) / span_ms),
        )
        return current + progress * (
            next_index - current if next_index < len(self._document_lines) else 1
        )

    def scroll_progress(self) -> float:
        """Continuous progress to the next lyric row, used for smooth upward motion."""
        current = self._current_line_index()
        if not self._document_lines:
            return 0.0
        next_index = self._next_active_line_index(current)
        row_span = next_index - current if next_index < len(self._document_lines) else 1
        return (self.document_scroll_position() - current) / row_span

    def chord_label(self, chord: str) -> str:
        return chord_for_mode(chord, self.original_key, self.chord_mode)

    def _info_font(self) -> QFont:
        """标题字号只随窗口尺寸变化，不跟随歌词字号控件。"""
        font = QFont(
            self.lyrics_style.font_family,
            max(12, round(15 * self.height() / 720.0)),
        )
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def content_font_sizes(self, row_height: float) -> tuple[int, int]:
        """让歌词与和弦使用同一缩放档位，且不限制用户设置的最大值。"""
        height_scale = self.height() / 720.0
        lyric_size = max(
            12,
            round(self.font_size * 0.65 * height_scale),
        )
        chord_size = max(
            9,
            round((self.font_size * 0.38 + 3) * height_scale),
        )
        return lyric_size, chord_size

    @staticmethod
    def _vocal_line_baselines(
        row_top: float,
        row_height: float,
        lyric_metrics: QFontMetrics,
        chord_metrics: QFontMetrics,
    ) -> tuple[float, float]:
        """Attach a chord to the visible top edge of the lyric below it."""
        lyric_baseline = row_top + row_height * 0.88
        visual_gap = max(3.0, lyric_metrics.tightBoundingRect("歌词").height() * 0.08)
        lyric_ink_top = lyric_metrics.tightBoundingRect("歌词").top()
        chord_ink_bottom = chord_metrics.tightBoundingRect("4maj7").bottom()
        chord_baseline = lyric_baseline + lyric_ink_top - chord_ink_bottom - visual_gap
        return lyric_baseline, chord_baseline

    def chords_for_line(self, line: LyricLine) -> tuple[ChordSegment, ...]:
        if self.chords is None:
            return ()
        if line.id in self._cue_chords_by_line_id:
            return self._cue_chords_by_line_id[line.id]
        if line.id not in self._cue_line_ids and is_title_metadata_line(line, self.song_title):
            return ()
        if not self._document_lines:
            interval = sung_interval(line)
            start_ms, end_ms = (
                interval
                if interval is not None
                else (
                    line.start_ms,
                    line.end_ms,
                )
            )
            return tuple(
                segment for segment in self.chords.segments if start_ms <= segment.start_ms < end_ms
            )
        self._prepare_chord_owners()
        return tuple(
            segment
            for index, segment in enumerate(self.chords.segments)
            if self._chord_owner_line_ids[index] == line.id
        )

    def _prepare_chord_owners(self) -> None:
        """Assign each chord onset to its actual vocal or instrumental row."""
        signature = (id(self.chords), id(self._document_lines), self.song_title)
        if signature == self._chord_owner_signature:
            return
        self._chord_owner_signature = signature
        if self.chords is None:
            self._chord_owner_line_ids = ()
            return
        owners: list[str | None] = []
        for segment in self.chords.segments:
            owner: str | None = None
            index = bisect_right(self._line_starts_ms, segment.start_ms) - 1
            if index >= 0:
                candidate = self._document_lines[index]
                interval = None if candidate.id in self._cue_line_ids else sung_interval(candidate)
                end_ms = interval[1] if interval is not None else candidate.end_ms
                if segment.start_ms < end_ms and (
                    candidate.id in self._cue_line_ids
                    or not is_title_metadata_line(candidate, self.song_title)
                ):
                    owner = candidate.id
                elif index + 1 < len(self._document_lines):
                    following = self._document_lines[index + 1]
                    following_start = self._line_starts_ms[index + 1]
                    if (
                        following.id not in self._cue_line_ids
                        and following_start - end_ms < self.instrumental_gap_min_ms
                        and segment.end_ms > following_start
                    ):
                        # A chord that anticipates the next vocal line during a
                        # short breath belongs to that upcoming lyric.
                        owner = following.id
            owners.append(owner)
        self._chord_owner_line_ids = tuple(owners)

    @staticmethod
    def _character_index(line: LyricLine, timestamp_ms: int) -> int:
        return character_index_at(line, timestamp_ms)

    @staticmethod
    def _accidental_font(font: QFont) -> QFont:
        small = QFont(font)
        small.setPointSize(max(8, round(font.pointSize() * 0.67)))
        return small

    @classmethod
    def _chord_width(cls, label: str, font: QFont) -> int:
        normal = QFontMetrics(font)
        small = QFontMetrics(cls._accidental_font(font))
        superscript_indices = cls._chord_superscript_indices(label)
        return sum(
            small.horizontalAdvance("♯" if char == "#" else "♭")
            if char in {"#", "b"}
            else small.horizontalAdvance(char)
            if index in superscript_indices
            else normal.horizontalAdvance(char)
            for index, char in enumerate(label)
        )

    @classmethod
    def _lyric_gap_expansions(
        cls,
        line: LyricLine,
        positioned_labels: tuple[tuple[int, str], ...],
        lyric_font: QFont,
        chord_font: QFont,
        available_width: int,
    ) -> tuple[float, ...]:
        """Return local gaps needed between lyric characters under dense chords."""
        gap_count = max(0, len(line.text) - 1)
        if len(positioned_labels) < 2 or gap_count == 0:
            return (0.0,) * gap_count
        metrics = QFontMetrics(lyric_font)
        base_positions = tuple(
            metrics.horizontalAdvance(line.text[:index]) for index in range(len(line.text) + 1)
        )
        expansions = [0.0] * gap_count
        for (index, label), (next_index, _next_label) in pairwise(positioned_labels):
            character_distance = next_index - index
            if character_distance <= 0:
                continue
            anchor_distance = base_positions[next_index] - base_positions[index]
            missing = cls._chord_width(label, chord_font) + 5 - anchor_distance
            if missing > 0:
                local_gap = missing / character_distance
                for boundary in range(index, min(next_index, gap_count)):
                    expansions[boundary] = max(expansions[boundary], local_gap)

        required = sum(expansions)
        if required <= 0:
            return tuple(expansions)
        base_width = metrics.horizontalAdvance(line.text)
        available_extra = max(0, available_width - base_width)
        if required > available_extra:
            scale = available_extra / required
            expansions = [gap * scale for gap in expansions]
        return tuple(expansions)

    @staticmethod
    def _lyric_prefix_positions(
        text: str,
        metrics: QFontMetrics,
        gap_expansions: tuple[float, ...],
    ) -> tuple[float, ...]:
        """Measure character anchors using the same locally split runs as painting."""
        positions = [0.0] * (len(text) + 1)
        run_start = 0
        run_x = 0.0
        for boundary, extra in enumerate(gap_expansions[: max(0, len(text) - 1)]):
            if extra <= 0:
                continue
            for index in range(run_start, boundary + 1):
                positions[index] = run_x + metrics.horizontalAdvance(text[run_start:index])
            run = text[run_start : boundary + 1]
            run_x += metrics.horizontalAdvance(run) + extra
            run_start = boundary + 1
        for index in range(run_start, len(text) + 1):
            positions[index] = run_x + metrics.horizontalAdvance(text[run_start:index])
        return tuple(positions)

    @staticmethod
    def _draw_lyric_text(
        painter: QPainter,
        text: str,
        x: float,
        baseline: float,
        metrics: QFontMetrics,
        gap_expansions: tuple[float, ...],
    ) -> None:
        """Paint lyric runs with extra width only at selected character gaps."""
        run_start = 0
        run_x = x
        for boundary, extra in enumerate(gap_expansions[: max(0, len(text) - 1)]):
            if extra <= 0:
                continue
            run = text[run_start : boundary + 1]
            painter.drawText(QPointF(run_x, baseline), run)
            run_x += metrics.horizontalAdvance(run) + extra
            run_start = boundary + 1
        painter.drawText(QPointF(run_x, baseline), text[run_start:])

    @staticmethod
    def _chord_superscript_indices(label: str) -> frozenset[int]:
        """仅将和弦性质中的 7 设为上标，根音 7 和斜杠低音保持正常。"""
        root = re.match(r"(?:[#b]?[1-7]|[A-G][#b]?)", label)
        if root is None:
            return frozenset()
        suffix_end = label.find("/")
        if suffix_end < 0:
            suffix_end = len(label)
        return frozenset(index for index in range(root.end(), suffix_end) if label[index] == "7")

    @classmethod
    def _draw_chord_label(
        cls, painter: QPainter, label: str, x: float, baseline: float, font: QFont
    ) -> None:
        normal = QFontMetrics(font)
        small_font = cls._accidental_font(font)
        small = QFontMetrics(small_font)
        cursor = x
        superscript_indices = cls._chord_superscript_indices(label)
        for index, char in enumerate(label):
            if char in {"#", "b"} or index in superscript_indices:
                glyph = "♯" if char == "#" else "♭" if char == "b" else char
                painter.setFont(small_font)
                painter.drawText(QPointF(cursor, baseline - font.pointSize() * 0.35), glyph)
                cursor += small.horizontalAdvance(glyph)
            else:
                painter.setFont(font)
                painter.drawText(QPointF(cursor, baseline), char)
                cursor += normal.horizontalAdvance(char)

    @staticmethod
    def chord_color(active_line: bool) -> QColor:
        return QColor("#FFD34E" if active_line else "#8FE1C8")

    def _document_layer_offset(self, top: float, row_height: float) -> float:
        """整首歌词只使用一个对齐到物理像素的纵向偏移。"""
        offset = top + (self.current_row - self.document_scroll_position()) * row_height
        pixel_ratio = self.devicePixelRatioF()
        return round(offset * pixel_ratio) / pixel_ratio

    def _prepare_document_layer(
        self,
        row_height: float,
        lyric_size: int,
        chord_size: int,
    ) -> None:
        """一次性将所有歌词行合成同一个逻辑图层。"""
        signature = (
            self.width(),
            round(self.devicePixelRatioF(), 3),
            round(row_height, 3),
            lyric_size,
            chord_size,
            self.lyrics_style.font_family,
            self.chord_mode,
            self.original_key,
            id(self.chords),
            tuple(line.id for line in self._document_lines),
        )
        if signature == self._document_layer_signature:
            return
        self._document_layer_signature = signature
        self._document_tiles = self._render_document_tiles(
            row_height,
            lyric_size,
            chord_size,
        )
        self._active_row_pixmaps.clear()

    def _render_document_tiles(
        self,
        row_height: float,
        lyric_size: int,
        chord_size: int,
    ) -> tuple[tuple[float, QPixmap], ...]:
        if not self._document_lines:
            return ()
        pixel_ratio = self.devicePixelRatioF()
        physical_row_height = max(1, round(row_height * pixel_ratio))
        rows_per_tile = max(1, min(16, 4096 // physical_row_height))
        tiles: list[tuple[float, QPixmap]] = []
        for first_row in range(0, len(self._document_lines), rows_per_tile):
            lines = self._document_lines[first_row : first_row + rows_per_tile]
            tile = QPixmap(
                max(1, ceil(self.width() * pixel_ratio)),
                max(1, physical_row_height * len(lines)),
            )
            tile.setDevicePixelRatio(pixel_ratio)
            tile.fill(Qt.GlobalColor.transparent)
            tile_painter = QPainter(tile)
            tile_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            tile_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            for local_index, line in enumerate(lines):
                self._draw_line(
                    tile_painter,
                    line,
                    active=False,
                    row_top=local_index * row_height,
                    row_height=row_height,
                    lyric_size=lyric_size,
                    chord_size=chord_size,
                )
            tile_painter.end()
            tiles.append((first_row * row_height, tile))
        return tuple(tiles)

    def _active_row_pixmap(
        self,
        line: LyricLine,
        row_height: float,
        lyric_size: int,
        chord_size: int,
    ) -> QPixmap:
        cached = self._active_row_pixmaps.get(line.id)
        if cached is not None:
            self._active_row_pixmaps.move_to_end(line.id)
            return cached
        pixel_ratio = self.devicePixelRatioF()
        pixmap = QPixmap(
            max(1, ceil(self.width() * pixel_ratio)),
            max(1, round(row_height * pixel_ratio)),
        )
        pixmap.setDevicePixelRatio(pixel_ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        row_painter = QPainter(pixmap)
        row_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._draw_line(
            row_painter,
            line,
            active=True,
            row_top=0.0,
            row_height=row_height,
            lyric_size=lyric_size,
            chord_size=chord_size,
        )
        row_painter.end()
        self._active_row_pixmaps[line.id] = pixmap
        while len(self._active_row_pixmaps) > self.row_count:
            self._active_row_pixmaps.popitem(last=False)
        return pixmap

    def _draw_line(
        self,
        painter: QPainter,
        line: LyricLine,
        *,
        active: bool,
        row_top: float,
        row_height: float,
        lyric_size: int,
        chord_size: int,
    ) -> None:
        lyric_font = QFont(self.lyrics_style.font_family, lyric_size)
        # 只改变颜色，不改变字重或度量，避免换句时视觉跳动。
        lyric_font.setWeight(QFont.Weight.Normal)
        chord_font = QFont(self.lyrics_style.font_family, chord_size)
        chord_font.setWeight(QFont.Weight.DemiBold)
        if line.id in self._marker_line_ids:
            marker_font = QFont(lyric_font)
            marker_font.setPointSize(max(10, round(lyric_size * 0.78)))
            painter.setFont(marker_font)
            painter.setPen(
                self.lyrics_style.current_color if active else self.lyrics_style.next_color
            )
            painter.drawText(
                QRectF(24.0, row_top, max(0.0, self.width() - 48.0), row_height),
                Qt.AlignmentFlag.AlignCenter,
                line.text,
            )
            return
        if line.id in self._cue_line_ids:
            self._draw_instrumental_cue(
                painter,
                line,
                active=active,
                row_top=row_top,
                row_height=row_height,
                chord_font=chord_font,
            )
            return
        segments = self.chords_for_line(line)
        positions = unique_character_indices(
            line,
            tuple(max(segment.start_ms, line.start_ms) for segment in segments),
        )
        positioned = tuple(
            (segment, character_index, self.chord_label(segment.chord))
            for segment, character_index in zip(segments, positions, strict=True)
            if character_index is not None
        )
        positioned_labels = tuple(
            (character_index, label) for _segment, character_index, label in positioned if label
        )
        gap_expansions = self._lyric_gap_expansions(
            line,
            positioned_labels,
            lyric_font,
            chord_font,
            max(1, self.width() - 48),
        )
        lyric_metrics = QFontMetrics(lyric_font)
        chord_metrics = QFontMetrics(chord_font)
        lyric_baseline, chord_baseline = self._vocal_line_baselines(
            row_top,
            row_height,
            lyric_metrics,
            chord_metrics,
        )
        prefix_positions = self._lyric_prefix_positions(
            line.text,
            lyric_metrics,
            gap_expansions,
        )
        text = lyric_metrics.elidedText(
            line.text, Qt.TextElideMode.ElideRight, max(1, self.width() - 48)
        )
        text_width = (
            prefix_positions[-1] if text == line.text else lyric_metrics.horizontalAdvance(text)
        )
        content_width = max(
            [text_width]
            + [
                prefix_positions[character_index] + self._chord_width(label, chord_font)
                for _segment, character_index, label in positioned
                if label
            ]
        )
        text_x = max(24, (self.width() - content_width) // 2)
        painter.setFont(lyric_font)
        painter.setPen(self.lyrics_style.current_color if active else self.lyrics_style.next_color)
        self._draw_lyric_text(
            painter,
            text,
            text_x,
            lyric_baseline,
            lyric_metrics,
            gap_expansions if text == line.text else (),
        )

        painter.setFont(chord_font)
        for _segment, char_index, label in positioned:
            if not label:
                continue
            x = text_x + prefix_positions[char_index]
            label_width = self._chord_width(label, chord_font)
            x = max(24, min(x, self.width() - 24 - label_width))
            painter.setPen(self.chord_color(active))
            self._draw_chord_label(
                painter,
                label,
                x,
                chord_baseline,
                chord_font,
            )

    def _beats_per_cue_row(self) -> int:
        return self.cue_bars_per_row * (self.beats_per_bar or 4)

    def _bar_grid_metrics(self, width: int) -> tuple[float, float]:
        beats_per_row = self._beats_per_cue_row()
        margin = max(24.0, width * 0.04)
        grid_width = max(0.0, width - margin * 2.0)
        return margin, grid_width / beats_per_row

    def _beat_x(self, index: int, width: int) -> float:
        grid_left, slot_width = self._bar_grid_metrics(width)
        return grid_left + (index + 0.5) * slot_width

    @classmethod
    def _beat_dot_scale(cls, beat_ms: int, position_ms: int) -> float:
        """Return one restrained arrival pulse, then keep the reached beat enlarged."""
        age_ms = position_ms - beat_ms
        if age_ms < 0:
            return 1.0
        progress = min(1.0, age_ms / cls.beat_dot_pulse_duration_ms)
        if progress <= cls.beat_dot_peak_progress:
            phase = progress / cls.beat_dot_peak_progress
            return 1.0 + (cls.beat_dot_peak_scale - 1.0) * phase
        phase = (progress - cls.beat_dot_peak_progress) / (
            1.0 - cls.beat_dot_peak_progress
        )
        return cls.beat_dot_peak_scale + (
            cls.beat_dot_lit_scale - cls.beat_dot_peak_scale
        ) * phase

    def _bar_separator_xs(self, width: int) -> tuple[float, ...]:
        grid_left, slot_width = self._bar_grid_metrics(width)
        beats_per_bar = self.beats_per_bar or 4
        return tuple(
            grid_left + index * slot_width
            for index in range(0, self._beats_per_cue_row(), beats_per_bar)
        )

    def _two_bar_lyric_rect(self, beat_index: int, row_top: float, row_height: float) -> QRectF:
        _grid_left, slot_width = self._bar_grid_metrics(self.width())
        return QRectF(
            self._beat_x(beat_index, self.width()) - slot_width / 2.0 + 3.0,
            row_top + row_height * 0.66,
            max(1.0, slot_width - 6.0),
            row_height * 0.32,
        )

    def _two_bar_font_size(self, row_height: float) -> int:
        """Fit one shared chord/lyric size to the densest row in the song."""
        signature = (
            self.width(),
            self.height(),
            row_height,
            self.font_size,
            self.lyrics_style.font_family,
            self.chord_mode,
            self.original_key,
            id(self._bar_rows),
        )
        if signature == self._bar_font_signature:
            return self._bar_font_size

        _grid_left, slot_width = self._bar_grid_metrics(self.width())
        lyric_rows = tuple(
            tuple((index, text) for index, text in enumerate(row.lyric_cells) if text)
            for row in self._bar_rows
        )
        chord_rows = tuple(
            tuple(
                (index, "→".join(self.chord_label(chord) for chord in cell))
                for index, cell in enumerate(row.chord_cells)
                if cell
            )
            for row in self._bar_rows
        )
        font_size, _ = self.content_font_sizes(row_height)
        while font_size > 12:
            lyric_font = QFont(self.lyrics_style.font_family, font_size)
            chord_font = QFont(self.lyrics_style.font_family, font_size)
            chord_font.setWeight(QFont.Weight.DemiBold)
            lyric_metrics = QFontMetrics(lyric_font)
            crowded_lyrics = any(
                (
                    lyric_metrics.horizontalAdvance(text)
                    + lyric_metrics.horizontalAdvance(next_text)
                ) / 2.0 + 5.0 > (next_index - index) * slot_width
                for labeled in lyric_rows
                for (index, text), (next_index, next_text) in pairwise(labeled)
            )
            crowded_chords = any(
                (self._chord_width(label, chord_font) + self._chord_width(next_label, chord_font))
                / 2.0 + 6.0 > (next_index - index) * slot_width
                for labeled in chord_rows
                for (index, label), (next_index, next_label) in pairwise(labeled)
            )
            if not crowded_lyrics and not crowded_chords:
                break
            font_size -= 1
        self._bar_font_signature = signature
        self._bar_font_size = font_size
        return font_size

    def _paint_two_bar_view(self, painter: QPainter, top: float, bottom: float) -> None:
        """Draw a fixed two-bar beat grid for both sung and instrumental passages."""
        if not self._bar_rows:
            return
        row_height = max(1.0, (bottom - top) / self.bar_view_row_count)
        starts = tuple(row.start_ms for row in self._bar_rows)
        current = max(0, min(len(starts) - 1, bisect_right(starts, self._display_position_ms) - 1))
        following = self._bar_rows[current].end_ms
        progress = max(
            0.0,
            min(
                1.0,
                (self._display_position_ms - starts[current]) / max(1, following - starts[current]),
            ),
        )
        offset = top + (self.bar_view_current_row - current - progress) * row_height
        painter.save()
        painter.setClipRect(QRectF(0.0, top, self.width(), max(0.0, bottom - top)))
        for index in range(max(0, current - 3), min(len(self._bar_rows), current + 5)):
            row_top = offset + index * row_height
            if row_top + row_height < top or row_top > bottom:
                continue
            self._draw_two_bar_row(
                painter,
                self._bar_rows[index],
                row_top,
                row_height,
                active=index == current,
            )
        painter.restore()

    def _draw_two_bar_row(
        self,
        painter: QPainter,
        row: MusicianBarRow,
        row_top: float,
        row_height: float,
        *,
        active: bool,
    ) -> None:
        beats_per_row = self._beats_per_cue_row()
        font_size = self._two_bar_font_size(row_height)
        chord_labels = tuple(
            "→".join(self.chord_label(chord) for chord in cell) for cell in row.chord_cells
        )
        chord_font = QFont(self.lyrics_style.font_family, font_size)
        chord_font.setWeight(QFont.Weight.DemiBold)
        lyric_font = QFont(self.lyrics_style.font_family, font_size)
        section_content_shift = row_height * 0.1 if row.section_label else 0.0

        if active:
            painter.fillRect(
                QRectF(12.0, row_top, max(0.0, self.width() - 24.0), row_height),
                QColor(255, 209, 102, 17),
            )
        row_rule = QColor("#FFD166" if active else "#FFFFFF")
        row_rule.setAlpha(38 if active else 14)
        painter.setPen(QPen(row_rule, 1.0))
        painter.drawLine(
            QPointF(12.0, row_top + row_height - 0.5),
            QPointF(self.width() - 12.0, row_top + row_height - 0.5),
        )
        bar_rule = QColor("#FFFFFF")
        bar_rule.setAlpha(46 if active else 25)
        painter.setPen(QPen(bar_rule, 1.0))
        for separator_x in self._bar_separator_xs(self.width()):
            painter.drawLine(
                QPointF(separator_x, row_top + 7.0),
                QPointF(separator_x, row_top + row_height - 7.0),
            )
        if row.section_label:
            label_font = QFont(self.lyrics_style.font_family)
            label_font.setPointSize(max(9, round(font_size * 0.48)))
            label_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(label_font)
            label_metrics = QFontMetrics(label_font)
            label_width = label_metrics.horizontalAdvance(row.section_label) + 16.0
            label_height = max(20.0, label_metrics.height() + 5.0)
            grid_left, _slot_width = self._bar_grid_metrics(self.width())
            label_rect = QRectF(
                grid_left + 7.0,
                row_top + 6.0,
                label_width,
                label_height,
            )
            painter.save()
            label_background = QColor("#FFD166")
            label_background.setAlpha(31 if active else 17)
            label_border = QColor("#FFD166")
            label_border.setAlpha(62 if active else 34)
            painter.setBrush(label_background)
            painter.setPen(QPen(label_border, 1.0))
            painter.drawRoundedRect(label_rect, 5.0, 5.0)
            label_color = QColor("#FFD166")
            label_color.setAlpha(245 if active else 145)
            painter.setPen(label_color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, row.section_label)
            painter.restore()

        painter.setFont(chord_font)
        painter.setPen(self.chord_color(active))
        for index, label in enumerate(chord_labels):
            if not label:
                continue
            width = self._chord_width(label, chord_font)
            x = self._beat_x(index, self.width()) - width / 2.0
            self._draw_chord_label(
                painter,
                label,
                x,
                row_top + row_height * 0.37 + section_content_shift,
                chord_font,
            )

        if self.beat_lights_visible:
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(beats_per_row):
                has_beat = index < len(row.beat_times_ms)
                reached = has_beat and row.beat_times_ms[index] <= self.beat_position_ms
                lit = active and reached
                color = QColor("#8FE1C8" if lit else "#8AA99F")
                color.setAlpha(28 if not has_beat else 255 if lit else 86 if active else 100)
                painter.setBrush(color)
                radius = 6.0 if has_beat else 4.5
                if lit:
                    radius *= self._beat_dot_scale(
                        row.beat_times_ms[index], self.beat_position_ms
                    )
                painter.drawEllipse(
                    QPointF(
                        self._beat_x(index, self.width()),
                        row_top + row_height * 0.57 + section_content_shift,
                    ),
                    radius,
                    radius,
                )
            painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.setFont(lyric_font)
        painter.setPen(self.lyrics_style.current_color if active else self.lyrics_style.next_color)
        lyric_metrics = QFontMetrics(lyric_font)
        for index, text in enumerate(row.lyric_cells):
            if text:
                lyric_rect = self._two_bar_lyric_rect(index, row_top, row_height)
                lyric_rect.setWidth(
                    max(lyric_rect.width(), lyric_metrics.horizontalAdvance(text) + 2.0)
                )
                lyric_rect.moveCenter(
                    QPointF(self._beat_x(index, self.width()), lyric_rect.center().y())
                )
                painter.drawText(
                    lyric_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )

    def _draw_beat_dots(self, painter: QPainter, row_height: float, active_index: int) -> None:
        """Paint beat arrivals after cached rows, lighting each beat as it is reached."""
        if not self.beat_lights_visible:
            return
        for row_index, line in enumerate(self._document_lines):
            beats = self._cue_beats_by_line_id.get(line.id)
            if not beats:
                continue
            y = row_index * row_height + row_height * 0.70
            active = row_index == active_index
            for index, beat_ms in enumerate(beats):
                reached = beat_ms <= self._display_position_ms
                lit = active and reached
                color = QColor("#8FE1C8" if lit else "#8AA99F")
                color.setAlpha(255 if lit else 86 if active else 100)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                radius = 8.0
                if lit:
                    radius *= self._beat_dot_scale(beat_ms, self._display_position_ms)
                painter.drawEllipse(QPointF(self._beat_x(index, self.width()), y), radius, radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_instrumental_cue(
        self,
        painter: QPainter,
        line: LyricLine,
        *,
        active: bool,
        row_top: float,
        row_height: float,
        chord_font: QFont,
    ) -> None:
        """Place each chord change above its beat dot; dots update during playback."""
        beats = self._cue_beats_by_line_id.get(line.id)
        if beats:
            labels = self._cue_beat_labels_by_line_id[line.id]
            painter.setPen(self.chord_color(active))
            baseline = row_top + row_height * 0.43
            for index, label in enumerate(labels):
                if not label:
                    continue
                width = self._chord_width(label, chord_font)
                x = self._beat_x(index, self.width()) - width / 2.0
                x = max(24.0, min(x, self.width() - 24.0 - width))
                self._draw_chord_label(painter, label, x, baseline, chord_font)
            return

        # Older song packages without beat timestamps retain chord-only cues.
        segments = self.chords_for_line(line)
        labels = tuple(self.chord_label(segment.chord) for segment in segments)
        if not labels:
            return
        left = 24.0
        right = max(left, self.width() - 24.0)
        widths = tuple(self._chord_width(label, chord_font) for label in labels)
        slot_width = max(max(widths) + 12.0, min(160.0, (right - left) / 4.0))
        grid_left = max(left, (self.width() - slot_width * 4.0) / 2.0)
        painter.setPen(self.chord_color(active))
        for index, label in enumerate(labels):
            if not label:
                continue
            x = min(grid_left + index * slot_width, right - widths[index])
            self._draw_chord_label(painter, label, x, row_top + row_height * 0.65, chord_font)

    def _next_frame_buffer(self) -> QPixmap:
        """在屏外完整绘制一帧，再一次性提交到窗口。"""
        pixel_ratio = self.devicePixelRatioF()
        signature = (self.width(), self.height(), round(pixel_ratio, 3))
        if self._frame_buffers is None or signature != self._frame_buffer_signature:
            buffers: list[QPixmap] = []
            for _index in range(2):
                pixmap = QPixmap(
                    max(1, ceil(self.width() * pixel_ratio)),
                    max(1, ceil(self.height() * pixel_ratio)),
                )
                pixmap.setDevicePixelRatio(pixel_ratio)
                buffers.append(pixmap)
            self._frame_buffers = (buffers[0], buffers[1])
            self._frame_buffer_signature = signature
            self._frame_buffer_index = 0
        frame = self._frame_buffers[self._frame_buffer_index]
        self._frame_buffer_index = 1 - self._frame_buffer_index
        return frame

    def _guide_panel_rect(self, top: float, row_height: float) -> QRectF:
        width = min(420.0, max(0.0, self.width() - 48.0))
        height = 100.0
        if self._bar_rows:
            return QRectF((self.width() - width) / 2.0, max(58.0, top + 4.0), width, height)
        marker_index = next(
            (
                index
                for index, line in enumerate(self._document_lines)
                if line.id in self._marker_line_ids and "前奏" in line.text
            ),
            None,
        )
        if marker_index is not None:
            marker_top = self._document_layer_offset(top, row_height) + marker_index * row_height
            height = min(height, max(50.0, marker_top - 68.0))
            panel_top = max(58.0, marker_top - height - 10.0)
        else:
            panel_top = max(58.0, self.height() * 0.18)
        panel_top = min(panel_top, max(58.0, self.height() - height - 16.0))
        return QRectF((self.width() - width) / 2.0, panel_top, width, height)

    def _paint_guide_countdown(self, painter: QPainter, top: float, row_height: float) -> None:
        remaining, total = self.guide_countdown
        if not remaining or not total:
            return
        panel = self._guide_panel_rect(top, row_height)
        if panel.width() < 95:
            return
        painter.save()
        scale = panel.height() / 100.0
        painter.setPen(QColor("#295b81"))
        painter.setBrush(QColor("#0b1a2b"))
        painter.drawRoundedRect(panel, 14.0, 14.0)

        number_font = QFont(self.font())
        number_font.setPixelSize(max(28, round(44 * scale)))
        number_font.setBold(True)
        painter.setFont(number_font)
        painter.setPen(QColor("#69c8ff"))
        painter.drawText(
            QRectF(
                panel.center().x() + 25.0,
                panel.top() + 7.0 * scale,
                72.0,
                56.0 * scale,
            ),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            str(remaining),
        )

        label_font = QFont(self.font())
        label_font.setPixelSize(max(13, round(19 * scale)))
        painter.setFont(label_font)
        painter.setPen(QColor("#a6dcff"))
        painter.drawText(
            QRectF(
                panel.center().x() - 106.0,
                panel.top() + 7.0 * scale,
                124.0,
                56.0 * scale,
            ),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
            "引导拍子",
        )

        bar_size = max(1, total // 2)
        group_gap = 18.0
        step = min(30.0, max(9.0, (panel.width() - 54.0 - group_gap) / max(1, total - 1)))
        dots_left = panel.center().x() - ((total - 1) * step + group_gap) / 2.0
        radius = min(8.0 * scale, step * 0.3)
        current_index = total - remaining
        for index in range(total):
            x = dots_left + index * step + (group_gap if index >= bar_size else 0.0)
            if index < current_index:
                painter.setBrush(QColor("#0b1a2b"))
                painter.setPen(QColor("#366783"))
            elif index == current_index:
                painter.setBrush(QColor("#69c8ff"))
                painter.setPen(QColor("#bce8ff"))
            else:
                painter.setBrush(QColor("#376b94"))
                painter.setPen(QColor("#5a98c4"))
            y = panel.top() + panel.height() * 0.73
            painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
        painter.restore()

    def paintEvent(self, _event: object) -> None:
        frame = self._next_frame_buffer()
        frame.fill(Qt.GlobalColor.black)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        header_font = self._info_font()
        painter.setFont(header_font)
        painter.setPen(self.lyrics_style.next_color)
        header_width = max(0, self.width() - 48)
        header = self._visible_music_info(QFontMetrics(header_font), header_width)
        painter.drawText(24, 16, header_width, 32, Qt.AlignmentFlag.AlignLeft, header)

        top = 58
        bottom = self.height() - max(60, round(self.height() * 0.1))
        if self._bar_rows:
            self._paint_two_bar_view(painter, top, bottom)
            self._paint_guide_countdown(painter, top, (bottom - top) / self.bar_view_row_count)
            painter.end()
            window_painter = QPainter(self)
            window_painter.drawPixmap(QPointF(0.0, 0.0), frame)
            return
        pixel_ratio = self.devicePixelRatioF()
        row_height = max(1, round((bottom - top) / self.row_count * pixel_ratio)) / pixel_ratio
        lyric_size, chord_size = self.content_font_sizes(row_height)
        self._prepare_document_layer(row_height, lyric_size, chord_size)
        active_index = self._current_line_index()
        painter.save()
        painter.setClipRect(0, top, self.width(), max(0, round(bottom - top)))
        painter.translate(0.0, self._document_layer_offset(top, row_height))
        for tile_y, tile in self._document_tiles:
            painter.drawPixmap(QPointF(0.0, tile_y), tile)
        if self._document_lines:
            active_y = active_index * row_height
            painter.fillRect(
                QRectF(0.0, active_y, float(self.width()), row_height),
                Qt.GlobalColor.black,
            )
            painter.drawPixmap(
                QPointF(0.0, active_y),
                self._active_row_pixmap(
                    self._document_lines[active_index],
                    row_height,
                    lyric_size,
                    chord_size,
                ),
            )
            self._draw_beat_dots(painter, row_height, active_index)
        painter.restore()
        self._paint_guide_countdown(painter, top, row_height)
        painter.end()

        window_painter = QPainter(self)
        window_painter.drawPixmap(QPointF(0.0, 0.0), frame)

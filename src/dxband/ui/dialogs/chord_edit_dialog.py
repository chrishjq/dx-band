# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""歌曲库中以歌词为基准的和弦表编辑器。"""

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dxband.analysis.chord_notation import (
    chord_for_mode,
    chord_from_mode,
    chord_key_is_valid,
)
from dxband.lyrics.character_timing import (
    character_index_at,
    character_timestamp,
    is_title_metadata_line,
    sung_interval,
    unique_character_indices,
)
from dxband.lyrics.instrumental_markers import instrumental_marker_label
from dxband.lyrics.musician_bar_rows import MusicianBarRow, build_musician_bar_rows
from dxband.models.chord import ChordSegment, ChordTimeline
from dxband.models.lyric import LyricLine, LyricsDocument, WordTiming
from dxband.ui.page_layout import set_button_icon
from dxband.ui.public_messages import public_message
from dxband.ui.widgets.analysis_progress import analysis_progress


def _chord_character_index(line: LyricLine, timestamp_ms: int) -> int:
    """按乐手屏规则，将和弦时间映射到歌词字符位置。"""
    return character_index_at(line, timestamp_ms)


class ChordLyricRow(QFrame):
    """每个歌词字符一列，和弦输入框固定在字符上方。"""

    @staticmethod
    def _update_editor_presence(editor: QLineEdit, text: str) -> None:
        has_chord = bool(text.strip())
        if editor.property("hasChord") == has_chord:
            return
        editor.setProperty("hasChord", has_chord)
        editor.style().unpolish(editor)
        editor.style().polish(editor)
        editor.update()

    def __init__(
        self,
        line: LyricLine,
        cells: list[tuple[int, str, int | None, ChordSegment | None, str]],
        changed: Callable[[LyricLine, int, int | None, QLineEdit], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.line = line
        self.setObjectName("chordLyricRow")
        self.setFixedHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_layout = QHBoxLayout(self)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(5)
        self.editors: list[tuple[int, int | None, QLineEdit]] = []
        self.character_labels: list[QLabel] = []
        self.character_cells: list[QWidget] = []
        for character_index, character, segment_index, _segment, label in cells:
            cell = QWidget(self)
            cell.setFixedSize(74, 76)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(2, 0, 2, 0)
            cell_layout.setSpacing(6)
            editor = QLineEdit(label, cell)
            editor.setObjectName("chordInlineEditor")
            editor.setProperty("hasChord", bool(label.strip()))
            editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            editor.setFixedHeight(38)
            editor_font = QFont(editor.font())
            editor_font.setPointSize(16)
            editor_font.setWeight(QFont.Weight.DemiBold)
            editor.setFont(editor_font)
            location = f'“{character}”' if character.strip() else "歌词间空位"
            editor.setToolTip(f"修改{location}上方的和弦；留空表示此处不变和弦")
            editor.textChanged.connect(
                lambda text, current=editor: self._update_editor_presence(current, text)
            )
            editor.editingFinished.connect(
                partial(changed, line, character_index, segment_index, editor)
            )
            lyric_label = QLabel(
                character if character and not character.isspace() else "\u00a0",
                cell,
            )
            lyric_label.setObjectName("chordEditorLyricCharacter")
            lyric_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lyric_font = QFont(lyric_label.font())
            lyric_font.setPointSize(20)
            lyric_font.setWeight(QFont.Weight.DemiBold)
            lyric_label.setFont(lyric_font)
            cell_layout.addWidget(editor)
            cell_layout.addWidget(lyric_label)
            row_layout.addWidget(cell)
            self.editors.append((character_index, segment_index, editor))
            self.character_labels.append(lyric_label)
            self.character_cells.append(cell)
        row_layout.addStretch(1)


class InstrumentalChordRow(QFrame):
    """Eight editable chord slots for an intro, interlude, or outro row."""

    def __init__(
        self,
        label: str,
        entries: list[tuple[int | None, str, int, int]],
        changed: Callable[[int | None, int, int, QLineEdit], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chordLyricRow")
        self.setFixedHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        heading = QLabel(f"（{label}）", self)
        heading.setObjectName("instrumentalChordHeading")
        heading.setFixedWidth(108)
        layout.addWidget(heading)
        self.editors: list[tuple[int | None, QLineEdit]] = []
        for segment_index, chord_label, start_ms, section_end_ms in entries:
            cell = QWidget(self)
            cell.setFixedSize(116, 76)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(2, 0, 2, 0)
            cell_layout.setSpacing(4)
            editor = QLineEdit(chord_label, cell)
            editor.setObjectName("chordInlineEditor")
            editor.setProperty("hasChord", bool(chord_label.strip()))
            editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
            editor.setFixedHeight(38)
            editor_font = QFont(editor.font())
            editor_font.setPointSize(16)
            editor_font.setWeight(QFont.Weight.DemiBold)
            editor.setFont(editor_font)
            editor.setToolTip(
                "修改此处的和弦；清空可删除" if segment_index is not None else "在此时间新增和弦"
            )
            editor.textChanged.connect(
                lambda text, current=editor: ChordLyricRow._update_editor_presence(current, text)
            )
            editor.editingFinished.connect(
                partial(changed, segment_index, start_ms, section_end_ms, editor)
            )
            timestamp = QLabel(
                f"{start_ms // 60_000:02d}:{start_ms % 60_000 // 1000:02d}.{start_ms % 1000:03d}",
                cell,
            )
            timestamp.setObjectName("instrumentalChordTime")
            timestamp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell_layout.addWidget(editor)
            cell_layout.addWidget(timestamp)
            layout.addWidget(cell)
            self.editors.append((segment_index, editor))
        layout.addStretch(1)


class BeatChordLyricRow(QFrame):
    """A compact multi-measure row with chord and lyric inputs on every beat."""

    def __init__(
        self,
        row_index: int,
        row: MusicianBarRow,
        beats_per_bar: int,
        bars_per_row: int,
        chord_entries: list[tuple[tuple[int, ...], str]],
        chord_changed: Callable[[int, tuple[int, ...], QLineEdit], None],
        lyric_changed: Callable[[int, int, QLineEdit], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chordBeatRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(6)
        first_bar = row_index * bars_per_row + 1
        heading_text = f"第 {first_bar}–{first_bar + bars_per_row - 1} 小节"
        if row.section_label:
            heading_text += f" · {row.section_label}"
        heading = QLabel(heading_text, self)
        heading.setObjectName("chordBeatRowHeading")
        root.addWidget(heading)
        bars = QHBoxLayout()
        bars.setSpacing(8)
        self.measures: list[QFrame] = []
        self.chord_editors: list[QLineEdit] = []
        self.lyric_editors: list[QLineEdit] = []
        for bar_index in range(bars_per_row):
            bar = QFrame(self)
            bar.setObjectName("chordBeatMeasure")
            bar.setProperty("currentMeasure", False)
            self.measures.append(bar)
            bar_layout = QHBoxLayout(bar)
            bar_layout.setContentsMargins(3, 2, 3, 2)
            bar_layout.setSpacing(2)
            for local_beat in range(beats_per_bar):
                beat_index = bar_index * beats_per_bar + local_beat
                has_beat = beat_index < len(row.beat_times_ms)
                cell = QWidget(bar)
                cell.setObjectName("chordBeatCell")
                cell.setFixedWidth(78)
                cell_layout = QVBoxLayout(cell)
                cell_layout.setContentsMargins(2, 0, 2, 0)
                cell_layout.setSpacing(3)
                beat_label = QLabel(f"{local_beat + 1} 拍", cell)
                beat_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell_layout.addWidget(beat_label)
                indices, chord_label = chord_entries[beat_index]
                chord_editor = QLineEdit(chord_label, cell)
                chord_editor.setObjectName("chordInlineEditor")
                chord_editor.setProperty("hasChord", bool(chord_label.strip()))
                chord_editor.setProperty("beatOriginalLabel", chord_label)
                chord_editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
                chord_editor.setPlaceholderText("和弦")
                chord_editor.setFixedHeight(32)
                chord_font = QFont(chord_editor.font())
                chord_font.setPointSize(13)
                chord_font.setWeight(QFont.Weight.DemiBold)
                chord_editor.setFont(chord_font)
                chord_editor.setEnabled(has_beat)
                chord_editor.textChanged.connect(
                    lambda text, current=chord_editor: ChordLyricRow._update_editor_presence(
                        current, text
                    )
                )
                if has_beat:
                    chord_editor.editingFinished.connect(
                        partial(chord_changed, row.beat_times_ms[beat_index], indices, chord_editor)
                    )
                cell_layout.addWidget(chord_editor)
                lyric_editor = QLineEdit(
                    row.lyric_cells[beat_index] if beat_index < len(row.lyric_cells) else "",
                    cell,
                )
                lyric_editor.setObjectName("lyricBeatEditor")
                lyric_editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lyric_editor.setPlaceholderText("歌词")
                lyric_editor.setFixedHeight(34)
                lyric_font = QFont(lyric_editor.font())
                lyric_font.setPointSize(13)
                lyric_editor.setFont(lyric_font)
                lyric_editor.setEnabled(has_beat)
                if has_beat:
                    lyric_editor.editingFinished.connect(
                        partial(lyric_changed, row_index, beat_index, lyric_editor)
                    )
                cell_layout.addWidget(lyric_editor)
                bar_layout.addWidget(cell)
                self.chord_editors.append(chord_editor)
                self.lyric_editors.append(lyric_editor)
            bars.addWidget(bar)
            if bar_index < bars_per_row - 1:
                separator = QFrame(self)
                separator.setObjectName("chordBeatMeasureSeparator")
                separator.setFrameShape(QFrame.Shape.VLine)
                separator.setFrameShadow(QFrame.Shadow.Plain)
                bars.addWidget(separator)
        root.addLayout(bars)

    def set_current_measure(self, measure_index: int | None) -> None:
        for index, measure in enumerate(self.measures):
            active = index == measure_index
            if measure.property("currentMeasure") == active:
                continue
            measure.setProperty("currentMeasure", active)
            measure.style().unpolish(measure)
            measure.style().polish(measure)
            measure.update()


class ChordEditDialog(QDialog):
    chords_confirmed = Signal(object)
    lyrics_confirmed = Signal(object)
    lyrics_changed = Signal(object)
    reanalysis_requested = Signal()
    analysis_running_changed = Signal(bool)
    status_changed = Signal(str)

    _MODES = (
        ("级数谱", "degree"),
        ("和弦谱", "chord"),
        ("和弦谱（C调）", "chord_c"),
    )
    _BARS_PER_ROW = 4

    def __init__(
        self,
        timeline: ChordTimeline | None,
        document: LyricsDocument,
        title: str,
        original_key: str,
        duration_ms: int,
        initial_mode: str = "degree",
        show_analysis_controls: bool = True,
        embedded: bool = False,
        parent: QWidget | None = None,
        *,
        beat_times_ms: tuple[int, ...] | list[int] = (),
        downbeat_times_ms: tuple[int, ...] | list[int] = (),
        beats_per_bar: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.timeline = timeline or ChordTimeline()
        self.document = document
        self.title = title
        self.original_key = original_key
        self.duration_ms = duration_ms
        self.embedded = embedded
        self.show_analysis_controls = show_analysis_controls
        self.beat_times_ms = tuple(beat_times_ms)
        self.downbeat_times_ms = tuple(downbeat_times_ms)
        self.beats_per_bar = beats_per_bar
        self._beat_rows: tuple[MusicianBarRow, ...] = ()
        self._pending_lyric_cut = False
        self._pending_lyric_line_ids: set[str] = set()
        self._active_measure_index: int | None = None
        self._position_follow_enabled = True
        self._last_position_ms: int | None = None
        self._lyric_search_matches: list[tuple[str, int]] = []
        self._lyric_search_index = -1
        self._lyric_search_highlight: QWidget | None = None
        self.chord_edits: dict[int, QLineEdit] = {}
        self.cell_edits: list[QLineEdit] = []
        self.beat_rows: list[BeatChordLyricRow] = []
        self.lyric_rows: list[ChordLyricRow] = []
        self.instrumental_rows: list[InstrumentalChordRow] = []
        self._manual_instrumental_starts: set[int] = set()
        self.setWindowTitle(f"修改和弦 - {title}")
        self.resize(1560, 820)
        self.setModal(False)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)

        root = QVBoxLayout(self)
        root.setContentsMargins(16 if embedded else 24, 16, 16 if embedded else 24, 14)
        root.setSpacing(12)
        if not embedded:
            heading = QLabel(f"修改和弦 · {title}", self)
            heading.setObjectName("pageTitle")
            root.addWidget(heading)

        toolbar_panel = QFrame(self)
        toolbar_panel.setObjectName("editorPanel")
        toolbar_layout = QVBoxLayout(toolbar_panel)
        toolbar_layout.setContentsMargins(16, 12, 16, 14)
        toolbar_layout.setSpacing(0)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        toolbar.addWidget(QLabel("编辑模式", self))
        self.mode_combo = QComboBox(self)
        self.mode_combo.setObjectName("chordEditMode")
        for label, mode in self._MODES:
            self.mode_combo.addItem(label, mode)
        if not chord_key_is_valid(original_key):
            initial_mode = "chord"
        selected = self.mode_combo.findData(initial_mode)
        self.mode_combo.setCurrentIndex(max(0, selected))
        self.mode_combo.currentIndexChanged.connect(self._render_timeline)
        toolbar.addWidget(self.mode_combo)
        self._update_key_options()
        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("搜索歌词", self))
        self.lyric_search_edit = QLineEdit(self)
        self.lyric_search_edit.setObjectName("chordLyricSearchEdit")
        self.lyric_search_edit.setPlaceholderText("输入歌词关键词")
        self.lyric_search_edit.setClearButtonEnabled(True)
        self.lyric_search_edit.setMaximumWidth(280)
        toolbar.addWidget(self.lyric_search_edit)
        self.lyric_search_previous_button = QPushButton("上一处", self)
        set_button_icon(self.lyric_search_previous_button, "previous.svg")
        self.lyric_search_next_button = QPushButton("下一处", self)
        set_button_icon(self.lyric_search_next_button, "next.svg")
        toolbar.addWidget(self.lyric_search_previous_button)
        toolbar.addWidget(self.lyric_search_next_button)
        self.lyric_search_result_label = QLabel("", self)
        self.lyric_search_result_label.setObjectName("lyricSearchResult")
        toolbar.addWidget(self.lyric_search_result_label)
        toolbar.addStretch(1)
        self.reanalyze_button = QPushButton("重新识别和弦", self)
        set_button_icon(self.reanalyze_button, "chord.svg")
        self.reanalyze_button.setObjectName("reanalyzeChordsButton")
        self.reanalyze_button.clicked.connect(self._request_reanalysis)
        toolbar.addWidget(self.reanalyze_button)
        self.progress = analysis_progress(self)
        toolbar.addWidget(self.progress)
        if not show_analysis_controls:
            self.reanalyze_button.hide()
            self.progress.hide()
        toolbar_layout.addLayout(toolbar)
        root.addWidget(toolbar_panel)

        self.lyrics_scroll = QScrollArea(self)
        self.lyrics_scroll.setObjectName("chordLyricEditor")
        self.lyrics_scroll.setWidgetResizable(True)
        self.lyrics_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_content = QWidget(self.lyrics_scroll)
        self.scroll_content.setObjectName("chordLyricsContent")
        self.lyrics_layout = QVBoxLayout(self.scroll_content)
        self.lyrics_layout.setContentsMargins(8, 8, 8, 24)
        self.lyrics_layout.setSpacing(6)
        self.lyrics_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lyrics_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self.lyrics_scroll.setWidget(self.scroll_content)
        root.addWidget(self.lyrics_scroll, 1)

        footer = QHBoxLayout()
        initial_status = "" if embedded else "每拍可修改和弦与歌词，保存后写入歌曲包"
        self.status_label = QLabel(initial_status, self)
        self.status_label.setObjectName("statusBar")
        self.status_label.setVisible(bool(initial_status))
        cancel_button = QPushButton("取消", self)
        set_button_icon(cancel_button, "remove.svg")
        cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("保存和弦与歌词", self)
        set_button_icon(self.save_button, "save.svg")
        self.save_button.setProperty("role", "primary")
        self.save_button.clicked.connect(self._confirm)
        footer.addWidget(self.status_label, 1)
        if not embedded:
            footer.addWidget(cancel_button)
            footer.addWidget(self.save_button)
        else:
            cancel_button.hide()
            self.save_button.hide()
        root.addLayout(footer)
        self.lyric_search_edit.textChanged.connect(self._update_lyric_search)
        self.lyric_search_edit.returnPressed.connect(self._next_lyric_search_match)
        self.lyric_search_previous_button.clicked.connect(
            self._previous_lyric_search_match
        )
        self.lyric_search_next_button.clicked.connect(self._next_lyric_search_match)
        self._render_timeline()

    def _show_status(self, message: str) -> None:
        message = public_message(message, "和弦处理失败，请重试")
        if self.embedded:
            self.status_label.hide()
            self.status_changed.emit(
                "" if message.startswith(("已", "每拍", "正在")) else message
            )
            return
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message))

    def update_context(
        self,
        document: LyricsDocument,
        title: str,
        original_key: str,
        *,
        beat_times_ms: tuple[int, ...] | list[int] | None = None,
        downbeat_times_ms: tuple[int, ...] | list[int] | None = None,
        beats_per_bar: int | None = None,
    ) -> None:
        """Refresh the chord preview from the current lyric draft."""
        self.document = document
        self.title = title
        self.original_key = original_key
        if beat_times_ms is not None:
            self.beat_times_ms = tuple(beat_times_ms)
        if downbeat_times_ms is not None:
            self.downbeat_times_ms = tuple(downbeat_times_ms)
        if beat_times_ms is not None or downbeat_times_ms is not None:
            self.beats_per_bar = beats_per_bar
        self._update_key_options()
        self._render_timeline()

    def _update_key_options(self) -> None:
        valid = chord_key_is_valid(self.original_key)
        model = self.mode_combo.model()
        if isinstance(model, QStandardItemModel):
            for mode in ("degree", "chord_c"):
                item = model.item(self.mode_combo.findData(mode))
                if item is not None:
                    item.setEnabled(valid)
                    item.setToolTip("" if valid else "该模式需要先设置有效的原 Key")
        self.mode_combo.setToolTip("" if valid else "未设置有效原 Key，当前只能用原调和弦谱编辑")
        if not valid and self.current_mode() != "chord":
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("chord"))

    def current_mode(self) -> str:
        return str(self.mode_combo.currentData())

    def _update_lyric_search(
        self,
        _text: str = "",
        *,
        reveal: bool = True,
    ) -> None:
        previous_match = (
            self._lyric_search_matches[self._lyric_search_index]
            if 0 <= self._lyric_search_index < len(self._lyric_search_matches)
            else None
        )
        query = self.lyric_search_edit.text().strip().casefold()
        matches: list[tuple[str, int]] = []
        if query:
            for line in self.document.lines:
                if (
                    is_title_metadata_line(line, self.title)
                    or instrumental_marker_label(line) is not None
                ):
                    continue
                folded = line.text.casefold()
                index = folded.find(query)
                if index >= 0:
                    matches.append((line.id, index))
        self._lyric_search_matches = matches
        self._lyric_search_index = (
            matches.index(previous_match)
            if previous_match is not None and previous_match in matches
            else (0 if matches else -1)
        )
        self._update_lyric_search_controls()
        if reveal and self._lyric_search_index >= 0:
            self._reveal_lyric_search_match()
        elif not matches:
            self._set_lyric_search_highlight(None)

    def _update_lyric_search_controls(self) -> None:
        count = len(self._lyric_search_matches)
        enabled = count > 0
        self.lyric_search_previous_button.setEnabled(enabled)
        self.lyric_search_next_button.setEnabled(enabled)
        if not self.lyric_search_edit.text().strip():
            result = ""
        elif not enabled:
            result = "无匹配"
        else:
            result = f"{self._lyric_search_index + 1}/{count}"
        self.lyric_search_result_label.setText(result)

    def _set_lyric_search_highlight(self, widget: QWidget | None) -> None:
        previous = self._lyric_search_highlight
        self._lyric_search_highlight = widget
        if previous is not None and previous is not widget:
            try:
                previous.setProperty("searchMatch", False)
                previous.style().unpolish(previous)
                previous.style().polish(previous)
            except RuntimeError:
                pass
        if widget is not None:
            widget.setProperty("searchMatch", True)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _reveal_lyric_search_match(self) -> None:
        if self._lyric_search_index < 0:
            return
        line_id, character_index = self._lyric_search_matches[
            self._lyric_search_index
        ]
        query = self.lyric_search_edit.text().strip().casefold()
        target: QWidget | None = None
        for row, controls in zip(self._beat_rows, self.beat_rows, strict=True):
            visible_beat = next(
                (
                    beat_index
                    for beat_index, (sources, editor) in enumerate(
                        zip(row.lyric_sources, controls.lyric_editors, strict=False)
                    )
                    if query in editor.text().casefold()
                    and any(source_line_id == line_id for source_line_id, _index in sources)
                ),
                None,
            )
            if visible_beat is not None:
                target = controls.lyric_editors[visible_beat]
                break
        for row, controls in zip(self._beat_rows, self.beat_rows, strict=True):
            if target is not None:
                break
            exact_beat = next(
                (
                    beat_index
                    for beat_index, sources in enumerate(row.lyric_sources)
                    if (line_id, character_index) in sources
                ),
                None,
            )
            if exact_beat is None:
                exact_beat = next(
                    (
                        beat_index
                        for beat_index, sources in enumerate(row.lyric_sources)
                        if any(source_line_id == line_id for source_line_id, _index in sources)
                    ),
                    None,
                )
            if exact_beat is not None:
                target = controls.lyric_editors[exact_beat]
                break
        if target is None:
            target = next(
                (row for row in self.lyric_rows if row.line.id == line_id),
                None,
            )
        self._set_lyric_search_highlight(target)
        if target is not None:
            self._position_follow_enabled = False
            self.lyrics_scroll.ensureWidgetVisible(target, 20, 28)
        self._update_lyric_search_controls()

    def _next_lyric_search_match(self) -> None:
        if not self._lyric_search_matches:
            return
        self._lyric_search_index = (
            self._lyric_search_index + 1
        ) % len(self._lyric_search_matches)
        self._reveal_lyric_search_match()

    def _previous_lyric_search_match(self) -> None:
        if not self._lyric_search_matches:
            return
        self._lyric_search_index = (
            self._lyric_search_index - 1
        ) % len(self._lyric_search_matches)
        self._reveal_lyric_search_match()

    def has_pending_lyric_cut(self) -> bool:
        return self._pending_lyric_cut

    def commit_pending_lyric_inputs(self) -> bool:
        """Save the visible beat cells even if the user has not pasted cut text."""
        if not self._pending_lyric_cut:
            return True
        if not self._pending_lyric_line_ids:
            return True
        lines_by_id = {line.id: line for line in self.document.lines}
        placed: dict[str, list[WordTiming]] = {
            line_id: [] for line_id in self._pending_lyric_line_ids
        }
        try:
            for row, controls in zip(self._beat_rows, self.beat_rows, strict=True):
                for beat_index, editor in enumerate(controls.lyric_editors):
                    if beat_index >= len(row.beat_times_ms):
                        continue
                    chars = [char for char in editor.text() if not char.isspace()]
                    if not chars:
                        continue
                    sources = row.lyric_sources[beat_index]
                    owners = [line_id for line_id, _index in sources]
                    if not owners:
                        nearest = min(
                            self._pending_lyric_line_ids,
                            key=lambda line_id: abs(
                                row.beat_times_ms[beat_index]
                                - lines_by_id[line_id].start_ms
                            ),
                        )
                        owners = [nearest] * len(chars)
                    elif len(set(owners)) == 1:
                        owners = [owners[0]] * len(chars)
                    else:
                        source_owners = [
                            line_id for line_id, index in sources
                            if not lines_by_id[line_id].text[index].isspace()
                        ]
                        if not source_owners:
                            source_owners = [owners[0]]
                        owners = [
                            source_owners[min(index, len(source_owners) - 1)]
                            for index in range(len(chars))
                        ]
                    beat_ms = row.beat_times_ms[beat_index]
                    next_ms = (
                        row.beat_times_ms[beat_index + 1]
                        if beat_index + 1 < len(row.beat_times_ms)
                        else min(row.end_ms, self.duration_ms)
                    )
                    end_ms = self._manual_lyric_beat_end(beat_ms, next_ms)
                    if end_ms - beat_ms < len(chars):
                        raise ValueError("这一拍时间不足，无法保存当前歌词")
                    for index, (char, owner) in enumerate(zip(chars, owners, strict=True)):
                        if owner not in placed:
                            continue
                        placed[owner].append(
                            WordTiming(
                                text=char,
                                start_ms=beat_ms + (end_ms - beat_ms) * index // len(chars),
                                end_ms=beat_ms + (end_ms - beat_ms) * (index + 1) // len(chars),
                            )
                        )
            lines = [
                line for line in self.document.lines
                if line.id not in placed or placed[line.id]
            ]
            for index, line in enumerate(lines):
                if line.id not in placed:
                    continue
                words = placed[line.id]
                lines[index] = line.model_copy(
                    update={
                        "text": "".join(word.text for word in words),
                        "start_ms": words[0].start_ms,
                        "end_ms": words[-1].end_ms,
                        "words": words,
                    }
                )
            for line_id in placed:
                if placed[line_id]:
                    lines = self._resolve_moved_line_overlaps(lines, line_id)
            payload = self.document.model_dump(mode="python")
            payload["lines"] = [line.model_dump(mode="python") for line in lines]
            updated = LyricsDocument.model_validate(payload, strict=True)
        except ValueError as exc:
            self._show_status(str(exc))
            return False
        self.document = updated
        self._pending_lyric_cut = False
        self._pending_lyric_line_ids.clear()
        self.lyrics_changed.emit(updated)
        self._render_timeline()
        self._show_status("")
        return True

    def set_position_ms(self, position_ms: int, *, force_reveal: bool = False) -> None:
        """Highlight and reveal the four-bar editor cell containing playback."""
        self._last_position_ms = position_ms
        if not self.beat_rows or not self.downbeat_times_ms:
            return
        measure_index = max(0, bisect_right(self.downbeat_times_ms, position_ms) - 1)
        measure_index = min(
            measure_index, len(self.beat_rows) * self._BARS_PER_ROW - 1
        )
        if measure_index == self._active_measure_index and not force_reveal:
            return
        row_index, local_measure = divmod(measure_index, self._BARS_PER_ROW)
        if measure_index != self._active_measure_index:
            self._active_measure_index = measure_index
            for index, row in enumerate(self.beat_rows):
                row.set_current_measure(local_measure if index == row_index else None)
        if not force_reveal and not self._position_follow_enabled:
            return
        self.lyrics_scroll.ensureWidgetVisible(self.beat_rows[row_index], 0, 24)

    def suspend_position_follow(self) -> None:
        """Keep playback highlighting without scrolling away from the edited cell."""
        self._position_follow_enabled = False

    def resume_position_follow(self) -> None:
        """Resume revealing the playback measure after an explicit transport action."""
        self._position_follow_enabled = True
        if self._last_position_ms is not None:
            self.set_position_ms(self._last_position_ms, force_reveal=True)

    def _render_timeline(self) -> None:
        pending_lyrics = (
            tuple(tuple(editor.text() for editor in row.lyric_editors) for row in self.beat_rows)
            if self._pending_lyric_cut else ()
        )
        scroll_position = self.lyrics_scroll.verticalScrollBar().value()
        self._lyric_search_highlight = None
        while self.lyrics_layout.count():
            item = self.lyrics_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.chord_edits = {}
        self.cell_edits = []
        self.beat_rows = []
        self._active_measure_index = None
        self.lyric_rows = []
        self.instrumental_rows = []
        self._beat_rows = build_musician_bar_rows(
            self.document,
            self.beat_times_ms,
            self.downbeat_times_ms,
            self.beats_per_bar,
            self.timeline,
            bars_per_row=self._BARS_PER_ROW,
        )
        last_beat_end = 0
        if len(self.beat_times_ms) >= 2:
            last_beat_end = self.beat_times_ms[-1] + (
                self.beat_times_ms[-1] - self.beat_times_ms[-2]
            )
        last_content = max(
            (
                line.end_ms
                for line in self.document.lines
                if not is_title_metadata_line(line, self.title)
                and instrumental_marker_label(line) is None
            ),
            default=0,
        )
        if self._beat_rows and last_beat_end >= last_content - 1_000:
            self._render_beat_rows()
            for beat_row_widget, values in zip(
                self.beat_rows, pending_lyrics, strict=False
            ):
                for editor, value in zip(
                    beat_row_widget.lyric_editors, values, strict=False
                ):
                    editor.setText(value)
            self.scroll_content.adjustSize()
            QTimer.singleShot(
                0,
                self.lyrics_scroll,
                lambda: self.lyrics_scroll.verticalScrollBar().setValue(scroll_position),
            )
            self._update_lyric_search(reveal=False)
            return
        self._beat_rows = ()
        visible_segments: set[int] = set()
        mode = self.current_mode()
        previous_vocal_end = 0
        vocal_index = 0
        for line in self.document.lines:
            entries: list[tuple[int, ChordSegment, str]] = []
            if is_title_metadata_line(line, self.title):
                continue
            explicit_label = instrumental_marker_label(line)
            if explicit_label is not None:
                self._add_instrumental_rows(
                    explicit_label,
                    line.start_ms,
                    line.end_ms,
                    visible_segments,
                    mode,
                )
                previous_vocal_end = line.end_ms
                continue
            interval = sung_interval(line)
            start_ms, end_ms = interval if interval is not None else (line.start_ms, line.end_ms)
            gap_start = previous_vocal_end
            gap_end = start_ms
            gap_minimum = 1_200 if vocal_index == 0 else 3_500
            has_gap_chords = any(
                segment_index not in visible_segments
                and gap_start <= segment.start_ms < gap_end
                for segment_index, segment in enumerate(self.timeline.segments)
            )
            if gap_end > gap_start and (
                gap_end - gap_start >= gap_minimum or has_gap_chords
            ):
                gap_label = "前奏" if vocal_index == 0 else "间奏"
                self._add_instrumental_rows(gap_label, gap_start, gap_end, visible_segments, mode)
            for segment_index, segment in enumerate(self.timeline.segments):
                if segment_index in visible_segments:
                    continue
                if segment.start_ms >= end_ms or segment.end_ms <= start_ms:
                    continue
                label = self._segment_label(segment, mode)
                entries.append((segment_index, segment, label))
                visible_segments.add(segment_index)
            cells, overflow = self._assign_entries_to_characters(line, entries)
            for segment_index in overflow:
                visible_segments.discard(segment_index)
            row = ChordLyricRow(line, cells, self._edit_cell, self.scroll_content)
            self.lyrics_layout.addWidget(row)
            self.lyric_rows.append(row)
            for _character_index, cell_segment_index, editor in row.editors:
                self.cell_edits.append(editor)
                if cell_segment_index is not None:
                    self.chord_edits.setdefault(cell_segment_index, editor)
            previous_vocal_end = end_ms
            vocal_index += 1
        has_tail_chords = any(
            segment_index not in visible_segments
            and previous_vocal_end <= segment.start_ms < self.duration_ms
            for segment_index, segment in enumerate(self.timeline.segments)
        )
        if vocal_index and self.duration_ms > previous_vocal_end and (
            self.duration_ms - previous_vocal_end >= 3_500 or has_tail_chords
        ):
            self._add_instrumental_rows(
                "尾奏", previous_vocal_end, self.duration_ms, visible_segments, mode
            )
        hidden_count = len(self.timeline.segments) - len(visible_segments)
        if hidden_count:
            self._show_status(
                f"有 {hidden_count} 个和弦未显示（未匹配歌词或间奏时间），将保留原数据"
            )
        self.scroll_content.adjustSize()
        QTimer.singleShot(
            0,
            self.lyrics_scroll,
            lambda: self.lyrics_scroll.verticalScrollBar().setValue(scroll_position),
        )
        self._update_lyric_search(reveal=False)

    def _render_beat_rows(self) -> None:
        """Show four compact measures per editor row."""
        assert self.beats_per_bar is not None
        first_beat = bisect_left(self.beat_times_ms, self.downbeat_times_ms[0])
        beats = self.beat_times_ms[first_beat:]
        segment_indices: list[list[int]] = [[] for _ in beats]
        for segment_index, segment in enumerate(self.timeline.segments):
            following = bisect_left(beats, segment.start_ms)
            if following == 0:
                beat_index = 0
            elif following == len(beats):
                beat_index = len(beats) - 1
            else:
                beat_index = min(
                    (following - 1, following),
                    key=lambda candidate: abs(beats[candidate] - segment.start_ms),
                )
            segment_indices[beat_index].append(segment_index)

        beats_per_row = self.beats_per_bar * self._BARS_PER_ROW
        for row_index, row in enumerate(self._beat_rows):
            entries: list[tuple[tuple[int, ...], str]] = []
            for beat_index in range(beats_per_row):
                global_index = row_index * beats_per_row + beat_index
                if global_index >= len(beats):
                    entries.append(((), ""))
                    continue
                indices = tuple(segment_indices[global_index])
                carried_label = ""
                if not indices and beat_index % self.beats_per_bar == 0:
                    active = next(
                        (
                            index
                            for index, segment in enumerate(self.timeline.segments)
                            if segment.start_ms <= beats[global_index] < segment.end_ms
                        ),
                        None,
                    )
                    if active is not None:
                        carried_label = self._segment_label(
                            self.timeline.segments[active], self.current_mode()
                        )
                label = carried_label or "→".join(
                    self._segment_label(self.timeline.segments[index], self.current_mode())
                    for index in indices
                )
                entries.append((indices, label))
            beat_row = BeatChordLyricRow(
                row_index,
                row,
                self.beats_per_bar,
                self._BARS_PER_ROW,
                entries,
                self._edit_beat_chord,
                self._edit_beat_lyric,
                self.scroll_content,
            )
            self.lyrics_layout.addWidget(beat_row)
            self.beat_rows.append(beat_row)
            for (indices, _label), editor in zip(entries, beat_row.chord_editors, strict=True):
                editor.textEdited.connect(self.suspend_position_follow)
                self.cell_edits.append(editor)
                for index in indices:
                    self.chord_edits.setdefault(index, editor)
            for editor in beat_row.lyric_editors:
                editor.textEdited.connect(self.suspend_position_follow)

    def _edit_beat_chord(
        self, beat_ms: int, indices: tuple[int, ...], editor: QLineEdit
    ) -> None:
        if editor.text().strip() == editor.property("beatOriginalLabel"):
            return
        if len(indices) <= 1:
            self._edit_instrumental_segment(
                indices[0] if indices else None, beat_ms, self.duration_ms, editor
            )
            return
        labels = [label.strip() for label in editor.text().split("→")]
        if len(labels) != len(indices) or any(not label for label in labels):
            self._show_status("同一拍有多个和弦，请用 → 分隔并保留原有数量")
            self._render_timeline()
            return
        try:
            segments = list(self.timeline.segments)
            for index, label in zip(indices, labels, strict=True):
                segment = segments[index]
                segments[index] = ChordSegment(
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    chord=chord_from_mode(label, self.original_key, self.current_mode()),
                )
            self.timeline = ChordTimeline(segments=segments)
            self._render_timeline()
            self._show_status(f"已修改 {beat_ms / 1000:.3f} 秒处的和弦，保存后写入歌曲包")
        except ValueError as exc:
            self._show_status(str(exc))
            self._render_timeline()

    @staticmethod
    def _timed_characters_for_edit(line: LyricLine) -> list[WordTiming]:
        """Expand saved word timings to characters without moving unaffected syllables."""
        characters = [character for character in line.text if not character.isspace()]
        timed: list[WordTiming] = []
        for word in line.words:
            word_chars = [character for character in word.text if not character.isspace()]
            duration = word.end_ms - word.start_ms
            if duration < len(word_chars):
                break
            for index, character in enumerate(word_chars):
                timed.append(
                    WordTiming(
                        text=character,
                        start_ms=word.start_ms + duration * index // len(word_chars),
                        end_ms=word.start_ms + duration * (index + 1) // len(word_chars),
                    )
                )
        if len(timed) == len(characters):
            return timed
        duration = line.end_ms - line.start_ms
        if duration < len(characters):
            raise ValueError("该句时间不足，无法按拍修改歌词")
        return [
            WordTiming(
                text=character,
                start_ms=line.start_ms + duration * index // len(characters),
                end_ms=line.start_ms + duration * (index + 1) // len(characters),
            )
            for index, character in enumerate(characters)
        ]

    @staticmethod
    def _replace_line_beat_text(
        line: LyricLine,
        start: int,
        end: int,
        replacement: str,
        beat_ms: int,
        beat_end_ms: int,
    ) -> LyricLine:
        text = line.text[:start] + replacement + line.text[end:]
        if not text.strip():
            raise ValueError("不能清空整句歌词；请在歌词页删除该句")
        if not line.words:
            return line.model_copy(update={"text": text})

        original = ChordEditDialog._timed_characters_for_edit(line)
        old_indices = [index for index, char in enumerate(line.text) if not char.isspace()]
        before = [word for index, word in zip(old_indices, original, strict=True) if index < start]
        selected = [
            word for index, word in zip(old_indices, original, strict=True) if start <= index < end
        ]
        after = [word for index, word in zip(old_indices, original, strict=True) if index >= end]
        new_chars = [character for character in replacement if not character.isspace()]
        if len(new_chars) == len(selected):
            inserted = [
                WordTiming(text=char, start_ms=word.start_ms, end_ms=word.end_ms)
                for char, word in zip(new_chars, selected, strict=True)
            ]
        else:
            start_ms = selected[0].start_ms if selected else max(line.start_ms, beat_ms)
            end_ms = selected[-1].end_ms if selected else min(line.end_ms, beat_end_ms)
            if before:
                start_ms = max(start_ms, before[-1].end_ms)
            if after:
                end_ms = min(end_ms, after[0].start_ms)
            if end_ms - start_ms < len(new_chars):
                raise ValueError("该拍剩余时间不足，无法写入这些歌词")
            inserted = [
                WordTiming(
                    text=character,
                    start_ms=start_ms + (end_ms - start_ms) * index // len(new_chars),
                    end_ms=start_ms + (end_ms - start_ms) * (index + 1) // len(new_chars),
                )
                for index, character in enumerate(new_chars)
            ]
        return LyricLine(
            id=line.id,
            start_ms=line.start_ms,
            end_ms=line.end_ms,
            text=text,
            words=before + inserted + after,
        )

    def _existing_move_source(
        self, row_index: int, beat_index: int, replacement: str
    ) -> tuple[str, list[int]] | None:
        """Find an existing nearby lyric phrase typed into an empty beat.

        A phrase can currently be grouped into one beat even when the user wants to
        spread it over several beats.  Looking only for an exact adjacent cell makes
        that edit impossible (and also fails when a chord anchor visually splits the
        phrase).  Match the saved lyric characters instead, then prefer the closest
        occurrence within the surrounding four-bar row.
        """
        if self.beats_per_bar is None:
            return None
        beats_per_row = self.beats_per_bar * self._BARS_PER_ROW
        target = row_index * beats_per_row + beat_index
        replacement_chars = [character for character in replacement if not character.isspace()]
        if not replacement_chars:
            return None

        source_beats: dict[tuple[str, int], int] = {}
        for source_row_index, row in enumerate(self._beat_rows):
            for source_beat_index, sources in enumerate(row.lyric_sources):
                source = source_row_index * beats_per_row + source_beat_index
                for line_id, character_index in sources:
                    source_beats[(line_id, character_index)] = source

        candidates: list[tuple[tuple[int, int], str, list[int]]] = []
        for line in self.document.lines:
            if (
                instrumental_marker_label(line) is not None
                or is_title_metadata_line(line, self.title)
            ):
                continue
            indexed_chars = [
                (index, character)
                for index, character in enumerate(line.text)
                if not character.isspace()
            ]
            size = len(replacement_chars)
            for offset in range(len(indexed_chars) - size + 1):
                chunk = indexed_chars[offset : offset + size]
                if [character for _index, character in chunk] != replacement_chars:
                    continue
                indices = [index for index, _character in chunk]
                occupied = [
                    source_beats[(line.id, index)]
                    for index in indices
                    if (line.id, index) in source_beats
                ]
                if len(occupied) != len(indices) or all(source == target for source in occupied):
                    continue
                distance = min(abs(source - target) for source in occupied)
                if distance > beats_per_row:
                    continue
                same_row = any(source // beats_per_row == row_index for source in occupied)
                candidates.append(((0 if same_row else 1, distance), line.id, indices))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        best_rank = candidates[0][0]
        best = [candidate for candidate in candidates if candidate[0] == best_rank]
        return (best[0][1], best[0][2]) if len(best) == 1 else None

    @staticmethod
    def _move_line_characters_to_beat(
        line: LyricLine,
        indices: list[int],
        beat_ms: int,
        beat_end_ms: int,
    ) -> LyricLine:
        """Move existing character timings while keeping the lyric text unchanged."""
        if not line.words:
            raise ValueError("该句没有逐字时间，请先重新分析歌词时间")
        original = ChordEditDialog._timed_characters_for_edit(line)
        text_indices = [index for index, char in enumerate(line.text) if not char.isspace()]
        timing_by_index = dict(zip(text_indices, original, strict=True))
        if any(index not in timing_by_index for index in indices):
            raise ValueError("找不到要移动的歌词时间")
        first, last = indices[0], indices[-1]
        previous = next(
            (timing_by_index[index] for index in reversed(text_indices) if index < first),
            None,
        )
        following = next(
            (timing_by_index[index] for index in text_indices if index > last),
            None,
        )
        start_ms = beat_ms
        end_ms = beat_end_ms
        if previous is not None:
            start_ms = max(start_ms, previous.end_ms)
        if following is not None:
            end_ms = min(end_ms, following.start_ms)
        if end_ms - start_ms < len(indices):
            raise ValueError("目标拍没有足够时间容纳这些歌词")
        for order, index in enumerate(indices):
            timing_by_index[index] = WordTiming(
                text=line.text[index],
                start_ms=start_ms + (end_ms - start_ms) * order // len(indices),
                end_ms=start_ms + (end_ms - start_ms) * (order + 1) // len(indices),
            )
        return line.model_copy(
            update={
                "start_ms": min(line.start_ms, start_ms),
                "end_ms": max(line.end_ms, end_ms),
                "words": [timing_by_index[index] for index in text_indices],
            }
        )

    def _manual_lyric_beat_end(self, beat_ms: int, beat_end_ms: int) -> int:
        """Keep a manual lyric phrase before a chord assigned to the next beat."""
        midpoint = beat_ms + (beat_end_ms - beat_ms) // 2
        return min(
            (
                segment.start_ms
                for segment in self.timeline.segments
                if midpoint <= segment.start_ms < beat_end_ms
            ),
            default=beat_end_ms,
        )

    def _resolve_moved_line_overlaps(
        self, lines: list[LyricLine], moved_line_id: str
    ) -> list[LyricLine]:
        """Let a moved lyric consume overlapping intro/interlude marker time."""
        moved = next(line for line in lines if line.id == moved_line_id)
        resolved: list[LyricLine] = []
        for line in lines:
            if (
                line.id == moved_line_id
                or line.end_ms <= moved.start_ms
                or line.start_ms >= moved.end_ms
            ):
                resolved.append(line)
                continue
            if instrumental_marker_label(line) is None:
                raise ValueError("目标拍与另一句歌词重叠，请先调整相邻歌词")
            if line.start_ms < moved.start_ms:
                resolved.append(line.model_copy(update={"end_ms": moved.start_ms}))
            elif line.end_ms > moved.end_ms:
                resolved.append(line.model_copy(update={"start_ms": moved.end_ms}))
        return sorted(resolved, key=lambda line: line.start_ms)

    def _rebuild_lyrics_from_beat_inputs(self) -> LyricsDocument | None:
        """Use the edited beat cells as the authority for existing lyric timing.

        A cut followed by a paste temporarily removes characters from the visible
        grid.  Once the complete lyric sequence is present again, assign each
        character a fresh time inside its chosen beat, using the chord change as
        the boundary when it belongs to the following beat.
        """
        source_beats = {
            (line_id, character_index): row_index * len(row.lyric_cells) + beat_index
            for row_index, row in enumerate(self._beat_rows)
            for beat_index, sources in enumerate(row.lyric_sources)
            for line_id, character_index in sources
        }
        placed: list[tuple[str, int, WordTiming]] = []
        for row_index, (row, controls) in enumerate(
            zip(self._beat_rows, self.beat_rows, strict=True)
        ):
            for beat_index, editor in enumerate(controls.lyric_editors):
                if beat_index >= len(row.beat_times_ms):
                    continue
                chars = [char for char in editor.text() if not char.isspace()]
                if not chars:
                    continue
                beat_ms = row.beat_times_ms[beat_index]
                next_ms = (
                    row.beat_times_ms[beat_index + 1]
                    if beat_index + 1 < len(row.beat_times_ms)
                    else min(row.end_ms, self.duration_ms)
                )
                end_ms = self._manual_lyric_beat_end(beat_ms, next_ms)
                if end_ms - beat_ms < len(chars):
                    raise ValueError("这一拍时间不足，无法放下输入的歌词")
                for offset, char in enumerate(chars):
                    placed.append(
                        (
                            char,
                            row_index * len(row.lyric_cells) + beat_index,
                            WordTiming(
                                text=char,
                                start_ms=beat_ms + (end_ms - beat_ms) * offset // len(chars),
                                end_ms=beat_ms + (end_ms - beat_ms) * (offset + 1) // len(chars),
                            ),
                        )
                    )

        vocal_lines = [
            line
            for line in self.document.lines
            if instrumental_marker_label(line) is None
            and not is_title_metadata_line(line, self.title)
        ]
        original = "".join(
            char for line in vocal_lines for char in line.text if not char.isspace()
        )
        if "".join(char for char, _beat, _word in placed) != original:
            return None

        lines = list(self.document.lines)
        cursor = 0
        changed_ids: list[str] = []
        for line in vocal_lines:
            indices = [index for index, char in enumerate(line.text) if not char.isspace()]
            assigned = placed[cursor : cursor + len(indices)]
            cursor += len(indices)
            if all(
                source_beats.get((line.id, index)) == beat
                for index, (_char, beat, _word) in zip(indices, assigned, strict=True)
            ):
                continue
            words = [word for _char, _beat, word in assigned]
            updated = line.model_copy(
                update={
                    "start_ms": words[0].start_ms,
                    "end_ms": words[-1].end_ms,
                    "words": words,
                }
            )
            index = next(index for index, current in enumerate(lines) if current.id == line.id)
            lines[index] = updated
            changed_ids.append(line.id)
        if not changed_ids:
            return None
        for line_id in changed_ids:
            lines = self._resolve_moved_line_overlaps(lines, line_id)
        payload = self.document.model_dump(mode="python")
        payload["lines"] = [line.model_dump(mode="python") for line in lines]
        return LyricsDocument.model_validate(payload, strict=True)

    def _edit_beat_lyric(self, row_index: int, beat_index: int, editor: QLineEdit) -> None:
        row = self._beat_rows[row_index]
        replacement = editor.text().strip()
        if replacement == row.lyric_cells[beat_index]:
            if self._pending_lyric_cut and all(
                control.text().strip() == saved
                for saved_row, controls in zip(self._beat_rows, self.beat_rows, strict=True)
                for saved, control in zip(
                    saved_row.lyric_cells, controls.lyric_editors, strict=False
                )
            ):
                self._pending_lyric_cut = False
                self._pending_lyric_line_ids.clear()
                self._show_status("")
            return
        lines_by_id = {line.id: line for line in self.document.lines}
        source_text_chars = "".join(
            lines_by_id[line_id].text[character_index]
            for line_id, character_index in row.lyric_sources[beat_index]
            if not lines_by_id[line_id].text[character_index].isspace()
        )
        replacement_text_chars = "".join(
            char for char in replacement if not char.isspace()
        )
        if (
            source_text_chars
            and len(replacement_text_chars) < len(source_text_chars)
            and replacement_text_chars in source_text_chars
        ):
            self._pending_lyric_cut = True
            self._pending_lyric_line_ids.update(
                line_id for line_id, _index in row.lyric_sources[beat_index]
            )
            self._show_status("已暂存剪切；请粘贴到目标拍，随后按新拍位重建歌词时间")
            return
        try:
            rebuilt = self._rebuild_lyrics_from_beat_inputs()
        except ValueError as exc:
            self._show_status(str(exc))
            return
        if rebuilt is not None:
            self.document = rebuilt
            self._pending_lyric_cut = False
            self._pending_lyric_line_ids.clear()
            self.lyrics_changed.emit(self.document)
            self._render_timeline()
            beat_number = beat_index % (self.beats_per_bar or len(row.beat_times_ms)) + 1
            self._show_status(f"已按第 {beat_number} 拍重建歌词时间，保存后写入歌曲包")
            return
        if self._pending_lyric_cut:
            self._show_status("已暂存剪切；请完成粘贴，确保整句歌词没有缺字或重复")
            return
        beat_ms = row.beat_times_ms[beat_index]
        following = (
            row.beat_times_ms[beat_index + 1]
            if beat_index + 1 < len(row.beat_times_ms)
            else min(row.end_ms, self.duration_ms)
        )
        sources = row.lyric_sources[beat_index]
        lines = list(self.document.lines)
        try:
            if sources:
                line_ids = {line_id for line_id, _index in sources}
                indices = [index for _line_id, index in sources]
                if len(line_ids) != 1 or indices != list(range(indices[0], indices[-1] + 1)):
                    raise ValueError("这一拍跨越两句歌词，请在歌词页修改")
                line_index = next(
                    index for index, line in enumerate(lines) if line.id == sources[0][0]
                )
                line = lines[line_index]
                timed_indices = [
                    index for index in indices if not line.text[index].isspace()
                ]
                current_chars = [line.text[index] for index in timed_indices]
                replacement_chars = [
                    character for character in replacement if not character.isspace()
                ]
                # Shortening a populated cell to its prefix means "put the suffix
                # on the next beat", not "delete the suffix from the song".  This
                # is the natural workflow when splitting one recognized phrase over
                # several chord beats.
                if (
                    replacement_chars
                    and len(replacement_chars) < len(current_chars)
                    and current_chars[: len(replacement_chars)] == replacement_chars
                    and beat_index + 1 < len(row.beat_times_ms)
                ):
                    split = len(replacement_chars)
                    current_end = self._manual_lyric_beat_end(beat_ms, following)
                    line = self._move_line_characters_to_beat(
                        line, timed_indices[:split], beat_ms, current_end
                    )
                    next_end = (
                        row.beat_times_ms[beat_index + 2]
                        if beat_index + 2 < len(row.beat_times_ms)
                        else min(row.end_ms, self.duration_ms)
                    )
                    next_end = self._manual_lyric_beat_end(following, next_end)
                    lines[line_index] = self._move_line_characters_to_beat(
                        line, timed_indices[split:], following, next_end
                    )
                else:
                    lines[line_index] = self._replace_line_beat_text(
                        line,
                        indices[0],
                        indices[-1] + 1,
                        replacement,
                        beat_ms,
                        following,
                    )
            elif replacement:
                move_source = self._existing_move_source(row_index, beat_index, replacement)
                if move_source is not None:
                    line_id, indices = move_source
                    move_line_index = next(
                        index for index, line in enumerate(lines) if line.id == line_id
                    )
                    move_end = self._manual_lyric_beat_end(beat_ms, following)
                    lines[move_line_index] = self._move_line_characters_to_beat(
                        lines[move_line_index], indices, beat_ms, move_end
                    )
                    lines = self._resolve_moved_line_overlaps(lines, line_id)
                else:
                    containing_line_index = next(
                        (
                            index
                            for index, line in enumerate(lines)
                            if line.start_ms <= beat_ms < line.end_ms
                            and instrumental_marker_label(line) is None
                            and not is_title_metadata_line(line, self.title)
                        ),
                        None,
                    )
                    if containing_line_index is None:
                        if any(line.start_ms <= beat_ms < line.end_ms for line in lines):
                            raise ValueError(
                                "该拍属于标题或段落标记，请先在歌词页调整该行"
                            )
                        next_line_start = min(
                            (line.start_ms for line in lines if line.start_ms > beat_ms),
                            default=self.duration_ms,
                        )
                        end_ms = min(following, next_line_start, self.duration_ms)
                        characters = [char for char in replacement if not char.isspace()]
                        if end_ms - beat_ms < len(characters):
                            raise ValueError("该拍剩余时间不足，无法新增歌词")
                        words = (
                            [
                                WordTiming(
                                    text=char,
                                    start_ms=beat_ms
                                    + (end_ms - beat_ms) * index // len(characters),
                                    end_ms=(
                                        beat_ms
                                        + (end_ms - beat_ms) * (index + 1) // len(characters)
                                    ),
                                )
                                for index, char in enumerate(characters)
                            ]
                            if self.document.timing_mode == "word"
                            else []
                        )
                        next_id = max(int(line.id[5:]) for line in lines) + 1
                        lines.append(
                            LyricLine(
                                id=f"line-{next_id:04d}",
                                start_ms=beat_ms,
                                end_ms=end_ms,
                                text=replacement,
                                words=words,
                            )
                        )
                        lines.sort(key=lambda line: line.start_ms)
                    else:
                        line = lines[containing_line_index]
                        insertion = bisect_left(
                            [
                                character_timestamp(line, index)
                                for index in range(len(line.text))
                            ],
                            beat_ms,
                        )
                        lines[containing_line_index] = self._replace_line_beat_text(
                            line, insertion, insertion, replacement, beat_ms, following
                        )
            else:
                return
            payload = self.document.model_dump(mode="python")
            payload["lines"] = [line.model_dump(mode="python") for line in lines]
            self.document = LyricsDocument.model_validate(payload, strict=True)
            self.lyrics_changed.emit(self.document)
            self._render_timeline()
            beat_number = beat_index % (self.beats_per_bar or len(row.beat_times_ms)) + 1
            self._show_status(
                f"已按拍修改歌词（第 {beat_number} 拍），保存后写入歌曲包"
            )
        except (StopIteration, ValueError) as exc:
            self._show_status(str(exc) or "找不到对应的歌词句")
            self._render_timeline()

    def _add_instrumental_rows(
        self,
        label: str,
        start_ms: int,
        end_ms: int,
        visible_segments: set[int],
        mode: str,
    ) -> None:
        entries = [
            (segment_index, segment, self._segment_label(segment, mode))
            for segment_index, segment in enumerate(self.timeline.segments)
            if segment_index not in visible_segments and start_ms <= segment.start_ms < end_ms
        ]
        row_capacity = 8
        recognized_capacity = 4
        recognized = [
            entry for entry in entries if entry[1].start_ms not in self._manual_instrumental_starts
        ]
        manual = [
            entry for entry in entries if entry[1].start_ms in self._manual_instrumental_starts
        ]
        offsets = list(range(0, len(recognized), recognized_capacity)) or [0]
        for row_number, offset in enumerate(offsets):
            row_label = label if row_number == 0 else f"{label}·续"
            chunk = recognized[offset : offset + recognized_capacity]
            row_start_ms = start_ms if row_number == 0 else chunk[0][1].start_ms
            next_offset = offset + recognized_capacity
            row_end_ms = (
                recognized[next_offset][1].start_ms if next_offset < len(recognized) else end_ms
            )
            row_manual = [
                entry for entry in manual if row_start_ms <= entry[1].start_ms < row_end_ms
            ]
            actual_entries = chunk + row_manual[: row_capacity - len(chunk)]
            row_entries: list[tuple[int | None, str, int, int]] = [
                (segment_index, chord_label, segment.start_ms, end_ms)
                for segment_index, segment, chord_label in actual_entries
            ]
            empty_count = row_capacity - len(row_entries)
            if empty_count:
                if actual_entries:
                    anchor_ms = actual_entries[-1][1].start_ms
                    empty_times = [
                        anchor_ms + (row_end_ms - anchor_ms) * (index + 1) // (empty_count + 1)
                        for index in range(empty_count)
                    ]
                else:
                    empty_times = [
                        row_start_ms + (row_end_ms - row_start_ms) * index // row_capacity
                        for index in range(row_capacity)
                    ]
                row_entries.extend((None, "", timestamp_ms, end_ms) for timestamp_ms in empty_times)
            row = InstrumentalChordRow(
                row_label,
                row_entries,
                self._edit_instrumental_segment,
                self.scroll_content,
            )
            self.lyrics_layout.addWidget(row)
            self.instrumental_rows.append(row)
            for segment_index, editor in row.editors:
                if segment_index is not None:
                    visible_segments.add(segment_index)
                    self.chord_edits[segment_index] = editor
                self.cell_edits.append(editor)

    def _segment_label(self, segment: ChordSegment, mode: str) -> str:
        return (
            "N" if segment.chord == "N" else chord_for_mode(segment.chord, self.original_key, mode)
        )

    def _edit_instrumental_segment(
        self,
        segment_index: int | None,
        start_ms: int,
        section_end_ms: int,
        editor: QLineEdit,
    ) -> None:
        if segment_index is not None and not 0 <= segment_index < len(self.timeline.segments):
            return
        label = editor.text().strip()
        try:
            segments = list(self.timeline.segments)
            if segment_index is None:
                if not label:
                    return
                chord = chord_from_mode(label, self.original_key, self.current_mode())
                insertion = next(
                    (
                        index
                        for index, segment in enumerate(segments)
                        if segment.start_ms >= start_ms
                    ),
                    len(segments),
                )
                if insertion < len(segments) and segments[insertion].start_ms == start_ms:
                    raise ValueError("该时间已有和弦")
                end_ms = section_end_ms
                if insertion < len(segments):
                    end_ms = min(end_ms, segments[insertion].start_ms)
                if insertion > 0 and segments[insertion - 1].end_ms > start_ms:
                    previous = segments[insertion - 1]
                    if previous.start_ms >= start_ms:
                        raise ValueError("该时间已有和弦")
                    segments[insertion - 1] = ChordSegment(
                        start_ms=previous.start_ms,
                        end_ms=start_ms,
                        chord=previous.chord,
                    )
                if end_ms <= start_ms:
                    raise ValueError("该时间无法新增和弦")
                segments.insert(
                    insertion,
                    ChordSegment(start_ms=start_ms, end_ms=end_ms, chord=chord),
                )
                self._manual_instrumental_starts.add(start_ms)
                action = "新增"
            else:
                segment = segments[segment_index]
                start_ms = segment.start_ms
                if label:
                    segments[segment_index] = ChordSegment(
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        chord=chord_from_mode(label, self.original_key, self.current_mode()),
                    )
                    action = "修改"
                else:
                    segments.pop(segment_index)
                    self._manual_instrumental_starts.discard(start_ms)
                    action = "删除"
            self.timeline = ChordTimeline(segments=segments)
            self._render_timeline()
            self._show_status(f"已在 {start_ms / 1000:.3f} 秒处{action}和弦，保存后写入歌曲包")
        except ValueError as exc:
            self._show_status(str(exc))
            self._render_timeline()

    @staticmethod
    def _assign_entries_to_characters(
        line: LyricLine,
        entries: list[tuple[int, ChordSegment, str]],
    ) -> tuple[
        list[tuple[int, str, int | None, ChordSegment | None, str]],
        tuple[int, ...],
    ]:
        if not line.text:
            return [], tuple(index for index, _segment, _label in entries)
        character_count = len(line.text)
        slot_count = max(character_count, len(entries))
        slots: list[tuple[int, str]]
        positions: tuple[int | None, ...]
        if slot_count == character_count:
            slots = [(index, character) for index, character in enumerate(line.text)]
            timestamps = [max(segment.start_ms, line.start_ms) for _, segment, _ in entries]
            positions = unique_character_indices(line, timestamps)
        else:
            lyric_positions: tuple[int, ...]
            if character_count == 1:
                lyric_positions = (0,)
            else:
                lyric_positions = tuple(
                    round(index * (slot_count - 1) / (character_count - 1))
                    for index in range(character_count)
                )
            characters_by_position = {
                position: (index, line.text[index])
                for index, position in enumerate(lyric_positions)
            }
            slots = []
            for position in range(slot_count):
                source = characters_by_position.get(position)
                if source is not None:
                    slots.append(source)
                    continue
                nearest = min(
                    range(character_count),
                    key=lambda index: abs(lyric_positions[index] - position),
                )
                slots.append((nearest, ""))
            positions = tuple(range(len(entries)))
        cells: list[tuple[int, str, int | None, ChordSegment | None, str]] = [
            (character_index, character, None, None, "")
            for character_index, character in slots
        ]
        overflow: list[int] = []
        for (segment_index, segment, label), assigned_position in zip(
            entries, positions, strict=True
        ):
            if assigned_position is None:
                overflow.append(segment_index)
                continue
            character_index, character = slots[assigned_position]
            cells[assigned_position] = (
                character_index,
                character,
                segment_index,
                segment,
                label,
            )
        return cells, tuple(overflow)

    @staticmethod
    def _character_timestamp(line: LyricLine, character_index: int) -> int:
        return character_timestamp(line, character_index)

    def _edit_cell(
        self,
        line: LyricLine,
        character_index: int,
        segment_index: int | None,
        editor: QLineEdit,
    ) -> None:
        label = editor.text().strip()
        if segment_index is not None and not 0 <= segment_index < len(self.timeline.segments):
            return
        try:
            segments = list(self.timeline.segments)
            if segment_index is not None:
                segment = segments[segment_index]
                if not label:
                    segments.pop(segment_index)
                    action = "删除"
                else:
                    segments[segment_index] = ChordSegment(
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        chord=chord_from_mode(label, self.original_key, self.current_mode()),
                    )
                    action = "修改"
            else:
                if not label:
                    return
                chord = chord_from_mode(label, self.original_key, self.current_mode())
                start_ms = self._character_timestamp(line, character_index)
                insertion = next(
                    (
                        index
                        for index, segment in enumerate(segments)
                        if segment.start_ms > start_ms
                    ),
                    len(segments),
                )
                end_ms = line.end_ms
                if insertion < len(segments):
                    end_ms = min(end_ms, segments[insertion].start_ms)
                if insertion > 0 and segments[insertion - 1].end_ms > start_ms:
                    previous = segments[insertion - 1]
                    if previous.start_ms >= start_ms:
                        raise ValueError("该字符位置已有和弦")
                    segments[insertion - 1] = ChordSegment(
                        start_ms=previous.start_ms,
                        end_ms=start_ms,
                        chord=previous.chord,
                    )
                if end_ms <= start_ms:
                    raise ValueError("该字符位置无法新增和弦")
                segments.insert(
                    insertion,
                    ChordSegment(start_ms=start_ms, end_ms=end_ms, chord=chord),
                )
                action = "新增"
            self.timeline = ChordTimeline(segments=segments)
            self._render_timeline()
            self._show_status(
                f"已在“{line.text[character_index]}”上方{action}和弦，保存后写入歌曲包"
            )
        except ValueError as exc:
            self._show_status(str(exc))
            self._render_timeline()

    def _request_reanalysis(self) -> None:
        self.set_analysis_running(True)
        self._show_status("正在重新识别和弦……")
        self.reanalysis_requested.emit()

    def set_analysis_running(self, running: bool) -> None:
        self.reanalyze_button.setEnabled(not running)
        self.reanalyze_button.setText("识别中…" if running else "重新识别和弦")
        self.progress.setVisible(running and self.show_analysis_controls)
        self.save_button.setEnabled(not running)
        self.mode_combo.setEnabled(not running)
        self.lyrics_scroll.setEnabled(not running)
        self.analysis_running_changed.emit(running)

    def apply_reanalysis(self, timeline: ChordTimeline) -> None:
        self.timeline = timeline
        self._manual_instrumental_starts.clear()
        self.set_analysis_running(False)
        self._render_timeline()
        self._show_status(f"重新识别完成，共 {len(timeline.segments)} 个和弦（尚未保存）")

    def show_reanalysis_error(self, message: str) -> None:
        self.set_analysis_running(False)
        self._show_status(message)

    def _confirm(self) -> None:
        focused = self.focusWidget()
        if isinstance(focused, QLineEdit) and focused.objectName() in {
            "chordInlineEditor", "lyricBeatEditor"
        }:
            focused.clearFocus()
        if not self.commit_pending_lyric_inputs():
            return
        if not self.timeline.segments:
            answer = QMessageBox.question(
                self,
                "保存空和弦表",
                "当前和弦表为空，确定保存吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if any(segment.end_ms > self.duration_ms for segment in self.timeline.segments):
            QMessageBox.warning(self, "和弦校验失败", "存在超出歌曲时长的和弦")
            return
        self.chords_confirmed.emit(self.timeline)
        self.lyrics_confirmed.emit(self.document)
        if not self.embedded:
            self.accept()
